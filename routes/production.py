import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required

from modules.history_board import append_history_log, get_project_history_context
from modules.db_context import get_db
from modules.utils import safe_int
from modules.pagination import make_pagination
from modules.models import (
    Project,
    Contract,
    ContractItem,
    CONTRACT_ITEM_SPEC_SCHEMA,
    normalize_detail_item,
)
from modules.production_logic import (
    sync_production_processes,
    refresh_production_statuses,
)
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)
from modules.services.production_actions import (
    handle_sync_production_processes,
    handle_update_process_status,
    handle_add_daily_log,
    handle_toggle_item_complete,
    handle_toggle_process_active,
    handle_update_process_modal,
    handle_add_chat,
    handle_add_history_reply,
)

production_bp = Blueprint('production', __name__)




def _item_progress(item):
    processes = list(item.production_processes or [])
    if not processes:
        return 0.0
    return round(sum(float(p.progress_percent or 0) for p in processes) / len(processes), 2)


BOOLEAN_SPEC_FIELDS = {'has_stabilizer_box', 'is_integrated', 'is_painted'}
SPEC_FIELD_LABELS = {
    'lens_angle': '렌즈각도',
    'spacing_distance': '이격거리',
    'body_type': '일체형/분리형',
    'has_stabilizer_box': '안정기함 유무',
    'stabilizer_vendor_contact': '안정기함 업체 연락처',
    'stabilizer_address': '안정기함 주소',
    'smps_shipment_schedule': 'SMPS 발송 일정',
    'is_integrated': '일체형 여부',
    'tower_height': '조명타워 높이',
    'lamp_count': '등수',
    'replace_or_new': '교체/신설 여부',
    'anchor_spacing': '기초앙카간격',
    'arm_type': '암대타입',
    'is_painted': '도장 여부',
    'paint_color': '도장 색상',
    'stainless_finish_type': '스텐 마감',
}


def _spec_label(field):
    return SPEC_FIELD_LABELS.get(field, field)


def _is_filled_spec_value(field, value):
    if field in BOOLEAN_SPEC_FIELDS:
        return value is not None
    return value not in (None, '', [])


def _required_spec_fields(category, spec):
    category = normalize_detail_item(category, default='투광등기구')
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    fields = list(schema.get('required', []))
    conditional = schema.get('conditional_required', {})
    for trigger, rule in conditional.items():
        expected = rule.get('equals')
        current = spec.get(trigger)
        if current == expected:
            fields.extend(rule.get('fields', []))
    return sorted(set(fields))


def _spec_completion_summary(item):
    spec = dict(item.item_spec or {})
    required_fields = _required_spec_fields(item.category, spec)
    if not required_fields:
        return {'filled': 0, 'total': 0, 'rate': 0, 'missing_fields': []}

    filled = 0
    missing_fields = []
    for field in required_fields:
        if _is_filled_spec_value(field, spec.get(field)):
            filled += 1
        else:
            missing_fields.append(field)
    rate = round((filled / len(required_fields)) * 100) if required_fields else 0
    return {
        'filled': filled,
        'total': len(required_fields),
        'rate': rate,
        'missing_fields': missing_fields,
    }


def _format_spec_value(field, value):
    if value in (None, ''):
        return '-'
    if isinstance(value, bool):
        return '예' if value else '아니오'
    return str(value)


def _sales_summary(item, contract_obj):
    completion = _spec_completion_summary(item)
    spec = dict(item.item_spec or {})
    required_fields = _required_spec_fields(item.category, spec)
    return {
        'status': (item.status_sales or '계약확인'),
        'desired_delivery_date': contract_obj.desired_delivery_date.isoformat() if contract_obj and contract_obj.desired_delivery_date else None,
        'spec_completion': completion,
        'spec_entries': [
            {
                'label': _spec_label(field),
                'value': _format_spec_value(field, spec.get(field)),
                'is_missing': field in completion['missing_fields'],
            }
            for field in required_fields
        ]
    }


def _contract_summary(project_obj, contract_obj, dday):
    return {
        'contract_name': contract_obj.contract_name if contract_obj else '-',
        'contract_date': contract_obj.contract_date.isoformat() if contract_obj and contract_obj.contract_date else None,
        'delivery_due_date': contract_obj.delivery_due_date.isoformat() if contract_obj and contract_obj.delivery_due_date else None,
        'desired_delivery_date': contract_obj.desired_delivery_date.isoformat() if contract_obj and contract_obj.desired_delivery_date else None,
        'is_prof_inspection': bool(contract_obj.is_prof_inspection) if contract_obj else False,
        'is_urgent_prod': bool(contract_obj.is_urgent_prod) if contract_obj else False,
        'is_project_urgent': bool(project_obj.is_urgent),
        'project_site_address': project_obj.site_address or '',
        'project_shipping_address': project_obj.shipping_address or '',
        'design_basis': project_obj.design_basis or '',
        'dday': dday,
    }


def _comparison_warnings(item, contract_obj, dday):
    warnings = []
    sales_status = (item.status_sales or '계약확인').strip()
    prod_status = (item.status_prod or '자재대기중').strip()
    completion = _spec_completion_summary(item)

    for field in completion['missing_fields']:
        warnings.append({
            'level': 'warning',
            'label': f'{_spec_label(field)} 누락',
            'detail': '협의 스펙 필수값이 비어 있습니다.'
        })

    if contract_obj:
        due = contract_obj.delivery_due_date
        desired = contract_obj.desired_delivery_date
        if due and desired and due != desired:
            warnings.append({
                'level': 'danger',
                'label': '납품희망일 불일치',
                'detail': f'계약납기 {due.isoformat()} / 희망납기 {desired.isoformat()}'
            })

    if prod_status in ('생산중', '생산완료') and sales_status != '협의완료':
        warnings.append({
            'level': 'danger',
            'label': '생산 선행 위험',
            'detail': f'영업단계가 {sales_status} 인데 생산상태는 {prod_status} 입니다.'
        })

    if dday is not None and dday < 0 and prod_status != '생산완료':
        warnings.append({
            'level': 'danger',
            'label': '납기 지연',
            'detail': f'D+{-dday} 상태입니다.'
        })
    elif dday is not None and dday <= 7 and prod_status != '생산완료':
        warnings.append({
            'level': 'warning',
            'label': '납기 임박',
            'detail': f'D-{dday} 남았습니다.' if dday > 0 else '오늘이 납기입니다.'
        })

    return warnings


def _panel_payload(project_obj, contract_obj, item, dday):
    return {
        'project_id': project_obj.id,
        'project_no': project_obj.project_no or '-',
        'project_name': project_obj.temp_name or '-',
        'contract_id': contract_obj.id if contract_obj else None,
        'contract_name': contract_obj.contract_name if contract_obj else '-',
        'item_id': item.id,
        'item_category': item.category or '-',
        'item_model_name': item.model_name or '-',
        'item_quantity': int(item.quantity or 0),
        'prod_status': item.status_prod or '자재대기중',
        'prod_progress': item._prod_progress,
        'sales_summary': _sales_summary(item, contract_obj),
        'contract_summary': _contract_summary(project_obj, contract_obj, dday),
        'warnings': _comparison_warnings(item, contract_obj, dday),
        'source_links': {
            'sales': url_for('sales.sales_detail', project_id=project_obj.id) + f'#item-{item.id}',
            'contract': url_for('project.contract_detail', project_id=project_obj.id) + f'#item-{item.id}',
        }
    }


def _project_dday(project_obj, today):
    contracts_sorted = sorted(project_obj.contracts, key=lambda c: c.delivery_due_date or datetime.date.max)
    primary = contracts_sorted[0] if contracts_sorted else None
    due = primary.delivery_due_date if primary else None
    return (due - today).days if due else None


def _project_desired_delivery(project_obj):
    contracts_with_desired = [c for c in (project_obj.contracts or []) if c.desired_delivery_date]
    if not contracts_with_desired:
        return None
    contracts_with_desired.sort(key=lambda c: c.desired_delivery_date)
    return contracts_with_desired[0].desired_delivery_date


ACTION_HANDLERS = {
    'sync_production_processes': handle_sync_production_processes,
    'update_process_status': handle_update_process_status,
    'add_daily_log': handle_add_daily_log,
    'toggle_item_complete': handle_toggle_item_complete,
    'toggle_process_active': handle_toggle_process_active,
    'update_process_modal': handle_update_process_modal,
    'add_chat': handle_add_chat,
    'add_history_reply': handle_add_history_reply,
}

@production_bp.route('/production_management', methods=['GET', 'POST'])
@login_required
def production_management():

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        if request.method == 'POST' and request.form.get('action') == 'sync_production_processes':
            sync_production_processes(db)
            refresh_production_statuses(db)
            first_project = db.query(Project).filter(Project.is_contracted.is_(True)).order_by(Project.id.asc()).first()
            if first_project:
                append_history_log(
                    db,
                    project_id=first_project.id,
                    user_name='시스템 🤖',
                    content=f"{current_user}님이 생산공정 자동생성/동기화를 실행했습니다.",
                    scope='production',
                    kind='system'
                )
            db.commit()
            flash('생산공정 자동생성/동기화가 완료되었습니다.', 'success')
            return redirect(url_for('production.production_management'))

        sync_production_processes(db)
        refresh_production_statuses(db)
        db.commit()

        q = (request.args.get('q') or '').strip().lower()
        status_filter = (request.args.get('status') or 'all').strip()
        due_filter = (request.args.get('due') or 'all').strip()
        sort_by = (request.args.get('sort') or 'due_asc').strip()

        projects = db.query(Project).filter(Project.is_contracted.is_(True)).options(
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.production_processes),
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.material_orders),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        today = datetime.date.today()
        total_items = 0
        waiting_items = 0
        working_items = 0
        done_items = 0

        filtered = []
        for p in projects:
            has_match = False
            p._matched_contracts = []
            p._avg_progress = 0.0
            proj_progress_pool = []

            for c in p.contracts:
                matched_items = []
                for item in c.items:
                    total_items += 1
                    prod_status = (item.status_prod or '').strip() or '자재대기중'
                    if prod_status == '자재대기중':
                        waiting_items += 1
                    elif prod_status == '생산중':
                        working_items += 1
                    elif prod_status == '생산완료':
                        done_items += 1

                    search_pool = ' '.join([
                        p.project_no or '',
                        p.temp_name or '',
                        c.contract_name or '',
                        item.category or '',
                        item.model_name or '',
                        prod_status,
                    ]).lower()

                    if q and q not in search_pool:
                        continue
                    if status_filter != 'all' and prod_status != status_filter:
                        continue

                    item._prod_progress = _item_progress(item)
                    item._spec_completion = _spec_completion_summary(item)
                    proj_progress_pool.append(item._prod_progress)
                    item._panel_payload = _panel_payload(p, c, item, _project_dday(p, today))
                    item._warning_count = len(item._panel_payload['warnings'])
                    matched_items.append(item)

                if matched_items:
                    c._matched_items = matched_items
                    p._matched_contracts.append(c)
                    has_match = True

            p._dday = _project_dday(p, today)
            if due_filter == 'overdue' and (p._dday is None or p._dday >= 0):
                has_match = False
            if due_filter == 'week' and (p._dday is None or p._dday < 0 or p._dday > 7):
                has_match = False
            if due_filter == 'twoweek' and (p._dday is None or p._dday < 0 or p._dday > 14):
                has_match = False

            if has_match:
                p._avg_progress = round(sum(proj_progress_pool) / len(proj_progress_pool), 2) if proj_progress_pool else 0.0
                filtered.append(p)

        if sort_by == 'due_desc':
            filtered.sort(key=lambda p: (p._dday is None, -(p._dday if p._dday is not None else -99999)))
        elif sort_by == 'created_desc':
            filtered.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
        else:
            filtered.sort(key=lambda p: (p._dday is None, p._dday if p._dday is not None else 99999))

        priority_projects = []
        for p in filtered:
            reasons = []
            override = append_manual_priority_reason(reasons, p)
            warning_count = 0
            active_items = 0
            is_urgent_project = bool(p.is_urgent or any(c.is_urgent_prod for c in (p.contracts or [])))

            for c in getattr(p, '_matched_contracts', []) or []:
                for item in getattr(c, '_matched_items', []) or []:
                    warning_count += int(getattr(item, '_warning_count', 0) or 0)
                    if (item.status_prod or '') != '생산완료':
                        active_items += 1

            if is_urgent_project:
                append_priority_reason(reasons, 'urgent')
            append_due_priority_reason(reasons, p._dday, 'production')
            if warning_count > 0:
                append_priority_reason(reasons, 'production_warning', f"경고 {warning_count}건")

            if reasons:
                meta_lines = [
                    f"조회 계약건: {len(getattr(p, '_matched_contracts', []) or [])}건",
                    f"미완료 품목: {active_items}건",
                    f"생산 경고: {warning_count}건",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=p.id,
                    project_no=p.project_no,
                    title=p.temp_name or '-',
                    subtitle=f"평균 공정률: {p._avg_progress}%",
                    detail_url=url_for('production.production_detail', project_id=p.id),
                    reasons=reasons,
                    dday=p._dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)

        page = safe_int(request.args.get('page'), 1)
        per_page = safe_int(request.args.get('per_page'), 20)
        pagination = make_pagination(page, per_page, len(filtered))
        start = (pagination['page'] - 1) * per_page
        projects_page = filtered[start:start + per_page]

        return render_template(
            'production_management.html',
            projects=projects_page,
            priority_projects=priority_projects,
            stats={
                'total_projects': len(projects),
                'filtered_projects': len(filtered),
                'total_items': total_items,
                'waiting_items': waiting_items,
                'working_items': working_items,
                'done_items': done_items,
            },
            pagination=pagination,
            filters={'q': request.args.get('q', ''), 'status': status_filter, 'due': due_filter, 'sort': sort_by}
        )


@production_bp.route('/production_management/<int:project_id>', methods=['GET', 'POST'])
@login_required
def production_detail(project_id):

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        project = db.query(Project).options(
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.production_processes),
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.material_orders)
        ).get(project_id)

        if not project:
            flash('대상을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('production.production_management'))

        if request.method == 'POST':
            action = request.form.get('action')

            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            handler = ACTION_HANDLERS.get(action)
            if handler:
                result = handler(db, project, request.form, current_user)

                if result.get('error'):
                    if is_ajax:
                        return jsonify({'ok': False, 'message': result['error']}), result.get('status_code', 400)
                    flash(result['error'], 'warning')
                    return redirect(url_for('production.production_detail', project_id=project_id))

                db.commit()

                if is_ajax and result.get('ajax_data'):
                    return jsonify(result['ajax_data'])

                if result.get('flash'):
                    flash(*result['flash'])
                for f in result.get('flashes', []):
                    flash(*f)

            return redirect(url_for('production.production_detail', project_id=project_id))

        sync_production_processes(db, project_id=project_id)
        refresh_production_statuses(db, project_id=project_id)
        db.commit()

        for c in project.contracts:
            for item in c.items:
                item._prod_progress = _item_progress(item)
                item._spec_completion = _spec_completion_summary(item)
                item._panel_payload = _panel_payload(project, c, item, _project_dday(project, datetime.date.today()))
                item._warning_count = len(item._panel_payload['warnings'])
                item.production_processes = sorted(item.production_processes or [], key=lambda x: (x.step_order, x.id))
        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope='production',
            limit=300,
        )

        response = render_template(
            'production_detail.html',
            project=project,
            history=history,
            history_counts=history_counts,
            today=datetime.date.today(),
        )
        return response
