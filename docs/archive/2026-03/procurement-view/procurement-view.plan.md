# procurement-view Planning Document

> **Summary**: 나라장터 조달내역(1,545건) 조회 UI + 계약관리/설계 매칭 연동
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: Claude (PDCA)
> **Date**: 2026-03-17
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 나라장터 조달내역 1,545건(2015~2026, 547억원)이 DB에 수집되었으나, ERP에서 조회/분석할 UI가 없고 기존 계약관리(Contract)와 연결되지 않아 영업/설계 단계에서 과거 실적 참조가 불가능하다. |
| **Solution** | 조달내역 전용 조회 페이지(검색/필터/통계) + 계약 등록 시 조달내역 자동 매칭 기능 구현. 수요기관명·물품규격명으로 기존 Project와 연결 가능하도록 한다. |
| **기능/UX 효과** | 연도·품목·수요기관별 필터링으로 과거 실적 즉시 조회, 계약 등록 시 "나라장터 연결" 버튼으로 조달내역 자동 가져오기, 대시보드에 월별 수주 추이 표시. |
| **핵심 가치** | 영업팀 과거 실적 기반 영업 전략 수립, 설계팀 납품 이력 참조로 사양 결정 신속화, 경영진 수주 현황 실시간 파악. |

---

## 1. Overview

### 1.1 Purpose

DB에 축적된 나라장터 조달내역(G2bProcurement 1,545건)을 ERP 내에서 조회·분석·활용할 수 있는 UI를 제공하고, 기존 계약관리(Contract/ContractItem) 및 설계(Project)와 연동하여 과거 실적 기반 업무를 가능하게 한다.

### 1.2 Background

- `g2b_procurement_sync.py`로 2015~2026년 조달내역 **1,545건, 약 547억원** 수집 완료
- 품목별: LED투광등 421건(342억), 스테인리스가로등주 264건, 조명타워 159건 등 11개 카테고리
- 수요기관: 전국 150+ 기관 (전남 지자체 집중)
- 일일 cron 동기화 API(`/api/sync_g2b_procurement`) 구현 완료
- 현재 이 데이터를 볼 수 있는 UI가 없음

### 1.3 Related Documents

- 나라장터 API 명세: `조달청_OpenAPI참고자료_나라장터_종합쇼핑몰품목정보서비스_1.0.pdf`
- 기존 모델: `modules/models/entities.py` (G2bProcurement, ProductCatalog, Contract, Project)
- 동기화 서비스: `modules/services/g2b_procurement_sync.py`
- 카탈로그 UI: `routes/catalog.py`, `templates/catalog_list.html`

---

## 2. Scope

### 2.1 In Scope

| # | 기능 | 우선순위 |
|---|------|----------|
| 1 | 조달내역 목록 조회 페이지 (검색/필터/정렬/페이지네이션) | P0 |
| 2 | 연도·품목·수요기관·계약방법별 필터 | P0 |
| 3 | 상단 통계 카드 (총 건수, 총 금액, 올해 실적, 품목별 비율) | P0 |
| 4 | 수동 동기화 버튼 (벌크/일일) - 카탈로그 페이지에서 이동 | P1 |
| 5 | 계약 등록 시 조달내역 연결 (Contract ↔ G2bProcurement 매칭) | P1 |
| 6 | Project 자동 매칭 (수요기관명/공사명 유사도 기반) | P2 |

### 2.2 Out of Scope

- 조달내역 직접 수정/삭제 (API 원본 보존 원칙)
- 차트/그래프 시각화 (추후 대시보드 확장 시 별도 기능)
- 타 업체 조달내역 조회 (매그나텍 전용)

---

## 3. Data Model

### 3.1 기존 모델 활용 (변경 없음)

```
G2bProcurement (g2b_procurements) - 이미 구현됨
├── cntrct_dlvr_req_no (PK 조합)   계약납품요구번호
├── cntrct_dlvr_req_date            계약일자
├── cntrct_dlvr_req_nm              계약명(공사명)
├── dminstt_nm                      수요기관명
├── dminstt_rgn_nm                  지역
├── dtil_prdct_clsfc_no_nm          세부품명
├── prdct_idnt_no_nm                물품규격명
├── prdct_amt                       금액
├── prdct_qty                       수량
├── cntrct_mthd_nm                  계약방법
├── dlvr_tmlmt_date                 납품기한
└── ...
```

### 3.2 연동용 컬럼 추가 (Contract 테이블)

```python
# Contract 모델에 추가
g2b_req_no = Column(String(30), nullable=True)  # 조달내역 연결 (cntrct_dlvr_req_no)
```

이 컬럼으로 Contract ↔ G2bProcurement 1:1 매칭 가능.

---

## 4. UI Design

### 4.1 조달내역 목록 페이지 (`/procurement`)

```
┌─────────────────────────────────────────────────────┐
│ 📋 나라장터 조달내역                    [동기화 ▼]   │
├─────────────────────────────────────────────────────┤
│ [총 1,545건] [547억원] [2026년 33건/5.2억] [LED투광등 27%] │
├─────────────────────────────────────────────────────┤
│ 검색: [________________] 연도: [전체▼]               │
│ 품목: [전체▼]  수요기관: [전체▼]  계약방법: [전체▼]    │
├─────┬──────┬─────────┬──────┬─────┬──────┬──────────┤
│ 일자 │ 품목  │ 규격명   │수요기관│ 수량 │  금액  │ 계약방법  │
├─────┼──────┼─────────┼──────┼─────┼──────┼──────────┤
│03.12│LED보안등│MT-SLA.. │여수시 │  14 │11.2M │ 제한경쟁 │
│03.04│철제가로│MTPF-201│여수시 │  26 │17.4M │ 수의계약 │
│ ... │      │         │      │     │      │          │
├─────┴──────┴─────────┴──────┴─────┴──────┴──────────┤
│                    < 1 2 3 ... 52 >                  │
└─────────────────────────────────────────────────────┘
```

### 4.2 계약 등록 시 조달내역 연결 (기존 계약 상세 페이지)

```
계약 상세 > [🔗 조달내역 연결] 버튼 클릭 시:
┌─────────────────────────────────────┐
│ 조달내역 검색                        │
│ [계약명/수요기관 자동검색_________]   │
│                                     │
│ ☐ R26TB01655701 | 여수시 | LED보안등 │
│ ☐ R26TB01558371 | 충주시 | LED투광등 │
│                    [연결]  [취소]     │
└─────────────────────────────────────┘
```

---

## 5. Implementation Plan

### 5.1 파일 목록

| # | 파일 | 작업 | 설명 |
|---|------|------|------|
| 1 | `routes/procurement.py` | 신규 | 조달내역 조회 Blueprint |
| 2 | `templates/procurement_list.html` | 신규 | 목록 페이지 템플릿 |
| 3 | `modules/models/entities.py` | 수정 | Contract.g2b_req_no 컬럼 추가 |
| 4 | `app.py` | 수정 | procurement_bp 등록 |
| 5 | `templates/base.html` | 수정 | 사이드바 메뉴 추가 |
| 6 | `routes/contract.py` | 수정 | 조달내역 연결 액션 추가 |

### 5.2 구현 순서

```
Phase 1 (P0): 조회 페이지
  1. routes/procurement.py - 목록 조회 + 검색/필터
  2. templates/procurement_list.html - UI 템플릿
  3. app.py - Blueprint 등록 + 사이드바 메뉴

Phase 2 (P1): 계약 연동
  4. Contract.g2b_req_no 컬럼 추가
  5. 계약 상세에서 조달내역 연결 기능
  6. 카탈로그 페이지에 조달내역 동기화 버튼

Phase 3 (P2): 고급 매칭
  7. Project ↔ G2bProcurement 자동 매칭 (수요기관명/공사명)
```

### 5.3 접근 권한

| 메뉴 | 권한 |
|------|------|
| 조달내역 조회 | 전체 사용자 (읽기 전용) |
| 동기화 버튼 | admin만 |
| 계약 연결 | admin, 영업부 |

---

## 6. Risk & Mitigation

| 리스크 | 대응 |
|--------|------|
| 조달내역 1,545건 목록 로딩 속도 | 페이지네이션(30건/페이지) + DB 인덱스 (cntrct_dlvr_req_date, dtil_prdct_clsfc_no_nm) |
| 공사명 기반 Project 매칭 정확도 | 자동 매칭은 후보 제시만, 최종 연결은 사용자 확인 |
| API 일일 트래픽 제한 | 일일 동기화는 전일 데이터만 (API 1~2회 호출) |

---

## 7. Success Criteria

- [ ] 조달내역 목록 페이지에서 연도/품목/수요기관 필터링 정상 동작
- [ ] 통계 카드에 총 건수·금액·올해 실적 정확히 표시
- [ ] 페이지네이션 정상 동작 (30건/페이지)
- [ ] Contract.g2b_req_no로 조달내역 ↔ 계약 1:1 연결 가능
- [ ] 관리자만 동기화 버튼 접근 가능
