"""
발주서 PDF 생성 모듈.

reportlab 사용, 한글 지원 (시스템 폰트 자동 탐색).
가로 A4, 참고 양식 기반.
"""

import io
import os
import logging
from datetime import date

logger = logging.getLogger(__name__)

COMPANY_NAME = '(주)매그나텍'
COMPANY_CEO = '박선후'
COMPANY_TEL = '061)392-5508'
COMPANY_FAX = '061)392-5518'
COMPANY_ADDR_1 = '전남광주 장성군 동화면 전자농공단지2길'
COMPANY_ADDR_2 = '55 (동화 전자농공단지내)'


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


def _wrap_text(text, font_name, font_size, max_width, canvas_obj):
    """텍스트를 max_width에 맞게 줄바꿈한다. 한글은 글자 단위, 영문은 공백 단위 우선."""
    if not text:
        return []
    lines = []
    for raw_line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if not raw_line:
            lines.append('')
            continue
        cur = ''
        for ch in raw_line:
            test = cur + ch
            if canvas_obj.stringWidth(test, font_name, font_size) <= max_width:
                cur = test
            else:
                if cur:
                    # 공백이 있다면 마지막 공백에서 끊기 시도 (영문 가독성)
                    if ' ' in cur and ch != ' ':
                        sp = cur.rfind(' ')
                        if sp > 0 and sp >= len(cur) - 20:
                            lines.append(cur[:sp])
                            cur = cur[sp + 1:] + ch
                            continue
                    lines.append(cur)
                    cur = ch
                else:
                    lines.append(ch)
                    cur = ''
        if cur:
            lines.append(cur)
    return lines


def _fmt_num(val):
    """숫자 포맷: 소수점 2자리."""
    if val is None:
        return '0.00'
    return f'{val:,.2f}'


def generate_po_pdf(po, vendor, items):
    """발주서 PDF를 생성한다."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as canvas_mod
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

    # 색상
    HDR_BG = colors.Color(0.2, 0.3, 0.5)          # 테이블 헤더 (짙은 남색)
    LABEL_BG = colors.Color(0.82, 0.88, 0.96)     # 하단 라벨 (연한 하늘색)
    SUBTOTAL_BG = colors.Color(1.0, 0.92, 0.82)   # 소계 (연한 주황)
    BORDER = colors.Color(0.3, 0.3, 0.6)          # 테두리
    THIN = colors.Color(0.85, 0.85, 0.85)         # 내부 얇은선

    buf = io.BytesIO()
    page = landscape(A4)
    c = canvas_mod.Canvas(buf, pagesize=page)
    w, h = page
    ml = 15 * mm
    uw = w - ml * 2  # usable width

    y = h - 18 * mm

    # ━━━ 제목 ━━━
    c.setFont(fn_bold, 20)
    title = '구 매 발 주 서'
    tw = c.stringWidth(title, fn_bold, 20)
    tx = (w - tw) / 2
    c.drawString(tx, y, title)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(tx, y - 2, tx + tw, y - 2)
    y -= 14 * mm

    # ━━━ 수신 (왼쪽) / 발신 (오른쪽) ━━━
    right_x = w / 2 + 10 * mm
    sy = y  # save start y

    # 수신: 업체명 귀중
    c.setFont(fn, 11)
    vn = vendor.name or ''
    vnw = c.stringWidth(vn, fn, 11)
    c.drawString(ml + 2 * mm, y, f'{vn}    귀중')
    line_end = ml + 2 * mm + vnw + c.stringWidth('    귀중', fn, 11) + 2 * mm
    c.setLineWidth(0.5)
    c.line(ml, y - 2, line_end, y - 2)

    y -= 6 * mm
    c.setFont(fn, 9)
    c.drawString(ml, y, f'전화번호 :  {vendor.tel or ""}')
    y -= 5 * mm
    c.drawString(ml, y, f'팩스번호 :  {vendor.fax or ""}')

    # 발신 (오른쪽, 같은 높이에서 시작)
    ry = sy
    c.setFont(fn, 9)
    c.drawString(right_x, ry, f'사 업 장 :  {COMPANY_NAME}')
    ry -= 6 * mm
    c.drawString(right_x, ry, f'대 표 자 :  {COMPANY_CEO}')
    ry -= 6 * mm
    c.drawString(right_x, ry, f'주     소 :  {COMPANY_ADDR_1}')
    ry -= 5 * mm
    indent = c.stringWidth('주     소 :  ', fn, 9)
    c.drawString(right_x + indent, ry, COMPANY_ADDR_2)
    ry -= 6 * mm
    c.drawString(right_x, ry, f'전화번호 :  {COMPANY_TEL}')
    ry -= 5 * mm
    c.drawString(right_x, ry, f'팩스번호 :  {COMPANY_FAX}')

    # 수신/발신 중 더 아래까지 내려간 y 기준
    y = min(y, ry) - 5 * mm
    c.setFont(fn, 9)
    c.drawString(ml, y, f'발주번호 :    {po.po_no or ""}')
    y -= 8 * mm

    # ━━━ 품목 테이블 ━━━
    # No(3%) 품번(12%) 품명(24%) 규격(17%) 단위(4%) 납기일(9%) 발주수량(10%) 단가(10%) 금액(11%)
    col_pcts = [0.03, 0.12, 0.24, 0.17, 0.04, 0.09, 0.10, 0.10, 0.11]
    col_w = [uw * p for p in col_pcts]
    hdrs = ['No.', '품번', '품명', '규격', '단위', '납기일', '발주수량', '단가', '금액']
    rh = 7.5 * mm

    def _cell_borders(y1, y2):
        """데이터 행 테두리 (외곽 + 세로선)."""
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(ml, y1, ml + uw, y1)
        c.line(ml, y2, ml + uw, y2)
        c.line(ml, y1, ml, y2)
        c.line(ml + uw, y1, ml + uw, y2)
        cx = ml
        for cw in col_w[:-1]:
            cx += cw
            c.setStrokeColor(THIN)
            c.setLineWidth(0.3)
            c.line(cx, y1, cx, y2)

    def _header_row(yy):
        """테이블 헤더."""
        yb = yy - rh
        c.setFillColor(HDR_BG)
        c.rect(ml, yb, uw, rh, fill=1, stroke=0)
        _cell_borders(yy, yb)
        c.setFillColor(colors.white)
        c.setFont(fn_bold, 7)
        cx = ml
        for i, h in enumerate(hdrs):
            c.drawCentredString(cx + col_w[i] / 2, yb + 1.8 * mm, h)
            cx += col_w[i]
        c.setFillColor(colors.black)
        return yb

    y = _header_row(y)

    # 데이터 행
    for idx, item in enumerate(items, 1):
        if y - rh < 45 * mm:
            c.showPage()
            y = h - 18 * mm
            y = _header_row(y)

        yt, yb = y, y - rh
        _cell_borders(yt, yb)
        c.setFont(fn, 7)
        ty = yb + 1.8 * mm
        cx = ml

        c.drawCentredString(cx + col_w[0] / 2, ty, str(idx))
        cx += col_w[0]

        c.drawString(cx + 1 * mm, ty, _truncate(item.item_code or '', fn, 7, col_w[1] - 2 * mm, c))
        cx += col_w[1]

        c.drawString(cx + 1 * mm, ty, _truncate(item.item_name or '', fn, 7, col_w[2] - 2 * mm, c))
        cx += col_w[2]

        c.drawString(cx + 1 * mm, ty, _truncate(item.item_spec or '', fn, 7, col_w[3] - 2 * mm, c))
        cx += col_w[3]

        c.drawCentredString(cx + col_w[4] / 2, ty, item.unit or '')
        cx += col_w[4]

        dlv = ''
        if hasattr(item, 'delivery_date') and item.delivery_date:
            dlv = item.delivery_date.strftime('%Y/%m/%d') if isinstance(item.delivery_date, date) else str(item.delivery_date)
        c.drawCentredString(cx + col_w[5] / 2, ty, dlv)
        cx += col_w[5]

        c.drawRightString(cx + col_w[6] - 1.5 * mm, ty, _fmt_num(item.quantity))
        cx += col_w[6]

        c.drawRightString(cx + col_w[7] - 1.5 * mm, ty, _fmt_num(item.unit_price))
        cx += col_w[7]

        c.drawRightString(cx + col_w[8] - 1.5 * mm, ty, _fmt_num(item.amount))
        y -= rh

    # 빈 행 채우기 (최소 10행)
    for _ in range(max(0, 10 - len(items))):
        if y - rh < 45 * mm:
            break
        _cell_borders(y, y - rh)
        y -= rh

    # ━━━ 소계 행 ━━━
    supply = sum(i.amount for i in items)
    qty = sum(i.quantity for i in items)
    yb = y - rh
    c.setFillColor(SUBTOTAL_BG)
    c.rect(ml, yb, uw, rh, fill=1, stroke=0)
    c.setFillColor(colors.black)
    _cell_borders(y, yb)
    c.setFont(fn_bold, 8)
    c.drawCentredString(ml + col_w[0] + col_w[1] + col_w[2] / 2, yb + 1.8 * mm, '소     계')
    c.drawRightString(ml + sum(col_w[:7]) - 1.5 * mm, yb + 1.8 * mm, _fmt_num(qty))
    c.drawRightString(ml + sum(col_w[:9]) - 1.5 * mm, yb + 1.8 * mm, _fmt_num(supply))
    y = yb

    # ━━━ 하단 정보 테이블 ━━━
    # 왼쪽: 4행 (라벨+값), 오른쪽: 합쳐진 1개 큰 셀 (금액합계)
    y -= 3 * mm
    tax = po.tax_amount or 0
    total = supply + tax
    irh = 7 * mm
    lw = 28 * mm                  # 라벨 너비
    left_val_w = uw * 0.45 - lw   # 왼쪽 값 칸 너비
    left_w = lw + left_val_w      # 왼쪽 전체 너비
    right_w = uw - left_w         # 오른쪽 큰 셀 너비

    po_dt = ''
    if po.po_date:
        po_dt = po.po_date.strftime('%Y년%m월%d일') if isinstance(po.po_date, date) else str(po.po_date)

    # 비고 줄바꿈 계산 — 행 높이를 동적으로 결정
    # PO 전체 비고 + 품목별 비고를 함께 표기
    po_note = (getattr(po, 'note', '') or '').strip()
    note_pad_x = 2 * mm
    note_line_h = 4.2 * mm
    note_max_w = left_val_w - note_pad_x * 2

    note_lines = []
    if po_note:
        note_lines.extend(_wrap_text(po_note, fn, 8, note_max_w, c))
    item_note_entries = []
    for it in items:
        it_note = (getattr(it, 'note', '') or '').strip()
        if it_note:
            it_label = (getattr(it, 'item_name', '') or getattr(it, 'item_code', '') or '').strip()
            line = f'- {it_label}: {it_note}' if it_label else f'- {it_note}'
            item_note_entries.append(line)
    if item_note_entries:
        if note_lines:
            note_lines.append('')  # 간격용 빈 줄
        for entry in item_note_entries:
            note_lines.extend(_wrap_text(entry, fn, 8, note_max_w, c))

    note_row_h = max(irh, len(note_lines) * note_line_h + 3 * mm) if note_lines else irh

    # 왼쪽 4행: 지불조건/납품장소/운반조건은 irh 고정, 비고는 가변
    left_row_heights = [irh, irh, irh, note_row_h]
    total_h = sum(left_row_heights)

    y_top = y
    y_bot = y - total_h

    # 오른쪽 큰 셀 (왼쪽 전체 높이에 맞춤) — 먼저 그리기
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.rect(ml + left_w, y_bot, right_w, total_h, fill=0, stroke=1)
    # 오른쪽 큰 셀 내용 (4등분)
    rx = ml + left_w
    sub_h = total_h / 4
    c.setFillColor(colors.black)
    c.setFont(fn, 10)
    c.drawCentredString(rx + right_w / 2, y_top - sub_h + (sub_h - 10) / 2, f'금액합계 :     {total:,.0f} 원')
    # 금액합계 아래 가로선
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(rx, y_top - sub_h, rx + right_w, y_top - sub_h)
    # 안내문구 / 날짜 / 담당자
    c.setFillColor(colors.black)
    c.setFont(fn, 8)
    c.drawCentredString(rx + right_w / 2, y_top - sub_h * 2 + (sub_h - 8) / 2,
                        '위와 같이 발주하오니 계약조건을 준수하여 납품하여 주시기 바랍니다')
    c.drawCentredString(rx + right_w / 2, y_top - sub_h * 3 + (sub_h - 8) / 2, po_dt)
    assignee_disp = ''
    if hasattr(po, 'assignee') and po.assignee:
        assignee_disp = getattr(po.assignee, 'name', '')
    c.drawCentredString(rx + right_w / 2, y_top - sub_h * 4 + (sub_h - 8) / 2, assignee_disp)

    # 왼쪽 4행 (라벨 + 값 셀)
    left_rows = [
        ('지 불 조 건', '', irh),
        ('납 품 장 소', '', irh),
        ('운 반 조 건', '', irh),
        ('비     고', po_note, note_row_h),
    ]
    cy = y_top
    for lbl, val, rh_i in left_rows:
        cyb = cy - rh_i
        # 라벨 셀
        c.setFillColor(LABEL_BG)
        c.rect(ml, cyb, lw, rh_i, fill=1, stroke=0)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.rect(ml, cyb, lw, rh_i, fill=0, stroke=1)
        c.setFillColor(colors.black)
        c.setFont(fn_bold, 8)
        c.drawCentredString(ml + lw / 2, cyb + rh_i / 2 - 2.5, lbl)
        # 값 셀
        c.setStrokeColor(BORDER)
        c.rect(ml + lw, cyb, left_val_w, rh_i, fill=0, stroke=1)
        is_note_row = (lbl == '비     고')
        wrapped = note_lines if is_note_row else ([val] if val else [])
        if wrapped:
            c.setFont(fn, 8)
            # 상단부터 줄단위로 그리기
            ty = cy - 2 * mm - 8 * 0.75  # 첫 줄 baseline
            for ln in wrapped:
                if ty < cyb + 1 * mm:
                    break
                c.drawString(ml + lw + note_pad_x, ty, ln)
                ty -= note_line_h
        cy = cyb

    y = y_bot

    # ━━━ 부가세 구분 ━━━
    y -= 3 * mm
    c.setFont(fn, 8)
    c.drawString(ml, y, '부가세  구분 :    매입과세')

    c.save()
    return buf.getvalue()
