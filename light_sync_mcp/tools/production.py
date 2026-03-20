"""FR-05: 생산 도메인 Tools (4개)"""
import json
from mcp.server import Server
from mcp.types import Tool, TextContent

from ..db import get_session


def _safe(val, default=""):
    return val if val is not None else default


def _safe_date(val):
    return val.isoformat() if val else ""


def register(server: Server):

    @server.list_tools()
    async def list_production_tools():
        return [
            Tool(
                name="get_production_status",
                description="생산 현황 조회. 현장별, 품목별 공정 진행 상태를 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "integer", "description": "현장 ID 필터"},
                        "status": {"type": "string", "description": "공정 상태 필터"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
            Tool(
                name="get_production_by_site",
                description="현장별 생산 카드 목록. 현장명과 진행 중인 생산 공정을 그룹핑하여 반환합니다.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_worker_assignments",
                description="작업자 배치 현황. 현재 진행 중인 생산 공정의 담당자를 반환합니다.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_fab_status",
                description="FAB 공정 현황. FAB 단계의 생산 공정 목록을 반환합니다.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_production_tool(name: str, arguments: dict):
        if name == "get_production_status":
            return await _get_production_status(**arguments)
        elif name == "get_production_by_site":
            return await _get_production_by_site()
        elif name == "get_worker_assignments":
            return await _get_worker_assignments()
        elif name == "get_fab_status":
            return await _get_fab_status()


async def _get_production_status(project_id=None, status=None, limit=50):
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
            proj = session.query(Project).get(pr.project_id) if pr.project_id else None
            row = {"id": pr.id}
            for col in ["project_id", "status", "stage", "item_name", "quantity",
                        "worker_name", "note"]:
                if hasattr(pr, col):
                    row[col] = _safe(getattr(pr, col))
            for col in ["start_date", "end_date", "planned_date"]:
                if hasattr(pr, col):
                    row[col] = _safe_date(getattr(pr, col))
            row["project_name"] = _safe(proj.temp_name) if proj else ""
            result.append(row)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_production_by_site():
    from modules.models.entities import ProductionProcess, Project

    session = get_session()
    try:
        processes = session.query(ProductionProcess).all()
        by_project = {}
        for pr in processes:
            pid = pr.project_id or 0
            if pid not in by_project:
                proj = session.query(Project).get(pid) if pid else None
                by_project[pid] = {
                    "project_id": pid,
                    "project_name": _safe(proj.temp_name) if proj else "미연결",
                    "processes": [],
                }
            row = {"id": pr.id}
            for col in ["status", "stage", "item_name", "quantity", "worker_name"]:
                if hasattr(pr, col):
                    row[col] = _safe(getattr(pr, col))
            by_project[pid]["processes"].append(row)

        result = list(by_project.values())
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_worker_assignments():
    from modules.models.entities import ProductionProcess, Project

    session = get_session()
    try:
        processes = session.query(ProductionProcess).filter(
            ProductionProcess.status.notin_(["완료", "취소"]) if hasattr(ProductionProcess, "status") else True
        ).all()

        by_worker = {}
        for pr in processes:
            worker = _safe(pr.worker_name) if hasattr(pr, "worker_name") else "미배정"
            if worker not in by_worker:
                by_worker[worker] = {"worker_name": worker, "tasks": []}
            proj = session.query(Project).get(pr.project_id) if pr.project_id else None
            by_worker[worker]["tasks"].append({
                "process_id": pr.id,
                "project_name": _safe(proj.temp_name) if proj else "",
                "stage": _safe(pr.stage) if hasattr(pr, "stage") else "",
                "status": _safe(pr.status) if hasattr(pr, "status") else "",
                "item_name": _safe(pr.item_name) if hasattr(pr, "item_name") else "",
            })

        result = list(by_worker.values())
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_fab_status():
    from modules.models.entities import ProductionProcess, Project

    session = get_session()
    try:
        q = session.query(ProductionProcess)
        if hasattr(ProductionProcess, "stage"):
            q = q.filter(ProductionProcess.stage.ilike("%FAB%"))
        processes = q.all()

        result = []
        for pr in processes:
            proj = session.query(Project).get(pr.project_id) if pr.project_id else None
            row = {"id": pr.id, "project_name": _safe(proj.temp_name) if proj else ""}
            for col in ["status", "stage", "item_name", "quantity", "worker_name", "note"]:
                if hasattr(pr, col):
                    row[col] = _safe(getattr(pr, col))
            for col in ["start_date", "end_date"]:
                if hasattr(pr, col):
                    row[col] = _safe_date(getattr(pr, col))
            result.append(row)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()
