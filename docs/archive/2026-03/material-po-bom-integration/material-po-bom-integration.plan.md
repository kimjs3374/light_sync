# BOM-발주서-자재관리 통합 연동 Planning Document

> **Summary**: BOM 소요자재 계산 결과에서 발주서 자동 생성, 발주-BOM 부품 추적, 입고 시 소요자재 자동 차감까지 3개 모듈 간 end-to-end 연동 구현
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-18
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | BOM 소요자재/발주서/입고 3개 모듈이 독립 동작하여, 부족 자재에서 발주서 생성까지 수동 입력이 필요하고 추적이 불가능함 |
| **Solution** | PurchaseOrderItem/MaterialOrder에 bom_item_id FK 추가, BOM 소요자재 페이지에서 거래처별 발주서 일괄 생성 API, 입고 완료 시 BOM 소요 자동 차감 |
| **Function/UX Effect** | 부족 자재 체크 -> 1클릭 발주서 생성, 발주-BOM 부품 양방향 추적, 소요자재 페이지에서 실시간 발주/입고 현황 확인 |
| **Core Value** | 자재 발주 리드타임 단축 및 수동 입력 오류 제거, 계약별 자재 소요-발주-입고 전체 파이프라인 가시성 확보 |

---

## 1. Overview

### 1.1 Purpose

BOM(Bill of Materials), 발주서(Purchase Order), 자재관리(Material Order), 입고(Receiving) 4개 모듈 간 데이터 흐름을 자동화하여 자재 조달 프로세스의 end-to-end 추적성을 확보한다.

### 1.2 Background

현재 각 모듈의 연동 상태:
- **BOM -> 발주서**: 연결 없음. 소요자재 페이지에서 부족분을 확인해도 발주서는 별도로 수동 생성해야 함
- **발주서 -> BOM**: PurchaseOrderItem에 bom_item_id가 없어 어떤 BOM 부품에 대한 발주인지 추적 불가
- **발주서 -> 자재관리**: `_sync_po_to_material_orders()`로 이메일 발송 시 자동 연동되지만, contract_item 매칭이 품명 유사도 기반으로 부정확
- **입고 -> BOM**: `_update_po_status_on_receiving()`이 PO/MaterialOrder 상태만 갱신하고, BOM 소요량 대비 차감은 미반영

### 1.3 Related Documents

- BOM 엑셀 임포트 Plan: `docs/01-plan/features/bom-excel-import.plan.md`
- iCUBE 조달관리 Plan: `docs/01-plan/features/icube-procurement.plan.md`

---

## 2. Scope

### 2.1 In Scope

- [x] FR-01: BOM 소요자재 부족분 -> 거래처별 발주서 자동 생성 API
- [x] FR-02: PurchaseOrderItem에 bom_item_id FK 추가
- [x] FR-03: MaterialOrder에 bom_item_id FK 추가
- [x] FR-04: 소요자재 페이지 UI 개선 (체크박스 + 발주생성 버튼)
- [x] FR-05: 입고 완료 시 소요자재 현황 자동 갱신 (기존 로직 보강)
- [x] FR-06: 발주서 상세에서 BOM 연결 정보 표시

### 2.2 Out of Scope

- BOM 자체 CRUD 변경 (기존 유지)
- 발주서 PDF/이메일 발송 로직 변경
- 입고 CRUD 변경
- 자동 재발주 (최소 재고량 기반) -- 향후 Phase
- BOM 버전 관리 (현재 version 컬럼은 표시용)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 소요자재 페이지에서 부족 자재를 선택하고 "발주서 생성" 클릭 시, BomItem.supplier 기준 거래처별로 PurchaseOrder를 자동 생성 | High | Pending |
| FR-02 | PurchaseOrderItem.bom_item_id (FK -> bom_items.id, nullable) 컬럼 추가하여 발주 품목과 BOM 부품 간 1:1 추적 | High | Pending |
| FR-03 | MaterialOrder.bom_item_id (FK -> bom_items.id, nullable) 컬럼 추가하여 자재관리와 BOM 부품 간 연결 | High | Pending |
| FR-04 | 소요자재 페이지에 체크박스 + "선택 자재 발주" 버튼 + 거래처별 그룹핑 프리뷰 추가 | High | Pending |
| FR-05 | 입고 완료 시 `_update_po_status_on_receiving()`에서 bom_item_id 연결된 MaterialOrder 소요량 차감 반영 | Medium | Pending |
| FR-06 | 발주서 상세 페이지에서 BOM 연결 정보 (완제품명, BOM 부품명) 표시 | Low | Pending |
| FR-07 | `_sync_po_to_material_orders()` 개선: bom_item_id가 있으면 정확한 contract_item 매칭 수행 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 호환성 | 기존 발주서/입고 CRUD 기능 100% 정상 동작 | 수동 테스트 |
| 데이터 무결성 | 새 FK 컬럼은 nullable로 추가, 기존 데이터 영향 없음 | DB 마이그레이션 후 기존 레코드 확인 |
| 성능 | 소요자재 계산 + 발주서 생성 API 응답 3초 이내 | 브라우저 네트워크 탭 |

---

## 4. Detailed Design

### 4.1 DB Schema Changes

#### 4.1.1 purchase_order_items 테이블

```sql
ALTER TABLE purchase_order_items
ADD COLUMN bom_item_id INTEGER REFERENCES bom_items(id) NULL;
```

#### 4.1.2 material_orders 테이블

```sql
ALTER TABLE material_orders
ADD COLUMN bom_item_id INTEGER REFERENCES bom_items(id) NULL;
```

#### 4.1.3 entities.py 모델 변경

**PurchaseOrderItem**:
```python
bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)
bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
```

**MaterialOrder**:
```python
bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)
bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
```

### 4.2 API Design

#### 4.2.1 POST `/bom/create-po-from-requirement`

BOM 소요자재 부족분에서 발주서 자동 생성.

**Request (Form POST)**:
```
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
    },
    ...
  ]
```

**Logic**:
1. selected_items를 supplier(거래처명) 기준으로 그룹핑
2. 각 supplier에 대해:
   a. Vendor 테이블에서 name 매칭 (ilike). 없으면 Vendor 자동 생성
   b. PurchaseOrder 생성 (po_no 자동 채번, contract_id 연결)
   c. 그룹 내 품목마다 PurchaseOrderItem 생성 (bom_item_id 설정)
3. 생성된 PO 목록 반환

**Response**: redirect to 발주서 목록 또는 생성된 PO 상세

#### 4.2.2 GET `/api/bom/requirement-for-po`

소요자재 중 부족분만 JSON으로 반환 (발주 프리뷰용).

**Parameters**: `contract_id`

**Response**:
```json
{
  "groups": [
    {
      "supplier": "(주)셀파세미컴",
      "vendor_id": 12,
      "items": [
        {
          "bom_item_id": 123,
          "contract_item_id": 45,
          "item_name": "HLG-320H-48A",
          "item_spec": "LED 드라이버",
          "shortage": 96,
          "unit": "EA",
          "unit_price": 97600
        }
      ]
    }
  ]
}
```

### 4.3 소요자재 페이지 (bom_requirement.html) 변경

1. **체크박스 컬럼 추가**: 부족(shortage > 0)인 행에만 체크박스 표시
2. **"전체 선택" 체크박스**: 테이블 헤더에 추가
3. **"선택 자재 발주서 생성" 버튼**: 하단에 추가
4. **거래처별 그룹핑 프리뷰 모달**: 버튼 클릭 시 supplier 기준 그룹핑 결과를 모달로 보여주고 확인 후 POST

### 4.4 기존 함수 수정

#### 4.4.1 `_sync_po_to_material_orders()` 개선

현재: contract_item 매칭이 품명 유사도 기반
변경: po_item.bom_item_id가 있으면 해당 BomItem의 bom_header -> ContractItem 매칭 경로 활용

```python
def _sync_po_to_material_orders(db, po):
    # 기존 로직 유지 (하위 호환)
    # + bom_item_id가 있는 po_item은 정확한 매칭 수행
    for po_item in po.items:
        if po_item.bom_item_id:
            # BOM 부품에서 contract_item_id를 정확히 찾을 수 있음
            mo.bom_item_id = po_item.bom_item_id
```

#### 4.4.2 `_update_po_status_on_receiving()` 보강

현재: PO 상태 + MaterialOrder.order_status 갱신
추가: bom_item_id가 연결된 경우 로깅만 추가 (실제 차감은 소요자재 계산 시 실시간 조회)

> Note: BOM 소요자재 "부족량"은 이미 MaterialOrder 발주/입고 상태 기반으로 실시간 계산 중.
> 입고 완료 시 MaterialOrder.order_status = '입고완료'가 되면 소요자재 페이지에서 자동 반영됨.
> 따라서 별도 "차감" 로직은 불필요하며, 기존 `_update_po_status_on_receiving()` 로직이 이미 충분함.

### 4.5 `material_requirement()` 라우트 개선

현재 문제: MaterialOrder 기준으로 발주/입고 현황을 조회하지만, BOM 부품별이 아닌 contract_item_id 기준으로 합산하므로 부정확.

변경:
- bom_item_id 기반 PurchaseOrderItem 조회로 정확한 발주량 계산
- 기존 MaterialOrder 기반 조회도 유지 (하위 호환, bom_item_id 없는 기존 데이터)

---

## 5. Implementation Order

| Step | Task | Files | Priority |
|------|------|-------|----------|
| 1 | DB 마이그레이션: bom_item_id 컬럼 추가 | `entities.py`, `db.py` | Must |
| 2 | 소요자재 계산 로직 개선 (bom_item_id 기반 발주/입고 조회) | `routes/bom.py` | Must |
| 3 | 발주서 자동 생성 API | `routes/bom.py` | Must |
| 4 | 소요자재 페이지 UI (체크박스, 발주 버튼, 프리뷰 모달) | `templates/bom_requirement.html` | Must |
| 5 | `_sync_po_to_material_orders()` 개선 | `routes/purchase_order.py` | Should |
| 6 | 발주서 상세에서 BOM 연결 표시 | `templates/po_detail.html` | Nice |

---

## 6. Success Criteria

### 6.1 Definition of Done

- [x] 소요자재 페이지에서 부족 자재 선택 -> 발주서 자동 생성 동작
- [x] 생성된 발주서의 품목에 bom_item_id가 정확히 연결됨
- [x] 기존 발주서/입고 CRUD가 정상 동작 (regression 없음)
- [x] 기존 데이터(bom_item_id=NULL)에서도 오류 없이 동작
- [x] 입고 완료 후 소요자재 페이지에서 발주/입고 현황이 정확히 반영됨

### 6.2 Quality Criteria

- [x] 새 FK 컬럼은 모두 nullable (기존 데이터 호환)
- [x] DB 마이그레이션은 IF NOT EXISTS 패턴 (멱등성)
- [x] 발주서 생성 시 거래처 없으면 자동 생성 (UX 끊김 방지)

---

## 7. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| BomItem.supplier와 Vendor.name 불일치 | High | High | ilike 매칭 + 없으면 자동 생성, 생성 후 사용자가 수정 가능 |
| 기존 PO/MaterialOrder 데이터에 bom_item_id 없음 | Medium | Certain | nullable FK + 기존 로직은 bom_item_id=NULL 시 기존 동작 유지 |
| 소요자재 계산이 느려질 수 있음 (JOIN 추가) | Low | Low | 인덱스 추가, 현재 데이터 규모에서는 문제 없음 |
| 동일 BOM 부품에 대한 중복 발주 | Medium | Medium | 발주 프리뷰에서 기존 발주 내역 표시, 경고 메시지 |

---

## 8. Architecture Considerations

### 8.1 Project Level

| Level | Selected |
|-------|:--------:|
| **Dynamic** | O |

### 8.2 Key Decisions

| Decision | Selected | Rationale |
|----------|----------|-----------|
| FK 연결 방식 | PurchaseOrderItem.bom_item_id, MaterialOrder.bom_item_id | 기존 테이블에 nullable FK 1개씩만 추가하여 최소 변경으로 추적성 확보 |
| 거래처 매칭 | BomItem.supplier -> Vendor.name ilike | BomItem에는 거래처 텍스트만 있으므로 문자열 매칭이 유일한 방법 |
| 소요량 계산 | 실시간 조회 (MaterialOrder/PurchaseOrderItem 상태 기반) | 별도 재고 테이블 없이 기존 구조 활용 |

---

## 9. Data Flow Diagram

```
[계약 품목 (ContractItem)]
        |
        | BOM 매칭 (model_name/category)
        v
[BOM 완제품 (BomHeader)] ─── [BOM 부품 (BomItem)]
                                    |
                        ┌───────────┼───────────┐
                        |           |           |
                   supplier    item_name    quantity
                        |           |           |
                        v           v           v
              [Vendor 매칭]   [PO Item 생성]  [소요량 계산]
                   |                |
                   v                v
            [PurchaseOrder] ── [PurchaseOrderItem]
                   |                |
                   |          bom_item_id (NEW)
                   v                |
            [이메일 발송]           |
                   |                v
            [MaterialOrder] ── bom_item_id (NEW)
                   |
                   v
            [Receiving] ── [ReceivingItem]
                   |
                   v
            [PO/MO 상태 갱신] ── [소요자재 실시간 반영]
```

---

## 10. Next Steps

1. [ ] Design 문서 작성 (`material-po-bom-integration.design.md`)
2. [ ] DB 마이그레이션 구현 및 테스트
3. [ ] 발주서 자동 생성 API 구현
4. [ ] 소요자재 페이지 UI 구현
5. [ ] 통합 테스트

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-18 | Initial draft | CTO Lead |
