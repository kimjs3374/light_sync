"""대한민국 법정공휴일 서비스

`holidays` 라이브러리 기반 — 음력 공휴일(설날/추석/부처님오신날) + 대체공휴일 +
임시공휴일(선거일 등) 자동 계산. 매년 수동 갱신 불필요.

연도별 법 개정도 라이브러리가 반영 (예: 제헌절은 2008~2025 비휴무, 2026부터 휴무 부활).
"""
import datetime
import logging

logger = logging.getLogger(__name__)

_cache = {}


def _kr_year(year):
    """해당 연도 공휴일(date) 집합. 캐시."""
    if year in _cache:
        return _cache[year]
    try:
        import holidays as _hol
        h = _hol.SouthKorea(years=year)
        days = set(h.keys())
    except Exception:
        logger.exception('holidays 계산 실패 year=%s', year)
        days = set()
    _cache[year] = days
    return days


def is_holiday(d):
    return d in _kr_year(d.year)


def working_days(start, end):
    """start~end(둘 다 포함) 사이 근무일수 = 평일 - 공휴일."""
    if not start or not end or end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in _kr_year(d.year):
            n += 1
        d += datetime.timedelta(days=1)
    return n


def holiday_list(years):
    """클라이언트 전달용 ['YYYY-MM-DD', ...] (해당 연도들의 공휴일)."""
    out = []
    for y in years:
        out.extend(sorted(d.isoformat() for d in _kr_year(y)))
    return out


def holiday_map(years):
    """{'YYYY-MM-DD': 한글 공휴일명}"""
    try:
        import holidays as _hol
        out = {}
        for y in years:
            try:
                h = _hol.SouthKorea(years=y, language='ko')  # 한글명
            except TypeError:
                h = _hol.SouthKorea(years=y)                 # 구버전 폴백(영문)
            for d in h:
                out[d.isoformat()] = h.get(d) or ''
        return out
    except Exception:
        return {}
