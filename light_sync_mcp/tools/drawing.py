"""FR-13: 도면 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_drawings(
        project_id: Optional[int] = None,
        drawing_type: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """도면 목록 조회. 현장별, 유형별 필터링.
        drawing_type: 설계도, 시공도, 기타
        """
        from modules.models.entities import Drawing, Project
        session = get_session()
        try:
            q = session.query(Drawing)
            if project_id:
                q = q.filter(Drawing.project_id == project_id)
            if drawing_type:
                q = q.filter(Drawing.drawing_type.ilike(f"%{drawing_type}%"))
            drawings = q.order_by(Drawing.created_at.desc()).limit(limit).all()

            result = []
            for d in drawings:
                proj = session.get(Project, d.project_id) if d.project_id else None
                result.append({
                    "id": d.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "title": _s(d.title),
                    "drawing_type": _s(d.drawing_type),
                    "created_by": _s(d.created_by),
                    "created_at": _sd(d.created_at),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_drawing_versions(drawing_id: int) -> str:
        """도면 버전 목록 조회. 최신 버전 포함."""
        from modules.models.entities import Drawing, DrawingVersion
        session = get_session()
        try:
            drawing = session.get(Drawing, drawing_id)
            if not drawing:
                return "도면을 찾을 수 없습니다."

            versions = session.query(DrawingVersion).filter(
                DrawingVersion.drawing_id == drawing_id
            ).order_by(DrawingVersion.version_no.desc()).all()

            return json.dumps({
                "drawing_id": drawing_id,
                "title": _s(drawing.title),
                "versions": [{
                    "version_no": v.version_no,
                    "is_latest": v.is_latest,
                    "created_by": _s(v.created_by),
                    "created_at": _sd(v.created_at),
                } for v in versions],
            }, ensure_ascii=False)
        finally:
            session.close()
