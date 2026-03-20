"""FR-07: 조달/발주 도메인 Tools (4개)"""
import json
from mcp.server import Server
from mcp.types import Tool, TextContent

from ..db import get_session


def _safe(val, default=""):
    return val if val is not None else default


def _safe_date(val):
    return val.isoformat() if val else ""


def register(server: Server):

    @server.list_tools()
    async def list_procurement_tools():
        return [
            Tool(
                name="get_purchase_orders",
                description="발주서 목록 조회. 상태, 거래처, 현장으로 필터링합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "발주 상태 (작성중/발송완료/입고대기/입고완료/취소)"},
                        "vendor_id": {"type": "integer", "description": "거래처 ID"},
                        "project_id": {"type": "integer", "description": "현장 ID"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
            Tool(
                name="get_po_detail",
                description="발주서 상세 조회. 발주 품목 목록과 금액을 포함합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "po_id": {"type": "integer", "description": "발주서 ID"},
                        "po_no": {"type": "string", "description": "발주번호 (po_id 또는 po_no 중 하나 필수)"},
                    },
                },
            ),
            Tool(
                name="get_receiving_history",
                description="입고 이력 조회. 입고일, 거래처, 품목별 입고 내역을 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "vendor_id": {"type": "integer"},
                        "date_from": {"type": "string", "description": "시작일 (YYYY-MM-DD)"},
                        "date_to": {"type": "string", "description": "종료일 (YYYY-MM-DD)"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
            Tool(
                name="get_vendor_list",
                description="거래처 목록 조회. 거래처명, 담당자, 연락처를 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "search": {"type": "string", "description": "거래처명 검색"},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_procurement_tool(name: str, arguments: dict):
        if name == "get_purchase_orders":
            return await _get_purchase_orders(**arguments)
        elif name == "get_po_detail":
            return await _get_po_detail(**arguments)
        elif name == "get_receiving_history":
            return await _get_receiving_history(**arguments)
        elif name == "get_vendor_list":
            return await _get_vendor_list(**arguments)


async def _get_purchase_orders(status=None, vendor_id=None, project_id=None, limit=50):
    from modules.models.entities import PurchaseOrder

    session = get_session()
    try:
        q = session.query(PurchaseOrder)
        if status:
            q = q.filter(PurchaseOrder.status == status)
        if vendor_id:
            q = q.filter(PurchaseOrder.vendor_id == vendor_id)
        if project_id:
            q = q.filter(PurchaseOrder.project_id == project_id)
        orders = q.order_by(PurchaseOrder.po_date.desc()).limit(limit).all()

        result = [{
            "id": po.id,
            "po_no": _safe(po.po_no),
            "po_date": _safe_date(po.po_date),
            "status": _safe(po.status),
            "vendor_name": _safe(po.vendor.vendor_name) if po.vendor else "",
            "project_name": _safe(po.project.temp_name) if po.project else "",
            "total_amount": int(po.total_amount or 0),
            "tax_amount": int(po.tax_amount or 0),
            "item_count": len(po.items),
            "note": _safe(po.note),
        } for po in orders]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_po_detail(po_id=None, po_no=None):
    from modules.models.entities import PurchaseOrder

    session = get_session()
    try:
        if po_id:
            po = session.query(PurchaseOrder).get(po_id)
        elif po_no:
            po = session.query(PurchaseOrder).filter(PurchaseOrder.po_no == po_no).first()
        else:
            return [TextContent(type="text", text="po_id 또는 po_no가 필요합니다.")]

        if not po:
            return [TextContent(type="text", text="발주서를 찾을 수 없습니다.")]

        items = [{
            "id": i.id,
            "item_name": _safe(i.item_name),
            "item_spec": _safe(i.item_spec),
            "quantity": float(i.quantity or 0),
            "unit": _safe(i.unit),
            "unit_price": int(i.unit_price or 0),
            "amount": int(i.amount or 0),
            "delivery_date": _safe_date(i.delivery_date),
            "note": _safe(i.note),
        } for i in po.items]

        result = {
            "id": po.id,
            "po_no": _safe(po.po_no),
            "po_date": _safe_date(po.po_date),
            "status": _safe(po.status),
            "vendor_name": _safe(po.vendor.vendor_name) if po.vendor else "",
            "project_name": _safe(po.project.temp_name) if po.project else "",
            "total_amount": int(po.total_amount or 0),
            "tax_amount": int(po.tax_amount or 0),
            "email_to": _safe(po.email_to),
            "note": _safe(po.note),
            "items": items,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_receiving_history(vendor_id=None, date_from=None, date_to=None, limit=50):
    from modules.models.entities import Receiving

    session = get_session()
    try:
        q = session.query(Receiving)
        if vendor_id:
            q = q.filter(Receiving.vendor_id == vendor_id)
        if date_from:
            q = q.filter(Receiving.rcv_date >= date_from)
        if date_to:
            q = q.filter(Receiving.rcv_date <= date_to)
        receivings = q.order_by(Receiving.rcv_date.desc()).limit(limit).all()

        result = []
        for rcv in receivings:
            items = [{
                "item_name": _safe(i.item_name),
                "item_spec": _safe(i.item_spec),
                "received_qty": float(i.received_qty or 0),
                "unit": _safe(i.unit),
                "unit_price": int(i.unit_price or 0),
                "amount": int(i.amount or 0),
            } for i in rcv.items]
            result.append({
                "id": rcv.id,
                "rcv_no": _safe(rcv.rcv_no),
                "rcv_date": _safe_date(rcv.rcv_date),
                "status": _safe(rcv.status),
                "vendor_name": _safe(rcv.vendor.vendor_name) if rcv.vendor else "",
                "total_amount": int(sum(i["amount"] for i in items)),
                "items": items,
            })
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_vendor_list(search=None):
    from modules.models.entities import Vendor

    session = get_session()
    try:
        q = session.query(Vendor)
        if search:
            q = q.filter(Vendor.vendor_name.ilike(f"%{search}%"))
        vendors = q.order_by(Vendor.vendor_name).all()

        result = []
        for v in vendors:
            row = {"id": v.id}
            for col in ["vendor_name", "vendor_type", "contact_name", "contact_phone",
                        "contact_email", "business_no", "address", "note"]:
                if hasattr(v, col):
                    row[col] = _safe(getattr(v, col))
            result.append(row)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()
