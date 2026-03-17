from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import datetime
import json
from sqlalchemy.orm import joinedload

from modules.models import (
    SessionLocal, Project, Contract, ContractItem, HistoryLog, Contact,
    DETAIL_ITEM_OPTIONS, LIGHTING_DETAIL_ITEMS, normalize_detail_item,
    CONTRACT_ITEM_SPEC_SCHEMA, Drawing, DRAWING_TYPE_OPTIONS
)
from modules.history_board import append_history_log, get_project_history_context
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)

sales_bp = Blueprint('sales', __name__)

SALES_STATUS_STEPS = ['계약확인', '상세협의중', '협의완료']
TRUE_VALUES = {'1', 'true', 'True', 'on', 'yes', 'Y'}
BOOLEAN_SPEC_FIELDS = {'has_stabilizer_box', 'is_integrated', 'is_painted'}


def _is_true_value(value):
    return str(value).strip() in TRUE_VALUES


def _parse_date(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d').date()
    except Exception:
        return None


def _extract_item_spec(form, category):
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    required = schema.get('required', [])
    conditional = schema.get('conditional_required', {})

    spec = {}
    for field in required:
        if f'spec_{field}' not in form:
            if field in BOOLEAN_SPEC_FIELDS:
                spec[field] = False
            continue
        val = form.get(f'spec_{field}')
        if field in BOOLEAN_SPEC_FIELDS:
            val = _is_true_value(val)
        spec[field] = val.strip() if isinstance(val, str) else val

    for trigger, rule in conditional.items():
        current = spec.get(trigger)
        expected = rule.get('equals')
        current_cmp = _is_true_value(current) if isinstance(expected, bool) else current
        if current_cmp == expected:
            for field in rule.get('fields', []):
                if f'spec_{field}' not in form:
                    if field in BOOLEAN_SPEC_FIELDS:
                        spec[field] = False
                    continue
                val = form.get(f'spec_{field}')
                if field in BOOLEAN_SPEC_FIELDS:
                    val = _is_true_value(val)
                spec[field] = val.strip() if isinstance(val, str) else val

    for key, val in list(spec.items()):
        if key in BOOLEAN_SPEC_FIELDS:
            spec[key] = _is_true_value(val)
        elif key == 'lamp_count':
            try:
                spec[key] = int(val)
            except Exception:
                spec[key] = 0
        elif val is None:
            spec[key] = ''
    return spec


def _validate_item_spec(category, spec):
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    required = list(schema.get('required', []))
    conditional = schema.get('conditional_required', {})

    for trigger, rule in conditional.items():
        expected = rule.get('equals')
        current = spec.get(trigger)
        current_cmp = _is_true_value(current) if isinstance(expected, bool) else current
        if current_cmp == expected:
            required.extend(rule.get('fields', []))

    missing = []
    for field in sorted(set(required)):
        val = spec.get(field)
        if field in BOOLEAN_SPEC_FIELDS and val is False:
            continue
        if val in (None, '', []):
            missing.append(field)
    return missing


def _diff_spec(old_spec, new_spec):
    old_spec = old_spec or {}
    new_spec = new_spec or {}
    changed = []
    for k in sorted(set(list(old_spec.keys()) + list(new_spec.keys()))):
        if old_spec.get(k) != new_spec.get(k):
            changed.append(f"{k}: {old_spec.get(k)} → {new_spec.get(k)}")
    return changed


def _is_filled_value(field, value):
    if field in BOOLEAN_SPEC_FIELDS:
        return value is not None
    return value not in (None, '')


def _required_fields_for_status(category, spec):
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    fields = list(schema.get('required', []))
    conditional = schema.get('conditional_required', {})

    for trigger, rule in conditional.items():
        expected = rule.get('equals')
        current = spec.get(trigger)
        current_cmp = _is_true_value(current) if isinstance(expected, bool) else current
        if current_cmp == expected:
            fields.extend(rule.get('fields', []))
    return sorted(set(fields))


def _derive_sales_status(category, spec):
    spec = spec or {}
    req_fields = _required_fields_for_status(category, spec)
    if not req_fields:
        return '계약확인'

    filled_count = 0
    for field in req_fields:
        if _is_filled_value(field, spec.get(field)):
            filled_count += 1

    if filled_count == 0:
        return '계약확인'
    if filled_count == len(req_fields):
        return '협의완료'
    return '상세협의중'


@sales_bp.route('/sales_management')
def sales_list():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    sort_by = request.args.get('sort', 'due_asc')
    q = (request.args.get('q') or '').strip().lower()

    db = SessionLocal()
    projects = db.query(Project).filter(Project.is_contracted == True).options(
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

    stats = {
        'total': total_count,
        'filtered': len(enriched),
        'overdue': sum(1 for p in enriched if p.dday is not None and p.dday < 0),
        'due_7': sum(1 for p in enriched if p.dday is not None and 0 <= p.dday <= 7),
    }

    db.close()
    return render_template(
        'sales_list.html',
        projects=enriched,
        priority_projects=priority_projects,
        stats=stats,
        today=today,
        filters={
            'sort': sort_by,
            'q': q,
        }
    )


@sales_bp.route('/sales_management/<int:project_id>', methods=['GET', 'POST'])
def sales_detail(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    db = SessionLocal()
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
        db.close()
        flash('대상을 찾을 수 없습니다.', 'warning')
        return redirect(url_for('sales.sales_list'))

    if request.method == 'POST':
        action = request.form.get('action')
        user_name = session.get('full_name') or '사용자'

        if action == 'update_sales_item':
            item_id = int(request.form.get('item_id'))
            item = db.query(ContractItem).get(item_id)
            if item and item.contract and item.contract.project_id == project_id:
                old_status = item.status_sales or '계약확인'
                old_spec = dict(item.item_spec or {})

                spec_payload_raw = (request.form.get('spec_payload') or '').strip()
                spec = {}
                if spec_payload_raw:
                    try:
                        parsed_payload = json.loads(spec_payload_raw)
                        if isinstance(parsed_payload, dict):
                            spec = parsed_payload
                    except Exception:
                        spec = {}
                if not spec:
                    spec = _extract_item_spec(request.form, item.category)
                merged_spec = dict(old_spec)
                merged_spec.update(spec)
                item.item_spec = merged_spec
                item.status_sales = _derive_sales_status(item.category, merged_spec)

                contract = item.contract
                planned_delivery = _parse_date(request.form.get('planned_delivery_date'))
                old_planned_delivery = contract.desired_delivery_date if contract else None
                if contract:
                    contract.desired_delivery_date = planned_delivery

                changed_lines = []
                if old_status != item.status_sales:
                    changed_lines.append(f"영업단계: {old_status} → {item.status_sales}")
                spec_changes = _diff_spec(old_spec, merged_spec)
                if spec_changes:
                    changed_lines.append('협의내용 변경: ' + '; '.join(spec_changes))
                if contract and old_planned_delivery != contract.desired_delivery_date:
                    changed_lines.append(f"납품예정일: {old_planned_delivery or '-'} → {contract.desired_delivery_date or '-'}")

                if changed_lines:
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name='시스템 🤖',
                        content=(
                            f"[영업관리] {user_name}님이 협의내용 수정\n"
                            f"대상: {item.category}/{item.model_name}({item.quantity})\n"
                            + "\n".join(changed_lines)
                        ),
                        scope='sales'
                    )

                if changed_lines:
                    flash('협의내용이 저장되었습니다.', 'success')
                else:
                    flash('저장되었습니다. (변경값 없음)', 'success')

        elif action == 'add_sales_comment':
            msg = (request.form.get('chat_message') or '').strip()
            if msg:
                append_history_log(
                    db,
                    project_id=project_id,
                    user_name=user_name,
                    content=msg,
                    scope='common',
                    kind='comment'
                )
                flash('코멘트가 등록되었습니다.', 'success')

        elif action == 'add_contact':
            category = (request.form.get('contact_category') or '').strip()
            name = (request.form.get('name') or '').strip()
            phone = (request.form.get('phone') or '').strip()
            email = (request.form.get('email') or '').strip()

            if not category or not name:
                flash('담당자 구분과 이름은 필수입니다.', 'warning')
            else:
                new_contact = Contact(
                    project_id=project_id,
                    category=category,
                    name=name,
                    phone=phone,
                    email=email
                )
                db.add(new_contact)
                append_history_log(
                    db,
                    project_id=project_id,
                    user_name='시스템 🤖',
                    content=f"[영업관리] {user_name}님이 담당자 추가: {name} ({category})",
                    scope='sales'
                )
                flash('담당자가 추가되었습니다.', 'success')

        elif action == 'update_contact':
            contact_id_raw = request.form.get('contact_id')
            if contact_id_raw:
                contact = db.query(Contact).get(int(contact_id_raw))
                if contact and contact.project_id == project_id:
                    old_info = f"{contact.category or '-'} / {contact.name or '-'} / {contact.phone or '-'} / {contact.email or '-'}"

                    contact.category = (request.form.get('contact_category') or '').strip()
                    contact.name = (request.form.get('name') or '').strip()
                    contact.phone = (request.form.get('phone') or '').strip()
                    contact.email = (request.form.get('email') or '').strip()

                    new_info = f"{contact.category or '-'} / {contact.name or '-'} / {contact.phone or '-'} / {contact.email or '-'}"
                    if old_info != new_info:
                        append_history_log(
                            db,
                            project_id=project_id,
                            user_name='시스템 🤖',
                            content=f"[영업관리] {user_name}님이 담당자 수정\n변경 전: {old_info}\n변경 후: {new_info}",
                            scope='sales'
                        )
                    flash('담당자 정보가 수정되었습니다.', 'success')

        elif action == 'add_history_reply':
            parent_id_raw = request.form.get('parent_log_id')
            reply_message = (request.form.get('reply_message') or '').strip()
            if parent_id_raw and reply_message:
                parent = db.query(HistoryLog).get(int(parent_id_raw))
                if parent and parent.project_id == project_id:
                    origin_full = (parent.content or '').strip()
                    origin_snapshot = origin_full
                    if len(origin_snapshot) > 220:
                        origin_snapshot = origin_snapshot[:220] + '...'
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name=user_name,
                        content=reply_message,
                        scope=parent.log_scope or ('common' if (parent.log_kind or '') == 'comment' else 'sales'),
                        kind='reply',
                        parent_log_id=parent.id,
                        root_log_id=parent.root_log_id or parent.id,
                        origin_snapshot=origin_snapshot
                    )
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name=user_name,
                        content=f"[대댓글]\n답글:\n{reply_message}\n---원글---\n{origin_full}",
                        scope='common',
                        kind='comment'
                    )
                    flash('대댓글이 등록되었습니다.', 'success')

        db.commit()
        db.close()
        return redirect(url_for('sales.sales_detail', project_id=project_id))

    history, history_counts = get_project_history_context(
        db,
        project_id=project_id,
        default_scope='sales',
        limit=500
    )

    db.close()
    return render_template(
        'sales_detail.html',
        project=project,
        history=history,
        history_counts=history_counts,
        detail_item_options=DETAIL_ITEM_OPTIONS,
        contract_item_spec_schema=CONTRACT_ITEM_SPEC_SCHEMA,
        lighting_detail_items=LIGHTING_DETAIL_ITEMS,
        sales_status_steps=SALES_STATUS_STEPS,
        drawing_type_options=DRAWING_TYPE_OPTIONS,
        can_write_drawings=(session.get('role') == 'admin' or session.get('user_group') == '영업부'),
        now=datetime.datetime.now()
    )
