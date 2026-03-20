# Plan: mcp-server

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | Claude가 Light-Sync ERP 데이터에 직접 접근할 수 없어 매번 수동으로 DB 조회 결과를 붙여넣어야 하는 비효율 발생 |
| **Solution** | MCP(Model Context Protocol) 서버를 구현하여 Claude Desktop에서 ERP 28개 도메인 Tool을 자연어로 직접 호출 |
| **Function UX Effect** | "이번 달 납품 실적 알려줘", "현장 BOM 재고 부족 항목 뽑아줘" 등 자연어 질의로 즉시 ERP 데이터 조회/분석 가능 |
| **Core Value** | Claude + ERP 통합으로 보고서 자동생성, 재고 분석, BOM 계산 등 반복 업무의 AI 자동화 기반 마련 |

---

## 1. 기능 요구사항 (FR)

### FR-01: MCP 서버 기반 구조
- Python `mcp` SDK 기반 stdio transport MCP 서버 구현
- `light_sync_mcp/` 독립 패키지로 분리 (ERP Flask 앱과 분리)
- 기존 `entities.py` SQLAlchemy 모델 재사용 (DB 연결 공유)
- Claude Desktop `claude_desktop_config.json` 연결 설정

### FR-02: 현장/프로젝트 도메인 Tools (5개)
- `get_projects` — 현장 목록 조회 (상태, 발주처, 기간 필터)
- `get_project_detail` — 현장 상세 (계약금액, 납품일정, 진행률)
- `get_project_timeline` — 현장별 납품/생산 타임라인
- `search_projects` — 현장명/발주처/지역 검색
- `get_delivery_summary` — 현장별 납품집계 (G2B 연동)

### FR-03: BOM/품목 도메인 Tools (6개)
- `get_bom_list` — BOM 목록 (품목명, 버전, 옵션 필터)
- `get_bom_detail` — BOM 상세 (자재 구성, 수량, 단가, option_schema)
- `calculate_bom_cost` — BOM 원가 계산 (수량 × 단가 합산)
- `get_items` — 품목 목록 조회 (카테고리, 규격 필터)
- `search_items` — 품목 검색
- `get_bom_stock_status` — BOM 기준 재고 충족 여부 확인

### FR-04: 재고 도메인 Tools (5개)
- `get_inventory` — 현재 재고 현황 (품목별 수량, 위치)
- `get_low_stock` — 안전재고 미달 품목 목록
- `get_inventory_turnover` — 재고 회전율 분석
- `get_stock_movements` — 재고 변동 이력 (입고/출고/조정)
- `get_inventory_valuation` — 재고 평가액

### FR-05: 생산 도메인 Tools (4개)
- `get_production_status` — 생산 현황 (현장별, 품목별)
- `get_production_by_site` — 현장별 생산 카드 목록
- `get_worker_assignments` — 작업자 배치 현황
- `get_fab_status` — FAB 공정 현황

### FR-06: 재무/세금계산서 도메인 Tools (4개)
- `get_revenue_summary` — 매출 집계 (월별, 현장별)
- `get_tax_invoices` — 세금계산서 목록 (G2B 매칭 상태 포함)
- `get_financial_overview` — 재무 대시보드 요약
- `get_unpaid_invoices` — 미수금 현황

### FR-07: 조달/발주 도메인 Tools (4개)
- `get_purchase_orders` — 발주서 목록 (상태, 거래처 필터)
- `get_po_detail` — 발주서 상세
- `get_receiving_history` — 입고 이력
- `get_vendor_list` — 거래처 목록

### FR-08: MCP Resources (4개)
- `magnatech://process` — MAGNATECH 생산 공정 설명서
- `magnatech://products` — 제품 사양 및 스펙
- `magnatech://certifications` — 인증서 목록
- `lightsync://schema` — ERP DB 스키마 요약

### FR-09: 일일보고 자동화 Tool (추가)
- `generate_daily_report_data` — 일일업무보고 데이터 자동 수집 (현장/생산/납품 집계)

---

## 2. 비기능 요구사항 (NFR)

| 항목 | 요구사항 |
|------|----------|
| 성능 | Tool 응답 3초 이내 (쿼리 최적화 필수) |
| 보안 | 로컬 stdio transport (네트워크 노출 없음), DB 읽기 전용 연결 권장 |
| 의존성 | `mcp`, `sqlalchemy`, `psycopg2-binary`, `python-dotenv` |
| 호환성 | Claude Desktop (Windows), Python 3.10+ |
| 유지보수 | ERP 스키마 변경 시 entities.py 공유로 자동 반영 |

---

## 3. 구현 범위 및 우선순위

### Phase 1 — 핵심 (1순위)
- MCP 서버 스켈레톤 (`server.py`, `db.py`, `__main__.py`)
- Claude Desktop 연결 설정
- 재고 Tools 5개 (FR-04) — 가장 자주 조회하는 데이터
- BOM Tools 3개 (FR-03 중 get_bom_list, get_bom_detail, calculate_bom_cost)

### Phase 2 — 확장 (2순위)
- 현장/프로젝트 Tools 5개 (FR-02)
- 생산 Tools 4개 (FR-05)
- BOM 나머지 3개 (FR-03)

### Phase 3 — 심화 (3순위)
- 재무/세금계산서 Tools 4개 (FR-06)
- 조달/발주 Tools 4개 (FR-07)
- MCP Resources 4개 (FR-08)
- 일일보고 Tool (FR-09)

---

## 4. 파일 구조

```
light_sync_mcp/
├── __init__.py
├── __main__.py          # python -m light_sync_mcp 진입점
├── server.py            # MCP 서버 메인 (tool 등록)
├── db.py                # DB 연결 (entities.py 재사용)
├── tools/
│   ├── __init__.py
│   ├── inventory.py     # FR-04 재고 tools
│   ├── bom.py           # FR-03 BOM tools
│   ├── project.py       # FR-02 현장 tools
│   ├── production.py    # FR-05 생산 tools
│   ├── financial.py     # FR-06 재무 tools
│   └── procurement.py   # FR-07 조달 tools
├── resources/
│   ├── __init__.py
│   └── magnatech.py     # FR-08 Resources
└── requirements.txt
```

---

## 5. Claude Desktop 연결 설정

```json
// %APPDATA%\Claude\claude_desktop_config.json
{
  "mcpServers": {
    "light-sync": {
      "command": "python",
      "args": ["-m", "light_sync_mcp"],
      "cwd": "D:/light_sync",
      "env": {
        "DATABASE_URL": "postgresql://user:pass@localhost/light_sync"
      }
    }
  }
}
```

---

## 6. 제외 범위 (Out of Scope)

- 데이터 쓰기/수정 Tool (읽기 전용으로 시작)
- HTTP transport (stdio로 충분)
- 인증/권한 관리 (로컬 전용)
- 웹 대시보드 연동 (별도 프로젝트)

---

## 7. 관련 파일

| 파일 | 역할 |
|------|------|
| `models/entities.py` | SQLAlchemy 모델 (재사용) |
| `routes/inventory.py` | 재고 비즈니스 로직 참조 |
| `routes/bom.py` | BOM 비즈니스 로직 참조 |
| `routes/project.py` | 현장 비즈니스 로직 참조 |
| `docs/magnatech_memory.md` | MAGNATECH 도메인 지식 (Resource용) |
