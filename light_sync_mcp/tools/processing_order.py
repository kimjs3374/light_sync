"""가공발주 Tools"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_processing_orders(
        status: Optional[str] = None,
        vendor_id: Optional[int] = None,
        project_id: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """가공발주 목록 조회. 외주 가공업체 발주 현황.
        ★ '가공발주 몇 건', '외주가공 현황' 등의 질문에 사용.
        status: 작성중, 발송완료, 입고대기, 입고완료, 취소
        search: 발주번호/업체명/현장명 검색
        """
        from modules.models.entities import ProcessingOrder, Vendor, Project
        from sqlalchemy import or_
        session = get_session()
        try:
            q = session.query(ProcessingOrder)
            if status:
                q = q.filter(ProcessingOrder.status == status)
            if vendor_id:
                q = q.filter(ProcessingOrder.vendor_id == vendor_id)
            if project_id:
                q = q.filter(ProcessingOrder.project_id == project_id)
            if search:
                kw = f"%{search}%"
                q = q.filter(or_(
                    ProcessingOrder.fo_no.ilike(kw),
                    ProcessingOrder.note.ilike(kw),
                ))

            orders = q.order_by(ProcessingOrder.fo_date.desc()).limit(limit).all()

            result = []
            for fo in orders:
                vendor = session.get(Vendor, fo.vendor_id) if fo.vendor_id else None
                proj = session.get(Project, fo.project_id) if fo.project_id else None
                result.append({
                    "id": fo.id,
                    "fo_no": _s(fo.fo_no),
                    "fo_date": _sd(fo.fo_date),
                    "status": _s(fo.status),
                    "processing_type": _s(fo.processing_type),
                    "vendor_name": _s(vendor.name) if vendor else "",
                    "project_name": _s(proj.temp_name) if proj else "",
                    "total_amount": int(fo.total_amount or 0),
                    "item_count": len(fo.items) if fo.items else 0,
                    "note": _s(fo.note),
                })

            return json.dumps({
                "total": len(result),
                "orders": result,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_processing_order_detail(
        fo_id: Optional[int] = None,
        fo_no: Optional[str] = None,
    ) -> str:
        """가공발주 상세 조회. 품목 목록과 첨부파일을 포함합니다.
        fo_id 또는 fo_no 중 하나 필수.
        """
        from modules.models.entities import ProcessingOrder, ProcessingOrderItem, ProcessingOrderFile, Vendor, Project
        session = get_session()
        try:
            if fo_id:
                fo = session.get(ProcessingOrder, fo_id)
            elif fo_no:
                fo = session.query(ProcessingOrder).filter(ProcessingOrder.fo_no == fo_no).first()
            else:
                return "fo_id 또는 fo_no가 필요합니다."

            if not fo:
                return "가공발주를 찾을 수 없습니다."

            vendor = session.get(Vendor, fo.vendor_id) if fo.vendor_id else None
            proj = session.get(Project, fo.project_id) if fo.project_id else None

            items = [{
                "item_name": _s(it.item_name),
                "item_spec": _s(it.item_spec),
                "quantity": _sn(it.quantity),
                "unit": _s(it.unit),
                "unit_price": int(it.unit_price or 0),
                "amount": int(it.amount or 0),
                "delivery_date": _sd(it.delivery_date),
                "in_confirmed": it.in_confirmed,
                "processing_note": _s(it.processing_note),
            } for it in (fo.items or [])]

            files = [{
                "file_name": _s(f.file_name),
                "file_type": _s(f.file_type),
                "file_size": f.file_size,
            } for f in (fo.files or [])]

            return json.dumps({
                "id": fo.id,
                "fo_no": _s(fo.fo_no),
                "fo_date": _sd(fo.fo_date),
                "status": _s(fo.status),
                "processing_type": _s(fo.processing_type),
                "vendor_name": _s(vendor.name) if vendor else "",
                "project_name": _s(proj.temp_name) if proj else "",
                "total_amount": int(fo.total_amount or 0),
                "tax_amount": int(fo.tax_amount or 0),
                "note": _s(fo.note),
                "items": items,
                "files": files,
            }, ensure_ascii=False)
        finally:
            session.close()
