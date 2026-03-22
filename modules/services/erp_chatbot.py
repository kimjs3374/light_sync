"""ERP 챗봇 — Groq Function Calling (대화형, 히스토리 유지)"""
import inspect
import json
import typing
import datetime
import logging

from groq import Groq

from modules.models.helpers import _read_env_value
from modules.services.erp_tools import TOOL_FUNCTIONS, check_permission

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"
MAX_HISTORY = 6   # user+assistant 메시지 최대 개수 (3회 대화) — Groq 무료 TPM 6000 제한

# Groq TPM 6000 제한 → 핵심 도구만 전송 (스키마 토큰 절약)
GROQ_CORE_TOOLS = {
    # 현장/프로젝트
    "get_projects", "search_projects", "get_project_detail",
    "get_overdue_projects", "get_delivery_summary",
    # 재고
    "get_inventory", "get_low_stock", "search_items",
    # 생산
    "get_production_status", "get_production_by_site",
    # 재무 (관리부/임원진)
    "get_revenue_summary", "get_financial_overview", "get_unpaid_invoices",
    # 납품
    "get_deliveries", "get_delivery_status_summary",
    # 발주
    "get_purchase_orders",
    # AS
    "get_warranty_cases", "get_warranty_stats",
    # 아카이브 (워크보드)
    "search_archive",
    # 영업
    "get_sales_projects",
}


def _load_history(session_id: str) -> list[dict]:
    """DB에서 대화 히스토리 불러오기"""
    from modules.models.db import engine
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT messages_json FROM chatbot_history WHERE session_id = :s"),
                {"s": session_id}
            ).fetchone()
            if row and row[0]:
                data = json.loads(row[0])
                logger.info(f"[chatbot] 히스토리 로드: {session_id} → {len(data)}개 메시지")
                return data
        logger.info(f"[chatbot] 히스토리 없음: {session_id}")
    except Exception as e:
        logger.error(f"[chatbot] 히스토리 로드 실패: {e}", exc_info=True)
    return []


def _save_history(session_id: str, history: list[dict]):
    """대화 히스토리를 DB에 저장"""
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
        logger.info(f"[chatbot] 히스토리 저장: {session_id} → {len(history)}개 메시지")
    except Exception as e:
        logger.error(f"[chatbot] 히스토리 저장 실패: {e}", exc_info=True)


def _py_type_to_json(annotation) -> dict:
    """Python 타입 어노테이션 → JSON Schema 타입 변환"""
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    # Optional[X] = Union[X, NoneType]
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _py_type_to_json(non_none[0])

    return {"type": {
        str: "string", int: "integer", bool: "boolean", float: "number",
    }.get(annotation, "string")}


def _parse_param_desc(doc: str, param_name: str) -> str:
    """docstring에서 'param_name: 설명' 형식 파싱"""
    for line in (doc or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{param_name}:"):
            return stripped[len(param_name) + 1:].strip()
    return param_name


def _build_tools_schema(allowed_tools: set | None = None) -> list[dict]:
    """MCP TOOL_FUNCTIONS에서 Groq Function Calling 스키마 동적 생성.
    GROQ_CORE_TOOLS ∩ allowed_tools 범위만 포함 (TPM 절약).
    """
    from modules.services.erp_tools import RESTRICTED_TOOLS

    tools = []
    for name, func in TOOL_FUNCTIONS.items():
        # Groq 핵심 도구셋 필터
        if name not in GROQ_CORE_TOOLS:
            continue
        # 권한 제한 툴은 allowed_tools에 명시된 경우만 포함
        if name in RESTRICTED_TOOLS:
            if allowed_tools is None or name not in allowed_tools:
                continue
        elif allowed_tools is not None and name not in allowed_tools:
            continue

        sig = inspect.signature(func)
        doc = func.__doc__ or ""
        description = doc.strip().splitlines()[0].strip() if doc.strip() else name

        properties = {}
        required = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            type_schema = _py_type_to_json(param.annotation)
            type_schema["description"] = _parse_param_desc(doc, param_name)
            properties[param_name] = type_schema
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        func_def: dict = {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties},
        }
        if required:
            func_def["parameters"]["required"] = required

        tools.append({"type": "function", "function": func_def})

    return tools


def _get_client() -> Groq:
    api_key = _read_env_value("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY가 설정되지 않았습니다")
    return Groq(api_key=api_key)


def _system_prompt() -> str:
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    return (
        f"당신은 Light-Sync ERP 어시스턴트입니다. 오늘은 {today}입니다.\n"
        "짧고 핵심만 담아 답변하세요. 숫자는 한국 단위(건, 개, 원)로 표시하세요.\n"
        "이전 대화 맥락을 기억하고 연속 질문에 자연스럽게 답하세요.\n"
        "데이터가 없으면 '해당 데이터가 없습니다'라고 안내하세요.\n\n"
        "**중요: 데이터 조회 질문에는 반드시 도구를 호출하세요. 절대 추측하거나 가짜 정보를 만들지 마세요.**\n\n"
        "도구 선택 가이드:\n"
        "- 워크보드, 아카이브, 과거이력, A/S이력, 댓글 → search_archive\n"
        "- 현장, 프로젝트 목록/상세 → get_projects, search_projects\n"
        "- 재고, 부족, 안전재고 → get_inventory, get_low_stock\n"
        "- 매출, 세금계산서, 미수금 → get_revenue_summary, get_unpaid_invoices\n"
        "- 생산, 공정, 작업자 → get_production_status, get_production_by_site\n"
        "- 납품 → get_deliveries, get_delivery_summary\n"
        "- 발주, 입고 → get_purchase_orders\n"
        "- AS, 하자 → get_warranty_cases, get_warranty_stats"
    )


_DATA_KEYWORDS = (
    "조회", "검색", "알려", "보여", "현황", "목록", "리스트", "몇", "얼마",
    "재고", "납품", "생산", "매출", "발주", "입고", "계약", "견적", "프로젝트",
    "현장", "워크보드", "아카이브", "AS", "하자", "부족", "미수금", "세금",
    "품목", "BOM", "도면", "카탈로그", "단가", "거래처", "작업자", "FAB",
)


def _tool_choice(user_text: str) -> str:
    """데이터 조회 질문이면 required, 일반 대화면 auto"""
    t = user_text.lower()
    if any(kw in t for kw in _DATA_KEYWORDS):
        return "required"
    return "auto"


def _strip_think(text: str) -> str:
    import re
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _rescue_failed_tool_call(err, allowed_tools: set | None) -> str | None:
    """Groq tool_use_failed 에러에서 tool call을 파싱하여 직접 실행"""
    import re
    err_str = str(err)
    # failed_generation에서 함수명과 인자 추출
    m = re.search(r'"name":\s*"(\w+)".*?"arguments":\s*(\{[^}]+\})', err_str)
    if not m:
        # <function=name>{...}</function> 형식도 시도
        m = re.search(r'<function=(\w+)>(\{[^}]+\})', err_str)
    if not m:
        return None

    tool_name = m.group(1)
    try:
        tool_args = json.loads(m.group(2))
    except json.JSONDecodeError:
        return None

    # 함수명 퍼지 매칭 (LLM이 이름을 잘못 생성하는 경우)
    if tool_name not in TOOL_FUNCTIONS:
        for real_name in TOOL_FUNCTIONS:
            if tool_name in real_name or real_name in tool_name:
                logger.info(f"[chatbot] fuzzy match: {tool_name} → {real_name}")
                tool_name = real_name
                break

    # 권한 확인
    if allowed_tools is not None and tool_name not in allowed_tools:
        return None

    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return None

    # 타입 교정 (string → int)
    sig = inspect.signature(func)
    for pname, param in sig.parameters.items():
        if pname in tool_args and param.annotation is int:
            try:
                tool_args[pname] = int(tool_args[pname])
            except (ValueError, TypeError):
                pass

    logger.info(f"[chatbot] rescue tool call: {tool_name}({tool_args})")
    return func(**tool_args)


def _format_tool_result(client: Groq, messages: list, result) -> str:
    """도구 결과를 자연어 요약으로 변환"""
    result_str = json.dumps(result, ensure_ascii=False)
    if len(result_str) > 3000:
        result_str = result_str[:3000] + "...(생략)"
    messages.append({"role": "user", "content":
        f"다음 조회 결과를 한국어로 간결하게 요약하세요:\n{result_str}"})
    resp = client.chat.completions.create(model=MODEL, messages=messages)
    return _strip_think(resp.choices[0].message.content or "조회 결과를 요약할 수 없습니다.")


def clear_history(session_id: str):
    """대화 히스토리 초기화"""
    _save_history(session_id, [])


def process_chat(user_text: str, erp_user: str, kakao_user_id: str,
                 allowed_tools: set | None = None) -> str:
    """Groq Function Calling으로 사용자 메시지 처리 후 응답 반환 (대화 히스토리 유지)"""
    # 히스토리 초기화 명령
    if user_text.strip() in ("초기화", "대화초기화", "/reset", "리셋"):
        clear_history(kakao_user_id)
        return "대화 기록을 초기화했습니다. 새로운 대화를 시작하세요!"

    try:
        client = _get_client()
        history = _load_history(kakao_user_id)

        # system + 기존 히스토리 + 새 사용자 메시지
        messages = [
            {"role": "system", "content": _system_prompt()},
            *history,
            {"role": "user", "content": user_text},
        ]

        # 1차 호출 — Function Call 유도 (TPM 초과 시 히스토리 축소 재시도)
        tools_schema = _build_tools_schema(allowed_tools)
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools_schema,
                tool_choice=_tool_choice(user_text),
            )
        except Exception as api_err:
            err_str = str(api_err)
            if "rate_limit" in err_str or "413" in err_str:
                logger.warning(f"[chatbot] TPM 초과 → 히스토리 제거 후 재시도")
                messages = [messages[0], messages[-1]]
                clear_history(kakao_user_id)
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice=_tool_choice(user_text),
                )
            elif "tool_use_failed" in err_str and "failed_generation" in err_str:
                # LLM이 tool call 스키마를 안 지킴 → failed_generation에서 파싱해서 직접 실행
                result = _rescue_failed_tool_call(api_err, allowed_tools)
                if result is not None:
                    reply = _format_tool_result(client, messages, result)
                    _append_history(kakao_user_id, user_text, reply)
                    return reply
                raise
            else:
                raise

        msg = response.choices[0].message

        # Function Call 없으면 바로 반환
        if not msg.tool_calls:
            reply = _strip_think(msg.content or "죄송합니다, 이해하지 못했습니다.")
            _append_history(kakao_user_id, user_text, reply)
            return reply

        tool_call = msg.tool_calls[0]
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments or "{}")

        # LLM이 int 파라미터를 string으로 보내는 경우 교정
        func = TOOL_FUNCTIONS.get(tool_name)
        if func:
            sig = inspect.signature(func)
            for pname, param in sig.parameters.items():
                if pname in tool_args and param.annotation is int:
                    try:
                        tool_args[pname] = int(tool_args[pname])
                    except (ValueError, TypeError):
                        pass

        # 권한 확인
        if allowed_tools is not None and tool_name not in allowed_tools:
            reply = "해당 기능은 사용 권한이 없습니다."
            _append_history(kakao_user_id, user_text, reply)
            return reply
        explicitly_allowed = allowed_tools is not None and tool_name in allowed_tools
        if not explicitly_allowed and not check_permission(erp_user, tool_name):
            reply = "해당 정보는 조회 권한이 없습니다."
            _append_history(kakao_user_id, user_text, reply)
            return reply

        # 툴 실행
        func = TOOL_FUNCTIONS.get(tool_name)
        if not func:
            reply = "지원하지 않는 조회입니다."
            _append_history(kakao_user_id, user_text, reply)
            return reply

        result = func(**tool_args)

        # 2차 호출 — 툴 결과를 자연어로 변환
        # tool_call 메시지는 히스토리에 저장하지 않고 이번 턴에만 사용
        tool_messages = [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": tool_call.id, "type": "function",
                             "function": {"name": tool_name,
                                          "arguments": tool_call.function.arguments}}]},
            {"role": "tool", "tool_call_id": tool_call.id,
             "content": json.dumps(result, ensure_ascii=False)},
        ]
        final = client.chat.completions.create(
            model=MODEL,
            messages=messages + tool_messages,
        )
        reply = _strip_think(final.choices[0].message.content or str(result))
        _append_history(kakao_user_id, user_text, reply)
        return reply

    except Exception as e:
        logger.error(f"[kakao_chatbot] process_chat 오류: {e}")
        return "오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def _append_history(session_id: str, user_text: str, reply: str):
    """히스토리에 user/assistant 메시지 추가 후 DB 저장"""
    history = _load_history(session_id)
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    _save_history(session_id, history)
