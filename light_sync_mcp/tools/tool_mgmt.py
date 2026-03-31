"""공구관리 Tools"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_tools_list(
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """공구(전동공구) 목록 조회. 보유현황, 불출상태를 반환합니다.
        ★ '공구 목록', '전동공구 뭐 있어', '사용중인 공구' 등의 질문에 사용.
        status: 보관중 / 사용중 / 점검중 / 폐기
        search: 공구명 검색
        """
        from modules.models.tool_entities import Tool
        session = get_session()
        try:
            q = session.query(Tool)
            if status:
                q = q.filter(Tool.status == status)
            if search:
                q = q.filter(Tool.tool_name.ilike(f"%{search}%"))
            tools = q.order_by(Tool.tool_name).limit(limit).all()

            result = []
            for t in tools:
                latest_checkout = t.checkouts[0] if t.checkouts else None
                result.append({
                    "id": t.id,
                    "tool_name": _s(t.tool_name),
                    "category": _s(t.category),
                    "team": _s(t.team),
                    "total_qty": t.total_qty or 0,
                    "available_qty": t.available_qty or 0,
                    "current_location": _s(t.current_location),
                    "status": _s(t.status),
                    "note": _s(t.note),
                    "last_checkout": {
                        "user": _s(latest_checkout.checkout_user_name),
                        "location": _s(latest_checkout.location),
                        "date": _sd(latest_checkout.checkout_at),
                        "status": _s(latest_checkout.status),
                    } if latest_checkout else None,
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
