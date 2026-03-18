# product-autocomplete Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: Light-Sync ERP
> **Analyst**: Claude (gap-detector)
> **Date**: 2026-03-17
> **Design Doc**: [product-autocomplete.design.md](../02-design/features/product-autocomplete.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design 문서(product-autocomplete.design.md)와 실제 구현 코드 간의 일치도를 검증하고, GAP 항목을 식별한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/product-autocomplete.design.md`
- **Implementation Files**:
  - `routes/api.py` (catalog_search 엔드포인트)
  - `templates/components/catalog_autocomplete.html` (JS+CSS 컴포넌트)
  - `templates/base.html` (include)
  - `templates/contract_detail.html` (적용)
  - `templates/project_create.html` (적용)
  - `templates/project_detail.html` (적용)

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 API 엔드포인트 (Section 2)

| Design 항목 | Implementation | Status | Notes |
|-------------|---------------|--------|-------|
| `GET /api/catalog/search` | `@api_bp.route('/catalog/search')` | ✅ Match | |
| `q` 파라미터 (필수, 2글자 이상) | `q = (request.args.get('q') or '').strip()` + `len(q) < 2` 체크 | ✅ Match | |
| `category` 파라미터 (선택) | `category = (request.args.get('category') or '').strip()` | ✅ Match | |
| Response `{results: [...]}` | `jsonify({'results': [...]})` | ✅ Match | |
| Response 필드: id, model_name, item_name, spec, unit_price, unit | 동일 6개 필드 반환 | ✅ Match | |
| 검색: model_name OR item_name OR spec ILIKE | `or_(...)` 3개 필드 | ✅ Match | |
| category 추가 필터 | `query.filter(item_name.ilike(...))` | ✅ Match | |
| `ORDER BY model_name ASC` | `query.order_by(ProductCatalog.model_name)` | ✅ Match | |
| `LIMIT 10` | `.limit(10)` | ✅ Match | |
| `@login_required` | `@login_required` | ✅ Match | |
| DB 접근: `db.query(ProductCatalog)` 직접 | `with get_db() as db:` 컨텍스트 매니저 사용 | ✅ Match | Design은 단순 예시, 구현은 프로젝트 패턴 준수 |

**API Match Rate: 11/11 = 100%**

### 2.2 JS 컴포넌트 (Section 3)

| Design 항목 | Implementation | Status | Notes |
|-------------|---------------|--------|-------|
| `data-catalog-autocomplete` 속성 마커 | `e.target.hasAttribute('data-catalog-autocomplete')` | ✅ Match | |
| `data-category-select` 속성 | `input.getAttribute('data-category-select')` | ✅ Match | |
| 이벤트 위임 (document level) | `document.addEventListener('input', ...)` | ✅ Match | |
| 디바운스 300ms | `setTimeout(..., 300)` | ✅ Match | |
| 2글자 미만 드롭다운 닫기 | `if (q.length < 2) { closeDropdown(); return; }` | ✅ Match | |
| `fetch GET /api/catalog/search?q=...&category=...` | `fetch('/api/catalog/search?' + params, ...)` | ✅ Match | |
| AbortController 이전 요청 취소 | `if (controller) controller.abort(); controller = new AbortController();` | ✅ Match | |
| 선택 시 `input.value = model_name` | `currentInput.value = item.getAttribute('data-model')` | ✅ Match | |
| ArrowDown: 다음 항목 (닫혀있으면 열기) | `if (!dd.classList.contains('show')) return;` -- 닫혀있으면 무시 | ❌ GAP | 드롭다운 닫혀있을 때 ArrowDown으로 열기 미구현 |
| ArrowUp: 이전 항목 | `activeIndex = Math.max(activeIndex - 1, 0)` | ✅ Match | |
| Enter: 활성 항목 선택 | `if (e.key === 'Enter' && activeIndex >= 0)` | ✅ Match | |
| Esc: 드롭다운 닫기 | `e.key === 'Escape'` | ✅ Match | |
| Tab: 드롭다운 닫기 | Tab 전용 핸들러 없음 (document.click으로 간접 처리) | ⚠️ Minor | 기능적으로 동작하나 명시적 핸들링 없음 |
| 한글 compositionend 처리 | `compositionstart/compositionend` 리스너 구현 | ✅ Match | |

**JS 컴포넌트 Match Rate: 12/14 = 86%** (1 GAP, 1 Minor)

### 2.3 드롭다운 UI & CSS (Section 3.4, 5)

| Design 항목 | Implementation | Status | Notes |
|-------------|---------------|--------|-------|
| `position: absolute` | `position: fixed` | ⚠️ Minor | fixed 사용으로 스크롤 안정성 개선 (의도적 개선) |
| `z-index: 1050` | `z-index: 9999` | ⚠️ Minor | 모달 위에서도 표시되도록 상향 (의도적) |
| `max-height: 250px` | `max-height: 220px` | ⚠️ Minor | 30px 차이 |
| `box-shadow: 0 4px 8px rgba(0,0,0,0.15)` | `box-shadow: 0 6px 16px rgba(0,0,0,0.2)` | ⚠️ Minor | 그림자 강화 |
| Bootstrap `dropdown-menu show` 스타일 재활용 | 자체 CSS 클래스 `.catalog-ac-dropdown` + `.show` | ⚠️ Minor | Bootstrap 의존 제거 (더 안정적) |
| `.dropdown-item` 클래스 | `.ac-item` 클래스 | ⚠️ Minor | 자체 네이밍으로 변경 |
| `.dropdown-item .ac-price` | `.ac-item .ac-spec` | ⚠️ Minor | 클래스명 변경 |
| 항목 표시: **모델명** -- 규격 (단가) | `<strong>모델명</strong><span class="ac-spec"> -- 규격 (단가)</span>` | ✅ Match | |
| 활성 항목 `active` 클래스 파란 배경 | `.ac-item.active { background-color: #0d6efd; color: white; }` | ✅ Match | |
| `font-size: 0.85rem`, `padding: 6px 12px` | `font-size: 0.85rem`, `padding: 7px 12px` | ⚠️ Minor | 1px 차이 |

**CSS Match Rate: 2/10 = 20% (exact), 기능적 Match Rate: 10/10 = 100%**

CSS 차이는 모두 의도적 개선으로 판단됨. 기능 동작에는 영향 없음.

### 2.4 엣지 케이스 (Section 6)

| Design 항목 | Implementation | Status | Notes |
|-------------|---------------|--------|-------|
| 검색 결과 0건: 드롭다운 미표시 | `if (!data.results \|\| data.results.length === 0) { closeDropdown(); }` | ✅ Match | |
| 네트워크 오류: 조용히 실패 | `catch(e) { if (e.name !== 'AbortError') closeDropdown(); }` | ✅ Match | |
| 포커스 아웃: 200ms 지연 후 닫기 | `mousedown`에서 `e.preventDefault()` + document click 핸들러 | ⚠️ Minor | 다른 메커니즘이나 동일 효과 |
| 동일 모델명 규격 차이: 구분 표시 | 규격+단가 표시 구현 | ✅ Match | |
| 한글 조합 중 처리 | `compositionstart/compositionend` 구현 | ✅ Match | |

**엣지 케이스 Match Rate: 4/5 = 80%** (1 Minor)

### 2.5 템플릿 적용 (Section 4)

| Design 항목 | Implementation | Status | Notes |
|-------------|---------------|--------|-------|
| contract_detail 기존 품목 수정: `data-catalog-autocomplete` | L245: `data-catalog-autocomplete data-category-select="category"` | ✅ Match+ | Design보다 category 연동 추가 (개선) |
| contract_detail 신규 추가 폼: `data-catalog-autocomplete` | L311: `data-catalog-autocomplete data-category-select="category"` | ✅ Match+ | Design보다 category 연동 추가 (개선) |
| project_create: `data-catalog-autocomplete data-category-select` | L59: `data-catalog-autocomplete data-category-select="light_category[]"` | ✅ Match | |
| project_create 동적 행: 자동완성 적용 | `addRow()` 함수의 innerHTML에 `data-catalog-autocomplete` 미포함 | ❌ GAP | 동적 추가 행에서 자동완성 미작동 |
| project_detail 자재 모델명: `data-catalog-autocomplete` | L131: 기존 자재 `data-catalog-autocomplete` 적용 | ✅ Match | |
| project_detail 신규 추가: `data-catalog-autocomplete` | L167: `data-catalog-autocomplete data-category-select="category"` | ✅ Match | |
| base.html `</body>` 직전 include | L480: `{% include 'components/catalog_autocomplete.html' %}` | ✅ Match | |

**템플릿 적용 Match Rate: 6/7 = 86%** (1 GAP)

### 2.6 Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 93%                     |
+---------------------------------------------+
|  Total Items:         47                     |
|  Match:               35 items (74%)         |
|  Match (Minor diff):  10 items (21%)         |
|  GAP (Not impl):       2 items ( 4%)         |
+---------------------------------------------+
|  Functional Match:    96% (45/47)            |
|  Exact Match:         74% (35/47)            |
+---------------------------------------------+
```

---

## 3. GAP 목록 (Must Fix)

### 3.1 Missing Features (Design O, Implementation X)

| # | Item | Design Location | Impl Location | Description | Impact |
|---|------|----------------|---------------|-------------|--------|
| G-1 | ArrowDown 드롭다운 열기 | design.md:154 | catalog_autocomplete.html:145 | 드롭다운 닫혀있을 때 ArrowDown으로 열기 미구현. 현재 `return`으로 무시됨 | Low - 키보드만 사용하는 UX에서 불편 |
| G-2 | 동적 행 자동완성 누락 | design.md:233 (project_create) | project_create.html:81 | `addRow()` 함수의 innerHTML에 `data-catalog-autocomplete`, `data-category-select` 속성 미포함. 이벤트 위임으로 JS는 동작하나 속성 자체가 없어 트리거 안 됨 | Medium - 항목 추가 후 자동완성 불가 |

---

## 4. Minor Difference 목록 (Won't Fix / Intentional)

| # | Item | Design | Implementation | Reason |
|---|------|--------|----------------|--------|
| M-1 | CSS position | `absolute` | `fixed` | 스크롤 시 위치 이탈 방지 (의도적 개선) |
| M-2 | z-index | `1050` | `9999` | 모달 등 다른 UI 위에서도 표시 보장 |
| M-3 | max-height | `250px` | `220px` | 미세 조정 (시각적 영향 미미) |
| M-4 | box-shadow | `0 4px 8px rgba(0,0,0,0.15)` | `0 6px 16px rgba(0,0,0,0.2)` | 그림자 강화로 가시성 개선 |
| M-5 | CSS 클래스 | `dropdown-menu`, `dropdown-item`, `ac-price` | `catalog-ac-dropdown`, `ac-item`, `ac-spec` | Bootstrap 의존 제거, 자체 네이밍 |
| M-6 | padding | `6px 12px` | `7px 12px` | 1px 차이 (미미) |
| M-7 | Tab 키 처리 | 명시적 `Tab` case | document click으로 간접 처리 | 동일 결과, 다른 메커니즘 |
| M-8 | 포커스 아웃 처리 | 200ms 지연 후 닫기 | mousedown preventDefault + document click | 동일 UX, 더 안정적인 패턴 |
| M-9 | contract_detail category 연동 | 미언급 | `data-category-select="category"` 추가 | Design 대비 기능 추가 (개선) |
| M-10 | 드롭다운 생성 방식 | Bootstrap 스타일 재활용 | body에 단일 div 생성 + fixed position | overflow 문제 해결 (의도적 개선) |

---

## 5. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| API Match | 100% | ✅ |
| JS Component Match | 86% | ⚠️ |
| CSS (기능적) | 100% | ✅ |
| Edge Case Match | 80% | ⚠️ |
| Template Match | 86% | ⚠️ |
| **Overall (Functional)** | **96%** | **✅** |
| **Overall (Exact)** | **74%** | **⚠️** |

> **판정**: Functional Match Rate 96% >= 90% 기준 충족.
> Minor Difference는 모두 의도적 개선으로 분류되어 Design 문서 업데이트 권장.

---

## 6. Recommended Actions

### 6.1 Immediate (GAP 수정)

| Priority | Item | File | Action |
|----------|------|------|--------|
| 1 | G-2: 동적 행 자동완성 | `templates/project_create.html:81` | `addRow()` innerHTML에 `data-catalog-autocomplete data-category-select="${prefix}_category[]"` 추가 |
| 2 | G-1: ArrowDown 드롭다운 열기 | `templates/components/catalog_autocomplete.html:145` | 드롭다운 닫혀있을 때 ArrowDown 시 `doSearch(e.target)` 호출 추가 |

### 6.2 Design 문서 업데이트 (Minor Difference 반영)

| Item | Action |
|------|--------|
| M-1~M-6 | CSS Section 5를 실제 구현 값으로 업데이트 |
| M-5 | 클래스 네이밍을 `.ac-item`, `.ac-spec`으로 변경 반영 |
| M-7~M-8 | 엣지 케이스 처리 방식 업데이트 |
| M-9 | contract_detail에 `data-category-select` 연동 명시 |
| M-10 | 드롭다운 구현 방식을 "body에 fixed div 1개 생성" 방식으로 업데이트 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial gap analysis | Claude (gap-detector) |
