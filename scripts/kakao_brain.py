#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카카오워크 → ERP 두뇌 브리지 (Claude Code + light-sync-erp MCP, 독립 실행).

Windows 봇 호스트가 SSH로 호출:
    claude 로그인된 서버에서
    ./venv/bin/python scripts/kakao_brain.py <kakao_user_id> <base64_utf8_text>

동작:
  1) kakao_user_mapping -> erp_username (신원)
  2) chatbot_permissions[erp_username] -> channel_enabled / allowed_tools (권한·도구, 단일 출처)
     - kakao_user_mapping.allowed_tools 가 있으면 우선(개별 오버라이드)
     - 채널 미허용이면 응답 생략(침묵)
     - 허용 도구는 읽기전용(ALL_TOOLS)과 교집합만 → write_ops 등 배제
  3) claude -p <질문> --mcp-config mcp-erp-only.json --output-format json 으로
     Claude가 ERP MCP 도구를 호출해 응답 생성 (Groq 아님)
  4) JSON 한 줄 stdout: {"reply": "...", "erp_user": "..."} / {"error": "..."}

대화 맥락(2026-07-09 추가):
  - 사용자별 claude 세션 id 를 kakao_sessions.json 에 기억.
  - 이어지는 질문은 `--resume <session_id>` 로 이전 맥락 유지(우린 새 메시지 한 줄만 전송).
  - 만료: 마지막 응답으로부터 SESSION_TTL(기본 2시간) 초과 또는 MAX_TURNS(기본 40) 초과 시 새 세션.
"""
import sys
import os
import time
import uuid
import base64
import json
import subprocess

APP_ROOT = "/web/light_sync"
sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

import config  # noqa: F401  # load_dotenv(override=True)

from sqlalchemy import text as _sqltext
from modules.db_context import get_db
from modules.services.erp_tools import ALL_TOOLS

ALL_TOOL_NAMES = {t[0] for t in ALL_TOOLS}          # 읽기전용 ERP 도구 화이트리스트
MCP_CONFIG = os.path.join(APP_ROOT, "scripts", "mcp-erp-only.json")
MCP_PREFIX = "mcp__light-sync-erp__"
CLAUDE_MODEL = os.environ.get("KAKAO_CLAUDE_MODEL", "sonnet")
CLAUDE_TIMEOUT = int(os.environ.get("KAKAO_CLAUDE_TIMEOUT", "150"))
IGNORE_CHANNEL_GATE = os.environ.get("KAKAO_IGNORE_CHANNEL_GATE", "0").strip() in ("1", "true", "True")

# ── 대화 맥락(세션 재사용) 설정 ──
# 사용자별 파일(kakao_sessions/<uid>.json). 동시 실행돼도 서로 다른 파일이라 레이스 없음.
# (같은 사용자 동시 2건은 봇이 in-flight 가드로 막으므로 한 파일에 동시 쓰기도 없음.)
SESSION_DIR = os.path.join(APP_ROOT, "scripts", "kakao_sessions")
SESSION_TTL = int(os.environ.get("KAKAO_SESSION_TTL", "7200"))   # 초. 기본 2시간
MAX_TURNS = int(os.environ.get("KAKAO_MAX_TURNS", "40"))         # 세션당 최대 왕복 수

# 사용자별 격리 = --session-id(신규 UUID)/--resume(이어가기) 세션 transcript.
# 메모리 격리: 봇 전용 CLAUDE_CONFIG_DIR(bkit 플러그인 비활성) 사용 → 팀 dev용 자동메모리와
#   완전 분리 + bkit auto-memory 자체가 안 뜸(enabledPlugins:{}, extraKnownMarketplaces:{}).
#   OAuth 자격은 이 디렉토리의 .credentials.json 심볼릭으로 유지. 팀 ~/.claude 는 안 건드림.
BOT_CONFIG_DIR = "/web/light_sync/.claude_bot"

# 차량 계기판 참고사진 등록소 — 사진으로 차량 자동 인식용.
VEHICLE_REF_DIR = os.path.join(APP_ROOT, "vehicle_refs")
VEHICLE_REF_JSON = os.path.join(VEHICLE_REF_DIR, "refs.json")


def _load_vehicle_refs():
    """{차량명: 참고 이미지 절대경로} — 존재하는 파일만."""
    try:
        with open(VEHICLE_REF_JSON, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    out = {}
    for veh, rel in raw.items():
        p = rel if os.path.isabs(rel) else os.path.join(VEHICLE_REF_DIR, rel)
        if os.path.exists(p):
            out[veh] = p
    return out

SYSTEM_PROMPT = (
    "너는 매그나텍 사내 ERP 비서 'AX'다. 사용자의 질문에 반드시 제공된 light-sync-erp "
    "MCP 도구로 ERP 데이터를 조회해 한국어로 간결하고 정확하게 답한다. "
    "카카오워크 채팅 답변이므로 장황한 표 대신 핵심 위주로 요약한다. "
    "도구 조회 결과에 근거해서만 답하고, 데이터가 없으면 없다고 말한다. "
    "단, 날씨·기온·환율·주가·뉴스·교통·스포츠·일반상식 등 ERP와 무관한 실시간/일반 정보를 물으면 'ERP에 없다'고 하지 말고 WebSearch/WebFetch 로 즉시 조회해 최신 정보를 근거와 함께 간결히 답한다. 이때도 카카오워크 채팅답변답게 핵심만 짧게. "
    "머리말·설명 없이 답변 본문만 출력한다. "
    "★차량 계기판 사진을 받으면: 총주행거리(주행 후 계기판=odometer_end, 예 56749km)를 정확히 읽고 "
    "write_preview_vehicle_log 로 운행일지 등록을 시작한다. 목적지·출발지·목적·차량 등 부족한 정보는 "
    "사용자에게 하나씩 되물어 채운다(운전자는 서버가 본인으로 자동 지정하니 묻지 마라). "
    "필드가 다 모여 preview(session_token 포함)가 나오면 요약을 보여주고, 사용자가 '등록/네/맞아' 등으로 "
    "동의하면 confirm_vehicle_log(session_token) 로 실제 등록한다. 동의 전엔 절대 confirm 하지 마라. "
    "★'OO 출장 운행일지 써줘'처럼 출장 기준으로 요청하면: 먼저 get_business_trips(search=\"OO\")로 "
    "trip_id 를 찾고, write_preview_vehicle_log(from_trip_id=그 id, 거리 또는 계기판)로 시작한다. "
    "차량·목적지·목적·날짜·출발지(본사)는 출장에서 자동으로 채워지니 거리(또는 계기판)만 받으면 된다. "
    "후보 출장이 여러 건이면 어느 출장인지 하나 골라 되묻는다. "
    "★업무 등록/신청/처리(쓰기) 요청 처리: 사용자가 '등록/신청/처리해줘' 등 기록 생성을 요청하면 "
    "해당 write_preview_* 도구를 호출한다. "
    "  · 출장 등록/잡아줘 → write_preview_business_trip(destination, departure_date, departure_time, travelers, purpose, vehicle, return_date, return_time, include_requester) "
    "    (출장자는 사용자가 말한 이름 그대로. 단 사용자가 '나/저/제가/나도/우리/본인/같이/함께' 처럼 자기도 간다고 하면 반드시 include_requester=true 로 발신자 본인을 포함시킨다. 예: '나 문정훈하고 출장' → travelers=\"문정훈\", include_requester=true) "
    "  · 휴가/반차/연차 신청 → write_preview_leave_request "
    "  · 업무일지/일일보고 작성 → write_preview_daily_report "
    "  · 납품완료 처리 → write_preview_delivery_complete / AS·하자 접수 → write_preview_as_register / "
    "청구·세금계산서 발행 → write_preview_billing_complete / 발주 상태변경 → write_preview_po_status / "
    "생산완료 → write_preview_production_complete(_all) / 메일 발송 → write_preview_email_send "
    "write_preview_* 는 미리보기(session_token 포함)만 만든다. 결과가 status=needs_info 면 무엇이 "
    "부족한지 물어 채우고(절대 임의로 지어내지 마라), preview 가 나오면 요약을 보여준 뒤 사용자가 "
    "'네/응/등록/맞아' 등으로 동의하면 그때 confirm_write(session_token) 로 실제 반영한다. "
    "동의 전엔 절대 confirm 하지 마라. 운행일지는 confirm_vehicle_log, 휴가는 confirm_leave_request 도 쓸 수 있다. "
    "신원(기안자/출장자/운전자)은 서버가 로그인 사용자로 강제하므로 본인 명의로만 등록된다."
)


def _q(sql, params):
    with get_db() as db:
        return db.execute(_sqltext(sql), params).fetchone()


def _default_tools():
    row = _q("SELECT tools_json FROM chatbot_presets WHERE name = :n", {"n": "일반직원"})
    if row and row[0]:
        try:
            return set(json.loads(row[0]))
        except Exception:
            pass
    return set(ALL_TOOL_NAMES)


def resolve(kakao_uid: str):
    """(erp_user, allowed_tools set(읽기전용), channel_enabled) 또는 (None,None,None).

    도구 권한 단일 출처 = chatbot_permissions[erp_username]. (kakao_user_mapping.allowed_tools 는
    무시 — 과거 짧은 목록이 박혀 있어 도구가 부당하게 막히는 문제 방지.)
    """
    m = _q("SELECT erp_username FROM kakao_user_mapping WHERE kakao_user_id = :k",
           {"k": str(kakao_uid)})
    if not (m and m[0]):
        return None, None, None
    erp_user = m[0]
    p = _q("SELECT allowed_tools, COALESCE(channel_enabled, false) "
           "FROM chatbot_permissions WHERE erp_username = :u", {"u": erp_user})
    channel_enabled = bool(p and p[1])
    perm_tools = set(p[0].split(",")) if (p and p[0]) else None
    allowed = perm_tools or _default_tools()
    allowed = {t for t in allowed if t in ALL_TOOL_NAMES}  # 읽기전용만
    return erp_user, allowed, channel_enabled


# ── 세션 저장소(사용자별 파일). 동시성 안전(파일이 분리됨). ──
def _session_file(kakao_uid):
    return os.path.join(SESSION_DIR, f"{kakao_uid}.json")


def _load_session(kakao_uid):
    try:
        with open(_session_file(kakao_uid), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_session(kakao_uid, data):
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        path = _session_file(kakao_uid)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass  # 저장 실패해도 응답엔 지장 없음(다음 턴이 새 세션이 될 뿐)


def _pick_session(kakao_uid):
    """이어갈 세션 id + 현재 턴수 반환. 만료/상한이면 (None, 0)=새 세션."""
    e = _load_session(kakao_uid)
    if not e:
        return None, 0
    if (time.time() - e.get("last_ts", 0)) >= SESSION_TTL:
        return None, 0
    if e.get("turns", 0) >= MAX_TURNS:
        return None, 0
    return e.get("session_id"), e.get("turns", 0)


def ask_claude(question: str, resume_sid=None, new_sid=None, image_path=None, erp_user=None):
    """Claude 1회 호출. resume_sid 있으면 이어감 / 없으면 new_sid(신규 UUID)로 격리된 새 세션.
    image_path 있으면 이미지 첨부(비전+OCR): 경로를 프롬프트에 넣으면 claude가 읽어 분석.
    반환: (reply_text, session_id). MCP 서버는 READONLY 모드라 쓰기도구 미노출.
    ※ 세션 플래그 없이 -p만 쓰면 직전 세션을 auto-continue 해 사용자간 맥락이 샘 → 반드시 지정."""
    prompt = question
    if image_path:
        q = question or "이 이미지를 보고 답해줘."
        refs = _load_vehicle_refs()
        ref_lines = ""
        if refs:
            ref_lines = ("\n등록된 차량 계기판 참고사진(비교용):\n"
                         + "\n".join(f"  - {v}: {p}" for v, p in refs.items()))
        prompt = (
            f"사용자가 이미지를 보냈다. 새 이미지: {image_path}{ref_lines}\n\n"
            f"[지시]\n"
            f"- 이 이미지가 '차량 계기판'이면: (1) 위 등록 차량 참고사진들과 비교해 어느 차량인지 판단한다"
            f"(참고사진과 같은 차종·계기판 배치면 그 차량으로 확정, 애매하면 사용자에게 되물음). "
            f"(2) 계기판에서 **최종 총주행거리(odometer_end)만** 정확히 읽는다(다른 수치는 무시). "
            f"(3) 확정된 차량과 odometer_end로 write_preview_vehicle_log 를 진행한다"
            f"(차량이 확정됐으면 차량은 다시 묻지 말고, 목적지·목적 등 부족분만 되묻는다).\n"
            f"- 차량 계기판이 아니면: 일반 이미지로 내용을 읽어(OCR 포함) 답한다.\n\n"
            f"사용자 메시지: {q}")
    cmd = ["claude", "-p", prompt,
           "--model", CLAUDE_MODEL,
           "--mcp-config", MCP_CONFIG,
           "--dangerously-skip-permissions",
           "--append-system-prompt", SYSTEM_PROMPT,
           "--output-format", "json"]
    if resume_sid:
        cmd += ["--resume", resume_sid]
    elif new_sid:
        cmd += ["--session-id", new_sid]   # 신규 세션을 명시적 UUID로 → auto-continue 방지
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=CLAUDE_TIMEOUT,
                          stdin=subprocess.DEVNULL, cwd=APP_ROOT,
                          env={**os.environ, "CLAUDE_CONFIG_DIR": BOT_CONFIG_DIR,
                               "KAKAO_ERP_USER": (erp_user or "")})  # 운행일지 등 신원강제(위조차단)
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError((proc.stderr or "claude 무응답").strip()[-200:])
    # --output-format json = 단일 결과 객체. 혹시 로그가 섞이면 마지막 JSON 라인 사용.
    data = None
    try:
        data = json.loads(out)
    except Exception:
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line); break
                except Exception:
                    continue
    if not isinstance(data, dict):
        raise RuntimeError("claude json 파싱 실패: " + out[-200:])
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result") or data.get("error") or "claude is_error")[:200])
    reply = (data.get("result") or "").strip()
    sid = data.get("session_id") or resume_sid
    if not reply:
        raise RuntimeError("claude 빈 응답")
    return reply, sid


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: kakao_brain.py <kakao_user_id> <b64text>"}))
        return
    kakao_uid = str(sys.argv[1])
    try:
        user_text = base64.b64decode(sys.argv[2]).decode("utf-8")
    except Exception:
        user_text = sys.argv[2]
    # 선택적 4번째 인자 = 이미지 파일 경로(비전/OCR). 있으면 존재하는 파일만 사용.
    image_path = None
    if len(sys.argv) >= 4 and sys.argv[3].strip():
        cand = sys.argv[3].strip()
        image_path = cand if os.path.exists(cand) else None

    erp_user, allowed, channel_enabled = resolve(kakao_uid)
    if not erp_user:
        print(json.dumps({"error": "unmapped", "reply": None, "kakao_user_id": kakao_uid},
                         ensure_ascii=False))
        return
    if not channel_enabled and not IGNORE_CHANNEL_GATE:
        print(json.dumps({"error": "channel_disabled", "reply": None, "erp_user": erp_user},
                         ensure_ascii=False))
        return
    if not allowed:
        print(json.dumps({"error": "no_allowed_tools", "reply": None, "erp_user": erp_user},
                         ensure_ascii=False))
        return

    resume_sid, turns = _pick_session(kakao_uid)
    new_sid = None if resume_sid else str(uuid.uuid4())  # 새 세션은 고유 UUID로 격리

    try:
        reply, sid = ask_claude(user_text, resume_sid=resume_sid, new_sid=new_sid,
                                image_path=image_path, erp_user=erp_user)
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "claude_timeout", "reply": None}, ensure_ascii=False))
        return
    except Exception as e:
        print(json.dumps({"error": f"claude: {str(e)[:200]}", "reply": None}, ensure_ascii=False))
        return

    # 세션 갱신(이어가기 성공/새 세션 모두). turns 는 이어갈 때만 누적.
    if sid:
        _save_session(kakao_uid, {
            "session_id": sid,
            "last_ts": time.time(),
            "turns": (turns + 1) if resume_sid else 1,
        })

    print(json.dumps({"reply": reply, "erp_user": erp_user}, ensure_ascii=False))


if __name__ == "__main__":
    main()
