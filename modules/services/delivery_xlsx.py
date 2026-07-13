"""
납품계 엑셀 파일 생성 모듈 (ONLYOFFICE 연동용).

기초 자료 입력 시트에 현장 데이터를 채운 xlsx 파일을 생성합니다.
zipfile로 원본 템플릿의 XML을 직접 수정하여 ONLYOFFICE 호환성을 유지합니다.
"""

import io
import os
import re
import zipfile
import logging

from modules.services.delivery_doc_pdf import number_to_korean
from modules.storage_adapter import download_bytes

logger = logging.getLogger(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'templates', 'delivery_template.xlsx')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'documents', 'delivery')


def _strip_formula_cache(xml_content):
    """수식 셀의 캐시값(<v>) 제거 → ONLYOFFICE 로드 시 자동 재계산."""
    def _remove_v(match):
        cell = match.group(0)
        if '<f>' in cell or '<f ' in cell:
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

    # 빈 값이면 셀을 비움 (수식 IF(D27="",...)이 정상 작동하도록)
    if str_val == '':
        new_cell = f'<c r="{cell_ref}"{style}/>'
        return xml_content.replace(old_cell, new_cell)

    try:
        float(str_val)
        is_number = not str_val.startswith('0') or str_val == '0'
    except (ValueError, TypeError):
        is_number = False

    if is_number:
        new_cell = f'<c r="{cell_ref}"{style}><v>{str_val}</v></c>'
    else:
        escaped = str_val.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        new_cell = f'<c r="{cell_ref}"{style} t="inlineStr"><is><t>{escaped}</t></is></c>'

    return xml_content.replace(old_cell, new_cell)


def generate_delivery_xlsx(package, procurements, db=None):
    """
    현장 데이터를 채운 납품계 xlsx 파일을 생성합니다.
    db가 전달되면 사진관리에서 사진을 가져와 사진대지에 삽입합니다.

    Returns:
        str: 생성된 파일의 웹 경로
    """
    # 변경계약으로 빠진 품목(수량 0 + 금액 0)은 서류에서 제외 (기초 자료 입력·물납영수증 포함)
    _active = [p for p in procurements if (p.prdct_qty or 0) or (p.prdct_amt or 0)]
    if _active:
        procurements = _active

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    req_no = package.procurement_req_no or 'unknown'
    output_path = os.path.join(OUTPUT_DIR, f'{req_no}.xlsx')

    template = os.path.abspath(TEMPLATE_PATH)
    if not os.path.exists(template):
        raise FileNotFoundError(f"납품계 엑셀 템플릿이 없습니다: {template}")

    # 데이터 추출
    business_name = package.business_name or ''
    contract_no = package.contract_no or ''
    demand_org = package.demand_org or ''

    # G2B 진실원천: 변경계약 반영을 위해 cntrct_dlvr_req_date 우선 사용
    contract_date = None
    delivery_due = None
    if procurements:
        contract_date = procurements[0].cntrct_dlvr_req_date or procurements[0].pdf_contract_date
        delivery_due = procurements[0].dlvr_tmlmt_date
    if not contract_date:
        contract_date = package.contract_date

    delivery_date = package.delivery_date
    fee = package.fee or 0

    doc_no_seq = 1
    if package.delivery_doc_no:
        m = re.search(r'(\d+)호', package.delivery_doc_no)
        if m:
            seq_str = m.group(1)
            doc_no_seq = int(seq_str[-2:]) if len(seq_str) >= 2 else int(seq_str)

    # 품목 정보
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

    # 날짜 → 엑셀 시리얼 번호
    from datetime import date as _date
    def _date_serial(d):
        if not d:
            return ''
        if isinstance(d, str):
            d = _date.fromisoformat(d)
        return str((d - _date(1899, 12, 30)).days)

    # 기초 자료 입력 시트 (sheet2) 셀 매핑
    cell_data = {
        'D7': business_name,
        'D8': contract_no,
        'D9': _date_serial(contract_date),
        'D11': req_no,
        'D12': _date_serial(delivery_due),
        'D14': _date_serial(delivery_date),
        'D15': str(doc_no_seq),
        'D18': demand_org,
        'D19': package.demand_org_no or '',
        'D20': package.org_type or '청',
        'D21': '유',
        'D23': str(len(items)),
        'D38': str(fee),
    }

    # 물품 정보 (D26~D35: 모델명, G26~G35: 수량)
    # 원본 템플릿에 예시 데이터가 있는 26~29행만 초기화, 30~35행은 원래 빈 행
    for i in range(10):
        row = 26 + i
        if i < len(items):
            cell_data[f'D{row}'] = items[i]['model']
            cell_data[f'G{row}'] = str(items[i]['qty'])
        elif row <= 29:
            # 26~29행: 예시 데이터가 있으므로 빈 셀로 초기화 (수식 셀 포함)
            for col in ['D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M']:
                cell_data[f'{col}{row}'] = ''

    # NUMBERSTRING 대체: 총 공급가액 한글 변환 (ONLYOFFICE 미지원 함수)
    total_supply = sum(it['price'] * it['qty'] for it in items)
    korean_amount_str = f'금{number_to_korean(total_supply)}원 (₩{total_supply:,})'

    # zipfile로 원본 템플릿의 sheet2(기초 자료 입력) 수정 + 전체 캐시 제거
    with zipfile.ZipFile(template, 'r') as zin:
        sheet2_xml = zin.read('xl/worksheets/sheet2.xml').decode('utf-8')

        for cell, value in cell_data.items():
            sheet2_xml = _replace_cell_value(sheet2_xml, cell, value)

        sheet2_xml = _strip_formula_cache(sheet2_xml)

        # sheet3(공문): C13 NUMBERSTRING 수식을 한글 금액 문자열로 대체
        sheet3_xml = zin.read('xl/worksheets/sheet3.xml').decode('utf-8')
        sheet3_xml = _replace_cell_value(sheet3_xml, 'C13', korean_amount_str)
        sheet3_xml = _strip_formula_cache(sheet3_xml)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item_info in zin.infolist():
                if item_info.filename == 'xl/worksheets/sheet2.xml':
                    zout.writestr(item_info, sheet2_xml.encode('utf-8'))
                elif item_info.filename == 'xl/worksheets/sheet3.xml':
                    zout.writestr(item_info, sheet3_xml.encode('utf-8'))
                elif item_info.filename.startswith('xl/worksheets/sheet') and item_info.filename.endswith('.xml'):
                    other_xml = zin.read(item_info.filename).decode('utf-8')
                    other_xml = _strip_formula_cache(other_xml)
                    zout.writestr(item_info, other_xml.encode('utf-8'))
                else:
                    zout.writestr(item_info, zin.read(item_info.filename))

        with open(output_path, 'wb') as f:
            f.write(buf.getvalue())

    # 사진대지 삽입
    if db:
        try:
            project_id = package.project_id
            if not project_id:
                # package.project_id가 NULL이면 contract에서 역추적
                from modules.models import Contract
                contract = db.query(Contract).filter(
                    Contract.g2b_contract_no == req_no
                ).first()
                if contract:
                    project_id = contract.project_id
            if project_id:
                photo_data = get_delivery_photos_data(db, project_id)
                if photo_data:
                    insert_photos_into_xlsx(output_path, photo_data)
        except Exception:
            logger.exception("사진대지 사진 삽입 실패")

    web_path = f'/static/documents/delivery/{req_no}.xlsx'
    logger.info("납품계 xlsx 생성: %s (%s)", web_path, business_name)
    return web_path


# ── 사진대지 사진 삽입 ──

# 템플릿 기본 슬롯 (drawing 0-indexed): C15~C55 = 9장
_BASE_SLOT_ROWS = [14, 19, 24, 29, 34, 39, 44, 49, 54]

# 행 높이
PHOTO_ROW_HEIGHT_EMU = 3724275   # 293.25pt
PHOTO_MARGIN = 50000             # 약 4px 마진

# 5행 블록 패턴 (Excel 1-indexed 기준, 행 높이 pt)
# spacer(10.5) + label(14.1) + PHOTO(293.25) + label(14.1) + info(24.95)
_BLOCK_HEIGHTS = [10.5, 14.1, 293.25, 14.1, 24.95]


def _get_photo_slot_rows(photo_count):
    """사진 수에 맞는 drawing row 목록 반환. 9장 초과 시 동적 확장."""
    if photo_count <= len(_BASE_SLOT_ROWS):
        return _BASE_SLOT_ROWS[:photo_count]
    slots = list(_BASE_SLOT_ROWS)
    # 마지막 슬롯 Excel row = 55, 다음 블록 시작 Excel row = 58 (spacer=58, label=59, photo=60)
    next_photo_excel = 60
    for _ in range(photo_count - len(_BASE_SLOT_ROWS)):
        slots.append(next_photo_excel - 1)  # 0-indexed
        next_photo_excel += 5
    return slots


def _extract_block_templates(sheet8_xml):
    """템플릿에서 홀수/짝수 5행 블록 XML을 추출."""
    # 홀수 블록: rows 53-57, 짝수 블록: rows 48-52
    templates = {}
    for label, rows in [('odd', range(53, 58)), ('even', range(48, 53))]:
        block = []
        for rn in rows:
            pattern = rf'(<row r="{rn}"[^>]*>.*?</row>|<row r="{rn}"[^/]*/>)'
            m = re.search(pattern, sheet8_xml, re.DOTALL)
            if m:
                block.append(m.group(1))
        templates[label] = block
    return templates


def _clone_block(template_rows, src_rows, dst_start):
    """블록 행들을 복제하면서 행 번호와 셀 참조를 변경."""
    result = []
    for i, row_xml in enumerate(template_rows):
        src_r = src_rows[i]
        dst_r = dst_start + i
        # row r="N" 변경
        new_row = re.sub(rf'r="{src_r}"', f'r="{dst_r}"', row_xml)
        # 셀 참조 변경: A53 → A{dst_r}, B53 → B{dst_r}, ...
        new_row = re.sub(
            rf'r="([A-Z]+){src_r}"',
            lambda m: f'r="{m.group(1)}{dst_r}"',
            new_row,
        )
        result.append(new_row)
    return result


def _extend_sheet_rows(sheet8_xml, photo_count):
    """9장 초과 시 원본 블록을 복제하여 행·병합셀 추가."""
    if photo_count <= len(_BASE_SLOT_ROWS):
        return sheet8_xml

    templates = _extract_block_templates(sheet8_xml)
    extra_needed = photo_count - len(_BASE_SLOT_ROWS)
    # 마지막 템플릿 행: 57, 다음 블록 시작: 58
    base_row = 58

    new_rows = []
    new_merges = []

    for block_idx in range(extra_needed):
        block_start = base_row + block_idx * 5
        # 홀짝 교대 (블록 10=odd(53-57), 블록 11=even(48-52), ...)
        # 기존 9개 슬롯은 블록 1~9, 10번째부터 추가
        total_block = len(_BASE_SLOT_ROWS) + block_idx  # 0-based: 9,10,11,...
        is_odd = (total_block % 2 == 0)  # 블록 0,2,4...=odd패턴
        tpl_key = 'odd' if is_odd else 'even'
        src_rows = list(range(53, 58)) if is_odd else list(range(48, 53))

        cloned = _clone_block(templates[tpl_key], src_rows, block_start)
        new_rows.extend(cloned)

        # 병합셀 추가
        r_label = block_start + 1
        r_photo = block_start + 2
        r_label2 = block_start + 3
        r_info = block_start + 4
        new_merges.append(f'<mergeCell ref="B{r_label}:F{r_label}"/>')
        new_merges.append(f'<mergeCell ref="C{r_photo}:E{r_photo}"/>')
        new_merges.append(f'<mergeCell ref="B{r_label2}:F{r_label2}"/>')
        new_merges.append(f'<mergeCell ref="B{r_info}:F{r_info}"/>')

    rows_xml = ''.join(new_rows)
    sheet8_xml = sheet8_xml.replace('</sheetData>', rows_xml + '</sheetData>')

    merges_xml = ''.join(new_merges)
    sheet8_xml = sheet8_xml.replace('</mergeCells>', merges_xml + '</mergeCells>')

    return sheet8_xml


def _make_photo_anchor_xml(row, rid, photo_id):
    """사진 한 장의 twoCellAnchor XML 생성. col 2(C) ~ col 5(F 시작)."""
    return (
        f'<xdr:twoCellAnchor editAs="oneCell">'
        f'<xdr:from><xdr:col>2</xdr:col><xdr:colOff>{PHOTO_MARGIN}</xdr:colOff>'
        f'<xdr:row>{row}</xdr:row><xdr:rowOff>{PHOTO_MARGIN}</xdr:rowOff></xdr:from>'
        f'<xdr:to><xdr:col>5</xdr:col><xdr:colOff>0</xdr:colOff>'
        f'<xdr:row>{row}</xdr:row><xdr:rowOff>{PHOTO_ROW_HEIGHT_EMU - PHOTO_MARGIN}</xdr:rowOff></xdr:to>'
        f'<xdr:pic><xdr:nvPicPr>'
        f'<xdr:cNvPr id="{photo_id}" name="Photo {photo_id}"></xdr:cNvPr>'
        f'<xdr:cNvPicPr><a:picLocks noChangeAspect="1"></a:picLocks></xdr:cNvPicPr>'
        f'</xdr:nvPicPr>'
        f'<xdr:blipFill rotWithShape="1">'
        f'<a:blip r:embed="{rid}"></a:blip><a:stretch></a:stretch>'
        f'</xdr:blipFill>'
        f'<xdr:spPr bwMode="auto">'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'</xdr:spPr></xdr:pic><xdr:clientData/></xdr:twoCellAnchor>'
    )


def insert_photos_into_xlsx(xlsx_path, photo_data_list):
    """
    생성된 납품계 xlsx의 사진대지 시트에 사진을 삽입합니다.
    9장 초과 시 시트 행을 동적으로 확장합니다.

    Args:
        xlsx_path: xlsx 파일 경로
        photo_data_list: [(filename, image_bytes), ...]
    """
    if not photo_data_list:
        return

    photos = photo_data_list
    slot_rows = _get_photo_slot_rows(len(photos))

    with zipfile.ZipFile(xlsx_path, 'r') as zin:
        drawing3 = zin.read('xl/drawings/drawing3.xml').decode('utf-8')
        drawing3_rels = zin.read('xl/drawings/_rels/drawing3.xml.rels').decode('utf-8')
        sheet8_xml = zin.read('xl/worksheets/sheet8.xml').decode('utf-8')

        # 9장 초과 시 시트 행 확장
        if len(photos) > len(_BASE_SLOT_ROWS):
            sheet8_xml = _extend_sheet_rows(sheet8_xml, len(photos))

        # 기존 rels에서 마지막 rId 번호 추출
        existing_rids = re.findall(r'Id="rId(\d+)"', drawing3_rels)
        next_rid = max(int(r) for r in existing_rids) + 1 if existing_rids else 1

        new_anchors = []
        new_rels = []
        new_media = []

        for i, (fname, img_bytes) in enumerate(photos):
            ext = os.path.splitext(fname)[1].lower() or '.jpg'
            if ext not in ('.jpg', '.jpeg', '.png'):
                ext = '.jpg'
            media_name = f'photo_{i + 1}{ext}'
            archive_path = f'xl/media/{media_name}'

            rid = f'rId{next_rid + i}'
            photo_id = 100 + i
            row = slot_rows[i]

            new_anchors.append(_make_photo_anchor_xml(row, rid, photo_id))
            new_rels.append(
                f'<Relationship Id="{rid}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                f'Target="../media/{media_name}"/>'
            )
            new_media.append((archive_path, img_bytes))

        anchor_xml = ''.join(new_anchors)
        drawing3 = drawing3.replace('</xdr:wsDr>', anchor_xml + '</xdr:wsDr>')

        rels_xml = ''.join(new_rels)
        drawing3_rels = drawing3_rels.replace('</Relationships>', rels_xml + '</Relationships>')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == 'xl/drawings/drawing3.xml':
                    zout.writestr(item, drawing3.encode('utf-8'))
                elif item.filename == 'xl/drawings/_rels/drawing3.xml.rels':
                    zout.writestr(item, drawing3_rels.encode('utf-8'))
                elif item.filename == 'xl/worksheets/sheet8.xml':
                    zout.writestr(item, sheet8_xml.encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item.filename))

            for archive_path, img_bytes in new_media:
                zout.writestr(archive_path, img_bytes)

    # 인쇄영역 + 페이지 나누기 업데이트
    buf.seek(0)
    buf2 = _update_print_settings(buf.getvalue(), len(photos))

    with open(xlsx_path, 'wb') as f:
        f.write(buf2)

    logger.info("사진대지 사진 %d장 삽입: %s", len(photos), xlsx_path)


def _update_print_settings(xlsx_bytes, photo_count):
    """사진 수에 맞게 사진대지 인쇄영역·페이지 나누기 업데이트."""
    if photo_count <= 0:
        return xlsx_bytes

    # 마지막 사진 행 (1-indexed Excel row)
    slot_rows = _get_photo_slot_rows(photo_count)
    excel_photo_rows = [r + 1 for r in slot_rows]
    last_photo_row = excel_photo_rows[photo_count - 1]
    # 사진 블록 끝 = 사진행 + 2 (label + info)
    last_row = last_photo_row + 2

    # 페이지 나누기: row 8 (page1 끝) + 매 10행마다 (2장씩)
    # 13-22 (C15,C20), 23-32 (C25,C30), 33-42 (C35,C40), ...
    breaks = [8]  # page 1 끝
    r = 22
    while r < last_row:
        breaks.append(r)
        r += 10

    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), 'r') as zin:
        # 1) workbook.xml: 인쇄영역 업데이트
        wb_xml = zin.read('xl/workbook.xml').decode('utf-8')
        wb_xml = re.sub(
            r"(사진대지!\$A\$1:\$G\$)\d+",
            rf"\g<1>{last_row}",
            wb_xml,
        )

        # 2) sheet8.xml: rowBreaks 업데이트
        sheet8_xml = zin.read('xl/worksheets/sheet8.xml').decode('utf-8')
        brk_items = ''.join(f'<brk id="{b}" man="1" max="6"/>' for b in breaks)
        new_breaks = f'<rowBreaks count="{len(breaks)}" manualBreakCount="{len(breaks)}">{brk_items}</rowBreaks>'
        sheet8_xml = re.sub(
            r'<rowBreaks.*?</rowBreaks>',
            new_breaks,
            sheet8_xml,
            flags=re.DOTALL,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == 'xl/workbook.xml':
                    zout.writestr(item, wb_xml.encode('utf-8'))
                elif item.filename == 'xl/worksheets/sheet8.xml':
                    zout.writestr(item, sheet8_xml.encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item.filename))

        return buf.getvalue()


def get_delivery_photos_data(db, project_id):
    """
    사진관리(ProjectPhoto)에서 프로젝트 사진을 다운로드합니다.
    사진관리 갤러리에서 드래그&드롭으로 지정한 순서(sort_order) 그대로 배치합니다.
    (생산/상차/하차 타입만 포함, 없는 타입은 건너뜀)

    Returns:
        [(filename, image_bytes), ...]
    """
    from modules.models import ProjectPhoto

    # 갤러리 드래그 순서(sort_order) 그대로 — 타입 구분 없이 지정한 순서대로
    photos = (
        db.query(ProjectPhoto)
        .filter(
            ProjectPhoto.project_id == project_id,
            ProjectPhoto.photo_type.in_(['생산', '상차', '하차']),
        )
        .order_by(ProjectPhoto.sort_order.asc(), ProjectPhoto.created_at.desc())
        .all()
    )

    result = []
    for photo in photos:
        img_bytes = download_bytes(photo.storage_path)
        if img_bytes:
            result.append((photo.file_name, img_bytes))
        else:
            logger.warning("사진 다운로드 실패: %s", photo.storage_path)

    return result
