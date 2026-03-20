# Design: mcp-server

## 1. 아키텍처 개요

```
Claude Desktop
      │  stdio (JSON-RPC 2.0)
      ▼
light_sync_mcp/          ← 이번 구현 대상
  server.py              ← MCP 서버 (tool/resource 등록)
  db.py                  ← DB 세션 (entities.py 재사용)
  tools/
    inventory.py         ← FR-04: 재고 5개 Tool
    bom.py               ← FR-03: BOM 6개 Tool
    project.py           ← FR-02: 현장 5개 Tool
    production.py        ← FR-05: 생산 4개 Tool
    financial.py         ← FR-06: 재무 4개 Tool
    procurement.py       ← FR-07: 조달 4개 Tool
  resources/
    magnatech.py         ← FR-08: 4개 Resource
      │
      ▼
modules/models/entities.py   ← 기존 SQLAlchemy 모델 (공유)
      │
      ▼
PostgreSQL (light_sync DB)
```

---

## 2. 파일 구조 및 구현 명세

### 2.1 진입점 및 기반 코드

#### `light_sync_mcp/__main__.py`
```python
import asyncio
from .server import create_server

if __name__ == "__main__":
    server = create_server()
    asyncio.run(server.run_stdio())
```

#### `light_sync_mcp/db.py`
```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def get_session():
    return SessionLocal()
```

#### `light_sync_mcp/server.py`
```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from .tools import inventory, bom, project, production, financial, procurement
from .resources import magnatech

def create_server():
    server = Server("light-sync-erp")

    # Phase 1 (필수)
    inventory.register(server)
    bom.register(server)

    # Phase 2
    project.register(server)
    production.register(server)

    # Phase 3
    financial.register(server)
    procurement.register(server)
    magnatech.register(server)

    return server
```

---

## 3. Tool 명세 (FR-04: 재고 도메인 — Phase 1 핵심)

### `get_inventory`
```python
@server.tool()
def get_inventory(
    category: str = None,     # 품목 분류 필터 (드라이버, LED모듈 등)
    low_stock_only: bool = False,  # 안전재고 미달만
    search: str = None        # 품목명 검색
) -> list[dict]:
    """
    현재 재고 현황 조회.
    Items 테이블: stock_qty, reserved_qty, safety_stock
    반환: [{item_name, item_spec, category, stock_qty, reserved_qty,
            available_qty(stock-reserved), safety_stock, unit, last_unit_price}]
    """
```
- **쿼리 대상**: `items` 테이블
- **필터**: `is_active=True`, category LIKE, item_name LIKE
- `available_qty = stock_qty - reserved_qty`

### `get_low_stock`
```python
@server.tool()
def get_low_stock() -> list[dict]:
    """
    안전재고 미달 품목 목록.
    조건: stock_qty < safety_stock AND safety_stock > 0
    반환: [{item_name, stock_qty, safety_stock, shortage(차이), category}]
    정렬: shortage DESC (부족량 큰 순)
    """
```

### `get_inventory_turnover`
```python
@server.tool()
def get_inventory_turnover(
    year: int,
    month: int = None   # None이면 연간 전체
) -> list[dict]:
    """
    재고 회전율 분석.
    stock_movements 테이블의 출고(OUT) 합산 / 평균재고
    반환: [{item_name, total_out, avg_stock, turnover_rate}]
    """
```
- **쿼리 대상**: `stock_movements` 테이블 (movement_type='OUT')

### `get_stock_movements`
```python
@server.tool()
def get_stock_movements(
    item_id: int = None,
    movement_type: str = None,  # IN / OUT / ADJUST
    date_from: str = None,      # YYYY-MM-DD
    date_to: str = None,
    limit: int = 50
) -> list[dict]:
    """
    재고 변동 이력 조회.
    반환: [{date, item_name, movement_type, quantity, note, reference_no}]
    """
```
- **쿼리 대상**: `stock_movements` 테이블

### `get_inventory_valuation`
```python
@server.tool()
def get_inventory_valuation(category: str = None) -> dict:
    """
    재고 평가액 (stock_qty × last_unit_price 합산).
    반환: {total_valuation, by_category: [{category, count, valuation}]}
    """
```

---

## 4. Tool 명세 (FR-03: BOM 도메인 — Phase 1 핵심)

### `get_bom_list`
```python
@server.tool()
def get_bom_list(
    category: str = None,     # product_category 필터
    search: str = None,       # product_name 검색
    is_active: bool = True
) -> list[dict]:
    """
    BOM 목록 조회.
    반환: [{id, product_code, product_name, product_category,
            version, item_count, option_schema}]
    """
```
- **쿼리 대상**: `bom_headers` LEFT JOIN COUNT(`bom_items`)

### `get_bom_detail`
```python
@server.tool()
def get_bom_detail(
    bom_id: int = None,
    product_code: str = None,   # 둘 중 하나 필수
    option_filter: dict = None  # {"lens_angle": "20도"} 옵션 필터링
) -> dict:
    """
    BOM 상세 (소요 부품 목록 + 원가).
    option_filter가 있으면 해당 옵션 조건 부품만 반환.
    반환: {header: {...}, items: [{item_name, quantity, unit_price, amount, option_filter}], total_cost}
    """
```
- **option_filter 로직**: `BomItem.option_filter` JSON 파싱 → 조건 매칭 또는 null(공통)

### `calculate_bom_cost`
```python
@server.tool()
def calculate_bom_cost(
    bom_id: int,
    quantity: int = 1,         # 생산 수량
    option_filter: dict = None
) -> dict:
    """
    BOM 원가 계산 (quantity × 단가 합산).
    반환: {bom_name, quantity, unit_cost, total_cost,
            items: [{item_name, qty_per_unit, total_qty, unit_price, total_price}]}
    """
```

### `get_items`
```python
@server.tool()
def get_items(
    category: str = None,
    search: str = None,
    has_stock: bool = None     # 재고 있는 품목만
) -> list[dict]:
```

### `search_items`
```python
@server.tool()
def search_items(query: str) -> list[dict]:
    """item_name, item_spec, icube_item_cd ILIKE 검색"""
```

### `get_bom_stock_status`
```python
@server.tool()
def get_bom_stock_status(bom_id: int, quantity: int = 1) -> dict:
    """
    BOM 기준 생산 가능 여부 확인.
    각 BomItem의 소요량 × quantity vs Item.stock_qty 비교
    반환: {can_produce: bool, shortage_items: [{item_name, required, available, shortage}]}
    """
```

---

## 5. Tool 명세 (FR-02: 현장 도메인 — Phase 2)

### `get_projects`
```python
@server.tool()
def get_projects(
    status: str = None,          # 설계/영업, 계약, 생산, 납품완료 등
    is_contracted: bool = None,
    year: int = None,
    search: str = None
) -> list[dict]:
    """반환: [{project_no, temp_name, status, is_contracted, contract_date, is_urgent}]"""
```

### `get_project_detail`
```python
@server.tool()
def get_project_detail(project_id: int = None, project_no: str = None) -> dict:
    """
    현장 상세 (계약, 납품, 생산 포함).
    반환: {project, contracts: [...], deliveries: [...], production: [...]}
    """
```

### `get_project_timeline`
- Delivery + ProductionProcess JOIN으로 현장별 일정 타임라인

### `search_projects`
- `temp_name`, `short_name`, `site_address` ILIKE

### `get_delivery_summary`
```python
@server.tool()
def get_delivery_summary(
    year: int,
    month: int = None,
    project_id: int = None
) -> dict:
    """G2bProcurement + Contract 기반 납품집계"""
```

---

## 6. Tool 명세 (FR-05: 생산 — FR-06: 재무 — FR-07: 조달)

### 생산 (FR-05)
| Tool | 쿼리 대상 | 반환 핵심 |
|------|-----------|-----------|
| `get_production_status` | `production_processes` | 현장별 공정 진행률 |
| `get_production_by_site` | `production_processes` JOIN `projects` | 현장카드 목록 |
| `get_worker_assignments` | `production_processes` | 작업자별 배치 현황 |
| `get_fab_status` | `production_processes` WHERE stage='FAB' | FAB 공정 현황 |

### 재무 (FR-06)
| Tool | 쿼리 대상 | 반환 핵심 |
|------|-----------|-----------|
| `get_revenue_summary` | `tax_invoices` | 월별/현장별 매출 집계 |
| `get_tax_invoices` | `tax_invoices` | 목록 (G2B 매칭 상태) |
| `get_financial_overview` | `tax_invoices` + `payment_records` | 매출/수금/미수금 요약 |
| `get_unpaid_invoices` | `tax_invoices` WHERE payment_status!='입금완료' | 미수금 현황 |

### 조달 (FR-07)
| Tool | 쿼리 대상 | 반환 핵심 |
|------|-----------|-----------|
| `get_purchase_orders` | `purchase_orders` | 발주서 목록 |
| `get_po_detail` | `purchase_orders` JOIN `purchase_order_items` | 발주 상세 |
| `get_receiving_history` | `receivings` JOIN `receiving_items` | 입고 이력 |
| `get_vendor_list` | `vendors` | 거래처 목록 |

---

## 7. MCP Resources 명세 (FR-08)

```python
@server.resource("magnatech://process")
def get_process_doc() -> str:
    """MAGNATECH 생산 공정 설명 (docs/magnatech_memory.md 내용)"""

@server.resource("magnatech://products")
def get_products_doc() -> str:
    """제품 사양 및 스펙 (BomHeader 전체 요약)"""

@server.resource("magnatech://certifications")
def get_certifications() -> str:
    """BomHeader.certification_no 목록"""

@server.resource("lightsync://schema")
def get_db_schema() -> str:
    """주요 테이블 스키마 요약 (Claude가 쿼리 맥락 이해용)"""
```

---

## 8. 구현 순서 (Do Phase)

| 순서 | 작업 | 파일 | FR |
|------|------|------|----|
| 1 | 패키지 구조 생성 | `light_sync_mcp/__init__.py` 외 기반 파일 | FR-01 |
| 2 | DB 연결 | `db.py` | FR-01 |
| 3 | 서버 기반 | `server.py` | FR-01 |
| 4 | 재고 Tools 5개 | `tools/inventory.py` | FR-04 |
| 5 | BOM Tools 6개 | `tools/bom.py` | FR-03 |
| 6 | Claude Desktop 연결 테스트 | `claude_desktop_config.json` | FR-01 |
| 7 | 현장 Tools 5개 | `tools/project.py` | FR-02 |
| 8 | 생산 Tools 4개 | `tools/production.py` | FR-05 |
| 9 | 재무 Tools 4개 | `tools/financial.py` | FR-06 |
| 10 | 조달 Tools 4개 | `tools/procurement.py` | FR-07 |
| 11 | Resources 4개 | `resources/magnatech.py` | FR-08 |
| 12 | 일일보고 Tool | `tools/daily_report.py` | FR-09 |

---

## 9. requirements.txt

```
mcp>=1.0.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
python-dotenv>=1.0.0
```

---

## 10. 데이터 반환 규칙

- 모든 Tool은 `list[dict]` 또는 `dict` 반환 (MCP 직렬화)
- 날짜: `ISO 8601` 문자열 (`date.isoformat()`)
- Float 금액: 소수점 없이 정수 캐스팅 (`int(amount)`) — 원화 단위
- None 값: 빈 문자열 `""` 또는 `0`으로 치환 (Claude 파싱 편의)
- 최대 반환 row: 기본 100개, `limit` 파라미터로 조절 가능

---

## 11. Claude Desktop 설정 파일

```json
{
  "mcpServers": {
    "light-sync": {
      "command": "python",
      "args": ["-m", "light_sync_mcp"],
      "cwd": "D:/light_sync",
      "env": {
        "DATABASE_URL": "postgresql://user:password@localhost/light_sync"
      }
    }
  }
}
```

저장 경로: `%APPDATA%\Claude\claude_desktop_config.json`
