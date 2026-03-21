"""FR-06: 재무/매출 도메인 Tools (4개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_revenue_summary(year: int, month: Optional[int] = None) -> str:
        """매출 집계. 세금계산서 기준 연월별 매출 합산을 반환합니다."""
        from modules.models.entities import TaxInvoice
        from sqlalchemy import func, extract
        session = get_session()
        try:
            if month:
                rows = session.query(
                    func.date(TaxInvoice.issue_date).label("date"),
                    func.sum(TaxInvoice.supply_amount).label("supply"),
                    func.sum(TaxInvoice.total_amount).label("total"),
                    func.count(TaxInvoice.id).label("count"),
                ).filter(
                    extract("year", TaxInvoice.issue_date) == year,
                    extract("month", TaxInvoice.issue_date) == month,
                ).group_by(func.date(TaxInvoice.issue_date)).order_by("date").all()
                items = [{"date": str(r.date), "supply_amount": int(r.supply or 0),
                          "total_amount": int(r.total or 0), "count": r.count} for r in rows]
            else:
                rows = session.query(
                    extract("month", TaxInvoice.issue_date).label("month"),
                    func.sum(TaxInvoice.supply_amount).label("supply"),
                    func.sum(TaxInvoice.total_amount).label("total"),
                    func.count(TaxInvoice.id).label("count"),
                ).filter(extract("year", TaxInvoice.issue_date) == year
                ).group_by("month").order_by("month").all()
                items = [{"month": int(r.month), "supply_amount": int(r.supply or 0),
                          "total_amount": int(r.total or 0), "count": r.count} for r in rows]

            return json.dumps({
                "year": year,
                "month": month,
                "grand_total": sum(i["total_amount"] for i in items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_tax_invoices(
        year: Optional[int] = None,
        month: Optional[int] = None,
        payment_status: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """세금계산서 목록 조회. G2B 매칭 상태, 수금 상태로 필터링합니다.
        payment_status: 미수금 / 부분입금 / 입금완료
        """
        from modules.models.entities import TaxInvoice
        from sqlalchemy import extract
        session = get_session()
        try:
            q = session.query(TaxInvoice)
            if year:
                q = q.filter(extract("year", TaxInvoice.issue_date) == year)
            if month:
                q = q.filter(extract("month", TaxInvoice.issue_date) == month)
            if payment_status and hasattr(TaxInvoice, "payment_status"):
                q = q.filter(TaxInvoice.payment_status == payment_status)
            invoices = q.order_by(TaxInvoice.issue_date.desc()).limit(limit).all()

            return json.dumps([{
                "id": inv.id,
                "approval_no": _s(inv.approval_no),
                "issue_date": _sd(inv.issue_date),
                "buyer_name": _s(inv.buyer_name),
                "supply_amount": int(inv.supply_amount or 0),
                "tax_amount": int(inv.tax_amount or 0),
                "total_amount": int(inv.total_amount or 0),
                "payment_status": _s(inv.payment_status) if hasattr(inv, "payment_status") else "",
                "match_status": _s(inv.match_status) if hasattr(inv, "match_status") else "",
                "g2b_matched": bool(getattr(inv, "g2b_procurement_id", None)),
            } for inv in invoices], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_financial_overview(year: Optional[int] = None) -> str:
        """재무 대시보드 요약. 총 매출, 미수금, 수금액을 반환합니다."""
        from modules.models.entities import TaxInvoice
        from sqlalchemy import func, extract
        session = get_session()
        try:
            q = session.query(
                func.sum(TaxInvoice.supply_amount).label("supply"),
                func.sum(TaxInvoice.total_amount).label("total"),
                func.count(TaxInvoice.id).label("count"),
            )
            if year:
                q = q.filter(extract("year", TaxInvoice.issue_date) == year)
            row = q.first()

            unpaid_q = session.query(func.sum(TaxInvoice.total_amount))
            if year:
                unpaid_q = unpaid_q.filter(extract("year", TaxInvoice.issue_date) == year)
            if hasattr(TaxInvoice, "payment_status"):
                unpaid_q = unpaid_q.filter(TaxInvoice.payment_status.in_(["미수금", "부분입금"]))
            unpaid = int(unpaid_q.scalar() or 0)
            total = int(row.total or 0)

            return json.dumps({
                "year": year,
                "total_supply_amount": int(row.supply or 0),
                "total_amount": total,
                "invoice_count": row.count or 0,
                "unpaid_amount": unpaid,
                "paid_amount": total - unpaid,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_unpaid_invoices(limit: int = 50) -> str:
        """미수금 현황. 수금되지 않은 세금계산서 목록과 합계를 반환합니다."""
        from modules.models.entities import TaxInvoice
        session = get_session()
        try:
            q = session.query(TaxInvoice)
            if hasattr(TaxInvoice, "payment_status"):
                q = q.filter(TaxInvoice.payment_status.in_(["미수금", "부분입금"]))
            invoices = q.order_by(TaxInvoice.issue_date.desc()).limit(limit).all()

            items = [{
                "id": inv.id,
                "approval_no": _s(inv.approval_no),
                "issue_date": _sd(inv.issue_date),
                "buyer_name": _s(inv.buyer_name),
                "total_amount": int(inv.total_amount or 0),
                "payment_status": _s(inv.payment_status) if hasattr(inv, "payment_status") else "",
            } for inv in invoices]

            return json.dumps({
                "total_unpaid": sum(i["total_amount"] for i in items),
                "count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
