# G2B Contract Match Design

## 1. Data Model Change

### Contract 테이블 확장
```sql
ALTER TABLE contracts ADD COLUMN g2b_contract_no VARCHAR(30) NULL;
```
- `g2b_contract_no`: G2bProcurement.cntrct_dlvr_req_no 참조
- nullable, 매칭 전 NULL

## 2. Matching Algorithm

### 2.1 점수 체계 (총 100점)

| 항목 | 최대점수 | 로직 |
|------|---------|------|
| 날짜 | 40 | 정확일치 40, +/-7일 20, +/-30일 10 |
| 이름 | 30 | 부분문자열 매칭 (양방향) |
| 금액 | 20 | +/-15% 이내 20, +/-30% 이내 10 |
| 기관-현장명 | 10 | 부분문자열 매칭 |

### 2.2 매칭 대상 필터링 (Pre-filter)
- G2B에서 prdct_amt > 0 (취소 건 제외)
- 이미 다른 Contract에 연동된 G2B 건 제외
- 계약일 기준 +/-180일 이내만 후보

### 2.3 결과 정렬
- 점수 내림차순, 동점 시 날짜 차이 오름차순
- 최대 10건 반환

## 3. API Design

### GET /api/g2b-match/<contract_id>
- 권한: 영업부 또는 admin
- Response: `{ "candidates": [{ "req_no", "req_nm", "req_date", "dminstt", "total_amt", "score", "score_detail" }] }`

### POST /api/g2b-match/<contract_id>/link
- Body: `{ "g2b_contract_no": "..." }`
- 권한: 영업부 또는 admin
- Contract.g2b_contract_no 저장

### POST /api/g2b-match/<contract_id>/unlink
- 권한: 영업부 또는 admin
- Contract.g2b_contract_no = NULL

## 4. UI Design

### 4.1 contract_detail.html
- 각 계약 카드 헤더에 "G2B 연동" 버튼 추가
- 이미 연동된 경우: 연동 번호 표시 + 해제 버튼
- 미연동: 클릭 시 매칭 모달 오픈
- 모달: 후보 목록 테이블 (점수바, 계약명, 기관, 금액, 날짜) + 선택 버튼

### 4.2 procurement_list.html
- 계약번호 옆에 "ERP 연동" 뱃지 (연동된 경우)
- 클릭 시 해당 ERP 계약 상세로 이동

## 5. Implementation Order
1. entities.py - Contract.g2b_contract_no 추가
2. DB 마이그레이션 스크립트
3. routes/procurement.py - 매칭 API 3개
4. templates/contract_detail.html - G2B 매칭 모달
5. templates/procurement_list.html - 연동 뱃지
