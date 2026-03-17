import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

import requests


def load_kakaowork_config() -> Dict[str, str]:
    token = os.environ.get("KAKAOWORK_BOT_TOKEN", "")
    workboard_id = os.environ.get("KAKAOWORK_WORKBOARD_ID", "")
    api_base_url = os.environ.get("KAKAOWORK_API_BASE_URL", "https://api.kakaowork.com")
    post_path_template = os.environ.get("KAKAOWORK_WORKBOARD_POST_PATH", "/v1/workboards/{workboard_id}/posts")

    return {
        "token": token,
        "workboard_id": workboard_id,
        "api_base_url": api_base_url.rstrip("/"),
        "post_path_template": post_path_template,
    }


def build_contract_workboard_text(project, contracts: List) -> str:
    title = project.temp_name or project.short_name or f"현장 #{project.id}"
    lines: List[str] = [f"[신규 계약 현장 등록] {title}", ""]

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
                f"건명 : {contract.contract_name or '-'}",
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

    lines.extend(
        [
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
