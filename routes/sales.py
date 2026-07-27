import json
import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from modules.auth_decorators import login_required, menu_required
import datetime
from sqlalchemy.orm import joinedload
from modules.utils import safe_int
from modules.pagination import make_pagination

from modules.db_context import get_db
from modules.contract_filters import active_contract_filter
from modules.search_filters import sales_search_filter
from modules.models import (
    Project, Contract, ContractItem,
    DETAIL_ITEM_OPTIONS, LIGHTING_DETAIL_ITEMS,
    CONTRACT_ITEM_SPEC_SCHEMA, Drawing, DRAWING_TYPE_OPTIONS,
    SALES_STATUS_STEPS,
)

# ── 협의 스펙 스키마 JSON 오버라이드 ──
_SPEC_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'spec_schema.json')
_SPEC_META_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'spec_meta.json')


def _load_spec_schema():
    """JSON 오버라이드가 있으면 사용, 없으면 constants 폴백."""
    if os.path.isfile(_SPEC_SCHEMA_PATH):
        with open(_SPEC_SCHEMA_PATH, encoding='utf-8') as f:
            return json.load(f)
    return CONTRACT_ITEM_SPEC_SCHEMA


def _save_spec_schema(data):
    os.makedirs(os.path.dirname(_SPEC_SCHEMA_PATH), exist_ok=True)
    with open(_SPEC_SCHEMA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_spec_meta():
    if os.path.isfile(_SPEC_META_PATH):
        with open(_SPEC_META_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_spec_meta(data):
    os.makedirs(os.path.dirname(_SPEC_META_PATH), exist_ok=True)
    with open(_SPEC_META_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
from modules.history_board import get_project_history_context
from modules.activity import log_activity
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)
from modules.services.g2b_catalog_sync import get_catalog_price_map, match_from_price_map
from modules.services.sales_actions import (
    handle_update_sales_item,
    handle_add_sales_comment,
    handle_add_contact,
    handle_update_contact,
    handle_add_history_reply,
)

sales_bp = Blueprint('sales', __name__)

ACTION_HANDLERS = {
    'update_sales_item': handle_update_sales_item,
    'add_sales_comment': handle_add_sales_comment,
    'add_contact': handle_add_contact,
    'update_contact': handle_update_contact,
    'add_history_reply': handle_add_history_reply,
}

@sales_bp.route('/sales_management')
@login_required
def sales_list():

    sort_by = request.args.get('sort', 'due_asc')
    q = (request.args.get('q') or '').strip().lower()
    show_done = request.args.get('show_done', '') == '1'
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 50)

    with get_db() as db:
        base_query = db.query(Project).filter(Project.is_contracted == True)
        if not show_done:
            base_query = base_query.filter(active_contract_filter())
        # 검색어를 DB 로 내려 후보를 줄인다. 최종 판정은 아래 _match_project 가 그대로 한다.
        pre_filter = sales_search_filter(q)
        if pre_filter is not None:
            base_query = base_query.filter(pre_filter)
        projects = base_query.options(
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        today = datetime.date.today()
        enriched = []
        for p in projects:
            contracts_sorted = sorted(
                p.contracts,
                key=lambda c: c.delivery_due_date or datetime.date.max
            )
            primary_contract = contracts_sorted[0] if contracts_sorted else None
            due_date = primary_contract.delivery_due_date if primary_contract else None
            dday = (due_date - today).days if due_date else None

            p.contracts = contracts_sorted
            p.primary_contract = primary_contract
            p.due_date = due_date
            p.dday = dday
            enriched.append(p)

        total_count = len(enriched)

        if q:
            def _match_project(p):
                haystacks = [
                    p.project_no or '',
                    p.temp_name or '',
                    p.short_name or ''
                ]
                for c in (p.contracts or []):
                    haystacks.append(c.contract_name or '')
                    haystacks.append(c.item_group or '')
                    for item in (c.items or []):
                        haystacks.append(item.model_name or '')
                        haystacks.append(item.category or '')
                return any(q in str(x).lower() for x in haystacks)

            enriched = [p for p in enriched if _match_project(p)]

        if sort_by == 'due_desc':
            enriched.sort(key=lambda p: (p.dday is None, -(p.dday if p.dday is not None else -99999)))
        elif sort_by == 'created_desc':
            enriched.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
        else:  # due_asc
            enriched.sort(key=lambda p: (p.dday is None, p.dday if p.dday is not None else 99999))

        priority_projects = []
        for p in enriched:
            reasons = []
            override = append_manual_priority_reason(reasons, p)
            pending_items = 0
            total_items_for_priority = 0
            is_urgent_project = bool(p.is_urgent or any(c.is_urgent_prod for c in (p.contracts or [])))

            for c in (p.contracts or []):
                for item in (c.items or []):
                    total_items_for_priority += 1
                    if (item.status_sales or '계약확인') != '협의완료':
                        pending_items += 1

            if is_urgent_project:
                append_priority_reason(reasons, 'urgent')
            append_due_priority_reason(reasons, p.dday, 'sales')
            if pending_items > 0:
                append_priority_reason(reasons, 'sales_pending', f"미완료 {pending_items}건")

            if reasons:
                meta_lines = [
                    f"계약건 수: {len(p.contracts or [])}건",
                    f"협의 미완료: {pending_items}건 / 전체 품목: {total_items_for_priority}건",
                    f"희망납기: {p.primary_contract.desired_delivery_date if p.primary_contract and p.primary_contract.desired_delivery_date else '-'}",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=p.id,
                    project_no=p.project_no,
                    title=p.temp_name or '-',
                    subtitle=(f"대표 계약: {p.primary_contract.contract_name}" if p.primary_contract else ''),
                    detail_url=url_for('sales.sales_detail', project_id=p.id),
                    reasons=reasons,
                    dday=p.dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)

        # 제품 카탈로그 단가 매칭
        price_map = get_catalog_price_map(db)
        for p in enriched:
            for c in (p.contracts or []):
                for item in (c.items or []):
                    item._catalog_price = match_from_price_map(price_map, item.model_name)

        stats = {
            'total': total_count,
            'filtered': len(enriched),
            'overdue': sum(1 for p in enriched if p.dday is not None and p.dday < 0),
            'due_7': sum(1 for p in enriched if p.dday is not None and 0 <= p.dday <= 7),
        }

        pagination = make_pagination(page, per_page, len(enriched))
        start = (pagination['page'] - 1) * per_page
        enriched_page = enriched[start:start + per_page]

        return render_template(
            'sales_list.html',
            projects=enriched_page,
            priority_projects=priority_projects,
            stats=stats,
            today=today,
            pagination=pagination,
            filters={
                'sort': sort_by,
                'q': q,
                'show_done': '1' if show_done else '',
            }
        )

@sales_bp.route('/sales_management/<int:project_id>', methods=['GET', 'POST'])
@login_required
@menu_required('sales')
def sales_detail(project_id):

    with get_db() as db:
        project = db.query(Project).options(
            joinedload(Project.contacts),
            joinedload(Project.contracts)
                .joinedload(Contract.items)
                .joinedload(ContractItem.drawings)
                .joinedload(Drawing.versions),
            joinedload(Project.contracts)
                .joinedload(Contract.items)
                .joinedload(ContractItem.barcodes)
        ).get(project_id)
        if not project:
            flash('대상을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('sales.sales_list'))

        if request.method == 'POST':
            action = request.form.get('action')
            user_name = session.get('full_name') or '사용자'

            handler = ACTION_HANDLERS.get(action)
            if handler:
                result = handler(db, project, request.form, user_name)
                if result.get('flash'):
                    flash(*result['flash'])
                for f in result.get('flashes', []):
                    flash(*f)

            log_activity(db, '협의관리', 'status_change', f'{project.temp_name or project.project_no} 협의 {action}',
                         ref_type='Project', ref_id=project.id, project_id=project.id)
            db.commit()
            return redirect(url_for('sales.sales_detail', project_id=project_id))

        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope='sales',
            limit=500,
            user_id=session.get('user_id'),
        )

        return render_template(
            'sales_detail.html',
            project=project,
            history=history,
            history_counts=history_counts,
            detail_item_options=DETAIL_ITEM_OPTIONS,
            contract_item_spec_schema=_load_spec_schema(),
            lighting_detail_items=LIGHTING_DETAIL_ITEMS,
            sales_status_steps=SALES_STATUS_STEPS,
            drawing_type_options=DRAWING_TYPE_OPTIONS,
            can_write_drawings=(session.get('role') == 'admin' or session.get('user_group') == '영업부'),
            now=datetime.datetime.now()
        )


# ── 협의 스펙 항목 관리 ──────────────────────────────────
@sales_bp.route('/sales_management/spec_schema', methods=['GET'])
@login_required
@menu_required('sales')
def spec_schema_admin():
    if session.get('role') != 'admin' and session.get('user_group') != '영업부':
        flash('영업부 또는 관리자만 접근 가능합니다.', 'warning')
        return redirect(url_for('sales.sales_list'))

    schema = _load_spec_schema()
    meta = _load_spec_meta()
    return render_template(
        'sales_spec_admin.html',
        schema=schema,
        meta=meta,
        detail_item_options=DETAIL_ITEM_OPTIONS,
    )


@sales_bp.route('/sales_management/spec_schema/save', methods=['POST'])
@login_required
@menu_required('sales')
def spec_schema_save():
    if session.get('role') != 'admin' and session.get('user_group') != '영업부':
        return jsonify({'ok': False, 'error': '권한 없음'}), 403

    data = request.get_json(silent=True) or {}
    schema = data.get('schema')
    meta = data.get('meta')

    if schema is not None:
        _save_spec_schema(schema)
    if meta is not None:
        _save_spec_meta(meta)

    return jsonify({'ok': True})


# ── BOM 옵션 스키마 조회 API ──────────────────────────────
@sales_bp.route('/api/sales/bom-options/<model_name>')
@login_required
def api_bom_options(model_name):
    """모델명으로 BOM option_schema 반환 (협의관리 옵션 드롭다운용)."""
    import json as _json
    from modules.services.bom_actions import find_bom_by_model_name
    with get_db() as db:
        bom = find_bom_by_model_name(db, model_name)
        if not bom or not bom.option_schema:
            return jsonify({'options': None})
        try:
            schema = _json.loads(bom.option_schema)
        except (ValueError, TypeError):
            return jsonify({'options': None})
        return jsonify({'options': schema, 'bom_code': bom.product_code})
