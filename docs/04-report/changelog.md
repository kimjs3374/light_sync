# Light-Sync Changelog

> Automatic changelog tracking for PDCA completion reports

---

## [2026-03-18] - dept-weekly-report 부서별 주간보고서 자동화

### Overview
Light-Sync ERP 부서별 주간보고서(dept-weekly-report) PDCA 완료. Match Rate 100% (FR 6/6, Design 100%, Gap 0건), Iteration 0회 달성.
영업부 전용 주간보고서를 session['user_group'] 기반 자동 부서 판별 + 3개 부서별 맞춤형 보고서(영업부/생산부/관리부)로 확장.
부서별 자동 액세스 제어(403) + admin 전체 부서 조회 드롭다운 + 인쇄 기능(landscape) 완성.

### Added

**New Backend Functions**
- `routes/report.py` - _resolve_dept() 부서 판별 + 접근 제어
  - dept 파라미터 있으면 admin만 허용
  - dept 파라미터 없으면 session['user_group'] 기반 자동 판별
  - 기타 그룹 / 비admin 타부서 접근 → 403 Forbidden
- `_weekly_production()` - 생산부 보고서
  - 주간 요약: 생산중/납품준비/납품완료/AS접수 건수
  - 생산 공정 현황: 현장별 공정 진행률(%) + 완료된 현장 제외
  - 납품 진행 현황: 예정일 기준 정렬
  - AS/하자보증 현황: 미완료 케이스만
- `_weekly_management()` - 관리부 보고서
  - 주간 요약: 발주건수/입고건수/검수대기/발주총액
  - 자재 발주 현황: 현장별 발주율(%) + 미완료 현장만
  - 발주서 현황: 금액 합계행 포함
  - 입고 검수 현황: 첫 품목명 + "외 N건" 형식

**New Templates**
- `templates/report_weekly_production.html` - 생산부 보고서 (340줄)
  - 4개 섹션, page-break로 인쇄 페이지 분리
  - 진행률 프로그레스바 시각화
  - 상태 배지(대기/진행/완료)
- `templates/report_weekly_management.html` - 관리부 보고서 (350줄)
  - 4개 섹션, tfoot 합계행
  - 발주율 프로그레스바
  - 금액 천 단위 포맷팅

### Changed

**Route File**
- `routes/report.py` - 469줄 전체 재작성
  - DEPT_MAP / DEPT_LABELS 추가
  - _parse_week_range() 날짜 범위 파싱 추가
  - _weekly_sales() 기존 로직 함수 추출 (호환성 100%)
  - weekly_report() 라우터 → 부서별 분기 구현

**Template Updates**
- `templates/report_weekly.html` - admin 부서 선택 드롭다운 추가 (lines 150-158)
  - onchange="this.form.submit()" 즉시 전환
  - 비admin일 때 숨김
  - select name="dept" 옵션: sales/production/management

### Fixed

**Access Control**
- ✅ 부서별 자동 판별: 로그인 사용자 user_group → 자동 보고서 제공
- ✅ 비admin 접근 제어: 타부서 접근 시도 → 403 Forbidden
- ✅ admin 권한: ?dept 파라미터로 전체 부서 조회 가능

**Data Accuracy**
- ✅ 생산부 공정 진행률: done/total * 100 (완료된 현장 제외)
- ✅ 관리부 발주율: ordered/total * 100 (완료된 현장 제외)
- ✅ 금액 집계: SUM() 쿼리로 정확한 합계
- ✅ 기간별 필터: week_start~week_end 범위만 집계

### Quality Metrics

| Metric | Value |
|--------|-------|
| Design Match Rate | **100%** (FR 6/6, Design 100%, Gap 0) |
| Gap Analysis Iterations | **0** (first pass completion) |
| Files Created | 2 (production.html, management.html) |
| Files Modified | 2 (report.py, report_weekly.html) |
| Total LOC (Routes) | 469줄 |
| Total LOC (Templates) | ~1,040줄 |
| DB Model Changes | 0 (기존 모델 재사용) |
| Backwards Compatibility | 100% (/report/weekly URL 유지) |

### Migration Notes

**For Deployment:**
1. routes/report.py 전체 교체 (부서 판별 + 3개 함수)
2. templates/ 2개 신규 템플릿 추가 (production/management)
3. templates/report_weekly.html admin 드롭다운 추가
4. 기존 /report/weekly 링크 동일하게 동작 (URL 변경 없음)

**User Groups Supported:**
- '영업부' → sales (고정)
- '생산부' → production (고정)
- '관리부', '경영관리부' → management (동일)
- admin → 모든 부서 + 드롭다운

---

## [2026-03-18] - material-po-bom-integration BOM-발주서-자재관리 통합 연동

### Overview
BOM 소요자재 부족분에서 거래처별 발주서 1클릭 자동 생성, bom_item_id FK 기반 발주-BOM 양방향 추적 구현. Match Rate 97% (FR 7/7, Gap 1건 기능 목적 충족), Iteration 0회 달성.
PurchaseOrderItem/MaterialOrder에 nullable FK 2개 추가로 기존 데이터 완전 하위 호환을 유지하면서 자재 조달 end-to-end 파이프라인 가시성 확보.

### Added

**New API**
- `POST /bom/create-po-from-requirement` (`routes/bom.py:432`) — 소요자재 선택 → supplier 그룹핑 → 거래처별 PurchaseOrder 자동 생성
  - Vendor.name ilike 매칭 + 없으면 Vendor 자동 생성
  - PurchaseOrderItem.bom_item_id 자동 설정
  - 1건: PO 상세 redirect / N건: PO 목록 redirect + flash

**Helper**
- `_get_latest_receiving_prices()` (`routes/bom.py`) — 최근 입고 단가 조회

### Changed

**Data Model**
- `modules/models/entities.py` — FK 2개 추가
  - `PurchaseOrderItem.bom_item_id` (Integer, FK→bom_items.id, nullable=True)
  - `MaterialOrder.bom_item_id` (Integer, FK→bom_items.id, nullable=True)
- `modules/models/db.py` — PostgreSQL ALTER TABLE 2건 (try/except 멱등성 패턴)

**Logic Improvements**
- `routes/bom.py` `material_requirement()` — 소요량 계산 이중화
  - 1차: bom_item_id 기반 PurchaseOrderItem 발주량 (취소 PO 자동 제외)
  - 2차: MaterialOrder 기반 fallback (기존 데이터 하위 호환)
  - max(ordered_via_po, ordered_via_mo) 중복 방지
- `routes/purchase_order.py` `_sync_po_to_material_orders()` — bom_item_id 있으면 BOM 경로 정확 매칭, 없으면 품명 유사도 fallback
- `routes/purchase_order.py` `po_detail()` — BomItem → BomHeader joinedload (N+1 쿼리 방지)

**UI**
- `templates/bom_requirement.html` — 체크박스(shortage>0 행) + 전체선택 + "선택 자재 발주서 생성" 버튼 + 거래처별 그룹핑 프리뷰 모달 + 거래처 컬럼 추가
- `templates/po_detail.html` — BOM 연결 배지 컬럼 (bom_item_id 있는 품목: BomHeader.product_name 표시)

### Quality Metrics

| Metric | Value |
|--------|-------|
| Design Match Rate | **97%** (FR 7/7, Gap 1건 기능 목적 충족) |
| Gap Count | **1건** (GET `/api/bom/requirement-for-po` → 클라이언트 JS 대체) |
| Iteration 횟수 | **0회** |
| 설계 초과 구현 | 4건 (project_id/created_by 설정, 취소 PO 제외, 거래처 컬럼, joinedload) |
| Files Modified | 6 (entities.py, db.py, bom.py, purchase_order.py, bom_requirement.html, po_detail.html) |
| Backwards Compatibility | 100% (nullable FK, fallback 로직 유지) |

### Migration Notes

**For Deployment:**
1. `init_db()` 실행 시 PostgreSQL ALTER TABLE 자동 적용 (bom_item_id 컬럼 2건)
2. 기존 PO/MaterialOrder 데이터: bom_item_id=NULL — 기존 동작 그대로 유지
3. 신규 발주서 생성(소요자재 페이지 경유): bom_item_id 자동 설정

**Backwards Compatibility:**
- 기존 발주서 생성/수정/삭제 CRUD 100% 정상 동작
- 기존 MaterialOrder 데이터: bom_item_id=NULL에서 기존 품명 유사도 매칭 그대로 동작
- 입고 CRUD 변경 없음

---

## [2026-03-18] - item-management 품목관리 CRUD + 분류 체계

### Overview
Light-Sync ERP item-management 피처 PDCA 완료. Match Rate 100% (FR 6/6, 구현 파일 8/8, Scope 7/7, NFR 3/3), Gap 0건, Iteration 0회 달성.
iCUBE SITEM 1,835건 품목 데이터에 category/manufacturer/note 분류 체계 추가 및 전용 CRUD 관리 화면 구현. USE_YN 매핑 버그 수정으로 데이터 신뢰성 동시 확보.

### Added

**New Route**
- `routes/item.py` — 품목관리 CRUD Blueprint
  - `item_list()` — 품목 목록 (페이지네이션 50건, 통합 검색, 카테고리 필터)
  - `item_detail()` — 품목 상세/수정
  - `item_create()` — 품목 신규 등록 (품번 중복 체크 포함)
  - `item_deactivate()` — 품목 비활성화 (삭제 대신)
  - `api_item_categories()` — `/api/item/categories` datalist 자동완성용

**New Templates**
- `templates/item_list.html` — 품목 목록 (table-sm 0.8rem, 50건/페이지, 카테고리 필터, 통합 검색)
- `templates/item_detail.html` — 품목 상세/수정 (거래처 자동완성, 카테고리 datalist)
- `templates/item_create.html` — 품목 신규 등록 (거래처 자동완성, 카테고리 datalist)

### Changed

**Model Extension**
- `modules/models/entities.py` — Item 모델 필드 추가
  - `category` (String 50, nullable) — 품목 분류
  - `manufacturer` (String 100, nullable) — 제조사/납품업체
  - `note` (Text, nullable) — 비고
  - `is_active` (Boolean, default=True) — 비활성화 지원

**Infrastructure**
- `modules/models/db.py` — init_db() 내 PostgreSQL ALTER TABLE 자동 마이그레이션 추가 (컬럼 중복 예외 처리로 반복 실행 안전)
- `app.py` — item_bp Blueprint 등록
- `templates/base.html` — 사이드바 관리부 섹션에 "품목관리" 메뉴 추가

### Fixed

**Data Integrity Bug**
- `scripts/migrate_icube.py` — iCUBE USE_YN 매핑 버그 수정
  - 버그: `USE_YN == 'Y'` (`'Y' == True`는 Python에서 False — 전 품목 is_active=False로 등록됨)
  - 수정: `str(USE_YN) in ('1', 'Y', 'y')` 패턴으로 변경
  - 영향: migrate_vendors 업데이트 경로 수정 (migrate_items는 이미 정상 패턴 사용 중)

### Quality Metrics

| Metric | Value |
|--------|-------|
| Design Match Rate | **100%** (FR 6/6, Files 8/8, Scope 7/7, NFR 3/3) |
| Gap Count | **0** |
| Gap Analysis Iterations | **0** (first pass completion) |
| Overall Score | 97/100 (코드 품질 -3: SQLAlchemy deprecated API) |
| Files Created | 4 (item.py, item_list.html, item_detail.html, item_create.html) |
| Files Modified | 5 (entities.py, db.py, app.py, base.html, migrate_icube.py) |
| iCUBE 품목 데이터 | 1,835건 (분류 체계 추가 대상) |

### Migration Notes

**For Deployment:**
1. `init_db()` 실행 시 PostgreSQL에 ALTER TABLE 자동 적용 (category, manufacturer, note 컬럼 추가)
2. iCUBE 마이그레이션 재실행으로 USE_YN 수정 반영: `python scripts/migrate_icube.py`
3. 기존 품목 is_active 상태 확인: 재마이그레이션 전 is_active=False 품목 수 확인 권장

**Backwards Compatibility:**
- 기존 발주서/BOM 품목 검색 API 경로 변경 없음 (별도 라우트 유지)
- 신규 필드 모두 nullable — 기존 품목 데이터 호환성 유지

### Next PDCA Cycle

**Backlog (item-management 범위 외)**
- 거래처별 단가 이력 연동 (VendorItem 테이블 연결)
- 재고 수량 관리
- SQLAlchemy 2.x deprecated API 전체 마이그레이션

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
