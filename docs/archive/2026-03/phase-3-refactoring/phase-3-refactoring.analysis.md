# Phase 3 Refactoring - Gap Analysis Report

> **Analysis Type**: Design vs Implementation Gap Analysis
>
> **Project**: Light-Sync (LED ERP)
> **Analyst**: Claude Code (gap-detector)
> **Date**: 2026-03-17
> **Design Doc**: [phase-3-refactoring.design.md](../02-design/features/phase-3-refactoring.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Phase 3 리팩토링 설계 문서(D-01 ~ D-14)와 실제 구현 코드 간의 일치율을 검증한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/phase-3-refactoring.design.md`
- **Implementation Path**: `routes/`, `modules/`, `app.py`, `templates/`
- **Checkpoints**: D-01 through D-14

---

## 2. Checkpoint Verification

### D-01: `_to_int()` -> `safe_int()` 통합 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `modules/utils.py`에 `safe_int()` 존재 | PASS | `utils.py:17` - `def safe_int(value, default=0)` |
| 라우트 파일에 `_to_int()` 정의 없음 | PASS | `grep def _to_int` in `routes/` = 0 matches |

### D-02: project.py에서 `_to_int` 제거 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `safe_int` import 존재 | PASS | `project.py:8` - `from modules.utils import safe_int, parse_date, is_true_value` |
| `parse_date` import 존재 | PASS | 동일 라인 |
| 로컬 `_to_int()` 정의 없음 | PASS | grep 결과 0건 |
| 로컬 `_parse_date()` 정의 없음 | PASS | grep 결과 0건 |
| `_date_to_dt_start()` 유지 | PASS | `project.py:42` - 설계 의도대로 project.py에 유지 |

### D-03: production.py 중복 제거 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `safe_int, parse_date` import 존재 | PASS | `production.py:8` - `from modules.utils import safe_int, parse_date` |
| 로컬 `_parse_date()` 정의 없음 | PASS | grep 결과 0건 |
| 로컬 `_to_int()` 정의 없음 | PASS | grep 결과 0건 |

### D-04: delivery.py 중복 제거 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `validate_upload, safe_int, parse_date` import 존재 | PASS | `delivery.py:11` - `from modules.utils import validate_upload, safe_int, parse_date` |
| 로컬 `_parse_date()` 정의 없음 | PASS | grep 결과 0건 |
| 로컬 `_to_int()` 정의 없음 | PASS | grep 결과 0건 |
| `_parse_datetime_local()` 유지 | PASS | `delivery.py:61` - delivery 전용 함수 유지 (설계 의도) |

### D-05: sales.py 중복 제거 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `safe_int, parse_date, is_true_value` import 존재 | PASS | `sales.py:7` - `from modules.utils import safe_int, parse_date, is_true_value` |
| 로컬 `TRUE_VALUES` 정의 없음 | PASS | grep 결과 0건 |
| 로컬 `_is_true_value()` 정의 없음 | PASS | grep 결과 0건 |
| 로컬 `_parse_date()` 정의 없음 | PASS | grep 결과 0건 |
| `_extract_item_spec()` 유지 | PASS | `sales.py:29` - sales 전용 변형 유지 (설계 허용) |
| `_validate_item_spec()` 유지 | PASS | `sales.py:74` - sales 전용 변형 유지 (설계 허용) |

### D-06: project.py `_is_true_value` 제거 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `is_true_value` import 존재 | PASS | `project.py:8` (D-02와 동일 라인) |
| 로컬 `TRUE_VALUES` 정의 없음 | PASS | grep 결과 0건 |
| 로컬 `_is_true_value()` 정의 없음 | PASS | grep 결과 0건 |

### D-07: dashboard.py `_safe_int` 제거 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `safe_int` import 존재 | PASS | `dashboard.py:10` - `from modules.utils import safe_int` |
| 로컬 `_safe_int()` 정의 없음 | PASS | grep 결과 0건 |

### D-08: `modules/spec_utils.py` 모듈 생성 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| 파일 존재 | PASS | `modules/spec_utils.py` exists |
| `extract_contract_item_spec()` 함수 | PASS | `spec_utils.py:15` |
| `validate_contract_item_spec()` 함수 | PASS | `spec_utils.py:55` |
| `format_spec_summary()` 함수 | PASS | `spec_utils.py:80` |
| `BOOLEAN_SPEC_FIELDS` 상수 | PASS | `spec_utils.py:12` |
| project.py에서 import | PASS | `project.py:9` - `from modules.spec_utils import extract_contract_item_spec, validate_contract_item_spec, format_spec_summary` |
| project.py에 원본 함수 없음 | PASS | grep 결과 0건 |

### D-09: 상태 상수 중앙화 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `constants.py`에 `SALES_STATUS_STEPS` | PASS | `constants.py:130` |
| `constants.py`에 `ADMIN_STATUS_STEPS` | PASS | `constants.py:131` |
| `constants.py`에 `PROD_STATUS_STEPS` | PASS | `constants.py:132` |
| `__init__.py`에서 export | PASS | `__init__.py:3,10,11` - 3개 상수 모두 import/export |
| project.py에서 import | PASS | `project.py:16` |
| sales.py에서 import | PASS | `sales.py:12` |
| 로컬 상태 상수 정의 없음 | PASS | routes/ 내 로컬 정의 0건 |

### D-10: `routes/material.py` Blueprint 분리 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| 파일 존재 | PASS | `routes/material.py` exists |
| `material_bp` Blueprint | PASS | `material.py:20` - `material_bp = Blueprint('material', __name__)` |
| `material_management()` 라우트 | PASS | 라우트 존재 확인 |
| `material_detail()` 라우트 | PASS | 라우트 존재 확인 |
| `refresh_admin_statuses_from_material_orders` 공용 함수 | PASS | `material.py:72` |
| `sync_material_orders` 공용 함수 | PASS | `material.py:176` |
| `sync_material_orders_for_contract_item` 공용 함수 | PASS | `material.py:138` |
| `compute_admin_status_from_orders` 공용 함수 | PASS | `material.py:43` |
| project.py에서 import | PASS | `project.py:29-34` |

### D-11: `routes/barcode.py` Blueprint 분리 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| 파일 존재 | PASS | `routes/barcode.py` exists |
| `barcode_bp` Blueprint | PASS | `barcode.py:9` - `barcode_bp = Blueprint('barcode', __name__)` |
| `download_barcode_template()` 라우트 | PASS | `barcode.py:12` |
| `parse_barcode_csv_rows()` | PASS | `barcode.py:46` |
| `parse_barcode_xlsx_rows()` | PASS | `barcode.py:147` |
| `_col_to_letters()` | PASS | `barcode.py:68` |
| `_xml_escape()` | PASS | `barcode.py:76` |
| `_build_simple_xlsx()` | PASS | `barcode.py:83` |
| project.py에서 import | PASS | `project.py:35` - `from routes.barcode import parse_barcode_xlsx_rows` |
| project.py에 바코드 함수 없음 | PASS | grep 결과 0건 (import/호출만 존재) |

### D-12: app.py Blueprint 등록 -- PASS

| Check | Result | Evidence |
|-------|--------|----------|
| `material_bp` import | PASS | `app.py:19` - `from routes.material import material_bp` |
| `barcode_bp` import | PASS | `app.py:20` - `from routes.barcode import barcode_bp` |
| `material_bp` register | PASS | `app.py:102` - `app.register_blueprint(material_bp)` |
| `barcode_bp` register | PASS | `app.py:103` - `app.register_blueprint(barcode_bp)` |

### D-13: url_for 참조 업데이트 -- PASS

**Material 관련 (templates)**:

| File | Expected | Actual | Status |
|------|----------|--------|--------|
| `templates/base.html:297` | `material.material_management` | `material.material_management` | PASS |
| `templates/dashboard.html:928` | `material.material_management` | `material.material_management` | PASS |
| `templates/material_detail.html:16` | `material.material_management` | `material.material_management` | PASS |
| `templates/material_detail.html:179` | `material.material_detail` | `material.material_detail` | PASS |
| `templates/material_management.html:80` | `material.material_management` | `material.material_management` | PASS |
| `templates/material_management.html:112,156` | `material.material_detail` | `material.material_detail` | PASS |

**Routes 내 Python 파일**:

| File | Expected | Actual | Status |
|------|----------|--------|--------|
| `routes/dashboard.py:185` | `material.material_detail` | `material.material_detail` | PASS |
| `routes/dashboard.py:807` | `material.material_management` | `material.material_management` | PASS |

**Barcode 관련**:

| File | Expected | Actual | Status |
|------|----------|--------|--------|
| `templates/contract_detail.html:393` | `barcode.download_barcode_template` | `barcode.download_barcode_template` | PASS |

**잔존 `project.material_*` / `project.download_barcode*` 참조**: grep 결과 templates/ 및 routes/ 내 0건 -- 모두 교체 완료.

### D-14: project.py 라인 수 검증 -- PASS

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| project.py 라인 수 | <= 1,500 | **1,266** | PASS |
| 설계 예측 | ~1,433 | 1,266 | 예측보다 167줄 추가 감소 |
| 원본 대비 감소 | -33% target | **-41%** (2,150 -> 1,266) | 초과 달성 |

---

## 3. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| D-01 ~ D-07: 유틸 함수 통합 | 100% (7/7) | PASS |
| D-08: spec_utils 분리 | 100% (1/1) | PASS |
| D-09: 상태 상수 중앙화 | 100% (1/1) | PASS |
| D-10 ~ D-11: Blueprint 분리 | 100% (2/2) | PASS |
| D-12: app.py 등록 | 100% (1/1) | PASS |
| D-13: url_for 업데이트 | 100% (1/1) | PASS |
| D-14: 줄 수 검증 | 100% (1/1) | PASS |
| **Overall** | **100% (14/14)** | **PASS** |

```
+---------------------------------------------+
|  Overall Match Rate: 100%                   |
+---------------------------------------------+
|  PASS:  14 checkpoints                      |
|  FAIL:   0 checkpoints                      |
+---------------------------------------------+
```

---

## 4. Missing Features (Design O, Implementation X)

None.

---

## 5. Added Features (Design X, Implementation O)

| Item | Location | Description | Impact |
|------|----------|-------------|--------|
| `BOOLEAN_SPEC_FIELDS` in `spec_utils.py` exported to `sales.py` | `sales.py:25` | sales.py가 spec_utils에서 상수를 import하여 재사용 | Low (긍정적: 중복 방지) |
| `_date_to_dt_start()` in `material.py` | `material.py:23` | material.py에도 동일 헬퍼 존재 (project.py와 중복) | Low (Phase 4 통합 후보) |

---

## 6. Observations

1. **project.py 감소율 초과 달성**: 설계 예측 1,433줄 대비 실제 1,266줄로 167줄 추가 감소.
2. **sales.py spec 함수 유지**: `_extract_item_spec()`, `_validate_item_spec()`가 sales 전용 변형으로 유지됨. 설계 문서에서 허용한 사항.
3. **`_date_to_dt_start()` 중복**: `project.py:42`와 `material.py:23`에 동일 함수 존재. Phase 4에서 `modules/utils.py`로 통합 권장.
4. **production.py 내 spec 관련 함수**: `_spec_completion_summary()`, `_required_spec_fields()` 등이 production.py에 로컬 정의 유지 중. 향후 `spec_utils.py` 확장 시 통합 후보.

---

## 7. Recommended Actions

### Phase 4 후보 (Backlog)

| Priority | Item | Current Location | Target |
|----------|------|-----------------|--------|
| Low | `_date_to_dt_start()` 통합 | `project.py:42`, `material.py:23` | `modules/utils.py` |
| Low | production.py spec 함수 통합 | `production.py:47-119` | `modules/spec_utils.py` 확장 |
| Medium | `handle_detail_common()` 분할 | `project.py` (~700줄) | 서비스 레이어 도입 |

### Design Document Update

None required. 설계 문서와 구현이 100% 일치.

---

## 8. Conclusion

Phase 3 리팩토링이 설계 문서(D-01 ~ D-14) 대비 **100% 일치율**로 완료됨. 모든 체크포인트가 PASS이며, project.py는 목표(1,500줄) 대비 234줄 추가 감소한 1,266줄을 달성. 설계-구현 간 갭이 없으므로 Check 단계를 완료로 처리할 수 있다.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial gap analysis | Claude Code (gap-detector) |
