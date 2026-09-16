"""인사관리(HR) 라우트

- 직원 인사카드 + 연차 현황(입사일 기준 자동 산정 + 전자결재 휴가 자동 차감)
- 조직도 / 결재권한
- 연차 수동 가감(이월/보정)
"""
import datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, abort)

from modules.auth_decorators import menu_required, admin_required, login_required
from modules.db_context import get_db
from modules.activity import log_activity
from modules.models import User, LeaveAdjustment, LeaveUsage
from modules.services import hr_service as hr
from modules.services import approval_service as appsvc
from modules.services import leave_promotion_service as lp

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
        year_opts = hr.leave_year_options(u.hire_date)
        cur_year = year_opts[0][2] if year_opts else None
        # ?ly=<연차연도 시작연도> 로 과거 연차연도 열람
        sel = request.args.get('ly', type=int)
        as_of = None
        if sel and sel != cur_year:
            as_of = hr.leave_year_start_for(u.hire_date, sel)
        summ = hr.leave_summary(db, u, as_of=as_of)
        is_admin = session.get('role') == 'admin' or session.get('user_group') == '임원진'
        return render_template('hr_detail.html', u=u, leave=summ, is_admin=is_admin,
                               year_opts=year_opts, sel_year=summ['year_start'].year,
                               cur_year=cur_year)


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


@hr_bp.route('/<int:user_id>/leave-usage', methods=['POST'])
@admin_required
def hr_leave_usage(user_id):
    """관리자 수동 연차 사용 등록 (전자결재 미경유, 도입 전 사용분 소급)."""
    with get_db() as db:
        u = db.query(User).get(user_id)
        if not u:
            abort(404)
        used_date = _safe_date(request.form.get('used_date'))
        if not used_date:
            flash('사용일을 입력하세요.', 'warning')
            return redirect(url_for('hr.hr_detail', user_id=user_id))
        end_date = _safe_date(request.form.get('end_date'))
        if end_date and end_date < used_date:
            flash('종료일이 시작일보다 빠릅니다.', 'warning')
            return redirect(url_for('hr.hr_detail', user_id=user_id))
        if end_date == used_date:
            end_date = None      # 하루짜리는 종료일을 두지 않는다
        if end_date:
            # 기간 등록: 일수는 근무일수(주말·공휴일 제외)로 서버가 정한다.
            # 전자결재 휴가(_doc_leave_days)와 같은 기준이어야 잔여가 어긋나지 않는다.
            from modules.services import holiday_service
            days = float(holiday_service.working_days(used_date, end_date))
            if days <= 0:
                flash('그 기간은 전부 주말·공휴일이라 차감할 연차가 없습니다.', 'warning')
                return redirect(url_for('hr.hr_detail', user_id=user_id))
        else:
            try:
                days = float((request.form.get('days') or '1').replace(',', ''))
            except ValueError:
                flash('일수를 올바르게 입력하세요.', 'warning')
                return redirect(url_for('hr.hr_detail', user_id=user_id))
            if days <= 0:
                flash('사용일수는 0보다 커야 합니다.', 'warning')
                return redirect(url_for('hr.hr_detail', user_id=user_id))
            if days > 1:
                # 종료일 없이 여러 날 = 어느 날짜인지 특정 불가 → 촉진 서면이 막힌다
                flash('하루를 넘으면 종료일을 입력하세요. '
                      '(종료일 없이 여러 날로 등록하면 연차사용촉진 서면을 출력할 수 없습니다)',
                      'warning')
                return redirect(url_for('hr.hr_detail', user_id=user_id))
        # 사용일이 속한 연차연도 시작연도
        ys, _ = hr.leave_year_range(u.hire_date, used_date)
        db.add(LeaveUsage(
            user_id=u.id, used_date=used_date, end_date=end_date, days=days,
            leave_type=(request.form.get('leave_type') or '연차').strip() or '연차',
            reason=(request.form.get('reason') or '').strip() or None,
            leave_year=ys.year,
            created_by=session.get('full_name', ''),
        ))
        period = (f'{used_date:%Y-%m-%d}~{end_date:%Y-%m-%d}' if end_date
                  else f'{used_date:%Y-%m-%d}')
        log_activity(db, 'hr', 'leave_usage',
                     f'{u.full_name} 연차 사용 {period} {days:g}일 직접등록',
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        flash(f'연차 사용 {days:g}일이 등록되었습니다. ({ys.year}년도 연차연도)', 'success')
        # 입력한 날짜가 속한 연차연도 화면으로 이동(바로 확인 가능)
        return redirect(url_for('hr.hr_detail', user_id=user_id, ly=ys.year))


# ══════════════════════════════════════════════════════════
# 연차사용촉진제 (근로기준법 제61조)
# ══════════════════════════════════════════════════════════
def _parse_dates(form, key='dates'):
    """폼에서 사용일 목록 파싱 (줄바꿈/콤마 구분 또는 다중 필드)."""
    vals = form.getlist(key) if hasattr(form, 'getlist') else []
    out = []
    for v in vals:
        for token in str(v).replace(',', '\n').splitlines():
            d = _safe_date(token.strip())
            if d:
                out.append(d.strftime('%Y-%m-%d'))
    # 중복 제거(순서 유지)
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


@hr_bp.route('/promotion')
@menu_required('hr')
def hr_promotion():
    """연차사용촉진 관리 화면 (대상자 산출 + 촉구/지정 이력)."""
    with get_db() as db:
        cand = lp.candidates(db)
        records = lp.all_promotions(db)
        # 전자결재 승인분 포함 실시간 잔여 부착(스냅샷 remaining_days 대신 표시용)
        today = datetime.date.today()
        n_off = 0
        for p in records:
            p.remaining_live = lp.live_leave(db, p, p.user, today)['remaining']
            # 서면 지정 사용일 ↔ 실제 사용일 대사 (표시용, 비영속)
            p.diff = lp.doc_dates_diff(db, p, p.user, today)
            if not p.diff['in_sync']:
                n_off += 1
            # 법정 기한을 넘긴 회차는 증빙으로 못 쓴다 — 표에서 바로 보이게
            p.legal = lp.legal_deadline(p, p.user)
        return render_template('hr_promotion.html',
                               cand=cand, records=records, n_off=n_off,
                               excluded=lp.excluded_employees(db),
                               stage_label=lp.STAGE_LABEL,
                               emp_label=lp.EMP_TYPE_LABEL)


@hr_bp.route('/promotion/exempt', methods=['POST'])
@admin_required
def hr_promotion_exempt():
    """연차촉진 제외 지정/해제 — 근로자가 아닌 임원 등."""
    user_id = request.form.get('user_id', type=int)
    exempt = request.form.get('exempt') == '1'
    reason = request.form.get('reason') or ''
    with get_db() as db:
        u, err = lp.set_promotion_exempt(db, user_id, exempt, reason,
                                         by=session.get('full_name', ''))
        if err:
            flash(err, 'warning')
            return redirect(url_for('hr.hr_promotion'))
        log_activity(db, 'hr', 'leave_promotion_exempt',
                     f'{u.full_name} 연차촉진 {"제외" if exempt else "제외 해제"}',
                     detail=(f'사유: {reason.strip()}' if exempt else None),
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        flash(f'{u.full_name}님을 연차촉진 대상에서 '
              + ('제외했습니다.' if exempt else '다시 포함했습니다.'), 'success')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/send', methods=['POST'])
@admin_required
def hr_promotion_send():
    """1차/추가 촉구 발송 — 대상 직원에게 이력 기록(+메일은 4단계). 단건 또는 전체."""
    user_id = request.form.get('user_id', type=int)
    stage = (request.form.get('stage') or '').strip()
    emp_type = (request.form.get('emp_type') or '').strip()
    by = session.get('full_name', '') or 'system'
    with get_db() as db:
        targets = []
        if user_id and stage:
            u = db.get(User, user_id)
            if u:
                targets.append((u, emp_type or 'over1y', stage))
        else:
            # 전체 발송: 현재 1차/추가 대상 전원
            for c in lp.candidates(db)['first']:
                targets.append((c['user'], c['emp_type'], c['stage']))
        sent = 0
        mailed = 0
        for u, et, st in targets:
            p = lp.record_promotion(db, u, et, st, by=by)
            if p:
                sent += 1
                if lp.send_promotion_email(db, p, u):
                    mailed += 1
                log_activity(db, 'hr', 'leave_promotion',
                             f'{u.full_name} 연차촉진 {lp.STAGE_LABEL.get(st, st)} 발송',
                             ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        if sent:
            flash(f'{sent}건 촉구 기록 · {mailed}건 메일 발송 완료', 'success')
        else:
            flash('발송 대상이 없습니다.', 'warning')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/<int:promo_id>/delete', methods=['POST'])
@admin_required
def hr_promotion_delete(promo_id):
    """촉구 회수 — 기록은 남기고 '회수됨'으로만 표시(재발송 가능 상태로 복원).

    예전엔 행을 지웠다. 그런데 메일은 이미 나갔고 이 행이 '보냈다'는 유일한
    증빙이라(근로기준법 제61조), 지우면 입증 수단만 없어진다. 실제로 그렇게
    한 건이 사라져 백업에서 되살렸다. 이제 지우지 않는다.

    직원 화면/인앱 알림에서는 그대로 걷어낸다 — 회수의 목적은 그쪽이다.
    """
    from modules.models import LeavePromotion, Notification
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        if p.cancelled_at:
            flash('이미 회수된 촉구입니다.', 'info')
            return redirect(url_for('hr.hr_promotion'))
        u = db.get(User, p.user_id)
        # 직원 인앱 알림 정리
        dk = 'lp_emp_%d_%d_%s' % (p.user_id, p.leave_year, p.stage)
        db.query(Notification).filter(Notification.dedupe_key == dk).delete(
            synchronize_session=False)
        lp.cancel_promotion(db, promo_id, by=session.get('full_name', '') or 'system')
        log_activity(db, 'hr', 'leave_promotion_cancel',
                     f'{u.full_name if u else p.user_id} 연차촉진 {lp.STAGE_LABEL.get(p.stage, p.stage)} 회수',
                     detail=f'통보일 {p.notified_at:%Y-%m-%d} · 기록은 이력에 남습니다(서면 출력 가능)'
                            if p.notified_at else '기록은 이력에 남습니다(서면 출력 가능)',
                     ref_type='user', ref_id=p.user_id,
                     ref_label=(u.full_name if u else None))
        db.commit()
        flash('촉구를 회수했습니다. 기록은 이력에 남아 서면 출력이 가능합니다. '
              '(이미 발송된 메일 자체는 회수되지 않습니다)', 'success')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/<int:promo_id>/resend', methods=['POST'])
@admin_required
def hr_promotion_resend(promo_id):
    """촉구·통보 메일 재발송 — 발송 실패가 조용히 묻히지 않게."""
    from modules.models import LeavePromotion
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        ok = lp.send_promotion_email(db, p, u)
        log_activity(db, 'hr', 'leave_promotion_resend',
                     f'{u.full_name} 연차촉진 {lp.STAGE_LABEL.get(p.stage, p.stage)} '
                     f'메일 {"재발송" if ok else "재발송 실패"}',
                     detail=f'수신 {p.email_to}',
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        flash(f'{u.full_name} 메일을 {p.email_to}로 재발송했습니다.' if ok
              else f'메일 발송에 실패했습니다. 서면으로 교부해 주세요.',
              'success' if ok else 'danger')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/<int:promo_id>/uncancel', methods=['POST'])
@admin_required
def hr_promotion_uncancel(promo_id):
    """회수 취소 — 잘못 회수한 촉구를 되살린다."""
    from modules.models import LeavePromotion
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        _, dup = lp.uncancel_promotion(db, promo_id)
        if dup:
            flash('같은 회차가 이미 다시 발송되어 있어 되돌릴 수 없습니다. '
                  f'(발송일 {dup.notified_at:%Y-%m-%d})', 'warning')
            return redirect(url_for('hr.hr_promotion'))
        log_activity(db, 'hr', 'leave_promotion_uncancel',
                     f'{u.full_name if u else p.user_id} 연차촉진 {lp.STAGE_LABEL.get(p.stage, p.stage)} 회수 취소',
                     ref_type='user', ref_id=p.user_id,
                     ref_label=(u.full_name if u else None))
        db.commit()
        flash('회수를 취소했습니다.', 'success')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/second', methods=['POST'])
@admin_required
def hr_promotion_second():
    """2차 — 직원 미지정 시 회사가 사용시기를 직접 지정해 통보."""
    user_id = request.form.get('user_id', type=int)
    emp_type = (request.form.get('emp_type') or 'over1y').strip()
    dates = _parse_dates(request.form)
    by = session.get('full_name', '') or 'system'
    with get_db() as db:
        u = db.get(User, user_id)
        if not u:
            abort(404)
        if not dates:
            flash('회사 지정 사용일을 1개 이상 입력하세요.', 'warning')
            return redirect(url_for('hr.hr_promotion'))
        # 현재 연차연도 밖 날짜는 제외 (다른 연차연도 사용분 혼입 차단)
        s = hr.leave_summary(db, u)
        ys, ye = s['year_start'], s['year_end'] - datetime.timedelta(days=1)
        keep = [d for d in dates
                if ys.strftime('%Y-%m-%d') <= d <= ye.strftime('%Y-%m-%d')]
        if len(keep) != len(dates):
            flash(f'연차연도({ys} ~ {ye}) 밖 날짜 {len(dates) - len(keep)}건은 '
                  f'제외했습니다.', 'warning')
        dates = keep
        if not dates:
            flash('연차연도 안의 사용일이 없습니다.', 'warning')
            return redirect(url_for('hr.hr_promotion'))
        # 1년 미만은 회사지정이 두 번(second / extra2) 있다 — 어느 벌인지 폼이 알려준다
        stage = (request.form.get('stage') or 'second').strip()
        if stage not in ('second', 'extra2'):
            stage = 'second'
        p = lp.record_second(db, u, emp_type, dates, by=by, stage=stage)
        label = lp.STAGE_LABEL.get(stage, stage)
        # 회사지정은 '통보'까지 해야 성립한다 — 기록만 남기고 안 보내면
        # 근로자는 어느 날 쉬어야 하는지 모른다(제61조 제1항 2호).
        mailed = lp.send_promotion_email(db, p, u)
        log_activity(db, 'hr', 'leave_promotion_second',
                     f'{u.full_name} 연차촉진 {label}(회사지정 {len(dates)}일) 통보',
                     detail=('메일 발송 완료' if mailed else
                             '⚠ 메일 발송 실패 — 서면으로 교부해야 합니다'),
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        if mailed:
            flash(f'{u.full_name} {label}(회사지정 {len(dates)}일)을 통보했습니다.', 'success')
        else:
            flash(f'{u.full_name} {label}이 기록됐지만 <b>메일이 나가지 않았습니다.</b> '
                  f'서면으로 교부하시거나 이력에서 재발송해 주세요.', 'warning')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/<int:promo_id>/desig-delete', methods=['POST'])
@admin_required
def hr_promotion_desig_delete(promo_id):
    """관리자 — 직원이 지정한 사용시기 삭제(미지정으로 복원). 재지정 가능."""
    from modules.models import LeavePromotion
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        if not p.employee_dates:
            flash('삭제할 직원 지정 내역이 없습니다.', 'warning')
            return redirect(url_for('hr.hr_promotion'))
        cnt = len(p.employee_dates)
        lp.clear_employee_designation(db, promo_id)
        log_activity(db, 'hr', 'leave_promotion_desig_delete',
                     f'{u.full_name if u else p.user_id} 연차촉진 직원지정 사용일 삭제({cnt}건)',
                     ref_type='user', ref_id=p.user_id)
        db.commit()
        flash('직원 지정 사용일을 삭제했습니다. (직원이 다시 지정할 수 있습니다)', 'success')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/sync-actual', methods=['POST'])
@hr_bp.route('/promotion/<int:promo_id>/sync-actual', methods=['POST'])
@admin_required
def hr_promotion_sync_actual(promo_id=None):
    """서면 인쇄용 지정 사용일을 **실제 사용일**과 일치시킨다. 단건 또는 전체.

    회차별 통보일 이후 ~ 연차연도 종료일의 실제 사용분 기준.
    직원 사전지정(employee_dates)과 status는 건드리지 않는다.
    """
    from modules.models import LeavePromotion
    by = session.get('full_name', '') or 'admin'
    with get_db() as db:
        if promo_id:
            targets = [db.get(LeavePromotion, promo_id)]
            if not targets[0]:
                abort(404)
        else:
            targets = lp.all_promotions(db)
        synced, already, noact = 0, 0, 0
        for p in targets:
            u = db.get(User, p.user_id)
            if not u:
                continue
            _, diff = lp.sync_doc_dates_to_actual(db, p, u, by=by)
            if diff['in_sync']:
                already += 1
                continue
            if not diff['has_actual'] and not diff['designated']:
                noact += 1
                continue
            synced += 1
            log_activity(
                db, 'hr', 'leave_promotion_sync_actual',
                f'{u.full_name} 연차촉진 {lp.STAGE_LABEL.get(p.stage, p.stage)} '
                f'서면 사용일 실제기준 정정 '
                f'(추가 {len(diff["missing"])} · 제거 {len(diff["extra"])} · '
                f'구분정정 {len(diff["changed"])})',
                ref_type='user', ref_id=p.user_id, ref_label=u.full_name)
        db.commit()
        if synced:
            flash(f'{synced}건을 실제 사용일 기준으로 맞췄습니다.'
                  + (f' (이미 일치 {already}건)' if already else ''), 'success')
        else:
            flash('정정할 대상이 없습니다. (모두 실제 사용일과 일치)', 'info')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/<int:promo_id>/print')
@menu_required('hr')
def hr_promotion_print(promo_id):
    """연차사용촉진 서면 통보서 출력 (노동부 표준서식 근접).

    **해당 촉진의 연차연도(p.year_start~p.year_end) 기준** 실제 사용/잔여를
    조회해 반영한다. 오늘 기준으로 뽑으면 이미 끝난 직전 연차연도 문서에
    다음(올해) 연차연도 사용분이 섞여 들어간다.
    """
    from modules.models import LeavePromotion
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        # 해당 연차연도 기준 사용/잔여 스냅샷
        summ = lp.promo_summary(db, p, u)
        diff = lp.doc_dates_diff(db, p, u) if u else None
        lp.mark_printed(db, promo_id)
        db.commit()
        company = {
            'name': '(주)매그나텍',
            'ceo': '',          # 대표이사 성명 (서명란)
        }
        return render_template('hr_promotion_doc.html',
                               p=p, u=u, summ=summ, company=company,
                               today=datetime.date.today(),
                               stage_label=lp.STAGE_LABEL,
                               diff=diff,
                               # 문서 종류는 **회차·상태**로만 판정.
                               # admin_dates 유무로 보면 실제 사용일을 서면에
                               # 반영했다는 이유만으로 1차 통보서가 회사
                               # 지정통보서로 뒤바뀐다.
                               is_second=(p.stage == 'second'
                                          or p.status == 'admin_designated'))


@hr_bp.route('/promotion/<int:promo_id>/doc-edit', methods=['GET', 'POST'])
@admin_required
def hr_promotion_doc_edit(promo_id):
    """서면 증빙용 사용일 편집 (회사 임의지정 / 실제 사용일 반영)."""
    import json
    from modules.models import LeavePromotion
    from modules.services import holiday_service
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        summ = lp.promo_summary(db, p, u)   # 해당 연차연도 기준

        if request.method == 'POST':
            raw = (request.form.get('dates') or '').strip()
            try:
                entries = json.loads(raw) if raw.startswith('[') else []
            except ValueError:
                entries = []
            entries = lp.normalize_entries(entries)
            # 연차연도 밖 날짜는 저장 금지 (다른 연차연도 사용분 혼입 차단)
            entries, dropped = lp.filter_in_leave_year(p, entries)
            if dropped:
                flash(f'연차연도({p.year_start} ~ {p.year_end}) 밖 날짜 '
                      f'{dropped}건은 제외했습니다.', 'warning')
            lp.set_doc_dates(db, promo_id, entries,
                             by=session.get('full_name', '') or 'admin')
            log_activity(db, 'hr', 'leave_promotion_doc',
                         f'{u.full_name if u else p.user_id} 연차촉진 서면 사용일 {len(entries)}건 지정',
                         ref_type='user', ref_id=p.user_id)
            db.commit()
            flash(f'서면 사용일 {len(entries)}건이 저장되었습니다.', 'success')
            return redirect(url_for('hr.hr_promotion_print', promo_id=promo_id))

        # 실제 사용내역 = 촉진(통보)일 이후 ~ **연차연도 종료일까지**.
        # 상한(year_end)이 없으면 다음 연차연도(올해) 사용분이 섞여 들어온다.
        since = p.notified_at.date() if p.notified_at else None
        actual = lp.actual_usage_entries(summ, since=since, until=p.year_end)
        # 프리필: 회사확정 > 직원지정 > 촉진일 이후 실제사용
        prefill = p.admin_dates or p.employee_dates or actual
        # 달력 국경일 (촉진일~연차연도 종료)
        yrs = set()
        if since:
            yrs.add(since.year)
        if p.year_start:
            yrs.add(p.year_start.year)
        if p.year_end:
            yrs.add(p.year_end.year)
        holidays = holiday_service.holiday_map(sorted(yrs))
        return render_template('hr_promotion_doc_edit.html',
                               p=p, u=u, summ=summ, prefill=prefill, actual=actual,
                               holidays=holidays, today=datetime.date.today())


def _load_my_promotions(db, uid, today):
    """셀프 지정 화면 공용 데이터 로더 (PC/모바일 공용)."""
    from modules.services import holiday_service
    promos = lp.promotions_for_user(db, uid)
    u = db.get(User, uid)
    # 전자결재 승인분 포함 실시간 잔여/사용 + 결재 연차 일자 부착(비영속)
    for p in promos:
        live = lp.live_leave(db, p, u, today)
        p.remaining_live = live['remaining']
        p.used_live = live['used']
        p.approved_entries = live['approved']
    # 달력 표시용 국경일 맵 (오늘 ~ 각 촉진의 연차연도 종료일 범위 연도)
    years = {today.year}
    for p in promos:
        if p.year_end:
            years.add(p.year_end.year)
    holidays = holiday_service.holiday_map(sorted(years))
    return promos, holidays


def _build_promo_calendars(promos, today, holidays):
    """모바일 전용 — 달력 그리드를 **서버에서 HTML 데이터로 미리 구성**.

    클라이언트 JS 가 달력을 그리지 못하는(구형/제한 인앱) 브라우저에서도
    달력이 항상 보이도록, 월/주/일 구조를 파이썬에서 만들어 템플릿에 넘긴다.
    JS 는 '탭 선택'만 담당한다.

    반환: {promo_id: [ {label, months:[{title, weeks:[[cell|None,...]] }] } ]}
      cell = {'day','date','off','hol','dow','sel'}  (sel: None|'연차'|'반차')
    """
    import calendar as _cal
    cals = {}
    for p in promos:
        if p.status == 'admin_designated':
            continue
        # 달력은 **그 촉진의 연차연도 안**에서만 그린다.
        # today로 시작하고 end<start 를 today로 밀면, 이미 끝난 연차연도의
        # 촉진에 올해 날짜 달력이 붙어 다른 연차연도 사용분이 지정된다.
        end = p.year_end
        if not end:
            continue
        start = max(today, p.year_start) if p.year_start else today
        if end < start:
            continue   # 연차연도 종료 — 더 지정할 수 없음
        # 직원 기존 지정 → date(str) → type 맵
        sel_map = {}
        for it in (p.employee_dates or []):
            if isinstance(it, dict) and it.get('date'):
                sel_map[it['date']] = '반차' if it.get('type') == '반차' else '연차'
        # 전자결재 승인 연차 → date(str) → type 맵 (달력 자동표시·잠금)
        appr_map = {}
        for it in (getattr(p, 'approved_entries', None) or []):
            if isinstance(it, dict) and it.get('date'):
                appr_map[it['date']] = '반차' if it.get('type') == '반차' else '연차'
        months = []
        y, m = start.year, start.month
        while (y < end.year) or (y == end.year and m <= end.month):
            title = f'{y}년 {m}월'
            weeks = []
            # 일요일 시작 주 구성
            first_dow = (datetime.date(y, m, 1).weekday() + 1) % 7  # Mon=0 → 일=0 보정
            dim = _cal.monthrange(y, m)[1]
            week = [None] * first_dow
            for day in range(1, dim + 1):
                d = datetime.date(y, m, day)
                key = d.strftime('%Y-%m-%d')
                dow = (d.weekday() + 1) % 7  # 0=일 .. 6=토
                hol = holidays.get(key)
                off = (d < start) or (d > end) or dow == 0 or dow == 6 or bool(hol)
                appr = None if off else appr_map.get(key)
                week.append({'day': day, 'date': key, 'off': off,
                             'hol': hol, 'dow': dow,
                             'sel': None if appr else sel_map.get(key),
                             'appr': appr})
                if len(week) == 7:
                    weeks.append(week)
                    week = []
            if week:
                week += [None] * (7 - len(week))
                weeks.append(week)
            months.append({'title': title, 'ym': f'{y:04d}-{m:02d}', 'weeks': weeks})
            m += 1
            if m > 12:
                m = 1
                y += 1
        cals[p.id] = months
    return cals


@hr_bp.route('/my-promotion')
@login_required
def hr_my_promotion():
    """직원 본인 — 연차사용촉진 사용시기 셀프 지정 화면.

    모바일 UA는 달력 표기가 뭉개지므로 모바일 전용 페이지로 자동 리다이렉션.
    PC/모바일 토글은 **요청별 `?pc=1`로만** 제어하고 세션에 저장하지 않는다.
    (세션 force_pc 를 건드리면 ERP 전체 네비게이션이 PC 로 전역 고정돼
     모바일로 복귀할 수 없게 됨)."""
    from routes.auth import _is_mobile_ua
    ua = request.headers.get('User-Agent', '')
    if request.args.get('pc') != '1' and _is_mobile_ua(ua):
        return redirect(url_for('hr.hr_my_promotion_mobile'))
    uid = session.get('user_id')
    today = datetime.date.today()
    with get_db() as db:
        promos, holidays = _load_my_promotions(db, uid, today)
        calendars = _build_promo_calendars(promos, today, holidays)
        return render_template('hr_my_promotion.html',
                               promos=promos, stage_label=lp.STAGE_LABEL,
                               today=today, holidays=holidays, calendars=calendars)


@hr_bp.route('/my-promotion/<int:promo_id>/toggle')
@login_required
def hr_my_promotion_toggle(promo_id):
    """직원 본인 — 사용시기 지정 (링크/GET 방식, 폼 제출 불가 웹뷰 대응).

    날짜 링크 탭 1회 = 그 날짜 상태 순환(해제→연차→반차→해제). 매 탭마다 서버에
    즉시 저장하고 모바일 화면으로 되돌아온다(폼 제출·JS 불필요).
    """
    from modules.models import LeavePromotion
    uid = session.get('user_id')
    date_str = (request.args.get('date') or '').strip()
    d = _safe_date(date_str)
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p or p.user_id != uid:
            flash('지정 권한이 없거나 대상을 찾을 수 없습니다.', 'danger')
            return _redirect_promo_mobile()
        if p.status == 'admin_designated':
            flash('회사 지정분은 수정할 수 없습니다.', 'warning')
            return _redirect_promo_mobile()
        if not d:
            return _redirect_promo_mobile()
        if not lp.in_leave_year(p, date_str):
            flash(f'연차연도({p.year_start} ~ {p.year_end}) 안의 날짜만 '
                  f'지정할 수 있습니다.', 'warning')
            return _redirect_promo_mobile()
        # 현재 지정 맵
        cur_map = {}
        for it in (p.employee_dates or []):
            if isinstance(it, dict) and it.get('date'):
                cur_map[it['date']] = '반차' if it.get('type') == '반차' else '연차'
        cur = cur_map.get(date_str)
        nxt = '연차' if cur is None else ('반차' if cur == '연차' else None)
        if nxt is None:
            cur_map.pop(date_str, None)
        else:
            cur_map[date_str] = nxt
        entries = lp.normalize_entries(
            [{'date': k, 'type': v} for k, v in cur_map.items()])
        total = lp.entries_total(entries)
        u = db.get(User, uid)
        rem = float(lp.live_leave(db, p, u)['remaining'] or 0)
        if total > rem + 0.001:
            flash(f'미사용 잔여 연차 {rem:g}일을 초과할 수 없습니다.', 'warning')
            return _redirect_promo_mobile(anchor=date_str)
        lp.employee_designate(db, promo_id, entries, user_id=uid) if entries \
            else lp.clear_employee_designation(db, promo_id, user_id=uid)
        log_activity(db, 'hr', 'leave_promotion_designate',
                     f'연차촉진 사용시기 지정 {total:g}일 ({len(entries)}건)',
                     ref_type='user', ref_id=uid)
        db.commit()
        return _redirect_promo_mobile(anchor=date_str)


def _redirect_promo_mobile(anchor=None):
    """모바일 지정화면으로 no-store 리다이렉트 (탭한 날짜의 달/위치로 복귀)."""
    from flask import make_response
    ym = anchor[:7] if anchor else None   # 'YYYY-MM-DD' → 'YYYY-MM'
    url = url_for('hr.hr_my_promotion_mobile', ym=ym) if ym \
        else url_for('hr.hr_my_promotion_mobile')
    if anchor:
        url += '#d-' + anchor
    resp = make_response(redirect(url))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


# 1x1 투명 GIF (CSS background-image 콜백 응답용)
_PIXEL_GIF = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!'
              b'\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01'
              b'\x00\x00\x02\x02D\x01\x00;')


@hr_bp.route('/my-promotion/<int:promo_id>/set')
@login_required
def hr_my_promotion_set(promo_id):
    """CSS background-image 콜백 — 폼 제출·JS 안 되는 웹뷰용 **무새로고침 저장**.

    화면의 `:checked` 상태가 바뀌면 CSS가 이 URL을 background-image로 불러
    (=GET) 그 날짜 상태(t=y연차/b반차/n해제)를 서버에 저장한다. 1x1 gif 반환.
    변경 없으면 no-op(로드 시 대량 콜백에도 DB write 없음).
    """
    from flask import make_response
    from modules.models import LeavePromotion
    uid = session.get('user_id')
    date_str = (request.args.get('date') or '').strip()
    t = (request.args.get('t') or '').strip()

    def _pixel():
        resp = make_response(_PIXEL_GIF)
        resp.headers['Content-Type'] = 'image/gif'
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    d = _safe_date(date_str)
    want = {'y': '연차', 'b': '반차'}.get(t)   # 그 외/n → 해제(제거)
    if not d:
        return _pixel()
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p or p.user_id != uid or p.status == 'admin_designated':
            return _pixel()
        if not lp.in_leave_year(p, date_str):
            return _pixel()   # 연차연도 밖 → 저장 안 함
        cur_map = {}
        for it in (p.employee_dates or []):
            if isinstance(it, dict) and it.get('date'):
                cur_map[it['date']] = '반차' if it.get('type') == '반차' else '연차'
        if cur_map.get(date_str) == want:
            return _pixel()   # 변경 없음 → no-op (안전)
        if want is None:
            cur_map.pop(date_str, None)
        else:
            cur_map[date_str] = want
        entries = lp.normalize_entries(
            [{'date': k, 'type': v} for k, v in cur_map.items()])
        u = db.get(User, uid)
        rem = float(lp.live_leave(db, p, u)['remaining'] or 0)
        if lp.entries_total(entries) > rem + 0.001:
            return _pixel()   # 잔여 초과 → 저장 안 함
        if entries:
            lp.employee_designate(db, promo_id, entries, user_id=uid)
        else:
            lp.clear_employee_designation(db, promo_id, user_id=uid)
        db.commit()
        return _pixel()


@hr_bp.route('/lp-ping', methods=['GET', 'POST'])
@login_required
def hr_lp_ping():
    """진단용 — 모바일 탭/제출이 서버에 도달하는지 격리 확인."""
    from flask import current_app
    current_app.logger.warning('LP_PING method=%s from=%s ua=%r',
                               request.method, request.args.get('from') or request.form.get('from'),
                               request.headers.get('User-Agent', '')[:100])
    kind = request.args.get('from') or request.form.get('from') or '?'
    return ('<html><body style="font-family:sans-serif;padding:40px;text-align:center">'
            '<h2 style="color:#16a34a">✅ 도달 성공</h2>'
            f'<p>탭({kind})이 서버까지 정상 도달했습니다.</p>'
            '<a href="javascript:history.back()">돌아가기</a></body></html>')


@hr_bp.route('/my-promotion/m')
@login_required
def hr_my_promotion_mobile():
    """직원 본인 — 연차사용촉진 사용시기 지정 (모바일 전용, 월 단위 페이징 달력)."""
    # 모바일 화면을 직접 본다는 것은 'PC 강제'를 해제한다는 의미 → 굳은 전역 플래그 정리
    session.pop('force_pc', None)
    uid = session.get('user_id')
    try:
        from flask import current_app
        current_app.logger.info('LP_MOBILE_GET uid=%s cf=%s xff=%s host=%s ua=%r', uid,
                                request.headers.get('CF-Ray', '-'),
                                request.headers.get('X-Forwarded-For', '-'),
                                request.headers.get('Host', '-'),
                                request.headers.get('User-Agent', '')[:100])
    except Exception:
        pass
    today = datetime.date.today()
    with get_db() as db:
        promos, holidays = _load_my_promotions(db, uid, today)
        calendars = _build_promo_calendars(promos, today, holidays)
        # 월 단위 페이징 — 한 화면에 한 달만(탭당 리프레시 경량화)
        all_yms = sorted({mon['ym'] for months in calendars.values() for mon in months})
        cur_ym = today.strftime('%Y-%m')
        active_ym = request.args.get('ym')
        if active_ym not in all_yms:
            active_ym = cur_ym if cur_ym in all_yms else (all_yms[0] if all_yms else cur_ym)
        idx = all_yms.index(active_ym) if active_ym in all_yms else -1
        prev_ym = all_yms[idx - 1] if idx > 0 else None
        next_ym = all_yms[idx + 1] if 0 <= idx < len(all_yms) - 1 else None
        html = render_template('hr_my_promotion_mobile.html',
                               promos=promos, stage_label=lp.STAGE_LABEL,
                               today=today, holidays=holidays, calendars=calendars,
                               active_ym=active_ym, prev_ym=prev_ym, next_ym=next_ym)
    # 브라우저가 옛 버전을 절대 캐시하지 못하게 (모바일 단말 캐시/뒤로가기 캐시 방지)
    from flask import make_response
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@hr_bp.route('/my-promotion/<int:promo_id>/designate', methods=['POST'])
@login_required
def hr_my_promotion_designate(promo_id):
    """직원 본인 — 사용시기 지정 제출 (연차/반차 구분, 잔여일 한도)."""
    import json
    from modules.models import LeavePromotion
    uid = session.get('user_id')
    # 제출한 화면(모바일/PC)으로 그대로 복귀 — UA 판별에 의존하지 않는다.
    # (모바일 웹뷰 UA가 _is_mobile_ua에 안 잡히면 PC로 튕겨 "적용 안 됨"처럼 보임)
    from routes.auth import _is_mobile_ua
    _from_mobile = (request.form.get('src') == 'm'
                    or _is_mobile_ua(request.headers.get('User-Agent', '')))
    _back_ep = 'hr.hr_my_promotion_mobile' if _from_mobile else 'hr.hr_my_promotion'
    entries = []
    # 순환 라디오 방식(JS 불요): st_<YYYY-MM-DD> = 연차|반차|''
    for key, val in request.form.items():
        if key.startswith('st_') and val in ('연차', '반차'):
            d = _safe_date(key[3:])
            if d:
                entries.append({'date': d.strftime('%Y-%m-%d'), 'type': val})
    if not entries:
        # (구) JSON / 체크박스 호환
        raw = (request.form.get('dates') or '').strip()
        if raw.startswith('['):
            try:
                entries = json.loads(raw)
            except ValueError:
                entries = []
        if not entries:
            half = set(request.form.getlist('half'))
            entries = [{'date': d, 'type': '반차' if d in half else '연차'}
                       for d in _parse_dates(request.form)]
    entries = lp.normalize_entries(entries)
    # 진단 로그 — 특정 모바일 웹뷰에서 제출 반응 없음 신고 대응(폼 수신 여부 확인)
    try:
        from flask import current_app
        _fk = [k for k in request.form.keys() if k.startswith('st_')]
        current_app.logger.info(
            'LP_DESIGNATE promo=%s uid=%s src=%s ct=%s st_keys=%d entries=%d ua=%r',
            promo_id, uid, request.form.get('src'),
            request.content_type, len(_fk), len(entries),
            request.headers.get('User-Agent', '')[:120])
    except Exception:
        pass
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p or p.user_id != uid:
            flash('지정 권한이 없거나 대상을 찾을 수 없습니다.', 'danger')
            return redirect(url_for(_back_ep))
        if not entries:
            flash('사용 예정일을 1개 이상 선택하세요.', 'warning')
            return redirect(url_for(_back_ep))
        total = lp.entries_total(entries)
        # 전자결재 승인분 포함 실시간 잔여로 한도 판정(스냅샷 대신)
        u = db.get(User, uid)
        rem = float(lp.live_leave(db, p, u)['remaining'] or 0)
        if total > rem + 0.001:
            flash(f'선택 {total:g}일이 미사용 잔여 연차 {rem:g}일을 초과합니다.', 'warning')
            return redirect(url_for(_back_ep))
        lp.employee_designate(db, promo_id, entries, user_id=uid)
        log_activity(db, 'hr', 'leave_promotion_designate',
                     f'연차촉진 사용시기 지정 {total:g}일 ({len(entries)}건)',
                     ref_type='user', ref_id=uid)
        db.commit()
        flash(f'사용 예정일 {total:g}일({len(entries)}건)이 지정되었습니다.', 'success')
        return redirect(url_for(_back_ep))


@hr_bp.route('/<int:user_id>/leave-usage/<int:usage_id>/delete', methods=['POST'])
@admin_required
def hr_leave_usage_delete(user_id, usage_id):
    ly = request.form.get('ly', type=int)
    with get_db() as db:
        usage = db.query(LeaveUsage).get(usage_id)
        if usage and usage.user_id == user_id:
            db.delete(usage)
            log_activity(db, 'hr', 'leave_usage_delete',
                         f'{usage.user.full_name if usage.user else ""} 연차 사용기록 삭제',
                         ref_type='user', ref_id=user_id)
            db.commit()
            flash('사용 기록이 삭제되었습니다.', 'success')
        return redirect(url_for('hr.hr_detail', user_id=user_id, ly=ly))
