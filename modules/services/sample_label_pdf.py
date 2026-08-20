"""시료 QR 라벨 PDF — 라벨프린터 실치수 출력.

브라우저 HTML 인쇄는 Chrome이 "인쇄 가능 영역"에 맞춰 제멋대로 축소해서
100×50 라벨도 작게 찍히는 문제가 있다. PDF는 페이지 크기(MediaBox)가
문서 안에 박혀 있어서, 뷰어에서 '실제 크기'로만 두면 항상 원치수로 나온다.
"""

import io
import logging
import os

from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from modules.services.sample_qr import build_label_qr_png

logger = logging.getLogger(__name__)

FONT_CANDIDATES = [
    ('/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
     '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'),
    (r'C:\Windows\Fonts\malgun.ttf', r'C:\Windows\Fonts\malgunbd.ttf'),
    ('/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf',
     '/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf'),
]


def _register_fonts():
    """(일반, 굵게) 폰트명 반환. 한글 폰트가 없으면 Helvetica로 폴백."""
    for regular, bold in FONT_CANDIDATES:
        if not os.path.exists(regular):
            continue
        try:
            if 'LabelKR' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('LabelKR', regular))
            name_bold = 'LabelKR'
            if os.path.exists(bold):
                if 'LabelKRBold' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('LabelKRBold', bold))
                name_bold = 'LabelKRBold'
            return 'LabelKR', name_bold
        except Exception as e:  # 폰트 파일 손상 등
            logger.warning('라벨 PDF 한글 폰트 등록 실패(%s): %s', regular, e)
    return 'Helvetica', 'Helvetica-Bold'


def _fit(c, text, font, size, max_w):
    """max_w(pt)를 넘으면 잘라내고 말줄임. 라벨은 줄바꿈 금지."""
    text = (text or '').strip()
    if not text:
        return ''
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while len(text) > 1 and c.stringWidth(text + '…', font, size) > max_w:
        text = text[:-1]
    return text + '…'


def _shrink_to_fit(c, text, font, size, max_w, floor=4.5):
    """시료번호처럼 잘리면 안 되는 줄 — 폭에 맞을 때까지 글자를 줄인다.

    라벨이 작아도 번호만은 온전히 찍혀야 한다(스캔 실패 시 사람이 읽어야 함).
    floor 까지 줄여도 안 들어가면 그때만 말줄임한다.
    """
    text = (text or '').strip()
    if not text:
        return size
    while size > floor and c.stringWidth(text, font, size) > max_w:
        size -= 0.25
    return round(size, 2)


def build_label_pdf(labels, spec, public_url_of):
    """라벨 PDF bytes 생성 — 라벨 1장 = PDF 1페이지.

    labels        : dict 리스트 (sample_no / model_name / purpose / mfg_date / qr_token)
    spec          : routes.sample._resolve_label_spec() 결과 (mm 단위)
    public_url_of : qr_token -> 공개 URL 함수
    """
    fn, fn_bold = _register_fonts()

    page_w, page_h = spec['pw'] * mm, spec['ph'] * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle('매그나텍 시료 QR 라벨')

    lw, lh = spec['lw'] * mm, spec['lh'] * mm
    off_x, off_y = spec['off_x'] * mm, spec['off_y'] * mm
    pad = 1.2 * mm
    gap = 1.2 * mm
    qr_size = spec['qr'] * mm

    for item in labels:
        # PDF 원점은 좌하단 — 화면(좌상단) 기준 off_y를 뒤집는다
        base_x = off_x
        base_y = page_h - off_y - lh

        # QR — 라벨 좌측, 세로 중앙
        qr_x = base_x + pad
        qr_y = base_y + (lh - qr_size) / 2
        png = build_label_qr_png(public_url_of(item['qr_token']))
        c.drawImage(ImageReader(io.BytesIO(png)), qr_x, qr_y, qr_size, qr_size,
                    preserveAspectRatio=True, anchor='c', mask=None)

        # 텍스트 — QR 오른쪽 남은 폭
        tx = qr_x + qr_size + gap
        tw = base_x + lw - pad - tx
        if tw < 6 * mm:      # 글자 자리가 안 나오면 QR만 (초소형 라벨)
            c.showPage()
            continue

        f = spec['fonts']
        # 시료번호는 잘림 금지 — 폭에 맞춰 글자만 줄인다
        no_size = _shrink_to_fit(c, item.get('sample_no'), fn_bold, f['no'], tw)
        # (텍스트, 폰트, 크기pt, 회색농도 0=검정)
        lines = [
            (item.get('sample_no') or '', fn_bold, no_size, 0),
            (item.get('model_name') or '', fn, f['model'], 0),
            (item.get('sub') or '', fn, f['sub'], 0.15),
            ('(주)매그나텍 시료 · 스캔하면 시험이력', fn, f['brand'], 0.35),
        ]
        leading = [size * 1.45 for _, _, size, _ in lines]
        block_h = sum(leading)
        # 세로 중앙 정렬 — 첫 줄 baseline
        cursor = base_y + (lh + block_h) / 2 - leading[0]

        for (text, font, size, gray), lead in zip(lines, leading):
            if text:
                c.setFont(font, size)
                c.setFillGray(gray)
                c.drawString(tx, cursor + size * 0.15, _fit(c, text, font, size, tw))
            cursor -= lead

        c.showPage()

    if not labels:          # 빈 목록이어도 유효한 PDF를 돌려준다
        c.showPage()

    c.save()
    return buf.getvalue()
