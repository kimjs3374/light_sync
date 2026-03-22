"""조명배치도 Tools (타워별 투광등 넘버링 + 렌즈각도)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_lighting_layouts(
        project_id: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """조명배치도 목록 조회. 현장별 타워 배치 현황.
        project_id: 현장 ID 필터
        search: 현장명 검색
        """
        from modules.models.entities import TowerLayout, Project
        session = get_session()
        try:
            q = session.query(TowerLayout)
            if project_id:
                q = q.filter(TowerLayout.project_id == project_id)
            if search:
                # Project join으로 검색
                q = q.join(Project, TowerLayout.project_id == Project.id).filter(
                    Project.temp_name.ilike(f"%{search}%")
                )

            towers = q.order_by(TowerLayout.created_at.desc()).limit(limit).all()

            result = []
            for t in towers:
                proj = session.get(Project, t.project_id) if t.project_id else None
                result.append({
                    "id": t.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "project_id": t.project_id,
                    "tower_name": _s(t.tower_name),
                    "rows": t.rows,
                    "cols": t.cols,
                    "total_lights": t.rows * t.cols,
                    "model_name": _s(t.model_name),
                    "watt": t.watt,
                    "note": _s(t.note),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_lighting_layout_detail(tower_id: int) -> str:
        """조명배치도 타워 상세 조회. 각 투광등 위치별 렌즈각도를 포함합니다."""
        from modules.models.entities import TowerLayout, TowerLayoutPosition, Project
        session = get_session()
        try:
            t = session.get(TowerLayout, tower_id)
            if not t:
                return "배치도를 찾을 수 없습니다."

            proj = session.get(Project, t.project_id) if t.project_id else None
            positions = session.query(TowerLayoutPosition).filter(
                TowerLayoutPosition.tower_layout_id == tower_id
            ).order_by(TowerLayoutPosition.position_no).all()

            return json.dumps({
                "id": t.id,
                "project_name": _s(proj.temp_name) if proj else "",
                "tower_name": _s(t.tower_name),
                "rows": t.rows,
                "cols": t.cols,
                "model_name": _s(t.model_name),
                "watt": t.watt,
                "note": _s(t.note),
                "positions": [{
                    "position_no": p.position_no,
                    "row": p.row_idx,
                    "col": p.col_idx,
                    "lens_angle": _s(p.lens_angle),
                    "note": _s(p.note),
                } for p in positions],
            }, ensure_ascii=False)
        finally:
            session.close()
