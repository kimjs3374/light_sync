# G2B 자동 계약생성 + 설계관리 매칭 Gap Analysis

> **Date**: 2026-03-18
> **Feature**: g2b-auto-contract
> **Design Doc**: [g2b-auto-contract.design.md](../02-design/features/g2b-auto-contract.design.md)

---

## Match Rate: 100%

---

## Checklist

| ID | Design Requirement | Implementation | Status |
|----|-------------------|----------------|:------:|
| FR-01 | sync-g2b 후 미연동 G2B 자동 Project+Contract 생성 | `auto_create_contracts()` in g2b_procurement_sync.py | PASS |
| FR-02 | 자동생성 Project: status='G2B자동', is_contracted=True | Project 생성 시 status='G2B자동', is_contracted=True 설정 | PASS |
| FR-03 | g2b_contract_no 중복 생성 방지 | existing_g2b_nos set으로 사전 조회 후 skip | PASS |
| FR-04 | 취소건(prdct_amt=0 AND prdct_qty=0) 제외 | valid_items 필터에서 제외 | PASS |
| FR-05 | 계약상세 "설계현장 연결" 버튼 + 모달 | contract_detail.html에 버튼 + mergeDesignModal 추가 | PASS |
| FR-06 | 설계프로젝트 자식 엔티티 병합 | api_merge_design_project에서 6종 엔티티 project_id 변경 | PASS |
| FR-07 | 병합 후 설계 프로젝트 비활성화 | source.status = '병합완료' 처리 | PASS |

## Design vs Implementation Comparison

### 1. auto_create_contracts (g2b_procurement_sync.py)

**Design**: G2bProcurement를 cntrct_dlvr_req_no 기준 그룹핑 -> Project + Contract + ContractItem 자동 생성
**Implementation**: 정확히 설계대로 구현됨
- 이미 연동된 g2b_contract_no 사전 조회 (set)
- defaultdict로 그룹핑
- 취소건 필터 (prdct_amt=0 AND prdct_qty=0)
- Project 채번: YYYY-NNN 기존 규칙 준수
- Contract: g2b_contract_no 연결
- ContractItem: 품목별 생성

### 2. CLI 통합 (app.py)

**Design**: flask sync-g2b 실행 시 동기화 + 자동생성 한번에 수행
**Implementation**: sync 완료 후 auto_create_contracts 호출, --no-auto-contract 플래그로 비활성화 가능

### 3. 설계프로젝트 검색 API (routes/project.py)

**Design**: GET /api/design-projects/search
**Implementation**: 미계약 + 병합완료 아닌 프로젝트만 검색, 최대 50건 반환

### 4. 병합 API (routes/project.py)

**Design**: POST /api/project/{id}/merge-design/{design_id}
**Implementation**: 6종 자식 엔티티(materials, contacts, drawings, history_logs, deliveries, sports_modules) project_id 일괄 변경, 히스토리 로그 기록

### 5. UI (contract_detail.html)

**Design**: "설계현장 연결" 버튼 + 검색 모달
**Implementation**: 헤더 액션 영역에 버튼 추가, 모달에서 검색/선택/확인/병합 처리

---

## Gap List

No gaps found.

---

## Conclusion

모든 설계 요구사항이 구현에 정확히 반영되었습니다. Match Rate 100%.
