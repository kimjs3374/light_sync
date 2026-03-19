# 재고관리 (Inventory Management) 설계서

> **Summary**: 재고실사/가용재고/회전율/금액관리를 위한 데이터 모델 및 UI 설계
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead
> **Date**: 2026-03-19
> **Status**: Draft
> **Planning Doc**: [inventory-management.plan.md](../01-plan/features/inventory-management.plan.md)

---

## 1. 설계 목표

1. **기존 인프라 최대 활용**: Item.stock_qty/reserved_qty, Receiving 입고로직, 예약로직을 변경 없이 확장
2. **재고 변동의 완전한 추적**: 모든 재고 증감에 대해 StockMovement 이력 기록
3. **재고실사 워크플로우**: 실사생성 -> 수량입력 -> 차이확인 -> 조정확정 4단계
4. **금액 기반 관리**: 재고 = 돈, 모든 조회에 금액 컬럼 포함

---

## 2. 데이터 모델

### 2.1 신규 테이블

#### StockAudit (재고실사 회차)

```sql
CREATE TABLE stock_audits (
    id SERIAL PRIMARY KEY,
    audit_no VARCHAR(20) UNIQUE NOT NULL,       -- SA2026-001
    audit_date DATE NOT NULL,                    -- 실사일
    auditor_id INTEGER REFERENCES users(id),     -- 실사자
    auditor_name VARCHAR(50) NOT NULL,           -- 실사자명
    status VARCHAR(20) DEFAULT '진행중',          -- 진행중/완료/취소
    note TEXT,
    total_items INTEGER DEFAULT 0,               -- 실사 품목 수
    diff_items INTEGER DEFAULT 0,                -- 차이 발생 품목 수
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### StockAuditItem (실사 품목 상세)

```sql
CREATE TABLE stock_audit_items (
    id SERIAL PRIMARY KEY,
    audit_id INTEGER REFERENCES stock_audits(id) NOT NULL,
    item_id INTEGER REFERENCES items(id) NOT NULL,
    system_qty FLOAT DEFAULT 0,                  -- 실사 시점 시스템재고
    actual_qty FLOAT,                            -- 실사 수량 (사용자 입력)
    diff_qty FLOAT DEFAULT 0,                    -- actual - system
    diff_reason TEXT,                             -- 차이 사유
    is_adjusted BOOLEAN DEFAULT FALSE,           -- 조정 확정 여부
    adjusted_at TIMESTAMP,
    UNIQUE(audit_id, item_id)
);
```

#### StockMovement (재고 변동 이력)

```sql
CREATE TABLE stock_movements (
    id SERIAL PRIMARY KEY,
    item_id INTEGER REFERENCES items(id) NOT NULL,
    movement_type VARCHAR(20) NOT NULL,          -- IN_RECEIVING / IN_ADJUST / OUT_RESERVE / OUT_CANCEL_RESERVE / AUDIT_ADJUST
    quantity FLOAT NOT NULL,                     -- 양수=입고, 음수=출고
    before_qty FLOAT DEFAULT 0,                  -- 변동 전 재고
    after_qty FLOAT DEFAULT 0,                   -- 변동 후 재고
    unit_price FLOAT,                            -- 변동 시점 단가
    reference_type VARCHAR(30),                  -- receiving / purchase_order / stock_audit / material_order
    reference_id INTEGER,                        -- 참조 테이블 ID
    note TEXT,
    created_by VARCHAR(50) DEFAULT '시스템',
    created_at TIMESTAMP DEFAULT NOW()
);
-- 인덱스
CREATE INDEX idx_stock_movement_item ON stock_movements(item_id);
CREATE INDEX idx_stock_movement_type ON stock_movements(movement_type);
CREATE INDEX idx_stock_movement_date ON stock_movements(created_at);
```

### 2.2 기존 테이블 컬럼 추가

#### Item 테이블 확장

```sql
-- 안전재고 기준
ALTER TABLE items ADD COLUMN safety_stock FLOAT DEFAULT 0;

-- 최근 입고단가 (캐시, 입고 시 자동 갱신)
ALTER TABLE items ADD COLUMN last_unit_price FLOAT DEFAULT 0;
```

### 2.3 Entity 관계도

```
[Item] 1 ──── N [StockMovement]       재고 변동 이력
   │
   └── N ──── 1 [StockAuditItem]      실사 품목
                    │
                    N ──── 1 [StockAudit]  실사 회차

[Item] ── stock_qty        (총재고)
       ── reserved_qty     (예약수량)
       ── safety_stock     (안전재고, NEW)
       ── last_unit_price  (최근단가, NEW)

가용재고 = stock_qty - reserved_qty  (계산 필드, DB 컬럼 아님)
재고금액 = stock_qty * last_unit_price  (계산 필드, DB 컬럼 아님)
```

### 2.4 SQLAlchemy 모델 (entities.py 추가)

```python
# 재고실사 회차
class StockAudit(Base):
    __tablename__ = 'stock_audits'
    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_no = Column(String(20), unique=True, nullable=False)
    audit_date = Column(Date, nullable=False)
    auditor_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    auditor_name = Column(String(50), nullable=False)
    status = Column(String(20), default='진행중')  # 진행중/완료/취소
    note = Column(Text, nullable=True)
    total_items = Column(Integer, default=0)
    diff_items = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    audit_items = relationship("StockAuditItem", back_populates="audit", cascade="all, delete-orphan")

# 실사 품목 상세
class StockAuditItem(Base):
    __tablename__ = 'stock_audit_items'
    __table_args__ = (
        UniqueConstraint('audit_id', 'item_id', name='uq_audit_item'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(Integer, ForeignKey('stock_audits.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=False)
    system_qty = Column(Float, default=0)
    actual_qty = Column(Float, nullable=True)
    diff_qty = Column(Float, default=0)
    diff_reason = Column(Text, nullable=True)
    is_adjusted = Column(Boolean, default=False)
    adjusted_at = Column(DateTime, nullable=True)

    audit = relationship("StockAudit", back_populates="audit_items")
    item = relationship("Item")

# 재고 변동 이력
MOVEMENT_TYPES = [
    'IN_RECEIVING',         # 입고
    'IN_ADJUST',            # 수동 조정 (증가)
    'OUT_ADJUST',           # 수동 조정 (감소)
    'OUT_RESERVE',          # 예약 (출고 예정)
    'IN_CANCEL_RESERVE',    # 예약 취소 (복원)
    'AUDIT_ADJUST',         # 실사 조정
]

class StockMovement(Base):
    __tablename__ = 'stock_movements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=False)
    movement_type = Column(String(20), nullable=False)
    quantity = Column(Float, nullable=False)
    before_qty = Column(Float, default=0)
    after_qty = Column(Float, default=0)
    unit_price = Column(Float, nullable=True)
    reference_type = Column(String(30), nullable=True)
    reference_id = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String(50), default='시스템')
    created_at = Column(DateTime, default=datetime.datetime.now)

    item = relationship("Item")
```

---

## 3. db.py 마이그레이션 코드

```python
# items: safety_stock, last_unit_price 추가 (v2026-03-19, 재고관리)
for col, col_type in [
    ('safety_stock', 'FLOAT DEFAULT 0'),
    ('last_unit_price', 'FLOAT DEFAULT 0'),
]:
    try:
        conn.execute(text(
            f"ALTER TABLE {quote_ident(DB_SCHEMA)}.items "
            f"ADD COLUMN {col} {col_type}"
        ))
    except Exception:
        pass  # 이미 존재하면 무시
```

(stock_audits, stock_audit_items, stock_movements 테이블은 Base.metadata.create_all()로 자동 생성)

---

## 4. 라우트 설계 (routes/inventory.py)

### 4.1 엔드포인트 목록

| Method | Path | 설명 | FR |
|--------|------|------|-----|
| GET | `/inventory` | 재고 현황 대시보드 | FR-01 |
| GET | `/inventory/items` | 가용재고 목록 (필터/검색) | FR-05 |
| GET | `/inventory/audit` | 재고실사 목록 | FR-10 |
| GET/POST | `/inventory/audit/create` | 실사 회차 생성 | FR-02 |
| GET | `/inventory/audit/<id>` | 실사 상세 (품목 입력) | FR-03 |
| POST | `/inventory/audit/<id>/save` | 실사 수량 저장 | FR-03 |
| POST | `/inventory/audit/<id>/confirm` | 실사 조정 확정 | FR-04 |
| GET | `/inventory/turnover` | 재고회전율 분석 | FR-07 |
| GET | `/inventory/movements` | 재고 변동 이력 | FR-08 |
| GET | `/inventory/export` | 재고현황 엑셀 다운로드 | FR-11 |
| POST | `/inventory/item/<id>/adjust` | 수동 재고 조정 | FR-08 |
| POST | `/inventory/item/<id>/safety-stock` | 안전재고 설정 | FR-09 |
| GET | `/api/inventory/summary` | 대시보드 통계 JSON | FR-01 |
| GET | `/api/inventory/low-stock` | 저재고 품목 JSON | FR-09 |

### 4.2 핵심 비즈니스 로직

#### 재고 변동 기록 헬퍼 (모든 재고 변동에 사용)

```python
def record_stock_movement(db, item_id, movement_type, quantity,
                          reference_type=None, reference_id=None,
                          unit_price=None, note=None, created_by='시스템'):
    """재고 변동을 기록하고 Item.stock_qty를 갱신한다."""
    item = db.query(Item).get(item_id)
    if not item:
        return None

    before_qty = item.stock_qty or 0
    item.stock_qty = before_qty + quantity
    after_qty = item.stock_qty

    movement = StockMovement(
        item_id=item_id,
        movement_type=movement_type,
        quantity=quantity,
        before_qty=before_qty,
        after_qty=after_qty,
        unit_price=unit_price,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        created_by=created_by,
    )
    db.add(movement)
    return movement
```

#### 재고실사 조정 확정

```python
def confirm_audit(db, audit_id, confirmed_by):
    """실사 차이 항목을 일괄 조정하고 stock_qty를 갱신한다."""
    audit = db.query(StockAudit).get(audit_id)
    items = db.query(StockAuditItem).filter(
        StockAuditItem.audit_id == audit_id,
        StockAuditItem.actual_qty.isnot(None),
        StockAuditItem.is_adjusted == False,
        StockAuditItem.diff_qty != 0,
    ).all()

    for ai in items:
        record_stock_movement(
            db, ai.item_id,
            movement_type='AUDIT_ADJUST',
            quantity=ai.diff_qty,
            reference_type='stock_audit',
            reference_id=audit_id,
            note=f'실사조정 ({audit.audit_no}): {ai.diff_reason or ""}',
            created_by=confirmed_by,
        )
        ai.is_adjusted = True
        ai.adjusted_at = datetime.datetime.now()

    audit.status = '완료'
    audit.diff_items = len(items)
```

#### 재고회전율 산출

```python
def calc_turnover_rate(db, start_date, end_date, category=None):
    """
    재고회전율 = 기간 내 출고수량 / 평균재고
    출고 proxy: StockMovement에서 OUT_ 타입 합산 (절대값)
    평균재고: (기간시작 재고 + 기간종료 재고) / 2
    """
    query = db.query(
        StockMovement.item_id,
        func.sum(func.abs(StockMovement.quantity)).label('total_out')
    ).filter(
        StockMovement.movement_type.in_(['OUT_RESERVE', 'OUT_ADJUST']),
        StockMovement.created_at >= start_date,
        StockMovement.created_at <= end_date,
    ).group_by(StockMovement.item_id)

    # 각 품목별 회전율 계산
    results = []
    for item_id, total_out in query.all():
        item = db.query(Item).get(item_id)
        avg_stock = (item.stock_qty or 0)  # 단순화: 현재 재고를 평균으로 사용
        turnover = total_out / avg_stock if avg_stock > 0 else 0
        results.append({
            'item': item,
            'total_out': total_out,
            'avg_stock': avg_stock,
            'turnover': round(turnover, 2),
        })
    return results
```

---

## 5. UI/UX 설계

### 5.1 페이지 구성

```
재고관리 (메뉴)
├── 재고 현황         -- /inventory (대시보드)
├── 가용재고 조회     -- /inventory/items
├── 재고실사          -- /inventory/audit
├── 재고회전율        -- /inventory/turnover
└── 변동 이력         -- /inventory/movements
```

### 5.2 재고 현황 대시보드 레이아웃

```
┌─────────────────────────────────────────────────────────────┐
│ [재고 현황 대시보드]                                          │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ 총 품목수 │ 총재고금액 │ 가용재고액 │ 예약재고액 │ 저재고 경고    │
│   342    │ 48,500만  │ 35,200만  │ 13,300만  │   12건         │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                                                             │
│ [카테고리별 재고금액 요약 테이블]                               │
│ 카테고리 │ 품목수 │ 총재고 │ 예약수량 │ 가용재고 │ 재고금액       │
│ ─────────┼────────┼───────┼────────┼────────┼──────────      │
│ 드라이버  │   45   │  320  │   120  │   200  │ 15,680,000     │
│ 하우징    │   38   │  180  │    60  │   120  │  8,400,000     │
│ LED모듈   │   52   │  450  │   200  │   250  │ 12,250,000     │
│ ...                                                         │
│                                                             │
│ [저재고 경고 품목 목록 (상위 10건)]                             │
│ 품명 │ 현재고 │ 안전재고 │ 부족분 │ 최근입고일                     │
│                                                             │
│ [최근 재고 변동 (최근 10건)]                                   │
│ 일시 │ 품목 │ 유형 │ 수량 │ 변동후재고 │ 담당자                   │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 재고실사 워크플로우

```
[실사 목록] ─── [신규 실사 생성] ─── [품목 수량 입력] ─── [차이 확인] ─── [조정 확정]
                    │                      │                   │               │
                 실사일 입력           품목별 actual_qty     diff_qty !=0    stock_qty 갱신
                 실사자 지정           입력 (인라인)        품목 하이라이트   StockMovement 기록
                                                           사유 입력
```

실사 상세 화면:
```
┌─────────────────────────────────────────────────────────────┐
│ 재고실사: SA2026-001 (2026-03-19)   상태: 진행중              │
│ 실사자: 이지훈   메모: 3월 정기실사                            │
├─────────────────────────────────────────────────────────────┤
│ [검색] [카테고리 필터] [차이있는 항목만 v]                       │
├─────┬────────────┬──────┬──────────┬──────────┬─────┬──────┤
│ No  │ 품명        │ 품번  │ 시스템수량 │ 실사수량   │ 차이 │ 사유  │
├─────┼────────────┼──────┼──────────┼──────────┼─────┼──────┤
│  1  │ HLG-320H   │ D001 │    50    │ [  48  ] │ -2  │ [  ] │
│  2  │ LED모듈 50W │ L003 │    120   │ [ 120  ] │  0  │      │
│  3  │ 하우징 A타입 │ H012 │    30    │ [  35  ] │ +5  │ [  ] │
└─────┴────────────┴──────┴──────────┴──────────┴─────┴──────┘
│ [임시저장]  [차이 항목만 표시]  [조정 확정] (diff!=0 항목 일괄) │
└─────────────────────────────────────────────────────────────┘
```

### 5.4 가용재고 조회 화면

```
┌─────────────────────────────────────────────────────────────┐
│ [가용재고 조회]   검색: [______] 카테고리: [전체 v]             │
├─────┬────────────┬──────┬──────┬──────┬──────┬──────┬──────┤
│ No  │ 품명        │ 품번  │ 총재고│ 예약  │ 가용  │ 단가  │ 금액  │
├─────┼────────────┼──────┼──────┼──────┼──────┼──────┼──────┤
│  1  │ HLG-320H   │ D001 │  50  │  20  │  30  │97,600│4,880K│
│     │            │      │      │      │      │      │      │
│ [!] │ LED모듈 50W │ L003 │  10  │   8  │   2  │25,000│ 250K │ ← 저재고 경고
└─────┴────────────┴──────┴──────┴──────┴──────┴──────┴──────┘
 [!] = 안전재고 미만 (빨간 배경)
```

### 5.5 재고회전율 화면

```
┌─────────────────────────────────────────────────────────────┐
│ [재고회전율 분석]  기간: [2026-01-01] ~ [2026-03-19]          │
├─────┬────────────┬──────┬──────────┬──────────┬────────────┤
│ No  │ 품명        │ 분류  │ 출고수량  │ 평균재고  │ 회전율      │
├─────┼────────────┼──────┼──────────┼──────────┼────────────┤
│  1  │ HLG-320H   │드라이버│   150   │    75    │   2.0x     │
│  2  │ LED모듈 50W │LED모듈│   300   │   120    │   2.5x     │
│  3  │ 하우징 A타입 │하우징 │     5   │    30    │   0.17x    │ ← 과다재고
└─────┴────────────┴──────┴──────────┴──────────┴────────────┘
 회전율 < 0.5: 과다재고 경고 (주황)
 회전율 > 3.0: 빈번 소진 (파랑)
```

---

## 6. 기존 모듈 연동 (변경 지점)

### 6.1 입고 시 StockMovement 기록 추가

**파일**: `routes/receiving.py` > `_update_po_status_on_receiving()`

```python
# 기존: linked_item.stock_qty = (linked_item.stock_qty or 0) + total_received
# 변경: record_stock_movement() 사용
from modules.services.inventory_utils import record_stock_movement

record_stock_movement(
    db, linked_item.id,
    movement_type='IN_RECEIVING',
    quantity=total_received,
    reference_type='receiving',
    reference_id=rcv.id,
    unit_price=po_item.unit_price,
    note=f'입고 {rcv.rcv_no}',
)
# last_unit_price 갱신
if po_item.unit_price and po_item.unit_price > 0:
    linked_item.last_unit_price = po_item.unit_price
```

### 6.2 예약/취소 시 StockMovement 기록 추가

**파일**: `modules/services/material_actions.py`

- `handle_reserve_stock()`: `OUT_RESERVE` 기록 추가
- `handle_cancel_reservation()`: `IN_CANCEL_RESERVE` 기록 추가

### 6.3 품목 수동 재고 수정 시

**파일**: `routes/item.py` > `item_edit()`

기존 stock_qty 직접 수정 로직에 `IN_ADJUST` 또는 `OUT_ADJUST` 기록 추가.

---

## 7. 템플릿 목록

| 파일명 | 설명 | 라우트 |
|--------|------|--------|
| `inventory_dashboard.html` | 재고 현황 대시보드 | `/inventory` |
| `inventory_items.html` | 가용재고 목록 | `/inventory/items` |
| `inventory_audit_list.html` | 실사 목록 | `/inventory/audit` |
| `inventory_audit_create.html` | 실사 생성 | `/inventory/audit/create` |
| `inventory_audit_detail.html` | 실사 상세 (수량입력) | `/inventory/audit/<id>` |
| `inventory_turnover.html` | 재고회전율 | `/inventory/turnover` |
| `inventory_movements.html` | 변동 이력 | `/inventory/movements` |

---

## 8. 구현 순서

### Phase 1: 데이터 모델 + 기본 인프라 (Day 1)

1. [ ] entities.py에 StockAudit, StockAuditItem, StockMovement 모델 추가
2. [ ] `__init__.py` export 추가
3. [ ] db.py에 ALTER TABLE (Item.safety_stock, Item.last_unit_price) 추가
4. [ ] `modules/services/inventory_utils.py` 생성 (record_stock_movement 등)

### Phase 2: 재고 현황 + 가용재고 (Day 1-2)

5. [ ] `routes/inventory.py` Blueprint 생성
6. [ ] `inventory_dashboard.html` -- 대시보드 (통계카드 + 카테고리별 요약 + 저재고 경고)
7. [ ] `inventory_items.html` -- 가용재고 목록 (필터/검색/페이징)
8. [ ] app.py에 inventory_bp 등록

### Phase 3: 재고실사 (Day 2-3)

9. [ ] 실사 목록/생성/상세 라우트 구현
10. [ ] `inventory_audit_list.html` -- 실사 이력 목록
11. [ ] `inventory_audit_create.html` -- 실사 생성 폼
12. [ ] `inventory_audit_detail.html` -- 품목별 수량 입력 + 차이 표시
13. [ ] 조정 확정 로직 (confirm_audit)

### Phase 4: 변동이력 + 기존 연동 (Day 3)

14. [ ] `inventory_movements.html` -- 변동 이력 목록
15. [ ] receiving.py 입고 시 StockMovement 기록 연동
16. [ ] material_actions.py 예약/취소 시 StockMovement 기록 연동
17. [ ] item.py 수동 조정 시 StockMovement 기록 연동

### Phase 5: 회전율 + 엑셀 + 마무리 (Day 3-4)

18. [ ] `inventory_turnover.html` -- 재고회전율 분석
19. [ ] 엑셀 다운로드 기능
20. [ ] 안전재고 설정 UI
21. [ ] 메뉴 등록 (config.py MENU_REGISTRY)

---

## 9. 보안 및 권한

- 재고관리 메뉴: `inventory` 키로 MENU_REGISTRY 등록
- 재고실사 조정 확정: 관리부 + 최고관리자만 가능 (user_group 체크)
- 수동 재고 조정: 반드시 사유 입력 필수
- 모든 조정 액션에 `append_history_log()` 호출

---

## 10. UI 규칙 (기존 컨벤션 준수)

| 규칙 | 적용 |
|------|------|
| 테이블 줄바꿈 금지 | 모든 td에 `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` |
| 뱃지/버튼 nowrap | `white-space: nowrap` 필수 |
| 폰트 크기 축소 | 테이블 본문 `font-size: 0.82rem` |
| 컬럼 비율 | 품명 30%, 나머지 균등 배분, max-width 설정 |
| 금액 표시 | 3자리 콤마 구분, 우측 정렬 |
| 차이 표시 | 양수: 파란색, 음수: 빨간색, 0: 회색 |

---

## 버전 이력

| 버전 | 날짜 | 변경사항 | 작성자 |
|------|------|----------|--------|
| 0.1 | 2026-03-19 | 초안 작성 | CTO Lead |
