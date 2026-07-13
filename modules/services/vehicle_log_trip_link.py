"""출장관리 ↔ 운행일지 연동 — 단일 소스.

출장(BusinessTrip)의 대부분 필드가 운행일지(VehicleLog)와 겹친다(차량·목적지·목적·날짜·인원).
운행일지가 필요로 하는데 출장이 못 주는 값은 계기판/거리뿐이다. 그래서 연동은
"출장에서 프리필하고 계기판만 입력받는다".

세 표면이 이 모듈을 공유한다.
  - PC 웹: 운행일지 작성 모달에서 출장 선택 → 프리필 (routes/vehicle_log.py)
  - MCP 챗봇: write_preview_vehicle_log(from_trip_id=...) (light_sync_mcp)
  - (역방향 동일) 출장 상세의 '운행일지 작성' 버튼도 같은 프리필로 귀결

운행일지는 회사차량만 기록하므로(대중교통/자차이용 등 제외), 출장 차량이
회사차량이 아니면 연동 대상이 아니다(None 반환).
"""
from __future__ import annotations

import datetime
import json
from typing import Optional

# 운행일지 기록 대상에서 제외 (routes/vehicle_log.py:EXCLUDED_VEHICLES 와 동일)
EXCLUDED_VEHICLES = {'개인차량', '대중교통', '기타', '도보', ''}
VEHICLE_SETTING_KEY = 'business_trip_vehicles'
DEFAULT_ORIGIN = '본사'  # 본사→현장→본사 흐름. 프리필 기본값이며 수정 가능.


def _vehicle_presets(session) -> list:
    from modules.models.entities import DashboardSetting
    row = session.query(DashboardSetting).filter_by(setting_key=VEHICLE_SETTING_KEY).first()
    if row and row.setting_value:
        try:
            presets = json.loads(row.setting_value)
            if isinstance(presets, list) and presets:
                return presets
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def company_vehicles(session) -> list:
    """운행일지 기록 대상 회사차량 목록."""
    return [v for v in _vehicle_presets(session) if v not in EXCLUDED_VEHICLES]


def is_company_vehicle(session, vehicle: Optional[str]) -> bool:
    return bool(vehicle) and vehicle in company_vehicles(session)


def _pick_driver(trip, driver_user_id: Optional[int]):
    """운전자 멤버 선택. 지정 없으면 기안자(멤버인 경우) → 첫 멤버 순."""
    members = list(trip.members or [])
    if not members:
        return None
    if driver_user_id is not None:
        for m in members:
            if m.user_id == driver_user_id:
                return m
    for m in members:  # 기안자가 참가자면 우선
        if m.user_id and m.user_id == trip.created_by:
            return m
    return members[0]


def trip_to_log_defaults(session, trip, driver_user_id: Optional[int] = None) -> Optional[dict]:
    """출장 1건 → 운행일지 프리필 dict. 회사차량이 아니면 None.

    운전자 신원(driver_*)은 챗봇 등 운전자 지정이 필요한 경우에만 쓴다.
    PC 웹은 로그인 사용자가 운전자이므로 driver_* 를 무시한다.
    """
    if not is_company_vehicle(session, trip.vehicle):
        return None

    dep = trip.departure_date
    use_date = dep.date() if isinstance(dep, datetime.datetime) else dep
    driver = _pick_driver(trip, driver_user_id)

    return {
        "trip_id": trip.id,
        "trip_title": trip.title,
        "vehicle": trip.vehicle,
        "origin": DEFAULT_ORIGIN,          # 수정 가능
        "destination": trip.destination or "",
        "purpose": trip.purpose or "",
        "use_date": use_date.isoformat() if use_date else None,
        # 운전자 후보 (챗봇/모바일용). PC 웹은 미사용.
        "driver_name": driver.user_name if driver else None,
        "driver_user_id": driver.user_id if driver else None,
        "driver_department": driver.department if driver else None,
        "driver_position": driver.position if driver else None,
        "member_names": trip.member_names,
    }


def recent_trips_for_vehicle_log(session, user_id=None, user_name=None,
                                 limit: int = 15) -> list:
    """운행일지 작성 모달의 '출장 불러오기' 후보 목록.

    회사차량 출장만, 최근 출발순. user_id/user_name 이 주어지면 **그 사람이
    출장자(참가자)로 등록된 출장만** 반환한다(PC 작성자=운전자 본인 기준).
    """
    from modules.models.entities import BusinessTrip, BusinessTripMember
    from sqlalchemy.orm import joinedload
    from sqlalchemy import or_

    allowed = set(company_vehicles(session))
    if not allowed:
        return []
    q = (session.query(BusinessTrip)
         .options(joinedload(BusinessTrip.members))
         .filter(BusinessTrip.vehicle.in_(allowed),
                 BusinessTrip.status != '취소'))
    if user_id or user_name:
        conds = []
        if user_id:
            conds.append(BusinessTripMember.user_id == user_id)
        if user_name:
            conds.append(BusinessTripMember.user_name == user_name)
        q = q.filter(BusinessTrip.members.any(or_(*conds)))
    trips = (q.order_by(BusinessTrip.departure_date.desc())
             .limit(limit).all())
    out = []
    for t in trips:
        dep = t.departure_date
        d = dep.date() if isinstance(dep, datetime.datetime) else dep
        out.append({
            "trip_id": t.id,
            "label": f"{d.isoformat() if d else '?'} · {t.destination} · {t.vehicle}"
                     + (f" ({t.member_names})" if t.member_names else ""),
        })
    return out
