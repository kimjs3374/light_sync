# icube-procurement Phase 1 Design Document

> **Summary**: iCUBE DB 읽기 전용 연동 + 거래처/발주/입고 이력 조회 (Phase 1)
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: Claude (CTO Lead)
> **Date**: 2026-03-17
> **Status**: Approved
> **Planning Doc**: [icube-procurement.plan.md](../../01-plan/features/icube-procurement.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- iCUBE SQL Server(DZICUBE) 읽기 전용 연결 모듈 구현 (pyodbc)
- 거래처 7,030건 목록/검색/상세 조회 페이지
- 거래처별 발주/입고 이력 타임라인
- 품목별 거래 이력 + 단가 추이 차트

### 1.2 Design Principles

- **읽기 전용**: iCUBE DB에 대한 모든 접근은 SELECT만 허용
- **기존 패턴 준수**: Flask Blueprint + Jinja2 + Bootstrap 5 + make_pagination
- **연결 풀 최소화**: SQL Server Express 부하 방지 (max 2 connections)
- **파라미터 바인딩**: SQL injection 방지, pyodbc 파라미터 바인딩 사용
- **CO_CD 필터**: 모든 쿼리에 CO_CD='1000' 필터 적용

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Browser    │────>│  routes/vendor.py │────>│ modules/icube_db │
│  (Jinja2)   │     │  (Blueprint)     │     │ (pyodbc pool)    │
└─────────────┘     └──────────────────┘     └────────┬─────────┘
                                                       │ READ ONLY
                                                       v
                                              ┌──────────────────┐
                                              │ SQL Server       │
                                              │ DZICUBE          │
                                              │ STRADE/LPURCLS/  │
                                              │ LSTOCK           │
                                              └──────────────────┘
```

### 2.2 Data Flow

```
User Request → vendor.py route → icube_db.execute_query()
             → pyodbc cursor → SQL Server → dict rows
             → Jinja2 template render → HTML response
```

---

## 3. File Structure

| # | File | Type | Description |
|---|------|------|-------------|
| 1 | `modules/icube_db.py` | NEW | iCUBE SQL Server 연결 모듈 |
| 2 | `routes/vendor.py` | NEW | 거래처 조회 Blueprint |
| 3 | `templates/vendor_list.html` | NEW | 거래처 목록 페이지 |
| 4 | `templates/vendor_detail.html` | NEW | 거래처 상세 + 이력 |
| 5 | `app.py` | MODIFY | vendor_bp 등록 |
| 6 | `templates/base.html` | MODIFY | 사이드바 메뉴 추가 |
| 7 | `.env` | MODIFY | iCUBE 환경변수 추가 |

---

## 4. Module Design

### 4.1 modules/icube_db.py

```python
# 핵심 함수:
def get_icube_connection() -> pyodbc.Connection
    # - 환경변수: ICUBE_DB_SERVER, ICUBE_DB_NAME
    # - DRIVER={ODBC Driver 18 for SQL Server}
    # - Trusted_Connection=yes; TrustServerCertificate=yes
    # - autocommit=True (읽기 전용이므로)

def execute_query(sql, params=None) -> list[dict]
    # - 파라미터 바인딩으로 SQL injection 방지
    # - cursor.description으로 컬럼명 자동 매핑
    # - 결과를 list[dict]로 반환

def execute_scalar(sql, params=None) -> any
    # - 단일 값 반환 (COUNT 등)
```

### 4.2 routes/vendor.py

```python
vendor_bp = Blueprint('vendor', __name__)

# GET /vendor - 거래처 목록 (검색/필터/페이지네이션)
# GET /vendor/<tr_cd> - 거래처 상세 + 발주/입고 이력
# GET /vendor/<tr_cd>/orders - 거래처별 발주 이력 JSON (AJAX)
# GET /vendor/item-history - 품목별 거래 이력 + 단가 추이
```

---

## 5. API Specification (Routes)

### 5.1 GET /vendor

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| q | string | '' | 거래처명/사업자번호 검색 |
| use_yn | string | '' | 사용여부 필터 (Y/N) |
| page | int | 1 | 페이지 번호 |
| per_page | int | 30 | 페이지당 건수 |

**Response:** vendor_list.html (거래처 목록 테이블 + 페이지네이션)

### 5.2 GET /vendor/<tr_cd>

**Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| tr_cd | string | 거래처코드 (URL path) |

**Response:** vendor_detail.html
- 거래처 기본정보 (STRADE)
- 발주 이력 (LPURCLS + LPURCLS_D)
- 입고 이력 (LSTOCK + LSTOCK_D)
- 거래 통계 (총 발주금액, 총 입고금액, 최근 거래일)

### 5.3 GET /vendor/item-history

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| item_cd | string | '' | 품목코드 검색 |
| q | string | '' | 품목명 검색 |
| tr_cd | string | '' | 거래처 필터 |

**Response:** JSON (품목별 거래 이력 + 단가 추이 데이터)

---

## 6. SQL Queries

### 6.1 거래처 목록

```sql
SELECT TR_CD, TR_NM, CEO_NM, REG_NB, EMAIL, TEL, FAX,
       DIV_ADDR1, BUSINESS, JONGMOK, USE_YN
FROM STRADE
WHERE CO_CD = '1000'
  AND (TR_NM LIKE ? OR REG_NB LIKE ?)  -- 검색 조건
ORDER BY TR_NM
OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
```

### 6.2 거래처 상세

```sql
SELECT * FROM STRADE WHERE CO_CD = '1000' AND TR_CD = ?
```

### 6.3 거래처별 발주 이력

```sql
SELECT h.CLS_NB, h.CLS_DT, h.REMARK_DC,
       d.CLS_SQ, d.ITEM_CD, d.SPEC_DC, d.CLS_QT, d.CLS_UM, d.CLSH_AM
FROM LPURCLS h
JOIN LPURCLS_D d ON h.CO_CD = d.CO_CD AND h.CLS_NB = d.CLS_NB
WHERE h.CO_CD = '1000' AND h.TR_CD = ?
ORDER BY h.CLS_DT DESC, d.CLS_SQ
```

### 6.4 거래처별 입고 이력

```sql
SELECT h.RCV_NB, h.RCV_DT, h.WH_CD,
       d.RCV_SQ, d.ITEM_CD, d.RCV_QT, d.RCV_UM, d.RCVH_AM
FROM LSTOCK h
JOIN LSTOCK_D d ON h.CO_CD = d.CO_CD AND h.RCV_NB = d.RCV_NB
WHERE h.CO_CD = '1000' AND h.TR_CD = ?
ORDER BY h.RCV_DT DESC, d.RCV_SQ
```

### 6.5 품목별 단가 추이

```sql
-- 발주 단가
SELECT h.CLS_DT as TX_DT, 'PO' as TX_TYPE, h.TR_CD, d.ITEM_CD, d.SPEC_DC,
       d.CLS_QT as QTY, d.CLS_UM as UNIT_PRICE, d.CLSH_AM as AMOUNT
FROM LPURCLS h JOIN LPURCLS_D d ON h.CO_CD=d.CO_CD AND h.CLS_NB=d.CLS_NB
WHERE h.CO_CD='1000' AND d.ITEM_CD = ?

UNION ALL

-- 입고 단가
SELECT h.RCV_DT as TX_DT, 'RCV' as TX_TYPE, h.TR_CD, d.ITEM_CD, '' as SPEC_DC,
       d.RCV_QT as QTY, d.RCV_UM as UNIT_PRICE, d.RCVH_AM as AMOUNT
FROM LSTOCK h JOIN LSTOCK_D d ON h.CO_CD=d.CO_CD AND h.RCV_NB=d.RCV_NB
WHERE h.CO_CD='1000' AND d.ITEM_CD = ?

ORDER BY TX_DT
```

---

## 7. UI Design

### 7.1 vendor_list.html

```
┌──────────────────────────────────────────────────┐
│ 구매관리 > 거래처 목록                              │
├──────────────────────────────────────────────────┤
│ [통계 카드 4장]                                    │
│ 전체 거래처 | 사용중 | 최근 거래 | 주요 거래처       │
├──────────────────────────────────────────────────┤
│ 검색: [______] 사용여부: [전체 v]  [검색]           │
├──────────────────────────────────────────────────┤
│ 거래처코드 | 거래처명 | 대표자 | 사업자번호 | 업종   │
│ TR_CD      | TR_NM    | CEO_NM | REG_NB    | ...  │
│ ...        | ...      | ...    | ...       | ...  │
├──────────────────────────────────────────────────┤
│ [페이지네이션]                                     │
└──────────────────────────────────────────────────┘
```

### 7.2 vendor_detail.html

```
┌──────────────────────────────────────────────────┐
│ 거래처 상세: (주)OOO                               │
├──────────────────────────────────────────────────┤
│ [기본정보 카드]                                    │
│ 대표자 | 사업자번호 | 업종 | 종목                   │
│ 이메일 | 전화 | 팩스 | 주소                         │
├──────────────────────────────────────────────────┤
│ [거래 통계 카드]                                   │
│ 총 발주건수/금액 | 총 입고건수/금액 | 최근거래일      │
├──────────────────────────────────────────────────┤
│ [Tab: 발주이력 | 입고이력 | 품목별 단가추이]         │
│                                                   │
│ 발주이력 탭:                                       │
│ 발주번호 | 발주일 | 품목 | 수량 | 단가 | 합계       │
│                                                   │
│ 입고이력 탭:                                       │
│ 입고번호 | 입고일 | 품목 | 수량 | 단가 | 합계       │
│                                                   │
│ 단가추이 탭:                                       │
│ [Chart.js 라인 차트]                               │
└──────────────────────────────────────────────────┘
```

---

## 8. Implementation Order

1. [ ] `.env` - ICUBE 환경변수 추가
2. [ ] `modules/icube_db.py` - iCUBE 연결 모듈
3. [ ] `routes/vendor.py` - Blueprint 전체 구현
4. [ ] `templates/vendor_list.html` - 거래처 목록
5. [ ] `templates/vendor_detail.html` - 거래처 상세
6. [ ] `app.py` - vendor_bp 등록
7. [ ] `templates/base.html` - 사이드바 메뉴 추가

---

## 9. Security

- [x] iCUBE DB 읽기 전용 (Trusted_Connection, autocommit=True)
- [x] SQL injection 방지 (pyodbc 파라미터 바인딩 `?` placeholder)
- [x] login_required 데코레이터 적용
- [x] CO_CD='1000' 하드코딩 필터 (다른 회사 데이터 접근 차단)
- [x] 환경변수로 DB 서버/DB명 분리

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Phase 1 Design 완료 | Claude (CTO Lead) |
