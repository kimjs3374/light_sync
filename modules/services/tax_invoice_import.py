"""
국세청 매출전자세금계산서 엑셀(.xls) 임포트 + G2B 자동 매칭.

세금계산서가 주 데이터. G2B 번호로 기존 계약 매칭.
"""

import re
import logging
import datetime
import xlrd

logger = logging.getLogger(__name__)

RE_G2B_CONTRACT = re.compile(r'R\d{2}TB[\d]+')           # 2025~ 신형식
RE_G2B_DELIVERY_REQ = re.compile(r'R\d{2}JG[\d]+')
RE_G2B_DELIVERY = re.compile(r'R\d{2}NS[\d]+')
RE_G2B_OLD_PAREN = re.compile(r'\((\d{10,13})\)')        # ~2024 구형식: 괄호 안 숫자 (앞10자리=계약번호)
RE_CONTRACT_NAME_NEW = re.compile(r'^(.+?)\|R\d{2}TB')   # 신형식: 계약명|R##TB...
RE_CONTRACT_NAME_OLD = re.compile(r'^(.+?)\(\d{10,13}\)') # 구형식: 계약명(숫자...)


def _parse_date(cell_value, book=None):
    if isinstance(cell_value, datetime.datetime):
        return cell_value.date()
    if isinstance(cell_value, datetime.date):
        return cell_value
    if isinstance(cell_value, float) and book:
        try:
            tup = xlrd.xldate_as_tuple(cell_value, book.datemode)
            return datetime.date(tup[0], tup[1], tup[2])
        except Exception:
            return None
    if isinstance(cell_value, str):
        cell_value = cell_value.strip()
        for fmt in ('%Y%m%d', '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
            try:
                return datetime.datetime.strptime(cell_value, fmt).date()
            except ValueError:
                continue
    return None


def _safe_int(val):
    if val is None or val == '':
        return 0
    try:
        if isinstance(val, str):
            val = val.replace(',', '').strip()
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def _safe_str(val):
    if val is None:
        return ''
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    return str(val).strip()


def _read_rows(file_path=None, file_stream=None):
    """xls/xlsx 공통 행 읽기. list of list[값] 반환."""
    raw = file_stream.read() if file_stream else None

    # xlsx 시도
    try:
        import openpyxl, io
        src = io.BytesIO(raw) if raw else file_path
        wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
        wb.close()
        return rows, None
    except Exception:
        pass

    # xls 시도
    if raw:
        book = xlrd.open_workbook(file_contents=raw)
    elif file_path:
        book = xlrd.open_workbook(file_path)
    else:
        raise ValueError("file_path 또는 file_stream 필요")

    sheet = book.sheet_by_index(0)
    rows = []
    for r in range(sheet.nrows):
        rows.append([sheet.cell_value(r, c) for c in range(sheet.ncols)])
    return rows, book


def parse_tax_invoice_excel(file_path=None, file_stream=None):
    """국세청 엑셀 파싱. xls/xlsx 모두 지원."""
    all_rows, book = _read_rows(file_path=file_path, file_stream=file_stream)
    records = []

    def _cell(row, idx):
        return row[idx] if idx < len(row) else None

    for row_idx in range(6, len(all_rows)):
        row = all_rows[row_idx]

        approval_no = _safe_str(_cell(row, 1))
        if not approval_no or len(approval_no) < 5:
            continue

        issue_date_raw = _cell(row, 0)
        send_date_raw = _cell(row, 3)

        # date 파싱: openpyxl은 datetime 객체 반환, xlrd는 float
        def _to_date(val):
            if isinstance(val, datetime.datetime):
                return val.date()
            if isinstance(val, datetime.date):
                return val
            if book:
                return _parse_date(val, book)
            return _parse_date(val, None)

        issue_date = _to_date(issue_date_raw)
        send_date = _to_date(send_date_raw)

        supplier_business_no = _safe_str(_cell(row, 4))
        supplier_name = _safe_str(_cell(row, 6))

        buyer_business_no = _safe_str(_cell(row, 9))
        buyer_name = _safe_str(_cell(row, 11))
        buyer_ceo = _safe_str(_cell(row, 12))

        total_amount = _safe_int(_cell(row, 14))
        supply_amount = _safe_int(_cell(row, 15))
        tax_amount = _safe_int(_cell(row, 16))

        invoice_type = _safe_str(_cell(row, 17)) or '세금계산서'

        remark = _safe_str(_cell(row, 20))

        # 품목
        item_date = _to_date(_cell(row, 25))
        item_name = _safe_str(_cell(row, 26))
        item_spec = _safe_str(_cell(row, 27))
        item_qty = _safe_int(_cell(row, 28))
        item_unit_price = _safe_int(_cell(row, 29))

        # G2B 번호 + 계약명 추출
        g2b_contract_no = None
        g2b_contract_name = None
        g2b_delivery_req_no = None
        g2b_delivery_no = None
        if remark:
            # 2025~ 신형식: 계약명|R##TB########|...
            m = RE_G2B_CONTRACT.search(remark)
            if m:
                g2b_contract_no = m.group(0)
                m_name = RE_CONTRACT_NAME_NEW.match(remark)
                if m_name:
                    g2b_contract_name = m_name.group(1).strip()
            else:
                # ~2024 구형식: 계약명(숫자10~13자리)
                m_old = RE_G2B_OLD_PAREN.search(remark)
                if m_old:
                    g2b_contract_no = m_old.group(1)[:10]
                    m_name = RE_CONTRACT_NAME_OLD.match(remark)
                    if m_name:
                        g2b_contract_name = m_name.group(1).strip()

            m = RE_G2B_DELIVERY_REQ.search(remark)
            if m:
                g2b_delivery_req_no = m.group(0)
            m = RE_G2B_DELIVERY.search(remark)
            if m:
                g2b_delivery_no = m.group(0)

        records.append({
            'approval_no': approval_no,
            'issue_date': issue_date,
            'send_date': send_date,
            'invoice_type': invoice_type,
            'supplier_business_no': supplier_business_no,
            'supplier_name': supplier_name,
            'buyer_business_no': buyer_business_no,
            'buyer_name': buyer_name,
            'buyer_ceo': buyer_ceo,
            'total_amount': total_amount,
            'supply_amount': supply_amount,
            'tax_amount': tax_amount,
            'item_date': item_date,
            'item_name': item_name,
            'item_spec': item_spec,
            'item_qty': item_qty,
            'item_unit_price': item_unit_price,
            'remark': remark,
            'g2b_contract_no': g2b_contract_no,
            'g2b_contract_name': g2b_contract_name,
            'g2b_delivery_req_no': g2b_delivery_req_no,
            'g2b_delivery_no': g2b_delivery_no,
        })

    return records


def import_and_match(db, records):
    """세금계산서 DB 저장 + G2B 계약 매칭."""
    from modules.models import TaxInvoice, Contract, G2bProcurement

    result = {'imported': 0, 'matched': 0, 'unmatched': 0, 'skipped': 0}

    for rec in records:
        existing = db.query(TaxInvoice).filter_by(approval_no=rec['approval_no']).first()
        if existing:
            result['skipped'] += 1
            continue

        inv = TaxInvoice(
            approval_no=rec['approval_no'],
            issue_date=rec['issue_date'],
            send_date=rec['send_date'],
            invoice_type=rec['invoice_type'],
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
            g2b_contract_no=rec['g2b_contract_no'],
            g2b_contract_name=rec['g2b_contract_name'],
            g2b_delivery_req_no=rec['g2b_delivery_req_no'],
            g2b_delivery_no=rec['g2b_delivery_no'],
        )

        # G2B 매칭: g2b_procurements.cntrct_dlvr_req_no 기준
        matched = False
        if rec['g2b_contract_no']:
            proc = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_no == rec['g2b_contract_no']
            ).first()
            if proc:
                inv.match_status = '자동매칭'
                matched = True

                # 이 G2B 번호로 연결된 Contract가 있으면 연결
                contract = db.query(Contract).filter(
                    Contract.g2b_contract_no == rec['g2b_contract_no']
                ).first()
                if contract:
                    inv.contract_id = contract.id
                    inv.project_id = contract.project_id
                    contract.payment_status = '입금완료'
                    if rec['issue_date']:
                        contract.invoice_date = rec['issue_date']
                        contract.payment_date = rec['issue_date']

        if matched:
            result['matched'] += 1
        else:
            inv.match_status = '미매칭'
            result['unmatched'] += 1

        db.add(inv)
        result['imported'] += 1

    db.flush()
    return result
