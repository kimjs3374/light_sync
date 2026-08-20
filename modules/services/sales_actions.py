import json

from modules.utils import safe_int, parse_date, is_true_value
from modules.models import (
    ContractItem, Contact, HistoryLog,
    DETAIL_ITEM_OPTIONS, normalize_detail_item,
    CONTRACT_ITEM_SPEC_SCHEMA,
)
from modules.history_board import append_history_log
from modules.notification_engine import notify
from modules.spec_utils import BOOLEAN_SPEC_FIELDS, spec_field_label, is_boolean_spec_field


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


def _spec_label(key):
    """내부 필드명 → 표시명.

    관리자설정(스펙항목 설정)에서 저장한 라벨이 있으면 그걸 쓰고,
    없으면 기본 라벨, 그것도 없으면 키 원문.
    """
    return spec_field_label(key)


def _spec_value_text(key, value):
    """스펙 값을 알림/히스토리에 쓸 문자열로 변환.

    파이썬 표현(None / True / [{'렌즈': ...}])이 그대로 나가던 것을 막는다.
    """
    if value is None or value == '':
        return '미입력'
    if is_boolean_spec_field(key) or isinstance(value, bool):
        # '안정기 BOX 유무' 처럼 라벨이 유/무를 묻는 항목은 예/아니오보다 있음/없음이 읽힌다.
        yes, no = ('있음', '없음') if _spec_label(key).endswith('유무') else ('예', '아니오')
        return yes if is_true_value(value) else no
    if isinstance(value, list):
        # bom_breakdown: [{'렌즈': '20도', '바이저': '480', 'qty': 20}, ...]
        parts = []
        for row in value:
            if isinstance(row, dict):
                qty = row.get('qty')
                desc = ' '.join(f"{k} {v}" for k, v in row.items() if k != 'qty' and v not in (None, ''))
                parts.append(f"{desc} {qty}EA".strip() if qty not in (None, '') else desc)
            else:
                parts.append(str(row))
        return ', '.join(p for p in parts if p) or '미입력'
    if isinstance(value, dict):
        inner = ', '.join(f"{k} {v}" for k, v in value.items() if v not in (None, ''))
        return inner or '미입력'
    return str(value)


def _is_blank(value):
    """None 과 '' 는 둘 다 '미입력'이므로 서로 바뀌어도 변경이 아니다."""
    return value is None or value == ''


def _spec_field_order(category):
    """협의항목을 화면(폼)에 뜨는 순서대로 정렬하기 위한 기준 키 목록.

    알파벳순으로 늘어놓으면 사용자가 입력한 순서와 어긋나 읽기 어렵다.
    """
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    order = list(schema.get('required', []))
    for trigger, rule in (schema.get('conditional_required') or {}).items():
        for field in rule.get('fields', []):
            if field not in order:
                order.append(field)
    return order


def diff_spec_entries(old_spec, new_spec, category=None):
    """협의내용 변경분을 [{label, old, new, is_new}] 로.

    빈값 ↔ 빈값(None → '')은 변경으로 치지 않는다. 이걸 걸러내지 않으면
    폼을 한 번 저장할 때마다 미입력 항목 전부가 '변경'으로 알림에 실렸다.
    """
    old_spec = old_spec or {}
    new_spec = new_spec or {}
    order = _spec_field_order(category) if category else []
    keys = sorted(
        set(list(old_spec.keys()) + list(new_spec.keys())),
        key=lambda k: (order.index(k) if k in order else len(order), k)
    )

    entries = []
    for k in keys:
        old_v, new_v = old_spec.get(k), new_spec.get(k)
        if old_v == new_v:
            continue
        if _is_blank(old_v) and _is_blank(new_v):
            continue
        entries.append({
            'key': k,
            'label': _spec_label(k),
            'old': _spec_value_text(k, old_v),
            'new': _spec_value_text(k, new_v),
            'is_new': _is_blank(old_v),
        })
    return entries


def _diff_spec(old_spec, new_spec, category=None):
    """(구형) 변경분을 '항목: 이전 → 이후' 문자열 리스트로."""
    return [
        f"{e['label']}: {e['old']} → {e['new']}"
        for e in diff_spec_entries(old_spec, new_spec, category)
    ]


def _item_headline(item):
    """품목 한 줄 — '카테고리 20EA'."""
    cat = (item.category or '').strip() or '품목'
    qty = safe_int(item.quantity, 0)
    return f"{cat} {qty}EA" if qty else cat


def _item_model_text(item):
    """모델 한 줄 — 카테고리 중복 제거 + 콤마 나열 정리.

    'LED투광등기구, 매그나텍, ARENA(M)-600, 600W' → '매그나텍 ARENA(M)-600 600W'
    """
    from modules.services.notification_bodies import model_label
    return model_label(item.category, item.model_name)


def build_spec_change_report(item, project_name, current_user,
                             old_status, new_status,
                             old_spec, new_spec,
                             old_delivery, new_delivery):
    """협의내용 수정 결과를 히스토리/알림용 문구로 조립.

    변경분을 세미콜론으로 이어붙여 한 줄에 몰아넣던 것을 항목별 줄바꿈으로 바꾼다.
    웹(routes/sales.py)과 모바일(routes/app_api.py)이 같은 문구를 쓰도록 여기 한 곳에서만 만든다.

    Returns:
        None (변경 없음) 또는 {'log', 'kakao', 'summary', 'entries'}
    """
    entries = diff_spec_entries(old_spec, new_spec, item.category)
    stage_changed = (old_status or '') != (new_status or '')
    delivery_changed = old_delivery != new_delivery
    if not (entries or stage_changed or delivery_changed):
        return None

    from modules import notification_format as nf

    detail_lines = []
    if entries:
        detail_lines.append(nf.BLANK)
        detail_lines.append(f"협의내용 {len(entries)}건")
        for e in entries:
            # 새로 채운 항목은 '미입력 →' 를 붙이지 않는다 — 값만 보이는 게 읽힌다.
            value_text = e['new'] if e['is_new'] else f"{e['old']} {nf.ARROW} {e['new']}"
            detail_lines.append(nf.bullet(f"{e['label']}: {value_text}"))

    body = nf.body(
        nf.kv('품목', _item_headline(item)),
        nf.kv('모델', _item_model_text(item)),
        nf.change('영업단계', old_status, new_status, blank='-') if stage_changed else None,
        nf.change('납품예정일', old_delivery, new_delivery, blank='미정') if delivery_changed else None,
        detail_lines,
        nf.BLANK,
        nf.kv('수정', current_user),
    )

    return {
        # 3개 채널이 그대로 쓰는 본문 (제목·링크는 알림 엔진이 붙인다)
        'body': body,
        'log': nf.body(f"[협의관리] {current_user}님이 협의내용 수정", nf.BLANK, body),
        'entries': entries,
    }


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

    project_name = project.temp_name or project.short_name or f"현장#{project.id}"

    # 계약명 조회 — 알림 제목은 현장명 아닌 계약명 기준
    from modules.models import Contract as _C
    _first_c = db.query(_C).filter(_C.project_id == project.id).first()
    _contract_name = _first_c.contract_name if _first_c and _first_c.contract_name else project_name

    report = build_spec_change_report(
        item,
        project_name=_contract_name,
        current_user=current_user,
        old_status=old_status,
        new_status=item.status_sales,
        old_spec=old_spec,
        new_spec=merged_spec,
        old_delivery=old_planned_delivery,
        new_delivery=contract.desired_delivery_date if contract else None,
    )

    if report:
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=report['log'],
            scope='sales'
        )

        # 알림 엔진: ERP 내부 + 카카오워크 동시 발송
        notify(db, 'issue.flagged', {
            'contract_name': _contract_name,
            'project_name': project_name,
            'project_id': project.id,
            'detail': report['body'],
        })

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
