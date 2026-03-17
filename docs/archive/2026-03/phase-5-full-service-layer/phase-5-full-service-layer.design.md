# Phase 5: 전체 라우트 서비스 레이어 추출 — Design

> Plan 문서: `docs/01-plan/features/phase-5-full-service-layer.plan.md`

---

## 1. Architecture Overview

### 1.1 서비스 함수 규약 (Phase 4 동일)

```python
def handle_xxx(db, project, form, current_user, **ctx) -> dict:
    # Flask 의존 없음 (flash/redirect/session 직접 호출 금지)
    # db.commit() 호출 안 함 (라우트 공통 commit에서 처리)
    # return {'flash': (msg, cat), 'flashes': [(msg,cat),...], 'ajax_log': dict}
```

### 1.2 디스패치 패턴 (Phase 4 동일)

```python
ACTION_HANDLERS = {
    'action_name': handle_action_name,
    ...
}

# POST 처리부
action = request.form.get('action')
handler = ACTION_HANDLERS.get(action)
if handler:
    ctx = { 'page_scope': ..., 'files': request.files, ... }
    result = handler(db, p, request.form, current_user, **ctx)
    if result.get('flash'):
        flash(*result['flash'])
    for f in result.get('flashes', []):
        flash(*f)
    if result.get('ajax_log'):
        ajax_log_entry = result['ajax_log']
```

---

## 2. Sub-Phase 5-1: production.py (829줄 → ≤400줄)

### D-01: production_actions.py 생성

서비스 모듈: `modules/services/production_actions.py`

| # | Action | 원본 라인 | Handler |
|:-:|--------|:---------:|---------|
| 1 | `sync_production_processes` | 481~494 | `handle_sync_production_processes` |
| 2 | `update_process_status` | 495~527 | `handle_update_process_status` |
| 3 | `add_daily_log` | 528~572 | `handle_add_daily_log` |
| 4 | `toggle_item_complete` | 573~638 | `handle_toggle_item_complete` |
| 5 | `toggle_process_active` | 639~713 | `handle_toggle_process_active` |
| 6 | `update_process_modal` | 714~767 | `handle_update_process_modal` |
| 7 | `add_chat` | 768~780 | `handle_add_chat` |
| 8 | `add_history_reply` | 781~829 | `handle_add_history_reply` |

의존성:
- `modules.utils.safe_int, parse_date`
- `modules.models.HistoryLog, ...` (생산 관련 모델)
- `modules.history_board.append_history_log`
- `modules.production_logic.refresh_production_statuses`

### D-02: production.py 유틸 함수 정리

현재 18개 private 함수 중:
- `_spec_label`, `_is_filled_spec_value`, `_required_spec_fields`, `_spec_completion_summary`, `_format_spec_value` → spec 관련 5개는 라우트에 유지 (GET 렌더링에 사용)
- `_as_bool` → `modules/utils.py`로 이동 (`is_true_value`와 통합 검토)
- `_calc_logged_qty`, `_clamp_daily_qty` → `production_actions.py`로 이동 (action 전용)
- `_history_payload`, `_project_dday`, `_project_desired_delivery` → 라우트에 유지 (GET 렌더링)
- 나머지 → 라우트에 유지 (GET 렌더링 + 패널 빌드)

### D-03: production.py 디스패치 적용

- `production_detail()` 내 8개 `elif action ==` 분기를 `ACTION_HANDLERS` 디스패치로 교체
- HistoryLog 기본값 보정 블록 유지
- 미사용 import 정리

검증:
- `elif action ==` 분기 0개
- `production_detail()` ≤150줄
- `production.py` 전체 ≤400줄

---

## 3. Sub-Phase 5-2: delivery.py (577줄 → ≤300줄)

### D-04: delivery_actions.py 생성

서비스 모듈: `modules/services/delivery_actions.py`

| # | Action | 원본 라인 | Handler |
|:-:|--------|:---------:|---------|
| 1 | `sync_deliveries` | 304~309 | `handle_sync_deliveries` |
| 2 | `add_split` | 310~327 | `handle_add_split` |
| 3 | `update_split` | 328~343 | `handle_update_split` |
| 4 | `delete_split` | 344~353 | `handle_delete_split` |
| 5 | `assign_delivery_owner` | 354~368 | `handle_assign_delivery_owner` |
| 6 | `assign_me` | 369~379 | `handle_assign_me` |
| 7 | `add_photo` | 380~412 | `handle_add_photo` |
| 8 | `delete_photo` | 413~423 | `handle_delete_photo` |
| 9 | `add_contact` | 424~436 | `handle_add_contact` |
| 10 | `update_contact` | 437~450 | `handle_update_contact` |
| 11 | `delete_contact` | 451~460 | `handle_delete_contact` |
| 12 | `add_chat` | 461~466 | `handle_add_chat` |
| 13 | `add_history_reply` | 467~559 | `handle_add_history_reply` |

의존성:
- `modules.utils.safe_int, parse_date, validate_upload`
- `modules.models.HistoryLog, Delivery*, Contact, ...`
- `modules.history_board.append_history_log`
- `modules.storage_adapter` (사진 업로드)

주의사항:
- `handle_add_photo`는 `ctx['files']` 필요
- `_sync_deliveries` (line 84, 48줄)는 public util로 라우트에 유지 (delivery_management에서도 사용)
- `handle_sync_deliveries`는 내부에서 `_sync_deliveries()` 호출

### D-05: delivery.py 디스패치 적용

- `delivery_detail()` 내 13개 분기 → `ACTION_HANDLERS` 디스패치
- `_parse_datetime_local`, `_normalize_photo_type` → `delivery_actions.py`로 이동 (action 전용)
- `_can_assign_owner`, `_status_badge`, `_sync_deliveries` → 라우트에 유지

검증:
- `elif action ==` 분기 0개
- `delivery_detail()` ≤100줄
- `delivery.py` 전체 ≤300줄

---

## 4. Sub-Phase 5-3: material.py (603줄 → ≤350줄)

### D-06: material_actions.py 생성

서비스 모듈: `modules/services/material_actions.py`

| # | Action | 원본 라인 | Handler |
|:-:|--------|:---------:|---------|
| 1 | `sync_material_orders` | 362~375 | `handle_sync_material_orders` |
| 2 | `update_material_order` | 376~430 | `handle_update_material_order` |
| 3 | `bulk_update_material_orders` | 431~549 | `handle_bulk_update_material_orders` |
| 4 | `add_chat` | 550~562 | `handle_add_chat` |
| 5 | `add_history_reply` | 563~603 | `handle_add_history_reply` |

의존성:
- `modules.utils.safe_int, parse_date, date_to_dt_start`
- `modules.models.MaterialOrder, HistoryLog, ...`
- `modules.history_board.append_history_log`

주의사항:
- `bulk_update_material_orders`가 가장 큰 블록 (~119줄) — 다수 주문의 일괄 상태/날짜 업데이트
- material.py의 public 함수 4개 (`refresh_admin_statuses_from_material_orders`, `sync_material_orders`, `sync_material_orders_for_contract_item`, `compute_admin_status_from_orders`)는 라우트에 유지 (다른 모듈에서 import)
- `_is_pristine_material_order`, `_material_specs_from_contract_item` → 라우트에 유지 (GET 렌더링)

### D-07: material.py 디스패치 적용

- `material_detail()` 내 5개 분기 → `ACTION_HANDLERS` 디스패치
- 미사용 import 정리

검증:
- `elif action ==` 분기 0개
- `material_detail()` ≤100줄
- `material.py` 전체 ≤350줄

---

## 5. Sub-Phase 5-4: sales.py (460줄 → ≤250줄)

### D-08: sales_actions.py 생성

서비스 모듈: `modules/services/sales_actions.py`

| # | Action | 원본 라인 | Handler |
|:-:|--------|:---------:|---------|
| 1 | `update_sales_item` | 289~344 | `handle_update_sales_item` |
| 2 | `add_sales_comment` | 345~357 | `handle_add_sales_comment` |
| 3 | `add_contact` | 358~383 | `handle_add_contact` |
| 4 | `update_contact` | 384~406 | `handle_update_contact` |
| 5 | `add_history_reply` | 407~460 | `handle_add_history_reply` |

의존성:
- `modules.utils.safe_int, parse_date`
- `modules.models.ContractItem, Contact, HistoryLog, ...`
- `modules.history_board.append_history_log`
- `modules.spec_utils.*` (스펙 관련)

주의사항:
- `_extract_item_spec`, `_validate_item_spec`, `_diff_spec`, `_is_filled_value`, `_required_fields_for_status`, `_derive_sales_status` → sales_actions.py로 이동 (action 전용 spec 로직)

### D-09: sales.py 디스패치 적용

- `sales_detail()` 내 5개 분기 → `ACTION_HANDLERS` 디스패치
- spec 관련 6개 private 함수 제거 (sales_actions.py로 이동됨)
- 미사용 import 정리

검증:
- `elif action ==` 분기 0개
- `sales_detail()` ≤100줄
- `sales.py` 전체 ≤250줄

---

## 6. Sub-Phase 5-5: dashboard.py (908줄 → ≤500줄)

### D-10: dashboard_actions.py 생성

서비스 모듈: `modules/services/dashboard_actions.py`

| # | Action | 원본 라인 | Handler |
|:-:|--------|:---------:|---------|
| 1 | `update_global_seconds` | 498~504 | `handle_update_global_seconds` |
| 2 | `create_notice` | 505~526 | `handle_create_notice` |
| 3 | `update_notice` | 527~544 | `handle_update_notice` |
| 4 | `delete_notice` | 545~557 | `handle_delete_notice` |

### D-11: dashboard_utils.py 생성

대시보드 전용 집계/통계 로직을 `modules/dashboard_utils.py`로 추출:

| Function | 원본 라인 | 대략 줄수 | 역할 |
|----------|:---------:|:---------:|------|
| `build_action_tabs` | 126~286 | 161 | 우선순위 액션탭 구성 |
| `build_month_calendar` | 287~312 | 26 | 월간 캘린더 아이템 |
| `build_auto_alert_items` | 313~376 | 64 | 자동 알림 항목 |
| `build_dashboard_priority_items` | 377~487 | 113 | 대시보드 우선순위 |
| **합계** | | **~364줄** | |

유틸 함수 (dashboard_utils.py로 함께 이동):
- `_project_detail_link`, `_resolve_kanban_stage`, `_project_primary_contract`
- `_days_until`, `_dday_badge`, `_delivery_status_label`
- `_is_delivery_done_photo`, `_sort_action_items`, `_hot_project_count`

라우트에 유지:
- `_is_admin` (session 의존)
- `_get_dashboard_setting_int`, `_set_dashboard_setting_int` (DB 의존, 간단)

### D-12: dashboard.py 디스패치 적용

- `dashboard_notice_admin()` 내 4개 분기 → `ACTION_HANDLERS` 디스패치
- `dashboard_view()` 339줄 → 집계 함수 호출로 ≤150줄 목표
- 미사용 import 정리

검증:
- `elif action ==` 분기 0개
- `dashboard_view()` ≤200줄
- `dashboard.py` 전체 ≤500줄

---

## 7. Implementation Order

```
Phase 5-1: D-01~D-03  (production.py — 8 actions, 가장 복잡한 비즈니스 로직)
Phase 5-2: D-04~D-05  (delivery.py — 13 actions, 최다 action)
Phase 5-3: D-06~D-07  (material.py — 5 actions, public 함수 유지 주의)
Phase 5-4: D-08~D-09  (sales.py — 5 actions, spec 함수 이동)
Phase 5-5: D-10~D-12  (dashboard.py — 4 actions + 대형 집계 함수)
```

---

## 8. File Change Matrix

| Action | File | Type | Checkpoint |
|--------|------|------|:----------:|
| CREATE | `modules/services/production_actions.py` | 8 handlers | D-01 |
| MODIFY | `routes/production.py` | 디스패치 + import 정리 | D-02, D-03 |
| CREATE | `modules/services/delivery_actions.py` | 13 handlers | D-04 |
| MODIFY | `routes/delivery.py` | 디스패치 + import 정리 | D-05 |
| CREATE | `modules/services/material_actions.py` | 5 handlers | D-06 |
| MODIFY | `routes/material.py` | 디스패치 + import 정리 | D-07 |
| CREATE | `modules/services/sales_actions.py` | 5 handlers | D-08 |
| MODIFY | `routes/sales.py` | 디스패치 + import 정리 | D-09 |
| CREATE | `modules/services/dashboard_actions.py` | 4 handlers | D-10 |
| CREATE | `modules/dashboard_utils.py` | 집계/통계 함수 | D-11 |
| MODIFY | `routes/dashboard.py` | 디스패치 + 집계 분리 | D-12 |
| MODIFY | `modules/utils.py` | `_as_bool` 통합 (선택) | D-02 |
| **Total** | **6 CREATE + 6 MODIFY = 12 files** | | **12 checkpoints** |

---

## 9. Gap Analysis Checkpoints (12개)

| # | Checkpoint | 검증 기준 |
|:-:|:----------:|-----------|
| D-01 | production_actions.py | 8 handlers, 올바른 시그니처, Flask import 0, db.commit() 0 |
| D-02 | production.py 유틸 정리 | `_calc_logged_qty`, `_clamp_daily_qty` → service로 이동 |
| D-03 | production.py 디스패치 | `elif action ==` 0개, 전체 ≤400줄 |
| D-04 | delivery_actions.py | 13 handlers, `ctx['files']` 사용 (add_photo) |
| D-05 | delivery.py 디스패치 | `elif action ==` 0개, 전체 ≤300줄 |
| D-06 | material_actions.py | 5 handlers, public 함수 4개는 라우트 유지 |
| D-07 | material.py 디스패치 | `elif action ==` 0개, 전체 ≤350줄 |
| D-08 | sales_actions.py | 5 handlers + spec 관련 6개 private 함수 포함 |
| D-09 | sales.py 디스패치 | `elif action ==` 0개, 전체 ≤250줄 |
| D-10 | dashboard_actions.py | 4 handlers |
| D-11 | dashboard_utils.py | 4개 대형 집계 함수 + 9개 유틸 함수 |
| D-12 | dashboard.py 디스패치 | `elif action ==` 0개, 전체 ≤500줄 |

---

## 10. Risk Mitigations

| Risk | Mitigation |
|------|------------|
| 한 세션에 전체 불가능 | Sub-Phase별 독립 구현, 각각 syntax check |
| production_actions 복잡성 | toggle_item_complete, toggle_process_active가 각 60줄+ — 함수 분할 검토 |
| material.py public 함수 | sync_material_orders 등은 다른 모듈에서 import — 절대 이동 금지 |
| delivery.py 13 actions | 가장 많은 action — 빠진 것 없는지 체크리스트 필수 |
| dashboard 집계 로직 분리 | build_action_tabs 등은 DB session 필요 — 파라미터로 전달 |
| Circular import | 서비스 모듈 → routes import 금지 (역방향만 허용) |
