"""
견적서 PDF 생성 모듈.

reportlab 사용, 한글 지원 (시스템 폰트 자동 탐색).
매그나텍 견적서 양식 기반.
"""

import io
import logging
from datetime import date

logger = logging.getLogger(__name__)

COMPANY_NAME = '(주)매그나텍'
COMPANY_BIZ_NO = '408-81-68519'
COMPANY_TEL = '061-392-5508'
COMPANY_FAX = '061-392-5518'
COMPANY_EMAIL = 'sales@mgnt.kr'
COMPANY_HOMEPAGE = 'www.magnatech.co.kr'
COMPANY_ADDR = '전남광주 장성군 동화면 전자농공단지2길 55'
COMPANY_CEO = '박선후 / 대표이사'


def _find_korean_font():
    """한글 지원 폰트 경로를 찾는다."""
    import os
    candidates = [
        r'C:\Windows\Fonts\malgun.ttf',
        r'C:\Windows\Fonts\malgunbd.ttf',
        r'C:\Windows\Fonts\NanumGothic.ttf',
        r'C:\Windows\Fonts\gulim.ttc',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _truncate(text, font_name, font_size, max_width, canvas_obj):
    """텍스트가 max_width를 초과하면 잘라서 '..' 붙인다."""
    if not text:
        return ''
    tw = canvas_obj.stringWidth(text, font_name, font_size)
    if tw <= max_width:
        return text
    while len(text) > 1 and canvas_obj.stringWidth(text + '..', font_name, font_size) > max_width:
        text = text[:-1]
    return text + '..'


def generate_quote_pdf(quotation, items, creator=None):
    """견적서 PDF를 생성한다. (매그나텍 양식)"""
    import os
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = _find_korean_font()
    fn = 'Helvetica'
    fn_bold = 'Helvetica-Bold'
    if font_path:
        try:
            if 'KoreanFont' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('KoreanFont', font_path))
            fn = 'KoreanFont'
            bold_path = font_path.replace('malgun.ttf', 'malgunbd.ttf')
            if os.path.exists(bold_path) and bold_path != font_path:
                if 'KoreanFontBold' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('KoreanFontBold', bold_path))
                fn_bold = 'KoreanFontBold'
            else:
                fn_bold = fn
        except Exception as e:
            logger.warning("한글 폰트 등록 실패: %s", e)
            fn_bold = fn

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    ml = 20 * mm
    mr = 20 * mm
    uw = w - ml - mr

    y = h - 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 22)
    c.drawCentredString(w / 2, y, '견  적  서')
    y -= 12 * mm

    # ── 견적일 ──
    c.setFont(fn, 10)
    quote_date_str = quotation.quote_date.strftime('%Y년 %m월 %d일') if isinstance(quotation.quote_date, date) else str(quotation.quote_date)
    c.drawString(ml, y, f'견적일 : {quote_date_str}')
    y -= 7 * mm

    # ── 메타정보 (좌: 사업자등록번호/견적서NO, 우: 납기일/대금지불/견적유효/계좌번호) ──
    col_mid = w / 2
    meta_y = y

    c.setFont(fn, 9)
    c.drawString(ml, meta_y, f'사업자등록번호 {COMPANY_BIZ_NO}')
    c.drawString(col_mid + 5 * mm, meta_y, f'납기일')
    c.drawString(col_mid + 25 * mm, meta_y, quotation.delivery_date or '협의')
    meta_y -= 5 * mm

    c.drawString(ml, meta_y, f'견적서 NO.  {quotation.quote_no}')
    c.drawString(col_mid + 5 * mm, meta_y, f'대금지불')
    c.drawString(col_mid + 25 * mm, meta_y, quotation.payment_method or '현금')
    meta_y -= 5 * mm

    c.drawString(col_mid + 5 * mm, meta_y, f'견적유효')
    c.drawString(col_mid + 25 * mm, meta_y, quotation.validity_period or '견적일로부터 1개월')
    meta_y -= 5 * mm

    c.drawString(col_mid + 5 * mm, meta_y, f'계좌번호')
    c.drawString(col_mid + 25 * mm, meta_y, quotation.bank_account or '')

    y = meta_y - 8 * mm

    # ── 구분선 ──
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(ml, y, w - mr, y)
    y -= 6 * mm

    # ── 공급자 / 수급자 정보 (2컬럼) ──
    left_x = ml
    right_x = col_mid + 5 * mm
    info_y = y

    # 공급자 (왼쪽)
    c.setFont(fn_bold, 10)
    c.drawString(left_x, info_y, '공급자')
    c.setFont(fn, 9)
    c.drawString(left_x + 20 * mm, info_y, COMPANY_NAME)

    # 수급자 (오른쪽)
    c.setFont(fn_bold, 10)
    c.drawString(right_x, info_y, '수급자')
    c.setFont(fn, 9)
    c.drawString(right_x + 20 * mm, info_y, quotation.customer_name or '')
    info_y -= 5 * mm

    # 건명 (오른쪽)
    c.setFont(fn_bold, 10)
    c.drawString(right_x, info_y, '건  명')
    c.setFont(fn, 8)
    project_name = quotation.project_name or ''
    project_name = _truncate(project_name, fn, 8, 60 * mm, c)
    c.drawString(right_x + 20 * mm, info_y, project_name)
    info_y -= 5 * mm

    # 담당자
    c.setFont(fn, 9)
    c.drawString(left_x, info_y, '담당자')
    # 공급자 담당자: 이름 직급
    creator_text = ''
    if creator:
        creator_text = creator.full_name or ''
        if creator.position:
            creator_text += f' {creator.position}'
    c.drawString(left_x + 20 * mm, info_y, creator_text)
    c.drawString(right_x, info_y, '담당자')
    c.drawString(right_x + 20 * mm, info_y, quotation.customer_contact or '')
    info_y -= 5 * mm

    # 주소
    c.drawString(left_x, info_y, '주소')
    c.setFont(fn, 8)
    c.drawString(left_x + 20 * mm, info_y, COMPANY_ADDR)
    c.setFont(fn, 9)
    c.drawString(right_x, info_y, '주소')
    c.setFont(fn, 8)
    cust_addr = _truncate(quotation.customer_address or '', fn, 8, 55 * mm, c)
    c.drawString(right_x + 20 * mm, info_y, cust_addr)
    info_y -= 5 * mm

    # Tel
    c.setFont(fn, 9)
    c.drawString(left_x, info_y, 'Tel')
    c.drawString(left_x + 20 * mm, info_y, COMPANY_TEL)
    c.drawString(right_x, info_y, 'Tel')
    c.drawString(right_x + 20 * mm, info_y, quotation.customer_tel or '')
    info_y -= 5 * mm

    # Fax
    c.drawString(left_x, info_y, 'Fax')
    c.drawString(left_x + 20 * mm, info_y, COMPANY_FAX)
    c.drawString(right_x, info_y, 'Fax')
    c.drawString(right_x + 20 * mm, info_y, quotation.customer_fax or '')
    info_y -= 5 * mm

    # E-mail
    c.drawString(left_x, info_y, 'E-mail')
    c.drawString(left_x + 20 * mm, info_y, COMPANY_EMAIL)
    c.drawString(right_x, info_y, 'E-mail')
    c.drawString(right_x + 20 * mm, info_y, quotation.customer_email or '')
    info_y -= 5 * mm

    # Homepage
    c.drawString(left_x, info_y, 'Homepage')
    c.drawString(left_x + 20 * mm, info_y, COMPANY_HOMEPAGE)
    c.drawString(right_x, info_y, 'Homepage')

    y = info_y - 6 * mm

    # ── (단위 : 원) ──
    c.setFont(fn, 8)
    c.drawRightString(w - mr, y + 2 * mm, '(단위 : 원)')

    # ── 품목 테이블 ──
    # No(5%), 품명(25%), 규격(15%), 단위(6%), 수량(7%), 단가(15%), 금액(17%), 비고(10%)
    col_pcts = [0.05, 0.25, 0.15, 0.06, 0.07, 0.14, 0.17, 0.11]
    col_w = [uw * p for p in col_pcts]
    headers = ['NO', '품명', '규격', '단위', '수량', '단 가', '금액', '비고']
    row_h = 7 * mm

    def draw_table_header(y_pos):
        c.setFillColor(colors.Color(0.2, 0.3, 0.5))
        c.rect(ml, y_pos - row_h, uw, row_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(fn_bold, 8)
        x = ml
        for i, hdr in enumerate(headers):
            c.drawCentredString(x + col_w[i] / 2, y_pos - row_h + 2 * mm, hdr)
            x += col_w[i]
        c.setFillColor(colors.black)
        return y_pos - row_h

    y = draw_table_header(y)

    # 테이블 행
    for idx, item in enumerate(items, 1):
        if y - row_h < 40 * mm:
            c.showPage()
            y = h - 25 * mm
            y = draw_table_header(y)

        # 짝수행 배경
        if idx % 2 == 0:
            c.setFillColor(colors.Color(0.96, 0.96, 0.96))
            c.rect(ml, y - row_h, uw, row_h, fill=1, stroke=0)
            c.setFillColor(colors.black)

        # 행 테두리
        c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
        c.setLineWidth(0.3)
        c.line(ml, y - row_h, ml + uw, y - row_h)

        # 세로 구분선
        x = ml
        for cwidth in col_w[:-1]:
            x += cwidth
            c.line(x, y, x, y - row_h)

        c.setStrokeColor(colors.black)
        c.setFont(fn, 8)
        text_y = y - row_h + 2 * mm

        x = ml
        # No
        c.drawCentredString(x + col_w[0] / 2, text_y, str(idx))
        x += col_w[0]

        # 품명
        name = _truncate(item.item_name or '', fn, 8, col_w[1] - 2 * mm, c)
        c.drawString(x + 1 * mm, text_y, name)
        x += col_w[1]

        # 규격
        spec = _truncate(item.item_spec or '', fn, 8, col_w[2] - 2 * mm, c)
        c.drawString(x + 1 * mm, text_y, spec)
        x += col_w[2]

        # 단위
        c.drawCentredString(x + col_w[3] / 2, text_y, item.unit or '')
        x += col_w[3]

        # 수량
        c.drawCentredString(x + col_w[4] / 2, text_y, f'{item.quantity:,.0f}')
        x += col_w[4]

        # 단가
        c.drawRightString(x + col_w[5] - 1.5 * mm, text_y, f'{item.unit_price:,.0f}')
        x += col_w[5]

        # 금액
        c.setFont(fn_bold, 8)
        c.drawRightString(x + col_w[6] - 1.5 * mm, text_y, f'{item.amount:,.0f}')
        x += col_w[6]

        # 비고
        c.setFont(fn, 7)
        note_text = _truncate(item.note or '', fn, 7, col_w[7] - 2 * mm, c)
        c.drawString(x + 1 * mm, text_y, note_text)

        y -= row_h

    # 테이블 하단선
    c.setStrokeColor(colors.Color(0.2, 0.3, 0.5))
    c.setLineWidth(0.8)
    c.line(ml, y, ml + uw, y)

    # ── 합계 영역 ──
    y -= 6 * mm
    supply_total = sum(i.amount for i in items)

    # 공급가액
    c.setFont(fn, 10)
    c.drawString(ml, y, '공급가액')
    c.drawRightString(w - mr, y, f'{supply_total:,.0f}')
    y -= 5 * mm

    # 부과금 (부가세, 이윤 등)
    import json as _json
    surcharges = []
    try:
        surcharges = _json.loads(quotation.surcharges_json or '[]')
    except Exception:
        pass

    grand_total = supply_total
    for sc in surcharges:
        sc_name = sc.get('name', '')
        sc_rate = sc.get('rate', 0)
        sc_amount = sc.get('amount', 0)
        c.setFont(fn, 10)
        c.drawString(ml, y, f'{sc_name} ({sc_rate}%)')
        c.drawRightString(w - mr, y, f'{sc_amount:,.0f}')
        grand_total += sc_amount
        y -= 5 * mm

    # 합계선
    y -= 2 * mm
    c.setStrokeColor(colors.Color(0.2, 0.3, 0.5))
    c.setLineWidth(1.0)
    c.line(ml, y, w - mr, y)
    y -= 7 * mm

    c.setFont(fn_bold, 14)
    c.drawString(ml, y, '합    계')
    c.drawRightString(w - mr, y, f'{grand_total:,.0f}')

    # ── 비고 + 서명 ──
    y -= 12 * mm
    c.setFont(fn_bold, 9)
    c.drawString(ml, y, '[비고]')

    # 비고 내용
    note_lines = []
    if not quotation.tax_included and not any(s.get('name', '') == '부가세' for s in surcharges):
        note_lines.append('-.부가세 별도가')
    note_lines.append('-.견적 외 추가비용 별도')
    note_lines.append('-.납품은 현장 준공일정에 따름')
    if quotation.note:
        for line in quotation.note.split('\n'):
            note_lines.append(f'-.{line.strip()}')

    c.setFont(fn, 9)
    note_start_y = y - 5 * mm
    for line in note_lines:
        c.drawString(ml, note_start_y, line)
        note_start_y -= 5 * mm

    # 서명 (오른쪽)
    sig_x = w - mr - 50 * mm
    sig_y = y - 5 * mm
    c.setFont(fn_bold, 10)
    c.drawString(sig_x, sig_y, '매그나텍 주식회사')
    sig_y -= 6 * mm
    c.setFont(fn, 10)
    c.drawString(sig_x, sig_y, COMPANY_CEO)

    # ── 하단 회사 정보 ──
    footer_y = 12 * mm
    c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
    c.setLineWidth(0.3)
    c.line(ml, footer_y + 3 * mm, w - mr, footer_y + 3 * mm)
    c.setFont(fn, 8)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawCentredString(w / 2, footer_y,
                        f'{COMPANY_NAME}  |  {COMPANY_ADDR}  |  TEL {COMPANY_TEL}  |  FAX {COMPANY_FAX}')

    c.save()
    return buf.getvalue()
