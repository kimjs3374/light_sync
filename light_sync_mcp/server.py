"""Light-Sync ERP MCP 서버"""
from mcp.server.fastmcp import FastMCP
from .tools_registry import register_all

INSTRUCTIONS = """
# Light-Sync ERP MCP 서버

(주)매그나텍 LED 조명 사업부 사내 ERP 데이터를 **읽기 전용**으로 조회합니다.

## 핵심 규칙

1. **계약 정보 = G2B 조달내역**: `get_contracts()`는 항상 빈 배열 반환 (contracts 테이블 0건).
   반드시 `get_g2b_contract_detail()`을 사용하세요.
2. **계약금액 ≠ 매출액**: 계약금액은 `get_g2b_contract_detail()`, 매출(청구기준)은 `get_revenue_summary()`.
3. **현장 검색**: `search_projects()`로 현장 ID 확보 → 다른 Tool에 project_id 전달.
4. **Tool 1개로 해결하세요**: 여러 Tool을 순차 호출하지 말고, 가장 적합한 Tool 1개를 바로 호출하세요.

## 한국어 업무 용어 → Tool 매핑 (필독)

사용자가 한국어로 질문하면 아래 매핑을 따르세요. **추측으로 여러 Tool 시도 금지.**

| 업무 용어 | 의미 | 정확한 Tool |
|-----------|------|------------|
| 납품해야 되는/할 현장 | 계약 체결됨, 아직 납품 안 한 현장 | `get_projects(status="계약")` |
| 진행 중인 현장 | 생산/납품 중 | `get_projects(status="계약")` |
| 완료된 현장 | 납품 끝남 | `get_projects(status="납품완료")` |
| 설계 중인/영업 현장 | 아직 계약 전 | `get_projects(status="설계/영업")` |
| 현장 몇 건/개 | 현장 목록 건수 | `get_projects(status=해당상태)` |
| 매출/매출액 | 세금계산서 기준 | `get_revenue_summary(year, month)` |
| 계약금액/수주액 | G2B 조달 기준 | `get_g2b_contract_detail(search=키워드)` |
| 미수금/안 받은 돈 | 미청구 세금계산서 | `get_unpaid_invoices()` |
| 재고 부족/없는 거 | 안전재고 미달 | `get_low_stock()` |
| OO현장 어떻게 | 현장 상세 | `search_projects(query="OO")` → `get_project_detail(id)` |
| 납품 예정/일정 | 납품 스케줄 | `get_deliveries(project_id)` |
| 생산 현황 | 공정 진행상태 | `get_production_by_site()` |
| AS/하자/고장 | AS 케이스 | `get_warranty_cases(status=해당상태)` |
| 만료/인증서 | 인증서 만료 | `get_cert_expiry_alerts(days=60)` |
| 배치도/타워 | 조명배치도 | `get_lighting_layouts(search=키워드)` |
| 직원/인원/사원 | 직원 목록 | `get_employees()` |
| 근무인원/출근/연차/반차 | 오늘 근무현황 | `get_today_attendance()` |
| 가공발주/외주가공/FO | 가공발주 현황 | `get_processing_orders()` |
| 출장/출장 일정 | 출장 목록 | `get_business_trips()` |
| 서류/착수계/납품계 | 서류 현황 | `get_document_list()` |
| 공구/전동공구 | 공구 목록 | `get_tools_list()` |
| 소진/자재 소진/썼어 | 소진 이력 | `get_inventory_consumption()` |
| 전체 현황/종합/요약 | KPI 요약 | `get_dashboard_summary()` |
| 입고 상세/입고번호 | 입고 상세 | `get_receiving_detail(rcv_no=번호)` |

## Tool 분류 (73개)

### 현장/프로젝트 (7개)
- `get_projects(status, year, month, search)` — 현장 목록
- `get_project_detail(project_id)` — 현장 상세
- `search_projects(query)` — 현장명/약칭/주소 통합 검색
- `get_project_timeline(project_id)` — 납품/생산 타임라인
- `get_delivery_summary(year, month)` — 납품집계 (G2B 조달 실적)
- `get_overdue_projects()` — 납기 초과 현장
- `get_project_progress(project_id)` — 설계→자재→생산→납품 진행률

### G2B 조달 (2개) ★ contracts 대체
- `get_g2b_contract_detail(contract_no, search)` — G2B 계약 상세 (품목 그룹핑)
- `get_warranty_by_g2b(contract_no, search)` — G2B 기준 하자보증 조회

### 재무/매출 (4개)
- `get_revenue_summary(year, month)` — 세금계산서 기준 매출 집계
- `get_tax_invoices(year, payment_status)` — 세금계산서 목록
- `get_financial_overview()` — 총매출/미수금/수금 요약
- `get_unpaid_invoices()` — 미수금 현황

### 납품 (3개)
- `get_deliveries(project_id, status)` — 납품 현황
- `get_delivery_detail(delivery_id)` — 납품 상세 (분할 포함)
- `get_delivery_status_summary()` — 상태별 요약 통계

### 생산 (4개)
- `get_production_status(project_id, status)` — 생산 현황
- `get_production_by_site()` — 현장별 생산 카드
- `get_worker_assignments()` — 작업자 배치 현황
- `get_fab_status()` — FAB 공정 현황

### 재고 (6개)
- `get_inventory(category, search)` — 재고 현황
- `get_low_stock()` — 안전재고 미달 품목
- `get_inventory_turnover(year, month)` — 회전율 분석
- `get_stock_movements(item_id, movement_type, date_from, date_to)` — 변동 이력 (IN/OUT/ADJUST)
- `get_inventory_valuation()` — 재고 평가액
- `get_inventory_consumption(project_id, model_name, date_from, date_to)` — BOM 소진 이력

### BOM/품목 (6개)
- `get_bom_list()` — BOM 목록
- `get_bom_detail(bom_id, option_filter)` — BOM 상세 (옵션 필터)
- `calculate_bom_cost(bom_id, quantity)` — 원가 계산
- `get_items(category, search)` — 품목 목록
- `search_items(query)` — 품목 통합 검색
- `get_bom_stock_status(bom_id)` — 생산 가능 여부

### 발주/입고 (5개)
- `get_purchase_orders(status, vendor_id, project_id)` — 발주서 목록
- `get_po_detail(po_id, po_no)` — 발주서 상세
- `get_receiving_history(vendor_id, project_id, status, date_from, date_to)` — 입고 이력
- `get_receiving_detail(rcv_id, rcv_no)` — 입고 상세 (품목+발주연결)
- `get_vendor_list(search)` — 거래처 목록

### 견적 (3개)
- `get_quotations(status, search)` — 견적서 목록
- `get_quotation_detail(quotation_id)` — 견적서 상세
- `get_quote_templates()` — 견적 템플릿

### 영업 (2개)
- `get_sales_projects()` — 영업 현장 (D-day 우선순위)
- `get_contract_items_status(contract_id)` — 계약품목 상태

### AS/보증 (3개)
- `get_warranty_cases(status, defect_type, project_id)` — AS 케이스 목록
- `get_warranty_case_detail(case_id)` — AS 케이스 상세 + 로그
- `get_warranty_stats()` — 상태별/유형별 통계

### 도면 (2개)
- `get_drawings(project_id, drawing_type)` — 도면 목록
- `get_drawing_versions(drawing_id)` — 도면 버전 이력

### 카탈로그 (2개)
- `get_catalog_products(search)` — 나라장터 제품 카탈로그
- `get_catalog_price(model_name)` — 제품 단가 조회

### 인증서 (1개)
- `get_cert_expiry_alerts(days, cert_type)` — 만료 임박 인증서

### 시방서 (1개)
- `get_spec_doc_status(project_id, doc_status)` — 시방서 현황

### 조명배치도 (2개)
- `get_lighting_layouts(project_id, search)` — 배치도 목록
- `get_lighting_layout_detail(tower_id)` — 타워별 투광등 배치

### 조도검증 (2개)
- `get_illuminance_projects(status, facility_type, search)` — 조도 프로젝트
- `get_illuminance_detail(project_id)` — 조도 상세 + KS 기준 판정

### 일일보고 (2개)
- `get_daily_reports(department, date)` — 일일업무보고 목록
- `get_daily_report_detail(report_id)` — 보고 상세

### 알림 (2개)
- `get_notifications(user_id, is_read)` — 알림 목록
- `get_unread_notification_count(user_id)` — 미읽음 수

### 아카이브 (2개)
- `search_archive(query, board_type)` — 카카오워크 워크보드 검색
- `get_archive_post_detail(post_id)` — 게시글 + 댓글 상세

### 직원/근무 (2개)
- `get_employees(department, search)` — 직원 목록 + 부서별 인원수
- `get_today_attendance(target_date)` — 오늘 근무인원 (연차/반차 반영)

### 계약 (2개) ⚠️ 빈 테이블, get_g2b_contract_detail 사용 권장
- `get_contracts()` — 항상 빈 배열 (사용 금지)
- `get_contract_detail()` — 사용 금지

### 가공발주 (2개)
- `get_processing_orders(status, vendor_id, project_id, search)` — 가공발주 목록 (외주가공)
- `get_processing_order_detail(fo_id, fo_no)` — 가공발주 상세 (품목+첨부파일)
★ 가공발주(FO번호)는 일반 발주(PO번호)와 다릅니다. "가공발주" 질문에는 get_processing_orders 사용.

### 출장관리 (2개)
- `get_business_trips(status, search)` — 출장 일정 목록
- `get_business_trip_detail(trip_id)` — 출장 상세 (참가자, 차량, 목적)

### 서류관리 (2개)
- `get_document_list(search)` — 착수계/납품계 서류 패키지 목록
- `get_document_detail(package_id)` — 서류 패키지 상세 (공문번호, 첨부파일)

### 공구관리 (1개)
- `get_tools_list(status, search)` — 전동공구 보유/불출 현황

### 대시보드 (1개)
- `get_dashboard_summary()` — 전체 KPI 종합 (진행현장/재고부족/입고대기/출장)

## 자주 묻는 질문 패턴 (1개 Tool로 해결)

| 질문 | 사용할 Tool (1개만!) |
|------|-----------|
| "납품해야 되는 현장 몇 건?" | `get_projects(status="계약")` |
| "진행 중인 현장 알려줘" | `get_projects(status="계약")` |
| "OO현장 어떻게 돼가?" | `search_projects(query="OO")` |
| "미수금 얼마야?" | `get_unpaid_invoices()` |
| "이번 달 매출?" | `get_revenue_summary(year=2026, month=3)` |
| "재고 부족한 거?" | `get_low_stock()` |
| "AS 접수 건?" | `get_warranty_cases(status="접수")` |
| "OO현장 계약금액?" | `get_g2b_contract_detail(search="OO")` |
| "만료 임박 인증서?" | `get_cert_expiry_alerts(days=60)` |
| "OO현장 배치도?" | `get_lighting_layouts(search="OO")` |
| "납기 지난 현장?" | `get_overdue_projects()` |
| "생산 현황?" | `get_production_by_site()` |
| "올해 수주 실적?" | `get_g2b_contract_detail(search="2026")` |
| "직원 몇 명이야?" | `get_employees()` |
| "오늘 근무 인원?" | `get_today_attendance()` |
| "누가 연차야?" | `get_today_attendance()` |

## Resource

- `lightsync://query-patterns` — 실제 사용자 질문에서 학습된 Tool 매핑 패턴 (hit_count 순).
  비슷한 질문이 오면 이 패턴을 참고하여 Tool을 선택하세요.
- `lightsync://schema` — DB 테이블 스키마 요약
- `magnatech://process` — 생산 공정 설명서
- `magnatech://products` — BOM 기준 제품 사양
- `magnatech://certifications` — 제품 인증번호
""".strip()

# host="0.0.0.0" → DNS rebinding 보호 비활성화 (외부 도메인 허용)
mcp = FastMCP(
    "light-sync-erp",
    host="0.0.0.0",
    instructions=INSTRUCTIONS,
)

register_all(mcp)
