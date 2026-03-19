# G2B Contract Match - Gap Analysis

## Match Rate: 95%

## Design vs Implementation Comparison

| # | Design Item | Status | Notes |
|---|-------------|--------|-------|
| 1 | Contract.g2b_contract_no 컬럼 추가 | OK | entities.py 반영, migration 스크립트 제공 |
| 2 | 날짜 점수 (최대 40) | OK | _score_date() 구현 완료 |
| 3 | 이름 유사도 (최대 30) | OK | _score_name() 공통 부분문자열 매칭 |
| 4 | 금액 근사 (최대 20) | PARTIAL | ContractItem에 단가/금액 컬럼 없어 현재 미활성. 최대 80점 체계로 동작 |
| 5 | 기관-현장명 (최대 10) | OK | _score_org() 구현 완료 |
| 6 | GET /api/g2b-match/<contract_id> | OK | 후보 10건 반환 |
| 7 | POST /api/g2b-match/<contract_id>/link | OK | 중복 검증 포함 |
| 8 | POST /api/g2b-match/<contract_id>/unlink | OK | 연동 해제 |
| 9 | contract_detail.html G2B 매칭 모달 | OK | 점수바 + 선택 버튼 |
| 10 | procurement_list.html 연동 뱃지 | OK | ERP 뱃지 + 계약상세 링크 |
| 11 | 권한 체크 (영업부/admin) | OK | _can_match() + 템플릿 조건부 렌더링 |
| 12 | DB 마이그레이션 스크립트 | OK | scripts/migrate_g2b_contract_match.py |

## Gaps

### Gap 1: 금액 매칭 미활성 (Severity: Low)
- **원인**: ContractItem에 단가/금액 컬럼이 없어 계약 총액 산출 불가
- **영향**: 100점 만점이 아닌 80점 만점 체계로 동작. 매칭 품질에 큰 영향 없음 (날짜+이름이 핵심)
- **해결**: 향후 ContractItem에 unit_price 컬럼 추가 시 활성화 가능

## Summary
- Critical Issues: 0
- Major Issues: 0
- Minor Issues: 1 (금액 매칭 미활성 - 데이터 구조 한계)
- Match Rate: 95% (11/12 항목 완전 구현, 1항목 부분 구현)
