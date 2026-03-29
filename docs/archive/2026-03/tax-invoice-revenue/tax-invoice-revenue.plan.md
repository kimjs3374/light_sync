# 매출 세금계산서 임포트 + 수금관리 + 매출 대시보드 Planning Document

> **Summary**: 국세청 매출세금계산서 엑셀 임포트 → G2B 계약/납품 자동 매칭 → 수금(입금) 관리 → 매출·수금율 대시보드(그래프)
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-19
> **Status**: Approved

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 납품 후 세금계산서 발행 여부, 입금 현황을 수기 추적 → 미수금 누락·보고 지연 |
| **Solution** | 국세청 엑셀 임포트 + G2B번호 자동 매칭 + 수금 기록 + 매출·수금율 대시보드(그래프) |
| **Function/UX Effect** | 엑셀 업로드 한 번으로 세금계산서↔계약 자동 매칭, 경영진용 매출·수금 그래프 대시보드 |
| **Core Value** | 매출채권 실시간 가시화, 미수금 누락 방지, 경영진 보고용 시각화 즉시 제공 |

---

## 1. Overview

### 1.1 Purpose
1. 국세청 매출전자세금계산서 엑셀 → ERP 자동 임포트
2. 비고란의 G2B 계약번호(R##TB) / 납품요구번호(R##JG) 파싱 → 기존 계약 자동 매칭
3. 세금계산서별 수금(입금) 상태 관리
4. 계약 대비 납품율 / 세금계산서 발행율 / 수금율 대시보드 + 그래프

### 1.2 Background
- 국세청 홈택스에서 매출전자세금계산서 목록 다운로드 (.xls)
- 비고란에 `계약명|R##TB########|\n R##JG########|...|NATTAX\n R##TB...00|R##NS########|...` 형태로 G2B 번호 포함
- 현재 Contract에 `payment_status`(미청구/청구완료/입금완료), `invoice_date`, `payment_date` 필드 존재
- 하지만 실제 세금계산서 데이터(금액, 승인번호 등)는 미관리
- 비G2B 거래(직발주)는 비고란에 계좌번호 등 기재 → 수동 매칭 필요

### 1.3 Scope
**In-scope:**
- 세금계산서 테이블 (TaxInvoice) 신규 생성
- 수금 기록 테이블 (PaymentRecord) 신규 생성
- 국세청 엑셀 임포트 + 파싱 + G2B 자동 매칭
- 세금계산서 목록/상세 화면 (CRUD)
- 수금 등록/확인 화면
- 매출·수금 대시보드 (월별 매출추이, 수금율, 미수금 현황 그래프)
- 계약 상세에서 세금계산서/수금 현황 연동 표시

**Out-of-scope:**
- 세금계산서 자동 발행 (홈택스 API 연동)
- 매입세금계산서 관리
- 회계 전표 연동

---

## 2. Data Model

### 2.1 TaxInvoice (세금계산서)
| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | |
| approval_no | String(50) UNIQUE | 국세청 승인번호 (20260318-42000105-g9051795) |
| issue_date | Date | 작성일자 |
| send_date | Date | 전송일자 |
| invoice_type | String(20) | 세금계산서/수정세금계산서 |
| supplier_business_no | String(20) | 공급자 사업자번호 (자사) |
| buyer_business_no | String(20) | 공급받는자 사업자번호 |
| buyer_name | String(200) | 공급받는자 상호 |
| buyer_ceo | String(100) | 공급받는자 대표자명 |
| total_amount | Integer | 합계금액 (공급가액+세액) |
| supply_amount | Integer | 공급가액 |
| tax_amount | Integer | 세액 |
| item_date | Date | 품목 작성일 |
| item_name | String(200) | 품목명 |
| item_spec | String(200) | 품목규격 |
| item_qty | Integer | 품목수량 |
| item_unit_price | Integer | 품목단가 |
| remark | Text | 비고 원문 |
| g2b_contract_no | String(30) | 파싱된 G2B 계약번호 (R##TB) |
| g2b_delivery_req_no | String(30) | 파싱된 G2B 납품요구번호 (R##JG) |
| g2b_delivery_no | String(30) | 파싱된 G2B 납품서번호 (R##NS) |
| contract_id | Integer FK | 매칭된 계약 ID (nullable) |
| project_id | Integer FK | 매칭된 프로젝트 ID (nullable) |
| match_status | String(20) | 자동매칭/수동매칭/미매칭 |
| payment_status | String(20) | 미수금/부분입금/입금완료 (기본: 미수금) |
| paid_amount | Integer DEFAULT 0 | 입금 누계액 |
| created_at | DateTime | |
| updated_at | DateTime | |

### 2.2 PaymentRecord (수금 기록)
| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | |
| tax_invoice_id | Integer FK | 세금계산서 ID |
| payment_date | Date | 입금일 |
| amount | Integer | 입금액 |
| payment_method | String(30) | 계좌이체/카드/어음/기타 |
| note | Text | 비고 |
| created_by | String(50) | 등록자 |
| created_at | DateTime | |

---

## 3. Feature Breakdown

### 3.1 엑셀 임포트 + 자동 매칭
- `/financial/tax-invoice/import` POST: 엑셀 파일 업로드
- xlrd로 .xls 파싱 (국세청 포맷: 헤더 row 5, 데이터 row 6~)
- 비고 컬럼에서 정규식으로 G2B 번호 추출:
  - `R\d{2}TB\d{8,}` → g2b_contract_no
  - `R\d{2}JG\d{8,}` → g2b_delivery_req_no
  - `R\d{2}NS\d{8,}` → g2b_delivery_no
- approval_no 기준 중복 체크 (이미 임포트된 건 skip)
- g2b_contract_no로 contracts 테이블 매칭 → contract_id, project_id 자동 연결
- 매칭 결과 요약 반환 (N건 임포트, M건 자동매칭, K건 미매칭)

### 3.2 세금계산서 목록/상세
- `/financial/tax-invoices` GET: 목록 (기간 필터, 매칭상태 필터, 수금상태 필터)
- 목록 컬럼: 작성일 | 거래처 | 공급가액 | 세액 | 합계 | 매칭계약 | 수금상태
- 미매칭 건은 수동 매칭 버튼 (계약 검색 모달)
- 수정세금계산서(음수 금액)는 별도 표시

### 3.3 수금 관리
- 세금계산서 상세에서 수금 기록 추가/삭제
- 수금 등록 시 자동으로 paid_amount 누계, payment_status 갱신
- paid_amount >= total_amount → '입금완료'
- 0 < paid_amount < total_amount → '부분입금'
- paid_amount == 0 → '미수금'

### 3.4 매출·수금 대시보드 (경영진용)
- `/financial/dashboard` GET
- **Chart 1: 월별 매출 추이** (Bar Chart) - 최근 12개월 공급가액 합계
- **Chart 2: 수금율 추이** (Line Chart) - 월별 (입금완료액/매출액) × 100
- **Chart 3: 미수금 현황** (Doughnut) - 미수금/부분입금/입금완료 비율
- **Chart 4: 계약 대비 실적** (Stacked Bar) - 계약금액 vs 세금계산서 발행액 vs 수금액
- **KPI 카드**: 당월 매출 | 당월 수금 | 미수금 잔액 | 수금율(%)
- 기간 필터 (연도/분기 선택)

### 3.5 계약 상세 연동
- 계약 상세 화면에 세금계산서 발행 내역 섹션 추가
- 해당 계약에 매칭된 세금계산서 목록 + 수금 현황 요약
- 계약금액 대비 세금계산서 발행율, 수금율 프로그레스 바

---

## 4. UI/UX Design

### 4.1 메뉴 구조
```
💰 매출·수금관리
  ├── 📊 매출 대시보드    (그래프 중심, 경영진용)
  ├── 📄 세금계산서 목록  (임포트/관리)
  └── 💵 수금 현황        (미수금 추적)
```

### 4.2 대시보드 레이아웃
```
┌─────────────────────────────────────────────┐
│ KPI: 당월매출 | 당월수금 | 미수금 | 수금율  │
├──────────────────────┬──────────────────────┤
│  월별 매출 추이      │  수금율 추이          │
│  (Bar Chart)         │  (Line Chart)        │
├──────────────────────┼──────────────────────┤
│  미수금 현황         │  계약 대비 실적       │
│  (Doughnut)          │  (Stacked Bar)       │
└──────────────────────┴──────────────────────┘
```

### 4.3 세금계산서 목록 테이블
- 기간 필터 + 매칭/수금 상태 필터
- 엑셀 업로드 버튼 (상단)
- 수금상태 뱃지: 미수금(red) / 부분입금(orange) / 입금완료(green)
- 매칭상태 뱃지: 자동매칭(blue) / 수동매칭(cyan) / 미매칭(gray)

---

## 5. File Structure

### 5.1 New Files
| File | Purpose |
|------|---------|
| `routes/financial.py` | 매출·수금 라우트 |
| `modules/services/tax_invoice_import.py` | 엑셀 파싱 + 매칭 로직 |
| `templates/financial_dashboard.html` | 매출 대시보드 (그래프) |
| `templates/tax_invoice_list.html` | 세금계산서 목록 |
| `templates/tax_invoice_detail.html` | 세금계산서 상세 + 수금 |

### 5.2 Modified Files
| File | Change |
|------|--------|
| `modules/models/entities.py` | TaxInvoice, PaymentRecord 모델 추가 |
| `modules/models/db.py` | 마이그레이션 (ALTER TABLE) |
| `config.py` | 메뉴 등록 |
| `app.py` | Blueprint 등록 |
| `templates/contract_detail.html` | 세금계산서 연동 섹션 추가 |

---

## 6. Implementation Priority

| Phase | Task | Priority |
|-------|------|----------|
| 1 | TaxInvoice + PaymentRecord 모델 생성 | P0 |
| 2 | 엑셀 임포트 + G2B 자동 매칭 서비스 | P0 |
| 3 | 세금계산서 목록/상세 화면 | P0 |
| 4 | 수금 등록/관리 기능 | P0 |
| 5 | 매출·수금 대시보드 (4개 차트) | P0 |
| 6 | 계약 상세 연동 | P1 |

---

## 7. Technical Notes

### 7.1 엑셀 파싱 주의사항
- 국세청 .xls 파일 = CDFV2 Microsoft Excel (xlrd 지원)
- 한글 인코딩: codepage 1200 → `str.encode('latin-1').decode('euc-kr')` 변환 필요할 수 있음
  - 단, 실제 서버(Linux)에서는 정상 디코딩 가능성 높음 → 런타임 테스트 필요
- 헤더 Row 5, 데이터 Row 6~
- 합계행(row 2~4) 및 빈 행 skip 처리
- 수정세금계산서: 금액이 음수 → invoice_type='수정' 으로 구분
- 비G2B 거래: 비고란에 계좌번호(224-075779-01-014) → match_status='미매칭'

### 7.2 G2B 매칭 로직
```
1) 비고에서 R##TB 추출 → contracts.g2b_contract_no 매칭
2) 매칭 안 되면 g2b_delivery_requests.cntrct_dlvr_req_no 매칭 시도
3) 매칭 성공 → contract_id, project_id 자동 설정
4) 비G2B 거래 → buyer_name으로 프로젝트 검색 시도 (optional)
```

### 7.3 기존 payment_status 연동
- 세금계산서 임포트 시 해당 계약의 payment_status = '청구완료', invoice_date 자동 갱신
- 수금 완료 시 payment_status = '입금완료', payment_date 자동 갱신
- 기존 계약 상세의 수동 결제상태 변경과 충돌 방지: 세금계산서 기준이 우선

---

## 8. Estimated Effort

| Component | Complexity |
|-----------|------------|
| 모델 + 마이그레이션 | Low |
| 엑셀 임포트 서비스 | Medium (인코딩 처리) |
| 세금계산서 CRUD | Medium |
| 수금 관리 | Low |
| 대시보드 차트 4개 | Medium-High |
| 계약 상세 연동 | Low |
