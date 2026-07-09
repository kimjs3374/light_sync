"""Light-Sync ERP MCP 서버"""
from mcp.server.fastmcp import FastMCP
from .tools_registry import register_all

INSTRUCTIONS = """
# Light-Sync ERP MCP 서버

(주)매그나텍 LED 조명 사업부 사내 ERP 데이터를 **읽기 전용**으로 조회합니다.

## 핵심 규칙

1. **계약 정보 = G2B 조달내역**: 계약의 뿌리는 `g2b_procurements` 입니다.
   조달 원문(품목·금액·납기)은 `get_g2b_contract_detail()`, 수금상태·현장연결이 필요하면
   `get_contracts()` / `get_contract_detail()` 을 사용하세요.
2. **계약금액 ≠ 매출액**: 계약금액은 `get_g2b_contract_detail()`, 매출(청구기준)은 `get_revenue_summary()`.
3. **매출/매입은 반드시 구분**: `tax_invoices` 에 매입이 매출보다 5배 많이 들어있습니다.
   매출은 `get_revenue_summary()`(기본 direction='매출'), 매입/지출은 `get_purchase_summary()`.
   direction 없이 합산하면 매출이 2배로 부풀려집니다.
4. **현장 검색**: `search_projects()`로 현장 ID 확보 → 다른 Tool에 project_id 전달.
5. **휴가/근태는 전자결재 기준**: 카카오워크 캘린더는 더 이상 쓰지 않습니다.
   `get_today_attendance()` / `get_leave_calendar()` 모두 승인된 휴가신청서를 봅니다.
6. **Tool 1개로 해결하세요**: 여러 Tool을 순차 호출하지 말고, 가장 적합한 Tool 1개를 바로 호출하세요.

## 한국어 업무 용어 → Tool 매핑 (필독)

사용자가 한국어로 질문하면 아래 매핑을 따르세요. **추측으로 여러 Tool 시도 금지.**

| 업무 용어 | 의미 | 정확한 Tool |
|-----------|------|------------|
| 납품해야 되는/할 현장 | 계약 체결됨, 아직 납품 안 한 현장 | `get_projects(status="계약")` |
| 진행 중인 현장 | 생산/납품 중 | `get_projects(status="계약")` |
| 완료된 현장 | 납품 끝남 | `get_projects(status="납품완료")` |
| 설계 중인/영업 현장 | 아직 계약 전 | `get_projects(status="설계/영업")` |
| 현장 몇 건/개 | 현장 목록 건수 | `get_projects(status=해당상태)` |
| 매출/매출액 | 세금계산서 매출분 | `get_revenue_summary(year, month)` |
| 매입/지출/어디에 얼마 썼어 | 세금계산서 매입분, 거래처별 | `get_purchase_summary(year, month, vendor)` |
| 계약금액/수주액 | G2B 조달 기준 | `get_g2b_contract_detail(search=키워드)` |
| 미수금/안 받은 돈 | 미청구 세금계산서 | `get_unpaid_invoices()` |
| 재고 부족/없는 거 | 안전재고 미달 | `get_low_stock()` |
| OO현장 어떻게 | 현장 상세 | `search_projects(query="OO")` → `get_project_detail(id)` |
| 납품 예정/일정 | 납품 스케줄 | `get_deliveries(project_id)` |
| 생산 현황 | 현장별 공정 진행상태 | `get_production_by_site(search)` |
| 작업일지/누가 작업했어/생산실적 | 일일 작업일지 | `get_work_logs(date_from, worker)` |
| 공정별 현황/어느 단계가 막혔어 | 공정단계별 집계 | `get_process_summary(project_search)` |
| AS/하자/고장 | AS 케이스 | `get_warranty_cases(status=해당상태)` |
| 만료/인증서 | 인증서 만료 | `get_cert_expiry_alerts(days=60)` |
| 배치도/타워 | 조명배치도 | `get_lighting_layouts(search=키워드)` |
| 직원/인원/사원 | 직원 목록 | `get_employees()` |
| 근무인원/출근/연차/반차 | 오늘 근무현황 | `get_today_attendance()` |
| 연차 며칠 남았어/잔여 연차 | 연차 잔여일수 | `get_leave_balance(employee)` |
| 이번달 누가 휴가/휴가 일정 | 월간 휴가 달력 | `get_leave_calendar(year, month)` |
| 연차촉진/촉구 대상자 | 연차사용촉진 현황 | `get_leave_promotion_status()` |
| OO 입사일/근속/인사정보 | 인사카드 | `get_employee_card(employee)` |
| 결재 문서/올라온 결재/반려된 거 | 전자결재 목록 | `get_approval_documents(status, form)` |
| EA-YYYY-NNNN/그 결재 어떻게 됐어 | 결재 상세(결재선·의견) | `get_approval_detail(doc_no)` |
| 내가 결재할 거/결재 대기 | 내 결재 차례 | `get_my_pending_approvals(requester_username)` |
| 내가 올린 결재/내 상신 | 내 기안 문서 | `get_my_approval_drafts(requester_username)` |
| 가공발주/외주가공/FO | 가공발주 현황 | `get_processing_orders()` |
| 자재발주/현장별 자재/발주대기 자재 | 계약품목 발주 진행상태 | `get_material_orders(status, project_search)` |
| 입고현황/미입고/부분입고/입고지연 | 발주품목 입고 추적 | `get_incoming_overview(status, search)` |
| 청구/미청구/세금계산서 발행할 거/부분입금 | 청구관리 현황 | `get_billing_status(status, search)` |
| 운행일지/차량 운행기록/주행거리/주유 | 차량 운행기록부 | `get_vehicle_logs(vehicle, user_name)` |
| 부서 주간보고/주간 KPI/이번주 부서 현황 | 부서별 주간 집계 | `get_dept_weekly_report(dept)` |
| 출장/출장 일정 | 출장 목록 | `get_business_trips()` |
| 서류/착수계/납품계 | 서류 현황 | `get_document_list()` |
| 공구/전동공구 | 공구 목록 | `get_tools_list()` |
| 소진/자재 소진/썼어 | 소진 이력 | `get_inventory_consumption()` |
| 전체 현황/종합/요약 | KPI 요약 | `get_dashboard_summary()` |
| 입고 상세/입고번호 | 입고 상세 | `get_receiving_detail(rcv_no=번호)` |
| 거래처 이메일/메일주소 | 이메일 주소록 | `get_mail_contacts(query=키워드)` |
| 메일 보낸 이력/누구한테 메일 | 메일 송수신 이력 (DB) | `get_email_history(query/receiver/po_ref)` |
| 누가 뭐 했어/시스템 이력/변경 이력 | 시스템 활동 로그 | `get_activity_logs(user_name/module/date_from)` |
| 현장 담당자/감독관/감리/시공사 | 현장 연락처 | `get_project_contacts(project_id 또는 query=현장명)` |
| 내 메일 계정 뭐 있어/공유메일함 | 접근 가능 메일 계정 | `list_mail_accounts(requester_username)` |
| 받은편지함/안 읽은 메일/메일 왔어 | 메일함 메시지 목록 | `list_inbox_messages(requester_username, unseen_only?)` |
| 메일 검색/OO 보낸 메일 있어 | 메일함 검색 (IMAP) | `search_mailbox(requester_username, query)` |
| 이 메일 내용/본문/첨부 | 메일 본문 조회 | `read_mail_message(requester_username, uid)` |
| 메일 폴더/보관함 구조 | 폴더 목록 | `list_mail_folders(requester_username)` |
| 메일 보내줘/메일 발송/회신해줘 | 메일 발송 (확인 후 SMTP) | `write_preview_email_send(requester_username, to, subject, body, cc?, bcc?, account_id?)` |
| 연차 낼게/휴가 신청/내일 쉴게 | 휴가 상신 (확인 후 전자결재) | `write_preview_leave_request(requester_username, start_date, leave_type?, period?, reason)` |
| 납품완료 처리/AS 접수/청구완료/운행일지·출장·일일보고 등록/발주상태 변경/생산완료 | 쓰기작업 (preview→확인 버튼 클릭 후 DB 반영) | `write_preview_*` |

## ⚠️ 쓰기 작업(write_preview_*) 패턴 (필독)

`write_preview_*` 도구는 **즉시 DB를 변경하지 않습니다**. 필드 검증 후 preview(요약+확인
토큰)만 반환하고, 사용자가 채팅의 **확인 버튼**을 눌러야 Flask `/mattermost/action`에서
실제 반영됩니다(`history_logs.origin='chat_confirmed'`).
- 반환 `status=needs_info` → `question` 을 사용자에게 그대로 질문.
- 반환 `status=preview` → `summary`/`fields` 를 보여주고 확인을 받으세요.
- 절대 임의로 여러 번 호출하지 말 것. 한 작업당 1회 preview.

## ⚠️ 메일 도구 권한 정책 (필독)

메일 도구 5종(`list_mail_accounts`, `list_mail_folders`, `list_inbox_messages`,
`search_mailbox`, `read_mail_message`)은 **반드시 `requester_username` 인자
필수**. 챗봇 채널 태그의 `user="..."` 값을 그대로 전달하세요.

- 사용자 본인 개인 계정(`mail_accounts.user_id == 발신자 user_id`) 만 접근.
- 공유 계정(`is_shared=True`)은 `mail_shared_access` 권한 있을 때만 접근.
- admin role 은 모든 공유 계정 접근 (개인 계정은 본인만).
- 다른 사용자의 개인 계정은 **절대 접근 불가** — `account_id` 명시해도 차단됨.
- `requester_username` 없거나 식별 실패 시 모든 도구가 error 반환.

## Tool 분류 (111개)

### 현장/프로젝트 (8개)
- `get_projects(status, year, month, search)` — 현장 목록
- `get_project_detail(project_id)` — 현장 상세
- `search_projects(query)` — 현장명/약칭/주소 통합 검색
- `get_project_timeline(project_id)` — 납품/생산 타임라인
- `get_project_contacts(project_id, query, category)` — 현장 담당자(감독관/감리/시공사)
- `get_delivery_summary(year, month)` — 납품집계 (G2B 조달 실적)
- `get_overdue_projects()` — 납기 초과 현장
- `get_project_progress(project_id)` — 설계→자재→생산→납품 진행률

### G2B 조달 (2개) ★ contracts 대체
- `get_g2b_contract_detail(contract_no, search)` — G2B 계약 상세 (품목 그룹핑)
- `get_warranty_by_g2b(contract_no, search)` — G2B 기준 하자보증 조회

### 재무/매출 (5개)
- `get_revenue_summary(year, month, direction='매출')` — 세금계산서 기준 매출 집계
  · ⚠️ direction 기본 '매출'. 매입까지 합치면 금액이 2배가 됩니다.
- `get_purchase_summary(year, month, vendor, limit)` — 매입(지출) 거래처별 집계
  · grand_total 은 limit 무관 전체 합계, items 는 금액순 상위 N개
- `get_tax_invoices(year, payment_status, direction='매출', search)` — 세금계산서 목록
  · direction: '매출'(기본) / '매입' / 'all'
- `get_financial_overview()` — 매출/매입 총액 + 미수금/수금 요약
- `get_unpaid_invoices(months_back=24, include_old=False, status, include_exception=False)` — 미수금 현황
  · 기준: Contract.payment_status (조달내역). 통장입금 무관.
  · 기본 대상: 미청구 + 부분입금 (예외 자동 제외)
  · 부분입금 잔액 = G2B 총액 − 매칭 세금계산서 발행합계
  · 기본 최근 24개월. 사용자가 "전체"/"5년치" 명시 시 include_old=True

### 납품 (3개)
- `get_deliveries(project_id, status)` — 납품 현황
- `get_delivery_detail(delivery_id)` — 납품 상세 (분할 포함)
- `get_delivery_status_summary()` — 상태별 요약 통계

### 생산 (4개)
- `get_production_status(project_id, status, limit)` — 공정 목록 (status: 대기/진행중/완료)
- `get_production_by_site(search, limit)` — 현장별 생산 카드 + 진행률 (전체 1,268현장, 기본 30)
- `get_work_logs(date_from, date_to, worker, project_search)` — 일일 작업일지 (기본 최근 30일)
- `get_process_summary(project_search)` — 공정단계(P001~P011)별 대기/진행/완료 집계
★ production_processes 에는 stage/worker_name/item_name 컬럼이 없습니다.
  작업자는 production_daily_logs.created_by(기록자)가 유일한 근거입니다.

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

### 자재발주 (2개)
- `get_material_orders(status, project_search, material_search, limit)` — 현장 계약품목 단위 발주 진행상태 (발주대기/발주완료/입고완료)
- `get_material_orders_by_project(project_id)` — 특정 현장 자재발주 전체 + 발주율
★ 발주서(PO) 단위는 get_purchase_orders, 입고 진행 통합은 get_incoming_overview.

### 입고현황 통합 (1개)
- `get_incoming_overview(status, search, date_from, date_to, limit)` — 발주품목 입고 추적
  · status: pending(미입고)/partial(부분입고)/done(입고완료)/overdue(지연)/direct(직접입고)/all

### 청구관리 (1개)
- `get_billing_status(status, search, limit)` — 납품완료 건 청구상태 (미청구/청구완료/부분입금)
  · ⚠️ "미수금(안 받은 돈)"은 get_unpaid_invoices() — 다른 개념(세금계산서 기준)

### 운행일지 (2개)
- `get_vehicle_logs(vehicle, user_name, date_from, date_to, limit)` — 업무용차량 운행기록부
- `get_vehicle_log_summary(year, month)` — 차량별 운행 요약 (누적 km/주유금액/건수)

### 부서 주간보고 (1개)
- `get_dept_weekly_report(dept, week_start, week_end)` — 부서별 주간 KPI
  · dept: sales(영업)/production(생산)/management(관리), 한글 '영업부/생산부/관리부' 가능

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
- `get_today_attendance(target_date)` — 오늘 근무인원 (전자결재 휴가 기준, 연차/반차 반영)

### 인사/연차 (4개)
- `get_leave_balance(employee)` — 연차 부여/사용/조정/잔여 (생략 시 전 직원)
- `get_leave_calendar(year, month, employee)` — 월간 휴가 달력 (승인 휴가신청서 기준)
- `get_leave_promotion_status(year)` — 연차사용촉진제 진행 현황
- `get_employee_card(employee)` — 인사카드 (소속/입사일/근속 + 연차 요약)

### 전자결재 (4개)
- `get_approval_documents(status, form, drafter, search, limit)` — 결재 문서 목록
  · status: 작성중/진행중/완료/반려/회수, form: 휴가/지출/품의/출장/연장근무
- `get_approval_detail(doc_id, doc_no)` — 결재 상세 (양식값 + 결재선 + 의견)
- `get_my_pending_approvals(requester_username)` — 내 결재 차례 문서
- `get_my_approval_drafts(requester_username, limit)` — 내가 상신한 문서 + 진행상태

### 계약 (2개)
- `get_contracts(project_id, payment_status, limit)` — 계약 목록 (수금상태·현장연결)
- `get_contract_detail(contract_id)` — 계약 상세
★ 조달 원문(품목/금액/납기)은 `get_g2b_contract_detail()` 이 더 정확합니다.

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

### 메일 — DB 기록 (2개)
- `get_mail_contacts(query, is_shared)` — 거래처 이메일 주소록 검색 (1,000+건)
- `get_email_history(query, sender, receiver, po_ref, date_from, date_to, months_back=24, include_old)` — 자동발송 송수신 이력 (PO 자동 메일 등)
  · 기본 최근 24개월 (옛날 데이터 오염 차단). 사용자가 "전체" 명시 시 include_old=True
  · 발주 연결 메일 검색은 po_ref 사용 (예: po_ref="PO-2026-001")

### 메일함 — IMAP 실시간 조회 (5개, 권한 격리 ⚠️ requester_username 필수)
- `list_mail_accounts(requester_username)` — 접근 가능 메일 계정 (개인+공유)
- `list_mail_folders(requester_username, account_id?)` — 폴더 목록 (INBOX/Sent/Drafts/라벨)
- `list_inbox_messages(requester_username, account_id?, folder=INBOX, limit=30, unseen_only?)` — 메일 목록
- `search_mailbox(requester_username, query, account_id?, folder?, limit=30)` — 서버측 IMAP SEARCH
- `read_mail_message(requester_username, uid, account_id?, folder?, body_max_chars=10000)` — 본문+첨부 메타
  · 모든 도구에서 본인 계정 또는 공유권한 있는 계정만 접근 (다른 사용자 계정 차단)

### 쓰기 작업 — write_preview 패턴 (11개) ⚠️ preview→확인 버튼 후 반영
- `write_preview_delivery_complete(project_search, completed_date?)` — 납품완료 처리
- `write_preview_as_register(project_search, defect_type?, symptom?, received_date?)` — AS(하자) 접수 등록
- `write_preview_billing_complete(project_search, invoice_date?)` — 청구완료(세금계산서 발행) 처리
- `write_preview_vehicle_log(destination?, distance_km?, purpose?, vehicle?, use_date?, driver_name?)` — 운행일지 등록
- `write_preview_business_trip(destination?, departure_date?, travelers?, purpose?, vehicle?, return_date?, ...)` — 출장 등록
- `write_preview_daily_report(department?, items?, report_date?, reporter_name?)` — 일일업무보고 등록
- `write_preview_po_status(po_search?, new_status?)` — 발주서 상태 변경 (작성중/발송완료/입고대기/입고완료/취소)
- `write_preview_production_complete(keyword?, process_id?, completed_date?)` — 단일 공정 생산완료
- `write_preview_production_complete_all(keyword?, contract_item_id?, quantity?, completed_date?)` — 계약품목 일괄 생산완료
- `write_preview_leave_request(requester_username, start_date, end_date?, leave_type?, period?, reason)` — 휴가 상신 (전자결재)
  · 결재선 자동 구성(부서장→임원진). 본인 명의만 가능. 승인 시 연차 자동 차감.
  · 모두 `status=needs_info`면 question 으로 추가 질문, `status=preview`면 확인 버튼 제시.

### 메일 발송 — write_preview 패턴 (1개, 권한 격리 ⚠️)
- `write_preview_email_send(requester_username, to, subject, body, cc?, bcc?, account_id?, request_read_receipt=True, large_file_ids?)` — 메일 발송 preview
  · 사용자 확인 버튼 클릭 후 confirm_email_send 액션 → 실 SMTP 송신
  · 권한 검증 2회 (preview + confirm) — 다른 사람 계정 발송 차단
  · 공유 계정 사용 시 `mail_shared_access.can_send` 권한 필수 (admin 예외)
  · 본문 plain text 면 자동 HTML 변환 (\n → <br>)
  · 수신확인 트래킹 픽셀 자동 삽입 (기본 활성)
  · MailContact 자동 수집 (외부 이메일만), MailReadReceipt 생성
  · **첨부파일**: `large_file_ids=["abc123", ...]` 로 ERP 메일 화면에서
    미리 업로드한 파일(`mail_large_files`) 의 file_id 배열 전달.
    본문 끝에 다운로드 링크 자동 삽입 (외부 수신자도 클릭 다운로드).
    권한: **본인 업로드 파일만 첨부 가능** (admin 예외).

### 시스템 활동 로그 (1개)
- `get_activity_logs(user_name, module, action, project_id, ref_type, date_from, date_to, query, months_back=12, include_old)` — 시스템 활동 1,000+건
  · 기본 최근 12개월. 사용자/모듈/액션/현장/참조타입 다축 필터
  · "오늘 누가 뭐 했어?" / "OO현장 작업 이력" 같은 질문에 사용

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
| "OO 거래처 이메일?" | `get_mail_contacts(query="OO")` |
| "최근 누구한테 메일 보냈어?" | `get_email_history()` (기본 24개월) |
| "PO-2026-001 관련 메일?" | `get_email_history(po_ref="PO-2026-001")` |
| "오늘 누가 뭐 했어?" | `get_activity_logs(date_from="오늘")` |
| "김정수가 협의관리 뭐 변경했어?" | `get_activity_logs(user_name="김정수", module="협의관리")` |
| "OO현장 작업 이력?" | `get_activity_logs(project_id=N)` |
| "발주대기 자재 뭐 있어?" | `get_material_orders(status="발주대기")` |
| "아직 입고 안 된 거?" | `get_incoming_overview(status="pending")` |
| "청구해야 할 거 있어?" | `get_billing_status(status="미청구")` |
| "이번달 운행거리?" | `get_vehicle_log_summary(year=2026, month=6)` |
| "영업부 이번주 주간보고?" | `get_dept_weekly_report(dept="sales")` |
| "OO현장 납품완료 처리해줘" | `write_preview_delivery_complete(project_search="OO")` |
| "OO현장 AS 접수해줘" | `write_preview_as_register(project_search="OO", ...)` |
| "OO현장 감독관 누구야?" | `search_projects(query="OO")` → `get_project_contacts(project_id=ID)` |
| "OO현장 시공사 연락처?" | `get_project_contacts(project_id=N, category="공사업체")` |
| "내 메일계정 뭐 있어?" | `list_mail_accounts(requester_username)` |
| "받은편지함 보여줘" | `list_inbox_messages(requester_username)` |
| "안 읽은 메일 있어?" | `list_inbox_messages(requester_username, unseen_only=True)` |
| "OO한테 받은 메일 검색" | `search_mailbox(requester_username, query="OO")` |
| "이 메일 내용 알려줘" | `read_mail_message(requester_username, uid=N)` |
| "OO한테 메일 보내줘" | `write_preview_email_send(requester_username, to, subject, body)` |

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
