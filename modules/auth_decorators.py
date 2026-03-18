import functools
from flask import session, redirect, url_for, flash


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


def menu_required(menu_key):
    """allowed_menus 세션 기반 라우트 접근 제어"""
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if session.get('role') == 'admin' or session.get('user_group') == '임원진':
                return f(*args, **kwargs)
            allowed = session.get('allowed_menus', [])
            if menu_key in allowed:
                return f(*args, **kwargs)
            flash('접근 권한이 없습니다.', 'danger')
            return redirect(url_for('dashboard.dashboard_view'))
        return decorated
    return decorator
