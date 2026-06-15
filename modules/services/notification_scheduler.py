"""시간 기반 알림 스케줄러 — 평일 09:00 실행

납품기한 D-7/D-1/초과, 입고 지연, 안전재고, 서류 마감, 하자보증, 인증서 만료 등
시간 경과로 발생하는 알림을 일괄 점검하여 **일일 다이제스트 1건**으로 통합 발송합니다.
주말(crontab)·공휴일(코드) 제외.
"""
import datetime
import logging
from typing import Dict, List

from modules.notification_engine import notify

logger = logging.getLogger(__name__)

# ── 한국 공휴일 (음력 포함, 매년 초 갱신 필요) ──
# 대체공휴일도 포함. 음력(설/추석/부처님오신날)은 매년 날짜가 다름.
KOREAN_HOLIDAYS_2026 = {
    # 고정 공휴일
    '01-01',  # 신정
    '03-01',  # 삼일절
    '05-05',  # 어린이날
    '06-06',  # 현충일
    '08-15',  # 광복절
    '10-03',  # 개천절
    '10-09',  # 한글날
    '12-25',  # 크리스마스
    # 2026 음력 공휴일 (양력 변환)
    '02-16',  # 설 연휴 (전날)
    '02-17',  # 설날
    '02-18',  # 설 연휴 (다음날)
    '05-24',  # 부처님오신날
    '09-24',  # 추석 연휴 (전날)
    '09-25',  # 추석
    '09-26',  # 추석 연휴 (다음날)
    # 대체공휴일
    '03-02',  # 삼일절 대체
    '10-12',  # 한글날 대체
}

KOREAN_HOLIDAYS_2027 = {
    '01-01', '03-01', '05-05', '06-06', '08-15', '10-03', '10-09', '12-25',
    # 2027 음력 → 양력 (확정 시 갱신)
    '02-06', '02-07', '02-08',  # 설
    '05-13',  # 부처님오신날
    '09-14', '09-15', '09-16',  # 추석
}

_HOLIDAYS_BY_YEAR = {
    2026: KOREAN_HOLIDAYS_2026,
    2027: KOREAN_HOLIDAYS_2027,
}


def _is_korean_holiday(d: datetime.date) -> bool:
    """공휴일 여부 (등록된 연도만 체크, 미등록 연도는 고정 공휴일만)"""
    md = d.strftime('%m-%d')
    year_holidays = _HOLIDAYS_BY_YEAR.get(d.year)
    if year_holidays:
        return md in year_holidays
    # 미등록 연도: 고정 공휴일만
    fixed = {'01-01', '03-01', '05-05', '06-06', '08-15', '10-03', '10-09', '12-25'}
    return md in fixed


def run_daily_notification_checks():
    """평일 09:00 실행 — 시간 기반 알림 일괄 점검 → 다이제스트 1건 발송"""
    from modules.db_context import get_db

    # ── 일시정지 (2026-06-12, 사용자 요청) ──
    # 일일점검(daily digest) 발송을 임시 중단. 복구 시 아래 가드 삭제.
    DAILY_DIGEST_PAUSED = True
    if DAILY_DIGEST_PAUSED:
        logger.info("[notification_scheduler] 일일점검 일시정지 중 — 스킵")
        return

    try:
        today = datetime.date.today()

        # 공휴일이면 스킵
        if _is_korean_holiday(today):
            logger.info("[notification_scheduler] 공휴일(%s) — 알림 스킵", today)
            return

        with get_db() as db:

            # 각 점검 함수는 (카테고리명, 항목 리스트) 반환
            sections: List[Dict] = []

            items = _check_delivery_deadlines(db, today)
            if items:
                sections.append({'label': '납품기한', 'icon': '📦', 'items': items})

            items = _check_material_overdue(db, today)
            if items:
                sections.append({'label': '입고지연', 'icon': '🚚', 'items': items})

            items = _check_low_stock(db)
            if items:
                sections.append({'label': '재고부족', 'icon': '📉', 'items': items})

            items = _check_document_deadlines(db, today)
            if items:
                sections.append({'label': '서류마감', 'icon': '📋', 'items': items})

            items = _check_warranty_expiry(db, today)
            if items:
                sections.append({'label': '하자보증', 'icon': '🔧', 'items': items})

            items = _check_cert_expiry(db, today)
            if items:
                sections.append({'label': '인증서', 'icon': '📜', 'items': items})

            if not sections:
                logger.info("[notification_scheduler] 일일 점검 — 알림 대상 없음")
                return

            total = sum(len(s['items']) for s in sections)

            # 다이제스트 메시지 조립
            message_lines = []
            for sec in sections:
                message_lines.append(f"{sec['icon']} {sec['label']} ({len(sec['items'])}건)")
                for item in sec['items']:
                    message_lines.append(f"  · {item}")

            data = {
                'date': today.strftime('%m/%d'),
                'total': total,
                'summary': _build_summary(sections),
                'digest_message': '\n'.join(message_lines),
            }

            notify(db, 'daily.digest', data,
                   dedupe_key=f'digest-{today.isoformat()}')

            db.commit()
            logger.info("[notification_scheduler] 일일 다이제스트 발송 — %d건 (%d개 카테고리)",
                        total, len(sections))
    except Exception as e:
        logger.error("[notification_scheduler] 일일 알림 점검 오류: %s", e)


def cleanup_old_notifications():
    """90일 이상 된 읽은 알림 삭제 (매주 일요일 03:00)"""
    from modules.db_context import get_db
    from modules.models import Notification

    try:
        with get_db() as db:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=90)
            deleted = db.query(Notification).filter(
                Notification.is_read.is_(True),
                Notification.created_at < cutoff,
            ).delete()
            db.commit()
            if deleted:
                logger.info("[notification_scheduler] 만료 알림 %d건 삭제", deleted)
    except Exception as e:
        logger.error("[notification_scheduler] 알림 정리 오류: %s", e)


def _build_summary(sections: List[Dict]) -> str:
    """카테고리별 건수 요약 한 줄 (예: 납품기한 3 · 재고부족 1)"""
    parts = [f"{s['label']} {len(s['items'])}" for s in sections]
    return ' · '.join(parts)


# ────────────────────────────────────────────────────────
# 개별 점검 함수 — 항목 문자열 리스트 반환
# ────────────────────────────────────────────────────────

def _check_delivery_deadlines(db, today) -> List[str]:
    """납품기한 D-7, D-1, 초과"""
    from modules.models import Contract, Project
    from modules.contract_filters import active_contract_filter
    from sqlalchemy.orm import joinedload

    contracts = db.query(Contract).join(
        Project, Project.id == Contract.project_id
    ).filter(
        Project.is_contracted.is_(True),
        active_contract_filter(),
        Contract.delivery_due_date.isnot(None),
    ).options(joinedload(Contract.project)).all()

    items = []
    for c in contracts:
        if not c.project:
            continue
        delta = (c.delivery_due_date - today).days
        name = c.contract_name or c.project.short_name or c.project.temp_name or f'현장#{c.project_id}'

        if delta == 7:
            items.append(f"{name} — D-7 ({c.delivery_due_date.strftime('%m/%d')})")
        elif delta == 1:
            items.append(f"{name} — 내일 납품 ({c.delivery_due_date.strftime('%m/%d')})")
        elif delta < 0:
            items.append(f"{name} — D+{abs(delta)}일 초과")

    return items


def _check_material_overdue(db, today) -> List[str]:
    """입고 지연"""
    from modules.models.entities import MaterialOrder
    from sqlalchemy.orm import joinedload

    overdue_list = db.query(MaterialOrder).filter(
        MaterialOrder.order_status == '발주완료',
        MaterialOrder.in_confirmed.is_(False),
        MaterialOrder.expected_in_date.isnot(None),
        MaterialOrder.expected_in_date < today,
    ).options(joinedload(MaterialOrder.project)).all()

    items = []
    for mo in overdue_list:
        project_name = mo.project.temp_name if mo.project else '미지정'
        overdue_days = (today - mo.expected_in_date).days
        material_name = mo.material_name or f'자재#{mo.id}'
        items.append(f"{material_name} ({project_name}) — D+{overdue_days}일")

    return items


def _check_low_stock(db) -> List[str]:
    """안전재고 미달"""
    from modules.models.inventory_entities import Item

    low_items = db.query(Item).filter(
        Item.safety_stock.isnot(None),
        Item.safety_stock > 0,
        Item.stock_qty < Item.safety_stock,
    ).all()

    items = []
    for item in low_items:
        name = item.item_name or item.model_code or f'품목#{item.id}'
        items.append(f"{name} — 현재 {int(item.stock_qty or 0)} / 안전재고 {int(item.safety_stock or 0)}")

    return items


def _check_document_deadlines(db, today) -> List[str]:
    """서류 마감 D-7 — 납품기한 7일 전인데 착수계/납품계 미완료"""
    from modules.models.document_entities import DocumentPackage
    from modules.models import Contract
    from sqlalchemy.orm import joinedload

    d7_date = today + datetime.timedelta(days=7)

    packages = db.query(DocumentPackage).join(
        Contract, Contract.id == DocumentPackage.contract_id
    ).filter(
        Contract.delivery_due_date == d7_date,
        (DocumentPackage.commencement_generated.is_(False)) | (DocumentPackage.delivery_generated.is_(False)),
    ).options(joinedload(DocumentPackage.project)).all()

    items = []
    for pkg in packages:
        project_name = pkg.project.temp_name if pkg.project else pkg.business_name or '미지정'
        missing = []
        if not pkg.commencement_generated:
            missing.append('착수계')
        if not pkg.delivery_generated:
            missing.append('납품계')
        items.append(f"{project_name} — {'/'.join(missing)} 미완료")

    return items


def _check_warranty_expiry(db, today) -> List[str]:
    """하자보증 만료 D-30"""
    from modules.models.misc_entities import Warranty
    from sqlalchemy.orm import joinedload

    d30_date = today + datetime.timedelta(days=30)

    warranties = db.query(Warranty).filter(
        Warranty.warranty_end.isnot(None),
        Warranty.warranty_end == d30_date,
    ).options(joinedload(Warranty.project)).all()

    items = []
    for w in warranties:
        project_name = w.project.temp_name if w.project else '미지정'
        items.append(f"{project_name} — {w.warranty_end.strftime('%m/%d')} 만료")

    return items


def _check_cert_expiry(db, today) -> List[str]:
    """인증서 만료 (alert_days 기준)"""
    from modules.models.misc_entities import Certification

    certs = db.query(Certification).filter(
        Certification.is_active.is_(True),
        Certification.expiry_date.isnot(None),
    ).all()

    items = []
    for cert in certs:
        alert_days = cert.alert_days or 30
        alert_date = today + datetime.timedelta(days=alert_days)
        if cert.expiry_date == alert_date:
            items.append(f"{cert.cert_name or '인증서'} — {cert.expiry_date.strftime('%m/%d')} 만료")

    return items
