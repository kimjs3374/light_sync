import datetime as dt
import logging
import os
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def load_kakaowork_config() -> Dict[str, str]:
    token = os.environ.get("KAKAOWORK_BOT_TOKEN", "")
    workboard_id = os.environ.get("KAKAOWORK_WORKBOARD_ID", "")
    api_base_url = os.environ.get("KAKAOWORK_API_BASE_URL", "https://api.kakaowork.com")
    post_path_template = os.environ.get("KAKAOWORK_WORKBOARD_POST_PATH", "/v1/workboards/{workboard_id}/posts")
    notify_conv_id = os.environ.get("KAKAOWORK_NOTIFY_CONV_ID", "")

    return {
        "token": token,
        "workboard_id": workboard_id,
        "api_base_url": api_base_url.rstrip("/"),
        "post_path_template": post_path_template,
        "notify_conv_id": notify_conv_id,
    }


def send_group_notification(text: str) -> bool:
    """그룹채팅방에 봇 알림 메시지 전송. 실패해도 예외 미발생 (non-blocking)."""
    cfg = load_kakaowork_config()
    token = cfg["token"]
    conv_id = cfg["notify_conv_id"]

    if not token or not conv_id:
        logger.debug("카카오워크 알림 스킵: KAKAOWORK_BOT_TOKEN 또는 KAKAOWORK_NOTIFY_CONV_ID 미설정")
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


def build_production_complete_text(project_name: str, model_name: str, quantity: int, category: str = '') -> str:
    """품목 단위 생산완료 알림 텍스트"""
    lines = [
        f"[생산완료] {project_name}",
        "",
        f"모델명 : {model_name or '-'}",
        f"품목구분 : {category or '-'}",
        f"수량 : {quantity}EA",
        "",
        f"(완료시각: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
    ]
    return "\n".join(lines)


def build_site_complete_text(project_name: str, items_summary: List[Dict]) -> str:
    """현장 전체 생산완료 알림 텍스트"""
    lines = [
        f"[🏭 현장 전체 생산완료] {project_name}",
        "",
    ]
    for item in items_summary:
        lines.append(f"- {item.get('model_name', '-')} / {item.get('quantity', 0)}EA")
    total_qty = sum(item.get('quantity', 0) for item in items_summary)
    lines.extend([
        "",
        f"총 {len(items_summary)}개 품목, {total_qty}EA 생산완료",
        f"(완료시각: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
    ])
    return "\n".join(lines)


def notify_production_complete(project_name: str, model_name: str, quantity: int, category: str = '') -> bool:
    """품목 생산완료 시 그룹채팅 알림"""
    text = build_production_complete_text(project_name, model_name, quantity, category)
    return send_group_notification(text)


def notify_site_complete(project_name: str, items_summary: List[Dict]) -> bool:
    """현장 전체 생산완료 시 그룹채팅 알림"""
    text = build_site_complete_text(project_name, items_summary)
    return send_group_notification(text)


def build_contract_workboard_text(project, contracts: List) -> str:
    lines: List[str] = ["[신규 계약 현장 등록]"]

    for idx, contract in enumerate(contracts, start=1):
        item_lines = []
        total_qty = 0
        for item in getattr(contract, "items", []) or []:
            model_name = (item.model_name or "").strip() or "-"
            qty = int(item.quantity or 0)
            total_qty += qty
            item_lines.append(f"- {model_name} / {qty}EA")

        lines.extend(
            [
                f"{contract.contract_name or '-'}",
                "",
                f"계약일자 : {contract.contract_date.strftime('%Y-%m-%d') if contract.contract_date else '-'}",
                f"납품기한 : {contract.delivery_due_date.strftime('%Y-%m-%d') if contract.delivery_due_date else '-'}",
                f"모델명 : {', '.join([(item.model_name or '-').strip() or '-' for item in (getattr(contract, 'items', []) or [])]) or '-'}",
                f"수량 : {total_qty}EA",
            ]
        )
        if item_lines:
            lines.append("세부품목 :")
            lines.extend(item_lines)

        if idx != len(contracts):
            lines.append("")
            lines.append("--------------------")
            lines.append("")

    detail_url = f"https://work.mgnt.kr/contract_detail/{project.id}"
    lines.extend(
        [
            "",
            f"{detail_url}",
            "",
            "※ 아래 댓글에 협의내용/업무내용을 이어서 작성해 주세요.",
            f"(발행시각: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
        ]
    )

    return "\n".join(lines)


def post_contract_summary(project, contracts: List) -> Tuple[bool, str, Optional[dict]]:
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
