# 입고예정 관리 — Design Spec (v2)

## 문서 정보

| 항목 | 내용 |
|------|------|
| 기능 | 입고예정 관리 — 발주건 전체 조회 + 입고예정일 인라인 편집 |
| 연관 Plan | `docs/01-plan/features/receiving-expected.plan.md` (v2) |
| 대상 파일 | `routes/receiving.py`, `templates/receiving_list.html`, `routes/dashboard.py`, `templates/dashboard.html` |
| 작성일 | 2026-03-20 |

---

## 1. 디자인 시스템 토큰 (기존 프로젝트 기준)

```
--mg-primary:  #2563eb
--mg-success:  #16a34a
--mg-warning:  #d97706
--mg-danger:   #dc2626
--mg-border:   #e2e8f0
--mg-radius:   .65rem
--mg-shadow:   0 2px 12px rgba(15,23,42,.06)
--mg-muted:    #64748b
--mg-subtle:   #94a3b8
```

### D-Day 뱃지 컬러 (기존 receiving_list.html 패턴 유지)

| 조건 | 배경 | 텍스트 | 의미 |
|------|------|--------|------|
| 미정 (null) | `#f1f5f9` | `#64748b` | 예정일 미입력 |
| dday < 0 (지연) | `#fee2e2` | `#dc2626` | 빨강 |
| dday == 0 (오늘) | `#fef3c7` | `#92400e` | 주황 |
| 0 < dday <= 7 | `#fefce8` | `#854d0e` | 노랑 |
| dday > 7 | `#dcfce7` | `#166534` | 초록 |

### 납기위험도 뱃지 (기존 패턴 유지)

| 상태 | 배경 | 텍스트 | 표시 |
|------|------|--------|------|
| danger | `#fee2e2` | `#dc2626` | 위험 |
| warning | `#fef3c7` | `#92400e` | 주의 |
| ok | `#dcfce7` | `#166534` | 정상 |
| none | - | `#94a3b8` | - |

---

## 2. routes/receiving.py — 쿼리 변경

### 2.1 기존 → 변경

```python
# ── 기존 (잘못됨): expected_in_date IS NOT NULL만 조회 ──
expected_qs = db.query(MaterialOrder).options(
    joinedload(MaterialOrder.project),
    joinedload(MaterialOrder.contract),
    joinedload(MaterialOrder.purchase_order).joinedload(PurchaseOrder.vendor),
).filter(
    MaterialOrder.order_status == '발주완료',
    MaterialOrder.in_confirmed == False,
    MaterialOrder.expected_in_date.isnot(None),  # ← 제거
).order_by(MaterialOrder.expected_in_date.asc()).all()
```

```python
# ── 변경: 발주완료 + 미입고 전체 (예정일 유무 관계없이) ──
from sqlalchemy import case

expected_qs = db.query(MaterialOrder).options(
    joinedload(MaterialOrder.project),
    joinedload(MaterialOrder.contract),
    joinedload(MaterialOrder.purchase_order).joinedload(PurchaseOrder.vendor),
).filter(
    MaterialOrder.order_status == '발주완료',
    MaterialOrder.in_confirmed == False,
).order_by(
    # 미정(NULL)을 맨 위에 → 예정일 입력 유도
    case(
        (MaterialOrder.expected_in_date.is_(None), 0),
        else_=1
    ).asc(),
    MaterialOrder.expected_in_date.asc(),
).all()
```

### 2.2 D-Day 및 속성 부착 (미정 처리 추가)

```python
for mo in expected_qs:
    if mo.expected_in_date:
        d = (mo.expected_in_date - today).days
        mo._dday = d
        mo._dday_state = (
            'overdue' if d < 0
            else 'today' if d == 0
            else 'week' if d <= 7
            else 'ok'
        )
    else:
        mo._dday = None
        mo._dday_state = 'unknown'  # ← 미정

    # 납기위험도 (기존 로직 유지, 미정이면 none)
    delivery_due = mo.contract.desired_delivery_date if mo.contract else None
    if delivery_due and mo.expected_in_date:
        margin = (delivery_due - mo.expected_in_date).days - production_lead_days
        mo._risk = 'danger' if margin < 0 else 'warning' if margin <= 7 else 'ok'
        mo._delivery_due = delivery_due
    else:
        mo._risk = 'none'
        mo._delivery_due = delivery_due  # 납품기일은 예정일 없어도 표시

    # 거래처명 (PO 경유)
    mo._vendor_name = (
        mo.purchase_order.vendor.name
        if mo.purchase_order and mo.purchase_order.vendor
        else ''
    )
```

### 2.3 통계 (unknown 추가)

```python
expected_stats = {
    'total': len(expected_qs),
    'overdue': sum(1 for mo in expected_qs if mo._dday_state == 'overdue'),
    'today': sum(1 for mo in expected_qs if mo._dday_state == 'today'),
    'this_week': sum(1 for mo in expected_qs if mo._dday_state == 'week'),
    'unknown': sum(1 for mo in expected_qs if mo._dday_state == 'unknown'),
}
```

---

## 3. 입고예정일 인라인 저장 API (신규)

### 3.1 엔드포인트

```
POST /api/receiving/update-expected-date/<int:mo_id>
Content-Type: application/json

Body: { "expected_in_date": "2026-04-01" }   → 날짜 설정
Body: { "expected_in_date": "" }              → null 설정 (미정으로 복귀)

Response 200: { "ok": true, "dday": 12, "dday_state": "ok" }
Response 404: { "ok": false, "message": "..." }
```

### 3.2 서버 로직

```python
@receiving_bp.route('/api/receiving/update-expected-date/<int:mo_id>', methods=['POST'])
@login_required
def api_update_expected_date(mo_id):
    import datetime as _dt
    from modules.history_board import append_history_log

    with get_db() as db:
        mo = db.query(MaterialOrder).get(mo_id)
        if not mo:
            return jsonify({'ok': False, 'message': '자재를 찾을 수 없습니다.'}), 404

        data = request.get_json(silent=True) or {}
        date_str = (data.get('expected_in_date') or '').strip()

        if date_str:
            try:
                new_date = _dt.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'ok': False, 'message': '날짜 형식 오류'}), 400
            mo.expected_in_date = new_date
        else:
            mo.expected_in_date = None

        append_history_log(
            db,
            project_id=mo.project_id,
            user_name=session.get('full_name', '시스템'),
            content=f"입고예정일 변경: {mo.material_name} → {date_str or '미정'}",
            scope='material',
            kind='system'
        )
        db.commit()

        # 응답에 D-Day 계산 결과 포함 (프론트에서 뱃지 즉시 갱신용)
        today = _dt.date.today()
        if mo.expected_in_date:
            d = (mo.expected_in_date - today).days
            dday_state = 'overdue' if d < 0 else 'today' if d == 0 else 'week' if d <= 7 else 'ok'
        else:
            d = None
            dday_state = 'unknown'

        return jsonify({'ok': True, 'dday': d, 'dday_state': dday_state})
```

---

## 4. receiving_list.html — 입고예정 탭 테이블 변경

### 4.1 필터 바 변경 (unknown 추가)

기존 btn-group 필터에 "미정" 버튼 추가:

```html
<div class="btn-group btn-group-sm" id="expectedFilterGroup">
    <button type="button" class="btn btn-outline-secondary active"
            data-filter="all" style="white-space:nowrap;">
        전체 <span class="badge bg-secondary ms-1" id="cnt-all">0</span>
    </button>
    <button type="button" class="btn btn-outline-secondary"
            data-filter="unknown" style="white-space:nowrap;">
        미정 <span class="badge ms-1" style="background:#f1f5f9;color:#64748b;" id="cnt-unknown">0</span>
    </button>
    <button type="button" class="btn btn-outline-danger"
            data-filter="overdue" style="white-space:nowrap;">
        지연 <span class="badge ms-1" style="background:#fee2e2;color:#dc2626;" id="cnt-overdue">0</span>
    </button>
    <button type="button" class="btn btn-outline-warning"
            data-filter="today" style="white-space:nowrap;">
        오늘 <span class="badge ms-1" style="background:#fef3c7;color:#92400e;" id="cnt-today">0</span>
    </button>
    <button type="button" class="btn btn-outline-success"
            data-filter="week" style="white-space:nowrap;">
        이번주 <span class="badge ms-1" style="background:#fefce8;color:#854d0e;" id="cnt-week">0</span>
    </button>
</div>
```

### 4.2 테이블 컬럼 정의

| # | 컬럼 | 너비 | 정렬 | 비고 |
|---|------|------|------|------|
| 1 | 현장 | 14% | left | `project.temp_name`, ellipsis |
| 2 | 거래처 | 90px | left | `#008000` 기존 패턴 |
| 3 | 자재명 | 20% | left | ellipsis + title |
| 4 | 수량 | 52px | right | |
| 5 | 발주일 | 72px | center | `mo.order_date` |
| 6 | 입고예정일 | 100px | center | **`<input type="date">` 인라인 편집** |
| 7 | D-Day | 62px | center | 뱃지, 미정="미정" |
| 8 | 납품기일 | 72px | center | `contract.desired_delivery_date` |
| 9 | 납기위험 | 56px | center | 뱃지 |
| 10 | 액션 | 62px | center | 입고확인 버튼 |

### 4.3 colgroup (기존 테이블 패턴 준수)

```html
<colgroup>
    <col style="width:14%">     <!-- 현장 -->
    <col style="width:90px">    <!-- 거래처 -->
    <col style="width:20%">     <!-- 자재명 -->
    <col style="width:52px">    <!-- 수량 -->
    <col style="width:72px">    <!-- 발주일 -->
    <col style="width:100px">   <!-- 입고예정일 (인라인 input) -->
    <col style="width:62px">    <!-- D-Day -->
    <col style="width:72px">    <!-- 납품기일 -->
    <col style="width:56px">    <!-- 납기위험 -->
    <col style="width:62px">    <!-- 액션 -->
</colgroup>
```

### 4.4 입고예정일 셀 — 인라인 date input

```html
{# 입고예정일 — 인라인 편집 #}
<td class="text-center" style="overflow:visible;">
    <input type="date"
           class="form-control form-control-sm input-expected-date"
           data-mo-id="{{ mo.id }}"
           value="{{ mo.expected_in_date.strftime('%Y-%m-%d') if mo.expected_in_date else '' }}"
           style="font-size:.72rem; padding:1px 4px; border:1px solid #e2e8f0;
                  border-radius:4px; width:100%; min-width:0;
                  background:transparent; text-align:center;">
</td>
```

> **기존 패턴 준수**: `base.html`에 `.table td:has(input) { overflow:visible; max-width:none; }` 이미 정의되어 있으므로, date input이 잘림 없이 표시됨.

### 4.5 D-Day 셀 (미정 처리 추가)

```html
{# D-Day #}
<td class="text-center" id="dday-{{ mo.id }}">
    {% if dday_state == 'unknown' %}
    <span style="display:inline-block; padding:1px 6px; border-radius:4px;
                 background:#f1f5f9; color:#64748b;
                 font-size:0.75rem; white-space:nowrap;">미정</span>
    {% elif dday_state == 'overdue' %}
    <span style="display:inline-block; padding:1px 6px; border-radius:4px;
                 background:#fee2e2; color:#dc2626;
                 font-size:0.75rem; font-weight:600; white-space:nowrap;">D+{{ dday|abs }}</span>
    {% elif dday_state == 'today' %}
    <span style="display:inline-block; padding:1px 6px; border-radius:4px;
                 background:#fef3c7; color:#92400e;
                 font-size:0.75rem; font-weight:600; white-space:nowrap;">D-Day</span>
    {% elif dday_state == 'week' %}
    <span style="display:inline-block; padding:1px 6px; border-radius:4px;
                 background:#fefce8; color:#854d0e;
                 font-size:0.75rem; font-weight:600; white-space:nowrap;">D-{{ dday }}</span>
    {% else %}
    <span style="display:inline-block; padding:1px 6px; border-radius:4px;
                 background:#dcfce7; color:#166534;
                 font-size:0.75rem; white-space:nowrap;">D-{{ dday }}</span>
    {% endif %}
</td>
```

### 4.6 입고예정일 AJAX 저장 + D-Day 즉시 갱신 JS

```javascript
/* ===================================================
   입고예정일 인라인 편집 AJAX
   =================================================== */
(function() {
    document.addEventListener('change', function(e) {
        var input = e.target.closest('.input-expected-date');
        if (!input) return;

        var moId = input.dataset.moId;
        var val = input.value;  // 'YYYY-MM-DD' or ''

        fetch('/api/receiving/update-expected-date/' + moId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ expected_in_date: val })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.ok) {
                alert(data.message || '저장 실패');
                return;
            }
            // D-Day 뱃지 즉시 갱신
            var ddayTd = document.getElementById('dday-' + moId);
            if (!ddayTd) return;
            ddayTd.innerHTML = buildDDayBadge(data.dday, data.dday_state);

            // data-dday-state 갱신 (필터링용)
            var row = input.closest('tr');
            if (row) row.dataset.ddayState = data.dday_state;

            // 필터 건수 갱신
            updateExpectedCounts();

            // 저장 피드백: 인풋 테두리 깜빡임
            input.style.borderColor = '#16a34a';
            setTimeout(function() { input.style.borderColor = '#e2e8f0'; }, 800);
        })
        .catch(function() {
            alert('네트워크 오류');
        });
    });

    function buildDDayBadge(dday, state) {
        var styles = {
            unknown: 'background:#f1f5f9;color:#64748b;',
            overdue: 'background:#fee2e2;color:#dc2626;font-weight:600;',
            today:   'background:#fef3c7;color:#92400e;font-weight:600;',
            week:    'background:#fefce8;color:#854d0e;font-weight:600;',
            ok:      'background:#dcfce7;color:#166534;'
        };
        var base = 'display:inline-block;padding:1px 6px;border-radius:4px;font-size:0.75rem;white-space:nowrap;';
        var text = state === 'unknown' ? '미정'
                 : state === 'overdue' ? 'D+' + Math.abs(dday)
                 : state === 'today'   ? 'D-Day'
                 : 'D-' + dday;
        return '<span style="' + base + (styles[state] || '') + '">' + text + '</span>';
    }
})();
```

### 4.7 필터 JS 수정 (unknown 추가)

```javascript
/* ===================================================
   입고예정 클라이언트사이드 필터 (unknown 추가)
   =================================================== */
(function() {
    var filterGroup = document.getElementById('expectedFilterGroup');
    if (!filterGroup) return;

    function getRows() {
        return Array.from(document.querySelectorAll('.expected-row'));
    }

    function countByState(rows, state) {
        if (state === 'all') return rows.length;
        return rows.filter(function(r){ return r.dataset.ddayState === state; }).length;
    }

    window.updateExpectedCounts = function() {
        var rows = getRows();
        var el;
        el = document.getElementById('cnt-all');     if(el) el.textContent = rows.length;
        el = document.getElementById('cnt-unknown');  if(el) el.textContent = countByState(rows, 'unknown');
        el = document.getElementById('cnt-overdue');  if(el) el.textContent = countByState(rows, 'overdue');
        el = document.getElementById('cnt-today');    if(el) el.textContent = countByState(rows, 'today');
        el = document.getElementById('cnt-week');     if(el) el.textContent = countByState(rows, 'week');
    };

    function applyFilter(state) {
        getRows().forEach(function(r) {
            r.style.display = (state === 'all' || r.dataset.ddayState === state) ? '' : 'none';
        });
        filterGroup.querySelectorAll('button').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.filter === state);
        });
    }

    filterGroup.addEventListener('click', function(e) {
        var btn = e.target.closest('button[data-filter]');
        if (!btn) return;
        applyFilter(btn.dataset.filter);
    });

    updateExpectedCounts();
})();
```

---

## 5. dashboard.py — dash_expected 변경

### 5.1 unknown 칩 추가

```python
# ── 기존 ──
_base_expected = db.query(MaterialOrder).filter(
    MaterialOrder.order_status == '발주완료',
    MaterialOrder.in_confirmed.is_(False),
)
dash_expected = {
    'overdue': _base_expected.filter(
        MaterialOrder.expected_in_date.isnot(None),
        MaterialOrder.expected_in_date < today,
    ).count(),
    'today': _base_expected.filter(MaterialOrder.expected_in_date == today).count(),
    'this_week': _base_expected.filter(
        MaterialOrder.expected_in_date >= today,
        MaterialOrder.expected_in_date <= week_later,
    ).count(),
    'unknown': _base_expected.filter(MaterialOrder.expected_in_date.is_(None)).count(),
}
```

---

## 6. dashboard.html — 입고예정 카드 변경

기존 카드의 칩 그룹에 "미정" 칩 추가:

```html
{# 통계 칩 그룹 #}
<div style="display:flex;gap:.4rem;align-items:center;flex-shrink:0;flex-wrap:nowrap;">
    {% if dash_expected.overdue > 0 %}
    <span style="display:inline-flex;align-items:center;
                 background:#fee2e2;color:#dc2626;
                 font-size:.7rem;font-weight:700;
                 padding:.15rem .45rem;border-radius:.35rem;white-space:nowrap;">
        지연 {{ dash_expected.overdue }}
    </span>
    {% endif %}
    <span style="display:inline-flex;align-items:center;
                 {% if dash_expected.today > 0 %}background:#fef3c7;color:#d97706;
                 {% else %}background:#f1f5f9;color:#64748b;{% endif %}
                 font-size:.7rem;font-weight:700;
                 padding:.15rem .45rem;border-radius:.35rem;white-space:nowrap;">
        오늘 {{ dash_expected.today }}
    </span>
    <span style="display:inline-flex;align-items:center;
                 background:#eff6ff;color:#2563eb;
                 font-size:.7rem;font-weight:700;
                 padding:.15rem .45rem;border-radius:.35rem;white-space:nowrap;">
        이번주 {{ dash_expected.this_week }}
    </span>
    {% if dash_expected.unknown > 0 %}
    <span style="display:inline-flex;align-items:center;
                 background:#f1f5f9;color:#64748b;
                 font-size:.7rem;font-weight:700;
                 padding:.15rem .45rem;border-radius:.35rem;white-space:nowrap;">
        미정 {{ dash_expected.unknown }}
    </span>
    {% endif %}
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
         stroke="#94a3b8" stroke-width="2.5" stroke-linecap="round">
        <path d="M5 12h14M12 5l7 7-7 7"/>
    </svg>
</div>
```

---

## 7. 파일별 변경 요약

| 파일 | 변경 내용 |
|------|-----------|
| `routes/receiving.py` | 쿼리: `expected_in_date IS NOT NULL` 필터 제거 + NULL 먼저 정렬. `api_update_expected_date` 엔드포인트 신규 |
| `templates/receiving_list.html` | 필터에 "미정" 버튼 추가. 테이블에 "발주일" 컬럼 추가, "입고예정일" 셀을 `<input type="date">` 인라인 편집으로 변경. D-Day 미정 뱃지 추가. 예정일 변경 AJAX + D-Day 즉시 갱신 JS |
| `routes/dashboard.py` | `_base_expected` 필터에서 `expected_in_date.isnot(None)` 제거. `unknown` 통계 추가 |
| `templates/dashboard.html` | 입고예정 카드 칩 그룹에 "미정 N" 칩 추가 |

---

## 8. 구현 순서 (Do 단계)

1. `routes/receiving.py` — 쿼리 수정 (NULL 포함 + NULL 먼저 정렬)
2. `routes/receiving.py` — `api_update_expected_date` 엔드포인트 추가
3. `templates/receiving_list.html` — 테이블 변경 (인라인 date input + 미정 뱃지 + 발주일 컬럼)
4. `templates/receiving_list.html` — JS 변경 (인라인 저장 AJAX + 필터 unknown)
5. `routes/dashboard.py` — dash_expected unknown 추가
6. `templates/dashboard.html` — 미정 칩 추가

---

## 9. 디자인 일관성 체크리스트

- [x] `white-space: nowrap` — 모든 뱃지/버튼에 적용
- [x] `table-layout: fixed` + `colgroup` — 기존 테이블 패턴 유지
- [x] `overflow:hidden; text-overflow:ellipsis` — 텍스트 셀 기본
- [x] `font-size: 0.8rem` — 테이블 폰트 크기 통일
- [x] thead `background:#f0f0f0; border-bottom:2px solid #999` — 기존 패턴
- [x] D-Day 뱃지 `display:inline-block; padding:1px 6px; border-radius:4px; font-size:0.75rem` — 기존 패턴 그대로
- [x] 거래처명 `color:#008000; font-weight:600` — 기존 패턴
- [x] btn-group 필터 `btn-outline-{color} btn-sm` — 기존 패턴
- [x] date input `form-control-sm` + `overflow:visible` — base.html 기존 td:has(input) 규칙 활용
- [x] AJAX fetch 패턴 — `X-Requested-With: XMLHttpRequest` 기존 패턴
- [x] 저장 피드백 — 테두리 색상 변경 (초록→원래) 800ms
