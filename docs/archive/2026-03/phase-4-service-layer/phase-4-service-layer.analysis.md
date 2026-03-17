# Phase 4: Service Layer Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: Light-Sync ERP
> **Analyst**: gap-detector (automated)
> **Date**: 2026-03-17
> **Design Doc**: [phase-4-service-layer.design.md](../02-design/features/phase-4-service-layer.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Phase 4 Service Layer 추출 작업이 Design Checkpoint 9개를 모두 만족하는지 검증한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/phase-4-service-layer.design.md`
- **Implementation Files**: `modules/utils.py`, `modules/services/`, `routes/project.py`, `routes/material.py`
- **Checkpoints**: D-01 ~ D-09 (9개)

---

## 2. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match (9 checkpoints) | 100% | PASS |
| Architecture Compliance | 100% | PASS |
| Convention Compliance | 100% | PASS |
| **Overall** | **100%** | **PASS** |

---

## 3. Checkpoint Verification

### D-01: `_date_to_dt_start()` Duplication Removed -- PASS

| Check Item | Result | Evidence |
|------------|:------:|----------|
| `modules/utils.py` has `date_to_dt_start(d)` | PASS | `utils.py:25-29` -- `def date_to_dt_start(d):` with correct signature returning `datetime \| None` |
| `routes/project.py` has NO `_date_to_dt_start` | PASS | grep for `_date_to_dt_start` in `routes/` returns 0 matches |
| `routes/material.py` imports from `modules.utils` | PASS | `material.py:5` -- `from modules.utils import safe_int, parse_date, date_to_dt_start` |

### D-02: `modules/services/__init__.py` Exists -- PASS

| Check Item | Result | Evidence |
|------------|:------:|----------|
| File exists | PASS | `modules/services/__init__.py` exists (empty file, 1 line) |

### D-03: `project_actions.py` -- 5 Handlers -- PASS

| Handler | Present | Line | Signature Correct |
|---------|:-------:|:----:|:-----------------:|
| `handle_update_design_basis` | PASS | 11 | `(db, project, form, current_user, **ctx)` |
| `handle_update_project` | PASS | 22 | `(db, project, form, current_user, **ctx)` |
| `handle_update_priority_override` | PASS | 39 | `(db, project, form, current_user, **ctx)` |
| `handle_update_work_path` | PASS | 85 | `(db, project, form, current_user, **ctx)` |
| `handle_update_material` | PASS | 94 | `(db, project, form, current_user, **ctx)` |

| Rule | Result | Evidence |
|------|:------:|----------|
| No Flask imports | PASS | 0 matches for `from flask import` in `modules/services/` |
| No `db.commit()` calls | PASS | 0 matches for `db.commit()` in `modules/services/` |
| Returns dict | PASS | All 5 handlers return `{}` or `{'flash': (...)}` |

### D-04: `contract_actions.py` -- 6 Handlers -- PASS

| Handler | Present | Line | Signature Correct |
|---------|:-------:|:----:|:-----------------:|
| `handle_update_contract` | PASS | 13 | `(db, project, form, current_user, **ctx)` |
| `handle_add_contract` | PASS | 52 | `(db, project, form, current_user, **ctx)` |
| `handle_update_contract_item` | PASS | 81 | `(db, project, form, current_user, **ctx)` |
| `handle_add_contract_item` | PASS | 170 | `(db, project, form, current_user, **ctx)` |
| `handle_delete_contract_item` | PASS | 208 | `(db, project, form, current_user, **ctx)` |
| `handle_delete_material` | PASS | 224 | `(db, project, form, current_user, **ctx)` |

| Rule | Result | Evidence |
|------|:------:|----------|
| No Flask imports | PASS | No `from flask` in file |
| No `db.commit()` calls | PASS | No `db.commit()` in file |

### D-05: `barcode_actions.py` -- 4 Handlers -- PASS

| Handler | Present | Line | Signature Correct |
|---------|:-------:|:----:|:-----------------:|
| `handle_update_barcodes_manual` | PASS | 10 | `(db, project, form, current_user, **ctx)` |
| `handle_upload_barcodes` | PASS | 107 | `(db, project, form, current_user, **ctx)` |
| `handle_delete_barcode` | PASS | 186 | `(db, project, form, current_user, **ctx)` |
| `handle_update_barcode_meta` | PASS | 207 | `(db, project, form, current_user, **ctx)` |

| Rule | Result | Evidence |
|------|:------:|----------|
| `handle_upload_barcodes` uses `ctx['files']` | PASS | Line 108: `files = ctx.get('files', {})` |
| No Flask imports | PASS | No `from flask` in file |
| No `db.commit()` calls | PASS | No `db.commit()` in file |

### D-06: `contact_actions.py` -- 6 Handlers -- PASS

| Handler | Present | Line | Signature Correct |
|---------|:-------:|:----:|:-----------------:|
| `handle_add_contact` | PASS | 10 | `(db, project, form, current_user, **ctx)` |
| `handle_update_contact` | PASS | 22 | `(db, project, form, current_user, **ctx)` |
| `handle_delete_contact` | PASS | 36 | `(db, project, form, current_user, **ctx)` |
| `handle_add_material` | PASS | 46 | `(db, project, form, current_user, **ctx)` |
| `handle_add_chat` | PASS | 58 | `(db, project, form, current_user, **ctx)` |
| `handle_add_history_reply` | PASS | 72 | `(db, project, form, current_user, **ctx)` |

| Rule | Result | Evidence |
|------|:------:|----------|
| No Flask imports | PASS | No `from flask` in file |
| No `db.commit()` calls | PASS | No `db.commit()` in file |

### D-07: `handle_detail_common()` ACTION_HANDLERS Dispatch -- PASS

| Check Item | Result | Evidence |
|------------|:------:|----------|
| ACTION_HANDLERS dict exists | PASS | `project.py:49-71` with 21 entries |
| 21 action-to-handler mappings | PASS | Counted 21 entries matching all service handlers |
| 0 `elif action ==` branches | PASS | grep returns 0 matches in `project.py` |
| ctx dict has required keys | PASS | Lines 393-400: `page_scope`, `can_manage_priority`, `user_id`, `user_group`, `role`, `files` |
| Processes `result['flash']` | PASS | Line 402-403 |
| Processes `result['flashes']` | PASS | Lines 404-405 |
| Processes `result['ajax_log']` | PASS | Lines 406-407, 419 |
| HistoryLog default fix preserved | PASS | Lines 410-415 |

### D-08: Line Count Compliance -- PASS

| Metric | Target | Actual | Status |
|--------|:------:|:------:|:------:|
| `project.py` total lines | <=700 | 672 | PASS |
| `handle_detail_common()` lines | <=150 | 72 (lines 370-441) | PASS |
| `elif action ==` branches | 0 | 0 | PASS |

### D-09: Unused Import Cleanup -- PASS

| Import to Remove | Absent | Evidence |
|------------------|:------:|----------|
| `extract_contract_item_spec` | PASS | Not found in project.py imports |
| `validate_contract_item_spec` | PASS | Not found in project.py imports |
| `MaterialOrder` | PASS | Not found in project.py imports |
| `SportsModule` | PASS | Not found in project.py imports |
| `Contact` | PASS | Not found in project.py imports |
| `ContractBarcode` | PASS | Not found in project.py imports |
| `ProjectPriorityOverride` | PASS | Not found in project.py imports |
| `SALES_STATUS_STEPS` | PASS | Not found in project.py imports |
| `ADMIN_STATUS_STEPS` | PASS | Not found in project.py imports |
| `PROD_STATUS_STEPS` | PASS | Not found in project.py imports |
| `refresh_production_statuses` | PASS | Not found in project.py imports |
| `sync_material_orders` | PASS | Not found in project.py imports |
| `sync_material_orders_for_contract_item` | PASS | Not found in project.py imports |
| `refresh_admin_statuses_from_material_orders` | PASS | Not found in project.py imports |
| `parse_barcode_xlsx_rows` | PASS | Not found in project.py imports |

---

## 4. Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 100% (9/9 PASS)        |
+---------------------------------------------+
|  D-01  _date_to_dt_start dedup      PASS    |
|  D-02  services package              PASS    |
|  D-03  project_actions (5 handlers)  PASS    |
|  D-04  contract_actions (6 handlers) PASS    |
|  D-05  barcode_actions (4 handlers)  PASS    |
|  D-06  contact_actions (6 handlers)  PASS    |
|  D-07  ACTION_HANDLERS dispatch      PASS    |
|  D-08  line count compliance         PASS    |
|  D-09  unused import cleanup         PASS    |
+---------------------------------------------+
```

---

## 5. Minor Design-Implementation Deviations

These are non-blocking observations that do not affect the pass/fail status.

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| Handler name (D-06/D-07) | `handle_add_material_entry` (design.md:222,242) | `handle_add_material` (contact_actions.py:46, project.py:68) | None -- name is simpler, mapping key `'add_material'` is consistent |
| Section 1.2 handler count | barcode: "3 actions", contact: "5+2" | barcode: 4 handlers (D-05), contact: 6 handlers (D-06) | None -- D-05/D-06 sections are authoritative, Section 1.2 is summary |

---

## 6. Design Document Update Suggestions

- [ ] Section 1.2: Update barcode_actions count from "3 actions" to "4 actions"
- [ ] Section 1.2: Clarify contact_actions count as "6 handlers"
- [ ] D-07 import block: Rename `handle_add_material_entry` to `handle_add_material` to match implementation

---

## 7. Conclusion

Match Rate >= 90% -- Design and implementation match well. All 9 checkpoints pass. The service layer extraction is complete: 21 action handlers are distributed across 4 service modules, `routes/project.py` reduced from ~1035 lines to 672 lines, and `handle_detail_common()` reduced from ~697 lines to 72 lines using a clean dispatch pattern with zero `elif action ==` branches.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial analysis -- 9/9 PASS | gap-detector |
