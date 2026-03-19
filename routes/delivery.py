import datetime
import io
import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, send_file
from modules.auth_decorators import login_required
from sqlalchemy.orm import joinedload
from modules.utils import safe_int
from modules.pagination import make_pagination

from modules.history_board import append_history_log, get_project_history_context
from modules.db_context import get_db
from modules.models import Project, Contract, User, Delivery, DeliveryPhoto
from modules.storage_adapter import download_bytes
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)
from modules.services.delivery_actions import (
    sync_deliveries,
    normalize_photo_type,
    handle_sync_deliveries,
    handle_add_split,
    handle_update_split,
    handle_delete_split,
    handle_assign_delivery_owner,
    handle_assign_me,
    handle_add_photo,
    handle_delete_photo,
    handle_add_contact,
    handle_update_contact,
    handle_delete_contact,
    handle_add_chat,
    handle_add_history_reply,
    handle_update_inspection,
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


def _can_assign_owner():
    return bool(
        session.get("role") == "admin"
        or session.get("can_approve_delete")
        or (session.get("user_group") or "").strip() in ("영업부서장", "관리부서장", "생산부서장", "부서장")
    )


def _status_badge(status):
    return {
        "done": "success",
        "in_progress": "warning",
        "coordinating": "info",
    }.get(status, "secondary")


ACTION_HANDLERS = {
    'sync_deliveries': handle_sync_deliveries,
    'add_split': handle_add_split,
    'update_split': handle_update_split,
    'delete_split': handle_delete_split,
    'assign_delivery_owner': handle_assign_delivery_owner,
    'assign_me': handle_assign_me,
    'add_photo': handle_add_photo,
    'delete_photo': handle_delete_photo,
    'add_contact': handle_add_contact,
    'update_contact': handle_update_contact,
    'delete_contact': handle_delete_contact,
    'add_chat': handle_add_chat,
    'add_history_reply': handle_add_history_reply,
    'update_inspection': handle_update_inspection,
}


@delivery_bp.route("/delivery_management", methods=["GET", "POST"])
@login_required
def delivery_management():

    with get_db() as db:
        current_user = session.get("full_name") or "사용자"
        if request.method == "POST" and request.form.get("action") == "sync_deliveries":
            sync_deliveries(db)
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

        sync_deliveries(db)
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

        page = safe_int(request.args.get('page'), 1)
        per_page = safe_int(request.args.get('per_page'), 20)
        pagination = make_pagination(page, per_page, len(filtered))
        start = (pagination['page'] - 1) * per_page
        projects_page = filtered[start:start + per_page]

        return render_template(
            "delivery_management.html",
            projects=projects_page,
            priority_projects=priority_projects,
            stats=stats,
            pagination=pagination,
            filters={"q": request.args.get("q", ""), "status": status_filter, "sort": sort_by},
            status_labels=STATUS_LABELS,
            status_badge=_status_badge,
        )

@delivery_bp.route("/delivery_management/<int:project_id>", methods=["GET", "POST"])
@login_required
def delivery_detail(project_id):

    with get_db() as db:
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
            handler = ACTION_HANDLERS.get(action)
            if handler:
                ctx = {
                    'user_id': session.get('user_id'),
                    'files': request.files,
                    'can_assign_owner': _can_assign_owner(),
                }
                result = handler(db, project, request.form, current_user, **ctx)

                db.commit()

                if result.get('flash'):
                    flash(*result['flash'])
                for f in result.get('flashes', []):
                    flash(*f)

            return redirect(url_for("delivery.delivery_detail", project_id=project_id))

        sync_deliveries(db, project_id=project_id)
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
                normalized_type = normalize_photo_type(photo.photo_type)
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

@delivery_bp.route("/delivery/photo/<int:photo_id>/view")
@login_required
def view_delivery_photo(photo_id):

    with get_db() as db:
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
