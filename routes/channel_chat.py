"""Claude Channel 채팅 — Channel 서버 경유 Claude Code 연동

기존 /chatbot (Groq) 과 별개로 동작.
Flask → Channel HTTP (8788) → Claude Code CLI → reply tool → Flask callback

v2: 폴링 기반 비동기 응답 — send()는 즉시 request_id 반환,
    프론트가 /poll로 응답 대기 (타임아웃 내성 강화)
"""
import json
import logging
import threading
import time
import uuid

import requests
from flask import Blueprint, render_template, request, jsonify, session

from modules.auth_decorators import login_required
from routes.chatbot import _get_allowed_tools

logger = logging.getLogger(__name__)
channel_chat_bp = Blueprint("channel_chat", __name__, url_prefix="/channel-chat")

CHANNEL_URL = "http://127.0.0.1:8788"
REPLY_TIMEOUT = 180  # 최대 대기 초 (60→180)
POLL_WAIT = 10       # 롱폴링 1회 대기 초
MAX_HISTORY = 30     # 최대 메시지 수 (15회 대화)

# 응답 대기 저장소: { request_id: {"reply": str|None, "event": Event, "created": float} }
_pending = {}


def _cleanup_old(max_age=300):
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
    import datetime as _dt
    now = _dt.datetime.now().isoformat()
    history = _load_history(session_id)
    history.append({"role": "user", "content": user_text, "ts": now})
    history.append({"role": "assistant", "content": reply_text, "ts": now})
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

    logger.info(f"[channel] channel-reply called: req_id={req_id[:8]}, pending_keys={list(_pending.keys())[:5]}")
    if req_id in _pending:
        _pending[req_id]["reply"] = text
        _pending[req_id]["event"].set()
        logger.info(f"[channel] reply matched: {req_id[:8]}")
        return jsonify({"ok": True})

    # request_id가 없어도 최근 pending 중 아직 미응답인 것에 매칭 시도
    # (타이밍 이슈로 request_id 불일치 시 fallback)
    for pid, pdata in _pending.items():
        if pdata.get("reply") is None and not pdata["event"].is_set():
            pdata["reply"] = text
            pdata["event"].set()
            logger.info(f"[channel] reply fallback matched: {req_id[:8]} → {pid[:8]}")
            return jsonify({"ok": True, "fallback": True})

    logger.warning(f"[channel] unknown request_id: {req_id[:8]}...")
    return jsonify({"ok": False, "reason": "unknown request_id"}), 404


# ── Channel 서버 상태 확인 ────────────────────────────────────────────
@channel_chat_bp.route("/health")
@login_required
def channel_health():
    """Channel 서버(Claude Code) 연결 상태를 빠르게 확인."""
    try:
        resp = requests.get(f"{CHANNEL_URL}", timeout=2)
        # channel.mjs는 POST만 받으므로 405=서버 살아있음
        alive = resp.status_code in (200, 405)
    except Exception:
        alive = False
    return jsonify({"alive": alive})


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


# ── 메시지 전송 (비동기 — 즉시 request_id 반환) ─────────────────────
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
    _pending[req_id] = {
        "reply": None,
        "event": event,
        "created": time.time(),
        "user": erp_user,
        "session_id": session_id,
        "user_text": text,
    }

    # 사용자 허용 도구 조회
    allowed = _get_allowed_tools(erp_user)
    allowed_str = ", ".join(sorted(allowed))

    # Channel 서버에 전송 (허용 도구 목록 포함)
    try:
        resp = requests.post(
            CHANNEL_URL,
            json={
                "request_id": req_id,
                "user": erp_user,
                "session_id": session_id,
                "text": text,
                "allowed_tools": allowed_str,
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

    # 비동기 모드: 즉시 request_id 반환 (프론트가 /poll로 대기)
    return jsonify({"request_id": req_id, "status": "pending"})


# ── 폴링 응답 대기 (롱폴링) ──────────────────────────────────────────
@channel_chat_bp.route("/poll", methods=["POST"])
@login_required
def chat_poll():
    """프론트가 request_id로 응답 도착 여부를 폴링. 롱폴링 방식."""
    body = request.get_json(silent=True) or {}
    req_id = body.get("request_id", "")

    if req_id not in _pending:
        return jsonify({"status": "not_found"}), 404

    entry = _pending[req_id]
    elapsed = time.time() - entry["created"]

    # 이미 응답 도착
    if entry["reply"] is not None:
        reply = entry["reply"]
        user_text = entry.get("user_text", "")
        session_id = entry.get("session_id", "")
        _pending.pop(req_id, None)
        _append_history(session_id, user_text, reply)
        return jsonify({"status": "done", "reply": reply})

    # 타임아웃 초과
    if elapsed > REPLY_TIMEOUT:
        _pending.pop(req_id, None)
        return jsonify({"status": "timeout", "reply": "응답 시간이 초과되었습니다. Claude Code 세션을 확인하세요."})

    # 롱폴링 대기 (최대 POLL_WAIT초)
    got = entry["event"].wait(timeout=POLL_WAIT)
    if got and entry["reply"] is not None:
        reply = entry["reply"]
        user_text = entry.get("user_text", "")
        session_id = entry.get("session_id", "")
        _pending.pop(req_id, None)
        _append_history(session_id, user_text, reply)
        return jsonify({"status": "done", "reply": reply})

    # 아직 대기중 — 경과 시간 알려줌
    return jsonify({"status": "waiting", "elapsed": int(elapsed)})
