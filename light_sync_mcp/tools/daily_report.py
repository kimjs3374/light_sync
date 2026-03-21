"""FR-16: 일일업무보고 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_daily_reports(
        department: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """일일업무보고 목록 조회. 부서별, 날짜별 필터링.
        department: 영업부, 생산부, 관리부
        date_from / date_to: YYYY-MM-DD 형식
        """
        from modules.models.entities import DailyReport
        session = get_session()
        try:
            q = session.query(DailyReport)
            if department:
                q = q.filter(DailyReport.department.ilike(f"%{department}%"))
            if date_from:
                q = q.filter(DailyReport.report_date >= date_from)
            if date_to:
                q = q.filter(DailyReport.report_date <= date_to)
            reports = q.order_by(DailyReport.report_date.desc()).limit(limit).all()

            return json.dumps([{
                "id": r.id,
                "report_date": _sd(r.report_date),
                "department": _s(r.department),
                "reporter_name": _s(r.reporter_name),
                "headcount_total": r.headcount_total,
                "headcount_present": r.headcount_present,
            } for r in reports], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_daily_report_detail(report_id: int) -> str:
        """일일업무보고 상세 조회. 자동 수집 항목과 수기 입력 항목을 포함합니다."""
        from modules.models.entities import DailyReport
        session = get_session()
        try:
            r = session.get(DailyReport, report_id)
            if not r:
                return "보고서를 찾을 수 없습니다."

            items = json.loads(r.items_json) if r.items_json else []
            auto_items = json.loads(r.auto_items_json) if r.auto_items_json else []

            return json.dumps({
                "id": r.id,
                "report_date": _sd(r.report_date),
                "department": _s(r.department),
                "reporter_name": _s(r.reporter_name),
                "headcount_total": r.headcount_total,
                "headcount_present": r.headcount_present,
                "headcount_absence_info": _s(r.headcount_absence_info),
                "auto_items": auto_items,
                "manual_items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
