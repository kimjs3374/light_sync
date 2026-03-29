# icube-procurement Planning Document

> **Summary**: iCUBE ERP DB 연동 기반 거래처 관리, 발주서 작성/이메일 발송, 입고/거래명세서 관리, BOM 자재관리
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
| **Problem** | 기존 iCUBE ERP(더존)에 축적된 거래처 7,030건, 발주 367건, 입고 13,480건의 거래 데이터가 있으나 Light-Sync ERP에서 활용 불가. 발주서를 수동으로 작성해 거래처에 별도 전달하고 있어 업무 효율이 낮음. |
| **Solution** | iCUBE SQL Server DB를 읽기 전용으로 연동하여 거래처/발주/입고 이력을 Light-Sync ERP에서 조회하고, 자체 발주서 작성 → PDF 생성 → IMAP 이메일 자동 발송 기능 구현. 최종적으로 BOM 리스트 연동으로 프로젝트별 자재 소요 자동 계산. |
| **기능/UX 효과** | 거래처 과거 거래 이력 즉시 조회, 발주서 작성 5분 → 1분 단축, 이메일 원클릭 발송, 입고 대비 발주 매칭 자동화, BOM 기반 자재 소요량 자동 산출. |
| **핵심 가치** | 기존 10년간 축적된 거래 데이터를 활용하여 구매 의사결정 속도 향상. 발주→입고→거래명세 프로세스 디지털화로 경영관리부 업무 부담 경감. |

---

## 1. Overview

### 1.1 Purpose

iCUBE ERP(DZICUBE DB)에 축적된 거래 데이터를 Light-Sync ERP에서 조회·활용하고, 자체적으로 발주서 작성 → 이메일 발송 → 입고 확인 → 거래명세서 관리까지의 구매 프로세스를 구현한다.

### 1.2 Background

- DZICUBE SQL Server DB: 3,364 테이블, 323만건 (localhost\SQLEXPRESS)
- 거래처(STRADE): 7,030건 (업체명, 대표자, 사업자번호, 이메일, 전화, 팩스)
- 발주(LPURCLS/LPURCLS_D): 367건 헤더 + 5,773건 상세
- 입고(LSTOCK/LSTOCK_D): 3,236건 헤더 + 13,480건 상세
- 재고수불(LX_LINVTORY): 22,573건
- 최근 발주: 2025-01-14 (주)케이씨씨나라 실리콘 자재
- 최근 입고: 2026-03-11 (주)셀파세미컴 LED드라이버

### 1.3 iCUBE 핵심 테이블 매핑

| iCUBE 테이블 | 건수 | Light-Sync 용도 |
|-------------|------|----------------|
| STRADE | 7,030 | 거래처 마스터 (TR_CD, TR_NM, EMAIL, TEL, FAX) |
| LPURCLS | 367 | 발주 헤더 (CLS_NB, CLS_DT, TR_CD) |
| LPURCLS_D | 5,773 | 발주 상세 (ITEM_CD, CLS_QT, CLS_UM, CLSH_AM) |
| LSTOCK | 3,236 | 입고 헤더 (RCV_NB, RCV_DT, TR_CD) |
| LSTOCK_D | 13,480 | 입고 상세 (ITEM_CD, RCV_QT, RCV_UM, RCVH_AM) |
| ADOCUH | 9,833 | 전표/거래명세 헤더 |
| ADOCUD | 19,199 | 전표/거래명세 상세 |
| LX_LINVTORY | 22,573 | 재고 수불 내역 |

---

## 2. Scope

### 2.1 In Scope (4단계 구현)

**Phase 1 - 거래처 + 거래이력 조회 (읽기 전용)**
- [ ] FR-01: iCUBE DB 연결 모듈 (pyodbc, 읽기 전용)
- [ ] FR-02: 거래처 목록/검색/상세 조회 페이지
- [ ] FR-03: 거래처별 발주/입고 이력 조회
- [ ] FR-04: 품목별 거래 이력 (언제 어디서 얼마에)

**Phase 2 - 발주서 작성 + 이메일 발송**
- [ ] FR-05: Light-Sync 자체 발주서 작성 (거래처/품목 선택 → 수량/단가 입력)
- [ ] FR-06: 발주서 PDF 생성 (회사 양식)
- [ ] FR-07: IMAP 이메일 발송 (거래처 EMAIL로 PDF 첨부 발송)
- [ ] FR-08: 발주 상태 관리 (작성중→발송완료→입고대기→입고완료)

**Phase 3 - 입고/거래명세서 관리**
- [ ] FR-09: 입고 등록 (발주 대비 입고 매칭)
- [ ] FR-10: 거래명세서 조회/관리
- [ ] FR-11: 발주 vs 입고 대사 (미입고/과입고 알림)

**Phase 4 - BOM + 자재관리 통합**
- [ ] FR-12: BOM 리스트 관리 (제품별 소요 부품)
- [ ] FR-13: 프로젝트별 소요 자재 자동 계산 (BOM × 수량)
- [ ] FR-14: 재고 현황 연동 (iCUBE LX_LINVTORY)

### 2.2 Out of Scope

- iCUBE DB 쓰기 (Light-Sync은 읽기 전용, 자체 DB에 발주/입고 기록)
- iCUBE 회계 데이터 연동 (SACCT, ADSUM 등)
- iCUBE 인사/급여 데이터

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Phase | Priority |
|----|-------------|-------|----------|
| FR-01 | iCUBE SQL Server 읽기 전용 연결 모듈 (pyodbc) | 1 | P0 |
| FR-02 | 거래처 목록 (검색/필터/페이지네이션) + 상세 | 1 | P0 |
| FR-03 | 거래처별 발주/입고 이력 타임라인 | 1 | P0 |
| FR-04 | 품목별 거래 이력 + 단가 추이 | 1 | P1 |
| FR-05 | 발주서 작성 폼 (거래처/품목 선택, 수량/단가) | 2 | P0 |
| FR-06 | 발주서 PDF 생성 (회사 양식) | 2 | P0 |
| FR-07 | IMAP 이메일 발송 (PDF 첨부) | 2 | P0 |
| FR-08 | 발주 상태 추적 (작성중→발송→입고대기→완료) | 2 | P0 |
| FR-09 | 입고 등록 + 발주 매칭 | 3 | P0 |
| FR-10 | 거래명세서 조회/관리 | 3 | P1 |
| FR-11 | 발주 vs 입고 대사 (미입고/과입고 알림) | 3 | P1 |
| FR-12 | BOM 리스트 CRUD | 4 | P1 |
| FR-13 | 프로젝트별 소요 자재 자동 계산 | 4 | P2 |
| FR-14 | 재고 현황 연동 | 4 | P2 |

### 3.2 Non-Functional Requirements

| Category | Criteria |
|----------|----------|
| Performance | iCUBE 쿼리 응답 < 500ms (인덱스 활용) |
| Security | iCUBE DB 읽기 전용 계정 사용, SQL injection 방지 (ORM/파라미터 바인딩) |
| Email | IMAP/SMTP TLS 암호화, 발송 이력 로깅 |
| Data | iCUBE 원본 데이터 수정 불가, Light-Sync 자체 DB에 발주/입고 저장 |

---

## 4. Data Model (Light-Sync 자체 DB)

### 4.1 신규 테이블

```
Vendor (거래처 캐시/확장)
├── id (PK)
├── icube_tr_cd          # iCUBE 거래처코드 (연결 키)
├── name                 # 거래처명
├── ceo_name             # 대표자
├── business_no          # 사업자번호
├── email                # 이메일 (발주서 발송용)
├── tel, fax
├── address
├── note                 # 메모
└── created_at, updated_at

PurchaseOrder (발주서)
├── id (PK)
├── po_no                # 발주번호 (PO2026-001)
├── po_date              # 발주일
├── vendor_id (FK)       # 거래처
├── project_id (FK)      # 연결 프로젝트 (nullable)
├── status               # 작성중/발송완료/입고대기/입고완료/취소
├── total_amount         # 합계 금액
├── email_sent_at        # 이메일 발송 시각
├── email_to             # 발송 이메일 주소
├── note
├── created_by (FK)
└── created_at, updated_at

PurchaseOrderItem (발주 품목)
├── id (PK)
├── po_id (FK)
├── item_code            # 품목코드 (iCUBE ITEM_CD)
├── item_name            # 품명
├── spec                 # 규격
├── quantity             # 수량
├── unit_price           # 단가
├── amount               # 금액
├── delivery_date        # 납기일
└── note

Receiving (입고)
├── id (PK)
├── rcv_no               # 입고번호
├── rcv_date             # 입고일
├── po_id (FK)           # 연결 발주서
├── vendor_id (FK)
├── status               # 검수대기/검수완료/반품
├── note
└── created_at

ReceivingItem (입고 품목)
├── id (PK)
├── receiving_id (FK)
├── po_item_id (FK)      # 연결 발주 품목
├── item_code
├── received_qty         # 입고 수량
├── inspected_qty        # 검수 수량
├── rejected_qty         # 불량 수량
└── note
```

### 4.2 BOM (Phase 4)

```
BomHeader (BOM 마스터)
├── id (PK)
├── product_code         # 완제품 코드
├── product_name         # 완제품명
├── version              # BOM 버전
└── is_active

BomItem (BOM 품목)
├── id (PK)
├── bom_id (FK)
├── item_code            # 부품 코드
├── item_name            # 부품명
├── quantity             # 소요량 (1개 완제품 기준)
├── unit
└── note
```

---

## 5. Implementation Plan

### 5.1 Phase 1 파일 목록 (거래처 + 거래이력 조회)

| # | 파일 | 작업 | 설명 |
|---|------|------|------|
| 1 | `modules/icube_db.py` | 신규 | iCUBE SQL Server 연결 모듈 (pyodbc, 읽기 전용) |
| 2 | `routes/vendor.py` | 신규 | 거래처 조회 Blueprint |
| 3 | `templates/vendor_list.html` | 신규 | 거래처 목록 |
| 4 | `templates/vendor_detail.html` | 신규 | 거래처 상세 + 거래이력 |
| 5 | `app.py` | 수정 | vendor_bp 등록 |
| 6 | `templates/base.html` | 수정 | 사이드바 "구매관리" 메뉴 그룹 추가 |
| 7 | `.env` | 수정 | ICUBE_DB_SERVER, ICUBE_DB_NAME 환경변수 |

### 5.2 Phase 2 파일 목록 (발주서 + 이메일)

| # | 파일 | 작업 | 설명 |
|---|------|------|------|
| 8 | `modules/models/entities.py` | 수정 | Vendor, PurchaseOrder, PurchaseOrderItem 모델 |
| 9 | `routes/purchase_order.py` | 신규 | 발주서 CRUD + PDF 생성 |
| 10 | `templates/po_list.html` | 신규 | 발주서 목록 |
| 11 | `templates/po_create.html` | 신규 | 발주서 작성 |
| 12 | `templates/po_detail.html` | 신규 | 발주서 상세 + PDF 미리보기 |
| 13 | `modules/services/email_sender.py` | 신규 | IMAP/SMTP 이메일 발송 |
| 14 | `modules/services/po_pdf.py` | 신규 | 발주서 PDF 생성 (ReportLab) |

### 5.3 Phase 3 파일 목록 (입고/거래명세)

| # | 파일 | 작업 | 설명 |
|---|------|------|------|
| 15 | `modules/models/entities.py` | 수정 | Receiving, ReceivingItem 모델 |
| 16 | `routes/receiving.py` | 신규 | 입고 관리 Blueprint |
| 17 | `templates/receiving_*.html` | 신규 | 입고 목록/등록/상세 |

### 5.4 Phase 4 파일 목록 (BOM)

| # | 파일 | 작업 | 설명 |
|---|------|------|------|
| 18 | `modules/models/entities.py` | 수정 | BomHeader, BomItem 모델 |
| 19 | `routes/bom.py` | 신규 | BOM 관리 Blueprint |
| 20 | `templates/bom_*.html` | 신규 | BOM 목록/편집 |

---

## 6. Architecture

### 6.1 데이터 흐름

```
┌──────────────┐     읽기 전용      ┌──────────────────────────┐
│ iCUBE DB     │ ◄─────────────── │ modules/icube_db.py      │
│ (SQL Server) │                   │ (pyodbc 연결 풀)          │
│              │                   └──────────┬───────────────┘
│ STRADE       │                              │
│ LPURCLS/D    │                              ▼
│ LSTOCK/D     │                   ┌──────────────────────────┐
│ LX_LINVTORY  │                   │ Light-Sync ERP           │
└──────────────┘                   │                          │
                                   │ routes/vendor.py     조회 │
                                   │ routes/purchase_order 발주 │
                                   │ routes/receiving.py  입고 │
                                   │                          │
                                   │ ┌──────────────────────┐ │
                                   │ │ Light-Sync DB (SQLite)│ │
                                   │ │ Vendor (캐시)         │ │
                                   │ │ PurchaseOrder         │ │
                                   │ │ Receiving             │ │
                                   │ │ BOM                   │ │
                                   │ └──────────────────────┘ │
                                   │                          │
                                   │ ┌──────────────────────┐ │
                                   │ │ Email (IMAP/SMTP)    │ │
                                   │ │ → 거래처 EMAIL로     │ │
                                   │ │   발주서 PDF 발송    │ │
                                   │ └──────────────────────┘ │
                                   └──────────────────────────┘
```

### 6.2 환경변수

| Variable | Purpose | 예시 |
|----------|---------|------|
| `ICUBE_DB_SERVER` | iCUBE SQL Server 주소 | `localhost\SQLEXPRESS` |
| `ICUBE_DB_NAME` | iCUBE 데이터베이스명 | `DZICUBE` |
| `SMTP_HOST` | SMTP 서버 | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP 포트 | `587` |
| `SMTP_USER` | 발송 이메일 | `purchase@magnatech.co.kr` |
| `SMTP_PASS` | 이메일 비밀번호 | `(app password)` |
| `IMAP_HOST` | IMAP 서버 (발송 보관용) | `imap.gmail.com` |

---

## 7. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| iCUBE DB 동시 접속 부하 | Medium | 읽기 전용 + 연결 풀 최소화 (max 2), 캐시 활용 |
| SQL Server Express 메모리 제한 | Low | 쿼리 최적화, 필요 시 뷰 생성 |
| 이메일 발송 실패 (SMTP 차단) | High | 발송 실패 시 재시도 큐, 발송 이력 로깅, fallback 안내 |
| iCUBE 품목코드 체계 불일치 | Medium | 거래처 캐시(Vendor)에 매핑 정보 저장, 점진적 매칭 |
| BOM 데이터 부재 | Low | Phase 4에서 수동 입력으로 시작, 추후 iCUBE BOM 테이블 연동 |

---

## 8. Success Criteria

### Phase 1
- [ ] iCUBE DB 연결 정상 (응답 < 500ms)
- [ ] 거래처 7,030건 목록 조회 + 검색 동작
- [ ] 거래처 상세에서 발주/입고 이력 타임라인 표시

### Phase 2
- [ ] 발주서 작성 → PDF 생성 → 이메일 발송 완료
- [ ] 발주 상태 추적 (4단계) 정상 동작
- [ ] 이메일 발송 이력 로깅

### Phase 3
- [ ] 입고 등록 시 발주서 자동 매칭
- [ ] 미입고/과입고 알림 표시

### Phase 4
- [ ] BOM 등록/수정/삭제 정상
- [ ] 프로젝트별 소요 자재 자동 계산

---

## 9. Next Steps

1. [ ] `/pdca design icube-procurement` - Phase 1 상세 설계
2. [ ] Phase 1 구현 (거래처 + 거래이력 조회)
3. [ ] Phase 2 구현 (발주서 + 이메일)
4. [ ] Phase 3 구현 (입고/거래명세)
5. [ ] Phase 4 구현 (BOM)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft - 4 Phase 구조, iCUBE DB 분석 완료 | Claude (PDCA) |
