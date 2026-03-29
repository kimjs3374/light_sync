# Design: 협의완료 → 부서별 할일 자동 표시

> Plan 참조: `docs/01-plan/features/consultation-task-flow.plan.md`

---

## 1. 설계 개요

기존 대시보드 `build_action_tabs()`의 4탭 (영업/자재/생산/납품)을 5탭 (영업/자재/생산/**가공**/납품)으로 확장하고, 자재·생산탭에 **협의완료 필터**를 적용하여 실행 가능한 할일만 표시한다.

### 변경 원칙
- DB 스키마 변경 없음
- 신규 파일 생성 없음
- 기존 3개 파일만 수정

---

## 2. 수정 대상 파일

| # | 파일 | 변경 |
|---|------|------|
| 1 | `modules/dashboard_utils.py` | `build_action_tabs()` 로직 수정 |
| 2 | `templates/dashboard.html` | 탭 메타 5개 + 부서별 기본탭 |
| 3 | `modules/models/constants.py` | `DRAWING_REQUIRED_ITEMS` 상수 추가 |

---

## 3. 상세 설계

### 3.1 `modules/models/constants.py` — 상수 추가

```python
# 도면 필요 품목 (가공발주 대상)
DRAWING_REQUIRED_ITEMS = [
    '조명타워',
    '철제가로등주',
    '철제가로등주(보안등주)',
    '스텐가로등주',
    '스텐가로등주(보안등주)',
]
```

### 3.2 `modules/dashboard_utils.py` — `build_action_tabs()` 수정

#### 3.2.1 탭 구조 변경

```python
tabs = {
    'sales': [],       # 영업: 협의 미완료
    'fabrication': [],  # 가공: 도면 품목 + 협의완료 + 미처리 (신규)
    'material': [],     # 자재: 협의완료 + 자재 미완료
    'production': [],   # 생산: 협의완료 + 생산 미완료
    'delivery': [],     # 납품: 기존 동일
}
```

#### 3.2.2 영업탭 — 기존 유지
```
조건: status_sales != '협의완료'
변경: 없음
```

#### 3.2.3 자재탭 — 협의완료 필터 추가
```
기존: status_admin != '입고완료'
변경: status_sales == '협의완료' AND status_admin != '입고완료'
효과: 협의 안 된 건이 자재탭에서 사라짐 → 관리부 노이즈 제거
```

#### 3.2.4 생산탭 — 협의완료 필터 추가
```
기존: status_prod != '생산완료'
변경: status_sales == '협의완료' AND status_prod != '생산완료'
효과: 협의 안 된 건이 생산탭에서 사라짐 → 생산부 노이즈 제거
```

#### 3.2.5 가공탭 — 신규
```
조건: status_sales == '협의완료'
       AND category IN DRAWING_REQUIRED_ITEMS
       AND 해당 품목에 도면이 없음 (item.drawings가 비어있음)
chip: '도면 미작성' / '가공발주 필요'
action_label: '도면 작업'
action_url: sales_detail (영업 상세)
```

**가공발주 상태 판단 로직**:
- 현재 가공발주 전용 상태 필드 없음
- 1단계에서는 **도면 존재 여부**로 판단:
  - `item.drawings`가 비어있음 → "도면 미작성"
  - `item.drawings`가 있음 → 가공탭에서 제외 (도면 완료 = 가공 진행 중으로 간주)

#### 3.2.6 납품탭 — 변경 없음

#### 3.2.7 sort_action_items limit 조정
기존 `limit=6` 유지. 탭이 추가되므로 기존 limit으로 충분.

### 3.3 `templates/dashboard.html` — 탭 UI 수정

#### 3.3.1 action_tab_meta 확장

```python
{% set action_tab_meta = [
    {'key': 'sales', 'label': '영업', 'desc': '협의 미완료 / 선행 위험', 'group': '영업부'},
    {'key': 'fabrication', 'label': '가공', 'desc': '도면 미작성 / 가공발주 필요', 'group': '영업부'},
    {'key': 'material', 'label': '자재', 'desc': '협의완료 → 발주·입고 필요', 'group': '관리부'},
    {'key': 'production', 'label': '생산', 'desc': '협의완료 → 생산 진행 필요', 'group': '생산부'},
    {'key': 'delivery', 'label': '납품', 'desc': '담당 배정 / 완료사진 / 일정', 'group': '영업부'}
] %}
```

#### 3.3.2 부서별 기본 활성 탭

```jinja2
{% set user_group = session.get('user_group', '') %}
{% set default_tab = 'material' if user_group == '관리부'
                     else 'production' if user_group == '생산부'
                     else 'sales' %}
```

탭 버튼 active 클래스:
```jinja2
<button class="nav-link {% if tab.key == default_tab %}active{% endif %}" ...>
```

탭 콘텐츠 show active:
```jinja2
<div class="tab-pane fade {% if tab.key == default_tab %}show active{% endif %}" ...>
```

---

## 4. 데이터 흐름도

```
dashboard_view()
  │
  ├── contracted_projects 쿼리 (기존, joinedload contracts → items)
  │     ※ items에 drawings도 joinedload 필요 (가공탭용)
  │
  └── build_action_tabs(contracted_projects, deliveries, today)
        │
        ├── for project → contract → item:
        │     │
        │     ├── status_sales != '협의완료'?
        │     │     └── YES → sales 탭 추가
        │     │
        │     ├── status_sales == '협의완료'?
        │     │     ├── category in DRAWING_REQUIRED_ITEMS + 도면없음?
        │     │     │     └── YES → fabrication 탭 추가
        │     │     ├── status_admin != '입고완료'?
        │     │     │     └── YES → material 탭 추가
        │     │     └── status_prod != '생산완료'?
        │     │           └── YES → production 탭 추가
        │     │
        │     └── (조건 중복 가능: 하나의 품목이 자재+생산 동시 표시)
        │
        └── for delivery → delivery 탭 (기존 동일)
```

---

## 5. 쿼리 변경

### `routes/dashboard.py` — contracted_projects joinedload 추가

기존:
```python
joinedload(Project.contracts).joinedload(Contract.items),
```

변경:
```python
joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.drawings),
```

가공탭에서 `item.drawings` 존재 여부를 확인해야 하므로 drawings를 선로드.

---

## 6. 구현 순서

| 순서 | 작업 | 파일 |
|------|------|------|
| 1 | `DRAWING_REQUIRED_ITEMS` 상수 추가 | `constants.py` |
| 2 | `build_action_tabs()` 로직 수정 | `dashboard_utils.py` |
| 3 | joinedload drawings 추가 | `dashboard.py` |
| 4 | 탭 메타 + 부서별 기본탭 | `dashboard.html` |

---

## 7. 테스트 시나리오

| # | 시나리오 | 기대 결과 |
|---|---------|----------|
| 1 | 협의 미완료 품목 | 영업탭에만 표시, 자재·생산탭에 안 보임 |
| 2 | 협의완료 + 자재 미발주 | 자재탭에 표시 |
| 3 | 협의완료 + 생산 미착수 | 생산탭에 표시 |
| 4 | 협의완료 + 도면 품목 + 도면 없음 | 가공탭에 표시 |
| 5 | 협의완료 + 도면 품목 + 도면 있음 | 가공탭에서 제외 |
| 6 | 관리부 로그인 | 자재탭이 기본 활성 |
| 7 | 생산부 로그인 | 생산탭이 기본 활성 |
| 8 | 영업부 로그인 | 영업탭이 기본 활성 |
| 9 | 모든 품목 협의완료 + 입고완료 + 생산완료 | 자재·생산탭 "처리할 액션 없음" |
