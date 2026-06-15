"""자재 발주 (MaterialOrder) Tools — 현장 자재 단위 발주 관리"""
import datetime
import json
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


_ORDER_STATUSES = ('발주대기', '발주완료', '입고완료')


def register(mcp: FastMCP):

    @mcp.tool()
    def get_material_orders(
        status: Optional[str] = None,
        project_search: Optional[str] = None,
        material_search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """현장별 자재발주 목록 — 계약 품목 단위로 발주/입고 진행상태 추적.
        ★ '자재 발주', '발주대기', '발주 안 한 자재', '현장별 자재현황' 등에 사용.
        ※ 발주서(PO) 단위 조회는 get_purchase_orders, 통합 입고진행은 get_incoming_overview.

        status: 발주대기 / 발주완료 / 입고완료 / all
        project_search: 현장명 부분 검색
        material_search: 자재명/모델명 부분 검색
        limit: 최대 건수 (기본 50)
        """
        from modules.models import MaterialOrder, Project, Contract
        session = get_session()
        try:
            target_status = status or 'all'
            if target_status != 'all' and target_status not in _ORDER_STATUSES:
                return json.dumps({
                    "error": f"status는 {'/'.join(_ORDER_STATUSES)}/all 중 하나여야 합니다.",
                }, ensure_ascii=False)

            q = (
                session.query(MaterialOrder)
                .options(
                    joinedload(MaterialOrder.project),
                    joinedload(MaterialOrder.contract),
                    joinedload(MaterialOrder.purchase_order),
                )
            )

            if target_status != 'all':
                q = q.filter(MaterialOrder.order_status == target_status)

            if project_search:
                like = f"%{project_search}%"
                q = q.join(Project, Project.id == MaterialOrder.project_id) \
                     .outerjoin(Contract, Contract.id == MaterialOrder.contract_id) \
                     .filter(or_(
                         Project.temp_name.ilike(like),
                         Contract.contract_name.ilike(like),
                     ))

            if material_search:
                like = f"%{material_search}%"
                q = q.filter(or_(
                    MaterialOrder.material_name.ilike(like),
                    MaterialOrder.item_model_name.ilike(like),
                ))

            # 통계 (전체)
            stats_rows = session.query(
                MaterialOrder.order_status,
                func.count(MaterialOrder.id),
            ).group_by(MaterialOrder.order_status).all()
            stats = {s: 0 for s in _ORDER_STATUSES}
            for st, cnt in stats_rows:
                stats[_s(st, '발주대기')] = cnt

            orders = q.order_by(MaterialOrder.order_date.desc().nullslast(),
                                MaterialOrder.id.desc()).limit(limit).all()

            items = []
            for mo in orders:
                items.append({
                    "id": mo.id,
                    "project_name": mo.project.temp_name if mo.project else "",
                    "contract_name": mo.contract.contract_name if mo.contract else "",
                    "item_category": _s(mo.item_category),
                    "item_model_name": _s(mo.item_model_name),
                    "material_name": _s(mo.material_name),
                    "quantity": int(mo.quantity or 0),
                    "order_status": _s(mo.order_status),
                    "order_date": _sd(mo.order_date),
                    "expected_in_date": _sd(mo.expected_in_date),
                    "in_confirmed": bool(mo.in_confirmed),
                    "is_outsourcing": bool(mo.is_outsourcing),
                    "outsourcing_status": _s(mo.outsourcing_status),
                    "po_no": mo.purchase_order.po_no if mo.purchase_order else "",
                })

            return json.dumps({
                "stats": stats,
                "filter_applied": target_status,
                "filtered_count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_material_orders_by_project(project_id: int) -> str:
        """특정 현장의 자재발주 전체 목록 + 발주율.
        ★ 'OO현장 자재 어디까지 발주됐어', '현장 자재 진행률' 등에 사용.
        """
        from modules.models import MaterialOrder, Project
        session = get_session()
        try:
            project = session.get(Project, project_id)
            if not project:
                return json.dumps({"error": "현장을 찾을 수 없습니다."}, ensure_ascii=False)

            orders = (
                session.query(MaterialOrder)
                .filter(MaterialOrder.project_id == project_id)
                .options(joinedload(MaterialOrder.purchase_order))
                .order_by(MaterialOrder.id.asc())
                .all()
            )

            total = len(orders)
            ordered = sum(1 for mo in orders if mo.order_status in ('발주완료', '입고완료'))
            received = sum(1 for mo in orders if mo.order_status == '입고완료')
            order_pct = round(ordered / total * 100) if total else 0
            recv_pct = round(received / total * 100) if total else 0

            items = [{
                "id": mo.id,
                "item_category": _s(mo.item_category),
                "material_name": _s(mo.material_name),
                "item_model_name": _s(mo.item_model_name),
                "quantity": int(mo.quantity or 0),
                "order_status": _s(mo.order_status),
                "order_date": _sd(mo.order_date),
                "expected_in_date": _sd(mo.expected_in_date),
                "po_no": mo.purchase_order.po_no if mo.purchase_order else "",
            } for mo in orders]

            return json.dumps({
                "project_id": project.id,
                "project_name": _s(project.temp_name),
                "total_items": total,
                "ordered_count": ordered,
                "received_count": received,
                "order_percent": order_pct,
                "receive_percent": recv_pct,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
