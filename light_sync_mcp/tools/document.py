"""서류관리 Tools"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_document_list(
        search: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """서류 패키지 목록 조회. 착수계/납품계 생성 현황을 반환합니다.
        ★ '서류 현황', '착수계', '납품계' 등의 질문에 사용.
        search: 사업명 또는 납품요구번호 검색
        """
        from modules.models.document_entities import DocumentPackage
        session = get_session()
        try:
            q = session.query(DocumentPackage)
            if search:
                q = q.filter(
                    DocumentPackage.business_name.ilike(f"%{search}%")
                    | DocumentPackage.procurement_req_no.ilike(f"%{search}%")
                )
            packages = q.order_by(DocumentPackage.created_at.desc()).limit(limit).all()

            result = []
            for p in packages:
                result.append({
                    "id": p.id,
                    "procurement_req_no": _s(p.procurement_req_no),
                    "business_name": _s(p.business_name),
                    "demand_org": _s(p.demand_org),
                    "commencement_generated": p.commencement_generated or False,
                    "commencement_doc_no": _s(p.commencement_doc_no),
                    "commencement_date": _sd(p.commencement_date),
                    "delivery_generated": p.delivery_generated or False,
                    "delivery_doc_no": _s(p.delivery_doc_no),
                    "delivery_date": _sd(p.delivery_date),
                    "project_name": _s(p.project.temp_name) if p.project else "",
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_document_detail(package_id: int) -> str:
        """서류 패키지 상세 조회. 착수계/납품계 정보, 첨부파일, 금액을 포함합니다.
        ★ 특정 납품요구건의 서류 상세 확인 시 사용.
        """
        from modules.models.document_entities import DocumentPackage, DOC_ATTACH_TYPES
        session = get_session()
        try:
            pkg = session.get(DocumentPackage, package_id)
            if not pkg:
                return "서류 패키지를 찾을 수 없습니다."

            attachments = [{
                "file_type": _s(a.file_type),
                "file_type_label": DOC_ATTACH_TYPES.get(a.file_type, a.file_type),
                "file_name": _s(a.file_name),
            } for a in pkg.attachments]

            return json.dumps({
                "id": pkg.id,
                "procurement_req_no": _s(pkg.procurement_req_no),
                "business_name": _s(pkg.business_name),
                "demand_org": _s(pkg.demand_org),
                "org_type": _s(pkg.org_type),
                "contract_no": _s(pkg.contract_no),
                "contract_date": _sd(pkg.contract_date),
                "total_amount": int(pkg.total_amount or 0),
                "supply_amount": int(pkg.supply_amount or 0),
                "fee": int(pkg.fee or 0),
                "warranty_period": _s(pkg.warranty_period),
                "inspection_org": _s(pkg.inspection_org),
                "acceptance_org": _s(pkg.acceptance_org),
                "commencement": {
                    "generated": pkg.commencement_generated or False,
                    "doc_no": _s(pkg.commencement_doc_no),
                    "date": _sd(pkg.commencement_date),
                    "agent": _s(pkg.commencement_agent.full_name) if pkg.commencement_agent else "",
                },
                "delivery": {
                    "generated": pkg.delivery_generated or False,
                    "doc_no": _s(pkg.delivery_doc_no),
                    "date": _sd(pkg.delivery_date),
                },
                "attachments": attachments,
                "project_name": _s(pkg.project.temp_name) if pkg.project else "",
                "created_by": _s(pkg.created_by),
                "created_at": _sd(pkg.created_at),
            }, ensure_ascii=False)
        finally:
            session.close()
