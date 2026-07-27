"""알림 엔진 — 단일 진입점 notify() + 이벤트 레지스트리 + 듀얼 채널 디스패처

모든 알림은 이 모듈의 notify() 함수를 통해 발생합니다.
ERP 내부 알림(notifications 테이블) + 카카오워크 그룹챗을 동시 처리합니다.
"""
import datetime
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────
# Event Registry — 이벤트별 대상·채널·메시지 포맷 선언
# ────────────────────────────────────────────────────────

EVENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── 전자결재 ── (target은 target_override로 동적 지정)
    # 봇 발송은 approval_service에서 결재자 본인에게 Mattermost DM으로 직접 처리.
    # 여기서는 ERP 인앱 알림만 생성 (kakao/mattermost 채널 브로드캐스트는 끔 — 노이즈 방지).
    'approval.requested': {
        'title': '[결재요청] {form_name}',
        'message': '{drafter_name}님이 상신: {title}',
        'target': [],
        'noti_type': 'approval',
        'link': '/approval/{doc_id}',
        'kakao': False,
        'mattermost': False,
    },
    # 미결재 독촉 (매일 09:00 crontab) — 카카오/MM 디지털 DM은 approval_service에서 직접 발송
    'approval.reminder': {
        'title': '[미결재] 결재 대기 {pending_count}건',
        'message': '결재 차례인 문서가 {pending_count}건 있습니다.',
        'target': [],
        'noti_type': 'approval',
        'link': '/approval?tab=inbox',
        'kakao': False,
        'mattermost': False,
    },
    'approval.approved': {
        'title': '[결재완료] {form_name}',
        'message': '{title} — 최종 승인되었습니다',
        'target': [],
        'noti_type': 'approval',
        'link': '/approval/{doc_id}',
        'kakao': False,
        'mattermost': False,
    },
    'approval.rejected': {
        'title': '[결재반려] {form_name}',
        'message': '{title} — {rejecter_name}님이 반려',
        'target': [],
        'noti_type': 'approval_reject',
        'link': '/approval/{doc_id}',
        'kakao': False,
        'mattermost': False,
    },

    # ── 계약 ──
    'contract.created': {
        'title': '[신규 계약] {contract_name}',
        'message': '납품기한: {delivery_due_date}',
        'target': 'all',
        'noti_type': 'contract',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'workboard',
    },
    'contract.qty_changed': {
        'title': '[변경계약 수량반영] {contract_name}',
        'message': '{chg_ord}차 변경 — {detail}',
        'target': 'all',
        'noti_type': 'contract',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'contract.cancelled': {
        'title': '[계약취소] {contract_name}',
        'message': '{detail} — 예외처리(취소) 자동 반영',
        'target': 'all',
        'noti_type': 'contract',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'contract.change_review': {
        'title': '[변경계약 확인필요] {contract_name}',
        'message': '{reason}',
        'target': 'all',
        'noti_type': 'contract',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 납품 ──
    'delivery.scheduled': {
        'title': '[납품일정] {contract_name}',
        'message': '{detail}',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/delivery_management/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.due_d7': {
        'title': '[납품 D-7] {contract_name}',
        'message': '{delivery_due_date} 납품기한 7일 전',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.due_d1': {
        'title': '[내일 납품] {contract_name}',
        'message': '{delivery_due_date} 납품기한 — 준비 확인 필요',
        'target': 'all',
        'noti_type': 'delivery_urgent',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.overdue': {
        'title': '[납기 초과] {contract_name}',
        'message': '{delivery_due_date} 기한 D+{overdue_days}일 경과',
        'target': 'all',
        'noti_type': 'delivery_overdue',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.check_unassigned': {
        'title': '[납품확인 불가] 담당자 미배정 {count}건',
        'message': '{detail} — 담당자를 지정해 주세요',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/delivery_management',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.completed': {
        'title': '[납품 완료] {contract_name}',
        'message': '{detail}',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/delivery_management/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 생산 ──
    'production.item_complete': {
        'title': '[생산완료] {contract_name}',
        'message': '{model_name} {quantity}EA 생산완료',
        'target': 'all',
        'noti_type': 'production',
        'link': '/production_management/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'production.site_complete': {
        'title': '[전체 생산완료] {contract_name}',
        'message': '전 품목 생산완료 — 출고 준비 필요',
        'target': 'all',
        'noti_type': 'production',
        'link': '/production_management/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 자재/입고 ──
    'material.received': {
        'title': '[자재 입고] {material_name}',
        'message': '{contract_name} — {material_name} 입고 완료',
        'target': 'group:생산부',
        'noti_type': 'material',
        'link': '/receiving?tab=expected',
        'kakao': False,
    },
    'material.overdue': {
        'title': '[입고 지연] {material_name}',
        'message': '{contract_name} — D+{overdue_days}일 지연',
        'target': 'group:관리부',
        'noti_type': 'material',
        'link': '/receiving?tab=expected',
        'kakao': False,
    },

    # ── 재고 ──
    'inventory.low_stock': {
        'title': '[재고 부족] {item_name}',
        'message': '현재고 {current_qty} / 안전재고 {safe_qty}',
        'target': 'group:관리부',
        'noti_type': 'inventory',
        'link': '/inventory',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 가공발주 ──
    'processing.completed': {
        'title': '[가공 완료] {order_name}',
        'message': '{vendor_name} — 가공 완료',
        'target': 'group:생산부',
        'noti_type': 'processing',
        'link': '/processing_orders',
        'kakao': False,
    },

    # ── 서류 ──
    'document.deadline_d7': {
        'title': '[서류 마감 D-7] {document_name}',
        'message': '{contract_name} — {deadline} 마감',
        'target': 'group:관리부',
        'noti_type': 'document',
        'link': '/documents/{package_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 세금계산서 ──
    'tax_invoice.issued': {
        'title': '[세금계산서] {contract_name}',
        'message': '{amount}원 발행',
        'target': 'group:관리부',
        'noti_type': 'tax_invoice',
        'link': '/procurement',
        'kakao': False,
    },

    # ── 대금청구 ──
    'billing.completed': {
        'title': '[청구완료] {contract_name}',
        'message': '{user_name} — 대금청구 완료 처리',
        'target': 'group:관리부',
        'noti_type': 'billing',
        'link': '/billing',
        'kakao': False,
    },
    'billing.reverted': {
        'title': '[청구복원] {contract_name}',
        'message': '{user_name} — 미청구로 복원',
        'target': 'group:관리부',
        'noti_type': 'billing',
        'link': '/billing',
        'kakao': False,
    },

    # ── 하자보증 ──
    'warranty.expiring': {
        'title': '[하자보증 만료 임박] {contract_name}',
        'message': '{expiry_date} 만료 예정',
        'target': 'group:관리부',
        'noti_type': 'warranty',
        'link': '/warranty',
        'kakao': True,
        'kakao_format': 'text',
    },
    'warranty.case_registered': {
        'title': '[AS접수] {contract_name}',
        'message': '{detail}',
        'target': 'group:관리부',
        'noti_type': 'warranty',
        'link': '/warranty',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 인증서 ──
    'cert.expiring': {
        'title': '[인증서 만료 임박] {cert_name}',
        'message': '{expiry_date} 만료 — 갱신 필요',
        'target': 'group:관리부',
        'noti_type': 'cert',
        'link': '/admin/settings#cert',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 일일 다이제스트 ──
    'daily.digest': {
        'title': '[일일점검 {date}] {total}건 확인 필요',
        'message': '{digest_message}',
        'target': 'all',
        'noti_type': 'daily_digest',
        'link': '/notifications',
        'kakao': True,
        'kakao_format': 'digest',
    },

    # ── 출장 ──
    'trip.created': {
        'title': '[출장 등록] {destination}',
        'message': '{detail}',
        'target': 'all',
        'noti_type': 'trip',
        'link': '/trip_detail/{trip_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 이슈/협의변경 ──
    'issue.flagged': {
        'title': '[협의변경] {contract_name}',
        'message': '{detail}',
        'target': 'all',
        'noti_type': 'issue',
        'link': '/sales_management/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 연차사용촉진 (근로기준법 제61조) ──
    # 인사관리 권한자 전체에게 촉진 대상자 명단 통지 (target_override 로 동적 지정)
    'leave.promotion_admin': {
        'title': '[연차사용촉진] 대상자 {count}명',
        'message': '{detail}',
        'target': [],
        'noti_type': 'hr',
        'link': '/hr/promotion',
        'kakao': False,
        'mattermost': True,
    },
    # 직원 본인에게 사용시기 지정 요청 (target_override=['user:<id>'])
    'leave.promotion_employee': {
        'title': '[연차사용촉진] 사용시기 지정 요청',
        'message': '{leave_year}년도 미사용 연차 {remaining}일 — {due}까지 사용시기를 지정해 주세요',
        'target': [],
        'noti_type': 'hr',
        'link': '/hr/my-promotion',
        'kakao': False,
        'mattermost': True,
    },
}


# ────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────

def notify(db, event_type: str, data: Dict[str, Any],
           dedupe_key: Optional[str] = None,
           kakao_text_override: Optional[str] = None,
           target_override=None) -> bool:
    """알림 엔진 단일 진입점.

    Args:
        db: SQLAlchemy session
        event_type: EVENT_REGISTRY 키 (예: 'delivery.due_d1')
        data: 이벤트 데이터 — title/message 포맷 변수 + 라우팅 정보
        dedupe_key: 중복 방지 키 (같은 날 동일 키 알림 스킵, None이면 중복 체크 안 함)
        kakao_text_override: 카카오워크 메시지를 별도로 지정할 때 사용 (기본: title + message)

    Returns:
        bool: 하나 이상의 채널에 성공했으면 True
    """
    config = EVENT_REGISTRY.get(event_type)
    if not config:
        logger.warning("[notify] 등록되지 않은 이벤트: %s", event_type)
        return False

    try:
        title = _safe_format(config['title'], data)
        message = _safe_format(config['message'], data)
        link = _safe_format(config['link'], data)
        noti_type = config['noti_type']

        # 대상 사용자 결정 (target_override가 있으면 우선 — 결재 등 동적 라우팅)
        users = _resolve_targets(db, target_override if target_override is not None else config['target'])

        # dedupe_key 자동 생성 — 호출자가 명시하지 않으면 EVENT_REGISTRY 템플릿 또는
        # 합리적 디폴트(event_type + 핵심 id + 날짜)로 생성
        if dedupe_key is None:
            dedupe_key = _auto_dedupe_key(event_type, config, data)

        # ERP 내부 알림 생성
        _create_erp_notifications(db, users, title, message, noti_type, link, dedupe_key)

        # 카카오워크 발송
        if config.get('kakao'):
            _send_kakao(config, title, message, data, kakao_text_override)

        # Mattermost 발송 — 등록된 18개 이벤트 모두 기본 발송
        # (kakao=False 이벤트도 포함). mattermost=False를 명시한 경우만 스킵.
        if config.get('mattermost', True):
            _send_mattermost(event_type, title, message, link, kakao_text_override)

        return True
    except Exception as e:
        logger.error("[notify] %s 처리 오류: %s", event_type, e)
        return False


# ────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────

def _auto_dedupe_key(event_type: str, config: Dict[str, Any], data: Dict[str, Any]) -> Optional[str]:
    """이벤트별 합리적 dedupe_key 자동 생성.

    EVENT_REGISTRY의 'dedupe_template'이 있으면 그걸 우선 사용.
    없으면 event_type에서 entity_id 키워드를 추론하여 자동 생성.
    """
    tmpl = config.get('dedupe_template')
    if tmpl:
        try:
            return tmpl.format(**data, today=datetime.date.today().isoformat())
        except KeyError:
            return None

    # entity_id 자동 추론 — 자주 쓰는 키 우선순위
    today = datetime.date.today().isoformat()
    for k in ('contract_id', 'delivery_id', 'split_id', 'project_id',
              'trip_id', 'fo_id', 'rcv_id', 'case_id', 'tax_invoice_id',
              'po_id', 'cert_id'):
        if k in data and data[k]:
            return f"{event_type}:{k}={data[k]}:{today}"

    # daily.digest 같이 entity 없는 이벤트는 날짜 단위 1건만 허용
    return f"{event_type}:{today}"


def _safe_format(template: str, data: Dict[str, Any]) -> str:
    """포맷 변수가 없어도 에러 없이 처리"""
    try:
        return template.format(**data)
    except KeyError:
        return template


def _resolve_targets(db, target_spec) -> List:
    """target 사양 → User 목록"""
    from modules.models import User
    base = db.query(User).filter(User.is_active.is_(True), User.is_approved.is_(True))

    if target_spec == 'all':
        return base.all()

    if isinstance(target_spec, str) and target_spec.startswith('group:'):
        group_name = target_spec.split(':', 1)[1]
        return base.filter(User.user_group == group_name).all()

    if isinstance(target_spec, str) and target_spec.startswith('user:'):
        try:
            uid = int(target_spec.split(':', 1)[1])
        except ValueError:
            return []
        return base.filter(User.id == uid).all()

    if isinstance(target_spec, list):
        users = []
        seen = set()
        for spec in target_spec:
            for user in _resolve_targets(db, spec):
                if user.id not in seen:
                    seen.add(user.id)
                    users.append(user)
        return users

    return []


def _create_erp_notifications(db, users, title, message, noti_type, link, dedupe_key=None):
    """ERP 내부 알림 생성 — dedupe_key 컬럼 기반 중복 방지.

    같은 (user_id, dedupe_key)가 당일에 이미 있으면 스킵.
    dedupe_key=None이면 중복 체크 안 함 (즉시 알림).
    """
    from modules.models import Notification
    today_start = datetime.datetime.combine(datetime.date.today(), datetime.time.min)

    if dedupe_key:
        # 한 번에 기존 user_id 셋 조회 (N+1 쿼리 방지)
        target_uids = [u.id for u in users]
        existing = set(
            row[0]
            for row in db.query(Notification.user_id).filter(
                Notification.user_id.in_(target_uids),
                Notification.dedupe_key == dedupe_key,
                Notification.created_at >= today_start,
            ).all()
        )
    else:
        existing = set()

    for user in users:
        if dedupe_key and user.id in existing:
            continue
        db.add(Notification(
            user_id=user.id,
            title=title,
            message=message,
            noti_type=noti_type,
            link=link,
            dedupe_key=dedupe_key,
            is_read=False,
        ))


def _send_mattermost(event_type, title, message, link, text_override=None):
    """Mattermost 알림 발송 (실패해도 다른 채널에 영향 없음)"""
    try:
        from modules.services.mattermost_notification import send_mattermost_notification
        send_mattermost_notification(event_type, title, message, link, text_override=text_override)
    except Exception as e:
        logger.warning("[notify] mattermost 발송 실패 (무시): %s", e)


def _send_kakao(config, title, message, data, text_override=None):
    """카카오워크 채널 발송 (rate limit 방지: 건당 0.5초 대기)"""
    import time
    from modules.kakaowork_notifier import send_group_notification, post_contract_summary
    time.sleep(0.5)  # rate limit 방지

    kakao_format = config.get('kakao_format', 'text')

    if kakao_format == 'workboard' and 'project' in data and 'contracts' in data:
        post_contract_summary(data['project'], data['contracts'])
    elif kakao_format == 'digest':
        # 다이제스트: title + 카테고리별 요약
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        digest_msg = data.get('digest_message', message)
        text = f"{title}\n\n{digest_msg}\n\n(발행시각: {now_str})"
        send_group_notification(text)
    else:
        if text_override:
            send_group_notification(text_override)
        else:
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            text = f"{title}\n\n{message}\n\n(발행시각: {now_str})"
            send_group_notification(text)
