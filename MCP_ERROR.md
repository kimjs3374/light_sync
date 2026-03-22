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

| Tool | 용도 | 비고 |
|------|------|------|
| 가공발주 Tool | 가공발주 목록/상세 | processing_order.py 개발 완료 후 |
