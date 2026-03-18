# 품목 자동완성 입력 - Design

> **Feature**: product-autocomplete
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Design
> **Plan Reference**: [product-autocomplete.plan.md](../../01-plan/features/product-autocomplete.plan.md)

---

## 1. Implementation Order

| Step | 파일 | 작업 | FR |
|------|------|------|----|
| 1 | `routes/api.py` | 검색 API 엔드포인트 추가 | FR-01 |
| 2 | `templates/components/catalog_autocomplete.html` | 자동완성 JS+CSS 컴포넌트 | FR-02, FR-03 |
| 3 | `templates/contract_detail.html` | 자동완성 적용 (계약 상세) | FR-04 |
| 4 | `templates/project_create.html` | 자동완성 적용 (설계 등록) | FR-04 |
| 5 | `templates/project_detail.html` | 자동완성 적용 (설계 상세) | FR-04 |

---

## 2. API 설계

### 2.1 검색 엔드포인트

```
GET /api/catalog/search?q={검색어}&category={품목군}
```

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `q` | Y | 검색어 (2글자 이상) |
| `category` | N | 품목군 필터 (투광등기구, 조명타워 등) |

**Response (200)**:
```json
{
  "results": [
    {
      "id": 1,
      "model_name": "ARENA-200S",
      "item_name": "LED투광등기구",
      "spec": "200W",
      "unit_price": 350000,
      "unit": "개"
    }
  ]
}
```

**검색 로직**:
- `ProductCatalog.model_name ILIKE '%{q}%'` OR `ProductCatalog.item_name ILIKE '%{q}%'` OR `ProductCatalog.spec ILIKE '%{q}%'`
- category 파라미터 있으면: `ProductCatalog.item_name ILIKE '%{category}%'` 추가 필터
- `ORDER BY model_name ASC`
- `LIMIT 10`

**인증**: `@login_required` (세션 기반)

### 2.2 라우트 코드 (routes/api.py에 추가)

```python
@api_bp.route('/catalog/search')
@login_required
def catalog_search():
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()

    if len(q) < 2:
        return jsonify({'results': []})

    query = db.query(ProductCatalog).filter(
        or_(
            ProductCatalog.model_name.ilike(f'%{q}%'),
            ProductCatalog.item_name.ilike(f'%{q}%'),
            ProductCatalog.spec.ilike(f'%{q}%'),
        )
    )
    if category:
        query = query.filter(ProductCatalog.item_name.ilike(f'%{category}%'))

    results = query.order_by(ProductCatalog.model_name).limit(10).all()
    return jsonify({'results': [
        {
            'id': r.id,
            'model_name': r.model_name or '',
            'item_name': r.item_name or '',
            'spec': r.spec or '',
            'unit_price': r.unit_price or 0,
            'unit': r.unit or '',
        } for r in results
    ]})
```

---

## 3. 자동완성 JS 컴포넌트 설계

### 3.1 파일: `templates/components/catalog_autocomplete.html`

Jinja2 `{% include %}` 방식으로 포함. `<script>` + `<style>` 블록.

### 3.2 동작 방식

```
사용자 타이핑
  → input 이벤트 발생
  → 이벤트 위임 (document level)에서 data-catalog-autocomplete 속성 감지
  → 디바운스 300ms
  → 2글자 미만이면 드롭다운 닫기
  → fetch GET /api/catalog/search?q=...&category=...
  → 이전 요청 AbortController로 취소
  → 결과를 드롭다운으로 표시
  → 선택 시 input.value = model_name
```

### 3.3 HTML 마크업 규칙

자동완성을 적용할 input에 `data-catalog-autocomplete` 속성 추가:

```html
<!-- 기본 사용 -->
<input type="text" name="model_name" data-catalog-autocomplete>

<!-- 카테고리 연동 (같은 행의 select에서 category 값 읽기) -->
<input type="text" name="model_name" data-catalog-autocomplete data-category-select="light_category[]">
```

- `data-catalog-autocomplete`: 자동완성 활성화 마커
- `data-category-select`: (선택) 같은 행에서 category select의 name. 있으면 검색 시 category 파라미터로 전달

### 3.4 드롭다운 UI

```
┌─────────────────────────────────────────┐
│ [입력 필드: ARE___]                      │
├─────────────────────────────────────────┤
│ ARENA-200S — 200W (₩350,000)            │  ← 활성(파란 배경)
│ ARENA-400S — 400W (₩520,000)            │
│ ARENA-600S — 600W (₩780,000)            │
└─────────────────────────────────────────┘
```

- Bootstrap 5 `dropdown-menu show` 스타일 재활용
- `position: absolute` + 입력 필드 바로 아래 위치
- 활성 항목: `active` 클래스 (↑↓ 키보드 이동)
- 각 항목 표시: **모델명** — 규격 (₩단가)

### 3.5 키보드 인터랙션

| 키 | 동작 |
|----|------|
| `↓` | 다음 항목 선택 (드롭다운 닫혀있으면 열기) |
| `↑` | 이전 항목 선택 |
| `Enter` | 현재 활성 항목 선택 → input에 채움 → 드롭다운 닫기 |
| `Esc` | 드롭다운 닫기 |
| `Tab` | 드롭다운 닫기 (기본 동작 유지) |

### 3.6 이벤트 위임 (동적 행 지원)

```javascript
// document 레벨에서 이벤트 위임 — 동적으로 추가된 행에도 자동 적용
document.addEventListener('input', function(e) {
    if (e.target.hasAttribute('data-catalog-autocomplete')) {
        handleAutocompleteInput(e.target);
    }
});
document.addEventListener('keydown', function(e) {
    if (e.target.hasAttribute('data-catalog-autocomplete')) {
        handleAutocompleteKeydown(e);
    }
});
```

### 3.7 AbortController (이전 요청 취소)

```javascript
let currentController = null;

async function fetchCatalog(query, category) {
    if (currentController) currentController.abort();
    currentController = new AbortController();

    const params = new URLSearchParams({q: query});
    if (category) params.set('category', category);

    const resp = await fetch(`/api/catalog/search?${params}`, {
        signal: currentController.signal
    });
    return resp.json();
}
```

---

## 4. 템플릿 적용 상세

### 4.1 contract_detail.html

**신규 품목 추가 폼** (현재):
```html
<input type="text" name="model_name" class="form-control form-control-sm" placeholder="신규 모델">
```

**변경 후**:
```html
<input type="text" name="model_name" class="form-control form-control-sm"
       placeholder="모델명 입력 (자동완성)" data-catalog-autocomplete>
```

**기존 품목 수정** (현재):
```html
<input type="text" name="model_name" class="form-control form-control-sm" value="{{ item.model_name or '' }}">
```

**변경 후**:
```html
<input type="text" name="model_name" class="form-control form-control-sm"
       value="{{ item.model_name or '' }}" data-catalog-autocomplete>
```

### 4.2 project_create.html

**현재**:
```html
<input type="text" name="light_model[]" class="form-control form-control-sm">
```

**변경 후**:
```html
<input type="text" name="light_model[]" class="form-control form-control-sm"
       data-catalog-autocomplete data-category-select="light_category[]">
```

### 4.3 project_detail.html

자재 추가 모델명 input에 동일하게 `data-catalog-autocomplete` 추가.

### 4.4 컴포넌트 include 위치

`templates/base.html`의 `</body>` 직전에 추가:

```html
{% include 'components/catalog_autocomplete.html' %}
```

→ 모든 페이지에서 자동완성 JS 로드. `data-catalog-autocomplete` 속성이 없으면 아무 동작 안 함.

---

## 5. CSS 스타일

```css
.catalog-ac-dropdown {
    position: absolute;
    z-index: 1050;
    max-height: 250px;
    overflow-y: auto;
    width: 100%;
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}
.catalog-ac-dropdown .dropdown-item {
    font-size: 0.85rem;
    padding: 6px 12px;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.catalog-ac-dropdown .dropdown-item.active {
    background-color: #0d6efd;
    color: white;
}
.catalog-ac-dropdown .dropdown-item .ac-price {
    color: #6c757d;
    font-size: 0.78rem;
}
.catalog-ac-dropdown .dropdown-item.active .ac-price {
    color: #e0e0e0;
}
```

---

## 6. 엣지 케이스

| 상황 | 처리 |
|------|------|
| 검색 결과 0건 | 드롭다운 표시하지 않음 (자유 입력 계속) |
| 네트워크 오류 | 조용히 실패 (자유 입력 계속) |
| 입력 필드 포커스 아웃 | 200ms 지연 후 드롭다운 닫기 (클릭 선택 허용) |
| 동일 모델명 다수 (규격 차이) | 규격+단가로 구분하여 표시 |
| 한글 입력 (조합 중) | `compositionend` 이벤트 후 검색 실행 |

---

## 7. 테스트 시나리오

| # | 시나리오 | 기대 결과 |
|---|---------|----------|
| 1 | "ARE" 입력 | ARENA 시리즈 모델 목록 표시 |
| 2 | 목록에서 ↓↓ Enter | 선택한 모델명이 input에 채워짐 |
| 3 | "존재하지않는모델" 입력 | 결과 없음, 자유 입력 유지 |
| 4 | 동적 행 추가 후 입력 | 새 행에서도 자동완성 정상 동작 |
| 5 | 빠르게 연속 타이핑 | 디바운스로 마지막 입력만 API 호출 |
| 6 | Esc 키 | 드롭다운 닫힘 |
| 7 | category select 변경 후 검색 | 해당 품목군 내에서만 검색 |
