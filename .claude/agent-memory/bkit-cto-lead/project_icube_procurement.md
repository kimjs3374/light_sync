---
name: icube-procurement Phase 2 Complete
description: iCUBE -> PostgreSQL 마이그레이션 + 발주서 CRUD + PDF + 이메일 발송 Phase 2 구현 완료
type: project
---

icube-procurement Phase 2 (마이그레이션 + 발주서 + 이메일) PDCA 완료 (2026-03-18).

**Phase 1 (완료 2026-03-17):** iCUBE 직접 조회 - vendor.py + icube_db.py
**Phase 2 (완료 2026-03-18):** iCUBE -> PostgreSQL 마이그레이션, 자체 DB 전환

**Phase 2 구현 파일:**
- modules/models/entities.py: 7개 모델 추가 (Vendor, Item, PurchaseOrder, PurchaseOrderItem, PurchaseOrderHistory, ReceivingHistory, EmailHistory)
- scripts/migrate_icube.py: iCUBE -> PostgreSQL 멱등 마이그레이션
- routes/vendor.py: 자체 DB 조회로 전환 (icube_db 의존 제거)
- routes/purchase_order.py: 발주서 CRUD + PDF + 이메일 (10 routes)
- templates/po_list.html, po_create.html, po_detail.html
- modules/services/po_pdf.py: ReportLab PDF 생성 (한글 폰트)
- modules/services/email_sender.py: SMTP 발송 (DRY_RUN 지원)

**마이그레이션 결과:** vendors 3,714 / items 1,835 / PO history 367 / RCV history 3,236

**Why:** iCUBE SQL Server 실시간 의존성 제거. 자체 DB에서 거래처/품목 관리 + 발주서 작성/PDF/이메일 업무 디지털화.

**How to apply:** Phase 3 (입고/거래명세서) 구현 시 PurchaseOrder/Vendor 모델 활용. icube_db.py는 마이그레이션 스크립트에서만 사용. SMTP_DRY_RUN=true에서 false로 전환 시 실제 발송 시작.
