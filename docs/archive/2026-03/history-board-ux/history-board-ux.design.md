# history-board-ux Design Document

> **Summary**: 통합히스토리보드 offcanvas 전환 + 연락처 접히는 바 + 매그나텍 업무 프로세스 히스토리 연동 (검수/대금/설계)
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead (PDCA)
> **Date**: 2026-03-19
> **Status**: Approved
> **Planning Doc**: [history-board-ux.plan.md](../01-plan/features/history-board-ux.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 히스토리보드를 인라인에서 offcanvas 슬라이드 패널로 전환 (A: 완료)
2. production_detail은 기존 prodInfoPanel 탭에 통합, 나머지는 독립 offcanvas (A: 완료)
3. 상단 한줄 바로 최근 로그 요약 + 뱃지 + 펄스 알림 (A: 완료)
4. technical scope 숨김, reply 카운트 수정 (A: 완료)
5. 연락처를 접히는 한줄 바(collapse bar)로 전환, 본문 col-12 확장 (B: 완료)
6. 납품 검수 이벤트 → delivery scope 히스토리 자동 기록 (C: 신규)
7. 대금 이벤트(청구/입금) → contract scope 히스토리 자동 기록 (C: 신규)
8. 설계 시방서 반영 확인 → design scope 히스토리 자동 기록 (C: 신규)

### 1.2 Design Principles

- 기존 history_board.html 컴포넌트 재사용 (offcanvas body에 include)
- 최소 변경 원칙: history_board.py append/build 함수 시그니처 유지
- Bootstrap 5 offcanvas 네이티브 활용

---

## 2. Architecture

### 2.1 Component Structure

```
변경 전:
┌─────────────────────────────────────────┐
│ detail page                             │
│ ┌──────────────┐ ┌────────────────────┐ │
│ │ col-md-8     │ │ col-md-4           │ │
│ │ 본문 콘텐츠    │ │ history_board.html │ │
│ └──────────────┘ └────────────────────┘ │
└─────────────────────────────────────────┘

변경 후:
┌─────────────────────────────────────────┐
│ detail page                             │
│ ┌─────────────── 한줄바 ──────────────┐ │
│ │ 최근: "xxx" | 전체 N건 [열기]       │ │
│ └────────────────────────────────────┘ │
│ ┌────────────────────────────────────┐ │
│ │ col-12 본문 콘텐츠 (전체폭)          │ │
│ └────────────────────────────────────┘ │
│                    ┌───────────────────┐│
│                    │ offcanvas-end     ││
│                    │ history_board.html││
│                    │ (슬라이드 패널)     ││
│                    └───────────────────┘│
└─────────────────────────────────────────┘
```

### 2.2 파일 변경 목록

| File | Action | Description |
|------|--------|-------------|
| `templates/components/history_board.html` | Modify | technical 탭 제거, drawing 유지 |
| `templates/components/history_summary_bar.html` | **New** | 상단 한줄 바 컴포넌트 |
| `templates/components/history_offcanvas.html` | **New** | 독립 offcanvas 래퍼 (history_board.html include) |
| `templates/production_detail.html` | Modify | col-4 히스토리 제거, prodInfoPanel에 히스토리 탭 추가, 한줄 바 추가 |
| `templates/project_detail.html` | Modify | col-4 히스토리 제거, 독립 offcanvas + 한줄 바 |
| `templates/contract_detail.html` | Modify | 인라인 히스토리 제거, 독립 offcanvas + 한줄 바 |
| `templates/sales_detail.html` | Modify | 인라인 히스토리 제거, 독립 offcanvas + 한줄 바 |
| `templates/material_detail.html` | Modify | 인라인 히스토리 제거, 독립 offcanvas + 한줄 바 |
| `templates/delivery_detail.html` | Modify | 인라인 히스토리 제거, 독립 offcanvas + 한줄 바 |
| `modules/history_board.py` | Modify | reply 카운트 수정 |

---

## 3. Component Specifications

### 3.1 history_summary_bar.html (새 컴포넌트)

상단 한줄 바. 최근 로그 1건 + 전체 건수 뱃지 표시.

**Jinja2 변수:**
- `history` - 히스토리 로그 리스트
- `history_counts` - 카운트 dict
- `history_panel_target` - 오픈할 offcanvas ID (예: `#historyOffcanvas`)

**HTML 구조:**
```html
<div class="history-summary-bar" id="historySummaryBar">
  <div class="d-flex align-items-center gap-2">
    <span class="badge bg-dark">히스토리</span>
    <span class="text-truncate small">{{ 최근로그.content }}</span>
    <span class="badge bg-secondary ms-auto">{{ history_counts.all }}건</span>
    <button class="btn btn-sm btn-outline-dark"
            data-bs-toggle="offcanvas"
            data-bs-target="{{ history_panel_target }}">열기</button>
  </div>
</div>
```

**CSS:**
- 한줄 고정, overflow: hidden, white-space: nowrap
- 새 로그 시 빨간 펄스: `@keyframes history-pulse { ... }`
- `.history-bar-pulse` 클래스 추가/제거로 제어

### 3.2 history_offcanvas.html (새 컴포넌트)

독립 offcanvas 래퍼. project/contract/sales/material/delivery에서 사용.

**Jinja2 변수:** 기존 history_board.html과 동일 + `history_offcanvas_id`

**HTML 구조:**
```html
<div class="offcanvas offcanvas-end" tabindex="-1"
     id="{{ history_offcanvas_id }}"
     style="width:min(520px, 100vw);">
  <div class="offcanvas-header border-bottom">
    <h5 class="offcanvas-title fw-bold">{{ history_board_title }}</h5>
    <button class="btn-close" data-bs-dismiss="offcanvas"></button>
  </div>
  <div class="offcanvas-body p-2">
    {% include 'components/history_board.html' %}
  </div>
</div>
```

### 3.3 production_detail.html 변경

prodInfoPanel 기존 탭(요약/협의/계약/원문)에 "히스토리" 탭 추가:

```html
<li class="nav-item" role="presentation">
  <button class="nav-link" data-bs-toggle="tab"
          data-bs-target="#prod-tab-history" type="button" role="tab">
    히스토리 <span class="badge bg-secondary">{{ history_counts.all }}</span>
  </button>
</li>
```

탭 콘텐츠:
```html
<div class="tab-pane fade" id="prod-tab-history" role="tabpanel">
  {% include 'components/history_board.html' %}
</div>
```

한줄 바의 열기 버튼은 prodInfoPanel을 열고 히스토리 탭을 활성화.

### 3.4 build_history_view 수정 (reply 카운트)

현재 문제: `for log in top_logs` 루프에서만 counts를 세므로, reply(parent_log_id가 있는 로그)가 counts.all에 포함되지 않음.

수정: reply도 counts.all에 포함시키고, comments count에도 reply kind가 comment인 경우 포함.

```python
# 변경: 전체 로그 대상으로 카운트 (reply 포함)
for log in history_rows:  # top_logs 대신 history_rows 전체
    counts['all'] += 1
    if log.log_kind == 'comment' or log.log_kind == 'reply':
        counts['comments'] += 1
    else:
        scope = log.log_scope if log.log_scope in VALID_SCOPES_SET else default_scope
        counts.setdefault(scope, 0)
        counts[scope] += 1
```

### 3.5 technical scope 숨김

`history_board.html`에서 technical 탭 버튼을 제거(또는 `d-none`).
VALID_SCOPES에서는 유지 (기존 데이터 호환).

---

## 4. Implementation Order

1. [ ] `modules/history_board.py` - reply 카운트 수정
2. [ ] `templates/components/history_board.html` - technical 탭 숨김
3. [ ] `templates/components/history_summary_bar.html` - 한줄 바 컴포넌트 생성
4. [ ] `templates/components/history_offcanvas.html` - 독립 offcanvas 래퍼 생성
5. [ ] `templates/production_detail.html` - col-4 제거, prodInfoPanel 히스토리 탭 추가, 한줄 바 추가
6. [ ] `templates/project_detail.html` - 인라인 제거, offcanvas + 한줄 바
7. [ ] `templates/contract_detail.html` - 인라인 제거, offcanvas + 한줄 바
8. [ ] `templates/sales_detail.html` - 인라인 제거, offcanvas + 한줄 바
9. [ ] `templates/material_detail.html` - 인라인 제거, offcanvas + 한줄 바
10. [ ] `templates/delivery_detail.html` - 인라인 제거, offcanvas + 한줄 바

---

## 5. CSS Design

### 5.1 한줄 바 스타일

```css
.history-summary-bar {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: .45rem .75rem;
    cursor: pointer;
}
.history-summary-bar:hover { background: #f1f5f9; }
.history-bar-pulse {
    animation: history-pulse 1.5s ease-in-out 3;
}
@keyframes history-pulse {
    0%, 100% { border-color: #e2e8f0; }
    50% { border-color: #ef4444; box-shadow: 0 0 8px rgba(239,68,68,.3); }
}
```

### 5.2 offcanvas 사이즈

- 독립 offcanvas: `width: min(520px, 100vw)`
- production prodInfoPanel: 기존 `min(560px, 100vw)` 유지

---

## 6. Section C: 매그나텍 업무 프로세스 히스토리 연동 (FR-10, FR-11, FR-12)

> 매그나텍 관급자재 업무 프로세스 9단계 중 PHASE 7(납품검수), PHASE 8(대금), PHASE 2-3(설계) 이벤트를 히스토리에 자동 기록하는 설계.
> Section A/B는 구현 완료 상태이므로 이 섹션은 C만 다룬다.

### 6.1 데이터 모델 변경

#### 6.1.1 Delivery 모델 확장 (FR-10: 납품 검수)

`modules/models/entities.py` - Delivery 클래스에 컬럼 추가:

```python
# 검수 관련 필드 (매그나텍 PHASE 7)
inspection_status = Column(String(20), default='미검수')    # 미검수/합격/불합격/보완
inspection_date = Column(Date, nullable=True)                # 검수일
inspection_note = Column(Text, nullable=True)                # 검수 비고 (체크리스트 결과 등)
```

**inspection_status 상태값:**

| 값 | 설명 | 다음 가능 상태 |
|----|------|----------------|
| 미검수 | 초기값 (납품 전/후 검수 미진행) | 합격, 불합격, 보완 |
| 합격 | 검수 통과 | - (최종) |
| 불합격 | 검수 실패 | 보완 |
| 보완 | 보완 조치 중 | 합격, 불합격 |

#### 6.1.2 Contract 모델 확장 (FR-11: 대금)

`modules/models/entities.py` - Contract 클래스에 컬럼 추가:

```python
# 대금 관련 필드 (매그나텍 PHASE 8)
payment_status = Column(String(20), default='미청구')       # 미청구/청구완료/입금완료
invoice_date = Column(Date, nullable=True)                   # 세금계산서 발행일
payment_date = Column(Date, nullable=True)                   # 대금 입금확인일
```

**payment_status 상태값:**

| 값 | 설명 | 다음 가능 상태 |
|----|------|----------------|
| 미청구 | 초기값 | 청구완료 |
| 청구완료 | 세금계산서 발행 완료 | 입금완료 |
| 입금완료 | 대금 수령 확인 | - (최종) |

#### 6.1.3 Project 모델 확장 (FR-12: 설계 시방서)

`modules/models/entities.py` - Project 클래스에 컬럼 추가:

```python
# 설계 시방서 반영 확인 (매그나텍 PHASE 2-3)
spec_confirmed = Column(Boolean, default=False)              # 시방서 반영 확인 여부
spec_confirmed_date = Column(Date, nullable=True)            # 시방서 반영 확인일
```

### 6.2 DB 마이그레이션

#### 6.2.1 PostgreSQL 마이그레이션 (db.py)

`modules/models/db.py` - `init_db()` 내 PostgreSQL 마이그레이션 블록에 추가:

```python
# deliveries: 검수 관련 컬럼 추가 (v2026-03-19, 매그나텍 PHASE 7)
for col, col_type in [
    ('inspection_status', "VARCHAR(20) DEFAULT '미검수'"),
    ('inspection_date', 'DATE'),
    ('inspection_note', 'TEXT'),
]:
    try:
        conn.execute(text(
            f"ALTER TABLE {quote_ident(DB_SCHEMA)}.deliveries "
            f"ADD COLUMN {col} {col_type}"
        ))
    except Exception:
        pass  # 이미 존재하면 무시

# contracts: 대금 관련 컬럼 추가 (v2026-03-19, 매그나텍 PHASE 8)
for col, col_type in [
    ('payment_status', "VARCHAR(20) DEFAULT '미청구'"),
    ('invoice_date', 'DATE'),
    ('payment_date', 'DATE'),
]:
    try:
        conn.execute(text(
            f"ALTER TABLE {quote_ident(DB_SCHEMA)}.contracts "
            f"ADD COLUMN {col} {col_type}"
        ))
    except Exception:
        pass

# projects: 시방서 반영 확인 컬럼 추가 (v2026-03-19, 매그나텍 PHASE 2-3)
for col, col_type in [
    ('spec_confirmed', 'BOOLEAN DEFAULT FALSE'),
    ('spec_confirmed_date', 'DATE'),
]:
    try:
        conn.execute(text(
            f"ALTER TABLE {quote_ident(DB_SCHEMA)}.projects "
            f"ADD COLUMN {col} {col_type}"
        ))
    except Exception:
        pass
```

### 6.3 백엔드 구현

#### 6.3.1 FR-10: 검수 이벤트 핸들러 (delivery_actions.py)

`modules/services/delivery_actions.py`에 `handle_update_inspection()` 추가:

```python
def handle_update_inspection(db, project, form, current_user, **ctx):
    """납품 검수 상태 업데이트 + 히스토리 자동 기록"""
    delivery_id = safe_int(form.get("delivery_id"))
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.project_id == project.id
    ).first()
    if not delivery:
        return {}

    old_status = delivery.inspection_status or '미검수'
    new_status = (form.get("inspection_status") or "").strip()
    if not new_status or new_status == old_status:
        return {}

    delivery.inspection_status = new_status
    delivery.inspection_date = parse_date(form.get("inspection_date"))
    delivery.inspection_note = (form.get("inspection_note") or "").strip() or None

    # 히스토리 자동 기록
    content = f"[검수] {old_status} → {new_status}"
    if delivery.inspection_note:
        content += f" | 비고: {delivery.inspection_note}"
    append_history_log(
        db,
        project_id=project.id,
        user_name="System",
        content=f"{current_user} {content}",
        scope="delivery",
        kind="system",
    )
    return {'flash': (f'검수 상태 변경: {new_status}', 'success')}
```

**ACTION_HANDLERS 등록** (`routes/delivery.py`):

```python
from modules.services.delivery_actions import handle_update_inspection

# ACTION_HANDLERS dict에 추가
ACTION_HANDLERS["update_inspection"] = handle_update_inspection
```

#### 6.3.2 FR-11: 대금 이벤트 핸들러 (project.py 또는 contract_actions.py)

`modules/services/contract_actions.py`에 `handle_update_payment()` 추가:

```python
def handle_update_payment(db, project, form, current_user, **ctx):
    """대금 상태 업데이트 + 히스토리 자동 기록"""
    contract_id = safe_int(form.get("contract_id"))
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.project_id == project.id
    ).first()
    if not contract:
        return {}

    old_status = contract.payment_status or '미청구'
    new_status = (form.get("payment_status") or "").strip()
    if not new_status or new_status == old_status:
        return {}

    contract.payment_status = new_status

    if new_status == '청구완료':
        contract.invoice_date = parse_date(form.get("invoice_date")) or datetime.date.today()
    elif new_status == '입금완료':
        contract.payment_date = parse_date(form.get("payment_date")) or datetime.date.today()

    # 히스토리 자동 기록
    content = f"[대금] {old_status} → {new_status}"
    if new_status == '청구완료' and contract.invoice_date:
        content += f" | 세금계산서 발행일: {contract.invoice_date}"
    elif new_status == '입금완료' and contract.payment_date:
        content += f" | 입금확인일: {contract.payment_date}"
    append_history_log(
        db,
        project_id=project.id,
        user_name="System",
        content=f"{current_user} {content}",
        scope="contract",
        kind="system",
    )
    return {'flash': (f'대금 상태 변경: {new_status}', 'success')}
```

**라우트 연동** (`routes/project.py` handle_detail_common 내):

contract_detail에서 POST action이 `update_payment`인 경우 위 핸들러 호출.

#### 6.3.3 FR-12: 시방서 반영 확인 핸들러 (project_actions.py)

`modules/services/project_actions.py`에 `handle_confirm_spec()` 추가:

```python
def handle_confirm_spec(db, project, form, current_user, **ctx):
    """시방서 반영 확인 체크 + 히스토리 자동 기록"""
    confirmed = form.get("spec_confirmed") == "on"
    project.spec_confirmed = confirmed
    project.spec_confirmed_date = datetime.date.today() if confirmed else None

    if confirmed:
        content = "시방서 반영 확인됨"
    else:
        content = "시방서 반영 확인 해제"

    append_history_log(
        db,
        project_id=project.id,
        user_name="System",
        content=f"{current_user} [설계] {content}",
        scope="design",
        kind="system",
    )
    return {'flash': (content, 'success')}
```

### 6.4 프론트엔드 UI

#### 6.4.1 FR-10: delivery_detail.html 검수 UI

`templates/delivery_detail.html`에 검수 섹션 추가 (납품 상세 카드 내부 또는 하단):

```html
<!-- 검수 결과 입력 (매그나텍 PHASE 7) -->
<div class="card mb-3">
  <div class="card-header d-flex align-items-center gap-2">
    <span class="fw-bold">검수 결과</span>
    {% if delivery.inspection_status == '합격' %}
      <span class="badge bg-success">합격</span>
    {% elif delivery.inspection_status == '불합격' %}
      <span class="badge bg-danger">불합격</span>
    {% elif delivery.inspection_status == '보완' %}
      <span class="badge bg-warning text-dark">보완</span>
    {% else %}
      <span class="badge bg-secondary">미검수</span>
    {% endif %}
  </div>
  <div class="card-body">
    <form method="post">
      <input type="hidden" name="action" value="update_inspection">
      <input type="hidden" name="delivery_id" value="{{ delivery.id }}">
      <div class="row g-2">
        <div class="col-auto">
          <select name="inspection_status" class="form-select form-select-sm">
            {% for st in ['미검수', '합격', '불합격', '보완'] %}
              <option value="{{ st }}" {{ 'selected' if delivery.inspection_status == st }}>{{ st }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-auto">
          <input type="date" name="inspection_date" class="form-control form-control-sm"
                 value="{{ delivery.inspection_date or '' }}">
        </div>
        <div class="col">
          <input type="text" name="inspection_note" class="form-control form-control-sm"
                 value="{{ delivery.inspection_note or '' }}" placeholder="검수 비고">
        </div>
        <div class="col-auto">
          <button type="submit" class="btn btn-sm btn-outline-primary" style="white-space:nowrap">저장</button>
        </div>
      </div>
    </form>
    <!-- 검수 체크리스트 참조 (접히는 영역) -->
    <details class="mt-2">
      <summary class="small text-muted">검수 체크리스트 참조</summary>
      <ul class="small mt-1 mb-0">
        <li>모델명/수량 일치 확인</li>
        <li>외관 손상 여부</li>
        <li>부속품 확인</li>
        <li>G2B 식별번호/인증마크 확인</li>
        <li>납품서류 (성적서, 시험성적서, 인증서) 확인</li>
      </ul>
    </details>
  </div>
</div>
```

#### 6.4.2 FR-11: contract_detail.html 대금 UI

`templates/contract_detail.html`에 대금 상태 섹션 추가 (계약 상세 카드 내부):

```html
<!-- 대금 상태 (매그나텍 PHASE 8) -->
<div class="card mb-3">
  <div class="card-header d-flex align-items-center gap-2">
    <span class="fw-bold">대금 상태</span>
    {% if contract.payment_status == '입금완료' %}
      <span class="badge bg-success">입금완료</span>
    {% elif contract.payment_status == '청구완료' %}
      <span class="badge bg-primary">청구완료</span>
    {% else %}
      <span class="badge bg-secondary">미청구</span>
    {% endif %}
  </div>
  <div class="card-body">
    <form method="post">
      <input type="hidden" name="action" value="update_payment">
      <input type="hidden" name="contract_id" value="{{ contract.id }}">
      <div class="row g-2">
        <div class="col-auto">
          <select name="payment_status" class="form-select form-select-sm">
            {% for st in ['미청구', '청구완료', '입금완료'] %}
              <option value="{{ st }}" {{ 'selected' if contract.payment_status == st }}>{{ st }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-auto">
          <label class="col-form-label col-form-label-sm">세금계산서 발행일</label>
        </div>
        <div class="col-auto">
          <input type="date" name="invoice_date" class="form-control form-control-sm"
                 value="{{ contract.invoice_date or '' }}">
        </div>
        <div class="col-auto">
          <label class="col-form-label col-form-label-sm">입금확인일</label>
        </div>
        <div class="col-auto">
          <input type="date" name="payment_date" class="form-control form-control-sm"
                 value="{{ contract.payment_date or '' }}">
        </div>
        <div class="col-auto">
          <button type="submit" class="btn btn-sm btn-outline-primary" style="white-space:nowrap">저장</button>
        </div>
      </div>
    </form>
  </div>
</div>
```

#### 6.4.3 FR-12: project_detail.html 시방서 반영 확인 UI

`templates/project_detail.html` 설계 기준 영역에 체크박스 추가:

```html
<!-- 시방서 반영 확인 (매그나텍 PHASE 2-3) -->
<form method="post" class="d-inline">
  <input type="hidden" name="action" value="confirm_spec">
  <div class="form-check form-check-inline">
    <input class="form-check-input" type="checkbox" name="spec_confirmed"
           id="specConfirmed" {{ 'checked' if project.spec_confirmed }}
           onchange="this.form.submit()">
    <label class="form-check-label small" for="specConfirmed">
      시방서 반영 확인
      {% if project.spec_confirmed_date %}
        <span class="text-muted">({{ project.spec_confirmed_date }})</span>
      {% endif %}
    </label>
  </div>
</form>
```

### 6.5 파일 변경 목록 (Section C 전체)

| File | Action | Description |
|------|--------|-------------|
| `modules/models/entities.py` | Modify | Delivery에 inspection 3컬럼, Contract에 payment 3컬럼, Project에 spec 2컬럼 추가 |
| `modules/models/db.py` | Modify | PostgreSQL ALTER TABLE 마이그레이션 추가 (8컬럼) |
| `modules/services/delivery_actions.py` | Modify | handle_update_inspection() 추가 |
| `modules/services/contract_actions.py` | Modify | handle_update_payment() 추가 |
| `modules/services/project_actions.py` | Modify | handle_confirm_spec() 추가 |
| `routes/delivery.py` | Modify | ACTION_HANDLERS에 update_inspection 등록 |
| `routes/project.py` | Modify | action 디스패치에 update_payment, confirm_spec 추가 |
| `templates/delivery_detail.html` | Modify | 검수 결과 입력 카드 + 체크리스트 참조 |
| `templates/contract_detail.html` | Modify | 대금 상태 카드 추가 |
| `templates/project_detail.html` | Modify | 시방서 반영 확인 체크박스 추가 |

### 6.6 구현 순서 (Section C)

1. [ ] `modules/models/entities.py` — Delivery/Contract/Project 모델에 컬럼 추가
2. [ ] `modules/models/db.py` — PostgreSQL ALTER TABLE 마이그레이션 8컬럼
3. [ ] `modules/services/delivery_actions.py` — handle_update_inspection() 함수
4. [ ] `modules/services/contract_actions.py` — handle_update_payment() 함수
5. [ ] `modules/services/project_actions.py` — handle_confirm_spec() 함수
6. [ ] `routes/delivery.py` — ACTION_HANDLERS 등록
7. [ ] `routes/project.py` — action 디스패치 연동 (update_payment, confirm_spec)
8. [ ] `templates/delivery_detail.html` — 검수 UI 카드
9. [ ] `templates/contract_detail.html` — 대금 UI 카드
10. [ ] `templates/project_detail.html` — 시방서 반영 확인 체크박스

### 6.7 히스토리 기록 형식

모든 Section C 이벤트는 기존 `append_history_log()` 함수를 사용하며, kind는 `system`으로 통일한다.

| 이벤트 | scope | content 예시 |
|--------|-------|-------------|
| 검수 상태 변경 | delivery | `"이지훈 [검수] 미검수 → 합격 \| 비고: 전체 수량 확인 완료"` |
| 대금 상태 변경 | contract | `"이지훈 [대금] 미청구 → 청구완료 \| 세금계산서 발행일: 2026-03-20"` |
| 대금 입금 확인 | contract | `"이지훈 [대금] 청구완료 → 입금완료 \| 입금확인일: 2026-04-15"` |
| 시방서 반영 확인 | design | `"이지훈 [설계] 시방서 반영 확인됨"` |
| 시방서 확인 해제 | design | `"이지훈 [설계] 시방서 반영 확인 해제"` |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-19 | Initial design — A: UX 개선 (offcanvas + 한줄 바 + 버그수정) | CTO Lead |
| 1.1 | 2026-03-19 | Section C 추가 — 매그나텍 업무 프로세스 히스토리 연동 (FR-10/11/12) | CTO Lead |
