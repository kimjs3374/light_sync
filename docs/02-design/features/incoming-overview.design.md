# Design: incoming-overview

## Context Anchor (from Plan)

| Key | Value |
|-----|-------|
| WHY | 발주/입고/가공발주 분산 → 생산팀 자재 추적 어려움 |
| WHO | 생산부 / 관리부 / 임공진 |
| RISK | N+1 쿼리, 대량 데이터 |
| SUCCESS | 한 화면 통합, 잔량 정확도 100% |
| SCOPE | PO 기반 흐름만 (v1) |

## 1. Architecture (Selected: Option C — Pragmatic Balance)

신규 라우트 모듈 1개(`routes/incoming_overview.py`) + 모바일 API 1개(`app_api.py` 추가) + PC 템플릿 1개 + 모바일 페이지 1개. 기존 PO/Receiving 모델 그대로 사용, JOIN/집계는 라우트에서 처리.

## 2. Data Model

기존 모델 사용:
- `PurchaseOrder` (id, po_no, po_date, vendor_id, project_id, status)
- `PurchaseOrderItem` (id, po_id, item_name, item_spec, quantity, delivery_date, unit)
- `ReceivingItem` (id, po_item_id, received_qty)

### 2.1 집계 쿼리

```python
# 활성 PO 품목 (취소 제외)
po_items = db.query(PurchaseOrderItem).join(PurchaseOrder).options(
    joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.vendor),
    joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.project),
    joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.contract),
).filter(PurchaseOrder.status != '취소').all()

# 입고량 합계 (po_item_id별)
recv_sums = dict(db.query(
    ReceivingItem.po_item_id,
    func.sum(ReceivingItem.received_qty)
).filter(ReceivingItem.po_item_id.isnot(None)).group_by(ReceivingItem.po_item_id).all())
```

### 2.2 상태 계산
```python
def compute_status(qty, recv, due_date):
    remain = qty - recv
    if remain <= 0: return 'done'  # 입고완료
    if recv > 0:    return 'partial'  # 부분입고
    if due_date and due_date < today: return 'overdue'  # 지연
    return 'pending'  # 미입고
```

## 3. API Contract

### 3.1 PC HTML
- `GET /production/incoming` → `templates/incoming_overview.html`
- Query: `?status=all|pending|partial|done|overdue`, `?q=검색어`, `?from=YYYY-MM-DD`, `?to=YYYY-MM-DD`
- 응답: `items[], stats{}`

### 3.2 Mobile JSON
- `GET /api/incoming-overview` → JSON
- 응답:
```json
{
  "ok": true,
  "items": [{
    "po_id": 1, "po_no": "PO2026-001", "po_date": "2026-01-01",
    "vendor_name": "거래처", "project_name": "현장",
    "item_name": "철제가로등", "item_spec": "8m",
    "quantity": 100, "received_qty": 30, "remain": 70,
    "delivery_date": "2026-04-30", "unit": "EA",
    "status": "partial", "status_label": "부분입고"
  }],
  "stats": {"pending": 10, "partial": 5, "done": 80, "overdue": 3, "this_week": 12, "today_in": 2}
}
```

## 4. UI

### 4.1 PC (`templates/incoming_overview.html`)
- `page-hero` 헤더 (eyebrow: "Incoming Items", title: "발주/입고현황", sub)
- 4개 KPI 카드 (border-left 색 stripe + stat-num + stat-label)
  - 미입고(amber) / 지연(red) / 7일내(blue) / 오늘 입고(green)
- 상태 탭 (`btn-group`): 전체 / 미입고 / 부분 / 완료 / 지연
- 검색 + 기간 필터
- 메인 테이블 (po-table 스타일):
  - 컬럼: 예정일 | PO번호 | 거래처 | 품목명+규격 | 현장 | 발주량 | 입고량 | 잔량 | 상태
  - 정렬: 지연>미입고>부분 우선, 이내 예정일 오름차순
  - 행 클릭 → PO 상세

### 4.2 Mobile (`mobile/src/pages/IncomingOverview.jsx`)
- ListPage 컴포넌트 재사용
- stats 4장 (전체/미입고/지연/완료)
- filters: 상태 select 1개
- 카드: Indicator(상태색) + 품목명(굵게) + 거래처·현장 + 잔량/발주 + 예정일 + 상태 Badge
- onItemClick → `/m/purchase-orders/:po_id`

## 5. File Plan

| File | Action |
|------|--------|
| `config.py` | MENU_REGISTRY에 `incoming_overview` 추가, DEFAULT_GROUP_MENUS에 권한 추가 |
| `routes/incoming_overview.py` | 신규 - PC 라우트 1개 |
| `app.py` | blueprint import + register |
| `templates/incoming_overview.html` | 신규 - PC 템플릿 |
| `routes/app_api.py` | `/api/incoming-overview` 엔드포인트 추가 |
| `mobile/src/pages/IncomingOverview.jsx` | 신규 - 모바일 페이지 |
| `mobile/src/App.jsx` | 라우트 등록 |
| `mobile/src/pages/More.jsx` | 생산부 메뉴에 항목 추가 |

## 6. Implementation Order
1. config.py — 메뉴 + 권한
2. routes/incoming_overview.py — PC 라우트 + 집계 로직
3. app.py — blueprint 등록
4. routes/app_api.py — JSON API
5. templates/incoming_overview.html — PC UI (frontend-architect)
6. mobile/IncomingOverview.jsx — 모바일 UI (frontend-architect)
7. mobile/App.jsx + More.jsx — 라우트/메뉴 연결
8. systemctl restart light_sync
