# Light-Sync ERP MCP 사용 가이드

## MCP란?

MCP(Model Context Protocol)는 AI가 외부 데이터에 접근하는 표준 프로토콜입니다.
Light-Sync MCP 서버를 통해 AI 챗봇이 ERP 데이터를 직접 조회할 수 있습니다.

## 서버 실행 방법

### Claude Code (로컬 stdio)
```bash
# Claude Code가 자동으로 실행 (settings.json에 등록됨)
# 수동 실행이 필요한 경우:
python -m light_sync_mcp
```

### 웹 서버 (Claude Web / LM Studio)
```bash
python -m light_sync_mcp.server_http

# 포트:
#   5010 → Streamable HTTP (Claude Web: https://mcp.mgnt.kr/mcp)
#   5011 → SSE (LM Studio: http://localhost:5011/sse)
```

### 환경변수
- `DATABASE_URL` — PostgreSQL 연결 문자열 (Supabase)
- `MCP_PORT` — HTTP 포트 (기본 5010)
- `MCP_SSE_PORT` — SSE 포트 (기본 5011)

## Tool 목록 (111개)

### 핵심 조회 패턴

#### 현장 정보 조회
```
1. search_projects("현장명") → 현장 ID 확보
2. get_project_detail(project_id) → 기본 정보
3. get_deliveries(project_id) → 납품 현황
4. get_g2b_contract_detail(search="현장명") → 계약금액
5. search_archive("현장명") → 과거 이력
```

#### 재무 현황
```
get_financial_overview() → 총매출/미수금/수금 요약
get_revenue_summary(year=2026, month=3) → 월별 매출
get_unpaid_invoices() → 미수금 상세
```

#### 생산/재고
```
get_production_by_site() → 현장별 생산 현황
get_low_stock() → 안전재고 미달 품목
get_bom_stock_status(bom_id) → 생산 가능 여부
```

### 주의사항

1. **`get_contracts()` 사용 금지** — contracts 테이블 0건, 항상 빈 배열 반환
   - 대신 `get_g2b_contract_detail()` 사용
2. **계약금액 ≠ 매출액**
   - 계약금액: `get_g2b_contract_detail()` (조달 시점)
   - 매출액: `get_revenue_summary()` (세금계산서 매출분. direction 기본 '매출')
   - 매입/지출: `get_purchase_summary()` — tax_invoices 는 매입이 매출의 5배
3. **조회 + 쓰기(preview)** — `get_*`/`search_*`/`list_*` 는 조회 전용.
   `write_preview_*` 11종은 **즉시 변경하지 않고** preview만 반환 →
   사용자가 확인 버튼을 눌러야 Flask `/mattermost/action`에서 DB 반영.

### 도메인별 Tool 정리

| 도메인 | Tool 수 | 주요 Tool |
|--------|---------|----------|
| 현장/프로젝트 | 8 | search_projects, get_project_detail, get_project_contacts |
| G2B 조달 | 2 | get_g2b_contract_detail, get_warranty_by_g2b |
| 재무/매출 | 5 | get_revenue_summary(direction='매출'), get_purchase_summary, get_unpaid_invoices |
| 납품 | 3 | get_deliveries, get_delivery_detail |
| 생산 | 4 | get_production_status, get_production_by_site, get_process_summary, get_work_logs |
| 재고 | 6 | get_inventory, get_low_stock, get_inventory_consumption |
| BOM/품목 | 6 | get_bom_detail, calculate_bom_cost |
| 발주/입고 | 5 | get_purchase_orders, get_receiving_history, get_receiving_detail |
| 자재발주 | 2 | get_material_orders, get_material_orders_by_project |
| 입고현황 통합 | 1 | get_incoming_overview |
| 청구관리 | 1 | get_billing_status |
| 견적 | 3 | get_quotations, get_quotation_detail |
| 영업 | 2 | get_sales_projects |
| AS/보증 | 3 | get_warranty_cases, get_warranty_stats |
| 도면 | 2 | get_drawings, get_drawing_versions |
| 카탈로그 | 2 | get_catalog_products, get_catalog_price |
| 인증서 | 1 | get_cert_expiry_alerts |
| 시방서 | 1 | get_spec_doc_status |
| 조명배치도 | 2 | get_lighting_layouts, get_lighting_layout_detail |
| 조도검증 | 2 | get_illuminance_projects, get_illuminance_detail |
| 일일보고 | 2 | get_daily_reports, get_daily_report_detail |
| 알림 | 2 | get_notifications, get_unread_notification_count |
| 아카이브 | 2 | search_archive, get_archive_post_detail |
| 직원/근무 | 2 | get_employees, get_today_attendance (전자결재 기준) |
| 인사/연차 | 4 | get_leave_balance, get_leave_calendar, get_leave_promotion_status, get_employee_card |
| 전자결재 | 4 | get_approval_documents, get_approval_detail, get_my_pending_approvals, get_my_approval_drafts |
| 가공발주 | 2 | get_processing_orders, get_processing_order_detail |
| 출장관리 | 2 | get_business_trips, get_business_trip_detail |
| 서류관리 | 2 | get_document_list, get_document_detail |
| 운행일지 | 2 | get_vehicle_logs, get_vehicle_log_summary |
| 부서 주간보고 | 1 | get_dept_weekly_report |
| 공구관리 | 1 | get_tools_list |
| 대시보드 | 1 | get_dashboard_summary |
| 메일 — DB기록 | 2 | get_mail_contacts, get_email_history |
| 메일함 — IMAP | 5 | list_inbox_messages, search_mailbox, read_mail_message |
| 시스템 활동로그 | 1 | get_activity_logs |
| 쓰기작업(preview) | 11 | write_preview_delivery_complete, write_preview_email_send, write_preview_leave_request 등 |
| 계약 (비활성) | 2 | ~~get_contracts~~ (사용 금지) |

## Resource 목록 (5개)

| URI | 설명 |
|-----|------|
| `magnatech://process` | 매그나텍 생산 공정 설명서 |
| `magnatech://products` | BOM 기준 제품 사양 목록 |
| `magnatech://certifications` | 제품 인증번호 목록 |
| `lightsync://query-patterns` | 실제 질문에서 학습된 Tool 매핑 패턴 (hit_count 순) |
| `lightsync://schema` | DB 스키마 요약 |

## 파일 구조

```
light_sync_mcp/
├── __main__.py          # stdio 진입점
├── server.py            # FastMCP 인스턴스 + instructions
├── server_http.py       # HTTP/SSE 웹 서버
├── db.py                # SQLAlchemy 세션
├── tools_registry.py    # 전체 Tool 등록
├── tools/
│   ├── _helpers.py      # 공통 헬퍼 (_s, _sn, _sd)
│   ├── project.py       # 현장 (7개)
│   ├── g2b.py           # G2B 조달 (2개)
│   ├── financial.py     # 재무 (4개)
│   ├── delivery.py      # 납품 (3개)
│   ├── production.py    # 생산 (4개)
│   ├── inventory.py     # 재고 (5개)
│   ├── bom.py           # BOM/품목 (6개)
│   ├── procurement.py   # 발주/입고 (4개)
│   ├── quotation.py     # 견적 (3개)
│   ├── sales.py         # 영업 (2개)
│   ├── warranty.py      # AS/보증 (3개)
│   ├── drawing.py       # 도면 (2개)
│   ├── catalog.py       # 카탈로그 (2개)
│   ├── certification.py # 인증서 (1개)
│   ├── spec_doc.py      # 시방서 (1개)
│   ├── lighting_layout.py # 조명배치도 (2개)
│   ├── illuminance.py   # 조도검증 (2개)
│   ├── daily_report.py  # 일일보고 (2개)
│   ├── notification.py  # 알림 (2개)
│   ├── archive.py       # 아카이브 (2개)
│   ├── contract.py      # 계약 (2개, 비활성)
│   ├── overview.py      # 진행률 (1개)
│   ├── employee.py      # 직원/근무 (2개)
│   ├── processing_order.py # 가공발주 (2개)
│   ├── business_trip.py # 출장 (2개)
│   ├── document.py      # 서류 (2개)
│   ├── tool_mgmt.py     # 공구 (1개)
│   ├── mail.py          # 메일 DB기록+IMAP (7개)
│   ├── activity.py      # 활동로그 (1개)
│   ├── material_order.py    # 자재발주 (2개)
│   ├── vehicle_log.py       # 운행일지 (2개)
│   ├── billing.py           # 청구관리 (1개)
│   ├── dept_report.py       # 부서 주간보고 (1개)
│   ├── incoming_overview.py # 입고현황 통합 (1개)
│   └── write_ops.py         # 쓰기작업 preview (11개)
└── resources/
    └── magnatech.py     # 5개 Resource (+ query-patterns, schema)
```

## 업데이트 이력

| 날짜 | 변경 |
|------|------|
| 2026-06-19 | 미등록 6개 모듈 registry 연결 (material_order·vehicle_log·billing·dept_report·incoming_overview·write_ops, +17 Tool → 100개). mattermost_action 확인 게이트에 production_complete_all·email_send 추가 |
| 2026-03-22 | g2b, certification, spec_doc, lighting_layout, illuminance 추가 (53→61개) |
| 2026-03-21 | MCP_ERROR.md 작성 (contracts 0건 문제 확인) |
