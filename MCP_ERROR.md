# MCP API 사용 주의사항

## 1. 조달 계약금액 조회

### ❌ 잘못된 방법
```
get_revenue_summary(year=2025)  // 세금계산서 기준
get_tax_invoices(year=2025)     // 청구 기준
```

### ✅ 올바른 방법
```
get_g2b_contract_detail(search="키워드")  // G2B 조달내역 기반
// 계약 시점 기준 데이터 사용
```

### 차이점
| 구분 | 세금계산서 | 조달 계약 |
|------|---------|---------|
| 기준 | 청구 시점 | 계약 시점 |
| 금액 | 청구액 | 계약금액 |
| 예시 | 2025년 12억2천만원 | 2025년 44억원 |

### 교훈
- **계약금액** 조회 → `get_g2b_contract_detail()` 사용
- **매출액(청구기준)** 조회 → `get_revenue_summary()` / `get_tax_invoices()` 사용

---

## 2. contracts 테이블 — 이제 사용 중 (2026-07-09 재확인)

### 현황 (2026-07-09 실측)
- `contracts` 테이블: **1,300건** — G2B 동기화로 자동 생성됨
- `g2b_procurements` 테이블: **1,673건** (실제 조달 이력)
- `tax_invoices` 테이블: **15,477건** (매출 2,671 / 매입 12,806)
- `warranties` 테이블: **1,253건**

> ⚠️ 2026-03-21 시점의 "contracts 0건, get_contracts() 항상 빈 배열" 기록은
> **더 이상 사실이 아닙니다.** 이 잘못된 안내가 server.py INSTRUCTIONS 에도
> 들어 있어서 LLM 이 계약 조회를 일부러 우회하고 있었습니다. (2026-07-09 수정)

### 용도 구분
- 조달 원문(품목·금액·납기) → `get_g2b_contract_detail()`
- 수금상태(payment_status)·현장연결 → `get_contracts()` / `get_contract_detail()`
- 하자보증 → `get_warranty_by_g2b()`
- 계약금액은 `g2b_procurements.prdct_amt` 합산으로 산출

---

## 2-1. tax_invoices 는 매출·매입 혼재 ⚠️ (2026-07-09 발견)

`direction` 컬럼으로 매출/매입을 구분합니다. **매입이 매출의 약 5배**입니다.

| direction | 건수 |
|-----------|------|
| 매출 | 2,671 |
| 매입 | 12,806 |

direction 필터 없이 합산하면 매출이 2배 가까이 부풀려집니다.
실제로 `get_revenue_summary(2025)` 가 65.4억 대신 **121.1억**을 반환하고 있었습니다.

- 매출 집계: `get_revenue_summary(year, direction='매출')` — 기본값이 '매출'
- 매입/지출: `get_purchase_summary(year, month, vendor)` — 2026-07-09 신설
- 목록: `get_tax_invoices(direction='매출'|'매입'|'all')`
- `tax_invoices` 에 `g2b_procurement_id` 컬럼은 **없습니다**. 매칭 판정은
  `contract_id` 또는 `match_status`(자동매칭/수동매칭/미매칭) 로 하세요.

---

## 2-2. production_processes 에 없는 컬럼 ⚠️ (2026-07-09 발견)

실제 컬럼: `process_code`, `process_name`, `step_order`, `status`,
`progress_qty`, `progress_percent`, `started_at`, `completed_at`

**존재하지 않는 컬럼**: `stage`, `worker_name`, `item_name`, `quantity`, `note`

기존 Tool 들이 `hasattr()` 가드로 이 컬럼들을 참조해 조용히 빈 값을 반환했습니다.
그 결과 `get_fab_status()` 는 FAB 필터가 걸리지 않아 전체 공정 5,327건을 "FAB"로,
`get_worker_assignments()` 는 전원을 "미배정" 한 덩어리로 반환했습니다.
→ 두 Tool 을 `get_process_summary()` / `get_work_logs()` 로 재설계 (2026-07-09).

작업자 정보의 유일한 근거는 `production_daily_logs.created_by`(기록자)입니다.

---

## 3. MCP Tool 추가 이력

### 2026-07-09 — 전체 점검 + 전자결재·인사 도메인 추가 (100 → 111 Tool)

전 Tool 실호출 점검 후 결함 수정 및 미커버 도메인 보강.

| 구분 | 내용 |
|------|------|
| 버그 | `get_revenue_summary`/`get_tax_invoices`/`get_financial_overview` direction 미필터 → 매출 2배 과대계상 |
| 버그 | `get_contracts` "항상 빈 배열" 안내가 거짓 (실제 1,300건) |
| 버그 | `get_fab_status`·`get_worker_assignments` 가 없는 컬럼 참조 → 재설계 |
| 버그 | `get_tax_invoices.g2b_matched` 가 없는 컬럼 참조 → 항상 False |
| 성능 | limit 없던 `get_fab_status`(5,327) `get_vendor_list`(3,738) `get_production_by_site`(1,268) `get_worker_assignments`(625KB) 에 limit + total/truncated 추가 |
| 신설 | 전자결재 4종: `get_approval_documents`, `get_approval_detail`, `get_my_pending_approvals`, `get_my_approval_drafts` |
| 신설 | 인사/연차 4종: `get_leave_balance`, `get_leave_calendar`, `get_leave_promotion_status`, `get_employee_card` |
| 신설 | 재무 1종: `get_purchase_summary` (매입 거래처별 지출) |
| 신설 | 생산 2종: `get_process_summary`, `get_work_logs` (fab/worker 대체) |
| 신설 | 쓰기 1종: `write_preview_leave_request` (휴가 상신 → confirm_leave_request) |
| 변경 | `get_today_attendance` 가 카카오워크 ICS → 전자결재 휴가신청서 기준으로 전환 |

**연차/휴가 로직은 직접 계산 금지.** `hr_service.leave_summary()` 와
`approval_service.get_approved_leaves_for_date/_for_month()` 를 재사용해야
ERP 화면과 숫자가 일치합니다.

### 2026-06-19 — 미등록 모듈 일괄 등록 (+17 Tool → 100개)

`tools/` 폴더에 구현돼 있으나 `tools_registry.py`에 **import/register 누락**돼 있던
6개 모듈을 등록. (그동안 INSTRUCTIONS에는 일부 문서화돼 있었으나 실제 호출 불가 상태였음)

| 모듈 | Tool | 용도 |
|------|------|------|
| material_order.py | `get_material_orders`, `get_material_orders_by_project` | 현장 계약품목 발주 진행상태 |
| incoming_overview.py | `get_incoming_overview` | 발주품목 입고 추적 통합 |
| billing.py | `get_billing_status` | 청구관리(미청구/청구완료/부분입금) |
| vehicle_log.py | `get_vehicle_logs`, `get_vehicle_log_summary` | 차량 운행기록부 |
| dept_report.py | `get_dept_weekly_report` | 부서별 주간 KPI |
| write_ops.py | `write_preview_*` 10종 | 쓰기작업(확인 후 DB 반영) |

**⚠️ 함께 수정한 버그**: `routes/mattermost_action.py`의 `WRITE_CONFIRM_ACTIONS`
게이트에 `confirm_production_complete_all`, `confirm_email_send`가 빠져 있어
해당 preview의 **확인 버튼이 "알 수 없는 action_type"으로 실패**하던 문제를 수정.

**write_preview_* 패턴 주의**: 이 도구들은 즉시 DB를 바꾸지 않고 preview/토큰만 반환.
실제 반영은 사용자가 채팅 확인 버튼 클릭 → `/mattermost/action`에서 처리.
한 작업당 1회만 호출하고, `status=needs_info`면 `question`으로 추가 질문할 것.

### 2026-03-22 추가 (8개 Tool)

| Tool | 파일 | 용도 | 상태 |
|------|------|------|------|
| `get_g2b_contract_detail` | g2b.py | G2B 계약 상세 (contracts 대체) | ✅ 완료 |
| `get_warranty_by_g2b` | g2b.py | G2B 계약번호 기준 하자보증 조회 | ✅ 완료 |
| `get_cert_expiry_alerts` | certification.py | 만료 임박 인증서 알림 | ✅ 완료 |
| `get_spec_doc_status` | spec_doc.py | 현장별 시방서 반영 현황 | ✅ 완료 |
| `get_lighting_layouts` | lighting_layout.py | 조명배치도 목록 조회 | ✅ 완료 |
| `get_lighting_layout_detail` | lighting_layout.py | 타워별 투광등 배치 상세 | ✅ 완료 |
| `get_illuminance_projects` | illuminance.py | 조도설계 검증 프로젝트 목록 | ✅ 완료 |
| `get_illuminance_detail` | illuminance.py | 조도설계 상세 + KS 기준 판정 | ✅ 완료 |

### 미구현 (개발 대기)

(없음 — 2026-06-19 기준 구현된 모든 Tool 모듈이 registry에 등록됨)
