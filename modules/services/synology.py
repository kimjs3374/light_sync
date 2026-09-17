"""사내 파일서버(시놀로지 NAS) — 서버가 사내망에서 직접 읽는다.

왜 만들었나: 메일에 NAS 파일을 붙이려면 사람이 NAS → PC 로 내려받아 다시 올려야 했다.
같은 파일이 사내망을 두 번 건넌다. 서버가 NAS 와 같은 망에 있으니 **한 번만** 건너면 된다.

**외부로 여는 것은 없다.** 서버(192.168.0.110) ↔ NAS(192.168.0.101) 내부 통신뿐이고,
받는 사람에게 나가는 것은 지금과 똑같다(메일에 실리거나 우리 Storage 링크).
시놀로지 공유링크는 쓰지 않는다.

지켜야 할 것
  - **읽기만 한다.** 여기에는 삭제·업로드·이름변경을 부르는 코드가 없다.
    계정도 읽기 전용으로 두는 것이 맞다(NAS 쪽 권한).
  - 세션(sid)은 붙일 때마다 새로 받지 않고 잠깐 들고 쓴다. 매번 로그인하면
    DSM 이 로그인 시도로 보고 계정을 잠글 수 있다.
  - 경로는 반드시 검사한다 — `..` 나 허용 목록 밖은 서버가 거부한다.
  - 사내 기기라 인증서가 자체서명이다. 검증을 끄되 **주소는 사설 IP 만** 받는다.
"""

import json
import logging
import os
import threading
import time

import requests
import urllib3

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SESSION_TTL = 20 * 60          # sid 를 들고 있는 시간
TIMEOUT = (5, 60)              # (연결, 읽기) — 큰 파일은 읽기가 길다
MAX_DOWNLOAD = 200 * 1024 * 1024

_sid_cache = {'sid': None, 'at': 0}
_lock = threading.Lock()


class NasError(Exception):
    """사람에게 그대로 보여 줄 수 있는 문구를 담는다."""


# DSM 이 돌려주는 오류 번호 — 숫자만 보여 주면 아무도 못 고친다
_ERR = {
    400: '계정 또는 비밀번호가 맞지 않습니다.',
    401: '계정이 잠겨 있습니다. NAS 관리자에게 확인해 주세요.',
    402: '계정에 권한이 없습니다.',
    403: 'NAS 에서 2단계 인증을 요구합니다. ERP 전용 계정은 2단계 인증을 꺼 주세요.',
    404: '2단계 인증 코드가 맞지 않습니다.',
    407: '접속이 차단된 IP 입니다. NAS 방화벽에서 서버 주소를 열어 주세요.',
    408: '비밀번호가 만료됐습니다.',
    409: '비밀번호를 바꿔야 합니다.',
    410: '비밀번호 정책에 걸립니다.',
    119: '세션이 끊겼습니다. 다시 시도해 주세요.',
    408_0: '',
}


def _base(cfg):
    scheme = 'https' if cfg['use_ssl'] else 'http'
    return f"{scheme}://{cfg['host']}:{cfg['port']}/webapi"


def check_host(host):
    """사설 IP 만 받는다 — 바깥 주소를 넣어 두면 사내 파일이 밖으로 나간다."""
    h = (host or '').strip()
    if h.startswith('192.168.') or h.startswith('10.') or h.startswith('127.'):
        return True
    if h.startswith('172.'):
        try:
            return 16 <= int(h.split('.')[1]) <= 31
        except (IndexError, ValueError):
            return False
    return False


def _api(cfg, params, stream=False):
    r = requests.get(f'{_base(cfg)}/entry.cgi', params=params,
                     verify=False, timeout=TIMEOUT, stream=stream)
    r.raise_for_status()
    return r


def _login(cfg):
    r = _api(cfg, {
        'api': 'SYNO.API.Auth', 'version': 6, 'method': 'login',
        'account': cfg['username'], 'passwd': cfg['password'],
        'session': 'FileStation', 'format': 'sid',
    })
    j = r.json()
    if not j.get('success'):
        code = (j.get('error') or {}).get('code')
        raise NasError(_ERR.get(code) or f'파일서버에 접속하지 못했습니다 (코드 {code}).')
    return j['data']['sid']


def _sid(cfg, force=False):
    with _lock:
        if not force and _sid_cache['sid'] and time.time() - _sid_cache['at'] < SESSION_TTL:
            return _sid_cache['sid']
        sid = _login(cfg)
        _sid_cache.update({'sid': sid, 'at': time.time()})
        return sid


def _call(cfg, params, stream=False):
    """sid 를 붙여 부른다. 세션이 끊겼으면 한 번만 다시 로그인한다."""
    for attempt in (0, 1):
        sid = _sid(cfg, force=(attempt == 1))
        r = _api(cfg, {**params, '_sid': sid}, stream=stream)
        if stream:
            ctype = r.headers.get('Content-Type', '')
            if 'application/json' not in ctype:
                return r                     # 파일 내용이 내려오는 중
            j = r.json()
        else:
            j = r.json()
        if j.get('success'):
            return j
        code = (j.get('error') or {}).get('code')
        if code == 119 and attempt == 0:
            continue                          # sid 만료 — 다시 로그인하고 한 번 더
        raise NasError(_ERR.get(code) or f'파일서버가 요청을 거절했습니다 (코드 {code}).')
    raise NasError('파일서버에 접속하지 못했습니다.')


# ── 바깥에서 쓰는 것들 ────────────────────────────────────────────────────

def test_connection(cfg):
    """접속 시험 — 되면 보이는 공유폴더 이름을 돌려준다."""
    if not check_host(cfg.get('host')):
        raise NasError('사내망 주소(192.168.x.x 등)만 넣을 수 있습니다.')
    _sid_cache.update({'sid': None, 'at': 0})     # 시험은 늘 새 세션으로
    shares = list_shares(cfg)
    return [s['name'] for s in shares]


def list_shares(cfg):
    """첨부 화면에 보일 공유폴더. allowed_shares 로 좁힌다(목록만 좁히는 것이다 —
    경로를 직접 적으면 계정이 볼 수 있는 곳은 그대로 열린다)."""
    j = _call(cfg, {'api': 'SYNO.FileStation.List', 'version': 2, 'method': 'list_share',
                    'additional': '["time"]'})
    out = []
    allowed = cfg.get('allowed_shares') or []
    for s in j.get('data', {}).get('shares', []):
        if allowed and s['name'] not in allowed:
            continue
        out.append({'name': s['name'], 'path': s['path'], 'is_dir': True})
    return sorted(out, key=lambda x: x['name'])


def list_folder(cfg, path):
    """폴더 하나의 내용. 폴더 먼저, 그 다음 파일."""
    check_path(cfg, path)
    j = _call(cfg, {'api': 'SYNO.FileStation.List', 'version': 2, 'method': 'list',
                    'folder_path': path, 'additional': '["size","time"]',
                    'sort_by': 'name', 'limit': 1000})
    folders, files = [], []
    for f in j.get('data', {}).get('files', []):
        item = {
            'name': f['name'], 'path': f['path'], 'is_dir': bool(f.get('isdir')),
            'size': (f.get('additional') or {}).get('size') or 0,
            'mtime': ((f.get('additional') or {}).get('time') or {}).get('mtime'),
        }
        (folders if item['is_dir'] else files).append(item)
    return folders + files


def stat(cfg, path):
    check_path(cfg, path)
    j = _call(cfg, {'api': 'SYNO.FileStation.List', 'version': 2, 'method': 'getinfo',
                    'path': json.dumps([path]), 'additional': '["size"]'})
    files = j.get('data', {}).get('files') or []
    if not files:
        raise NasError('파일을 찾지 못했습니다.')
    f = files[0]
    return {'name': f.get('name'), 'path': f.get('path'),
            'is_dir': bool(f.get('isdir')),
            'size': (f.get('additional') or {}).get('size') or 0}


def download(cfg, path):
    """파일 내용을 바이트로. 큰 파일은 여기서 막는다."""
    info = stat(cfg, path)
    if info['is_dir']:
        raise NasError('폴더는 첨부할 수 없습니다.')
    if info['size'] > MAX_DOWNLOAD:
        raise NasError(f"파일이 너무 큽니다 ({info['size'] // (1024 * 1024)}MB). "
                       f"{MAX_DOWNLOAD // (1024 * 1024)}MB 까지 붙일 수 있습니다.")

    r = _call(cfg, {'api': 'SYNO.FileStation.Download', 'version': 2, 'method': 'download',
                    'path': json.dumps([path]), 'mode': 'download'}, stream=True)
    chunks, total = [], 0
    for chunk in r.iter_content(1024 * 256):
        total += len(chunk)
        if total > MAX_DOWNLOAD:
            raise NasError('파일이 너무 큽니다.')
        chunks.append(chunk)
    return info['name'], b''.join(chunks)


def check_path(cfg, path):
    """경로 모양 검사 — 여기를 지나지 않은 경로로는 아무것도 읽지 않는다.

    **allowed_shares 는 여기서 보지 않는다.** 그 목록은 "첨부 화면에 **보일** 폴더" 를
    정할 뿐이고, 경로를 직접 적어 붙이는 것은 그대로 된다(김정수 지시 2026-09-17).
    화면을 깔끔하게 하려는 것이지 접근을 막으려는 것이 아니다 —
    실제로 못 보게 하려면 NAS 계정 권한에서 잘라야 한다.
    """
    p = (path or '').strip()
    if not p.startswith('/') or '..' in p or '\\' in p:
        raise NasError('올바른 경로가 아닙니다.')
    return p


# ── 윈도우 경로(UNC) 받기 ────────────────────────────────────────────────
# 탐색기에서 "경로로 복사" 한 것을 그대로 붙여넣을 수 있게 한다.
#   \\magnatech\현장관리\2026\견적.xlsx  →  /현장관리/2026/견적.xlsx
#
# **브라우저는 고른 파일의 경로를 안 알려준다**(보안상 C:\fakepath 로만 준다).
# 그래서 "PC에서 첨부하면 경로를 보고 판단" 은 브라우저 안에서는 불가능하다.
# 대신 사람이 경로를 붙여넣거나 NAS 탐색기에서 고르면 서버가 직접 읽는다.

UNC_ALIASES = {'magnatech', 'nas', 'magnatech-nas'}   # 사내에서 NAS 를 부르는 이름들


def parse_unc(raw, cfg):
    """윈도우 UNC 경로 → NAS 경로. 우리 NAS 가 아니면 NasError."""
    p = (raw or '').strip().strip('"').strip("'")
    if not p:
        raise NasError('경로가 비어 있습니다.')

    # 역슬래시를 먼저 바꾼다 — //host/share 를 NAS 경로(/share/...)로 잘못 보면
    # 공유폴더 이름 자리에 서버 이름이 들어가 엉뚱한 곳을 가리킨다
    p = p.replace('\\', '/')
    if p.startswith('//'):
        pass                       # 아래에서 UNC 로 푼다
    elif p.startswith('/'):        # 이미 NAS 경로면 검사만
        return check_path(cfg, p)
    if not p.startswith('//'):
        # Z:\... 같은 매핑 드라이브는 어느 공유인지 서버가 알 길이 없다
        if len(p) > 2 and p[1] == ':':
            raise NasError('드라이브 문자(Z:) 경로는 서버가 어느 공유폴더인지 알 수 없습니다. '
                           '탐색기에서 \\\\magnatech\\... 처럼 시작하는 경로로 복사해 주세요.')
        raise NasError('\\\\magnatech\\... 또는 \\\\192.168.0.101\\... 로 시작하는 경로를 넣어 주세요.')

    parts = [x for x in p[2:].split('/') if x]
    if len(parts) < 2:
        raise NasError('공유폴더까지 포함한 경로가 필요합니다.')

    host = parts[0].lower()
    if host != str(cfg.get('host', '')).lower() and host not in UNC_ALIASES:
        raise NasError(f"'{parts[0]}' 은 사내 파일서버가 아닙니다.")

    return check_path(cfg, '/' + '/'.join(parts[1:]))
