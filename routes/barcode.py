"""바코드 관련 Blueprint – project.py에서 분리 (D-11)."""
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from flask import Blueprint, Response, redirect, url_for, session, current_app
from modules.auth_decorators import login_required

barcode_bp = Blueprint('barcode', __name__)


@barcode_bp.route('/barcode_template')
@login_required
def download_barcode_template():

    headers = [
        'barcode', '현장명', '모델명', '생산자', '렌즈각도',
        'PCB사양', '색온도', '칩사양', '제조일자',
        'SMPS 모델명', 'SMPS 수량', 'SMPS세팅값',
        '세팅전압(VDC)', '세팅전류(ADC)', '이격거리',
        '교체전바코드', '교체사유'
    ]
    sample_row = [
        'BC-2026-0001', '샘플현장', 'LGT-500W-A', '홍길동', '90도',
        'PCB-X1', '5700K', 'Chip-3030', '26/03/03',
        'SMPS-600W', '1', '기본세팅',
        '48', '10.5', '2.5m',
        '', ''
    ]

    xlsx_data = _build_simple_xlsx([headers, sample_row])

    return Response(
        xlsx_data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': 'attachment; filename=barcode_upload_template.xlsx'
        }
    )


# ── 유틸리티 (project.py 에서 공용으로 import 가능) ──────────────


def parse_barcode_csv_rows(file_storage):
    """CSV 파일에서 바코드 행 파싱."""
    data = file_storage.read()
    text_data = ''
    for enc in ('utf-8-sig', 'cp949', 'euc-kr', 'utf-8'):
        try:
            text_data = data.decode(enc)
            break
        except Exception:
            current_app.logger.debug('CSV decode failed with enc=%s', enc)
            continue
    if not text_data:
        return []

    reader = csv.DictReader(io.StringIO(text_data))
    rows = []
    for r in reader:
        if not r:
            continue
        rows.append({(k or '').strip(): (v or '').strip() for k, v in r.items()})
    return rows


def _col_to_letters(n):
    letters = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xml_escape(v):
    s = '' if v is None else str(v)
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;'))


def _build_simple_xlsx(rows):
    content_types = """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>
  <Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
  <Override PartName='/xl/styles.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'/>
</Types>"""

    rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>
</Relationships>"""

    workbook = """<?xml version='1.0' encoding='UTF-8'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <sheets>
    <sheet name='barcode_template' sheetId='1' r:id='rId1'/>
  </sheets>
</workbook>"""

    workbook_rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>
  <Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles' Target='styles.xml'/>
</Relationships>"""

    styles = """<?xml version='1.0' encoding='UTF-8'?>
<styleSheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <fonts count='1'><font><sz val='11'/><name val='Calibri'/></font></fonts>
  <fills count='1'><fill><patternFill patternType='none'/></fill></fills>
  <borders count='1'><border/></borders>
  <cellStyleXfs count='1'><xf numFmtId='0' fontId='0' fillId='0' borderId='0'/></cellStyleXfs>
  <cellXfs count='1'><xf numFmtId='0' fontId='0' fillId='0' borderId='0' xfId='0'/></cellXfs>
</styleSheet>"""

    row_xml = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{_col_to_letters(c_idx)}{r_idx}"
            v = _xml_escape(value)
            cells.append(f"<c r='{ref}' t='inlineStr'><is><t>{v}</t></is></c>")
        row_xml.append(f"<row r='{r_idx}'>{''.join(cells)}</row>")

    sheet = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        "</worksheet>"
    )

    buff = io.BytesIO()
    with zipfile.ZipFile(buff, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('xl/workbook.xml', workbook)
        zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        zf.writestr('xl/styles.xml', styles)
        zf.writestr('xl/worksheets/sheet1.xml', sheet)
    return buff.getvalue()


def parse_barcode_xlsx_rows(file_storage):
    """XLSX 파일에서 바코드 행 파싱."""
    raw = file_storage.read()
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rows = []

    def _cell_text(cell, shared):
        c_type = cell.attrib.get('t')
        if c_type == 'inlineStr':
            t = cell.find('x:is/x:t', ns)
            return (t.text or '') if t is not None else ''
        v = cell.find('x:v', ns)
        if v is None or v.text is None:
            return ''
        if c_type == 's':
            try:
                return shared[int(v.text)]
            except Exception:
                current_app.logger.debug('XLSX shared string lookup failed for index=%s', v.text)
                return ''
        return v.text

    with zipfile.ZipFile(io.BytesIO(raw), 'r') as zf:
        shared = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            sroot = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in sroot.findall('x:si', ns):
                t = si.find('x:t', ns)
                if t is not None and t.text is not None:
                    shared.append(t.text)
                else:
                    parts = [n.text or '' for n in si.findall('.//x:t', ns)]
                    shared.append(''.join(parts))

        sheet_candidates = [n for n in zf.namelist() if n.startswith('xl/worksheets/') and n.endswith('.xml')]
        if not sheet_candidates:
            return []
        sroot = ET.fromstring(zf.read(sheet_candidates[0]))
        for row in sroot.findall('.//x:sheetData/x:row', ns):
            values = {}
            max_col = 0
            for cell in row.findall('x:c', ns):
                ref = cell.attrib.get('r', '')
                m = re.match(r'([A-Z]+)', ref)
                if not m:
                    continue
                col_letters = m.group(1)
                col_idx = 0
                for ch in col_letters:
                    col_idx = col_idx * 26 + (ord(ch) - ord('A') + 1)
                max_col = max(max_col, col_idx)
                values[col_idx] = _cell_text(cell, shared).strip()

            if max_col == 0:
                continue
            row_list = [values.get(i, '') for i in range(1, max_col + 1)]
            rows.append(row_list)

    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        d = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            d[h] = (row[i] if i < len(row) else '').strip()
        if d:
            result.append(d)
    return result
