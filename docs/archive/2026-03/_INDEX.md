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
| nas-folder-sync | NAS 폴더 → ERP 현장 자동 동기화 (.lnk + 연도 자동 결정) | 100% | 2026-03-17 | 1 |
| product-autocomplete | 품목 모델명 자동완성 (ProductCatalog 연동) | 100% | 2026-03-17 | 4 |
| daily-report | 일일업무보고 (ERP 자동수집 + 카톡 복사) | 92% | 2026-03-17 | 1 |
| procurement-view | 나라장터 조달내역 조회 + 분석 보고서 | 93% | 2026-03-18 | 4 |
| item-management | 품목관리 (분류 체계 + CRUD + 거래처 자동완성) | 100% | 2026-03-18 | 3 |
| bom-excel-import | BOM 엑셀 임포트 (223 완성품, 3,762 부품, 14 제품군) | 100% | 2026-03-18 | 1 |
| material-po-bom-integration | 자재-발주-BOM 통합 연동 (1클릭 발주, bom_item_id FK) | 97% | 2026-03-18 | 4 |
| dept-permission | 조직도 기반 부서별 권한 + 개인 추가 메뉴 + 임원진 전체 열람 | 95% | 2026-03-18 | 4 |
| dept-weekly-report | 부서별 주간보고서 (영업/생산/관리 + 접근 제어 + 메뉴 트리) | 100% | 2026-03-18 | 4 |
| production-display | MAGNATECH 전사 현황판 (6컬럼 칸반 + 전광판 + 날씨 + 캘린더) | 100% | 2026-03-19 | 4 |
| history-board-ux | 통합히스토리보드 UX + 연락처 재배치 + 매그나텍 연동 | 97% | 2026-03-19 | 4 |
| delivery-summary | 납품집계 (G2B 조달내역 피벗+차트+엑셀) | 95% | 2026-03-19 | 4 |
| inventory-management | 재고관리 (대시보드+실사+회전율+BOM재고+변동이력) | 95% | 2026-03-19 | 4 |
| sidebar-collapse | 접이식 사이드바 + 즐겨찾기 (250px↔60px, 플라이아웃, FOUC방지) | 95% | 2026-03-19 | 4 |
| super-bom | 슈퍼BOM (옵션별 BOM 필터링, 8FR 100% 구현) | 95% | 2026-03-20 | 3 |
| po-ux-improve | 발주 UX 개선 (선택발주+계약그룹핑+재고표시) | 90% | 2026-03-20 | 4 |
| mcp-server | Light-Sync ERP MCP 서버 (FastMCP 28Tool+4Resource, Claude Web+LM Studio) | 92% | 2026-03-20 | 4 |
| photo-management | 현장 사진 독립 갤러리 (모바일 카메라+드래그앤드롭+ZIP다운로드+계약별필터) | 91% | 2026-03-20 | 3 |
| illuminance-verification | Relux PDF 파싱 + 조도 격자 히트맵 + KS 판정 + 비교 리포트 | 95% | 2026-03-20 | 4 |
| receiving-expected | 입고예정 v2 (MaterialOrder→PurchaseOrderItem 전환, 검수 제거, 디자인 통일) | N/A | 2026-03-20 | 3 |
| illuminance-design-integration | 조도검증-설계관리 통합 연동 (양방향+PDF원스톱+파서개선+자유입력+다중기구) | 95% | 2026-03-21 | 4 |
| code-simplify-split | 전체 코드 간소화 및 스플릿 (4Phase: CSS/JS추출+MCP분할+엔티티분할+Route서비스분리) | 100% | 2026-03-21 | 4 |
| drawing-management | 도면관리 고도화 (SPA 갤러리+PDF 미리보기+DWG 업/다운+버전관리+선택삭제) | ~93% | 2026-03-21 | 1 |

## drawing-management

- **Duration**: 2026-03-21 (1 session)
- **Iterations**: 1 (CSRF 중복 헤더 버그 수정)
- **Key Result**: 도면관리 전면 재작성. photo_gallery 동일 SPA 구조, PDF iframe 미리보기, DWG 원본 업/다운, XHR 인라인 업로드(드래그앤드롭), 버전 탭 라이트박스, 전체선택/선택삭제 bulk delete, `api_delete_drawing` 신규 엔드포인트
- **New Files**: templates/drawings_gallery.html (~850줄)
- **Modified**: routes/drawing.py, config.py, modules/models/db.py

### Documents

| Document | File |
|----------|------|
| Report | [drawing-management.report.md](drawing-management/drawing-management.report.md) |

---

## receiving-expected

- **Duration**: 2026-03-20 (1 session)
- **Iterations**: 3 (데이터소스 전환, NULL 처리, 미지정 표시)
- **Key Result**: 입고예정을 MaterialOrder→PurchaseOrderItem 직접 조회로 전환. 계약 없는 발주서도 표시. 불필요한 검수 프로세스 전면 제거. 입고관리 디자인 po_list 기준 통일. 대시보드/전사현황판 입고예정 통계도 동일하게 변경.
- **Modified**: entities.py, db.py, routes/receiving.py, routes/dashboard.py, modules/production_display_utils.py, templates/receiving_list.html, templates/receiving_detail.html, templates/production_display.html, sql_editer.sql

### Documents

| Document | File |
|----------|------|
| Plan | [receiving-expected.plan.md](receiving-expected/receiving-expected.plan.md) |
| Design | [receiving-expected.design.md](receiving-expected/receiving-expected.design.md) |
| Report | [receiving-expected.report.md](receiving-expected/receiving-expected.report.md) |

---

## illuminance-verification

- **Duration**: 2026-03-20 (1 session)
- **Iterations**: 1 (82% → 95%, PDF 파서 버그 3건 수정 + 리포트 구현)
- **Key Result**: Relux PDF layout-mode 파싱 엔진, 구역별 격자 히트맵 UI, 모바일 순차입력 모드, 설계-실측 차이맵, KS 기준 자동 판정, 비교 분석 리포트(인쇄용). `[m]` 치환 버그·all-None 컬럼·Y축 반전 3가지 파서 버그 수정.
- **New Files**: routes/illuminance.py, modules/services/illuminance_pdf_parser.py, illuminance_list/new/detail/area/report.html (5 templates)
- **Modified**: entities.py, db.py, app.py, config.py, sql_editer.sql

### Documents

| Document | File |
|----------|------|
| Plan | [illuminance-verification.plan.md](illuminance-verification/illuminance-verification.plan.md) |
| Design | [illuminance-verification.design.md](illuminance-verification/illuminance-verification.design.md) |
| Analysis | [illuminance-verification.analysis.md](illuminance-verification/illuminance-verification.analysis.md) |
| Report | [illuminance-verification.report.md](illuminance-verification/illuminance-verification.report.md) |

---

## photo-management

- **Duration**: 2026-03-20 (1 session)
- **Iterations**: 0 (first-pass 91%, 핵심 기능 99%)
- **Key Result**: 독립 사진관리 페이지(/photos). 현장별 갤러리 UI, 카메라/파일/드래그앤드롭 3중 업로드, 계약별 필터, ZIP 다운로드, 다중 선택삭제, 라이트박스 네비게이션(좌우/Esc), 모바일 2열 대응
- **New Files**: routes/photos.py (238줄), templates/photo_gallery.html (~980줄)
- **Modified**: modules/models/entities.py (ProjectPhoto 모델), app.py, config.py, templates/delivery_detail.html

### Documents

| Document | File |
|----------|------|
| Plan | [photo-management.plan.md](photo-management/photo-management.plan.md) |
| Design | [photo-management.design.md](photo-management/photo-management.design.md) |
| Report | [photo-management.report.md](photo-management/photo-management.report.md) |

---

## mcp-server

- **Duration**: 2026-03-20 (1 session)
- **Iterations**: 0 (first-pass 92%)
- **Key Result**: FastMCP 기반 ERP MCP 서버. 28개 Tool(재고/BOM/현장/생산/재무/조달) + 4개 Resource. Streamable HTTP(5010, Claude Web) + SSE(5011, LM Studio) 이중 서버. mcp.mgnt.kr 외부 도메인 연결 완료.
- **New Package**: `light_sync_mcp/` (server.py, db.py, tools_registry.py, server_http.py 등 15파일, 2,777줄)

### Documents

| Document | File |
|----------|------|
| Plan | [mcp-server.plan.md](mcp-server/mcp-server.plan.md) |
| Design | [mcp-server.design.md](mcp-server/mcp-server.design.md) |
| Analysis | [mcp-server.analysis.md](mcp-server/mcp-server.analysis.md) |
| Report | [mcp-server.report.md](mcp-server/mcp-server.report.md) |

---

## po-ux-improve

- **Duration**: 2026-03-20 (1 session)
- **Iterations**: 0 (first-pass 90%)
- **Key Result**: 자재관리 선택발주(체크→거래처별PO), BOM 선택발주 UX 강화, 발주목록 계약컬럼+3모드 그룹핑(거래처/계약/날짜), 발주상세 실재고/가용재고
- **Modified**: bom_requirement.html, po_list.html, po_detail.html, material_detail.html, purchase_order.py, material_actions.py, material.py

### Documents

| Document | File |
|----------|------|
| Plan | [po-ux-improve.plan.md](po-ux-improve/po-ux-improve.plan.md) |
| Design | [po-ux-improve.design.md](po-ux-improve/po-ux-improve.design.md) |
| Analysis | [po-ux-improve.analysis.md](po-ux-improve/po-ux-improve.analysis.md) |
| Report | [po-ux-improve.report.md](po-ux-improve/po-ux-improve.report.md) |

---

## super-bom

- **Duration**: 2026-03-19 ~ 2026-03-20 (1 session)
- **Iterations**: 0 (first-pass 95%, FR 100%)
- **Key Result**: 단일 슈퍼BOM으로 N개 옵션조합 커버. option_filter/option_schema JSON 컬럼, 엑셀/웹 임포트 옵션조건 자동 파싱, BOM 상세 드롭다운 필터 UI + JS 필터링, 소요자재 계산 옵션 반영, 엑셀 다운로드 옵션조건 포함
- **Modified**: entities.py, db.py, routes/bom.py, scripts/import_bom_from_excel.py, templates/bom_detail.html

### Documents

| Document | File |
|----------|------|
| Plan | [super-bom.plan.md](super-bom/super-bom.plan.md) |
| Analysis | [super-bom.analysis.md](super-bom/super-bom.analysis.md) |
| Report | [super-bom.report.md](super-bom/super-bom.report.md) |

---

## sidebar-collapse

- **Duration**: 2026-03-19 (1 session)
- **Iterations**: 0 (first-pass 95%)
- **Key Result**: 접이식 사이드바(250px↔60px), 그룹 아이콘 플라이아웃, 즐겨찾기 ⭐(최대 8개), FOUC 완전 제거
- **Modified**: config.py, app.py, templates/base.html

### Documents

| Document | File |
|----------|------|
| Plan | [sidebar-collapse.plan.md](sidebar-collapse/sidebar-collapse.plan.md) |
| Design | [sidebar-collapse.design.md](sidebar-collapse/sidebar-collapse.design.md) |
| Analysis | [sidebar-collapse.analysis.md](sidebar-collapse/sidebar-collapse.analysis.md) |
| Report | [sidebar-collapse.report.md](sidebar-collapse/sidebar-collapse.report.md) |

---

## delivery-summary

- **Duration**: 2026-03-19 (1 session)
- **Iterations**: 0 (first-pass 95%)
- **Key Result**: G2B 조달내역 대분류/모델별 월별 피벗 집계, stacked bar 차트, 엑셀 다운로드, 모델 자동완성, 금액 토글, 년도별 sub_rows
- **New Modules**: modules/services/procurement_summary.py, templates/procurement_summary.html
- **Modified**: routes/procurement.py, config.py

### Documents

| Document | File |
|----------|------|
| Plan | [delivery-summary.plan.md](delivery-summary/delivery-summary.plan.md) |
| Design | [delivery-summary.design.md](delivery-summary/delivery-summary.design.md) |
| Analysis | [delivery-summary.analysis.md](delivery-summary/delivery-summary.analysis.md) |
| Report | [delivery-summary.report.md](delivery-summary/delivery-summary.report.md) |

---

## production-display

- **Duration**: 2026-03-19 (1 session, ~3시간)
- **Iterations**: 0 (first-pass 100%)
- **Key Result**: 공장 TV 전용 다크 테마 6컬럼 전사 현황판. 협의→자재→생산대기→생산중→납품→일정 파이프라인 + 전광판 + 자재 입고예정 티커 + 날씨 API + 카드 클릭 모달 + 미니 캘린더
- **New Modules**: modules/production_display_utils.py, templates/production_display.html
- **Modified**: routes/production.py, templates/dashboard.html

### Documents

| Document | File |
|----------|------|
| Plan | [production-display.plan.md](production-display/production-display.plan.md) |
| Design | [production-display.design.md](production-display/production-display.design.md) |
| Analysis | [production-display.analysis.md](production-display/production-display.analysis.md) |
| Report | [production-display.report.md](production-display/production-display.report.md) |

---

## dept-weekly-report

- **Duration**: 2026-03-18 (1 session, CTO Team Mode)
- **Iterations**: 0 (first-pass 100%)
- **Key Result**: 3개 부서 자동 집계 주간보고서, user_group 기반 접근 제어, admin 부서 드롭다운, 영업부 품목 상세 펼침+합계
- **New Modules**: templates/report_weekly_production.html, templates/report_weekly_management.html
- **Modified**: routes/report.py, templates/report_weekly.html, templates/base.html

### Documents

| Document | File |
|----------|------|
| Plan | [dept-weekly-report.plan.md](dept-weekly-report/dept-weekly-report.plan.md) |
| Design | [dept-weekly-report.design.md](dept-weekly-report/dept-weekly-report.design.md) |
| Analysis | [dept-weekly-report.analysis.md](dept-weekly-report/dept-weekly-report.analysis.md) |
| Report | [dept-weekly-report.report.md](dept-weekly-report/dept-weekly-report.report.md) |

---

## dept-permission

- **Duration**: 2026-03-18 (1 session)
- **Iterations**: 1 (91% → Gap 수정 + extra_menus 추가)
- **Key Result**: MENU_REGISTRY 17개 중앙 정의, GroupPermission 동적 사이드바, 개인 extra_menus, 임원진 전체 접근
- **Modified**: config.py, app.py, base.html, auth_decorators.py, entities.py, db.py, routes/auth.py, admin_settings.html

### Documents

| Document | File |
|----------|------|
| Plan | [dept-permission.plan.md](dept-permission/dept-permission.plan.md) |
| Design | [dept-permission.design.md](dept-permission/dept-permission.design.md) |
| Analysis | [dept-permission.analysis.md](dept-permission/dept-permission.analysis.md) |
| Report | [dept-permission.report.md](dept-permission/dept-permission.report.md) |

---

## material-po-bom-integration

- **Duration**: 2026-03-18 (1 session)
- **Iterations**: 0 (first-pass 97%)
- **Key Result**: BOM 소요자재→1클릭 발주서 자동 생성, bom_item_id FK로 양방향 추적, 최신 입고 단가 연동
- **New**: POST /bom/create-po-from-requirement API
- **Modified**: entities.py, db.py, routes/bom.py, routes/purchase_order.py, bom_requirement.html, po_detail.html

### Documents

| Document | File |
|----------|------|
| Plan | [material-po-bom-integration.plan.md](material-po-bom-integration/material-po-bom-integration.plan.md) |
| Design | [material-po-bom-integration.design.md](material-po-bom-integration/material-po-bom-integration.design.md) |
| Analysis | [material-po-bom-integration.analysis.md](material-po-bom-integration/material-po-bom-integration.analysis.md) |
| Report | [material-po-bom-integration.report.md](material-po-bom-integration/material-po-bom-integration.report.md) |

---

## item-management

- **Duration**: 2026-03-18 (1 session)
- **Iterations**: 0 (first-pass 100%)
- **Key Result**: Item 모델 확장(category/manufacturer/note), 품목 CRUD 페이지, 거래처 API 자동완성, iCUBE USE_YN 버그 수정
- **New Modules**: routes/item.py, templates/item_list.html, item_detail.html, item_create.html
- **Modified**: entities.py, app.py, base.html, db.py, migrate_icube.py

### Documents

| Document | File |
|----------|------|
| Plan | [item-management.plan.md](item-management/item-management.plan.md) |
| Analysis | [item-management.analysis.md](item-management/item-management.analysis.md) |
| Report | [item-management.report.md](item-management/item-management.report.md) |

---

## procurement-view

- **Duration**: 2026-03-17 ~ 2026-03-18 (2일)
- **Iterations**: 0 (first-pass 93%)
- **Key Result**: 조달청 API 1,591건(554억원) 수집, 계약 그룹핑 목록, Chart.js 분석 보고서, Flask CLI 일일 동기화
- **New Modules**: routes/procurement.py, templates/procurement_list.html, templates/procurement_report.html, services/g2b_procurement_sync.py, crontab.md
- **Modified**: app.py, base.html, entities.py, __init__.py

### Documents

| Document | File |
|----------|------|
| Plan | [procurement-view.plan.md](procurement-view/procurement-view.plan.md) |
| Design | [procurement-view.design.md](procurement-view/procurement-view.design.md) |
| Analysis | [procurement-view.analysis.md](procurement-view/procurement-view.analysis.md) |
| Report | [procurement-view.report.md](procurement-view/procurement-view.report.md) |

---

## daily-report

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (code-analyzer 82% → 수정 후 92%)
- **Key Result**: ERP 7개 데이터소스 자동수집 → 부서별 카톡 포맷 생성, 실시간 미리보기, 원클릭 복사
- **New Modules**: routes/daily_report.py, templates/daily_report.html, DailyReport 모델
- **Modified**: app.py, base.html, entities.py, __init__.py

### Documents

| Document | File |
|----------|------|
| Report | [daily-report.report.md](daily-report/daily-report.report.md) |

---

## product-autocomplete

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 96% → GAP 수정 100%)
- **Key Result**: 검색 API + 순수 JS 자동완성 컴포넌트, 카테고리 연동, 설계관리 모달→인라인 전환
- **New Modules**: templates/components/catalog_autocomplete.html
- **Modified**: routes/api.py, base.html, contract_detail.html, project_create.html, project_detail.html

### Documents

| Document | File |
|----------|------|
| Plan | [product-autocomplete.plan.md](product-autocomplete/product-autocomplete.plan.md) |
| Design | [product-autocomplete.design.md](product-autocomplete/product-autocomplete.design.md) |
| Analysis | [product-autocomplete.analysis.md](product-autocomplete/product-autocomplete.analysis.md) |
| Report | [product-autocomplete.report.md](product-autocomplete/product-autocomplete.report.md) |

---

## nas-folder-sync

- **Duration**: 2026-03-17 (1 session)
- **Iterations**: 0 (first-pass 100%)
- **Key Result**: NAS cron 1분 폴더+.lnk 감지 → 폴더명 연도 기준 경로 자동 결정, 히스토리 로그, SMB 경로 저장
- **New Modules**: routes/api.py, scripts/nas_folder_sync.sh
- **Modified**: app.py, .env
- **NAS 스크립트**: `/scripts/nas_folder_sync.sh` (crontab `*/1 * * * *`)

### Documents

| Document | File |
|----------|------|
| Report | [nas-folder-sync.report.md](nas-folder-sync/nas-folder-sync.report.md) |

---

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
