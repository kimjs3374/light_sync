# product-catalog Planning Document

> **Summary**: 나라장터(G2B) API 연동 제품 카탈로그 구축 및 계약 품목 단가 자동화
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: CTO Lead (PDCA Team)
> **Date**: 2026-03-17
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 계약 품목(ContractItem)에 단가 정보가 없어, 영업/주간보고서에서 금액 파악이 불가능하고 나라장터 단가 변동을 수동으로 확인해야 한다. |
| **Solution** | ProductCatalog 모델을 신규 생성하여 나라장터 종합쇼핑몰 API(다수공급자 226건 + 제3자단가 41건)에서 계약단가를 자동 수집하고, 미등록 148건은 수기 입력 UI를 제공한다. |
| **기능/UX 효과** | 버튼 한 번으로 API 동기화 완료, ContractItem과 자동 매칭으로 영업관리/주간보고서에 품목별 예상금액(수량 x 단가) 즉시 표시. |
| **핵심 가치** | 영업팀의 단가 조회 시간 제거, 견적/보고서 금액 정확도 향상, 나라장터 계약단가 변동 이력 추적 가능. |

---

## 1. Overview

### 1.1 Purpose

매그나텍이 나라장터(조달청 G2B)에 등록한 제품의 계약단가를 ERP 시스템에서 관리하고, 계약 품목(ContractItem)과 연동하여 금액 기반 업무 처리를 가능하게 한다.

### 1.2 Background

- 매그나텍은 나라장터에 **다수공급자(MAS) 226건**, **제3자단가 41건** 총 267건(중복 제거 후 241건)의 제품을 등록하고 있다.
- 현재 ERP의 `ContractItem`에는 `model_name`, `quantity`만 있고 **단가(unit_price) 필드가 없다**.
- 영업팀은 단가 확인을 위해 나라장터 웹사이트를 별도 조회하고 있으며, 주간보고서에도 금액 정보가 빠져 있다.
- 물품목록 API(389건)에는 단가가 없고, **종합쇼핑몰 품목정보 API**에서만 `cntrctPrceAmt`(계약단가)를 취득할 수 있다.
- 241건 중 **148건은 API에 단가가 없어** `magnatech_missing_prices.xlsx`로 출력 완료, 수기 입력이 필요하다.

### 1.3 Related Documents

- 나라장터 API 명세: `조달청_물품목록정보서비스 API 명세서.docx` (프로젝트 루트)
- 나라장터 종합쇼핑몰 API: `조달청_OpenAPI참고자료_나라장터_종합쇼핑몰품목정보서비스_1.0.pdf` (프로젝트 루트)
- 단가 미등록 목록: `magnatech_missing_prices.xlsx` (프로젝트 루트)
- 기존 모델: `modules/models/entities.py` (ContractItem, Material, Contract)

---

## 2. Scope

### 2.1 In Scope

- [ ] `ProductCatalog` SQLAlchemy 모델 생성 (물품식별번호, 품명, 분류, 단가, 단가출처, 계약방식, 갱신일시)
- [ ] 나라장터 종합쇼핑몰 API 연동 서비스 (`modules/services/g2b_catalog_sync.py`)
  - [ ] 다수공급자(MAS) 계약 품목 조회 (`getMASCntrctPrdctInfoList`)
  - [ ] 제3자단가 계약 품목 조회 (`getThptyUcntrctPrdctInfoList`)
  - [ ] 중복 제거 및 DB Upsert 로직
- [ ] 제품 카탈로그 관리 페이지 (`/product_catalog`)
  - [ ] 목록 조회 (검색, 필터링, 페이지네이션)
  - [ ] API 동기화 버튼 (관리자 전용)
  - [ ] 수기 단가 입력/수정 (관리자 전용)
- [ ] ContractItem 연동: `model_name` 기반 ProductCatalog 매칭 -> 단가 자동 참조
- [ ] 영업관리(sales) 상세 페이지에 품목별 단가/금액 컬럼 추가
- [ ] 주간보고서(`report_weekly.html`)에 품목별 예상금액 표시

### 2.2 Out of Scope

- 물품목록 API(389건) 연동 (단가 없음, 카탈로그 마스터로는 불필요)
- 자동 견적서 PDF 생성 (후속 기능으로 분리)
- 단가 변동 알림 (Notification 연동은 후속 기능)
- 타사 제품 단가 관리 (매그나텍 자사 제품만 대상)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | ProductCatalog 모델 생성: prdctIdntNo(PK), krnPrdctNm, category, unit_price, price_source(api/manual), g2b_contract_method(MAS/제3자단가), updated_at | High | Pending |
| FR-02 | 나라장터 API 동기화: 다수공급자 + 제3자단가 API 호출 -> ProductCatalog DB Upsert | High | Pending |
| FR-03 | 카탈로그 목록 페이지: 전체 제품 목록, 검색(품명/식별번호), 필터(단가출처, 계약방식), 페이지네이션 | High | Pending |
| FR-04 | 수기 단가 입력: unit_price 직접 수정, price_source='manual'로 자동 표시 | High | Pending |
| FR-05 | ContractItem 단가 매칭: ContractItem.model_name <-> ProductCatalog.krnPrdctNm 매칭 후 단가 조회 | High | Pending |
| FR-06 | 영업관리 금액 표시: sales_detail 페이지에 품목별 단가, 수량 x 단가 = 금액 컬럼 추가 | Medium | Pending |
| FR-07 | 주간보고서 금액 표시: 계약 전환 프로젝트에 예상 총금액 컬럼 추가 | Medium | Pending |
| FR-08 | API 동기화 이력 로그: 동기화 실행 시각, 갱신 건수, 오류 건수 기록 | Low | Pending |
| FR-09 | 단가 미등록 품목 강조: unit_price가 NULL인 품목을 시각적으로 구분 (노란 배경 등) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | API 동기화 30초 이내 완료 (241건 기준) | 동기화 실행 후 소요시간 측정 |
| Security | API 키(.env 관리), CSRF 보호 유지, 관리자 전용 동기화 | 코드 리뷰 |
| Reliability | API 장애 시 기존 데이터 유지 (부분 업데이트) | 장애 시나리오 테스트 |
| UX | 동기화 중 로딩 표시, 완료 후 결과 Flash 메시지 | 화면 검증 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] ProductCatalog 모델 생성 및 DB 마이그레이션 완료
- [ ] API 동기화로 241건 정상 적재 확인
- [ ] 수기 입력으로 148건 미등록 단가 입력 가능 확인
- [ ] ContractItem 매칭 로직 동작 확인
- [ ] 영업관리 상세 페이지에 금액 표시 확인
- [ ] 주간보고서에 예상금액 표시 확인

### 4.2 Quality Criteria

- [ ] 기존 페이지(영업관리, 자재관리, 주간보고서) 정상 동작 유지
- [ ] API 키 하드코딩 없음 (.env 관리)
- [ ] 기존 코드 패턴(Blueprint, get_db(), login_required, Flash 메시지) 준수
- [ ] 반응형 테이블 레이아웃 유지 (base.html 패턴 준수)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 나라장터 API 응답 지연/장애 | Medium | Medium | timeout 설정(30초), 기존 데이터 보존, Flash 메시지로 오류 안내 |
| model_name 매칭 불일치 | High | High | 정규화 로직(대소문자, 공백, 특수문자 제거) 적용, 매칭 실패 목록 별도 표시 |
| API 일일 호출 제한 (data.go.kr) | Low | Low | 동기화 버튼을 관리자 전용으로 제한, 마지막 동기화 시각 표시 |
| 기존 ContractItem 스키마 변경 충돌 | Medium | Low | ContractItem은 수정하지 않고, ProductCatalog를 별도 테이블로 분리하여 JOIN 조회 |
| 148건 수기 입력 누락 | Medium | Medium | 미등록 단가 건수를 대시보드에 표시, 필터로 빠르게 접근 가능 |

---

## 6. Architecture Considerations

### 6.1 Project Level

| Level | Characteristics | Selected |
|-------|-----------------|:--------:|
| **Starter** | 단순 구조 | - |
| **Dynamic** | Flask + SQLAlchemy + Jinja2, 기능별 모듈 분리 | **선택** |
| **Enterprise** | MSA, DI, Kubernetes | - |

> Light-Sync ERP는 Flask 단일 서버 + SQLite 기반 Dynamic 레벨 프로젝트이다.

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 단가 저장 위치 | ContractItem에 필드 추가 / 별도 ProductCatalog 테이블 | **별도 ProductCatalog** | 제품 마스터는 계약과 독립적이며 API 동기화 주기가 다름 |
| API 호출 방식 | 동기(requests) / 비동기(aiohttp) | **동기(requests)** | Flask 동기 구조에 맞춤, 241건 수준이라 성능 문제 없음 |
| 매칭 방식 | model_name 문자열 매칭 / FK 연결 | **문자열 매칭** | 기존 ContractItem 스키마 변경 최소화, 점진적 FK 전환 가능 |
| 단가 표시 | 서버사이드 계산 / 클라이언트 JS 계산 | **서버사이드** | Jinja2 템플릿 패턴 유지, SEO/인쇄 호환 |

### 6.3 데이터 모델 설계

```
ProductCatalog (신규 테이블)
├── id: Integer (PK, autoincrement)
├── prdct_idnt_no: String(30) (물품식별번호, unique)
├── krn_prdct_nm: String(300) (한글품명)
├── prdct_clsfc_no: String(30) (물품분류번호)
├── dtl_prdct_nm: String(500) (상세품명)
├── unit: String(20) (단위)
├── unit_price: Integer (계약단가, nullable)
├── price_source: String(10) (api/manual)
├── g2b_contract_method: String(20) (MAS/제3자단가)
├── g2b_cntrct_no: String(50) (계약번호)
├── cntrct_bgn_date: Date (계약시작일)
├── cntrct_end_date: Date (계약종료일)
├── last_synced_at: DateTime (마지막 동기화 시각)
├── created_at: DateTime
└── updated_at: DateTime

연동 관계:
ContractItem.model_name ←→ ProductCatalog.krn_prdct_nm (문자열 매칭)
→ unit_price 참조하여 금액 계산: quantity * unit_price
```

### 6.4 파일 구조 (신규/수정 파일)

```
modules/
├── models/
│   ├── entities.py          (수정) ProductCatalog 모델 추가
│   └── __init__.py          (수정) ProductCatalog export 추가
├── services/
│   └── g2b_catalog_sync.py  (신규) 나라장터 API 동기화 서비스
routes/
│   └── catalog.py           (신규) 제품 카탈로그 Blueprint
templates/
│   ├── catalog_list.html    (신규) 카탈로그 목록 페이지
│   └── sales_detail.html    (수정) 단가/금액 컬럼 추가
│   └── report_weekly.html   (수정) 예상금액 표시 추가
app.py                       (수정) catalog_bp 등록
```

---

## 7. Convention Prerequisites

### 7.1 기존 프로젝트 컨벤션 확인

- [x] `CLAUDE.md` 코딩 컨벤션 섹션 존재
- [x] Blueprint 패턴: `routes/{feature}.py` + `{feature}_bp`
- [x] DB 접근: `with get_db() as db:` 컨텍스트 매니저
- [x] 인증: `@login_required` 데코레이터
- [x] 페이지네이션: `make_pagination()` + `pagination_query` Jinja2 global
- [x] 알림: `flash()` 메시지
- [x] 히스토리: `append_history_log()` 이력 기록
- [x] 서비스 패턴: `modules/services/{feature}_actions.py` (액션 핸들러 분리)

### 7.2 준수할 컨벤션

| Category | Rule | Example |
|----------|------|---------|
| Blueprint 네이밍 | `{feature}_bp` | `catalog_bp` |
| Route prefix | `/{feature}_명` | `/product_catalog` |
| Template 경로 | `templates/{feature}_{page}.html` | `catalog_list.html` |
| Action handler | `ACTION_HANDLERS` dict + 개별 함수 | `handle_sync_catalog()` |
| 모델 필드 | snake_case, nullable 명시 | `unit_price = Column(Integer, nullable=True)` |

### 7.3 Environment Variables

| Variable | Purpose | Scope | Status |
|----------|---------|-------|:------:|
| `DATA_GO_KR_API_KEY` | 공공데이터포털 API Decoding 키 | Server | 기존 .env에 설정 완료 |
| `COMPANY_BIZ_NO` | 매그나텍 사업자번호 (4088168519) | Server | 기존 .env에 설정 완료 |

---

## 8. Implementation Strategy

### 8.1 구현 순서 (권장)

| Step | Task | 예상 소요 | 의존성 |
|------|------|-----------|--------|
| 1 | ProductCatalog 모델 + DB 마이그레이션 | 30분 | 없음 |
| 2 | g2b_catalog_sync.py API 동기화 서비스 | 1시간 | Step 1 |
| 3 | catalog.py Route + catalog_list.html 템플릿 | 1시간 | Step 1, 2 |
| 4 | 수기 단가 입력 기능 | 30분 | Step 3 |
| 5 | ContractItem 매칭 유틸리티 함수 | 30분 | Step 1 |
| 6 | sales_detail.html 금액 컬럼 추가 | 30분 | Step 5 |
| 7 | report_weekly.html 예상금액 추가 | 30분 | Step 5 |
| 8 | app.py Blueprint 등록 + 통합 테스트 | 30분 | All |

### 8.2 API 호출 설계

```
동기화 흐름:
1. [관리자] "API 동기화" 버튼 클릭
2. [Server] getMASCntrctPrdctInfoList(cntrctCorpNm=매그나텍) → 226건
3. [Server] getThptyUcntrctPrdctInfoList(cntrctCorpNm=매그나텍) → 41건
4. [Server] prdctIdntNo 기준 중복 제거 → 241건
5. [Server] DB Upsert (기존 price_source='manual' 단가는 보존)
6. [Server] Flash 메시지: "동기화 완료: 갱신 N건, 신규 N건"
```

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`product-catalog.design.md`) - 상세 UI 와이어프레임, API 응답 매핑
2. [ ] 팀 리뷰 및 승인
3. [ ] 구현 시작 (Step 1부터 순차 진행)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft | CTO Lead (PDCA Team) |
