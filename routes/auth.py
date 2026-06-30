import datetime
import re
import secrets
import string
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify
from modules.auth_decorators import admin_required, login_required
import bcrypt
from modules.db_context import get_db
import json as _json_mod
from modules.models import User, GroupPermission, ProjectDeleteRequest, UserPriorityPermission, DashboardSetting
from modules.models.db import SUPERADMIN_USERNAME
from config import MENU_REGISTRY, COMMON_MENU_KEYS

auth_bp = Blueprint('auth', __name__)

# ── 로그인 실패 잠금 (IP 기반, 5회 실패 → 5분 잠금) ──
_login_failures = {}  # {ip: {'count': int, 'locked_until': datetime}}
_MAX_FAILURES = 5
_LOCKOUT_MINUTES = 5


def _check_login_lockout(ip):
    """잠금 상태면 남은 초 반환, 아니면 None"""
    info = _login_failures.get(ip)
    if not info:
        return None
    if info.get('locked_until') and datetime.datetime.now() < info['locked_until']:
        remaining = (info['locked_until'] - datetime.datetime.now()).seconds
        return remaining
    if info.get('locked_until') and datetime.datetime.now() >= info['locked_until']:
        _login_failures.pop(ip, None)
    return None


def _record_login_failure(ip):
    info = _login_failures.setdefault(ip, {'count': 0, 'locked_until': None})
    info['count'] += 1
    if info['count'] >= _MAX_FAILURES:
        info['locked_until'] = datetime.datetime.now() + datetime.timedelta(minutes=_LOCKOUT_MINUTES)


def _clear_login_failure(ip):
    _login_failures.pop(ip, None)


def _auto_register_mail_account(db, user, plain_password):
    """로그인 시 mail_accounts에 Mailcow 계정이 없으면 자동 등록."""
    try:
        import os
        from sqlalchemy import text as _text
        from modules.services.mail_client import encrypt_password

        mailcow_domain = os.environ.get('MAILCOW_DOMAIN', 'mgnt.kr')
        mailcow_email = f"{user.username}@{mailcow_domain}"
        mailcow_imap_host = os.environ.get('MAILCOW_URL', '127.0.0.1').replace('https://', '').replace('http://', '').split(':')[0]
        mailcow_imap_port = int(os.environ.get('MAILCOW_IMAPS_PORT', '993'))
        mailcow_smtp_port = int(os.environ.get('MAILCOW_SUBMISSION_PORT', '587'))

        existing = db.execute(_text(
            "SELECT id FROM light_sync.mail_accounts WHERE email = :email AND user_id = :uid"
        ), {"email": mailcow_email, "uid": user.id}).fetchone()

        if not existing:
            enc_pw = encrypt_password(plain_password)
            db.execute(_text("""
                INSERT INTO light_sync.mail_accounts
                    (user_id, email, display_name, imap_host, imap_port, smtp_host, smtp_port,
                     username, password_encrypted, use_ssl, is_shared, is_active)
                VALUES
                    (:uid, :email, :name, :imap_host, :imap_port, :smtp_host, :smtp_port,
                     :username, :pw, true, false, true)
            """), {
                "uid": user.id,
                "email": mailcow_email,
                "name": f"{user.full_name or user.username}",
                "imap_host": mailcow_imap_host,
                "imap_port": mailcow_imap_port,
                "smtp_host": mailcow_imap_host,
                "smtp_port": mailcow_smtp_port,
                "username": mailcow_email,
                "pw": enc_pw,
            })
            db.commit()
        else:
            # 이미 있으면 비밀번호만 갱신
            enc_pw = encrypt_password(plain_password)
            db.execute(_text(
                "UPDATE light_sync.mail_accounts SET password_encrypted = :pw WHERE email = :email AND user_id = :uid"
            ), {"pw": enc_pw, "email": mailcow_email, "uid": user.id})
            db.commit()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("mail_accounts 자동등록 실패")


def _validate_password(pw):
    """비밀번호 규칙: 8자 이상, 영문 대/소문자·숫자·특수문자 중 3종 이상"""
    if len(pw) < 8:
        return "비밀번호는 8자 이상 입력해주세요."
    types = sum([
        bool(re.search(r'[a-z]', pw)),
        bool(re.search(r'[A-Z]', pw)),
        bool(re.search(r'[0-9]', pw)),
        bool(re.search(r'[^a-zA-Z0-9]', pw)),
    ])
    if types < 3:
        return "영문 대문자, 소문자, 숫자, 특수문자 중 3종 이상 조합해주세요."
    return None


def _get_limiter():
    """app.py에서 생성한 limiter 참조"""
    return current_app.extensions.get("limiter")


def _is_mobile_ua(ua: str) -> bool:
    """User-Agent가 모바일이면 True. 태블릿(iPad)은 PC 취급."""
    if not ua:
        return False
    ua_l = ua.lower()
    if 'ipad' in ua_l or 'tablet' in ua_l:
        return False
    return any(k in ua_l for k in ('iphone', 'android', 'mobile', 'webos', 'blackberry', 'iemobile', 'opera mini'))


def _should_force_mobile() -> bool:
    """모바일 UA + 세션에 PC 강제 플래그 없을 때 True."""
    if session.get('force_pc'):
        return False
    return _is_mobile_ua(request.headers.get('User-Agent', ''))


def _post_auth_redirect():
    """로그인 성공/이미 로그인 시 PC/모바일 분기 리다이렉트."""
    if request.args.get('pc') == '1':
        session['force_pc'] = True
    # OIDC 등 외부 흐름에서 ?next=/oauth/authorize?... 로 돌아가야 하는 경우
    next_url = request.args.get('next') or request.form.get('next')
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    if _should_force_mobile():
        return redirect('/m/')
    return redirect(url_for('dashboard.dashboard_view'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # ?pc=1 쿼리는 로그인 단계에서도 세션 플래그로 보존
    if request.args.get('pc') == '1':
        session['force_pc'] = True
    elif request.args.get('pc') == '0':
        session.pop('force_pc', None)

    if 'user_id' in session:
        return _post_auth_redirect()

    # GET 요청에서 모바일 UA면 /m/로 (모바일 SPA의 자체 로그인 화면 사용)
    if request.method == 'GET' and _should_force_mobile():
        return redirect('/m/')

    with get_db() as db:
        if request.method == 'POST':
            client_ip = request.remote_addr or '0.0.0.0'
            lockout_sec = _check_login_lockout(client_ip)
            if lockout_sec:
                flash(f"로그인 시도 초과. {lockout_sec // 60 + 1}분 후 다시 시도하세요.", "danger")
                return redirect(url_for('auth.login'))

            login_id = request.form.get('username')
            login_pw = request.form.get('password')
            user = db.query(User).filter(User.username == login_id).first()

            if user and bcrypt.checkpw(login_pw.encode('utf-8'), user.password_hash.encode('utf-8')):
                if user.is_approved:
                    if user.is_active is False:
                        flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "danger")
                        return redirect(url_for('auth.login'))

                    group_data = db.query(GroupPermission).filter(GroupPermission.group_name == user.user_group).first()
                    # 권한 우선순위: 관리자 > 개인권한 > 그룹권한
                    if user.role == 'admin':
                        # 관리자는 모든 메뉴 RW + 금액 표시 (그룹 권한 무시)
                        from config import MENU_REGISTRY, COMMON_MENU_KEYS
                        allowed_menus = [k for k in MENU_REGISTRY if k not in COMMON_MENU_KEYS]
                        writable_menus = list(allowed_menus)
                        hide_financial = False
                    else:
                        # 1단계: 그룹 권한을 base로 깔기
                        perm_map = {}  # {menu_key: 'r' or 'rw'}
                        if group_data and group_data.allowed_menus:
                            for entry in group_data.allowed_menus.split(","):
                                entry = entry.strip()
                                if not entry:
                                    continue
                                if ':' in entry:
                                    key, perm = entry.rsplit(':', 1)
                                else:
                                    key, perm = entry, 'rw'
                                perm_map[key] = perm
                        # 2단계: 개인권한으로 override (그룹 r → 개인 rw 가능)
                        if user.extra_menus:
                            for entry in user.extra_menus.split(","):
                                entry = entry.strip()
                                if not entry:
                                    continue
                                if ':' in entry:
                                    key, perm = entry.rsplit(':', 1)
                                else:
                                    key, perm = entry, 'rw'
                                perm_map[key] = perm  # 개인이 그룹 덮어쓰기
                        # 3단계: allowed / writable 리스트 생성
                        allowed_menus = list(perm_map.keys())
                        writable_menus = [k for k, v in perm_map.items() if v == 'rw']
                        # 금액 가시성: 그룹 기본 → 개인 override 가능
                        hide_financial = bool(group_data and getattr(group_data, 'hide_financial', False))
                        if hasattr(user, 'hide_financial_override') and user.hide_financial_override is not None:
                            hide_financial = user.hide_financial_override
                    can_manage_priority = bool(
                        user.role == 'admin'
                        or db.query(UserPriorityPermission).filter(
                            UserPriorityPermission.user_id == user.id,
                            UserPriorityPermission.is_active.is_(True)
                        ).first()
                    )

                    # Mailcow 비밀번호 동기화 + 웹메일 계정 자동 등록
                    from modules.services.mailcow_api import sync_password as _mc_sync
                    _mc_sync(user.username, login_pw)
                    _auto_register_mail_account(db, user, login_pw)

                    # Mattermost 자격증명 + 이름/직책 동기화 (실패해도 ERP 로그인은 계속)
                    try:
                        from modules.services.mattermost_api import sync_password as _mm_sync
                        _mm_sync(
                            user.username, login_pw,
                            email=user.email,
                            full_name=user.full_name,
                            position=user.position or None,
                            department=user.user_group or None,
                        )
                    except Exception:
                        pass

                    session.update({
                        'user_id': user.id, 'username': user.username, 'full_name': user.full_name,
                        'user_group': user.user_group, 'role': user.role, 'position': user.position or '',
                        'allowed_menus': allowed_menus,
                        'writable_menus': writable_menus,
                        'hide_financial': hide_financial,
                        'can_approve_delete': bool(user.role == 'admin' or user.can_approve_delete),
                        'can_manage_priority': can_manage_priority,
                    })
                    _clear_login_failure(client_ip)
                    # 비밀번호 초기화 후 강제 변경
                    if getattr(user, 'must_change_password', False):
                        session['must_change_password'] = True
                        return redirect(url_for('auth.force_change_password'))
                    return _post_auth_redirect()
                else:
                    flash("승인 대기 중입니다.", "warning")
            else:
                _record_login_failure(client_ip)
                flash("아이디 또는 비밀번호 오류", "danger")

        groups = [g.group_name for g in db.query(GroupPermission).filter(GroupPermission.group_name != "최고관리자").all()]
        return render_template('login.html', groups=groups)


@auth_bp.route('/find_username', methods=['POST'])
def find_username():
    full_name = (request.form.get('find_name') or '').strip()
    contact = (request.form.get('find_contact') or '').strip()

    if not full_name or not contact:
        flash("이름과 연락처(또는 이메일)를 입력해주세요.", "danger")
        return redirect(url_for('auth.login'))

    with get_db() as db:
        from sqlalchemy import or_
        user = db.query(User).filter(
            User.full_name == full_name,
            or_(User.phone_number == contact, User.email == contact)
        ).first()
        if user:
            # 아이디 일부 마스킹 (앞2자 + ***)
            uid = user.username
            masked = uid[:2] + '*' * max(1, len(uid) - 2) if len(uid) > 2 else uid[0] + '*'
            flash(f"아이디: {masked}", "success")
        else:
            flash("일치하는 계정을 찾을 수 없습니다.", "danger")
    return redirect(url_for('auth.login'))


@auth_bp.route('/find_password', methods=['POST'])
def find_password():
    username = (request.form.get('reset_username') or '').strip()
    email = (request.form.get('reset_email') or '').strip()

    if not username or not email:
        flash("아이디와 이메일을 입력해주세요.", "danger")
        return redirect(url_for('auth.login'))

    with get_db() as db:
        user = db.query(User).filter(User.username == username, User.email == email).first()
        if not user:
            flash("아이디와 이메일이 일치하는 계정이 없습니다.", "danger")
            return redirect(url_for('auth.login'))

        # 임시 비밀번호 생성 (8자리 영숫자)
        temp_pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        hashed_pw = bcrypt.hashpw(temp_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user.password_hash = hashed_pw
        user.must_change_password = True
        db.commit()

        # 이메일 발송
        from modules.services.email_sender import send_email_with_attachments
        result = send_email_with_attachments(
            to_email=email,
            subject='[Light-Sync ERP] 비밀번호 초기화 안내',
            body_text=f'{user.full_name}님 안녕하세요.\n\n'
                      f'비밀번호가 초기화되었습니다.\n\n'
                      f'임시 비밀번호: {temp_pw}\n\n'
                      f'로그인 후 반드시 비밀번호를 변경해주세요.\n\n'
                      f'- 매그나텍 ERP',
            from_email='dontreplyme@mgnt.kr',
            from_name='매그나텍 ERP'
        )
        if result.get('success'):
            flash("임시 비밀번호가 이메일로 발송되었습니다.", "success")
        else:
            flash(f"이메일 발송 실패: {result.get('message', '')}", "danger")
    return redirect(url_for('auth.login'))


@auth_bp.route('/force_change_password', methods=['GET', 'POST'])
def force_change_password():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not session.get('must_change_password'):
        return redirect(url_for('dashboard.dashboard_view'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        pw_err = _validate_password(new_password)
        if pw_err:
            flash(pw_err, "danger")
            return redirect(url_for('auth.force_change_password'))
        if new_password != confirm_password:
            flash("비밀번호가 일치하지 않습니다.", "danger")
            return redirect(url_for('auth.force_change_password'))

        with get_db() as db:
            user = db.get(User, session['user_id'])
            if user:
                hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                user.password_hash = hashed_pw
                user.must_change_password = False
                db.commit()
                session.pop('must_change_password', None)
                flash("비밀번호가 변경되었습니다.", "success")
                return redirect(url_for('dashboard.dashboard_view'))

    return render_template('force_change_password.html')


@auth_bp.route('/register', methods=['POST'])
def register():
    username = (request.form.get('new_username') or '').strip()
    password = request.form.get('new_password') or ''
    fullname = (request.form.get('new_fullname') or '').strip()
    phone = (request.form.get('new_phone') or '').strip()
    email = (request.form.get('new_email') or '').strip()
    group = request.form.get('new_group') or ''

    # 입력값 검증
    errors = []
    if len(username) < 3:
        errors.append("아이디는 3자 이상 입력해주세요.")
    pw_err = _validate_password(password)
    if pw_err:
        errors.append(pw_err)
    if not fullname:
        errors.append("이름을 입력해주세요.")
    if not email:
        errors.append("이메일을 입력해주세요.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for('auth.login'))

    with get_db() as db:
        # 중복 체크
        if db.query(User).filter(User.username == username).first():
            flash("이미 존재하는 아이디입니다.", "danger")
            return redirect(url_for('auth.login'))

        try:
            hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.add(User(
                username=username, password_hash=hashed_pw,
                full_name=fullname, phone_number=phone,
                email=email or None,
                user_group=group, is_approved=False
            ))
            db.commit()
            flash("가입 신청 완료!", "success")
        except Exception:
            db.rollback()
            current_app.logger.exception('register failed for username=%s', username)
            flash("가입 처리 중 오류가 발생했습니다.", "danger")
    return redirect(url_for('auth.login'))


@auth_bp.route('/admin_settings')
@admin_required
def admin_settings():
    with get_db() as db:
        GROUP_ORDER = ['임원진', '관리부', '영업부', '생산부']
        POSITION_ORDER = ['대표이사', '전무', '상무', '이사', '부장', '차장', '과장', '대리', '주임', '사원']
        def _sort_key(u):
            gi = GROUP_ORDER.index(u.user_group) if u.user_group in GROUP_ORDER else len(GROUP_ORDER)
            pi = POSITION_ORDER.index(u.position) if u.position in POSITION_ORDER else len(POSITION_ORDER)
            return (gi, pi, u.full_name)

        pending = db.query(User).filter(User.is_approved == False).all()
        users = db.query(User).filter(User.is_approved == True).all()
        users.sort(key=_sort_key)
        priority_permissions = db.query(UserPriorityPermission).filter(UserPriorityPermission.is_active.is_(True)).all()
        priority_user_ids = {row.user_id for row in priority_permissions}
        for user in users:
            user.can_manage_priority = bool(user.role == 'admin' or user.id in priority_user_ids)
        delete_requests = db.query(ProjectDeleteRequest).order_by(ProjectDeleteRequest.created_at.desc()).all()

        # 통계 데이터
        total_count = len(users)
        active_count = sum(1 for u in users if u.is_active)
        inactive_count = total_count - active_count
        pending_count = len(pending)

        # 부서 목록 (필터용)
        groups = sorted(set(u.user_group for u in users if u.user_group),
                        key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER))

        # 그룹별 메뉴 권한 데이터 (부서 순서 고정)
        all_gp = db.query(GroupPermission).all()
        group_permissions = sorted(all_gp,
            key=lambda g: GROUP_ORDER.index(g.group_name) if g.group_name in GROUP_ORDER else len(GROUP_ORDER))
        group_menu_data = []
        for gp in group_permissions:
            current_menus = [m.strip() for m in gp.allowed_menus.split(",") if m.strip()] if gp.allowed_menus else []
            # R/RW map 생성: {key: 'rw'} 또는 레거시 배열 → 전부 rw
            menus_rw = {}
            for entry in current_menus:
                if ':' in entry:
                    k, p = entry.rsplit(':', 1)
                    menus_rw[k] = p
                else:
                    menus_rw[entry] = 'rw'
            group_menu_data.append({
                "group_name": gp.group_name,
                "current_menus": list(menus_rw.keys()),
                "current_menus_rw": menus_rw,
                "hide_financial": bool(getattr(gp, 'hide_financial', False)),
            })

        configurable_menus = [
            {"key": k, "label": v["label"], "group": v["group"]}
            for k, v in MENU_REGISTRY.items()
            if k not in COMMON_MENU_KEYS and not v.get("admin_only")
        ]

        position_choices = ['대표이사', '전무', '상무', '이사', '부장', '차장', '과장', '대리', '주임', '사원']

        # 최초 admin 계정 확인 (프로젝트 초기화 탭 표시 여부)
        # admin 권한이면 모두 노출 (G2B동기화/홈택스연동/프로젝트초기화 탭). 페이지는 이미 @admin_required.
        is_superadmin = session.get('role') == 'admin'

        # 운영설정 + 메뉴 순서
        from modules.services.dashboard_actions import get_dashboard_setting_int
        production_lead_days = get_dashboard_setting_int(db, 'production_lead_days', 7)

        # 메뉴 순서
        _mo_row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_order').first()
        menu_order_data = _json_mod.loads(_mo_row.setting_value) if _mo_row else {}

        # 메뉴 활성/비활성 (전역)
        from modules.services.dashboard_actions import get_disabled_menus
        from config import PROTECTED_MENU_KEYS
        disabled_menus = sorted(get_disabled_menus(db))

        # 토글 가능 메뉴: 핵심(dashboard)/admin_only 제외한 전 메뉴 (공통메뉴 포함)
        toggleable_menus = [
            {"key": k, "label": v["label"], "group": v["group"]}
            for k, v in MENU_REGISTRY.items()
            if k not in PROTECTED_MENU_KEYS and not v.get("admin_only")
        ]
        if menu_order_data:
            _k2g_t = {}
            for _gn in menu_order_data.get('groups', []):
                for _mk in menu_order_data.get(_gn, []):
                    _k2g_t[_mk] = _gn
            for _m in toggleable_menus:
                if _m["key"] in _k2g_t:
                    _m["group"] = _k2g_t[_m["key"]]

        # menu_order 기준 그룹 이동 반영 (configurable_menus + 권한관리에 적용)
        if menu_order_data:
            _key_to_group = {}
            for _gn in menu_order_data.get('groups', []):
                for _mk in menu_order_data.get(_gn, []):
                    _key_to_group[_mk] = _gn
            for _m in configurable_menus:
                if _m["key"] in _key_to_group:
                    _m["group"] = _key_to_group[_m["key"]]

        # ── 공지관리 데이터 ──
        from modules.models import DashboardNotice
        from modules.dashboard_utils import build_auto_alert_items
        notices = db.query(DashboardNotice).order_by(DashboardNotice.sort_order.asc(), DashboardNotice.id.asc()).all()
        _today = datetime.date.today()
        _week_later = _today + datetime.timedelta(days=7)
        auto_notice_items = build_auto_alert_items(db, _today, _week_later)
        global_display_seconds = max(2, get_dashboard_setting_int(db, 'billboard_global_seconds', 6))

        # ── 제품카탈로그 데이터 ──
        from modules.models import ProductCatalog
        catalog_total = db.query(ProductCatalog).count()
        catalog_missing = db.query(ProductCatalog).filter(ProductCatalog.unit_price.is_(None)).count()
        catalog_last_sync = db.query(ProductCatalog.last_synced_at).filter(
            ProductCatalog.last_synced_at.isnot(None)
        ).order_by(ProductCatalog.last_synced_at.desc()).first()
        catalog_stats = {
            'total': catalog_total,
            'missing_price': catalog_missing,
            'has_price': catalog_total - catalog_missing,
            'last_synced': catalog_last_sync[0].strftime('%Y-%m-%d %H:%M') if catalog_last_sync and catalog_last_sync[0] else '-',
        }
        # 카탈로그 목록 (최근 30건)
        catalog_items = db.query(ProductCatalog).order_by(ProductCatalog.krn_prdct_nm).limit(30).all()
        catalog_pagination = {'page': 1, 'per_page': 30, 'total_pages': max(1, (catalog_total + 29) // 30)}
        catalog_filters = {'q': '', 'price_source': '', 'method': ''}

        # ── 챗봇 권한 데이터 ──
        from sqlalchemy import text as _text
        from modules.services.erp_tools import ALL_TOOLS as _ALL_TOOLS
        chatbot_users = db.query(User).order_by(User.full_name).all()
        _cb_rows = db.execute(
            _text("SELECT erp_username, allowed_tools, COALESCE(channel_enabled, false) FROM chatbot_permissions")
        ).fetchall()
        perm_map = {r[0]: r[1].split(",") if r[1] else [] for r in _cb_rows}
        channel_map = {r[0]: bool(r[2]) for r in _cb_rows}
        _cb_default = ",".join(t[0] for t in _ALL_TOOLS)

        # 챗봇 카테고리별 그룹핑
        import re as _re, inspect as _inspect
        from modules.services import erp_tools as _erp_tools_mod
        _src = _inspect.getsource(_erp_tools_mod)
        _tool_groups = []
        _cur_cat = "기타"
        _tool_set = {t[0] for t in _ALL_TOOLS}
        _cat_tools = []
        for _line in _src.splitlines():
            _m = _re.match(r'\s*#\s*(.+?)\s*\(\d+\)', _line)
            if _m:
                if _cat_tools:
                    _tool_groups.append((_cur_cat, _cat_tools))
                _cur_cat = _m.group(1).strip()
                _cat_tools = []
                continue
            _m2 = _re.match(r'\s*\("(\w+)"', _line)
            if _m2 and _m2.group(1) in _tool_set:
                _name = _m2.group(1)
                _label = next((t[1] for t in _ALL_TOOLS if t[0] == _name), _name)
                _group = next((t[2] for t in _ALL_TOOLS if t[0] == _name), "전체")
                _cat_tools.append((_name, _label, _group))
        if _cat_tools:
            _tool_groups.append((_cur_cat, _cat_tools))

        # 챗봇 프리셋
        import json as _json
        try:
            _preset_rows = db.execute(_text("SELECT name, tools_json, channel_enabled FROM chatbot_presets ORDER BY name")).fetchall()
        except Exception:
            _preset_rows = []
        chatbot_presets = [{"name": r[0], "tools": _json.loads(r[1]) if r[1] else [], "channel": bool(r[2])} for r in _preset_rows]
        presets_map = {p["name"]: p for p in chatbot_presets}

        return render_template('admin_settings.html',
            pending=pending, users=users, delete_requests=delete_requests,
            total_count=total_count, active_count=active_count,
            inactive_count=inactive_count, pending_count=pending_count,
            groups=groups,
            group_menu_data=group_menu_data,
            configurable_menus=configurable_menus,
            position_choices=position_choices,
            is_superadmin=is_superadmin,
            current_admin_id=session.get('user_id'),
            production_lead_days=production_lead_days,
            # 공지관리
            notices=notices, auto_notice_items=auto_notice_items,
            global_display_seconds=global_display_seconds,
            # 제품카탈로그
            catalog_items=catalog_items, catalog_stats=catalog_stats,
            catalog_pagination=catalog_pagination, catalog_filters=catalog_filters,
            is_admin=True,
            # 챗봇 권한
            chatbot_users=chatbot_users, perm_map=perm_map, channel_map=channel_map,
            all_tools=_ALL_TOOLS, default_tools=_cb_default.split(","),
            tool_groups=_tool_groups, chatbot_presets=chatbot_presets,
            presets_map=presets_map,
            menu_order_data=menu_order_data,
            disabled_menus=disabled_menus,
            toggleable_menus=toggleable_menus)


@auth_bp.route('/admin/update_ops_setting', methods=['POST'])
@admin_required
def update_ops_setting():
    key = (request.form.get('key') or '').strip()
    value = (request.form.get('value') or '').strip()
    allowed_keys = {'production_lead_days'}
    if key not in allowed_keys:
        return jsonify({'ok': False, 'error': f'허용되지 않는 설정: {key}'}), 400
    if not value:
        return jsonify({'ok': False, 'error': '값을 입력해주세요.'}), 400
    with get_db() as db:
        from modules.services.dashboard_actions import set_dashboard_setting_int
        set_dashboard_setting_int(db, key, int(value))
        db.commit()
    return jsonify({'ok': True})


@auth_bp.route('/toggle_admin/<int:user_id>', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    if user_id == session.get('user_id'):
        flash('자기 자신의 권한은 변경할 수 없습니다.', 'warning')
        return redirect(url_for('auth.admin_settings'))
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            flash('사용자를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('auth.admin_settings'))
        user.role = 'user' if user.role == 'admin' else 'admin'
        db.commit()
        flash(f'{user.full_name}님의 권한을 {user.role}로 변경했습니다.', 'success')
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/update_position/<int:user_id>', methods=['POST'])
@admin_required
def update_position(user_id):
    position = (request.form.get('position') or '').strip()
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify({'ok': False, 'error': '사용자 없음'}), 404
        user.position = position or None
        db.commit()
    return jsonify({'ok': True})


@auth_bp.route('/admin/update_user_group/<int:user_id>', methods=['POST'])
@admin_required
def update_user_group(user_id):
    new_group = (request.form.get('user_group') or '').strip()
    if not new_group:
        return jsonify({'ok': False, 'error': '그룹명 필요'}), 400
    with get_db() as db:
        gp = db.query(GroupPermission).filter_by(group_name=new_group).first()
        if not gp:
            return jsonify({'ok': False, 'error': '존재하지 않는 그룹'}), 400
        user = db.get(User, user_id)
        if not user:
            return jsonify({'ok': False, 'error': '사용자 없음'}), 404
        user.user_group = new_group
        user.extra_menus = None
        db.commit()
    return jsonify({'ok': True})


@auth_bp.route('/toggle_delete_approver/<int:user_id>', methods=['POST'])
@admin_required
def toggle_delete_approver(user_id):

    with get_db() as db:
        user = db.get(User, user_id)
        if user:
            target = request.form.get('can_approve_delete') == '1'
            user.can_approve_delete = bool(target)
            db.commit()
            flash(f"{user.full_name} 삭제승인 권한이 {'활성화' if target else '해제'}되었습니다.", 'success')
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/toggle_priority_manager/<int:user_id>', methods=['POST'])
@admin_required
def toggle_priority_manager(user_id):

    with get_db() as db:
        user = db.get(User, user_id)
        if user:
            if user.role == 'admin':
                flash('관리자는 기본적으로 우선순위 지정 권한이 있습니다.', 'info')
            else:
                target = request.form.get('can_manage_priority') == '1'
                perm = db.query(UserPriorityPermission).filter(UserPriorityPermission.user_id == user_id).first()
                if perm:
                    perm.is_active = bool(target)
                    perm.granted_by_user_id = session.get('user_id')
                    perm.granted_by_name = session.get('full_name') or '관리자'
                elif target:
                    db.add(UserPriorityPermission(
                        user_id=user_id,
                        is_active=True,
                        granted_by_user_id=session.get('user_id'),
                        granted_by_name=session.get('full_name') or '관리자',
                    ))
                db.commit()
                flash(f"{user.full_name} 우선순위 지정 권한이 {'활성화' if target else '해제'}되었습니다.", 'success')
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/toggle_user_active/<int:user_id>', methods=['POST'])
@admin_required
def toggle_user_active(user_id):

    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            flash("사용자를 찾을 수 없습니다.", "warning")
            return redirect(url_for('auth.admin_settings'))

        if user.role == 'admin':
            flash("관리자 계정은 비활성화할 수 없습니다.", "warning")
            return redirect(url_for('auth.admin_settings'))

        if session.get('user_id') == user.id:
            flash("본인 계정은 비활성화할 수 없습니다.", "warning")
            return redirect(url_for('auth.admin_settings'))

        target = request.form.get('is_active') == '1'
        reason = (request.form.get('deactivated_reason') or '').strip()
        user.is_active = bool(target)
        if user.is_active:
            user.deactivated_at = None
            user.deactivated_reason = None
            flash(f"{user.full_name} 계정이 재활성화되었습니다.", "success")
        else:
            user.deactivated_at = datetime.datetime.now()
            user.deactivated_reason = reason if reason else '퇴사/비활성 처리'
            flash(f"{user.full_name} 계정이 비활성화되었습니다.", "warning")

        db.commit()
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/approve_user/<int:user_id>', methods=['POST'])
@admin_required
def approve_user(user_id):
    with get_db() as db:
        user = db.get(User, user_id)
        if user:
            user.is_approved = True
            # Mailcow 메일박스 자동 생성
            from modules.services.mailcow_api import create_mailbox as _mc_create
            _mc_create(user.username, user.full_name, "Mgnt2026!")
            # 챗봇 권한 초기값: 일반직원 프리셋 적용
            from sqlalchemy import text as _text
            import json as _json
            _preset_row = db.execute(_text("SELECT tools_json FROM chatbot_presets WHERE name = '일반직원'")).fetchone()
            _default_tools = ','.join(_json.loads(_preset_row[0])) if _preset_row and _preset_row[0] else ''
            db.execute(_text("""
                INSERT INTO chatbot_permissions (erp_username, allowed_tools, channel_enabled)
                VALUES (:u, :t, false)
                ON CONFLICT (erp_username) DO NOTHING
            """), {"u": user.username, "t": _default_tools})
            db.commit()
            flash(f"{user.full_name} 계정이 승인되었습니다.", "success")
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/reject_user/<int:user_id>', methods=['POST'])
@admin_required
def reject_user(user_id):
    with get_db() as db:
        user = db.get(User, user_id)
        if user and user.role != 'admin':
            db.delete(user)
            db.commit()
            flash("가입 신청이 거절(삭제)되었습니다.", "warning")
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not current_password or not new_password:
        flash("모든 항목을 입력해주세요.", "danger")
        return redirect(request.referrer or url_for('dashboard.dashboard_view'))

    if new_password != confirm_password:
        flash("새 비밀번호가 일치하지 않습니다.", "danger")
        return redirect(request.referrer or url_for('dashboard.dashboard_view'))

    pw_err = _validate_password(new_password)
    if pw_err:
        flash(pw_err, "danger")
        return redirect(request.referrer or url_for('dashboard.dashboard_view'))

    with get_db() as db:
        user = db.get(User, session['user_id'])
        if not user:
            flash("사용자를 찾을 수 없습니다.", "danger")
            return redirect(request.referrer or url_for('dashboard.dashboard_view'))

        if not bcrypt.checkpw(current_password.encode('utf-8'), user.password_hash.encode('utf-8')):
            flash("현재 비밀번호가 올바르지 않습니다.", "danger")
            return redirect(request.referrer or url_for('dashboard.dashboard_view'))

        hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user.password_hash = hashed_pw
        db.commit()
        flash("비밀번호가 변경되었습니다.", "success")
    return redirect(request.referrer or url_for('dashboard.dashboard_view'))


@auth_bp.route('/my_profile', methods=['GET'])
@login_required
def my_profile():
    with get_db() as db:
        user = db.get(User, session['user_id'])
        if not user:
            flash("사용자를 찾을 수 없습니다.", "danger")
            return redirect(url_for('dashboard.dashboard_view'))
        return render_template('my_profile.html', user=user)


@auth_bp.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    full_name = (request.form.get('full_name') or '').strip()
    phone_number = (request.form.get('phone_number') or '').strip()
    email = (request.form.get('email') or '').strip()

    if not full_name:
        flash("이름을 입력해주세요.", "danger")
        return redirect(url_for('auth.my_profile'))
    if not email:
        flash("이메일을 입력해주세요.", "danger")
        return redirect(url_for('auth.my_profile'))

    with get_db() as db:
        user = db.get(User, session['user_id'])
        if not user:
            flash("사용자를 찾을 수 없습니다.", "danger")
            return redirect(url_for('dashboard.dashboard_view'))
        user.full_name = full_name
        user.phone_number = phone_number or None
        user.email = email or None
        db.commit()
        session['full_name'] = full_name
        flash("정보가 저장되었습니다.", "success")
    return redirect(url_for('auth.my_profile'))


@auth_bp.route('/admin/update_user_info/<int:user_id>', methods=['POST'])
@admin_required
def update_user_info(user_id):
    full_name = (request.form.get('full_name') or '').strip()
    phone_number = (request.form.get('phone_number') or '').strip()
    email = (request.form.get('email') or '').strip()

    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            return jsonify({'ok': False, 'error': '사용자 없음'}), 404
        if full_name:
            user.full_name = full_name
        user.phone_number = phone_number or None
        user.email = email or None
        db.commit()
    return jsonify({'ok': True})


@auth_bp.route('/reset_password/<int:user_id>', methods=['POST'])
@admin_required
def reset_password(user_id):
    DEFAULT_PASSWORD = '3925508'

    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            flash("사용자를 찾을 수 없습니다.", "danger")
            return redirect(url_for('auth.admin_settings'))

        hashed_pw = bcrypt.hashpw(DEFAULT_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user.password_hash = hashed_pw
        user.must_change_password = True
        db.commit()
        flash(f"{user.full_name} 비밀번호가 초기화되었습니다. (다음 로그인 시 변경 필수)", "success")
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/admin/update_group_menus', methods=['POST'])
@admin_required
def update_group_menus():
    """그룹별 allowed_menus 업데이트"""
    group_name = request.form.get('group_name', '').strip()
    selected_menus = request.form.getlist('menus')

    if not group_name:
        flash('그룹을 선택해주세요.', 'danger')
        return redirect(url_for('auth.admin_settings'))

    with get_db() as db:
        group = db.query(GroupPermission).filter(
            GroupPermission.group_name == group_name
        ).first()
        if not group:
            flash('존재하지 않는 그룹입니다.', 'danger')
            return redirect(url_for('auth.admin_settings'))

        group.allowed_menus = ",".join(selected_menus)
        db.commit()
        flash(f'{group_name} 메뉴 권한이 업데이트되었습니다.', 'success')

    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/admin/update_user_extra_menus', methods=['POST'])
@admin_required
def update_user_extra_menus():
    """개인 추가 메뉴 권한 업데이트"""
    user_id = request.form.get('user_id', type=int)
    selected_menus = request.form.getlist('extra_menus')

    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            flash('사용자를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('auth.admin_settings'))

        user.extra_menus = ",".join(selected_menus) if selected_menus else None
        db.commit()
        flash(f'{user.full_name} 추가 메뉴 권한이 업데이트되었습니다.', 'success')

    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/admin/menu_perms')
@admin_required
def menu_perms():
    """메뉴 권한 관리 전용 페이지"""
    with get_db() as db:
        GROUP_ORDER = ['임원진', '관리부', '영업부', '생산부']
        POSITION_ORDER = ['대표이사', '전무', '상무', '이사', '부장', '차장', '과장', '대리', '주임', '사원']
        def _sort_key(u):
            gi = GROUP_ORDER.index(u.user_group) if u.user_group in GROUP_ORDER else len(GROUP_ORDER)
            pi = POSITION_ORDER.index(u.position) if u.position in POSITION_ORDER else len(POSITION_ORDER)
            return (gi, pi, u.full_name)
        users = db.query(User).filter(User.is_approved == True).all()
        users.sort(key=_sort_key)
        group_permissions = db.query(GroupPermission).all()
        group_menu_data = []
        for gp in group_permissions:
            current_menus = [m.strip() for m in gp.allowed_menus.split(",") if m.strip()] if gp.allowed_menus else []
            group_menu_data.append({"group_name": gp.group_name, "current_menus": current_menus})
        configurable_menus = [
            {"key": k, "label": v["label"], "group": v["group"]}
            for k, v in MENU_REGISTRY.items()
            if k not in COMMON_MENU_KEYS and not v.get("admin_only")
        ]
        # menu_order 기준 그룹 이동 반영
        _mo2 = db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_order').first()
        if _mo2:
            _ord2 = _json_mod.loads(_mo2.setting_value)
            _k2g = {}
            for _gn in _ord2.get('groups', []):
                for _mk in _ord2.get(_gn, []):
                    _k2g[_mk] = _gn
            for _m in configurable_menus:
                if _m["key"] in _k2g:
                    _m["group"] = _k2g[_m["key"]]
    return render_template('menu_perms.html',
        users=users, group_menu_data=group_menu_data, configurable_menus=configurable_menus)


@auth_bp.route('/admin/api/group_menus', methods=['POST'])
@admin_required
def api_update_group_menus():
    """그룹 메뉴 권한 JSON API (R/RW 지원)"""
    body = request.get_json(silent=True) or {}
    group_name = body.get('group_name', '').strip()
    menus_rw = body.get('menus_rw', {})   # {contract: 'rw', sales: 'r'}
    menus = body.get('menus', [])          # 레거시 호환
    hide_financial = body.get('hide_financial', None)
    if not group_name:
        return jsonify({'success': False, 'error': '그룹명 필요'}), 400
    with get_db() as db:
        group = db.query(GroupPermission).filter(GroupPermission.group_name == group_name).first()
        if not group:
            return jsonify({'success': False, 'error': '그룹 없음'}), 404
        if menus_rw:
            # R/RW 형식: "contract:rw,sales:r,inventory:r"
            parts = [f"{k}:{v}" for k, v in menus_rw.items()]
            group.allowed_menus = ",".join(parts)
        else:
            group.allowed_menus = ",".join(menus)
        if hide_financial is not None:
            group.hide_financial = bool(hide_financial)
        db.commit()
    return jsonify({'success': True})


@auth_bp.route('/admin/api/user_extra_menus', methods=['POST'])
@admin_required
def api_update_user_extra_menus():
    """개인 추가 메뉴 권한 JSON API (R/RW override 지원)"""
    body = request.get_json(silent=True) or {}
    user_id = body.get('user_id')
    extra_menus = body.get('extra_menus', [])       # 레거시: ["key1","key2"]
    extra_menus_rw = body.get('extra_menus_rw', {})  # 신규: {"key1":"rw","key2":"r"}
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id 필요'}), 400
    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            return jsonify({'success': False, 'error': '사용자 없음'}), 404
        if extra_menus_rw:
            # R/RW 형식: "sales:rw,inventory:r"
            parts = [f"{k}:{v}" for k, v in extra_menus_rw.items()]
            user.extra_menus = ",".join(parts) if parts else None
        else:
            user.extra_menus = ",".join(extra_menus) if extra_menus else None
        db.commit()
    return jsonify({'success': True})


@auth_bp.route('/admin/api/user_hide_financial/<int:user_id>', methods=['POST'])
@admin_required
def api_update_user_hide_financial(user_id):
    """개인별 금액 숨김 override API"""
    body = request.get_json(silent=True) or {}
    override_val = body.get('hide_financial_override')  # True/False/None
    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            return jsonify({'success': False, 'error': '사용자 없음'}), 404
        user.hide_financial_override = override_val
        db.commit()
    return jsonify({'success': True})


@auth_bp.route('/admin/reset_projects', methods=['POST'])
@admin_required
def reset_projects():
    """프로젝트 전체 초기화 — 프로젝트 + 연관 데이터 삭제, 마스터 데이터 유지"""
    # admin 권한이면 허용(페이지는 @admin_required). 삭제 안전장치는 아래 확인문구로 유지.
    confirm_text = (request.form.get('confirm_text') or '').strip()
    if confirm_text != '프로젝트초기화':
        flash('확인 문구가 일치하지 않습니다. "프로젝트초기화"를 정확히 입력해주세요.', 'danger')
        return redirect(url_for('auth.admin_settings') + '#resetPane')

    from modules.models import (
        Project, Contract, ContractItem, Delivery, MaterialOrder,
        ProductionProcess, ProductionDailyLog, HistoryLog,
        Contact, Drawing, Warranty, WarrantyCase, SportsModule,
        ProjectDeleteRequest, ProjectPhoto, TaxInvoice,
        PurchaseOrder, PurchaseOrderItem, Receiving, ReceivingItem,
        StockMovement, Notification,
    )
    from modules.models.entities import ProjectPriorityOverride

    with get_db() as db:
        # 하위 → 상위 순서로 삭제 (FK 의존관계)
        counts = {}

        # 생산
        counts['production_daily_logs'] = db.query(ProductionDailyLog).delete()
        counts['production_processes'] = db.query(ProductionProcess).delete()

        # 입고 (발주서 연결)
        counts['receiving_items'] = db.query(ReceivingItem).delete()
        counts['receivings'] = db.query(Receiving).delete()

        # 발주 (email_history FK 먼저)
        from modules.models import EmailHistory, PurchaseOrderHistory
        counts['email_history'] = db.query(EmailHistory).delete()
        counts['po_history'] = db.query(PurchaseOrderHistory).delete()
        counts['purchase_order_items'] = db.query(PurchaseOrderItem).delete()
        counts['purchase_orders'] = db.query(PurchaseOrder).delete()

        # 자재
        counts['material_orders'] = db.query(MaterialOrder).delete()

        # 재고 변동 이력
        counts['stock_movements'] = db.query(StockMovement).delete()

        # 하자 (하위 FK 먼저)
        from modules.models import WarrantyCaseLog
        counts['warranty_case_logs'] = db.query(WarrantyCaseLog).delete()
        counts['warranty_cases'] = db.query(WarrantyCase).delete()
        counts['warranties'] = db.query(Warranty).delete()

        # 납품 (하위 FK 먼저)
        from modules.models import DeliverySplit, DeliveryPhoto
        from sqlalchemy import text
        counts['delivery_contract_files'] = db.execute(text('DELETE FROM delivery_contract_files')).rowcount
        counts['delivery_documents'] = db.execute(text('DELETE FROM delivery_documents')).rowcount
        counts['delivery_photos'] = db.query(DeliveryPhoto).delete()
        counts['delivery_splits'] = db.query(DeliverySplit).delete()
        counts['deliveries'] = db.query(Delivery).delete()

        # 기타 프로젝트 연관
        counts['history_logs'] = db.query(HistoryLog).delete()
        counts['contacts'] = db.query(Contact).delete()
        from modules.models import DrawingVersion, ContractBarcode, Material
        counts['drawing_share_links'] = db.execute(text('DELETE FROM drawing_share_links')).rowcount
        counts['drawing_versions'] = db.query(DrawingVersion).delete()
        counts['drawings'] = db.query(Drawing).delete()
        counts['contract_barcodes'] = db.query(ContractBarcode).delete()
        counts['materials'] = db.query(Material).delete()
        counts['sports_modules'] = db.query(SportsModule).delete()
        counts['project_photos'] = db.query(ProjectPhoto).delete()
        counts['delete_requests'] = db.query(ProjectDeleteRequest).delete()
        counts['priority_overrides'] = db.query(ProjectPriorityOverride).delete()
        counts['notifications'] = db.query(Notification).delete()

        # 세금계산서: 프로젝트 연결만 해제 (데이터 유지)
        db.query(TaxInvoice).update({TaxInvoice.project_id: None, TaxInvoice.contract_id: None})

        # 계약품목 → 계약 → 프로젝트
        counts['contract_items'] = db.query(ContractItem).delete()
        counts['contracts'] = db.query(Contract).delete()
        counts['projects'] = db.query(Project).delete()

        # Item 재고는 유지 (프로젝트와 무관한 실재고)

        # Storage 파일 삭제 (사진/도면)
        from modules.storage_adapter import delete_prefix, is_storage_enabled
        storage_deleted = 0
        if is_storage_enabled():
            storage_deleted += delete_prefix('storage/photos/')
            storage_deleted += delete_prefix('storage/drawings/')
        counts['storage_files'] = storage_deleted

        db.commit()

        total = sum(counts.values())
        detail = ', '.join(f'{k}: {v}' for k, v in counts.items() if v > 0)
        flash(f'프로젝트 초기화 완료 — 총 {total}건 삭제. ({detail})', 'success')

    return redirect(url_for('auth.admin_settings') + '#resetPane')


@auth_bp.route('/admin/api/menu_order', methods=['POST', 'DELETE'])
@admin_required
def api_menu_order():
    """메뉴 순서 저장/삭제"""
    with get_db() as db:
        if request.method == 'DELETE':
            db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_order').delete()
            db.commit()
            return jsonify(ok=True)

        data = request.get_json(silent=True) or {}
        value = _json_mod.dumps(data, ensure_ascii=False)
        row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_order').first()
        if row:
            row.setting_value = value
        else:
            db.add(DashboardSetting(setting_key='menu_order', setting_value=value))

        # 그룹 간 메뉴 이동 시 권한 이전 (원래 그룹에서 빼고 새 그룹에 동일 권한으로 넣기)
        # 이동된 메뉴 감지: menu_order에서 그룹 != MENU_REGISTRY 원래 그룹
        moved = {}  # {menu_key: new_group}
        for gname in data.get('groups', []):
            for mk in data.get(gname, []):
                reg = MENU_REGISTRY.get(mk)
                if reg and reg["group"] != gname:
                    moved[mk] = gname

        if moved:
            all_gps = db.query(GroupPermission).all()
            for gp in all_gps:
                if not gp.allowed_menus:
                    continue
                entries = [e.strip() for e in gp.allowed_menus.split(",") if e.strip()]
                perm_map = {}
                for e in entries:
                    if ':' in e:
                        k, p = e.rsplit(':', 1)
                    else:
                        k, p = e, 'rw'
                    perm_map[k] = p

                changed = False
                for mk, new_group in moved.items():
                    orig_group = MENU_REGISTRY[mk]["group"]
                    if mk in perm_map:
                        perm_level = perm_map[mk]
                        # 원래 그룹의 권한에서 제거
                        if gp.group_name == orig_group:
                            del perm_map[mk]
                            changed = True
                        # 새 그룹의 권한에 동일 레벨로 추가
                        if gp.group_name == new_group and mk not in perm_map:
                            perm_map[mk] = perm_level
                            changed = True
                    elif gp.group_name == new_group:
                        # 원래 그룹 권한에 없었으면 새 그룹에도 안 넣음 (권한 없던 메뉴)
                        pass

                if changed:
                    gp.allowed_menus = ",".join(f"{k}:{v}" for k, v in perm_map.items())

        db.commit()
        return jsonify(ok=True)


@auth_bp.route('/admin/api/menu_toggle', methods=['POST'])
@admin_required
def api_menu_toggle():
    """메뉴 전역 활성/비활성 토글.
    body: {"key": "<menu_key>", "enabled": true|false}
    enabled=false → 비활성 목록에 추가, true → 제거.
    공통/admin_only 메뉴는 비활성 불가(시스템관리 잠금 방지).
    """
    from modules.services.dashboard_actions import get_disabled_menus, set_disabled_menus
    data = request.get_json(silent=True) or {}
    key = (data.get('key') or '').strip()
    enabled = bool(data.get('enabled'))

    from config import PROTECTED_MENU_KEYS
    reg = MENU_REGISTRY.get(key)
    if not reg:
        return jsonify(ok=False, error='알 수 없는 메뉴입니다.'), 400
    if key in PROTECTED_MENU_KEYS or reg.get('admin_only'):
        return jsonify(ok=False, error='이 메뉴는 비활성화할 수 없습니다.'), 400

    with get_db() as db:
        disabled = get_disabled_menus(db)
        if enabled:
            disabled.discard(key)
        else:
            disabled.add(key)
        set_disabled_menus(db, disabled)
        db.commit()
    return jsonify(ok=True, disabled=sorted(disabled))


@auth_bp.route('/logout')
def logout():
    session.clear()
    resp = redirect(url_for('auth.login'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.delete_cookie('session')
    return resp
