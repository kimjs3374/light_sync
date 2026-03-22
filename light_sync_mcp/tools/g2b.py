"""G2B 조달내역 기반 계약 조회 Tools (contracts 테이블 대체)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_g2b_contract_detail(
        contract_no: Optional[str] = None,
        search: Optional[str] = None,
    ) -> str:
        """G2B 계약납품요구번호 기준 계약 상세 조회.
        contract_no: 계약납품요구번호 (예: 20250312104112461)
        search: 계약명/수요기관명/품명 검색
        동일 계약번호의 여러 품목을 그룹핑하여 반환합니다.
        contracts 테이블(0건) 대신 g2b_procurements 테이블 사용.
        """
        from modules.models.entities import G2bProcurement
        from sqlalchemy import or_
        session = get_session()
        try:
            q = session.query(G2bProcurement)
            if contract_no:
                q = q.filter(G2bProcurement.cntrct_dlvr_req_no == contract_no)
            elif search:
                kw = f"%{search}%"
                q = q.filter(or_(
                    G2bProcurement.cntrct_dlvr_req_nm.ilike(kw),
                    G2bProcurement.dminstt_nm.ilike(kw),
                    G2bProcurement.prdct_clsfc_no_nm.ilike(kw),
                    G2bProcurement.dtil_prdct_clsfc_no_nm.ilike(kw),
                ))
            else:
                return "contract_no 또는 search 파라미터가 필요합니다."

            rows = q.order_by(
                G2bProcurement.cntrct_dlvr_req_no,
                G2bProcurement.prdct_sno,
            ).all()

            if not rows:
                return "조달내역을 찾을 수 없습니다."

            # 계약번호별 그룹핑
            groups = {}
            for r in rows:
                key = r.cntrct_dlvr_req_no
                if key not in groups:
                    groups[key] = {
                        "cntrct_dlvr_req_no": _s(key),
                        "cntrct_dlvr_req_nm": _s(r.cntrct_dlvr_req_nm),
                        "cntrct_dlvr_req_date": _sd(r.cntrct_dlvr_req_date),
                        "dminstt_nm": _s(r.dminstt_nm),
                        "dminstt_rgn_nm": _s(r.dminstt_rgn_nm),
                        "cntrct_div_nm": _s(r.cntrct_div_nm),
                        "dlvr_tmlmt_date": _sd(r.dlvr_tmlmt_date),
                        "dlvr_plce_nm": _s(r.dlvr_plce_nm),
                        "corp_nm": _s(r.corp_nm),
                        "total_amt": 0,
                        "items": [],
                    }
                groups[key]["total_amt"] += int(r.prdct_amt or 0)
                groups[key]["items"].append({
                    "prdct_sno": _s(r.prdct_sno),
                    "prdct_clsfc_no_nm": _s(r.prdct_clsfc_no_nm),
                    "dtil_prdct_clsfc_no_nm": _s(r.dtil_prdct_clsfc_no_nm),
                    "prdct_idnt_no_nm": _s(r.prdct_idnt_no_nm),
                    "prdct_qty": int(r.prdct_qty or 0),
                    "prdct_unit": _s(r.prdct_unit),
                    "prdct_uprc": int(r.prdct_uprc or 0),
                    "prdct_amt": int(r.prdct_amt or 0),
                })

            result = list(groups.values())
            if len(result) == 1:
                return json.dumps(result[0], ensure_ascii=False)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_warranty_by_g2b(
        contract_no: Optional[str] = None,
        search: Optional[str] = None,
    ) -> str:
        """G2B 계약번호 또는 현장명으로 하자보증 조회.
        contract_no: G2B 계약납품요구번호
        search: 계약명/현장명 검색
        warranties 테이블에서 contract_name 매칭.
        """
        from modules.models.entities import Warranty, Project
        from sqlalchemy import or_
        session = get_session()
        try:
            q = session.query(Warranty)
            if contract_no:
                # warranties에 g2b_contract_no 없으므로 contract_name으로 검색
                # 또는 project → g2b 매칭
                q = q.filter(Warranty.contract_name.ilike(f"%{contract_no}%"))
            elif search:
                kw = f"%{search}%"
                q = q.filter(or_(
                    Warranty.contract_name.ilike(kw),
                    Warranty.model_name.ilike(kw),
                    Warranty.site_address.ilike(kw),
                ))
            else:
                return "contract_no 또는 search 파라미터가 필요합니다."

            warranties = q.order_by(Warranty.warranty_end.desc()).all()

            result = []
            for w in warranties:
                proj = session.get(Project, w.project_id) if w.project_id else None
                days_left = None
                if w.warranty_end:
                    import datetime
                    days_left = (w.warranty_end - datetime.date.today()).days

                result.append({
                    "id": w.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "contract_name": _s(w.contract_name),
                    "item_group": _s(w.item_group),
                    "model_name": _s(w.model_name),
                    "quantity": int(w.quantity or 0),
                    "warranty_type": _s(w.warranty_type),
                    "warranty_start": _sd(w.warranty_start),
                    "warranty_end": _sd(w.warranty_end),
                    "days_left": days_left,
                    "warranty_amount": int(w.warranty_amount or 0),
                    "insurance_no": _s(w.insurance_no),
                    "insurance_returned": w.insurance_returned,
                    "site_address": _s(w.site_address),
                    "auto_generated": w.auto_generated,
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
