"""메일 첨부를 ONLYOFFICE 로 보여주기 위한 임시 보관.

왜 보관이 필요한가: 문서서버(도커 `onlyoffice-docs`)는 **자기가 파일을 가지러 온다.**
브라우저가 들고 있는 바이트를 넘겨줄 방법이 없고, 메일 첨부는 IMAP 안에 있어
주소가 없다. 그래서 잠깐 디스크에 두고 **한 번 쓰고 버리는 주소**를 내준다.

지켜야 할 것
  - 주소에는 **추측할 수 없는 토큰**을 쓰고 **수명을 짧게**(30분) 둔다.
  - 그 주소는 로그인 없이 열린다(문서서버가 세션을 들고 있지 않다). 대신
    **사설 IP 에서 온 요청만** 받는다 — 문서서버는 도커 브리지(172.17.0.x)에서 온다.
  - 임시파일을 `/tmp` 에 두지 않는다(systemd PrivateTmp — 서비스마다 /tmp 가 다르다).
"""

import json
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STASH_DIR = os.path.join(_BASE, '.upload_tmp', 'office')
TTL_SEC = 30 * 60

# 문서서버가 열 수 있는 것들 (routes/office.py 의 FILE_TYPE_MAP 과 같은 잣대)
DOC_TYPE = {
    'xlsx': 'cell', 'xls': 'cell', 'csv': 'cell', 'ods': 'cell',
    'docx': 'word', 'doc': 'word', 'odt': 'word', 'rtf': 'word', 'txt': 'word',
    'pptx': 'slide', 'ppt': 'slide', 'odp': 'slide',
    'pdf': 'pdf',
}


def doc_type(filename):
    """이 파일을 문서서버로 열 수 있는가 — 'cell' | 'word' | 'slide' | 'pdf' | None"""
    ext = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    return DOC_TYPE.get(ext)


def _sweep():
    """수명이 지난 것은 지운다. 새로 담을 때마다 한 번씩 훑으면 따로 돌릴 것이 없다."""
    now = time.time()
    try:
        for name in os.listdir(STASH_DIR):
            path = os.path.join(STASH_DIR, name)
            try:
                if now - os.path.getmtime(path) > TTL_SEC:
                    os.remove(path)
            except OSError:
                pass
    except FileNotFoundError:
        pass


def stash(data, filename):
    """첨부를 잠깐 두고 토큰을 돌려준다."""
    os.makedirs(STASH_DIR, exist_ok=True)
    _sweep()
    token = secrets.token_hex(16)
    ext = (filename or 'x').rsplit('.', 1)[-1].lower()
    with open(os.path.join(STASH_DIR, f'{token}.bin'), 'wb') as f:
        f.write(data)
    with open(os.path.join(STASH_DIR, f'{token}.json'), 'w', encoding='utf-8') as f:
        json.dump({'filename': filename or f'첨부.{ext}', 'ext': ext, 'at': time.time()}, f)
    return token


def load(token):
    """토큰으로 꺼내기 — (filename, ext, bytes). 없거나 수명이 지났으면 (None, None, None)."""
    if not token or not token.isalnum() or len(token) != 32:
        return None, None, None      # 경로를 파고드는 값은 여기서 끊는다
    meta_path = os.path.join(STASH_DIR, f'{token}.json')
    bin_path = os.path.join(STASH_DIR, f'{token}.bin')
    try:
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
        if time.time() - float(meta.get('at') or 0) > TTL_SEC:
            for p in (meta_path, bin_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
            return None, None, None
        with open(bin_path, 'rb') as f:
            return meta.get('filename'), meta.get('ext'), f.read()
    except (FileNotFoundError, ValueError):
        return None, None, None


def is_internal_caller(remote_addr):
    """문서서버(도커 브리지)에서 온 요청인가.

    토큰만으로도 추측은 어렵지만, 이 주소는 로그인을 안 보므로 한 겹 더 둔다.
    도커 기본 브리지는 172.17.0.x, 같은 호스트는 127.0.0.1 이다.
    """
    addr = (remote_addr or '').strip()
    if addr in ('127.0.0.1', '::1'):
        return True
    if addr.startswith('172.') or addr.startswith('192.168.') or addr.startswith('10.'):
        return True
    return False
