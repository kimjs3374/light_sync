import datetime
import json

from flask import Blueprint, render_template, request, session, jsonify, flash, redirect, url_for
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models import (
    DailyReport, User, HistoryLog, Project, Contract, ContractItem,
    Delivery, MaterialOrder, ProductionProcess, ProductionDailyLog,
    WarrantyCase,
)

daily_report_bp = Blueprint('daily_report', __name__)

WEEKDAY_KR = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']

# log_scope → 부서 매핑
SCOPE_TO_DEPT = {
    'design': '영업부',
    'drawing': '영업부',
    'sales': '영업부',
    'contract': '영업부',
    'delivery': '영업부',
    'material': '경영관리부',
    'production': '생산부',
    'technical': '영업부',
    'common': None,
}


def _collect_auto_items(db, target_date):
    """ERP 데이터에서 당일 활동을 부서별로 자동 수집"""
    day_start = datetime.datetime.combine(target_date, datetime.time.min)
    day_end = datetime.datetime.combine(target_date, datetime.time.max)

    dept_items = {}

    # 사용자→부서 매핑
    user_dept_map = {}
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        user_dept_map[u.full_name] = u.user_group or '미지정'

    # ─── 1. 신규 프로젝트 ───
    for p in db.query(Project).filter(
        Project.created_at >= day_start, Project.created_at <= day_end,
    ).all():
        dept_items.setdefault('영업부', []).append(
            f"{p.temp_name} 현장 신규 등록 ({p.project_no})"
        )

    # ─── 2. 계약 등록 ───
    for c in db.query(Contract).filter(
        Contract.contract_date == target_date,
    ).options(joinedload(Contract.project)).all():
        site = c.project.temp_name if c.project else '(현장미상)'
        cname = c.contract_name or ''
        if site in cname:
            item = f"{cname} 계약 등록"
        else:
            item = f"{site} {cname} 계약 등록"
        dept_items.setdefault('영업부', []).append(item)

    # ─── 3. 납품 ───
    for d in db.query(Delivery).filter(
        Delivery.created_at >= day_start, Delivery.created_at <= day_end,
    ).options(joinedload(Delivery.project)).all():
        site = d.project.temp_name if d.project else '(현장미상)'
        dept_items.setdefault('영업부', []).append(
            f"{site} 납품 {d.delivery_status or '등록'}"
        )

    # ─── 4. 자재 발주/입고 ───
    mat_summary = {}
    for m in db.query(MaterialOrder).filter(
        MaterialOrder.updated_at >= day_start, MaterialOrder.updated_at <= day_end,
    ).options(
        joinedload(MaterialOrder.contract_item)
        .joinedload(ContractItem.contract)
        .joinedload(Contract.project)
    ).all():
        try:
            site = m.contract_item.contract.project.temp_name
        except AttributeError:
            site = '(현장미상)'
        mat_summary.setdefault(site, set()).add(m.order_status)
    for site, statuses in mat_summary.items():
        dept_items.setdefault('경영관리부', []).append(
            f"{site} 자재 {'/'.join(sorted(statuses))}"
        )

    # ─── 5. 생산 실적 ───
    for log in db.query(ProductionDailyLog).filter(
        ProductionDailyLog.work_date == target_date,
    ).options(
        joinedload(ProductionDailyLog.production_process)
        .joinedload(ProductionProcess.contract_item)
        .joinedload(ContractItem.contract)
        .joinedload(Contract.project)
    ).all():
        try:
            site = log.production_process.contract_item.contract.project.temp_name
        except AttributeError:
            site = '(현장미상)'
        pname = log.production_process.process_name if log.production_process else ''
        parts = [f"{site} {pname}"]
        if log.daily_qty:
            parts.append(f"{log.daily_qty}개")
        if log.memo:
            parts.append(log.memo)
        dept_items.setdefault('생산부', []).append(' '.join(parts))

    # ─── 6. 하자/AS ───
    for c in db.query(WarrantyCase).filter(
        WarrantyCase.created_at >= day_start, WarrantyCase.created_at <= day_end,
    ).options(joinedload(WarrantyCase.warranty)).all():
        site = c.warranty.site_name if c.warranty else '(현장미상)'
        dept_items.setdefault('생산부', []).append(
            f"{site} 하자/AS 접수 ({c.defect_type or '기타'})"
        )

    # ─── 7. 사용자 코멘트 ───
    for log in db.query(HistoryLog).filter(
        HistoryLog.created_at >= day_start, HistoryLog.created_at <= day_end,
        HistoryLog.log_kind == 'comment',
    ).options(joinedload(HistoryLog.project)).all():
        dept = SCOPE_TO_DEPT.get(log.log_scope)
        if dept is None:
            dept = user_dept_map.get(log.user_name)
        if not dept:
            continue
        site = log.project.temp_name if log.project else ''
        item = f"{site} {log.content}" if site else log.content
        if len(item) > 80:
            item = item[:77] + '...'
        dept_items.setdefault(dept, []).append(item)

    return dept_items


@daily_report_bp.route('/daily-report')
@login_required
def daily_report_view():
    """일일업무보고 - 자동수집 + 수동추가"""
    target_date_str = request.args.get('date')
    if target_date_str:
        try:
            target_date = datetime.date.fromisoformat(target_date_str)
        except ValueError:
            target_date = datetime.date.today()
    else:
        target_date = datetime.date.today()

    user_group = session.get('user_group', '')

    with get_db() as db:
        auto_items = _collect_auto_items(db, target_date)

        saved_reports = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
        ).order_by(DailyReport.department).all()

        saved_map = {}
        for r in saved_reports:
            saved_map[r.department] = {
                'id': r.id,
                'reporter_name': r.reporter_name,
                'headcount_total': r.headcount_total,
                'headcount_present': r.headcount_present,
                'headcount_absence_info': r.headcount_absence_info or '',
                'manual_items': r.items,
            }

        all_depts = sorted(set(list(auto_items.keys()) + list(saved_map.keys())))

        # 부서별 인원 수 (한번에 조회)
        from sqlalchemy import func
        dept_headcounts = dict(
            db.query(User.user_group, func.count(User.id))
            .filter(User.is_active.is_(True), User.is_approved.is_(True))
            .group_by(User.user_group).all()
        )

        dept_reports = []
        for dept in all_depts:
            auto = auto_items.get(dept, [])
            saved = saved_map.get(dept, {})
            hc = dept_headcounts.get(dept, 0)
            dept_reports.append({
                'department': dept,
                'auto_items': auto,
                'manual_items': saved.get('manual_items', []),
                'headcount_total': saved.get('headcount_total', hc),
                'headcount_present': saved.get('headcount_present', hc),
                'headcount_absence_info': saved.get('headcount_absence_info', ''),
                'is_my_dept': dept == user_group,
                'is_saved': dept in saved_map,
            })

        if user_group and not any(d['department'] == user_group for d in dept_reports):
            hc = dept_headcounts.get(user_group, 0)
            dept_reports.insert(0, {
                'department': user_group,
                'auto_items': [],
                'manual_items': [],
                'headcount_total': hc,
                'headcount_present': hc,
                'headcount_absence_info': '',
                'is_my_dept': True,
                'is_saved': False,
            })

    prev_date = (target_date - datetime.timedelta(days=1)).isoformat()
    next_date = (target_date + datetime.timedelta(days=1)).isoformat()

    return render_template(
        'daily_report.html',
        target_date=target_date,
        weekday_kr=WEEKDAY_KR[target_date.weekday()],
        user_group=user_group,
        user_name=session.get('full_name', ''),
        dept_reports=dept_reports,
        prev_date=prev_date,
        next_date=next_date,
    )


@daily_report_bp.route('/daily-report/save', methods=['POST'])
@login_required
def daily_report_save():
    """수동 추가 항목 + 기본사항 저장"""
    target_date_str = request.form.get('report_date', '')
    department = request.form.get('department', session.get('user_group', ''))
    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except ValueError:
        target_date = datetime.date.today()

    user_id = session.get('user_id')
    user_name = session.get('full_name', '')

    try:
        headcount_total = int(request.form.get('headcount_total', 0) or 0)
        headcount_present = int(request.form.get('headcount_present', 0) or 0)
    except (ValueError, TypeError):
        headcount_total = 0
        headcount_present = 0
    headcount_absence_info = request.form.get('headcount_absence_info', '').strip()

    # 본인 부서만 수정 가능
    user_group = session.get('user_group', '')
    if department != user_group:
        flash('본인 부서만 수정할 수 있습니다.', 'danger')
        return redirect(url_for('daily_report.daily_report_view', date=target_date_str))

    manual_raw = request.form.get('manual_items', '').strip()
    manual_items = [line.strip() for line in manual_raw.splitlines() if line.strip()]

    with get_db() as db:
        existing = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
            DailyReport.department == department,
        ).first()

        if existing:
            existing.reporter_name = user_name
            existing.reporter_id = user_id
            existing.headcount_total = headcount_total
            existing.headcount_present = headcount_present
            existing.headcount_absence_info = headcount_absence_info
            existing.items = manual_items
        else:
            report = DailyReport(
                report_date=target_date,
                department=department,
                reporter_name=user_name,
                reporter_id=user_id,
                headcount_total=headcount_total,
                headcount_present=headcount_present,
                headcount_absence_info=headcount_absence_info,
            )
            report.items = manual_items
            db.add(report)

        db.commit()

    flash(f'{department} 업무보고가 저장되었습니다.', 'success')
    return redirect(url_for('daily_report.daily_report_view', date=target_date_str))


@daily_report_bp.route('/daily-report/generate-text')
@login_required
def generate_kakao_text():
    """단일 부서 카카오톡 포맷"""
    target_date_str = request.args.get('date')
    department = request.args.get('department', session.get('user_group', ''))
    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except (ValueError, TypeError):
        target_date = datetime.date.today()

    with get_db() as db:
        auto = _collect_auto_items(db, target_date).get(department, [])
        saved = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
            DailyReport.department == department,
        ).first()
        manual = saved.items if saved else []
        hc_total = saved.headcount_total if saved else 0
        hc_present = saved.headcount_present if saved else 0
        absence = saved.headcount_absence_info if saved else ''

    all_items = auto + manual
    if not all_items:
        return jsonify({'ok': False, 'error': '해당 부서의 업무 내역이 없습니다.'}), 404

    text = _format_kakao_text(department, target_date, hc_total, hc_present, absence, all_items)
    return jsonify({'ok': True, 'text': text})


@daily_report_bp.route('/daily-report/generate-all-text')
@login_required
def generate_all_kakao_text():
    """전체 부서 카카오톡 포맷"""
    target_date_str = request.args.get('date')
    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except (ValueError, TypeError):
        target_date = datetime.date.today()

    with get_db() as db:
        auto_items = _collect_auto_items(db, target_date)
        saved_reports = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
        ).order_by(DailyReport.department).all()
        saved_map = {r.department: r for r in saved_reports}

        all_depts = sorted(set(list(auto_items.keys()) + list(saved_map.keys())))
        texts = []
        for dept in all_depts:
            auto = auto_items.get(dept, [])
            saved = saved_map.get(dept)
            manual = saved.items if saved else []
            all_items = auto + manual
            if not all_items:
                continue
            hc_total = saved.headcount_total if saved else 0
            hc_present = saved.headcount_present if saved else 0
            absence = saved.headcount_absence_info if saved else ''
            texts.append(_format_kakao_text(dept, target_date, hc_total, hc_present, absence, all_items))

    if not texts:
        return jsonify({'ok': False, 'error': '해당 날짜의 보고가 없습니다.'}), 404
    return jsonify({'ok': True, 'text': '\n\n'.join(texts)})


def _format_kakao_text(department, target_date, hc_total, hc_present, absence_info, items):
    """카카오톡 업무보고 포맷"""
    weekday = WEEKDAY_KR[target_date.weekday()]
    date_str = target_date.strftime('%y.%m.%d')
    lines = [
        f"{date_str} {weekday}",
        f"{department} 업무보고",
        "",
        "- 기본사항",
        f"인원 {hc_total}명중 재실 {hc_present}명{' ' + absence_info if absence_info else ''}",
        "",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item}")
    lines.append("")
    lines.append("이상입니다.")
    return '\n'.join(lines)
