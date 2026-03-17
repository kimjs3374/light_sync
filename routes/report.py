import datetime
from flask import Blueprint, render_template, request, session
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models import Project, HistoryLog
from modules.services.g2b_catalog_sync import get_catalog_price_map, match_from_price_map

report_bp = Blueprint('report', __name__)


@report_bp.route('/report/weekly')
@login_required
def weekly_report():
    """설계관리 주간 업무보고서 생성"""
    # 날짜 범위: 기본값은 이번 주 월~일
    today = datetime.date.today()
    # 이번 주 월요일
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end = week_start + datetime.timedelta(days=6)

    # 사용자 지정 날짜
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if start_str:
        try:
            week_start = datetime.date.fromisoformat(start_str)
        except ValueError:
            pass
    if end_str:
        try:
            week_end = datetime.date.fromisoformat(end_str)
        except ValueError:
            pass

    with get_db() as db:
        # 1. 진행중인 설계관리 프로젝트 (미계약)
        active_projects = db.query(Project).filter(
            Project.is_contracted.is_(False)
        ).options(
            joinedload(Project.materials),
            joinedload(Project.contacts),
        ).order_by(Project.expected_contract_date.asc().nullslast(), Project.id.desc()).all()

        # 2. 해당 기간 내 신규 등록된 프로젝트
        new_projects = db.query(Project).filter(
            Project.created_at >= datetime.datetime.combine(week_start, datetime.time.min),
            Project.created_at <= datetime.datetime.combine(week_end, datetime.time.max),
        ).order_by(Project.created_at.desc()).all()

        # 3. 해당 기간 내 계약 전환된 프로젝트
        converted_projects = db.query(Project).filter(
            Project.is_contracted.is_(True),
            Project.contract_date >= week_start,
            Project.contract_date <= week_end,
        ).options(
            joinedload(Project.contracts),
        ).order_by(Project.contract_date.desc()).all()

        # 4. 해당 기간 내 활동 이력 (design scope)
        recent_logs = db.query(HistoryLog).filter(
            HistoryLog.created_at >= datetime.datetime.combine(week_start, datetime.time.min),
            HistoryLog.created_at <= datetime.datetime.combine(week_end, datetime.time.max),
            HistoryLog.log_scope.in_(['design', 'common']),
            HistoryLog.log_kind != 'reply',
        ).options(
            joinedload(HistoryLog.project),
        ).order_by(HistoryLog.created_at.desc()).limit(30).all()

        # 5. 긴급/지연 프로젝트
        urgent_projects = [p for p in active_projects if p.is_urgent]
        overdue_projects = [p for p in active_projects
                           if p.expected_contract_date and p.expected_contract_date < today]

        # 6. 통계
        stats = {
            'total_active': len(active_projects),
            'new_count': len(new_projects),
            'converted_count': len(converted_projects),
            'urgent_count': len(urgent_projects),
            'overdue_count': len(overdue_projects),
        }

        # 계약 전환 프로젝트 예상금액 계산
        price_map = get_catalog_price_map(db)
        for p in converted_projects:
            total_amount = 0
            for c in (p.contracts or []):
                for item in (c.items or []):
                    match = match_from_price_map(price_map, item.model_name)
                    if match['matched'] and match['unit_price']:
                        total_amount += item.quantity * match['unit_price']
            p._estimated_amount = total_amount if total_amount > 0 else None

        # D-Day 계산 helper
        def calc_dday(p):
            if p.expected_contract_date:
                return (p.expected_contract_date - today).days
            return None

    return render_template(
        'report_weekly.html',
        week_start=week_start,
        week_end=week_end,
        today=today,
        active_projects=active_projects,
        new_projects=new_projects,
        converted_projects=converted_projects,
        recent_logs=recent_logs,
        urgent_projects=urgent_projects,
        overdue_projects=overdue_projects,
        stats=stats,
        calc_dday=calc_dday,
        report_date=today,
        reporter=request.args.get('reporter', ''),
    )
