"""Claude Channel 채팅 — Channel 서버 경유 Claude Code 연동

v5: pending 제거 — channel.mjs가 reply 시 원본 메타(session_id, user_text)를
    함께 전달하므로 worker 간 상태 공유 불필요.
    /send → channel 전송 → channel-reply에서 히스토리 저장 + 응답 저장
    /poll → 응답 파일 확인
"""
import json
import logging
import os
import random
import time
import uuid

import requests
from flask import Blueprint, render_template, request, jsonify, session

from modules.auth_decorators import login_required
from routes.chatbot import _get_allowed_tools

logger = logging.getLogger(__name__)
channel_chat_bp = Blueprint("channel_chat", __name__, url_prefix="/channel-chat")

# 멀티워커: worker N → 포트 (BASE_PORT + N). start-channel.py와 동일 규칙.
# 워커 수는 CHANNEL_WORKERS env로 조정 (systemd @1..@N enable 수와 맞출 것).
# BASE는 mmbot 워커 영역(8789~8791)을 피해 8800 사용.
CHANNEL_BASE_PORT = 8800
CHANNEL_WORKERS = int(os.environ.get("CHANNEL_WORKERS", "1"))
CHANNEL_URLS = [
    f"http://127.0.0.1:{CHANNEL_BASE_PORT + i}"
    for i in range(1, CHANNEL_WORKERS + 1)
]
REPLY_TIMEOUT = 600
MAX_HISTORY = 30

# 응답 저장 디렉토리 (worker 간 공유)
REPLY_DIR = "/tmp/channel_replies"
os.makedirs(REPLY_DIR, exist_ok=True)


def _reply_path(req_id):
    return os.path.join(REPLY_DIR, f"{req_id}.json")


# ── 히스토리 ────────────────────────────────────────────────────────
def _get_engine():
    from modules.models.db import engine
    return engine


def _load_history(session_id):
    from sqlalchemy import text
    try:
        with _get_engine().begin() as conn:
            row = conn.execute(
                text("SELECT messages_json FROM chatbot_history WHERE session_id = :s"),
                {"s": session_id}
            ).fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception as e:
        logger.error(f"[channel] history load fail: {e}")
    return []


def _save_history(session_id, history):
    from sqlalchemy import text
    try:
        payload = json.dumps(history, ensure_ascii=False)
        with _get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO chatbot_history (session_id, messages_json, updated_at)
                VALUES (:s, :m, NOW())
                ON CONFLICT (session_id) DO UPDATE SET messages_json = :m, updated_at = NOW()
            """), {"s": session_id, "m": payload})
    except Exception as e:
        logger.error(f"[channel] history save fail: {e}")


def _append_history(session_id, user_text, reply_text):
    import datetime as _dt
    now = _dt.datetime.now().isoformat()
    history = _load_history(session_id)
    history.append({"role": "user", "content": user_text, "ts": now})
    history.append({"role": "assistant", "content": reply_text, "ts": now})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    _save_history(session_id, history)


# ── Channel 응답 수신 ───────────────────────────────────────────────
@channel_chat_bp.route("/channel-reply", methods=["POST"])
def channel_reply():
    """channel.mjs가 원본 메타(session_id, user_text)를 함께 전달."""
    data = request.get_json(silent=True) or {}
    req_id = data.get("request_id", "")
    text_content = data.get("text", "")
    is_partial = data.get("partial", False)
    ch_session_id = data.get("session_id", "")
    ch_user_text = data.get("user_text", "")

    label = "partial" if is_partial else "final"
    logger.info(f"[channel] channel-reply ({label}): req_id={req_id}")

    # 응답 파일로 저장 (poll에서 읽음)
    path = _reply_path(req_id)
    if is_partial:
        # partial: 기존 파일에 추가
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    existing = json.load(f)
            except Exception:
                pass
        partials = existing.get("partial_replies", [])
        partials.append(text_content)
        existing["partial_replies"] = partials
        existing["status"] = "partial"
        existing["updated_at"] = time.time()
        with open(path, "w") as f:
            json.dump(existing, f, ensure_ascii=False)
    else:
        # 최종 응답
        reply_data = {
            "reply": text_content,
            "status": "done",
            "updated_at": time.time(),
        }
        with open(path, "w") as f:
            json.dump(reply_data, f, ensure_ascii=False)

        # 히스토리 저장
        if ch_session_id and ch_user_text:
            _append_history(ch_session_id, ch_user_text, text_content)
            logger.info(f"[channel] history saved: {req_id}, session={ch_session_id}")

    return jsonify({"ok": True})


@channel_chat_bp.route("/health")
@login_required
def channel_health():
    alive = 0
    for url in CHANNEL_URLS:
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code in (200, 405):
                alive += 1
        except Exception:
            pass
    return jsonify({
        "alive": alive > 0,
        "workers_alive": alive,
        "workers_total": len(CHANNEL_URLS),
    })


@channel_chat_bp.route("/history")
@login_required
def chat_history():
    erp_user = session.get("username", "anonymous")
    session_id = f"channel_{erp_user}"
    return jsonify(_load_history(session_id))


@channel_chat_bp.route("/")
@login_required
def chat_page():
    return render_template("channel_chat.html")


@channel_chat_bp.route("/send", methods=["POST"])
@login_required
def chat_send():
    body = request.get_json(silent=True) or {}
    text_content = (body.get("text") or "").strip()
    if not text_content:
        return jsonify({"error": "메시지 없음"}), 400

    if text_content in ("초기화", "대화초기화", "/reset", "리셋"):
        erp_user = session.get("username", "anonymous")
        _save_history(f"channel_{erp_user}", [])
        return jsonify({"reply": "대화 기록을 초기화했습니다."})

    erp_user = session.get("username", "anonymous")
    session_id = f"channel_{erp_user}"
    req_id = uuid.uuid4().hex[:8]

    logger.info(f"[channel] /send: req_id={req_id}, user={erp_user}, text={text_content[:30]}")

    # 빈 응답 파일 생성 (poll에서 대기 시작점)
    with open(_reply_path(req_id), "w") as f:
        json.dump({"status": "waiting", "created_at": time.time()}, f)

    allowed = _get_allowed_tools(erp_user)
    allowed_str = ", ".join(sorted(allowed))

    # 워커 풀에 셔플 순서로 분배 → 응답한 워커에 배정. 죽은 워커는 자동 우회.
    payload = {
        "request_id": req_id,
        "user": erp_user,
        "session_id": session_id,
        "text": text_content,
        "allowed_tools": allowed_str,
    }
    worker_urls = list(CHANNEL_URLS)
    random.shuffle(worker_urls)
    last_err = None
    for url in worker_urls:
        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info(f"[channel] /send dispatched: req_id={req_id} → {url}")
                return jsonify({"request_id": req_id, "status": "pending"})
            last_err = f"{url} → HTTP {resp.status_code}"
        except requests.ConnectionError:
            last_err = f"{url} 연결 실패"
        except Exception as e:
            last_err = f"{url} → {e}"
        logger.warning(f"[channel] worker unavailable: {last_err}")

    # 전체 워커 실패
    try:
        os.remove(_reply_path(req_id))
    except Exception:
        pass
    return jsonify({"error": f"채널 워커에 연결할 수 없습니다({last_err}). Claude Code 세션을 확인하세요."}), 502


@channel_chat_bp.route("/poll", methods=["POST"])
@login_required
def chat_poll():
    body = request.get_json(silent=True) or {}
    req_id = body.get("request_id", "")

    path = _reply_path(req_id)
    if not os.path.exists(path):
        return jsonify({"status": "not_found"}), 404

    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return jsonify({"status": "waiting", "elapsed": 0})

    created = data.get("created_at", time.time())
    elapsed = time.time() - created

    # partial 확인
    partials = data.get("partial_replies", [])
    if partials:
        first = partials.pop(0)
        data["partial_replies"] = partials
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        return jsonify({"status": "partial", "reply": first, "elapsed": int(elapsed)})

    # 최종 응답
    if data.get("status") == "done" and data.get("reply"):
        reply = data["reply"]
        try:
            os.remove(path)
        except Exception:
            pass
        return jsonify({"status": "done", "reply": reply})

    # 타임아웃
    if elapsed > REPLY_TIMEOUT:
        try:
            os.remove(path)
        except Exception:
            pass
        return jsonify({"status": "timeout", "reply": "응답 시간이 초과되었습니다. Claude Code 세션을 확인하세요."})

    return jsonify({"status": "waiting", "elapsed": int(elapsed)})


# ══════════════════════════════════════════════════════════════════════
# 봇 전용 엔드포인트 (2026-07-09 추가)
#   - X-Bot-Token 헤더로 '신뢰된 봇에서 온 요청'만 통과(전송 신뢰).
#   - 권한은 봇이 아니라 요청에 실린 kakao_user_id(실사용자)로 서버가 계산.
#     → 봇이 보낸 erp_user/allowed_tools 는 신뢰하지 않음(위조·상향 방지).
#   - session_id = kakao_<erp_user> (웹 channel_<erp_user> 히스토리와 분리).
# ══════════════════════════════════════════════════════════════════════
import hmac as _hmac

_BOT_TOKEN = os.environ.get("KAKAO_CHANNEL_BOT_TOKEN", "")


def _check_bot_token(req):
    tok = req.headers.get("X-Bot-Token", "")
    return bool(_BOT_TOKEN) and _hmac.compare_digest(tok, _BOT_TOKEN)


def _resolve_kakao_user(kakao_uid):
    """kakao_user_id → (erp_user, allowed_tools, channel_enabled). 미매핑=(None,None,None).
    권한은 반드시 서버가 이 함수로 계산(클라이언트 입력 불신)."""
    from sqlalchemy import text
    with _get_engine().begin() as conn:
        m = conn.execute(
            text("SELECT erp_username FROM kakao_user_mapping WHERE kakao_user_id = :k"),
            {"k": str(kakao_uid)}).fetchone()
        if not (m and m[0]):
            return None, None, None
        erp_user = m[0]
        p = conn.execute(
            text("SELECT COALESCE(channel_enabled, false) FROM chatbot_permissions WHERE erp_username = :u"),
            {"u": erp_user}).fetchone()
        channel_enabled = bool(p and p[0])
    allowed = _get_allowed_tools(erp_user)
    return erp_user, allowed, channel_enabled


@channel_chat_bp.route("/bot-send", methods=["POST"])
def bot_send():
    if not _check_bot_token(request):
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    kakao_uid = str(data.get("kakao_user_id", "")).strip()
    text_content = (data.get("text") or "").strip()
    if not kakao_uid or not text_content:
        return jsonify({"error": "kakao_user_id/text 필요"}), 400

    erp_user, allowed, channel_enabled = _resolve_kakao_user(kakao_uid)
    if not erp_user:
        return jsonify({"status": "skip", "reason": "unmapped"}), 200
    if not channel_enabled:
        return jsonify({"status": "skip", "reason": "channel_disabled", "erp_user": erp_user}), 200
    if not allowed:
        return jsonify({"status": "skip", "reason": "no_allowed_tools", "erp_user": erp_user}), 200

    session_id = f"kakao_{erp_user}"
    req_id = uuid.uuid4().hex[:8]
    with open(_reply_path(req_id), "w") as f:
        json.dump({"status": "waiting", "created_at": time.time()}, f)

    payload = {
        "request_id": req_id,
        "user": erp_user,
        "session_id": session_id,
        "text": text_content,
        "allowed_tools": ", ".join(sorted(allowed)),
    }
    worker_urls = list(CHANNEL_URLS)
    random.shuffle(worker_urls)
    last_err = None
    for url in worker_urls:
        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info(f"[channel] /bot-send dispatched: req_id={req_id} user={erp_user} → {url}")
                return jsonify({"request_id": req_id, "status": "pending", "erp_user": erp_user})
            last_err = f"{url} → HTTP {resp.status_code}"
        except Exception as e:
            last_err = f"{url} → {e}"
        logger.warning(f"[channel] bot worker unavailable: {last_err}")
    try:
        os.remove(_reply_path(req_id))
    except Exception:
        pass
    return jsonify({"error": f"채널 워커 연결 실패({last_err})"}), 502


@channel_chat_bp.route("/bot-poll", methods=["POST"])
def bot_poll():
    if not _check_bot_token(request):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    req_id = body.get("request_id", "")
    path = _reply_path(req_id)
    if not os.path.exists(path):
        return jsonify({"status": "not_found"}), 404
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return jsonify({"status": "waiting"})
    created = data.get("created_at", time.time())
    elapsed = time.time() - created
    if data.get("status") == "done" and data.get("reply"):
        reply = data["reply"]
        try:
            os.remove(path)
        except Exception:
            pass
        return jsonify({"status": "done", "reply": reply})
    if elapsed > REPLY_TIMEOUT:
        try:
            os.remove(path)
        except Exception:
            pass
        return jsonify({"status": "timeout"})
    return jsonify({"status": "waiting", "elapsed": int(elapsed)})
