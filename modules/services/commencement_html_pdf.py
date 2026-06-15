"""
착수계 PDF 생성 모듈 (HTML 템플릿 방식).

3개 HTML 페이지(공문, 착수계, 현장대리인계)를 Chrome headless로 PDF 변환 후
첨부서류와 합쳐서 하나의 PDF로 생성합니다.
"""

import io
import os
import base64
import logging
from datetime import date

from jinja2 import Template as J2Template

from modules.services.commencement_pdf import number_to_korean
from modules.services.html_to_pdf import html_to_pdf

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'templates')
IMAGES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'images', 'company')

# Supabase 공통 서류 경로
COMMON_DOCS_PREFIX = 'documents/common/'
DRAWINGS_PREFIX = 'documents/drawings/'
COMMON_DOC_FILES = {
    'biz_registration': 'biz_registration.pdf',
    'factory_cert': 'factory_cert.pdf',
    'direct_production_light': 'direct_production_light.pdf',
    'direct_production_pole': 'direct_production_pole.pdf',
    'direct_production_tower': 'direct_production_tower.pdf',
}


def _img_to_data_uri(filepath):
    """이미지 파일을 data URI로 변환."""
    if not os.path.exists(filepath):
        return ''
    with open(filepath, 'rb') as f:
        data = f.read()
    ext = os.path.splitext(filepath)[1].lower()
    mime = 'image/png' if ext == '.png' else 'image/jpeg'
    b64 = base64.b64encode(data).decode('ascii')
    return f'data:{mime};base64,{b64}'


def _fmt_date_kr(d):
    """날짜를 '2026년 03월 26일' 형식으로."""
    if not d:
        return ''
    if isinstance(d, str):
        from datetime import date as _date
        d = _date.fromisoformat(d)
    return f'{d.year}년 {d.month:02d}월 {d.day:02d}일'


def _fmt_date_dot(d):
    """날짜를 '2026. 03. 26.' 형식으로."""
    if not d:
        return ''
    if isinstance(d, str):
        from datetime import date as _date
        d = _date.fromisoformat(d)
    return f'{d.year}. {d.month:02d}. {d.day:02d}.'


def _space_name(name):
    """'최한진' → '최  한  진'"""
    if not name:
        return ''
    return '  '.join(name)


def _render_template(template_name, context):
    """템플릿 파일을 렌더링하여 HTML 문자열 반환."""
    tpl_path = os.path.join(TEMPLATES_DIR, template_name)
    with open(tpl_path, encoding='utf-8') as f:
        tpl = J2Template(f.read())
    return tpl.render(**context)


def generate_commencement_html_pdf(package, procurements, agent_user=None,
                                    attachments=None):
    """
    착수계 PDF를 HTML 템플릿 기반으로 생성합니다.

    Returns:
        io.BytesIO: PDF 바이트 스트림
    """
    import pypdf

    # ── 공통 데이터 추출 ──
    business_name = package.business_name or ''
    demand_org = package.demand_org or ''
    org_type = package.org_type or '청'
    commencement_date = package.commencement_date or date.today()

    contract_date = package.contract_date
    delivery_due = None
    if procurements:
        if not contract_date:
            contract_date = procurements[0].pdf_contract_date or procurements[0].cntrct_dlvr_req_date
        delivery_due = procurements[0].dlvr_tmlmt_date

    # 금액 계산
    total_supply = sum((p.prdct_uprc or 0) * (p.prdct_qty or 0) for p in procurements)
    amount_korean = f'일금 {number_to_korean(total_supply)} 원정'
    amount_formatted = f'{total_supply:,.0f}'

    # 이미지 data URI
    logo_uri = _img_to_data_uri(os.path.join(IMAGES_DIR, 'logo.png'))
    stamp_uri = _img_to_data_uri(os.path.join(IMAGES_DIR, 'stamp.png'))
    square_stamp_uri = _img_to_data_uri(os.path.join(IMAGES_DIR, 'square stamp.png'))

    # 관청구분
    org_greeting = '귀 청' if org_type == '청' else '귀 기관'

    # 현장대리인 정보
    agent_name = ''
    agent_position = ''
    agent_address = ''
    agent_birth_str = ''
    if agent_user:
        agent_name = _space_name(agent_user.full_name)
        agent_position = agent_user.position or ''
        agent_address = agent_user.address or ''
        agent_birth_str = _fmt_date_kr(agent_user.birth_date)

    # ── 1. 공문 PDF ──
    letter_html = _render_template('official_letter.html', {
        'doc_number': package.commencement_doc_no or '',
        'submit_date': _fmt_date_dot(commencement_date),
        'recipient': demand_org,
        'business_name': business_name,
        'req_no': f'{package.procurement_req_no}-00',
        'org_type_greeting': org_greeting,
        'doc_type': '착수계',
        'stamp_url': square_stamp_uri,
    })
    letter_pdf = html_to_pdf(letter_html)

    # ── 2. 착수계 본문 PDF ──
    body_html = _render_template('commencement_body.html', {
        'business_name': business_name,
        'amount_korean': amount_korean,
        'amount_formatted': amount_formatted,
        'contract_date_str': _fmt_date_kr(contract_date),
        'commencement_date_str': _fmt_date_kr(commencement_date),
        'delivery_due_str': _fmt_date_kr(delivery_due),
        'delivery_deadline_str': _fmt_date_kr(delivery_due),
        'demand_org': demand_org,
        'logo_url': logo_uri,
        'stamp_url': stamp_uri,
    })
    body_pdf = html_to_pdf(body_html)

    # ── 3. 현장대리인계 PDF ──
    agent_pdf = None
    if agent_user:
        agent_html = _render_template('agent_appointment.html', {
            'business_name': business_name,
            'agent_name_spaced': agent_name,
            'agent_position': agent_position,
            'agent_address': agent_address,
            'agent_birth_str': agent_birth_str,
            'submit_date_str': _fmt_date_kr(commencement_date),
            'delivery_due_str': _fmt_date_kr(delivery_due),
            'demand_org': demand_org,
            'logo_url': logo_uri,
            'stamp_url': stamp_uri,
        })
        agent_pdf = html_to_pdf(agent_html)

    # ── PDF 합치기 ──
    writer = pypdf.PdfWriter()

    def _add_pdf_bytes(pdf_bytes):
        if not pdf_bytes:
            return
        try:
            r = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in r.pages:
                writer.add_page(page)
        except Exception as e:
            logger.warning("PDF 바이트 읽기 실패: %s", e)

    def _add_supabase_pdf(storage_path):
        from modules.storage_adapter import download_bytes as dl_bytes
        pdf_bytes = dl_bytes(storage_path)
        _add_pdf_bytes(pdf_bytes)

    def _add_common_doc(doc_key):
        filename = COMMON_DOC_FILES.get(doc_key)
        if filename:
            _add_supabase_pdf(COMMON_DOCS_PREFIX + filename)

    def _add_attachment_pdf(file_type):
        if not attachments:
            return
        for att in attachments:
            if att.file_type == file_type and att.storage_path:
                if att.storage_path.startswith('documents/'):
                    _add_supabase_pdf(att.storage_path)
                else:
                    base = os.path.join(os.path.dirname(__file__), '..', '..')
                    fpath = os.path.join(base, att.storage_path)
                    if os.path.exists(fpath):
                        try:
                            r = pypdf.PdfReader(fpath)
                            for page in r.pages:
                                writer.add_page(page)
                        except Exception as e:
                            logger.warning("첨부 PDF 읽기 실패: %s", e)

    # 품목 모델 판별
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
        items.append({'model': model})

    first_model_upper = (items[0]['model'] if items else '').upper()

    # ═══ 붙임 순서 ═══
    # 1. 공문
    _add_pdf_bytes(letter_pdf)

    # 2. 착수계
    _add_pdf_bytes(body_pdf)

    # 3. 사업자등록증
    _add_common_doc('biz_registration')

    # 4-5. 납세증명서
    _add_attachment_pdf('tax_cert_national')
    _add_attachment_pdf('tax_cert_local')

    # 6. 공장등록증명서
    _add_common_doc('factory_cert')

    # 7. 직접생산확인증명서
    if 'MTT' in first_model_upper:
        _add_common_doc('direct_production_tower')
    elif 'MTPF' in first_model_upper or 'MTPS' in first_model_upper:
        _add_common_doc('direct_production_pole')
    else:
        _add_common_doc('direct_production_light')

    # 8. 현장대리인계
    if agent_pdf:
        _add_pdf_bytes(agent_pdf)

    # 9. 재직증명서 — 엑셀 기반(기존 방식 유지 필요 시 여기에 추가)
    # TODO: 재직증명서 HTML 템플릿 생성 시 교체

    # 10. 물품계약서 (업로드한 납품요구서 PDF)
    if package.req_pdf_path:
        req_path = package.req_pdf_path
        if not os.path.isabs(req_path):
            req_path = os.path.join(os.path.dirname(__file__), '..', '..', req_path)
        if os.path.exists(req_path):
            try:
                r = pypdf.PdfReader(req_path)
                for page in r.pages:
                    writer.add_page(page)
            except Exception as e:
                logger.warning("납품요구서 PDF 읽기 실패: %s", e)

    # 11. 예정공정표 — 엑셀 기반(기존 유지)
    # TODO: 공정표 HTML 템플릿 생성 시 교체

    # 12. 납품내역서 — 엑셀 기반(기존 유지)
    # TODO: 납품내역서 HTML 템플릿 생성 시 교체

    # 13. 제작도면
    for it in items:
        if it['model']:
            _add_supabase_pdf(DRAWINGS_PREFIX + it['model'] + '.pdf')

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)

    logger.info("착수계 HTML PDF 생성 완료: %s (%d pages, %d bytes)",
                business_name, len(writer.pages), buf.getbuffer().nbytes)
    return buf
