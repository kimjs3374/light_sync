---
name: Mobile Responsive Design Spec
description: Light-Sync ERP mobile responsive strategy - 90+ templates, mobile-table.js auto-stacking, 4 breakpoints, overflow-x fix
type: project
---

Mobile responsive design specification created 2026-03-23.

**Why:** Only ~16 of 90+ templates had mobile support. The ERP is used on-site by field workers with phones.

**How to apply:**
- Design doc at `docs/02-design/mobile-responsive-design.md`
- Phase 1 (P0): magnatech.css global changes + base.html timeline fix
- Phase 2 (P1-P2): Dashboard + 6 list pages filter collapse
- Phase 3 (P3): Detail/form pages minor grid fixes
- Phase 4 (P4): Long tail -- most templates auto-handled by mobile-table.js
- Key fix: `overflow-x: visible !important` must be scoped to `:has(.mobile-stack-table)` only
- `no-stack-table` tables (BOM, reports, input tables) must keep horizontal scroll
- Timeline panel needs CSS class extraction from inline styles
