import datetime
from collections import defaultdict

from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from modules.auth_decorators import login_required, admin_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from modules.db_context import get_db
from modules.contract_filters import active_contract_filter, DONE_STATUSES
from modules.utils import safe_int
from modules.models import (
    Project, User, HistoryLog, Contract, ContractItem, Drawing,
    DashboardNotice, Delivery, MaterialOrder,
    PurchaseOrder, PurchaseOrderItem,
    BusinessTrip, BusinessTripMember,
)
from modules.services.dashboard_actions import (
    get_dashboard_setting_int,
    handle_update_global_seconds,
    handle_create_notice,
    handle_update_notice,
    handle_delete_notice,
)
from modules.services.ical_sync import get_leave_events_for_month, get_leave_events_for_date
from modules.dashboard_utils import (
    project_detail_link,
    resolve_kanban_stage,
    project_primary_contract,
    days_until,
    dday_badge,
    hot_project_count,
    build_action_tabs,
    build_month_calendar,
    build_auto_alert_items,
    build_dashboard_priority_items,
    history_detail_link,
)

dashboard_bp = Blueprint('dashboard', __name__)

ACTION_HANDLERS = {
    'update_global_seconds': handle_update_global_seconds,
    'create_notice': handle_create_notice,
    'update_notice': handle_update_notice,
    'delete_notice': handle_delete_notice,
}


@dashboard_bp.route('/dashboard/notices', methods=['GET', 'POST'])
@admin_required
def dashboard_notice_admin():

    with get_db() as db:
        if request.method == 'POST':
            action = (request.form.get('action') or '').strip()

            handler = ACTION_HANDLERS.get(action)
            if handler:
                result = handler(db, request.form)
                if result.get('flash'):
                    flash(*result['flash'])

            db.commit()
            return redirect(url_for('dashboard.dashboard_notice_admin'))

        notices = db.query(DashboardNotice).order_by(DashboardNotice.sort_order.asc(), DashboardNotice.id.asc()).all()

        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)
        auto_notice_items = build_auto_alert_items(db, today, week_later)
        global_display_seconds = max(2, get_dashboard_setting_int(db, 'billboard_global_seconds', 6))

        return render_template(
            'dashboard_notice_admin.html',
            notices=notices,
            auto_notice_items=auto_notice_items,
            global_display_seconds=global_display_seconds,
        )


@dashboard_bp.route('/dashboard')
@login_required
def dashboard_view():
    """계약/납품 중심 메인 현황판"""

    with get_db() as db:
        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1, day=1)

        contracted_count = db.query(Project).filter(
            Project.is_contracted.is_(True), active_contract_filter()
        ).count()

        contracted_projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(True), active_contract_filter())
            .options(
                joinedload(Project.materials),
                joinedload(Project.priority_override),
                joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.drawings),
            )
            .order_by(Project.created_at.desc(), Project.id.desc())
            .all()
        )

        # design_projects 제거 — Priority Brief 삭제로 불필요

        deliveries = (
            db.query(Delivery)
            .join(Project, Project.id == Delivery.project_id)
            .filter(Project.is_contracted.is_(True), active_contract_filter())
            .options(
                joinedload(Delivery.project),
                joinedload(Delivery.contract),
                joinedload(Delivery.splits),
                joinedload(Delivery.photos),
            )
            .order_by(Delivery.updated_at.desc(), Delivery.id.desc())
            .all()
        )

        urgent_contracts = (
            db.query(Contract)
            .join(Project, Project.id == Contract.project_id)
            .filter(
                Project.is_contracted.is_(True),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date >= today,
                Contract.delivery_due_date <= week_later,
            )
            .options(joinedload(Contract.project))
            .order_by(Contract.delivery_due_date.asc(), Contract.id.asc())
            .all()
        )
        urgent_delivery_count = len(urgent_contracts)
        urgent_delivery_projects = [c.project for c in urgent_contracts if c.project]

        # 진행현장 ID 목록 (contracted_projects와 동일 기준)
        active_project_ids = [p.id for p in contracted_projects]

        prod_waiting_contract_ids = {
            pid
            for (pid,) in db.query(Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .filter(
                Contract.project_id.in_(active_project_ids),
                ContractItem.status_prod.in_(['자재대기중', '생산대기중'])
            )
            .distinct()
            .all()
        } if active_project_ids else set()
        prod_waiting_site_count = len(prod_waiting_contract_ids)

        material_pending_project_ids = {
            pid
            for (pid,) in db.query(Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .filter(
                Contract.project_id.in_(active_project_ids),
                ContractItem.status_admin != '입고완료'
            )
            .distinct()
            .all()
        } if active_project_ids else set()

        overdue_project_ids = {
            pid
            for (pid,) in db.query(Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .filter(
                Contract.project_id.in_(active_project_ids),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date < today,
                ContractItem.status_prod != '생산완료',
            )
            .distinct()
            .all()
        } if active_project_ids else set()
        waiting_delay_site_count = len(set(prod_waiting_contract_ids) | set(material_pending_project_ids) | set(overdue_project_ids))

        issue_project_ids = set()

        issue_status_project_ids = db.query(Project.id).filter(
            Project.is_contracted.is_(True),
            Project.status.like('%이슈%')
        ).all()
        issue_project_ids.update(pid for (pid,) in issue_status_project_ids)

        issue_contract_item_project_ids = (
            db.query(Contract.project_id)
            .join(Project, Project.id == Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .filter(
                Project.is_contracted.is_(True),
                or_(
                    ContractItem.status_sales == '이슈',
                    ContractItem.status_admin == '이슈',
                    ContractItem.status_prod == '이슈',
                )
            )
            .distinct()
            .all()
        )
        issue_project_ids.update(pid for (pid,) in issue_contract_item_project_ids)

        issue_log_project_ids = db.query(HistoryLog.project_id).join(Project, Project.id == HistoryLog.project_id).filter(
            Project.is_contracted.is_(True),
            HistoryLog.content.like('%이슈%')
        ).all()
        issue_project_ids.update(pid for (pid,) in issue_log_project_ids)
        as_issue_count = len(issue_project_ids)

        # timeline_items는 피드 API(/api/dashboard/feed)로 이관됨

        monthly_delivery_contracts = (
            db.query(Contract)
            .join(Project, Project.id == Contract.project_id)
            .filter(
                Project.is_contracted.is_(True),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date >= month_start,
                Contract.delivery_due_date < next_month_start,
            )
            .options(joinedload(Contract.project))
            .order_by(Contract.delivery_due_date.asc(), Contract.id.asc())
            .all()
        )
        mini_calendar_items = [
            {
                'project_id': c.project.id,
                'contract_id': c.id,
                'date': c.delivery_due_date,
                'dday': days_until(c.delivery_due_date, today),
                'project_name': c.project.short_name or c.project.temp_name,
                'project_no': c.project.project_no,
                'contract_name': c.contract_name,
                'detail_url': url_for('project.contract_detail', project_id=c.project.id),
            }
            for c in monthly_delivery_contracts if c.project
        ]
        calendar_weeks = build_month_calendar(today, mini_calendar_items)

        kanban = defaultdict(list)
        for project in contracted_projects:
            stage = resolve_kanban_stage(project)
            kanban[stage].append(
                {
                    'project_id': project.id,
                    'project_no': project.project_no,
                    'project_name': project.short_name or project.temp_name,
                    'is_urgent': project.is_urgent,
                    'status': project.status,
                    'detail_url': project_detail_link(project),
                }
            )

        action_tabs = build_action_tabs(contracted_projects, deliveries, today)
        # dashboard_priority 제거 — 통합 피드로 이관, Priority Brief 삭제됨
        delivery_active_project_ids = {
            delivery.project_id
            for delivery in deliveries
            if (delivery.delivery_status or '').strip() in {'coordinating', 'in_progress'}
        }
        workflow_nodes = [
            {
                'title': '영업/설계',
                'subtitle': '협의/설계 기준 정리',
                'count': len(kanban['영업/설계']),
                'hot_count': hot_project_count(action_tabs['sales']),
                'tone': 'primary',
                'action_url': url_for('sales.sales_list'),
            },
            {
                'title': '자재확인',
                'subtitle': '발주 / 입고 상태 추적',
                'count': len(kanban['자재확인']),
                'hot_count': hot_project_count(action_tabs['material']),
                'tone': 'warning',
                'action_url': url_for('material.material_management'),
            },
            {
                'title': '생산중',
                'subtitle': '공정 진행 및 병목 대응',
                'count': len(kanban['생산중']),
                'hot_count': hot_project_count(action_tabs['production']),
                'tone': 'primary',
                'action_url': url_for('production.production_management'),
            },
            {
                'title': '출고대기',
                'subtitle': '생산완료 후 출고 준비',
                'count': len(kanban['출고대기']),
                'hot_count': len({p['project_id'] for p in kanban['출고대기'] if p.get('is_urgent')}),
                'tone': 'success',
                'action_url': url_for('project.contract_list'),
            },
            {
                'title': '납품진행',
                'subtitle': '일정 / 담당 / 완료사진 관리',
                'count': len(delivery_active_project_ids),
                'hot_count': hot_project_count(action_tabs['delivery']),
                'tone': 'danger',
                'action_url': url_for('delivery.delivery_management'),
            },
        ]

        # billboard/전광판은 통합 피드로 이관됨
        pending_users = db.query(User).filter(User.is_approved.is_(False)).count()

        # ── 입고 지연 알림은 스케줄러(07:00)로 이관됨 ──

        # ── 입고예정 통계 (발주서 품목 기준) ──
        _base_expected = db.query(PurchaseOrderItem).join(
            PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id
        ).filter(
            PurchaseOrder.status.in_(['발송완료', '입고대기']),
            (PurchaseOrderItem.in_confirmed == False) | (PurchaseOrderItem.in_confirmed.is_(None)),
        )
        _has_date = _base_expected.filter(PurchaseOrderItem.expected_in_date.isnot(None))
        dash_expected = {
            'overdue': _has_date.filter(PurchaseOrderItem.expected_in_date < today).count(),
            'today': _has_date.filter(PurchaseOrderItem.expected_in_date == today).count(),
            'this_week': _has_date.filter(
                PurchaseOrderItem.expected_in_date >= today,
                PurchaseOrderItem.expected_in_date <= week_later,
            ).count(),
            'unknown': _base_expected.filter(PurchaseOrderItem.expected_in_date.is_(None)).count(),
        }

        # 연차 캘린더 동기화 (외부 iCal) + 전자결재 승인 휴가 병합
        from modules.services import approval_service as _appsvc
        leave_by_date = get_leave_events_for_month(today.year, today.month)
        today_leaves = get_leave_events_for_date(today)
        try:
            ea_month = _appsvc.get_approved_leaves_for_month(db, today.year, today.month)
            for _d, _evs in ea_month.items():
                leave_by_date.setdefault(_d, []).extend(_evs)
            today_leaves = list(today_leaves) + _appsvc.get_approved_leaves_for_date(db, today)
        except Exception:
            pass

        # ── 최근 코멘트 (전체 현장) ──
        recent_comments_raw = (
            db.query(HistoryLog)
            .join(Project, Project.id == HistoryLog.project_id)
            .filter(
                HistoryLog.log_kind.in_(['comment', 'reply']),
                Project.is_contracted.is_(True),
            )
            .order_by(HistoryLog.created_at.desc())
            .limit(10)
            .all()
        )
        recent_comments = []
        for log in recent_comments_raw:
            project = db.query(Project).get(log.project_id)
            if not project:
                continue
            recent_comments.append({
                'user_name': log.user_name or '사용자',
                'project_name': project.short_name or project.temp_name,
                'content': (log.content or '')[:80],
                'scope': log.log_scope or 'common',
                'created_at': log.created_at,
                'link': url_for('project.contract_detail', project_id=project.id) + '#history-board',
            })

        # 오늘 출장 중인 인원
        today_dt = datetime.datetime.combine(today, datetime.time.min)
        today_trips = (
            db.query(BusinessTrip)
            .options(joinedload(BusinessTrip.members))
            .filter(
                BusinessTrip.status.in_(['예정', '진행중']),
                BusinessTrip.departure_date <= datetime.datetime.combine(today, datetime.time.max),
                BusinessTrip.return_date >= today_dt,
            )
            .order_by(BusinessTrip.departure_date)
            .all()
        )

        # calendar_weeks에 연차 정보 주입
        for week in calendar_weeks:
            for cell in week:
                cell_date = datetime.date(today.year, today.month, cell['day']) if cell.get('in_month') else None
                cell['leaves'] = leave_by_date.get(cell_date, []) if cell_date else []

        return render_template(
            'dashboard.html',
            today=today,
            kpi={
                'contracted_count': contracted_count,
                'urgent_delivery_count': urgent_delivery_count,
                'prod_waiting_site_count': prod_waiting_site_count,
                'material_pending_site_count': len(material_pending_project_ids),
                'overdue_site_count': len(overdue_project_ids),
                'waiting_delay_site_count': waiting_delay_site_count,
                'as_issue_count': as_issue_count,
                'pending_users': pending_users,
                'urgent_delivery_projects': urgent_delivery_projects[:6],
            },
            mini_calendar_items=mini_calendar_items,
            calendar_weeks=calendar_weeks,
            calendar_month_label=f"{today.year}.{today.month:02d}",
            calendar_weekdays=['일', '월', '화', '수', '목', '금', '토'],
            today_leaves=today_leaves,
            today_trips=today_trips,
            kanban={
                '영업/설계': kanban['영업/설계'],
                '자재확인': kanban['자재확인'],
                '생산중': kanban['생산중'],
                '출고대기': kanban['출고대기'],
            },
            workflow_nodes=workflow_nodes,
            action_tabs=action_tabs,
            dash_expected=dash_expected,
            recent_comments=recent_comments,
        )


@dashboard_bp.route('/api/kpi-summary')
@login_required
def kpi_summary_api():
    """상단 고정 바용 KPI 요약 (가벼운 카운트만)"""
    with get_db() as db:
        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)

        contracted_count = db.query(Project).filter(
            Project.is_contracted.is_(True), active_contract_filter()
        ).count()

        active_project_ids = [
            pid for (pid,) in db.query(Project.id).filter(
                Project.is_contracted.is_(True), active_contract_filter()
            ).all()
        ]

        urgent_delivery_count = db.query(Contract).join(
            Project, Project.id == Contract.project_id
        ).filter(
            Project.is_contracted.is_(True),
            Contract.delivery_due_date.isnot(None),
            Contract.delivery_due_date >= today,
            Contract.delivery_due_date <= week_later,
        ).count()

        overdue_count = 0
        if active_project_ids:
            overdue_count = db.query(Contract.project_id).join(
                ContractItem, ContractItem.contract_id == Contract.id
            ).filter(
                Contract.project_id.in_(active_project_ids),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date < today,
                ContractItem.status_prod != '생산완료',
            ).distinct().count()

        pending_users = db.query(User).filter(
            User.is_approved.is_(False)
        ).count()

        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        return jsonify({
            'contracted_count': contracted_count,
            'urgent_delivery_count': urgent_delivery_count,
            'overdue_count': overdue_count,
            'pending_users': pending_users,
            'today': today.strftime('%Y.%m.%d'),
            'weekday': weekdays[today.weekday()],
        })