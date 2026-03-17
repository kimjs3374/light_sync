# Archive Index - 2026-03

| Feature | Phase | Match Rate | Archived Date | Documents |
|---------|-------|:----------:|:-------------:|:---------:|
| light-sync-improvement | Phase 1 (Security) + Phase 2 (Stability) | 100% (17/17) | 2026-03-17 | 4 |
| phase-3-refactoring | Phase 3 (Refactoring) | 100% (14/14) | 2026-03-17 | 4 |
| phase-4-service-layer | Phase 4 (Service Layer) | 100% (9/9) | 2026-03-17 | 4 |
| phase-5-full-service-layer | Phase 5 (Full Service Layer) | 95% (12/12) | 2026-03-17 | 4 |
| phase-6-auth-error-optimization | Phase 6 (Auth Decorator + Error Handling + DB Index) | 97% (9/10) | 2026-03-17 | 4 |
| ux-improvements-batch | UX 개선 5종 (검색/비번/페이지네이션/알림/종합현황) | 95% (20/21) | 2026-03-17 | 4 |
| warranty-as | 하자보증/AS 관리 (관급자재 Phase 9) | 99% (11/11) | 2026-03-17 | 4 |
| product-catalog | 품목관리 (나라장터 G2B API 단가 연동) | 98% (65/66) | 2026-03-17 | 4 |

## product-catalog

- **Duration**: 2026-03-17 (1 session, CTO Team Mode)
- **Iterations**: 0 (first-pass 98%)
- **Key Result**: 나라장터 API 267건 자동 동기화, 영업관리/주간보고서 금액 연동, 품목 분리(품목명/모델명/규격)
- **New Modules**: services/g2b_catalog_sync.py, routes/catalog.py, templates/catalog_list.html
- **Modified**: sales.py, report.py, sales_list.html, report_weekly.html, admin_settings.html

### Documents

| Document | File |
|----------|------|
| Plan | [product-catalog.plan.md](product-catalog/product-catalog.plan.md) |
| Design | [product-catalog.design.md](product-catalog/product-catalog.design.md) |
| Analysis | [product-catalog.analysis.md](product-catalog/product-catalog.analysis.md) |
| Report | [product-catalog.report.md](product-catalog/product-catalog.report.md) |

---

## warranty-as

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 99%)
- **Key Result**: 3 new models (Warranty, WarrantyCase, WarrantyCaseLog), 7 defect types, 4-step AS workflow, 7 new files + 3 modified
- **New Modules**: services/warranty_actions.py, routes/warranty.py, 4 templates

### Documents

| Document | File |
|----------|------|
| Plan | [warranty-as.plan.md](warranty-as/warranty-as.plan.md) |
| Design | [warranty-as.design.md](warranty-as/warranty-as.design.md) |
| Analysis | [warranty-as.analysis.md](warranty-as/warranty-as.analysis.md) |
| Report | [warranty-as.report.md](warranty-as/warranty-as.report.md) |

---

## ux-improvements-batch

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 1 (95% -> Gap fix)
- **Key Result**: 5 features, 8 new files, 16 modified files, 24 total files changed
- **New Modules**: pagination.py, notification_utils.py, notification.py, overview.py
- **New Templates**: pagination.html, change_password_modal.html, notification_center.html, project_overview.html

### Documents

| Document | File |
|----------|------|
| Plan | [ux-improvements-batch.plan.md](ux-improvements-batch/ux-improvements-batch.plan.md) |
| Design | [ux-improvements-batch.design.md](ux-improvements-batch/ux-improvements-batch.design.md) |
| Analysis | [ux-improvements-batch.analysis.md](ux-improvements-batch/ux-improvements-batch.analysis.md) |
| Report | [ux-improvements-batch.report.md](ux-improvements-batch/ux-improvements-batch.report.md) |

---

## phase-6-auth-error-optimization

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 97%)
- **Key Result**: 36 decorators (30 login + 6 admin), 14 error handlers improved, 8 DB indexes, 2 backup files deleted (435 lines)
- **New Modules**: modules/auth_decorators.py, scripts/add_indexes.sql

### Documents

| Document | File |
|----------|------|
| Plan | [plan.md](phase-6-auth-error-optimization/plan.md) |
| Design | [design.md](phase-6-auth-error-optimization/design.md) |
| Analysis | [analysis.md](phase-6-auth-error-optimization/analysis.md) |
| Report | [report.md](phase-6-auth-error-optimization/report.md) |

---

## phase-5-full-service-layer

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 95%)
- **Key Result**: 5 routes 3,380 -> 1,884 lines (-44%), 35 handlers extracted into 6 service modules
- **New Modules**: services/production_actions.py, delivery_actions.py, material_actions.py, sales_actions.py, dashboard_actions.py, dashboard_utils.py

### Documents

| Document | File |
|----------|------|
| Plan | [phase-5-full-service-layer.plan.md](phase-5-full-service-layer/phase-5-full-service-layer.plan.md) |
| Design | [phase-5-full-service-layer.design.md](phase-5-full-service-layer/phase-5-full-service-layer.design.md) |
| Analysis | [phase-5-full-service-layer.analysis.md](phase-5-full-service-layer/phase-5-full-service-layer.analysis.md) |
| Report | [phase-5-full-service-layer.report.md](phase-5-full-service-layer/phase-5-full-service-layer.report.md) |

---

## phase-4-service-layer

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 100%)
- **Key Result**: project.py 1,260 -> 672 lines (-47%), handle_detail_common 697 -> 72 lines (-90%)
- **New Modules**: services/project_actions.py, contract_actions.py, barcode_actions.py, contact_actions.py

### Documents

| Document | File |
|----------|------|
| Plan | [phase-4-service-layer.plan.md](phase-4-service-layer/phase-4-service-layer.plan.md) |
| Design | [phase-4-service-layer.design.md](phase-4-service-layer/phase-4-service-layer.design.md) |
| Analysis | [phase-4-service-layer.analysis.md](phase-4-service-layer/phase-4-service-layer.analysis.md) |
| Report | [phase-4-service-layer.report.md](phase-4-service-layer/phase-4-service-layer.report.md) |

---

## phase-3-refactoring

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 100%)
- **Key Result**: project.py 2,150 -> 1,266 lines (-41%), 12+ duplicates eliminated
- **New Modules**: spec_utils.py, routes/material.py, routes/barcode.py

### Documents

| Document | File |
|----------|------|
| Plan | [phase-3-refactoring.plan.md](phase-3-refactoring/phase-3-refactoring.plan.md) |
| Design | [phase-3-refactoring.design.md](phase-3-refactoring/phase-3-refactoring.design.md) |
| Analysis | [phase-3-refactoring.analysis.md](phase-3-refactoring/phase-3-refactoring.analysis.md) |
| Report | [phase-3-refactoring.report.md](phase-3-refactoring/phase-3-refactoring.report.md) |

---

## light-sync-improvement

- **Duration**: 2026-03-17 (1 day)
- **Iterations**: 2 (88% -> 100%)
- **Files Modified**: 11 routes/modules + 48 templates
- **Files Created**: 4 (config.py, db_context.py, utils.py, error.html)

### Documents

| Document | File |
|----------|------|
| Plan | [light-sync-improvement.plan.md](light-sync-improvement/light-sync-improvement.plan.md) |
| Design | [light-sync-improvement.design.md](light-sync-improvement/light-sync-improvement.design.md) |
| Analysis | [light-sync-improvement.analysis.md](light-sync-improvement/light-sync-improvement.analysis.md) |
| Report | [light-sync-improvement.report.md](light-sync-improvement/light-sync-improvement.report.md) |
