import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify
from modules.auth_decorators import admin_required, login_required
import bcrypt
from modules.db_context import get_db
from modules.models import User, GroupPermission, ProjectDeleteRequest, UserPriorityPermission
from modules.models.db import SUPERADMIN_USERNAME
from config import MENU_REGISTRY, COMMON_MENU_KEYS

auth_bp = Blueprint('auth', __name__)


def _get_limiter():
    """app.py에서 생성한 limiter 참조"""
    return current_app.extensions.get("limiter")


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard_view'))

    with get_db() as db:
        if request.method == 'POST':
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

                    session.update({
                        'user_id': user.id, 'username': user.username, 'full_name': user.full_name,
                        'user_group': user.user_group, 'role': user.role, 'position': user.position or '',
                        'allowed_menus': allowed_menus,
                        'writable_menus': writable_menus,
                        'hide_financial': hide_financial,
                        'can_approve_delete': bool(user.role == 'admin' or user.can_approve_delete),
                        'can_manage_priority': can_manage_priority,
                    })
                    return redirect(url_for('dashboard.dashboard_view'))
                else:
                    flash("승인 대기 중입니다.", "warning")
            else:
                flash("아이디 또는 비밀번호 오류", "danger")

        groups = [g.group_name for g in db.query(GroupPermission).filter(GroupPermission.group_name != "최고관리자").all()]
        return render_template('login.html', groups=groups)


@auth_bp.route('/register', methods=['POST'])
def register():
    username = (request.form.get('new_username') or '').strip()
    password = request.form.get('new_password') or ''
    fullname = (request.form.get('new_fullname') or '').strip()
    phone = (request.form.get('new_phone') or '').strip()
    group = request.form.get('new_group') or ''

    # 입력값 검증
    errors = []
    if len(username) < 3:
        errors.append("아이디는 3자 이상 입력해주세요.")
    if len(password) < 6:
        errors.append("비밀번호는 6자 이상 입력해주세요.")
    if not fullname:
        errors.append("이름을 입력해주세요.")

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
        is_superadmin = session.get('username') == SUPERADMIN_USERNAME

        # 운영설정
        from modules.services.dashboard_actions import get_dashboard_setting_int
        production_lead_days = get_dashboard_setting_int(db, 'production_lead_days', 7)

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
            presets_map=presets_map)


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
            # 챗봇 권한 초기값: 전체 해제
            from sqlalchemy import text as _text
            db.execute(_text("""
                INSERT INTO chatbot_permissions (erp_username, allowed_tools, channel_enabled)
                VALUES (:u, '', false)
                ON CONFLICT (erp_username) DO NOTHING
            """), {"u": user.username})
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

    if len(new_password) < 6:
        flash("비밀번호는 6자 이상 입력해주세요.", "danger")
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
        db.commit()
        flash(f"{user.full_name} 비밀번호가 초기화되었습니다.", "success")
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
    # db.py SUPERADMIN_USERNAME 계정만 허용
    if session.get('username') != SUPERADMIN_USERNAME:
        flash('최고관리자 계정만 프로젝트 초기화를 실행할 수 있습니다.', 'danger')
        return redirect(url_for('auth.admin_settings'))

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


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
