# icube-procurement Phase 2 Design Document

> **Summary**: iCUBE -> PostgreSQL 마이그레이션 + 발주서 CRUD + PDF 생성 + 이메일 발송
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: Claude (CTO Lead)
> **Date**: 2026-03-18
> **Status**: Approved
> **Planning Doc**: [icube-procurement.plan.md](../../01-plan/features/icube-procurement.plan.md)
> **Phase 1 Design**: [icube-procurement.design.md](icube-procurement.design.md)

---

## 1. Overview

### 1.1 Design Goals

- iCUBE SQL Server 데이터를 PostgreSQL(Light-Sync 자체 DB)로 1회 마이그레이션
- 마이그레이션 후 vendor.py를 자체 DB 조회로 전환 (iCUBE 실시간 연동 제거)
- 발주서 작성/수정/삭제 CRUD + 자동 발주번호 채번
- 발주서 PDF 생성 (reportlab, 한글 지원)
- SMTP 이메일 발송 (거래처 EMAIL로 PDF 첨부)
- 이메일 발송 이력 관리

### 1.2 Design Principles

- **자체 DB 완결**: iCUBE DB 의존성 제거, PostgreSQL에서 모든 데이터 관리
- **멱등 마이그레이션**: 스크립트 여러 번 실행해도 안전 (중복 체크)
- **기존 패턴 준수**: Flask Blueprint + Jinja2 + get_db 컨텍스트 매니저
- **DRY_RUN 지원**: 이메일 발송 테스트 모드 (.env SMTP_DRY_RUN=true)

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Browser    │────>│ routes/vendor.py  │────>│ PostgreSQL       │
│  (Jinja2)   │     │ routes/po.py     │     │ (Light-Sync DB)  │
└─────────────┘     └──────────────────┘     └──────────────────┘
                           │                         ^
                           │                         │ migrate
                    ┌──────v──────────┐     ┌────────┴─────────┐
                    │ services/       │     │ scripts/          │
                    │  po_pdf.py      │     │  migrate_icube.py │
                    │  email_sender.py│     │  (pyodbc -> PG)   │
                    └─────────────────┘     └──────────────────┘
                                                     ^
                                                     │ READ ONLY
                                            ┌────────┴─────────┐
                                            │ iCUBE SQL Server  │
                                            │ (DZICUBE)         │
                                            └──────────────────┘
```

### 2.2 Data Flow

```
마이그레이션: iCUBE -> pyodbc -> migrate_icube.py -> SQLAlchemy -> PostgreSQL
발주서 작성: Browser -> purchase_order.py -> PostgreSQL
PDF 생성: purchase_order.py -> po_pdf.py -> ReportLab -> PDF bytes
이메일 발송: purchase_order.py -> email_sender.py -> SMTP -> 거래처
```

---

## 3. Data Model

### 3.1 신규 테이블 (PostgreSQL)

| Model | Table | 용도 |
|-------|-------|------|
| Vendor | vendors | 거래처 마스터 (iCUBE STRADE 마이그레이션) |
| Item | items | 품목 마스터 (iCUBE SITEM 마이그레이션) |
| PurchaseOrder | purchase_orders | 발주서 (신규 작성) |
| PurchaseOrderItem | purchase_order_items | 발주 품목 상세 |
| PurchaseOrderHistory | purchase_order_history | iCUBE 발주이력 (마이그레이션) |
| ReceivingHistory | receiving_history | iCUBE 입고이력 (마이그레이션) |
| EmailHistory | email_history | 이메일 발송이력 |

### 3.2 발주서 상태 흐름

```
작성중 -> 발송완료 -> 입고대기 -> 입고완료
  |
  +-> 취소
```

### 3.3 발주번호 채번 규칙

PO{YYYY}-{NNN} (예: PO2026-001, PO2026-002, ...)
- 연도별 자동 채번
- SELECT MAX(po_no) WHERE po_no LIKE 'PO2026-%' 기반

---

## 4. File Structure

| # | File | Type | Description |
|---|------|------|-------------|
| 1 | modules/models/entities.py | MODIFY | 7개 모델 추가 |
| 2 | modules/models/__init__.py | MODIFY | 새 모델 export |
| 3 | scripts/migrate_icube.py | NEW | iCUBE -> PostgreSQL 마이그레이션 |
| 4 | routes/vendor.py | MODIFY | 자체 DB 조회로 전환 |
| 5 | routes/purchase_order.py | NEW | 발주서 CRUD + PDF + 이메일 |
| 6 | templates/po_list.html | NEW | 발주서 목록 |
| 7 | templates/po_create.html | NEW | 발주서 작성 |
| 8 | templates/po_detail.html | NEW | 발주서 상세 |
| 9 | modules/services/email_sender.py | NEW | SMTP 이메일 발송 |
| 10 | modules/services/po_pdf.py | NEW | 발주서 PDF 생성 |
| 11 | app.py | MODIFY | purchase_order_bp 등록 |
| 12 | templates/base.html | MODIFY | 사이드바 메뉴 추가 |
| 13 | .env | MODIFY | SMTP 환경변수 추가 |

---

## 5. Implementation Order

1. entities.py - 모델 추가
2. __init__.py - export
3. .env - SMTP 환경변수
4. migrate_icube.py - 마이그레이션 스크립트
5. vendor.py - 자체 DB 전환
6. po_pdf.py - PDF 생성
7. email_sender.py - 이메일 발송
8. purchase_order.py - 발주서 CRUD
9. po_list.html, po_create.html, po_detail.html - 템플릿
10. app.py - Blueprint 등록
11. base.html - 사이드바 메뉴

---

## 6. Security

- iCUBE DB 읽기만 (마이그레이션 스크립트에서만 접근)
- SMTP 비밀번호 환경변수 관리
- SMTP_DRY_RUN=true 시 실제 발송 차단
- login_required 데코레이터 모든 라우트 적용
- CSRF 보호 (Flask-WTF)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-18 | Phase 2 Design 완료 | Claude (CTO Lead) |
