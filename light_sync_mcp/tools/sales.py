"""FR-12: 영업 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn


def register(mcp: FastMCP):

    @mcp.tool()
    def get_sales_projects(
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """영업/설계 현장 목록. D-day 우선순위 정렬, 긴급/지연 표시.
        status: 설계/영업, 계약, 생산 등
        """
        import datetime
        from modules.models.entities import Project, Contract, Material
        from sqlalchemy import func
        session = get_session()
        try:
            q = session.query(Project)
            if status:
                q = q.filter(Project.status.ilike(f"%{status}%"))
            else:
                q = q.filter(Project.status.notin_(["납품완료", "완료", "취소"]))
            if search:
                q = q.filter(
                    Project.temp_name.ilike(f"%{search}%")
                    | Project.short_name.ilike(f"%{search}%")
                )
            projects = q.order_by(Project.created_at.desc()).limit(limit).all()

            today = datetime.date.today()
            result = []
            for p in projects:
                contract = session.query(Contract).filter(
                    Contract.project_id == p.id
                ).first()
                due_date = contract.delivery_due_date if contract else None
                d_day = (due_date - today).days if due_date else None

                material_count = session.query(func.count(Material.id)).filter(
                    Material.project_id == p.id
                ).scalar() or 0

                result.append({
                    "id": p.id,
                    "project_no": _s(p.project_no),
                    "temp_name": _s(p.temp_name),
                    "short_name": _s(p.short_name),
                    "status": _s(p.status),
                    "is_contracted": p.is_contracted,
                    "is_urgent": p.is_urgent,
                    "delivery_due_date": due_date.isoformat() if due_date else "",
                    "d_day": d_day,
                    "material_count": material_count,
                })

            result.sort(key=lambda x: x["d_day"] if x["d_day"] is not None else 9999)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_contract_items_status(project_id: int) -> str:
        """현장별 계약품목 상태 조회. 영업/관리/생산 진행 상태를 반환합니다."""
        from modules.models.entities import Contract, ContractItem, Project
        session = get_session()
        try:
            proj = session.get(Project, project_id)
            if not proj:
                return "현장을 찾을 수 없습니다."

            contracts = session.query(Contract).filter(
                Contract.project_id == project_id
            ).all()

            all_items = []
            for ct in contracts:
                items = session.query(ContractItem).filter(
                    ContractItem.contract_id == ct.id
                ).all()
                for it in items:
                    all_items.append({
                        "contract_name": _s(ct.contract_name),
                        "category": _s(it.category),
                        "model_name": _s(it.model_name),
                        "quantity": _sn(it.quantity),
                        "status_sales": _s(it.status_sales),
                        "status_admin": _s(it.status_admin),
                        "status_prod": _s(it.status_prod),
                    })

            return json.dumps({
                "project_id": project_id,
                "project_name": _s(proj.temp_name),
                "items": all_items,
                "total_items": len(all_items),
            }, ensure_ascii=False)
        finally:
            session.close()
