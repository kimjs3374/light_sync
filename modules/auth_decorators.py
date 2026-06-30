"""인증/권한 데코레이터.

세션 기반(PC)과 Bearer 토큰 기반(모바일 SPA) 양쪽을 동일 데코레이터에서 처리한다.
- 세션이 살아있으면 그대로 통과
- 세션이 없고 Authorization: Bearer <token> 이 유효하면
  해당 사용자의 권한 정보를 in-memory 세션에 채워 view 함수가 기존과 동일하게 동작하게 한다.
  이때 응답에 Set-Cookie 가 발급되지 않도록 session.modified 를 False 로 강제하여
  토큰 인증 경로에서 PC 세션 쿠키가 새어 나가지 않게 한다.
"""

import functools
import hashlib
import hmac
import time
from flask import (
    session, redirect, url_for, flash, request, jsonify, g, current_app,
)

from config import COMMON_MENU_KEYS, MENU_REGISTRY
from flask.sessions import SecureCookieSessionInterface

from modules.db_context import get_db
from modules.models.auth_entities import User, GroupPermission, UserPriorityPermission


# ── 토큰 유틸 (모바일 SPA 공용) ──────────────────────────────────────────────

def _get_secret() -> str:
    return current_app.config.get('SECRET_KEY', 'fallback-secret')


def make_app_token(user_id: int) -> str:
    """user_id + 만료시각을 HMAC 서명한 토큰 문자열."""
    expires = int(time.time()) + 8 * 3600
    payload = f'{user_id}:{expires}'
    sig = hmac.new(_get_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f'{payload}:{sig}'


def verify_app_token(token: str):
    """토큰 검증 → user_id (int) 또는 None."""
    try:
        parts = token.split(':')
        if len(parts) != 3:
            return None
        user_id, expires, sig = int(parts[0]), int(parts[1]), parts[2]
        if time.time() > expires:
            return None
        expected = hmac.new(
            _get_secret().encode(), f'{user_id}:{expires}'.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id
    except Exception:
        return None


# ── 권한 계산 (로그인/토큰 인증 시 동일하게 사용) ─────────────────────────────

def compute_user_permissions(db, user: User) -> dict:
    """User 레코드로부터 세션에 들어갈 권한 dict 를 계산.

    app_api.app_login / webview-auth / 토큰 인증 fallback 모두 동일하게 사용한다.
    """
    group_data = (
        db.query(GroupPermission).filter(GroupPermission.group_name == user.user_group).first()
    )
    if user.role == 'admin':
        allowed_menus = [k for k in MENU_REGISTRY if k not in COMMON_MENU_KEYS]
        writable_menus = list(allowed_menus)
        hide_financial = False
    else:
        perm_map: dict[str, str] = {}
        if group_data and group_data.allowed_menus:
            for entry in group_data.allowed_menus.split(','):
                entry = entry.strip()
                if not entry:
                    continue
                if ':' in entry:
                    key, perm = entry.rsplit(':', 1)
                else:
                    key, perm = entry, 'rw'
                perm_map[key] = perm
        if user.extra_menus:
            for entry in user.extra_menus.split(','):
                entry = entry.strip()
                if not entry:
                    continue
                if ':' in entry:
                    key, perm = entry.rsplit(':', 1)
                else:
                    key, perm = entry, 'rw'
                perm_map[key] = perm
        allowed_menus = list(perm_map.keys())
        writable_menus = [k for k, v in perm_map.items() if v == 'rw']
        hide_financial = bool(group_data and getattr(group_data, 'hide_financial', False))
        if hasattr(user, 'hide_financial_override') and user.hide_financial_override is not None:
            hide_financial = user.hide_financial_override

    can_manage_priority = bool(
        user.role == 'admin'
        or db.query(UserPriorityPermission)
        .filter(
            UserPriorityPermission.user_id == user.id,
            UserPriorityPermission.is_active.is_(True),
        )
        .first()
    )

    return {
        'user_id': user.id,
        'username': user.username,
        'full_name': user.full_name,
        'user_group': user.user_group,
        'role': user.role,
        'position': user.position or '',
        'allowed_menus': allowed_menus,
        'writable_menus': writable_menus,
        'hide_financial': hide_financial,
        'can_approve_delete': bool(user.role == 'admin' or user.can_approve_delete),
        'can_manage_priority': can_manage_priority,
    }


# ── Bearer 토큰 → in-memory 세션 보조 ────────────────────────────────────────

def _try_token_auth() -> bool:
    """Authorization: Bearer <token> 이 유효하면 세션에 권한 정보를 채우고 True.

    응답에 세션 쿠키가 발급되지 않도록 session.modified 를 False 로 강제하여
    PC 세션 컨텍스트로 새어 나가지 않게 한다. 또한 g.token_auth=True 로 표시한다.
    """
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return False
    token = auth_header[7:].strip()
    if not token:
        return False
    user_id = verify_app_token(token)
    if not user_id:
        return False
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user or not user.is_approved or user.is_active is False:
            return False
        perms = compute_user_permissions(db, user)
    # in-memory 세션 채움. 이후 view 의 session['user_id'] 등 기존 코드가 그대로 동작.
    for k, v in perms.items():
        session[k] = v
    # Flask SecureCookieSessionInterface.should_set_cookie() 는
    #   session.modified or (session.permanent and SESSION_REFRESH_EACH_REQUEST)
    # 일 때만 Set-Cookie 를 응답에 붙인다. 토큰 인증 경로에서는 PC 세션 쿠키가
    # 새어 나가지 않도록 permanent 를 끄고 modified 를 마지막에 False 로 되돌린다.
    # 주의: session.permanent = False 는 내부적으로 session["_permanent"] = False
    # 라서 modified 를 다시 True 로 만든다. 반드시 permanent 먼저 → modified 마지막.
    session.permanent = False
    session.modified = False
    g.token_auth = True
    g.token_user_id = user_id
    return True


class TokenAwareSessionInterface(SecureCookieSessionInterface):
    """Bearer 토큰 인증 요청에서는 응답에 세션 쿠키를 발급하지 않는다.

    Flask 의 save_session 은 모든 after_request hook 이후에 실행되기 때문에
    헤더 단에서 Set-Cookie 를 지우는 방식으로는 막을 수 없다. 인터페이스의
    save_session 자체에서 g.token_auth 플래그를 보고 조기 return 하는 것이
    유일하게 확실한 방법이다.
    """

    def save_session(self, app, session, response):  # type: ignore[override]
        try:
            if g.get('token_auth'):
                return
        except RuntimeError:
            # 앱 컨텍스트 밖이면 그냥 통과
            pass
        return super().save_session(app, session, response)


def init_auth_security(app, csrf=None):
    """앱 시작 시 1회 호출.

    - 세션 인터페이스를 TokenAwareSessionInterface 로 교체
      → Bearer 토큰 인증 경로에서 PC 세션 쿠키가 응답으로 새어 나가는 것을 차단.
    - csrf 가 주어지면 Bearer 토큰 요청을 CSRF 검증에서 면제
      → 모바일 SPA(Bearer 헤더 + 동일출처 아님) 가 폼 토큰 없이 POST 가능.
        PC 세션(쿠키) 기반 POST 는 기존대로 CSRF 보호 유지.
    """
    app.session_interface = TokenAwareSessionInterface()

    if csrf is not None:
        _orig_protect = csrf.protect

        def _patched_protect():
            auth = request.headers.get('Authorization', '')
            if auth.startswith('Bearer '):
                return  # 토큰 인증 경로는 CSRF 검증 우회
            return _orig_protect()

        csrf.protect = _patched_protect


def _is_api_request() -> bool:
    """JSON / XHR / mobile SPA(`/api/app/`, `/mail/api/`) 요청 여부."""
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    if request.headers.get('Authorization', '').startswith('Bearer '):
        return True
    path = request.path or ''
    if path.startswith('/api/') or '/api/' in path:
        return True
    return False


def _auth_failure():
    """API 요청이면 401 JSON, 아니면 로그인 페이지로 redirect."""
    if _is_api_request():
        return jsonify(ok=False, error='로그인이 필요합니다'), 401
    return redirect(url_for('auth.login'))


# ── 데코레이터 ───────────────────────────────────────────────────────────────

def login_required(f):
    """세션 또는 Bearer 토큰 인증 필요."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session and not _try_token_auth():
            return _auth_failure()
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """login_required + role == 'admin'."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session and not _try_token_auth():
            return _auth_failure()
        if session.get('role') != 'admin':
            if _is_api_request():
                return jsonify(ok=False, error='관리자 권한이 필요합니다'), 403
            flash('관리자 권한이 필요합니다.', 'danger')
            return redirect(url_for('dashboard.dashboard_view'))
        return f(*args, **kwargs)
    return decorated


def menu_required(menu_key, write=False):
    """allowed_menus 세션 기반 라우트 접근 제어.
    write=True 또는 GET 이외 요청이면 writable_menus 도 체크.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            g.active_menu_key = menu_key
            if 'user_id' not in session and not _try_token_auth():
                return _auth_failure()
            # 관리자가 전역 비활성화한 메뉴는 누구도(관리자 포함) 접근 불가
            # — admin_only/공통 메뉴는 비활성 대상에서 제외되므로 시스템관리는 항상 접근 가능
            if menu_key in session.get('disabled_menus', []):
                if _is_api_request():
                    return jsonify({'error': '비활성화된 메뉴입니다.'}), 403
                flash('비활성화된 메뉴입니다.', 'warning')
                return redirect(url_for('dashboard.dashboard_view'))
            if session.get('role') == 'admin' or session.get('user_group') == '임원진':
                return f(*args, **kwargs)
            if menu_key in COMMON_MENU_KEYS:
                return f(*args, **kwargs)
            allowed = session.get('allowed_menus', [])
            if menu_key not in allowed:
                if _is_api_request():
                    return jsonify({'error': '접근 권한이 없습니다.'}), 403
                flash('접근 권한이 없습니다.', 'danger')
                return redirect(url_for('dashboard.dashboard_view'))
            if write or request.method != 'GET':
                writable = session.get('writable_menus', [])
                if menu_key not in writable:
                    if _is_api_request():
                        return jsonify({'error': '읽기 전용 권한입니다. 수정할 수 없습니다.'}), 403
                    flash('읽기 전용 권한입니다. 수정할 수 없습니다.', 'warning')
                    return redirect(request.referrer or url_for('dashboard.dashboard_view'))
            return f(*args, **kwargs)
        return decorated
    return decorator
