"""ERP 챗봇 — Groq Function Calling (히스토리는 기록용, Groq에 안 보냄)"""
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
MAX_HISTORY = 50   # 기록용 최대 보관 (UI 표시용, Groq에는 안 보냄)

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

# "아까 그거", "방금 거" 등 이전 대화 참조 키워드
_CONTEXT_KEYWORDS = (
    "아까", "방금", "위에", "그거", "그것", "아까 그", "이전", "전에",
    "다시", "또", "그 현장", "그 프로젝트", "거기", "같은",
)


def _needs_context(user_text: str) -> bool:
    """사용자 질문이 이전 대화 맥락을 참조하는지 판단"""
    t = user_text.strip()
    return any(kw in t for kw in _CONTEXT_KEYWORDS)


# ── 3단계 Tool 라우터 ────────────────────────────────────────────────
def _route_tool(user_text: str, allowed_tools: set | None = None):
    """질문 → Tool 자동 라우팅 (3단계).
    Returns: (tool_name, tool_args) or None (LLM 폴백)
    """
    # 1단계: 키워드 하드코딩 (가장 빠름)
    result = _route_by_keywords(user_text)
    if result:
        tool_name, tool_args = result
        if allowed_tools is None or tool_name in allowed_tools:
            logger.info(f"[chatbot] 라우터 1단계(키워드): {user_text[:30]} → {tool_name}")
            return result

    # 2단계: DB 학습 패턴 매칭
    result = _route_by_patterns(user_text)
    if result:
        tool_name, tool_args = result
        if allowed_tools is None or tool_name in allowed_tools:
            logger.info(f"[chatbot] 라우터 2단계(패턴): {user_text[:30]} → {tool_name}")
            return result

    # 3단계: LLM 폴백
    logger.info(f"[chatbot] 라우터 3단계(LLM): {user_text[:30]}")
    return None


# 1단계: 키워드 기반 하드코딩 라우터
_KEYWORD_ROUTES = [
    # (키워드 리스트, tool_name, tool_args) — 순서대로 매칭, 먼저 걸리면 반환
    # 현장
    (["납품해야", "납품할 현장", "진행중인 현장", "진행 중 현장", "계약된 현장", "계약 현장", "수행중", "작업중인 현장"],
     "get_projects", {"status": "계약"}),
    (["설계 중", "설계중", "영업 현장", "미계약", "계약 전"],
     "get_projects", {"status": "설계/영업"}),
    (["완료된 현장", "끝난 현장", "납품완료", "납품 완료"],
     "get_projects", {"status": "납품완료"}),
    (["납기 지난", "납기 초과", "기한 지난", "지연된 현장", "납기초과", "오버된"],
     "get_overdue_projects", {}),

    # 재무
    (["미수금", "안 받은 돈", "못 받은 돈", "미청구", "받을 돈", "받을돈", "미입금", "안받은"],
     "get_unpaid_invoices", {}),
    (["재무 현황", "재무 요약", "재무 대시보드", "자금 현황"],
     "get_financial_overview", {}),

    # 재고
    (["재고 부족", "부족한 재고", "안전재고 미달", "재고 없", "부족한 거", "모자란", "바닥난", "떨어진 거"],
     "get_low_stock", {}),

    # AS
    (["AS 통계", "하자 통계", "AS 분석", "결함 유형"],
     "get_warranty_stats", {}),

    # 인증서
    (["인증서 만료", "만료 인증", "인증 만료", "인증서 갱신", "KS 인증", "KC 인증", "ISO 인증", "시험성적서"],
     "get_cert_expiry_alerts", {"days": 60}),

    # 조명배치도
    (["배치도", "조명배치도", "타워 배치", "투광등 배치"],
     "get_lighting_layouts", {}),

    # 조도
    (["조도 검증", "조도설계", "조도 프로젝트", "룩스"],
     "get_illuminance_projects", {}),

    # 생산
    (["현장별 생산", "생산 카드"],
     "get_production_by_site", {}),
    (["작업일지", "누가 뭐해", "누가 작업", "생산 실적", "작업 실적"],
     "get_work_logs", {}),
    (["공정별", "공정 현황", "공정 단계", "어느 단계", "조립 현황"],
     "get_process_summary", {}),

    # 기타
    (["거래처", "협력사", "협력업체", "공급업체"],
     "get_vendor_list", {}),
    # 직원/근무
    (["직원 몇", "직원 수", "인원 몇", "회사 인원", "전체 인원", "사원 수", "사원 몇"],
     "get_employees", {}),
    (["근무 인원", "근무인원", "출근 인원", "출근인원", "오늘 출근", "누가 연차", "연차 누구", "오늘 연차", "반차 누구", "휴가 누구", "오늘 근무"],
     "get_today_attendance", {}),

    (["워크보드", "아카이브", "과거 이력", "카카오워크", "보드 검색"],
     "search_archive", {}),
    (["일일보고", "일보", "업무보고", "업무 보고"],
     "get_daily_reports", {}),
    (["시방서", "규격서"],
     "get_spec_doc_status", {}),
    # 출장
    (["출장 일정", "출장 목록", "출장 가", "누가 출장", "이번주 출장", "출장 현황"],
     "get_business_trips", {}),
    # 서류
    (["서류 현황", "착수계", "납품계", "서류 패키지", "공문번호"],
     "get_document_list", {}),
    # 공구
    (["공구 목록", "전동공구", "공구 현황", "공구 뭐", "드릴", "그라인더"],
     "get_tools_list", {}),
    # 소진
    (["소진 이력", "소진이력", "자재 소진", "자재소진", "어디에 썼", "뭐 썼", "소모 이력"],
     "get_inventory_consumption", {}),
    # 대시보드 종합
    (["전체 현황", "종합 현황", "현황 요약", "오늘 현황", "오늘 어때", "전체 요약"],
     "get_dashboard_summary", {}),
]


def _route_by_keywords(user_text: str):
    """1단계: 키워드 기반 하드코딩 매칭"""
    t = user_text.lower().strip()
    for keywords, tool_name, tool_args in _KEYWORD_ROUTES:
        if any(kw in t for kw in keywords):
            return (tool_name, tool_args)

    # 매출 관련 (연/월 파싱)
    import re
    if any(kw in t for kw in ("매출", "매출액", "월매출", "연매출")):
        import datetime
        now = datetime.date.today()
        year, month = now.year, now.month
        m = re.search(r'(\d{4})년', t)
        if m:
            year = int(m.group(1))
        m2 = re.search(r'(\d{1,2})월', t)
        if m2:
            month = int(m2.group(1))
        if "올해" in t or "연간" in t:
            return ("get_revenue_summary", {"year": year})
        if "지난달" in t or "저번달" in t:
            month = month - 1 if month > 1 else 12
            year = year if month != 12 else year - 1
        return ("get_revenue_summary", {"year": year, "month": month})

    # AS 관련 (상태 파싱)
    if any(kw in t for kw in ("as", "a/s", "하자", "고장", "불량", "미점등")):
        if any(kw in t for kw in ("접수", "신규", "새로")):
            return ("get_warranty_cases", {"status": "접수"})
        if any(kw in t for kw in ("처리중", "진행중", "수리중")):
            return ("get_warranty_cases", {"status": "처리중"})
        if any(kw in t for kw in ("완료", "끝난")):
            return ("get_warranty_cases", {"status": "완료"})
        return ("get_warranty_cases", {})

    # 가공발주 (일반발주보다 먼저 매칭)
    if any(kw in t for kw in ("가공발주", "가공 발주", "외주가공", "사급가공")):
        return ("get_processing_orders", {})

    # 일반발주
    if any(kw in t for kw in ("발주", "주문", "po ")):
        return ("get_purchase_orders", {})

    # 재고 (일반)
    if "재고" in t:
        return ("get_inventory", {})

    # 생산 (일반)
    if any(kw in t for kw in ("생산 현황", "생산 상태", "공정 현황", "생산현황", "생산상태")):
        return ("get_production_status", {})

    # 납품 (일반)
    if any(kw in t for kw in ("납품 현황", "납품현황", "납품 상태", "납품상태")):
        return ("get_deliveries", {})

    # 세금계산서
    if any(kw in t for kw in ("세금계산서", "계산서")):
        return ("get_tax_invoices", {})

    # 견적
    if any(kw in t for kw in ("견적", "견적서")):
        return ("get_quotations", {})

    # 영업
    if any(kw in t for kw in ("영업 현황", "수주 현황", "영업현황", "수주현황", "영업 목록")):
        return ("get_sales_projects", {})

    return None


def _route_by_patterns(user_text: str):
    """2단계: DB 학습 패턴에서 유사 질문 매칭 (포함 검색)"""
    from modules.models.db import engine
    from sqlalchemy import text as sql_text
    try:
        t = user_text.strip()
        with engine.begin() as conn:
            # 정확히 일치
            row = conn.execute(sql_text("""
                SELECT tool_name, tool_args FROM mcp_query_patterns
                WHERE question = :q AND success = true
                ORDER BY hit_count DESC LIMIT 1
            """), {"q": t}).fetchone()
            if row:
                return (row[0], json.loads(row[1]) if row[1] else {})

            # 질문이 패턴을 포함 (패턴이 질문의 부분문자열)
            row = conn.execute(sql_text("""
                SELECT tool_name, tool_args, hit_count FROM mcp_query_patterns
                WHERE :q LIKE '%' || question || '%' AND success = true
                ORDER BY length(question) DESC, hit_count DESC
                LIMIT 1
            """), {"q": t}).fetchone()
            if row:
                return (row[0], json.loads(row[1]) if row[1] else {})

            # 패턴이 질문을 포함
            row = conn.execute(sql_text("""
                SELECT tool_name, tool_args, hit_count FROM mcp_query_patterns
                WHERE question LIKE '%' || :q || '%' AND success = true
                ORDER BY hit_count DESC
                LIMIT 1
            """), {"q": t}).fetchone()
            if row:
                return (row[0], json.loads(row[1]) if row[1] else {})

            # 핵심 단어 추출 후 매칭 (2글자 이상 단어)
            import re
            words = [w for w in re.split(r'\s+', t) if len(w) >= 2]
            if words:
                # 가장 긴 단어로 LIKE 검색
                key_word = max(words, key=len)
                row = conn.execute(sql_text("""
                    SELECT tool_name, tool_args, hit_count FROM mcp_query_patterns
                    WHERE question LIKE :kw AND success = true
                    ORDER BY hit_count DESC
                    LIMIT 1
                """), {"kw": f"%{key_word}%"}).fetchone()
                if row:
                    return (row[0], json.loads(row[1]) if row[1] else {})

    except Exception as e:
        logger.warning(f"[chatbot] 패턴 매칭 실패 (무시): {e}")
    return None


def _load_history(session_id: str) -> list[dict]:
    """DB에서 대화 히스토리 불러오기 (기록 확인용)"""
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
                return data
    except Exception as e:
        logger.error(f"[chatbot] 히스토리 로드 실패: {e}", exc_info=True)
    return []


def _load_recent_context(session_id: str, count: int = 4) -> list[dict]:
    """이전 대화 참조 시에만 최근 N개 메시지를 불러옴"""
    history = _load_history(session_id)
    if not history:
        return []
    return history[-count:]


def _save_history(session_id: str, history: list[dict]):
    """대화 히스토리를 DB에 저장 (기록용)"""
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
        "데이터가 없으면 '해당 데이터가 없습니다'라고 안내하세요.\n\n"
        "**중요: 데이터 조회 질문에는 반드시 도구를 호출하세요. 절대 추측하거나 가짜 정보를 만들지 마세요.**\n\n"
        "도구 선택 가이드 (반드시 1개만 호출):\n"
        "- 납품해야 할/되는 현장, 진행중 현장 → get_projects(status='계약')\n"
        "- 납기 지난/초과 현장 → get_overdue_projects\n"
        "- 완료된 현장 → get_projects(status='납품완료')\n"
        "- 설계/영업 현장 → get_projects(status='설계/영업')\n"
        "- 현장 검색 → search_projects(query='키워드')\n"
        "- 워크보드, 아카이브, 과거이력 → search_archive\n"
        "- 재고, 부족 → get_inventory, get_low_stock\n"
        "- 매출 → get_revenue_summary\n"
        "- 미수금 → get_unpaid_invoices\n"
        "- 생산 현황 → get_production_by_site\n"
        "- 납품 상세 → get_deliveries\n"
        "- 발주 → get_purchase_orders\n"
        "- AS, 하자 → get_warranty_cases"
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


def _direct_format(result) -> str | None:
    """LLM 없이 도구 결과를 직접 포맷. 포맷 가능하면 문자열, 아니면 None."""
    if not isinstance(result, str):
        return None
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None

    # {"items": [...], "total": N} 패턴
    items = None
    total = 0
    if isinstance(data, dict):
        items = data.get('items') or data.get('data') or data.get('orders') or data.get('results')
        total = data.get('total') or data.get('count') or (len(items) if items else 0)
        # 단일 객체 (items 없음) → 키-값 나열
        if items is None and not any(k in data for k in ('items', 'data', 'orders', 'results')):
            lines = []
            for k, v in data.items():
                if v is not None and v != '' and v != 0:
                    lines.append(f"- **{k}**: {v}")
            return '\n'.join(lines) if lines else None
    elif isinstance(data, list):
        items = data
        total = len(data)
    else:
        return None

    if not items:
        return "조회 결과가 없습니다."

    # 테이블 생성
    if not isinstance(items[0], dict):
        return None

    keys = list(items[0].keys())
    # id, note 등 불필요한 컬럼 제거
    skip = {'id', 'note', 'processing_type'}
    keys = [k for k in keys if k not in skip]
    if len(keys) > 8:
        keys = keys[:8]

    header = '| ' + ' | '.join(keys) + ' |'
    sep = '|' + '|'.join(['------'] * len(keys)) + '|'
    rows = []
    for item in items[:20]:
        vals = [str(item.get(k, '')) for k in keys]
        rows.append('| ' + ' | '.join(vals) + ' |')

    title = f"조회 결과 (총 {total}건)" if total else "조회 결과"
    table = '\n'.join([f"📋 {title}", '', header, sep] + rows)
    if total > 20:
        table += f"\n\n... 외 {total - 20}건"
    return table


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
    """Groq Function Calling으로 사용자 메시지 처리 후 응답 반환.
    히스토리는 기록용으로만 저장하고, Groq에는 보내지 않음.
    단, "아까 그거" 등 이전 대화 참조 시에만 최근 맥락을 포함.
    """
    # 히스토리 초기화 명령
    if user_text.strip() in ("초기화", "대화초기화", "/reset", "리셋"):
        clear_history(kakao_user_id)
        return "대화 기록을 초기화했습니다. 새로운 대화를 시작하세요!"

    try:
        client = _get_client()

        # ── 3단계 라우터: LLM 없이 Tool 직접 매칭 시도 ──
        routed = _route_tool(user_text, allowed_tools)
        if routed:
            tool_name, tool_args = routed
            # 개발 중 기능 안내
            if tool_name == '__not_ready__':
                reply = tool_args.get('message', '해당 기능은 준비 중입니다.')
                _append_history(kakao_user_id, user_text, reply)
                return reply
            func = TOOL_FUNCTIONS.get(tool_name)
            if func:
                try:
                    result = func(**tool_args)
                    _save_query_pattern(user_text, tool_name, tool_args, success=True)
                    # 직접 포맷 시도 (LLM 없이 즉시 응답)
                    direct = _direct_format(result)
                    if direct:
                        _append_history(kakao_user_id, user_text, direct)
                        return direct
                    # 직접 포맷 불가 → LLM 요약
                    messages = [
                        {"role": "system", "content": _system_prompt()},
                        {"role": "user", "content": user_text},
                    ]
                    reply = _format_tool_result(client, messages, result)
                    _append_history(kakao_user_id, user_text, reply)
                    return reply
                except Exception as e:
                    logger.warning(f"[chatbot] 라우터 Tool 실행 실패 ({tool_name}): {e}")
                    # 폴백: LLM에게 맡김

        # ── LLM 폴백 (라우터에서 못 잡은 경우) ──
        # 기본: system + 사용자 질문만 (히스토리 없음)
        messages = [
            {"role": "system", "content": _system_prompt()},
        ]

        # 이전 대화 참조 시에만 최근 맥락 추가
        if _needs_context(user_text):
            context = _load_recent_context(kakao_user_id, count=4)
            if context:
                messages.extend(context)
                logger.info(f"[chatbot] 맥락 참조: {len(context)}개 메시지 포함")

        messages.append({"role": "user", "content": user_text})

        # 1차 호출 — Function Call 유도
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
                logger.warning(f"[chatbot] TPM 초과 → 맥락 제거 후 재시도")
                messages = [messages[0], messages[-1]]
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice=_tool_choice(user_text),
                )
            elif "tool_use_failed" in err_str and "failed_generation" in err_str:
                result = _rescue_failed_tool_call(api_err, allowed_tools)
                if result is not None:
                    reply = _format_tool_result(client, messages, result)
                    _append_history(kakao_user_id, user_text, reply)
                    import re
                    m = re.search(r'"name":\s*"(\w+)"', str(api_err))
                    if m:
                        _save_query_pattern(user_text, m.group(1), {}, success=True)
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
        tool_args = json.loads(tool_call.function.arguments or "{}") or {}

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

        # 질문→Tool 패턴 자동 저장
        _save_query_pattern(user_text, tool_name, tool_args, success=True)

        # 2차 호출 — 툴 결과를 자연어로 변환
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
    """히스토리에 user/assistant 메시지 추가 후 DB 저장 (기록용, timestamp 포함)"""
    now = datetime.datetime.now().isoformat()
    history = _load_history(session_id)
    history.append({"role": "user", "content": user_text, "ts": now})
    history.append({"role": "assistant", "content": reply, "ts": now})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    _save_history(session_id, history)


def _save_query_pattern(question: str, tool_name: str, tool_args: dict, success: bool = True):
    """질문→Tool 매핑 패턴을 DB에 저장 (동일 패턴은 hit_count 증가)"""
    from modules.models.db import engine
    from sqlalchemy import text
    try:
        args_json = json.dumps(tool_args, ensure_ascii=False)
        with engine.begin() as conn:
            # 같은 질문+tool 조합이 있으면 hit_count 증가
            existing = conn.execute(text("""
                SELECT id FROM mcp_query_patterns
                WHERE question = :q AND tool_name = :t
                LIMIT 1
            """), {"q": question, "t": tool_name}).fetchone()

            if existing:
                conn.execute(text("""
                    UPDATE mcp_query_patterns
                    SET hit_count = hit_count + 1, last_used_at = NOW(), success = :s
                    WHERE id = :id
                """), {"id": existing[0], "s": success})
            else:
                conn.execute(text("""
                    INSERT INTO mcp_query_patterns (question, tool_name, tool_args, success)
                    VALUES (:q, :t, CAST(:a AS jsonb), :s)
                """), {"q": question, "t": tool_name, "a": args_json, "s": success})
    except Exception as e:
        logger.warning(f"[chatbot] 패턴 저장 실패 (무시): {e}")
