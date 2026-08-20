"""시료 QR 코드 생성 — 라벨 부착용 PNG.

QR 내용은 공개 페이지 URL(/s/<qr_token>) 하나뿐이다.
스캔하면 별도 앱 없이 기본 카메라만으로 시료 이력이 열린다.
"""

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_Q


def build_qr_png(data, box_size=8, border=2, error_correction=None):
    """QR PNG bytes 생성.

    box_size: 모듈 1칸의 픽셀 수. 라벨프린터(203dpi)는 6~8이 적당.
    border  : 여백 모듈 수. QR 규격 최소 4지만 소형 라벨은 2로 줄인다.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction or ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def build_label_qr_png(data):
    """라벨용 QR — 실물 부착 후 오염/긁힘을 견디도록 복원율 25%(Q) 사용."""
    return build_qr_png(data, box_size=8, border=2, error_correction=ERROR_CORRECT_Q)
