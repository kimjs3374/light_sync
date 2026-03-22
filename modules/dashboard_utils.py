import calendar as calendar_lib
import datetime
from collections import defaultdict

from flask import url_for
from sqlalchemy.orm import joinedload

from modules.models import Project, Contract, DRAWING_REQUIRED_ITEMS
from modules.contract_filters import active_contract_filter
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)


# --- Small utility functions ---

def project_detail_link(project):
    if project.is_contracted:
        return url_for('project.contract_detail', project_id=project.id)
    return url_for('project.project_detail', project_id=project.id)


def resolve_kanban_stage(project):
    """계약 현장 기준 대표 단계를 계산하여 4단계 칸반에 배치한다."""
    contract_items = []
    for contract in (project.contracts or []):
        contract_items.extend(contract.items or [])

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

    return '영업/설계'


def project_primary_contract(project):
    contracts = sorted(project.contracts or [], key=lambda c: c.delivery_due_date or datetime.date.max)
    return contracts[0] if contracts else None


def days_until(date_value, today):
    if not date_value:
        return None
    return (date_value - today).days


def dday_badge(dday):
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


def delivery_status_label(status):
    return {
        'waiting': '납품대기',
        'coordinating': '납품협의중',
        'in_progress': '납품진행중',
        'done': '납품완료',
    }.get((status or '').strip(), (status or '-').strip() or '-')


def is_delivery_done_photo(photo):
    return (photo.photo_type or '').strip() in {'delivery_done', '납품완료'}


def sort_action_items(items, limit=6):
    items.sort(key=lambda item: (item['sort_priority'], item['sort_dday'], item['project_name'], item['title']))
    return items[:limit]


def hot_project_count(items):
    return len({item['project_id'] for item in items if item.get('chip_class') in {'danger', 'warning'} or item.get('badge_class') in {'danger', 'warning'}})


# --- Large aggregate functions ---

def build_action_tabs(contracted_projects, deliveries, today):
    tabs = {
        'sales': [],
        'fabrication': [],
        'material': [],
        'production': [],
        'delivery': [],
    }

    for project in contracted_projects:
        primary_contract = project_primary_contract(project)
        dday = days_until(primary_contract.delivery_due_date if primary_contract else None, today)
        badge_text, badge_class, badge_priority = dday_badge(dday)
        project_name = project.short_name or project.temp_name

        for contract in (project.contracts or []):
            for item in (contract.items or []):
                sales_status = (item.status_sales or '계약확인').strip()
                admin_status = (item.status_admin or '자재확인중').strip()
                prod_status = (item.status_prod or '자재대기중').strip()
                model_name = item.model_name or '-'
                subtitle = f"{contract.contract_name} · {model_name}"
                is_confirmed = (sales_status == '협의완료')
                category = (item.category or contract.item_group or '').strip()

                # ── 영업탭: 협의 미완료 ──
                if not is_confirmed:
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
                            'action_label': '협의 처리',
                            'action_url': url_for('sales.sales_detail', project_id=project.id),
                            'sort_priority': min(badge_priority, 0 if chip_class == 'danger' else 1 if chip_class == 'warning' else 2),
                            'sort_dday': dday if dday is not None else 99999,
                        }
                    )

                # ── 가공탭: 도면 필요 품목 + 도면 미작성 ──
                if is_confirmed and category in DRAWING_REQUIRED_ITEMS:
                    has_drawing = bool(getattr(item, 'drawings', None) and len(item.drawings) > 0)
                    if not has_drawing:
                        fab_chip_class = 'danger' if dday is not None and dday <= 7 else 'warning'
                        tabs['fabrication'].append(
                            {
                                'project_id': project.id,
                                'project_name': project_name,
                                'project_no': project.project_no,
                                'title': project_name,
                                'subtitle': subtitle,
                                'meta': f"품목 {category}",
                                'badge_text': badge_text,
                                'badge_class': badge_class,
                                'chip_text': '도면 미작성',
                                'chip_class': fab_chip_class,
                                'action_label': '도면 작업',
                                'action_url': url_for('sales.sales_detail', project_id=project.id),
                                'sort_priority': min(badge_priority, 0 if fab_chip_class == 'danger' else 1),
                                'sort_dday': dday if dday is not None else 99999,
                            }
                        )

                # ── 자재탭: 협의완료 우선, 미완료도 표시 ──
                if admin_status != '입고완료':
                    if is_confirmed:
                        chip_class = 'danger' if dday is not None and dday <= 3 else ('warning' if dday is not None and dday <= 7 else 'primary')
                        chip_text = admin_status
                        mat_priority = min(badge_priority, 0 if chip_class == 'danger' else 1 if chip_class == 'warning' else 2)
                    else:
                        chip_class = 'secondary'
                        chip_text = f'협의중 · {admin_status}'
                        mat_priority = 3  # 협의 미완료는 뒤로
                    tabs['material'].append(
                        {
                            'project_id': project.id,
                            'project_name': project_name,
                            'project_no': project.project_no,
                            'title': project_name,
                            'subtitle': subtitle,
                            'meta': f"자재상태 {admin_status}" + (' · 협의완료' if is_confirmed else ' · 협의중'),
                            'badge_text': badge_text,
                            'badge_class': badge_class,
                            'chip_text': chip_text,
                            'chip_class': chip_class,
                            'action_label': '자재 확인',
                            'action_url': url_for('material.material_detail', project_id=project.id),
                            'sort_priority': mat_priority,
                            'sort_dday': dday if dday is not None else 99999,
                        }
                    )

                # ── 생산탭: 협의완료 우선, 미완료도 표시 ──
                if prod_status != '생산완료':
                    if not is_confirmed and prod_status in {'생산중', '생산완료'}:
                        chip_text = '생산 선행 위험'
                        chip_class = 'danger'
                        prod_priority = 0
                    elif is_confirmed and dday is not None and dday < 0:
                        chip_text = '납기 초과'
                        chip_class = 'danger'
                        prod_priority = 0
                    elif is_confirmed and dday is not None and dday <= 7:
                        chip_text = '납기 임박'
                        chip_class = 'warning'
                        prod_priority = 1
                    elif is_confirmed:
                        chip_text = prod_status
                        chip_class = 'primary'
                        prod_priority = 2
                    else:
                        chip_text = f'협의중 · {prod_status}'
                        chip_class = 'secondary'
                        prod_priority = 3  # 협의 미완료는 뒤로

                    tabs['production'].append(
                        {
                            'project_id': project.id,
                            'project_name': project_name,
                            'project_no': project.project_no,
                            'title': project_name,
                            'subtitle': subtitle,
                            'meta': f"생산상태 {prod_status}" + (' · 협의완료' if is_confirmed else ' · 협의중'),
                            'badge_text': badge_text,
                            'badge_class': badge_class,
                            'chip_text': chip_text,
                            'chip_class': chip_class,
                            'action_label': '생산 보기',
                            'action_url': url_for('production.production_detail', project_id=project.id),
                            'sort_priority': min(badge_priority, prod_priority),
                            'sort_dday': dday if dday is not None else 99999,
                        }
                    )

    for delivery in deliveries:
        project = delivery.project
        contract = delivery.contract
        if not project:
            continue

        project_name = project.short_name or project.temp_name
        dday = days_until(contract.delivery_due_date if contract else None, today)
        badge_text, badge_class, badge_priority = dday_badge(dday)
        has_done_photo = any(is_delivery_done_photo(photo) for photo in (delivery.photos or []))
        needs_done_photo = bool(
            (delivery.planned_total_qty or 0) > 0
            and (delivery.delivered_total_qty or 0) >= (delivery.planned_total_qty or 0)
            and not has_done_photo
        )
        is_unassigned = not (delivery.contact_name or '').strip()
        status_label = delivery_status_label(delivery.delivery_status)
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
        tabs[key] = sort_action_items(tabs[key])

    return tabs


def build_month_calendar(today, items):
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


def build_auto_alert_items(db, today, week_later):
    """자동 생성 전광판 문구 + 원문 이동 링크를 생성한다."""
    contracted_projects = (
        db.query(Project)
        .filter(Project.is_contracted.is_(True), active_contract_filter())
        .options(joinedload(Project.contracts))
        .order_by(Project.created_at.desc(), Project.id.desc())
        .all()
    )

    urgent_contracts = (
        db.query(Contract)
        .join(Project, Project.id == Contract.project_id)
        .filter(
            Project.is_contracted.is_(True),
            active_contract_filter(),
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


def build_dashboard_priority_items(design_projects, contracted_projects, deliveries, today, limit=5):
    delivery_map = defaultdict(list)
    for delivery in deliveries:
        delivery_map[delivery.project_id].append(delivery)

    items = []

    for project in design_projects:
        reasons = []
        override = append_manual_priority_reason(reasons, project)
        dday = days_until(project.expected_contract_date, today)

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
        primary_contract = project_primary_contract(project)
        dday = days_until(primary_contract.delivery_due_date if primary_contract else None, today)

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
            f"단계: {resolve_kanban_stage(project)}",
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
