"""출장관리 Tools"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_business_trips(
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """출장 목록 조회. 출장일정, 참가자, 차량정보를 반환합니다.
        ★ '출장 일정', '누가 출장 가', '이번주 출장' 등의 질문에 사용.
        status: 예정 / 진행중 / 완료 / 취소
        search: 제목 또는 목적지 검색
        """
        from modules.models.misc_entities import BusinessTrip
        session = get_session()
        try:
            q = session.query(BusinessTrip)
            if status:
                q = q.filter(BusinessTrip.status == status)
            if search:
                q = q.filter(
                    BusinessTrip.title.ilike(f"%{search}%")
                    | BusinessTrip.destination.ilike(f"%{search}%")
                )
            trips = q.order_by(BusinessTrip.departure_date.desc()).limit(limit).all()

            result = []
            for t in trips:
                result.append({
                    "id": t.id,
                    "title": _s(t.title),
                    "destination": _s(t.destination),
                    "status": _s(t.status),
                    "vehicle": _s(t.vehicle),
                    "departure_date": _sd(t.departure_date),
                    "return_date": _sd(t.return_date),
                    "members": t.member_names,
                    "created_by": _s(t.creator.full_name) if t.creator else "",
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_business_trip_detail(trip_id: int) -> str:
        """출장 상세 조회. 참가자 목록, 목적, 차량, 비고를 포함합니다.
        ★ 특정 출장의 상세 내역 확인 시 사용.
        """
        from modules.models.misc_entities import BusinessTrip
        session = get_session()
        try:
            trip = session.get(BusinessTrip, trip_id)
            if not trip:
                return "출장 정보를 찾을 수 없습니다."

            members = [{
                "name": _s(m.user_name),
                "position": _s(m.position),
                "department": _s(m.department),
            } for m in trip.members]

            return json.dumps({
                "id": trip.id,
                "title": _s(trip.title),
                "destination": _s(trip.destination),
                "purpose": _s(trip.purpose),
                "status": _s(trip.status),
                "vehicle": _s(trip.vehicle),
                "departure_date": _sd(trip.departure_date),
                "return_date": _sd(trip.return_date),
                "note": _s(trip.note),
                "members": members,
                "member_count": len(members),
                "created_by": _s(trip.creator.full_name) if trip.creator else "",
                "created_at": _sd(trip.created_at),
            }, ensure_ascii=False)
        finally:
            session.close()
