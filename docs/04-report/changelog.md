# Light-Sync Changelog

> Automatic changelog tracking for PDCA completion reports

---

## [2026-03-17] - Phase 6 Auth Decorator + Error Handling + DB Index Optimization

### Overview
Light-Sync ERP Phase 6 (Auth Decorator + Error Handling + DB Index Optimization) PDCA cycle completed with 97% design match rate (9/10 PASS, 1/10 PARTIAL).
Centralized authentication across 36 endpoints via decorators, improved error handling with structured logging in 14 blocks, added 8 database indexes for FK relationships, and cleaned up 435 lines of backup files.

### Added

**New Modules**
- `modules/auth_decorators.py` - Centralized authentication decorators
  - `login_required` - Redirect to login if user_id not in session
  - `admin_required` - Check user_id and role == 'admin' with flash message

**Database Infrastructure**
- `scripts/add_indexes.sql` - 8 database indexes for FK relationships and frequently-filtered columns
  - `ix_projects_is_contracted` - Boolean filter on project list queries
  - `ix_contracts_project_id` - FK relationship optimization
  - `ix_contracts_delivery_due_date` - Date range query optimization
  - `ix_contract_items_contract_id` - FK relationship optimization
  - `ix_deliveries_project_id` - FK relationship optimization
  - `ix_history_logs_project_id` - FK relationship optimization
  - `ix_delivery_photos_delivery_id` - FK relationship optimization
  - `ix_material_orders_contract_item_id` - FK relationship optimization

### Changed

**Routes - Authentication Decorators**
- `routes/project.py` - 10 endpoints decorated with `@login_required`
- `routes/drawing.py` - 6 endpoints decorated with `@login_required`
- `routes/delivery.py` - 3 endpoints decorated with `@login_required`
- `routes/sales.py` - 2 endpoints decorated with `@login_required`
- `routes/production.py` - 2 endpoints decorated with `@login_required`
- `routes/auth.py` - 6 admin endpoints decorated with `@admin_required`
- `routes/dashboard.py` - 1 admin + 1 login endpoints decorated; `_is_admin()` helper deleted
- `routes/contract.py` - 1 endpoint decorated with `@login_required`
- `routes/barcode.py` - 1 endpoint decorated with `@login_required`
- `routes/material.py` - 2 endpoints decorated with `@login_required`
- `routes/technical.py` - 1 endpoint decorated with `@login_required`

**Decorators Summary:**
- Total decorators applied: 36 (30 `@login_required` + 6 `@admin_required`)
- Replaces: 30 inline session checks (5-10 lines each) → 1-line decorator

**Routes - Error Handling**
- `routes/project.py` - 7 error blocks improved: `logger.warning()` + `logger.exception()`
- `routes/auth.py` - 1 error block improved: `logger.exception()`
- `routes/barcode.py` - 2 error blocks improved: `logger.debug()` (encoding fallback, intentional deviation)
- `routes/contract.py` - 1 error block improved: `logger.exception()`
- `routes/drawing.py` - 2 error blocks improved: `logger.exception()`
- `routes/technical.py` - 1 error block improved: `logger.exception()`

**Error Handling Pattern:**
- All bare `except Exception:` converted to structured logging with context
- Flash messages use generic text (no `str(e)` exposure for security)
- All error messages include context information (project_id, action, etc.) for debugging

### Fixed

**Security Issues (3 resolved)**
- ✅ FIX-01: Centralized authentication eliminates risk of missing auth checks on new routes
- ✅ FIX-02: Removed all `str(e)` exposure in user-facing error messages (no internal error leakage)
- ✅ FIX-03: Eliminated 14 bare `except Exception` blocks without logging

**Code Organization Issues**
- ✅ Deleted `modules/models.back` (210 lines) - stale Phase 3 backup
- ✅ Deleted `routes/project.back` (225 lines) - stale Phase 4 backup

**Performance Issues (8 indexes)**
- ✅ Added index on `projects.is_contracted` - accelerates project list filtering
- ✅ Added 7 FK relationship indexes - optimizes joins and foreign key lookups
- ✅ Added index on `contracts.delivery_due_date` - enables fast date range queries

### Quality Metrics

| Metric | Value |
|--------|-------|
| Design Match Rate | **97%** (9/10 PASS, 1/10 PARTIAL) |
| Gap Analysis Iterations | **0** (first pass completion) |
| Decorators Applied | 36 (100% as designed) |
| Error Handlers Improved | 14 (93% as designed, 1 intentional deviation) |
| SQL Indexes Created | 8 (100% as designed) |
| Backup Files Deleted | 2 (435 lines removed) |
| Files Created | 2 (auth_decorators.py, add_indexes.sql) |
| Files Modified | 11 (all route files) |
| Security Compliance | 100% (no `str(e)` exposure, all decorators applied correctly) |

### Migration Notes

**For Deployment:**
1. Apply indexes to production database: `sqlite3 {db_file} < scripts/add_indexes.sql`
2. Verify index creation success: `SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'`
3. Test auth decorator behavior (login redirect on unauthenticated access)
4. Monitor error logs for structured messages (context information should be present)

**Backwards Compatibility:**
- All existing endpoints remain functional (route paths unchanged)
- Auth behavior identical (redirect to login same as before)
- Error flash messages slightly improved (generic instead of internal error text)
- DB schema unchanged (only new indexes added)
- No breaking changes to API or session format

### Code Examples

**Before (inline auth check):**
```python
@project_bp.route('/project_list')
def project_list():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    # ... 50 lines of business logic
```

**After (decorator-based):**
```python
@project_bp.route('/project_list')
@login_required
def project_list():
    # ... 50 lines of business logic
```

**Before (bare exception + error message exposure):**
```python
try:
    # ... contract detail update logic
except Exception as e:
    db.rollback()
    flash(f'오류: {str(e)}', 'danger')  # Exposes internal error
```

**After (structured logging with generic message):**
```python
try:
    # ... contract detail update logic
except Exception as e:
    db.rollback()
    current_app.logger.exception('contract_detail action=%s project=%s', action, project_id)
    flash('처리 중 오류가 발생했습니다.', 'danger')  # Safe, generic message
```

### Known Limitations (Phase 7+ scope)

- Rate limiting per-user not yet implemented (currently global)
- CSRF token not yet extended to AJAX endpoints (next phase)
- Session timeout enforcement not yet logged (monitoring capability)
- No audit log for admin actions yet (Phase 7 scope)

### Next PDCA Cycle

**Phase 7: Security Hardening (Planned)**
- CSP headers implementation
- Session timeout enforcement with logging
- AJAX endpoint CSRF protection
- Audit logging for admin operations
- Target: ~1.5 days

**Phase 8: Performance Monitoring (Planned)**
- Slow query logging (> 100ms queries)
- Index effectiveness metrics
- Auth decorator performance overhead measurement
- Error logging analysis dashboard
- Target: ~2 days

### Lessons Learned

✅ **What Went Well:**
- Decorator pattern is Flask-idiomatic, immediately recognizable by team
- Centralized auth policy eliminates duplicated session checks across 11 files
- YAGNI decision (excluding `role_required`, `permission_required`) kept implementation simple
- Error logging pattern is consistent and easily extended
- 0 iterations needed - design was clear and implementation matched on first pass (97%)
- Backup file cleanup opportune moment improved code hygiene

⚠️ **Areas for Improvement:**
- barcode.py log level decision: Design specified `logger.warning()`, but implementation correctly identified `logger.debug()` as appropriate for normal encoding fallback (no action needed, but shows gap analysis should validate log levels)
- dashboard_view decorator not in design scope, but implemented as security improvement (shows design could be more comprehensive)
- SQL index application strategy unclear - how/when to apply? (recommend Alembic migration planning for Phase 8+)

### Recommendations

1. **Establish Logging Guidelines** - Before Phase 7, document when to use error/warning/debug/info levels
2. **Index Monitoring** - Add slow query logging to measure index effectiveness before Phase 7
3. **Auth Coverage** - Security audit checklist for all endpoints (identify remaining auth gaps if any)
4. **Error Message Audit** - Review all flash messages ensure no `str(e)` exposure remains

---

## [2026-03-17] - Phase 3 Code Refactoring Completion

### Overview
Light-Sync ERP Phase 3 (Code Refactoring) PDCA cycle completed with 100% design match rate (14/14 checkpoints PASS).
Refactoring achieved 41% reduction in project.py, consolidated 12+ duplicate utility functions, and separated concerns into modular Blueprints.

### Added

**New Modules**
- `modules/spec_utils.py` - Centralized spec extraction, validation, and formatting utilities
  - `extract_contract_item_spec()` - Extract spec JSON from form data
  - `validate_contract_item_spec()` - Validate required spec fields per category
  - `format_spec_summary()` - Generate human-readable spec summaries
  - `BOOLEAN_SPEC_FIELDS` - Reusable boolean field definitions for spec schemas

**New Blueprints**
- `routes/material.py` - Material management module (300 LOC)
  - `material_management()` - GET/POST for material list and import
  - `material_detail()` - GET/POST for individual material detail
  - `refresh_admin_statuses_from_material_orders()` - Compute admin status from material orders
  - `sync_material_orders()` - Synchronize all material orders for a project
  - `sync_material_orders_for_contract_item()` - Synchronize material for specific contract item
  - `compute_admin_status_from_orders()` - Calculate admin workflow status

- `routes/barcode.py` - Barcode handling module (250 LOC)
  - `download_barcode_template()` - Generate and serve barcode template (CSV/XLSX)
  - `parse_barcode_csv_rows()` - Parse barcode data from CSV format
  - `parse_barcode_xlsx_rows()` - Parse barcode data from XLSX format
  - Helper functions: `_col_to_letters()`, `_xml_escape()`, `_build_simple_xlsx()`

**Centralized Constants**
- `modules/models/constants.py` - Added workflow status constants
  - `SALES_STATUS_STEPS = ['계약확인', '상세협의중', '협의완료']`
  - `ADMIN_STATUS_STEPS = ['자재확인중', '발주진행중', '발주완료', '입고진행중', '입고완료']`
  - `PROD_STATUS_STEPS = ['자재대기중', '생산대기중', '생산중', '생산완료']`

### Changed

**Route File Consolidation**
- `routes/project.py` - Reduced from 2,150 → 1,266 lines (-884 lines, -41%)
  - Removed material management routes (moved to routes/material.py)
  - Removed barcode handling routes (moved to routes/barcode.py)
  - Removed spec extraction functions (moved to modules/spec_utils.py)
  - Removed duplicate utility functions (consolidated to modules/utils.py)
  - Updated imports to use centralized utilities, constants, and helper functions

- `routes/production.py` - Removed duplicate utility functions
  - Removed local `_parse_date()`, `_to_int()` functions
  - Updated to import from `modules.utils`

- `routes/delivery.py` - Removed duplicate utility functions
  - Removed local `_parse_date()`, `_to_int()` functions
  - Updated to import from `modules.utils`
  - Retained `_parse_datetime_local()` (delivery-specific datetime parsing)

- `routes/sales.py` - Removed duplicate utility functions and constants
  - Removed local `_parse_date()`, `_is_true_value()`, `TRUE_VALUES` definitions
  - Updated to import from `modules.utils` and `modules.models`
  - Retained `_extract_item_spec()` and `_validate_item_spec()` (sales-specific variations)

- `routes/dashboard.py` - Removed duplicate safe_int function
  - Removed local `_safe_int()` definition
  - Updated to import `safe_int` from `modules.utils`

**Blueprint Registration**
- `app.py` - Updated to register new Blueprints
  - Added: `from routes.material import material_bp`
  - Added: `from routes.barcode import barcode_bp`
  - Added: `app.register_blueprint(material_bp)`
  - Added: `app.register_blueprint(barcode_bp)`

**Template Updates**
- `templates/base.html` - Updated material management url_for references
- `templates/dashboard.html` - Updated material management and detail url_for references
- `templates/material_detail.html` - Updated material management and detail url_for references
- `templates/material_management.html` - Updated material management and detail url_for references
- `templates/contract_detail.html` - Updated barcode template download url_for reference

All url_for changes: `project.material_management` → `material.material_management`, `project.material_detail` → `material.material_detail`, `project.download_barcode_template` → `barcode.download_barcode_template`

### Fixed

**Code Duplication Issues (12+ functions consolidated)**
- ✅ Consolidated 4 duplicate `_parse_date()` functions (project.py, production.py, delivery.py, sales.py) → modules/utils.py
- ✅ Consolidated 3 duplicate `_to_int()` functions (project.py, production.py, delivery.py) → modules/utils.py as safe_int
- ✅ Consolidated 2 duplicate `_is_true_value()` + `TRUE_VALUES` (project.py, sales.py) → modules/utils.py
- ✅ Consolidated 1 duplicate `_safe_int()` (dashboard.py) → modules/utils.py

**Code Organization Issues**
- ✅ Separated 8 material-related functions from project.py into routes/material.py Blueprint
- ✅ Separated 6 barcode-related functions from project.py into routes/barcode.py Blueprint
- ✅ Separated 3 spec utility functions from project.py into modules/spec_utils.py
- ✅ Centralized 3 workflow status constants from various routes into modules/models/constants.py

### Quality Metrics

| Metric | Value |
|--------|-------|
| Design Match Rate | **100%** (14/14 checkpoints) |
| Gap Analysis Iterations | **0** (first pass completion) |
| Files Created | 3 (spec_utils.py, material.py, barcode.py) |
| Files Modified | 14 (routes, modules, templates, app.py) |
| Total Files Changed | 17 |
| Code Reduction (project.py) | 884 lines (-41%) |
| Duplicate Functions Eliminated | 12+ |
| New Blueprints | 2 (material_bp, barcode_bp) |
| Target Achievement | **超達成** (1,266 lines vs 1,500 target) |

### Migration Notes

**For Deployment:**
1. Verify new Blueprints (material_bp, barcode_bp) are properly registered in app.py
2. Update any external references to old route names (e.g., `project.material_management` → `material.material_management`)
3. Verify url_for references in templates and Python code point to correct Blueprint names
4. Test material and barcode functionality after deployment

**Cross-Blueprint Dependencies:**
- `routes/project.py` imports material functions: `refresh_admin_statuses_from_material_orders`, `sync_material_orders`, `sync_material_orders_for_contract_item`, `compute_admin_status_from_orders`
- `routes/project.py` imports barcode functions: `parse_barcode_csv_rows`, `parse_barcode_xlsx_rows`, `build_simple_xlsx`
- No circular imports (unidirectional: material.py ← project.py, barcode.py ← project.py)

**Backwards Compatibility:**
- All existing endpoints remain functional (route paths unchanged)
- DB schema unchanged
- API responses unchanged
- Session/user data unchanged
- Only internal code organization changed (transparent to end users)

### Known Limitations (Phase 4+ scope)

- `_date_to_dt_start()` duplicated in project.py:42 and material.py:23 (Phase 4 consolidation candidate)
- `handle_detail_common()` (~700 lines) remains in project.py (Phase 4 service layer extraction)
- production.py spec functions could merge into spec_utils.py (Phase 4 expansion)
- No test automation added (separate PDCA cycle planned)

### Next PDCA Cycle

**Phase 4: Performance Optimization (Planned)**
- Extract service layer from project.py (handle_detail_common and related)
- Remove GET request data synchronization side effects
- Add database query optimization and caching
- Performance profiling and endpoint response time improvements
- Consolidate remaining helper function duplicates
- Target: ~20 hours (estimated based on Phase 3 experience)

### Lessons Learned

✅ **What Went Well:**
- Checkpoint-driven design (14 checkpoints) eliminated ambiguity
- Phased approach (6 sub-phases) reduced complexity effectively
- Achieved 100% match rate on first pass without iteration
- Better than predicted line reduction (1,266 vs 1,433)
- No circular imports despite Blueprint separation

⚠️ **Areas for Improvement:**
- Estimate efficiency underestimated (12h predicted vs 1 session actual)
- Phase 3-6 verification could be done incrementally
- sales.py spec functions not unified (Phase 4 candidate)

---

## [2026-03-17] - Phase 1 Security + Phase 2 Stability Completion

### Overview
Light-Sync ERP Phase 1 (Security) + Phase 2 (Stability) PDCA cycle completed with 100% design match rate.

### Added

**Phase 1: Security Enhancements**
- `config.py` - Environment-based configuration management with ProductionConfig/DevelopmentConfig
- `.env.example` - Template for 11 environment variables (SECRET_KEY, FLASK_DEBUG, DATABASE_URL, etc.)
- CSRF Protection - Flask-WTF CSRFProtect applied globally + fetch/XMLHttpRequest automatic header injection
- Session Security - HttpOnly, Secure, SameSite=Lax cookies + 8-hour expiration
- Admin Endpoint Security - POST method conversion + role-based permission checks for approve_user/reject_user

**Phase 2: Stability Enhancements**
- `modules/db_context.py` - Context manager for safe DB session management with automatic rollback on exceptions
- `modules/utils.py` - Common utilities: safe_int(), parse_date(), is_true_value(), validate_upload()
- Rate Limiting - Flask-Limiter integration: 10/min for login, 3/min for registration, 200/hour global
- Error Handling - 404/500 error handlers with user-friendly error.html template
- File Upload Validation - ALLOWED_EXTENSIONS + MAX_FILE_SIZE checks in validate_upload()
- Structured Logging - RotatingFileHandler with 10MB per file, 5 backup files, rotating logs

**Infrastructure**
- `templates/error.html` - Error page template for 404/500 responses with styled messages
- Logging system - `logs/light_sync.log` with automatic directory creation and rotation

### Changed

**Routes - DB Session Management**
- All 9 route files migrated from manual `SessionLocal()` to context manager pattern
- `routes/auth.py` - Enhanced with input validation, POST conversion, rate limiting
- `routes/production.py` - int casting replaced with safe_int() at 4 locations
- `routes/sales.py` - int casting replaced with safe_int()
- `routes/delivery.py` - int casting replaced with safe_int()
- `routes/drawing.py` - Open redirect prevention added via _safe_next_url()
- Other routes - Context manager pattern applied to all DB operations

**Configuration**
- `app.py` - Config loading from environment, CSRF initialization, error handlers, logging setup
- `config.py` - Central configuration management (SECRET_KEY, SESSION settings, FILE_CONTENT_LENGTH)
- Session management - Conditional env/dev config loading based on FLASK_ENV

**Security Posture**
- Debug mode disabled in production (FLASK_DEBUG=false by default)
- Secret key now random 32-byte hex from environment or generated at runtime
- No hardcoded credentials in codebase

### Fixed

**Critical Security Issues (9/9 resolved)**
- ✅ FR-01: Credentials removed from Git, `.env.example` provided
- ✅ FR-02: secret_key now environment-based with fallback to random generation
- ✅ FR-03: debug=False enforced in production config
- ✅ FR-04: CSRF protection applied globally to all POST operations
- ✅ FR-05: Admin operations (approve/reject) now require POST + permission check
- ✅ FR-06: Default admin password sourced from ADMIN_DEFAULT_PASSWORD env var
- ✅ FR-07: Registration validation for username (≥3 chars), password (≥6 chars), fullname required
- ✅ FR-08: Session timeout set to 8 hours (28800 seconds)
- ✅ FR-09: Secure session cookies (HttpOnly, Secure, SameSite)

**Stability Improvements (8/8 resolved)**
- ✅ FR-10: DB session context manager with automatic rollback and cleanup
- ✅ FR-11: safe_int() utility prevents ValueError on type casting
- ✅ FR-12: File upload validation with extension whitelist and size limits
- ✅ FR-13: Rate limiting on authentication endpoints to prevent brute force
- ✅ FR-14: Exception handling standardized (bare except → except Exception) with logging
- ✅ FR-15: Open redirect prevention using urlparse and relative URL validation
- ✅ Task 2-8: bare except statements replaced with specific Exception handling
- ✅ Task 2-9: Structured logging with RotatingFileHandler

### Quality Metrics

| Metric | Value |
|--------|-------|
| Design Match Rate | 100% (17/17 items) |
| Gap Analysis Iterations | 2 (88% → 100%) |
| Files Modified | 11 (routes, models, app, config) |
| Files Created | 4 (config.py, db_context.py, utils.py, error.html) |
| Templates Updated | 48 (CSRF token injection) |
| Security Issues Fixed | 9 Critical |
| Stability Issues Fixed | 8 High |
| Git Commits | 4 |

### Migration Notes

**For Deployment:**
1. Set environment variables in `.env` (use `.env.example` as template)
2. Run `pip install Flask-WTF Flask-Limiter` (added to requirements.txt)
3. Create `logs/` directory (auto-created by app.py) or ensure write permissions
4. Replace hardcoded credentials with environment variables
5. Verify HTTPS enforcement for Secure cookie flag in production

**Backwards Compatibility:**
- All existing endpoints remain functional
- DB schema unchanged
- URL routes unchanged
- Session cookie format compatible with existing sessions

### Known Limitations (Phase 3+ scope)

- Large files not yet split: `routes/project.py` (2,100 lines) scheduled for Phase 3
- Service layer not extracted: Business logic still in route handlers (Phase 3)
- GET request side effects: Data synchronization on GET not yet removed (Phase 4)
- Partial logging: Only app-level error logging; route-level logging to be expanded (Phase 4)

### Next PDCA Cycle

**Phase 3: Refactoring (Planned)**
- Split `routes/project.py` into material, barcode submodules
- Extract service layer for business logic
- Consolidate duplicate utility functions
- Target: ~1.5 days

**Phase 4: Performance Optimization (Planned)**
- Remove GET request data synchronization
- Add database indexes for common queries
- Implement event-based synchronization
- Target: ~2 days

---

## Version History of Changelog

| Date | Changes | Author |
|------|---------|--------|
| 2026-03-17 | Phase 1 + Phase 2 completion entry created | Claude Code (report-generator) |
