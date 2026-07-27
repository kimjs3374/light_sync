"""FR-15: 계약 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_contracts(
        project_id: Optional[int] = None,
        payment_status: Optional[str] = None,
        limit: int = 50,
        include_done: bool = False,
    ) -> str:
        """계약 목록 조회. 현장별, 수금 상태별 필터링.
        payment_status: 미수금, 부분입금, 입금완료

        ★ 기본은 **수금 완료된 계약을 제외**합니다 (입금완료/청구완료/변경완료/취소 +
          예외처리분). 전체 계약의 96%(1,250/1,302)가 입금완료라 제외하지 않으면
          진행중 계약이 limit 에 밀립니다.
          payment_status 를 명시하거나 include_done=True 를 붙이면 전체를 봅니다.
        """
        from modules.models.entities import Contract, Project
        from modules.contract_filters import DONE_STATUSES
        session = get_session()
        try:
            q = session.query(Contract)
            if project_id:
                q = q.filter(Contract.project_id == project_id)
            if payment_status:
                q = q.filter(Contract.payment_status == payment_status)
            total = q.count()
            # payment_status 를 명시했으면 사용자가 범위를 정한 것 — 덧씌우지 않는다
            if not include_done and not payment_status:
                q = q.filter(
                    Contract.payment_status.notin_(DONE_STATUSES),
                    Contract.is_excluded.isnot(True),
                )
            contracts = q.order_by(Contract.contract_date.desc()).limit(limit).all()

            result = []
            for c in contracts:
                proj = session.get(Project, c.project_id) if c.project_id else None
                result.append({
                    "id": c.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "contract_name": _s(c.contract_name),
                    "item_group": _s(c.item_group),
                    "contract_date": _sd(c.contract_date),
                    "delivery_due_date": _sd(c.delivery_due_date),
                    "g2b_contract_no": _s(c.g2b_contract_no),
                    "payment_status": _s(c.payment_status),
                    "is_urgent_prod": c.is_urgent_prod,
                })
            scoped = include_done or bool(payment_status)
            return json.dumps({
                "summary": {
                    "total_matched": total,
                    "returned": len(result),
                    "done_excluded": not scoped,
                    "note": (
                        f"검색조건 전체 {total}건 중 {len(result)}건 반환"
                        + ("" if scoped else " (수금완료 계약 제외 — 전체를 보려면 include_done=True)")
                    ),
                },
                "contracts": result,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_contract_detail(contract_id: int) -> str:
        """계약 상세 조회. 계약품목 목록을 포함합니다."""
        from modules.models.entities import Contract, ContractItem, Project
        session = get_session()
        try:
            c = session.get(Contract, contract_id)
            if not c:
                return "계약을 찾을 수 없습니다."

            proj = session.get(Project, c.project_id) if c.project_id else None
            items = session.query(ContractItem).filter(
                ContractItem.contract_id == contract_id
            ).all()

            return json.dumps({
                "id": c.id,
                "project_name": _s(proj.temp_name) if proj else "",
                "contract_name": _s(c.contract_name),
                "item_group": _s(c.item_group),
                "contract_date": _sd(c.contract_date),
                "delivery_due_date": _sd(c.delivery_due_date),
                "desired_delivery_date": _sd(c.desired_delivery_date),
                "g2b_contract_no": _s(c.g2b_contract_no),
                "payment_status": _s(c.payment_status),
                "is_prof_inspection": c.is_prof_inspection,
                "is_urgent_prod": c.is_urgent_prod,
                "items": [{
                    "category": _s(it.category),
                    "model_name": _s(it.model_name),
                    "quantity": _sn(it.quantity),
                    "status_sales": _s(it.status_sales),
                    "status_admin": _s(it.status_admin),
                    "status_prod": _s(it.status_prod),
                } for it in items],
            }, ensure_ascii=False)
        finally:
            session.close()
