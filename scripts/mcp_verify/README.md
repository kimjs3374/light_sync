# MCP Tool 검증 스크립트

Tool 추가·수정 후 반드시 3개 다 돌릴 것. 실행: `venv/bin/python scripts/mcp_verify/<파일>`

| 스크립트 | 무엇을 잡는가 |
|----------|---------------|
| `smoke_all_tools.py` | 전 Tool 실호출. 예외·크래시 탐지 (write_preview 는 호출 안 함) |
| `verify_empty_fields.py` | **모든 행이 빈값/0 인 필드** 탐지 → 존재하지 않는 DB 컬럼 참조 의심 |
| `verify_aggregates.py` | 집계 Tool 반환값 vs DB 직접 쿼리 대조 |

## 왜 필요한가

Tool 코드가 `hasattr(model, "col")` 가드나 ORM 속성으로 **없는 컬럼**을 참조하면
예외 없이 그 값이 조용히 빠진다. 필터에 쓰이면 필터 자체가 증발해 전량이 반환된다.

2026-07-09 전수점검에서 실제로 발견된 사례:
- `get_fab_status` — `stage` 컬럼 부재 → FAB 필터 증발, 전체 공정 5,327건을 "FAB"로 반환
- `get_worker_assignments` — `worker_name` 부재 → 전원 "미배정" 한 덩어리(625KB)
- `get_project_detail` — `Contract.contract_amount` 부재 → 계약금액 항상 0원
- `get_revenue_summary` — `direction` 미필터 → 매입까지 합산, 매출 2배 과대계상

앞의 셋은 `verify_empty_fields.py` 가, 마지막은 `verify_aggregates.py` 가 잡는다.

## 주의

- `verify_empty_fields.py` 가 필드를 지목해도 **DB 자체가 비어있는 경우**가 많다.
  반드시 `information_schema.columns` 로 컬럼 존재 여부부터 확인할 것.
- `verify_aggregates.py` 의 기대값 SQL은 Tool 로직과 같은 조건이어야 한다
  (예: `get_inventory_valuation` 은 `is_active` 만 필터하고 재고 0 도 포함).
- 새 Tool 을 추가하면 각 스크립트의 `CALLS` / `check()` 목록에 직접 등록해야 한다.

관련 문서: `MCP_ERROR.md`, `.claude/mcp_guide.md`
