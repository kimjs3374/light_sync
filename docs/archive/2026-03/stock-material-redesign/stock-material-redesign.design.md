# stock-material-redesign Design Document

> **Feature**: 재고 기반 자재관리 재설계
> **Version**: 1.0
> **Date**: 2026-03-18
> **Status**: Implemented

---

## 1. Architecture Overview

### 1.1 Data Model Changes

```
items (existing table)
  + stock_qty FLOAT DEFAULT 0      -- 실재고 수량
  + reserved_qty FLOAT DEFAULT 0   -- 예약수량 (현장별 합산)

  가용재고 = stock_qty - reserved_qty (computed, not stored)
```

### 1.2 Core Flow

```
계약 자재동기화 (sync_material_orders_for_contract_item)
  |
  +-- BOM 매칭 있음?
  |     |
  |     +-- 각 BomItem에 대해:
  |     |     필요수량 = bi.quantity * contract_item.quantity
  |     |     BomItem.item_id -> Item -> 가용재고 계산
  |     |     |
  |     |     +-- 가용재고 >= 필요수량 -> MO(재고이용) + reserved_qty 증가
  |     |     +-- 가용재고 < 필요수량  -> MO(발주대기) + 있는만큼 예약
  |     |
  |     +-- 기존 발주완료/입고완료/재고이용 MO는 건드리지 않음
  |
  +-- BOM 매칭 없음?
        +-- 기존 하드코딩 fallback 유지

예약 취소 (cancel_reservation)
  MO(재고이용) -> MO(발주대기) + Item.reserved_qty 감소

재예약 (reserve_stock)
  MO(발주대기) -> MO(재고이용) + Item.reserved_qty 증가 (가용재고 체크)

발주서 생성 (create_po_from_material)
  MO(발주대기) -> PO + POItem 자동 생성
  BomItem.supplier -> Vendor 매칭 (없으면 자동 생성)

일괄발주 (bulk_create_po)
  발주대기 MO들 -> 거래처별 그룹핑 -> 각 그룹별 PO 생성

입고 완료 시 (receiving._update_po_status_on_receiving)
  PO 전체 입고 완료 -> POItem.bom_item_id -> Item.stock_qty 증가
```

## 2. Implementation Details

### 2.1 Modified Files

| File | Changes |
|------|---------|
| `modules/models/entities.py` | Item: +stock_qty, +reserved_qty |
| `modules/models/db.py` | ALTER TABLE items ADD COLUMN migration |
| `routes/material.py` | sync logic + stock judgment, new action handlers |
| `modules/services/material_actions.py` | 5 new handlers: cancel_reservation, reserve_stock, create_po, bulk_create_po, stock edit |
| `routes/item.py` | stock_qty manual edit in item_edit |
| `routes/receiving.py` | stock_qty increase on receiving |
| `templates/material_detail.html` | Tabs (발주관리/재고이용/전체), action buttons |
| `templates/item_list.html` | 실재고/예약/가용 columns |
| `templates/item_detail.html` | Stock display + manual edit |

### 2.2 order_status States

```
발주대기 -> 발주완료 -> 입고완료
발주대기 -> 재고이용 (재고 충분)
재고이용 -> 발주대기 (예약 취소)
발주대기 -> 재고이용 (재예약, 가용재고 체크)
```

### 2.3 Safety Guards

- `reserved_qty = max(0, ...)` -- 음수 방지
- 기존 발주완료/입고완료 MO는 sync 시 건드리지 않음
- CSRF 토큰 모든 POST에 필수
- 거래처 없으면 자동 생성 (ilike 매칭 우선)

## 3. FR Coverage

| FR | Status | Implementation |
|----|--------|---------------|
| FR-01 | Done | entities.py: stock_qty, reserved_qty |
| FR-03 | Done | sync logic with stock judgment |
| FR-04 | Done | reserved_qty increase on sync |
| FR-05 | Done | cancel_reservation handler |
| FR-06 | Done | material_detail.html tabs |
| FR-07 | Done | receiving.py stock_qty increase |
| FR-08 | Done | item_list.html + item_detail.html |
| FR-09 | Done | cancel_reservation handler |
| FR-10 | Done | reserve_stock handler |
| FR-11 | Done | order_status '재고이용' in selects |
| FR-12 | Done | compute_admin_status_from_orders |
| FR-13 | Done | create_po_from_material handler |
| FR-14 | Done | bulk_create_po handler |
| FR-15 | Done | auto quantity calculation |
| FR-17 | Done | item_edit stock_qty manual edit |
| FR-02 | Pending | Excel import script (needs excel file) |
| FR-16 | Pending | Bulk email send (P2) |
