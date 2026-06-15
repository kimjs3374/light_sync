"""부서별 주간 리포트 KPI Tools (영업/생산/관리)"""
import datetime
import json
from typing import Optional

from sqlalchemy import func
from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _sd


_DEPT_LABELS = {
    'sales': '영업부',
    'production': '생산부',
    'management': '관리부',
}


def _parse_week(start: Optional[str], end: Optional[str]):
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end = week_start + datetime.timedelta(days=4)
    if start:
        try:
            week_start = datetime.date.fromisoformat(start)
        except ValueError:
            pass
    if end:
        try:
            week_end = datetime.date.fromisoformat(end)
        except ValueError:
            pass
    return today, week_start, week_end


def register(mcp: FastMCP):

    @mcp.tool()
    def get_dept_weekly_report(
        dept: str,
        week_start: Optional[str] = None,
        week_end: Optional[str] = None,
    ) -> str:
        """부서별 주간보고서 KPI 요약.
        ★ '영업부 주간보고', '생산부 이번주 어땠어', '관리부 주간 KPI', '부서별 주간 현황' 등에 사용.

        dept: sales(영업) / production(생산) / management(관리) — 한글 '영업부/생산부/관리부'도 가능
        week_start, week_end: YYYY-MM-DD (생략 시 이번주 월~금)

        반환: 부서 KPI + 주요 카운트
        - 영업: 진행중 설계, 신규 등록, 계약 전환, 긴급/지연 카운트
        - 생산: 생산중 품목, 납품준비/완료, AS접수
        - 관리: 발주 건수, 입고 건수, 검수대기, 발주총액
        """
        from modules.models import (
            Project, Contract, ContractItem,
            ProductionProcess, Delivery, DeliverySplit,
            WarrantyCase, MaterialOrder, PurchaseOrder, Receiving,
        )

        # 부서 키 정규화
        dept_map = {'영업부': 'sales', '생산부': 'production',
                    '관리부': 'management', '경영관리부': 'management'}
        dept_key = dept_map.get(dept, dept)
        if dept_key not in _DEPT_LABELS:
            return json.dumps({
                "error": "dept는 sales/production/management 중 하나입니다.",
            }, ensure_ascii=False)

        session = get_session()
        try:
            today, ws, we = _parse_week(week_start, week_end)
            start_dt = datetime.datetime.combine(ws, datetime.time.min)
            end_dt = datetime.datetime.combine(we, datetime.time.max)

            result = {
                "dept": dept_key,
                "dept_label": _DEPT_LABELS[dept_key],
                "week_start": _sd(ws),
                "week_end": _sd(we),
                "today": _sd(today),
            }

            if dept_key == 'sales':
                active = session.query(func.count(Project.id)).filter(
                    Project.is_contracted.is_(False)
                ).scalar() or 0

                new_count = session.query(func.count(Project.id)).filter(
                    Project.created_at >= start_dt,
                    Project.created_at <= end_dt,
                ).scalar() or 0

                converted_count = session.query(func.count(Project.id)).filter(
                    Project.is_contracted.is_(True),
                    Project.contract_date >= ws,
                    Project.contract_date <= we,
                ).scalar() or 0

                urgent_count = session.query(func.count(Project.id)).filter(
                    Project.is_contracted.is_(False),
                    Project.is_urgent.is_(True),
                ).scalar() or 0

                overdue_count = session.query(func.count(Project.id)).filter(
                    Project.is_contracted.is_(False),
                    Project.expected_contract_date.isnot(None),
                    Project.expected_contract_date < today,
                ).scalar() or 0

                result["stats"] = {
                    "total_active": active,
                    "new_count": new_count,
                    "converted_count": converted_count,
                    "urgent_count": urgent_count,
                    "overdue_count": overdue_count,
                }

            elif dept_key == 'production':
                producing = session.query(func.count(ContractItem.id)).filter(
                    ContractItem.status_prod.in_(['생산중', '조립중', '자재입고완료'])
                ).scalar() or 0

                delivery_ready = session.query(func.count(Delivery.id)).filter(
                    Delivery.delivery_status == '납품준비'
                ).scalar() or 0

                delivery_done = session.query(func.count(DeliverySplit.id)).filter(
                    DeliverySplit.delivered_done_at >= start_dt,
                    DeliverySplit.delivered_done_at <= end_dt,
                ).scalar() or 0

                as_count = session.query(func.count(WarrantyCase.id)).filter(
                    WarrantyCase.reported_date >= ws,
                    WarrantyCase.reported_date <= we,
                ).scalar() or 0

                result["stats"] = {
                    "producing": producing,
                    "delivery_ready": delivery_ready,
                    "delivery_done": delivery_done,
                    "as_received": as_count,
                }

            else:  # management
                order_count = session.query(func.count(MaterialOrder.id)).filter(
                    MaterialOrder.order_date >= ws,
                    MaterialOrder.order_date <= we,
                ).scalar() or 0

                receiving_count = session.query(func.count(Receiving.id)).filter(
                    Receiving.rcv_date >= ws,
                    Receiving.rcv_date <= we,
                ).scalar() or 0

                inspect_pending = session.query(func.count(Receiving.id)).filter(
                    Receiving.status == '검수대기'
                ).scalar() or 0

                po_total = session.query(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).filter(
                    PurchaseOrder.po_date >= ws,
                    PurchaseOrder.po_date <= we,
                    PurchaseOrder.status != '취소',
                ).scalar() or 0

                result["stats"] = {
                    "order_count": order_count,
                    "receiving_count": receiving_count,
                    "inspect_pending": inspect_pending,
                    "po_total_won": int(po_total),
                }

            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
