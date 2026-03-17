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
    board_id = env.get("KAKAO_WORK_BOARD_ID") or env.get("KAKAOWORK_WORKBOARD_ID")
    base = env.get("KAKAOWORK_API_BASE_URL", "https://api.kakaowork.com").rstrip("/")

    if not token or not board_id:
        print("[FAIL] token 또는 board_id 누락")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "content": "[더미 테스트] 계약 등록 알림\n건명 : 테스트\n계약일자 : 2026-03-06\n납품기한 : 2026-03-31\n모델명 : TEST-1000\n수량 : 1EA",
    }

    paths = [
        f"/v1/workboards/{board_id}/posts",
        f"/v1/workboards/{board_id}/post",
        f"/v1/workboard/{board_id}/posts",
        f"/v1/workboard/{board_id}/post",
        f"/v1/workboards/{board_id}/messages",
        f"/v1/workboards/{board_id}/feed",
        "/v1/workboards/posts",
    ]

    for path in paths:
        url = f"{base}{path}"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            text = (r.text or "")[:220].replace("\n", " ")
            print(f"{path} => {r.status_code} {text}")
            try:
                body = r.json()
            except Exception:
                body = None

            if r.status_code in (200, 201) and not (
                isinstance(body, dict) and (body.get("success") is False or body.get("error"))
            ):
                print(f"[SUCCESS_PATH] {path}")
                return
        except Exception as exc:
            print(f"{path} => EXCEPTION {exc}")

    print("[FAIL] 동작하는 API 경로를 찾지 못했습니다.")


if __name__ == "__main__":
    main()
