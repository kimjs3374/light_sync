"""
발주서 PDF 생성 모듈.

reportlab 사용, 한글 지원 (시스템 폰트 자동 탐색).
"""

import io
import os
import logging
from datetime import date

logger = logging.getLogger(__name__)

COMPANY_NAME = '(주)매그나텍'
COMPANY_TEL = '061-392-5508'
COMPANY_FAX = '061-392-5518'
COMPANY_EMAIL = 'purchase@mgnt.kr'
COMPANY_ADDR = '전라남도 장성군 동화면 전자농공단지2길 55'


def _find_korean_font():
    """한글 지원 폰트 경로를 찾는다."""
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


def generate_po_pdf(po, vendor, items):
    """발주서 PDF를 생성한다."""
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
            # Bold 폰트 탐색
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
    ml = 20 * mm  # margin left
    mr = 20 * mm  # margin right
    uw = w - ml - mr  # usable width

    y = h - 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 22)
    c.drawCentredString(w / 2, y, '발  주  서')
    y -= 12 * mm

    # ── 발주번호 / 날짜 ──
    c.setFont(fn, 10)
    po_date_str = po.po_date.strftime('%Y년 %m월 %d일') if isinstance(po.po_date, date) else str(po.po_date)
    c.drawString(ml, y, f'발주번호: {po.po_no}')
    c.drawRightString(w - mr, y, f'발주일자: {po_date_str}')
    y -= 10 * mm

    # ── 구분선 ──
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(ml, y, w - mr, y)
    y -= 8 * mm

    # ── 수신/발신 정보 (2컬럼 레이아웃) ──
    col_mid = w / 2

    # 수신 (왼쪽)
    c.setFont(fn_bold, 10)
    c.drawString(ml, y, '[ 수  신 ]')
    c.setFont(fn, 9)
    y -= 6 * mm
    c.drawString(ml + 2 * mm, y, f'업체명 : {vendor.name}')
    y -= 5 * mm
    c.drawString(ml + 2 * mm, y, f'TEL : {vendor.tel or "-"}    FAX : {vendor.fax or "-"}')
    y -= 5 * mm
    c.drawString(ml + 2 * mm, y, f'E-mail : {vendor.email or "-"}')

    # 발신 (오른쪽, 같은 y 위치)
    ry = y + 16 * mm  # 수신 시작 y로 복원
    c.setFont(fn_bold, 10)
    c.drawString(col_mid + 5 * mm, ry, '[ 발  신 ]')
    c.setFont(fn, 9)
    ry -= 6 * mm
    c.drawString(col_mid + 7 * mm, ry, f'업체명 : {COMPANY_NAME}')
    ry -= 5 * mm
    c.drawString(col_mid + 7 * mm, ry, f'TEL : {COMPANY_TEL}  FAX : {COMPANY_FAX}')
    ry -= 5 * mm
    c.drawString(col_mid + 7 * mm, ry, f'E-mail : {COMPANY_EMAIL}')

    y -= 8 * mm

    # ── 구분선 ──
    c.setLineWidth(0.5)
    c.line(ml, y, w - mr, y)
    y -= 6 * mm

    # ── 안내 문구 ──
    c.setFont(fn, 10)
    c.drawString(ml, y, '아래와 같이 발주하오니 납기일을 준수하여 주시기 바랍니다.')
    y -= 8 * mm

    # ── 품목 테이블 ──
    # 컬럼: No(7%), 품명/규격(38%), 수량(10%), 단위(7%), 단가(13%), 금액(15%), 비고(10%)
    col_pcts = [0.06, 0.38, 0.09, 0.07, 0.13, 0.15, 0.12]
    col_w = [uw * p for p in col_pcts]
    headers = ['No', '품명 / 규격', '수량', '단위', '단가', '금액', '비고']
    row_h = 7 * mm

    def draw_table_header(y_pos):
        """테이블 헤더를 그린다."""
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
        if y - row_h < 35 * mm:
            c.showPage()
            y = h - 25 * mm
            y = draw_table_header(y)

        # 짝수행 배경
        if idx % 2 == 0:
            c.setFillColor(colors.Color(0.96, 0.96, 0.96))
            c.rect(ml, y - row_h, uw, row_h, fill=1, stroke=0)
            c.setFillColor(colors.black)

        # 행 테두리 (얇은 선)
        c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
        c.setLineWidth(0.3)
        c.line(ml, y - row_h, ml + uw, y - row_h)

        # 세로 구분선
        x = ml
        for cw in col_w[:-1]:
            x += cw
            c.line(x, y, x, y - row_h)

        c.setStrokeColor(colors.black)
        c.setFont(fn, 8)
        text_y = y - row_h + 2 * mm

        x = ml
        # No
        c.drawCentredString(x + col_w[0] / 2, text_y, str(idx))
        x += col_w[0]

        # 품명/규격
        name_spec = item.item_name or ''
        if item.item_spec:
            name_spec += f'  {item.item_spec}'
        name_spec = _truncate(name_spec, fn, 8, col_w[1] - 2 * mm, c)
        c.drawString(x + 1 * mm, text_y, name_spec)
        x += col_w[1]

        # 수량
        c.drawRightString(x + col_w[2] - 1.5 * mm, text_y, f'{item.quantity:,.0f}')
        x += col_w[2]

        # 단위
        c.drawCentredString(x + col_w[3] / 2, text_y, item.unit or '')
        x += col_w[3]

        # 단가
        c.drawRightString(x + col_w[4] - 1.5 * mm, text_y, f'{item.unit_price:,.0f}')
        x += col_w[4]

        # 금액
        c.setFont(fn_bold, 8)
        c.drawRightString(x + col_w[5] - 1.5 * mm, text_y, f'{item.amount:,.0f}')
        x += col_w[5]

        # 비고
        c.setFont(fn, 7)
        note_text = _truncate(item.note or '', fn, 7, col_w[6] - 2 * mm, c)
        c.drawString(x + 1 * mm, text_y, note_text)

        y -= row_h

    # 테이블 외곽 테두리
    table_top = y + row_h * len(items)
    # 재계산이 복잡하므로 하단선만 그음
    c.setStrokeColor(colors.Color(0.2, 0.3, 0.5))
    c.setLineWidth(0.8)
    c.line(ml, y, ml + uw, y)

    # ── 합계 영역 ──
    y -= 5 * mm
    supply_total = sum(i.amount for i in items)
    tax_total = po.tax_amount or 0
    grand_total = supply_total + tax_total

    # 합계 박스 (오른쪽 정렬)
    box_w = 75 * mm
    box_x = w - mr - box_w
    box_h = 22 * mm

    c.setStrokeColor(colors.Color(0.2, 0.3, 0.5))
    c.setLineWidth(0.5)
    c.rect(box_x, y - box_h, box_w, box_h, fill=0, stroke=1)

    c.setFont(fn, 10)
    ly = y - 6 * mm
    c.drawString(box_x + 3 * mm, ly, '공급가액')
    c.drawRightString(box_x + box_w - 3 * mm, ly, f'{supply_total:>12,.0f} 원')
    ly -= 6 * mm
    c.drawString(box_x + 3 * mm, ly, '부 가 세')
    c.drawRightString(box_x + box_w - 3 * mm, ly, f'{tax_total:>12,.0f} 원')
    ly -= 1.5 * mm
    c.setLineWidth(0.3)
    c.line(box_x + 2 * mm, ly, box_x + box_w - 2 * mm, ly)
    ly -= 5.5 * mm
    c.setFont(fn_bold, 12)
    c.drawString(box_x + 3 * mm, ly, '합    계')
    c.drawRightString(box_x + box_w - 3 * mm, ly, f'{grand_total:>12,.0f} 원')

    y -= box_h + 5 * mm

    # ── 비고 ──
    if po.note:
        c.setFont(fn, 9)
        c.drawString(ml, y, f'* 비고: {po.note}')
        y -= 8 * mm

    # ── 하단 회사 정보 (페이지 맨 아래 고정) ──
    footer_y = 12 * mm
    c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
    c.setLineWidth(0.3)
    c.line(ml, footer_y + 3 * mm, w - mr, footer_y + 3 * mm)
    c.setFont(fn, 8)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawCentredString(w / 2, footer_y, f'{COMPANY_NAME}  |  {COMPANY_ADDR}  |  TEL {COMPANY_TEL}  |  FAX {COMPANY_FAX}')

    c.save()
    return buf.getvalue()
