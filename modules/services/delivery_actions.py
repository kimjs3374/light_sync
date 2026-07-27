import datetime
import os

from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload

from modules.utils import validate_upload, safe_int, parse_date
from modules.notification_engine import notify
from modules.models import (
    Project,
    Contract,
    ContractItem,
    Contact,
    User,
    Delivery,
    DeliverySplit,
    DeliverySplitItem,
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


def sync_deliveries(db, project_id=None, project_ids=None):
    """계약품목 수량 기준으로 납품 계획/실적을 재계산한다.

    project_id  : 현장 1건만
    project_ids : 현장 여러 건 (목록 화면이 실제로 표시할 현장만 넘긴다).
                  빈 리스트를 넘기면 아무것도 하지 않는다 — 전체 동기화로 새지 않도록
                  None(=전체) 과 반드시 구분해서 처리한다.
    둘 다 없으면 계약된 전 현장 (수동 동기화 버튼 / 배치용).
    """
    if project_ids is not None and not project_ids:
        return
    q = db.query(Project).filter(Project.is_contracted.is_(True)).options(
        joinedload(Project.contacts),
        joinedload(Project.contracts).joinedload(Contract.items),
        joinedload(Project.deliveries).joinedload(Delivery.splits),
        joinedload(Project.deliveries).joinedload(Delivery.photos),
    )
    if project_id:
        q = q.filter(Project.id == project_id)
    elif project_ids is not None:
        q = q.filter(Project.id.in_(project_ids))

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
            # split.quantity = 회차 총수량 (split_items 합계 또는 레거시 직접입력)
            delivered_total = sum(safe_int(split.quantity, 0) for split in (delivery.splits or []) if (split.status or "") in SPLIT_STATUS_DONE_VALUES)
            delivery.planned_total_qty = planned_total
            delivery.delivered_total_qty = delivered_total

            has_confirmed_split = any(split.confirmed_date for split in (delivery.splits or []))
            has_loading_done = any(split.loading_done_at for split in (delivery.splits or []))
            has_today_split = any((split.confirmed_date == today or split.scheduled_date == today) for split in (delivery.splits or []))
            is_completed = bool(planned_total > 0 and delivered_total >= planned_total)

            if is_completed:
                old_status = delivery.delivery_status
                delivery.delivery_status = "done"
                if old_status != "done":
                    _proj_name = project.temp_name or project.short_name or f'현장#{project.id}'
                    _c_name = contract.contract_name or _proj_name
                    notify(db, 'delivery.completed', {
                        'contract_name': _c_name,
                        'project_name': _proj_name,
                        'project_id': project.id,
                        'detail': f'{_c_name} 전체 납품 완료',
                    })
            elif has_loading_done or has_today_split:
                delivery.delivery_status = "in_progress"
            elif has_confirmed_split:
                delivery.delivery_status = "coordinating"
            else:
                delivery.delivery_status = "waiting"

        # 모든 delivery가 done이면 project.status → 납품완료
        all_deliveries = [d for d in (project.deliveries or []) if d.contract_id]
        if all_deliveries and all(d.delivery_status == "done" for d in all_deliveries):
            if project.status != "납품완료":
                project.status = "납품완료"
        elif project.status == "납품완료" and all_deliveries:
            # 완료로 올리기만 하고 되돌리지 않아, 변경계약으로 물량이 늘어도
            # 현장은 납품완료로 남아 있었다(소제지구: 계획 375/완료 192인데 납품완료).
            #
            # 단 회차를 한 번도 등록한 적 없는 현장은 건드리지 않는다. 과거 완료건
            # 1,200여건이 G2B 동기화로만 생성돼 delivery_status='waiting' 인데,
            # 이걸 되돌리면 완료된 현장이 전부 진행중으로 뒤집힌다.
            if any(d.splits for d in all_deliveries):
                project.status = "계약"


# --- Action Handlers ---

def handle_sync_deliveries(db, project, form, current_user, **ctx):
    sync_deliveries(db, project_id=project.id)
    append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 납품 동기화 실행", scope="delivery", kind="system")
    return {'flash': ('납품 동기화 완료', 'success')}


def _parse_split_item_qtys(form):
    """폼에서 item_qty_{contract_item_id} 필드 파싱 → [(contract_item_id, qty), ...]"""
    items = []
    for key in form:
        if key.startswith("item_qty_"):
            cid = safe_int(key.replace("item_qty_", ""), 0)
            qty = safe_int(form.get(key), 0)
            if cid and qty > 0:
                items.append((cid, qty))
    return items


def _save_split_items(db, split, item_qtys):
    """split_items upsert — 기존 삭제 후 재생성"""
    db.query(DeliverySplitItem).filter(DeliverySplitItem.split_id == split.id).delete()
    total = 0
    for cid, qty in item_qtys:
        db.add(DeliverySplitItem(split_id=split.id, contract_item_id=cid, quantity=qty))
        total += qty
    split.quantity = total


def _build_item_names(db, item_qtys):
    """[(cid, qty), ...] → '조명기구 MT-FL100 30EA, 타워 MT-TW01 5EA'"""
    parts = []
    for cid, qty in item_qtys:
        ci = db.query(ContractItem).get(cid)
        if ci:
            parts.append(f"{ci.category} {ci.model_name or ''} {qty}EA".strip())
    return ", ".join(parts) if parts else ""


def handle_add_split(db, project, form, current_user, **ctx):
    delivery_id = safe_int(form.get("delivery_id"))
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project.id).first()
    if delivery:
        item_qtys = _parse_split_item_qtys(form)
        total_qty = sum(q for _, q in item_qtys) or safe_int(form.get("quantity"), 0)

        split = DeliverySplit(
            delivery_id=delivery.id,
            split_no=safe_int(form.get("split_no"), 1),
            quantity=total_qty,
            scheduled_date=parse_date(form.get("scheduled_date")),
            confirmed_date=parse_date(form.get("confirmed_date")),
            status=(form.get("status") or "waiting"),
            note=(form.get("note") or "").strip() or None,
        )
        db.add(split)
        db.flush()

        if item_qtys:
            _save_split_items(db, split, item_qtys)

        item_names = _build_item_names(db, item_qtys) if item_qtys else ""
        append_history_log(
            db, project_id=project.id, user_name="시스템",
            content=f"{current_user} {split.split_no}차 납품회차 등록 (총 {split.quantity}EA) {item_names}".strip(),
            scope="delivery", kind="system",
        )

        # 알림 엔진: ERP 내부 + 카카오워크 동시 발송
        project_name = project.temp_name or project.short_name or f"현장#{project.id}"
        sched_str = split.scheduled_date.strftime('%Y-%m-%d') if split.scheduled_date else '-'
        detail_url = f"https://work.mgnt.kr/delivery_management/{project.id}"
        kakao_text = (
            f"[납품일정등록]\n"
            f"{project_name}\n"
            f"\n"
            f"{('모델: ' + item_names + chr(10)) if item_names else ''}"
            f"차수: {split.split_no}차  총수량: {split.quantity}EA\n"
            f"납품예정일: {sched_str}\n"
            f"등록자: {current_user}\n"
            f"\n"
            f"{detail_url}"
        )
        # 계약명 조회
        from modules.models import Contract as _C
        _first_c = db.query(_C).filter(_C.project_id == project.id).first()
        _contract_name = _first_c.contract_name if _first_c and _first_c.contract_name else project_name
        notify(db, 'delivery.scheduled', {
            'contract_name': _contract_name,
            'project_name': project_name,
            'project_id': project.id,
            'detail': f"{split.split_no}차 {split.quantity}EA · {sched_str} 예정 · {current_user}",
            'delivery_date': sched_str,
            'manager_name': current_user,
        }, kakao_text_override=kakao_text)

        return {'flash': ('회차가 추가되었습니다.', 'success')}
    return {}


def handle_update_split(db, project, form, current_user, **ctx):
    split_id = safe_int(form.get("split_id"))
    split = db.query(DeliverySplit).join(Delivery).filter(DeliverySplit.id == split_id, Delivery.project_id == project.id).first()
    if split:
        item_qtys = _parse_split_item_qtys(form)

        split.split_no = safe_int(form.get("split_no"), split.split_no)
        split.scheduled_date = parse_date(form.get("scheduled_date"))
        split.confirmed_date = parse_date(form.get("confirmed_date"))
        split.loading_done_at = _parse_datetime_local(form.get("loading_done_at"))
        split.delivered_done_at = _parse_datetime_local(form.get("delivered_done_at"))
        split.status = form.get("status") or split.status or "waiting"
        split.note = (form.get("note") or "").strip() or None

        if item_qtys:
            _save_split_items(db, split, item_qtys)
        else:
            split.quantity = safe_int(form.get("quantity"), split.quantity)

        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} {split.split_no}차 회차 수정 (상태: {split.status})", scope="delivery", kind="system")
        return {'flash': ('회차가 수정되었습니다.', 'success')}
    return {}


def handle_delete_split(db, project, form, current_user, **ctx):
    split_id = safe_int(form.get("split_id"))
    split = db.query(DeliverySplit).join(Delivery).filter(DeliverySplit.id == split_id, Delivery.project_id == project.id).first()
    if split:
        split_no = split.split_no
        db.delete(split)
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} {split_no}차 회차 삭제", scope="delivery", kind="system")
        return {'flash': ('회차가 삭제되었습니다.', 'success')}
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
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 납품담당자 지정 → {owner.full_name}", scope="delivery", kind="system")
        return {'flash': ('담당자가 지정되었습니다.', 'success')}
    return {}


def handle_assign_me(db, project, form, current_user, **ctx):
    delivery_id = safe_int(form.get("delivery_id"))
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.project_id == project.id).first()
    if delivery:
        delivery.contact_name = current_user
        user_id = ctx.get('user_id')
        db_user = db.query(User).get(user_id) if user_id else None
        delivery.contact_phone = db_user.phone_number if db_user else delivery.contact_phone
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 본인 담당 배정", scope="delivery", kind="system")
        return {'flash': ('본인 담당으로 배정되었습니다.', 'success')}
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
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 사진 업로드 {stored_name} ({photo_type})", scope="delivery", kind="system")
        return {'flash': ('사진이 업로드되었습니다.', 'success')}
    return {}


def handle_delete_photo(db, project, form, current_user, **ctx):
    photo_id = safe_int(form.get("photo_id"))
    photo = db.query(DeliveryPhoto).join(Delivery).filter(DeliveryPhoto.id == photo_id, Delivery.project_id == project.id).first()
    if photo:
        file_name = photo.file_name
        delete_object(photo.storage_path)
        db.delete(photo)
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 사진 삭제 {file_name}", scope="delivery", kind="system")
        return {'flash': ('사진이 삭제되었습니다.', 'success')}
    return {}


def handle_add_contact(db, project, form, current_user, **ctx):
    name = (form.get("name") or "").strip()
    category = (form.get("contact_category") or "").strip()
    phone = (form.get("phone") or "").strip()
    email = (form.get("email") or "").strip()
    if not name:
        return {'flash': ('Name is required.', 'warning')}
    db.add(Contact(project_id=project.id, category=category, name=name, phone=phone, email=email))
    append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 연락처 추가 {name} ({category or '-'})", scope="delivery", kind="system")
    return {'flash': ('연락처가 추가되었습니다.', 'success')}


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
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 연락처 수정. 이전: {old} | 변경: {new}", scope="delivery", kind="system")
        return {'flash': ('연락처가 수정되었습니다.', 'success')}
    return {}


def handle_delete_contact(db, project, form, current_user, **ctx):
    contact_id = safe_int(form.get("contact_id"))
    con = db.query(Contact).filter(Contact.id == contact_id, Contact.project_id == project.id).first()
    if con:
        con_name = con.name
        db.delete(con)
        append_history_log(db, project_id=project.id, user_name="시스템", content=f"{current_user} 연락처 삭제 {con_name}", scope="delivery", kind="system")
        return {'flash': ('연락처가 삭제되었습니다.', 'success')}
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
