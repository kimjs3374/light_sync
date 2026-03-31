import json

from modules.utils import safe_int, parse_date, is_true_value
from modules.models import (
    ContractItem, Contact, HistoryLog,
    DETAIL_ITEM_OPTIONS, normalize_detail_item,
    CONTRACT_ITEM_SPEC_SCHEMA,
)
from modules.history_board import append_history_log
from modules.kakaowork_notifier import send_group_notification
from modules.spec_utils import BOOLEAN_SPEC_FIELDS


# --- Spec helpers (moved from routes/sales.py) ---

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
            val = is_true_value(val)
        spec[field] = val.strip() if isinstance(val, str) else val

    for trigger, rule in conditional.items():
        current = spec.get(trigger)
        expected = rule.get('equals')
        current_cmp = is_true_value(current) if isinstance(expected, bool) else current
        if current_cmp == expected:
            for field in rule.get('fields', []):
                if f'spec_{field}' not in form:
                    if field in BOOLEAN_SPEC_FIELDS:
                        spec[field] = False
                    continue
                val = form.get(f'spec_{field}')
                if field in BOOLEAN_SPEC_FIELDS:
                    val = is_true_value(val)
                spec[field] = val.strip() if isinstance(val, str) else val

    for key, val in list(spec.items()):
        if key in BOOLEAN_SPEC_FIELDS:
            spec[key] = is_true_value(val)
        elif key == 'lamp_count':
            try:
                spec[key] = int(val)
            except Exception:
                spec[key] = 0
        elif val is None:
            spec[key] = ''
    return spec


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
        current_cmp = is_true_value(current) if isinstance(expected, bool) else current
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


# --- Action Handlers ---

def handle_update_sales_item(db, project, form, current_user, **ctx):
    item_id = safe_int(form.get('item_id'))
    item = db.query(ContractItem).get(item_id)
    if not (item and item.contract and item.contract.project_id == project.id):
        return {}

    old_status = item.status_sales or '계약확인'
    old_spec = dict(item.item_spec or {})

    spec_payload_raw = (form.get('spec_payload') or '').strip()
    spec = {}
    if spec_payload_raw:
        try:
            parsed_payload = json.loads(spec_payload_raw)
            if isinstance(parsed_payload, dict):
                spec = parsed_payload
        except Exception:
            spec = {}
    if not spec:
        spec = _extract_item_spec(form, item.category)
    merged_spec = dict(old_spec)
    merged_spec.update(spec)
    item.item_spec = merged_spec
    item.status_sales = _derive_sales_status(item.category, merged_spec)

    contract = item.contract
    planned_delivery = parse_date(form.get('planned_delivery_date'))
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
        log_content = (
            f"[협의관리] {current_user}님이 협의내용 수정\n"
            f"대상: {item.category}/{item.model_name}({item.quantity})\n"
            + "\n".join(changed_lines)
        )
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=log_content,
            scope='sales'
        )

        # 카카오워크 그룹채팅 알림
        project_name = project.temp_name or project.short_name or f"현장#{project.id}"
        detail_url = f"https://work.mgnt.kr/sales_management/{project.id}"
        notify_text = (
            f"[협의변경]\n"
            f"{project_name}\n"
            f"\n"
            f"품목: {item.category} / {item.model_name} ({item.quantity})\n"
            + "\n".join(changed_lines) + f"\n수정자: {current_user}\n"
            f"\n"
            f"{detail_url}"
        )
        send_group_notification(notify_text)

        return {'flash': ('협의내용이 저장되었습니다.', 'success')}
    return {'flash': ('저장되었습니다. (변경값 없음)', 'success')}


def handle_add_sales_comment(db, project, form, current_user, **ctx):
    msg = (form.get('chat_message') or '').strip()
    if msg:
        append_history_log(
            db,
            project_id=project.id,
            user_name=current_user,
            content=msg,
            scope='common',
            kind='comment'
        )
        return {'flash': ('코멘트가 등록되었습니다.', 'success')}
    return {}


def handle_add_contact(db, project, form, current_user, **ctx):
    category = (form.get('contact_category') or '').strip()
    name = (form.get('name') or '').strip()
    phone = (form.get('phone') or '').strip()
    email = (form.get('email') or '').strip()

    if not category or not name:
        return {'flash': ('담당자 구분과 이름은 필수입니다.', 'warning')}

    db.add(Contact(
        project_id=project.id,
        category=category,
        name=name,
        phone=phone,
        email=email
    ))
    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템 🤖',
        content=f"[협의관리] {current_user}님이 담당자 추가: {name} ({category})",
        scope='sales'
    )
    return {'flash': ('담당자가 추가되었습니다.', 'success')}


def handle_update_contact(db, project, form, current_user, **ctx):
    contact_id_raw = form.get('contact_id')
    if not contact_id_raw:
        return {}
    contact = db.query(Contact).get(int(contact_id_raw))
    if not (contact and contact.project_id == project.id):
        return {}

    old_info = f"{contact.category or '-'} / {contact.name or '-'} / {contact.phone or '-'} / {contact.email or '-'}"
    contact.category = (form.get('contact_category') or '').strip()
    contact.name = (form.get('name') or '').strip()
    contact.phone = (form.get('phone') or '').strip()
    contact.email = (form.get('email') or '').strip()

    new_info = f"{contact.category or '-'} / {contact.name or '-'} / {contact.phone or '-'} / {contact.email or '-'}"
    if old_info != new_info:
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=f"[협의관리] {current_user}님이 담당자 수정\n변경 전: {old_info}\n변경 후: {new_info}",
            scope='sales'
        )
    return {'flash': ('담당자 정보가 수정되었습니다.', 'success')}


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
                scope=parent.log_scope or ('common' if (parent.log_kind or '') == 'comment' else 'sales'),
                kind='reply',
                parent_log_id=parent.id,
                root_log_id=parent.root_log_id or parent.id,
                origin_snapshot=origin_snapshot
            )
            append_history_log(
                db,
                project_id=project.id,
                user_name=current_user,
                content=f"[대댓글]\n답글:\n{reply_message}\n---원글---\n{origin_full}",
                scope='common',
                kind='comment'
            )
            return {'flash': ('대댓글이 등록되었습니다.', 'success')}
    return {}
