"""Mattermost Interactive Action endpoint.

봇 메시지의 attachment action(버튼) 클릭 시 Mattermost가 호출.
- POST /mattermost/action
- payload: {user_id, user_name, channel_id, post_id, team_id, context: {action_type, data}}
- action_type 별로 분기 (register_delivery_announcement, cancel ...)

응답 포맷 (Mattermost 메시지 update):
    {"update": {"message": "...", "props": {...}}}

보안: 봇이 보낸 메시지의 actions이므로 별도 토큰 검증은 하지 않지만,
응답 메시지에 user_name을 명시해 누가 눌렀는지 추적 가능.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict

import requests
from flask import Blueprint, jsonify, request

from modules.db_context import get_db
from modules.models import Project, Delivery, DeliverySplit, User
from modules.services.delivery_actions import handle_add_split, sync_deliveries

mattermost_action_bp = Blueprint("mattermost_action_bp", __name__)
logger = logging.getLogger(__name__)

MM_BASE_URL = os.environ.get("MM_BASE_URL", "https://team.mgnt.kr")
MM_BOT_TOKEN = os.environ.get("MM_BOT_TOKEN", "")


def _mm_update_post(post_id: str, message: str, props: Dict[str, Any] | None = None) -> None:
    """Mattermost 메시지 업데이트 (성공/실패 알림 표시용)"""
    if not MM_BOT_TOKEN or not post_id:
        return
    try:
        body: Dict[str, Any] = {"id": post_id, "message": message}
        if props is not None:
            body["props"] = props
        r = requests.put(
            f"{MM_BASE_URL}/api/v4/posts/{post_id}",
            json=body,
            headers={"Authorization": f"Bearer {MM_BOT_TOKEN}"},
            timeout=5.0,
        )
        if r.status_code >= 400:
            logger.warning("[mm-action] update_post %s → %d %s", post_id, r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("[mm-action] update_post 실패: %s", e)


def _resolve_erp_user(session, mm_user_name: str) -> User | None:
    """Mattermost username → ERP User 매칭. username 우선, email 보조."""
    if not mm_user_name:
        return None
    user = (
        session.query(User)
        .filter(User.username == mm_user_name)
        .first()
    )
    if user:
        return user
    # email local-part 매칭 (예: mm=ai, erp email=ai@mgnt.kr)
    user = (
        session.query(User)
        .filter(User.email.ilike(f"{mm_user_name}@%"))
        .first()
    )
    return user


def _action_register_delivery(payload: Dict[str, Any], mm_user_name: str) -> Dict[str, Any]:
    """납품공지 등록 액션 — handle_add_split 호출.

    Mattermost user_name을 ERP User로 매칭 후 진행. 매칭 실패 시 등록 거부.
    """
    project_id = payload.get("project_id")
    scheduled_date = payload.get("scheduled_date")
    items = payload.get("items") or []
    contact_name = payload.get("contact_name") or ""
    contact_phone = payload.get("contact_phone") or ""
    note = payload.get("note") or ""

    if not project_id or not scheduled_date or not items:
        return {"ok": False, "msg": "필수 데이터 누락 (project_id/scheduled_date/items)"}

    with get_db() as session:
        # 1) ERP user 매칭 — 매칭 실패 시 등록 거부 (감사 추적 보장)
        erp_user = _resolve_erp_user(session, mm_user_name)
        if not erp_user:
            return {
                "ok": False,
                "msg": (
                    f"ERP 사용자 매칭 실패: Mattermost '{mm_user_name}' 와 일치하는 ERP 계정이 없습니다.\n"
                    f"본인 username으로 ERP에 로그인한 적이 있는지 확인해주세요."
                ),
            }
        actor_display = f"{erp_user.full_name or erp_user.username}"
        if erp_user.position:
            actor_display += f" {erp_user.position}"

        # 2) 현장 조회
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"ok": False, "msg": f"현장 id={project_id} 없음"}

        # 3) Delivery row 보장
        delivery = session.query(Delivery).filter(Delivery.project_id == project.id).first()
        if not delivery:
            delivery = Delivery(project_id=project.id, delivery_status="진행중")
            session.add(delivery)
            session.flush()

        # 4) 다음 split_no 자동 산정
        last_split = (
            session.query(DeliverySplit)
            .filter(DeliverySplit.delivery_id == delivery.id)
            .order_by(DeliverySplit.split_no.desc())
            .first()
        )
        next_no = (last_split.split_no + 1) if last_split else 1

        # 5) form dict 구성 (handle_add_split 시그니처 호환)
        total_qty = sum(int(it.get("qty") or 0) for it in items)
        contact_suffix = (
            f" / 연락처: {contact_name} {contact_phone}" if contact_name or contact_phone else ""
        )
        form: Dict[str, Any] = {
            "delivery_id": str(delivery.id),
            "split_no": str(next_no),
            "quantity": str(total_qty),
            "scheduled_date": scheduled_date,
            "confirmed_date": "",
            "status": "예정",
            "note": (note + contact_suffix + f" / 등록경로: Mattermost(@{mm_user_name})").strip(" /"),
        }
        for it in items:
            ci_id = it.get("contract_item_id")
            qty = it.get("qty") or 0
            if ci_id:
                form[f"item_qty_{ci_id}"] = str(qty)

        try:
            result = handle_add_split(session, project, form, current_user=actor_display)
            session.commit()
            msg = "등록 완료"
            if result and isinstance(result, dict) and result.get("flash"):
                msg = result["flash"][0]
            return {
                "ok": True,
                "msg": msg,
                "split_no": next_no,
                "total_qty": total_qty,
                "actor": actor_display,
            }
        except Exception as e:
            session.rollback()
            logger.exception("[mm-action] register_delivery 실패: %s", e)
            return {"ok": False, "msg": f"등록 실패: {e}"}


def _action_complete_delivery(payload: Dict[str, Any], mm_user_name: str) -> Dict[str, Any]:
    """납품완료 처리 액션 — split.status="완료" + delivered_done_at + sync_deliveries.

    Args (payload):
        project_id: int
        split_ids: list[int] — 완료 처리할 split id 리스트
        completed_date: str (YYYY-MM-DD)
        note: str
    """
    from modules.history_board import append_history_log
    from datetime import datetime as _dt, date as _date

    project_id = payload.get("project_id")
    split_ids = payload.get("split_ids") or []
    completed_date = payload.get("completed_date") or _date.today().isoformat()
    note = payload.get("note") or ""

    if not project_id or not split_ids:
        return {"ok": False, "msg": "필수 데이터 누락 (project_id/split_ids)"}

    with get_db() as session:
        erp_user = _resolve_erp_user(session, mm_user_name)
        if not erp_user:
            return {
                "ok": False,
                "msg": (
                    f"ERP 사용자 매칭 실패: Mattermost '{mm_user_name}' 와 일치하는 ERP 계정 없음."
                ),
            }
        actor_display = erp_user.full_name or erp_user.username
        if erp_user.position:
            actor_display += f" {erp_user.position}"

        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"ok": False, "msg": f"현장 id={project_id} 없음"}

        try:
            cd = _dt.fromisoformat(completed_date)
        except Exception:
            return {"ok": False, "msg": f"완료일 포맷 오류: {completed_date}"}

        completed_split_nos = []
        completed_total_qty = 0
        for sid in split_ids:
            split = (
                session.query(DeliverySplit)
                .join(Delivery)
                .filter(DeliverySplit.id == sid, Delivery.project_id == project.id)
                .first()
            )
            if not split:
                continue
            if (split.status or "") in ("done", "완료"):
                continue  # 이미 완료
            split.status = "완료"
            # delivered_done_at = 완료일 00:00 (시간 정보 없으면)
            split.delivered_done_at = _dt(cd.year, cd.month, cd.day)
            if not split.confirmed_date:
                split.confirmed_date = cd.date()
            if note:
                split.note = ((split.note or "") + f" / 완료처리(@{mm_user_name}): {note}").strip(" /")
            completed_split_nos.append(split.split_no)
            completed_total_qty += int(split.quantity or 0)

        if not completed_split_nos:
            return {"ok": False, "msg": "완료 처리된 회차 없음 (이미 완료되었거나 매칭 실패)"}

        # history_log + sync_deliveries (delivery.delivery_status + notify('delivery.completed') 자동)
        no_str = ", ".join(f"{n}차" for n in sorted(completed_split_nos))
        append_history_log(
            session, project_id=project.id, user_name="시스템",
            content=f"{actor_display} {no_str} 납품완료 처리 (총 {completed_total_qty}EA, {completed_date}) [Mattermost@{mm_user_name}]",
            scope="delivery", kind="system",
        )
        try:
            sync_deliveries(session, project_id=project.id)
            session.commit()
            return {
                "ok": True,
                "msg": f"{no_str} 납품완료 처리됨 (총 {completed_total_qty}EA)",
                "split_nos": completed_split_nos,
                "total_qty": completed_total_qty,
                "actor": actor_display,
            }
        except Exception as e:
            session.rollback()
            logger.exception("[mm-action] complete_delivery 실패: %s", e)
            return {"ok": False, "msg": f"완료 처리 실패: {e}"}


def _action_approval(action_type: str, data: Dict[str, Any], mm_user_name: str) -> Dict[str, Any]:
    """전자결재 승인/반려 버튼 처리. 클릭자 본인검증 후 즉시 상태 전이.

    action_type: approval_approve / approval_reject
    data: {doc_id, step_id}
    """
    from modules.models import ApprovalDocument, ApprovalStep
    from modules.services import approval_service as svc
    from modules.activity import log_activity

    doc_id = data.get("doc_id")
    step_id = data.get("step_id")
    approve = action_type == "approval_approve"
    with get_db() as session:
        user = _resolve_erp_user(session, mm_user_name)
        if not user:
            return {"ok": False, "msg": "ERP 사용자 매칭 실패 — 웹에서 처리해 주세요."}
        doc = session.query(ApprovalDocument).get(doc_id) if doc_id else None
        step = session.query(ApprovalStep).get(step_id) if step_id else None
        if not doc or not step or step.document_id != doc.id:
            return {"ok": False, "msg": "결재 문서를 찾을 수 없습니다."}
        if step.approver_id != user.id:
            return {"ok": False, "msg": "본인 결재 차례가 아닙니다."}
        try:
            if approve:
                svc.approve_step(session, doc, step, None)
            else:
                svc.reject_step(session, doc, step, None)  # 반려 사유는 추후 코멘트로 입력
        except ValueError as e:
            session.rollback()
            return {"ok": False, "msg": str(e)}
        try:
            log_activity(session, 'approval', 'approve' if approve else 'reject',
                         f'[{doc.doc_no}] {doc.title} {"승인" if approve else "반려"}(카카오/MM 버튼)',
                         ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        except Exception:
            pass
        session.commit()
        return {"ok": True, "title": doc.title, "doc_no": doc.doc_no or "",
                "actor": user.full_name, "approve": approve}


@mattermost_action_bp.route("/mattermost/action", methods=["POST"])
def mattermost_action():
    """Mattermost interactive action endpoint."""
    payload = request.get_json(silent=True) or {}
    context = payload.get("context") or {}
    action_type = context.get("action_type") or ""
    data = context.get("data") or {}
    user_name = payload.get("user_name") or payload.get("user_id") or "user"
    post_id = payload.get("post_id") or ""

    logger.info("[mm-action] type=%s user=%s post=%s", action_type, user_name, post_id)

    if action_type == "register_delivery_announcement":
        result = _action_register_delivery(data, user_name)
        ts = datetime.now().strftime("%H:%M")
        if result["ok"]:
            new_msg = (
                f"✅ **납품공지 등록 완료** ({ts})\n"
                f"- {result.get('split_no')}차 / 총 {result.get('total_qty')}EA\n"
                f"- 처리자: @{user_name}"
            )
            # 원본 메시지 update (버튼 제거)
            if post_id:
                _mm_update_post(post_id, new_msg, props={})
            return jsonify({"update": {"message": new_msg, "props": {}}}), 200
        else:
            new_msg = f"❌ **납품공지 등록 실패** ({ts})\n- {result['msg']}\n- 처리자: @{user_name}"
            if post_id:
                _mm_update_post(post_id, new_msg, props={})
            return jsonify({"update": {"message": new_msg, "props": {}}}), 200

    if action_type == "complete_delivery":
        result = _action_complete_delivery(data, user_name)
        ts = datetime.now().strftime("%H:%M")
        if result["ok"]:
            no_str = ", ".join(f"{n}차" for n in sorted(result.get("split_nos") or []))
            new_msg = (
                f"✅ **납품완료 처리됨** ({ts})\n"
                f"- {no_str} / 총 {result.get('total_qty')}EA\n"
                f"- 처리자: {result.get('actor')} (@{user_name})"
            )
            if post_id:
                _mm_update_post(post_id, new_msg, props={})
            return jsonify({"update": {"message": new_msg, "props": {}}}), 200
        else:
            new_msg = f"❌ **납품완료 처리 실패** ({ts})\n- {result['msg']}\n- 처리자: @{user_name}"
            if post_id:
                _mm_update_post(post_id, new_msg, props={})
            return jsonify({"update": {"message": new_msg, "props": {}}}), 200

    if action_type in ("approval_approve", "approval_reject"):
        result = _action_approval(action_type, data, user_name)
        ts = datetime.now().strftime("%H:%M")
        if result["ok"]:
            verb = "승인" if result.get("approve") else "반려"
            icon = "✅" if result.get("approve") else "❌"
            new_msg = (
                f"{icon} **{verb} 완료** ({ts})\n"
                f"- [{result.get('doc_no')}] {result.get('title')}\n"
                f"- 처리자: {result.get('actor')} (@{user_name})"
            )
        else:
            new_msg = f"⚠️ **처리 불가** ({ts})\n- {result['msg']}\n- @{user_name}"
        # 메시지 갱신은 응답의 update로 처리(클릭한 MM 메시지). 반대 채널/타채널 갱신은
        # approval_service._finalize_step_messages가 결재봇 토큰으로 수정 → 별도 REST 호출 불필요.
        return jsonify({"update": {"message": new_msg, "props": {}}}), 200

    if action_type == "cancel":
        ts = datetime.now().strftime("%H:%M")
        new_msg = f"✗ 취소됨 ({ts}) — @{user_name}"
        if post_id:
            _mm_update_post(post_id, new_msg, props={})
        return jsonify({"update": {"message": new_msg, "props": {}}}), 200

    # ── write_ops 확인 액션들 ──────────────────────────────────
    WRITE_CONFIRM_ACTIONS = {
        "confirm_delivery_complete",
        "confirm_as_register",
        "confirm_billing_complete",
        "confirm_vehicle_log",
        "confirm_business_trip",
        "confirm_daily_report",
        "confirm_po_status",
        "confirm_production_complete",
        "confirm_production_complete_all",
        "confirm_email_send",
    }
    if action_type in WRITE_CONFIRM_ACTIONS:
        token = data.get("session_token") or ""
        result = _action_write_confirm(action_type, token, user_name)
        ts = datetime.now().strftime("%H:%M")
        if result["ok"]:
            new_msg = f"✅ **{result['label']}** ({ts})\n{result['detail']}\n처리자: @{user_name}"
        else:
            new_msg = f"❌ **처리 실패** ({ts})\n{result['msg']}\n처리자: @{user_name}"
        if post_id:
            _mm_update_post(post_id, new_msg, props={})
        return jsonify({"update": {"message": new_msg, "props": {}}}), 200

    return jsonify({"ephemeral_text": f"알 수 없는 action_type: {action_type}"}), 200


# ──────────────────────────────────────────────────────────────
# Write-confirm 공통 핸들러
# ──────────────────────────────────────────────────────────────

def _action_write_confirm(action_type: str, token: str, mm_user_name: str) -> dict:
    """PendingWriteSession 조회 후 실제 DB 기록."""
    import json as _json
    from modules.models.misc_entities import PendingWriteSession
    from modules.history_board import append_history_log

    if not token:
        return {"ok": False, "msg": "session_token 없음"}

    with get_db() as session:
        row = session.get(PendingWriteSession, token)
        if not row:
            return {"ok": False, "msg": "세션을 찾을 수 없습니다 (만료됐을 수 있음)"}
        if row.used:
            return {"ok": False, "msg": "이미 처리된 세션입니다"}
        if row.expires_at < datetime.now():
            return {"ok": False, "msg": "세션이 만료되었습니다 (30분 초과)"}
        if row.intent_type != action_type:
            return {"ok": False, "msg": f"세션 타입 불일치: {row.intent_type} ≠ {action_type}"}

        try:
            payload = _json.loads(row.payload_json)
        except Exception:
            return {"ok": False, "msg": "payload 파싱 오류"}

        # ERP 사용자 조회
        erp_user = _resolve_erp_user(session, mm_user_name)
        actor = (erp_user.full_name or mm_user_name) if erp_user else mm_user_name
        if erp_user and erp_user.position:
            actor += f" {erp_user.position}"

        try:
            if action_type == "confirm_delivery_complete":
                result = _write_delivery_complete(session, payload, actor, mm_user_name)
            elif action_type == "confirm_as_register":
                result = _write_as_register(session, payload, actor)
            elif action_type == "confirm_billing_complete":
                result = _write_billing_complete(session, payload, actor, mm_user_name)
            elif action_type == "confirm_vehicle_log":
                result = _write_vehicle_log(session, payload, erp_user)
            elif action_type == "confirm_business_trip":
                result = _write_business_trip(session, payload)
            elif action_type == "confirm_daily_report":
                result = _write_daily_report(session, payload, actor)
            elif action_type == "confirm_po_status":
                result = _write_po_status(session, payload, actor, mm_user_name)
            elif action_type == "confirm_production_complete":
                result = _write_production_complete(session, payload, actor, mm_user_name)
            elif action_type == "confirm_production_complete_all":
                result = _write_production_complete_all(session, payload, actor, mm_user_name)
            elif action_type == "confirm_email_send":
                result = _write_email_send(session, payload, actor, mm_user_name)
            else:
                return {"ok": False, "msg": f"미구현 액션: {action_type}"}

            if result["ok"]:
                row.used = True
                session.commit()
            return result
        except Exception as e:
            session.rollback()
            logger.exception("[mm-action] write_confirm %s 오류", action_type)
            return {"ok": False, "msg": f"처리 중 오류: {e}"}


def _write_delivery_complete(session, payload, actor, mm_user_name):
    from modules.services.delivery_actions import sync_deliveries
    from modules.history_board import append_history_log

    project_id = payload["project_id"]
    split_ids = payload["split_ids"]
    completed_date = payload["completed_date"]

    from datetime import datetime as _dt
    cd = _dt.fromisoformat(completed_date)
    project = session.get(Project, project_id)
    if not project:
        return {"ok": False, "msg": f"현장 id={project_id} 없음"}

    done_nos = []
    total_qty = 0
    for sid in split_ids:
        split = session.query(DeliverySplit).filter(DeliverySplit.id == sid).first()
        if not split or (split.status or "") in ("done", "완료"):
            continue
        split.status = "완료"
        split.delivered_done_at = _dt(cd.year, cd.month, cd.day)
        if not split.confirmed_date:
            split.confirmed_date = cd.date()
        done_nos.append(split.split_no)
        total_qty += int(split.quantity or 0)

    if not done_nos:
        return {"ok": False, "msg": "완료 처리할 회차 없음"}

    no_str = ", ".join(f"{n}차" for n in sorted(done_nos))
    append_history_log(session, project_id=project_id, user_name=actor,
        content=f"{no_str} 납품완료 (총 {total_qty}EA, {completed_date}) [채팅확인 @{mm_user_name}]",
        scope="delivery", kind="system", origin="chat_confirmed")
    sync_deliveries(session, project_id=project_id)
    return {"ok": True, "label": "납품완료 처리됨",
            "detail": f"- {no_str} / 총 {total_qty}EA\n- 완료일: {completed_date}"}


def _write_as_register(session, payload, actor):
    from modules.models.entities import WarrantyCase
    import datetime as _dt

    wc = WarrantyCase(
        warranty_id=payload.get("warranty_id"),
        project_id=payload["project_id"],
        case_no=payload["case_no"],
        defect_type=payload["defect_code"],
        symptom=payload["symptom"],
        status="접수",
        reported_date=_dt.date.fromisoformat(payload["received_date"]),
        created_by=actor,
        request_channel="mattermost",
        manual_site_name=payload.get("manual_site_name"),
        entity_version=1,
    )
    session.add(wc)
    session.flush()
    from modules.history_board import append_history_log
    append_history_log(session, project_id=payload["project_id"], user_name=actor,
        content=f"AS 접수 {payload['case_no']} — {payload['defect_label']}: {payload['symptom']}",
        scope="common", kind="system", origin="chat_confirmed")

    # ── ERP알림 채널 알림 (신규 이벤트 warranty.case_registered) ────────────────
    # PC/모바일/서비스 레이어 어디에도 AS 접수 알림이 없어, 채팅 등록을 통해
    # 처음으로 알림 경로를 깐다. EVENT_REGISTRY/template 양쪽에 동일 키 등록.
    try:
        from modules.notification_engine import notify
        from modules.models.entities import Project
        proj = session.get(Project, payload["project_id"])
        proj_name = (
            payload.get("manual_site_name")
            or (proj.temp_name or proj.short_name if proj else None)
            or f"현장#{payload['project_id']}"
        )
        kakao_text = (
            f"[AS접수] {proj_name}\n"
            f"접수번호: {payload['case_no']}\n"
            f"유형: {payload['defect_label']}\n"
            f"증상: {payload['symptom']}\n"
            f"접수일: {payload['received_date']}\n"
            f"접수자: {actor}"
        )
        notify(session, 'warranty.case_registered', {
            'project': proj_name,
            'project_id': payload["project_id"],
            'case_no': payload['case_no'],
            'defect_label': payload['defect_label'],
            'symptom': payload['symptom'],
            'received_date': payload['received_date'],
            'user_name': actor,
            # EVENT_REGISTRY 호환 필드
            'contract_name': proj_name,
            'detail': f"{payload['defect_label']}: {payload['symptom']}",
        }, kakao_text_override=kakao_text,
           dedupe_key=f"warranty.case_registered:{payload['case_no']}:{payload['received_date']}")
    except Exception as _exc:
        # 알림 실패해도 등록은 성공으로 유지
        try:
            logger.warning("warranty.case_registered 알림 발송 실패 (등록은 성공): %s", _exc)
        except Exception:
            pass

    return {"ok": True, "label": "AS 접수 완료",
            "detail": f"- 접수번호: {payload['case_no']}\n- 유형: {payload['defect_label']}\n- 증상: {payload['symptom']}"}


def _write_billing_complete(session, payload, actor, mm_user_name):
    from modules.models.entities import Contract
    import datetime as _dt

    contract = session.get(Contract, payload["contract_id"])
    if not contract:
        return {"ok": False, "msg": "계약 없음"}

    contract.payment_status = "청구완료"
    contract.invoice_date = _dt.date.fromisoformat(payload["invoice_date"])
    from modules.history_board import append_history_log
    append_history_log(session, project_id=payload["project_id"], user_name=actor,
        content=f"청구완료 처리 — 세금계산서 {payload['invoice_date']} [채팅확인 @{mm_user_name}]",
        scope="contract", kind="system", origin="chat_confirmed")

    # ── ERP알림 채널 알림 (모바일 /api/billing/mark-billed 와 동일 경로) ──────
    # routes/app_api.py:5690 의 mobile billing 마크빌드는 이미
    # notify(db, 'billing.completed', ...) 를 호출하지만 Mattermost 액션 핸들러는
    # 누락돼 있어 ERP알림 채널에 알림이 안 갔음. 출장/생산완료와 동일 회귀 패턴.
    try:
        from modules.notification_engine import notify
        kakao_text = (
            f"[계산서발행] {contract.contract_name or '-'}\n"
            f"세금계산서 발행일: {payload['invoice_date']}\n"
            f"처리자: {actor}"
        )
        # contract_amount 는 일부 환경에서 property 가 없을 수 있어 getattr fallback.
        try:
            amount_val = getattr(contract, 'contract_amount', None) or '-'
        except Exception:
            amount_val = '-'
        notify(session, 'billing.completed', {
            'contract_name': contract.contract_name,
            'user_name': actor,
            'project': contract.contract_name or '',
            'project_id': payload.get("project_id") or '',
            'invoice_date': payload["invoice_date"],
            'amount': amount_val,
        }, kakao_text_override=kakao_text)
    except Exception as _exc:
        # 알림 실패해도 등록은 성공으로 유지
        try:
            import logging
            logging.getLogger(__name__).warning(
                "billing.completed 알림 발송 실패 (등록은 성공): %s", _exc)
        except Exception:
            pass

    return {"ok": True, "label": "청구완료 처리됨",
            "detail": f"- 세금계산서 발행일: {payload['invoice_date']}"}


def _write_vehicle_log(session, payload, erp_user):
    from modules.models.entities import VehicleLog
    import datetime as _dt

    vl = VehicleLog(
        use_date=_dt.date.fromisoformat(payload["use_date"]),
        vehicle=payload["vehicle"],
        user_name=payload["driver_name"],
        user_id=payload.get("user_id"),
        user_department=payload.get("user_department"),
        user_position=payload.get("user_position"),
        origin=payload.get("origin", "출발지 미기재"),
        destination=payload["destination"],
        distance_km=payload["distance_km"],
        purpose=payload["purpose"],
        odometer_end=0,  # 채팅 등록 시 계기판 미입력
    )
    session.add(vl)
    return {"ok": True, "label": "운행일지 등록됨",
            "detail": f"- {payload['driver_name']} / {payload['vehicle']}\n- {payload['destination']} {payload['distance_km']}km"}


def _write_business_trip(session, payload):
    from modules.models.entities import BusinessTrip, BusinessTripMember
    import datetime as _dt

    trip = BusinessTrip(
        title=payload["title"],
        destination=payload["destination"],
        purpose=payload["purpose"],
        vehicle=payload.get("vehicle"),
        departure_date=_dt.datetime.fromisoformat(payload["departure_date"]),
        return_date=_dt.datetime.fromisoformat(payload["return_date"]),
        created_by=payload["created_by"],
        status="예정",
    )
    session.add(trip)
    session.flush()

    member_labels = []
    for m in payload.get("members", []):
        member = BusinessTripMember(
            trip_id=trip.id,
            user_name=m["user_name"],
            user_id=m.get("user_id"),
            position=m.get("position"),
            department=m.get("department"),
        )
        session.add(member)
        nm = m["user_name"]
        pos = (m.get("position") or "").strip()
        member_labels.append(f"{nm} {pos}".strip() if pos else nm)

    traveler_names = ", ".join(m["user_name"] for m in payload.get("members", []))

    # ── ERP알림 채널 알림 (PC 폼 / 모바일 API와 동일 경로) ──────────────────────
    # PC routes/business_trip.py 와 routes/app_api.py 의 trip_create 는 이미
    # notify(db, 'trip.created', ...) 를 호출하지만 Mattermost 액션 핸들러는
    # 누락돼 있어 ERP알림 채널에 알림이 안 갔음.
    try:
        from modules.notification_engine import notify
        dep_str = trip.departure_date.strftime('%Y-%m-%d %H:%M') if trip.departure_date else '-'
        ret_str = trip.return_date.strftime('%Y-%m-%d %H:%M') if trip.return_date else '-'
        members_str = ', '.join(member_labels) if member_labels else (traveler_names or '-')
        kakao_text = (
            f"[출장등록] {trip.title}\n"
            f"목적지: {trip.destination}\n"
            f"출발: {dep_str}\n"
            f"귀환: {ret_str}\n"
            f"차량: {trip.vehicle or '-'}\n"
            f"인원: {members_str}"
        )
        notify(session, 'trip.created', {
            'destination': trip.destination or trip.title,
            'detail': f"{dep_str}~{ret_str} · {members_str}",
            'trip_id': trip.id,
            'departure_date': dep_str,
            'return_date': ret_str,
            'members': members_str,
        }, kakao_text_override=kakao_text)
    except Exception as _exc:
        # 알림 실패해도 등록은 성공으로 유지
        try:
            import logging
            logging.getLogger(__name__).warning(
                "trip.created 알림 발송 실패 (등록은 성공): %s", _exc)
        except Exception:
            pass

    return {"ok": True, "label": "출장 등록됨",
            "detail": f"- 출장지: {payload['destination']}\n- 출장자: {traveler_names}\n- 출발일: {payload['departure_date']}"}


def _write_daily_report(session, payload, actor):
    from modules.models.entities import DailyReport
    import datetime as _dt
    import json as _json

    existing_id = payload.get("existing_id")
    items_json = _json.dumps(payload["items"], ensure_ascii=False)

    if existing_id:
        report = session.get(DailyReport, existing_id)
        if report:
            report.items_json = items_json
            report.reporter_name = payload["reporter_name"]
            report.reporter_id = payload["reporter_id"]
            report.updated_at = datetime.now()
    else:
        report = DailyReport(
            report_date=_dt.date.fromisoformat(payload["report_date"]),
            department=payload["department"],
            reporter_name=payload["reporter_name"],
            reporter_id=payload["reporter_id"],
            items_json=items_json,
            headcount_total=0,
            headcount_present=0,
        )
        session.add(report)

    items_preview = "\n".join(f"  - {i}" for i in payload["items"][:5])
    return {"ok": True, "label": "일일보고 등록됨",
            "detail": f"- {payload['department']} / {payload['report_date']}\n{items_preview}"}


def _write_po_status(session, payload, actor, mm_user_name):
    from modules.models.entities import PurchaseOrder

    po = session.get(PurchaseOrder, payload["po_id"])
    if not po:
        return {"ok": False, "msg": "발주서 없음"}

    old_status = po.status
    po.status = payload["new_status"]
    from modules.history_board import append_history_log
    # PO는 project_id 없으므로 로그 스킵하거나 별도 처리
    return {"ok": True, "label": "발주 상태 변경됨",
            "detail": f"- {payload['po_no']}: {old_status} → {payload['new_status']}"}


def _write_production_complete(session, payload, actor, mm_user_name):
    from modules.models.production_entities import ProductionProcess
    from modules.history_board import append_history_log
    from datetime import datetime as _dt

    process_id = payload["process_id"]
    completed_date = payload.get("completed_date") or str(datetime.now().date())

    proc = session.get(ProductionProcess, process_id)
    if not proc:
        return {"ok": False, "msg": f"생산공정 ID {process_id} 없음"}
    if proc.status in ("완료", "스킵"):
        return {"ok": False, "msg": f"이미 {proc.status} 처리된 공정입니다"}

    old_status = proc.status
    proc.status = "완료"
    proc.progress_percent = 100.0
    proc.completed_at = _dt.fromisoformat(f"{completed_date}T00:00:00")
    if not proc.started_at:
        proc.started_at = proc.completed_at

    append_history_log(session, project_id=proc.project_id, user_name=actor,
        content=f"생산완료 처리: {proc.process_name} (공정ID {proc.id}, {completed_date}) [채팅확인 @{mm_user_name}]",
        scope="production", kind="system", origin="chat_confirmed")

    # ── 부모 ContractItem.status_prod 자동 재계산 + 생산완료 알림 (PC와 동일 경로) ──
    # PC 경로(modules/services/production_actions.handle_process_complete)는 공정 완료 후
    # refresh_production_statuses(db, project_id) 를 호출해 (1) item.status_prod 자동 갱신
    # (2) 새로 '생산완료'가 된 품목에 대해 production.item_complete / production.site_complete
    # 알림을 자동으로 발송. Mattermost 액션 핸들러는 이를 호출하지 않아 #ERP알림 채널이
    # 조용했음. 한 줄 추가로 PC와 동등한 동작 확보.
    try:
        from modules.production_logic import refresh_production_statuses
        refresh_production_statuses(session, project_id=proc.project_id)
    except Exception as _exc:
        try:
            import logging
            logging.getLogger(__name__).warning(
                "생산완료 상태 재계산/알림 실패 (공정 완료는 성공): %s", _exc)
        except Exception:
            pass

    return {"ok": True, "label": "생산완료 처리됨",
            "detail": f"- {proc.process_name}\n- {old_status} → 완료\n- 완료일: {completed_date}"}


def _write_production_complete_all(session, payload, actor, mm_user_name):
    """품목(ContractItem) 전체 공정을 step_order 순서로 일괄 완료 처리.

    payload: {contract_item_id, process_ids[], quantity, completed_date}
    동작:
      1) 모든 process를 step_order 순으로 status='완료', progress_qty=quantity,
         progress_percent=100, started_at/completed_at 채움 (이미 완료된 건 skip)
      2) history_logs 1행 (요약: N개 공정 일괄완료 + 채팅확인 표시)
      3) refresh_production_statuses 호출 → ContractItem.status_prod 자동 재계산
         + '생산완료'로 전이되면 production.item_complete / site_complete 알림 발송
    """
    from modules.models.production_entities import ProductionProcess
    from modules.models.contract_entities import ContractItem
    from modules.history_board import append_history_log
    from datetime import datetime as _dt

    item_id = payload["contract_item_id"]
    completed_date = payload.get("completed_date") or str(datetime.now().date())
    quantity = int(payload["quantity"])
    completed_dt = _dt.fromisoformat(f"{completed_date}T00:00:00")

    item = session.get(ContractItem, item_id)
    if not item:
        return {"ok": False, "msg": f"ContractItem ID {item_id} 없음"}

    procs = (session.query(ProductionProcess)
             .filter(ProductionProcess.contract_item_id == item_id)
             .order_by(ProductionProcess.step_order, ProductionProcess.id)
             .all())
    if not procs:
        return {"ok": False, "msg": f"품목 {item_id} 에 등록된 공정 없음"}

    closed = []
    skipped = []
    for p in procs:
        if p.status in ("완료", "스킵"):
            skipped.append(p)
            continue
        p.status = "완료"
        p.progress_qty = quantity
        p.progress_percent = 100.0
        p.completed_at = completed_dt
        if not p.started_at:
            p.started_at = completed_dt
        closed.append(p)

    # 이미 완료된 공정도 수량이 0이면 보정 (예: 단건 완료 도구가 quantity=0 으로 들어간 케이스)
    qty_patched = []
    for p in skipped:
        if (p.progress_qty or 0) == 0 and p.status == "완료":
            p.progress_qty = quantity
            qty_patched.append(p)

    item.quantity_completed = quantity if hasattr(item, "quantity_completed") else getattr(item, "quantity_completed", None)

    summary = (f"전체 생산완료 일괄처리: {item.model_name} × {quantity}개 — "
               f"신규완료 {len(closed)}건 / 이미완료 {len(skipped)}건"
               + (f" (수량보정 {len(qty_patched)}건)" if qty_patched else "")
               + f" [채팅확인 @{mm_user_name}]")
    append_history_log(session, project_id=(item.contract.project_id if item.contract else None),
                       user_name=actor, content=summary,
                       scope="production", kind="system", origin="chat_confirmed")

    # 부모 status_prod 자동 재계산 + 생산완료 알림 발송
    try:
        from modules.production_logic import refresh_production_statuses
        refresh_production_statuses(session,
                                    project_id=(item.contract.project_id if item.contract else None))
    except Exception as _exc:
        try:
            import logging
            logging.getLogger(__name__).warning(
                "일괄완료 상태 재계산/알림 실패 (공정 완료는 성공): %s", _exc)
        except Exception:
            pass

    detail_lines = [f"- {item.model_name} × {quantity}개",
                    f"- 공정 {len(procs)}개 모두 완료 처리",
                    f"- 완료일: {completed_date}"]
    if qty_patched:
        detail_lines.append(f"- 수량 보정: {len(qty_patched)}건")
    return {"ok": True, "label": "전체 생산완료 일괄처리됨",
            "detail": "\n".join(detail_lines)}


def _write_email_send(session, payload, actor, mm_user_name):
    """SMTP 이메일 발송 confirm 핸들러.

    payload: {sender_user_id, account_id, to[], cc[], bcc[], subject,
              html_body, request_read_receipt}

    보안 — preview 단계 권한 검증을 confirm 단계에서도 다시 수행
    (preview ↔ confirm 사이 payload 변조 차단).

    동작:
      1) 권한 재검증 (account 의 owner 또는 shared can_send 또는 admin)
      2) 트래킹 픽셀 삽입 (request_read_receipt=True 시)
      3) SMTP 발송 (mail_client.send_message)
      4) MailReadReceipt 생성
      5) 주소록 자동 수집 (외부 이메일만)
    """
    import os
    import uuid as _uuid
    from modules.models.auth_entities import User
    from modules.models.mail_entities import (
        MailAccount, MailSharedAccess, MailReadReceipt, MailContact,
    )
    from modules.services.mail_client import MailClient, decrypt_password

    from modules.models.mail_entities import MailLargeFile

    sender_user_id = payload["sender_user_id"]
    account_id = payload["account_id"]
    to_list = list(payload.get("to") or [])
    cc_list = list(payload.get("cc") or [])
    bcc_list = list(payload.get("bcc") or [])
    subject = payload.get("subject", "")
    html_body = payload.get("html_body", "")
    request_receipt = bool(payload.get("request_read_receipt", True))
    large_file_ids = list(payload.get("large_file_ids") or [])
    mm_file_ids = list(payload.get("mm_file_ids") or [])

    if not to_list:
        return {"ok": False, "msg": "받는 사람이 없습니다."}

    sender = session.get(User, sender_user_id)
    if not sender:
        return {"ok": False, "msg": f"발신자 user#{sender_user_id} 없음"}
    account = session.get(MailAccount, account_id)
    if not account or not account.is_active:
        return {"ok": False, "msg": f"메일 계정 #{account_id} 없거나 비활성"}

    # ── 권한 재검증 (preview ↔ confirm 사이 변조 차단) ──
    if account.is_shared:
        access = session.query(MailSharedAccess).filter_by(
            mail_account_id=account.id, user_id=sender.id).first()
        is_admin = (sender.role or '').lower() == 'admin'
        if not is_admin:
            if not access:
                return {"ok": False, "msg": f"공유 계정 #{account.id} 접근 권한 없음 (confirm 재검증)"}
            if not access.can_send:
                return {"ok": False, "msg": f"공유 계정 #{account.id} 발송 권한(can_send) 없음 (confirm 재검증)"}
    else:
        if account.user_id != sender.id:
            return {"ok": False, "msg": f"개인 계정 #{account.id} 소유자 불일치 (confirm 재검증)"}

    # ── 비밀번호 복호화 + MailClient 생성 ──
    try:
        password = decrypt_password(account.password_encrypted)
    except Exception as e:
        return {"ok": False, "msg": f"메일 비밀번호 복호화 실패: {e!s:.60}"}

    client = MailClient(
        imap_host=account.imap_host, imap_port=account.imap_port,
        smtp_host=account.smtp_host, smtp_port=account.smtp_port,
        username=account.username, password=password,
        use_ssl=account.use_ssl,
    )

    domain = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')

    # ── 첨부 분기 정책 (ERP 표준과 동일) ──
    # ≤25MB(누적) → SMTP MIME 직첨부
    # >25MB         → Supabase Storage 업로드 후 본문에 다운로드 링크 fallback (만료 30일)
    SMTP_MAX_TOTAL = 25 * 1024 * 1024
    LARGE_FILE_EXPIRE_DAYS = 30

    body_to_send = html_body
    attached_files = []         # [(filename, bytes), ...] — SMTP MIME
    attached_names = []
    link_entries = []           # [(filename, file_id, size, expires_at), ...] — 본문 링크
    smtp_running = 0
    is_admin = (sender.role or '').lower() == 'admin'

    # ── 1) ERP large_file_ids: 권한 검증 후 SMTP/링크 분기 ──
    if large_file_ids:
        from modules import storage_adapter
        from datetime import datetime as _dt2, timezone as _tz2
        now = _dt2.now(_tz2.utc)

        records = []
        for fid in large_file_ids:
            rec = session.query(MailLargeFile).filter_by(file_id=fid).first()
            if not rec or rec.is_deleted:
                return {"ok": False, "msg": f"첨부 파일 file_id='{fid}' 없음/삭제됨 (confirm 재검증)"}
            exp = rec.expires_at
            if exp and exp.tzinfo is None:
                exp = exp.replace(tzinfo=_tz2.utc)
            if exp and exp < now:
                return {"ok": False, "msg": f"첨부 파일 file_id='{fid}' 만료됨"}
            if rec.sender_user_id != sender.id and not is_admin:
                return {"ok": False, "msg": f"첨부 파일 file_id='{fid}' 본인 업로드 아님 (confirm 재검증)"}
            records.append(rec)

        for rec in records:
            fsize = int(rec.file_size or 0)
            # 단일 파일이 25MB 초과거나 누적이 25MB 초과 → 링크 fallback (이미 Supabase 에 있음)
            if fsize > SMTP_MAX_TOTAL or smtp_running + fsize > SMTP_MAX_TOTAL:
                link_entries.append((rec.original_filename, rec.file_id, fsize, rec.expires_at))
                continue

            # SMTP MIME — 스토리지에서 바이트 받아옴
            data = storage_adapter.download_bytes(rec.storage_path)
            if data is None:
                return {"ok": False, "msg": f"첨부 파일 '{rec.original_filename}' 스토리지 다운로드 실패"}
            attached_files.append((rec.original_filename, data))
            attached_names.append(rec.original_filename)
            smtp_running += fsize

    # ── 2) MM 첨부: 메타 조회 후 SMTP/링크 분기 ──
    if mm_file_ids:
        from modules import storage_adapter
        import requests as _rq
        import uuid as _uuid_mm
        from datetime import datetime as _dt3, timedelta as _td3
        mm_base = os.environ.get('MM_BASE_URL', 'https://team.mgnt.kr').rstrip('/')
        mm_tok = os.environ.get('MM_BOT_TOKEN', '')
        if not mm_tok:
            return {"ok": False, "msg": "MM 첨부 발송 불가 — MM_BOT_TOKEN 미설정."}

        for fid in mm_file_ids:
            # 메타 조회 (파일명 + 크기)
            try:
                rinfo = _rq.get(
                    f"{mm_base}/api/v4/files/{fid}/info",
                    headers={"Authorization": f"Bearer {mm_tok}"},
                    timeout=10,
                )
            except Exception as e:
                return {"ok": False, "msg": f"MM 파일 메타 조회 실패 file_id='{fid}': {e!s:.100}"}
            if rinfo.status_code != 200:
                return {"ok": False,
                        "msg": (f"MM 파일 메타 조회 실패 file_id='{fid}' "
                                f"(HTTP {rinfo.status_code}) — confirm 재검증")}
            meta = rinfo.json()
            fname = meta.get('name') or f'mm-{fid}'
            fsize = int(meta.get('size') or 0)

            # 바이트 fetch (SMTP/Storage 어느 쪽이든 필요)
            try:
                rdata = _rq.get(
                    f"{mm_base}/api/v4/files/{fid}",
                    headers={"Authorization": f"Bearer {mm_tok}"},
                    timeout=120,
                )
            except Exception as e:
                return {"ok": False, "msg": f"MM 파일 다운로드 실패 file_id='{fid}': {e!s:.100}"}
            if rdata.status_code != 200:
                return {"ok": False,
                        "msg": (f"MM 파일 다운로드 실패 file_id='{fid}' "
                                f"(HTTP {rdata.status_code})")}
            data = rdata.content
            actual_size = len(data) or fsize

            # 25MB 이하 + 누적 25MB 이하 → SMTP MIME
            if actual_size <= SMTP_MAX_TOTAL and smtp_running + actual_size <= SMTP_MAX_TOTAL:
                attached_files.append((fname, data))
                attached_names.append(fname)
                smtp_running += actual_size
                continue

            # 25MB 초과 → Supabase 업로드 + MailLargeFile 행 생성 → 본문 링크
            new_fid = _uuid_mm.uuid4().hex[:16]
            ext = os.path.splitext(fname)[1] or ''
            storage_path = f'mail-attachments/{new_fid}{ext}'
            ok, msg = storage_adapter.upload_bytes(
                storage_path, data,
                content_type=meta.get('mime_type') or 'application/octet-stream',
                upsert=True,
            )
            if not ok:
                return {"ok": False, "msg": f"MM 첨부 '{fname}' Supabase 업로드 실패: {msg[:120]}"}

            expires_at = _dt3.now() + _td3(days=LARGE_FILE_EXPIRE_DAYS)
            try:
                session.add(MailLargeFile(
                    file_id=new_fid,
                    sender_user_id=sender.id,
                    original_filename=fname,
                    file_size=actual_size,
                    storage_path=storage_path,
                    expires_at=expires_at,
                ))
                session.flush()
            except Exception as e:
                return {"ok": False, "msg": f"MM 첨부 '{fname}' 메타 저장 실패: {e!s:.120}"}

            link_entries.append((fname, new_fid, actual_size, expires_at))

    # ── 3) 본문에 대용량 다운로드 링크 블록 삽입 ──
    if link_entries:
        rows_html = []
        for fname, fid, fsize, exp in link_entries:
            url = f'https://{domain}/mail/dl/{fid}'
            mb = (fsize or 0) / 1024 / 1024
            exp_str = exp.strftime('%Y-%m-%d') if exp else ''
            rows_html.append(
                f'<li style="margin:4px 0;">'
                f'<a href="{url}" style="color:#1a73e8;">{fname}</a> '
                f'<span style="color:#666;font-size:12px;">({mb:.1f}MB · 만료 {exp_str})</span>'
                f'</li>'
            )
        link_block = (
            '<div style="margin-top:24px;padding:12px 16px;border:1px solid #ddd;'
            'border-radius:6px;background:#f8f9fa;font-family:Arial,sans-serif;">'
            f'<div style="font-weight:bold;margin-bottom:8px;">대용량 첨부 ({len(link_entries)}개) — 다운로드 링크</div>'
            f'<ul style="margin:0;padding-left:20px;">{"".join(rows_html)}</ul>'
            f'<div style="margin-top:8px;color:#888;font-size:12px;">'
            f'25MB 초과 파일은 보관기간 {LARGE_FILE_EXPIRE_DAYS}일 후 자동 삭제됩니다.'
            '</div></div>'
        )
        body_to_send = body_to_send + link_block

    # ── 트래킹 픽셀 삽입 ──
    tracking_id = None
    if request_receipt:
        tracking_id = _uuid.uuid4().hex[:16]
        pixel_url = f'https://{domain}/mail/t/{tracking_id}.gif'
        pixel_tag = f'<img src="{pixel_url}" width="1" height="1" style="display:none;" alt="">'
        body_to_send = body_to_send + pixel_tag

    # ── SMTP 발송 (MIME 첨부) ──
    try:
        with client as c:
            result = c.send_message(
                from_addr=account.email,
                to=to_list, cc=cc_list or None, bcc=bcc_list or None,
                subject=subject,
                html_body=body_to_send,
                attachments=attached_files or None,
                from_name=account.display_name,
            )
    except Exception as e:
        return {"ok": False, "msg": f"SMTP 발송 실패: {e!s:.120}"}

    # ── MailReadReceipt 저장 ──
    if tracking_id:
        try:
            session.add(MailReadReceipt(
                tracking_id=tracking_id,
                sender_user_id=sender.id,
                mail_account_id=account.id,
                to_email=to_list[0],
                subject=subject,
            ))
        except Exception:
            pass  # 추적 저장 실패해도 발송 결과는 OK

    # ── 주소록 자동 수집 (외부 이메일만) ──
    try:
        all_addrs = list(to_list) + list(cc_list) + list(bcc_list)
        internal_emails = {
            u[0].lower() for u in session.query(User.email)
            .filter(User.email.isnot(None)).all() if u[0]
        }
        existing = {
            c[0].lower() for c in session.query(MailContact.email)
            .filter_by(user_id=sender.id).all() if c[0]
        }
        for addr in all_addrs:
            a = addr.strip().lower()
            if a and a not in internal_emails and a not in existing:
                session.add(MailContact(
                    user_id=sender.id,
                    name=a.split('@')[0],
                    email=a,
                ))
                existing.add(a)
    except Exception:
        pass  # 주소록 수집 실패해도 발송은 OK

    detail = (f"- 받는사람: {', '.join(to_list)}\n"
              f"- 제목: {subject}\n"
              f"- 발송계정: {account.email}\n"
              f"- 채팅확인: @{mm_user_name}")
    if attached_names:
        detail += f"\n- 첨부 ({len(attached_names)}개, SMTP MIME): {', '.join(attached_names)}"
    if link_entries:
        link_names = ', '.join(fn for fn, _, _, _ in link_entries)
        detail += f"\n- 대용량링크 ({len(link_entries)}개, 만료 {LARGE_FILE_EXPIRE_DAYS}일): {link_names}"
    if tracking_id:
        detail += f"\n- 수신확인_트래킹ID: {tracking_id}"
    return {"ok": True, "label": "메일 발송됨", "detail": detail}

