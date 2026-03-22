"""조도설계 검증 Tools"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_illuminance_projects(
        status: Optional[str] = None,
        facility_type: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """조도설계 검증 프로젝트 목록 조회.
        status: design(설계), measured(측정), reported(보고)
        facility_type: 풋살장, 축구장, 테니스장, 주차장, 보행로
        search: 프로젝트명/고객명 검색
        """
        from modules.models.entities import IlluminanceProject
        from sqlalchemy import or_
        session = get_session()
        try:
            q = session.query(IlluminanceProject)
            if status:
                q = q.filter(IlluminanceProject.status == status)
            if facility_type:
                q = q.filter(IlluminanceProject.facility_type.ilike(f"%{facility_type}%"))
            if search:
                kw = f"%{search}%"
                q = q.filter(or_(
                    IlluminanceProject.project_name.ilike(kw),
                    IlluminanceProject.customer.ilike(kw),
                    IlluminanceProject.location.ilike(kw),
                ))

            projects = q.order_by(IlluminanceProject.created_at.desc()).limit(limit).all()

            result = []
            for p in projects:
                area_count = len(p.areas) if p.areas else 0
                result.append({
                    "id": p.id,
                    "project_name": _s(p.project_name),
                    "customer": _s(p.customer),
                    "location": _s(p.location),
                    "facility_type": _s(p.facility_type),
                    "status": _s(p.status),
                    "install_date": _sd(p.install_date),
                    "area_count": area_count,
                    "erp_project_id": p.erp_project_id,
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_illuminance_detail(project_id: int) -> str:
        """조도설계 검증 프로젝트 상세 조회. 구역별 설계조도와 KS 기준 판정을 포함합니다."""
        from modules.models.entities import IlluminanceProject, IlluminanceArea
        session = get_session()
        try:
            p = session.get(IlluminanceProject, project_id)
            if not p:
                return "조도 프로젝트를 찾을 수 없습니다."

            areas = session.query(IlluminanceArea).filter(
                IlluminanceArea.project_id == project_id
            ).order_by(IlluminanceArea.area_index).all()

            area_list = []
            for a in areas:
                # KS 기준 판정
                ks_pass_eav = None
                ks_pass_uo = None
                if a.ks_eav_min and a.design_eav:
                    ks_pass_eav = a.design_eav >= a.ks_eav_min
                if a.ks_uo_min and a.design_uo:
                    ks_pass_uo = a.design_uo >= a.ks_uo_min

                area_list.append({
                    "area_name": _s(a.area_name),
                    "area_index": a.area_index,
                    "lamp_type": _s(a.lamp_type),
                    "lamp_watt": a.lamp_watt,
                    "lamp_qty": a.lamp_qty,
                    "tower_qty": a.tower_qty,
                    "installation_height": a.installation_height,
                    "design_eav": a.design_eav,
                    "design_emin": a.design_emin,
                    "design_emax": a.design_emax,
                    "design_uo": a.design_uo,
                    "ks_eav_min": a.ks_eav_min,
                    "ks_uo_min": a.ks_uo_min,
                    "ks_pass_eav": ks_pass_eav,
                    "ks_pass_uo": ks_pass_uo,
                    "ks_result": "적합" if (ks_pass_eav and ks_pass_uo) else
                                 "부적합" if (ks_pass_eav is not None) else "미판정",
                    "maintenance_factor": a.maintenance_factor,
                    "total_power": a.total_power,
                })

            return json.dumps({
                "id": p.id,
                "project_name": _s(p.project_name),
                "customer": _s(p.customer),
                "location": _s(p.location),
                "facility_type": _s(p.facility_type),
                "status": _s(p.status),
                "install_date": _sd(p.install_date),
                "notes": _s(p.notes),
                "areas": area_list,
            }, ensure_ascii=False)
        finally:
            session.close()
