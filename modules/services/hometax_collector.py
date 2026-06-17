"""
홈택스 공동인증서 무인 매입/매출 세금계산서 수집.

hometaxbot(Apache 2.0) 라이브러리로 공동인증서 로그인 후
전자(세금)계산서 매입·매출을 끌어와 tax_invoices에 적재한다.

- 매출: 기존 import_and_match() 재사용 → G2B 계약 매칭 + 하자보증 파이프라인 연결
- 매입: direction='매입'으로 저장만 (계약 매칭/하자보증 대상 아님)
- 중복방지: approval_no(unique) 기준 skip

인증서 파일은 NPKI/(로컬 비밀 디렉토리, .gitignore)에 두고,
비밀번호는 Fernet 복호화(메일계정과 동일 키 MAIL_ENCRYPT_KEY)하여 사용한다.
"""

import re
import logging
import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def _digits(s) -> str:
    return re.sub(r'\D', '', str(s or ''))


def _int(v) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return None


# ---------------------------------------------------------------------------
# 세금계산서 객체 → import_and_match 가 받는 rec dict 로 변환
# ---------------------------------------------------------------------------
def _invoice_to_rec(inv, our_biz_no: str, g2b_set: set) -> Optional[dict]:
    """hometaxbot 세금계산서 객체를 우리 TaxInvoice rec dict 로 매핑.

    direction 판정:
      공급자 사업자번호 == 우리 → '매출'
      공급받는자 사업자번호 == 우리 → '매입'
      둘 다 아니면(위수탁 등) None 반환 → skip
    """
    from modules.services.tax_invoice_import import (
        find_g2b_no_from_remark, RE_G2B_DELIVERY_REQ, RE_G2B_DELIVERY,
    )

    supplier_no = _digits(getattr(inv.공급자, '납세자번호', ''))
    buyer_no = _digits(getattr(inv.공급받는자, '납세자번호', ''))

    if supplier_no == our_biz_no:
        direction = '매출'
    elif buyer_no == our_biz_no:
        direction = '매입'
    else:
        return None

    # invoice_type: 세금계산서/수정세금계산서/계산서/수정계산서
    try:
        invoice_type = inv.세금계산서분류.name
    except Exception:
        invoice_type = '세금계산서'

    remark = inv.비고 or ''

    # 대표 품목(첫 품목)만 단일 행으로 저장 (TaxInvoice 모델이 단일 품목 구조)
    item = (inv.품목 or [None])[0]

    g2b_contract_no = g2b_contract_name = None
    g2b_delivery_req_no = g2b_delivery_no = None
    if remark and direction == '매출':
        # G2B 매칭은 매출(우리 납품)에만 의미가 있음
        g2b_contract_no, g2b_contract_name = find_g2b_no_from_remark(remark, g2b_set)
        m = RE_G2B_DELIVERY_REQ.search(remark)
        if m:
            g2b_delivery_req_no = m.group(0)
        m = RE_G2B_DELIVERY.search(remark)
        if m:
            g2b_delivery_no = m.group(0)

    return {
        'approval_no': _digits(inv.승인번호),
        'issue_date': _to_date(inv.작성일자),
        'send_date': _to_date(inv.전송일자),
        'invoice_type': invoice_type,
        'direction': direction,
        'supplier_business_no': supplier_no,
        'supplier_name': getattr(inv.공급자, '납세자명', '') or '',
        'buyer_business_no': buyer_no,
        'buyer_name': getattr(inv.공급받는자, '납세자명', '') or '',
        'buyer_ceo': getattr(inv.공급받는자, '대표자명', '') or '',
        'total_amount': _int(inv.총금액),
        'supply_amount': _int(inv.공급가액),
        'tax_amount': _int(inv.세액),
        'item_date': _to_date(getattr(item, '공급일자', None)) if item else None,
        'item_name': (getattr(item, '품목명', '') or '') if item else '',
        'item_spec': (getattr(item, '규격', '') or '') if item else '',
        'item_qty': _int(getattr(item, '수량', 0)) if item else 0,
        'item_unit_price': _int(getattr(item, '단가', 0)) if item else 0,
        'remark': remark,
        'g2b_contract_no': g2b_contract_no,
        'g2b_contract_name': g2b_contract_name,
        'g2b_delivery_req_no': g2b_delivery_req_no,
        'g2b_delivery_no': g2b_delivery_no,
    }


# ---------------------------------------------------------------------------
# 매입분 저장 (계약매칭/하자보증 없이 upsert)
# ---------------------------------------------------------------------------
def _save_purchases(db, records) -> dict:
    from modules.models import TaxInvoice
    result = {'imported': 0, 'skipped': 0}
    for rec in records:
        if not rec['approval_no']:
            continue
        exists = db.query(TaxInvoice).filter_by(approval_no=rec['approval_no']).first()
        if exists:
            result['skipped'] += 1
            continue
        db.add(TaxInvoice(
            approval_no=rec['approval_no'],
            issue_date=rec['issue_date'],
            send_date=rec['send_date'],
            invoice_type=rec['invoice_type'],
            direction='매입',
            supplier_business_no=rec['supplier_business_no'],
            supplier_name=rec['supplier_name'],
            buyer_business_no=rec['buyer_business_no'],
            buyer_name=rec['buyer_name'],
            buyer_ceo=rec['buyer_ceo'],
            total_amount=rec['total_amount'],
            supply_amount=rec['supply_amount'],
            tax_amount=rec['tax_amount'],
            item_date=rec['item_date'],
            item_name=rec['item_name'],
            item_spec=rec['item_spec'],
            item_qty=rec['item_qty'],
            item_unit_price=rec['item_unit_price'],
            remark=rec['remark'],
            match_status='미매칭',
        ))
        result['imported'] += 1
    db.flush()
    return result


# ---------------------------------------------------------------------------
# 로그인 (인증서 + 비번)
# ---------------------------------------------------------------------------
def build_scraper(cred):
    """HometaxCredential 로 로그인된 HometaxScraper 반환."""
    from hometaxbot.scraper import HometaxScraper
    from modules.services.mail_client import decrypt_password

    if not cred or not cred.cert_der_path or not cred.cert_key_path:
        raise RuntimeError('홈택스 인증서가 등록되지 않았습니다.')
    if not cred.password_encrypted:
        raise RuntimeError('홈택스 인증서 비밀번호가 등록되지 않았습니다.')

    password = decrypt_password(cred.password_encrypted)
    scraper = HometaxScraper()
    scraper.login_with_cert([cred.cert_der_path, cred.cert_key_path], password)
    return scraper


def test_connection(cred) -> dict:
    """관리자 '연결 테스트' 용: 로그인만 수행하고 사용자 정보를 돌려준다."""
    scraper = build_scraper(cred)
    u = scraper.user_info
    return {
        'ok': True,
        'biz_no': _digits(getattr(u, '납세자번호', '')),
        'name': getattr(u, '납세자명', ''),
        'hometax_id': getattr(u, '홈택스ID', ''),
    }


# ---------------------------------------------------------------------------
# 수집 본체
# ---------------------------------------------------------------------------
def collect_invoices(db, scraper, begin: datetime.date, end: datetime.date,
                     our_biz_no: str, batch_commit: int = 200) -> dict:
    """begin~end 기간의 매입/매출 전자(세금)계산서를 수집·적재."""
    from hometaxbot.scraper.transactions import 세금계산서
    from modules.models import G2bProcurement
    from modules.services.tax_invoice_import import import_and_match

    g2b_set = {r[0] for r in db.query(G2bProcurement.cntrct_dlvr_req_no).all() if r[0]}

    stats = {'sales': 0, 'sales_matched': 0, 'purchase': 0,
             'skipped': 0, 'errors': 0, 'scanned': 0}
    sales_buf, purchase_buf = [], []

    def _flush():
        if sales_buf:
            r = import_and_match(db, sales_buf)
            stats['sales'] += r['imported']
            stats['sales_matched'] += r['matched']
            stats['skipped'] += r['skipped']
            sales_buf.clear()
        if purchase_buf:
            r = _save_purchases(db, purchase_buf)
            stats['purchase'] += r['imported']
            stats['skipped'] += r['skipped']
            purchase_buf.clear()
        db.commit()

    for inv in 세금계산서(scraper, begin, end):
        stats['scanned'] += 1
        try:
            rec = _invoice_to_rec(inv, our_biz_no, g2b_set)
            if rec is None or not rec['approval_no']:
                continue
            (sales_buf if rec['direction'] == '매출' else purchase_buf).append(rec)
            if len(sales_buf) + len(purchase_buf) >= batch_commit:
                _flush()
        except Exception as e:
            stats['errors'] += 1
            logger.warning('홈택스 세금계산서 적재 실패 (승인번호=%s): %s',
                           getattr(inv, '승인번호', '?'), e)

    _flush()
    return stats


def run_collection(begin: Optional[datetime.date] = None,
                   end: Optional[datetime.date] = None) -> dict:
    """CLI/수동 진입점. 세션 생성·인증서 로드·수집·상태갱신을 한 번에."""
    from modules.models import SessionLocal, HometaxCredential

    if end is None:
        end = datetime.date.today()
    if begin is None:
        # 일일 수집: 전송 누락 대비 최근 10일 재조회 (중복은 approval_no로 skip)
        begin = end - datetime.timedelta(days=10)

    db = SessionLocal()
    try:
        cred = db.query(HometaxCredential).order_by(HometaxCredential.id).first()
        if not cred or not cred.enabled:
            return {'ok': False, 'message': '홈택스 수집이 비활성화되어 있거나 인증서가 없습니다.'}

        cred.last_sync_status = '진행중'
        cred.last_sync_at = datetime.datetime.now()
        db.commit()

        scraper = build_scraper(cred)
        our_biz_no = _digits(cred.biz_no) or _digits(getattr(scraper.user_info, '납세자번호', ''))

        stats = collect_invoices(db, scraper, begin, end, our_biz_no)

        msg = (f"{begin}~{end} 수집완료 — "
               f"매출 {stats['sales']}건(매칭 {stats['sales_matched']}), "
               f"매입 {stats['purchase']}건, 중복 {stats['skipped']}, 오류 {stats['errors']}")
        cred.last_sync_status = '성공'
        cred.last_sync_at = datetime.datetime.now()
        cred.last_sync_message = msg
        db.commit()
        logger.info('[hometax] %s', msg)
        return {'ok': True, 'message': msg, 'stats': stats}

    except Exception as e:
        db.rollback()
        try:
            cred = db.query(HometaxCredential).order_by(HometaxCredential.id).first()
            if cred:
                cred.last_sync_status = '실패'
                cred.last_sync_at = datetime.datetime.now()
                cred.last_sync_message = f'{type(e).__name__}: {e}'
                db.commit()
        except Exception:
            db.rollback()
        logger.exception('[hometax] 수집 실패')
        # 무인 실행 실패 알림 (이벤트 미등록 시 조용히 무시)
        try:
            from modules.notification_engine import notify
            notify(db, 'hometax.sync_failed', {'message': str(e)[:200]})
        except Exception:
            pass
        return {'ok': False, 'message': f'{type(e).__name__}: {e}'}
    finally:
        db.close()
