# 견적서 관리 (Quotation) Planning Document

> **Summary**: 매그나텍 양식 견적서를 ERP에서 생성/관리하고 PDF로 출력하는 기능
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-19
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 견적서를 엑셀/워드로 수작업 작성하여 번호 체계 관리 불가, 이력 추적 어려움 |
| **Solution** | ERP 내 견적서 CRUD + 샘플 양식 그대로 PDF 자동 생성 |
| **Function/UX Effect** | 품목 DB 검색 또는 수기 입력으로 견적 작성 → 원클릭 PDF 다운로드 |
| **Core Value** | 견적 이력 통합 관리 + 번호 자동채번 + 인쇄 품질 PDF 출력 |

---

## 1. Overview

### 1.1 Purpose

매그나텍 표준 견적서 양식을 ERP 시스템에서 직접 생성·관리하고, PDF로 출력하여 고객에게 발송할 수 있도록 한다.

### 1.2 Background

- 현재 견적서는 엑셀 파일로 수작업 작성
- 견적 번호 체계(MT-YYMMDD-순번)가 수동 관리되어 중복/누락 발생 가능
- 과거 견적 이력 검색이 어려움
- 발주서(po_pdf.py) PDF 생성 패턴이 이미 존재하여 재활용 가능

### 1.3 Related Documents

- Reference: `reference/견적서 샘플.pdf` (매그나텍 표준 양식)
- Reference: `modules/services/po_pdf.py` (발주서 PDF 패턴)

---

## 2. Scope

### 2.1 In Scope

- [x] 견적서 목록 (검색/필터/페이지네이션)
- [x] 견적서 생성 (기본정보 + 품목 동적 추가)
- [x] 견적서 상세 조회
- [x] 견적서 수정/삭제
- [x] 견적서 PDF 출력 (샘플 양식 그대로)
- [x] 견적 번호 자동채번 (MT-YYMMDD-순번)
- [x] 품목 선택: Item DB 검색 + 수기 입력 모두 지원
- [x] 수급자 정보 입력 (거래처 DB 선택 또는 수기 입력)

### 2.2 Out of Scope

- 견적서 → 계약 전환 (추후 별도 기능)
- 이메일 자동 발송
- 견적서 승인 워크플로우
- 견적서 버전 관리 (개정)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 견적서 CRUD (생성/조회/수정/삭제) | High | Pending |
| FR-02 | 견적번호 자동채번: MT-YYMMDD-순번 | High | Pending |
| FR-03 | 품목 동적 추가/삭제 (JS) | High | Pending |
| FR-04 | 품목 선택: Item DB 검색 autocomplete | High | Pending |
| FR-05 | 품목 수기 입력 (DB에 없는 품목) | Medium | Pending |
| FR-06 | 공급가액/부가세/합계 자동 계산 | High | Pending |
| FR-07 | PDF 출력 (매그나텍 양식 그대로) | High | Pending |
| FR-08 | 수급자: 거래처 DB 선택 또는 수기 입력 | Medium | Pending |
| FR-09 | 견적 목록 필터 (기간/수급자/상태) | Medium | Pending |
| FR-10 | 히스토리 로그 기록 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 목록 로딩 < 500ms | 브라우저 DevTools |
| PDF | A4 1페이지 생성 < 2초 | 서버 로그 |
| UX | 기존 발주서 UI 패턴과 일관성 유지 | 육안 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [x] 견적서 CRUD 전체 동작
- [x] PDF 출력이 샘플과 동일한 레이아웃
- [x] 품목 DB 검색 + 수기 입력 모두 가능
- [x] 자동채번 정상 동작
- [x] 사이드바 메뉴 등록 완료

### 4.2 Quality Criteria

- [x] 금액 계산 정확성 (소수점 반올림)
- [x] 한글 PDF 깨짐 없음
- [x] 모바일 반응형 지원

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| ReportLab 한글 폰트 서버 미설치 | High | Low | _find_korean_font() 패턴 재사용 |
| 견적번호 동시 채번 충돌 | Medium | Low | DB unique 제약 + 재시도 로직 |
| 품목 수 많을 때 PDF 페이지 넘침 | Medium | Medium | 페이지 분할 로직 (po_pdf.py 참고) |

---

## 6. Architecture Considerations

### 6.1 기술 스택

| Component | Selected | Rationale |
|-----------|----------|-----------|
| Backend | Flask Blueprint | 기존 패턴 동일 |
| DB | SQLAlchemy + SQLite | 기존 패턴 동일 |
| PDF | ReportLab | po_pdf.py 패턴 재사용 |
| Frontend | Bootstrap 5 + Jinja2 | 기존 패턴 동일 |
| 품목 검색 | AJAX autocomplete | 기존 Item 검색 패턴 재사용 |

### 6.2 파일 구조

```
modules/models/entities.py    ← Quotation, QuotationItem 모델 추가
modules/services/quote_pdf.py ← 견적서 PDF 생성 (신규)
routes/quotation.py           ← 견적서 라우트 (신규)
templates/quotation_list.html ← 목록 (신규)
templates/quotation_create.html ← 생성/수정 (신규)
templates/quotation_detail.html ← 상세 (신규)
config.py                     ← MENU_REGISTRY 추가
app.py                        ← Blueprint 등록
sql_editer.sql                ← ALTER TABLE 마이그레이션
```

### 6.3 DB 모델

```
Quotation (quotations)
├── id (PK)
├── quote_no (String, unique) — MT-YYMMDD-순번
├── quote_date (Date)
├── validity_period (String) — "견적일로부터 1개월"
├── delivery_date (String) — "협의"
├── payment_method (String) — "현금"
├── project_name (String) — 건명
├── customer_name (String) — 수급자명
├── customer_contact (String) — 수급자 담당자
├── customer_address (String)
├── customer_tel (String)
├── customer_fax (String)
├── customer_email (String)
├── note (Text) — 비고
├── total_amount (Float)
├── tax_included (Boolean) — 부가세 포함 여부
├── status (String) — 작성중/발송/만료
├── created_by (Integer, FK→users)
├── created_at (DateTime)
├── updated_at (DateTime)
└── items → QuotationItem[]

QuotationItem (quotation_items)
├── id (PK)
├── quotation_id (FK→quotations)
├── seq (Integer) — 순번
├── item_id (Integer, FK→items, nullable) — DB 품목 연결
├── item_name (String) — 품명
├── item_spec (String) — 규격
├── unit (String) — 단위
├── quantity (Float)
├── unit_price (Float)
├── amount (Float)
└── note (String) — 비고
```

---

## 7. Implementation Order

1. **DB 모델** — Quotation, QuotationItem 엔티티 추가 + 마이그레이션
2. **라우트** — quotation.py CRUD + PDF 다운로드 엔드포인트
3. **PDF 서비스** — quote_pdf.py (샘플 양식 기반)
4. **템플릿** — 목록 → 생성 → 상세 순서
5. **메뉴 등록** — config.py + app.py

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`quotation.design.md`)
2. [ ] 구현 시작
3. [ ] Gap Analysis

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft | ENG |
