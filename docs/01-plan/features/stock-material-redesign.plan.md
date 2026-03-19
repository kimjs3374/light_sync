# stock-material-redesign Planning Document

> **Summary**: 자재관리 재설계 — 실재고/가용재고 분리 운영, BOM 기반 자동 재고 판단, 예약/취소 메커니즘
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: Claude (PDCA)
> **Date**: 2026-03-18
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 자재 재고를 엑셀(자재CHECK LIST)로 수기 관리하여 ERP와 연동이 없음. 계약별 자재 확보 여부를 판단할 수 없고, 긴급현장 재고 돌려쓰기 시 추적이 불가능함. BOM 부품을 자재관리에 전부 넣으면 너무 많아 관리 불가. |
| **Solution** | Item 모델에 실재고(stock_qty)와 예약수량(reserved_qty)을 분리하여 가용재고(stock_qty - reserved_qty) 개념 도입. 계약 등록 시 BOM 기반으로 자동 판단하여 재고 충분 품목은 예약(재고이용), 부족 품목만 발주대기로 분류. 긴급현장 전용 시 예약 취소 → 가용재고 복원 → 다른 현장에서 재예약. |
| **기능/UX 효과** | 자재담당자가 품목별 재고/발주 상태를 일일이 체크할 필요 없이 자동 분류. 자재관리 화면에서 발주 필요 품목과 재고이용 품목을 탭으로 분리. 긴급현장 대응 시 예약 취소 1클릭으로 가용재고 확보. |
| **핵심 가치** | 엑셀 수기 관리 → 시스템 기반 실시간 재고 관리로 전환. 생산팀이 "이 현장 생산 가능한가?" 즉시 판단 가능. 재고 예약 충돌 방지. |

---

## 1. Overview

### 1.1 Purpose

자재 재고를 ERP 시스템에서 관리하고, 계약별 BOM 기반으로 재고 충분/부족을 자동 판단하여 자재관리 업무를 체계화한다.

### 1.2 Background

- 현재: 자재CHECK LIST 엑셀로 수기 관리 (품목별 재고 수량 기록)
- iCUBE 재고 데이터(LX_LINVTORY 22,573건)는 부정확하여 사용 불가
- BOM 부품을 자재관리에 전부 넣으면 계약당 10~20개 → 관리 불가
- 긴급현장에 재고를 돌려쓸 때 추적 방법이 없음
- 생산팀은 자재 입고 시점을 확인해야 생산계획 수립 가능

### 1.3 재고 개념 정의

```
실재고 (stock_qty)     = 창고에 물리적으로 존재하는 수량
예약수량 (reserved_qty) = 특정 현장/계약에 예약된 수량
가용재고 (available)    = stock_qty - reserved_qty (새 현장에 배정 가능한 수량)
```

**예시:**
```
SMPS HLG-480H: 실재고 100개
  A현장 예약: 50개
  B현장 예약: 30개
  가용재고: 20개

→ C현장에서 30개 필요 시: 가용재고 20개 부족 → 10개 발주대기
→ A현장 긴급 취소 시: 예약 50 해제 → 가용재고 70개 → C현장 충분
```

---

## 2. Requirements

### 2.1 Functional Requirements

| ID | 요구사항 | 우선순위 |
|----|---------|:--------:|
| FR-01 | Item 모델에 stock_qty, reserved_qty 필드 추가 | P0 |
| FR-02 | 자재CHECK LIST 엑셀에서 초기 재고 임포트 스크립트 | P0 |
| FR-03 | 계약 자재동기화 시 BOM 매칭 → 가용재고 비교 → 자동 분류 (재고이용/발주대기) | P0 |
| FR-04 | 재고이용 시 reserved_qty 증가 (예약) | P0 |
| FR-05 | 예약 취소 시 reserved_qty 감소 (가용재고 복원) | P0 |
| FR-06 | 자재관리 화면: 발주관리 탭 + 재고이용 탭 분리 | P1 |
| FR-07 | 입고 완료 시 stock_qty 자동 증가 | P1 |
| FR-08 | 품목관리 목록/상세에서 실재고/예약/가용 표시 | P1 |
| FR-09 | 재고이용 → 발주대기 전환 (예약 취소 + 가용재고 복원) | P1 |
| FR-10 | 발주대기 → 재고이용 전환 (재예약 + 가용재고 차감) | P1 |
| FR-11 | order_status에 "재고이용" 상태 추가 | P0 |
| FR-12 | compute_admin_status에서 "재고이용"을 완료 상태로 취급 | P0 |
| FR-13 | 자재관리 상세에서 발주서 바로 생성 (계약/품목/규격/수량 자동 연동, 단가 빈칸) | P0 |
| FR-14 | 발주대기 자재 일괄 발주서 생성 (거래처별 그룹핑, 부족수량 자동 계산) | P1 |
| FR-15 | 일괄발주 시 발주 필요 수량 자동 계산 (필요수량 - 가용재고) + 수동 수정 가능 | P1 |
| FR-16 | 일괄발주 발주서 순차 이메일 발송 (거래처별 PDF 생성 → 순환 발송) | P2 |
| FR-17 | 재고 수량 수동 수정 기능 (품목관리 또는 자재관리에서) | P1 |

### 2.2 Non-Functional Requirements

- 기존 자재관리/발주/입고 기능 절대 깨지면 안 됨
- BOM 매칭 안 되는 계약품목은 기존 하드코딩 fallback 유지
- 재고 음수 방지 (reserved_qty > stock_qty 허용하지 않음)
- 엑셀 임포트 여러 번 실행해도 안전 (idempotent)

---

## 3. Implementation Items

| # | 작업 | 파일 | 우선순위 |
|---|------|------|:--------:|
| 1 | Item 모델 확장 (stock_qty, reserved_qty) | `entities.py`, `db.py` | P0 |
| 2 | 엑셀 재고 임포트 스크립트 | `scripts/import_stock_from_excel.py` (신규) | P0 |
| 3 | 자재동기화 로직 변경 (BOM + 재고 판단) | `routes/material.py` | P0 |
| 4 | order_status "재고이용" 추가 + admin 상태 | `routes/material.py` | P0 |
| 5 | 자재관리 화면 탭 분리 | `templates/material_detail.html` | P1 |
| 6 | 예약 취소/재예약 API | `routes/material.py` | P1 |
| 7 | 입고 시 stock_qty 증가 | `routes/receiving.py` | P1 |
| 8 | 품목관리에 재고 표시 | `routes/item.py`, `templates/item_list.html` | P1 |
| 9 | 자재관리→발주서 바로 생성 (자동연동) | `routes/material.py`, `templates/material_detail.html` | P0 |
| 10 | 발주대기 자재 일괄 발주서 생성 | `routes/material.py`, `templates/material_detail.html` | P1 |
| 11 | 일괄발주 순차 이메일 발송 | `routes/purchase_order.py` | P2 |
| 12 | 재고 수량 수동 수정 | `routes/item.py`, `templates/item_detail.html` | P1 |

---

## 4. 핵심 로직 상세

### 4.1 자재동기화 (FR-03, FR-04)

```python
def sync_material_orders_for_contract_item(db, contract, item):
    bom = _find_bom_for_contract_item(db, item)

    if bom and bom.bom_items:
        for bi in bom.bom_items:
            needed = bi.quantity * item.quantity
            linked_item = db.query(Item).get(bi.item_id) if bi.item_id else None
            available = (linked_item.stock_qty - linked_item.reserved_qty) if linked_item else 0

            if needed <= available:
                # 재고 충분 → 재고이용 + 예약
                order_status = '재고이용'
                linked_item.reserved_qty += needed
                shortage = 0
            else:
                # 재고 부족 → 있는 만큼 예약 + 부족분 발주대기
                if available > 0 and linked_item:
                    linked_item.reserved_qty += available
                order_status = '발주대기'
                shortage = needed - max(available, 0)

            # MaterialOrder 생성/업데이트
            ...
    else:
        # BOM 없음 → 기존 하드코딩 fallback
        ...
```

### 4.2 예약 취소 (FR-05, FR-09)

```python
def cancel_reservation(db, material_order_id):
    mo = db.query(MaterialOrder).get(material_order_id)
    if mo.order_status != '재고이용':
        return

    item = db.query(Item).get(mo.bom_item.item_id)
    item.reserved_qty = max(0, item.reserved_qty - mo.quantity)
    mo.order_status = '발주대기'
```

### 4.3 재예약 (FR-10)

```python
def reserve_from_stock(db, material_order_id):
    mo = db.query(MaterialOrder).get(material_order_id)
    item = db.query(Item).get(mo.bom_item.item_id)
    available = item.stock_qty - item.reserved_qty

    if mo.quantity <= available:
        item.reserved_qty += mo.quantity
        mo.order_status = '재고이용'
    else:
        return '가용재고 부족'
```

### 4.4 자재관리→발주서 바로 생성 (FR-13)

```python
def create_po_from_material(db, material_order_id):
    mo = db.query(MaterialOrder).get(material_order_id)
    contract = db.query(Contract).get(mo.contract_id)
    bom_item = mo.bom_item  # BomItem → supplier로 거래처 매칭

    # 거래처 자동 매칭 (BomItem.supplier → Vendor)
    vendor = db.query(Vendor).filter(Vendor.name.ilike(f'%{bom_item.supplier}%')).first()

    po = PurchaseOrder(
        po_no=_generate_po_no(db),
        vendor_id=vendor.id,
        contract_id=contract.id,
        project_id=contract.project_id,
        # 자동 연동 필드들
    )
    po_item = PurchaseOrderItem(
        item_name=bom_item.item_name,       # 품명 자동
        item_spec=bom_item.item_spec,       # 규격 자동
        quantity=mo.quantity,                # 부족수량 자동
        unit_price=None,                    # 단가는 빈칸 (변동)
        bom_item_id=bom_item.id,
    )
```

### 4.5 일괄 발주서 생성 (FR-14, FR-15)

```python
def bulk_create_po_from_materials(db, contract_id):
    # 발주대기인 MaterialOrder들을 거래처별 그룹핑
    pending_orders = db.query(MaterialOrder).filter(
        MaterialOrder.contract_id == contract_id,
        MaterialOrder.order_status == '발주대기',
    ).all()

    # 거래처별 그룹핑 (BomItem.supplier 기준)
    groups = {}  # supplier_name → [mo, mo, ...]
    for mo in pending_orders:
        supplier = mo.bom_item.supplier if mo.bom_item else '미지정'
        groups.setdefault(supplier, []).append(mo)

    # 각 거래처별 PurchaseOrder 생성
    created_pos = []
    for supplier, orders in groups.items():
        po = PurchaseOrder(...)
        for mo in orders:
            # 발주 필요 수량 = 필요수량 - 가용재고 (자동 계산)
            # 사용자가 수정 가능하도록 프리뷰 모달에서 확인
            po_item = PurchaseOrderItem(
                quantity=mo.quantity,       # 부족분
                unit_price=None,           # 단가 빈칸
            )
        created_pos.append(po)
    return created_pos
```

### 4.6 일괄 이메일 순차 발송 (FR-16)

```python
def bulk_send_po_emails(db, po_ids):
    """여러 발주서를 거래처별로 순차 이메일 발송"""
    results = []
    for po_id in po_ids:
        po = db.query(PurchaseOrder).get(po_id)
        if not po.vendor.email:
            results.append({'po_no': po.po_no, 'status': 'skip', 'reason': '이메일 없음'})
            continue
        try:
            # 기존 po_send_email 로직 재활용
            pdf = generate_po_pdf(po, po.vendor, po.items)
            send_email(to=po.vendor.email, subject=f'발주서 {po.po_no}', pdf=pdf)
            po.status = '발송완료'
            po.email_sent_at = datetime.now()
            results.append({'po_no': po.po_no, 'status': 'sent'})
        except Exception as e:
            results.append({'po_no': po.po_no, 'status': 'error', 'reason': str(e)})
    return results
```

---

## 5. 화면 구성

### 5.1 자재관리 상세 (material_detail.html)

```
[발주관리] [재고이용]  ← 탭
[일괄발주] [재고수량수정] ← 상단 액션 버튼

발주관리 탭:
| 자재명 | 필요수량 | 가용재고 | 부족분 | 발주상태 | 발주일 | 예상입고 | 액션 |
| PCB    | 100     | 30      | 70    | 발주완료 | 03-15 | 03-25   | -    |
| SMPS   | 100     | 0       | 100   | 발주대기 | -     | -       | [발주서생성] |

재고이용 탭:
| 자재명 | 필요수량 | 예약수량 | 실재고 | 액션 |
| LED    | 100     | 100     | 500   | [예약취소] |
| 렌즈   | 100     | 100     | 200   | [예약취소] |
```

### 5.2 일괄발주 프리뷰 모달

```
──── 일괄발주 프리뷰 ────────────────────
거래처별 자동 그룹핑:

▶ (주)셀파세미컴 (2건)
| 품명          | 규격      | 필요 | 재고 | 발주수량 | 단가 |
| LED Chip      | XPLB...  | 100  | 20   | [80]    | [  ] |  ← 수동 수정 가능
| PCB-STA-108   | METAL    | 50   | 0    | [50]    | [  ] |

▶ Mean Well (1건)
| 품명          | 규격      | 필요 | 재고 | 발주수량 | 단가 |
| HLG-480H-54A  | 480W    | 30   | 5    | [25]    | [  ] |

[일괄 발주서 생성] [일괄 발주서 생성 + 이메일 발송]
```

### 5.3 품목관리 목록

```
| 품번 | 품명 | 규격 | 실재고 | 예약 | 가용 | 거래 |
```

### 5.4 품목 상세 — 재고 수동 수정

```
실재고: [100] ← input으로 수동 수정 가능
예약:   50 (자동 계산)
가용:   50 (자동 계산)
[재고 수정 저장]
```

---

## 6. Risks

| 리스크 | 대응 |
|--------|------|
| 엑셀 재고 데이터 구조 파악 필요 | 시트별 구조 분석 후 임포트 |
| BOM 매칭 안 되는 품목 | 기존 하드코딩 fallback 유지 |
| 동시 예약 충돌 | DB 트랜잭션으로 보장 |
| reserved_qty 음수 | max(0, ...) 방어 코드 |
