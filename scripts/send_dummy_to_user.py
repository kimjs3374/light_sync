from pathlib import Path

import requests


def load_env(path: str = "kakaowork/.env"):
    env = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    env = load_env()
    token = env.get("KAKAO_WORK_BOT_TOKEN") or env.get("KAKAOWORK_BOT_TOKEN")
    if not token:
        print("[FAIL] bot token 없음")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    target = None
    cursor = None
    scanned = 0
    while True:
        url = "https://api.kakaowork.com/v1/users.list"
        if cursor:
            url = f"{url}?cursor={cursor}"
        r = requests.get(url, headers=headers, timeout=20)
        body = r.json() if r.text else {}
        users = body.get("users") or []
        scanned += len(users)

        for u in users:
            name = (u.get("display_name") or "").strip()
            ids = u.get("identifications") or []
            id_values = [str(x.get("value") or "").lower() for x in ids if isinstance(x, dict)]
            emails = [str(x).lower() for x in (u.get("emails") or [])]

            if (
                name == "김정수"
                or any("kjs_3374@hanmail.net" in v for v in id_values)
                or any("kjs_3374@hanmail.net" in v for v in emails)
            ):
                target = u
                break

        if target:
            break

        cursor = body.get("cursor")
        if not cursor:
            break

    if not target:
        print(f"[FAIL] 대상 사용자를 찾지 못했습니다: 김정수 / kjs_3374@hanmail.net (scanned={scanned})")
        return

    user_id = str(target.get("id"))
    print(f"[INFO] 대상 사용자 확인: {target.get('display_name')} ({user_id})")

    open_resp = requests.post(
        "https://api.kakaowork.com/v1/conversations.open",
        headers=headers,
        json={"user_id": user_id},
        timeout=20,
    )
    open_body = open_resp.json() if open_resp.text else {}
    conversation_id = ((open_body.get("conversation") or {}).get("id")) or open_body.get("conversation_id")

    if not conversation_id:
        print(f"[FAIL] 대화방 열기 실패: {open_resp.status_code} {open_resp.text[:300]}")
        return

    text = "[더미 테스트] 김정수님 전달\n건명 : 테스트\n계약일자 : 2026-03-06\n납품기한 : 2026-03-31\n모델명 : TEST-1000\n수량 : 1EA"
    send_resp = requests.post(
        "https://api.kakaowork.com/v1/messages.send",
        headers=headers,
        json={"conversation_id": conversation_id, "text": text},
        timeout=20,
    )
    send_body = send_resp.json() if send_resp.text else {}

    if send_resp.status_code == 200 and not (
        isinstance(send_body, dict) and (send_body.get("success") is False or send_body.get("error"))
    ):
        msg_id = ((send_body.get("message") or {}).get("id")) if isinstance(send_body, dict) else None
        print(f"[PASS] 더미 메시지 전송 성공 (message_id={msg_id})")
    else:
        print(f"[FAIL] 메시지 전송 실패: {send_resp.status_code} {send_resp.text[:300]}")


if __name__ == "__main__":
    main()
