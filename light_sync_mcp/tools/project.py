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
        status: '설계/영업'(미계약), '계약'(납품대기/진행중), '납품완료'(완료)
        ★ '납품해야 되는 현장' = status='계약' (계약 체결 후 납품 전 현장)
        ★ '진행 중인 현장' = status='계약'
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

            # 계약금액은 contracts 에 없고 G2B 조달내역(prdct_amt) 합계가 정본
            from modules.models.entities import G2bProcurement
            from sqlalchemy import func

            contracts = []
            for c in p.contracts:
                amount = 0
                if c.g2b_contract_no:
                    amount = int(session.query(
                        func.coalesce(func.sum(G2bProcurement.prdct_amt), 0)
                    ).filter(
                        G2bProcurement.cntrct_dlvr_req_no == c.g2b_contract_no
                    ).scalar() or 0)
                contracts.append({
                    "id": c.id,
                    "contract_name": _s(c.contract_name),
                    "g2b_contract_no": _s(c.g2b_contract_no),
                    "contract_date": _sd(c.contract_date),
                    "delivery_due_date": _sd(c.delivery_due_date),
                    "payment_status": _s(c.payment_status),
                    "contract_amount": amount,
                })

            deliveries = [{
                "id": d.id,
                "delivery_status": _s(d.delivery_status),
                "inspection_status": _s(d.inspection_status),
                "planned_qty": int(d.planned_total_qty or 0),
                "delivered_qty": int(d.delivered_total_qty or 0),
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
                "status": _s(d.delivery_status),
                "inspection_status": _s(d.inspection_status),
                "planned_qty": int(d.planned_total_qty or 0),
                "delivered_qty": int(d.delivered_total_qty or 0),
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
    def get_project_contacts(
        project_id: Optional[int] = None,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """현장 담당자/연락처 검색. 발주처/감리/감독관/시공사 담당 등.

        Args:
            project_id: 특정 현장만 (생략 시 전체)
            query: 이름/전화/이메일/구분 부분 검색
            category: 구분 필터 (예: '감독관', '감리', '시공사', '발주처')
            limit: 최대 반환 건수 (기본 30)
        """
        from modules.models.entities import Contact, Project
        from sqlalchemy import or_
        session = get_session()
        try:
            q = session.query(Contact)
            if project_id:
                q = q.filter(Contact.project_id == project_id)
            if category:
                q = q.filter(Contact.category.ilike(f'%{category}%'))
            if query:
                q = q.filter(or_(
                    Contact.name.ilike(f'%{query}%'),
                    Contact.phone.ilike(f'%{query}%'),
                    Contact.email.ilike(f'%{query}%'),
                    Contact.category.ilike(f'%{query}%'),
                ))
            contacts = q.order_by(Contact.id.desc()).limit(limit).all()

            items = []
            for c in contacts:
                proj = session.get(Project, c.project_id) if c.project_id else None
                items.append({
                    "id": c.id,
                    "project_id": c.project_id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "name": _s(c.name),
                    "category": _s(c.category),
                    "phone": _s(c.phone),
                    "email": _s(c.email),
                })
            return json.dumps({
                "count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_summary(
        year: Optional[int] = None,
        month: Optional[int] = None,
        project_id: Optional[int] = None,
        months_back: int = 24,
        include_old: bool = False,
    ) -> str:
        """현장별 납품집계. 연월 기준 납품 실적(G2B 조달내역)을 반환합니다.

        기본은 **최근 24개월** 데이터만 (옛날 G2B 누적분이 검색에 섞이는 오염 방지).
        year 또는 project_id 명시 시 기간 필터 자동 해제.

        Args:
            year: 연도 (명시 시 해당 연도만, 기간 필터 자동 해제)
            month: 월 (1~12, year 와 함께)
            project_id: 특정 현장만 (명시 시 기간 필터 자동 해제)
            months_back: 최근 N개월 (기본 24). year/project_id 명시 시 무시.
            include_old: True 시 전체 기간 (기본 False).

        수정 이력 (2026-05-14): 기존 코드가 G2bProcurement.project_id /
        total_amount / contract_date 같이 모델에 없는 컬럼을 참조해
        `ToolError: Error executing tool get_delivery_summary` 로 항상 실패.
        실제 모델에 맞춰 Contract.g2b_contract_no = G2bProcurement.cntrct_dlvr_req_no
        join 으로 Project 매핑, prdct_amt 합계, cntrct_dlvr_req_date 기준 연/월 필터.
        """
        from modules.models.entities import G2bProcurement, Project
        from modules.models.contract_entities import Contract
        from sqlalchemy import func, extract
        import datetime
        session = get_session()
        try:
            q = session.query(
                Project.id.label("project_id"),
                Project.temp_name.label("project_name"),
                func.sum(G2bProcurement.prdct_amt).label("total_amount"),
                func.count(G2bProcurement.id).label("count"),
            ).join(
                Contract, Contract.g2b_contract_no == G2bProcurement.cntrct_dlvr_req_no
            ).join(
                Project, Project.id == Contract.project_id
            )
            if year:
                q = q.filter(extract("year", G2bProcurement.cntrct_dlvr_req_date) == year)
            if month:
                q = q.filter(extract("month", G2bProcurement.cntrct_dlvr_req_date) == month)
            if project_id:
                q = q.filter(Project.id == project_id)
            # 기간 필터 — year/project_id 명시 안 됐을 때만 적용
            cutoff = None
            if not year and not project_id and not include_old and months_back > 0:
                cutoff = datetime.date.today() - datetime.timedelta(days=30 * months_back)
                q = q.filter(G2bProcurement.cntrct_dlvr_req_date >= cutoff)
            rows = q.group_by(Project.id, Project.temp_name).all()

            items = []
            total = 0
            for row in rows:
                amount = int(row.total_amount or 0)
                total += amount
                items.append({
                    "project_id": row.project_id,
                    "project_name": _s(row.project_name) if row.project_name else "미연결",
                    "count": row.count,
                    "total_amount": amount,
                })
            items.sort(key=lambda x: x["total_amount"], reverse=True)

            return json.dumps({
                "year": year,
                "month": month,
                "filter_months_back": None if (include_old or year or project_id) else months_back,
                "filter_cutoff_date": str(cutoff) if cutoff else None,
                "include_old": include_old,
                "grand_total": total,
                "count_projects": len(items),
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
