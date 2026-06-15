"""인사관리(HR) 라우트

- 직원 인사카드 + 연차 현황(입사일 기준 자동 산정 + 전자결재 휴가 자동 차감)
- 조직도 / 결재권한
- 연차 수동 가감(이월/보정)
"""
import datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, abort)

from modules.auth_decorators import menu_required, admin_required
from modules.db_context import get_db
from modules.activity import log_activity
from modules.models import User, LeaveAdjustment
from modules.services import hr_service as hr
from modules.services import approval_service as appsvc

hr_bp = Blueprint('hr', __name__, url_prefix='/hr')


def _safe_date(s):
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s.strip()[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _active_employees(db):
    return (db.query(User)
            .filter(User.is_active.is_(True), User.user_group != '최고관리자')
            .order_by(User.user_group, User.full_name).all())


@hr_bp.route('')
@menu_required('hr')
def hr_list():
    with get_db() as db:
        emps = _active_employees(db)
        rows = []
        for u in emps:
            summ = hr.leave_summary(db, u)
            rows.append({'u': u, 'leave': summ})
        # 부서별 그룹
        from collections import OrderedDict
        by_dept = OrderedDict()
        for r in rows:
            by_dept.setdefault(r['u'].user_group or '미지정', []).append(r)
        return render_template('hr_list.html', by_dept=by_dept, total=len(rows))


@hr_bp.route('/org')
@menu_required('hr')
def hr_org():
    with get_db() as db:
        emps = _active_employees(db)
        from collections import OrderedDict
        by_dept = OrderedDict()
        for u in emps:
            by_dept.setdefault(u.user_group or '미지정', []).append(u)
        # 부서별 직급 내림차순 정렬
        for dept in by_dept:
            by_dept[dept].sort(key=lambda x: appsvc.position_rank(x.position), reverse=True)
        # 경영진(부장 이상)
        seniors = sorted(
            [u for u in emps if appsvc.position_rank(u.position) >= appsvc.SENIOR_THRESHOLD],
            key=lambda x: appsvc.position_rank(x.position), reverse=True)
        return render_template('hr_org.html', by_dept=by_dept, seniors=seniors,
                               rank_fn=appsvc.position_rank)


@hr_bp.route('/<int:user_id>')
@menu_required('hr')
def hr_detail(user_id):
    with get_db() as db:
        u = db.query(User).get(user_id)
        if not u:
            abort(404)
        summ = hr.leave_summary(db, u)
        is_admin = session.get('role') == 'admin' or session.get('user_group') == '임원진'
        return render_template('hr_detail.html', u=u, leave=summ, is_admin=is_admin)


@hr_bp.route('/<int:user_id>/edit', methods=['POST'])
@admin_required
def hr_edit(user_id):
    with get_db() as db:
        u = db.query(User).get(user_id)
        if not u:
            abort(404)
        # HR 정보 필드만 수정 (부서/권한은 시스템관리에서)
        u.position = (request.form.get('position') or '').strip() or None
        u.hire_date = _safe_date(request.form.get('hire_date'))
        u.birth_date = _safe_date(request.form.get('birth_date'))
        u.address = (request.form.get('address') or '').strip() or None
        u.phone_number = (request.form.get('phone_number') or '').strip() or u.phone_number
        u.email = (request.form.get('email') or '').strip() or None
        u.office_tel = (request.form.get('office_tel') or '').strip() or None
        u.office_fax = (request.form.get('office_fax') or '').strip() or None
        log_activity(db, 'hr', 'edit', f'{u.full_name} 인사정보 수정',
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        flash('인사정보가 저장되었습니다.', 'success')
        return redirect(url_for('hr.hr_detail', user_id=user_id))


@hr_bp.route('/<int:user_id>/leave-adjust', methods=['POST'])
@admin_required
def hr_leave_adjust(user_id):
    with get_db() as db:
        u = db.query(User).get(user_id)
        if not u:
            abort(404)
        try:
            days = float((request.form.get('days') or '0').replace(',', ''))
        except ValueError:
            flash('일수를 올바르게 입력하세요.', 'warning')
            return redirect(url_for('hr.hr_detail', user_id=user_id))
        if days == 0:
            flash('0이 아닌 일수를 입력하세요.', 'warning')
            return redirect(url_for('hr.hr_detail', user_id=user_id))
        ys, _ = hr.leave_year_range(u.hire_date)
        db.add(LeaveAdjustment(
            user_id=u.id, days=days,
            reason=(request.form.get('reason') or '').strip() or None,
            leave_year=ys.year,
            created_by=session.get('full_name', ''),
        ))
        log_activity(db, 'hr', 'leave_adjust', f'{u.full_name} 연차 {days:+g}일 조정',
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        flash(f'연차 {days:+g}일 조정되었습니다.', 'success')
        return redirect(url_for('hr.hr_detail', user_id=user_id))


@hr_bp.route('/<int:user_id>/leave-adjust/<int:adj_id>/delete', methods=['POST'])
@admin_required
def hr_leave_adjust_delete(user_id, adj_id):
    with get_db() as db:
        adj = db.query(LeaveAdjustment).get(adj_id)
        if adj and adj.user_id == user_id:
            db.delete(adj)
            db.commit()
            flash('조정 내역이 삭제되었습니다.', 'success')
        return redirect(url_for('hr.hr_detail', user_id=user_id))
