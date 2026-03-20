import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from modules.auth_decorators import admin_required, login_required
import bcrypt
from modules.db_context import get_db
from modules.models import User, GroupPermission, ProjectDeleteRequest, UserPriorityPermission
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
                    allowed_menus = [m.strip() for m in group_data.allowed_menus.split(",") if m.strip()] if group_data and group_data.allowed_menus else []
                    # 개인 추가 메뉴 병합 (팀장 등 개별 권한)
                    if user.extra_menus:
                        extra = [m.strip() for m in user.extra_menus.split(",") if m.strip()]
                        allowed_menus = list(dict.fromkeys(allowed_menus + extra))  # 중복 제거, 순서 유지
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
        pending = db.query(User).filter(User.is_approved == False).all()
        users = db.query(User).filter(User.is_approved == True).order_by(User.created_at.desc()).all()
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
        groups = sorted(set(u.user_group for u in users if u.user_group))

        # 그룹별 메뉴 권한 데이터
        group_permissions = db.query(GroupPermission).all()
        group_menu_data = []
        for gp in group_permissions:
            current_menus = [m.strip() for m in gp.allowed_menus.split(",") if m.strip()] if gp.allowed_menus else []
            group_menu_data.append({
                "group_name": gp.group_name,
                "current_menus": current_menus,
            })

        configurable_menus = [
            {"key": k, "label": v["label"], "group": v["group"]}
            for k, v in MENU_REGISTRY.items()
            if k not in COMMON_MENU_KEYS and not v.get("admin_only")
        ]

        return render_template('admin_settings.html',
            pending=pending, users=users, delete_requests=delete_requests,
            total_count=total_count, active_count=active_count,
            inactive_count=inactive_count, pending_count=pending_count,
            groups=groups,
            group_menu_data=group_menu_data,
            configurable_menus=configurable_menus)


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
    new_password = request.form.get('new_password', '')
    if len(new_password) < 6:
        flash("비밀번호는 6자 이상 입력해주세요.", "danger")
        return redirect(url_for('auth.admin_settings'))

    with get_db() as db:
        user = db.get(User, user_id)
        if not user:
            flash("사용자를 찾을 수 없습니다.", "danger")
            return redirect(url_for('auth.admin_settings'))

        hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
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


@auth_bp.route('/admin/reset_projects', methods=['POST'])
@admin_required
def reset_projects():
    """프로젝트 전체 초기화 — 프로젝트 + 연관 데이터 삭제, 마스터 데이터 유지"""
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

        # 발주
        counts['purchase_order_items'] = db.query(PurchaseOrderItem).delete()
        counts['purchase_orders'] = db.query(PurchaseOrder).delete()

        # 자재
        counts['material_orders'] = db.query(MaterialOrder).delete()

        # 재고 변동 이력
        counts['stock_movements'] = db.query(StockMovement).delete()

        # 하자
        counts['warranty_cases'] = db.query(WarrantyCase).delete()
        counts['warranties'] = db.query(Warranty).delete()

        # 납품
        counts['deliveries'] = db.query(Delivery).delete()

        # 기타 프로젝트 연관
        counts['history_logs'] = db.query(HistoryLog).delete()
        counts['contacts'] = db.query(Contact).delete()
        counts['drawings'] = db.query(Drawing).delete()
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
