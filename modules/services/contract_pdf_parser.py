"""
분할납품요구서 PDF 파싱 모듈.

나라장터(KONEPS) 표준 양식에서 API 미제공 필드를 추출한다.
- 계약체결번호, 계약체결일자
- 수수료, 합계금액
- 하자담보책임기간
- 검사기관, 검수기관
"""

import io
import re
import logging
from datetime import date

logger = logging.getLogger(__name__)


def parse_contract_pdf(file_bytes):
    """
    분할납품요구서 PDF 바이트에서 핵심 필드를 추출한다.

    Returns:
        dict with keys:
            delivery_req_no: 납품요구번호
            contract_no: 계약체결번호
            contract_date: 계약체결일자 (date)
            req_date: 납품요구일자 (date)
            demand_org: 수요기관명
            demand_org_no: 수요기관번호
            business_name: 사업명
            supply_amount: 품대계
            fee: 수수료
            total_amount: 합계금액
            warranty_period: 하자담보책임기간
            inspection_org: 검사기관
            acceptance_org: 검수기관
            items: list of dicts (품목별 정보)
    """
    import pdfplumber

    text = ''
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + '\n'

    if not text.strip():
        raise ValueError("PDF에서 텍스트를 추출할 수 없습니다.")

    result = {}

    # --- 납품요구번호 ---
    m = re.search(r'납\s*품\s*요\s*구\s*번\s*호\s*:?\s*([A-Za-z0-9\-]+)', text)
    if m:
        result['delivery_req_no'] = m.group(1).strip()

    # --- 계약번호 + 계약일자 ---
    # 패턴: 계약번호 제002280992-01호(2025/04/24) 또는 제00-22-7-0159-00호(2022.05.12)
    m = re.search(r'계약번호\s*제\s*([A-Za-z0-9\-]+)\s*호\s*\(\s*(\d{4}[./]\d{2}[./]\d{2})\s*\)', text)
    if m:
        result['contract_no'] = m.group(1).strip()
        date_str = m.group(2).replace('/', '.').replace('-', '.')
        parts = date_str.split('.')
        if len(parts) == 3:
            try:
                result['contract_date'] = date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                pass

    # --- 납품요구일자 ---
    m = re.search(r'납\s*품\s*요\s*구\s*일\s*자\s*:?\s*(\d{4}[./]\d{2}[./]\d{2})', text)
    if m:
        date_str = m.group(1).replace('/', '.').replace('-', '.')
        parts = date_str.split('.')
        if len(parts) == 3:
            try:
                result['req_date'] = date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                pass

    # --- 수요기관 ---
    m = re.search(r'수\s*요\s*기\s*관\s*:?\s*([^\s계나사문하][\w\s]*?)(?:\s{2,}|계)', text)
    if m:
        result['demand_org'] = m.group(1).strip()

    # --- 수요기관번호 ---
    m = re.search(r'수\s*요\s*기\s*관\s*번\s*호\s*:?\s*(\d+)', text)
    if m:
        result['demand_org_no'] = m.group(1).strip()

    # --- 하자담보책임기간 ---
    m = re.search(r'하자담보책임기간\s*:?\s*(\d+)\s*년', text)
    if m:
        result['warranty_period'] = f"{m.group(1)}년"

    # --- 품대계, 수수료, 합계금액, 분할납품, 검사, 검수 ---
    # 요약 테이블 행: 품대계 수수료 합계금액 분할납품 검사 검수
    # 예: 9,720,000 47,230 9,767,230 가능 전라남도 전라남도
    _parse_summary_table(text, result)

    # --- 사업명 ---
    m = re.search(r'사\s*업\s*명\s*:\s*(.+?)(?:\n|순)', text)
    if m:
        result['business_name'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # --- 품목 정보 ---
    result['items'] = _parse_items(text)

    logger.info("PDF 파싱 결과: 납품요구번호=%s, 계약번호=%s, 수수료=%s",
                result.get('delivery_req_no'), result.get('contract_no'), result.get('fee'))

    return result


def _parse_summary_table(text, result):
    """품대계 / 수수료 / 합계금액 / 분할납품 / 검사 / 검수 행을 파싱한다."""
    # 금액 행 패턴: 연속된 숫자,콤마 3개 + 가능/불가능 + 검사기관 + 검수기관
    # 예: 9,720,000 47,230 9,767,230 가능 전라남도 전라남도
    # 예: 4,650,000 25,110 4,675,110 가능 한국광기술원 전라남도
    pattern = (
        r'([\d,]+)\s+'           # 품대계
        r'([\d,]+)\s+'           # 수수료
        r'([\d,]+)\s+'           # 합계금액
        r'(가능|불가능)\s+'       # 분할납품
        r'(.+?)\s+'              # 검사기관
        r'(.+?)(?:\n|$)'         # 검수기관
    )
    m = re.search(pattern, text)
    if m:
        result['supply_amount'] = int(m.group(1).replace(',', ''))
        result['fee'] = int(m.group(2).replace(',', ''))
        result['total_amount'] = int(m.group(3).replace(',', ''))
        result['split_delivery'] = m.group(4).strip()
        result['inspection_org'] = m.group(5).strip()
        result['acceptance_org'] = m.group(6).strip()
    else:
        # 폴백: 개별 파싱
        amounts = re.findall(r'([\d,]{5,})', text[:text.find('사 업 명') if '사 업 명' in text else 2000])
        if len(amounts) >= 3:
            result['supply_amount'] = int(amounts[0].replace(',', ''))
            result['fee'] = int(amounts[1].replace(',', ''))
            result['total_amount'] = int(amounts[2].replace(',', ''))


def _parse_items(text):
    """품목 테이블에서 품명, 규격, 단가, 수량, 납품기한 등을 추출한다."""
    items = []

    # 물품식별번호 패턴으로 품목 행 찾기 (8자리분류번호+식별번호)
    # 예: 3911152622773990 또는 39111526 22773990
    item_pattern = re.findall(
        r'(\d{8})\s*(\d{8,})'  # 물품분류번호 + 물품식별번호
        r'.*?'
        r'([\d,]+\.?\d*)\s+'   # 단가
        r'(\d+)\s+'            # 수량
        r'(\d{4}/\d{2}/\d{2})', # 납품기한
        text, re.DOTALL
    )

    for match in item_pattern:
        item = {
            'product_class_no': match[0],
            'product_ident_no': match[1],
            'unit_price': int(float(match[2].replace(',', ''))),
            'quantity': int(match[3]),
        }
        # 납품기한
        date_parts = match[4].split('/')
        if len(date_parts) == 3:
            try:
                item['delivery_date'] = date(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
            except ValueError:
                pass
        items.append(item)

    return items


def update_procurement_from_pdf(db_session, parsed_data):
    """
    파싱 결과를 g2b_procurements 테이블에 보완 저장한다.
    납품요구번호로 매칭하여 PDF 전용 필드를 업데이트한다.

    Returns:
        int: 업데이트된 레코드 수
    """
    from modules.models.misc_entities import G2bProcurement

    req_no = parsed_data.get('delivery_req_no')
    if not req_no:
        logger.warning("납품요구번호 없음 — PDF 파싱 결과를 저장할 수 없습니다.")
        return 0

    records = db_session.query(G2bProcurement).filter(
        G2bProcurement.cntrct_dlvr_req_no == req_no
    ).all()

    if not records:
        logger.warning("납품요구번호 %s에 해당하는 조달내역이 없습니다.", req_no)
        return 0

    updated = 0
    for rec in records:
        changed = False
        if parsed_data.get('contract_no') and not rec.pdf_contract_no:
            rec.pdf_contract_no = parsed_data['contract_no']
            changed = True
        if parsed_data.get('contract_date') and not rec.pdf_contract_date:
            rec.pdf_contract_date = parsed_data['contract_date']
            changed = True
        if parsed_data.get('fee') and not rec.pdf_fee:
            rec.pdf_fee = parsed_data['fee']
            changed = True
        if parsed_data.get('total_amount') and not rec.pdf_total_amount:
            rec.pdf_total_amount = parsed_data['total_amount']
            changed = True
        if parsed_data.get('warranty_period') and not rec.pdf_warranty_period:
            rec.pdf_warranty_period = parsed_data['warranty_period']
            changed = True
        if parsed_data.get('inspection_org') and not rec.pdf_inspection_org:
            rec.pdf_inspection_org = parsed_data['inspection_org']
            changed = True
        if parsed_data.get('acceptance_org') and not rec.pdf_acceptance_org:
            rec.pdf_acceptance_org = parsed_data['acceptance_org']
            changed = True
        if changed:
            updated += 1

    if updated:
        db_session.commit()
        logger.info("납품요구번호 %s: %d건 PDF 보완 필드 업데이트", req_no, updated)

    return updated
