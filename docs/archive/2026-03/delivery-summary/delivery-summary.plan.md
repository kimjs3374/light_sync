# Delivery Summary Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 조달내역(G2bProcurement) 데이터가 1,600건 이상 쌓여있지만 년도별/모델별/월별 집계 화면이 없어서 보고서 작성 시 매번 수작업 엑셀 정리 필요 |
| Solution | 조달내역 기반 납품집계 페이지 — 년도/모델명 필터 + 월별 계약수량/금액 피벗 테이블 + Chart.js 그래프 + 엑셀 다운로드 |
| Function UX Effect | 필터 선택 즉시 월별 집계 테이블 + 막대/라인 차트 갱신. 엑셀 버튼 1클릭으로 보고용 파일 생성. 인쇄 최적화 CSS로 보고서 출력 가능 |
| Core Value | 조달실적 분석 시간 절감. 경영진 보고 + 영업 실무 양용 가능 |

## 1. Background

나라장터(G2B) 조달내역이 `g2b_procurements` 테이블에 1,600건 이상 축적됨.
현재 `procurement_list.html`에서 리스트 조회는 가능하나, 년도별/모델별/월별 집계 기능이 없어서:
- 보고서 작성 시 수작업 엑셀 피벗 → 시간 낭비
- 모델별 추이 분석 불가
- 경영진 보고와 영업 실무가 분리된 데이터로 운영

## 2. Goal
- 조달내역 기반 년도/모델명/월별 계약수량·금액 피벗 집계
- 업무용 테이블 뷰 + 보고용 차트 뷰 동시 제공
- 엑셀 다운로드 (openpyxl)
- 인쇄 최적화

## 3. Scope

### In Scope
- **신규 라우트**: `GET /procurement/summary` (집계 페이지)
- **신규 라우트**: `GET /procurement/summary/excel` (엑셀 다운로드)
- **필터**: 년도 (select, 다중 가능), 모델명 (품명 기준 검색/선택)
- **집계 테이블**: 행=모델명, 열=1~12월 + 합계. 셀=수량(건수)/금액
- **차트**: Chart.js — 월별 수량 막대차트 + 금액 라인차트 (모델별 색상 구분)
- **엑셀 출력**: openpyxl로 피벗 테이블 그대로 + 합계행/열 포함
- **인쇄 CSS**: @media print 최적화
- **사이드바 메뉴 추가**

### Out of Scope
- ERP 계약(Contract)과의 교차 분석 (향후 확장)
- 조달내역 수정/입력 (읽기 전용)
- 수요기관별 집계 (1차 범위 밖)

## 4. Success Criteria
- 년도+모델 필터 적용 시 집계 응답 < 1초
- 엑셀 다운로드 정상 동작 (한글 파일명)
- 차트에서 월별 추이 시각적 확인 가능
- 집계 합계 = 개별 건수 합과 일치 (데이터 정합성)

## 5. Technical Approach

### 5.1 데이터 소스
- `G2bProcurement` 테이블
- 년도: `cntrct_dlvr_req_date`의 year 추출
- 월: `cntrct_dlvr_req_date`의 month 추출
- 모델명: `prdct_clsfc_no_nm` (품명) 기준 그룹핑. `dtil_prdct_clsfc_no_nm` (세부품명)도 보조 표시
- 수량: `prdct_qty` 합계
- 금액: `prdct_amt` 합계

### 5.2 집계 쿼리
```sql
SELECT
    prdct_clsfc_no_nm AS model,
    EXTRACT(MONTH FROM cntrct_dlvr_req_date) AS month,
    SUM(prdct_qty) AS total_qty,
    SUM(prdct_amt) AS total_amt,
    COUNT(*) AS count
FROM g2b_procurements
WHERE EXTRACT(YEAR FROM cntrct_dlvr_req_date) IN (:years)
GROUP BY prdct_clsfc_no_nm, EXTRACT(MONTH FROM cntrct_dlvr_req_date)
ORDER BY prdct_clsfc_no_nm, month
```

### 5.3 UI 구조
```
┌──────────────────────────────────────────────────────┐
│ 납품집계                                              │
│ [년도: 2026 ▼] [모델명: 전체 ▼]  [검색]  [엑셀] [인쇄]│
├──────────────────────────────────────────────────────┤
│ 📊 차트 영역 (Chart.js)                              │
│  - 월별 수량 막대 + 금액 라인 (모델별 색상)             │
├──────────────────────────────────────────────────────┤
│ 📋 집계 테이블                                        │
│  모델명 | 1월 | 2월 | ... | 12월 | 합계              │
│  STA-200| 10  | 15  | ... |  8   | 120              │
│  ARENA  |  5  |  0  | ... | 12   |  85              │
│  합계   | 15  | 15  | ... | 20   | 205              │
└──────────────────────────────────────────────────────┘
```

## 6. Implementation Order
1. 집계 유틸리티 함수 (modules/)
2. Route + 엑셀 다운로드 엔드포인트
3. 템플릿 (테이블 + Chart.js + 필터)
4. 사이드바 메뉴 추가
