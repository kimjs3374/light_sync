"""FR-30: 시스템 활동 이력 도메인 Tools (1개)

activity_logs 테이블 검색 — "5/14 누가 뭐 변경했어?" / "탄금축구장 작업 이력"
같은 질문 답변 가능. DB 데이터: 약 1,100건.
"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_activity_logs(
        user_name: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        project_id: Optional[int] = None,
        ref_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        query: Optional[str] = None,
        months_back: int = 12,
        include_old: bool = False,
        limit: int = 50,
    ) -> str:
        """시스템 활동 이력 검색. 누가/언제/어디서/무엇을 했는지.

        Args:
            user_name: 사용자 이름 (부분 일치, 예: '김정수')
            module: 모듈명 (영업, 자재, 발주, 생산, 납품, 매출수금, 협의관리 등)
            action: 액션 (create, update, delete, complete, register 등)
            project_id: 특정 현장만
            ref_type: 참조 타입 (Contract, ContractItem, Delivery, Warranty 등)
            date_from / date_to: YYYY-MM-DD
            query: summary/detail 부분 검색
            months_back: 최근 N개월 (기본 12, date_from/include_old 시 무시)
            include_old: True 면 전체 기간 (기본 False)
            limit: 최대 반환 (기본 50, 최신순)
        """
        from modules.models.entities import ActivityLog
        from sqlalchemy import or_
        import datetime
        session = get_session()
        try:
            q = session.query(ActivityLog)
            if user_name:
                q = q.filter(ActivityLog.user_name.ilike(f'%{user_name}%'))
            if module:
                q = q.filter(ActivityLog.module.ilike(f'%{module}%'))
            if action:
                q = q.filter(ActivityLog.action == action)
            if project_id:
                q = q.filter(ActivityLog.project_id == project_id)
            if ref_type:
                q = q.filter(ActivityLog.ref_type == ref_type)
            if date_from:
                q = q.filter(ActivityLog.created_at >= date_from)
            if date_to:
                q = q.filter(ActivityLog.created_at <= date_to)
            if query:
                q = q.filter(or_(
                    ActivityLog.summary.ilike(f'%{query}%'),
                    ActivityLog.detail.ilike(f'%{query}%'),
                    ActivityLog.ref_label.ilike(f'%{query}%'),
                ))
            # 기간 필터 — date_from/include_old 명시 안 됐을 때만
            cutoff = None
            if not date_from and not include_old and months_back > 0:
                cutoff = datetime.datetime.now() - datetime.timedelta(days=30 * months_back)
                q = q.filter(ActivityLog.created_at >= cutoff)
            logs = q.order_by(ActivityLog.created_at.desc().nullslast()).limit(limit).all()

            items = [{
                "id": lg.id,
                "created_at": _sd(lg.created_at),
                "user_name": _s(lg.user_name),
                "user_id": lg.user_id,
                "module": _s(lg.module),
                "action": _s(lg.action),
                "summary": _s(lg.summary),
                "detail": _s(lg.detail),
                "ref_type": _s(lg.ref_type),
                "ref_id": lg.ref_id,
                "ref_label": _s(lg.ref_label),
                "project_id": lg.project_id,
            } for lg in logs]
            return json.dumps({
                "count": len(items),
                "filter_cutoff_date": str(cutoff)[:10] if cutoff else None,
                "include_old": include_old,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
