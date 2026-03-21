"""Claude Channel 채팅 — Channel 서버 경유 Claude Code 연동

기존 /chatbot (Groq) 과 별개로 동작.
Flask → Channel HTTP (8788) → Claude Code CLI → reply tool → Flask callback
"""
import json
import logging
import threading
import time
import uuid

import requests
from flask import Blueprint, render_template, request, jsonify, session

from modules.auth_decorators import login_required

logger = logging.getLogger(__name__)
channel_chat_bp = Blueprint("channel_chat", __name__, url_prefix="/channel-chat")

CHANNEL_URL = "http://127.0.0.1:8788"
REPLY_TIMEOUT = 60  # 최대 대기 초
MAX_HISTORY = 30    # 최대 메시지 수 (15회 대화)

# 응답 대기 저장소: { request_id: {"reply": str|None, "event": Event} }
_pending = {}


def _cleanup_old(max_age=120):
    now = time.time()
    expired = [k for k, v in _pending.items() if now - v.get("created", 0) > max_age]
    for k in expired:
        _pending.pop(k, None)


# ── 히스토리 저장/로드 (chatbot_history 테이블 재활용) ──────────────────
def _load_history(session_id):
    from modules.models.db import engine
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
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
    from modules.models.db import engine
    from sqlalchemy import text
    try:
        payload = json.dumps(history, ensure_ascii=False)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO chatbot_history (session_id, messages_json, updated_at)
                VALUES (:s, :m, NOW())
                ON CONFLICT (session_id) DO UPDATE SET messages_json = :m, updated_at = NOW()
            """), {"s": session_id, "m": payload})
    except Exception as e:
        logger.error(f"[channel] history save fail: {e}")


def _append_history(session_id, user_text, reply_text):
    history = _load_history(session_id)
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply_text})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    _save_history(session_id, history)


# ── Channel 응답 수신 (Channel reply tool → Flask) ─────────────────────
@channel_chat_bp.route("/channel-reply", methods=["POST"])
def channel_reply():
    """Channel 서버의 reply tool이 호출하는 콜백. CSRF 면제 (app.py)."""
    data = request.get_json(silent=True) or {}
    req_id = data.get("request_id", "")
    text = data.get("text", "")

    if req_id in _pending:
        _pending[req_id]["reply"] = text
        _pending[req_id]["event"].set()
        logger.info(f"[channel] reply received: {req_id[:8]}...")
        return jsonify({"ok": True})

    logger.warning(f"[channel] unknown request_id: {req_id[:8]}...")
    return jsonify({"ok": False, "reason": "unknown request_id"}), 404


# ── 히스토리 조회 ─────────────────────────────────────────────────────
@channel_chat_bp.route("/history")
@login_required
def chat_history():
    erp_user = session.get("username", "anonymous")
    session_id = f"channel_{erp_user}"
    return jsonify(_load_history(session_id))


# ── 채팅 페이지 ──────────────────────────────────────────────────────
@channel_chat_bp.route("/")
@login_required
def chat_page():
    return render_template("channel_chat.html")


# ── 메시지 전송 ──────────────────────────────────────────────────────
@channel_chat_bp.route("/send", methods=["POST"])
@login_required
def chat_send():
    _cleanup_old()

    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "메시지 없음"}), 400

    # 초기화 명령
    if text in ("초기화", "대화초기화", "/reset", "리셋"):
        erp_user = session.get("username", "anonymous")
        _save_history(f"channel_{erp_user}", [])
        return jsonify({"reply": "대화 기록을 초기화했습니다."})

    erp_user = session.get("username", "anonymous")
    session_id = f"channel_{erp_user}"
    req_id = uuid.uuid4().hex[:12]

    # pending 등록
    event = threading.Event()
    _pending[req_id] = {"reply": None, "event": event, "created": time.time()}

    # Channel 서버에 전송
    try:
        resp = requests.post(
            CHANNEL_URL,
            json={
                "request_id": req_id,
                "user": erp_user,
                "session_id": session_id,
                "text": text,
            },
            timeout=5,
        )
        if resp.status_code != 200:
            _pending.pop(req_id, None)
            return jsonify({"error": f"Channel 서버 오류: {resp.status_code}"}), 502
    except requests.ConnectionError:
        _pending.pop(req_id, None)
        return jsonify({"error": "Channel 서버에 연결할 수 없습니다. Claude Code가 실행 중인지 확인하세요."}), 502
    except Exception as e:
        _pending.pop(req_id, None)
        return jsonify({"error": str(e)}), 500

    # 응답 대기
    got_reply = event.wait(timeout=REPLY_TIMEOUT)
    reply = _pending.pop(req_id, {}).get("reply")

    if got_reply and reply:
        _append_history(session_id, text, reply)
        return jsonify({"reply": reply})
    else:
        return jsonify({"reply": "응답 시간이 초과되었습니다. Claude Code 세션을 확인하세요."})
