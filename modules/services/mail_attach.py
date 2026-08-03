"""메일 첨부 MIME 파트 생성 (구형 수신 시스템 호환).

파이썬 기본 방식 `add_header('Content-Disposition', 'attachment', filename=...)`은
파일명에 한글이 있으면 RFC2231 형식(`filename*=utf-8''%ED%95%9C...`)만 내보낸다.
Gmail·Outlook은 정상 처리하지만 korea.kr 정부통합메일 등 국내 관공서 메일 뷰어는
이 형식을 파싱하지 못해 파일명을 빈 값으로 읽고, 그 상태로 다운로드 링크를 만들어
수신자 쪽에서 링크 에러가 난다.

여기서는 첨부 파트를 아래 3가지로 맞춘다.
1. Content-Disposition 에 구형 `filename="=?UTF-8?B?..?="`(RFC2047 encoded-word)와
   표준 `filename*=UTF-8''..`(RFC2231)을 함께 기재
   → 구형 뷰어는 앞쪽, 최신 클라이언트는 뒤쪽을 읽어 양쪽 다 파일명이 살아난다.
2. Content-Type 을 application/octet-stream 으로 고정하고 `name` 파라미터를 추가
   → 뷰어가 내장 미리보기(PDF 뷰어)를 시도하지 못하고 다운로드로 처리한다.
3. 뷰어가 만드는 다운로드 URL을 깨뜨리는 문자(# % & ? + 공백 등)를 파일명에서 치환

발송 경로(웹메일 발송/임시저장, 발주서, 가공발주, 정기 보고서)가 모두 이 헬퍼를 쓴다.
"""

import re
from email.header import Header
from email.mime.application import MIMEApplication
from urllib.parse import quote

# 뷰어가 파일명으로 URL을 만들 때 깨지는 문자 + 파일시스템 금지 문자
_UNSAFE_CHARS = re.compile(r'[#%&?+*:;=,"\'<>|\\/\[\]{}()\r\n\t]')


def sanitize_attachment_filename(filename):
    """다운로드 링크를 깨뜨리는 문자를 제거한 안전한 파일명을 반환한다."""
    name = (filename or '').strip()
    if not name:
        return 'attachment'
    name = _UNSAFE_CHARS.sub('_', name)
    name = re.sub(r'\s+', '_', name)      # 공백도 _ 로 (URL 인코딩 안 하는 뷰어 대응)
    name = re.sub(r'_{2,}', '_', name)
    name = name.strip('_. ')
    return name or 'attachment'


def encode_attachment_filename(filename):
    """파일명을 RFC2047 encoded-word 로 변환 (ASCII 전용이면 그대로)."""
    try:
        filename.encode('ascii')
        return filename
    except UnicodeEncodeError:
        # maxlinelen 을 크게 줘서 encoded-word 가 여러 줄로 쪼개지지 않게 한다.
        # (파라미터 값 안에서 줄바꿈되면 구형 파서가 다시 파일명을 놓친다)
        return Header(filename, 'utf-8', maxlinelen=100000).encode()


def build_attachment_part(filename, file_bytes):
    """강제 다운로드용 첨부 파트를 만든다.

    Args:
        filename: 원본 파일명 (한글 가능)
        file_bytes: 파일 바이트
    Returns:
        MIMEApplication 파트
    """
    safe_name = sanitize_attachment_filename(filename)
    encoded_name = encode_attachment_filename(safe_name)
    rfc2231_name = quote(safe_name, safe='')

    part = MIMEApplication(file_bytes)  # application/octet-stream (미리보기 차단)
    # add_header 의 키워드 인자를 쓰지 않고 헤더 문자열을 직접 넣어야
    # 파이썬이 RFC2231 로 재인코딩하지 않는다.
    part.replace_header('Content-Type', f'application/octet-stream; name="{encoded_name}"')
    part.add_header(
        'Content-Disposition',
        f'attachment; filename="{encoded_name}"; filename*=UTF-8\'\'{rfc2231_name}'
    )
    return part
