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


def _wrap(c, text, font, size, max_w):
    """폭에 맞춰 여러 줄로 접는다 — 라벨은 잘라내기보다 접는 게 낫다.

    공백 기준으로 먼저 나누고, 한 낱말이 폭보다 길면(한글 붙임말·긴 모델명)
    글자 단위로 쪼갠다. 잘라내기는 마지막 수단으로 호출부에서만 한다.
    """
    text = (text or '').strip()
    if not text:
        return []
    lines, cur = [], ''
    for word in text.split(' '):
        trial = (cur + ' ' + word).strip()
        if c.stringWidth(trial, font, size) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ''
        while c.stringWidth(word, font, size) > max_w:
            cut = 1
            while cut < len(word) and c.stringWidth(word[:cut + 1], font, size) <= max_w:
                cut += 1
            lines.append(word[:cut])
            word = word[cut:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def _ellipsize(c, text, font, size, max_w):
    """마지막 수단 — 최소 크기로도 안 들어갈 때만 말줄임."""
    text = (text or '').strip()
    if not text or c.stringWidth(text, font, size) <= max_w:
        return text
    while len(text) > 1 and c.stringWidth(text + '…', font, size) > max_w:
        text = text[:-1]
    return text + '…'


def _shrink_to_fit(c, text, font, size, max_w, floor=4.5):
    """한 줄로 유지해야 하는 값(시료번호) — 폭에 맞을 때까지 글자만 줄인다.

    번호가 두 줄로 접히면 라벨에서 눈에 안 들어온다. 접는 대신 줄인다.
    """
    text = (text or '').strip()
    if not text:
        return size
    while size > floor and c.stringWidth(text, font, size) > max_w:
        size -= 0.25
    return round(size, 2)


def _layout_text(c, fields, max_w, max_h):
    """글자 블록 배치 확정 — 다 들어갈 때까지 통째로 줄여본다.

    fields : (텍스트, 폰트, 기준크기pt, 최대줄수, 회색농도, 생략가능) 리스트
    반환   : ([(줄, 폰트, 크기, 회색, 줄높이)], 전체 높이)

    ① 100%~50%까지 2.5%씩 줄이며 전부 들어가는 배율을 찾는다
    ② 그래도 안 되면 생략가능 줄(브랜드 문구)을 버리고 다시 ①
    ③ 최후에만 말줄임 — 시료번호·모델명이 잘리는 일은 없어야 한다
    """
    def attempt(subset, scale):
        drawn, total = [], 0.0
        for text, font, base, max_lines, gray, _drop in subset:
            size = round(base * scale, 2)
            lines = _wrap(c, text, font, size, max_w)
            if not lines:
                continue
            if len(lines) > max_lines:
                return None
            lead = size * 1.3
            for ln in lines:
                drawn.append((ln, font, size, gray, lead))
                total += lead
        return (drawn, total) if total <= max_h else None

    keep = [f for f in fields if not f[5]]
    for subset in (fields, keep):
        for step in range(0, 21):              # 100% → 50%
            got = attempt(subset, 1 - step * 0.025)
            if got:
                return got

    # 최소 크기로도 안 되면 — 줄수를 자르고 말줄임
    drawn, total = [], 0.0
    for text, font, base, max_lines, gray, _drop in keep:
        size = round(base * 0.5, 2)
        lead = size * 1.3
        for idx, ln in enumerate(_wrap(c, text, font, size, max_w)[:max_lines]):
            if total + lead > max_h:
                return drawn, total
            if idx == max_lines - 1:
                ln = _ellipsize(c, ln, font, size, max_w)
            drawn.append((ln, font, size, gray, lead))
            total += lead
    return drawn, total


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
        # (텍스트, 폰트, 기준크기pt, 최대줄수, 회색농도 0=검정, 자리 없으면 생략)
        # 시료번호는 접지 않고 폭에 맞춰 크기만 줄인다 (한 줄 고정)
        no_size = _shrink_to_fit(c, item.get('sample_no'), fn_bold, f['no'], tw)
        fields = [
            (item.get('sample_no') or '', fn_bold, no_size, 1, 0, False),
            (item.get('model_name') or '', fn, f['model'], 2, 0, False),
            (item.get('sub') or '', fn, f['sub'], 2, 0.15, False),
            ('(주)매그나텍 시료 · 스캔하면 시험이력', fn, f['brand'], 2, 0.35, True),
        ]
        lines, block_h = _layout_text(c, fields, tw, lh - 2 * pad)
        if not lines:
            c.showPage()
            continue

        # 세로 중앙 정렬 — 첫 줄 baseline
        cursor = base_y + (lh + block_h) / 2 - lines[0][4]
        for text, font, size, gray, lead in lines:
            c.setFont(font, size)
            c.setFillGray(gray)
            c.drawString(tx, cursor + size * 0.15, text)
            cursor -= lead

        c.showPage()

    if not labels:          # 빈 목록이어도 유효한 PDF를 돌려준다
        c.showPage()

    c.save()
    return buf.getvalue()
