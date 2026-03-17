# Phase 3: Code Refactoring Design

> **Feature**: phase-3-refactoring
> **Project**: Light-Sync (LED ERP)
> **Author**: Claude Code + User
> **Created**: 2026-03-17
> **Status**: Draft
> **Plan Reference**: [phase-3-refactoring.plan.md](../../01-plan/features/phase-3-refactoring.plan.md)

---

## 1. Overview

Phase 2 (안정성) 완료 후 코드베이스 리팩토링. `project.py` 2,150줄 분할, 중복 유틸 통합, 상수 중앙화.

### Design Checkpoints (Gap Analysis 대상)

| ID | Checkpoint | Category |
|----|-----------|----------|
| D-01 | `modules/utils.py`에 `to_int()` 추가 | 유틸 통합 |
| D-02 | project.py 로컬 `_parse_date()` → `from modules.utils import parse_date` | 유틸 통합 |
| D-03 | production.py 로컬 `_parse_date()` → import 교체 | 유틸 통합 |
| D-04 | delivery.py 로컬 `_parse_date()`, `_to_int()` → import 교체 | 유틸 통합 |
| D-05 | sales.py 로컬 `_parse_date()`, `_is_true_value()`, `TRUE_VALUES` → import 교체 | 유틸 통합 |
| D-06 | project.py 로컬 `_is_true_value()`, `TRUE_VALUES`, `_to_int()` → import 교체 | 유틸 통합 |
| D-07 | dashboard.py 로컬 `_safe_int()` → `from modules.utils import safe_int` | 유틸 통합 |
| D-08 | `modules/spec_utils.py` 신규 생성 (스펙 추출/검증/포맷 함수) | 스펙 분리 |
| D-09 | 상태 상수 `constants.py` 중앙화 (SALES/ADMIN/PROD_STATUS_STEPS) | 상수 중앙화 |
| D-10 | `routes/material.py` Blueprint 생성 + 라우트 이동 | Blueprint 분할 |
| D-11 | `routes/barcode.py` Blueprint 생성 + 라우트 이동 | Blueprint 분할 |
| D-12 | `app.py` Blueprint 등록 (material_bp, barcode_bp) | Blueprint 등록 |
| D-13 | 템플릿 url_for 경로 업데이트 | 정합성 |
| D-14 | project.py 최종 줄 수 ≤ 800줄 | 결과 검증 |

---

## 2. Implementation Details

### 2.1 D-01: `modules/utils.py`에 `to_int()` 추가

현재 `safe_int()`가 이미 존재하지만, 라우트에서 `_to_int(value, default=0)`라는 다른 이름으로 사용 중.
동일 기능이므로 별도 함수 추가 없이 `safe_int`로 통합.

```python
# modules/utils.py - 변경 없음. safe_int()가 이미 동일 기능 수행.
# _to_int() 사용처는 모두 safe_int()로 교체.
```

**판단**: `_to_int(value, default=0)` == `safe_int(value, default=0)` → **별도 함수 불필요, import 교체만 진행**

---

### 2.2 D-02~D-07: 중복 유틸 함수 제거 및 import 교체

#### 대상 파일별 변경 사항

**D-02: `routes/project.py`** (lines 215-233, 36, 43-44)
- 삭제: `_parse_date()` (line 215), `_date_to_dt_start()` (line 224), `_to_int()` (line 230)
- 삭제: `TRUE_VALUES` (line 36), `_is_true_value()` (line 43-44)
- import 추가: `from modules.utils import safe_int, parse_date, is_true_value`
- 호출부 변경: `_parse_date(` → `parse_date(`, `_to_int(` → `safe_int(`, `_is_true_value(` → `is_true_value(`

**참고**: `_date_to_dt_start(d)` 함수 (line 224)는 `parse_date`와 다른 함수 (date→datetime 변환). 이 함수는 project.py에 유지하거나 utils.py로 이동.

```python
# _date_to_dt_start는 project.py 내부에서만 사용 → project.py에 유지
def _date_to_dt_start(d):
    """date -> datetime(00:00:00) 변환"""
    if isinstance(d, datetime.date) and not isinstance(d, datetime.datetime):
        return datetime.datetime.combine(d, datetime.time.min)
    return d
```

**D-03: `routes/production.py`** (lines 38, 242)
- 삭제: `_parse_date()` (line 38), `_to_int()` (line 242)
- import 추가: `from modules.utils import safe_int, parse_date`
- 호출부 변경: `_parse_date(` → `parse_date(`, `_to_int(` → `safe_int(`

**D-04: `routes/delivery.py`** (lines 61, 70)
- 삭제: `_parse_date()` (line 61), `_to_int()` (line 70)
- import 추가: `from modules.utils import safe_int, parse_date`
- 호출부 변경: `_parse_date(` → `parse_date(`, `_to_int(` → `safe_int(`
- 유지: `_parse_datetime_local()` (line 77) - delivery 전용 datetime 파서, 범용성 낮음

**D-05: `routes/sales.py`** (lines 25, 29-30, 33)
- 삭제: `TRUE_VALUES` (line 25), `_is_true_value()` (line 29-30), `_parse_date()` (line 33)
- import 추가: `from modules.utils import safe_int, parse_date, is_true_value`
- 호출부 변경: `_is_true_value(` → `is_true_value(`, `_parse_date(` → `parse_date(`

**D-06**: project.py 변경은 D-02에서 이미 처리됨 (동일 파일).

**D-07: `routes/dashboard.py`** (line 62)
- 삭제: `_safe_int()` (line 62) 로컬 정의
- import 변경: `from modules.utils import safe_int` (이미 존재할 수 있음 → 확인 후 추가)
- 호출부 변경: `_safe_int(` → `safe_int(`

---

### 2.3 D-08: `modules/spec_utils.py` 신규 생성

project.py에서 스펙 관련 함수 3개를 분리:

```python
# modules/spec_utils.py (NEW)

from modules.models import (
    DETAIL_ITEM_OPTIONS,
    normalize_detail_item,
    CONTRACT_ITEM_SPEC_SCHEMA,
)


def extract_contract_item_spec(form, category):
    """
    폼 데이터에서 계약 품목별 스펙 JSON을 추출.
    project.py:47 의 _extract_contract_item_spec() 이동.
    """
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    req = schema.get('required', [])
    # ... (기존 로직 그대로 이동)


def validate_contract_item_spec(category, spec):
    """
    스펙 딕셔너리의 필수 필드 검증.
    project.py:86 의 _validate_contract_item_spec() 이동.
    """
    # ... (기존 로직 그대로 이동)


def format_spec_summary(category, spec):
    """
    스펙 요약 문자열 생성.
    project.py:110 의 _format_spec_summary() 이동.
    """
    # ... (기존 로직 그대로 이동)
```

**project.py 변경**:
- 삭제: `_extract_contract_item_spec()`, `_validate_contract_item_spec()`, `_format_spec_summary()` (lines 47-123)
- import 추가: `from modules.spec_utils import extract_contract_item_spec, validate_contract_item_spec, format_spec_summary`
- 호출부 변경: 언더스코어 prefix 제거

**sales.py 변경** (`_extract_item_spec()` 존재 시):
- sales.py의 스펙 추출 로직이 project.py와 유사한지 확인 후 통합 또는 래퍼 사용

---

### 2.4 D-09: 상태 상수 `constants.py` 중앙화

```python
# modules/models/constants.py에 추가 (기존 파일 끝에 append)

# ─── 워크플로우 상태 스텝 ──────────────────────────
SALES_STATUS_STEPS = ['계약확인', '상세협의중', '협의완료']
ADMIN_STATUS_STEPS = ['자재확인중', '발주진행중', '발주완료', '입고진행중', '입고완료']
PROD_STATUS_STEPS = ['자재대기중', '생산대기중', '생산중', '생산완료']
```

**변경 대상**:
- `routes/project.py` line 33-35: 삭제 → `from modules.models import SALES_STATUS_STEPS, ADMIN_STATUS_STEPS, PROD_STATUS_STEPS`
- `modules/models/__init__.py`: export에 3개 상수 추가

**확인 필요**: production.py, sales.py에서도 동일 상수를 로컬 정의하는지 확인 → 있으면 동일하게 교체.

---

### 2.5 D-10: `routes/material.py` Blueprint 생성

```python
# routes/material.py (NEW)

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from sqlalchemy.orm import joinedload
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.models import (
    Project, Material, MaterialOrder, Contract, ContractItem,
    DETAIL_ITEM_OPTIONS, ADMIN_STATUS_STEPS,
    CONTRACT_ITEM_SPEC_SCHEMA, normalize_detail_item,
)
from modules.history_board import append_history_log

material_bp = Blueprint('material', __name__)
```

**이동 대상 (project.py → material.py)**:

| 함수 | 원래 위치 | 설명 |
|------|-----------|------|
| `_material_specs_from_contract_item()` | line 644 | 자재 스펙 추출 헬퍼 |
| `_sync_material_orders_for_contract_item()` | line 694 | 단일 품목 자재 동기화 |
| `_sync_material_orders()` | line 732 | 프로젝트 전체 자재 동기화 |
| `_is_pristine_material_order()` | line 126 | 자재 주문 초기 상태 체크 |
| `_compute_admin_status_from_orders()` | line 140 | 관리 상태 계산 |
| `_refresh_admin_statuses_from_material_orders()` | line 169 | 관리 상태 갱신 |
| `material_management()` route | line 742 | `/material_management` GET/POST |
| `material_detail()` route | line 905 | `/material_management/<id>` GET/POST |

**라우트 경로 변경**:

| 현재 | 변경 후 | url_for 변경 |
|------|---------|-------------|
| `/material_management` | `/material_management` (경로 동일) | `project.material_management` → `material.material_management` |
| `/material_management/<id>` | `/material_management/<id>` (경로 동일) | `project.material_detail` → `material.material_detail` |

**cross-blueprint 의존성**: `_refresh_admin_statuses_from_material_orders()`는 project.py의 `handle_detail_common()`에서도 호출됨 → material.py에 정의하고 project.py에서 import.

```python
# routes/project.py에서 material 함수 참조
from routes.material import refresh_admin_statuses_from_material_orders, sync_material_orders
```

---

### 2.6 D-11: `routes/barcode.py` Blueprint 생성

```python
# routes/barcode.py (NEW)

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response
from modules.db_context import get_db
from modules.utils import safe_int
from modules.models import ContractBarcode

barcode_bp = Blueprint('barcode', __name__)

BASE_DIR = Path(__file__).resolve().parents[1]
```

**이동 대상 (project.py → barcode.py)**:

| 함수 | 원래 위치 | 설명 |
|------|-----------|------|
| `download_barcode_template()` route | line 185 | 바코드 템플릿 다운로드 |
| `_parse_barcode_csv_rows()` | line 282 | CSV 파싱 |
| `_col_to_letters()` | line 303 | 엑셀 컬럼 문자 변환 |
| `_xml_escape()` | line 311 | XML 이스케이프 |
| `_build_simple_xlsx()` | line 318 | XLSX 생성 |
| `_parse_barcode_xlsx_rows()` | line 382 | XLSX 파싱 |

**라우트 경로 변경**:

| 현재 | 변경 후 | url_for 변경 |
|------|---------|-------------|
| `/barcode_template` | `/barcode_template` | `project.download_barcode_template` → `barcode.download_barcode_template` |

**참고**: 바코드 업로드/관리는 `handle_detail_common()` 안에서 처리되므로 barcode.py에서 export하는 함수를 project.py에서 호출하는 구조:

```python
# routes/project.py에서 barcode 함수 참조
from routes.barcode import parse_barcode_csv_rows, parse_barcode_xlsx_rows, build_simple_xlsx
```

---

### 2.7 D-12: `app.py` Blueprint 등록

```python
# app.py에 추가
from routes.material import material_bp
from routes.barcode import barcode_bp

# Blueprint 등록 섹션에 추가
app.register_blueprint(material_bp)
app.register_blueprint(barcode_bp)
```

---

### 2.8 D-13: 템플릿 url_for 경로 업데이트

**material 관련 (6곳)**:

| 파일 | 변경 |
|------|------|
| `templates/base.html:297` | `project.material_management` → `material.material_management` |
| `templates/dashboard.html:928` | `project.material_management` → `material.material_management` |
| `templates/material_detail.html:16` | `project.material_management` → `material.material_management` |
| `templates/material_detail.html:179` | `project.material_detail` → `material.material_detail` |
| `templates/material_management.html:80` | `project.material_management` → `material.material_management` |
| `templates/material_management.html:112,156` | `project.material_detail` → `material.material_detail` |

**routes/ 내 Python 파일 (3곳)**:

| 파일 | 변경 |
|------|------|
| `routes/dashboard.py:191` | `project.material_detail` → `material.material_detail` |
| `routes/dashboard.py:813` | `project.material_management` → `material.material_management` |
| `routes/project.py` (handle_detail 내) | `project.material_detail` → `material.material_detail` |

**barcode 관련 (1곳)**:

| 파일 | 변경 |
|------|------|
| `templates/contract_detail.html:393` | `project.download_barcode_template` → `barcode.download_barcode_template` |

---

### 2.9 D-14: project.py 최종 크기 검증

| Section | Before (줄) | After (줄) | Action |
|---------|:-----------:|:----------:|--------|
| imports | ~31 | ~35 | import 추가/변경 |
| 상수 (STATUS_STEPS, TRUE_VALUES) | 4 | 0 | D-09로 이동 |
| 유틸 함수 (_parse_date 등) | ~50 | ~10 | D-02,D-06으로 삭제, _date_to_dt_start 유지 |
| 스펙 함수 (extract/validate/format) | ~77 | 0 | D-08로 이동 |
| 자재 함수 + 라우트 | ~425 | 0 | D-10으로 이동 |
| 바코드 함수 + 라우트 | ~175 | 0 | D-11로 이동 |
| 프로젝트 핵심 라우트 | ~1,388 | ~1,388 | 유지 |
| **Total** | **2,150** | **~1,433** | **-717줄 (33% 감소)** |

**참고**: `handle_detail_common()` (약 700줄)이 project.py에 남기 때문에 600줄 목표는 이 함수 분할 없이는 달성 불가. 이 함수의 분할은 서비스 레이어 도입이 필요하여 Phase 4 scope로 이관.

**수정된 목표**: project.py ≤ 1,500줄 (Phase 3), ≤ 700줄 (Phase 4 서비스 레이어 도입 후)

---

## 3. Implementation Order

```
Phase 3-1: 유틸 함수 통합
  D-01 → D-02 → D-03 → D-04 → D-05 → D-06 → D-07
  (modules/utils.py 보강 → 5개 라우트 파일 import 교체)

Phase 3-2: 스펙 로직 분리
  D-08
  (modules/spec_utils.py 생성 → project.py import 교체)

Phase 3-3: 상태 상수 중앙화
  D-09
  (constants.py 추가 → project.py import 교체)

Phase 3-4: material.py Blueprint 분리
  D-10 → D-12 (일부) → D-13 (material 관련)
  (routes/material.py 생성 → app.py 등록 → 템플릿 url_for 수정)

Phase 3-5: barcode.py Blueprint 분리
  D-11 → D-12 (일부) → D-13 (barcode 관련)
  (routes/barcode.py 생성 → app.py 등록 → 템플릿 url_for 수정)

Phase 3-6: 최종 검증
  D-14
  (project.py 줄 수 확인, url_for 전수 검사)
```

---

## 4. File Change Matrix

| File | Action | Checkpoints |
|------|--------|-------------|
| `modules/utils.py` | MODIFY (to_int 불필요 확인) | D-01 |
| `modules/spec_utils.py` | CREATE | D-08 |
| `modules/models/constants.py` | MODIFY (상태 상수 추가) | D-09 |
| `modules/models/__init__.py` | MODIFY (export 추가) | D-09 |
| `routes/material.py` | CREATE | D-10 |
| `routes/barcode.py` | CREATE | D-11 |
| `routes/project.py` | MODIFY (대규모 삭제+import 변경) | D-02,D-06,D-08,D-09,D-10,D-11 |
| `routes/production.py` | MODIFY (중복 함수 삭제) | D-03 |
| `routes/delivery.py` | MODIFY (중복 함수 삭제) | D-04 |
| `routes/sales.py` | MODIFY (중복 함수+상수 삭제) | D-05 |
| `routes/dashboard.py` | MODIFY (_safe_int 삭제) | D-07 |
| `app.py` | MODIFY (Blueprint 등록 추가) | D-12 |
| `templates/base.html` | MODIFY (url_for 1곳) | D-13 |
| `templates/dashboard.html` | MODIFY (url_for 1곳) | D-13 |
| `templates/material_detail.html` | MODIFY (url_for 2곳) | D-13 |
| `templates/material_management.html` | MODIFY (url_for 3곳) | D-13 |
| `templates/contract_detail.html` | MODIFY (url_for 1곳) | D-13 |

**Total**: 3 CREATE + 14 MODIFY = 17개 파일

---

## 5. Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| 순환 import (material.py ↔ project.py) | material.py의 공용 함수를 project.py에서 import하되, 역방향 참조 없음 |
| url_for 404 | grep으로 `project.material_` 및 `project.download_barcode` 전수 검색 후 교체 |
| `handle_detail_common()`에서 material/barcode 함수 호출 | project.py에서 `from routes.material import ...`, `from routes.barcode import ...` |
| `_parse_date` 동작 차이 | 로컬 버전은 단일 포맷, utils.py는 3개 포맷 지원 → 상위 호환 (기존 동작 유지) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial Phase 3 Design | Claude Code |
