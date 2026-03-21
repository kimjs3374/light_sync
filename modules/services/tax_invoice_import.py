"""
국세청 매출전자세금계산서 엑셀(.xls) 임포트 + G2B 자동 매칭.

세금계산서가 주 데이터. G2B 번호로 기존 계약 매칭.
"""

import re
import logging
import datetime
import xlrd

logger = logging.getLogger(__name__)

RE_G2B_CONTRACT = re.compile(r'R\d{2}T[AB][\d]+')         # 2025~ 신형식: R##TB or R##TA
RE_G2B_DELIVERY_REQ = re.compile(r'R\d{2}JG[\d]+')
RE_G2B_DELIVERY = re.compile(r'R\d{2}NS[\d]+')
RE_G2B_TOKEN = re.compile(r'[A-Za-z0-9_]{7,20}')          # 비고에서 토큰 추출용
RE_CONTRACT_NAME_NEW = re.compile(r'^(.+?)\|R\d{2}T[AB]')  # 신형식: 계약명|R##TB...
RE_CONTRACT_NAME_PIPE = re.compile(r'^(.+?)\|[A-Za-z0-9]') # 파이프: 계약명|...


def _extract_name_before_token(remark, token):
    """비고 텍스트에서 토큰 앞의 계약명 부분을 추출."""
    idx = remark.find(token)
    if idx <= 0:
        return None
    name_part = remark[:idx].rstrip('|(').strip()
    if name_part and '\n' in name_part:
        name_part = name_part.split('\n')[0].strip()
    return name_part


def find_g2b_no_from_remark(remark, g2b_numbers_set):
    """비고 텍스트에서 G2B 번호를 찾는다 (DB 대조 방식)

    Args:
        remark: 세금계산서 비고란 텍스트
        g2b_numbers_set: set of g2b_procurements.cntrct_dlvr_req_no

    Returns:
        (g2b_contract_no, g2b_contract_name) or (None, None)
    """
    if not remark:
        return None, None

    # 1차: 신형식 R##TB/R##TA 패턴 (가장 확실)
    m = RE_G2B_CONTRACT.search(remark)
    if m:
        g2b_no = m.group(0)
        if g2b_no in g2b_numbers_set:
            m_name = RE_CONTRACT_NAME_NEW.match(remark)
            return g2b_no, (m_name.group(1).strip() if m_name else None)

    # 2차: 비고의 모든 토큰을 G2B DB와 대조
    tokens = RE_G2B_TOKEN.findall(remark)
    for token in tokens:
        # 정확 매칭
        if token in g2b_numbers_set:
            return token, _extract_name_before_token(remark, token)

        # 변형 매칭 시도: 뒤 2자리(변경차수 00) 제거 후 조합
        candidates = set()
        if len(token) >= 10:
            candidates.add(token[:10])              # 앞 10자리
            candidates.add(token[:10] + '_1')       # 앞 10자리 + _1
        if len(token) >= 12:
            candidates.add(token[:-2])              # 뒤 2자리(변경차수) 제거
            candidates.add(token[:-2] + '_1')       # 뒤 2자리 제거 + _1
        if len(token) >= 9:
            candidates.add(token[:9] + '_1')        # 앞 9자리 + _1

        for c in candidates:
            if c in g2b_numbers_set:
                return c, _extract_name_before_token(remark, token)

    return None, None


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


def parse_tax_invoice_excel(file_path=None, file_stream=None, g2b_numbers_set=None):
    """국세청 엑셀 파싱. xls/xlsx 모두 지원.
    g2b_numbers_set: G2B 조달내역 계약번호 집합 (비고 파싱용, 없으면 빈 set)
    """
    _g2b_set = g2b_numbers_set or set()
    all_rows, book = _read_rows(file_path=file_path, file_stream=file_stream)
    records = []

    def _cell(row, idx):
        return row[idx] if idx < len(row) else None

    for row_idx in range(6, len(all_rows)):
        row = all_rows[row_idx]

        approval_no = _safe_str(_cell(row, 1))
        if not approval_no or len(approval_no) < 5:
            continue

        issue_date = _parse_date(_cell(row, 0), book)
        send_date = _parse_date(_cell(row, 3), book)

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
        item_date = _parse_date(_cell(row, 25), book)
        item_name = _safe_str(_cell(row, 26))
        item_spec = _safe_str(_cell(row, 27))
        item_qty = _safe_int(_cell(row, 28))
        item_unit_price = _safe_int(_cell(row, 29))

        # G2B 번호 + 계약명 추출 (DB 대조 방식)
        g2b_contract_no = None
        g2b_contract_name = None
        g2b_delivery_req_no = None
        g2b_delivery_no = None
        if remark:
            g2b_contract_no, g2b_contract_name = find_g2b_no_from_remark(remark, _g2b_set)

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


def _link_invoice_to_contract(db, inv, g2b_no, issue_date, auto_create_warranty):
    """G2B 번호로 계약을 찾아 세금계산서에 연결하고 수금 처리."""
    from modules.models import Contract
    contract = db.query(Contract).filter(
        Contract.g2b_contract_no == g2b_no
    ).first()
    if contract:
        inv.contract_id = contract.id
        inv.project_id = contract.project_id
        contract.payment_status = '입금완료'
        if issue_date:
            contract.invoice_date = issue_date
            contract.payment_date = issue_date
            auto_create_warranty(db, contract.id, issue_date)


def import_and_match(db, records):
    """세금계산서 DB 저장 + G2B 계약 매칭."""
    from modules.models import TaxInvoice, G2bProcurement
    from modules.services.warranty_auto import auto_create_warranty

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
                _link_invoice_to_contract(db, inv, rec['g2b_contract_no'], rec['issue_date'], auto_create_warranty)

        # 2차: 계약번호 매칭 실패 시 계약명으로 매칭 시도
        if not matched and rec['g2b_contract_name']:
            proc = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_nm == rec['g2b_contract_name']
            ).first()
            if proc:
                inv.g2b_contract_no = proc.cntrct_dlvr_req_no
                inv.match_status = '자동매칭'
                matched = True
                _link_invoice_to_contract(db, inv, proc.cntrct_dlvr_req_no, rec['issue_date'], auto_create_warranty)

        if matched:
            result['matched'] += 1
        else:
            inv.match_status = '미매칭'
            result['unmatched'] += 1

        db.add(inv)
        result['imported'] += 1

    db.flush()
    return result
