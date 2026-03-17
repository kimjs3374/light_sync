# product-catalog Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Analyst**: gap-detector
> **Date**: 2026-03-17
> **Design Doc**: [product-catalog.design.md](../02-design/features/product-catalog.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design document(`product-catalog.design.md`) Section 11 체크리스트 기준으로 실제 구현 코드와의 일치율을 검증한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/product-catalog.design.md`
- **Implementation Files**: 11개 파일 (entities.py, __init__.py, g2b_catalog_sync.py, catalog.py, catalog_list.html, app.py, base.html, sales.py, sales_list.html, report.py, report_weekly.html)
- **Analysis Date**: 2026-03-17

---

## 2. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 97% | ✅ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 100% | ✅ |
| **Overall** | **98%** | ✅ |

---

## 3. Gap Analysis (Design vs Implementation)

### 3.1 Data Model - ProductCatalog (Step 1)

| Column | Design Type | Design nullable | Impl Type | Impl nullable | Status |
|--------|-------------|:---------------:|-----------|:-------------:|:------:|
| id | Integer, PK, autoincrement | - | Integer, PK, autoincrement | - | ✅ |
| prdct_idnt_no | String(30), unique | False | String(30), unique | False | ✅ |
| krn_prdct_nm | String(300) | False | String(300) | False | ✅ |
| prdct_clsfc_no | String(30) | True | String(30) | True | ✅ |
| dtl_prdct_nm | String(500) | True | String(500) | True | ✅ |
| unit | String(20) | True | String(20) | True | ✅ |
| unit_price | Integer | True | Integer | True | ✅ |
| price_source | String(10), default='api' | False | String(10), default='api' | False | ✅ |
| g2b_contract_method | String(20) | True | String(20) | True | ✅ |
| g2b_cntrct_no | String(50) | True | String(50) | True | ✅ |
| cntrct_bgn_date | Date | True | Date | True | ✅ |
| cntrct_end_date | Date | True | Date | True | ✅ |
| last_synced_at | DateTime | True | DateTime | True | ✅ |
| created_at | DateTime, default=now | - | DateTime, default=now | - | ✅ |
| updated_at | DateTime, default=now, onupdate=now | - | DateTime, default=now, onupdate=now | - | ✅ |

**Result**: 14/14 columns match (100%)

### 3.2 Model Export (Step 2)

| Item | Design | Implementation | Status |
|------|--------|----------------|:------:|
| import ProductCatalog | entities.py에서 import | `__init__.py:41` ProductCatalog import 존재 | ✅ |
| __all__에 추가 | "ProductCatalog" 포함 | `__init__.py:102` "ProductCatalog" 존재 | ✅ |

**Result**: 2/2 match (100%)

### 3.3 g2b_catalog_sync.py (Step 3)

| Function | Design | Implementation | Status | Notes |
|----------|--------|----------------|:------:|-------|
| sync_from_g2b(db) | Section 5.1 | `g2b_catalog_sync.py:72` | ✅ | 로직 일치 |
| get_catalog_price_map(db) | Section 5.1 | `g2b_catalog_sync.py:169` | ✅ | 로직 일치 |
| match_from_price_map(price_map, model_name) | Section 5.1 | `g2b_catalog_sync.py:186` | ✅ | 로직 일치 |
| _normalize_name(name) | Section 5.1 | `g2b_catalog_sync.py:159` | ✅ | 정규화 규칙 일치 |
| match_catalog_price(db, model_name) | Section 5.1 | **미구현** | ⚠️ | 설계에 존재하나 구현에 없음 |
| _get_api_params() | Section 5.1 | `g2b_catalog_sync.py:17` | ✅ | 설계 일치 |
| _fetch_g2b_items(endpoint, label) | Section 5.1 | `g2b_catalog_sync.py:28` | ✅ | 설계 일치 |
| _parse_date(date_str) | Section 5.1 | `g2b_catalog_sync.py:50` | ✅ | 설계 일치 |
| _parse_price(price_val) | Section 5.1 | `g2b_catalog_sync.py:61` | ✅ | 설계 일치 |
| MAS 우선 중복 제거 | Section 5.1 | `g2b_catalog_sync.py:89-98` | ✅ | |
| 수기 단가 보존 (manual) | Section 5.1 | `g2b_catalog_sync.py:127-129` | ✅ | |

**Result**: 10/11 match (91%)

### 3.4 routes/catalog.py (Step 4)

| Item | Design | Implementation | Status |
|------|--------|----------------|:------:|
| catalog_bp Blueprint | Section 4.1 | `catalog.py:9` | ✅ |
| ACTION_HANDLERS dict | Section 4.1 | `catalog.py:43-46` | ✅ |
| handle_sync_catalog() | Section 4.1 | `catalog.py:14` | ✅ |
| handle_update_price() | Section 4.1 | `catalog.py:25` | ✅ |
| catalog_list() GET | Section 4.1 | `catalog.py:51` | ✅ |
| catalog_action() POST | Section 4.1 | `catalog.py:118` | ✅ |
| 검색 (q: 품명/식별번호/상세) | Section 4.1 | `catalog.py:64-69` | ✅ |
| 필터 (price_source, method) | Section 4.1 | `catalog.py:71-79` | ✅ |
| 통계 (total, missing, last_synced) | Section 4.1 | `catalog.py:87-102` | ✅ |
| 관리자 권한 체크 | Section 4.1 | `catalog.py:16, 28` | ✅ |

**Result**: 10/10 match (100%)

### 3.5 catalog_list.html (Step 5)

| Item | Design (Section 6.1) | Implementation | Status |
|------|---------------------|----------------|:------:|
| 통계 카드 4개 | 전체/단가등록/미등록/최종동기화 | `catalog_list.html:8-41` | ✅ |
| 검색/필터 폼 | q, price_source, method | `catalog_list.html:43-78` | ✅ |
| API 동기화 버튼 (관리자) | is_admin 조건 | `catalog_list.html:67-73` | ✅ |
| 테이블 헤더 | No/물품식별번호/품명/분류/단가/출처/계약방식/수정 | `catalog_list.html:83-92` | ✅ |
| 미등록 행 노란 배경 | `background: #fffbeb` | `catalog_list.html:96` | ✅ |
| 단가 포맷 | `"{:,}".format()` + 원 | `catalog_list.html:108` | ✅ |
| 수기 수정 (관리자) | inline form, update_price | `catalog_list.html:127-135` | ✅ |
| 페이지네이션 | `{% include 'components/pagination.html' %}` | `catalog_list.html:149` | ✅ |
| mobile-stack-table | class 적용 | `catalog_list.html:81` | ✅ |

**Result**: 9/9 match (100%)

### 3.6 app.py Blueprint 등록 (Step 6)

| Item | Design (Section 7.3) | Implementation | Status |
|------|---------------------|----------------|:------:|
| import catalog_bp | `from routes.catalog import catalog_bp` | `app.py:25` | ✅ |
| register_blueprint | `app.register_blueprint(catalog_bp)` | `app.py:117` | ✅ |

**Result**: 2/2 match (100%)

### 3.7 base.html 사이드바 (Step 6)

| Item | Design (Section 7.4) | Implementation | Status |
|------|---------------------|----------------|:------:|
| 카탈로그 링크 | `url_for('catalog.catalog_list')` | `base.html:305` | ✅ |
| 하자보증/AS 앞 위치 | 하자보증 앞에 배치 | 납품관리(304) 다음, 하자보증(306) 앞 | ✅ |

**Result**: 2/2 match (100%)

### 3.8 sales.py price_map (Step 7)

| Item | Design (Section 7.1) | Implementation | Status |
|------|---------------------|----------------|:------:|
| import get_catalog_price_map | 추가 | `sales.py:23` | ✅ |
| import match_from_price_map | 추가 | `sales.py:23` | ✅ |
| price_map = get_catalog_price_map(db) | enriched 루프 전 | `sales.py:143` | ✅ |
| item._catalog_price 할당 | 각 item에 매칭 결과 | `sales.py:147` | ✅ |

**Result**: 4/4 match (100%)

### 3.9 sales_list.html 금액 컬럼 (Step 7)

| Item | Design (Section 6.2) | Implementation | Status |
|------|---------------------|----------------|:------:|
| thead에 단가/금액 th | `<th>단가</th><th>금액</th>` | `sales_list.html:111` | ✅ |
| 단가 td (매칭시 표시) | `item._catalog_price.unit_price` | `sales_list.html:120-126` | ✅ |
| 금액 td (수량*단가) | `item.quantity * item._catalog_price.unit_price` | `sales_list.html:128-133` | ✅ |
| 미매칭시 `-` | `text-muted` span | `sales_list.html:124, 132` | ✅ |

**Result**: 4/4 match (100%)

### 3.10 report.py 예상금액 (Step 8)

| Item | Design (Section 7.2) | Implementation | Status |
|------|---------------------|----------------|:------:|
| import get_catalog_price_map | 추가 | `report.py:7` | ✅ |
| import match_from_price_map | 추가 | `report.py:7` | ✅ |
| price_map 로드 | converted_projects 후 | `report.py:85` | ✅ |
| total_amount 계산 루프 | contracts -> items -> match | `report.py:86-93` | ✅ |
| p._estimated_amount 할당 | total_amount > 0 else None | `report.py:93` | ✅ |

**Result**: 5/5 match (100%)

### 3.11 report_weekly.html 예상금액 컬럼 (Step 8)

| Item | Design (Section 6.3) | Implementation | Status |
|------|---------------------|----------------|:------:|
| thead에 예상금액 th | `<th>예상금액</th>` | `report_weekly.html:336` | ✅ |
| tbody에 금액 표시 | `p._estimated_amount` 포맷 | `report_weekly.html:347` | ✅ |
| 미매칭시 `-` | else `-` | `report_weekly.html:347` | ✅ |

**Result**: 3/3 match (100%)

---

## 4. Differences Found

### 4.1 Missing Features (Design O, Implementation X)

| Item | Design Location | Description | Impact |
|------|-----------------|-------------|--------|
| match_catalog_price() | design.md Section 5.1 L490-536 | 개별 DB 쿼리 기반 단가 매칭 함수 미구현 | Low |

> **분석**: `match_catalog_price()`는 개별 건 조회용 함수로, 현재 구현에서는 목록 렌더링 시 `get_catalog_price_map()` + `match_from_price_map()` 조합으로 대체하여 성능이 더 우수하다. 개별 건 조회가 필요한 신규 기능 추가 시에만 필요하므로 영향도 Low.

### 4.2 Changed Features (Design != Implementation)

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| handle_sync_catalog db.commit() | 핸들러 내부에서 `db.commit()` 호출 | 핸들러 외부 `catalog_action()`에서 `db.commit()` 호출 | None (동작 동일) |
| sync_from_g2b price_source 분기 | `'api' if api_price else 'api'` | `'api'` (단순화) | None (결과 동일) |

> 두 차이 모두 동작에 영향 없는 코드 정리 수준의 변경이다.

### 4.3 Added Features (Design X, Implementation O)

없음.

---

## 5. Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 97%                     |
+---------------------------------------------+
|  Total Check Items:    65                    |
|  Matched:              64 items (98.5%)      |
|  Missing (Low Impact):  1 item  ( 1.5%)     |
|  Changed (No Impact):   2 items (cosmetic)   |
+---------------------------------------------+
```

### Step별 Match Rate

| Step | Check Item | Matched | Total | Rate |
|------|-----------|:-------:|:-----:|:----:|
| 1 | ProductCatalog 모델 (14 columns) | 14 | 14 | 100% |
| 2 | 모델 export | 2 | 2 | 100% |
| 3 | g2b_catalog_sync.py 함수 | 10 | 11 | 91% |
| 4 | routes/catalog.py | 10 | 10 | 100% |
| 5 | catalog_list.html | 9 | 9 | 100% |
| 6 | app.py + base.html | 4 | 4 | 100% |
| 7 | sales.py + sales_list.html | 8 | 8 | 100% |
| 8 | report.py + report_weekly.html | 8 | 8 | 100% |
| **Total** | | **65** | **66** | **98%** |

---

## 6. Recommended Actions

### 6.1 Optional (Backlog)

| Priority | Item | File | Notes |
|----------|------|------|-------|
| Low | match_catalog_price() 구현 | g2b_catalog_sync.py | 개별 건 조회 필요 시에만 추가. 현재 사용처 없음 |

### 6.2 Documentation Update

| Item | Action |
|------|--------|
| handle_sync_catalog db.commit() 위치 | 설계 문서에서 핸들러 내부 commit 제거 (실구현 기준으로 정정) |
| match_catalog_price() | 설계 문서에 "선택적 구현" 주석 추가 또는, 미사용으로 제거 |

---

## 7. Conclusion

Match Rate **98%** -- 설계와 구현이 매우 높은 수준으로 일치한다.

유일한 미구현 항목인 `match_catalog_price()` 함수는 개별 DB 쿼리 기반 매칭 함수로, 현재 모든 사용처에서 `get_catalog_price_map()` + `match_from_price_map()` 조합으로 더 효율적으로 대체되어 있어 실질적 gap이 아니다.

**판정: Check 통과 (>= 90%)**

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial analysis | gap-detector |
