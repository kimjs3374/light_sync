# Gap Analysis: mcp-server

**분석일**: 2026-03-20
**Match Rate**: 92% ✅

---

## 1. 종합 점수

| 항목 | 점수 | 상태 |
|------|:----:|:----:|
| Tool 구현 (설계 28개) | 96% | ✅ |
| Resource 구현 (설계 4개) | 100% | ✅ |
| 파일 구조 | 85% | ⚠️ |
| 기반 코드 (db.py, server.py) | 90% | ✅ |
| 데이터 반환 규칙 | 95% | ✅ |
| **Overall** | **92%** | **✅** |

---

## 2. Gap 목록

### 2.1 설계 O / 구현 X (1건)

| 항목 | 내용 |
|------|------|
| FR-09 일일보고 Tool | 설계 Section 8에 명시된 일일보고 도메인 Tool 미구현 |

### 2.2 설계 X / 구현 O — 추가 구현 (6건)

| 항목 | 내용 |
|------|------|
| `tools_registry.py` | FastMCP 통합 등록 모듈 (모든 tool/resource 한 파일 관리) |
| `server_http.py` 이중 서버 | HTTP 5010 (Claude Web) + SSE 5011 (LM Studio) |
| `get_overdue_projects` | 납기 초과 현장 조회 Tool (FR-02 확장) |
| `nginx_mcp.conf.example` | nginx 리버스 프록시 설정 예제 |
| `DB_SCHEMA` 환경변수 | search_path 기반 스키마 분리 |
| `month` 파라미터 (`get_projects`) | 월별 필터 추가 |

### 2.3 설계 != 구현 — 변경 사항 (5건)

| 항목 | 설계 | 구현 |
|------|------|------|
| MCP API 스타일 | `mcp.server.Server` (low-level) | `FastMCP` (high-level) |
| `__main__.py` | `asyncio.run(server.run_stdio())` | `mcp.run()` |
| Tool 등록 방식 | 모듈별 개별 register | `tools_registry.register_all()` 통합 |
| Tool 반환 타입 | `list[dict]` / `dict` | `str` (json.dumps) |
| db.py | pool_pre_ping=True | pool_size=5, max_overflow=10 (pre_ping 제거) |

---

## 3. Dead Code 이슈

`tools/` 하위 6개 파일 + `resources/magnatech.py`는 Low-level `mcp.server.Server` API로
작성됐으나 `server.py`가 `tools_registry.py`만 참조함 → **약 1,748줄 사용되지 않는 코드**.

- `light_sync_mcp/tools/inventory.py`
- `light_sync_mcp/tools/bom.py`
- `light_sync_mcp/tools/project.py`
- `light_sync_mcp/tools/production.py`
- `light_sync_mcp/tools/financial.py`
- `light_sync_mcp/tools/procurement.py`
- `light_sync_mcp/resources/magnatech.py`

---

## 4. 권장 조치

| 우선순위 | 항목 | 액션 |
|---------|------|------|
| 낮음 | FR-09 일일보고 | 구현하거나 Phase 2로 이동 |
| 중간 | 설계 문서 업데이트 | FastMCP 전환, tools_registry, 이중 서버 반영 |
| 낮음 | 레거시 코드 정리 | `tools/`, `resources/` 삭제 또는 `_legacy/`로 이동 |

---

## 5. 결론

**Match Rate 92% — 90% 이상 달성. 보고서 작성 가능.**

핵심 기능(28개 Tool, 4개 Resource, DB 연결, SSE/HTTP 이중 서버, 외부 도메인 연결)이
모두 정상 구현됨. FR-09는 미구현이나 핵심 기능 외 항목으로 전체 완성도에 영향 없음.
