"""업무용차량 운행기록부 Tools"""
import datetime
import json
from typing import Optional

from sqlalchemy import func
from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_vehicle_logs(
        vehicle: Optional[str] = None,
        user_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """업무용차량 운행기록부 목록 조회.
        ★ '운행일지', '차량 운행기록', '누가 차 끌고 어디 갔어', '몇 km 탔어' 등에 사용.
        세법 별지서식 기반 회사 보유 업무용 승용차량의 운행 이력을 반환합니다.

        vehicle: 차종(번호) 부분 검색 (예: '카니발', '38가1234')
        user_name: 운전자 성명 부분 검색
        date_from / date_to: 사용일자 범위 (YYYY-MM-DD)
        limit: 최대 건수 (기본 50)
        """
        from modules.models.misc_entities import VehicleLog
        session = get_session()
        try:
            q = session.query(VehicleLog)
            if vehicle:
                q = q.filter(VehicleLog.vehicle.ilike(f"%{vehicle}%"))
            if user_name:
                q = q.filter(VehicleLog.user_name.ilike(f"%{user_name}%"))
            if date_from:
                try:
                    df = datetime.datetime.strptime(date_from, "%Y-%m-%d").date()
                    q = q.filter(VehicleLog.use_date >= df)
                except ValueError:
                    pass
            if date_to:
                try:
                    dt = datetime.datetime.strptime(date_to, "%Y-%m-%d").date()
                    q = q.filter(VehicleLog.use_date <= dt)
                except ValueError:
                    pass

            logs = q.order_by(VehicleLog.use_date.desc(), VehicleLog.id.desc()).limit(limit).all()

            result = []
            for v in logs:
                result.append({
                    "id": v.id,
                    "use_date": _sd(v.use_date),
                    "vehicle": _s(v.vehicle),
                    "user_name": _s(v.user_name),
                    "user_department": _s(v.user_department),
                    "user_position": _s(v.user_position),
                    "odometer_start": v.odometer_start or 0,
                    "odometer_end": v.odometer_end or 0,
                    "distance_km": v.distance_km or 0,
                    "fuel_amount": v.fuel_amount or 0,
                    "origin": _s(v.origin),
                    "destination": _s(v.destination),
                    "purpose": _s(v.purpose),
                    "has_receipt": bool(v.receipt_url),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_vehicle_log_summary(
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> str:
        """차량별 운행 요약 (월간/연간 누적 km, 주유금액, 건수).
        ★ '이번달 운행거리', 'OO차 누적', '연간 차량별 사용량' 등에 사용.

        year: 연도 (생략 시 올해)
        month: 월 (1-12, 생략 시 연 단위 집계)
        """
        from modules.models.misc_entities import VehicleLog
        session = get_session()
        try:
            today = datetime.date.today()
            yr = year or today.year

            q = session.query(
                VehicleLog.vehicle,
                func.count(VehicleLog.id).label("cnt"),
                func.coalesce(func.sum(VehicleLog.distance_km), 0).label("total_km"),
                func.coalesce(func.sum(VehicleLog.fuel_amount), 0).label("total_fuel"),
            ).filter(func.extract("year", VehicleLog.use_date) == yr)

            if month:
                q = q.filter(func.extract("month", VehicleLog.use_date) == month)

            rows = q.group_by(VehicleLog.vehicle).order_by(func.sum(VehicleLog.distance_km).desc()).all()

            period_label = f"{yr}년 {month}월" if month else f"{yr}년"
            vehicles = [{
                "vehicle": _s(r.vehicle),
                "log_count": int(r.cnt or 0),
                "total_km": int(r.total_km or 0),
                "total_fuel": int(r.total_fuel or 0),
            } for r in rows]

            return json.dumps({
                "period": period_label,
                "vehicle_count": len(vehicles),
                "vehicles": vehicles,
                "total_km_all": sum(v["total_km"] for v in vehicles),
                "total_fuel_all": sum(v["total_fuel"] for v in vehicles),
                "total_logs_all": sum(v["log_count"] for v in vehicles),
            }, ensure_ascii=False)
        finally:
            session.close()
