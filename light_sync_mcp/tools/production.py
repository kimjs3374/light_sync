"""FR-05: 생산 도메인 Tools (4개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_production_status(
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """생산 현황 조회. 현장별, 품목별 공정 진행 상태를 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            q = session.query(ProductionProcess)
            if project_id:
                q = q.filter(ProductionProcess.project_id == project_id)
            if status:
                q = q.filter(ProductionProcess.status.ilike(f"%{status}%"))
            processes = q.order_by(ProductionProcess.id.desc()).limit(limit).all()

            result = []
            for pr in processes:
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                row = {"id": pr.id, "project_name": _s(proj.temp_name) if proj else ""}
                for col in ["project_id", "status", "stage", "item_name", "quantity",
                            "worker_name", "note"]:
                    if hasattr(pr, col):
                        row[col] = _s(getattr(pr, col))
                for col in ["start_date", "end_date"]:
                    if hasattr(pr, col):
                        row[col] = _sd(getattr(pr, col))
                result.append(row)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_production_by_site() -> str:
        """현장별 생산 카드 목록. 현장별로 그룹핑된 생산 공정을 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            processes = session.query(ProductionProcess).all()
            by_project = {}
            for pr in processes:
                pid = pr.project_id or 0
                if pid not in by_project:
                    proj = session.get(Project, pid) if pid else None
                    by_project[pid] = {
                        "project_id": pid,
                        "project_name": _s(proj.temp_name) if proj else "미연결",
                        "processes": [],
                    }
                row = {"id": pr.id}
                for col in ["status", "stage", "item_name", "quantity", "worker_name"]:
                    if hasattr(pr, col):
                        row[col] = _s(getattr(pr, col))
                by_project[pid]["processes"].append(row)

            return json.dumps(list(by_project.values()), ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_worker_assignments() -> str:
        """작업자 배치 현황. 진행 중인 생산 공정의 담당자별 작업 목록을 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            processes = session.query(ProductionProcess).all()
            by_worker = {}
            for pr in processes:
                worker = _s(pr.worker_name) if hasattr(pr, "worker_name") else "미배정"
                if not worker:
                    worker = "미배정"
                if worker not in by_worker:
                    by_worker[worker] = {"worker_name": worker, "tasks": []}
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                by_worker[worker]["tasks"].append({
                    "process_id": pr.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "stage": _s(pr.stage) if hasattr(pr, "stage") else "",
                    "status": _s(pr.status) if hasattr(pr, "status") else "",
                    "item_name": _s(pr.item_name) if hasattr(pr, "item_name") else "",
                })
            return json.dumps(list(by_worker.values()), ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_fab_status() -> str:
        """FAB 공정 현황. FAB 단계의 생산 공정 목록을 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            q = session.query(ProductionProcess)
            if hasattr(ProductionProcess, "stage"):
                q = q.filter(ProductionProcess.stage.ilike("%FAB%"))
            processes = q.all()

            result = []
            for pr in processes:
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                row = {"id": pr.id, "project_name": _s(proj.temp_name) if proj else ""}
                for col in ["status", "stage", "item_name", "quantity", "worker_name", "note"]:
                    if hasattr(pr, col):
                        row[col] = _s(getattr(pr, col))
                result.append(row)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
