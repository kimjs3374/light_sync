import datetime

from flask import url_for
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from modules.utils import safe_int, parse_date, is_true_value
from modules.contract_filters import active_contract_filter
from modules.models import (
    Project,
    ProductionProcess,
    ProductionDailyLog,
    ContractItem,
    Contract,
    HistoryLog,
    CONTRACT_ITEM_SPEC_SCHEMA,
    normalize_detail_item,
)
from modules.history_board import append_history_log, get_project_history_context
from modules.production_logic import (
    sync_production_processes,
    refresh_production_statuses,
    can_start_process,
    are_materials_ready,
    set_process_status,
    recompute_process_progress,
)
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)
from modules.pagination import make_pagination


# --- Spec / panel helpers (moved from routes/production.py) ---

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


def item_progress(item):
    processes = list(item.production_processes or [])
    if not processes:
        return 0.0
    return round(sum(float(p.progress_percent or 0) for p in processes) / len(processes), 2)


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


def spec_completion_summary(item):
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
    completion = spec_completion_summary(item)
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
    completion = spec_completion_summary(item)

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


def panel_payload(project_obj, contract_obj, item, dday):
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


def project_dday(project_obj, today):
    contracts_sorted = sorted(project_obj.contracts, key=lambda c: c.delivery_due_date or datetime.date.max)
    primary = contracts_sorted[0] if contracts_sorted else None
    due = primary.delivery_due_date if primary else None
    return (due - today).days if due else None


def project_desired_delivery(project_obj):
    contracts_with_desired = [c for c in (project_obj.contracts or []) if c.desired_delivery_date]
    if not contracts_with_desired:
        return None
    contracts_with_desired.sort(key=lambda c: c.desired_delivery_date)
    return contracts_with_desired[0].desired_delivery_date


# --- Process card helpers (moved from routes/production.py) ---

def build_process_card(p, item, project, contract, today, today_logs):
    """공정 1개를 카드 dict로 변환"""
    mat_ready = are_materials_ready(item)
    can_go = can_start_process(item, p)
    delivery_date = contract.delivery_due_date if contract else None
    dday = (delivery_date - today).days if delivery_date else None
    return {
        'process_id': p.id,
        'process_name': p.process_name,
        'step_order': p.step_order,
        'status': p.status or '대기',
        'is_forced': bool(p.is_forced),
        'progress_qty': p.progress_qty or 0,
        'progress_pct': round(p.progress_percent or 0, 1),
        'started_at': p.started_at.strftime('%m/%d %H:%M') if p.started_at else None,
        'completed_at': p.completed_at.strftime('%m/%d %H:%M') if p.completed_at else None,
        'item_id': item.id,
        'model_name': item.model_name or '-',
        'category': item.category or '-',
        'quantity': int(item.quantity or 0),
        'item_status': item.status_prod or '자재대기중',
        'project_id': project.id,
        'site_name': project.temp_name or '-',
        'project_no': project.project_no or '-',
        'delivery_date': delivery_date.strftime('%Y/%m/%d') if delivery_date else None,
        'dday': dday,
        'materials_ready': mat_ready,
        'can_start': can_go,
        'today_qty': int(today_logs.get(p.id) or 0),
    }


def load_today_logs(db, today):
    return dict(
        db.query(
            ProductionDailyLog.production_process_id,
            func.sum(ProductionDailyLog.daily_qty),
        ).filter(
            ProductionDailyLog.work_date == today,
        ).group_by(ProductionDailyLog.production_process_id).all()
    )


# --- Service functions for route body extraction ---

def get_production_management_data(db, q, status_filter, due_filter, sort_by, page, per_page):
    """production_management GET 로직: 프로젝트 필터링, 정렬, 통계, 우선순위 계산"""
    sync_production_processes(db)
    refresh_production_statuses(db)
    db.commit()

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
            for item_obj in c.items:
                total_items += 1
                prod_status = (item_obj.status_prod or '').strip() or '자재대기중'
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
                    item_obj.category or '',
                    item_obj.model_name or '',
                    prod_status,
                ]).lower()

                if q and q not in search_pool:
                    continue
                if status_filter != 'all' and prod_status != status_filter:
                    continue

                item_obj._prod_progress = item_progress(item_obj)
                item_obj._spec_completion = spec_completion_summary(item_obj)
                proj_progress_pool.append(item_obj._prod_progress)
                item_obj._panel_payload = panel_payload(p, c, item_obj, project_dday(p, today))
                item_obj._warning_count = len(item_obj._panel_payload['warnings'])
                matched_items.append(item_obj)

            if matched_items:
                c._matched_items = matched_items
                p._matched_contracts.append(c)
                has_match = True

        p._dday = project_dday(p, today)
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
            for item_obj in getattr(c, '_matched_items', []) or []:
                warning_count += int(getattr(item_obj, '_warning_count', 0) or 0)
                if (item_obj.status_prod or '') != '생산완료':
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
    pagination = make_pagination(page, per_page, len(filtered))
    start = (pagination['page'] - 1) * per_page
    projects_page = filtered[start:start + per_page]

    return {
        'projects': projects_page,
        'priority_projects': priority_projects,
        'stats': {
            'total_projects': len(projects),
            'filtered_projects': len(filtered),
            'total_items': total_items,
            'waiting_items': waiting_items,
            'working_items': working_items,
            'done_items': done_items,
        },
        'pagination': pagination,
    }


def enrich_detail_items(project, today):
    """production_detail GET: 품목에 진행률/스펙/패널/경고 어트리뷰트 부여"""
    for c in project.contracts:
        for item_obj in c.items:
            item_obj._prod_progress = item_progress(item_obj)
            item_obj._spec_completion = spec_completion_summary(item_obj)
            item_obj._panel_payload = panel_payload(project, c, item_obj, project_dday(project, today))
            item_obj._warning_count = len(item_obj._panel_payload['warnings'])
            item_obj.production_processes = sorted(item_obj.production_processes or [], key=lambda x: (x.step_order, x.id))


def get_site_list(db, today):
    """production_main: 현장 목록 조회"""
    projects = db.query(Project).filter(
        Project.is_contracted.is_(True),
        active_contract_filter(),
    ).options(
        joinedload(Project.contracts)
        .joinedload(Contract.items)
        .joinedload(ContractItem.production_processes),
    ).order_by(Project.id.desc()).all()

    site_list = []
    for proj in projects:
        total_proc = 0
        working_proc = 0
        done_proc = 0
        items_count = 0
        delivery_date = None

        item_summaries = []
        for c in proj.contracts:
            if c.delivery_due_date and (delivery_date is None or c.delivery_due_date < delivery_date):
                delivery_date = c.delivery_due_date
            for item_obj in c.items:
                items_count += 1
                item_summaries.append({
                    'category': item_obj.category or '-',
                    'model_name': item_obj.model_name or '-',
                    'quantity': int(item_obj.quantity or 0),
                })
                for p in (item_obj.production_processes or []):
                    total_proc += 1
                    if p.status == '진행중':
                        working_proc += 1
                    elif p.status in ('완료', '스킵'):
                        done_proc += 1

        if total_proc == 0:
            continue

        dday = (delivery_date - today).days if delivery_date else None
        pct = round(done_proc / total_proc * 100, 1) if total_proc else 0

        site_list.append({
            'project_id': proj.id,
            'site_name': proj.temp_name or '-',
            'project_no': proj.project_no or '-',
            'items_count': items_count,
            'item_summaries': item_summaries,
            'total_proc': total_proc,
            'working_proc': working_proc,
            'done_proc': done_proc,
            'pct': pct,
            'delivery_date': delivery_date.strftime('%Y/%m/%d') if delivery_date else None,
            'dday': dday,
            'status': '완료' if pct >= 100 else ('진행중' if working_proc > 0 else '대기'),
        })

    status_order = {'진행중': 0, '대기': 1, '완료': 2}
    site_list.sort(key=lambda s: (status_order.get(s['status'], 9), s['dday'] if s['dday'] is not None else 9999))
    return site_list


def get_site_detail(db, project, site_id, today):
    """production_main: 현장 선택 시 품목별 공정 카드 + 통계"""
    today_logs = load_today_logs(db, today)

    item_groups = []
    all_cards = []
    for c in db.query(Contract).filter(Contract.project_id == site_id).options(
        joinedload(Contract.items).joinedload(ContractItem.production_processes),
        joinedload(Contract.items).joinedload(ContractItem.material_orders),
    ).all():
        for item_obj in c.items:
            processes = sorted(item_obj.production_processes or [], key=lambda x: (x.step_order, x.id))
            if not processes:
                continue
            cards = [build_process_card(p, item_obj, project, c, today, today_logs) for p in processes]
            all_cards.extend(cards)

            done_count = sum(1 for cd in cards if cd['status'] in ('완료', '스킵'))
            item_groups.append({
                'item_id': item_obj.id,
                'model_name': item_obj.model_name or '-',
                'category': item_obj.category or '-',
                'quantity': int(item_obj.quantity or 0),
                'item_status': item_obj.status_prod or '자재대기중',
                'total_proc': len(cards),
                'done_proc': done_count,
                'pct': round(done_count / len(cards) * 100, 1) if cards else 0,
                'cards': cards,
            })

    stats = {
        'total': len(all_cards),
        'working': sum(1 for c in all_cards if c['status'] == '진행중'),
        'ready': sum(1 for c in all_cards if c['status'] == '대기' and c['materials_ready'] and c['can_start']),
        'waiting': sum(1 for c in all_cards if c['status'] == '대기' and not (c['materials_ready'] and c['can_start'])),
        'done': sum(1 for c in all_cards if c['status'] in ('완료', '스킵')),
    }

    history, history_counts = get_project_history_context(
        db, project_id=site_id, default_scope='production', limit=100,
    )

    return item_groups, stats, history, history_counts


def handle_process_toggle(db, process_id, is_active, off_reason, current_user):
    """AJAX 공정 ON/OFF 토글 비즈니스 로직"""
    p = db.query(ProductionProcess).get(process_id)
    if not p:
        return {'ok': False, 'message': '공정을 찾을 수 없습니다.'}, 404

    item = db.query(ContractItem).get(p.contract_item_id)
    if not item:
        return {'ok': False, 'message': '품목을 찾을 수 없습니다.'}, 404

    if is_active:
        if not can_start_process(item, p):
            return {'ok': False, 'message': '선행 공정이 완료/진행되지 않았습니다.'}, 400
        set_process_status(p, '진행중')
    else:
        if not off_reason:
            off_reason = '작업자 OFF'
        set_process_status(p, '대기')
        p.started_at = None
        p.completed_at = None

    recompute_process_progress(db, p, item.quantity)
    refresh_production_statuses(db, project_id=p.project_id)

    append_history_log(
        db, project_id=p.project_id, user_name='시스템',
        content=f"{current_user} 공정토글: {item.model_name}/{p.process_name} → {p.status}" + (f" ({off_reason})" if not is_active else ""),
        scope='production', kind='system',
    )
    db.commit()

    return {
        'ok': True,
        'process_id': p.id,
        'process_status': p.status,
        'item_status': item.status_prod,
        'progress_pct': round(p.progress_percent or 0, 1),
    }, 200


def handle_process_daily_log(db, process_id, daily_qty_raw, current_user):
    """AJAX 일일 수량 입력 비즈니스 로직"""
    daily_qty = max(0, safe_int(daily_qty_raw, 0))

    p = db.query(ProductionProcess).get(process_id)
    if not p:
        return {'ok': False, 'message': '공정을 찾을 수 없습니다.'}, 404

    item = db.query(ContractItem).get(p.contract_item_id)
    if not item:
        return {'ok': False, 'message': '품목을 찾을 수 없습니다.'}, 404

    item_qty = int(item.quantity or 0)
    current_total = p.progress_qty or 0
    remain = max(0, item_qty - current_total)
    actual_qty = min(daily_qty, remain)

    if daily_qty > 0 and actual_qty <= 0:
        return {'ok': False, 'message': '계약수량에 이미 도달했습니다.'}, 400

    if actual_qty > 0:
        db.add(ProductionDailyLog(
            production_process_id=p.id,
            work_date=datetime.date.today(),
            daily_qty=actual_qty,
            created_by=current_user,
        ))

        if (p.status or '대기') == '대기':
            set_process_status(p, '진행중')

        recompute_process_progress(db, p, item.quantity)
        refresh_production_statuses(db, project_id=p.project_id)

        append_history_log(
            db, project_id=p.project_id, user_name='시스템',
            content=f"{current_user} 수량입력: {item.model_name}/{p.process_name} +{actual_qty}개 (누적 {p.progress_qty}/{item_qty})",
            scope='production', kind='system',
        )
        db.commit()

    today_total = db.query(func.coalesce(func.sum(ProductionDailyLog.daily_qty), 0)).filter(
        ProductionDailyLog.production_process_id == p.id,
        ProductionDailyLog.work_date == datetime.date.today(),
    ).scalar()

    return {
        'ok': True,
        'process_id': p.id,
        'progress_qty': p.progress_qty or 0,
        'progress_pct': round(p.progress_percent or 0, 1),
        'remain': max(0, item_qty - (p.progress_qty or 0)),
        'item_status': item.status_prod,
        'today_total': int(today_total),
        'clamped': actual_qty < daily_qty,
        'actual_qty': actual_qty,
    }, 200


def handle_process_complete(db, process_id, complete, current_user):
    """AJAX 공정 완료/완료해제 비즈니스 로직"""
    p = db.query(ProductionProcess).get(process_id)
    if not p:
        return {'ok': False, 'message': '공정을 찾을 수 없습니다.'}, 404

    item = db.query(ContractItem).get(p.contract_item_id)
    if not item:
        return {'ok': False, 'message': '품목을 찾을 수 없습니다.'}, 404

    target = '완료' if complete else '진행중'
    set_process_status(p, target)
    recompute_process_progress(db, p, item.quantity)
    refresh_production_statuses(db, project_id=p.project_id)

    append_history_log(
        db, project_id=p.project_id, user_name='시스템',
        content=f"{current_user} 공정{'완료' if complete else '완료해제'}: {item.model_name}/{p.process_name}",
        scope='production', kind='system',
    )
    db.commit()

    return {
        'ok': True,
        'process_id': p.id,
        'process_status': p.status,
        'item_status': item.status_prod,
        'completed_at': p.completed_at.strftime('%m/%d %H:%M') if p.completed_at else None,
    }, 200


# --- Private helpers ---

def _calc_logged_qty(db, process_obj):
    rows = db.query(ProductionDailyLog.daily_qty).filter(
        ProductionDailyLog.production_process_id == process_obj.id
    ).all()
    return sum(safe_int(row[0], 0) for row in rows)


def _clamp_daily_qty(db, process_obj, item_qty, requested_qty):
    req = max(0, safe_int(requested_qty, 0))
    qty_limit = max(0, safe_int(item_qty, 0))
    current = _calc_logged_qty(db, process_obj)
    remain = max(0, qty_limit - current)
    return min(req, remain), remain


def _get_last_process(item):
    processes = sorted(item.production_processes or [], key=lambda x: (x.step_order, x.id))
    return processes[-1] if processes else None


def _fmt_dt(value):
    if not value:
        return None
    return value.strftime('%Y-%m-%d %H:%M')


def _history_payload(log_obj):
    if not log_obj:
        return None
    return {
        'id': int(log_obj.id or 0),
        'user_name': log_obj.user_name or '',
        'content': log_obj.content or '',
        'scope': (log_obj.log_scope or 'common'),
        'kind': (log_obj.log_kind or 'system'),
        'created_at': _fmt_dt(log_obj.created_at),
    }


# --- Action Handlers ---

def handle_sync_production_processes(db, project, form, current_user, **ctx):
    sync_production_processes(db, project_id=project.id)
    refresh_production_statuses(db, project_id=project.id)
    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템 🤖',
        content=f"{current_user}님이 생산공정 자동생성/동기화를 실행했습니다.",
        scope='production',
        kind='system'
    )
    return {'flash': ('생산공정 자동생성/동기화가 완료되었습니다.', 'success')}


def handle_update_process_status(db, project, form, current_user, **ctx):
    process_id = safe_int(form.get('process_id'))
    new_status = form.get('new_status')
    is_forced = form.get('is_forced') == 'on'
    process_obj = db.query(ProductionProcess).get(process_id)
    if not (process_obj and process_obj.project_id == project.id):
        return {}
    item = db.query(ContractItem).get(process_obj.contract_item_id)
    if not item:
        return {}
    can_start = can_start_process(item, process_obj)
    if new_status in ('진행중', '완료') and not can_start and not is_forced:
        return {'flash': ('선행 공정이 완료/진행되지 않아 변경할 수 없습니다. (강제진행 사용 가능)', 'warning')}
    old = process_obj.status or '대기'
    changed = set_process_status(process_obj, new_status)
    if changed:
        process_obj.is_forced = bool(is_forced)
        recompute_process_progress(db, process_obj, item.quantity)
        refresh_production_statuses(db, project_id=project.id)
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=(
                f"{current_user}님이 공정상태 수정: {item.model_name or '-'} / {process_obj.process_name}"
                f"\n상태: {old} ➡️ {process_obj.status}"
                + ("\n(강제진행 적용)" if is_forced else "")
            ),
            scope='production',
            kind='system'
        )
        return {'flash': ('공정 상태가 저장되었습니다.', 'success')}
    return {}


def handle_add_daily_log(db, project, form, current_user, **ctx):
    process_id = safe_int(form.get('process_id'))
    process_obj = db.query(ProductionProcess).get(process_id)
    if not (process_obj and process_obj.project_id == project.id):
        return {}
    item = db.query(ContractItem).get(process_obj.contract_item_id)
    if not item:
        return {}

    work_date = parse_date(form.get('work_date')) or datetime.date.today()
    requested_qty = safe_int(form.get('daily_qty'), 0)
    daily_qty, remain = _clamp_daily_qty(db, process_obj, item.quantity, requested_qty)
    memo = form.get('memo')

    if requested_qty > 0 and daily_qty <= 0:
        return {'flash': ('진행량이 계약수량에 이미 도달하여 추가 반영할 수 없습니다.', 'warning')}

    db.add(ProductionDailyLog(
        production_process_id=process_obj.id,
        work_date=work_date,
        daily_qty=daily_qty,
        memo=memo,
        created_by=current_user
    ))
    if (process_obj.status or '대기') == '대기':
        set_process_status(process_obj, '진행중')

    recompute_process_progress(db, process_obj, item.quantity)
    refresh_production_statuses(db, project_id=project.id)

    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템 🤖',
        content=(
            f"{current_user}님이 일일진행량 등록: {item.model_name or '-'} / {process_obj.process_name}"
            f"\n작업일: {work_date} / 수량: {daily_qty}"
            + (f"\n메모: {memo}" if memo else "")
        ),
        scope='production',
        kind='system'
    )

    flashes = []
    if requested_qty > daily_qty:
        flashes.append((f'입력 수량이 계약수량을 초과하여 {daily_qty}개만 반영되었습니다. (잔여 가능수량: {remain}개)', 'warning'))
    flashes.append(('일일 진행량이 저장되었습니다.', 'success'))
    return {'flashes': flashes}


def handle_toggle_item_complete(db, project, form, current_user, **ctx):
    item_id = safe_int(form.get('item_id'), 0)
    is_complete = is_true_value(form.get('is_complete'))
    item = db.query(ContractItem).join(Contract).filter(
        ContractItem.id == item_id,
        Contract.project_id == project.id
    ).first()

    if not item:
        return {'error': '품목을 찾을 수 없습니다.', 'status_code': 404}

    last_process = _get_last_process(item)
    if not last_process:
        return {'error': '마지막 공정을 찾을 수 없습니다.', 'status_code': 400}

    current_status = (last_process.status or '대기').strip()
    if current_status not in ('진행중', '완료'):
        return {'error': '마지막 공정이 진행중/완료 상태일 때만 생산완료를 변경할 수 있습니다.', 'status_code': 400}

    target_status = '완료' if is_complete else '진행중'
    changed = set_process_status(last_process, target_status)
    if changed:
        recompute_process_progress(db, last_process, item.quantity)

    refresh_production_statuses(db, project_id=project.id)
    detail = (
        f"{current_user}님이 생산완료 토글 변경: {item.model_name or '-'}"
        f"\n마지막공정: {last_process.process_name}"
        f"\n상태: {current_status} ➡️ {last_process.status}"
        f"\n품목상태: {item.status_prod}"
    )
    history_log_obj = append_history_log(
        db,
        project_id=project.id,
        user_name='시스템 🤖',
        content=detail,
        scope='production',
        kind='system'
    )
    db.flush()

    return {
        'flash': ('생산완료 토글이 저장되었습니다.', 'success'),
        'ajax_data': {
            'ok': True,
            'item_id': item.id,
            'item_status': item.status_prod,
            'last_process_id': last_process.id,
            'last_process_status': last_process.status,
            'last_process_completed_at': _fmt_dt(last_process.completed_at),
            'history_log': _history_payload(history_log_obj),
            'message': '저장되었습니다.'
        }
    }


def handle_toggle_process_active(db, project, form, current_user, **ctx):
    process_id = safe_int(form.get('process_id'))
    is_active = is_true_value(form.get('is_active'))
    off_reason = (form.get('off_reason') or '').strip()
    process_obj = db.query(ProductionProcess).get(process_id)
    if not process_obj or process_obj.project_id != project.id:
        return {'error': '공정을 찾을 수 없습니다.', 'status_code': 404}

    item = db.query(ContractItem).get(process_obj.contract_item_id)
    if not item:
        return {'error': '품목을 찾을 수 없습니다.', 'status_code': 404}

    if not is_active and not off_reason:
        return {'error': '제작 OFF 사유를 입력해 주세요.', 'status_code': 400}

    target_status = '진행중' if is_active else '대기'
    if target_status == '진행중' and not can_start_process(item, process_obj):
        return {'error': '선행 공정이 진행/완료 상태가 아닙니다.', 'status_code': 400}

    old = process_obj.status or '대기'
    prev_started_at = process_obj.started_at
    changed = set_process_status(process_obj, target_status)
    history_log_obj = None
    if changed:
        if not is_active:
            process_obj.started_at = None
            process_obj.completed_at = None
        recompute_process_progress(db, process_obj, item.quantity)
        refresh_production_statuses(db, project_id=project.id)
        detail = (
            f"{current_user}님이 제작토글 변경: {item.model_name or '-'} / {process_obj.process_name}"
            f"\n상태: {old} ➡️ {process_obj.status}"
        )
        if not is_active:
            detail += f"\nOFF 사유: {off_reason}"
            if prev_started_at:
                detail += f"\n이전 시작일시 기록: {prev_started_at.strftime('%Y-%m-%d %H:%M')}"
        history_log_obj = append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=detail,
            scope='production',
            kind='system'
        )
        db.flush()

    return {
        'ajax_data': {
            'ok': True,
            'process_id': process_obj.id,
            'status': process_obj.status,
            'progress_qty': int(process_obj.progress_qty or 0),
            'progress_percent': float(process_obj.progress_percent or 0),
            'started_at': _fmt_dt(process_obj.started_at),
            'completed_at': _fmt_dt(process_obj.completed_at),
            'item_status': item.status_prod,
            'history_log': _history_payload(history_log_obj),
            'message': '저장되었습니다.'
        }
    }


def handle_update_process_modal(db, project, form, current_user, **ctx):
    process_id = safe_int(form.get('process_id'))
    process_obj = db.query(ProductionProcess).get(process_id)
    if not (process_obj and process_obj.project_id == project.id):
        return {}
    item = db.query(ContractItem).get(process_obj.contract_item_id)
    if not item:
        return {}

    is_forced = is_true_value(form.get('is_forced'))
    requested_qty = safe_int(form.get('daily_qty'), 0)
    add_qty, remain = _clamp_daily_qty(db, process_obj, item.quantity, requested_qty)
    memo = (form.get('memo') or '').strip()
    work_date = parse_date(form.get('work_date')) or datetime.date.today()
    changed = False
    old = process_obj.status or '대기'

    process_obj.is_forced = bool(is_forced)

    if add_qty > 0 or memo:
        db.add(ProductionDailyLog(
            production_process_id=process_obj.id,
            work_date=work_date,
            daily_qty=add_qty,
            memo=memo,
            created_by=current_user
        ))

    if add_qty > 0 and (process_obj.status or '대기') == '대기':
        can_start = can_start_process(item, process_obj)
        if not can_start and not is_forced:
            return {'flash': ('선행 공정이 완료/진행되지 않아 진행량을 반영할 수 없습니다.', 'warning')}
        changed = set_process_status(process_obj, '진행중')

    if changed or add_qty > 0 or memo:
        recompute_process_progress(db, process_obj, item.quantity)
        refresh_production_statuses(db, project_id=project.id)
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=(
                f"{current_user}님이 공정 상세수정: {item.model_name or '-'} / {process_obj.process_name}"
                f"\n상태: {old} ➡️ {process_obj.status}"
                + (f"\n진행량 추가: +{add_qty}" if add_qty > 0 else "")
                + (f"\n메모: {memo}" if memo else "")
                + ("\n(강제진행 적용)" if is_forced else "")
            ),
            scope='production',
            kind='system'
        )
        flashes = []
        if requested_qty > add_qty:
            flashes.append((f'입력 수량이 계약수량을 초과하여 {add_qty}개만 반영되었습니다. (잔여 가능수량: {remain}개)', 'warning'))
        flashes.append(('공정 상세정보가 저장되었습니다.', 'success'))
        return {'flashes': flashes}
    return {}


def handle_add_chat(db, project, form, current_user, **ctx):
    msg = (form.get('chat_message') or '').strip()
    if msg:
        append_history_log(
            db,
            project_id=project.id,
            user_name=current_user,
            content=msg,
            scope='production',
            kind='comment'
        )
    return {}


def handle_add_history_reply(db, project, form, current_user, **ctx):
    parent_id_raw = form.get('parent_log_id')
    reply_message = (form.get('reply_message') or '').strip()
    if parent_id_raw and reply_message:
        parent = db.query(HistoryLog).get(int(parent_id_raw))
        if parent and parent.project_id == project.id:
            origin_full = (parent.content or '').strip()
            origin_snapshot = origin_full[:220] + '...' if len(origin_full) > 220 else origin_full
            append_history_log(
                db,
                project_id=project.id,
                user_name=current_user,
                content=reply_message,
                scope='production',
                kind='reply',
                parent_log_id=parent.id,
                root_log_id=parent.root_log_id or parent.id,
                origin_snapshot=origin_snapshot,
            )
    return {}
