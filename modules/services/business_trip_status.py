"""출장 유효상태(effective status) 단일 소스.

출장 상태는 저장된 status 컬럼이 아니라 **날짜로 계산**한다('취소'만 저장값 사용).
ERP 웹 목록(routes/business_trip.py)과 MCP 도구(light_sync_mcp)가 이 로직을 공유해
서로 다른 답을 내지 않도록 한다.

  - departure_date 없음/미래  → 예정
  - 복귀일(없으면 출발 다음날 00:00) 이 지남 → 완료
  - 그 사이(출발했고 아직 복귀 전) → 진행중
"""
from __future__ import annotations

import datetime


def implicit_return(trip) -> datetime.datetime | None:
    """복귀 미정이면 출발일 다음날 00:00 을 묵시 복귀로 (당일 출장은 다음날 완료)."""
    if trip.departure_date is None:
        return None
    if trip.return_date is not None:
        return trip.return_date
    d = trip.departure_date
    return datetime.datetime(d.year, d.month, d.day) + datetime.timedelta(days=1)


def effective_status(trip, now: datetime.datetime | None = None) -> str:
    """저장 status 가 아니라 날짜 기준 실제 상태를 반환."""
    if now is None:
        now = datetime.datetime.now()
    if trip.status == '취소':
        return '취소'
    if trip.departure_date is None or trip.departure_date > now:
        return '예정'
    impl = implicit_return(trip)
    if impl is not None and impl <= now:
        return '완료'
    return '진행중'


def eff_status_sql_expr(now: datetime.datetime | None = None):
    """웹 목록 쿼리용 SQLAlchemy case 식 (effective_status 와 동일 규칙)."""
    from sqlalchemy import case, func
    from modules.models.misc_entities import BusinessTrip
    if now is None:
        now = datetime.datetime.now()
    impl = func.coalesce(
        BusinessTrip.return_date,
        func.date_trunc('day', BusinessTrip.departure_date) + datetime.timedelta(days=1),
    )
    return case(
        (BusinessTrip.status == '취소', '취소'),
        (BusinessTrip.departure_date == None, '예정'),  # noqa: E711
        (BusinessTrip.departure_date > now, '예정'),
        (impl <= now, '완료'),
        else_='진행중',
    )


def filter_by_effective_status(query, status_filter: str, now: datetime.datetime | None = None):
    """저장 status 대신 유효상태로 BusinessTrip 쿼리를 필터."""
    from sqlalchemy import or_
    from modules.models.misc_entities import BusinessTrip
    if now is None:
        now = datetime.datetime.now()
    impl = _impl_expr()
    if status_filter == '취소':
        return query.filter(BusinessTrip.status == '취소')
    if status_filter == '예정':
        return query.filter(
            BusinessTrip.status != '취소',
            or_(BusinessTrip.departure_date == None, BusinessTrip.departure_date > now),  # noqa: E711
        )
    if status_filter == '진행중':
        return query.filter(
            BusinessTrip.status != '취소',
            BusinessTrip.departure_date != None,  # noqa: E711
            BusinessTrip.departure_date <= now,
            impl > now,
        )
    if status_filter == '완료':
        return query.filter(
            BusinessTrip.status != '취소',
            BusinessTrip.departure_date != None,  # noqa: E711
            impl <= now,
        )
    return query


def reconcile_stored_status(db) -> dict:
    """저장 status 컬럼을 날짜 기준 유효상태로 맞춘다(멱등).

    표시 로직은 이미 유효상태를 계산하므로, 이 함수는 DB 직접 열람·저장값에
    의존하는 화면(대시보드 등)의 정합성을 위한 보정이다. crontab 으로 주기 실행.
    반환: {"updated": n, "changes": {"예정→완료": k, ...}}
    """
    from modules.models.misc_entities import BusinessTrip
    trips = db.query(BusinessTrip).all()
    changes: dict[str, int] = {}
    updated = 0
    for t in trips:
        eff = effective_status(t)
        if t.status != eff:
            key = f"{t.status}→{eff}"
            changes[key] = changes.get(key, 0) + 1
            t.status = eff
            updated += 1
    return {"updated": updated, "changes": changes}


def _impl_expr():
    from sqlalchemy import func
    from modules.models.misc_entities import BusinessTrip
    return func.coalesce(
        BusinessTrip.return_date,
        func.date_trunc('day', BusinessTrip.departure_date) + datetime.timedelta(days=1),
    )
