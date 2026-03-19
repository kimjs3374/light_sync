# Production Display Design

> Plan Reference: `docs/01-plan/features/production-display.plan.md`

## 1. File Change Map

| # | Action | File | Purpose |
|---|--------|------|---------|
| 1 | NEW | `modules/production_display_utils.py` | 디스플레이 카드 데이터 빌더 + 자재 티커 빌더 |
| 2 | EDIT | `routes/production.py` | `production_display()` 뷰 함수 추가 |
| 3 | NEW | `templates/production_display.html` | 전용 디스플레이 템플릿 (다크 테마, 사이드바 없음) |

총 신규 2개, 수정 1개 — 최소 범위 구현.

## 2. Data Builder (`modules/production_display_utils.py`)

### 2.1 `build_display_cards(contracted_projects, today) -> dict[str, list]`

ContractItem 기반으로 4개 컬럼 카드 리스트 생성.

```python
def build_display_cards(contracted_projects, today):
    """
    Returns:
        {
            'material_waiting': [card, ...],  # status_prod == '자재대기중'
            'production_ready': [card, ...],  # status_prod == '생산대기중'
            'in_production': [card, ...],     # status_prod == '생산중'
            'completed': [card, ...],         # status_prod == '생산완료' (최근 7일)
        }
    """
```

**카드 1장 데이터 구조:**

```python
card = {
    # 기본 정보
    'project_id': int,
    'contract_item_id': int,
    'project_name': str,         # project.short_name or project.temp_name
    'project_no': str,
    'category': str,             # ContractItem.category
    'model_name': str,           # ContractItem.model_name
    'quantity': int,             # ContractItem.quantity
    'dday': int | None,          # days_until(delivery_due_date, today)
    'is_urgent': bool,           # project.is_urgent or contract.is_urgent_prod
    'is_priority': bool,         # ProjectPriorityOverride 존재 여부
    'detail_url': str,           # url_for('production.production_detail', ...)

    # 자재 정보
    'material_total': int,       # len(item.material_orders)
    'material_ready': int,       # count where order_status in ('입고완료', '재고이용')
    'material_percent': int,     # round(material_ready / material_total * 100)
    'missing_materials': [       # order_status not in ('입고완료', '재고이용')
        {
            'name': str,             # material_name
            'status': str,           # order_status ('발주대기', '발주완료')
            'expected_date': str,    # expected_in_date.strftime('%m/%d') or None
            'is_outsourcing': bool,
            'outsourcing_status': str | None,
        }
    ],

    # 공정 정보 (생산중 컬럼용)
    'current_process': str | None,   # status=='진행중'인 공정의 process_name
    'process_percent': int,          # 전체 공정 평균 진행률
    'next_process': str | None,      # current 다음 step_order 공정의 process_name
    'completed_at': str | None,      # 마지막 공정 completed_at (완료 컬럼용)
}
```

**정렬 규칙 (각 컬럼 내):**

| 순위 | 기준 | 방향 |
|------|------|------|
| 1 | `is_priority` (수동 최우선) | True 먼저 |
| 2 | `is_urgent` (긴급 플래그) | True 먼저 |
| 3 | `dday` (납기까지 남은 일수) | 오름차순 (임박순) |
| 4 | `project_id` | 오름차순 (안정 정렬) |

**완료 컬럼 필터:** `생산완료` 중 최근 7일 이내 완료된 것만 표시 (마지막 공정의 `completed_at` 기준). 7일 초과는 미표시.

### 2.2 `build_material_ticker(db, today) -> list[dict]`

향후 7일 내 입고 예정 자재 목록 (하단 티커용).

```python
def build_material_ticker(db, today):
    """
    Query: MaterialOrder WHERE
        expected_in_date BETWEEN today AND today+7
        AND order_status NOT IN ('입고완료', '재고이용')
    JOIN: PurchaseOrder -> Vendor (거래처명)
    JOIN: ContractItem -> Contract -> Project (현장명)
    ORDER BY: expected_in_date ASC, id ASC

    Returns: [
        {
            'expected_date': str,       # '%m/%d(%a)'
            'material_name': str,
            'quantity': int,
            'vendor_name': str,         # po.vendor.name or '미지정'
            'project_name': str,        # project.short_name
            'is_outsourcing': bool,
        }
    ]
    """
```

## 3. Route (`routes/production.py`)

### 3.1 `GET /production/display`

```python
@production_bp.route('/production/display')
@login_required
def production_display():
    with get_db() as db:
        today = datetime.date.today()

        contracted_projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(True))
            .options(
                joinedload(Project.contracts)
                    .joinedload(Contract.items)
                    .joinedload(ContractItem.material_orders),
                joinedload(Project.contracts)
                    .joinedload(Contract.items)
                    .joinedload(ContractItem.production_processes),
                joinedload(Project.priority_override),
            )
            .all()
        )

        cards = build_display_cards(contracted_projects, today)
        ticker = build_material_ticker(db, today)

        return render_template(
            'production_display.html',
            today=today,
            cards=cards,
            ticker=ticker,
            column_meta=[
                {'key': 'material_waiting', 'label': '자재대기', 'icon': '📦', 'tone': 'amber'},
                {'key': 'production_ready', 'label': '생산대기', 'icon': '⏳', 'tone': 'blue'},
                {'key': 'in_production', 'label': '생산중', 'icon': '🔧', 'tone': 'green'},
                {'key': 'completed', 'label': '완료', 'icon': '✅', 'tone': 'slate'},
            ],
        )
```

## 4. Template (`templates/production_display.html`)

### 4.1 HTML 구조

base.html을 extends하지 **않음** — 사이드바 없는 전체화면 전용 레이아웃.

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">  <!-- 30초 자동 갱신 -->
    <title>Light-Sync 생산현황판</title>
    <link href="bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="pd-body">
    <!-- 헤더 -->
    <header class="pd-header">...</header>

    <!-- 4컬럼 칸반 보드 -->
    <main class="pd-board">
        {% for col in column_meta %}
        <section class="pd-column pd-tone-{{ col.tone }}">
            <div class="pd-column-head">
                <span>{{ col.icon }} {{ col.label }}</span>
                <span class="pd-column-count">{{ cards[col.key]|length }}</span>
            </div>
            <div class="pd-column-body">
                {% for card in cards[col.key] %}
                <div class="pd-card {% if card.is_urgent %}pd-urgent{% endif %} {% if card.is_priority %}pd-priority{% endif %}">
                    ...
                </div>
                {% endfor %}
            </div>
        </section>
        {% endfor %}
    </main>

    <!-- 하단 자재 입고 예정 티커 -->
    <footer class="pd-ticker">...</footer>
</body>
</html>
```

### 4.2 카드 내부 — 컬럼별 차이

#### 자재대기 카드
```html
<div class="pd-card-header">
    {% if card.is_priority %}★{% endif %}
    {{ card.project_name }}
    {% if card.dday is not none %}
    <span class="pd-dday pd-dday-{{ 'red' if card.dday <= 3 else 'yellow' if card.dday <= 7 else 'blue' }}">
        D{% if card.dday < 0 %}+{{ -card.dday }}{% elif card.dday == 0 %}-Day{% else %}-{{ card.dday }}{% endif %}
    </span>
    {% endif %}
</div>
<div class="pd-card-item">{{ card.category }} {{ card.model_name }} x{{ card.quantity }}</div>
<div class="pd-material-bar">
    <div class="pd-bar-track">
        <div class="pd-bar-fill" style="width:{{ card.material_percent }}%"></div>
    </div>
    <span>{{ card.material_ready }}/{{ card.material_total }}</span>
</div>
<!-- 미입고 품목 리스트 (최대 3개) -->
{% for m in card.missing_materials[:3] %}
<div class="pd-missing">
    {% if m.is_outsourcing %}<span class="pd-badge-outsource">외주</span>{% endif %}
    {{ m.name }}
    {% if m.status == '발주대기' %}<span class="pd-badge-danger">미발주</span>
    {% else %}<span class="pd-badge-muted">{{ m.expected_date or '미정' }}</span>{% endif %}
</div>
{% endfor %}
```

#### 생산대기 카드
```html
<div class="pd-card-header">★/긴급 + 현장명 + D-Day</div>
<div class="pd-card-item">품목 x수량</div>
<div class="pd-material-ok">자재 {{ card.material_total }}/{{ card.material_total }} ✅</div>
<div class="pd-ready-rank">투입 우선순위 #{{ loop.index }}</div>
```

#### 생산중 카드
```html
<div class="pd-card-header">현장명 + D-Day</div>
<div class="pd-card-item">품목 x수량</div>
<div class="pd-process-current">현재: {{ card.current_process }}</div>
<div class="pd-process-bar">
    <div class="pd-bar-track">
        <div class="pd-bar-fill pd-fill-green" style="width:{{ card.process_percent }}%"></div>
    </div>
    <span>{{ card.process_percent }}%</span>
</div>
<div class="pd-process-next">다음: {{ card.next_process or '없음' }}</div>
```

#### 완료 카드
```html
<div class="pd-card-header pd-muted">{{ card.project_name }}</div>
<div class="pd-card-item">{{ card.category }} {{ card.model_name }} x{{ card.quantity }}</div>
<div class="pd-completed-date">{{ card.completed_at }} 완료</div>
```

### 4.3 하단 자재 입고 예정 티커

```html
<footer class="pd-ticker">
    <span class="pd-ticker-label">📦 자재 입고 예정</span>
    <div class="pd-ticker-track">
        <div class="pd-ticker-scroll">
            {% for m in ticker %}
            <span class="pd-ticker-item">
                {{ m.expected_date }} {{ m.material_name }} {{ m.quantity }}EA
                ({{ m.vendor_name }}→{{ m.project_name }})
                {% if m.is_outsourcing %}<span class="pd-badge-outsource">외주</span>{% endif %}
            </span>
            {% endfor %}
            {% if not ticker %}
            <span class="pd-ticker-item">7일 내 입고 예정 자재가 없습니다.</span>
            {% endif %}
        </div>
    </div>
</footer>
```

CSS 애니메이션으로 좌→우 무한 롤링 (기존 dashboard.html의 `tickerRoll` 키프레임 재활용).

### 4.4 다크 테마 CSS 핵심

```css
.pd-body {
    background: #0f172a;
    color: #f1f5f9;
    font-family: 'Pretendard', -apple-system, sans-serif;
    margin: 0;
    overflow: hidden;       /* TV 전체화면용 */
    height: 100vh;
    display: flex;
    flex-direction: column;
}

.pd-header {
    padding: .6rem 1.2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #1e293b;
    flex-shrink: 0;
}

.pd-board {
    flex: 1;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: .8rem;
    padding: .8rem;
    overflow: hidden;
}

.pd-column {
    display: flex;
    flex-direction: column;
    background: #1e293b;
    border-radius: 16px;
    overflow: hidden;
}

.pd-column-head {
    padding: .7rem .9rem;
    font-size: 1.1rem;
    font-weight: 800;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 3px solid;
    flex-shrink: 0;
}

/* 컬럼별 톤 */
.pd-tone-amber .pd-column-head { border-color: #f59e0b; color: #fbbf24; }
.pd-tone-blue .pd-column-head { border-color: #3b82f6; color: #60a5fa; }
.pd-tone-green .pd-column-head { border-color: #22c55e; color: #4ade80; }
.pd-tone-slate .pd-column-head { border-color: #64748b; color: #94a3b8; }

.pd-column-body {
    flex: 1;
    overflow-y: auto;
    padding: .6rem;
    display: flex;
    flex-direction: column;
    gap: .6rem;
}

.pd-card {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: .7rem .8rem;
}

.pd-card.pd-urgent {
    border-color: #ef4444;
    box-shadow: 0 0 0 1px rgba(239,68,68,.3);
}

.pd-card.pd-priority {
    border-color: #f59e0b;
    background: linear-gradient(180deg, #1a1a2e 0%, #0f172a 100%);
}

/* 프로그레스 바 */
.pd-bar-track {
    height: 6px;
    background: #334155;
    border-radius: 3px;
    overflow: hidden;
    flex: 1;
}

.pd-bar-fill {
    height: 100%;
    border-radius: 3px;
    background: #f59e0b;   /* 자재대기 기본 amber */
    transition: width .3s;
}

.pd-fill-green { background: #22c55e; }

/* 폰트 크기 — TV 3m 가독성 */
.pd-card-header { font-size: 1rem; font-weight: 800; }
.pd-card-item { font-size: .85rem; color: #94a3b8; }
.pd-dday { font-size: .75rem; font-weight: 800; padding: .15rem .4rem; border-radius: 6px; }
.pd-dday-red { background: #ef4444; color: #fff; }
.pd-dday-yellow { background: #f59e0b; color: #0f172a; }
.pd-dday-blue { background: #3b82f6; color: #fff; }

/* 미입고 품목 */
.pd-missing { font-size: .75rem; color: #cbd5e1; padding: .15rem 0; }
.pd-badge-danger { background: #dc2626; color: #fff; font-size: .65rem; padding: .1rem .3rem; border-radius: 4px; }
.pd-badge-outsource { background: #7c3aed; color: #fff; font-size: .65rem; padding: .1rem .3rem; border-radius: 4px; }
.pd-badge-muted { color: #64748b; font-size: .7rem; }

/* 티커 */
.pd-ticker {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: .8rem;
    padding: .5rem 1rem;
    background: linear-gradient(90deg, #1e293b, #0f172a);
    border-top: 1px solid #334155;
    overflow: hidden;
}

.pd-ticker-label {
    font-weight: 800;
    font-size: .85rem;
    white-space: nowrap;
    flex-shrink: 0;
}

.pd-ticker-track {
    flex: 1;
    overflow: hidden;
    position: relative;
}

.pd-ticker-scroll {
    display: inline-flex;
    gap: 3rem;
    white-space: nowrap;
    animation: tickerRoll 30s linear infinite;
    padding-left: 100%;
}

.pd-ticker-item {
    font-size: .8rem;
    color: #cbd5e1;
}

@keyframes tickerRoll {
    0% { transform: translateX(0); }
    100% { transform: translateX(-100%); }
}

/* 카드 overflow 시 컬럼 스크롤 — 스크롤바 숨김 (TV용) */
.pd-column-body::-webkit-scrollbar { display: none; }
.pd-column-body { scrollbar-width: none; }
```

### 4.5 자동 갱신

**방법 1 (Simple)**: `<meta http-equiv="refresh" content="30">` — 전체 페이지 리프레시. TV용이라 충분.

**방법 2 (향후 개선)**: JS fetch로 `/production/display?json=1` 호출 → partial DOM update. 깜빡임 방지.

초기 구현은 방법 1 채택. 충분히 검증 후 방법 2로 업그레이드 가능.

## 5. Implementation Order

| Step | File | Description | Est. Lines |
|------|------|-------------|------------|
| 1 | `modules/production_display_utils.py` | `build_display_cards()` + `build_material_ticker()` | ~120 |
| 2 | `routes/production.py` | `production_display()` 뷰 함수 추가 | ~40 |
| 3 | `templates/production_display.html` | 전체 HTML + CSS + 티커 | ~350 |

총 예상: ~510줄 (신규 2파일 + 기존 1파일 수정)

## 6. Edge Cases

| Case | Handling |
|------|----------|
| 자재가 0개인 ContractItem | material_total=0, material_percent=100 (자재 불필요 → 바로 생산대기) |
| 공정이 생성 안 된 생산대기 | current_process=None, process_percent=0, "공정 미생성" 표시 |
| 카드가 컬럼당 10개 초과 | CSS overflow-y:auto로 스크롤. TV에서는 상위 카드가 중요하므로 정렬이 핵심 |
| 납기일 미지정 | dday=None, D-Day 뱃지 미표시, 정렬에서 후순위 |
| 완료 후 7일 경과 | 완료 컬럼에서 자동 제외 (조건: completed_at >= today - 7일) |
| 외주 자재 | `pd-badge-outsource` 뱃지로 시각 구분 + outsourcing_status 표시 |
