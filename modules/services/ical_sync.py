"""
카카오워크 캘린더 ICS 동기화 — 직원 연차/휴가 정보를 파싱
"""
import datetime
import logging
import requests
from icalendar import Calendar

logger = logging.getLogger(__name__)

KAKAO_ICS_URL = (
    'https://calendar.kakaowork.com/ical/calendars/'
    'afa0655ca1aa091651017ee7a4412593/public/basic.ics'
)

# 캐시: {fetched_at, events}
_cache = {'fetched_at': None, 'events': []}
CACHE_TTL = datetime.timedelta(minutes=10)


def fetch_leave_events(force=False):
    """ICS에서 연차/휴가 이벤트 파싱. 캐시 10분.

    Returns:
        list of dict: [{
            'summary': '홍길동 연차',
            'name': '홍길동',
            'leave_type': '연차',
            'start': date,
            'end': date,  # exclusive (iCal DTEND)
            'all_day': True,
        }, ...]
    """
    now = datetime.datetime.now()
    if not force and _cache['fetched_at'] and (now - _cache['fetched_at']) < CACHE_TTL:
        return _cache['events']

    try:
        resp = requests.get(KAKAO_ICS_URL, timeout=10)
        resp.raise_for_status()
        cal = Calendar.from_ical(resp.content)
    except Exception as e:
        logger.warning('ICS fetch failed: %s', e)
        return _cache['events']  # 실패 시 기존 캐시 반환

    events = []
    for component in cal.walk():
        if component.name != 'VEVENT':
            continue

        summary = str(component.get('summary', ''))
        dtstart = component.get('dtstart')
        dtend = component.get('dtend')

        if not dtstart:
            continue

        start = dtstart.dt
        end = dtend.dt if dtend else start

        # datetime → date 변환 (종일 이벤트)
        all_day = isinstance(start, datetime.date) and not isinstance(start, datetime.datetime)
        if isinstance(start, datetime.datetime):
            start = start.date()
        if isinstance(end, datetime.datetime):
            end = end.date()

        # 이름/유형 파싱
        # 패턴: "홍길동연차", "홍길동 연차", "김효민 공가(반차)", "최한진 경조사휴무"
        import re
        name = summary.strip()
        leave_type = '휴가'

        # 키워드 목록 (긴 것부터 매칭)
        _keywords = [
            '경조사휴무', '특별휴가', '오전반차', '오후반차',
            '연차', '반차', '공가', '경조', '출장', '외근', '병가', '휴무',
        ]
        # 1) 괄호 안 세부 유형 먼저 추출: "공가(반차)" → sub_type=반차
        sub_type = ''
        paren = re.search(r'\(([^)]+)\)', name)
        if paren:
            inner = paren.group(1)
            for kw in _keywords:
                if kw in inner:
                    sub_type = kw
                    break
            name = re.sub(r'\([^)]*\)', '', name).strip()

        # 2) 메인 키워드 추출
        for kw in _keywords:
            if kw in name:
                leave_type = kw
                name = name.replace(kw, '')
                break

        # 3) 반차 판별: 오전/오후 구분
        is_half = sub_type in ('반차', '오전반차', '오후반차') or '반차' in leave_type
        if is_half:
            # 시작시간으로 오전/오후 판단
            raw_start = dtstart.dt
            if isinstance(raw_start, datetime.datetime):
                leave_type = '오전반차' if raw_start.hour < 12 else '오후반차'
            elif '오전' in summary:
                leave_type = '오전반차'
            elif '오후' in summary:
                leave_type = '오후반차'
            else:
                leave_type = '반차'
        elif sub_type and sub_type != leave_type:
            leave_type = sub_type

        name = name.strip().rstrip(' -·')

        events.append({
            'summary': summary,
            'name': name,
            'leave_type': leave_type,
            'start': start,
            'end': end,
            'all_day': all_day,
        })

    _cache['fetched_at'] = now
    _cache['events'] = events
    logger.info('ICS synced: %d events', len(events))
    return events


def get_leave_events_for_date(target_date):
    """특정 날짜의 연차/휴가 이벤트 반환"""
    events = fetch_leave_events()
    # start <= target < end (iCal DTEND는 exclusive)
    return [e for e in events if e['start'] <= target_date < e['end']]


def get_leave_events_for_month(year, month):
    """특정 월의 연차/휴가 이벤트 반환 (날짜별 dict)"""
    events = fetch_leave_events()
    month_start = datetime.date(year, month, 1)
    if month == 12:
        month_end = datetime.date(year + 1, 1, 1)
    else:
        month_end = datetime.date(year, month + 1, 1)

    result = {}  # {date: [event, ...]}
    for e in events:
        day = max(e['start'], month_start)
        end = min(e['end'], month_end)
        while day < end:
            result.setdefault(day, []).append(e)
            day += datetime.timedelta(days=1)
    return result
