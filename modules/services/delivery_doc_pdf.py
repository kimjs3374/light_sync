"""
납품서류(납품계) PDF 생성 모듈.

reportlab 사용, 한글 지원 (시스템 폰트 자동 탐색).
1개 PDF에 7페이지:
  1. 공문 (납품계 서류 제출의 건)
  2. 납품완료계
  3. 물품납품 및 영수증
  4. 물품검사(수)조서
  5. 물품검사(수)내역서
  6. 물품납품확인서
  7. 사진대지 (빈 양식)
"""

import io
import logging
import math
import os
from datetime import date

from modules.services.quote_pdf import _find_korean_font

logger = logging.getLogger(__name__)

COMPANY_NAME = '(주)매그나텍'
COMPANY_NAME_SPACED = '(주)매 그 나 텍'
COMPANY_BIZ_NO = '408-81-68519'
COMPANY_TEL = '061-392-5508'
COMPANY_FAX = '061-392-5518'
COMPANY_ADDR = '전남 장성군 동화면 전자농공단지2길 55'
COMPANY_ZIPCODE = '57241'
COMPANY_CEO = '박선후'
COMPANY_CEO_SPACED = '박 선 후'

# ──────────────────────────────────────────────────────────────────────
# 한글 금액 변환
# ──────────────────────────────────────────────────────────────────────

_DIGITS = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']
_SMALL_UNITS = ['', '십', '백', '천']
_BIG_UNITS = ['', '만', '억', '조']


def number_to_korean(n):
    """정수를 한글 금액 문자열로 변환한다. 예: 12345000 → '일천이백삼십사만오천'"""
    if n is None or n == 0:
        return '영'
    n = int(n)
    if n < 0:
        return '마이너스 ' + number_to_korean(-n)

    # 4자리씩 끊어서 처리
    parts = []
    big_idx = 0
    while n > 0:
        chunk = n % 10000
        if chunk > 0:
            chunk_str = _chunk_to_korean(chunk)
            parts.append(chunk_str + _BIG_UNITS[big_idx])
        n //= 10000
        big_idx += 1

    parts.reverse()
    return ''.join(parts)


def _chunk_to_korean(n):
    """4자리 이하 숫자를 한글로."""
    result = ''
    for i in range(3, -1, -1):
        digit = n // (10 ** i) % 10
        if digit == 0:
            continue
        # 일의 자리가 아닌 곳의 '일'은 생략 가능하지만 관행상 표기
        if digit == 1 and i > 0:
            result += _SMALL_UNITS[i]
        else:
            result += _DIGITS[digit] + _SMALL_UNITS[i]
    return result


# ──────────────────────────────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────────────────────────────

def _fmt_amount(n):
    """숫자를 쉼표 포맷."""
    if n is None:
        return '0'
    return f'{int(n):,}'


def _fmt_date(d, fmt='%Y. %m. %d.'):
    """날짜 포맷. None이면 빈 문자열."""
    if d is None:
        return ''
    if isinstance(d, str):
        return d
    return d.strftime(fmt)


def _fmt_date_korean(d):
    """YYYY년 MM월 DD일 형식."""
    if d is None:
        return ''
    if isinstance(d, str):
        return d
    return d.strftime('%Y년 %m월 %d일')


def _safe_str(v, default=''):
    if v is None:
        return default
    return str(v)


# ──────────────────────────────────────────────────────────────────────
# PDF 생성
# ──────────────────────────────────────────────────────────────────────

def generate_delivery_doc_pdf(package, procurements, stamp_path=None, logo_path=None):
    """
    납품서류 PDF를 생성한다.

    Args:
        package: DocumentPackage 객체
        procurements: list of G2bProcurement 객체
        stamp_path: 법인인감 이미지 경로
        logo_path: 매그나텍 로고 이미지 경로

    Returns:
        io.BytesIO: PDF 바이트 스트림
    """
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
    w, h = A4  # 595.27, 841.89
    ml = 25 * mm  # 왼쪽 마진
    mr = 25 * mm  # 오른쪽 마진
    uw = w - ml - mr  # 유효 폭

    # ── 공통 데이터 추출 ──
    business_name = _safe_str(package.business_name, '-')
    demand_org = _safe_str(package.demand_org, '-')
    org_type = _safe_str(package.org_type, '청')
    doc_no = _safe_str(package.delivery_doc_no, '')
    delivery_date = package.delivery_date or date.today()
    contract_date = package.contract_date
    req_no = _safe_str(package.procurement_req_no, '-')

    # 납품기한: procurements에서 가져오기
    delivery_due = None
    if procurements:
        delivery_due = procurements[0].dlvr_tmlmt_date

    # 금액 계산
    total_amount = package.total_amount or 0  # 합계 (부가세포함)
    supply_amount = package.supply_amount or 0  # 품대계 (부가세 미포함 품대)
    fee = package.fee or 0  # 수수료

    # 물품대/부가세/합계 계산 (부가세 포함 기준)
    if total_amount > 0:
        goods_amount_pre_tax = math.floor(total_amount / 1.1)  # 물품대(세전)
        vat = total_amount - goods_amount_pre_tax                # 부가세
    else:
        goods_amount_pre_tax = 0
        vat = 0

    korean_amount = number_to_korean(total_amount)

    # ── 헬퍼 함수들 ──
    def _draw_stamp_or_seal(cx, cy, size=20 * mm):
        """도장 이미지가 있으면 삽입, 없으면 (인) 텍스트."""
        if stamp_path and os.path.exists(stamp_path):
            try:
                c.drawImage(stamp_path, cx - size / 2, cy - size / 2,
                            width=size, height=size, mask='auto',
                            preserveAspectRatio=True)
                return
            except Exception:
                pass
        c.setFont(fn, 12)
        c.drawCentredString(cx, cy - 4, '(인)')

    def _draw_logo(x, y, lw=30 * mm, lh=12 * mm):
        """로고 삽입."""
        if logo_path and os.path.exists(logo_path):
            try:
                c.drawImage(logo_path, x, y - lh,
                            width=lw, height=lh, mask='auto',
                            preserveAspectRatio=True)
                return True
            except Exception:
                pass
        return False

    def _draw_rect(x, y, rw, rh, fill_color=None, stroke=True):
        """사각형 그리기 (y는 좌하단)."""
        if fill_color:
            c.setFillColor(fill_color)
            c.rect(x, y, rw, rh, fill=1, stroke=1 if stroke else 0)
            c.setFillColor(colors.black)
        else:
            c.rect(x, y, rw, rh, fill=0, stroke=1)

    def _draw_cell(x, y, cw, ch, text, font=None, size=9, align='center', bold=False):
        """셀 안에 텍스트 쓰기 (y는 셀 상단)."""
        _font = fn_bold if bold else (font or fn)
        c.setFont(_font, size)
        text_y = y - ch / 2 - size * 0.35
        if align == 'center':
            c.drawCentredString(x + cw / 2, text_y, str(text))
        elif align == 'right':
            c.drawRightString(x + cw - 2 * mm, text_y, str(text))
        elif align == 'left':
            c.drawString(x + 2 * mm, text_y, str(text))

    def _draw_table_row(x, y, widths, row_h, texts, aligns=None, bold_cols=None, font_size=9):
        """테이블 행 하나를 그린다. y는 행 상단."""
        if aligns is None:
            aligns = ['center'] * len(widths)
        if bold_cols is None:
            bold_cols = []
        cx = x
        for i, (tw, text) in enumerate(zip(widths, texts)):
            c.rect(cx, y - row_h, tw, row_h)
            _draw_cell(cx, y, tw, row_h, text,
                       size=font_size,
                       align=aligns[i] if i < len(aligns) else 'center',
                       bold=(i in bold_cols))
            cx += tw

    # ══════════════════════════════════════════════════════════════════
    # Page 1: 공문 (납품계 서류 제출의 건)
    # ══════════════════════════════════════════════════════════════════
    _draw_page1(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, procurements, delivery_date,
                doc_no, business_name, demand_org, org_type,
                req_no, korean_amount, total_amount,
                contract_date, delivery_due,
                stamp_path, _draw_stamp_or_seal)

    c.showPage()

    # ══════════════════════════════════════════════════════════════════
    # Page 2: 납품완료계
    # ══════════════════════════════════════════════════════════════════
    _draw_page2(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, delivery_date,
                business_name, demand_org, req_no,
                korean_amount, total_amount,
                contract_date, delivery_due,
                _draw_logo, _draw_stamp_or_seal, logo_path)

    c.showPage()

    # ══════════════════════════════════════════════════════════════════
    # Page 3: 물품납품 및 영수증
    # ══════════════════════════════════════════════════════════════════
    _draw_page3(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, procurements, delivery_date,
                business_name, demand_org, req_no,
                total_amount, supply_amount, fee,
                goods_amount_pre_tax, vat,
                contract_date, delivery_due)

    c.showPage()

    # ══════════════════════════════════════════════════════════════════
    # Page 4: 물품검사(수)조서
    # ══════════════════════════════════════════════════════════════════
    _draw_page4(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, delivery_date,
                business_name, demand_org,
                korean_amount, total_amount,
                contract_date, delivery_due)

    c.showPage()

    # ══════════════════════════════════════════════════════════════════
    # Page 5: 물품검사(수)내역서
    # ══════════════════════════════════════════════════════════════════
    _draw_page5(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, procurements, delivery_date,
                korean_amount, total_amount)

    c.showPage()

    # ══════════════════════════════════════════════════════════════════
    # Page 6: 물품납품확인서
    # ══════════════════════════════════════════════════════════════════
    _draw_page6(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, procurements, delivery_date,
                business_name, contract_date, delivery_due,
                stamp_path, _draw_stamp_or_seal)

    c.showPage()

    # ══════════════════════════════════════════════════════════════════
    # Page 7: 사진대지 (빈 양식)
    # ══════════════════════════════════════════════════════════════════
    _draw_page7(c, w, h, ml, mr, uw, mm, fn, fn_bold, business_name)

    c.save()
    buf.seek(0)
    return buf


# ======================================================================
# 페이지별 그리기 함수
# ======================================================================

def _draw_page1(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, procurements, delivery_date,
                doc_no, business_name, demand_org, org_type,
                req_no, korean_amount, total_amount,
                contract_date, delivery_due,
                stamp_path, draw_stamp_fn):
    """Page 1: 공문 (납품계 서류 제출의 건)."""
    from reportlab.lib import colors

    y = h - 20 * mm

    # ── 레터헤드 (우상단) ──
    c.setFont(fn, 8)
    header_x = w - mr
    c.drawRightString(header_x, y, f'(우:{COMPANY_ZIPCODE}) {COMPANY_ADDR}')
    y -= 4 * mm
    c.drawRightString(header_x, y, f'Tel : {COMPANY_TEL}   Fax : {COMPANY_FAX}')
    y -= 8 * mm

    # ── 결재란 (우상단 박스) ──
    approval_x = w - mr - 90 * mm
    approval_y = y
    box_w = 18 * mm
    box_h = 7 * mm
    approval_labels = ['선결', '접수', '처리과', '담당자', '심사자']
    c.setLineWidth(0.5)
    for i, label in enumerate(approval_labels):
        bx = approval_x + i * box_w
        # 헤더 행
        c.rect(bx, approval_y - box_h, box_w, box_h)
        c.setFont(fn, 7)
        c.drawCentredString(bx + box_w / 2, approval_y - box_h + 2 * mm, label)
        # 빈 서명 행
        c.rect(bx, approval_y - box_h * 3, box_w, box_h * 2)

    y = approval_y - box_h * 3 - 5 * mm

    # ── 문서번호 / 시행일자 ──
    c.setFont(fn, 10)
    c.drawString(ml, y + 25 * mm, f'문서번호 : {doc_no}')
    c.drawString(ml, y + 20 * mm, f'시행일자 : {_fmt_date(delivery_date)}')
    c.drawString(ml, y + 15 * mm, f'수    신 : {demand_org}')

    y -= 5 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 14)
    c.drawCentredString(w / 2, y, f"'{business_name}' 건에 대한")
    y -= 7 * mm
    c.drawCentredString(w / 2, y, '납품계 서류 제출의 건.')
    y -= 12 * mm

    # ── 본문 ──
    c.setFont(fn, 10)
    line_h = 6 * mm

    c.drawString(ml, y, f'1. 귀 {org_type}의 무궁한 발전을 기원 합니다.')
    y -= line_h

    c.drawString(ml, y, f'2. 사업명 : {business_name}')
    y -= line_h

    c.drawString(ml, y, '3. 위 계약건과 관련하여 납품완료계를 아래와 같이 제출 하오니')
    y -= line_h
    c.drawString(ml + 5 * mm, y, '승인하여 주시기 바랍니다.')
    y -= line_h * 2

    # 아 래
    c.setFont(fn_bold, 11)
    c.drawCentredString(w / 2, y, '-  아   래  -')
    y -= line_h * 1.5

    c.setFont(fn, 10)
    indent = ml + 10 * mm

    c.drawString(indent, y, f'가. 계약번호 : {req_no}')
    y -= line_h

    c.drawString(indent, y, f'나. 계약금액 : 일금 {korean_amount}원정(₩ {_fmt_amount(total_amount)}원 : 부가세포함)')
    y -= line_h

    c.drawString(indent, y, f'다. 계약년월일 : {_fmt_date(contract_date)}')
    y -= line_h

    c.drawString(indent, y, f'라. 납품기한 : {_fmt_date(delivery_due)}')
    y -= line_h * 2

    # ── 붙임 ──
    c.setFont(fn_bold, 10)
    c.drawString(ml, y, '# 붙임')
    y -= line_h

    c.setFont(fn, 9)
    attachments = [
        '1. 납품완료계',
        '2. 분할납품요구서',
        '3. 물품납품 및 영수증',
        '4. 물품검사(수)조서',
        '5. 물품검사(수)내역서',
        '6. 납품확인서',
        '7. 사진대지',
    ]
    for att in attachments:
        c.drawString(ml + 15 * mm, y, att)
        y -= 5 * mm

    y -= 10 * mm

    # ── 하단 서명 ──
    c.setFont(fn_bold, 14)
    c.drawCentredString(w / 2, y, f'{COMPANY_NAME_SPACED}')
    y -= 8 * mm
    c.setFont(fn_bold, 13)
    c.drawCentredString(w / 2, y, f'대표이사  {COMPANY_CEO_SPACED}')

    # 도장
    draw_stamp_fn(w / 2 + 45 * mm, y + 4 * mm, size=22 * mm)


def _draw_page2(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, delivery_date,
                business_name, demand_org, req_no,
                korean_amount, total_amount,
                contract_date, delivery_due,
                draw_logo_fn, draw_stamp_fn, logo_path):
    """Page 2: 납품완료계."""
    from reportlab.lib import colors

    y = h - 20 * mm

    # ── 로고 헤더 ──
    draw_logo_fn(ml, y, lw=35 * mm, lh=14 * mm)
    y -= 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 20)
    c.drawCentredString(w / 2, y, '납 품 완 료 계')
    y -= 15 * mm

    # ── 표 ──
    row_h = 10 * mm
    label_w = 35 * mm
    value_w = uw - label_w

    def _info_row(label, value, bold_value=False):
        nonlocal y
        c.setLineWidth(0.5)
        c.rect(ml, y - row_h, label_w, row_h)
        c.rect(ml + label_w, y - row_h, value_w, row_h)
        c.setFont(fn_bold, 10)
        c.drawCentredString(ml + label_w / 2, y - row_h / 2 - 3, label)
        _f = fn_bold if bold_value else fn
        c.setFont(_f, 10)
        c.drawString(ml + label_w + 3 * mm, y - row_h / 2 - 3, str(value))
        y -= row_h

    _info_row('계약번호', req_no)
    _info_row('사 업 명', business_name)
    _info_row('계약금액', f'일금 {korean_amount}원정 (₩{_fmt_amount(total_amount)}원 : 부가세포함)')
    _info_row('계약년월일', _fmt_date(contract_date))
    _info_row('납품기한', _fmt_date(delivery_due))
    _info_row('납 품 일', _fmt_date(delivery_date))

    y -= 10 * mm

    # ── 본문 ──
    c.setFont(fn, 11)
    c.drawString(ml, y, '상기 용역에 대해 관급자재 납품 완료하였기에 완료계를 제출합니다.')
    y -= 8 * mm

    c.setFont(fn, 10)
    c.drawString(ml, y, '감독관 경유 :')
    y -= 20 * mm

    # ── 날짜 + 서명 ──
    c.setFont(fn, 11)
    c.drawCentredString(w / 2, y, _fmt_date(delivery_date))
    y -= 12 * mm

    c.setFont(fn_bold, 13)
    c.drawCentredString(w / 2, y, COMPANY_NAME)
    y -= 8 * mm
    c.drawCentredString(w / 2, y, f'대표이사  {COMPANY_CEO}')

    # 법인인감
    draw_stamp_fn(w / 2 + 45 * mm, y + 4 * mm, size=22 * mm)

    y -= 20 * mm

    # ── 수요기관 귀하 ──
    c.setFont(fn_bold, 12)
    c.drawCentredString(w / 2, y, f'{demand_org} 귀하')


def _draw_page3(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, procurements, delivery_date,
                business_name, demand_org, req_no,
                total_amount, supply_amount, fee,
                goods_amount_pre_tax, vat,
                contract_date, delivery_due):
    """Page 3: 물품납품 및 영수증."""
    from reportlab.lib import colors

    y = h - 18 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 16)
    c.drawCentredString(w / 2, y, '물 품 납 품 및 영 수 증')
    y -= 12 * mm

    # ── 상단 정보 테이블 ──
    c.setLineWidth(0.5)
    small_font = 7
    row_h = 7 * mm
    half_w = uw / 2

    # 좌측 블록
    left_items = [
        ('증빙번호', ''),
        ('계약번호', req_no),
        ('납품지시번호', ''),
        ('납품기한', _fmt_date(delivery_due, '%Y.%m.%d')),
        ('계약일자', _fmt_date(contract_date, '%Y.%m.%d')),
    ]
    # 우측 블록
    right_items = [
        ('수요기관', demand_org),
        ('수요기관번호', _safe_str(package.demand_org_no)),
        ('계약금액', _fmt_amount(total_amount)),
        ('물품대', _fmt_amount(supply_amount or goods_amount_pre_tax)),
        ('수수료', _fmt_amount(fee)),
    ]

    label_w_s = 28 * mm
    value_w_s = half_w - label_w_s

    for i, ((ll, lv), (rl, rv)) in enumerate(zip(left_items, right_items)):
        row_y = y - row_h
        # 좌측
        c.rect(ml, row_y, label_w_s, row_h)
        c.rect(ml + label_w_s, row_y, value_w_s, row_h)
        c.setFont(fn_bold, small_font)
        c.drawCentredString(ml + label_w_s / 2, row_y + 2 * mm, ll)
        c.setFont(fn, small_font)
        c.drawString(ml + label_w_s + 1 * mm, row_y + 2 * mm, str(lv))
        # 우측
        rx = ml + half_w
        c.rect(rx, row_y, label_w_s, row_h)
        c.rect(rx + label_w_s, row_y, value_w_s, row_h)
        c.setFont(fn_bold, small_font)
        c.drawCentredString(rx + label_w_s / 2, row_y + 2 * mm, rl)
        c.setFont(fn, small_font)
        c.drawString(rx + label_w_s + 1 * mm, row_y + 2 * mm, str(rv))
        y -= row_h

    y -= 3 * mm

    # ── 납품자 정보 ──
    c.setFont(fn_bold, 9)
    c.drawString(ml, y, '납품자 :')
    c.setFont(fn, 8)
    c.drawString(ml + 18 * mm, y, f'{COMPANY_NAME}  (대표: {COMPANY_CEO})  사업자번호: {COMPANY_BIZ_NO}')
    y -= 5 * mm
    c.drawString(ml + 18 * mm, y, f'주소: {COMPANY_ADDR}  Tel: {COMPANY_TEL}')
    y -= 6 * mm

    # ── 품목 테이블 ──
    col_widths = [18 * mm, 22 * mm, 40 * mm, 12 * mm, 14 * mm, 22 * mm, 25 * mm, 14 * mm]
    # 총 폭 확인/조정
    total_col = sum(col_widths)
    if total_col != uw:
        col_widths[-1] += (uw - total_col)

    headers = ['물품분류번호', '물품식별번호', '품명 및 규격', '단위', '수량', '단가', '금액', '원산지']
    item_row_h = 8 * mm

    # 헤더
    cx = ml
    c.setLineWidth(0.5)
    for i, (cw, hd) in enumerate(zip(col_widths, headers)):
        c.rect(cx, y - item_row_h, cw, item_row_h)
        c.setFont(fn_bold, 6.5)
        c.drawCentredString(cx + cw / 2, y - item_row_h + 2.5 * mm, hd)
        cx += cw
    y -= item_row_h

    # 데이터 행
    for proc in procurements:
        cx = ml
        texts = [
            _safe_str(proc.prdct_clsfc_no),
            _safe_str(proc.prdct_idnt_no),
            _safe_str(proc.prdct_idnt_no_nm or proc.dtil_prdct_clsfc_no_nm or proc.prdct_clsfc_no_nm),
            _safe_str(proc.prdct_unit, 'EA'),
            _fmt_amount(proc.prdct_qty),
            _fmt_amount(proc.prdct_uprc),
            _fmt_amount(proc.prdct_amt),
            '대한민국',
        ]
        aligns = ['center', 'center', 'left', 'center', 'right', 'right', 'right', 'center']

        for i, (cw, txt) in enumerate(zip(col_widths, texts)):
            c.rect(cx, y - item_row_h, cw, item_row_h)
            c.setFont(fn, 6.5)
            text_y = y - item_row_h + 2.5 * mm
            if aligns[i] == 'center':
                c.drawCentredString(cx + cw / 2, text_y, txt)
            elif aligns[i] == 'right':
                c.drawRightString(cx + cw - 1 * mm, text_y, txt)
            else:
                # left - truncate if needed
                tw = c.stringWidth(txt, fn, 6.5)
                if tw > cw - 2 * mm:
                    while len(txt) > 1 and c.stringWidth(txt + '..', fn, 6.5) > cw - 2 * mm:
                        txt = txt[:-1]
                    txt = txt + '..'
                c.drawString(cx + 1 * mm, text_y, txt)
            cx += cw
        y -= item_row_h

    y -= 5 * mm

    # ── 물품대 / 부가세 / 합계 ──
    summary_label_w = 30 * mm
    summary_value_w = 40 * mm
    sx = ml + uw - summary_label_w - summary_value_w
    summary_h = 7 * mm

    for label, val in [('물품대(세전)', _fmt_amount(goods_amount_pre_tax)),
                       ('부가세', _fmt_amount(vat)),
                       ('합    계', _fmt_amount(total_amount))]:
        c.rect(sx, y - summary_h, summary_label_w, summary_h)
        c.rect(sx + summary_label_w, y - summary_h, summary_value_w, summary_h)
        c.setFont(fn_bold, 8)
        c.drawCentredString(sx + summary_label_w / 2, y - summary_h + 2 * mm, label)
        c.setFont(fn, 8)
        c.drawRightString(sx + summary_label_w + summary_value_w - 2 * mm, y - summary_h + 2 * mm, val)
        y -= summary_h

    y -= 5 * mm

    # ── 사업명, 하자보수, 세금계산서 ──
    c.setFont(fn, 9)
    c.drawString(ml, y, f'사업명 : {business_name}')
    y -= 5 * mm
    c.drawString(ml, y, '하자보수보증금 수납필')
    y -= 5 * mm
    c.drawString(ml, y, '세금계산서 접수필')

    y -= 8 * mm

    # ── 우측: 검사 정보 (빈칸) ──
    c.setFont(fn_bold, 9)
    rx = ml + uw / 2 + 10 * mm
    inspect_items = [
        '검사요청일 :', '검사보완일 :', '검사합격일 :',
        '검사완료일 :', '소속검사관 :',
        '검수요청일 :', '검수완료일 :',
    ]
    iy = h - 18 * mm - 12 * mm - (len(left_items) * row_h) - 3 * mm - 5 * mm - 6 * mm
    # 우측 검사정보는 품목테이블 우측 여백에 배치하기엔 공간이 부족하므로
    # 하단에 별도 배치
    for item in inspect_items:
        c.setFont(fn, 8)
        c.drawString(rx, y, item)
        y -= 4.5 * mm


def _draw_page4(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, delivery_date,
                business_name, demand_org,
                korean_amount, total_amount,
                contract_date, delivery_due):
    """Page 4: 물품검사(수)조서."""
    from reportlab.lib import colors

    y = h - 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 18)
    c.drawCentredString(w / 2, y, '물 품 검 사 (수) 조 서')
    y -= 18 * mm

    # ── 정보 테이블 ──
    row_h = 10 * mm
    label_w = 38 * mm
    value_w = uw - label_w

    def _info_row(label, value):
        nonlocal y
        c.setLineWidth(0.5)
        c.rect(ml, y - row_h, label_w, row_h)
        c.rect(ml + label_w, y - row_h, value_w, row_h)
        c.setFont(fn_bold, 10)
        c.drawCentredString(ml + label_w / 2, y - row_h / 2 - 3, label)
        c.setFont(fn, 10)
        c.drawString(ml + label_w + 3 * mm, y - row_h / 2 - 3, str(value))
        y -= row_h

    _info_row('계약건명', business_name)

    # 납품자 (2행: 상호명, 대표자)
    c.setLineWidth(0.5)
    double_h = row_h * 2
    c.rect(ml, y - double_h, label_w, double_h)
    c.rect(ml + label_w, y - double_h, value_w, double_h)
    c.setFont(fn_bold, 10)
    c.drawCentredString(ml + label_w / 2, y - double_h / 2 - 3, '납 품 자')
    c.setFont(fn, 10)
    c.drawString(ml + label_w + 3 * mm, y - row_h / 2 - 3, f'상호명 : {COMPANY_NAME}')
    c.drawString(ml + label_w + 3 * mm, y - row_h - row_h / 2 - 3, f'대표자 : {COMPANY_CEO}')
    y -= double_h

    _info_row('계약금액', f'일금 {korean_amount}원정 (₩{_fmt_amount(total_amount)}원)')
    _info_row('계약체결년월일', _fmt_date(contract_date))
    _info_row('납품기한', _fmt_date(delivery_due))
    _info_row('납품년월일', _fmt_date(delivery_date))
    _info_row('검사(수)년월일', '')

    # 검사(수) 장소
    _info_row('검사(수)장소', '수요기관 지정장소 內')

    # 물품관리시스템 등록대상구분
    _info_row('물품관리시스템\n등록대상구분', '')

    y -= 10 * mm

    # ── 본문 ──
    c.setFont(fn, 11)
    c.drawCentredString(w / 2, y, '"위와 같이 검사(수) 하였음."')
    y -= 15 * mm

    # ── 날짜 ──
    c.setFont(fn, 11)
    c.drawCentredString(w / 2, y, f'{_fmt_date(delivery_date)}')
    y -= 15 * mm

    # ── 서명란 ──
    sig_label_w = 40 * mm
    sig_value_w = 50 * mm
    sig_x = ml + (uw - sig_label_w - sig_value_w) / 2
    sig_h = 12 * mm

    for label in ['검사(수)자', '확인자(공사감독)', '기 안 자', '결 재 자']:
        c.rect(sig_x, y - sig_h, sig_label_w, sig_h)
        c.rect(sig_x + sig_label_w, y - sig_h, sig_value_w, sig_h)
        c.setFont(fn_bold, 10)
        c.drawCentredString(sig_x + sig_label_w / 2, y - sig_h / 2 - 3, label)
        y -= sig_h


def _draw_page5(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, procurements, delivery_date,
                korean_amount, total_amount):
    """Page 5: 물품검사(수)내역서."""
    from reportlab.lib import colors

    y = h - 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 18)
    c.drawCentredString(w / 2, y, '물 품 검 사 (수) 내 역 서')
    y -= 12 * mm

    # ── 금회 검수 계 ──
    c.setFont(fn_bold, 11)
    c.drawString(ml, y, f'금회 검수 계 : {korean_amount} (₩{_fmt_amount(total_amount)})')
    y -= 12 * mm

    # ── 테이블 ──
    col_widths = [18 * mm, 45 * mm, 12 * mm, 22 * mm, 18 * mm, 18 * mm, 18 * mm, 16 * mm]
    total_col = sum(col_widths)
    if total_col != uw:
        col_widths[1] += (uw - total_col)  # 물품명 컬럼 조정

    headers = ['물품목록\n번호', '물품명/규격명', '단위', '단가', '계약상의\n수량',
               '전회까지의\n납품수량', '금회\n검사(수)량', '사용부서']
    row_h = 12 * mm

    # 헤더 그리기
    cx = ml
    c.setLineWidth(0.5)
    for cw, hd in zip(col_widths, headers):
        c.rect(cx, y - row_h, cw, row_h)
        c.setFont(fn_bold, 7)
        lines = hd.split('\n')
        if len(lines) == 1:
            c.drawCentredString(cx + cw / 2, y - row_h / 2 - 2, lines[0])
        else:
            c.drawCentredString(cx + cw / 2, y - row_h / 2 + 2, lines[0])
            c.drawCentredString(cx + cw / 2, y - row_h / 2 - 5, lines[1])
        cx += cw
    y -= row_h

    # 데이터 행
    data_row_h = 9 * mm
    for proc in procurements:
        cx = ml
        prdct_name = _safe_str(proc.prdct_idnt_no_nm or proc.dtil_prdct_clsfc_no_nm or proc.prdct_clsfc_no_nm)
        texts = [
            _safe_str(proc.prdct_clsfc_no),
            prdct_name,
            _safe_str(proc.prdct_unit, 'EA'),
            _fmt_amount(proc.prdct_uprc),
            _fmt_amount(proc.prdct_qty),
            '-',  # 전회까지의 납품수량: 항상 "-"
            _fmt_amount(proc.prdct_qty),  # 금회 검사(수)량 = 전체 수량
            '',
        ]
        aligns = ['center', 'left', 'center', 'right', 'right', 'center', 'right', 'center']

        for i, (cw, txt) in enumerate(zip(col_widths, texts)):
            c.rect(cx, y - data_row_h, cw, data_row_h)
            c.setFont(fn, 7)
            text_y = y - data_row_h + 3 * mm
            if aligns[i] == 'center':
                c.drawCentredString(cx + cw / 2, text_y, txt)
            elif aligns[i] == 'right':
                c.drawRightString(cx + cw - 1 * mm, text_y, txt)
            else:
                tw = c.stringWidth(txt, fn, 7)
                if tw > cw - 2 * mm:
                    while len(txt) > 1 and c.stringWidth(txt + '..', fn, 7) > cw - 2 * mm:
                        txt = txt[:-1]
                    txt = txt + '..'
                c.drawString(cx + 1 * mm, text_y, txt)
            cx += cw
        y -= data_row_h


def _draw_page6(c, w, h, ml, mr, uw, mm,
                fn, fn_bold, package, procurements, delivery_date,
                business_name, contract_date, delivery_due,
                stamp_path, draw_stamp_fn):
    """Page 6: 물품납품확인서."""
    from reportlab.lib import colors

    y = h - 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 18)
    c.drawCentredString(w / 2, y, '물 품 납 품 확 인 서')
    y -= 15 * mm

    # ── 정보 테이블 ──
    row_h = 10 * mm
    label_w = 35 * mm
    value_w = uw - label_w

    def _info_row(label, value):
        nonlocal y
        c.setLineWidth(0.5)
        c.rect(ml, y - row_h, label_w, row_h)
        c.rect(ml + label_w, y - row_h, value_w, row_h)
        c.setFont(fn_bold, 10)
        c.drawCentredString(ml + label_w / 2, y - row_h / 2 - 3, label)
        c.setFont(fn, 10)
        c.drawString(ml + label_w + 3 * mm, y - row_h / 2 - 3, str(value))
        y -= row_h

    _info_row('계약건명', business_name)
    _info_row('계약일자', _fmt_date(contract_date))
    _info_row('납품기한', _fmt_date(delivery_due))
    _info_row('납품일자', _fmt_date(delivery_date))
    _info_row('인도조건', '납품장소 하차도')

    y -= 8 * mm

    # ── 품목 테이블 ──
    col_widths = [35 * mm, 50 * mm, 15 * mm, 20 * mm, uw - 35 * mm - 50 * mm - 15 * mm - 20 * mm]
    headers = ['품명', '규격', '단위', '수량', '비고']
    item_row_h = 9 * mm

    # 헤더
    cx = ml
    c.setLineWidth(0.5)
    for cw, hd in zip(col_widths, headers):
        c.rect(cx, y - item_row_h, cw, item_row_h)
        c.setFont(fn_bold, 9)
        c.drawCentredString(cx + cw / 2, y - item_row_h + 3 * mm, hd)
        cx += cw
    y -= item_row_h

    # 데이터 행
    for proc in procurements:
        cx = ml
        item_name = _safe_str(proc.prdct_clsfc_no_nm or proc.dtil_prdct_clsfc_no_nm, '')
        spec = _safe_str(proc.prdct_idnt_no_nm or '', '')
        texts = [
            item_name,
            spec,
            _safe_str(proc.prdct_unit, 'EA'),
            _fmt_amount(proc.prdct_qty),
            '',
        ]
        aligns = ['left', 'left', 'center', 'right', 'center']

        for i, (cw, txt) in enumerate(zip(col_widths, texts)):
            c.rect(cx, y - item_row_h, cw, item_row_h)
            c.setFont(fn, 8)
            text_y = y - item_row_h + 3 * mm
            if aligns[i] == 'center':
                c.drawCentredString(cx + cw / 2, text_y, txt)
            elif aligns[i] == 'right':
                c.drawRightString(cx + cw - 1 * mm, text_y, txt)
            else:
                tw = c.stringWidth(txt, fn, 8)
                if tw > cw - 2 * mm:
                    while len(txt) > 1 and c.stringWidth(txt + '..', fn, 8) > cw - 2 * mm:
                        txt = txt[:-1]
                    txt = txt + '..'
                c.drawString(cx + 1 * mm, text_y, txt)
            cx += cw
        y -= item_row_h

    y -= 15 * mm

    # ── 날짜 ──
    c.setFont(fn, 11)
    c.drawCentredString(w / 2, y, _fmt_date(delivery_date))
    y -= 15 * mm

    # ── [납품자] ──
    c.setFont(fn_bold, 11)
    c.drawString(ml, y, '[납품자]')
    y -= 7 * mm
    c.setFont(fn, 10)
    c.drawString(ml + 10 * mm, y, f'주  소 : {COMPANY_ADDR}')
    y -= 6 * mm
    c.drawString(ml + 10 * mm, y, f'업체명 : {COMPANY_NAME}')
    y -= 6 * mm
    c.drawString(ml + 10 * mm, y, f'성  명 : {COMPANY_CEO}')
    # 인감
    draw_stamp_fn(ml + 10 * mm + 80 * mm, y + 3 * mm, size=18 * mm)

    y -= 12 * mm

    # ── [건설사업관리인] ──
    c.setFont(fn_bold, 11)
    c.drawString(ml, y, '[건설사업관리인]')
    y -= 7 * mm
    c.setFont(fn, 10)
    c.drawString(ml + 10 * mm, y, '성  명 :')
    c.drawString(ml + 10 * mm + 60 * mm, y, '(인)')

    y -= 12 * mm

    # ── [인수자] ──
    c.setFont(fn_bold, 11)
    c.drawString(ml, y, '[인수자]')
    y -= 7 * mm
    c.setFont(fn, 10)
    c.drawString(ml + 10 * mm, y, '성  명 :')
    c.drawString(ml + 10 * mm + 60 * mm, y, '(인)')


def _draw_page7(c, w, h, ml, mr, uw, mm, fn, fn_bold, business_name):
    """Page 7: 사진대지 (빈 양식)."""
    from reportlab.lib import colors

    y = h - 25 * mm

    # ── 제목 ──
    c.setFont(fn_bold, 18)
    c.drawCentredString(w / 2, y, '사 진 대 지')
    y -= 10 * mm

    # ── 사업명 ──
    c.setFont(fn, 10)
    c.drawString(ml, y, f'사업명 : {business_name}')
    y -= 10 * mm

    # ── 사진 영역 (2×2 or 2×3 빈 박스) ──
    box_w = (uw - 10 * mm) / 2
    box_h = 80 * mm
    gap = 10 * mm

    c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
    c.setLineWidth(0.3)
    c.setDash(3, 3)

    for row in range(3):
        for col in range(2):
            bx = ml + col * (box_w + gap)
            by = y - (row + 1) * (box_h + 5 * mm) + 5 * mm
            c.rect(bx, by, box_w, box_h)

            # 라벨
            c.setFont(fn, 8)
            c.setFillColor(colors.Color(0.6, 0.6, 0.6))
            label_idx = row * 2 + col + 1
            c.drawCentredString(bx + box_w / 2, by + box_h / 2, f'사진 {label_idx}')
            c.setFillColor(colors.black)

    c.setDash()  # 점선 해제
    c.setStrokeColor(colors.black)
