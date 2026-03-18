# material-po-bom-integration Completion Report

> **Summary**: BOM 소요자재 → 거래처별 1클릭 발주서 자동 생성, bom_item_id FK 기반 발주-BOM 양방향 추적, 입고 완료 시 소요현황 자동 반영
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Created**: 2026-03-18
> **Status**: Completed

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | BOM 소요자재/발주서/입고 3개 모듈이 독립 동작하여 부족 자재 확인 후 발주서 생성까지 수동 입력이 필요하고, 어떤 BOM 부품을 위한 발주인지 추적이 불가능했음 |
| **Solution** | PurchaseOrderItem/MaterialOrder에 bom_item_id FK를 추가하고, 소요자재 페이지에서 체크박스 선택 → 거래처별 발주서 일괄 자동 생성 API(POST `/bom/create-po-from-requirement`) 구현 |
| **Function/UX Effect** | 부족 자재 체크 후 1클릭으로 거래처별 발주서 자동 생성(프리뷰 모달 확인 후 확정), 발주서 상세에서 BOM 연결 배지 표시, 입고 완료 시 소요자재 페이지 실시간 자동 반영 |
| **Core Value** | 자재 발주 리드타임 단축 및 수동 입력 오류 제거, 계약별 자재 소요→발주→입고 전체 파이프라인의 end-to-end 추적성 확보 |

---

## 1. Overview

- **Feature**: BOM-발주서-자재관리 통합 연동 (material-po-bom-integration)
- **Duration**: 2026-03-18 (Plan → Report 당일 완료)
- **Owner**: CTO Lead

---

## 2. PDCA Cycle Summary

### Plan

- **문서**: `docs/01-plan/features/material-po-bom-integration.plan.md`
- **목표**: BOM/PO/자재관리/입고 4개 모듈 간 데이터 흐름 자동화로 자재 조달 end-to-end 추적성 확보
- **FR 정의**: FR-01~FR-07 (7개 기능 요건)
- **예상 기간**: 당일 완료 (단일 세션)

### Design

- **문서**: `docs/02-design/features/material-po-bom-integration.design.md`
- **주요 설계 결정**:
  - PurchaseOrderItem/MaterialOrder에 nullable FK(bom_item_id) 추가 — 최소 변경으로 추적성 확보
  - 소요량 계산: bom_item_id 기반 PurchaseOrderItem 조회 1차 + MaterialOrder fallback 2차 (max()로 중복 방지)
  - 거래처 매칭: BomItem.supplier → Vendor.name ilike + 없으면 자동 생성
  - 프리뷰 방식: 별도 서버 API 없이 클라이언트 JS의 data-* 속성 활용

### Do

- **구현 범위**:
  1. `modules/models/entities.py` — PurchaseOrderItem.bom_item_id, MaterialOrder.bom_item_id FK 추가
  2. `modules/models/db.py` — PostgreSQL ALTER TABLE 2건 (try/except 멱등성 패턴)
  3. `routes/bom.py` — material_requirement() 개선 + POST /bom/create-po-from-requirement + _get_latest_receiving_prices()
  4. `routes/purchase_order.py` — _sync_po_to_material_orders() bom_item_id 매칭 보강 + po_detail joinedload
  5. `templates/bom_requirement.html` — 체크박스 + 발주 버튼 + 거래처 그룹핑 프리뷰 모달
  6. `templates/po_detail.html` — BOM 연결 배지 컬럼 표시
- **실제 기간**: 당일 완료

### Check

- **분석 문서**: `docs/03-analysis/material-po-bom-integration.analysis.md`
- **Design Match Rate**: **97%**
- **FR 구현율**: 7/7 (100%)
- **Gap**: 1건 (GET `/api/bom/requirement-for-po` 미구현 — 클라이언트 JS data-* 처리로 대체, 기능 목적 충족)
- **설계 초과 구현**: 4건 (PO project_id/created_by 설정, 취소 PO 제외 필터, 소요자재 거래처 컬럼, joinedload N+1 방지)

---

## 3. Results

### Completed Items

- FR-01: 소요자재 부족분 → 거래처별 발주서 자동 생성 API (POST `/bom/create-po-from-requirement`)
- FR-02: PurchaseOrderItem.bom_item_id FK 추가 (entities.py + ALTER TABLE)
- FR-03: MaterialOrder.bom_item_id FK 추가 (entities.py + ALTER TABLE)
- FR-04: 소요자재 UI 개선 (체크박스 + 전체선택 + 발주서 생성 버튼 + 거래처별 프리뷰 모달)
- FR-05: 입고 완료 시 MaterialOrder.order_status = '입고완료' → 소요자재 페이지 실시간 자동 반영
- FR-06: 발주서 상세에서 BOM 연결 배지 표시 (BomHeader.product_name + joinedload 최적화)
- FR-07: _sync_po_to_material_orders() bom_item_id 기반 정확 매칭 + 기존 품명 유사도 fallback

### Incomplete/Deferred Items

- GET `/api/bom/requirement-for-po` JSON API: 클라이언트 JS에서 data-* 속성으로 직접 처리하는 방식으로 대체 구현. 기능 목적(거래처별 그룹핑 프리뷰) 동일하게 충족. 별도 서버 API 불필요로 판단하여 생략.

### Bonus Items (설계 초과)

- PO 생성 시 project_id, assigned_to, created_by 자동 설정 (이력 추적 강화)
- 소요량 계산에서 취소(status='취소') PO 제외 필터 적용 (데이터 정확도 개선)
- 소요자재 테이블에 거래처 컬럼 추가 (발주 계획 수립 편의)
- PurchaseOrderItem → BomItem → BomHeader joinedload (N+1 쿼리 방지)

---

## 4. Technical Details

### 4.1 DB Schema Changes

```sql
-- purchase_order_items 테이블
ALTER TABLE purchase_order_items
ADD COLUMN bom_item_id INTEGER REFERENCES bom_items(id) NULL;

-- material_orders 테이블
ALTER TABLE material_orders
ADD COLUMN bom_item_id INTEGER REFERENCES bom_items(id) NULL;
```

- 두 컬럼 모두 nullable — 기존 데이터(bom_item_id=NULL) 100% 하위 호환
- try/except 패턴으로 멱등성 보장 (중복 실행 안전)

### 4.2 핵심 로직 — 소요량 계산 (bom.py)

```python
# 1차: bom_item_id 기반 PurchaseOrderItem 발주량 (정확)
ordered_via_po = db.query(func.coalesce(func.sum(PurchaseOrderItem.quantity), 0)).filter(
    PurchaseOrderItem.bom_item_id == bi.id,
    PurchaseOrderItem.purchase_order.has(
        and_(PurchaseOrder.contract_id == contract_id,
             PurchaseOrder.status != '취소')
    )
).scalar() or 0

# 2차: MaterialOrder 기반 fallback (기존 데이터 호환)
ordered_via_mo = db.query(...).filter(
    MaterialOrder.contract_item_id == ci.id,
    MaterialOrder.order_status.in_(['발주완료', '입고완료']),
).scalar() or 0

# 중복 방지: 둘 중 큰 값 사용
ordered = max(float(ordered_via_po), float(ordered_via_mo))
```

### 4.3 거래처별 발주서 자동 생성 흐름

```
체크박스 선택 → 프리뷰 모달 확인 (클라이언트 JS, data-* 속성 활용)
    → POST /bom/create-po-from-requirement
        → supplier 기준 그룹핑
        → 각 그룹: Vendor.name ilike 매칭 (없으면 자동 생성)
        → PurchaseOrder 생성 (per vendor)
        → PurchaseOrderItem 생성 (bom_item_id 설정)
        → _sync_po_to_material_orders() → MaterialOrder.bom_item_id 연결
    → 1건: PO 상세 redirect / N건: PO 목록 redirect
```

### 4.4 Entity Relationships (변경 후)

```
[ContractItem] 1──N [MaterialOrder] N──1 [BomItem]
                                              |
[PurchaseOrderItem] N──────────────────────1 [BomItem]
      |
      N──1 [PurchaseOrder] N──1 [Vendor]
```

---

## 5. Quality Metrics

| Metric | Value |
|--------|:-----:|
| Design Match Rate | **97%** |
| FR 구현율 | **7/7 (100%)** |
| Gap 건수 | **1건** (기능 목적 충족) |
| Iteration 횟수 | **0회** |
| 설계 초과 구현 | **4건** |
| 수정 파일 | 6개 |
| 하위 호환성 | 100% (nullable FK, fallback 로직 유지) |

---

## 6. Lessons Learned

### What Went Well

- nullable FK + fallback 패턴으로 기존 데이터 완전 하위 호환 유지하면서 새 기능 추가
- 프리뷰 API를 클라이언트 data-* 방식으로 대체 — 서버 왕복 없이 빠른 UX 제공
- max(ordered_via_po, ordered_via_mo) 패턴이 bom_item_id 있는 신규 데이터와 없는 기존 데이터를 단일 쿼리로 처리
- joinedload로 N+1 쿼리 방지 — 설계 단계에 명시 없었지만 구현 시 자연스럽게 적용
- 취소 PO 제외 필터를 구현 시 추가 — 설계 단계에서 놓친 엣지케이스 선제 처리

### Areas for Improvement

- Plan 단계에서 `GET /api/bom/requirement-for-po` 설계 시 클라이언트 처리 가능 여부를 먼저 검토했다면 설계 문서에 불필요한 API 명세를 넣지 않았을 것
- 소요자재 테이블 거래처 컬럼은 UX에 유용했는데, 설계 wireframe에 포함시키는 게 더 정확한 설계 문서를 만드는 데 도움이 됨

### To Apply Next Time

- 프리뷰/미리보기 기능 설계 시: 이미 페이지에 로드된 데이터를 클라이언트 JS로 처리할 수 있는지 먼저 검토하여 불필요한 서버 API 설계 제거
- 발주량 계산처럼 기존/신규 데이터 혼재 상황에서는 항상 fallback 전략을 설계 단계에서 명시

---

## 7. Next Steps

- [ ] `design.md` 4.2절 `GET /api/bom/requirement-for-po` 항목: "클라이언트 JS data-* 처리로 대체" 주석 추가 또는 제거
- [ ] `design.md` 5.1절 소요자재 wireframe에 거래처 컬럼 반영
- [ ] (선택적, Low Priority) 발주 프리뷰 모달에서 동일 BOM 부품 기존 발주 내역 경고 표시 — plan.md 위험 항목 "중복 발주" 관련
- [ ] BOM 엑셀 임포트(`bom-excel-import`) 기능 연계 시 bom_item_id 자동 연결 검증

---

## 8. Related Documents

- Plan: [material-po-bom-integration.plan.md](../01-plan/features/material-po-bom-integration.plan.md)
- Design: [material-po-bom-integration.design.md](../02-design/features/material-po-bom-integration.design.md)
- Analysis: [material-po-bom-integration.analysis.md](../03-analysis/material-po-bom-integration.analysis.md)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-18 | Initial completion report | CTO Lead |
