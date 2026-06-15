"""
서류 패키지 조립 서비스.

ONLYOFFICE xlsx → PDF 변환 후 시트별 분리 + 공통서류 PDF 병합.
한 번 변환, 페이지 내용 분석으로 시트 식별, 사용자 순서대로 조립.
"""

import io
import os
import re
import time
import zipfile
import logging
import requests as _requests

from pypdf import PdfReader, PdfWriter

from modules.storage_adapter import download_bytes

logger = logging.getLogger(__name__)

ONLYOFFICE_CONVERT_URL = 'http://localhost:9980/ConvertService.ashx'

# 시트 식별 시그니처 (페이지 텍스트에서 매칭)
SHEET_SIGNATURES = [
    # 착수계
    ('공문', ['문서번호', '시행일자']),
    ('공문', ['귀청의무궁한발전']),         # 납품계 공문 (PDF 추출 텍스트)
    ('착수계', ['착수계']),
    ('서류', ['서류목록']),
    ('직생_등기구', ['직접생산확인증명서', '등기구']),
    ('직생_등주', ['직접생산확인증명서', '등주']),
    ('직생_타워', ['직접생산확인증명서', '타워']),
    ('현장대리인계', ['현장대리인계']),
    ('재직증명서', ['재직증명서']),
    ('물품계약서', ['물품계약서']),
    ('공정표_조명', ['공정표', '조명']),
    ('공정표_등주', ['공정표', '등주']),
    ('공정표_타워', ['공정표', '타워']),
    ('물품납품내역', ['납품내역', '배정']),
    # 납품계
    ('납품계', ['납품계', '감독관확인']),
    ('물납영수증', ['물품납품및영수증']),     # PDF: "물 품 납 품 및 영 수 증"
    ('물납영수증', ['물품대', '부가세']),     # 대안 매칭
    ('검수내역서', ['물품검사', '내역서']),
    ('물납확인서', ['물품납품확인서']),
    ('사진대지', ['사진대지']),
]

# 서류 항목 정의 (개별 시트 + 공통서류)
COMMENCEMENT_ITEMS = [
    {'key': 'gongmun', 'label': '공문', 'type': 'sheet', 'sheet_name': '공문'},
    {'key': 'chaksuge', 'label': '착수계', 'type': 'sheet', 'sheet_name': '착수계'},
    {'key': 'seoryu', 'label': '서류목록', 'type': 'sheet', 'sheet_name': '서류'},
    {'key': 'biz_registration', 'label': '사업자등록증', 'type': 'common',
     'path': 'documents/common/biz_registration.pdf'},
    {'key': 'factory_cert', 'label': '공장등록증명서', 'type': 'common',
     'path': 'documents/common/factory_cert.pdf'},
    {'key': 'direct_light', 'label': '직접생산확인증명서(등기구)', 'type': 'common',
     'path': 'documents/common/direct_production_light.pdf'},
    {'key': 'direct_pole', 'label': '직접생산확인증명서(등주)', 'type': 'common',
     'path': 'documents/common/direct_production_pole.pdf'},
    {'key': 'direct_tower', 'label': '직접생산확인증명서(타워)', 'type': 'common',
     'path': 'documents/common/direct_production_tower.pdf'},
    {'key': 'agent', 'label': '현장대리인계', 'type': 'sheet', 'sheet_name': '현장대리인계'},
    {'key': 'employment', 'label': '재직증명서', 'type': 'sheet', 'sheet_name': '재직증명서'},
    {'key': 'contract_doc', 'label': '물품계약서', 'type': 'sheet', 'sheet_name': '물품계약서'},
    {'key': 'schedule_light', 'label': '공정표(조명)', 'type': 'sheet', 'sheet_name': '공정표_조명'},
    {'key': 'schedule_pole', 'label': '공정표(등주)', 'type': 'sheet', 'sheet_name': '공정표_등주'},
    {'key': 'schedule_tower', 'label': '공정표(타워)', 'type': 'sheet', 'sheet_name': '공정표_타워'},
    {'key': 'delivery_list', 'label': '물품납품내역', 'type': 'sheet', 'sheet_name': '물품납품내역'},
    {'key': 'drawing', 'label': '제작도면', 'type': 'drawing'},
]

DELIVERY_ITEMS = [
    {'key': 'dl_gongmun', 'label': '공문', 'type': 'sheet', 'sheet_name': '공문'},
    {'key': 'dl_napumgye', 'label': '납품계', 'type': 'sheet', 'sheet_name': '납품계'},
    {'key': 'dl_mulnap', 'label': '물납영수증', 'type': 'sheet', 'sheet_name': '물납영수증'},
    {'key': 'dl_inspection', 'label': '검수내역서', 'type': 'sheet', 'sheet_name': '검수내역서'},
    {'key': 'dl_confirm', 'label': '물납확인서', 'type': 'sheet', 'sheet_name': '물납확인서'},
    {'key': 'dl_photos', 'label': '사진대지', 'type': 'sheet', 'sheet_name': '사진대지'},
    {'key': 'biz_registration', 'label': '사업자등록증', 'type': 'common',
     'path': 'documents/common/biz_registration.pdf'},
]

HIDDEN_SHEETS = {
    'commencement': {'환경설정', 'data'},
    'delivery': {'데이터', '기초 자료 입력'},
}

DEFAULT_COMMENCEMENT_ORDER = [item['key'] for item in COMMENCEMENT_ITEMS]
DEFAULT_DELIVERY_ORDER = [item['key'] for item in DELIVERY_ITEMS]


def get_available_items(doc_type='commencement'):
    return DELIVERY_ITEMS if doc_type == 'delivery' else COMMENCEMENT_ITEMS


def get_default_order(doc_type='commencement'):
    return DEFAULT_DELIVERY_ORDER[:] if doc_type == 'delivery' else DEFAULT_COMMENCEMENT_ORDER[:]


def _set_sheet_visibility(xlsx_bytes, visible_names, always_hidden):
    """workbook.xml에서 시트 visibility 설정."""
    visible_set = set(visible_names) - always_hidden

    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), 'r') as zin:
        wb_xml = zin.read('xl/workbook.xml').decode('utf-8')

        def _replace(m):
            tag = m.group(0)
            name_m = re.search(r'name="([^"]*)"', tag)
            if not name_m:
                return tag
            name = name_m.group(1)
            new_state = 'visible' if name in visible_set else 'veryHidden'
            return re.sub(r'state="[^"]*"', f'state="{new_state}"', tag)

        wb_xml = re.sub(r'<sheet [^/]*/>', _replace, wb_xml)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == 'xl/workbook.xml':
                    zout.writestr(item, wb_xml.encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item.filename))
        return buf.getvalue()


def _convert_to_pdf(xlsx_bytes, label='doc'):
    """xlsx bytes → PDF bytes via ONLYOFFICE."""
    temp_dir = '/web/light_sync/static/documents/temp'
    os.makedirs(temp_dir, exist_ok=True)
    fname = f'_asm_{int(time.time())}_{abs(hash(label)) % 9999}.xlsx'
    temp_path = os.path.join(temp_dir, fname)

    try:
        with open(temp_path, 'wb') as f:
            f.write(xlsx_bytes)

        url = f'http://host.internal:8501/static/documents/temp/{fname}'
        key = f'asm_{int(time.time())}_{abs(hash(label)) % 9999}'

        resp = _requests.post(ONLYOFFICE_CONVERT_URL, json={
            'async': False, 'filetype': 'xlsx', 'outputtype': 'pdf',
            'key': key, 'url': url,
            'spreadsheetLayout': {
                'ignorePrintArea': False,
                'fitToWidth': 1, 'fitToHeight': 0,
            },
        }, timeout=120)

        url_m = re.search(r'<FileUrl>(.*?)</FileUrl>', resp.text)
        if not url_m:
            raise RuntimeError(f'변환 실패: {resp.text[:200]}')

        pdf_url = url_m.group(1).replace('&amp;', '&')
        return _requests.get(pdf_url, timeout=60).content
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _strip_ws(s):
    """모든 공백 제거 (PDF 텍스트 추출 시 글자 간 공백 무시용)."""
    return re.sub(r'\s+', '', s)


def _identify_page(text):
    """페이지 텍스트로 시트 이름 식별. 공백 완전 무시."""
    if not text or len(text.strip()) < 10:
        return None

    stripped = _strip_ws(text)

    # 공정표 3종은 내용이 거의 같아서 시트 순서로 구분 (별도 처리)
    for sheet_name, keywords in SHEET_SIGNATURES:
        if sheet_name.startswith('공정표_'):
            continue  # 공정표는 아래에서 처리
        if all(_strip_ws(kw) in stripped for kw in keywords):
            return sheet_name

    # 공정표는 통합 식별
    if '공정표' in stripped or '기자재제작' in stripped:
        return '_공정표'

    return '_unknown'


def _split_pdf_by_sheet(pdf_bytes, sheet_order):
    """PDF를 시트별로 분리. 공정표는 시트 순서로 구분."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    result = {}  # sheet_name → [page, ...]
    schedule_counter = 0
    schedule_map = ['공정표_조명', '공정표_등주', '공정표_타워']

    for page in reader.pages:
        text = (page.extract_text() or '').strip()
        sheet_id = _identify_page(text)

        if sheet_id is None:
            continue  # 빈 페이지 건너뛰기

        if sheet_id == '_공정표':
            if schedule_counter < len(schedule_map):
                sheet_id = schedule_map[schedule_counter]
                schedule_counter += 1
            else:
                continue

        if sheet_id == '_unknown':
            # 미식별 페이지는 직전 시트에 추가 (다중 페이지 시트)
            if result:
                last_key = list(result.keys())[-1]
                result[last_key].append(page)
            continue

        if sheet_id not in result:
            result[sheet_id] = []
        result[sheet_id].append(page)

    return result


def assemble_package(xlsx_local_path, order_keys, doc_type='commencement',
                     drawings=None):
    """서류 패키지 조립 → 하나의 PDF."""
    items_map = {item['key']: item for item in get_available_items(doc_type)}
    hidden = HIDDEN_SHEETS.get(doc_type, set())
    writer = PdfWriter()

    # 1. 필요한 시트 목록 수집
    needed_sheets = []
    for key in order_keys:
        item = items_map.get(key)
        if item and item['type'] == 'sheet':
            needed_sheets.append(item['sheet_name'])

    # 2. ONLYOFFICE 한 번 변환 → 시트별 분리
    sheet_pages = {}
    if needed_sheets and os.path.exists(xlsx_local_path):
        with open(xlsx_local_path, 'rb') as f:
            xlsx = f.read()

        modified = _set_sheet_visibility(xlsx, needed_sheets, hidden)
        logger.info("변환: %d개 시트", len(needed_sheets))

        pdf_bytes = _convert_to_pdf(modified, doc_type)
        sheet_pages = _split_pdf_by_sheet(pdf_bytes, needed_sheets)
        logger.info("분리 완료: %s", {k: len(v) for k, v in sheet_pages.items()})

    # 3. 사용자 순서대로 조립
    for key in order_keys:
        item = items_map.get(key)
        if not item:
            continue

        if item['type'] == 'sheet':
            pages = sheet_pages.get(item['sheet_name'], [])
            for p in pages:
                writer.add_page(p)
            if pages:
                logger.info("  + %s (%d쪽)", item['label'], len(pages))

        elif item['type'] == 'common':
            pdf_data = download_bytes(item.get('path', ''))
            if pdf_data:
                reader = PdfReader(io.BytesIO(pdf_data))
                for p in reader.pages:
                    writer.add_page(p)
                logger.info("  + %s (%d쪽)", item['label'], len(reader.pages))
            else:
                logger.warning("  ! %s 없음", item['label'])

        elif item['type'] == 'drawing' and drawings:
            for drw in drawings:
                reader = PdfReader(io.BytesIO(drw))
                for p in reader.pages:
                    writer.add_page(p)
            logger.info("  + 도면 %d건", len(drawings))

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    logger.info("패키지 완료: 총 %d쪽", len(writer.pages))
    return buf.getvalue()
