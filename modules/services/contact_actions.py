"""연락처/히스토리/자재 추가 action 핸들러."""
import datetime

from modules.utils import safe_int, parse_date
from modules.models import (
    Contact, Contract, Material, HistoryLog,
    DETAIL_ITEM_OPTIONS, normalize_detail_item,
)
from modules.history_board import append_history_log


def handle_add_contact(db, project, form, current_user, **ctx):
    new_con = Contact(
        project_id=project.id,
        name=form.get('name'), phone=form.get('phone'),
        email=form.get('email'), category=form.get('contact_category')
    )
    db.add(new_con)
    append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                       content=f"{current_user}님이 담당자 추가: {new_con.name}({new_con.category})",
                       scope='common', kind='system')
    return {}


def handle_update_contact(db, project, form, current_user, **ctx):
    con = db.query(Contact).get(safe_int(form.get('contact_id')))
    if con:
        old_info = f"{con.name}/{con.phone or '-'}"
        con.category = form.get('contact_category')
        con.name = form.get('name')
        con.phone = form.get('phone')
        con.email = form.get('email')
        new_info = f"{con.name}/{con.phone or '-'}"
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                           content=f"{current_user}님이 담당자 수정: {old_info} ➡️ {new_info}",
                           scope='common', kind='system')
    return {}


def handle_delete_contact(db, project, form, current_user, **ctx):
    con = db.query(Contact).get(safe_int(form.get('contact_id')))
    if con:
        reason = form.get('delete_reason') or '사유 미입력'
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                           content=f"{current_user}님이 담당자 삭제: {con.name} (사유: {reason})",
                           scope='common', kind='system')
        db.delete(con)
    return {}


def handle_add_material(db, project, form, current_user, **ctx):
    mat_category = normalize_detail_item(form.get('category'), default=DETAIL_ITEM_OPTIONS[0])
    new_mat = Material(
        project_id=project.id, category=mat_category,
        model_name=form.get('model_name'), quantity=form.get('quantity')
    )
    db.add(new_mat)
    append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                       content=f"{current_user}님이 품목 추가: {new_mat.category}({new_mat.model_name}) {new_mat.quantity}개",
                       scope='design', kind='system')
    return {}


def handle_update_payment(db, project, form, current_user, **ctx):
    """대금 상태 업데이트 + 히스토리 자동 기록 (매그나텍 PHASE 8)"""
    contract_id = safe_int(form.get("contract_id"))
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.project_id == project.id
    ).first()
    if not contract:
        return {}

    old_status = contract.payment_status or '미청구'
    new_status = (form.get("payment_status") or "").strip()
    if not new_status or new_status == old_status:
        return {}

    contract.payment_status = new_status

    if new_status == '청구완료':
        contract.invoice_date = parse_date(form.get("invoice_date")) or datetime.date.today()
    elif new_status == '입금완료':
        contract.payment_date = parse_date(form.get("payment_date")) or datetime.date.today()

    content = f"[대금] {old_status} → {new_status}"
    if new_status == '청구완료' and contract.invoice_date:
        content += f" | 세금계산서 발행일: {contract.invoice_date}"
    elif new_status == '입금완료' and contract.payment_date:
        content += f" | 입금확인일: {contract.payment_date}"
    append_history_log(
        db,
        project_id=project.id,
        user_name="System",
        content=f"{current_user} {content}",
        scope="contract",
        kind="system",
    )
    return {'flash': (f'대금 상태 변경: {new_status}', 'success')}


def handle_add_chat(db, project, form, current_user, **ctx):
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
    return {}


def handle_add_history_reply(db, project, form, current_user, **ctx):
    page_scope = ctx.get('page_scope', 'design')
    parent_id_raw = form.get('parent_log_id')
    reply_message = (form.get('reply_message') or '').strip()
    if parent_id_raw and reply_message:
        parent = db.query(HistoryLog).get(int(parent_id_raw))
        if parent and parent.project_id == project.id:
            origin_full = (parent.content or '').strip()
            origin_snapshot = origin_full
            if len(origin_snapshot) > 220:
                origin_snapshot = origin_snapshot[:220] + '...'
            append_history_log(
                db,
                project_id=project.id,
                user_name=current_user,
                content=reply_message,
                scope=parent.log_scope or ('common' if (parent.log_kind or '') == 'comment' else page_scope),
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
    return {}
