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
        try:
            days = float((request.form.get('days') or '1').replace(',', ''))
        except ValueError:
            flash('일수를 올바르게 입력하세요.', 'warning')
            return redirect(url_for('hr.hr_detail', user_id=user_id))
        if days <= 0:
            flash('사용일수는 0보다 커야 합니다.', 'warning')
            return redirect(url_for('hr.hr_detail', user_id=user_id))
        # 사용일이 속한 연차연도 시작연도
        ys, _ = hr.leave_year_range(u.hire_date, used_date)
        db.add(LeaveUsage(
            user_id=u.id, used_date=used_date, days=days,
            leave_type=(request.form.get('leave_type') or '연차').strip() or '연차',
            reason=(request.form.get('reason') or '').strip() or None,
            leave_year=ys.year,
            created_by=session.get('full_name', ''),
        ))
        log_activity(db, 'hr', 'leave_usage',
                     f'{u.full_name} 연차 사용 {used_date:%Y-%m-%d} {days:g}일 직접등록',
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
        # user_id → 미지정(2차 필요) 표시용 맵
        return render_template('hr_promotion.html',
                               cand=cand, records=records,
                               stage_label=lp.STAGE_LABEL,
                               emp_label=lp.EMP_TYPE_LABEL)


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
    """촉구 회수 — leave_promotions 기록 삭제(재발송 가능 상태로 복원).

    이미 발송된 메일 자체는 회수 불가. 직원 화면/추적에서만 제거되고,
    관련 ERP 인앱 알림도 정리한다.
    """
    from modules.models import LeavePromotion, Notification
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        # 직원 인앱 알림 정리
        dk = 'lp_emp_%d_%d_%s' % (p.user_id, p.leave_year, p.stage)
        db.query(Notification).filter(Notification.dedupe_key == dk).delete(
            synchronize_session=False)
        log_activity(db, 'hr', 'leave_promotion_cancel',
                     f'{u.full_name if u else p.user_id} 연차촉진 {lp.STAGE_LABEL.get(p.stage, p.stage)} 회수',
                     ref_type='user', ref_id=p.user_id)
        db.delete(p)
        db.commit()
        flash('촉구 기록을 회수했습니다. (이미 발송된 메일 자체는 회수되지 않습니다)', 'success')
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
        lp.record_second(db, u, emp_type, dates, by=by)
        log_activity(db, 'hr', 'leave_promotion_second',
                     f'{u.full_name} 연차촉진 2차(회사지정 {len(dates)}일) 통보',
                     ref_type='user', ref_id=u.id, ref_label=u.full_name)
        db.commit()
        flash(f'{u.full_name} 2차 회사지정({len(dates)}일)이 기록되었습니다.', 'success')
        return redirect(url_for('hr.hr_promotion'))


@hr_bp.route('/promotion/<int:promo_id>/print')
@menu_required('hr')
def hr_promotion_print(promo_id):
    """연차사용촉진 서면 통보서 출력 (노동부 표준서식 근접).

    출력 시점(오늘) 기준 실제 사용/잔여 연차를 조회해 문서에 반영.
    """
    from modules.models import LeavePromotion
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p:
            abort(404)
        u = db.get(User, p.user_id)
        # 출력일자 기준 실제 사용 연차 스냅샷
        summ = hr.leave_summary(db, u) if u else None
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
                               # 회사 확정(admin_dates)이 있으면 지정통보서로 출력
                               is_second=(bool(p.admin_dates) or p.stage == 'second'))


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
        summ = hr.leave_summary(db, u) if u else None

        if request.method == 'POST':
            raw = (request.form.get('dates') or '').strip()
            try:
                entries = json.loads(raw) if raw.startswith('[') else []
            except ValueError:
                entries = []
            entries = lp.normalize_entries(entries)
            lp.set_doc_dates(db, promo_id, entries,
                             by=session.get('full_name', '') or 'admin')
            log_activity(db, 'hr', 'leave_promotion_doc',
                         f'{u.full_name if u else p.user_id} 연차촉진 서면 사용일 {len(entries)}건 지정',
                         ref_type='user', ref_id=p.user_id)
            db.commit()
            flash(f'서면 사용일 {len(entries)}건이 저장되었습니다.', 'success')
            return redirect(url_for('hr.hr_promotion_print', promo_id=promo_id))

        # 실제 사용내역은 촉진(통보)일 이후만 (촉진 결과로 사용한 분)
        since = p.notified_at.date() if p.notified_at else None
        actual = [e for e in lp.actual_usage_entries(summ)
                  if not since or e['date'] >= since.strftime('%Y-%m-%d')]
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
        yrs.add(datetime.date.today().year)
        holidays = holiday_service.holiday_map(sorted(yrs))
        return render_template('hr_promotion_doc_edit.html',
                               p=p, u=u, summ=summ, prefill=prefill, actual=actual,
                               holidays=holidays, today=datetime.date.today())


@hr_bp.route('/my-promotion')
@login_required
def hr_my_promotion():
    """직원 본인 — 연차사용촉진 사용시기 셀프 지정 화면."""
    from modules.services import holiday_service
    uid = session.get('user_id')
    today = datetime.date.today()
    with get_db() as db:
        promos = lp.promotions_for_user(db, uid)
        # 달력 표시용 국경일 맵 (오늘 ~ 각 촉진의 연차연도 종료일 범위 연도)
        years = {today.year}
        for p in promos:
            if p.year_end:
                years.add(p.year_end.year)
        holidays = holiday_service.holiday_map(sorted(years))
        return render_template('hr_my_promotion.html',
                               promos=promos, stage_label=lp.STAGE_LABEL,
                               today=today, holidays=holidays)


@hr_bp.route('/my-promotion/<int:promo_id>/designate', methods=['POST'])
@login_required
def hr_my_promotion_designate(promo_id):
    """직원 본인 — 사용시기 지정 제출 (연차/반차 구분, 잔여일 한도)."""
    import json
    from modules.models import LeavePromotion
    uid = session.get('user_id')
    raw = (request.form.get('dates') or '').strip()
    try:
        entries = json.loads(raw) if raw.startswith('[') else []
    except ValueError:
        entries = []
    if not entries and raw:  # 콤마 문자열 fallback → 전부 연차
        entries = [{'date': d, 'type': '연차'} for d in _parse_dates(request.form)]
    entries = lp.normalize_entries(entries)
    with get_db() as db:
        p = db.get(LeavePromotion, promo_id)
        if not p or p.user_id != uid:
            flash('지정 권한이 없거나 대상을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('hr.hr_my_promotion'))
        if not entries:
            flash('사용 예정일을 1개 이상 선택하세요.', 'warning')
            return redirect(url_for('hr.hr_my_promotion'))
        total = lp.entries_total(entries)
        rem = float(p.remaining_days or 0)
        if total > rem + 0.001:
            flash(f'선택 {total:g}일이 미사용 잔여 연차 {rem:g}일을 초과합니다.', 'warning')
            return redirect(url_for('hr.hr_my_promotion'))
        lp.employee_designate(db, promo_id, entries, user_id=uid)
        log_activity(db, 'hr', 'leave_promotion_designate',
                     f'연차촉진 사용시기 지정 {total:g}일 ({len(entries)}건)',
                     ref_type='user', ref_id=uid)
        db.commit()
        flash(f'사용 예정일 {total:g}일({len(entries)}건)이 지정되었습니다.', 'success')
        return redirect(url_for('hr.hr_my_promotion'))


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
