"""FR-09: 견적서 도메인 Tools (3개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd, _erp_url


def register(mcp: FastMCP):

    @mcp.tool()
    def get_quotations(
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """견적서 목록 조회. 상태, 검색어로 필터링합니다.
        status 예: 작성중, 발송완료, 계약완료
        search: 견적번호, 프로젝트명, 고객명 검색
        """
        from modules.models.entities import Quotation
        session = get_session()
        try:
            q = session.query(Quotation)
            if status:
                q = q.filter(Quotation.status == status)
            if search:
                q = q.filter(
                    Quotation.quote_no.ilike(f"%{search}%")
                    | Quotation.project_name.ilike(f"%{search}%")
                    | Quotation.customer_name.ilike(f"%{search}%")
                )
            quotes = q.order_by(Quotation.quote_date.desc()).limit(limit).all()
            return json.dumps([{
                "id": qt.id,
                "quote_no": _s(qt.quote_no),
                "quote_date": _sd(qt.quote_date),
                "project_name": _s(qt.project_name),
                "customer_name": _s(qt.customer_name),
                "grand_total": int(qt.grand_total or 0),
                "status": _s(qt.status),
                "item_count": len(qt.items) if hasattr(qt, "items") else 0,
                "created_by": _s(qt.created_by),
                "erp_url": _erp_url(f"/quotation/{qt.id}"),
            } for qt in quotes], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_quotation_detail(quotation_id: int) -> str:
        """견적서 상세 조회. 견적 품목 목록과 부과금 정보를 포함합니다."""
        from modules.models.entities import Quotation
        session = get_session()
        try:
            qt = session.get(Quotation, quotation_id)
            if not qt:
                return "견적서를 찾을 수 없습니다."

            items = [{
                "seq": _sn(i.seq),
                "item_name": _s(i.item_name),
                "item_spec": _s(i.item_spec),
                "unit": _s(i.unit),
                "quantity": _sn(i.quantity),
                "unit_price": int(_sn(i.unit_price)),
                "amount": int(_sn(i.amount)),
                "note": _s(i.note),
            } for i in qt.items] if hasattr(qt, "items") else []

            surcharges = json.loads(qt.surcharges_json) if qt.surcharges_json else []

            return json.dumps({
                "id": qt.id,
                "quote_no": _s(qt.quote_no),
                "quote_date": _sd(qt.quote_date),
                "project_name": _s(qt.project_name),
                "customer_name": _s(qt.customer_name),
                "customer_contact": _s(qt.customer_contact),
                "customer_tel": _s(qt.customer_tel),
                "total_amount": int(qt.total_amount or 0),
                "surcharges": surcharges,
                "grand_total": int(qt.grand_total or 0),
                "tax_included": qt.tax_included,
                "validity_period": _s(qt.validity_period),
                "payment_method": _s(qt.payment_method),
                "note": _s(qt.note),
                "status": _s(qt.status),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_quote_templates() -> str:
        """견적 템플릿 목록 조회."""
        from modules.models.entities import QuoteTemplate
        session = get_session()
        try:
            templates = session.query(QuoteTemplate).order_by(QuoteTemplate.template_name).all()
            return json.dumps([{
                "id": t.id,
                "template_name": _s(t.template_name),
                "note": _s(t.note),
                "created_by": _s(t.created_by),
            } for t in templates], ensure_ascii=False)
        finally:
            session.close()
