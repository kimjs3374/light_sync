"""운행일지 기록 — 채팅 confirm 경로의 단일 진입점.

두 곳에서 호출한다.
  - routes/mattermost_action.py : Mattermost 확인 버튼 콜백
  - light_sync_mcp/tools/write_ops.py : confirm_vehicle_log MCP 도구 (카카오워크 봇)

주행 전 계기판(odometer_start)은 같은 차량의 직전 기록에서 채운다.
preview 시점이 아니라 이 함수가 불릴 때 재조회한다(preview~confirm 사이 등록분 반영).
"""
from __future__ import annotations

import datetime
from typing import Optional

from modules.models.entities import VehicleLog


def get_last_odometer(session, vehicle: str, before_date) -> Optional[int]:
    """직전 동일 차량 기록의 주행 후 km.

    routes/vehicle_log.py 의 동명 헬퍼와 같은 규칙(운행일 <= 기준일, 최신순).
    odometer_end=0 은 계기판 미기재분이므로 기준으로 삼지 않는다.
    """
    last = (session.query(VehicleLog)
            .filter(VehicleLog.vehicle == vehicle,
                    VehicleLog.use_date <= before_date,
                    VehicleLog.odometer_end > 0)
            .order_by(VehicleLog.use_date.desc(), VehicleLog.id.desc())
            .first())
    return last.odometer_end if last else None


def write_vehicle_log(session, payload: dict) -> dict:
    """PendingWriteSession payload → VehicleLog 1건 추가.

    commit 은 호출자가 한다. 반환: {"ok": bool, "label"/"detail" 또는 "msg"}
    """
    use_date = datetime.date.fromisoformat(payload["use_date"])
    vehicle = payload["vehicle"]
    distance_km = int(payload["distance_km"])
    # origin 은 preview 에서 필수 수집. 구버전 대기 세션 대비 방어값(NOT NULL 컬럼).
    origin = payload.get("origin") or "출발지 미기재"

    odometer_start = get_last_odometer(session, vehicle, use_date)
    explicit_end = payload.get("odometer_end")

    if explicit_end is not None:
        odometer_end = int(explicit_end)
        if odometer_start is not None:
            if odometer_end < odometer_start:
                return {"ok": False,
                        "msg": f"주행 후 계기판({odometer_end}km)이 직전 기록({odometer_start}km)보다 작습니다"}
            distance_km = odometer_end - odometer_start
    elif odometer_start is not None:
        odometer_end = odometer_start + distance_km
    else:
        odometer_end = 0  # 직전 기록 없음 — 계기판 미기재 (NOT NULL 컬럼)

    session.add(VehicleLog(
        use_date=use_date,
        vehicle=vehicle,
        user_name=payload["driver_name"],
        user_id=payload.get("user_id"),
        user_department=payload.get("user_department"),
        user_position=payload.get("user_position"),
        origin=origin,
        destination=payload["destination"],
        distance_km=distance_km,
        purpose=payload["purpose"],
        odometer_start=odometer_start,
        odometer_end=odometer_end,
    ))

    odo_detail = (f"\n- 계기판 {odometer_start} → {odometer_end}km"
                  if odometer_start is not None else "\n- 계기판 미기재")
    return {"ok": True, "label": "운행일지 등록됨",
            "detail": (f"- {payload['driver_name']} / {vehicle}\n"
                       f"- {origin} → {payload['destination']} "
                       f"{distance_km}km{odo_detail}")}
