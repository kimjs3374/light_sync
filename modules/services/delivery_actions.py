import datetime
import os

from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload

from modules.utils import validate_upload, safe_int, parse_date
from modules.models import (
    Project,
    Contract,
    Contact,
    User,
    Delivery,
    DeliverySplit,
    DeliveryPhoto,
    HistoryLog,
)
from modules.history_board import append_history_log
from modules.storage_adapter import upload_bytes, delete_object, is_storage_enabled


# --- Constants (moved from routes/delivery.py) ---

PHOTO_TYPE_ALIASES = {
    "production_done": "production_done",
    "loading": "loading",
    "delivery_done": "delivery_done",
    "etc": "etc",
    "제작완료": "production_done",
    "상차": "loading",
    "납품완료": "delivery_done",
    "기타": "etc",
}
SPLIT_STATUS_DONE_VALUES = {"done", "완료"}


# --- Utility functions (moved from routes/delivery.py) ---

def normalize_photo_type(photo_type: str):
    return PHOTO_TYPE_ALIASES.get((photo_type or "").strip(), "etc")


def _parse_datetime_local(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def sync_deliveries(db, project_id=None):
    q = db.query(Project).filter(Project.is_contracted.is_(True)).options(
        joinedload(Project.contacts),
        joinedload(Project.contracts).joinedload(Contract.items),
        joinedload(Project.deliveries).joinedload(Delivery.splits),
        joinedload(Project.deliveries).joinedload(Delivery.photos),
    )
    if project_id:
        q = q.filter(Project.id == project_id)

    projects = q.all()
    today = datetime.date.today()
    for project in projects:
        existing_by_contract = {d.contract_id: d for d in (project.deliveries or []) if d.contract_id}
        for contract in project.contracts:
            delivery = existing_by_contract.get(contract.id)
            if not delivery:
                primary_contact = (project.contacts or [None])[0]
                delivery = Delivery(
                    project_id=project.id,
                    contract_id=contract.id,
                    delivery_status="waiting",
                    contact_name=(primary_contact.name if primary_contact else None),
                    contact_phone=(primary_contact.phone if primary_contact else None),
                )
                db.add(delivery)
                db.flush()

            planned_total = sum(safe_int(item.quantity, 0) for item in (contract.items or []))
            delivered_total = sum(safe_int(split.quantity, 0) for split in (delivery.splits or []) if (split.status or "") in SPLIT_STATUS_DONE_VALUES)
            delivery.planned_total_qty = planned_total
            delivery.delivered_total_qty = delivered_total

            has_confirmed_split = any(split.confirmed_date for split in (delivery.splits or []))
            has_loading_done = any(split.loading_done_at for split in (delivery.splits or []))
            has_today_split = any((split.confirmed_date == today or split.scheduled_date == today) for split in (delivery.splits or []))
            has_done_photo = any(normalize_photo_type(photo.photo_type) == "delivery_done" for photo in (delivery.photos or []))
            is_completed = bool(planned_total > 0 and delivered_total >= planned_total and has_done_photo)

            if is_completed:
                delivery.delivery_status = "done"
            elif has_loading_done or has_today_split:
                delivery.delivery_status = "in_progress"
            elif has_confirmed_split:
                delivery.delivery_status = "coordinating"
            else:
                delivery.delivery_status = "waiting"


# --- Action Handlers ---

def handle_sync_deliveries(db, project, form, current_user, **ctx):
    sync_deliveries(db, project_id=project.id)
    append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} executed delivery sync.", scope="delivery", kind="system")
    return {'flash': ('Delivery sync completed.', 'success')}


def handle_add_split(db, project, form, current_user, **ctx):
    delivery_id = safe_int(form.get("delivery_id"))
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project.id).first()
    if delivery:
        split = DeliverySplit(
            delivery_id=delivery.id,
            split_no=safe_int(form.get("split_no"), 1),
            quantity=safe_int(form.get("quantity"), 0),
            scheduled_date=parse_date(form.get("scheduled_date")),
            confirmed_date=parse_date(form.get("confirmed_date")),
            status=(form.get("status") or "waiting"),
            note=(form.get("note") or "").strip() or None,
        )
        db.add(split)
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} added split #{split.split_no} qty {split.quantity}.", scope="delivery", kind="system")
        return {'flash': ('Split added.', 'success')}
    return {}


def handle_update_split(db, project, form, current_user, **ctx):
    split_id = safe_int(form.get("split_id"))
    split = db.query(DeliverySplit).join(Delivery).filter(DeliverySplit.id == split_id, Delivery.project_id == project.id).first()
    if split:
        split.split_no = safe_int(form.get("split_no"), split.split_no)
        split.quantity = safe_int(form.get("quantity"), split.quantity)
        split.scheduled_date = parse_date(form.get("scheduled_date"))
        split.confirmed_date = parse_date(form.get("confirmed_date"))
        split.loading_done_at = _parse_datetime_local(form.get("loading_done_at"))
        split.delivered_done_at = _parse_datetime_local(form.get("delivered_done_at"))
        split.status = form.get("status") or split.status or "waiting"
        split.note = (form.get("note") or "").strip() or None
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} updated split #{split.split_no} status {split.status}.", scope="delivery", kind="system")
        return {'flash': ('Split updated.', 'success')}
    return {}


def handle_delete_split(db, project, form, current_user, **ctx):
    split_id = safe_int(form.get("split_id"))
    split = db.query(DeliverySplit).join(Delivery).filter(DeliverySplit.id == split_id, Delivery.project_id == project.id).first()
    if split:
        split_no = split.split_no
        db.delete(split)
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} deleted split #{split_no}.", scope="delivery", kind="system")
        return {'flash': ('Split deleted.', 'success')}
    return {}


def handle_assign_delivery_owner(db, project, form, current_user, **ctx):
    if not ctx.get('can_assign_owner'):
        return {'flash': ('No permission to assign owner.', 'warning')}
    delivery_id = safe_int(form.get("delivery_id"))
    owner_user_id = safe_int(form.get("owner_user_id"))
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project.id).first()
    owner = db.query(User).get(owner_user_id) if owner_user_id else None
    if delivery and owner:
        delivery.contact_name = owner.full_name
        delivery.contact_phone = owner.phone_number
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} assigned owner {owner.full_name}.", scope="delivery", kind="system")
        return {'flash': ('Owner assigned.', 'success')}
    return {}


def handle_assign_me(db, project, form, current_user, **ctx):
    delivery_id = safe_int(form.get("delivery_id"))
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project.id).first()
    if delivery:
        delivery.contact_name = current_user
        user_id = ctx.get('user_id')
        db_user = db.query(User).get(user_id) if user_id else None
        delivery.contact_phone = db_user.phone_number if db_user else delivery.contact_phone
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} assigned self as owner.", scope="delivery", kind="system")
        return {'flash': ('Assigned to you.', 'success')}
    return {}


def handle_add_photo(db, project, form, current_user, **ctx):
    if not is_storage_enabled():
        return {'flash': ('Storage is not configured.', 'danger')}
    delivery_id = safe_int(form.get("delivery_id"))
    split_id = safe_int(form.get("split_id"), 0) or None
    contract_item_id = safe_int(form.get("contract_item_id"), 0) or None
    photo_type = normalize_photo_type(form.get("photo_type") or "etc")
    files = ctx.get('files', {})
    file = files.get("photo_file")
    valid, upload_msg = validate_upload(file)
    if not valid:
        return {'flash': (upload_msg, 'warning')}
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project.id).first()
    if delivery and file and file.filename:
        safe_name = secure_filename(file.filename) or f"photo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        ext = os.path.splitext(safe_name)[1].lower() or ".jpg"
        stored_name = f"item{contract_item_id or 0}_{safe_name}"
        object_path = (
            f"storage/deliveries/project_{project.id}/delivery_{delivery_id}/"
            f"contract_{delivery.contract_id or 0}/item_{contract_item_id or 0}/split_{split_id or 0}/photos/"
            f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
        )
        content = file.read()
        ok, err = upload_bytes(object_path, content, content_type=(file.mimetype or "application/octet-stream"), upsert=True)
        if not ok:
            return {'flash': (f"Photo upload failed: {err}", 'danger')}
        db.add(DeliveryPhoto(delivery_id=delivery_id, split_id=split_id, photo_type=photo_type, file_name=stored_name, storage_path=object_path, uploaded_by=current_user))
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} uploaded photo {stored_name} ({photo_type}).", scope="delivery", kind="system")
        return {'flash': ('Photo uploaded.', 'success')}
    return {}


def handle_delete_photo(db, project, form, current_user, **ctx):
    photo_id = safe_int(form.get("photo_id"))
    photo = db.query(DeliveryPhoto).join(Delivery).filter(DeliveryPhoto.id == photo_id, Delivery.project_id == project.id).first()
    if photo:
        file_name = photo.file_name
        delete_object(photo.storage_path)
        db.delete(photo)
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} deleted photo {file_name}.", scope="delivery", kind="system")
        return {'flash': ('Photo deleted.', 'success')}
    return {}


def handle_add_contact(db, project, form, current_user, **ctx):
    name = (form.get("name") or "").strip()
    category = (form.get("contact_category") or "").strip()
    phone = (form.get("phone") or "").strip()
    email = (form.get("email") or "").strip()
    if not name:
        return {'flash': ('Name is required.', 'warning')}
    db.add(Contact(project_id=project.id, category=category, name=name, phone=phone, email=email))
    append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} added contact {name} ({category or '-'})", scope="delivery", kind="system")
    return {'flash': ('Contact added.', 'success')}


def handle_update_contact(db, project, form, current_user, **ctx):
    contact_id = safe_int(form.get("contact_id"))
    con = db.query(Contact).filter(Contact.id == contact_id, Contact.project_id == project.id).first()
    if con:
        old = f"{con.category or '-'} / {con.name or '-'} / {con.phone or '-'} / {con.email or '-'}"
        con.category = (form.get("contact_category") or "").strip()
        con.name = (form.get("name") or "").strip()
        con.phone = (form.get("phone") or "").strip()
        con.email = (form.get("email") or "").strip()
        new = f"{con.category or '-'} / {con.name or '-'} / {con.phone or '-'} / {con.email or '-'}"
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} updated contact. Before: {old} | After: {new}", scope="delivery", kind="system")
        return {'flash': ('Contact updated.', 'success')}
    return {}


def handle_delete_contact(db, project, form, current_user, **ctx):
    contact_id = safe_int(form.get("contact_id"))
    con = db.query(Contact).filter(Contact.id == contact_id, Contact.project_id == project.id).first()
    if con:
        con_name = con.name
        db.delete(con)
        append_history_log(db, project_id=project.id, user_name="System", content=f"{current_user} deleted contact {con_name}.", scope="delivery", kind="system")
        return {'flash': ('Contact deleted.', 'success')}
    return {}


def handle_update_inspection(db, project, form, current_user, **ctx):
    """납품 검수 상태 업데이트 + 히스토리 자동 기록 (매그나텍 PHASE 7)"""
    delivery_id = safe_int(form.get("delivery_id"))
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.project_id == project.id
    ).first()
    if not delivery:
        return {}

    old_status = delivery.inspection_status or '미검수'
    new_status = (form.get("inspection_status") or "").strip()
    if not new_status or new_status == old_status:
        return {}

    delivery.inspection_status = new_status
    delivery.inspection_date = parse_date(form.get("inspection_date"))
    delivery.inspection_note = (form.get("inspection_note") or "").strip() or None
    delivery.inspector = (form.get("inspector") or "").strip() or None

    content = f"[검수] {old_status} → {new_status}"
    if delivery.inspector:
        content += f" | 검수자: {delivery.inspector}"
    if delivery.inspection_note:
        content += f" | 비고: {delivery.inspection_note}"
    append_history_log(
        db,
        project_id=project.id,
        user_name="System",
        content=f"{current_user} {content}",
        scope="delivery",
        kind="system",
    )
    return {'flash': (f'검수 상태 변경: {new_status}', 'success')}


def handle_add_chat(db, project, form, current_user, **ctx):
    msg = (form.get("chat_message") or "").strip()
    if msg:
        append_history_log(db, project_id=project.id, user_name=current_user, content=msg, scope="delivery", kind="comment")
    return {}


def handle_add_history_reply(db, project, form, current_user, **ctx):
    parent_id_raw = form.get("parent_log_id")
    reply_message = (form.get("reply_message") or "").strip()
    if parent_id_raw and reply_message:
        parent = db.query(HistoryLog).get(int(parent_id_raw))
        if parent and parent.project_id == project.id:
            origin_full = (parent.content or "").strip()
            origin_snapshot = origin_full[:220] + "..." if len(origin_full) > 220 else origin_full
            append_history_log(
                db,
                project_id=project.id,
                user_name=current_user,
                content=reply_message,
                scope="delivery",
                kind="reply",
                parent_log_id=parent.id,
                root_log_id=parent.root_log_id or parent.id,
                origin_snapshot=origin_snapshot,
            )
            append_history_log(
                db,
                project_id=project.id,
                user_name=current_user,
                content="[reply]\nReply:\n" + reply_message + "\n---Original---\n" + origin_full,
                scope="common",
                kind="comment",
            )
    return {}
