# Phase 6: Auth Decorator + Error Handling + DB Index — Design Document

## 1. Architecture Overview

4개 독립적인 Cross-Cutting Concern을 한 사이클에서 해결한다.
각 항목은 서로 의존성이 없어 순서대로 적용 가능.

```
┌─────────────────────────────────────────────────────┐
│                   routes/*.py                       │
│                                                     │
│  @login_required  ← CP-01 (신규 모듈)               │
│  @admin_required  ← CP-01                           │
│  def endpoint():                                    │
│      try:                                           │
│          ...business logic...                       │
│      except Exception as e:                         │
│          current_app.logger.exception(...)  ← CP-06~07│
│          flash(user_msg, 'danger')                  │
│                                                     │
│  models.py: Column(..., index=True)  ← CP-08       │
└─────────────────────────────────────────────────────┘
```

---

## 2. Detailed Design

### D-01: `modules/auth_decorators.py` 신규 생성

**파일 위치**: `modules/auth_decorators.py`

```python
import functools
from flask import session, redirect, url_for, flash, abort

def login_required(f):
    """세션에 user_id가 없으면 로그인 페이지로 redirect"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """login_required + role == 'admin' 체크. 미달 시 dashboard로 redirect"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != 'admin':
            flash('관리자 권한이 필요합니다.', 'danger')
            return redirect(url_for('dashboard.dashboard_view'))
        return f(*args, **kwargs)
    return decorated
```

**설계 결정사항:**
- `role_required(*roles)`, `permission_required(perm)` 등 추가 데코레이터는 현재 사용처가 적어 **YAGNI 원칙으로 제외**
- `_can_write_drawings()`, `_can_approve_delete()`, `_can_manage_priority(db)` 등은 템플릿 ctx에도 전달되므로 **헬퍼 함수로 유지** (데코레이터로 변환하지 않음)
- `login_required`는 Flask-Login의 것과 동일한 이름이지만 Flask-Login 미사용이므로 충돌 없음

### D-02: project.py 인증 체크 교체 (10개소)

**Before** (각 엔드포인트 함수 내부):
```python
@project_bp.route('/project_list')
def project_list():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    ...
```

**After** (데코레이터):
```python
@project_bp.route('/project_list')
@login_required
def project_list():
    ...
```

**적용 대상** (10개):
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 124 | `project_list` | `@login_required` |
| 173 | `contract_list` | `@login_required` |
| 313 | `contract_detail` | `@login_required` |
| 362 | `delete_project` | `@login_required` |
| 367 | `approve_delete_request` | `@login_required` |
| 448 | `request_delete_project` | `@login_required` |
| 518 | `ajax_toggle_item_complete` | `@login_required` |
| 566 | `ajax_assign_item_owner` | `@login_required` |
| 608 | `ajax_update_contract_item_status` | `@login_required` |
| 639 | `ajax_bulk_update_contract_items` | `@login_required` |

**유지되는 헬퍼 함수들** (삭제하지 않음):
- `_can_approve_delete()` — 삭제 승인 체크, ctx로 전달됨
- `_can_manage_priority(db)` — DB 쿼리 포함, ctx로 전달됨
- `_is_prod_group()` — 생산부 체크, 조건 분기에 사용

### D-03: drawing.py 인증 체크 교체 (7개소)

**적용 대상:**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 57 | `drawings_index` | `@login_required` |
| 70 | `drawings_project` | `@login_required` |
| 99 | `upload_drawing` | `@login_required` |
| 224 | `view_pdf` | `@login_required` |
| 248 | `download_pdf` | `@login_required` |
| 273 | `delete_drawing_version` | `@login_required` |
| 28* | `_can_read_drawings()` 내부 | 유지 (헬퍼 함수 내 session 체크 제거 불가) |

**주의사항:**
- `_can_read_drawings()` 내부의 `if 'user_id' not in session: return False`는 데코레이터와 중복되지만, 이 함수가 독립적으로 호출될 수 있으므로 **안전장치로 유지**
- `_can_write_drawings()`는 데코레이터가 아닌 함수로 유지 (template ctx에 `can_write=_can_write_drawings()`로 전달됨)

### D-04: delivery.py, sales.py, production.py 인증 체크 교체 (7개소)

**delivery.py (3개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 91 | `delivery_management` | `@login_required` |
| 233 | `delivery_detail` | `@login_required` |
| 330 | `view_delivery_photo` | `@login_required` |

**sales.py (2개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 40 | `sales_list` | `@login_required` |
| 158 | `sales_detail` | `@login_required` |

**production.py (2개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 255 | `production_management` | `@login_required` |
| 427 | `production_detail` | `@login_required` |

### D-05: 나머지 라우트 인증/인가 체크 교체 (8개소)

**auth.py (6개) — `@admin_required` 적용:**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 104 | `admin_settings` | `@admin_required` |
| 119 | `toggle_delete_approver` | `@admin_required` |
| 134 | `toggle_priority_manager` | `@admin_required` |
| 163 | `toggle_user_active` | `@admin_required` |
| 198 | `approve_user` | `@admin_required` |
| 212 | `reject_user` | `@admin_required` |

**제외 대상 (데코레이터 미적용):**
- `login()` — 비인증 상태에서 접근해야 하는 엔드포인트
- `register()` — 비인증 상태에서 접근
- `logout()` — 세션 클리어만 수행

**dashboard.py (1개):**
| Line | Endpoint | Before | After |
|------|----------|--------|-------|
| 49 | `dashboard_notice_admin` | `_is_admin()` 체크 | `@admin_required` |

`_is_admin()` 함수는 다른 곳에서 사용하지 않으므로 **삭제**.

**contract.py (1개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 16 | `contract_create` | `@login_required` |

**barcode.py (1개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 14 | `download_barcode_template` | `@login_required` |

**material.py (2개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 198 | `material_management` | `@login_required` |
| 360 | `material_detail` | `@login_required` |

**technical.py (1개):**
| Line | Endpoint | Decorator |
|------|----------|-----------|
| 13 | `lux_calculator` | `@login_required` |

### D-06: project.py 에러 핸들링 개선 (7개소)

**패턴 교체:**

| Line | Current | After |
|------|---------|-------|
| 78 | `except Exception: pass` | `except Exception: current_app.logger.warning(...)` |
| 353 | `except Exception as e:` + flash | + `current_app.logger.exception(...)` |
| 507 | `except Exception as e:` + flash | + `current_app.logger.exception(...)` |
| 558 | `except Exception as e:` + flash | + `current_app.logger.exception(...)` |
| 600 | `except Exception as e:` + flash | + `current_app.logger.exception(...)` |
| 630 | `except Exception as e:` + flash | + `current_app.logger.exception(...)` |
| 669 | `except Exception as e:` + flash | + `current_app.logger.exception(...)` |

**코드 패턴:**
```python
# Before
except Exception as e:
    db.rollback()
    flash(f'오류: {str(e)}', 'danger')

# After
except Exception as e:
    db.rollback()
    current_app.logger.exception('contract_detail action=%s project=%s', action, project_id)
    flash('처리 중 오류가 발생했습니다.', 'danger')
```

**규칙:**
1. `current_app.logger.exception(msg)` 사용 — traceback 자동 포함
2. 사용자에게는 `str(e)` 대신 일반 메시지 표시 (보안: 내부 에러 노출 방지)
3. 로그에는 context 정보 포함 (action명, project_id 등)
4. `except Exception: pass` 패턴 (line 78) → `logger.warning()` 추가 (pass 유지)
5. `from flask import current_app` import 추가 필요

### D-07: 나머지 라우트 에러 핸들링 개선 (7개소)

| File | Line | Current | After |
|------|------|---------|-------|
| auth.py | 97 | `except Exception:` + rollback + flash | + `current_app.logger.exception('register failed')` |
| barcode.py | 54 | `except Exception:` + pass | + `current_app.logger.warning(...)` |
| barcode.py | 164 | `except Exception:` + continue | + `current_app.logger.warning(...)` |
| contract.py | 106 | `except Exception as e:` + rollback + flash | + `current_app.logger.exception(...)` |
| drawing.py | 215 | `except Exception as e:` + rollback + flash | + `current_app.logger.exception(...)` |
| drawing.py | 329 | `except Exception as e:` + rollback + flash | + `current_app.logger.exception(...)` |
| technical.py | 48 | `except Exception as e:` + rollback + flash | + `current_app.logger.exception(...)` |

**각 파일에 `from flask import current_app` import 추가.**

### D-08: DB 인덱스 추가

**대상 컬럼 (models.py 또는 models.back 기준):**

```python
# Project 테이블
is_contracted = Column(Boolean, default=False, index=True)  # 거의 모든 목록 쿼리

# Contract 테이블
project_id = Column(Integer, ForeignKey('projects.id'), index=True)
delivery_due_date = Column(Date, index=True)  # 납기일 범위 쿼리

# ContractItem 테이블
contract_id = Column(Integer, ForeignKey('contracts.id'), index=True)

# Delivery 테이블
project_id = Column(Integer, ForeignKey('projects.id'), index=True)

# HistoryLog 테이블
project_id = Column(Integer, ForeignKey('projects.id'), index=True)

# DeliveryPhoto 테이블
delivery_id = Column(Integer, ForeignKey('deliveries.id'), index=True)

# MaterialOrder 테이블
contract_item_id = Column(Integer, ForeignKey('contract_items.id'), index=True)
```

**적용 방법:**
- models.py가 git에서 empty이므로 models.back을 참조하여 `index=True` 추가
- 실제 DB에 인덱스 적용은 별도 SQL 스크립트 또는 init_db 시점에서 처리
- SQLAlchemy `create_all()`은 기존 테이블에 인덱스를 추가하지 않으므로, 별도 `CREATE INDEX IF NOT EXISTS` SQL도 준비

**인덱스 생성 SQL (SQLite 호환):**
```sql
CREATE INDEX IF NOT EXISTS ix_projects_is_contracted ON projects (is_contracted);
CREATE INDEX IF NOT EXISTS ix_contracts_project_id ON contracts (project_id);
CREATE INDEX IF NOT EXISTS ix_contracts_delivery_due_date ON contracts (delivery_due_date);
CREATE INDEX IF NOT EXISTS ix_contract_items_contract_id ON contract_items (contract_id);
CREATE INDEX IF NOT EXISTS ix_deliveries_project_id ON deliveries (project_id);
CREATE INDEX IF NOT EXISTS ix_history_logs_project_id ON history_logs (project_id);
CREATE INDEX IF NOT EXISTS ix_delivery_photos_delivery_id ON delivery_photos (delivery_id);
CREATE INDEX IF NOT EXISTS ix_material_orders_contract_item_id ON material_orders (contract_item_id);
```

### D-09: 백업 파일 제거

- `modules/models.back` 삭제
- `routes/project.back` 삭제
- git에서도 제거 (이미 tracked인 경우)

### D-10: 통합 검증

1. **Python syntax check**: `python -m py_compile routes/*.py modules/auth_decorators.py`
2. **Import chain check**: 모든 라우트 파일이 `from modules.auth_decorators import login_required` 또는 `admin_required`를 정상 import하는지 확인
3. **데코레이터 순서 확인**: `@bp.route()` → `@login_required` → `def func()` 순서 (route가 먼저, 데코레이터가 그 아래)
4. **기존 동작 보존 검증**: 비인증 시 redirect to login, admin 아닌 경우 redirect to dashboard

---

## 3. Implementation Order

| 순서 | Checkpoint | 파일 | 의존성 |
|------|-----------|------|--------|
| 1 | D-01 | `modules/auth_decorators.py` | 없음 (신규) |
| 2 | D-02 | `routes/project.py` | D-01 |
| 3 | D-03 | `routes/drawing.py` | D-01 |
| 4 | D-04 | `routes/delivery.py`, `sales.py`, `production.py` | D-01 |
| 5 | D-05 | `routes/auth.py`, `dashboard.py`, `contract.py`, `barcode.py`, `material.py`, `technical.py` | D-01 |
| 6 | D-06 | `routes/project.py` (에러 핸들링) | 없음 |
| 7 | D-07 | 나머지 라우트 (에러 핸들링) | 없음 |
| 8 | D-08 | `modules/models.back` + SQL 스크립트 | 없음 |
| 9 | D-09 | 백업 파일 삭제 | 없음 |
| 10 | D-10 | 전체 검증 | D-01~D-09 완료 |

---

## 4. Files Modified / Created

| Action | File | Changes |
|--------|------|---------|
| CREATE | `modules/auth_decorators.py` | login_required, admin_required |
| CREATE | `scripts/add_indexes.sql` | 8개 인덱스 생성 SQL |
| MODIFY | `routes/project.py` | import 추가, 10개 세션 체크 제거, 7개 에러 로깅 추가 |
| MODIFY | `routes/drawing.py` | import 추가, 6개 세션 체크 제거, 2개 에러 로깅 추가 |
| MODIFY | `routes/delivery.py` | import 추가, 3개 세션 체크 제거 |
| MODIFY | `routes/sales.py` | import 추가, 2개 세션 체크 제거 |
| MODIFY | `routes/production.py` | import 추가, 2개 세션 체크 제거 |
| MODIFY | `routes/auth.py` | import 추가, 6개 admin 체크 → @admin_required |
| MODIFY | `routes/dashboard.py` | import 추가, _is_admin() 삭제, @admin_required 적용 |
| MODIFY | `routes/contract.py` | import 추가, 1개 세션 체크 제거, 1개 에러 로깅 추가 |
| MODIFY | `routes/barcode.py` | import 추가, 1개 세션 체크 제거, 2개 에러 로깅 추가 |
| MODIFY | `routes/material.py` | import 추가, 2개 세션 체크 제거 |
| MODIFY | `routes/technical.py` | import 추가, 1개 세션 체크 제거, 1개 에러 로깅 추가 |
| DELETE | `modules/models.back` | 백업 파일 삭제 |
| DELETE | `routes/project.back` | 백업 파일 삭제 |

---

## 5. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| 데코레이터 순서 오류 | `@route()` 아래에 `@login_required` 배치 (Flask 표준 패턴) |
| `functools.wraps` 누락 시 endpoint name 충돌 | 데코레이터에 `@functools.wraps(f)` 필수 포함 |
| auth.py의 login/register에 데코레이터 오적용 | login, register, logout은 **제외 대상으로 명시** |
| `current_app.logger` 사용 시 application context 필요 | 라우트 핸들러 내에서만 사용하므로 context 보장됨 |
| models.py가 git에서 empty | models.back에 index=True 추가 + 별도 SQL 스크립트 제공 |
