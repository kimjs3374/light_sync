# Light-Sync Improvement Gap Analysis Report

> **Analysis Type**: Design vs Implementation Gap Analysis (Phase 1 + Phase 2)
>
> **Project**: Light-Sync (LED ERP)
> **Analyst**: Claude Code (gap-detector)
> **Date**: 2026-03-17
> **Design Doc**: [light-sync-improvement.design.md](../02-design/features/light-sync-improvement.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Phase 1 (Security) + Phase 2 (Stability) 설계 대비 구현 일치율 검증.
Phase 3 (Refactoring), Phase 4 (Performance)는 미래 작업이므로 분석 범위에서 제외.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/light-sync-improvement.design.md` Section 3-4
- **Implementation**: `config.py`, `app.py`, `routes/auth.py`, `modules/db_context.py`, `modules/utils.py`, `modules/models/db.py`, `routes/drawing.py`, `routes/delivery.py`, `templates/base.html`, `templates/error.html`
- **Design Items Checked**: FR-01 ~ FR-15, Task 2-8 (17 checkpoints total)

### 1.3 Iteration History

| Iteration | Date | Match Rate | Gaps | Action |
|:---------:|------|:----------:|:----:|--------|
| 1 (v2.0) | 2026-03-17 | 88% (15/17) | 3 | Initial Phase 1+2 analysis |
| 2 (v3.0) | 2026-03-17 | 100% (17/17) | 0 | 3 fixes applied and verified |

---

## 2. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Phase 1 Design Match | 100% (9/9) | ✅ |
| Phase 2 Design Match | 100% (8/8) | ✅ |
| **Overall (Phase 1+2)** | **100% (17/17)** | **✅** |

---

## 3. Phase 1: Security -- Detailed Comparison

### FR-01~03: config.py + .env.example + Environment Variables

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `config.py` exists | NEW file | Exists | ✅ |
| `SECRET_KEY` from env | `os.environ.get(...) or secrets.token_hex(32)` | `config.py:10` -- Identical | ✅ |
| `DevelopmentConfig` | `SESSION_COOKIE_SECURE = False` | `config.py:32-33` -- Identical | ✅ |
| `ProductionConfig` | `DEBUG = False` | `config.py:36-37` -- Identical | ✅ |
| `.env.example` exists | NEW file with 11 variables | All 11 variables present | ✅ |
| `MAX_CONTENT_LENGTH` | `50 * 1024 * 1024` | `config.py:25` -- Identical | ✅ |
| `app.py` uses config | `app.config.from_object(ProductionConfig)` | `app.py:24-27` -- Conditional Dev/Prod loading (better) | ✅ |

### FR-04: CSRF Protection

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `CSRFProtect(app)` | In app.py | `app.py:44` | ✅ |
| CSRF meta tag in base.html | `<meta name="csrf-token">` | `base.html:6` | ✅ |
| fetch override JS | X-CSRFToken header injection | `base.html:422-456` -- fetch + XMLHttpRequest (exceeds design) | ✅ |

### FR-05: approve_user / reject_user POST + Admin Check

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `approve_user` POST + admin check | `methods=['POST']`, `session.get('role') != 'admin'` | `auth.py:197-208` -- Identical | ✅ |
| `reject_user` POST + admin check | `methods=['POST']` | `auth.py:211-221` -- Identical (admin check added as bonus) | ✅ |

### FR-06: Admin Default Password from Environment Variable

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `os.environ.get('ADMIN_DEFAULT_PASSWORD', 'admin1234')` | In db.py | `db.py:295` -- Identical | ✅ |

### FR-07: Registration Validation

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| Username >= 3, Password >= 6, Fullname required | Validation block | `auth.py:69-80` -- Identical | ✅ |
| Duplicate check + `except Exception` | Present | `auth.py:84,97` -- Identical | ✅ |

### FR-08~09: Session Security

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| HttpOnly, Secure, SameSite=Lax | In Config class | `config.py:14-16` -- Identical | ✅ |
| 8-hour lifetime | `28800` (design) vs `timedelta(hours=8)` (impl) | Equivalent -- Flask accepts both | ✅ |
| `session.permanent = True` | Required for lifetime to apply | `app.py:55-57` -- Implemented | ✅ |

**Phase 1: 9/9 = 100%**

---

## 4. Phase 2: Stability -- Detailed Comparison

### FR-10: DB Session Context Manager

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `modules/db_context.py` with `get_db()` | contextmanager with rollback/close | `db_context.py:1-15` -- Identical | ✅ |
| All 9 route files use `get_db()` | `with get_db() as db:` pattern | All 9 files confirmed (`from modules.db_context import get_db`) | ✅ |
| No raw `SessionLocal()` in routes | Eliminated | Only in backup file `project.back` (inactive) | ✅ |

**Score: 1/1**

### FR-11: safe_int() Utility

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `safe_int()` in `modules/utils.py` | Function defined | `utils.py:17-22` -- Identical | ✅ |
| Used in production.py (4 locations) | Lines 510, 543, 654, 729 | `production.py:508,541,652,727` -- Present | ✅ |
| Used in sales.py | Line 304 | `sales.py:304` -- Present | ✅ |
| Also used in contract.py, project.py, technical.py | Not in original design | Broader adoption than designed | ✅ |

**Note**: `dashboard.py:62` retains a local `_safe_int()` duplicate -- Phase 3 cleanup scope.

**Score: 1/1**

### FR-12: File Upload Validation

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `validate_upload()` in utils.py | Function + ALLOWED_EXTENSIONS | `utils.py:30-40` -- Identical | ✅ |
| Called from drawing upload | Import and call before processing | `drawing.py:9` imports, `drawing.py:110-113` calls with early return | ✅ |
| Called from delivery photo upload | Import and call before processing | `delivery.py:11` imports, `delivery.py:405-408` calls with early return | ✅ |

**Score: 1/1** (previously 0.5 -- FIXED in iteration 2)

### FR-13: Rate Limiting

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| Limiter init (200/hour global) | `Limiter(app=app, ...)` | `app.py:47-52` -- Match | ✅ |
| Login: 10/min | `@limiter.limit("10 per minute")` | `app.py:79` -- Blueprint-level 10/min on auth_bp | ✅ |
| Register: 3/min | `@limiter.limit("3 per minute")` per-endpoint | `app.py:88-91` -- Individual endpoint override after blueprint registration | ✅ |

Implementation uses `app.view_functions['auth.register']` wrapping post-blueprint-registration to apply the stricter 3/min limit specifically to register while keeping 10/min for other auth endpoints. Functionally equivalent to the design's per-endpoint decorator approach.

**Score: 1/1** (previously 0.5 -- FIXED in iteration 2)

### FR-14: Error Handlers + Logging

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `@app.errorhandler(404)` | render error.html | `app.py:105-107` -- Present | ✅ |
| `@app.errorhandler(500)` | render error.html + log | `app.py:109-112` -- Present with logging | ✅ |
| `templates/error.html` | NEW file | Exists, functional | ✅ |
| RotatingFileHandler logging | `RotatingFileHandler('logs/light_sync.log', maxBytes=10_000_000, backupCount=5)` | `app.py:34-40` -- Identical parameters | ✅ |
| Log format | `'%(asctime)s %(levelname)s [%(name)s] %(message)s'` | `app.py:36-37` -- Identical format string | ✅ |
| `app.logger.error()` in 500 handler | `app.logger.error(f"Internal error: {e}")` | `app.py:111` -- Identical | ✅ |

**Score: 2/2** (previously 1/2 -- FIXED in iteration 2)

### FR-15: Open Redirect Fix

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `_safe_next_url()` with urlparse | Block `//`, verify no scheme/netloc | `drawing.py:35-42` -- Equivalent protection | ✅ |
| Used in upload/delete redirects | Safety redirects | `drawing.py:103,214,277,328,332` -- Used | ✅ |

**Score: 1/1**

### Task 2-8: bare except -> except Exception

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `db.py` bare except -> `except Exception` | Fix in init_db() | `db.py:300` -- `except Exception:` | ✅ |

**Score: 1/1**

**Phase 2: 8/8 = 100%**

---

## 5. Gap Summary

### Missing Features (Design O, Implementation X)

None.

### Added Features (Design X, Implementation O)

| # | Item | Location | Description |
|---|------|----------|-------------|
| 1 | `@app.errorhandler(403)` | `app.py:114-116` | Extra error handler |
| 2 | XMLHttpRequest CSRF override | `base.html:444-455` | Design only covers fetch |
| 3 | `storage_uri="memory://"` | `app.py:51` | Explicit limiter storage |
| 4 | `parse_date()`, `is_true_value()` | `modules/utils.py:4-27` | Phase 3 functions added early |
| 5 | `os.makedirs('logs', exist_ok=True)` | `app.py:34` | Auto-create logs directory |

### Changed Features (Design != Implementation)

| # | Item | Design | Implementation | Impact |
|---|------|--------|----------------|--------|
| 1 | Rate limit application method | Per-endpoint decorator | view_functions wrapping post-registration | None (functionally identical) |
| 2 | Error template params | `code`, `message` | `error_code`, `error_message` | None |
| 3 | Session lifetime type | `28800` (int) | `timedelta(hours=8)` | None |

---

## 6. Match Rate Calculation

### Phase 1 (9 items)

| # | FR | Description | Score |
|---|-----|-------------|:-----:|
| 1 | FR-01 | config.py with env vars | 1.0 |
| 2 | FR-02 | .env.example template | 1.0 |
| 3 | FR-03 | app.py config loading | 1.0 |
| 4 | FR-04 | CSRF Protection | 1.0 |
| 5 | FR-05 | approve/reject POST + admin check | 1.0 |
| 6 | FR-06 | Admin password from env | 1.0 |
| 7 | FR-07 | Registration validation | 1.0 |
| 8 | FR-08 | Session cookie security | 1.0 |
| 9 | FR-09 | Session 8hr lifetime | 1.0 |
| | | **Phase 1 Total** | **9.0/9 = 100%** |

### Phase 2 (8 items)

| # | FR/Task | Description | Score | Delta |
|---|---------|-------------|:-----:|:-----:|
| 1 | FR-10 | DB Session Context Manager | 1.0 | - |
| 2 | FR-11 | safe_int() utility + usage | 1.0 | - |
| 3 | FR-12 | validate_upload() usage in routes | 1.0 | +0.5 |
| 4 | FR-13 | Rate Limiting (per-endpoint) | 1.0 | +0.5 |
| 5 | FR-14a | Error handlers (404/500) + error.html | 1.0 | - |
| 6 | FR-14b | Logging (RotatingFileHandler) | 1.0 | +1.0 |
| 7 | FR-15 | Open Redirect fix | 1.0 | - |
| 8 | Task 2-8 | bare except fix | 1.0 | - |
| | | **Phase 2 Total** | **8.0/8 = 100%** | **+2.0** |

### Combined

```
Phase 1:  9.0 /  9 = 100%
Phase 2:  8.0 /  8 = 100%
-----------------------------
Total:   17.0 / 17 = 100%

Previous: 15.0 / 17 =  88%
Delta:    +2.0       = +12%
```

---

## 7. Fixes Verified (Iteration 2)

| # | Gap (from v2.0) | Fix Applied | Verification |
|---|-----------------|-------------|--------------|
| 1 | FR-14b: RotatingFileHandler missing | `app.py:33-40` -- RotatingFileHandler with `logs/light_sync.log`, 10MB max, 5 backups. `app.py:111` -- `app.logger.error()` in 500 handler. | Matches design Section 4.5 exactly |
| 2 | FR-12: validate_upload() dead code | `drawing.py:9` imports, `drawing.py:110-113` calls with early-return on failure. `delivery.py:11` imports, `delivery.py:405-408` calls in photo upload. | Both upload endpoints now protected |
| 3 | FR-13: Register uses 10/min instead of 3/min | `app.py:87-91` applies `limiter.limit("3 per minute")` to `auth.register` view function individually after blueprint registration. | Register: 3/min, other auth: 10/min |

---

## 8. Design Document Updates Recommended

| Item | Description |
|------|-------------|
| 403 handler | Document the extra error handler in design |
| XMLHttpRequest CSRF | Add XHR override to design Section 3.3 |
| Error template param names | Update to `error_code`/`error_message` |
| logs directory auto-creation | Add `os.makedirs('logs', exist_ok=True)` to design Section 4.5 |

---

## 9. Assessment

**Match Rate: 100% -- "Design and implementation match well."**

All 17 Phase 1 + Phase 2 checkpoints are now fully implemented as designed. The 3 gaps identified in iteration 1 (v2.0) have been resolved:

1. RotatingFileHandler logging is operational with correct parameters.
2. `validate_upload()` is actively called in both drawing upload and delivery photo upload routes.
3. Register endpoint has its own stricter 3/min rate limit separate from the 10/min auth blueprint limit.

Minor differences (error template param naming, session lifetime type) are cosmetic and functionally equivalent. Added features (403 handler, XHR CSRF, early Phase 3 utils) exceed design scope without negative impact.

**Recommendation**: Proceed to `/pdca report light-sync-improvement` for Phase 1+2 completion report, then begin Phase 3 (Refactoring) planning.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Phase 1 only analysis | Claude Code |
| 2.0 | 2026-03-17 | Full Phase 1 + Phase 2 gap analysis (88%) | Claude Code (gap-detector) |
| 3.0 | 2026-03-17 | Re-analysis after 3 fixes: 88% -> 100% | Claude Code (gap-detector) |
