"""FR-18: 오버뷰/진행률 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_project_progress(project_id: Optional[int] = None, limit: int = 30) -> str:
        """프로젝트 진행률 조회. 설계/자재/생산/납품 단계별 완료율을 반환합니다.
        project_id 생략 시 진행중 전체 현장 목록.
        """
        from modules.models.entities import Project, Contract, ContractItem, Delivery
        from sqlalchemy import func
        session = get_session()
        try:
            if project_id:
                projects = [session.get(Project, project_id)]
                if not projects[0]:
                    return "현장을 찾을 수 없습니다."
            else:
                projects = session.query(Project).filter(
                    Project.status.notin_(["납품완료", "완료", "취소"])
                ).order_by(Project.created_at.desc()).limit(limit).all()

            result = []
            for p in projects:
                total_items = session.query(func.count(ContractItem.id)).join(Contract).filter(
                    Contract.project_id == p.id
                ).scalar() or 0

                completed_sales = session.query(func.count(ContractItem.id)).join(Contract).filter(
                    Contract.project_id == p.id,
                    ContractItem.status_sales == "완료",
                ).scalar() or 0

                completed_prod = session.query(func.count(ContractItem.id)).join(Contract).filter(
                    Contract.project_id == p.id,
                    ContractItem.status_prod == "완료",
                ).scalar() or 0

                delivery = session.query(Delivery).filter(
                    Delivery.project_id == p.id
                ).first()
                delivery_progress = 0
                if delivery and _sn(delivery.planned_total_qty) > 0:
                    delivery_progress = round(
                        _sn(delivery.delivered_total_qty) / _sn(delivery.planned_total_qty) * 100, 1
                    )

                result.append({
                    "project_id": p.id,
                    "project_name": _s(p.temp_name),
                    "status": _s(p.status),
                    "total_items": total_items,
                    "sales_progress": round(completed_sales / total_items * 100, 1) if total_items else 0,
                    "production_progress": round(completed_prod / total_items * 100, 1) if total_items else 0,
                    "delivery_progress": delivery_progress,
                })

            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_dashboard_summary() -> str:
        """대시보드 KPI 종합 요약. 계약/납품/생산/재고/미수금 현황을 한눈에 반환합니다.
        ★ '현황 요약', '오늘 어때', '전체 현황' 등의 질문에 사용.
        """
        import datetime
        from modules.models.entities import Project, Contract, ContractItem, Delivery, PurchaseOrder
        from modules.models.inventory_entities import Item
        from modules.models.receiving_entities import Receiving
        from modules.models.misc_entities import BusinessTrip
        from modules.contract_filters import active_contract_filter
        from sqlalchemy import func
        session = get_session()
        try:
            today = datetime.date.today()

            # 진행중 현장
            active_projects = session.query(func.count(Project.id)).filter(
                Project.status.in_(["계약", "생산", "납품중"])
            ).scalar() or 0

            # 설계/영업 현장
            design_projects = session.query(func.count(Project.id)).filter(
                Project.status == "설계/영업"
            ).scalar() or 0

            # 완료 현장
            done_projects = session.query(func.count(Project.id)).filter(
                Project.status == "납품완료"
            ).scalar() or 0

            # 재고 부족
            low_stock = session.query(func.count(Item.id)).filter(
                Item.is_active == True,
                Item.safety_stock > 0,
                Item.stock_qty < Item.safety_stock,
            ).scalar() or 0

            # 입고 대기
            pending_receiving = session.query(func.count(Receiving.id)).filter(
                Receiving.status == "검수대기"
            ).scalar() or 0

            # 발주 진행중
            active_po = session.query(func.count(PurchaseOrder.id)).filter(
                PurchaseOrder.status.in_(["발송완료", "입고대기"])
            ).scalar() or 0

            # 출장 예정/진행중
            active_trips = session.query(func.count(BusinessTrip.id)).filter(
                BusinessTrip.status.in_(["예정", "진행중"])
            ).scalar() or 0

            return json.dumps({
                "date": today.isoformat(),
                "projects": {
                    "active": active_projects,
                    "design": design_projects,
                    "completed": done_projects,
                },
                "inventory": {
                    "low_stock_count": low_stock,
                },
                "procurement": {
                    "pending_receiving": pending_receiving,
                    "active_po": active_po,
                },
                "business_trips": {
                    "active": active_trips,
                },
                "summary": f"진행현장 {active_projects}건, 설계/영업 {design_projects}건, "
                           f"재고부족 {low_stock}건, 입고대기 {pending_receiving}건",
            }, ensure_ascii=False)
        finally:
            session.close()
