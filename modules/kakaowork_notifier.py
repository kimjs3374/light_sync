import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def _kakaowork_disabled() -> bool:
    """KAKAOWORK_DISABLED 환경변수가 truthy면 카카오워크 알림을 전면 차단.

    테스트/개발용 킬스위치. 실사용 알림과 혼동되지 않도록 사용.
    허용값(차단 활성): 1, true, yes, on (대소문자 무시).
    """
    val = os.environ.get("KAKAOWORK_DISABLED", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def load_kakaowork_config() -> Dict[str, str]:
    token = os.environ.get("KAKAOWORK_BOT_TOKEN", "")
    workboard_id = os.environ.get("KAKAOWORK_WORKBOARD_ID", "")
    api_base_url = os.environ.get("KAKAOWORK_API_BASE_URL", "https://api.kakaowork.com")
    post_path_template = os.environ.get("KAKAOWORK_WORKBOARD_POST_PATH", "/v1/workboards/{workboard_id}/posts")
    notify_conv_id = os.environ.get("KAKAOWORK_NOTIFY_CONV_ID", "")
    # 그룹 단체방 알림은 'ERP 알림 봇'(단체방 멤버)으로 발송.
    # DM 버튼은 KAKAOWORK_BOT_TOKEN('전자결재 알림' 봇)을 그대로 사용.
    notify_token = os.environ.get("KAKAOWORK_NOTIFY_BOT_TOKEN", "") or token

    return {
        "token": token,
        "notify_token": notify_token,
        "workboard_id": workboard_id,
        "api_base_url": api_base_url.rstrip("/"),
        "post_path_template": post_path_template,
        "notify_conv_id": notify_conv_id,
    }


def _erp_url(path: str) -> str:
    """ERP 절대 주소 (알림 엔진 _erp_url 과 같은 규칙)."""
    base = (os.environ.get('ERP_BASE_URL')
            or os.environ.get('SERVER_BASE_URL')
            or 'https://work.mgnt.kr').rstrip('/')
    return base + ('' if path.startswith('/') else '/') + path


def send_group_notification(text: str) -> bool:
    """그룹채팅방에 봇 알림 메시지 전송. 실패해도 예외 미발생 (non-blocking)."""
    if _kakaowork_disabled():
        logger.info("카카오워크 알림 차단(KAKAOWORK_DISABLED): %s", text[:120].replace("\n", " | "))
        return False

    cfg = load_kakaowork_config()
    token = cfg["notify_token"]   # 단체방 알림 = ERP 알림 봇 토큰
    conv_id = cfg["notify_conv_id"]

    if not token or not conv_id:
        logger.debug("카카오워크 알림 스킵: KAKAOWORK_NOTIFY_BOT_TOKEN 또는 KAKAOWORK_NOTIFY_CONV_ID 미설정")
        return False

    try:
        resp = requests.post(
            f"{cfg['api_base_url']}/v1/messages.send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"conversation_id": conv_id, "text": text},
            timeout=10,
        )
        body = resp.json() if resp.text else {}
        if resp.status_code == 200 and not (isinstance(body, dict) and (body.get("success") is False or body.get("error"))):
            return True
        logger.warning("카카오워크 알림 전송 실패: %s %s", resp.status_code, str(body)[:200])
        return False
    except Exception as exc:
        logger.warning("카카오워크 알림 예외: %s", exc)
        return False


# ────────────────────────────────────────────────────────
# DM (1:1) + 인터랙티브 버튼 — 전자결재 승인/반려
# ────────────────────────────────────────────────────────

def _kakao_headers() -> Optional[Dict[str, str]]:
    cfg = load_kakaowork_config()
    token = cfg["token"]
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def find_user_id(name: str, dept: Optional[str] = None,
                 email: Optional[str] = None) -> Optional[str]:
    """카카오워크 user_id 조회. users.list 페이지네이션 스캔.

    카카오워크 멤버는 회사 이메일이 없고 개인메일로 가입된 경우가 많아
    **이름(+부서) 매칭을 1순위**로 한다. 이메일(emails/identifications)은 보조.
    - 이름 일치 + (부서 미지정이거나 부서 일치) → 채택
    - 그래도 못 찾으면 이메일 일치로 폴백
    """
    headers = _kakao_headers()
    if not headers:
        return None
    nm = (name or "").strip()
    dp = (dept or "").strip()
    em = (email or "").strip().lower()
    cfg = load_kakaowork_config()
    base = cfg["api_base_url"]
    cursor = None
    email_hit = None
    name_matches = []  # [(id, dept)] — 이름 일치 후보 (부서는 동점 처리용)
    try:
        for _ in range(50):  # 안전 상한
            url = f"{base}/v1/users.list"
            if cursor:
                url = f"{url}?cursor={cursor}"
            r = requests.get(url, headers=headers, timeout=15)
            body = r.json() if r.text else {}
            for u in (body.get("users") or []):
                u_names = {(u.get("name") or "").strip(),
                           (u.get("display_name") or "").strip()} - {""}
                u_dept = (u.get("department") or "").strip()
                if nm and nm in u_names:
                    name_matches.append((str(u.get("id")), u_dept))
                if em and email_hit is None:
                    emails = [str(x).lower() for x in (u.get("emails") or [])]
                    ids = [str(x.get("value") or "").lower()
                           for x in (u.get("identifications") or []) if isinstance(x, dict)]
                    if em in emails or any(em == v for v in ids):
                        email_hit = str(u.get("id"))
            cursor = body.get("cursor")
            if not cursor:
                break
    except Exception as exc:
        logger.warning("카카오워크 user 조회 예외: %s", exc)

    # 이름 우선: 유일하면 부서 달라도 채택, 여러 명이면 부서로 구분
    if name_matches:
        if len(name_matches) == 1:
            return name_matches[0][0]
        if dp:
            for uid, u_dept in name_matches:
                if u_dept and u_dept == dp:
                    return uid
        return name_matches[0][0]
    return email_hit


def get_kakao_user(user_id: str) -> Optional[Dict]:
    """카카오워크 user_id → 멤버 정보(name/department/position/emails). 콜백 본인검증용."""
    if not user_id:
        return None
    headers = _kakao_headers()
    if not headers:
        return None
    cfg = load_kakaowork_config()
    try:
        r = requests.get(f"{cfg['api_base_url']}/v1/users.info?user_id={user_id}",
                         headers=headers, timeout=10)
        body = r.json() if r.text else {}
        return body.get("user") or None
    except Exception as exc:
        logger.warning("카카오워크 users.info 예외: %s", exc)
        return None


def _open_dm(user_id: str) -> Optional[str]:
    """user_id와의 1:1 대화방 열기 → conversation_id."""
    headers = _kakao_headers()
    if not headers or not user_id:
        return None
    cfg = load_kakaowork_config()
    try:
        r = requests.post(f"{cfg['api_base_url']}/v1/conversations.open",
                          headers=headers, json={"user_id": str(user_id)}, timeout=15)
        body = r.json() if r.text else {}
        return ((body.get("conversation") or {}).get("id")) or body.get("conversation_id")
    except Exception as exc:
        logger.warning("카카오워크 conversations.open 예외: %s", exc)
        return None


def send_text_to_conversation(conversation_id: str, text: str) -> bool:
    """이미 열린 conversation_id에 단순 텍스트 발송 (처리완료 후속 안내용). 실패 무시."""
    if _kakaowork_disabled() or not conversation_id:
        return False
    headers = _kakao_headers()
    if not headers:
        return False
    cfg = load_kakaowork_config()
    try:
        r = requests.post(f"{cfg['api_base_url']}/v1/messages.send",
                          headers=headers, json={"conversation_id": str(conversation_id), "text": text},
                          timeout=15)
        body = r.json() if r.text else {}
        return r.status_code == 200 and not (
            isinstance(body, dict) and (body.get("success") is False or body.get("error")))
    except Exception as exc:
        logger.warning("카카오워크 conversation 발송 예외: %s", exc)
        return False


def send_dm_text(user_id: str, text: str) -> bool:
    """user_id에게 단순 텍스트 DM (콜백 처리결과 안내용)."""
    if _kakaowork_disabled():
        return False
    headers = _kakao_headers()
    if not headers:
        return False
    conv_id = _open_dm(user_id)
    if not conv_id:
        return False
    cfg = load_kakaowork_config()
    try:
        r = requests.post(f"{cfg['api_base_url']}/v1/messages.send",
                          headers=headers, json={"conversation_id": conv_id, "text": text},
                          timeout=15)
        body = r.json() if r.text else {}
        return r.status_code == 200 and not (
            isinstance(body, dict) and (body.get("success") is False or body.get("error")))
    except Exception as exc:
        logger.warning("카카오워크 send_dm_text 예외: %s", exc)
        return False


def send_approval_request_dm(approver_name: str, doc_id: int, step_id: int,
                             form_name: str, drafter_name: str, title: str,
                             doc_link: str = "", approver_dept: str = "",
                             approver_email: str = "",
                             summary_lines: Optional[List[str]] = None,
                             reminder_days: Optional[int] = None) -> bool:
    """결재 차례인 사람에게 승인/반려 버튼이 달린 1:1 DM 발송.

    카카오 매칭은 이름(+부서) 우선, 이메일 보조.
    버튼 클릭 시 submit_action → 카카오워크 봇 콘솔에 등록된 콜백 URL(/kakaowork/action)로 전송.
    value 포맷: "approve|<doc_id>|<step_id>" / "reject|<doc_id>|<step_id>".
    실패해도 예외 미발생.
    """
    if _kakaowork_disabled():
        logger.info("카카오워크 결재 DM 차단(KAKAOWORK_DISABLED): doc=%s", doc_id)
        return False
    headers = _kakao_headers()
    if not headers:
        logger.debug("카카오워크 결재 DM 스킵: 토큰 미설정")
        return False

    user_id = find_user_id(approver_name, dept=approver_dept, email=approver_email)
    if not user_id:
        logger.warning("카카오워크 결재 DM 스킵: 사용자 매칭 실패 name=%s dept=%s",
                       approver_name, approver_dept)
        return False
    conv_id = _open_dm(user_id)
    if not conv_id:
        return False

    if reminder_days is not None:
        wtxt = f"{reminder_days}일 경과" if reminder_days > 0 else "오늘 접수"
        summary = f"⏰ 미결재 독촉 — {form_name} ({wtxt})\n{drafter_name}님 상신: {title}"
    else:
        summary = f"📋 결재요청 — {form_name}\n{drafter_name}님이 상신: {title}"
    detail = ("\n\n" + "\n".join(f"· {ln}" for ln in summary_lines)) if summary_lines else ""
    blocks = [
        {"type": "text", "text": summary + detail, "markdown": False},
        {"type": "button", "text": "✅ 승인", "style": "primary",
         "action_type": "submit_action", "action_name": "approval_approve",
         "value": f"approve|{doc_id}|{step_id}"},
        {"type": "button", "text": "❌ 반려", "style": "danger",
         "action_type": "submit_action", "action_name": "approval_reject",
         "value": f"reject|{doc_id}|{step_id}"},
    ]
    if doc_link:
        blocks.append({"type": "button", "text": "상세보기", "style": "default",
                       "action_type": "open_system_browser", "value": doc_link})

    cfg = load_kakaowork_config()
    try:
        r = requests.post(f"{cfg['api_base_url']}/v1/messages.send",
                          headers=headers,
                          json={"conversation_id": conv_id, "text": summary + detail, "blocks": blocks},
                          timeout=15)
        body = r.json() if r.text else {}
        ok = r.status_code == 200 and not (
            isinstance(body, dict) and (body.get("success") is False or body.get("error")))
        if not ok:
            logger.warning("카카오워크 결재 DM 전송 실패: %s %s", r.status_code, str(body)[:200])
            return None
        msg_id = ((body.get("message") or {}).get("id")) if isinstance(body, dict) else None
        return {"conversation_id": conv_id, "message_id": str(msg_id) if msg_id else None}
    except Exception as exc:
        logger.warning("카카오워크 결재 DM 예외: %s", exc)
        return None


def send_delivery_check_dm(owner_name: str, split_id: int, project_name: str,
                           contract_name: str, split_no: int, quantity: int,
                           due_date, elapsed_days: int,
                           owner_dept: str = "", owner_email: str = "") -> bool:
    """납품예정시각이 지난 회차에 대해 담당자에게 완료 여부를 묻는 버튼 DM.

    버튼 클릭 → 카카오워크 콘솔에 등록된 콜백(/kakaowork/action)으로 전송.
    value 포맷: "dlv_done|<split_id>" / "dlv_pending|<split_id>".
    결재 DM 과 같은 봇(DM 버튼봇) 토큰을 쓴다 — 그룹알림봇과 섞으면 안 된다.
    """
    if _kakaowork_disabled():
        logger.info("카카오워크 납품확인 DM 차단(KAKAOWORK_DISABLED): split=%s", split_id)
        return False
    headers = _kakao_headers()
    if not headers:
        logger.debug("카카오워크 납품확인 DM 스킵: 토큰 미설정")
        return False

    user_id = find_user_id(owner_name, dept=owner_dept, email=owner_email)
    if not user_id:
        logger.warning("카카오워크 납품확인 DM 스킵: 사용자 매칭 실패 name=%s", owner_name)
        return False
    conv_id = _open_dm(user_id)
    if not conv_id:
        return False

    elapsed = "오늘 예정" if elapsed_days <= 0 else f"{elapsed_days}일 경과"
    summary = (f"🚚 납품 확인 — {project_name}\n"
               f"{split_no}차 {quantity}EA · 예정 {due_date} ({elapsed})")
    if contract_name:
        summary += f"\n계약: {contract_name[:40]}"
    summary += "\n\n납품 완료하셨나요?"

    blocks = [
        {"type": "text", "text": summary, "markdown": False},
        {"type": "button", "text": "✅ 납품완료", "style": "primary",
         "action_type": "submit_action", "action_name": "delivery_done",
         "value": f"dlv_done|{split_id}"},
        {"type": "button", "text": "🕐 아직", "style": "default",
         "action_type": "submit_action", "action_name": "delivery_pending",
         "value": f"dlv_pending|{split_id}"},
    ]

    cfg = load_kakaowork_config()
    try:
        r = requests.post(f"{cfg['api_base_url']}/v1/messages.send",
                          headers=headers,
                          json={"conversation_id": conv_id, "text": summary, "blocks": blocks},
                          timeout=15)
        body = r.json() if r.text else {}
        ok = r.status_code == 200 and not (
            isinstance(body, dict) and (body.get("success") is False or body.get("error")))
        if not ok:
            logger.warning("카카오워크 납품확인 DM 전송 실패: %s %s", r.status_code, str(body)[:200])
        return ok
    except Exception as exc:
        logger.warning("카카오워크 납품확인 DM 예외: %s", exc)
        return False


def build_contract_workboard_text(project, contracts: List) -> str:
    """신규 계약 워크보드 게시글 본문.

    모델명을 한 줄에 콤마로 늘어놓던 것과 세부품목 목록이 같은 내용을 두 번
    보여주고 있었다. 품목은 목록 한 곳으로 모은다.
    """
    from modules import notification_format as nf
    from modules.services.notification_bodies import model_label

    def when(d):
        return d.strftime('%Y-%m-%d') if d else None

    parts = ["[신규 계약 현장 등록]"]

    for idx, contract in enumerate(contracts, start=1):
        items = list(getattr(contract, "items", []) or [])
        total_qty = sum(int(item.quantity or 0) for item in items)

        parts += [
            nf.BLANK,
            contract.contract_name or '-',
            nf.kv('계약일자', when(contract.contract_date)),
            nf.kv('납품기한', when(contract.delivery_due_date)),
            nf.kv('수량', f"{nf.qty(total_qty)}EA" if items else None),
        ]
        if items:
            parts += [
                '품목',
                nf.bullets([
                    f"{model_label(item.category, item.model_name)} {nf.qty(item.quantity)}EA"
                    for item in items
                ]),
            ]
        if idx != len(contracts):
            parts += [nf.BLANK, "--------------------"]

    parts += [
        nf.BLANK,
        _erp_url(f"/contract_detail/{project.id}"),
        nf.BLANK,
        "※ 아래 댓글에 협의내용/업무내용을 이어서 작성해 주세요.",
    ]
    return nf.body(*parts)


def post_contract_summary(project, contracts: List) -> Tuple[bool, str, Optional[dict]]:
    if _kakaowork_disabled():
        logger.info(
            "카카오워크 워크보드 게시 차단(KAKAOWORK_DISABLED): project_id=%s, contracts=%d",
            getattr(project, "id", "-"),
            len(contracts or []),
        )
        return False, "KAKAOWORK_DISABLED=1 — 카카오워크 알림 차단됨(테스트 모드)", None

    cfg = load_kakaowork_config()
    token = cfg["token"]
    workboard_id = cfg["workboard_id"]

    if not token or not workboard_id:
        return False, "카카오워크 토큰 또는 워크보드 ID가 설정되지 않았습니다. (kakaowork/.env)", None

    path = cfg["post_path_template"].format(workboard_id=workboard_id)
    url = f"{cfg['api_base_url']}{path if path.startswith('/') else '/' + path}"

    payload = {
        "content": build_contract_workboard_text(project, contracts),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        body = resp.json() if resp.text else {}

        if resp.status_code in (200, 201):
            if isinstance(body, dict):
                if body.get("success") is False or body.get("error"):
                    return False, f"워크보드 게시글 등록 실패(응답 에러): {body}", body
                return True, "워크보드 게시글 등록 성공", body

            return True, "워크보드 게시글 등록 성공", {"raw": body}

        return False, f"워크보드 게시글 등록 실패: {resp.status_code} {resp.text[:300]}", body if isinstance(body, dict) else None
    except Exception as exc:
        return False, f"카카오워크 API 호출 예외: {exc}", None
