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

## 2. contracts 테이블 미사용 (2026-03-21 확인)

### 현황
- `contracts` 테이블: **0건** (ERP에서 계약 등록 기능을 실무에서 사용하지 않음)
- `g2b_procurements` 테이블: **1,594건** (실제 조달 이력)
- `tax_invoices` 테이블: **2,360건** (매칭 1,278건)

### 영향
- `get_contracts()` → **항상 빈 배열 반환** (사용 금지)
- `get_contract_items_status()` → 사용 불가
- 하자보증(`warranties`)이 `contract_id` FK로 연결 → contract 없으면 생성 불가

### MCP에서 계약 정보 조회 시
- `get_contracts()` 대신 **`get_g2b_contract_detail()`** 사용 (2026-03-22 추가)
- 하자보증 조회 시 **`get_warranty_by_g2b()`** 사용 (2026-03-22 추가)
- 계약금액은 `g2b_procurements.prdct_amt` 합산으로 산출
- 매칭된 세금계산서의 `g2b_contract_no`로 조달내역 조인

---

## 3. MCP Tool 추가 이력

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
