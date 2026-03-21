"""FR-02: 현장/프로젝트 도메인 Tools (7개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_projects(
        status: Optional[str] = None,
        is_contracted: Optional[bool] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """현장 목록 조회. 상태, 계약 여부, 연도, 월, 검색어로 필터링합니다.
        status 예: '설계/영업', '계약', '생산', '납품완료'
        month: 1~12 (year와 함께 사용)
        """
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
            if month:
                q = q.filter(extract("month", Project.created_at) == month)
            if search:
                q = q.filter(
                    Project.temp_name.ilike(f"%{search}%")
                    | Project.short_name.ilike(f"%{search}%")
                    | Project.site_address.ilike(f"%{search}%")
                )
            projects = q.order_by(Project.created_at.desc()).limit(limit).all()

            return json.dumps([{
                "id": p.id,
                "project_no": _s(p.project_no),
                "temp_name": _s(p.temp_name),
                "short_name": _s(p.short_name),
                "status": _s(p.status),
                "is_contracted": p.is_contracted,
                "is_urgent": p.is_urgent,
                "contract_date": _sd(p.contract_date),
                "site_address": _s(p.site_address),
                "created_at": _sd(p.created_at),
            } for p in projects], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_project_detail(
        project_id: Optional[int] = None,
        project_no: Optional[str] = None,
    ) -> str:
        """현장 상세 조회. 계약, 납품 정보를 포함합니다.
        project_id 또는 project_no 중 하나는 필수.
        """
        from modules.models.entities import Project
        session = get_session()
        try:
            if project_id:
                p = session.get(Project, project_id)
            elif project_no:
                p = session.query(Project).filter(Project.project_no == project_no).first()
            else:
                return "project_id 또는 project_no가 필요합니다."

            if not p:
                return "현장을 찾을 수 없습니다."

            contracts = [{
                "id": c.id,
                "contract_amount": int(c.contract_amount) if hasattr(c, "contract_amount") and c.contract_amount else 0,
                "delivery_date": _sd(c.delivery_date) if hasattr(c, "delivery_date") else "",
            } for c in p.contracts]

            deliveries = [{
                "id": d.id,
                "status": _s(d.status) if hasattr(d, "status") else "",
            } for d in p.deliveries]

            return json.dumps({
                "id": p.id,
                "project_no": _s(p.project_no),
                "temp_name": _s(p.temp_name),
                "short_name": _s(p.short_name),
                "status": _s(p.status),
                "is_contracted": p.is_contracted,
                "is_urgent": p.is_urgent,
                "site_address": _s(p.site_address),
                "shipping_address": _s(p.shipping_address),
                "design_basis": _s(p.design_basis),
                "site_memo": _s(p.site_memo),
                "contract_date": _sd(p.contract_date),
                "spec_confirmed": p.spec_confirmed,
                "created_at": _sd(p.created_at),
                "contracts": contracts,
                "deliveries": deliveries,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def search_projects(query: str) -> str:
        """현장 통합 검색. 현장명, 약칭, 주소, 관리번호로 검색합니다."""
        from modules.models.entities import Project
        session = get_session()
        try:
            projects = session.query(Project).filter(
                Project.temp_name.ilike(f"%{query}%")
                | Project.short_name.ilike(f"%{query}%")
                | Project.site_address.ilike(f"%{query}%")
                | Project.project_no.ilike(f"%{query}%")
            ).order_by(Project.created_at.desc()).limit(30).all()

            return json.dumps([{
                "id": p.id,
                "project_no": _s(p.project_no),
                "temp_name": _s(p.temp_name),
                "short_name": _s(p.short_name),
                "status": _s(p.status),
                "is_contracted": p.is_contracted,
                "site_address": _s(p.site_address),
            } for p in projects], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_project_timeline(project_id: int) -> str:
        """현장별 납품/생산 타임라인 조회."""
        from modules.models.entities import Project
        session = get_session()
        try:
            p = session.get(Project, project_id)
            if not p:
                return "현장을 찾을 수 없습니다."

            deliveries = [{
                "type": "납품",
                "status": _s(d.status) if hasattr(d, "status") else "",
            } for d in p.deliveries]

            return json.dumps({
                "project_id": project_id,
                "project_name": _s(p.temp_name),
                "status": _s(p.status),
                "timeline": deliveries,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_summary(year: int, month: Optional[int] = None, project_id: Optional[int] = None) -> str:
        """현장별 납품집계. 연월 기준 납품 실적(G2B 조달내역)을 반환합니다."""
        from modules.models.entities import G2bProcurement, Project
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

            items = []
            total = 0
            for row in rows:
                proj = session.get(Project, row.project_id) if row.project_id else None
                amount = int(row.total_amount or 0)
                total += amount
                items.append({
                    "project_id": row.project_id,
                    "project_name": _s(proj.temp_name) if proj else "미연결",
                    "count": row.count,
                    "total_amount": amount,
                })
            items.sort(key=lambda x: x["total_amount"], reverse=True)

            return json.dumps({
                "year": year,
                "month": month,
                "grand_total": total,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_overdue_projects() -> str:
        """납기 지난 현장 목록. 계약 납기일이 오늘보다 이전이고 아직 완료되지 않은 현장을 반환합니다.
        납기일 초과 일수(days_overdue) 기준 내림차순 정렬.
        """
        import datetime
        from modules.models.entities import Project, Contract
        session = get_session()
        try:
            today = datetime.date.today()
            contracts = session.query(Contract).filter(
                Contract.delivery_due_date < today,
                Contract.delivery_due_date != None,
            ).all()

            result = []
            seen = set()
            for c in contracts:
                proj = session.get(Project, c.project_id) if c.project_id else None
                if not proj:
                    continue
                if proj.status in ("납품완료", "완료", "취소"):
                    continue
                if proj.id in seen:
                    continue
                seen.add(proj.id)

                delivery_date = c.delivery_due_date
                days_overdue = (today - delivery_date).days
                result.append({
                    "project_id": proj.id,
                    "project_no": _s(proj.project_no),
                    "project_name": _s(proj.temp_name),
                    "short_name": _s(proj.short_name),
                    "status": _s(proj.status),
                    "delivery_date": delivery_date.isoformat(),
                    "days_overdue": days_overdue,
                    "is_urgent": proj.is_urgent,
                    "site_address": _s(proj.site_address),
                })

            result.sort(key=lambda x: x["days_overdue"], reverse=True)
            return json.dumps({
                "today": today.isoformat(),
                "overdue_count": len(result),
                "projects": result,
            }, ensure_ascii=False)
        finally:
            session.close()
