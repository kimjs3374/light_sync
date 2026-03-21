"""FR-10: 납품 도메인 Tools (3개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_deliveries(
        status: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: int = 50,
    ) -> str:
        """납품 현황 조회. 상태, 현장으로 필터링합니다.
        status 예: 대기, 진행중, 완료
        """
        from modules.models.entities import Delivery, Project
        session = get_session()
        try:
            q = session.query(Delivery)
            if status:
                q = q.filter(Delivery.delivery_status.ilike(f"%{status}%"))
            if project_id:
                q = q.filter(Delivery.project_id == project_id)
            deliveries = q.order_by(Delivery.id.desc()).limit(limit).all()

            result = []
            for d in deliveries:
                proj = session.get(Project, d.project_id) if d.project_id else None
                result.append({
                    "id": d.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "delivery_status": _s(d.delivery_status),
                    "inspection_status": _s(d.inspection_status),
                    "inspection_date": _sd(d.inspection_date),
                    "planned_total_qty": _sn(d.planned_total_qty),
                    "delivered_total_qty": _sn(d.delivered_total_qty),
                    "contact_name": _s(d.contact_name),
                    "contact_phone": _s(d.contact_phone),
                    "note": _s(d.note),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_detail(delivery_id: int) -> str:
        """납품 상세 조회. 분할 납품 목록을 포함합니다."""
        from modules.models.entities import Delivery, DeliverySplit, Project
        session = get_session()
        try:
            d = session.get(Delivery, delivery_id)
            if not d:
                return "납품 정보를 찾을 수 없습니다."

            proj = session.get(Project, d.project_id) if d.project_id else None
            splits = session.query(DeliverySplit).filter(
                DeliverySplit.delivery_id == delivery_id
            ).order_by(DeliverySplit.split_no).all()

            return json.dumps({
                "id": d.id,
                "project_name": _s(proj.temp_name) if proj else "",
                "delivery_status": _s(d.delivery_status),
                "inspection_status": _s(d.inspection_status),
                "inspection_date": _sd(d.inspection_date),
                "inspection_note": _s(d.inspection_note),
                "planned_total_qty": _sn(d.planned_total_qty),
                "delivered_total_qty": _sn(d.delivered_total_qty),
                "contact_name": _s(d.contact_name),
                "contact_phone": _s(d.contact_phone),
                "note": _s(d.note),
                "splits": [{
                    "split_no": s.split_no,
                    "quantity": _sn(s.quantity),
                    "scheduled_date": _sd(s.scheduled_date),
                    "confirmed_date": _sd(s.confirmed_date),
                    "status": _s(s.status),
                    "note": _s(s.note),
                } for s in splits],
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_status_summary() -> str:
        """납품 상태별 요약 통계. 상태별 건수와 수량을 반환합니다."""
        from modules.models.entities import Delivery
        from sqlalchemy import func
        session = get_session()
        try:
            rows = session.query(
                Delivery.delivery_status,
                func.count(Delivery.id).label("count"),
                func.sum(Delivery.planned_total_qty).label("planned"),
                func.sum(Delivery.delivered_total_qty).label("delivered"),
            ).group_by(Delivery.delivery_status).all()

            return json.dumps({
                "summary": [{
                    "status": _s(r.delivery_status) or "미설정",
                    "count": r.count,
                    "planned_qty": _sn(r.planned),
                    "delivered_qty": _sn(r.delivered),
                } for r in rows],
                "total_count": sum(r.count for r in rows),
            }, ensure_ascii=False)
        finally:
            session.close()
