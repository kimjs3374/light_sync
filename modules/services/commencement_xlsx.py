"""
착수계 엑셀 파일 생성 모듈 (ONLYOFFICE 연동용).

환경설정 시트에 현장 데이터를 채운 xlsx 파일을 생성합니다.
zipfile로 원본 템플릿의 XML을 직접 수정하여 ONLYOFFICE 호환성을 유지합니다.
"""

import io
import os
import re
import zipfile
import logging
from datetime import date

logger = logging.getLogger(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'templates', 'commencement_template.xlsx')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'documents', 'commencement')


def _strip_formula_cache(xml_content):
    """수식 셀의 캐시값(<v>) 제거 → ONLYOFFICE 로드 시 자동 재계산."""
    def _remove_v(match):
        cell = match.group(0)
        if '<f>' in cell or '<f ' in cell:
            # 수식이 있는 셀에서 <v>...</v> 제거 (xml:space 속성 포함)
            cell = re.sub(r'<v[^>]*>.*?</v>', '', cell, flags=re.DOTALL)
        return cell
    return re.sub(r'<c r="[^"]*"[^>]*>.*?</c>', _remove_v, xml_content, flags=re.DOTALL)


def _replace_cell_value(xml_content, cell_ref, new_value):
    """셀 값을 교체. 숫자는 그대로, 문자열은 inlineStr로."""
    pattern = rf'<c r="{cell_ref}"[^>]*>.*?</c>'
    match = re.search(pattern, xml_content, re.DOTALL)
    if not match:
        return xml_content

    old_cell = match.group(0)
    style_match = re.search(r's="(\d+)"', old_cell)
    style = f' s="{style_match.group(1)}"' if style_match else ''

    str_val = str(new_value) if new_value is not None else ''

    try:
        float(str_val)
        is_number = str_val != '' and not str_val.startswith('0') or str_val == '0'
    except (ValueError, TypeError):
        is_number = False

    if is_number:
        new_cell = f'<c r="{cell_ref}"{style}><v>{str_val}</v></c>'
    else:
        escaped = str_val.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        new_cell = f'<c r="{cell_ref}"{style} t="inlineStr"><is><t>{escaped}</t></is></c>'

    return xml_content.replace(old_cell, new_cell)


def generate_commencement_xlsx(package, procurements, agent_user=None):
    """
    현장 데이터를 채운 착수계 xlsx 파일을 생성합니다.
    zipfile로 원본 xlsx 내부 XML을 직접 수정하여 ONLYOFFICE 호환성 유지.

    Returns:
        str: 생성된 파일의 웹 경로 (예: /static/documents/commencement/R25TB00778581.xlsx)
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    req_no = package.procurement_req_no or 'unknown'
    output_path = os.path.join(OUTPUT_DIR, f'{req_no}.xlsx')

    template = os.path.abspath(TEMPLATE_PATH)
    if not os.path.exists(template):
        raise FileNotFoundError(f"착수계 엑셀 템플릿이 없습니다: {template}")

    # 데이터 추출
    business_name = package.business_name or ''
    contract_no = package.contract_no or ''
    demand_org = package.demand_org or ''
    org_type = package.org_type or '청'
    commencement_date = package.commencement_date or date.today()
    fee = package.fee or 0

    # G2B 진실원천: 변경계약 반영을 위해 cntrct_dlvr_req_date 우선 사용
    # (chg_ord 갱신 시 G2B 동기화로 자동 반영됨, package.contract_date는 PDF 파싱 스냅샷이라 stale 가능)
    contract_date = None
    delivery_due = None
    if procurements:
        contract_date = procurements[0].cntrct_dlvr_req_date or procurements[0].pdf_contract_date
        delivery_due = procurements[0].dlvr_tmlmt_date
    if not contract_date:
        contract_date = package.contract_date

    items = []
    for p in procurements:
        model = ''
        if p.prdct_idnt_no_nm:
            parts = [x.strip() for x in p.prdct_idnt_no_nm.split(',')]
            for part in parts:
                if part.startswith(('MT', 'ARENA', 'BATOO')):
                    model = part
                    break
            if not model and len(parts) >= 3:
                model = parts[0]
        items.append({
            'model': model,
            'price': p.prdct_uprc or 0,
            'qty': p.prdct_qty or 0,
        })

    agent_name = ''
    if agent_user:
        agent_name = agent_user.full_name or agent_user.username or ''

    doc_no_seq = 1
    if package.commencement_doc_no:
        m = re.search(r'(\d+)호', package.commencement_doc_no)
        if m:
            seq_str = m.group(1)
            doc_no_seq = int(seq_str[-2:]) if len(seq_str) >= 2 else int(seq_str)

    # 날짜 → 엑셀 시리얼 번호 변환 (1900-01-01 = 1)
    def _date_serial(d):
        if not d:
            return ''
        if isinstance(d, str):
            d = date.fromisoformat(d)
        return str((d - date(1899, 12, 30)).days)

    # 환경설정 시트 셀 매핑
    cell_data = {
        'B1': business_name,
        'B2': contract_no,
        'D2': req_no,
        'B3': _date_serial(contract_date),
        'D3': _date_serial(delivery_due),
        'B4': _date_serial(commencement_date),
        'B5': str(len(items)),
        'D5': str(doc_no_seq),
        'B6': demand_org,
        'D6': package.demand_org_no or '',
        'B7': org_type,
        'D7': '유',
        'J1': org_type,
        'K1': '유',
        'B10': agent_name,
    }
    if len(items) >= 1:
        cell_data['B8'] = items[0]['model']
        cell_data['D8'] = str(items[0]['price'])
        cell_data['B9'] = str(items[0]['qty'])
        cell_data['D9'] = str(fee)
    if len(items) >= 2:
        cell_data['G8'] = items[1]['model']
        cell_data['I8'] = str(items[1]['price'])
        cell_data['G9'] = str(items[1]['qty'])
    if len(items) >= 3:
        cell_data['L8'] = items[2]['model']
        cell_data['N8'] = str(items[2]['price'])
        cell_data['L9'] = str(items[2]['qty'])

    # 착수계 시트 한글 금액
    from modules.services.commencement_pdf import number_to_korean
    total_supply = sum(it['price'] * it['qty'] for it in items)
    korean_amt = f'일금 {number_to_korean(total_supply)} 원정'

    # zipfile로 원본 템플릿의 sheet1(환경설정) + sheet3(착수계) 수정
    with zipfile.ZipFile(template, 'r') as zin:
        sheet1_xml = zin.read('xl/worksheets/sheet1.xml').decode('utf-8')
        sheet3_xml = zin.read('xl/worksheets/sheet3.xml').decode('utf-8')

        for cell, value in cell_data.items():
            sheet1_xml = _replace_cell_value(sheet1_xml, cell, value)

        # 착수계 C10: 한글 금액, G10: 숫자 금액
        sheet3_xml = _replace_cell_value(sheet3_xml, 'C10', korean_amt)
        sheet3_xml = _replace_cell_value(sheet3_xml, 'G10', str(total_supply))

        # 모든 시트의 수식 캐시 제거 → 로드 시 자동 재계산
        sheet1_xml = _strip_formula_cache(sheet1_xml)
        sheet3_xml = _strip_formula_cache(sheet3_xml)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == 'xl/worksheets/sheet1.xml':
                    zout.writestr(item, sheet1_xml.encode('utf-8'))
                elif item.filename == 'xl/worksheets/sheet3.xml':
                    zout.writestr(item, sheet3_xml.encode('utf-8'))
                elif item.filename.startswith('xl/worksheets/sheet') and item.filename.endswith('.xml'):
                    # 나머지 시트들도 수식 캐시 제거
                    other_xml = zin.read(item.filename).decode('utf-8')
                    other_xml = _strip_formula_cache(other_xml)
                    zout.writestr(item, other_xml.encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item.filename))

        with open(output_path, 'wb') as f:
            f.write(buf.getvalue())

    web_path = f'/static/documents/commencement/{req_no}.xlsx'
    logger.info("착수계 xlsx 생성: %s (%s)", web_path, business_name)
    return web_path
