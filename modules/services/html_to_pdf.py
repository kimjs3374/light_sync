"""
HTML → PDF 변환 유틸리티.

Chrome headless를 사용하여 HTML 파일을 A4 PDF로 변환합니다.
"""

import io
import os
import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)

CHROME_PATHS = [
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
]


def _find_chrome():
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    import shutil
    return shutil.which('google-chrome') or shutil.which('chromium')


def html_to_pdf(html_string: str) -> bytes:
    """
    HTML 문자열을 A4 PDF 바이트로 변환합니다.

    Args:
        html_string: 완성된 HTML 문서 문자열

    Returns:
        PDF 바이트
    """
    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError("Chrome/Chromium이 설치되어 있지 않습니다.")

    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = os.path.join(tmpdir, 'page.html')
        pdf_path = os.path.join(tmpdir, 'output.pdf')

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_string)

        result = subprocess.run([
            chrome,
            '--headless',
            '--disable-gpu',
            '--no-sandbox',
            '--disable-software-rasterizer',
            f'--print-to-pdf={pdf_path}',
            '--no-margins',
            '--print-to-pdf-no-header',
            f'file://{html_path}',
        ], capture_output=True, text=True, timeout=60)

        if not os.path.exists(pdf_path):
            logger.error("Chrome PDF 생성 실패: %s", result.stderr)
            raise RuntimeError(f"PDF 변환 실패: {result.stderr}")

        with open(pdf_path, 'rb') as f:
            return f.read()


def html_to_pdf_buf(html_string: str) -> io.BytesIO:
    """html_to_pdf의 BytesIO 래퍼."""
    pdf_bytes = html_to_pdf(html_string)
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf
