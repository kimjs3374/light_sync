import datetime

from modules.utils import safe_int, parse_date, date_to_dt_start
from modules.models import MaterialOrder, HistoryLog
from modules.history_board import append_history_log


def handle_sync_material_orders(db, project, form, current_user, **ctx):
    sync_fn = ctx['sync_fn']
    refresh_fn = ctx['refresh_fn']
    sync_fn(db, project.id)
    refresh_fn(db, project.id)
    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템 🤖',
        content=f"{current_user}님이 자재 자동생성/동기화를 실행했습니다.",
        scope='material',
        kind='system'
    )
    return {'flash': ('자재 자동생성/동기화가 완료되었습니다.', 'success')}


def handle_update_material_order(db, project, form, current_user, **ctx):
    refresh_fn = ctx['refresh_fn']
    order_id = safe_int(form.get('material_order_id'))
    order = db.query(MaterialOrder).get(order_id)
    if not (order and order.project_id == project.id):
        return {}

    old_status = order.order_status or '발주대기'
    old_out = order.outsourcing_status or '-'

    order.order_date = parse_date(form.get('order_date'))
    order.expected_in_date = parse_date(form.get('expected_in_date'))
    in_confirmed_date = parse_date(form.get('in_confirmed_date'))
    order.note = form.get('note')

    new_status = form.get('order_status') or old_status
    if new_status in ('발주대기', '발주완료', '입고완료'):
        order.order_status = new_status

    if order.is_outsourcing:
        new_out = form.get('outsourcing_status')
        if new_out in ('외주입고대기', '외주입고', '가공중', '본사입고완료'):
            order.outsourcing_status = new_out
            if new_out == '본사입고완료':
                order.order_status = '입고완료'
                order.in_confirmed = True
                order.in_confirmed_at = datetime.datetime.now()

    in_confirmed = form.get('in_confirmed') == 'on'
    order.in_confirmed = in_confirmed
    if in_confirmed:
        order.order_status = '입고완료'
        if in_confirmed_date:
            order.in_confirmed_at = date_to_dt_start(in_confirmed_date)
        elif not order.in_confirmed_at:
            order.in_confirmed_at = datetime.datetime.now()
    else:
        order.in_confirmed_at = None

    if order.order_status == '발주완료' and not order.order_date:
        order.order_date = datetime.date.today()

    append_history_log(
        db,
        project_id=order.project_id,
        user_name='시스템 🤖',
        content=(
            f"{current_user}님이 자재상태 수정: {order.item_model_name or '-'} / {order.material_name}"
            f"\n상태: {old_status} ➡️ {order.order_status}"
            f"\n외주: {old_out} ➡️ {order.outsourcing_status or '-'}"
        ),
        scope='material',
        kind='system'
    )
    refresh_fn(db, project.id)
    return {'flash': ('자재 정보가 저장되었습니다.', 'success')}


def handle_bulk_update_material_orders(db, project, form, current_user, **ctx):
    refresh_fn = ctx['refresh_fn']
    raw_ids = form.getlist('selected_order_ids')
    selected_ids = []
    for v in raw_ids:
        if (v or '').isdigit():
            selected_ids.append(int(v))
    selected_ids = sorted(set(selected_ids))

    if not selected_ids:
        return {'flash': ('일괄적용할 자재를 선택해 주세요.', 'warning')}

    orders = db.query(MaterialOrder).filter(
        MaterialOrder.project_id == project.id,
        MaterialOrder.id.in_(selected_ids)
    ).all()

    bulk_status = form.get('bulk_order_status') or ''
    bulk_order_date = parse_date(form.get('bulk_order_date'))
    bulk_expected_in_date = parse_date(form.get('bulk_expected_in_date'))
    bulk_in_confirmed = form.get('bulk_in_confirmed') or ''
    bulk_in_confirmed_date = parse_date(form.get('bulk_in_confirmed_date'))
    bulk_outsourcing_status = form.get('bulk_outsourcing_status') or ''
    bulk_note_mode = form.get('bulk_note_mode') or 'append'
    bulk_note_text = (form.get('bulk_note_text') or '').strip()

    valid_statuses = {'발주대기', '발주완료', '입고완료'}
    valid_out_statuses = {'외주입고대기', '외주입고', '가공중', '본사입고완료'}

    updated_count = 0
    skip_outsource_count = 0
    for order in orders:
        changed = False

        if bulk_status in valid_statuses and order.order_status != bulk_status:
            order.order_status = bulk_status
            changed = True

        if bulk_order_date and order.order_date != bulk_order_date:
            order.order_date = bulk_order_date
            changed = True

        if bulk_expected_in_date and order.expected_in_date != bulk_expected_in_date:
            order.expected_in_date = bulk_expected_in_date
            changed = True

        if bulk_outsourcing_status in valid_out_statuses:
            if order.is_outsourcing:
                if order.outsourcing_status != bulk_outsourcing_status:
                    order.outsourcing_status = bulk_outsourcing_status
                    changed = True
                if bulk_outsourcing_status == '본사입고완료':
                    if order.order_status != '입고완료':
                        order.order_status = '입고완료'
                        changed = True
                    if not order.in_confirmed:
                        order.in_confirmed = True
                        changed = True
                    if not order.in_confirmed_at:
                        order.in_confirmed_at = datetime.datetime.now()
                        changed = True
            else:
                skip_outsource_count += 1

        if bulk_in_confirmed == 'yes':
            if not order.in_confirmed:
                order.in_confirmed = True
                changed = True
            if order.order_status != '입고완료':
                order.order_status = '입고완료'
                changed = True
            target_confirm_dt = date_to_dt_start(bulk_in_confirmed_date) if bulk_in_confirmed_date else datetime.datetime.now()
            if order.in_confirmed_at != target_confirm_dt:
                order.in_confirmed_at = target_confirm_dt
                changed = True
        elif bulk_in_confirmed == 'no':
            if order.in_confirmed:
                order.in_confirmed = False
                changed = True
            if order.in_confirmed_at is not None:
                order.in_confirmed_at = None
                changed = True

        if bulk_note_text:
            if bulk_note_mode == 'replace':
                if (order.note or '') != bulk_note_text:
                    order.note = bulk_note_text
                    changed = True
            else:
                merged = f"{order.note}\n{bulk_note_text}".strip() if order.note else bulk_note_text
                if (order.note or '') != merged:
                    order.note = merged
                    changed = True

        if order.order_status == '발주완료' and not order.order_date:
            order.order_date = datetime.date.today()
            changed = True

        if changed:
            updated_count += 1

    if updated_count:
        refresh_fn(db, project.id)
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=(
                f"{current_user}님이 자재 {updated_count}건 일괄적용"
                f" (선택 {len(selected_ids)}건"
                f"{', 외주미대상 ' + str(skip_outsource_count) + '건 스킵' if skip_outsource_count else ''})"
            ),
            scope='material',
            kind='system'
        )
        return {'flash': (f'일괄적용 완료: {updated_count}건 반영', 'success')}
    return {'flash': ('변경된 내용이 없습니다. 적용값을 확인해 주세요.', 'info')}


def handle_add_chat(db, project, form, current_user, **ctx):
    msg = (form.get('chat_message') or '').strip()
    if msg:
        append_history_log(
            db,
            project_id=project.id,
            user_name=current_user,
            content=msg,
            scope='material',
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
                scope='material',
                kind='reply',
                parent_log_id=parent.id,
                root_log_id=parent.root_log_id or parent.id,
                origin_snapshot=origin_snapshot,
            )
    return {}
