# Design: mobile-responsive

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 전체 모바일 반응형 최적화 |
| 작성일 | 2026-03-23 |
| 범위 | 116 템플릿, 14 CSS 파일 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 116개 템플릿 중 GREEN 2개, YELLOW 16개, RED 42개 — 테이블 overflow + 폼 깨짐 |
| **Solution** | magnatech.css ~120줄 추가로 전체 60~70% 자동 개선 + mobile-table.js 자동 data-label 활용 |
| **Function UX Effect** | 375px~768px 뷰포트에서 모든 업무 페이지 조회·입력 가능 |
| **Core Value** | `mobile-table.js` 자동 처리 덕분에 대부분 CSS-only 변경 → 데스크톱 깨짐 위험 최소 |

### Key Discovery
> **`mobile-table.js`가 이미 모든 테이블에 `mobile-stack-table` + `data-label`을 자동 주입하고 있음.**
> 따라서 HTML 변경은 거의 불필요. 핵심은 CSS 보강 + overflow-x 버그 수정.

**Scope**: 116 templates, 14 CSS files, Flask + Jinja2 + Bootstrap 5.3

---

## 1. Current State Analysis

### What Works (16 templates)
- `mobile-table.js` auto-adds `mobile-stack-table` class to all `.table` inside `.main-content`
- `mobile-table.js` auto-hydrates `data-label` from `<thead>` text -- **no manual HTML changes needed for basic tables**
- `no-stack-table` class opts out of stacking (BOM tables, report tables, receiving tables)
- Sidebar mobile toggle at 991px breakpoint
- Chatbot panel goes bottom-sheet at 767px

### What is Broken
1. **`overflow-x: visible !important`** at `@media (max-width: 1199.98px)` on `.table-responsive` -- kills horizontal scroll for `no-stack-table` tables
2. **55 templates have tables** but only ~16 have `mobile-stack-table` explicitly -- however `mobile-table.js` auto-adds it, so the real gap is: filter bars, detail page layouts, form pages, and dashboard grids
3. **`#timelinePanel`** hardcoded 380px width, no responsive rules
4. **KPI cards** use fixed `col-4` grid, text overflows on small screens
5. **Filter bars** don't collapse on mobile -- form controls stack but without touch-friendly spacing
6. **Page hero** buttons overflow on narrow screens

### Breakpoint Strategy (existing, keep as-is)

| Breakpoint | Target | Role |
|------------|--------|------|
| 1199.98px | Tablets landscape | Stack tables, reduce column widths |
| 991.98px | Tablets portrait | Hide sidebar, full-width main |
| 767.98px | Phones landscape | Larger touch targets, simpler grids |
| 575.98px | Phones portrait | Single column everything |

---

## 2. Section A: Global CSS Changes (magnatech.css)

### A1. Fix `overflow-x: visible !important` Scoping

**Problem**: At `max-width: 1199.98px`, ALL `.table-responsive` get `overflow-x: visible`, which breaks horizontal scroll for `no-stack-table` tables.

**Fix**: Scope the override to only `.table-responsive` that contains a `.mobile-stack-table`.

```css
/* BEFORE (broken) */
@media (max-width: 1199.98px) {
    .main-content .table-responsive {
        overflow-x: visible !important;
    }
}

/* AFTER (fixed) */
@media (max-width: 1199.98px) {
    .main-content .table-responsive:has(.mobile-stack-table) {
        overflow-x: visible !important;
    }
    /* Explicit horizontal scroll guarantee for no-stack tables */
    .main-content .table-responsive:has(.no-stack-table) {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }
}
```

### A2. `.no-stack-table` Horizontal Scroll Guarantee

Add this new rule block at the bottom of the 1199px media query:

```css
@media (max-width: 1199.98px) {
    /* no-stack-table: always scroll, never stack */
    .main-content .no-stack-table {
        display: table !important;
    }
    .main-content .no-stack-table thead {
        display: table-header-group !important;
    }
    .main-content .no-stack-table tbody,
    .main-content .no-stack-table tr,
    .main-content .no-stack-table td {
        display: revert !important;
    }
    .main-content .no-stack-table td::before {
        content: none !important;
    }
}
```

### A3. Mobile Typography Scale

Add to the 767px media query:

```css
@media (max-width: 767.98px) {
    /* Typography scaling */
    .main-content h2 { font-size: 1.15rem; }
    .main-content h3 { font-size: 1rem; }
    .main-content h4 { font-size: .92rem; }
    .main-content .card-header { font-size: .82rem; }

    /* Touch targets: minimum 44px height */
    .main-content .btn {
        min-height: 38px;
        padding-top: .45rem;
        padding-bottom: .45rem;
    }
    .main-content .form-control,
    .main-content .form-select {
        min-height: 40px;
        font-size: .92rem;
    }

    /* Spacing reduction */
    .main-content .mb-4 { margin-bottom: .75rem !important; }
    .main-content .mb-3 { margin-bottom: .5rem !important; }
    .main-content .g-3, .main-content .gx-3 { --bs-gutter-x: .75rem; --bs-gutter-y: .75rem; }
}

@media (max-width: 575.98px) {
    .main-content h2 { font-size: 1.05rem; }

    /* KPI values shrink */
    .kpi-value { font-size: 1.2rem !important; }
    .kpi-label { font-size: .72rem !important; }

    /* Cards: minimal padding */
    .main-content .card-body {
        padding: .75rem !important;
    }
}
```

### A4. Page Hero Responsive

Add to the 767px media query:

```css
@media (max-width: 767.98px) {
    .page-hero {
        padding: 1rem 1.2rem;
        border-radius: .75rem;
    }
    .page-hero h2, .page-hero h3 {
        font-size: 1.1rem;
    }
    .page-hero .hero-sub {
        font-size: .72rem;
    }
    .page-hero .hero-eyebrow {
        font-size: .58rem;
    }
    /* Hero buttons: flex-wrap with full-width on very small */
    .page-hero .d-flex.gap-2,
    .page-hero .d-flex.flex-wrap {
        gap: .35rem !important;
    }
    .page-hero .btn {
        font-size: .7rem;
        padding: .25rem .5rem;
    }
}

@media (max-width: 575.98px) {
    .page-hero {
        padding: .85rem 1rem;
    }
    .page-hero h2, .page-hero h3 {
        font-size: 1rem;
    }
    .page-hero .d-flex.gap-2 > .btn,
    .page-hero .d-flex.flex-wrap > .btn,
    .page-hero .d-flex.flex-wrap > a.btn {
        flex: 1 1 auto;
        text-align: center;
    }
}
```

### A5. Filter Bar Collapse Pattern

New utility class for filter sections:

```css
/* ═══ Mobile Filter Bar ═══ */
.filter-bar-mobile {
    background: #f8fafc;
    border-radius: 10px;
    padding: 10px 14px;
}

@media (max-width: 767.98px) {
    .filter-bar-mobile {
        padding: 8px 10px;
    }
    .filter-bar-mobile .row {
        --bs-gutter-x: .5rem;
        --bs-gutter-y: .5rem;
    }
    .filter-bar-mobile label.small,
    .filter-bar-mobile .small.fw-bold {
        font-size: .72rem !important;
        margin-bottom: 2px !important;
    }
    .filter-bar-mobile .form-select,
    .filter-bar-mobile .form-control {
        font-size: .82rem;
        padding: .35rem .5rem;
    }

    /* Collapse filter behind toggle button on mobile */
    .filter-collapse-toggle {
        display: flex !important;
    }
    .filter-collapse-body {
        /* Bootstrap collapse handles visibility */
    }
}

@media (min-width: 768px) {
    .filter-collapse-toggle {
        display: none !important;
    }
    .filter-collapse-body {
        display: block !important;
        height: auto !important;
    }
}
```

**Usage in templates** (wrap existing filter forms):

```html
<!-- Add toggle button (hidden on desktop) -->
<button class="btn btn-outline-secondary btn-sm w-100 mb-2 filter-collapse-toggle"
        type="button" data-bs-toggle="collapse" data-bs-target="#filterBody">
    검색 필터 펼치기/접기
</button>
<div class="collapse show" id="filterBody">
    <form ...><!-- existing filter form --></form>
</div>
```

### A6. Mobile Actions Pattern (already exists, enhance)

```css
@media (max-width: 767.98px) {
    .mobile-actions {
        display: flex !important;
        flex-wrap: wrap;
        gap: .5rem;
        width: 100%;
    }
    .mobile-actions > .btn,
    .mobile-actions > a.btn,
    .mobile-actions > div > .btn {
        flex: 1 1 auto;
        text-align: center;
    }
}
```

---

## 3. Section B: mobile-stack-table Application Pattern

### B1. How `mobile-table.js` Works (auto-magic)

1. On page load, `markStackTables()` finds ALL `table.table` inside `.main-content`
2. If the table does NOT have `.no-stack-table`, it gets `.mobile-stack-table` added automatically
3. `hydrateMobileTableLabels()` reads `<thead th>` text and sets `data-label` on each `<td>`
4. If a `<td>` already has `data-label`, it is preserved (manual override)
5. `colspan > 1` cells get `mobile-full-row` class and empty `data-label`
6. Re-runs on collapse/modal/tab show events and window resize

### B2. What This Means for Implementation

**For most tables, NO HTML changes are needed.** The JS handles it automatically.

Exceptions requiring manual work:
- Tables where `<thead>` headers are icons or empty -- add `data-label` manually on `<td>`
- Tables with complex `rowspan`/`colspan` -- add `no-stack-table` class
- Tables inside forms with inline inputs -- may need `no-stack-table` to preserve layout
- Tables with action buttons that need full-width on mobile -- add `mobile-full-row` on that `<td>`

### B3. Template Modification Checklist (for applying to a new table)

```
[ ] 1. Check: Does the table already have class="table"?
       YES -> mobile-table.js will auto-apply mobile-stack-table. Done.
       NO -> Add class="table" or manually add class="mobile-stack-table"

[ ] 2. Check: Does <thead> have readable text in <th> elements?
       YES -> data-label auto-hydrated. Done.
       NO -> Add data-label="라벨" on each <td> manually

[ ] 3. Check: Does the table have editable inputs/selects?
       YES -> Add class="no-stack-table" and ensure parent has overflow-x:auto
       NO -> Continue

[ ] 4. Check: Is the table inside a card with table-responsive wrapper?
       YES -> overflow-x fix in A1 handles it. Done.
       NO -> Wrap in <div class="table-responsive">

[ ] 5. Check: Does any <td> have colspan?
       YES -> mobile-table.js handles it (adds mobile-full-row). Done.

[ ] 6. Check: Are there action buttons in the last column?
       Consider adding class="mobile-full-row" on that <td> for full-width actions
```

### B4. Opt-out Pattern

For tables that must NOT stack (BOM detail, weekly reports, input-heavy tables):

```html
<div class="table-responsive">
    <table class="table table-sm no-stack-table" style="min-width:900px;">
        ...
    </table>
</div>
```

---

## 4. Section C: Page-Type Patterns

### C1. List Pages (table with filters)

**Examples**: project_list, contract_list, sales_list, po_list, fo_list, warranty_list

**Pattern**: Hero > Filter bar > Stats cards (optional) > Table

```css
/* ═══ List Page Mobile Pattern ═══ */
@media (max-width: 767.98px) {
    /* Stat card rows: 2-column on mobile instead of 6 */
    .stat-cards-row .col-md-2 {
        flex: 0 0 50%;
        max-width: 50%;
    }
    .stat-cards-row .stat-num {
        font-size: 1.3rem;
    }

    /* Table card: remove border-radius, go edge-to-edge */
    .main-content > .card > .card-body.p-0 {
        padding: 0 !important;
    }

    /* Clickable row indicator on mobile */
    .main-content table.mobile-stack-table tbody tr[data-href]::after,
    .main-content table.mobile-stack-table tbody tr.clickable-row::after {
        content: '\203A';
        position: absolute;
        right: 10px;
        top: 10px;
        font-size: 1.2rem;
        color: #94a3b8;
    }
    .main-content table.mobile-stack-table tbody tr[data-href],
    .main-content table.mobile-stack-table tbody tr.clickable-row {
        position: relative;
        padding-right: 28px;
    }
}

@media (max-width: 575.98px) {
    .stat-cards-row .col-md-2 {
        flex: 0 0 33.333%;
        max-width: 33.333%;
    }
    .stat-cards-row .stat-num {
        font-size: 1.1rem;
    }
    .stat-cards-row .stat-label {
        font-size: .68rem;
    }
}
```

**Template pattern** (minimal changes needed):
```html
<!-- Filter: add collapse wrapper for mobile -->
<button class="btn btn-outline-secondary btn-sm w-100 mb-2 filter-collapse-toggle d-none"
        data-bs-toggle="collapse" data-bs-target="#filterBody">
    검색 필터
</button>
<form ... class="collapse show filter-collapse-body" id="filterBody">
    <!-- existing filter content unchanged -->
</form>
```

### C2. Detail Pages (info cards + sub-tables)

**Examples**: project_detail, contract_detail, po_detail, fo_detail, sales_detail

**Pattern**: Hero > Info cards (row) > Sub-sections with tables

```css
/* ═══ Detail Page Mobile Pattern ═══ */
@media (max-width: 767.98px) {
    /* Info cards: stack vertically */
    .main-content .row > .col-md-8,
    .main-content .row > .col-md-4 {
        /* Bootstrap handles this, but ensure no overflow */
        min-width: 0;
    }

    /* Info grid inside cards: 2-col on mobile */
    .info-card .row .col-md-3 {
        flex: 0 0 50%;
        max-width: 50%;
    }

    /* Label-value pairs */
    .info-label { font-size: .7rem; }
    .info-value { font-size: .85rem; }

    /* Amount cards: shrink totals */
    .amount-row.total .amount-val {
        font-size: 1.1rem;
    }
}

@media (max-width: 575.98px) {
    .info-card .row .col-md-3,
    .info-card .row .col-6 {
        flex: 0 0 100%;
        max-width: 100%;
    }
}
```

### C3. Form Pages (create/edit with item tables)

**Examples**: po_create, fo_create, bom_create, receiving_create, project_create

**Pattern**: Hero > Form sections > Item table (usually needs `no-stack-table`)

```css
/* ═══ Form Page Mobile Pattern ═══ */
@media (max-width: 767.98px) {
    /* Section cards */
    .po-section .card-body,
    .main-content form .card-body {
        padding: 12px !important;
    }

    /* Form labels */
    .po-label, .form-label {
        font-size: .78rem;
    }

    /* Item tables in forms: horizontal scroll, not stack */
    .main-content form .table-responsive {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        margin: 0 -12px;
        padding: 0 12px;
    }

    /* Add item button: full width */
    .btn-add-item {
        width: 100%;
    }

    /* Summary rows */
    .summary-total td {
        font-size: .88rem !important;
    }
}
```

**Key decision**: Item tables in forms should use `no-stack-table` because stacking an editable table with inputs creates a poor UX. Horizontal scroll is better here.

### C4. Dashboard Pages (cards + charts)

**Examples**: dashboard, financial_dashboard, inventory_dashboard

```css
/* ═══ Dashboard Mobile Pattern ═══ */
@media (max-width: 767.98px) {
    /* KPI row: 2-up or 3-up depending on count */
    .kpi-row-3 > .col-4 {
        /* Keep 3-up, shrink text */
    }
    .kpi-row-3 .kpi-value {
        font-size: 1.2rem;
    }

    /* Workflow pipeline board */
    .wf-board {
        grid-template-columns: 1fr !important;
    }

    /* Chart cards: full width */
    .chart-card { margin-bottom: .5rem; }
    .chart-card canvas {
        max-height: 220px !important;
    }

    /* Action tabs: horizontal scroll */
    .act-tabs {
        overflow-x: auto;
        flex-wrap: nowrap;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }
    .act-tabs::-webkit-scrollbar { display: none; }
    .act-tabs .nav-link {
        flex-shrink: 0;
    }

    /* Calendar: compact */
    .cal-cell { min-height: 36px; }
    .cal-day { font-size: .65rem; }

    /* Command center specific */
    .cmd-hero .nav-row {
        gap: .3rem;
    }
    .cmd-hero .nav-row .btn {
        font-size: .68rem;
        padding: .25rem .45rem;
    }
    .kpi-row {
        flex-wrap: wrap;
        gap: .25rem;
    }
    .kpi-chip {
        font-size: .65rem;
        padding: .15rem .4rem;
    }
}
```

---

## 5. Section D: Timeline Panel Responsive

### Current Problem

```html
<div id="timelinePanel" style="...width:380px;height:100vh;...">
```

Hardcoded 380px with no responsive handling.

### Fix: Add CSS media queries

Add to magnatech.css:

```css
/* ═══ Timeline Panel Responsive ═══ */
#timelinePanel {
    width: 380px;
    height: 100vh;
}

@media (max-width: 767.98px) {
    #timelinePanel {
        width: 100% !important;
        height: 85vh !important;
        top: auto !important;
        bottom: 0 !important;
        right: 0 !important;
        border-radius: 16px 16px 0 0;
        transform: translateY(100%) !important;
    }
    #timelinePanel[style*="translateX(0)"] {
        transform: translateY(0) !important;
    }
}
```

**Better approach**: Remove inline styles from base.html and use CSS classes.

Replace the inline-styled `#timelinePanel` in `base.html` with:

```html
<div id="timelinePanel" class="timeline-panel">
```

And add these CSS rules:

```css
.timeline-panel {
    display: none;
    position: fixed;
    top: 0;
    right: 0;
    width: 380px;
    height: 100vh;
    background: #fff;
    box-shadow: -4px 0 20px rgba(0,0,0,.12);
    z-index: 1060;
    overflow: hidden;
    transition: transform .25s;
    transform: translateX(100%);
}

@media (max-width: 767.98px) {
    .timeline-panel {
        width: 100%;
        height: 85vh;
        top: auto;
        bottom: 0;
        border-radius: 16px 16px 0 0;
        transform: translateY(100%);
    }
}
```

Update JS `openTimelinePanel()` and `closeTimelinePanel()` to detect mobile:

```javascript
function openTimelinePanel() {
    var panel = document.getElementById('timelinePanel');
    if (!panel) return;
    if (_tlOpen) { closeTimelinePanel(); return; }
    panel.style.display = 'block';
    document.getElementById('timelineBackdrop').style.display = 'block';
    requestAnimationFrame(function() {
        if (window.innerWidth <= 767.98) {
            panel.style.transform = 'translateY(0)';
        } else {
            panel.style.transform = 'translateX(0)';
        }
    });
    _tlOpen = true;
    loadPageTimeline(); loadLiveTimeline();
    _tlInterval = setInterval(loadLiveTimeline, 15000);
}

function closeTimelinePanel() {
    var panel = document.getElementById('timelinePanel');
    if (panel) {
        panel.style.transform = window.innerWidth <= 767.98
            ? 'translateY(100%)' : 'translateX(100%)';
    }
    var bd = document.getElementById('timelineBackdrop');
    if (bd) bd.style.display = 'none';
    setTimeout(function() { if (panel) panel.style.display = 'none'; }, 250);
    _tlOpen = false;
    if (_tlInterval) { clearInterval(_tlInterval); _tlInterval = null; }
}
```

---

## 6. Section E: Implementation Order

### Priority Matrix

| Priority | File | Type | Changes | Impact |
|----------|------|------|---------|--------|
| **P0** | `static/css/magnatech.css` | CSS | ~120 lines added | ALL pages benefit |
| **P0** | `templates/base.html` | HTML | ~15 lines | Timeline panel fix |
| **P1** | `static/css/dashboard.css` | CSS | ~30 lines | Dashboard (most visited) |
| **P1** | `templates/dashboard.html` | HTML | ~5 lines | KPI card grid fix |
| **P2** | `templates/contract_list.html` | HTML | ~8 lines | Filter collapse |
| **P2** | `templates/project_list.html` | HTML | ~8 lines | Filter collapse |
| **P2** | `templates/sales_list.html` | HTML | ~8 lines | Filter collapse |
| **P2** | `templates/delivery_management.html` | HTML | ~8 lines | Filter collapse |
| **P2** | `templates/production_management.html` | HTML | ~8 lines | Filter collapse |
| **P2** | `templates/material_management.html` | HTML | ~8 lines | Filter collapse |
| **P3** | `templates/po_detail.html` | HTML | ~5 lines | Info card grid |
| **P3** | `templates/fo_detail.html` | HTML | ~5 lines | Info card grid |
| **P3** | `templates/contract_detail.html` | HTML | ~5 lines | Info card grid |
| **P3** | `templates/financial_dashboard.html` | HTML+CSS | ~15 lines | KPI/chart layout |
| **P4** | 40+ remaining templates | HTML | ~3-5 lines each | Mostly auto-handled |

### Phase 1: Global Foundation (P0) -- 1 hour

**`static/css/magnatech.css`** -- ~120 lines added:
1. Fix `overflow-x: visible` scoping (Section A1)
2. Add `no-stack-table` guarantees (Section A2)
3. Add mobile typography + touch targets (Section A3)
4. Add page hero responsive (Section A4)
5. Add filter bar collapse utilities (Section A5)
6. Add timeline panel CSS (Section D)

**`templates/base.html`** -- ~15 lines changed:
1. Extract `#timelinePanel` inline styles to CSS class
2. Update JS functions for mobile direction

### Phase 2: High-Traffic Pages (P1-P2) -- 2 hours

**Dashboard**: Add responsive KPI chip wrapping, workflow grid collapse.

**6 List Pages**: Add filter collapse toggle buttons (8 lines each, identical pattern).

### Phase 3: Detail + Form Pages (P3) -- 2 hours

**Detail pages**: Mostly already work due to Bootstrap grid. Small fixes for info card grids.

**Form pages**: Verify `no-stack-table` on item tables, add horizontal scroll margin.

### Phase 4: Long Tail (P4) -- ongoing

Most remaining templates will "just work" after Phase 1 because:
- `mobile-table.js` auto-adds `mobile-stack-table` and `data-label`
- Global CSS changes apply to all `.main-content` tables
- Bootstrap grid responsive classes already handle most layout stacking

Templates that need individual attention:
- `inventory_dashboard.html` -- custom chart layout
- `production_display.html` -- TV display, skip mobile
- `report_weekly*.html` -- print-first, `no-stack-table`, skip mobile
- `illuminance_*.html` -- custom simulation UI

---

## 7. CSS Addition Summary (copy-paste ready)

Add the following to the END of `static/css/magnatech.css`, before the print styles:

```css
/* ═══ Mobile Responsive Enhancement (2026-03-23) ═══ */

/* --- A1: Fix overflow-x scoping --- */
/* (Replace the existing rule in the 1199px media query) */

/* --- A2: no-stack-table guarantee --- */
@media (max-width: 1199.98px) {
    .main-content .table-responsive:has(.no-stack-table) {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }
    .main-content .no-stack-table { display: table !important; }
    .main-content .no-stack-table thead { display: table-header-group !important; }
    .main-content .no-stack-table tbody,
    .main-content .no-stack-table tr,
    .main-content .no-stack-table td { display: revert !important; }
    .main-content .no-stack-table td::before { content: none !important; }
}

/* --- A4: Page hero responsive --- */
@media (max-width: 767.98px) {
    .page-hero { padding: 1rem 1.2rem; border-radius: .75rem; }
    .page-hero h2, .page-hero h3 { font-size: 1.1rem; }
    .page-hero .hero-sub { font-size: .72rem; }
    .page-hero .hero-eyebrow { font-size: .58rem; }
    .page-hero .btn { font-size: .7rem; padding: .25rem .5rem; }
}
@media (max-width: 575.98px) {
    .page-hero { padding: .85rem 1rem; }
    .page-hero h2, .page-hero h3 { font-size: 1rem; }
}

/* --- A3: Touch targets + typography --- */
@media (max-width: 767.98px) {
    .main-content h3 { font-size: 1rem; }
    .main-content h4 { font-size: .92rem; }
    .main-content .btn { min-height: 38px; }
    .main-content .form-control,
    .main-content .form-select { min-height: 40px; }
}
@media (max-width: 575.98px) {
    .main-content h2 { font-size: 1.05rem; }
    .main-content .card-body { padding: .75rem; }
    .kpi-value { font-size: 1.2rem !important; }
}

/* --- A5: Filter collapse toggle --- */
.filter-collapse-toggle { display: none; }
@media (max-width: 767.98px) {
    .filter-collapse-toggle { display: flex !important; align-items: center; justify-content: center; gap: 6px; }
}
@media (min-width: 768px) {
    .filter-collapse-body { display: block !important; height: auto !important; overflow: visible !important; }
}

/* --- Stat cards mobile --- */
@media (max-width: 767.98px) {
    .stat-cards-row .col-md-2 { flex: 0 0 33.333%; max-width: 33.333%; }
    .stat-cards-row .stat-num, .stat-num { font-size: 1.3rem; }
}

/* --- Detail info cards mobile --- */
@media (max-width: 575.98px) {
    .info-card .row .col-md-3 { flex: 0 0 50%; max-width: 50%; }
}

/* --- Mobile clickable row indicator --- */
@media (max-width: 1199.98px) {
    .main-content table.mobile-stack-table tbody tr.clickable-row {
        position: relative;
        cursor: pointer;
    }
}

/* --- Timeline panel --- */
.timeline-panel {
    display: none; position: fixed; top: 0; right: 0;
    width: 380px; height: 100vh; background: #fff;
    box-shadow: -4px 0 20px rgba(0,0,0,.12); z-index: 1060;
    overflow: hidden; transition: transform .25s; transform: translateX(100%);
}
@media (max-width: 767.98px) {
    .timeline-panel {
        width: 100%; height: 85vh; top: auto; bottom: 0;
        border-radius: 16px 16px 0 0; transform: translateY(100%);
    }
}
```

---

## 8. What NOT to Change

1. **`production_display.html`** -- TV wall display, desktop-only by design
2. **`report_weekly*.html`** -- Print-optimized, `no-stack-table` is correct
3. **`bom_detail.html`** / **`bom_create.html`** -- Complex editable tables, `no-stack-table` is correct
4. **`receiving_create.html`** -- Input-heavy, `no-stack-table` is correct
5. **`channel_chat.html`** -- Already has its own responsive design
6. **`login.html`** / **`force_change_password.html`** -- Simple centered forms, already responsive

---

## 9. Testing Checklist

After implementation, verify on Chrome DevTools responsive mode:

| Screen | Width | Key Checks |
|--------|-------|------------|
| iPad Landscape | 1024px | Tables stack, sidebar hidden |
| iPad Portrait | 768px | Filter collapse appears, touch targets |
| iPhone 14 | 390px | All content single-column, no horizontal overflow |
| iPhone SE | 375px | KPI cards readable, hero buttons wrap |
| Galaxy Fold | 280px | Nothing breaks (graceful degradation) |

For each page type, verify:
- [ ] No horizontal scrollbar on body (except inside `.table-responsive` with `.no-stack-table`)
- [ ] All buttons are tappable (44px minimum touch target)
- [ ] Stacked table cards show `data-label` text correctly
- [ ] Filter bar collapses/expands on mobile
- [ ] Page hero buttons don't overflow
- [ ] Timeline panel slides from bottom on mobile
- [ ] Chatbot panel is bottom-sheet on mobile (already works)

---

## 10. Template Inventory (Full Audit)

### Summary

| Category | Count | 설명 |
|----------|-------|------|
| **GREEN** | 2 | mobile-stack-table + data-label 완비 |
| **YELLOW** | 16 | 부분 대응 (MST 클래스만 or table-responsive만) |
| **RED** | 42 | 테이블 있으나 모바일 미대응 |
| **SKIP** | 56 | 테이블 없음 / 특수 목적 |
| **합계** | **116** | |

### GREEN (2) — 완전 대응
- `bom_list.html`, `bom_requirement.html`

### YELLOW (16) — 부분 대응
**MST 클래스 있으나 data-label 없음 (JS 자동 처리 예정):**
- `contract_detail.html`, `contract_list.html`, `delivery_management.html`
- `material_management.html`, `production_management.html`, `project_list.html`
- `sales_list.html`, `warranty_list.html`, `components/priority_section.html`
- `partials/admin_catalog.html`

**table-responsive만:**
- `admin_settings.html`, `tax_invoice_list.html`, `financial_dashboard.html`
- `certification_list.html`, `partials/admin_notices.html`, `components/contact_collapse_bar.html`

### RED (42) — 모바일 미대응 (주요)
**min-width 인라인 있는 테이블 (13개):**
- `procurement_list.html`, `sales_detail.html`, `warranty_case_create/detail.html`
- `po_list.html`, `receiving_list.html`, `warranty.html`, `illuminance_area.html`
- `material_detail.html`, `bom_detail.html`, `procurement_report.html`
- `production_detail.html`, `fo_list.html`, `receiving_create.html`

**테이블 있으나 스택 없음 (29개):**
- `inventory_*` (7개), `item_*` (4개), `po_create/detail.html`
- `fo_create/detail.html`, `project_detail/create.html`, `quotation_list.html`
- `receiving_detail.html`, `contract_create.html`, `bom_create/import.html`
- `vendor_list/detail.html`, `lux_calculator.html`, `illuminance_verification.html`
- `quotation_detail.html`, `tax_invoice_detail.html`

### SKIP (56) — 대상 외
- 테이블 없는 페이지: 로그인, 프로필, 채팅, 갤러리, 폼, 모달 등
- 특수 목적: `production_display.html` (TV), `report_weekly*.html` (인쇄)

### Phase별 대응 전략
| Phase | 대상 | 작업 | HTML 변경 필요 |
|-------|------|------|---------------|
| P0 | 전체 | magnatech.css 120줄 추가 + overflow-x 버그 수정 | **없음** |
| P1 | 대시보드 | dashboard.css 30줄 추가 | 최소 (~5줄) |
| P2 | 리스트 6개 | 필터 collapse 토글 버튼 추가 | 페이지당 ~8줄 |
| P3 | 상세/폼 | 그리드 미세 조정 | 페이지당 ~5줄 |
| P4 | 나머지 40+ | **mobile-table.js가 자동 처리** | **거의 없음** |
