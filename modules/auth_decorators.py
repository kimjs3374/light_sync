import functools
from flask import session, redirect, url_for, flash, request, jsonify, g


def login_required(f):
    """세션에 user_id가 없으면 로그인 페이지로 redirect"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """login_required + role == 'admin' 체크. 미달 시 dashboard로 redirect"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != 'admin':
            flash('관리자 권한이 필요합니다.', 'danger')
            return redirect(url_for('dashboard.dashboard_view'))
        return f(*args, **kwargs)
    return decorated


def menu_required(menu_key, write=False):
    """allowed_menus 세션 기반 라우트 접근 제어.
    write=True면 writable_menus도 체크하여 쓰기 권한이 없으면 차단.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            g.active_menu_key = menu_key
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if session.get('role') == 'admin' or session.get('user_group') == '임원진':
                return f(*args, **kwargs)
            allowed = session.get('allowed_menus', [])
            if menu_key not in allowed:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': '접근 권한이 없습니다.'}), 403
                flash('접근 권한이 없습니다.', 'danger')
                return redirect(url_for('dashboard.dashboard_view'))
            # 쓰기 권한 체크: write=True이거나 GET 이외 요청이면 쓰기 권한 필요
            if write or request.method != 'GET':
                writable = session.get('writable_menus', [])
                if menu_key not in writable:
                    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'error': '읽기 전용 권한입니다. 수정할 수 없습니다.'}), 403
                    flash('읽기 전용 권한입니다. 수정할 수 없습니다.', 'warning')
                    return redirect(request.referrer or url_for('dashboard.dashboard_view'))
            return f(*args, **kwargs)
        return decorated
    return decorator
