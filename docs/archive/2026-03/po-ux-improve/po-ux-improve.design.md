# 발주 UX 개선 — Frontend Design Spec
> Phase 3 Mockup / Phase 5 Design System 적용
> 작성일: 2026-03-20

---

## 1. 설계 범위

| 화면 | 파일 | 개선 항목 |
|------|------|-----------|
| 소요자재 계산 | `templates/bom_requirement.html` | R1-R5: 체크박스 UX 전면 개선 |
| 발주서 관리 목록 | `templates/po_list.html` | P1-P5: 컬럼 재배치 + 거래처 그룹핑 |

---

## 2. MAGNATECH Design Token 참조

```css
/* base.html에서 이미 정의됨 — 오버라이드 없이 참조만 */
--mg-primary:  #2563eb
--mg-success:  #16a34a
--mg-warning:  #d97706
--mg-danger:   #dc2626
--mg-ink:      #0f172a
--mg-muted:    #64748b
--mg-border:   #e2e8f0
--mg-bg:       #f8fafc
--mg-radius:   .65rem
--mg-shadow:   0 2px 12px rgba(15,23,42,.06)
```

---

## 3. bom_requirement.html — 체크박스 UX 설계 (R1-R5)

### 3-1. 변경 전/후 비교

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 버튼 가시성 | `display:none` → 선택시 표시 | 항상 표시, 0건이면 disabled |
| 전체선택 피드백 | 없음 | indeterminate 상태 지원 |
| 행 하이라이트 | 없음 | 선택행 배경색 + 좌측 accent bar |
| 선택 카운터 | 버튼 내 텍스트만 | 카드 헤더에 별도 배지 표시 |
| 모달 소계 | 소계 텍스트 우측 | 거래처 헤더행 + 소계 강조 행 |

### 3-2. 카드 헤더 HTML 변경

```html
<!-- 기존 -->
<div class="card-header bg-white py-2 d-flex justify-content-between align-items-center">
    <div>
        <strong>소요자재 목록</strong>
        <small class="text-muted ms-2">(계약 품목 x BOM = 소요 자재)</small>
    </div>
    <button type="button" class="btn btn-primary btn-sm" id="btnCreatePO"
            style="display:none;" data-bs-toggle="modal" data-bs-target="#poPreviewModal">
        선택 자재 발주서 생성 (<span id="selectedCount">0</span>건)
    </button>
</div>

<!-- 변경 후 -->
<div class="card-header bg-white py-2 d-flex justify-content-between align-items-center flex-wrap gap-2">
    <div class="d-flex align-items-center gap-2">
        <strong>소요자재 목록</strong>
        <small class="text-muted">(계약 품목 x BOM = 소요 자재)</small>
        <!-- R3: 선택 건수 배지 — 0건이면 숨김 -->
        <span class="badge rounded-pill bg-primary" id="selectionBadge"
              style="display:none; font-size:.72rem;">
            <span id="selectedCount">0</span>건 선택
        </span>
    </div>
    <!-- R3: 항상 표시, 0건이면 disabled -->
    <button type="button" class="btn btn-primary btn-sm" id="btnCreatePO"
            disabled
            data-bs-toggle="modal" data-bs-target="#poPreviewModal">
        선택 자재 발주서 생성
    </button>
</div>
```

### 3-3. 전체선택 체크박스 th 변경

```html
<!-- 기존 -->
<th style="width:36px"><input type="checkbox" id="checkAll" title="전체 선택"></th>

<!-- 변경 후 — indeterminate 상태 지원을 위해 label 추가 -->
<th style="width:36px; padding-left:12px;">
    <input type="checkbox" id="checkAll"
           class="form-check-input"
           title="전체 선택/해제"
           aria-label="전체 선택">
</th>
```

### 3-4. 체크 가능 행의 체크박스 td 변경

```html
<!-- 기존 -->
<input type="checkbox" class="item-check"
    data-bom-item-id="{{ r.bom_item.id }}" ...>

<!-- 변경 후 — form-check-input 클래스 통일 -->
<input type="checkbox" class="item-check form-check-input"
    data-bom-item-id="{{ r.bom_item.id }}"
    data-contract-item-id="{{ r.contract_item.id }}"
    data-item-name="{{ r.bom_item.item_name }}"
    data-item-spec="{{ r.bom_item.item_spec or '' }}"
    data-quantity="{{ r.shortage|int }}"
    data-unit="{{ r.bom_item.unit or 'EA' }}"
    data-unit-price="{{ r.bom_item.unit_price or 0 }}"
    data-supplier="{{ r.bom_item.supplier or '' }}"
    aria-label="{{ r.bom_item.item_name }} 선택">
```

### 3-5. CSS — 행 하이라이트 (R4)

```html
<style>
/* bom_requirement.html 전용 — base.html 변수 참조 */

/* R4: 선택 행 하이라이트 */
.req-table tbody tr.row-selected {
    background: #eff6ff !important;          /* blue-50 */
    box-shadow: inset 3px 0 0 var(--mg-primary);
}
.req-table tbody tr.row-selected td {
    color: var(--mg-ink);
}

/* 체크박스 열 고정 너비 */
.req-table th:first-child,
.req-table td:first-child {
    width: 44px;
    padding-left: 12px;
    padding-right: 4px;
}

/* 부족량 > 0 행: 체크박스 있는 행 cursor */
.req-table tbody tr.has-checkbox {
    cursor: pointer;
}
.req-table tbody tr.has-checkbox:hover {
    background: #f0f9ff;
}

/* 선택 버튼 disabled 상태 */
#btnCreatePO:disabled {
    opacity: .45;
    cursor: not-allowed;
    pointer-events: auto;   /* title tooltip 유지 */
}
#btnCreatePO:disabled:hover::after {
    content: '자재를 선택하세요';
    position: absolute;
    background: #0f172a;
    color: #fff;
    font-size: .72rem;
    padding: 3px 8px;
    border-radius: 4px;
    white-space: nowrap;
    margin-top: 28px;
    margin-left: -80px;
}

/* R3: 선택 배지 애니메이션 */
#selectionBadge {
    transition: opacity .15s, transform .15s;
}

/* 모바일 반응형 */
@media (max-width: 767.98px) {
    .req-table th,
    .req-table td {
        font-size: .75rem;
        padding: 5px 4px;
    }
    /* 모바일에서 숨길 컬럼: 제품수량, 단위소요 */
    .req-col-product-qty,
    .req-col-per-unit {
        display: none;
    }
}
</style>
```

### 3-6. JS 동작 명세 (R2, R3, R4 통합)

```javascript
(function () {
    'use strict';

    /* ── 요소 참조 ── */
    var checkAll       = document.getElementById('checkAll');
    var checks         = document.querySelectorAll('.item-check');
    var btnCreatePO    = document.getElementById('btnCreatePO');
    var selectionBadge = document.getElementById('selectionBadge');
    var selectedCountEl= document.getElementById('selectedCount');

    /* ── R3: UI 동기화 ── */
    function syncUI() {
        var total   = checks.length;
        var checked = 0;
        checks.forEach(function (cb) { if (cb.checked) checked++; });

        /* 선택 건수 표시 */
        selectedCountEl.textContent = checked;

        /* 배지: 0건이면 숨김 */
        selectionBadge.style.display = checked > 0 ? '' : 'none';

        /* 버튼: 0건이면 disabled */
        btnCreatePO.disabled = checked === 0;

        /* R2: 전체선택 체크박스 상태
           - 0건: unchecked
           - 전체: checked
           - 일부: indeterminate  */
        if (checkAll) {
            if (checked === 0) {
                checkAll.checked       = false;
                checkAll.indeterminate = false;
            } else if (checked === total) {
                checkAll.checked       = true;
                checkAll.indeterminate = false;
            } else {
                checkAll.checked       = false;
                checkAll.indeterminate = true;  /* 부분 선택 */
            }
        }

        /* R4: 행 하이라이트 */
        checks.forEach(function (cb) {
            var row = cb.closest('tr');
            if (!row) return;
            row.classList.toggle('row-selected', cb.checked);
        });
    }

    /* ── R2: 전체선택 ── */
    if (checkAll) {
        checkAll.addEventListener('change', function () {
            checks.forEach(function (cb) { cb.checked = checkAll.checked; });
            syncUI();
        });
    }

    /* ── 개별 체크박스 ── */
    checks.forEach(function (cb) {
        cb.addEventListener('change', syncUI);
    });

    /* ── R4: 행 클릭으로도 토글 (체크박스 있는 행만) ── */
    checks.forEach(function (cb) {
        var row = cb.closest('tr');
        if (!row) return;
        row.classList.add('has-checkbox');
        row.addEventListener('click', function (e) {
            /* 체크박스 자체 클릭은 기본 동작 유지 */
            if (e.target === cb) return;
            cb.checked = !cb.checked;
            syncUI();
        });
    });

    /* ── R5: 모달 — 거래처별 소계 표시 ── */
    var modal = document.getElementById('poPreviewModal');
    if (modal) {
        modal.addEventListener('show.bs.modal', function () {
            /* 선택 항목 수집 */
            var selected = [];
            checks.forEach(function (cb) {
                if (!cb.checked) return;
                selected.push({
                    bom_item_id:      parseInt(cb.dataset.bomItemId)      || 0,
                    contract_item_id: parseInt(cb.dataset.contractItemId) || 0,
                    item_name:        cb.dataset.itemName  || '',
                    item_spec:        cb.dataset.itemSpec  || '',
                    quantity:         parseInt(cb.dataset.quantity)  || 0,
                    unit:             cb.dataset.unit       || 'EA',
                    unit_price:       parseFloat(cb.dataset.unitPrice) || 0,
                    supplier:         cb.dataset.supplier  || '미지정'
                });
            });

            /* 거래처별 그룹핑 */
            var groups = {};
            var groupOrder = [];
            selected.forEach(function (item) {
                var key = item.supplier || '미지정';
                if (!groups[key]) { groups[key] = []; groupOrder.push(key); }
                groups[key].push(item);
            });

            /* R5: 프리뷰 HTML — 거래처별 소계 강조 */
            var poCount = groupOrder.length;
            var html = '<p class="mb-3 text-muted" style="font-size:.85rem;">'
                + '거래처별 발주서 <strong class="text-dark">' + poCount + '건</strong>이 생성됩니다.</p>';

            var grandTotal = 0;

            groupOrder.forEach(function (supplier) {
                var items    = groups[supplier];
                var subtotal = 0;

                /* 거래처 헤더 카드 */
                html += '<div class="card border-0 mb-3" style="border-left:3px solid var(--mg-primary)!important;border-radius:var(--mg-radius);background:#f8fafc;">';
                html += '<div class="card-header bg-transparent py-2 d-flex justify-content-between align-items-center" style="border-bottom:1px solid var(--mg-border);">';
                html += '<span class="fw-bold" style="font-size:.88rem;">' + escHtml(supplier) + '</span>';
                html += '<span class="badge bg-primary-subtle text-primary" style="font-size:.72rem;">' + items.length + '품목</span>';
                html += '</div>';
                html += '<div class="card-body p-0">';

                /* 품목 테이블 */
                html += '<table class="table table-sm mb-0" style="font-size:.8rem;">';
                html += '<thead><tr style="background:#f1f5f9;">'
                    + '<th style="width:40%">품명</th>'
                    + '<th>규격</th>'
                    + '<th class="text-end" style="width:60px">수량</th>'
                    + '<th style="width:30px">단위</th>'
                    + '<th class="text-end" style="width:90px">단가</th>'
                    + '<th class="text-end" style="width:90px">금액</th>'
                    + '</tr></thead><tbody>';

                items.forEach(function (it) {
                    var amt  = it.quantity * it.unit_price;
                    subtotal += amt;
                    html += '<tr>'
                        + '<td class="text-truncate" style="max-width:0;">' + escHtml(it.item_name) + '</td>'
                        + '<td class="text-muted text-truncate" style="max-width:0;"><small>' + escHtml(it.item_spec) + '</small></td>'
                        + '<td class="text-end fw-bold">' + it.quantity.toLocaleString() + '</td>'
                        + '<td class="text-muted">' + it.unit + '</td>'
                        + '<td class="text-end">' + it.unit_price.toLocaleString() + '</td>'
                        + '<td class="text-end fw-bold">' + amt.toLocaleString() + '</td>'
                        + '</tr>';
                });

                html += '</tbody></table>';

                /* R5: 소계 행 — 강조 스타일 */
                grandTotal += subtotal;
                html += '<div class="d-flex justify-content-between align-items-center px-3 py-2" '
                    + 'style="background:#eff6ff;border-top:1px solid #bfdbfe;">'
                    + '<small class="text-primary fw-bold">소계</small>'
                    + '<strong class="text-primary" style="font-size:.95rem;">'
                    + subtotal.toLocaleString() + '원</strong>'
                    + '</div>';

                html += '</div></div>';  /* card-body + card */
            });

            /* 총합계 */
            if (poCount > 1) {
                html += '<div class="d-flex justify-content-between align-items-center px-3 py-2 rounded" '
                    + 'style="background:#0f172a;color:#fff;margin-top:-4px;">'
                    + '<span class="fw-bold">총 발주 합계</span>'
                    + '<strong style="font-size:1rem;">' + grandTotal.toLocaleString() + '원</strong>'
                    + '</div>';
            }

            document.getElementById('poPreviewBody').innerHTML = html;
            document.getElementById('selectedItemsInput').value = JSON.stringify(selected);
        });
    }

    /* ── 유틸: XSS 방지 ── */
    function escHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ── 초기화 ── */
    syncUI();
})();
```

### 3-7. 모바일 반응형 고려사항

- 체크박스 터치 영역: 최소 44x44px (행 클릭 토글로 자연스럽게 충족)
- 숨김 컬럼: 제품수량, 단위소요 → `req-col-product-qty`, `req-col-per-unit` 클래스로 `display:none`
- 버튼은 카드 헤더 flex-wrap으로 줄바꿈 허용 (white-space:nowrap 유지)
- 모달: `modal-dialog modal-lg` + `modal-fullscreen-md-down` 고려

---

## 4. po_list.html — 거래처 그룹핑 UI 설계 (P1-P5)

### 4-1. 컬럼 재배치 명세 (P1, P2, P5)

| 순서 | 컬럼 | 너비 | 정렬 | 변경사항 |
|------|------|------|------|---------|
| 1 | 발주번호 | 110px | 좌 | 유지 |
| 2 | 발주일 | 90px | 좌 | 유지 |
| 3 | 현장 | 140px | 좌 | **신규 추가 (P2)** |
| 4 | 거래처 | auto | 좌 | 유지 |
| 5 | 상태 | 75px | 좌 | 유지 |
| 6 | 합계 | 100px | 우 | 유지 |
| 7 | 발송 | 55px | 좌 | 유지 |
| 8 | 액션 | 50px | - | 유지 |
| ~~공급가액~~ | ~~110px~~ | - | **P5: 제거** |

### 4-2. thead HTML 변경

```html
<!-- 기존 -->
<tr style="background:#f8fafc;">
    <th class="ps-3" style="width:110px">발주번호</th>
    <th style="width:95px">발주일</th>
    <th>거래처</th>
    <th style="width:75px">상태</th>
    <th style="width:110px" class="text-end">공급가액</th>
    <th style="width:100px" class="text-end">합계</th>
    <th style="width:55px">발송</th>
    <th style="width:50px"></th>
</tr>

<!-- 변경 후 (P1, P2, P5 적용) -->
<tr style="background:#f8fafc;">
    <th class="ps-3" style="width:110px">발주번호</th>
    <th style="width:90px">발주일</th>
    <th style="width:140px" class="po-col-project">현장</th>
    <th>거래처</th>
    <th style="width:75px">상태</th>
    <th style="width:100px" class="text-end">합계</th>
    <th style="width:55px">발송</th>
    <th style="width:50px"></th>
</tr>
```

### 4-3. tbody 행 — Jinja2 변경사항

```html
<!-- 변경 후: 현장명 컬럼 추가, 공급가액 td 제거 -->
<tr onclick="location.href='{{ url_for('purchase_order.po_detail', po_id=po.id) }}'">
    <td class="ps-3">
        <a href="{{ url_for('purchase_order.po_detail', po_id=po.id) }}" class="po-no-link">
            {{ po.po_no }}
        </a>
    </td>
    <td>{{ po.po_date.strftime('%Y-%m-%d') if po.po_date else '-' }}</td>
    <!-- P2: 현장명 — project 관계 활용 -->
    <td class="po-col-project text-truncate" style="max-width:140px;">
        {% if po.project %}
            <small class="text-muted">{{ po.project.temp_name or po.project.name or '-' }}</small>
        {% else %}
            <small class="text-muted">-</small>
        {% endif %}
    </td>
    <td><strong>{{ po.vendor.name if po.vendor else '-' }}</strong></td>
    <td>
        {# 상태 배지 — 기존 유지 #}
        {% if po.status == '작성중' %}
            <span class="badge-status" style="background:#fef3c7;color:#92400e;">{{ po.status }}</span>
        {% elif po.status == '발송완료' %}
            <span class="badge-status" style="background:#dcfce7;color:#166534;">{{ po.status }}</span>
        {% elif po.status == '입고대기' %}
            <span class="badge-status" style="background:#dbeafe;color:#1e40af;">{{ po.status }}</span>
        {% elif po.status == '입고완료' %}
            <span class="badge-status" style="background:#e0e7ff;color:#3730a3;">{{ po.status }}</span>
        {% else %}
            <span class="badge-status" style="background:#f1f5f9;color:#64748b;">{{ po.status }}</span>
        {% endif %}
    </td>
    <!-- P5: 공급가액 td 제거 → 합계만 -->
    <td class="text-end fw-bold" style="color:#0f172a;">
        {{ fmt_money((po.total_amount or 0) + (po.tax_amount or 0)) }}
    </td>
    <td>
        {% if po.email_sent_at %}
            <small class="text-success fw-bold">{{ po.email_sent_at.strftime('%m/%d') }}</small>
        {% else %}
            <small class="text-muted">-</small>
        {% endif %}
    </td>
    <td>
        {% if po.status in ('발송완료', '입고대기') %}
        <a href="{{ url_for('receiving.receiving_create', po_id=po.id) }}"
           class="btn btn-success btn-xs"
           style="white-space:nowrap;"
           onclick="event.stopPropagation();">입고</a>
        {% endif %}
    </td>
</tr>
```

### 4-4. P3/P4: 거래처 그룹핑 토글 — 설계 구조

**핵심 원칙**: 서버 렌더링된 행을 JS가 재정렬/그룹 헤더 삽입. 페이지네이션과 충돌하지 않도록 현재 페이지 내에서만 동작.

#### 토글 버튼 HTML (filter-bar 우측에 추가)

```html
<!-- filter-bar 내부 row에 추가 -->
<div class="col-auto ms-auto">
    <div class="btn-group btn-group-sm" id="groupToggle" role="group" aria-label="정렬 방식">
        <button type="button" class="btn btn-outline-secondary active" id="btnGroupByVendor"
                data-group="vendor" title="거래처별 그룹">
            <!-- 아이콘: 그룹 -->
            <svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">
                <path d="M1 2.5A1.5 1.5 0 0 1 2.5 1h3A1.5 1.5 0 0 1 7 2.5v3A1.5 1.5 0 0 1 5.5 7h-3A1.5 1.5 0 0 1 1 5.5zm8 0A1.5 1.5 0 0 1 10.5 1h3A1.5 1.5 0 0 1 15 2.5v3A1.5 1.5 0 0 1 13.5 7h-3A1.5 1.5 0 0 1 9 5.5zm-8 8A1.5 1.5 0 0 1 2.5 9h3A1.5 1.5 0 0 1 7 10.5v3A1.5 1.5 0 0 1 5.5 15h-3A1.5 1.5 0 0 1 1 13.5zm8 0A1.5 1.5 0 0 1 10.5 9h3A1.5 1.5 0 0 1 15 10.5v3A1.5 1.5 0 0 1 13.5 15h-3A1.5 1.5 0 0 1 9 13.5z"/>
            </svg>
            거래처별
        </button>
        <button type="button" class="btn btn-outline-secondary" id="btnGroupByDate"
                data-group="date" title="날짜순 정렬">
            <svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">
                <path d="M4 .5a.5.5 0 0 0-1 0V1H2a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V3a2 2 0 0 0-2-2h-1V.5a.5.5 0 0 0-1 0V1H4zM1 4h14v10a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1zm2 3a.5.5 0 0 0 0 1h10a.5.5 0 0 0 0-1zm0 3a.5.5 0 0 0 0 1h10a.5.5 0 0 0 0-1z"/>
            </svg>
            날짜순
        </button>
    </div>
</div>
```

#### 거래처 그룹 헤더행 HTML 명세

```html
<!-- JS가 tbody 내에 동적 삽입하는 그룹 헤더행 -->
<!-- data-group-header 속성으로 식별 -->
<tr class="po-group-header" data-group-header data-vendor-name="{vendorName}">
    <td colspan="8" style="
        background: linear-gradient(135deg, #f1f5f9, #e8f0fe);
        border-top: 2px solid var(--mg-primary);
        border-bottom: 1px solid #bfdbfe;
        padding: 6px 12px;
        cursor: pointer;
    ">
        <div class="d-flex align-items-center justify-content-between">
            <div class="d-flex align-items-center gap-2">
                <!-- 접기/펼치기 chevron -->
                <svg class="po-group-chevron" width="14" height="14" fill="currentColor"
                     viewBox="0 0 16 16" style="transition:transform .2s;flex-shrink:0;">
                    <path fill-rule="evenodd" d="M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708"/>
                </svg>
                <span class="fw-bold" style="font-size:.82rem;color:var(--mg-primary);">
                    {vendorName}
                </span>
                <span class="badge rounded-pill" style="
                    background:#dbeafe;color:#1e40af;
                    font-size:.68rem;padding:2px 7px;">
                    {count}건
                </span>
            </div>
            <span class="fw-bold" style="font-size:.82rem;color:var(--mg-ink);">
                {groupTotal}원
            </span>
        </div>
    </td>
</tr>
```

### 4-5. P3/P4: 그룹핑 JS 로직 전체

```javascript
(function () {
    'use strict';

    /* ── 상수 ── */
    var COL_COUNT = 8;  /* thead 컬럼 수 — P1 변경 후 */
    var STORAGE_KEY = 'po_list_group_mode';  /* 사용자 설정 기억 */

    /* ── 요소 참조 ── */
    var tbody          = document.querySelector('.po-table tbody');
    var btnVendor      = document.getElementById('btnGroupByVendor');
    var btnDate        = document.getElementById('btnGroupByDate');

    if (!tbody || !btnVendor || !btnDate) return;

    /* ── 원본 행 데이터 수집 (서버 렌더링 시점) ── */
    /* 빈 행(colspan) 제외 */
    var originalRows = Array.from(tbody.querySelectorAll('tr:not([data-group-header])'))
        .filter(function (tr) { return !tr.querySelector('[colspan]'); });

    /* 각 행에서 메타데이터 추출 */
    var rowMeta = originalRows.map(function (tr) {
        var dateCell   = tr.cells[1];
        var vendorCell = tr.cells[3];  /* P1 변경 후: 현장(2), 거래처(3) */
        var totalCell  = tr.cells[5];  /* 합계 셀 */

        /* 합계 금액 파싱 (쉼표 제거 + 원 제거) */
        var totalText  = totalCell ? totalCell.textContent.trim().replace(/[,원]/g, '') : '0';
        var totalNum   = parseInt(totalText, 10) || 0;

        return {
            tr:         tr,
            vendorName: vendorCell ? vendorCell.textContent.trim() : '',
            dateText:   dateCell   ? dateCell.textContent.trim()   : '',
            total:      totalNum
        };
    });

    /* ── 현재 모드 상태 ── */
    var currentMode = localStorage.getItem(STORAGE_KEY) || 'vendor';

    /* ── 모드 적용 ── */
    function applyMode(mode) {
        currentMode = mode;
        localStorage.setItem(STORAGE_KEY, mode);

        /* 버튼 active 상태 */
        btnVendor.classList.toggle('active', mode === 'vendor');
        btnDate.classList.toggle('active', mode === 'date');

        /* tbody 재구성 */
        if (mode === 'vendor') {
            renderGrouped();
        } else {
            renderFlat();
        }
    }

    /* ── 날짜순(flat) 렌더 ── */
    function renderFlat() {
        /* 기존 그룹 헤더 제거 */
        removeGroupHeaders();

        /* 원본 순서 복원 (서버가 날짜 desc로 정렬함) */
        originalRows.forEach(function (tr) {
            tbody.appendChild(tr);
            tr.style.display = '';
        });
    }

    /* ── 거래처 그룹 렌더 ── */
    function renderGrouped() {
        removeGroupHeaders();

        /* 거래처별 그룹 구성 — 원본 순서 유지하며 연속 병합 */
        var groups = [];
        var lastVendor = null;
        rowMeta.forEach(function (meta) {
            if (meta.vendorName !== lastVendor) {
                groups.push({ vendorName: meta.vendorName, rows: [], total: 0 });
                lastVendor = meta.vendorName;
            }
            var g = groups[groups.length - 1];
            g.rows.push(meta);
            g.total += meta.total;
        });

        /* tbody 재구성 */
        tbody.innerHTML = '';
        groups.forEach(function (group) {
            /* 그룹 헤더행 */
            var headerTr = buildGroupHeader(group.vendorName, group.rows.length, group.total);
            tbody.appendChild(headerTr);

            /* 데이터 행 */
            group.rows.forEach(function (meta) {
                tbody.appendChild(meta.tr);
                meta.tr.style.display = '';
            });
        });

        /* 접기/펼치기 이벤트 바인딩 */
        bindCollapseEvents();
    }

    /* ── 그룹 헤더 tr 생성 ── */
    function buildGroupHeader(vendorName, count, total) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-group-header', '');
        tr.setAttribute('data-vendor-name', vendorName);
        tr.dataset.collapsed = 'false';
        tr.style.cssText = 'cursor:pointer;user-select:none;';

        var formattedTotal = total > 0
            ? total.toLocaleString() + '원'
            : '-';

        tr.innerHTML = '<td colspan="' + COL_COUNT + '" style="'
            + 'background:linear-gradient(135deg,#f1f5f9,#e8f0fe);'
            + 'border-top:2px solid var(--mg-primary);'
            + 'border-bottom:1px solid #bfdbfe;'
            + 'padding:6px 12px;">'
            + '<div class="d-flex align-items-center justify-content-between">'
            + '<div class="d-flex align-items-center gap-2">'
            + '<svg class="po-group-chevron" width="14" height="14" fill="currentColor" '
            +      'viewBox="0 0 16 16" style="transition:transform .2s;flex-shrink:0;">'
            + '<path fill-rule="evenodd" d="M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708"/>'
            + '</svg>'
            + '<span class="fw-bold" style="font-size:.82rem;color:var(--mg-primary);">'
            + escHtml(vendorName) + '</span>'
            + '<span class="badge rounded-pill" style="background:#dbeafe;color:#1e40af;font-size:.68rem;padding:2px 7px;white-space:nowrap;">'
            + count + '건</span>'
            + '</div>'
            + '<span class="fw-bold" style="font-size:.82rem;color:#0f172a;">'
            + formattedTotal + '</span>'
            + '</div>'
            + '</td>';

        return tr;
    }

    /* ── 접기/펼치기 이벤트 바인딩 ── */
    function bindCollapseEvents() {
        tbody.querySelectorAll('[data-group-header]').forEach(function (headerTr) {
            headerTr.addEventListener('click', function () {
                var isCollapsed = headerTr.dataset.collapsed === 'true';
                var nextTr = headerTr.nextElementSibling;
                var chevron = headerTr.querySelector('.po-group-chevron');

                /* 다음 형제 tr들 중 그룹 행들을 토글 */
                while (nextTr && !nextTr.hasAttribute('data-group-header')) {
                    nextTr.style.display = isCollapsed ? '' : 'none';
                    nextTr = nextTr.nextElementSibling;
                }

                headerTr.dataset.collapsed = isCollapsed ? 'false' : 'true';

                /* chevron 회전 */
                if (chevron) {
                    chevron.style.transform = isCollapsed ? '' : 'rotate(-90deg)';
                }
            });
        });
    }

    /* ── 기존 그룹 헤더 제거 ── */
    function removeGroupHeaders() {
        tbody.querySelectorAll('[data-group-header]').forEach(function (tr) {
            tr.remove();
        });
    }

    /* ── XSS 방지 ── */
    function escHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ── 버튼 이벤트 ── */
    btnVendor.addEventListener('click', function () { applyMode('vendor'); });
    btnDate.addEventListener('click',   function () { applyMode('date');   });

    /* ── 초기 적용 ── */
    applyMode(currentMode);
})();
```

### 4-6. CSS 추가 (po_list.html style 블록)

```css
/* P3/P4: 그룹핑 관련 추가 스타일 */

/* 그룹 헤더행 hover */
.po-table tbody tr[data-group-header]:hover td {
    background: linear-gradient(135deg, #e8f0fe, #dbeafe) !important;
}

/* 그룹 헤더행은 클릭 이벤트만 — row-click 비활성 */
.po-table tbody tr[data-group-header] {
    cursor: pointer;
}

/* 토글 버튼 그룹 */
#groupToggle .btn {
    font-size: .75rem;
    padding: 3px 8px;
    white-space: nowrap;
}
#groupToggle .btn.active {
    background: var(--mg-primary);
    border-color: var(--mg-primary);
    color: #fff;
}
#groupToggle .btn:not(.active) {
    color: var(--mg-muted);
}

/* P2: 현장명 컬럼 */
.po-col-project {
    color: var(--mg-muted);
    font-size: .78rem;
}

/* 모바일: 현장 컬럼 숨김 (스크롤보다 컬럼 제거 우선) */
@media (max-width: 767.98px) {
    .po-col-project { display: none; }
    /* thead의 현장 th도 숨김 */
    .po-table thead th.po-col-project { display: none; }
    /* 그룹핑 토글은 필터바 아래 별도 행으로 */
    #groupToggle { width: 100%; }
    #groupToggle .btn { flex: 1; }
}
```

---

## 5. 접근성 (WCAG 2.1 AA)

| 항목 | 적용 방법 |
|------|-----------|
| 체크박스 레이블 | `aria-label="{{ r.bom_item.item_name }} 선택"` |
| 전체선택 | `aria-label="전체 선택"` + `indeterminate` 시 `aria-checked="mixed"` |
| 버튼 disabled | `disabled` 속성 (aria 자동 처리) |
| 그룹 헤더 접기 | `aria-expanded="true/false"` 동적 설정 |
| 색상만 의존 금지 | 선택 행: 배경색 + 좌측 border (두 가지 시각 단서) |
| 포커스 가시성 | Bootstrap 5.3 기본 focus-ring 유지 |

```javascript
/* bindCollapseEvents 내에 aria 업데이트 추가 */
headerTr.setAttribute('aria-expanded', isCollapsed ? 'true' : 'false');
```

---

## 6. 구현 순서 (Do 단계)

### Step 1 — bom_requirement.html (30분)
1. `<style>` 블록에 CSS 추가 (3-5절)
2. 카드 헤더 HTML 교체 (3-2절)
3. `checkAll` th 교체 (3-3절)
4. 체크박스 `form-check-input` 클래스 추가 (3-4절)
5. `<script>` 블록 전체 교체 (3-6절)
6. 테이블에 `req-table` 클래스 추가
7. 모바일 숨김 컬럼 클래스 추가 (th, td)

### Step 2 — po_list.html (45분)
1. `<style>` 블록에 CSS 추가 (4-6절)
2. thead 변경 — 현장 컬럼 삽입, 공급가액 제거 (4-2절)
3. tbody Jinja2 행 변경 — 현장 td 추가, 공급가액 td 제거 (4-3절)
4. filter-bar에 토글 버튼 추가 (4-4절)
5. `<script>` 블록 추가 (4-5절)

### Step 3 — 라우트 확인
- `bom_requirement.html`: 데이터 변경 없음
- `po_list.html`: `po.project` 관계가 eager load 되어 있는지 확인
  - `routes/po.py` 또는 해당 라우트에서 `joinedload(PurchaseOrder.project)` 필요할 수 있음

---

## 7. 체크리스트

### bom_requirement.html
- [ ] R1: 부족량 > 0인 행만 체크박스 (기존 유지)
- [ ] R2: 전체선택 indeterminate 지원
- [ ] R3: 선택 건수 배지 + 버튼 disabled/enabled
- [ ] R4: 선택 행 하이라이트 (배경색 + 좌측 bar)
- [ ] R4: 행 클릭으로 토글
- [ ] R5: 모달 거래처별 소계 강조 행
- [ ] R5: 다거래처 합산 총합계 행
- [ ] XSS: escHtml 적용
- [ ] 모바일: 숨김 컬럼 처리

### po_list.html
- [ ] P1: 컬럼 순서 발주번호|발주일|현장|거래처|상태|합계|발송|액션
- [ ] P2: 현장명 표시 (po.project.temp_name)
- [ ] P3: 거래처 연속 그룹 + 헤더행 삽입
- [ ] P4: 토글 버튼 (기본: 거래처별, localStorage 기억)
- [ ] P4: 그룹 접기/펼치기
- [ ] P5: 공급가액 컬럼 제거
- [ ] colspan 수 COL_COUNT=8 맞춤 확인
- [ ] 빈 테이블(colspan) 행 처리
- [ ] 모바일: 현장 컬럼 숨김, 토글 버튼 full-width
