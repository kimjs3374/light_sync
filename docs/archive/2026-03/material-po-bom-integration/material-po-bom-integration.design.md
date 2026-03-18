# BOM-발주서-자재관리 통합 연동 Design Document

> **Summary**: BOM 소요자재 부족분에서 거래처별 발주서 자동 생성, bom_item_id FK 기반 양방향 추적, 입고 시 소요현황 자동 반영
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-18
> **Status**: Draft
> **Planning Doc**: [material-po-bom-integration.plan.md](../01-plan/features/material-po-bom-integration.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. PurchaseOrderItem/MaterialOrder에 bom_item_id FK 추가로 BOM 부품 단위 추적성 확보
2. 소요자재 페이지에서 부족 자재 선택 -> 거래처별 발주서 일괄 자동 생성
3. 기존 발주서/입고/자재관리 CRUD 100% 하위 호환 유지
4. 발주서 상세에서 BOM 연결 정보 표시

### 1.2 Design Principles

- **하위 호환**: 새 FK는 모두 nullable, 기존 bom_item_id=NULL 데이터에서 기존 로직 그대로 동작
- **최소 변경**: entities.py에 컬럼 2개 + db.py ALTER TABLE 2개, 기존 라우트 로직은 보강만
- **실시간 계산**: 별도 재고/차감 테이블 없이 MaterialOrder/PurchaseOrderItem 상태 기반 실시간 소요 계산

---

## 2. Architecture

### 2.1 Data Flow

```
[소요자재 페이지] -- 부족 자재 체크 --> [프리뷰 모달 (거래처별 그룹핑)]
                                            |
                                     POST /bom/create-po-from-requirement
                                            |
                              ┌─────────────┼─────────────┐
                              v             v             v
                      [Vendor ilike    [PurchaseOrder  [PurchaseOrderItem
                       매칭/자동생성]   생성 per vendor]  생성 + bom_item_id]
                                            |
                                    _sync_po_to_material_orders()
                                            |
                                     [MaterialOrder 생성
                                      + bom_item_id 연결]
                                            |
                              입고 등록 시 _update_po_status_on_receiving()
                                            |
                                     MaterialOrder.order_status = '입고완료'
                                            |
                              소요자재 페이지 재조회 시 자동 반영
```

### 2.2 Modified Files

| File | Changes |
|------|---------|
| `modules/models/entities.py` | PurchaseOrderItem.bom_item_id, MaterialOrder.bom_item_id 추가 |
| `modules/models/db.py` | ALTER TABLE 마이그레이션 2건 |
| `routes/bom.py` | material_requirement() 개선 + create_po_from_requirement() 신규 |
| `routes/purchase_order.py` | _sync_po_to_material_orders() bom_item_id 연결 보강 |
| `templates/bom_requirement.html` | 체크박스 + 발주 버튼 + 프리뷰 모달 |
| `templates/po_detail.html` | BOM 연결 정보 표시 |

---

## 3. Data Model Changes

### 3.1 purchase_order_items 테이블

```sql
ALTER TABLE purchase_order_items
ADD COLUMN bom_item_id INTEGER REFERENCES bom_items(id) NULL;
```

```python
# entities.py - PurchaseOrderItem
bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)
bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
```

### 3.2 material_orders 테이블

```sql
ALTER TABLE material_orders
ADD COLUMN bom_item_id INTEGER REFERENCES bom_items(id) NULL;
```

```python
# entities.py - MaterialOrder
bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)
bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
```

### 3.3 Entity Relationships (변경 후)

```
[ContractItem] 1──N [MaterialOrder] N──1 [BomItem]
                                              |
[PurchaseOrderItem] N──────────────────────1 [BomItem]
      |
      N──1 [PurchaseOrder] N──1 [Vendor]
```

---

## 4. API Specification

### 4.1 POST `/bom/create-po-from-requirement`

소요자재 부족분에서 거래처별 발주서 자동 생성.

**Request (Form POST with CSRF)**:
```
csrf_token: string
contract_id: int
selected_items: JSON string
  [
    {
      "bom_item_id": 123,
      "contract_item_id": 45,
      "item_name": "HLG-320H-48A",
      "item_spec": "LED 드라이버",
      "quantity": 96,
      "unit": "EA",
      "unit_price": 97600,
      "supplier": "(주)셀파세미컴"
    }
  ]
```

**Logic**:
1. selected_items JSON 파싱, supplier 기준 그룹핑
2. 각 supplier 그룹에 대해:
   a. Vendor.name ilike 매칭. 없으면 Vendor 자동 생성 (is_active=True)
   b. PurchaseOrder 생성 (po_no=_generate_po_no(), contract_id, po_date=today, status='작성중')
   c. 그룹 내 품목마다 PurchaseOrderItem 생성 (bom_item_id 설정)
   d. total_amount/tax_amount 계산
3. 생성된 PO 수에 따라:
   - 1건: 해당 PO 상세로 redirect
   - N건: 발주서 목록으로 redirect + flash 메시지

**Response**: redirect (302)

### 4.2 material_requirement() 개선

현재 문제: contract_item_id 기준 MaterialOrder 합산 -> BOM 부품별 구분 불가

변경:
- bom_item_id 기반 PurchaseOrderItem 조회로 정확한 발주량 계산
- 기존 MaterialOrder 기반 fallback 유지

```python
# bom_item_id가 있는 PurchaseOrderItem에서 발주량 조회
ordered_via_po = db.query(func.coalesce(func.sum(PurchaseOrderItem.quantity), 0)).filter(
    PurchaseOrderItem.bom_item_id == bi.id,
    PurchaseOrderItem.purchase_order.has(PurchaseOrder.contract_id == contract_id),
).scalar() or 0

# 기존 MaterialOrder 기반 발주량 (하위 호환)
ordered_via_mo = db.query(...).filter(
    MaterialOrder.contract_item_id == ci.id,
    MaterialOrder.order_status.in_(['발주완료', '입고완료']),
).scalar() or 0

# 둘 중 큰 값 사용 (중복 방지)
ordered = max(float(ordered_via_po), float(ordered_via_mo))
```

---

## 5. UI/UX Design

### 5.1 소요자재 페이지 (bom_requirement.html) 변경

```
┌──────────────────────────────────────────────────────────────┐
│  소요자재 계산                                    [BOM 목록] │
├──────────────────────────────────────────────────────────────┤
│  계약 선택: [dropdown]                                       │
├──────────────────────────────────────────────────────────────┤
│  소요자재 목록                                               │
│ ┌──┬───────┬────────┬────┬────┬────┬────┬────┬────┬────┬──┐ │
│ │☑ │계약품목│소요부품 │규격│제품│단위│총소│발주│입고│부족│상│ │
│ │  │       │        │    │수량│소요│요  │량  │량  │량  │태│ │
│ ├──┼───────┼────────┼────┼────┼────┼────┼────┼────┼────┼──┤ │
│ │☑ │투광등 │HLG-320 │... │96  │1   │96  │0   │0   │96  │부│ │
│ │☑ │가로등 │CV*2.5  │... │30  │30  │900 │0   │0   │900 │부│ │
│ │  │투광등 │PCB     │... │96  │1   │96  │96  │96  │0   │충│ │
│ └──┴───────┴────────┴────┴────┴────┴────┴────┴────┴────┴──┘ │
│                                                              │
│  [전체 선택]           [선택 자재 발주서 생성 (2건)]          │
└──────────────────────────────────────────────────────────────┘
```

체크박스 규칙:
- shortage > 0인 행에만 체크박스 표시
- 체크박스 선택 수에 따라 버튼 텍스트 업데이트
- BOM 미등록 행은 체크박스 없음

### 5.2 프리뷰 모달

```
┌──────────────────────────────────────────────────┐
│  발주서 생성 프리뷰                        [닫기] │
├──────────────────────────────────────────────────┤
│                                                  │
│  거래처별 발주서 2건이 생성됩니다:                 │
│                                                  │
│  ■ (주)셀파세미컴                                 │
│    - HLG-320H-48A  96EA  @97,600  = 9,369,600   │
│    - CV*2.5SQ*3C   900M  @1,550   = 1,395,000   │
│    소계: 10,764,600원                             │
│                                                  │
│  ■ 송원스틸                                       │
│    - KS D 3566     6본   @174,010 = 1,044,060   │
│    소계: 1,044,060원                              │
│                                                  │
│              [취소]  [발주서 생성]                 │
└──────────────────────────────────────────────────┘
```

### 5.3 발주서 상세 BOM 연결 표시

품목 테이블에 BOM 연결 컬럼 추가:
- bom_item_id가 있는 품목: BomHeader.product_name + BomItem.item_name 표시
- bom_item_id가 없는 품목: '-' 표시

---

## 6. Implementation Order

| Step | Task | Files | FR |
|------|------|-------|----|
| 1 | entities.py bom_item_id 추가 | `entities.py` | FR-02, FR-03 |
| 2 | db.py ALTER TABLE 마이그레이션 | `db.py` | FR-02, FR-03 |
| 3 | material_requirement() 발주량 계산 개선 | `routes/bom.py` | FR-05 |
| 4 | create_po_from_requirement() API | `routes/bom.py` | FR-01 |
| 5 | bom_requirement.html UI 개선 | `templates/bom_requirement.html` | FR-04 |
| 6 | _sync_po_to_material_orders() 개선 | `routes/purchase_order.py` | FR-07 |
| 7 | po_detail.html BOM 연결 표시 | `templates/po_detail.html` | FR-06 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-18 | Initial draft | CTO Lead |
