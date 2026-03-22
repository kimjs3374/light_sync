"""ERP 챗봇 — 웹 채팅 UI + 권한 관리"""
import logging
from flask import Blueprint, request, jsonify, render_template, session

from modules.db_context import get_db
from modules.models.entities import User
from modules.services.erp_chatbot import process_chat
from modules.services.erp_tools import ALL_TOOLS

logger = logging.getLogger(__name__)
chatbot_bp = Blueprint("chatbot", __name__, url_prefix="/chatbot")

DEFAULT_TOOLS = ",".join(t[0] for t in ALL_TOOLS)  # 기본: 전체 허용


def _get_allowed_tools(erp_username: str) -> set[str]:
    from sqlalchemy import text
    with get_db() as db:
        row = db.execute(
            text("SELECT allowed_tools FROM chatbot_permissions WHERE erp_username = :u"),
            {"u": erp_username}
        ).fetchone()
    if row and row[0]:
        return set(row[0].split(","))
    return set(DEFAULT_TOOLS.split(","))


def _build_tool_groups():
    """ALL_TOOLS를 주석 기반 카테고리로 그룹핑"""
    import re
    import inspect
    # erp_tools.py 소스에서 주석으로 카테고리 파싱
    from modules.services import erp_tools
    src = inspect.getsource(erp_tools)
    groups = []
    current_cat = "기타"
    tool_set = {t[0] for t in ALL_TOOLS}
    cat_tools = []

    for line in src.splitlines():
        m = re.match(r'\s*#\s*(.+?)\s*\(\d+\)', line)
        if m:
            if cat_tools:
                groups.append((current_cat, cat_tools))
            current_cat = m.group(1).strip()
            cat_tools = []
            continue
        m2 = re.match(r'\s*\("(\w+)"', line)
        if m2 and m2.group(1) in tool_set:
            name = m2.group(1)
            label = next((t[1] for t in ALL_TOOLS if t[0] == name), name)
            group = next((t[2] for t in ALL_TOOLS if t[0] == name), "전체")
            cat_tools.append((name, label, group))
    if cat_tools:
        groups.append((current_cat, cat_tools))
    return groups


def _is_channel_enabled(erp_username: str) -> bool:
    """사용자의 채널 사용 권한 확인"""
    from sqlalchemy import text
    with get_db() as db:
        row = db.execute(
            text("SELECT channel_enabled FROM chatbot_permissions WHERE erp_username = :u"),
            {"u": erp_username}
        ).fetchone()
    return bool(row and row[0])


# ── 채팅 페이지 ──────────────────────────────────────────────────────────

@chatbot_bp.route("/")
def chat_page():
    if not session.get("username"):
        return "", 302, {"Location": "/auth/login"}
    channel_ok = _is_channel_enabled(session["username"])
    return render_template("chatbot.html", channel_enabled=channel_ok)


@chatbot_bp.route("/history")
def chat_history():
    if not session.get("username"):
        return jsonify([])
    from modules.services.erp_chatbot import _load_history
    session_id = f"web_{session['username']}"
    return jsonify(_load_history(session_id))


@chatbot_bp.route("/channel-allowed")
def channel_allowed():
    """프론트에서 채널 권한 확인용 API (슬라이드 패널용)"""
    username = session.get("username")
    if not username:
        return jsonify({"allowed": False})
    try:
        result = _is_channel_enabled(username)
    except Exception:
        logger.exception("channel_allowed: DB 오류 username=%s", username)
        result = False
    logger.debug("channel_allowed: username=%s allowed=%s", username, result)
    return jsonify({"allowed": result})


@chatbot_bp.route("/send", methods=["POST"])
def chat_send():
    if not session.get("username"):
        return jsonify({"error": "로그인 필요"}), 403
    erp_user = session["username"]
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "메시지 없음"}), 400
    allowed = _get_allowed_tools(erp_user)
    session_id = f"web_{erp_user}"
    reply = process_chat(text, erp_user, session_id, allowed)
    return jsonify({"reply": reply})


# ── 권한 관리 ──────────────────────────────────────────────────────────

@chatbot_bp.route("/admin")
def admin_page():
    if session.get("role") != "admin":
        return "권한 없음", 403
    with get_db() as db:
        users = db.query(User).order_by(User.full_name).all()
        from sqlalchemy import text
        rows = db.execute(
            text("SELECT erp_username, allowed_tools, COALESCE(channel_enabled, false) FROM chatbot_permissions")
        ).fetchall()
    perm_map = {r[0]: r[1].split(",") if r[1] else [] for r in rows}
    channel_map = {r[0]: bool(r[2]) for r in rows}

    # 카테고리별 그룹핑
    tool_groups = _build_tool_groups()

    # 프리셋
    presets = _load_presets()

    return render_template("chatbot_admin.html",
                           users=users, chatbot_users=users,
                           perm_map=perm_map, all_tools=ALL_TOOLS,
                           default_tools=DEFAULT_TOOLS.split(","),
                           channel_map=channel_map, tool_groups=tool_groups,
                           presets=presets, chatbot_presets=presets,
                           presets_map={p["name"]: p for p in presets})


@chatbot_bp.route("/admin/save", methods=["POST"])
def admin_save():
    if session.get("role") != "admin":
        return jsonify({"success": False}), 403
    body = request.get_json(silent=True) or {}
    erp_username = body.get("erp_username", "").strip()
    allowed_tools = ",".join(body.get("allowed_tools") or [])
    channel_enabled = bool(body.get("channel_enabled", False))
    from sqlalchemy import text
    with get_db() as db:
        db.execute(text("""
            INSERT INTO chatbot_permissions (erp_username, allowed_tools, channel_enabled)
            VALUES (:u, :t, :c)
            ON CONFLICT (erp_username) DO UPDATE SET allowed_tools = :t, channel_enabled = :c
        """), {"u": erp_username, "t": allowed_tools, "c": channel_enabled})
        db.commit()
    return jsonify({"success": True})


def _load_presets():
    """chatbot_presets 테이블에서 프리셋 목록 조회"""
    import json as _json
    from sqlalchemy import text
    with get_db() as db:
        try:
            rows = db.execute(text("SELECT name, tools_json, channel_enabled FROM chatbot_presets ORDER BY name")).fetchall()
        except Exception:
            return []
    return [{"name": r[0], "tools": _json.loads(r[1]) if r[1] else [], "channel": bool(r[2])} for r in rows]


@chatbot_bp.route("/admin/preset/save", methods=["POST"])
def preset_save():
    if session.get("role") != "admin":
        return jsonify({"success": False}), 403
    import json as _json
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    tools = body.get("tools") or []
    channel = bool(body.get("channel", False))
    if not name:
        return jsonify({"success": False}), 400
    from sqlalchemy import text
    with get_db() as db:
        db.execute(text("""
            INSERT INTO chatbot_presets (name, tools_json, channel_enabled)
            VALUES (:n, :t, :c)
            ON CONFLICT (name) DO UPDATE SET tools_json = :t, channel_enabled = :c
        """), {"n": name, "t": _json.dumps(tools), "c": channel})
        db.commit()
    return jsonify({"success": True})


@chatbot_bp.route("/admin/preset/delete", methods=["POST"])
def preset_delete():
    if session.get("role") != "admin":
        return jsonify({"success": False}), 403
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"success": False}), 400
    from sqlalchemy import text
    with get_db() as db:
        db.execute(text("DELETE FROM chatbot_presets WHERE name = :n"), {"n": name})
        db.commit()
    return jsonify({"success": True})


@chatbot_bp.route("/admin/preset/apply-all", methods=["POST"])
def preset_apply_all():
    """프리셋을 권한 미설정 사용자에게 일괄 적용"""
    if session.get("role") != "admin":
        return jsonify({"success": False}), 403
    import json as _json
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"success": False}), 400
    from sqlalchemy import text
    with get_db() as db:
        row = db.execute(text("SELECT tools_json, channel_enabled FROM chatbot_presets WHERE name = :n"), {"n": name}).fetchone()
        if not row:
            return jsonify({"success": False, "error": "프리셋 없음"}), 404
        tools_csv = ",".join(_json.loads(row[0])) if row[0] else DEFAULT_TOOLS
        channel = bool(row[1])
        existing = {r[0] for r in db.execute(text("SELECT erp_username FROM chatbot_permissions")).fetchall()}
        users = db.query(User).all()
        count = 0
        for u in users:
            if u.username not in existing:
                db.execute(text("""
                    INSERT INTO chatbot_permissions (erp_username, allowed_tools, channel_enabled)
                    VALUES (:u, :t, :c)
                """), {"u": u.username, "t": tools_csv, "c": channel})
                count += 1
        db.commit()
    return jsonify({"success": True, "count": count})
