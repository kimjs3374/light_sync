import datetime

from modules.utils import safe_int, parse_date, is_true_value
from modules.models import (
    ProductionProcess,
    ProductionDailyLog,
    ContractItem,
    Contract,
    HistoryLog,
)
from modules.history_board import append_history_log
from modules.production_logic import (
    sync_production_processes,
    refresh_production_statuses,
    can_start_process,
    set_process_status,
    recompute_process_progress,
)


# --- Private helpers (moved from routes/production.py) ---

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
