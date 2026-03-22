"""현장별 시방서/규격서 현황 Tools"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_spec_doc_status(
        project_id: Optional[int] = None,
        doc_status: Optional[str] = None,
    ) -> str:
        """현장별 시방서/규격서 반영 현황 조회.
        project_id: 특정 현장 필터
        doc_status: 상태 필터 (미제출, 제출, 승인, 반려)
        """
        from modules.models.entities import SpecDocument, Project
        session = get_session()
        try:
            q = session.query(SpecDocument)
            if project_id:
                q = q.filter(SpecDocument.project_id == project_id)
            if doc_status:
                q = q.filter(SpecDocument.doc_status == doc_status)

            docs = q.order_by(SpecDocument.created_at.desc()).all()

            result = []
            for d in docs:
                proj = session.get(Project, d.project_id) if d.project_id else None
                result.append({
                    "id": d.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "doc_type": _s(d.doc_type),
                    "doc_status": _s(d.doc_status),
                    "title": _s(d.title),
                    "submitted_date": _sd(d.submitted_date),
                    "confirmed_date": _sd(d.confirmed_date),
                    "note": _s(d.note),
                    "created_by": _s(d.created_by),
                })

            # 상태별 집계
            status_counts = {}
            for d in result:
                st = d["doc_status"] or "미분류"
                status_counts[st] = status_counts.get(st, 0) + 1

            return json.dumps({
                "total": len(result),
                "by_status": status_counts,
                "docs": result,
            }, ensure_ascii=False)
        finally:
            session.close()
