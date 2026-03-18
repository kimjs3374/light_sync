# material-po-bom-integration Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: Light-Sync ERP
> **Analyst**: CTO Lead
> **Date**: 2026-03-18
> **Design Doc**: [material-po-bom-integration.design.md](../02-design/features/material-po-bom-integration.design.md)
> **Plan Doc**: [material-po-bom-integration.plan.md](../../01-plan/features/material-po-bom-integration.plan.md)

---

## 1. Analysis Overview

### 1.1 Analysis Scope

- **Design Document**: `docs/02-design/features/material-po-bom-integration.design.md`
- **Plan Document**: `docs/01-plan/features/material-po-bom-integration.plan.md`
- **Implementation Files**:
  - `modules/models/entities.py`
  - `modules/models/db.py`
  - `routes/bom.py`
  - `routes/purchase_order.py`
  - `routes/receiving.py`
  - `templates/bom_requirement.html`
  - `templates/po_detail.html`

---

## 2. FR 체크리스트 (7개)

| FR | 내용 | 설계 | 구현 | 상태 |
|----|------|------|------|------|
| FR-01 | 소요자재 부족분 → 거래처별 발주서 자동 생성 API | POST `/bom/create-po-from-requirement` | `routes/bom.py:432` | ✅ 일치 |
| FR-02 | PurchaseOrderItem.bom_item_id FK | entities.py 컬럼 + db.py ALTER TABLE | `entities.py:913`, `db.py:103` | ✅ 일치 |
| FR-03 | MaterialOrder.bom_item_id FK | entities.py 컬럼 + db.py ALTER TABLE | `entities.py:296`, `db.py:111` | ✅ 일치 |
| FR-04 | 소요자재 UI (체크박스 + 발주 버튼 + 프리뷰 모달) | 체크박스/전체선택/프리뷰 모달 | `templates/bom_requirement.html` | ✅ 일치 |
| FR-05 | 입고 완료 시 소요자재 자동 반영 | MaterialOrder.order_status → 소요자재 페이지 실시간 반영 | `routes/receiving.py:90` | ✅ 일치 |
| FR-06 | 발주서 상세에서 BOM 연결 표시 | bom_item_id → BomHeader.product_name 표시 | `templates/po_detail.html:178`, `routes/purchase_order.py:318` | ✅ 일치 |
| FR-07 | _sync_po_to_material_orders bom_item_id 매칭 | bom_item_id가 있으면 BOM 경로로 정확 매칭, 없으면 fallback | `routes/purchase_order.py:97` | ✅ 일치 |

**FR 구현율: 7/7 (100%)**

---

## 3. Gap Analysis (Design vs Implementation)

### 3.1 API Endpoints

| 설계 | 구현 | 상태 | 비고 |
|------|------|------|------|
| POST `/bom/create-po-from-requirement` | `routes/bom.py:432` | ✅ 일치 | supplier 그룹핑, Vendor ilike, PO 자동 생성 모두 구현 |
| GET `/api/bom/requirement-for-po` | 미구현 | ⚠️ 설계에만 존재 | 설계 doc 4.2절 언급 API — 실제로는 bom_requirement() 내 로직으로 통합 처리. 별도 API 불필요 판단으로 생략 |

**참고**: `GET /api/bom/requirement-for-po`는 Plan(4.2.2절)에 프리뷰용 JSON API로 명시되어 있으나, 실제 구현은 프리뷰를 클라이언트 JS에서 직접 처리(이미 로드된 체크박스 data-* 속성 활용)하여 서버 API 호출 없이 동작. 기능 목적은 충족.

### 3.2 Data Model

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| PurchaseOrderItem.bom_item_id | `Integer, FK(bom_items.id), nullable=True` | `entities.py:913` — Column(Integer, ForeignKey('bom_items.id'), nullable=True) | ✅ 일치 |
| PurchaseOrderItem.bom_item relationship | `relationship("BomItem", foreign_keys=[bom_item_id])` | `entities.py:916` — 동일 | ✅ 일치 |
| MaterialOrder.bom_item_id | `Integer, FK(bom_items.id), nullable=True` | `entities.py:296` — Column(Integer, ForeignKey('bom_items.id'), nullable=True) | ✅ 일치 |
| MaterialOrder.bom_item relationship | `relationship("BomItem", foreign_keys=[bom_item_id])` | `entities.py:304` — 동일 | ✅ 일치 |
| DB 마이그레이션 — purchase_order_items | ALTER TABLE IF NOT EXISTS 패턴 | `db.py:102` — try/except pass 패턴 (멱등성) | ✅ 일치 |
| DB 마이그레이션 — material_orders | ALTER TABLE IF NOT EXISTS 패턴 | `db.py:111` — try/except pass 패턴 (멱등성) | ✅ 일치 |

### 3.3 소요자재 계산 로직 (material_requirement)

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| 1차: bom_item_id 기반 PurchaseOrderItem 발주량 | coalesce(sum(PurchaseOrderItem.quantity)) WHERE bom_item_id=bi.id AND contract_id | `bom.py:364` — 동일 로직 | ✅ 일치 |
| 2차: MaterialOrder 기반 fallback | coalesce(sum(MaterialOrder.quantity)) WHERE contract_item_id=ci.id | `bom.py:375` — 동일 로직 | ✅ 일치 |
| max() 중복 방지 | ordered = max(ordered_via_po, ordered_via_mo) | `bom.py:384` — 동일 | ✅ 일치 |
| 취소 PO 제외 | PurchaseOrder.status != '취소' 필터 | `bom.py:372` — 구현됨 | ✅ 설계에 없던 개선 사항 추가 |

### 3.4 발주서 자동 생성 API (create_po_from_requirement)

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| supplier 기준 그룹핑 | defaultdict(list) | `bom.py:462` | ✅ 일치 |
| Vendor ilike 매칭 | Vendor.name.ilike('%{supplier}%') | `bom.py:471` | ✅ 일치 |
| Vendor 자동 생성 | is_active=True로 생성 | `bom.py:478` | ✅ 일치 |
| PO 생성 필드 | po_no, po_date, vendor_id, contract_id, project_id, status='작성중' | `bom.py:483` | ✅ 일치 (project_id, assigned_to, created_by 추가 구현) |
| PurchaseOrderItem.bom_item_id 설정 | bom_item_id 설정 | `bom.py:511` | ✅ 일치 |
| total_amount / tax_amount 계산 | tax_amount = round(total * 0.1) | `bom.py:516` | ✅ 일치 |
| 1건 → PO 상세 redirect | 1건이면 po_detail로 redirect | `bom.py:522` | ✅ 일치 |
| N건 → 발주서 목록 redirect | N건이면 po_list로 redirect | `bom.py:526` | ✅ 일치 |
| CSRF token | `csrf_token: string` (Form POST with CSRF) | `bom_requirement.html:148` — csrf_token() 사용 | ✅ 일치 |

### 3.5 _sync_po_to_material_orders (FR-07)

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| bom_item_id 있으면 BOM 경로 매칭 | BomItem → BomHeader → product_name/code로 ContractItem 매칭 | `purchase_order.py:99` | ✅ 일치 |
| bom_item_id 없으면 기존 품명 유사도 fallback | contract_items[0] + 품명 유사도 | `purchase_order.py:115` | ✅ 일치 |
| MaterialOrder.bom_item_id 설정 | mo.bom_item_id = po_item.bom_item_id | `purchase_order.py:141` | ✅ 일치 |

### 3.6 소요자재 UI (FR-04)

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| 체크박스: shortage > 0인 행에만 표시 | shortage > 0 조건 | `bom_requirement.html:78` | ✅ 일치 |
| BOM 미등록 행: 체크박스 없음 | no_bom 플래그 | `bom_requirement.html:78` — `not r.get('no_bom')` 조건 | ✅ 일치 |
| "전체 선택" 체크박스 (헤더) | checkAll | `bom_requirement.html:60` | ✅ 일치 |
| "선택 자재 발주서 생성" 버튼 | 선택 수 표시 + 모달 트리거 | `bom_requirement.html:51` | ✅ 일치 |
| 거래처별 그룹핑 프리뷰 모달 | 거래처별 소계 표시 | `bom_requirement.html:211` — JS에서 동적 생성 | ✅ 일치 |
| 거래처 컬럼 | 설계 wireframe에 없음 | 구현에 거래처 컬럼 추가됨 | ⚠️ 설계 초과 (긍정적) |

### 3.7 발주서 상세 BOM 연결 표시 (FR-06)

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| bom_item_id 있는 품목: BomHeader.product_name 표시 | BomHeader.product_name + BomItem.item_name | `po_detail.html:178` — bom_item.bom_header.product_name 표시 | ✅ 일치 |
| bom_item_id 없는 품목: '-' 표시 | '-' | `po_detail.html:182` | ✅ 일치 |
| joinedload 최적화 | (설계 미명시) | `purchase_order.py:318` — PurchaseOrderItem → BomItem → BomHeader joinedload | ✅ 설계 초과 (N+1 방지) |

### 3.8 FR-05 입고 완료 → 소요자재 자동 반영

| 항목 | 설계 | 구현 | 상태 |
|------|------|------|------|
| MaterialOrder.order_status = '입고완료' 갱신 | 기존 _update_po_status_on_receiving() 로직으로 충분 | `receiving.py:90` — MaterialOrder.order_status = '입고완료' 설정 | ✅ 일치 |
| 소요자재 페이지 실시간 반영 | MaterialOrder 상태 기반 실시간 계산 | `bom.py:375` — order_status IN ('발주완료', '입고완료') 필터 | ✅ 일치 |

---

## 4. 차이점 요약

### 4.1 설계에만 있고 구현 안 된 항목

| 항목 | 설계 위치 | 미구현 이유 |
|------|-----------|-------------|
| GET `/api/bom/requirement-for-po` JSON API | plan.md 4.2.2, design.md 4.2 | 클라이언트 JS에서 data-* 속성으로 직접 처리 — 서버 API 불필요. 기능 목적 동일하게 충족 |

### 4.2 구현에만 있고 설계에 없는 항목 (긍정적 추가)

| 항목 | 구현 위치 | 설명 |
|------|-----------|------|
| PO 생성 시 project_id, assigned_to, created_by 설정 | `bom.py:488` | UX 및 이력 추적 강화 |
| 취소(status='취소') PO 제외 필터 | `bom.py:372` | 데이터 정확도 개선 |
| 소요자재 테이블 거래처 컬럼 | `bom_requirement.html:64` | 발주 계획 수립에 유용 |
| joinedload로 BomItem → BomHeader 최적화 | `purchase_order.py:318` | N+1 쿼리 방지 |

### 4.3 설계와 다르게 구현된 항목

| 항목 | 설계 | 구현 | 영향도 |
|------|------|------|--------|
| Vendor ilike 매칭 범위 | `Vendor.name.ilike('%supplier%')` — AND is_active=True | 동일 | 없음 |
| bom_item_id 설정 방식 | `bom_item_id=item.get('bom_item_id')` | `safe_int(item.get('bom_item_id'), 0) or None` | 없음 (더 안전한 처리) |

---

## 5. 전체 점수

| 범주 | 점수 | 상태 |
|------|:----:|:----:|
| FR 구현 완성도 | 100% | ✅ |
| 설계-구현 일치도 | 97% | ✅ |
| 설계 초과 구현 (긍정) | 4건 | ✅ |
| 미구현 항목 | 1건 (기능 목적 충족) | ✅ |
| **Overall Match Rate** | **97%** | **✅** |

```
┌─────────────────────────────────────────────┐
│  Overall Match Rate: 97%                     │
├─────────────────────────────────────────────┤
│  ✅ 설계-구현 일치:   30건                   │
│  ⚠️ 설계 초과 (긍정): 4건                   │
│  ❌ 미구현 (기능 대체): 1건                  │
└─────────────────────────────────────────────┘
```

---

## 6. 코드 품질 관찰

| 항목 | 위치 | 평가 |
|------|------|------|
| bom_item_id 안전 처리 | `bom.py:511` — `safe_int(...) or None` | 양호 — 0을 NULL로 처리 |
| N+1 방지 joinedload | `purchase_order.py:318` | 양호 — BomItem.bom_header까지 eager loading |
| _sync_po_to_material_orders fallback | `purchase_order.py:115` — contract_items[0]로 fallback | 주의 — contract_items가 비어있으면 IndexError 위험 없음 (if not contract_items: return 처리됨) |
| 소요자재 BOM 매칭 | `bom.py:346` — model_name → category 순 매칭 | 양호 — 두 단계 fallback |
| Vendor 자동 생성 시 중복 생성 위험 | `bom.py:471` — first()로 첫 번째 매칭만 사용 | 양호 |

---

## 7. 권장 액션

### 즉시 필요 없음 (Match Rate 97%)

### 문서 업데이트 필요

- [ ] `GET /api/bom/requirement-for-po` API 제거 또는 "클라이언트 JS 처리로 대체" 주석 추가 (`design.md` 4.2절)
- [ ] 소요자재 테이블 거래처 컬럼 wireframe에 반영 (`design.md` 5.1절)

### 선택적 개선 (Low Priority)

- [ ] 발주 프리뷰 모달에서 기존 발주 내역 경고 표시 — plan.md 위험 항목 "동일 BOM 부품 중복 발주" 미구현. 현재 발주량 컬럼으로 확인은 가능하나 모달에서 명시적 경고는 없음.

---

## 8. 다음 단계

- [x] Gap 분석 완료 (Match Rate 97% → 정상)
- [ ] `/pdca report material-po-bom-integration` — 완료 보고서 작성

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-18 | Initial gap analysis | CTO Lead |
