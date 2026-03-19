"""
iCUBE SQL Server -> Light-Sync PostgreSQL 마이그레이션 스크립트.

대상 테이블:
  - STRADE -> Vendor (거래처)
  - SITEM -> Item (품목)
  - LPURCLS + LPURCLS_D -> PurchaseOrderHistory (발주이력)
  - LSTOCK + LSTOCK_D -> ReceivingHistory (입고이력)

실행: python scripts/migrate_icube.py
- 여러 번 실행해도 안전 (중복 체크: icube_tr_cd, icube_item_cd, icube_cls_nb, icube_rcv_nb)
- iCUBE DB는 읽기만 (절대 쓰기 금지)
"""

import json
import os
import sys
import datetime
import logging

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import pyodbc
from modules.models import SessionLocal, init_db
from modules.models.entities import Vendor, Item, PurchaseOrderHistory, ReceivingHistory, EmailHistory
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CO_CD = '1000'

# ---------------------------------------------------------------------------
# iCUBE 연결
# ---------------------------------------------------------------------------
def get_icube_conn():
    server = os.environ.get('ICUBE_DB_SERVER', r'localhost\SQLEXPRESS')
    db_name = os.environ.get('ICUBE_DB_NAME', 'DZICUBE')
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={db_name};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=30)


def icube_query(conn, sql, params=None):
    cursor = conn.cursor()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    if not cursor.description:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# 날짜 변환 헬퍼
# ---------------------------------------------------------------------------
def parse_date(dt_str):
    """'YYYYMMDD' 문자열을 date 객체로 변환. 비정상이면 None."""
    if not dt_str:
        return None
    s = str(dt_str).strip()[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        year = int(s[:4])
        month = int(s[4:6])
        day = int(s[6:8])
        # 비정상 날짜 필터 (미래 2027년 이후 또는 1990년 이전)
        if year > 2027 or year < 1990:
            logger.warning("  비정상 날짜 보정 건너뜀: %s", dt_str)
            return None
        return datetime.date(year, month, day)
    except ValueError:
        logger.warning("  날짜 파싱 실패: %s", dt_str)
        return None


# ---------------------------------------------------------------------------
# 1. 거래처 마이그레이션 (STRADE -> Vendor)
# ---------------------------------------------------------------------------
def migrate_vendors(icube_conn, db):
    logger.info("=== 거래처(STRADE) 마이그레이션 시작 ===")
    rows = icube_query(icube_conn, """
        SELECT TR_CD, TR_NM, CEO_NM, REG_NB, EMAIL, TEL, FAX,
               DIV_ADDR1, ADDR2, BUSINESS, JONGMOK, USE_YN
        FROM STRADE
        WHERE CO_CD = ?
    """, [CO_CD])
    logger.info("  iCUBE 조회: %d건", len(rows))

    # 기존 데이터 조회 (중복 체크)
    existing = {v.icube_tr_cd for v in db.query(Vendor.icube_tr_cd).filter(Vendor.icube_tr_cd.isnot(None)).all()}
    new_count = 0
    update_count = 0

    for row in rows:
        tr_cd = str(row['TR_CD']).strip()
        addr1 = str(row.get('DIV_ADDR1') or '').strip()
        addr2 = str(row.get('ADDR2') or '').strip()
        address = f"{addr1} {addr2}".strip() if (addr1 or addr2) else None

        if tr_cd in existing:
            # 기존 데이터 업데이트
            vendor = db.query(Vendor).filter_by(icube_tr_cd=tr_cd).first()
            if vendor:
                vendor.name = str(row.get('TR_NM') or '').strip()
                vendor.ceo_name = str(row.get('CEO_NM') or '').strip() or None
                vendor.business_no = str(row.get('REG_NB') or '').strip() or None
                vendor.email = str(row.get('EMAIL') or '').strip() or None
                vendor.tel = str(row.get('TEL') or '').strip() or None
                vendor.fax = str(row.get('FAX') or '').strip() or None
                vendor.address = address
                vendor.business = str(row.get('BUSINESS') or '').strip() or None
                vendor.jongmok = str(row.get('JONGMOK') or '').strip() or None
                vendor.is_active = (row.get('USE_YN') == 'Y')
                update_count += 1
        else:
            db.add(Vendor(
                icube_tr_cd=tr_cd,
                name=str(row.get('TR_NM') or '').strip(),
                ceo_name=str(row.get('CEO_NM') or '').strip() or None,
                business_no=str(row.get('REG_NB') or '').strip() or None,
                email=str(row.get('EMAIL') or '').strip() or None,
                tel=str(row.get('TEL') or '').strip() or None,
                fax=str(row.get('FAX') or '').strip() or None,
                address=address,
                business=str(row.get('BUSINESS') or '').strip() or None,
                jongmok=str(row.get('JONGMOK') or '').strip() or None,
                is_active=(str(row.get('USE_YN') or '').strip() in ('1', 'Y', 'y')),
            ))
            new_count += 1

    db.commit()
    logger.info("  완료: 신규 %d건, 업데이트 %d건", new_count, update_count)


# ---------------------------------------------------------------------------
# 2. 품목 마이그레이션 (SITEM -> Item)
# ---------------------------------------------------------------------------
def migrate_items(icube_conn, db):
    logger.info("=== 품목(SITEM) 마이그레이션 시작 ===")
    rows = icube_query(icube_conn, """
        SELECT ITEM_CD, ITEM_NM, ITEM_DC, UNIT_DC, USE_YN
        FROM SITEM
        WHERE CO_CD = ?
    """, [CO_CD])
    logger.info("  iCUBE 조회: %d건", len(rows))

    existing = {i.icube_item_cd for i in db.query(Item.icube_item_cd).filter(Item.icube_item_cd.isnot(None)).all()}
    new_count = 0
    update_count = 0

    for row in rows:
        item_cd = str(row['ITEM_CD']).strip()
        if item_cd in existing:
            item = db.query(Item).filter_by(icube_item_cd=item_cd).first()
            if item:
                item.item_name = str(row.get('ITEM_NM') or '').strip()
                item.item_spec = str(row.get('ITEM_DC') or '').strip() or None
                item.unit = str(row.get('UNIT_DC') or '').strip() or None
                item.is_active = (str(row.get('USE_YN') or '').strip() in ('1', 'Y', 'y'))
                update_count += 1
        else:
            db.add(Item(
                icube_item_cd=item_cd,
                item_name=str(row.get('ITEM_NM') or '').strip(),
                item_spec=str(row.get('ITEM_DC') or '').strip() or None,
                unit=str(row.get('UNIT_DC') or '').strip() or None,
                is_active=(str(row.get('USE_YN') or '').strip() in ('1', 'Y', 'y', True)),
            ))
            new_count += 1

    db.commit()
    logger.info("  완료: 신규 %d건, 업데이트 %d건", new_count, update_count)

    # manufacturer 자동 채우기 (입고이력에서 최신 거래처)
    from modules.models.entities import ReceivingHistory
    empty_items = db.query(Item).filter(
        Item.icube_item_cd.isnot(None),
        (Item.manufacturer == None) | (Item.manufacturer == ''),
    ).all()
    if empty_items:
        all_hists = db.query(ReceivingHistory).filter(
            ReceivingHistory.items_json.isnot(None)
        ).order_by(ReceivingHistory.receive_date.desc()).all()
        vendor_map = {}
        for h in all_hists:
            try:
                for it in json.loads(h.items_json):
                    code = (it.get('item_cd') or '').strip()
                    if code and code not in vendor_map and h.vendor_name:
                        vendor_map[code] = h.vendor_name.strip()
            except Exception:
                continue
        mfr_count = 0
        for item in empty_items:
            v = vendor_map.get(item.icube_item_cd)
            if v:
                item.manufacturer = v
                mfr_count += 1
        db.commit()
        logger.info("  manufacturer 자동채움: %d건", mfr_count)


# ---------------------------------------------------------------------------
# 3. 발주이력 마이그레이션 (LPURCLS + LPURCLS_D -> PurchaseOrderHistory)
# ---------------------------------------------------------------------------
def migrate_purchase_orders(icube_conn, db):
    logger.info("=== 발주이력(LPURCLS) 마이그레이션 시작 ===")

    # 헤더 조회
    headers = icube_query(icube_conn, """
        SELECT h.CLS_NB, h.CLS_DT, h.TR_CD, h.REMARK_DC, t.TR_NM
        FROM LPURCLS h
        LEFT JOIN STRADE t ON h.CO_CD = t.CO_CD AND h.TR_CD = t.TR_CD
        WHERE h.CO_CD = ?
        ORDER BY h.CLS_DT DESC
    """, [CO_CD])
    logger.info("  iCUBE 발주 헤더: %d건", len(headers))

    # 상세 조회
    details = icube_query(icube_conn, """
        SELECT d.CLS_NB, d.CLS_SQ, d.ITEM_CD,
               s.ITEM_NM, s.ITEM_DC, s.UNIT_DC,
               d.CLS_QT, d.CLS_UM, d.CLSG_AM, d.CLSV_AM, d.CLSH_AM, d.REMARK_DC
        FROM LPURCLS_D d
        LEFT JOIN SITEM s ON d.CO_CD = s.CO_CD AND d.ITEM_CD = s.ITEM_CD
        WHERE d.CO_CD = ?
        ORDER BY d.CLS_NB, d.CLS_SQ
    """, [CO_CD])
    logger.info("  iCUBE 발주 상세: %d건", len(details))

    # 상세를 헤더 번호별 그룹핑
    detail_map = {}
    for d in details:
        nb = d['CLS_NB']
        if nb not in detail_map:
            detail_map[nb] = []
        detail_map[nb].append({
            'seq': int(d.get('CLS_SQ') or 0),
            'item_cd': str(d.get('ITEM_CD') or '').strip(),
            'item_name': str(d.get('ITEM_NM') or '').strip(),
            'spec': str(d.get('ITEM_DC') or '').strip(),
            'unit': str(d.get('UNIT_DC') or '').strip(),
            'qty': float(d.get('CLS_QT') or 0),
            'unit_price': float(d.get('CLS_UM') or 0),
            'supply_amount': float(d.get('CLSG_AM') or 0),
            'tax_amount': float(d.get('CLSV_AM') or 0),
            'amount': float(d.get('CLSH_AM') or 0),
            'remark': str(d.get('REMARK_DC') or '').strip(),
        })

    existing = {h.icube_cls_nb for h in db.query(PurchaseOrderHistory.icube_cls_nb).all()}
    new_count = 0

    for h in headers:
        cls_nb = str(h['CLS_NB']).strip()
        if cls_nb in existing:
            continue

        items_list = detail_map.get(cls_nb, [])
        total = sum(item.get('amount', 0) for item in items_list)

        db.add(PurchaseOrderHistory(
            icube_cls_nb=cls_nb,
            order_date=parse_date(h.get('CLS_DT')),
            vendor_name=str(h.get('TR_NM') or '').strip(),
            vendor_tr_cd=str(h.get('TR_CD') or '').strip(),
            items_json=json.dumps(items_list, ensure_ascii=False),
            total_amount=total,
            remark=str(h.get('REMARK_DC') or '').strip() or None,
        ))
        new_count += 1

    db.commit()
    logger.info("  완료: 신규 %d건 (기존 %d건 스킵)", new_count, len(existing))


# ---------------------------------------------------------------------------
# 3-2. 발주서 마이그레이션 (LPO + LPO_D -> PurchaseOrderHistory)
#      LPO가 실제 발주서 (1,128건), LPURCLS는 매입전표 (367건)
# ---------------------------------------------------------------------------
def migrate_purchase_orders_lpo(icube_conn, db):
    logger.info("=== 발주서(LPO) 마이그레이션 시작 ===")

    headers = icube_query(icube_conn, """
        SELECT h.PO_NB, h.PO_DT, h.TR_CD, h.REMARK_DC, t.TR_NM
        FROM LPO h
        LEFT JOIN STRADE t ON h.CO_CD = t.CO_CD AND h.TR_CD = t.TR_CD
        WHERE h.CO_CD = ?
        ORDER BY h.PO_DT DESC
    """, [CO_CD])
    logger.info("  iCUBE 발주서 헤더: %d건", len(headers))

    details = icube_query(icube_conn, """
        SELECT d.PO_NB, d.PO_SQ, d.ITEM_CD,
               s.ITEM_NM, s.ITEM_DC, s.UNIT_DC,
               d.PO_QT, d.PO_UM, d.POG_AM, d.POGV_AM1, d.POGH_AM1, d.REMARK_DC, d.SPEC_DC
        FROM LPO_D d
        LEFT JOIN SITEM s ON d.CO_CD = s.CO_CD AND d.ITEM_CD = s.ITEM_CD
        WHERE d.CO_CD = ?
        ORDER BY d.PO_NB, d.PO_SQ
    """, [CO_CD])
    logger.info("  iCUBE 발주서 상세: %d건", len(details))

    detail_map = {}
    for d in details:
        nb = d['PO_NB']
        if nb not in detail_map:
            detail_map[nb] = []
        detail_map[nb].append({
            'seq': int(d.get('PO_SQ') or 0),
            'item_cd': str(d.get('ITEM_CD') or '').strip(),
            'item_name': str(d.get('ITEM_NM') or '').strip(),
            'spec': str(d.get('ITEM_DC') or d.get('SPEC_DC') or '').strip(),
            'unit': str(d.get('UNIT_DC') or '').strip(),
            'qty': float(d.get('PO_QT') or 0),
            'unit_price': float(d.get('PO_UM') or 0),
            'supply_amount': float(d.get('POG_AM') or 0),
            'tax_amount': float(d.get('POGV_AM1') or 0),
            'amount': float(d.get('POGH_AM1') or d.get('POG_AM') or 0),
            'remark': str(d.get('REMARK_DC') or '').strip(),
        })

    existing = {h.icube_cls_nb for h in db.query(PurchaseOrderHistory.icube_cls_nb).all()}
    new_count = 0

    for h in headers:
        po_nb = str(h['PO_NB']).strip()
        if po_nb in existing:
            continue

        items_list = detail_map.get(po_nb, [])
        total = sum(item.get('amount', 0) or item.get('supply_amount', 0) for item in items_list)

        db.add(PurchaseOrderHistory(
            icube_cls_nb=po_nb,
            order_date=parse_date(h.get('PO_DT')),
            vendor_name=str(h.get('TR_NM') or '').strip(),
            vendor_tr_cd=str(h.get('TR_CD') or '').strip(),
            items_json=json.dumps(items_list, ensure_ascii=False),
            total_amount=total,
            remark=str(h.get('REMARK_DC') or '').strip() or None,
        ))
        new_count += 1

    db.commit()
    logger.info("  완료: 신규 %d건 (기존 %d건 스킵)", new_count, len(existing))


# ---------------------------------------------------------------------------
# 4. 입고이력 마이그레이션 (LSTOCK + LSTOCK_D -> ReceivingHistory)
# ---------------------------------------------------------------------------
def migrate_receivings(icube_conn, db):
    logger.info("=== 입고이력(LSTOCK) 마이그레이션 시작 ===")

    headers = icube_query(icube_conn, """
        SELECT h.RCV_NB, h.RCV_DT, h.TR_CD, h.WH_CD, t.TR_NM
        FROM LSTOCK h
        LEFT JOIN STRADE t ON h.CO_CD = t.CO_CD AND h.TR_CD = t.TR_CD
        WHERE h.CO_CD = ?
        ORDER BY h.RCV_DT DESC
    """, [CO_CD])
    logger.info("  iCUBE 입고 헤더: %d건", len(headers))

    details = icube_query(icube_conn, """
        SELECT d.RCV_NB, d.RCV_SQ, d.ITEM_CD,
               s.ITEM_NM, s.ITEM_DC, s.UNIT_DC,
               d.RCV_QT, d.RCV_UM, d.RCVH_AM, d.REMARK_DC
        FROM LSTOCK_D d
        LEFT JOIN SITEM s ON d.CO_CD = s.CO_CD AND d.ITEM_CD = s.ITEM_CD
        WHERE d.CO_CD = ?
        ORDER BY d.RCV_NB, d.RCV_SQ
    """, [CO_CD])
    logger.info("  iCUBE 입고 상세: %d건", len(details))

    detail_map = {}
    for d in details:
        nb = d['RCV_NB']
        if nb not in detail_map:
            detail_map[nb] = []
        detail_map[nb].append({
            'seq': int(d.get('RCV_SQ') or 0),
            'item_cd': str(d.get('ITEM_CD') or '').strip(),
            'item_name': str(d.get('ITEM_NM') or '').strip(),
            'spec': str(d.get('ITEM_DC') or '').strip(),
            'unit': str(d.get('UNIT_DC') or '').strip(),
            'qty': float(d.get('RCV_QT') or 0),
            'unit_price': float(d.get('RCV_UM') or 0),
            'amount': float(d.get('RCVH_AM') or 0),
            'remark': str(d.get('REMARK_DC') or '').strip(),
        })

    existing = {h.icube_rcv_nb for h in db.query(ReceivingHistory.icube_rcv_nb).all()}
    new_count = 0

    for h in headers:
        rcv_nb = str(h['RCV_NB']).strip()
        if rcv_nb in existing:
            continue

        items_list = detail_map.get(rcv_nb, [])
        total = sum(item.get('amount', 0) for item in items_list)

        db.add(ReceivingHistory(
            icube_rcv_nb=rcv_nb,
            receive_date=parse_date(h.get('RCV_DT')),
            vendor_name=str(h.get('TR_NM') or '').strip(),
            vendor_tr_cd=str(h.get('TR_CD') or '').strip(),
            warehouse=str(h.get('WH_CD') or '').strip() or None,
            items_json=json.dumps(items_list, ensure_ascii=False),
            total_amount=total,
        ))
        new_count += 1

    db.commit()
    logger.info("  완료: 신규 %d건 (기존 %d건 스킵)", new_count, len(existing))


# ---------------------------------------------------------------------------
# 5. 이메일 발송이력 마이그레이션 (SEMAIL_HISTORY -> EmailHistory)
# ---------------------------------------------------------------------------
def migrate_email_history(icube_conn, db):
    logger.info("=== 이메일발송이력(SEMAIL_HISTORY) 마이그레이션 시작 ===")

    rows = icube_query(icube_conn, """
        SELECT SEND_DT, SEND_SQ, SEND_MAIL, RECIVER, SUBJECT, CONTENT, ATTACH_FILE, SEND_OK
        FROM SEMAIL_HISTORY
        WHERE CO_CD = ?
        ORDER BY SEND_DT DESC, SEND_SQ
    """, [CO_CD])
    logger.info("  iCUBE 조회: %d건", len(rows))

    # 중복 체크 (SEND_DT + SEND_SQ 조합)
    existing = set()
    for e in db.query(EmailHistory.send_date, EmailHistory.id).all():
        existing.add(e.id)
    existing_count = db.query(EmailHistory).count()

    new_count = 0
    for row in rows:
        send_dt = parse_date(row.get('SEND_DT'))
        receiver_raw = str(row.get('RECIVER') or '').strip()
        # 이메일 주소 추출: "" <email@domain.com>, → email@domain.com
        email_match = re.search(r'<([^>]+)>', receiver_raw)
        receiver = email_match.group(1) if email_match else receiver_raw.strip(',').strip()

        # 첨부파일에서 PO번호 추출
        attach = str(row.get('ATTACH_FILE') or '')
        po_match = re.search(r'(PO\d+)\.htm', attach)
        po_ref = po_match.group(1) if po_match else None

        db.add(EmailHistory(
            send_date=send_dt,
            sender=str(row.get('SEND_MAIL') or '').strip(),
            receiver=receiver,
            subject=str(row.get('SUBJECT') or '').strip(),
            content=str(row.get('CONTENT') or '').strip(),
            attachment=attach.strip('|').strip() if attach else None,
            is_success=(str(row.get('SEND_OK')) == '1'),
            po_ref=po_ref,
        ))
        new_count += 1

    db.commit()
    logger.info("  완료: 신규 %d건 (기존 %d건)", new_count, existing_count)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info("iCUBE -> Light-Sync 마이그레이션 시작")
    logger.info("=" * 60)

    # DB 초기화 (테이블 생성)
    init_db()

    icube_conn = None
    db = None
    try:
        icube_conn = get_icube_conn()
        logger.info("iCUBE DB 연결 성공")

        db = SessionLocal()

        migrate_vendors(icube_conn, db)
        migrate_items(icube_conn, db)
        migrate_purchase_orders(icube_conn, db)
        migrate_purchase_orders_lpo(icube_conn, db)
        migrate_receivings(icube_conn, db)
        migrate_email_history(icube_conn, db)

        logger.info("=" * 60)
        logger.info("마이그레이션 완료!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error("마이그레이션 오류: %s", e, exc_info=True)
        if db:
            db.rollback()
        sys.exit(1)
    finally:
        if db:
            db.close()
        if icube_conn:
            icube_conn.close()


if __name__ == '__main__':
    main()
