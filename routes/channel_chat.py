"""Claude Channel 채팅 — Channel 서버 경유 Claude Code 연동

v5: pending 제거 — channel.mjs가 reply 시 원본 메타(session_id, user_text)를
    함께 전달하므로 worker 간 상태 공유 불필요.
    /send → channel 전송 → channel-reply에서 히스토리 저장 + 응답 저장
    /poll → 응답 파일 확인
"""
import json
import logging
import os
import time
import uuid

import requests
from flask import Blueprint, render_template, request, jsonify, session

from modules.auth_decorators import login_required
from routes.chatbot import _get_allowed_tools

logger = logging.getLogger(__name__)
channel_chat_bp = Blueprint("channel_chat", __name__, url_prefix="/channel-chat")

CHANNEL_URL = "http://127.0.0.1:8788"
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
    try:
        resp = requests.get(f"{CHANNEL_URL}", timeout=2)
        alive = resp.status_code in (200, 405)
    except Exception:
        alive = False
    return jsonify({"alive": alive})


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

    try:
        resp = requests.post(
            CHANNEL_URL,
            json={
                "request_id": req_id,
                "user": erp_user,
                "session_id": session_id,
                "text": text_content,
                "allowed_tools": allowed_str,
            },
            timeout=5,
        )
        if resp.status_code != 200:
            os.remove(_reply_path(req_id))
            return jsonify({"error": f"Channel 서버 오류: {resp.status_code}"}), 502
    except requests.ConnectionError:
        os.remove(_reply_path(req_id))
        return jsonify({"error": "Channel 서버에 연결할 수 없습니다. Claude Code가 실행 중인지 확인하세요."}), 502
    except Exception as e:
        os.remove(_reply_path(req_id))
        return jsonify({"error": str(e)}), 500

    return jsonify({"request_id": req_id, "status": "pending"})


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
