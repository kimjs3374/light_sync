# MCP API 사용 주의사항

## 1. 조달 계약금액 조회

### ❌ 잘못된 방법
```
get_revenue_summary(year=2025)  // 세금계산서 기준
get_tax_invoices(year=2025)     // 청구 기준
```

### ✅ 올바른 방법
```
get_contracts() 또는 조달 계약 관련 API
// 계약 시점 기준 데이터 사용
```

### 차이점
| 구분 | 세금계산서 | 조달 계약 |
|------|---------|---------|
| 기준 | 청구 시점 | 계약 시점 |
| 금액 | 청구액 | 계약금액 |
| 예시 | 2025년 12억2천만원 | 2025년 44억원 |

### 교훈
- **계약금액** 조회 → 조달 계약 테이블 사용
- **매출액(청구기준)** 조회 → 세금계산서 사용

---

## 2. contracts 테이블 미사용 (2026-03-21 확인)

### 현황
- `contracts` 테이블: **0건** (ERP에서 계약 등록 기능을 실무에서 사용하지 않음)
- `g2b_procurements` 테이블: **1,594건** (실제 조달 이력)
- `tax_invoices` 테이블: **2,360건** (매칭 1,278건)

### 영향
- `get_contracts()` → **항상 빈 배열 반환**
- `get_contract_items_status()` → 사용 불가
- 하자보증(`warranties`)이 `contract_id` FK로 연결 → contract 없으면 생성 불가

### MCP에서 계약 정보 조회 시
- `get_contracts()` 대신 **`get_deliveries()`** 또는 **G2B 조달내역** 기반으로 조회
- 계약금액은 `g2b_procurements.prdct_amt` 합산으로 산출
- 매칭된 세금계산서의 `g2b_contract_no`로 조달내역 조인

---

## 3. MCP 추가 필요 Tool (2026-03-21)

| Tool | 용도 | 비고 |
|------|------|------|
| `get_warranty_by_g2b` | G2B 계약번호 기준 하자보증 조회 | warranty 구조 변경 후 |
| `get_cert_expiry_alerts` | 만료 임박 인증서 알림 | certifications 테이블 |
| `get_spec_doc_status` | 현장별 시방서 반영 현황 | spec_documents 테이블 |
| `get_g2b_contract_detail` | G2B 계약 상세 (계약 대용) | g2b_procurements 그룹핑 |
