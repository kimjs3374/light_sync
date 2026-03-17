import calendar as calendar_lib
import datetime
from collections import defaultdict

from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from modules.db_context import get_db
from modules.models import Project, Material, User, HistoryLog, Contract, ContractItem, DashboardNotice, DashboardSetting, Delivery
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)

dashboard_bp = Blueprint('dashboard', __name__)


def _project_detail_link(project):
    if project.is_contracted:
        return url_for('project.contract_detail', project_id=project.id)
    return url_for('project.project_detail', project_id=project.id)


def _resolve_kanban_stage(project):
    """계약 현장 기준 대표 단계를 계산하여 4단계 칸반에 배치한다."""
    contract_items = []
    for contract in (project.contracts or []):
        contract_items.extend(contract.items or [])

    # 계약 데이터 우선, 예외적으로 과거 데이터 호환을 위해 materials를 fallback으로 사용
    materials = project.materials or []
    prod_statuses = [((i.status_prod or '').strip()) for i in contract_items] + [((m.status_prod or '').strip()) for m in materials]
    admin_statuses = [((i.status_admin or '').strip()) for i in contract_items] + [((m.status_admin or '').strip()) for m in materials]

    if any(s == '생산완료' for s in prod_statuses):
        return '출고대기'

    if any(s == '생산중' for s in prod_statuses):
        return '생산중'

    if any(s in {'자재확인중', '자재발주', '입고완료'} for s in admin_statuses):
        return '자재확인'

    if any(s in {'자재대기중', '생산대기중'} for s in prod_statuses):
        return '자재확인'

    status_text = (project.status or '').strip()
    if status_text in {'설계/영업', '영업 진행', '설계 진행', '영업/설계'}:
        return '영업/설계'

    return '영업/설계'


def _is_admin():
    return session.get('role') == 'admin'


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_dashboard_setting_int(db, key, default_value):
    row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == key).first()
    if not row:
        return default_value
    return _safe_int(row.setting_value, default_value)


def _set_dashboard_setting_int(db, key, value):
    row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == key).first()
    if not row:
        row = DashboardSetting(setting_key=key, setting_value=str(value))
        db.add(row)
    else:
        row.setting_value = str(value)


def _project_primary_contract(project):
    contracts = sorted(project.contracts or [], key=lambda c: c.delivery_due_date or datetime.date.max)
    return contracts[0] if contracts else None


def _days_until(date_value, today):
    if not date_value:
        return None
    return (date_value - today).days


def _dday_badge(dday):
    if dday is None:
        return '일정미정', 'secondary', 3
    if dday < 0:
        return f'D+{-dday}', 'danger', 0
    if dday == 0:
        return 'D-Day', 'danger', 0
    if dday <= 3:
        return f'D-{dday}', 'danger', 0
    if dday <= 7:
        return f'D-{dday}', 'warning', 1
    return f'D-{dday}', 'primary', 2


def _delivery_status_label(status):
    return {
        'waiting': '납품대기',
        'coordinating': '납품협의중',
        'in_progress': '납품진행중',
        'done': '납품완료',
    }.get((status or '').strip(), (status or '-').strip() or '-')


def _is_delivery_done_photo(photo):
    return (photo.photo_type or '').strip() in {'delivery_done', '납품완료'}


def _sort_action_items(items, limit=6):
    items.sort(key=lambda item: (item['sort_priority'], item['sort_dday'], item['project_name'], item['title']))
    return items[:limit]


def _hot_project_count(items):
    return len({item['project_id'] for item in items if item.get('chip_class') in {'danger', 'warning'} or item.get('badge_class') in {'danger', 'warning'}})


def _build_action_tabs(contracted_projects, deliveries, today):
    tabs = {
        'sales': [],
        'material': [],
        'production': [],
        'delivery': [],
    }

    for project in contracted_projects:
        primary_contract = _project_primary_contract(project)
        dday = _days_until(primary_contract.delivery_due_date if primary_contract else None, today)
        badge_text, badge_class, badge_priority = _dday_badge(dday)
        project_name = project.short_name or project.temp_name

        for contract in (project.contracts or []):
            for item in (contract.items or []):
                sales_status = (item.status_sales or '계약확인').strip()
                admin_status = (item.status_admin or '자재확인중').strip()
                prod_status = (item.status_prod or '자재대기중').strip()
                model_name = item.model_name or '-'
                subtitle = f"{contract.contract_name} · {model_name}"

                if sales_status != '협의완료':
                    chip_text = '생산 선행 위험' if prod_status in {'생산중', '생산완료'} else '협의 미완료'
                    chip_class = 'danger' if prod_status in {'생산중', '생산완료'} else ('warning' if dday is not None and dday <= 7 else 'primary')
                    tabs['sales'].append(
                        {
                            'project_id': project.id,
                            'project_name': project_name,
                            'project_no': project.project_no,
                            'title': project_name,
                            'subtitle': subtitle,
                            'meta': f"영업상태 {sales_status}",
                            'badge_text': badge_text,
                            'badge_class': badge_class,
                            'chip_text': chip_text,
                            'chip_class': chip_class,
                            'action_label': '영업 처리',
                            'action_url': url_for('sales.sales_detail', project_id=project.id),
                            'sort_priority': min(badge_priority, 0 if chip_class == 'danger' else 1 if chip_class == 'warning' else 2),
                            'sort_dday': dday if dday is not None else 99999,
                        }
                    )

                if admin_status != '입고완료':
                    chip_class = 'danger' if dday is not None and dday <= 3 else ('warning' if dday is not None and dday <= 7 else 'primary')
                    tabs['material'].append(
                        {
                            'project_id': project.id,
                            'project_name': project_name,
                            'project_no': project.project_no,
                            'title': project_name,
                            'subtitle': subtitle,
                            'meta': f"자재상태 {admin_status}",
                            'badge_text': badge_text,
                            'badge_class': badge_class,
                            'chip_text': admin_status,
                            'chip_class': chip_class,
                            'action_label': '자재 확인',
                            'action_url': url_for('project.material_detail', project_id=project.id),
                            'sort_priority': min(badge_priority, 0 if chip_class == 'danger' else 1 if chip_class == 'warning' else 2),
                            'sort_dday': dday if dday is not None else 99999,
                        }
                    )

                if prod_status != '생산완료':
                    if sales_status != '협의완료' and prod_status in {'생산중', '생산완료'}:
                        chip_text = '생산 선행 위험'
                        chip_class = 'danger'
                    elif dday is not None and dday < 0:
                        chip_text = '납기 초과'
                        chip_class = 'danger'
                    elif dday is not None and dday <= 7:
                        chip_text = '납기 임박'
                        chip_class = 'warning'
                    else:
                        chip_text = prod_status
                        chip_class = 'primary'

                    tabs['production'].append(
                        {
                            'project_id': project.id,
                            'project_name': project_name,
                            'project_no': project.project_no,
                            'title': project_name,
                            'subtitle': subtitle,
                            'meta': f"생산상태 {prod_status}",
                            'badge_text': badge_text,
                            'badge_class': badge_class,
                            'chip_text': chip_text,
                            'chip_class': chip_class,
                            'action_label': '생산 보기',
                            'action_url': url_for('production.production_detail', project_id=project.id),
                            'sort_priority': min(badge_priority, 0 if chip_class == 'danger' else 1 if chip_class == 'warning' else 2),
                            'sort_dday': dday if dday is not None else 99999,
                        }
                    )

    for delivery in deliveries:
        project = delivery.project
        contract = delivery.contract
        if not project:
            continue

        project_name = project.short_name or project.temp_name
        dday = _days_until(contract.delivery_due_date if contract else None, today)
        badge_text, badge_class, badge_priority = _dday_badge(dday)
        has_done_photo = any(_is_delivery_done_photo(photo) for photo in (delivery.photos or []))
        needs_done_photo = bool(
            (delivery.planned_total_qty or 0) > 0
            and (delivery.delivered_total_qty or 0) >= (delivery.planned_total_qty or 0)
            and not has_done_photo
        )
        is_unassigned = not (delivery.contact_name or '').strip()
        status_label = _delivery_status_label(delivery.delivery_status)
        should_track = bool(is_unassigned or needs_done_photo or (dday is not None and dday <= 7) or (delivery.delivery_status or '').strip() in {'coordinating', 'in_progress'})

        if not should_track:
            continue

        if is_unassigned:
            chip_text = '담당자 미배정'
            chip_class = 'danger'
        elif needs_done_photo:
            chip_text = '완료사진 누락'
            chip_class = 'warning'
        elif dday is not None and dday <= 3:
            chip_text = '납품 일정 확인'
            chip_class = 'danger'
        elif dday is not None and dday <= 7:
            chip_text = '납품 준비 필요'
            chip_class = 'warning'
        else:
            chip_text = status_label
            chip_class = 'primary'

        tabs['delivery'].append(
            {
                'project_id': project.id,
                'project_name': project_name,
                'project_no': project.project_no,
                'title': project_name,
                'subtitle': f"{(contract.contract_name if contract else '계약 미연결')} · 담당 {(delivery.contact_name or '미배정')}",
                'meta': f"납품상태 {status_label}",
                'badge_text': badge_text,
                'badge_class': badge_class,
                'chip_text': chip_text,
                'chip_class': chip_class,
                'action_label': '납품 확인',
                'action_url': url_for('delivery.delivery_detail', project_id=project.id),
                'sort_priority': min(badge_priority, 0 if chip_class == 'danger' else 1 if chip_class == 'warning' else 2),
                'sort_dday': dday if dday is not None else 99999,
            }
        )

    for key in list(tabs.keys()):
        tabs[key] = _sort_action_items(tabs[key])

    return tabs


def _build_month_calendar(today, items):
    calendar_obj = calendar_lib.Calendar(firstweekday=6)
    items_by_date = defaultdict(list)
    for item in items:
        if item.get('date'):
            items_by_date[item['date']].append(item)

    weeks = []
    for week in calendar_obj.monthdatescalendar(today.year, today.month):
        week_cells = []
        for day in week:
            day_items = items_by_date.get(day, [])
            week_cells.append(
                {
                    'date': day,
                    'day': day.day,
                    'in_month': day.month == today.month,
                    'is_today': day == today,
                    'items': day_items,
                    'is_urgent': any((item.get('dday') is not None and item.get('dday') <= 3) for item in day_items),
                }
            )
        weeks.append(week_cells)
    return weeks


def _build_auto_alert_items(db, today, week_later):
    """자동 생성 전광판 문구 + 원문 이동 링크를 생성한다."""
    contracted_projects = (
        db.query(Project)
        .filter(Project.is_contracted.is_(True))
        .options(joinedload(Project.contracts))
        .order_by(Project.created_at.desc(), Project.id.desc())
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

    auto_items = []

    for project in contracted_projects:
        is_urgent_project = project.is_urgent or any(c.is_urgent_prod for c in (project.contracts or []))
        if is_urgent_project:
            auto_items.append(
                {
                    'level': 'danger',
                    'label': '긴급현장',
                    'message': f"{project.short_name or project.temp_name} · 긴급 대응 필요",
                    'detail_url': url_for('project.contract_detail', project_id=project.id),
                    'rule': '현장 긴급 플래그(project.is_urgent) 또는 계약 긴급제작(contract.is_urgent_prod)'
                }
            )

    for c in urgent_contracts[:6]:
        if not c.project:
            continue
        auto_items.append(
            {
                'level': 'warning',
                'label': '납품임박',
                'message': f"{c.delivery_due_date.strftime('%m/%d')} · {c.project.short_name or c.project.temp_name} ({c.contract_name})",
                'detail_url': url_for('project.contract_detail', project_id=c.project.id),
                'rule': '계약 납품기일(Contract.delivery_due_date)이 오늘~7일 이내'
            }
        )

    uniq = []
    seen = set()
    for b in auto_items:
        key = f"{b['label']}|{b['message']}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)

    return uniq[:8]


def _build_dashboard_priority_items(design_projects, contracted_projects, deliveries, today, limit=5):
    delivery_map = defaultdict(list)
    for delivery in deliveries:
        delivery_map[delivery.project_id].append(delivery)

    items = []

    for project in design_projects:
        reasons = []
        override = append_manual_priority_reason(reasons, project)
        dday = _days_until(project.expected_contract_date, today)

        if project.is_urgent:
            append_priority_reason(reasons, 'urgent')
        append_due_priority_reason(reasons, dday, 'project')

        if not reasons:
            continue

        meta_lines = [
            '단계: 영업/설계',
            f"계약예정일: {project.expected_contract_date.strftime('%Y-%m-%d') if project.expected_contract_date else '-'}",
            f"설계 품목: {len(project.materials or [])}건",
        ]
        if override and override.note:
            meta_lines.insert(0, f"수동 사유: {override.note}")

        items.append(make_priority_entry(
            project_id=project.id,
            project_no=project.project_no,
            title=project.short_name or project.temp_name or '-',
            subtitle='설계관리 우선 브리핑',
            detail_url=url_for('project.project_detail', project_id=project.id),
            reasons=reasons,
            dday=dday,
            override_note=(override.note if override and override.note else ''),
            meta_lines=meta_lines,
        ))

    for project in contracted_projects:
        reasons = []
        override = append_manual_priority_reason(reasons, project)
        primary_contract = _project_primary_contract(project)
        dday = _days_until(primary_contract.delivery_due_date if primary_contract else None, today)

        contracts = list(project.contracts or [])
        contract_items = []
        for contract in contracts:
            contract_items.extend(contract.items or [])

        sales_pending_count = sum(1 for item in contract_items if (item.status_sales or '계약확인').strip() != '협의완료')
        material_pending_count = sum(1 for item in contract_items if (item.status_admin or '자재확인중').strip() != '입고완료')
        production_pending_count = sum(1 for item in contract_items if (item.status_prod or '자재대기중').strip() != '생산완료')
        is_urgent_project = bool(project.is_urgent or any(contract.is_urgent_prod for contract in contracts))
        has_inspection = any(contract.is_prof_inspection for contract in contracts)

        deliveries_for_project = delivery_map.get(project.id, [])
        delivery_unassigned_count = sum(1 for delivery in deliveries_for_project if not (delivery.contact_name or '').strip())
        delivery_today_count = 0
        for delivery in deliveries_for_project:
            for split in (delivery.splits or []):
                base_date = split.confirmed_date or split.scheduled_date
                if base_date == today:
                    delivery_today_count += 1

        if is_urgent_project:
            append_priority_reason(reasons, 'urgent')
        if has_inspection:
            append_priority_reason(reasons, 'inspection')
        append_due_priority_reason(reasons, dday, 'contract')
        if sales_pending_count > 0:
            append_priority_reason(reasons, 'sales_pending', f"협의 {sales_pending_count}건")
        if material_pending_count > 0:
            append_priority_reason(reasons, 'material_pending', f"자재 {material_pending_count}건")
        if production_pending_count > 0 and dday is not None and dday <= 7:
            append_priority_reason(reasons, 'production_warning', f"생산 {production_pending_count}건")
        if delivery_unassigned_count > 0:
            append_priority_reason(reasons, 'delivery_unassigned', f"미배정 {delivery_unassigned_count}건")
        if delivery_today_count > 0:
            append_priority_reason(reasons, 'delivery_today', f"금일 {delivery_today_count}건")

        if not reasons:
            continue

        meta_lines = [
            f"단계: {_resolve_kanban_stage(project)}",
            f"대표 계약: {primary_contract.contract_name if primary_contract else '-'}",
            f"협의/자재/생산 미완료: {sales_pending_count}/{material_pending_count}/{production_pending_count}",
        ]
        if override and override.note:
            meta_lines.insert(0, f"수동 사유: {override.note}")

        items.append(make_priority_entry(
            project_id=project.id,
            project_no=project.project_no,
            title=project.short_name or project.temp_name or '-',
            subtitle='계약 이후 통합 우선 브리핑',
            detail_url=url_for('project.contract_detail', project_id=project.id),
            reasons=reasons,
            dday=dday,
            override_note=(override.note if override and override.note else ''),
            meta_lines=meta_lines,
        ))

    items = sort_priority_entries(items)
    return {
        'total': len(items),
        'items': items[:limit],
        'more_count': max(0, len(items) - limit),
    }


@dashboard_bp.route('/dashboard/notices', methods=['GET', 'POST'])
def dashboard_notice_admin():
    if not _is_admin():
        return redirect(url_for('dashboard.dashboard_view'))

    with get_db() as db:
        if request.method == 'POST':
            action = (request.form.get('action') or '').strip()

            if action == 'update_global_seconds':
                global_seconds = max(2, _safe_int(request.form.get('global_display_seconds'), 6))
                _set_dashboard_setting_int(db, 'billboard_global_seconds', global_seconds)
                db.commit()
                flash('전광판 전역 노출시간이 저장되었습니다.', 'success')
                return redirect(url_for('dashboard.dashboard_notice_admin'))

            if action == 'create_notice':
                title = (request.form.get('title') or '공지').strip()
                message = (request.form.get('message') or '').strip()
                level = (request.form.get('level') or 'info').strip()
                sort_order = _safe_int(request.form.get('sort_order'), 100)
                display_seconds = max(2, _safe_int(request.form.get('display_seconds'), 6))
                is_active = request.form.get('is_active') == '1'

                if not message:
                    flash('공지 메시지를 입력해 주세요.', 'warning')
                else:
                    db.add(DashboardNotice(
                        title=title or '공지',
                        message=message,
                        level=level if level in {'info', 'warning', 'danger'} else 'info',
                        sort_order=sort_order,
                        display_seconds=display_seconds,
                        is_active=is_active,
                    ))
                    db.commit()
                    flash('전광판 공지가 등록되었습니다.', 'success')

            elif action == 'update_notice':
                notice_id = _safe_int(request.form.get('notice_id'))
                notice = db.query(DashboardNotice).get(notice_id)
                if notice:
                    notice.title = (request.form.get('title') or '공지').strip() or '공지'
                    notice.message = (request.form.get('message') or '').strip()
                    notice.level = (request.form.get('level') or 'info').strip()
                    if notice.level not in {'info', 'warning', 'danger'}:
                        notice.level = 'info'
                    notice.sort_order = _safe_int(request.form.get('sort_order'), 100)
                    notice.display_seconds = max(2, _safe_int(request.form.get('display_seconds'), 6))
                    notice.is_active = request.form.get('is_active') == '1'
                    if not notice.message:
                        flash('공지 메시지는 비워둘 수 없습니다.', 'warning')
                    else:
                        db.commit()
                        flash('전광판 공지가 수정되었습니다.', 'success')

            elif action == 'delete_notice':
                notice_id = _safe_int(request.form.get('notice_id'))
                notice = db.query(DashboardNotice).get(notice_id)
                if notice:
                    db.delete(notice)
                    db.commit()
                    flash('전광판 공지가 삭제되었습니다.', 'warning')

            return redirect(url_for('dashboard.dashboard_notice_admin'))

        notices = db.query(DashboardNotice).order_by(DashboardNotice.sort_order.asc(), DashboardNotice.id.asc()).all()

        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)
        auto_notice_items = _build_auto_alert_items(db, today, week_later)
        global_display_seconds = max(2, _get_dashboard_setting_int(db, 'billboard_global_seconds', 6))

        return render_template(
            'dashboard_notice_admin.html',
            notices=notices,
            auto_notice_items=auto_notice_items,
            global_display_seconds=global_display_seconds,
        )


@dashboard_bp.route('/dashboard')
def dashboard_view():
    """계약/납품 중심 메인 현황판"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    with get_db() as db:
        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1, day=1)

        contracted_count = db.query(Project).filter(Project.is_contracted.is_(True)).count()

        contracted_projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(True))
            .options(
                joinedload(Project.materials),
                joinedload(Project.priority_override),
                joinedload(Project.contracts).joinedload(Contract.items),
            )
            .order_by(Project.created_at.desc(), Project.id.desc())
            .all()
        )

        design_projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(False))
            .options(
                joinedload(Project.materials),
                joinedload(Project.contacts),
                joinedload(Project.priority_override),
            )
            .order_by(Project.created_at.desc(), Project.id.desc())
            .all()
        )

        deliveries = (
            db.query(Delivery)
            .join(Project, Project.id == Delivery.project_id)
            .filter(Project.is_contracted.is_(True))
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

        prod_waiting_contract_ids = {
            pid
            for (pid,) in db.query(Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .join(Project, Project.id == Contract.project_id)
            .filter(
                Project.is_contracted.is_(True),
                ContractItem.status_prod.in_(['자재대기중', '생산대기중'])
            )
            .distinct()
            .all()
        }
        prod_waiting_site_count = len(prod_waiting_contract_ids)

        material_pending_project_ids = {
            pid
            for (pid,) in db.query(Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .join(Project, Project.id == Contract.project_id)
            .filter(
                Project.is_contracted.is_(True),
                ContractItem.status_admin != '입고완료'
            )
            .distinct()
            .all()
        }

        overdue_project_ids = {
            pid
            for (pid,) in db.query(Contract.project_id)
            .join(ContractItem, ContractItem.contract_id == Contract.id)
            .join(Project, Project.id == Contract.project_id)
            .filter(
                Project.is_contracted.is_(True),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date < today,
                ContractItem.status_prod != '생산완료',
            )
            .distinct()
            .all()
        }
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

        recent_logs = (
            db.query(HistoryLog)
            .join(Project, Project.id == HistoryLog.project_id)
            .filter(Project.is_contracted.is_(True))
            .options(joinedload(HistoryLog.project))
            .order_by(HistoryLog.created_at.desc(), HistoryLog.id.desc())
            .limit(12)
            .all()
        )
        timeline_items = []
        for log in recent_logs:
            project = log.project
            content = log.content or ''
            timeline_items.append(
                {
                    'id': log.id,
                    'user_name': log.user_name,
                    'created_at': log.created_at,
                    'project_name': (project.short_name or project.temp_name) if project else '알 수 없는 현장',
                    'project_no': project.project_no if project else '-',
                    'content': content,
                    'detail_url': _project_detail_link(project) if project else url_for('project.contract_list'),
                    'is_issue': ('이슈' in content) or ('긴급' in content),
                    'is_system': '시스템' in (log.user_name or ''),
                }
            )

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
                'dday': _days_until(c.delivery_due_date, today),
                'project_name': c.project.short_name or c.project.temp_name,
                'project_no': c.project.project_no,
                'contract_name': c.contract_name,
                'detail_url': url_for('project.contract_detail', project_id=c.project.id),
            }
            for c in monthly_delivery_contracts if c.project
        ]
        calendar_weeks = _build_month_calendar(today, mini_calendar_items)

        kanban = defaultdict(list)
        for project in contracted_projects:
            stage = _resolve_kanban_stage(project)
            kanban[stage].append(
                {
                    'project_id': project.id,
                    'project_no': project.project_no,
                    'project_name': project.short_name or project.temp_name,
                    'is_urgent': project.is_urgent,
                    'status': project.status,
                    'detail_url': _project_detail_link(project),
                }
            )

        action_tabs = _build_action_tabs(contracted_projects, deliveries, today)
        dashboard_priority = _build_dashboard_priority_items(design_projects, contracted_projects, deliveries, today)
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
                'hot_count': _hot_project_count(action_tabs['sales']),
                'tone': 'primary',
                'action_url': url_for('sales.sales_list'),
            },
            {
                'title': '자재확인',
                'subtitle': '발주 / 입고 상태 추적',
                'count': len(kanban['자재확인']),
                'hot_count': _hot_project_count(action_tabs['material']),
                'tone': 'warning',
                'action_url': url_for('project.material_management'),
            },
            {
                'title': '생산중',
                'subtitle': '공정 진행 및 병목 대응',
                'count': len(kanban['생산중']),
                'hot_count': _hot_project_count(action_tabs['production']),
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
                'hot_count': _hot_project_count(action_tabs['delivery']),
                'tone': 'danger',
                'action_url': url_for('delivery.delivery_management'),
            },
        ]

        alert_banners = _build_auto_alert_items(db, today, week_later)

        manual_notices = (
            db.query(DashboardNotice)
            .filter(DashboardNotice.is_active.is_(True))
            .order_by(DashboardNotice.sort_order.asc(), DashboardNotice.id.asc())
            .all()
        )

        global_display_seconds = max(2, _get_dashboard_setting_int(db, 'billboard_global_seconds', 6))

        billboard_items = []
        for n in manual_notices:
            billboard_items.append(
                {
                    'title': n.title or '공지',
                    'message': n.message,
                    'level': n.level or 'info',
                    'detail_url': url_for('dashboard.dashboard_notice_admin'),
                    'display_seconds': global_display_seconds,
                }
            )

        for b in alert_banners:
            billboard_items.append(
                {
                    'title': b['label'],
                    'message': b['message'],
                    'level': b['level'],
                    'detail_url': b['detail_url'],
                    'display_seconds': global_display_seconds,
                }
            )

        pending_users = db.query(User).filter(User.is_approved.is_(False)).count()

        if not billboard_items:
            billboard_items.append(
                {
                    'title': '상태정상',
                    'message': '현재 긴급 공지나 전광판 알림이 없습니다. 예정 납품과 액션 탭을 확인해 주세요.',
                    'level': 'info',
                    'detail_url': url_for('project.contract_list'),
                    'display_seconds': global_display_seconds,
                }
            )

        return render_template(
            'dashboard.html',
            today=today,
            kpi={
                'contracted_count': contracted_count,
                'urgent_delivery_count': urgent_delivery_count,
                'prod_waiting_site_count': prod_waiting_site_count,
                'waiting_delay_site_count': waiting_delay_site_count,
                'as_issue_count': as_issue_count,
                'pending_users': pending_users,
                'urgent_delivery_projects': urgent_delivery_projects[:6],
            },
            billboard_items=billboard_items,
            timeline_items=timeline_items,
            mini_calendar_items=mini_calendar_items,
            calendar_weeks=calendar_weeks,
            calendar_month_label=f"{today.year}.{today.month:02d}",
            calendar_weekdays=['일', '월', '화', '수', '목', '금', '토'],
            dashboard_priority=dashboard_priority,
            kanban={
                '영업/설계': kanban['영업/설계'],
                '자재확인': kanban['자재확인'],
                '생산중': kanban['생산중'],
                '출고대기': kanban['출고대기'],
            },
            workflow_nodes=workflow_nodes,
            action_tabs=action_tabs,
        )