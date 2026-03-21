"""FR-17: 알림 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_notifications(
        user_id: Optional[int] = None,
        is_read: Optional[bool] = None,
        limit: int = 30,
    ) -> str:
        """사용자 알림 목록 조회. 읽음/안읽음 필터링 가능.
        user_id: 사용자 ID (생략 시 전체)
        """
        from modules.models.entities import Notification
        session = get_session()
        try:
            q = session.query(Notification)
            if user_id:
                q = q.filter(Notification.user_id == user_id)
            if is_read is not None:
                q = q.filter(Notification.is_read == is_read)
            notis = q.order_by(Notification.created_at.desc()).limit(limit).all()

            return json.dumps([{
                "id": n.id,
                "title": _s(n.title),
                "message": _s(n.message),
                "noti_type": _s(n.noti_type),
                "link": _s(n.link),
                "is_read": n.is_read,
                "created_at": _sd(n.created_at),
            } for n in notis], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_unread_notification_count(user_id: int) -> str:
        """사용자 미읽은 알림 수 조회."""
        from modules.models.entities import Notification
        from sqlalchemy import func
        session = get_session()
        try:
            count = session.query(func.count(Notification.id)).filter(
                Notification.user_id == user_id,
                Notification.is_read == False,
            ).scalar() or 0
            return json.dumps({"user_id": user_id, "unread_count": count}, ensure_ascii=False)
        finally:
            session.close()
