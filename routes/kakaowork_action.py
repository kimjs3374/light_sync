"""KakaoWork Interactive Action endpoint.

매그니 봇 메시지의 버튼(submit_action) 클릭 시 카카오워크 서버가 호출.
- POST /kakaowork/action
- 카카오워크 봇 콘솔의 "콜백(Request URL)"에 이 주소(https://work.mgnt.kr/kakaowork/action) 등록 필요.

payload(예):
    {"type": "submit_action", "action_name": "approval_approve",
     "value": "approve|<doc_id>|<step_id>", "react_user_id": 12345, "message": {...}}

보안: 클릭자(react_user_id)를 카카오워크 이메일로 역조회 → ERP User 매칭 →
      해당 결재단계의 본인인지 검증한 뒤에만 상태 전이. (외부 콜백이므로 CSRF 면제)
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from modules.db_context import get_db
from modules.models import ApprovalDocument, ApprovalStep, User

kakaowork_action_bp = Blueprint("kakaowork_action_bp", __name__)
logger = logging.getLogger(__name__)


def _resolve_erp_user_by_kakao(session, react_user_id: str) -> User | None:
    """카카오워크 user_id → 멤버정보 역조회 → ERP User 매칭.

    카카오는 회사 이메일이 없는 경우가 많아 이름(+부서) 매칭을 1순위로 한다.
    """
    if not react_user_id:
        return None
    from modules.kakaowork_notifier import get_kakao_user
    ku = get_kakao_user(str(react_user_id))
    if not ku:
        return None
    name = (ku.get("name") or ku.get("display_name") or "").strip()
    dept = (ku.get("department") or "").strip()
    if name:
        q = session.query(User).filter(User.full_name == name)
        cands = q.all()
        if len(cands) == 1:
            return cands[0]
        if cands and dept:
            for c in cands:
                if (c.user_group or "").strip() == dept:
                    return c
        if cands:
            return cands[0]
    # 이메일 보조 매칭 (개인메일이 ERP에 등록된 드문 경우)
    for x in (ku.get("identifications") or []) + [{"value": e} for e in (ku.get("emails") or [])]:
        val = (x.get("value") if isinstance(x, dict) else str(x) or "").strip().lower()
        if val:
            u = session.query(User).filter(User.email.ilike(val)).first()
            if u:
                return u
    return None


@kakaowork_action_bp.route("/kakaowork/action", methods=["POST", "GET"])
def kakaowork_action():
    """KakaoWork interactive(submit_action) 콜백 — 전자결재 승인/반려 즉시 처리."""
    payload = request.get_json(silent=True) or {}

    # ── URL 검증(challenge) 응답: 콘솔 등록 시 보내는 챌린지 echo ──
    challenge = (request.args.get("challenge") or payload.get("challenge")
                 or payload.get("verification") or payload.get("token"))
    if request.method == "GET" or (challenge and not payload.get("value")):
        return jsonify({"challenge": challenge} if challenge else {"ok": True}), 200

    value = str(payload.get("value") or "")
    react_user_id = (payload.get("react_user_id") or payload.get("user_id")
                     or (payload.get("message") or {}).get("user_id") or "")

    logger.info("[kakao-action] value=%s user=%s", value, react_user_id)

    parts = value.split("|")
    if len(parts) != 3 or parts[0] not in ("approve", "reject"):
        return jsonify({"text": "알 수 없는 요청입니다."}), 200
    verb, doc_id, step_id = parts[0], parts[1], parts[2]
    approve = verb == "approve"

    from modules.services import approval_service as svc
    from modules.activity import log_activity
    from modules.kakaowork_notifier import send_dm_text

    result_text = None
    processed_ok = False
    with get_db() as session:
        user = _resolve_erp_user_by_kakao(session, react_user_id)
        if not user:
            result_text = "⚠️ ERP 사용자 매칭 실패 — 웹에서 처리해 주세요."
        else:
            doc = session.query(ApprovalDocument).get(int(doc_id)) if doc_id.isdigit() else None
            step = session.query(ApprovalStep).get(int(step_id)) if step_id.isdigit() else None
            if not doc or not step or step.document_id != doc.id:
                result_text = "⚠️ 결재 문서를 찾을 수 없습니다."
            elif step.approver_id != user.id:
                result_text = "⚠️ 본인 결재 차례가 아닙니다."
            else:
                try:
                    if approve:
                        svc.approve_step(session, doc, step, None)
                    else:
                        svc.reject_step(session, doc, step, None)  # 사유는 추후 코멘트 입력
                    try:
                        log_activity(session, 'approval', 'approve' if approve else 'reject',
                                     f'[{doc.doc_no}] {doc.title} {"승인" if approve else "반려"}(카카오 버튼)',
                                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
                    except Exception:
                        pass
                    session.commit()
                    processed_ok = True  # _finalize_step_messages가 처리완료 메시지를 이미 발송
                except ValueError as e:
                    session.rollback()
                    result_text = f"⚠️ {e}"

    # 성공 시: finalize가 양쪽 채널 메시지를 갱신하므로 중복 발송 안 함.
    # 실패/가드 시에만 클릭자에게 안내 DM.
    if react_user_id and result_text and not processed_ok:
        try:
            send_dm_text(str(react_user_id), result_text)
        except Exception:
            pass

    return jsonify({"text": result_text or "처리되었습니다."}), 200
