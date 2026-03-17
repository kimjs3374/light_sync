# Phase 4: Service Layer 추출 — Design

> Plan 문서: `docs/01-plan/features/phase-4-service-layer.plan.md`

---

## 1. Architecture Overview

### 1.1 현재 구조
```
routes/project.py
  └── handle_detail_common() [line 344~1035, 697줄]
        ├── 21개 elif action == '...' 분기
        ├── DB 쿼리 + 비즈니스 로직 + flash + redirect 혼재
        └── POST 후 공통 commit + AJAX 응답 처리
```

### 1.2 목표 구조
```
routes/project.py
  └── handle_detail_common() [≤150줄, 디스패치만]
        ├── ACTION_HANDLERS dict 참조
        └── 공통 commit + AJAX + redirect

modules/services/
  ├── __init__.py
  ├── project_actions.py    (프로젝트 정보 수정 5 actions)
  ├── contract_actions.py   (계약/품목 CRUD 6 actions)
  ├── barcode_actions.py    (바코드 CRUD 3 actions)
  └── contact_actions.py    (연락처/히스토리 5 actions + 자재 2 actions)
```

### 1.3 서비스 함수 규약

```python
def handle_xxx(db, project, form, current_user, **ctx):
    """
    Args:
        db: SQLAlchemy session (commit은 호출자가 수행)
        project: Project 객체 (eager-loaded)
        form: request.form (ImmutableMultiDict)
        current_user: session.get('full_name')
        **ctx: page_scope, can_manage_priority 등 추가 컨텍스트
    Returns:
        dict: {
            'flash': (message, category) | None,
            'ajax_log': dict | None,  # AJAX 응답용 로그 엔트리
        }
    """
```

- 서비스 함수는 **Flask 의존 없음** (flash/redirect/session 직접 호출 금지)
- `db.commit()`은 호출하지 않음 (라우트의 공통 commit에서 처리)
- `request.files`가 필요한 경우 `files` 파라미터 추가

---

## 2. Design Checkpoints

### D-01: `_date_to_dt_start()` 중복 제거

| 항목 | 내용 |
|------|------|
| 현재 위치 | `routes/project.py:42`, `routes/material.py:23` |
| 목표 | `modules/utils.py`에 `date_to_dt_start()` 추가, 양쪽 로컬 제거 |
| 함수 시그니처 | `def date_to_dt_start(d): -> datetime | None` |
| 검증 | `_date_to_dt_start` 문자열이 routes/ 내 어디에도 없음 |

### D-02: `modules/services/` 패키지 생성

| 항목 | 내용 |
|------|------|
| 생성 파일 | `modules/services/__init__.py` |
| 내용 | 빈 파일 또는 서비스 모듈 re-export |
| 검증 | `import modules.services` 성공 |

### D-03: project_actions.py 추출

| Action | 원본 라인 | 대략 줄수 |
|--------|:---------:|:---------:|
| `update_design_basis` | 366~374 | 9 |
| `update_project` | 376~389 | 14 |
| `update_priority_override` | 391~431 | 41 |
| `update_work_path` | 434~439 | 6 |
| `update_material` | 442~462 | 21 |
| **합계** | | **~91줄** |

서비스 함수 5개:
```python
# modules/services/project_actions.py
def handle_update_design_basis(db, project, form, current_user, **ctx) -> dict
def handle_update_project(db, project, form, current_user, **ctx) -> dict
def handle_update_priority_override(db, project, form, current_user, **ctx) -> dict
def handle_update_work_path(db, project, form, current_user, **ctx) -> dict
def handle_update_material(db, project, form, current_user, **ctx) -> dict
```

의존성:
- `modules.utils.parse_date`
- `modules.models.HistoryLog, ProjectPriorityOverride`
- `modules.priority_utils.get_active_priority_override`

검증:
- project.py에서 해당 5개 action의 인라인 로직이 모두 제거됨
- 각 action에서 서비스 함수 호출로 대체됨

### D-04: contract_actions.py 추출

| Action | 원본 라인 | 대략 줄수 |
|--------|:---------:|:---------:|
| `update_contract` | 464~503 | 40 |
| `add_contract` | 505~531 | 27 |
| `update_contract_item` | 533~616 | 84 |
| `add_contract_item` | 857~892 | 36 |
| `delete_contract_item` | 894~907 | 14 |
| `delete_material` | 953~959 | 7 |
| **합계** | | **~208줄** |

서비스 함수 6개:
```python
# modules/services/contract_actions.py
def handle_update_contract(db, project, form, current_user, **ctx) -> dict
def handle_add_contract(db, project, form, current_user, **ctx) -> dict
def handle_update_contract_item(db, project, form, current_user, **ctx) -> dict
def handle_add_contract_item(db, project, form, current_user, **ctx) -> dict
def handle_delete_contract_item(db, project, form, current_user, **ctx) -> dict
def handle_delete_material(db, project, form, current_user, **ctx) -> dict
```

의존성:
- `modules.spec_utils.extract_contract_item_spec, validate_contract_item_spec, format_spec_summary`
- `modules.utils.safe_int, parse_date, is_true_value, date_to_dt_start`
- `modules.models.Contract, ContractItem, Material, HistoryLog, ...`
- `modules.history_board.append_history_log`
- `routes.material.sync_material_orders_for_contract_item, sync_material_orders, refresh_admin_statuses_from_material_orders`
- `modules.production_logic.refresh_production_statuses`

주의사항:
- `update_contract_item`이 가장 큰 블록 (84줄) — 스펙 검증, 상태 갱신, 히스토리 로깅 포함
- material sync 함수는 `routes.material`에서 import (Phase 3에서 이미 public)

### D-05: barcode_actions.py 추출

| Action | 원본 라인 | 대략 줄수 |
|--------|:---------:|:---------:|
| `update_contract_item_barcodes_manual` | 618~710 | 93 |
| `upload_contract_item_barcodes` | 712~786 | 75 |
| `delete_contract_item_barcode` | 788~806 | 19 |
| `update_contract_item_barcode_meta` | 808~855 | 48 |
| **합계** | | **~235줄** |

서비스 함수 4개:
```python
# modules/services/barcode_actions.py
def handle_update_barcodes_manual(db, project, form, current_user, **ctx) -> dict
def handle_upload_barcodes(db, project, form, current_user, **ctx) -> dict
def handle_delete_barcode(db, project, form, current_user, **ctx) -> dict
def handle_update_barcode_meta(db, project, form, current_user, **ctx) -> dict
```

의존성:
- `modules.utils.safe_int`
- `modules.models.ContractItem, ContractBarcode, HistoryLog`
- `modules.history_board.append_history_log`
- `routes.barcode.parse_barcode_xlsx_rows` (파일 업로드 시)

주의사항:
- `handle_upload_barcodes`는 `request.files`가 필요 → `files` 파라미터 추가
- `handle_update_barcodes_manual`도 가장 큰 블록 (93줄) — parsed rows 처리, 이력 로깅

### D-06: contact_actions.py 추출

| Action | 원본 라인 | 대략 줄수 |
|--------|:---------:|:---------:|
| `add_contact` | 909~918 | 10 |
| `update_contact` | 920~931 | 12 |
| `delete_contact` | 933~940 | 8 |
| `add_material` | 942~951 | 10 |
| `add_chat` | 961~971 | 11 |
| `add_history_reply` | 973~1001 | 29 |
| **합계** | | **~80줄** |

서비스 함수 6개:
```python
# modules/services/contact_actions.py
def handle_add_contact(db, project, form, current_user, **ctx) -> dict
def handle_update_contact(db, project, form, current_user, **ctx) -> dict
def handle_delete_contact(db, project, form, current_user, **ctx) -> dict
def handle_add_material(db, project, form, current_user, **ctx) -> dict
def handle_add_chat(db, project, form, current_user, **ctx) -> dict
def handle_add_history_reply(db, project, form, current_user, **ctx) -> dict
```

의존성:
- `modules.utils.safe_int`
- `modules.models.Contact, Material, HistoryLog`
- `modules.history_board.append_history_log`

### D-07: handle_detail_common 디스패치화

현재 697줄 → 목표 ≤150줄.

디스패치 패턴:
```python
from modules.services.project_actions import (
    handle_update_design_basis, handle_update_project,
    handle_update_priority_override, handle_update_work_path,
    handle_update_material,
)
from modules.services.contract_actions import (
    handle_update_contract, handle_add_contract,
    handle_update_contract_item, handle_add_contract_item,
    handle_delete_contract_item, handle_delete_material,
)
from modules.services.barcode_actions import (
    handle_update_barcodes_manual, handle_upload_barcodes,
    handle_delete_barcode, handle_update_barcode_meta,
)
from modules.services.contact_actions import (
    handle_add_contact, handle_update_contact, handle_delete_contact,
    handle_add_material_entry, handle_add_chat, handle_add_history_reply,
)

ACTION_HANDLERS = {
    'update_design_basis': handle_update_design_basis,
    'update_project': handle_update_project,
    'update_priority_override': handle_update_priority_override,
    'update_work_path': handle_update_work_path,
    'update_material': handle_update_material,
    'update_contract': handle_update_contract,
    'add_contract': handle_add_contract,
    'update_contract_item': handle_update_contract_item,
    'add_contract_item': handle_add_contract_item,
    'delete_contract_item': handle_delete_contract_item,
    'update_contract_item_barcodes_manual': handle_update_barcodes_manual,
    'upload_contract_item_barcodes': handle_upload_barcodes,
    'delete_contract_item_barcode': handle_delete_barcode,
    'update_contract_item_barcode_meta': handle_update_barcode_meta,
    'add_contact': handle_add_contact,
    'update_contact': handle_update_contact,
    'delete_contact': handle_delete_contact,
    'add_material': handle_add_material_entry,
    'delete_material': handle_delete_material,
    'add_chat': handle_add_chat,
    'add_history_reply': handle_add_history_reply,
}

def handle_detail_common(project_id, template_name):
    with get_db() as db:
        current_user = session.get('full_name')
        page_scope = 'contract' if 'contract' in template_name else 'design'
        p = db.query(Project).options(...).get(project_id)
        can_manage = _can_manage_priority(db)

        if request.method == 'POST':
            action = request.form.get('action')
            handler = ACTION_HANDLERS.get(action)
            if handler:
                ctx = {
                    'page_scope': page_scope,
                    'can_manage_priority': can_manage,
                    'files': request.files,
                }
                result = handler(db, p, request.form, current_user, **ctx)
                if result.get('flash'):
                    flash(*result['flash'])

            # HistoryLog 기본값 보정 (공통)
            for obj in list(db.new):
                if isinstance(obj, HistoryLog):
                    ...

            db.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                ajax_log = result.get('ajax_log') if handler else None
                return jsonify({'ok': True, 'action': action, 'log': ajax_log})
            redirect_to = "project.contract_detail" if "contract" in template_name else "project.project_detail"
            return redirect(url_for(redirect_to, project_id=project_id))

        # GET 처리
        history, history_counts = get_project_history_context(...)
        return render_template(template_name, project=p, ...)
```

검증:
- `handle_detail_common` 함수 내 `elif action ==` 분기가 0개
- 모든 action이 `ACTION_HANDLERS` dict에 등록됨
- HistoryLog 기본값 보정 코드가 공통 블록으로 유지됨

### D-08: project.py 라인 수 검증

| 지표 | 기준 |
|------|------|
| project.py 전체 | ≤700줄 |
| handle_detail_common() | ≤150줄 |
| `elif action ==` 분기 | 0개 |

### D-09: 미사용 import 정리

project.py에서 서비스 모듈로 이동된 로직에만 필요했던 import 제거:
- 더 이상 직접 사용하지 않는 model/util import가 있으면 정리
- syntax check 통과 확인

---

## 3. Implementation Order

```
Phase 4-1: D-01, D-02  (기반 작업: utils 통합 + services 패키지)
Phase 4-2: D-03        (project_actions.py 추출)
Phase 4-3: D-04        (contract_actions.py 추출)
Phase 4-4: D-05        (barcode_actions.py 추출)
Phase 4-5: D-06        (contact_actions.py 추출)
Phase 4-6: D-07~D-09   (디스패치화 + 라인 검증 + import 정리)
```

---

## 4. File Change Matrix

| Action | File | Type | Checkpoint |
|--------|------|------|:----------:|
| MODIFY | `modules/utils.py` | `date_to_dt_start()` 추가 | D-01 |
| MODIFY | `routes/project.py` | `_date_to_dt_start` 제거 + import | D-01 |
| MODIFY | `routes/material.py` | `_date_to_dt_start` 제거 + import | D-01 |
| CREATE | `modules/services/__init__.py` | 패키지 | D-02 |
| CREATE | `modules/services/project_actions.py` | 5 action 핸들러 | D-03 |
| CREATE | `modules/services/contract_actions.py` | 6 action 핸들러 | D-04 |
| CREATE | `modules/services/barcode_actions.py` | 4 action 핸들러 | D-05 |
| CREATE | `modules/services/contact_actions.py` | 6 action 핸들러 | D-06 |
| MODIFY | `routes/project.py` | 디스패치 패턴 적용 | D-07 |
| MODIFY | `routes/project.py` | import 정리 | D-09 |
| **Total** | **5 CREATE + 4 MODIFY = 9 files** | | **9 checkpoints** |

---

## 5. Risk Mitigations

| Risk | Mitigation |
|------|------------|
| DB 트랜잭션 일관성 | 서비스 함수는 `db.commit()` 호출 금지, 라우트 공통 commit만 사용 |
| Flask context 의존 | 서비스 함수에 `session`, `flash`, `redirect` import 금지 |
| 파일 업로드 | `request.files`를 `ctx['files']`로 전달 |
| Circular import | `routes.material`, `routes.barcode`는 project.py에서만 import |
| HistoryLog 기본값 | 공통 보정 로직은 디스패치 함수에 유지 |
