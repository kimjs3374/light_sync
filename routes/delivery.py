import datetime
import io
import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, send_file
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from modules.history_board import append_history_log, get_project_history_context
from modules.models import (
    SessionLocal,
    Project,
    Contract,
    Contact,
    User,
    Delivery,
    DeliverySplit,
    DeliveryPhoto,
    HistoryLog,
)
from modules.storage_adapter import upload_bytes, download_bytes, delete_object, is_storage_enabled
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)


delivery_bp = Blueprint("delivery", __name__)

DELIVERY_STATUS_OPTIONS = ["waiting", "coordinating", "in_progress", "done"]
STATUS_LABELS = {
    "waiting": "납품대기",
    "coordinating": "납품협의중",
    "in_progress": "납품진행중",
    "done": "납품완료",
}
PHOTO_TYPE_OPTIONS = ["production_done", "loading", "delivery_done", "etc"]
PHOTO_TYPE_LABELS = {
    "production_done": "제작완료",
    "loading": "상차",
    "delivery_done": "납품완료",
    "etc": "기타",
}
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


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime_local(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _normalize_photo_type(photo_type: str):
    return PHOTO_TYPE_ALIASES.get((photo_type or "").strip(), "etc")


def _can_assign_owner():
    return bool(
        session.get("role") == "admin"
        or session.get("can_approve_delete")
        or (session.get("user_group") or "").strip() in ("영업부서장", "관리부서장", "생산부서장", "부서장")
    )


def _sync_deliveries(db, project_id=None):
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

            planned_total = sum(_to_int(item.quantity, 0) for item in (contract.items or []))
            delivered_total = sum(_to_int(split.quantity, 0) for split in (delivery.splits or []) if (split.status or "") in SPLIT_STATUS_DONE_VALUES)
            delivery.planned_total_qty = planned_total
            delivery.delivered_total_qty = delivered_total

            has_confirmed_split = any(split.confirmed_date for split in (delivery.splits or []))
            has_loading_done = any(split.loading_done_at for split in (delivery.splits or []))
            has_today_split = any((split.confirmed_date == today or split.scheduled_date == today) for split in (delivery.splits or []))
            has_done_photo = any(_normalize_photo_type(photo.photo_type) == "delivery_done" for photo in (delivery.photos or []))
            is_completed = bool(planned_total > 0 and delivered_total >= planned_total and has_done_photo)

            if is_completed:
                delivery.delivery_status = "done"
            elif has_loading_done or has_today_split:
                delivery.delivery_status = "in_progress"
            elif has_confirmed_split:
                delivery.delivery_status = "coordinating"
            else:
                delivery.delivery_status = "waiting"


def _status_badge(status):
    return {
        "done": "success",
        "in_progress": "warning",
        "coordinating": "info",
    }.get(status, "secondary")


@delivery_bp.route("/delivery_management", methods=["GET", "POST"])
def delivery_management():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = SessionLocal()
    try:
        current_user = session.get("full_name") or "사용자"
        if request.method == "POST" and request.form.get("action") == "sync_deliveries":
            _sync_deliveries(db)
            db.commit()
            first_project = db.query(Project).filter(Project.is_contracted.is_(True)).order_by(Project.id.asc()).first()
            if first_project:
                append_history_log(
                    db,
                    project_id=first_project.id,
                    user_name="시스템",
                    content=f"{current_user} executed delivery sync.",
                    scope="delivery",
                    kind="system",
                )
                db.commit()
            flash("Delivery sync completed.", "success")
            return redirect(url_for("delivery.delivery_management"))

        _sync_deliveries(db)
        db.commit()

        q = (request.args.get("q") or "").strip().lower()
        status_filter = (request.args.get("status") or "all").strip()
        sort_by = (request.args.get("sort") or "due_asc").strip()

        projects = db.query(Project).filter(Project.is_contracted.is_(True)).options(
            joinedload(Project.contracts),
            joinedload(Project.deliveries).joinedload(Delivery.splits),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        today = datetime.date.today()
        filtered = []
        stats = {"total_projects": len(projects), "filtered_projects": 0, "total_deliveries": 0, "waiting": 0, "working": 0, "done": 0}

        for project in projects:
            project._matched_deliveries = []
            project._dday = None
            if project.contracts:
                due = sorted(project.contracts, key=lambda c: c.delivery_due_date or datetime.date.max)[0].delivery_due_date
                project._dday = (due - today).days if due else None

            for delivery in (project.deliveries or []):
                stats["total_deliveries"] += 1
                if delivery.delivery_status == "waiting":
                    stats["waiting"] += 1
                elif delivery.delivery_status in ("coordinating", "in_progress"):
                    stats["working"] += 1
                elif delivery.delivery_status == "done":
                    stats["done"] += 1

                hay = " ".join([
                    project.project_no or "",
                    project.temp_name or "",
                    delivery.contract.contract_name if delivery.contract else "",
                    delivery.delivery_status or "",
                ]).lower()
                if q and q not in hay:
                    continue
                if status_filter != "all" and delivery.delivery_status != status_filter:
                    continue

                delivery._latest_split = sorted(delivery.splits or [], key=lambda s: s.split_no or 0)[-1] if (delivery.splits or []) else None
                project._matched_deliveries.append(delivery)

            if project._matched_deliveries:
                filtered.append(project)

        stats["filtered_projects"] = len(filtered)

        if sort_by == "due_desc":
            filtered.sort(key=lambda p: (p._dday is None, -(p._dday if p._dday is not None else -99999)))
        elif sort_by == "created_desc":
            filtered.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
        else:
            filtered.sort(key=lambda p: (p._dday is None, p._dday if p._dday is not None else 99999))

        priority_projects = []
        for project in filtered:
            reasons = []
            override = append_manual_priority_reason(reasons, project)
            unassigned_count = 0
            today_split_count = 0
            working_count = 0
            is_urgent_project = bool(project.is_urgent or any((d.contract and d.contract.is_urgent_prod) for d in (project._matched_deliveries or [])))

            for delivery in (project._matched_deliveries or []):
                if not (delivery.contact_name or '').strip():
                    unassigned_count += 1
                if delivery.delivery_status != 'done':
                    working_count += 1
                for split in (delivery.splits or []):
                    base_date = split.confirmed_date or split.scheduled_date
                    if base_date == today:
                        today_split_count += 1

            if is_urgent_project:
                append_priority_reason(reasons, 'urgent')
            append_due_priority_reason(reasons, project._dday, 'delivery')
            if unassigned_count > 0:
                append_priority_reason(reasons, 'delivery_unassigned', f"미배정 {unassigned_count}건")
            if today_split_count > 0:
                append_priority_reason(reasons, 'delivery_today', f"금일회차 {today_split_count}건")

            if reasons:
                meta_lines = [
                    f"조회 납품건: {len(project._matched_deliveries or [])}건",
                    f"담당자 미배정: {unassigned_count}건",
                    f"금일 회차: {today_split_count}건",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=project.id,
                    project_no=project.project_no,
                    title=project.temp_name or '-',
                    subtitle=f"진행중 납품건: {working_count}건",
                    detail_url=url_for('delivery.delivery_detail', project_id=project.id),
                    reasons=reasons,
                    dday=project._dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)

        return render_template(
            "delivery_management.html",
            projects=filtered,
            priority_projects=priority_projects,
            stats=stats,
            filters={"q": request.args.get("q", ""), "status": status_filter, "sort": sort_by},
            status_labels=STATUS_LABELS,
            status_badge=_status_badge,
        )
    finally:
        db.close()


@delivery_bp.route("/delivery_management/<int:project_id>", methods=["GET", "POST"])
def delivery_detail(project_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = SessionLocal()
    try:
        project = db.query(Project).options(
            joinedload(Project.contacts),
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.deliveries).joinedload(Delivery.splits),
            joinedload(Project.deliveries).joinedload(Delivery.photos),
        ).get(project_id)
        if not project:
            flash("Project not found.", "warning")
            return redirect(url_for("delivery.delivery_management"))

        current_user = session.get("full_name") or "User"
        if request.method == "POST":
            action = request.form.get("action")

            if action == "sync_deliveries":
                _sync_deliveries(db, project_id=project_id)
                append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} executed delivery sync.", scope="delivery", kind="system")
                db.commit()
                flash("Delivery sync completed.", "success")

            elif action == "add_split":
                delivery_id = _to_int(request.form.get("delivery_id"))
                delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project_id).first()
                if delivery:
                    split = DeliverySplit(
                        delivery_id=delivery.id,
                        split_no=_to_int(request.form.get("split_no"), 1),
                        quantity=_to_int(request.form.get("quantity"), 0),
                        scheduled_date=_parse_date(request.form.get("scheduled_date")),
                        confirmed_date=_parse_date(request.form.get("confirmed_date")),
                        status=(request.form.get("status") or "waiting"),
                        note=(request.form.get("note") or "").strip() or None,
                    )
                    db.add(split)
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} added split #{split.split_no} qty {split.quantity}.", scope="delivery", kind="system")
                    db.commit()
                    flash("Split added.", "success")

            elif action == "update_split":
                split_id = _to_int(request.form.get("split_id"))
                split = db.query(DeliverySplit).join(Delivery).filter(DeliverySplit.id == split_id, Delivery.project_id == project_id).first()
                if split:
                    split.split_no = _to_int(request.form.get("split_no"), split.split_no)
                    split.quantity = _to_int(request.form.get("quantity"), split.quantity)
                    split.scheduled_date = _parse_date(request.form.get("scheduled_date"))
                    split.confirmed_date = _parse_date(request.form.get("confirmed_date"))
                    split.loading_done_at = _parse_datetime_local(request.form.get("loading_done_at"))
                    split.delivered_done_at = _parse_datetime_local(request.form.get("delivered_done_at"))
                    split.status = request.form.get("status") or split.status or "waiting"
                    split.note = (request.form.get("note") or "").strip() or None
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} updated split #{split.split_no} status {split.status}.", scope="delivery", kind="system")
                    db.commit()
                    flash("Split updated.", "success")

            elif action == "delete_split":
                split_id = _to_int(request.form.get("split_id"))
                split = db.query(DeliverySplit).join(Delivery).filter(DeliverySplit.id == split_id, Delivery.project_id == project_id).first()
                if split:
                    split_no = split.split_no
                    db.delete(split)
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} deleted split #{split_no}.", scope="delivery", kind="system")
                    db.commit()
                    flash("Split deleted.", "success")

            elif action == "assign_delivery_owner":
                if not _can_assign_owner():
                    flash("No permission to assign owner.", "warning")
                    return redirect(url_for("delivery.delivery_detail", project_id=project_id))
                delivery_id = _to_int(request.form.get("delivery_id"))
                owner_user_id = _to_int(request.form.get("owner_user_id"))
                delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project_id).first()
                owner = db.query(User).get(owner_user_id) if owner_user_id else None
                if delivery and owner:
                    delivery.contact_name = owner.full_name
                    delivery.contact_phone = owner.phone_number
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} assigned owner {owner.full_name}.", scope="delivery", kind="system")
                    db.commit()
                    flash("Owner assigned.", "success")

            elif action == "assign_me":
                delivery_id = _to_int(request.form.get("delivery_id"))
                delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project_id).first()
                if delivery:
                    delivery.contact_name = current_user
                    db_user = db.query(User).get(session.get("user_id")) if session.get("user_id") else None
                    delivery.contact_phone = db_user.phone_number if db_user else delivery.contact_phone
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} assigned self as owner.", scope="delivery", kind="system")
                    db.commit()
                    flash("Assigned to you.", "success")

            elif action == "add_photo":
                if not is_storage_enabled():
                    flash("Storage is not configured.", "danger")
                    return redirect(url_for("delivery.delivery_detail", project_id=project_id))
                delivery_id = _to_int(request.form.get("delivery_id"))
                split_id = _to_int(request.form.get("split_id"), 0) or None
                contract_item_id = _to_int(request.form.get("contract_item_id"), 0) or None
                photo_type = _normalize_photo_type(request.form.get("photo_type") or "etc")
                file = request.files.get("photo_file")
                delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project_id).first()
                if delivery and file and file.filename:
                    safe_name = secure_filename(file.filename) or f"photo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    ext = os.path.splitext(safe_name)[1].lower() or ".jpg"
                    stored_name = f"item{contract_item_id or 0}_{safe_name}"
                    object_path = (
                        f"storage/deliveries/project_{project_id}/delivery_{delivery_id}/"
                        f"contract_{delivery.contract_id or 0}/item_{contract_item_id or 0}/split_{split_id or 0}/photos/"
                        f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
                    )
                    content = file.read()
                    ok, err = upload_bytes(object_path, content, content_type=(file.mimetype or "application/octet-stream"), upsert=True)
                    if not ok:
                        flash(f"Photo upload failed: {err}", "danger")
                        return redirect(url_for("delivery.delivery_detail", project_id=project_id))
                    db.add(DeliveryPhoto(delivery_id=delivery_id, split_id=split_id, photo_type=photo_type, file_name=stored_name, storage_path=object_path, uploaded_by=current_user))
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} uploaded photo {stored_name} ({photo_type}).", scope="delivery", kind="system")
                    db.commit()
                    flash("Photo uploaded.", "success")

            elif action == "delete_photo":
                photo_id = _to_int(request.form.get("photo_id"))
                photo = db.query(DeliveryPhoto).join(Delivery).filter(DeliveryPhoto.id == photo_id, Delivery.project_id == project_id).first()
                if photo:
                    file_name = photo.file_name
                    delete_object(photo.storage_path)
                    db.delete(photo)
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} deleted photo {file_name}.", scope="delivery", kind="system")
                    db.commit()
                    flash("Photo deleted.", "success")

            elif action == "add_contact":
                name = (request.form.get("name") or "").strip()
                category = (request.form.get("contact_category") or "").strip()
                phone = (request.form.get("phone") or "").strip()
                email = (request.form.get("email") or "").strip()
                if not name:
                    flash("Name is required.", "warning")
                else:
                    db.add(Contact(project_id=project_id, category=category, name=name, phone=phone, email=email))
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} added contact {name} ({category or '-'})", scope="delivery", kind="system")
                    db.commit()
                    flash("Contact added.", "success")

            elif action == "update_contact":
                contact_id = _to_int(request.form.get("contact_id"))
                con = db.query(Contact).filter(Contact.id == contact_id, Contact.project_id == project_id).first()
                if con:
                    old = f"{con.category or '-'} / {con.name or '-'} / {con.phone or '-'} / {con.email or '-'}"
                    con.category = (request.form.get("contact_category") or "").strip()
                    con.name = (request.form.get("name") or "").strip()
                    con.phone = (request.form.get("phone") or "").strip()
                    con.email = (request.form.get("email") or "").strip()
                    new = f"{con.category or '-'} / {con.name or '-'} / {con.phone or '-'} / {con.email or '-'}"
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} updated contact. Before: {old} | After: {new}", scope="delivery", kind="system")
                    db.commit()
                    flash("Contact updated.", "success")

            elif action == "delete_contact":
                contact_id = _to_int(request.form.get("contact_id"))
                con = db.query(Contact).filter(Contact.id == contact_id, Contact.project_id == project_id).first()
                if con:
                    con_name = con.name
                    db.delete(con)
                    append_history_log(db, project_id=project_id, user_name="System", content=f"{current_user} deleted contact {con_name}.", scope="delivery", kind="system")
                    db.commit()
                    flash("Contact deleted.", "success")

            elif action == "add_chat":
                msg = (request.form.get("chat_message") or "").strip()
                if msg:
                    append_history_log(db, project_id=project_id, user_name=current_user, content=msg, scope="delivery", kind="comment")
                    db.commit()

            elif action == "add_history_reply":
                parent_id_raw = request.form.get("parent_log_id")
                reply_message = (request.form.get("reply_message") or "").strip()
                if parent_id_raw and reply_message:
                    parent = db.query(HistoryLog).get(int(parent_id_raw))
                    if parent and parent.project_id == project_id:
                        origin_full = (parent.content or "").strip()
                        origin_snapshot = origin_full[:220] + "..." if len(origin_full) > 220 else origin_full
                        append_history_log(
                            db,
                            project_id=project_id,
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
                            project_id=project_id,
                            user_name=current_user,
                            content="[reply]\nReply:\n" + reply_message + "\n---Original---\n" + origin_full,
                            scope="common",
                            kind="comment",
                        )
                        db.commit()

            return redirect(url_for("delivery.delivery_detail", project_id=project_id))

        _sync_deliveries(db, project_id=project_id)
        db.commit()

        users = db.query(User).filter(User.is_approved.is_(True), User.is_active.is_(True)).order_by(User.full_name.asc()).all()
        today = datetime.date.today()
        for delivery in (project.deliveries or []):
            delivery._latest_split = sorted(delivery.splits or [], key=lambda s: s.split_no or 0)[-1] if (delivery.splits or []) else None
            delivery._today_split_count = 0
            delivery._overdue_split_count = 0
            delivery._photo_counts = {
                "production_done": 0,
                "loading": 0,
                "delivery_done": 0,
                "etc": 0,
            }
            delivery._progress_percent = round(
                ((delivery.delivered_total_qty or 0) / (delivery.planned_total_qty or 1) * 100), 1
            ) if (delivery.planned_total_qty or 0) > 0 else 0

            for split in (delivery.splits or []):
                base_date = split.confirmed_date or split.scheduled_date
                split_status = (split.status or "").strip()
                if base_date == today:
                    delivery._today_split_count += 1
                if base_date and base_date < today and split_status not in ("done", "완료"):
                    delivery._overdue_split_count += 1

            for photo in (delivery.photos or []):
                normalized_type = _normalize_photo_type(photo.photo_type)
                delivery._photo_counts[normalized_type] = delivery._photo_counts.get(normalized_type, 0) + 1
                photo._photo_type_label = PHOTO_TYPE_LABELS.get(normalized_type, photo.photo_type)

            delivery._needs_done_photo = bool(
                (delivery.planned_total_qty or 0) > 0
                and (delivery.delivered_total_qty or 0) >= (delivery.planned_total_qty or 0)
                and delivery._photo_counts.get("delivery_done", 0) == 0
            )
            delivery._is_unassigned = not bool((delivery.contact_name or "").strip())

        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope="delivery",
            limit=300,
        )

        return render_template(
            "delivery_detail.html",
            project=project,
            users=users,
            can_assign_owner=_can_assign_owner(),
            status_labels=STATUS_LABELS,
            status_badge=_status_badge,
            photo_type_labels=PHOTO_TYPE_LABELS,
            photo_type_options=PHOTO_TYPE_OPTIONS,
            history=history,
            history_counts=history_counts,
            today=today,
        )
    finally:
        db.close()


@delivery_bp.route("/delivery/photo/<int:photo_id>/view")
def view_delivery_photo(photo_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = SessionLocal()
    try:
        photo = db.query(DeliveryPhoto).get(photo_id)
        if not photo:
            abort(404)
        data = download_bytes(photo.storage_path)
        if data is None:
            abort(404)
        ext = os.path.splitext(photo.file_name or "")[1].lower()
        mimetype = "image/jpeg"
        if ext == ".png":
            mimetype = "image/png"
        elif ext == ".webp":
            mimetype = "image/webp"
        return send_file(io.BytesIO(data), mimetype=mimetype)
    finally:
        db.close()
