"""FR-18: 오버뷰/진행률 도메인 Tools (1개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn


def register(mcp: FastMCP):

    @mcp.tool()
    def get_project_progress(project_id: Optional[int] = None, limit: int = 30) -> str:
        """프로젝트 진행률 조회. 설계/자재/생산/납품 단계별 완료율을 반환합니다.
        project_id 생략 시 진행중 전체 현장 목록.
        """
        from modules.models.entities import Project, Contract, ContractItem, Delivery
        from sqlalchemy import func
        session = get_session()
        try:
            if project_id:
                projects = [session.get(Project, project_id)]
                if not projects[0]:
                    return "현장을 찾을 수 없습니다."
            else:
                projects = session.query(Project).filter(
                    Project.status.notin_(["납품완료", "완료", "취소"])
                ).order_by(Project.created_at.desc()).limit(limit).all()

            result = []
            for p in projects:
                total_items = session.query(func.count(ContractItem.id)).join(Contract).filter(
                    Contract.project_id == p.id
                ).scalar() or 0

                completed_sales = session.query(func.count(ContractItem.id)).join(Contract).filter(
                    Contract.project_id == p.id,
                    ContractItem.status_sales == "완료",
                ).scalar() or 0

                completed_prod = session.query(func.count(ContractItem.id)).join(Contract).filter(
                    Contract.project_id == p.id,
                    ContractItem.status_prod == "완료",
                ).scalar() or 0

                delivery = session.query(Delivery).filter(
                    Delivery.project_id == p.id
                ).first()
                delivery_progress = 0
                if delivery and _sn(delivery.planned_total_qty) > 0:
                    delivery_progress = round(
                        _sn(delivery.delivered_total_qty) / _sn(delivery.planned_total_qty) * 100, 1
                    )

                result.append({
                    "project_id": p.id,
                    "project_name": _s(p.temp_name),
                    "status": _s(p.status),
                    "total_items": total_items,
                    "sales_progress": round(completed_sales / total_items * 100, 1) if total_items else 0,
                    "production_progress": round(completed_prod / total_items * 100, 1) if total_items else 0,
                    "delivery_progress": delivery_progress,
                })

            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
