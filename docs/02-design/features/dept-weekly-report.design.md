# Design: 부서별 주간보고서 (dept-weekly-report)

## 1. Architecture Overview

### 1.1 변경 구조

```
routes/report.py
  weekly_report()          # 기존 함수 → 부서 분기 라우터로 변경
  _weekly_sales()          # 영업부 (기존 로직 그대로 추출)
  _weekly_production()     # 생산부 신규
  _weekly_management()     # 관리부 신규

templates/
  report_weekly.html                # 영업부 (기존 유지, admin 드롭다운 추가)
  report_weekly_production.html     # 생산부 신규
  report_weekly_management.html     # 관리부 신규
```

### 1.2 부서 판별 + 접근 제어 Flow

```
GET /report/weekly?dept=XXX
  │
  ├─ dept 파라미터 있고 admin? → 해당 부서 보고서
  ├─ dept 파라미터 있고 비admin? → 403
  ├─ dept 없음 → session['user_group'] 기준 자동
  │    ├─ 영업부 → _weekly_sales()
  │    ├─ 생산부 → _weekly_production()
  │    ├─ 관리부/경영관리부 → _weekly_management()
  │    └─ 기타 → 403
  └─ admin이고 dept 없음 → 영업부 기본
```

## 2. Data Queries

### 2.1 생산부 보고서

**주간 요약 카드:**
- 생산중: `ContractItem.status_prod IN ('생산중', '조립중')` count
- 납품준비: `Delivery.delivery_status == '납품준비'` count
- 납품완료 (기간내): `DeliverySplit.delivered_done_at BETWEEN start..end` count
- AS접수 (기간내): `WarrantyCase.reported_date BETWEEN start..end` count

**생산 공정 현황:**
```sql
SELECT pp.*, ci.category, ci.model_name, p.temp_name, c.contract_name
FROM production_processes pp
JOIN contract_items ci ON pp.contract_item_id = ci.id
JOIN contracts c ON pp.contract_id = c.id
JOIN projects p ON pp.project_id = p.id
WHERE pp.status IN ('대기', '진행중')
ORDER BY p.temp_name, c.contract_name, pp.step_order
```

**납품 진행 현황:**
```sql
SELECT d.*, ds.*, p.temp_name
FROM deliveries d
JOIN delivery_splits ds ON ds.delivery_id = d.id
JOIN projects p ON d.project_id = p.id
WHERE d.delivery_status != '납품완료'
ORDER BY ds.scheduled_date ASC NULLS LAST
```

**AS/하자보증 현황:**
```sql
SELECT wc.*, p.temp_name
FROM warranty_cases wc
LEFT JOIN projects p ON wc.project_id = p.id
WHERE wc.status != '완료'
ORDER BY wc.reported_date DESC
```

### 2.2 관리부 보고서

**주간 요약 카드:**
- 발주건수 (기간내): `MaterialOrder.order_date BETWEEN start..end` count
- 입고건수 (기간내): `Receiving.rcv_date BETWEEN start..end` count
- 검수대기: `Receiving.status == '검수대기'` count
- 발주총액 (기간내): `PurchaseOrder.po_date BETWEEN start..end` SUM(total_amount)

**자재 발주 현황:**
```sql
SELECT mo.*, p.temp_name, ci.category, ci.model_name
FROM material_orders mo
JOIN projects p ON mo.project_id = p.id
JOIN contract_items ci ON mo.contract_item_id = ci.id
WHERE mo.order_status != '입고완료'
ORDER BY mo.order_date DESC NULLS LAST
```

**발주서 현황:**
```sql
SELECT po.*, v.name as vendor_name
FROM purchase_orders po
JOIN vendors v ON po.vendor_id = v.id
WHERE po.status != '취소'
AND po.po_date BETWEEN start AND end
ORDER BY po.po_date DESC
```

**입고 검수 현황:**
```sql
SELECT r.*, v.name as vendor_name
FROM receivings r
JOIN vendors v ON r.vendor_id = v.id
WHERE r.rcv_date BETWEEN start AND end
ORDER BY r.rcv_date DESC
```

## 3. Template Design

### 3.1 공통 스타일
- 영업부 `report_weekly.html`의 CSS 그대로 재사용
- `.report-container`, `.report-table`, `.summary-grid`, `.summary-card`
- 인쇄: `@page { size: landscape; }`, `.page-break`
- 테이블: `white-space: nowrap`, `font-size: 0.88rem`

### 3.2 Admin 부서 선택 드롭다운
- `.report-controls` 영역에 `<select name="dept">` 추가
- `session['role'] == 'admin'`일 때만 표시
- 선택 시 form submit으로 `?dept=XXX` 파라미터 전달

## 4. Implementation Order

1. `routes/report.py` - 부서 판별 + 접근 제어 + 생산부/관리부 쿼리 함수
2. `templates/report_weekly_production.html` - 생산부 템플릿
3. `templates/report_weekly_management.html` - 관리부 템플릿
4. `templates/report_weekly.html` - admin 드롭다운 추가

## 5. Risk & Constraints

- 영업부 기존 로직 절대 변경 불가 (함수 추출만)
- DB 변경 없음
- ContractItem.status_prod 값 확인 필요 (생산중/조립중 등 실제 사용값)
