"""FR-10: 납품 도메인 Tools (3개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_deliveries(
        status: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: int = 50,
        months_back: int = 24,
        include_old: bool = False,
        include_done: bool = False,
    ) -> str:
        """특정 현장의 납품 상세 현황 조회 (분할납품 포함).
        ★ '납품해야 되는 현장 몇 건?' 질문에는 이 Tool 대신 get_projects(status='계약') 사용.
        이 Tool은 특정 현장(project_id)의 납품 진행 상태를 볼 때 사용.
        status 예: 대기, 진행중, 완료

        기본은 **최근 24개월** 생성된 납품만 (옛날 waiting 1,000+건 데이터 오염 방지).

        ★ 기본은 **납품완료(done)를 제외**합니다. 특정 현장(project_id)을 볼 때는
          완료건도 함께 봐야 하므로 제외하지 않습니다.

        Args:
            months_back: 최근 N개월 기간 필터 (기본 24). project_id 명시 시 무시.
            include_old: True 시 전체 기간 (기본 False).
            include_done: True 시 납품완료 건까지 포함 (기본 False).
        """
        from modules.models.entities import Delivery, Project
        import datetime
        session = get_session()
        try:
            q = session.query(Delivery)
            if status:
                q = q.filter(Delivery.delivery_status.ilike(f"%{status}%"))
            if project_id:
                q = q.filter(Delivery.project_id == project_id)
            # status/project_id 를 명시했으면 범위를 이미 정한 것 — 덧씌우지 않는다
            elif not include_done and not status:
                q = q.filter(Delivery.delivery_status != "done")
            # 기간 필터 — project_id 명시 안 됐을 때만 적용 (특정 현장 조회는 옛날 거라도 봄)
            if not project_id and not include_old and months_back > 0:
                cutoff = datetime.datetime.now() - datetime.timedelta(days=30 * months_back)
                q = q.filter(Delivery.created_at >= cutoff)
            # 최신순 강제 (created_at 우선, 없으면 id)
            deliveries = q.order_by(Delivery.created_at.desc().nullslast(),
                                     Delivery.id.desc()).limit(limit).all()

            result = []
            for d in deliveries:
                proj = session.get(Project, d.project_id) if d.project_id else None
                result.append({
                    "id": d.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "delivery_status": _s(d.delivery_status),
                    "inspection_status": _s(d.inspection_status),
                    "inspection_date": _sd(d.inspection_date),
                    "planned_total_qty": _sn(d.planned_total_qty),
                    "delivered_total_qty": _sn(d.delivered_total_qty),
                    "contact_name": _s(d.contact_name),
                    "contact_phone": _s(d.contact_phone),
                    "note": _s(d.note),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_detail(delivery_id: int) -> str:
        """납품 상세 조회. 분할 납품 목록을 포함합니다."""
        from modules.models.entities import Delivery, DeliverySplit, Project
        session = get_session()
        try:
            d = session.get(Delivery, delivery_id)
            if not d:
                return "납품 정보를 찾을 수 없습니다."

            proj = session.get(Project, d.project_id) if d.project_id else None
            splits = session.query(DeliverySplit).filter(
                DeliverySplit.delivery_id == delivery_id
            ).order_by(DeliverySplit.split_no).all()

            return json.dumps({
                "id": d.id,
                "project_name": _s(proj.temp_name) if proj else "",
                "delivery_status": _s(d.delivery_status),
                "inspection_status": _s(d.inspection_status),
                "inspection_date": _sd(d.inspection_date),
                "inspection_note": _s(d.inspection_note),
                "planned_total_qty": _sn(d.planned_total_qty),
                "delivered_total_qty": _sn(d.delivered_total_qty),
                "contact_name": _s(d.contact_name),
                "contact_phone": _s(d.contact_phone),
                "note": _s(d.note),
                "splits": [{
                    "split_no": s.split_no,
                    "quantity": _sn(s.quantity),
                    "scheduled_date": _sd(s.scheduled_date),
                    "confirmed_date": _sd(s.confirmed_date),
                    "status": _s(s.status),
                    "note": _s(s.note),
                } for s in splits],
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_status_summary() -> str:
        """납품 레코드의 상태별 통계 (내부 관리용).
        ★ '납품해야 되는 현장 몇 건?' → 이 Tool 아님! get_projects(status='계약') 사용.
        이 Tool은 납품 레코드(delivery 테이블)의 상태별 집계를 반환합니다.
        """
        from modules.models.entities import Delivery
        from sqlalchemy import func
        session = get_session()
        try:
            rows = session.query(
                Delivery.delivery_status,
                func.count(Delivery.id).label("count"),
                func.sum(Delivery.planned_total_qty).label("planned"),
                func.sum(Delivery.delivered_total_qty).label("delivered"),
            ).group_by(Delivery.delivery_status).all()

            return json.dumps({
                "summary": [{
                    "status": _s(r.delivery_status) or "미설정",
                    "count": r.count,
                    "planned_qty": _sn(r.planned),
                    "delivered_qty": _sn(r.delivered),
                } for r in rows],
                "total_count": sum(r.count for r in rows),
            }, ensure_ascii=False)
        finally:
            session.close()
