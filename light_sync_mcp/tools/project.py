"""FR-02: 현장/프로젝트 도메인 Tools (5개)"""
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
    async def list_project_tools():
        return [
            Tool(
                name="get_projects",
                description="현장 목록 조회. 상태, 계약 여부, 연도, 검색어로 필터링합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "현장 상태 (설계/영업, 계약, 생산, 납품완료 등)"},
                        "is_contracted": {"type": "boolean", "description": "계약 체결 여부"},
                        "year": {"type": "integer", "description": "계약연도 필터"},
                        "search": {"type": "string", "description": "현장명/약칭/주소 검색"},
                        "limit": {"type": "integer", "default": 100},
                    },
                },
            ),
            Tool(
                name="get_project_detail",
                description="현장 상세 조회. 계약, 납품, 이력 정보를 포함합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "integer", "description": "현장 ID"},
                        "project_no": {"type": "string", "description": "관리번호 (project_id 또는 project_no 중 하나 필수)"},
                    },
                },
            ),
            Tool(
                name="search_projects",
                description="현장 통합 검색. 현장명, 약칭, 주소로 검색합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색어"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_project_timeline",
                description="현장별 납품/생산 타임라인. 납품일정과 생산 공정 일정을 시계열로 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "integer", "description": "현장 ID"},
                    },
                    "required": ["project_id"],
                },
            ),
            Tool(
                name="get_delivery_summary",
                description="현장별 납품집계. 연월 기준 납품 실적을 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "description": "조회 연도"},
                        "month": {"type": "integer", "description": "조회 월 (생략 시 연간 전체)"},
                        "project_id": {"type": "integer", "description": "특정 현장 ID"},
                    },
                    "required": ["year"],
                },
            ),
        ]

    @server.call_tool()
    async def call_project_tool(name: str, arguments: dict):
        if name == "get_projects":
            return await _get_projects(**arguments)
        elif name == "get_project_detail":
            return await _get_project_detail(**arguments)
        elif name == "search_projects":
            return await _search_projects(**arguments)
        elif name == "get_project_timeline":
            return await _get_project_timeline(**arguments)
        elif name == "get_delivery_summary":
            return await _get_delivery_summary(**arguments)


async def _get_projects(status=None, is_contracted=None, year=None, search=None, limit=100):
    from modules.models.entities import Project
    from sqlalchemy import extract

    session = get_session()
    try:
        q = session.query(Project)
        if status:
            q = q.filter(Project.status.ilike(f"%{status}%"))
        if is_contracted is not None:
            q = q.filter(Project.is_contracted == is_contracted)
        if year:
            q = q.filter(extract("year", Project.created_at) == year)
        if search:
            q = q.filter(
                Project.temp_name.ilike(f"%{search}%")
                | Project.short_name.ilike(f"%{search}%")
                | Project.site_address.ilike(f"%{search}%")
            )
        projects = q.order_by(Project.created_at.desc()).limit(limit).all()

        result = [{
            "id": p.id,
            "project_no": _safe(p.project_no),
            "temp_name": _safe(p.temp_name),
            "short_name": _safe(p.short_name),
            "status": _safe(p.status),
            "is_contracted": p.is_contracted,
            "is_urgent": p.is_urgent,
            "contract_date": _safe_date(p.contract_date),
            "site_address": _safe(p.site_address),
            "created_at": _safe_date(p.created_at),
        } for p in projects]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_project_detail(project_id=None, project_no=None):
    from modules.models.entities import Project

    session = get_session()
    try:
        if project_id:
            p = session.query(Project).get(project_id)
        elif project_no:
            p = session.query(Project).filter(Project.project_no == project_no).first()
        else:
            return [TextContent(type="text", text="project_id 또는 project_no가 필요합니다.")]

        if not p:
            return [TextContent(type="text", text="현장을 찾을 수 없습니다.")]

        contracts = [{
            "id": c.id,
            "contract_no": _safe(c.contract_no) if hasattr(c, "contract_no") else "",
            "contract_amount": int(c.contract_amount) if hasattr(c, "contract_amount") and c.contract_amount else 0,
            "delivery_date": _safe_date(c.delivery_date) if hasattr(c, "delivery_date") else "",
        } for c in p.contracts]

        deliveries = [{
            "id": d.id,
            "delivery_date": _safe_date(d.delivery_date) if hasattr(d, "delivery_date") else "",
            "status": _safe(d.status) if hasattr(d, "status") else "",
        } for d in p.deliveries]

        result = {
            "id": p.id,
            "project_no": _safe(p.project_no),
            "temp_name": _safe(p.temp_name),
            "short_name": _safe(p.short_name),
            "status": _safe(p.status),
            "is_contracted": p.is_contracted,
            "is_urgent": p.is_urgent,
            "site_address": _safe(p.site_address),
            "shipping_address": _safe(p.shipping_address),
            "design_basis": _safe(p.design_basis),
            "site_memo": _safe(p.site_memo),
            "contract_date": _safe_date(p.contract_date),
            "spec_confirmed": p.spec_confirmed,
            "created_at": _safe_date(p.created_at),
            "contracts": contracts,
            "deliveries": deliveries,
            "contract_count": len(contracts),
            "delivery_count": len(deliveries),
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _search_projects(query: str):
    from modules.models.entities import Project

    session = get_session()
    try:
        projects = session.query(Project).filter(
            Project.temp_name.ilike(f"%{query}%")
            | Project.short_name.ilike(f"%{query}%")
            | Project.site_address.ilike(f"%{query}%")
            | Project.project_no.ilike(f"%{query}%")
        ).order_by(Project.created_at.desc()).limit(30).all()

        result = [{
            "id": p.id,
            "project_no": _safe(p.project_no),
            "temp_name": _safe(p.temp_name),
            "short_name": _safe(p.short_name),
            "status": _safe(p.status),
            "is_contracted": p.is_contracted,
            "site_address": _safe(p.site_address),
        } for p in projects]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_project_timeline(project_id: int):
    from modules.models.entities import Project, Delivery, ProductionProcess

    session = get_session()
    try:
        p = session.query(Project).get(project_id)
        if not p:
            return [TextContent(type="text", text="현장을 찾을 수 없습니다.")]

        deliveries = [{
            "type": "납품",
            "date": _safe_date(d.delivery_date) if hasattr(d, "delivery_date") else "",
            "status": _safe(d.status) if hasattr(d, "status") else "",
        } for d in p.deliveries]

        processes = session.query(ProductionProcess).filter(
            ProductionProcess.project_id == project_id
        ).all() if hasattr(ProductionProcess, "project_id") else []

        production = [{
            "type": "생산",
            "stage": _safe(pr.stage) if hasattr(pr, "stage") else "",
            "status": _safe(pr.status) if hasattr(pr, "status") else "",
            "start_date": _safe_date(pr.start_date) if hasattr(pr, "start_date") else "",
            "end_date": _safe_date(pr.end_date) if hasattr(pr, "end_date") else "",
        } for pr in processes]

        result = {
            "project_id": project_id,
            "project_name": _safe(p.temp_name),
            "timeline": sorted(deliveries + production, key=lambda x: x.get("date", ""), reverse=False),
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_delivery_summary(year: int, month: int = None, project_id: int = None):
    from modules.models.entities import G2bProcurement
    from sqlalchemy import func, extract

    session = get_session()
    try:
        q = session.query(
            G2bProcurement.project_id,
            func.sum(G2bProcurement.total_amount).label("total_amount"),
            func.count(G2bProcurement.id).label("count"),
        ).filter(extract("year", G2bProcurement.contract_date) == year)

        if month:
            q = q.filter(extract("month", G2bProcurement.contract_date) == month)
        if project_id:
            q = q.filter(G2bProcurement.project_id == project_id)

        rows = q.group_by(G2bProcurement.project_id).all()

        from modules.models.entities import Project
        result = []
        total = 0
        for row in rows:
            proj = session.query(Project).get(row.project_id) if row.project_id else None
            amount = int(row.total_amount or 0)
            total += amount
            result.append({
                "project_id": row.project_id,
                "project_name": _safe(proj.temp_name) if proj else "미연결",
                "count": row.count,
                "total_amount": amount,
            })
        result.sort(key=lambda x: x["total_amount"], reverse=True)

        return [TextContent(type="text", text=json.dumps({
            "year": year,
            "month": month,
            "grand_total": total,
            "items": result,
        }, ensure_ascii=False, indent=2))]
    finally:
        session.close()
