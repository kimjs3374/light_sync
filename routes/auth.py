from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import bcrypt
from modules.models import SessionLocal, User, GroupPermission, ProjectDeleteRequest, UserPriorityPermission

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: 
        return redirect(url_for('dashboard.dashboard_view'))
        
    db = SessionLocal()
    if request.method == 'POST':
        login_id = request.form.get('username')
        login_pw = request.form.get('password')
        user = db.query(User).filter(User.username == login_id).first()
        
        if user and bcrypt.checkpw(login_pw.encode('utf-8'), user.password_hash.encode('utf-8')):
            if user.is_approved:
                if user.is_active is False:
                    flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "danger")
                    db.close()
                    return redirect(url_for('auth.login'))

                group_data = db.query(GroupPermission).filter(GroupPermission.group_name == user.user_group).first()
                allowed_menus = group_data.allowed_menus.split(",") if group_data else []
                if user.role == 'admin': allowed_menus.append("👑 시스템 및 권한 관리")
                can_manage_priority = bool(
                    user.role == 'admin'
                    or db.query(UserPriorityPermission).filter(
                        UserPriorityPermission.user_id == user.id,
                        UserPriorityPermission.is_active.is_(True)
                    ).first()
                )
                
                session.update({
                    'user_id': user.id, 'username': user.username, 'full_name': user.full_name,
                    'user_group': user.user_group, 'role': user.role, 'allowed_menus': allowed_menus,
                    'can_approve_delete': bool(user.role == 'admin' or user.can_approve_delete),
                    'can_manage_priority': can_manage_priority,
                })
                db.close()
                return redirect(url_for('dashboard.dashboard_view'))
            else:
                flash("🚨 승인 대기 중입니다.", "warning")
        else:
            flash("아이디 또는 비밀번호 오류", "danger")
            
    groups = [g.group_name for g in db.query(GroupPermission).filter(GroupPermission.group_name != "최고관리자").all()]
    db.close()
    return render_template('login.html', groups=groups)

@auth_bp.route('/register', methods=['POST'])
def register():
    db = SessionLocal()
    hashed_pw = bcrypt.hashpw(request.form.get('new_password').encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db.add(User(
        username=request.form.get('new_username'), password_hash=hashed_pw,
        full_name=request.form.get('new_fullname'), phone_number=request.form.get('new_phone'),
        user_group=request.form.get('new_group'), is_approved=False
    ))
    db.commit()
    db.close()
    flash("✅ 가입 신청 완료!", "success")
    return redirect(url_for('auth.login'))

@auth_bp.route('/admin_settings')
def admin_settings():
    if session.get('role') != 'admin': return redirect(url_for('dashboard.dashboard_view'))
    db = SessionLocal()
    pending = db.query(User).filter(User.is_approved == False).all()
    users = db.query(User).filter(User.is_approved == True).order_by(User.created_at.desc()).all()
    priority_permissions = db.query(UserPriorityPermission).filter(UserPriorityPermission.is_active.is_(True)).all()
    priority_user_ids = {row.user_id for row in priority_permissions}
    for user in users:
        user.can_manage_priority = bool(user.role == 'admin' or user.id in priority_user_ids)
    delete_requests = db.query(ProjectDeleteRequest).order_by(ProjectDeleteRequest.created_at.desc()).all()
    db.close()
    return render_template('admin_settings.html', pending=pending, users=users, delete_requests=delete_requests)


@auth_bp.route('/toggle_delete_approver/<int:user_id>', methods=['POST'])
def toggle_delete_approver(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard.dashboard_view'))

    db = SessionLocal()
    user = db.query(User).get(user_id)
    if user:
        target = request.form.get('can_approve_delete') == '1'
        user.can_approve_delete = bool(target)
        db.commit()
        flash(f"{user.full_name} 삭제승인 권한이 {'활성화' if target else '해제'}되었습니다.", 'success')
    db.close()
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/toggle_priority_manager/<int:user_id>', methods=['POST'])
def toggle_priority_manager(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard.dashboard_view'))

    db = SessionLocal()
    user = db.query(User).get(user_id)
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
    db.close()
    return redirect(url_for('auth.admin_settings'))


@auth_bp.route('/toggle_user_active/<int:user_id>', methods=['POST'])
def toggle_user_active(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard.dashboard_view'))

    db = SessionLocal()
    user = db.query(User).get(user_id)
    if not user:
        db.close()
        flash("사용자를 찾을 수 없습니다.", "warning")
        return redirect(url_for('auth.admin_settings'))

    if user.role == 'admin':
        db.close()
        flash("관리자 계정은 비활성화할 수 없습니다.", "warning")
        return redirect(url_for('auth.admin_settings'))

    if session.get('user_id') == user.id:
        db.close()
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
        user.deactivated_at = __import__('datetime').datetime.now()
        user.deactivated_reason = reason if reason else '퇴사/비활성 처리'
        flash(f"{user.full_name} 계정이 비활성화되었습니다.", "warning")

    db.commit()
    db.close()
    return redirect(url_for('auth.admin_settings'))

@auth_bp.route('/approve_user/<int:user_id>')
def approve_user(user_id):
    db = SessionLocal()
    user = db.query(User).get(user_id)
    if user: user.is_approved = True; db.commit()
    db.close()
    return redirect(url_for('auth.admin_settings'))

@auth_bp.route('/reject_user/<int:user_id>')
def reject_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard.dashboard_view'))
    db = SessionLocal()
    user = db.query(User).get(user_id)
    if user and user.role != 'admin':
        db.delete(user)
        db.commit()
        flash("가입 신청이 거절(삭제)되었습니다.", "warning")
    db.close()
    return redirect(url_for('auth.admin_settings'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))