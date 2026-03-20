"""FR-04: 재고 도메인 Tools (5개)"""
from mcp.server import Server
from mcp.types import Tool, TextContent
import json

from ..db import get_session


def _safe(val, default=""):
    return val if val is not None else default


def _safe_num(val, default=0):
    return float(val) if val is not None else default


def register(server: Server):

    @server.list_tools()
    async def list_inventory_tools():
        return [
            Tool(
                name="get_inventory",
                description="현재 재고 현황 조회. 품목별 재고수량, 예약수량, 가용수량, 안전재고 등을 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "품목 분류 필터 (예: 드라이버, LED모듈, 하우징)"},
                        "low_stock_only": {"type": "boolean", "description": "안전재고 미달 품목만 조회"},
                        "search": {"type": "string", "description": "품목명 검색어"},
                        "limit": {"type": "integer", "description": "최대 반환 수 (기본 100)", "default": 100},
                    },
                },
            ),
            Tool(
                name="get_low_stock",
                description="안전재고 미달 품목 목록. 부족량 큰 순으로 정렬하여 반환합니다.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_inventory_turnover",
                description="재고 회전율 분석. 지정 기간의 출고 이력 기반으로 품목별 회전율을 계산합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "description": "조회 연도 (예: 2026)"},
                        "month": {"type": "integer", "description": "조회 월 (1-12, 생략 시 연간 전체)"},
                    },
                    "required": ["year"],
                },
            ),
            Tool(
                name="get_stock_movements",
                description="재고 변동 이력 조회. 입고/출고/조정 이력을 날짜순으로 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer", "description": "품목 ID 필터"},
                        "movement_type": {"type": "string", "description": "변동 유형 (IN/OUT/ADJUST)"},
                        "date_from": {"type": "string", "description": "시작일 (YYYY-MM-DD)"},
                        "date_to": {"type": "string", "description": "종료일 (YYYY-MM-DD)"},
                        "limit": {"type": "integer", "description": "최대 반환 수 (기본 50)", "default": 50},
                    },
                },
            ),
            Tool(
                name="get_inventory_valuation",
                description="재고 평가액 조회. 품목별 재고수량 × 최근단가 합산 결과를 분류별로 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "품목 분류 필터"},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_inventory_tool(name: str, arguments: dict):
        if name == "get_inventory":
            return await _get_inventory(**arguments)
        elif name == "get_low_stock":
            return await _get_low_stock()
        elif name == "get_inventory_turnover":
            return await _get_inventory_turnover(**arguments)
        elif name == "get_stock_movements":
            return await _get_stock_movements(**arguments)
        elif name == "get_inventory_valuation":
            return await _get_inventory_valuation(**arguments)


async def _get_inventory(category=None, low_stock_only=False, search=None, limit=100):
    from modules.models.entities import Item
    from sqlalchemy import and_

    session = get_session()
    try:
        q = session.query(Item).filter(Item.is_active == True)
        if category:
            q = q.filter(Item.category.ilike(f"%{category}%"))
        if search:
            q = q.filter(Item.item_name.ilike(f"%{search}%"))
        if low_stock_only:
            q = q.filter(Item.safety_stock > 0, Item.stock_qty < Item.safety_stock)
        items = q.order_by(Item.item_name).limit(limit).all()

        result = []
        for item in items:
            available = _safe_num(item.stock_qty) - _safe_num(item.reserved_qty)
            result.append({
                "id": item.id,
                "item_name": _safe(item.item_name),
                "item_spec": _safe(item.item_spec),
                "category": _safe(item.category),
                "unit": _safe(item.unit),
                "stock_qty": _safe_num(item.stock_qty),
                "reserved_qty": _safe_num(item.reserved_qty),
                "available_qty": round(available, 2),
                "safety_stock": _safe_num(item.safety_stock),
                "last_unit_price": int(_safe_num(item.last_unit_price)),
                "is_low_stock": _safe_num(item.stock_qty) < _safe_num(item.safety_stock) and _safe_num(item.safety_stock) > 0,
            })
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_low_stock():
    from modules.models.entities import Item

    session = get_session()
    try:
        items = (
            session.query(Item)
            .filter(Item.is_active == True, Item.safety_stock > 0, Item.stock_qty < Item.safety_stock)
            .all()
        )
        result = []
        for item in items:
            shortage = _safe_num(item.safety_stock) - _safe_num(item.stock_qty)
            result.append({
                "id": item.id,
                "item_name": _safe(item.item_name),
                "item_spec": _safe(item.item_spec),
                "category": _safe(item.category),
                "unit": _safe(item.unit),
                "stock_qty": _safe_num(item.stock_qty),
                "safety_stock": _safe_num(item.safety_stock),
                "shortage": round(shortage, 2),
            })
        result.sort(key=lambda x: x["shortage"], reverse=True)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_inventory_turnover(year: int, month: int = None):
    from modules.models.entities import Item, StockMovement
    from sqlalchemy import func, extract

    session = get_session()
    try:
        q = session.query(
            StockMovement.item_id,
            func.sum(StockMovement.quantity).label("total_out"),
        ).filter(
            StockMovement.movement_type == "OUT",
            extract("year", StockMovement.created_at) == year,
        )
        if month:
            q = q.filter(extract("month", StockMovement.created_at) == month)
        rows = q.group_by(StockMovement.item_id).all()

        result = []
        for row in rows:
            item = session.query(Item).get(row.item_id)
            if not item:
                continue
            avg_stock = _safe_num(item.stock_qty)
            turnover = round(row.total_out / avg_stock, 2) if avg_stock > 0 else 0
            result.append({
                "item_id": row.item_id,
                "item_name": _safe(item.item_name),
                "category": _safe(item.category),
                "total_out": round(float(row.total_out), 2),
                "current_stock": avg_stock,
                "turnover_rate": turnover,
            })
        result.sort(key=lambda x: x["turnover_rate"], reverse=True)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_stock_movements(item_id=None, movement_type=None, date_from=None, date_to=None, limit=50):
    from modules.models.entities import Item, StockMovement
    from sqlalchemy import and_
    import datetime

    session = get_session()
    try:
        q = session.query(StockMovement)
        if item_id:
            q = q.filter(StockMovement.item_id == item_id)
        if movement_type:
            q = q.filter(StockMovement.movement_type == movement_type)
        if date_from:
            q = q.filter(StockMovement.created_at >= date_from)
        if date_to:
            q = q.filter(StockMovement.created_at <= date_to + " 23:59:59")
        movements = q.order_by(StockMovement.created_at.desc()).limit(limit).all()

        result = []
        for m in movements:
            item = session.query(Item).get(m.item_id)
            result.append({
                "id": m.id,
                "date": m.created_at.isoformat() if m.created_at else "",
                "item_name": _safe(item.item_name) if item else "",
                "item_spec": _safe(item.item_spec) if item else "",
                "movement_type": _safe(m.movement_type),
                "quantity": _safe_num(m.quantity),
                "before_qty": _safe_num(m.before_qty),
                "after_qty": _safe_num(m.after_qty),
                "reference_type": _safe(m.reference_type),
                "reference_id": m.reference_id,
                "note": _safe(m.note),
                "created_by": _safe(m.created_by),
            })
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_inventory_valuation(category=None):
    from modules.models.entities import Item

    session = get_session()
    try:
        q = session.query(Item).filter(Item.is_active == True)
        if category:
            q = q.filter(Item.category.ilike(f"%{category}%"))
        items = q.all()

        total_valuation = 0
        by_category = {}
        for item in items:
            val = _safe_num(item.stock_qty) * _safe_num(item.last_unit_price)
            total_valuation += val
            cat = _safe(item.category, "미분류")
            if cat not in by_category:
                by_category[cat] = {"category": cat, "count": 0, "valuation": 0}
            by_category[cat]["count"] += 1
            by_category[cat]["valuation"] += val

        cat_list = sorted(by_category.values(), key=lambda x: x["valuation"], reverse=True)
        for c in cat_list:
            c["valuation"] = int(c["valuation"])

        result = {
            "total_valuation": int(total_valuation),
            "item_count": len(items),
            "by_category": cat_list,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()
