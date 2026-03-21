"""FR-07: 조달/발주 도메인 Tools (4개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_purchase_orders(
        status: Optional[str] = None,
        vendor_id: Optional[int] = None,
        project_id: Optional[int] = None,
        limit: int = 50,
    ) -> str:
        """발주서 목록 조회. 상태, 거래처, 현장으로 필터링합니다.
        status 예: 작성중, 발송완료, 입고대기, 입고완료, 취소
        """
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

            return json.dumps([{
                "id": po.id,
                "po_no": _s(po.po_no),
                "po_date": _sd(po.po_date),
                "status": _s(po.status),
                "vendor_name": _s(po.vendor.vendor_name) if po.vendor else "",
                "project_name": _s(po.project.temp_name) if po.project else "",
                "total_amount": int(po.total_amount or 0),
                "item_count": len(po.items),
                "note": _s(po.note),
            } for po in orders], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_po_detail(
        po_id: Optional[int] = None,
        po_no: Optional[str] = None,
    ) -> str:
        """발주서 상세 조회. 발주 품목 목록과 금액을 포함합니다.
        po_id 또는 po_no 중 하나는 필수.
        """
        from modules.models.entities import PurchaseOrder
        session = get_session()
        try:
            if po_id:
                po = session.get(PurchaseOrder, po_id)
            elif po_no:
                po = session.query(PurchaseOrder).filter(PurchaseOrder.po_no == po_no).first()
            else:
                return "po_id 또는 po_no가 필요합니다."

            if not po:
                return "발주서를 찾을 수 없습니다."

            items = [{
                "item_name": _s(i.item_name),
                "item_spec": _s(i.item_spec),
                "quantity": float(i.quantity or 0),
                "unit": _s(i.unit),
                "unit_price": int(i.unit_price or 0),
                "amount": int(i.amount or 0),
                "delivery_date": _sd(i.delivery_date),
            } for i in po.items]

            return json.dumps({
                "id": po.id,
                "po_no": _s(po.po_no),
                "po_date": _sd(po.po_date),
                "status": _s(po.status),
                "vendor_name": _s(po.vendor.vendor_name) if po.vendor else "",
                "project_name": _s(po.project.temp_name) if po.project else "",
                "total_amount": int(po.total_amount or 0),
                "tax_amount": int(po.tax_amount or 0),
                "note": _s(po.note),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_receiving_history(
        vendor_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """입고 이력 조회. 입고일, 거래처별 입고 내역을 반환합니다.
        date_from / date_to: YYYY-MM-DD 형식
        """
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
                    "item_name": _s(i.item_name),
                    "item_spec": _s(i.item_spec),
                    "received_qty": float(i.received_qty or 0),
                    "unit_price": int(i.unit_price or 0),
                    "amount": int(i.amount or 0),
                } for i in rcv.items]
                result.append({
                    "id": rcv.id,
                    "rcv_no": _s(rcv.rcv_no),
                    "rcv_date": _sd(rcv.rcv_date),
                    "status": _s(rcv.status),
                    "vendor_name": _s(rcv.vendor.vendor_name) if rcv.vendor else "",
                    "total_amount": sum(i["amount"] for i in items),
                    "items": items,
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_vendor_list(search: Optional[str] = None) -> str:
        """거래처 목록 조회. 거래처명, 담당자, 연락처를 반환합니다."""
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
                            "contact_email", "business_no", "address"]:
                    if hasattr(v, col):
                        row[col] = _s(getattr(v, col))
                result.append(row)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
