"""FR-06: 재무/세금계산서 도메인 Tools (4개)"""
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
    async def list_financial_tools():
        return [
            Tool(
                name="get_revenue_summary",
                description="매출 집계. 연월별 세금계산서 기준 매출 합산 결과를 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "description": "조회 연도"},
                        "month": {"type": "integer", "description": "조회 월 (생략 시 연간 월별 집계)"},
                    },
                    "required": ["year"],
                },
            ),
            Tool(
                name="get_tax_invoices",
                description="세금계산서 목록 조회. G2B 매칭 상태, 수금 상태로 필터링합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer"},
                        "month": {"type": "integer"},
                        "payment_status": {"type": "string", "description": "수금 상태 (미수금/부분입금/입금완료)"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
            Tool(
                name="get_financial_overview",
                description="재무 대시보드 요약. 총 매출, 수금액, 미수금을 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "description": "조회 연도 (생략 시 전체)"},
                    },
                },
            ),
            Tool(
                name="get_unpaid_invoices",
                description="미수금 현황 조회. 아직 수금되지 않은 세금계산서 목록을 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_financial_tool(name: str, arguments: dict):
        if name == "get_revenue_summary":
            return await _get_revenue_summary(**arguments)
        elif name == "get_tax_invoices":
            return await _get_tax_invoices(**arguments)
        elif name == "get_financial_overview":
            return await _get_financial_overview(**arguments)
        elif name == "get_unpaid_invoices":
            return await _get_unpaid_invoices(**arguments)


async def _get_revenue_summary(year: int, month: int = None):
    from modules.models.entities import TaxInvoice
    from sqlalchemy import func, extract

    session = get_session()
    try:
        if month:
            # 월 상세: 일별 집계
            rows = session.query(
                func.date(TaxInvoice.issue_date).label("date"),
                func.sum(TaxInvoice.supply_amount).label("supply"),
                func.sum(TaxInvoice.tax_amount).label("tax"),
                func.sum(TaxInvoice.total_amount).label("total"),
                func.count(TaxInvoice.id).label("count"),
            ).filter(
                extract("year", TaxInvoice.issue_date) == year,
                extract("month", TaxInvoice.issue_date) == month,
            ).group_by(func.date(TaxInvoice.issue_date)).order_by("date").all()

            result = [{
                "date": str(r.date),
                "supply_amount": int(r.supply or 0),
                "tax_amount": int(r.tax or 0),
                "total_amount": int(r.total or 0),
                "count": r.count,
            } for r in rows]
        else:
            # 연간: 월별 집계
            rows = session.query(
                extract("month", TaxInvoice.issue_date).label("month"),
                func.sum(TaxInvoice.supply_amount).label("supply"),
                func.sum(TaxInvoice.total_amount).label("total"),
                func.count(TaxInvoice.id).label("count"),
            ).filter(
                extract("year", TaxInvoice.issue_date) == year,
            ).group_by("month").order_by("month").all()

            result = [{
                "month": int(r.month),
                "supply_amount": int(r.supply or 0),
                "total_amount": int(r.total or 0),
                "count": r.count,
            } for r in rows]

        grand_total = sum(r.get("total_amount", 0) for r in result)
        return [TextContent(type="text", text=json.dumps({
            "year": year,
            "month": month,
            "grand_total": grand_total,
            "items": result,
        }, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_tax_invoices(year=None, month=None, payment_status=None, limit=50):
    from modules.models.entities import TaxInvoice
    from sqlalchemy import extract

    session = get_session()
    try:
        q = session.query(TaxInvoice)
        if year:
            q = q.filter(extract("year", TaxInvoice.issue_date) == year)
        if month:
            q = q.filter(extract("month", TaxInvoice.issue_date) == month)
        if payment_status:
            q = q.filter(TaxInvoice.payment_status == payment_status)
        invoices = q.order_by(TaxInvoice.issue_date.desc()).limit(limit).all()

        result = [{
            "id": inv.id,
            "approval_no": _safe(inv.approval_no),
            "issue_date": _safe_date(inv.issue_date),
            "buyer_name": _safe(inv.buyer_name),
            "supply_amount": int(inv.supply_amount or 0),
            "tax_amount": int(inv.tax_amount or 0),
            "total_amount": int(inv.total_amount or 0),
            "payment_status": _safe(inv.payment_status) if hasattr(inv, "payment_status") else "",
            "match_status": _safe(inv.match_status) if hasattr(inv, "match_status") else "",
            "g2b_matched": bool(getattr(inv, "g2b_procurement_id", None)),
        } for inv in invoices]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_financial_overview(year=None):
    from modules.models.entities import TaxInvoice
    from sqlalchemy import func, extract

    session = get_session()
    try:
        q = session.query(
            func.sum(TaxInvoice.supply_amount).label("total_supply"),
            func.sum(TaxInvoice.tax_amount).label("total_tax"),
            func.sum(TaxInvoice.total_amount).label("total"),
            func.count(TaxInvoice.id).label("count"),
        )
        if year:
            q = q.filter(extract("year", TaxInvoice.issue_date) == year)
        row = q.first()

        # 미수금
        unpaid_q = session.query(func.sum(TaxInvoice.total_amount))
        if year:
            unpaid_q = unpaid_q.filter(extract("year", TaxInvoice.issue_date) == year)
        if hasattr(TaxInvoice, "payment_status"):
            unpaid_q = unpaid_q.filter(TaxInvoice.payment_status.in_(["미수금", "부분입금"]))
        unpaid = unpaid_q.scalar() or 0

        result = {
            "year": year,
            "total_supply_amount": int(row.total_supply or 0),
            "total_tax_amount": int(row.total_tax or 0),
            "total_amount": int(row.total or 0),
            "invoice_count": row.count or 0,
            "unpaid_amount": int(unpaid),
            "paid_amount": int((row.total or 0) - unpaid),
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_unpaid_invoices(limit=50):
    from modules.models.entities import TaxInvoice

    session = get_session()
    try:
        q = session.query(TaxInvoice)
        if hasattr(TaxInvoice, "payment_status"):
            q = q.filter(TaxInvoice.payment_status.in_(["미수금", "부분입금"]))
        invoices = q.order_by(TaxInvoice.issue_date.desc()).limit(limit).all()

        result = [{
            "id": inv.id,
            "approval_no": _safe(inv.approval_no),
            "issue_date": _safe_date(inv.issue_date),
            "buyer_name": _safe(inv.buyer_name),
            "total_amount": int(inv.total_amount or 0),
            "payment_status": _safe(inv.payment_status) if hasattr(inv, "payment_status") else "",
        } for inv in invoices]

        grand_total = sum(r["total_amount"] for r in result)
        return [TextContent(type="text", text=json.dumps({
            "total_unpaid": grand_total,
            "count": len(result),
            "items": result,
        }, ensure_ascii=False, indent=2))]
    finally:
        session.close()
