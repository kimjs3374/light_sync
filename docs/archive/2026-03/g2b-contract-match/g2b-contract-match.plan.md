# G2B Contract Match Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | G2B 조달내역과 ERP 계약이 수동 대조되어 누락/오매칭 발생 |
| Solution | 날짜/이름/금액/기관명 기반 자동 매칭 점수 계산 + 추천 UI |
| Function UX Effect | 계약 상세에서 1-click G2B 연동, 조달목록에서 연동 뱃지 확인 |
| Core Value | 계약-조달 대사 시간 절감, 데이터 정합성 향상 |

## 1. Background
나라장터(G2B) 조달계약 데이터(G2bProcurement)와 ERP 계약(Contract)은 별도 관리됨.
영업부에서 수동으로 대조하여 매칭하고 있으나, 건수가 많아 누락이 발생함.

## 2. Goal
- Contract별 G2B 후보 자동 추천 (점수 기반)
- 1-click 연동 저장 (Contract.g2b_contract_no)
- 조달내역 목록에서 연동 상태 시각화

## 3. Scope

### In Scope
- Contract 모델에 g2b_contract_no 컬럼 추가
- 매칭 점수 알고리즘 (날짜 40 + 이름 30 + 금액 20 + 기관 10 = 100점)
- 매칭 API: GET /api/g2b-match/<contract_id>
- 연동 API: POST /api/g2b-match/<contract_id>/link
- 연동 해제 API: POST /api/g2b-match/<contract_id>/unlink
- contract_detail.html에 G2B 매칭 모달
- procurement_list.html에 연동됨 뱃지

### Out of Scope
- 자동 매칭 (사용자 확인 필수)
- G2B 품목 단위 매칭 (계약 단위만)
- 역방향 매칭 (G2B에서 ERP 계약 추천)

## 4. Success Criteria
- 매칭 정확도: 실제 매칭 건이 상위 3개 안에 포함
- 응답 시간: 매칭 API < 2초
- 연동 후 양쪽에서 확인 가능
