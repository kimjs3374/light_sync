---
name: Phase 3+4 구현 완료
description: 입고관리(Receiving) + BOM/자재관리 Phase 3+4 구현 완료 (2026-03-18)
type: project
---

Phase 3 (입고관리) + Phase 4 (BOM/자재관리) 구현 완료.

**Phase 3 - 입고관리:**
- Receiving, ReceivingItem 모델 (entities.py)
- routes/receiving.py: 입고 목록/등록/상세/상태변경/삭제
- 발주서 기반 입고 + 직접 입고
- 발주 vs 입고 대사 (AJAX API)
- iCUBE 기존 입고이력 모달 조회
- 발주서 전체 입고 시 PO 상태/MaterialOrder 자동 전환

**Phase 4 - BOM/자재관리:**
- BomHeader, BomItem 모델 (entities.py)
- routes/bom.py: BOM CRUD + 소요자재 자동 계산
- 프로젝트 계약 x BOM = 소요자재 목록 (발주/입고 현황 대비 부족수량)

**Templates:** receiving_list/create/detail, bom_list/create/detail/requirement
**사이드바:** 관리부 메뉴에 입고관리 + BOM관리 추가
**발주서 연동:** po_detail.html에 [입고 등록] 버튼 추가

**Why:** iCUBE 탈피를 위한 자체 ERP 완성도 확보
**How to apply:** 다음 Phase에서는 재고관리/거래명세서 PDF 등을 고려
