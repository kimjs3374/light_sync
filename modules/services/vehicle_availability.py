"""차량 예약 충돌 검사 — 출장 등록/수정 시 같은 차량 기간겹침 감지.

같은 회사차량이 겹치는 기간에 두 출장에 배정되면 충돌이다. 복귀일 미정이면
출발일 다음날 00:00 을 묵시 복귀로 본다(effective_status 와 동일 규칙).

겹침 판정(반열림 구간, 맞닿는 경계는 충돌 아님):
    기존.출발 < 신규.복귀(묵시)  AND  신규.출발 < 기존.복귀(묵시)
"""
from __future__ import annotations

import datetime
from typing import Optional


def implicit_end(departure: datetime.datetime,
                 return_dt: Optional[datetime.datetime]) -> datetime.datetime:
    """복귀 미정이면 출발일 다음날 00:00."""
    if return_dt is not None:
        return return_dt
    return datetime.datetime(departure.year, departure.month, departure.day) \
        + datetime.timedelta(days=1)


def vehicle_conflicts(session, vehicle: str,
                      departure: datetime.datetime,
                      return_dt: Optional[datetime.datetime],
                      exclude_trip_id: Optional[int] = None) -> list:
    """해당 차량이 [departure, return] 기간에 이미 배정된 출장 목록(라벨 dict).

    회사차량이 아니거나(무한공급) 출발일이 없으면 빈 목록.
    """
    from modules.models.entities import BusinessTrip
    from modules.services.business_trip_status import _impl_expr
    from modules.services.vehicle_log_trip_link import is_company_vehicle
    from sqlalchemy.orm import joinedload

    if not vehicle or departure is None:
        return []
    if not is_company_vehicle(session, vehicle):
        return []  # 대중교통/자차 등은 충돌 개념 없음

    new_end = implicit_end(departure, return_dt)
    impl = _impl_expr()
    q = (session.query(BusinessTrip)
         .options(joinedload(BusinessTrip.members))
         .filter(BusinessTrip.vehicle == vehicle,
                 BusinessTrip.status != '취소',
                 BusinessTrip.departure_date != None,  # noqa: E711
                 BusinessTrip.departure_date < new_end,
                 departure < impl))
    if exclude_trip_id:
        q = q.filter(BusinessTrip.id != exclude_trip_id)

    out = []
    for t in q.order_by(BusinessTrip.departure_date).all():
        dep = t.departure_date
        d = dep.date() if isinstance(dep, datetime.datetime) else dep
        out.append({
            "trip_id": t.id,
            "destination": t.destination,
            "departure": d.isoformat() if d else None,
            "members": t.member_names,
            "label": f"{d.isoformat() if d else '?'} {t.destination}"
                     + (f" ({t.member_names})" if t.member_names else ""),
        })
    return out


def vehicle_availability(session,
                         departure: datetime.datetime,
                         return_dt: Optional[datetime.datetime],
                         exclude_trip_id: Optional[int] = None) -> dict:
    """회사차량별 예약 가능 여부. {vehicle: {"available": bool, "conflicts": [...]}}"""
    from modules.services.vehicle_log_trip_link import company_vehicles
    result = {}
    for v in company_vehicles(session):
        conflicts = vehicle_conflicts(session, v, departure, return_dt, exclude_trip_id)
        result[v] = {"available": not conflicts, "conflicts": conflicts}
    return result
