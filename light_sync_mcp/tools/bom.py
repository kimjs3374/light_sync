"""FR-03: BOM/품목 도메인 Tools (6개)"""
import json
from mcp.server import Server
from mcp.types import Tool, TextContent

from ..db import get_session


def _safe(val, default=""):
    return val if val is not None else default


def _safe_num(val, default=0.0):
    return float(val) if val is not None else default


def _match_option_filter(bom_item_filter_json: str, option_filter: dict) -> bool:
    """BomItem.option_filter JSON과 요청 옵션 조건 매칭.
    option_filter가 None이면 공통 부품(항상 포함).
    option_filter가 있으면 요청 옵션과 교집합 확인.
    """
    if not bom_item_filter_json:
        return True  # 공통 부품
    if not option_filter:
        return True  # 옵션 필터 없으면 전부 포함
    try:
        item_filter = json.loads(bom_item_filter_json)
        for key, val in item_filter.items():
            if option_filter.get(key) != val:
                return False
        return True
    except Exception:
        return True


def register(server: Server):

    @server.list_tools()
    async def list_bom_tools():
        return [
            Tool(
                name="get_bom_list",
                description="BOM 목록 조회. 완제품별 BOM 헤더 목록과 부품 수를 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "제품군 필터 (예: 실내등, 투광등)"},
                        "search": {"type": "string", "description": "제품명 검색어"},
                        "is_active": {"type": "boolean", "description": "활성 BOM만 조회 (기본 true)", "default": True},
                    },
                },
            ),
            Tool(
                name="get_bom_detail",
                description="BOM 상세 조회. 소요 부품 목록, 원가 합계, 옵션 필터링을 지원합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bom_id": {"type": "integer", "description": "BOM ID"},
                        "product_code": {"type": "string", "description": "제품코드 (bom_id 또는 product_code 중 하나 필수)"},
                        "option_filter": {"type": "object", "description": "옵션 필터 (예: {\"lens_angle\": \"20도\"})"},
                    },
                },
            ),
            Tool(
                name="calculate_bom_cost",
                description="BOM 원가 계산. 생산 수량 × 단가 합산으로 총 원가를 계산합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bom_id": {"type": "integer", "description": "BOM ID"},
                        "quantity": {"type": "integer", "description": "생산 수량 (기본 1)", "default": 1},
                        "option_filter": {"type": "object", "description": "옵션 필터"},
                    },
                    "required": ["bom_id"],
                },
            ),
            Tool(
                name="get_items",
                description="품목 목록 조회. 카테고리, 검색, 재고 유무로 필터링합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "품목 분류 필터"},
                        "search": {"type": "string", "description": "품목명/규격 검색어"},
                        "has_stock": {"type": "boolean", "description": "재고 있는 품목만"},
                        "limit": {"type": "integer", "description": "최대 반환 수 (기본 100)", "default": 100},
                    },
                },
            ),
            Tool(
                name="search_items",
                description="품목 통합 검색. 품목명, 규격, 품번(iCUBE코드) 통합 검색합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색어"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_bom_stock_status",
                description="BOM 기준 생산 가능 여부 확인. 소요 부품의 재고 충족 여부를 품목별로 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bom_id": {"type": "integer", "description": "BOM ID"},
                        "quantity": {"type": "integer", "description": "생산 수량 (기본 1)", "default": 1},
                    },
                    "required": ["bom_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_bom_tool(name: str, arguments: dict):
        if name == "get_bom_list":
            return await _get_bom_list(**arguments)
        elif name == "get_bom_detail":
            return await _get_bom_detail(**arguments)
        elif name == "calculate_bom_cost":
            return await _calculate_bom_cost(**arguments)
        elif name == "get_items":
            return await _get_items(**arguments)
        elif name == "search_items":
            return await _search_items(**arguments)
        elif name == "get_bom_stock_status":
            return await _get_bom_stock_status(**arguments)


async def _get_bom_list(category=None, search=None, is_active=True):
    from modules.models.entities import BomHeader
    from sqlalchemy import func

    session = get_session()
    try:
        q = session.query(BomHeader)
        if is_active:
            q = q.filter(BomHeader.is_active == True)
        if category:
            q = q.filter(BomHeader.product_category.ilike(f"%{category}%"))
        if search:
            q = q.filter(BomHeader.product_name.ilike(f"%{search}%"))
        boms = q.order_by(BomHeader.product_name).all()

        result = []
        for bom in boms:
            result.append({
                "id": bom.id,
                "product_code": _safe(bom.product_code),
                "product_name": _safe(bom.product_name),
                "product_category": _safe(bom.product_category),
                "version": _safe(bom.version),
                "certification_no": _safe(bom.certification_no),
                "item_count": len(bom.bom_items),
                "has_option_schema": bool(bom.option_schema),
                "is_active": bom.is_active,
            })
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_bom_detail(bom_id=None, product_code=None, option_filter=None):
    from modules.models.entities import BomHeader

    session = get_session()
    try:
        if bom_id:
            bom = session.query(BomHeader).get(bom_id)
        elif product_code:
            bom = session.query(BomHeader).filter(BomHeader.product_code == product_code).first()
        else:
            return [TextContent(type="text", text="bom_id 또는 product_code가 필요합니다.")]

        if not bom:
            return [TextContent(type="text", text="BOM을 찾을 수 없습니다.")]

        items = []
        total_cost = 0
        for bi in bom.bom_items:
            if not _match_option_filter(bi.option_filter, option_filter):
                continue
            amount = _safe_num(bi.unit_price) * _safe_num(bi.quantity)
            total_cost += amount
            items.append({
                "id": bi.id,
                "item_code": _safe(bi.item_code),
                "item_name": _safe(bi.item_name),
                "item_spec": _safe(bi.item_spec),
                "quantity": _safe_num(bi.quantity),
                "unit": _safe(bi.unit),
                "unit_price": int(_safe_num(bi.unit_price)),
                "amount": int(amount),
                "supplier": _safe(bi.supplier),
                "option_filter": json.loads(bi.option_filter) if bi.option_filter else None,
                "note": _safe(bi.note),
            })

        option_schema = None
        if bom.option_schema:
            try:
                option_schema = json.loads(bom.option_schema)
            except Exception:
                option_schema = bom.option_schema

        result = {
            "header": {
                "id": bom.id,
                "product_code": _safe(bom.product_code),
                "product_name": _safe(bom.product_name),
                "product_category": _safe(bom.product_category),
                "version": _safe(bom.version),
                "certification_no": _safe(bom.certification_no),
                "option_schema": option_schema,
            },
            "items": items,
            "item_count": len(items),
            "total_cost": int(total_cost),
            "applied_option_filter": option_filter,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _calculate_bom_cost(bom_id: int, quantity: int = 1, option_filter=None):
    from modules.models.entities import BomHeader

    session = get_session()
    try:
        bom = session.query(BomHeader).get(bom_id)
        if not bom:
            return [TextContent(type="text", text="BOM을 찾을 수 없습니다.")]

        items = []
        unit_cost = 0
        for bi in bom.bom_items:
            if not _match_option_filter(bi.option_filter, option_filter):
                continue
            qty_per_unit = _safe_num(bi.quantity)
            unit_price = _safe_num(bi.unit_price)
            total_qty = qty_per_unit * quantity
            total_price = unit_price * total_qty
            unit_cost += unit_price * qty_per_unit
            items.append({
                "item_name": _safe(bi.item_name),
                "item_spec": _safe(bi.item_spec),
                "qty_per_unit": qty_per_unit,
                "total_qty": total_qty,
                "unit_price": int(unit_price),
                "total_price": int(total_price),
            })

        result = {
            "bom_id": bom_id,
            "product_name": _safe(bom.product_name),
            "quantity": quantity,
            "unit_cost": int(unit_cost),
            "total_cost": int(unit_cost * quantity),
            "items": items,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_items(category=None, search=None, has_stock=None, limit=100):
    from modules.models.entities import Item

    session = get_session()
    try:
        q = session.query(Item).filter(Item.is_active == True)
        if category:
            q = q.filter(Item.category.ilike(f"%{category}%"))
        if search:
            q = q.filter(
                (Item.item_name.ilike(f"%{search}%")) | (Item.item_spec.ilike(f"%{search}%"))
            )
        if has_stock is True:
            q = q.filter(Item.stock_qty > 0)
        elif has_stock is False:
            q = q.filter(Item.stock_qty <= 0)
        items = q.order_by(Item.item_name).limit(limit).all()

        result = [{
            "id": i.id,
            "icube_item_cd": _safe(i.icube_item_cd),
            "item_name": _safe(i.item_name),
            "item_spec": _safe(i.item_spec),
            "category": _safe(i.category),
            "unit": _safe(i.unit),
            "stock_qty": _safe_num(i.stock_qty),
            "last_unit_price": int(_safe_num(i.last_unit_price)),
            "manufacturer": _safe(i.manufacturer),
        } for i in items]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _search_items(query: str):
    from modules.models.entities import Item

    session = get_session()
    try:
        items = session.query(Item).filter(
            Item.is_active == True,
            (Item.item_name.ilike(f"%{query}%"))
            | (Item.item_spec.ilike(f"%{query}%"))
            | (Item.icube_item_cd.ilike(f"%{query}%")),
        ).limit(50).all()

        result = [{
            "id": i.id,
            "icube_item_cd": _safe(i.icube_item_cd),
            "item_name": _safe(i.item_name),
            "item_spec": _safe(i.item_spec),
            "category": _safe(i.category),
            "unit": _safe(i.unit),
            "stock_qty": _safe_num(i.stock_qty),
            "last_unit_price": int(_safe_num(i.last_unit_price)),
        } for i in items]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_bom_stock_status(bom_id: int, quantity: int = 1):
    from modules.models.entities import BomHeader, Item

    session = get_session()
    try:
        bom = session.query(BomHeader).get(bom_id)
        if not bom:
            return [TextContent(type="text", text="BOM을 찾을 수 없습니다.")]

        shortage_items = []
        can_produce = True

        for bi in bom.bom_items:
            required = _safe_num(bi.quantity) * quantity
            available = 0
            item_name = _safe(bi.item_name)

            if bi.item_id:
                item = session.query(Item).get(bi.item_id)
                if item:
                    available = _safe_num(item.stock_qty) - _safe_num(item.reserved_qty)
                    item_name = _safe(item.item_name)

            if available < required:
                can_produce = False
                shortage_items.append({
                    "item_name": item_name,
                    "item_spec": _safe(bi.item_spec),
                    "required": required,
                    "available": round(available, 2),
                    "shortage": round(required - available, 2),
                })

        result = {
            "bom_id": bom_id,
            "product_name": _safe(bom.product_name),
            "quantity": quantity,
            "can_produce": can_produce,
            "shortage_count": len(shortage_items),
            "shortage_items": shortage_items,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()
