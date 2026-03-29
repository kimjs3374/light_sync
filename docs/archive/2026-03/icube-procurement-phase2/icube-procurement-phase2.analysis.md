# icube-procurement Phase 2 Gap Analysis

> **Date**: 2026-03-18
> **Design**: icube-procurement-phase2.design.md
> **Match Rate**: 100%

---

## Checklist

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1 | entities.py - 7 models (Vendor, Item, PurchaseOrder, PurchaseOrderItem, PurchaseOrderHistory, ReceivingHistory, EmailHistory) | PASS | All models added with correct fields and relationships |
| 2 | __init__.py - New model exports | PASS | All 8 exports added (including PO_STATUS_CHOICES) |
| 3 | migrate_icube.py - Idempotent migration script | PASS | Tested 2x runs, 0 duplicates on re-run |
| 4 | vendor.py - Self DB queries (not iCUBE) | PASS | Fully rewritten to use SQLAlchemy/PostgreSQL |
| 5 | purchase_order.py - CRUD + PDF + Email | PASS | 10 routes: list, create, detail, edit, delete, status, pdf, email, vendor search, item search |
| 6 | po_list.html - Purchase order list | PASS | Stats cards, search/filter, pagination, status badges |
| 7 | po_create.html - Purchase order create form | PASS | Vendor select, dynamic item rows, auto-calc, item search modal |
| 8 | po_detail.html - Purchase order detail | PASS | Info cards, amount summary, item table, edit/delete modals, email send, PDF preview, status change |
| 9 | po_pdf.py - PDF generation | PASS | ReportLab with Korean font (malgun.ttf), company format |
| 10 | email_sender.py - SMTP email | PASS | DRY_RUN support, PDF attachment, error handling |
| 11 | app.py - Blueprint registration | PASS | purchase_order_bp registered |
| 12 | base.html - Sidebar menu | PASS | "발주관리" added between 구매관리 and 조달내역 |
| 13 | .env - SMTP environment variables | PASS | SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_DRY_RUN |

## Data Verification

| Table | Expected | Actual |
|-------|----------|--------|
| vendors | ~3,500 | 3,714 |
| items | 1,835 | 1,835 |
| purchase_order_history | 367 | 367 |
| receiving_history | 3,236 | 3,236 |

## Constraints Verified

- [x] Migration script idempotent (verified 2x runs)
- [x] iCUBE DB read-only (no writes)
- [x] SMTP_DRY_RUN=true prevents actual email sending
- [x] vendor_detail.html tabs/chart preserved (data source changed)
- [x] table-layout:fixed + colgroup pattern maintained (7-column structure)
- [x] Abnormal date filtered (22231115 -> skipped)
- [x] login_required on all routes
- [x] CSRF protection on all POST forms

## Gap Count: 0

**Match Rate: 100%**
