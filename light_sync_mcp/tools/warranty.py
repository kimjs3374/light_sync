"""FR-11: AS/보증 도메인 Tools (3개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_warranty_cases(
        status: Optional[str] = None,
        defect_type: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: int = 50,
    ) -> str:
        """AS/하자 케이스 목록 조회.
        status 예: 접수, 현장방문예정, 처리중, 완료
        defect_type 예: 점등불량, 외관불량, 기구불량
        """
        from modules.models.entities import WarrantyCase, Project
        session = get_session()
        try:
            q = session.query(WarrantyCase)
            if status:
                q = q.filter(WarrantyCase.status.ilike(f"%{status}%"))
            if defect_type:
                q = q.filter(WarrantyCase.defect_type.ilike(f"%{defect_type}%"))
            if project_id:
                q = q.filter(WarrantyCase.project_id == project_id)
            cases = q.order_by(WarrantyCase.created_at.desc()).limit(limit).all()

            result = []
            for c in cases:
                proj = session.get(Project, c.project_id) if c.project_id else None
                result.append({
                    "id": c.id,
                    "case_no": _s(c.case_no),
                    "project_name": _s(proj.temp_name) if proj else _s(c.manual_site_name),
                    "defect_type": _s(c.defect_type),
                    "symptom": _s(c.symptom),
                    "status": _s(c.status),
                    "reported_date": _sd(c.reported_date),
                    "assigned_to": _s(c.assigned_to),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_warranty_case_detail(case_id: int) -> str:
        """AS/하자 케이스 상세 조회. 처리 이력을 포함합니다."""
        from modules.models.entities import WarrantyCase, WarrantyCaseLog, Project
        session = get_session()
        try:
            c = session.get(WarrantyCase, case_id)
            if not c:
                return "AS 케이스를 찾을 수 없습니다."

            proj = session.get(Project, c.project_id) if c.project_id else None
            logs = session.query(WarrantyCaseLog).filter(
                WarrantyCaseLog.case_id == case_id
            ).order_by(WarrantyCaseLog.created_at.desc()).all()

            return json.dumps({
                "id": c.id,
                "case_no": _s(c.case_no),
                "project_name": _s(proj.temp_name) if proj else _s(c.manual_site_name),
                "defect_type": _s(c.defect_type),
                "symptom": _s(c.symptom),
                "status": _s(c.status),
                "reported_by": _s(c.reported_by),
                "reported_date": _sd(c.reported_date),
                "site_visit_date": _sd(c.site_visit_date),
                "completed_date": _sd(c.completed_date),
                "cause_analysis": _s(c.cause_analysis),
                "action_taken": _s(c.action_taken),
                "replaced_parts": _s(c.replaced_parts),
                "assigned_to": _s(c.assigned_to),
                "logs": [{
                    "log_type": _s(lg.log_type),
                    "old_status": _s(lg.old_status),
                    "new_status": _s(lg.new_status),
                    "content": _s(lg.content),
                    "created_by": _s(lg.created_by),
                    "created_at": _sd(lg.created_at),
                } for lg in logs],
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_warranty_stats() -> str:
        """AS/하자 통계. 상태별, 유형별 건수를 반환합니다."""
        from modules.models.entities import WarrantyCase
        from sqlalchemy import func
        session = get_session()
        try:
            by_status = session.query(
                WarrantyCase.status, func.count(WarrantyCase.id)
            ).group_by(WarrantyCase.status).all()

            by_type = session.query(
                WarrantyCase.defect_type, func.count(WarrantyCase.id)
            ).group_by(WarrantyCase.defect_type).all()

            total = session.query(func.count(WarrantyCase.id)).scalar() or 0

            return json.dumps({
                "total_cases": total,
                "by_status": [{"status": _s(s), "count": c} for s, c in by_status],
                "by_defect_type": [{"defect_type": _s(t), "count": c} for t, c in by_type],
            }, ensure_ascii=False)
        finally:
            session.close()
