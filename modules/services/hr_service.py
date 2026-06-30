"""인사관리 로직 — 연차 자동 산정(입사일 기준) + 전자결재 휴가 자동 차감.

근로기준법 기준(입사일 기준):
  - 입사 1년 미만: 1개월 개근당 1일 (최대 11일)
  - 1년 이상: 15일
  - 3년 이상부터 매 2년 1일 가산, 최대 25일  → 15 + (근속연수-1)//2
"""
import datetime

from modules.models import ApprovalDocument, LeaveAdjustment, LeaveUsage, User

# 연차 차감 대상 (그 외 병가/경조사/공가/기타는 미차감)
ANNUAL_TYPES = ('연차',)

# 근무시간 기준 (시작/종료 일시 → 사용일수 자동 산정)
WORK_START = 9.0      # 09:00
WORK_END = 18.0       # 18:00
LUNCH = (12.0, 13.0)  # 점심 1시간 제외
HOURS_PER_DAY = 8.0   # 1일 = 8근무시간 (반차 4h=0.5, 반반차 2h=0.25)


def _completed_years(hire_date, as_of):
    y = as_of.year - hire_date.year
    if (as_of.month, as_of.day) < (hire_date.month, hire_date.day):
        y -= 1
    return y


def _completed_months(hire_date, as_of):
    m = (as_of.year - hire_date.year) * 12 + (as_of.month - hire_date.month)
    if as_of.day < hire_date.day:
        m -= 1
    return max(0, m)


def annual_entitlement(hire_date, as_of=None):
    """입사일 기준 연차 부여일수."""
    if not hire_date:
        return 0
    as_of = as_of or datetime.date.today()
    if as_of < hire_date:
        return 0
    years = _completed_years(hire_date, as_of)
    if years < 1:
        return min(_completed_months(hire_date, as_of), 11)
    return min(15 + (years - 1) // 2, 25)


def _safe_anniversary(year, hire_date):
    """입사 기념일(윤년 2/29 보정)."""
    try:
        return datetime.date(year, hire_date.month, hire_date.day)
    except ValueError:
        return datetime.date(year, hire_date.month, 28)


def leave_year_range(hire_date, as_of=None):
    """현재 연차연도 범위 (입사 기념일 기준). 반환 (start, end[exclusive])."""
    as_of = as_of or datetime.date.today()
    if not hire_date:
        # 입사일 없으면 회계연도 fallback
        return datetime.date(as_of.year, 1, 1), datetime.date(as_of.year + 1, 1, 1)
    if _completed_years(hire_date, as_of) < 1:
        # 1년 미만: 입사일 ~ 1년 후
        return hire_date, _safe_anniversary(hire_date.year + 1, hire_date)
    anniv = _safe_anniversary(as_of.year, hire_date)
    if as_of >= anniv:
        return anniv, _safe_anniversary(as_of.year + 1, hire_date)
    return _safe_anniversary(as_of.year - 1, hire_date), anniv


def leave_year_start_for(hire_date, year, as_of=None):
    """입사일 기준, 지정한 시작연도(year)의 연차연도 시작일."""
    if not hire_date:
        return datetime.date(year, 1, 1)
    return _safe_anniversary(year, hire_date)


def leave_year_options(hire_date, as_of=None):
    """선택 가능한 연차연도 목록 (입사연도~현재). 최신연도 우선.

    반환: [(start_date, end_date, year_label), ...]
    """
    as_of = as_of or datetime.date.today()
    if not hire_date:
        s = datetime.date(as_of.year, 1, 1)
        return [(s, datetime.date(as_of.year + 1, 1, 1), as_of.year)]
    cur_start, _ = leave_year_range(hire_date, as_of)
    opts = []
    y = hire_date.year
    while True:
        s = _safe_anniversary(y, hire_date)
        e = _safe_anniversary(y + 1, hire_date)
        opts.append((s, e, y))
        if s >= cur_start:
            break
        y += 1
    opts.reverse()
    return opts


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.datetime.strptime(str(s).strip()[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _parse_dt(s):
    """'2026-06-15T09:00' / '2026-06-15 09:00' / '2026-06-15' → datetime."""
    if not s:
        return None
    s = str(s).strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _is_holiday(d):
    if d.weekday() >= 5:
        return True
    try:
        from modules.services import holiday_service
        return holiday_service.is_holiday(d)
    except Exception:
        return False


def _work_hours_in_day(d, from_h, to_h):
    """해당 날짜의 [from_h, to_h] 구간 근무시간 (주말/공휴일=0, 점심 제외)."""
    if _is_holiday(d):
        return 0.0
    a = max(from_h, WORK_START)
    b = min(to_h, WORK_END)
    if b <= a:
        return 0.0
    hours = b - a
    lunch = max(0.0, min(b, LUNCH[1]) - max(a, LUNCH[0]))
    return max(0.0, hours - lunch)


def leave_days_between(start_dt, end_dt):
    """시작~종료 일시 → 사용일수 (8근무시간=1일, 0.25 단위 반올림)."""
    if not start_dt or not end_dt or end_dt < start_dt:
        return 0.0
    total = 0.0
    d = start_dt.date()
    last = end_dt.date()
    while d <= last:
        from_h = (start_dt.hour + start_dt.minute / 60.0) if d == start_dt.date() else WORK_START
        to_h = (end_dt.hour + end_dt.minute / 60.0) if d == end_dt.date() else WORK_END
        total += _work_hours_in_day(d, from_h, to_h)
        d += datetime.timedelta(days=1)
    days = total / HOURS_PER_DAY
    return round(days / 0.25) * 0.25


def _leave_start_date(fd):
    """연차연도 판정용 시작 날짜 (신규 start_dt / 구버전 start_date)."""
    dt = _parse_dt(fd.get('start_dt'))
    if dt:
        return dt.date()
    return _parse_date(fd.get('start_date'))


def _combine_dt(date_str, time_str, default_time):
    """날짜 + 시각 → datetime (시각 없으면 기본값)."""
    d = _parse_date(date_str)
    if not d:
        return None
    t = (str(time_str).strip() if time_str else '') or default_time
    try:
        hh, mm = (int(x) for x in t.split(':')[:2])
    except (ValueError, AttributeError):
        hh, mm = (int(x) for x in default_time.split(':'))
    return datetime.datetime(d.year, d.month, d.day, hh, mm)


def _doc_leave_days(doc):
    """휴가 문서의 연차 차감 일수. 연차만 차감.
    기간(period): 반차=0.5, 종일=근무일수(주말·공휴일 제외)."""
    fd = doc.form_data or {}
    ltype = fd.get('leave_type') or ''
    if ltype not in ANNUAL_TYPES:
        # 구버전 호환: 옛 반차/반반차가 leave_type에 있던 경우
        if '반차' in ltype:
            return 0.5
        return 0.0  # 병가/경조사/공가/기타 미차감
    # 연차
    period = fd.get('period') or ''
    if '반차' in period:
        return 0.5
    # 종일(또는 미지정): 시작~종료 근무일수
    s = _parse_date(fd.get('start_date')) or _parse_date(fd.get('start_dt'))
    e = _parse_date(fd.get('end_date')) or _parse_date(fd.get('end_dt')) or s
    if s and e:
        try:
            from modules.services import holiday_service
            wd = holiday_service.working_days(s, e)
            if wd > 0:
                return float(wd)
        except Exception:
            pass
        return float((e - s).days + 1)
    raw = fd.get('days')
    try:
        if raw not in (None, ''):
            return float(str(raw).replace(',', ''))
    except ValueError:
        pass
    return 1.0


def used_leave_days(db, user_id, year_start, year_end):
    """연차연도 내 사용 연차 합계 + 상세 목록.

    = 전자결재 승인 휴가(연차) 자동 차감분 + 관리자 수동 사용 등록분.
    """
    from sqlalchemy import or_
    docs = (db.query(ApprovalDocument)
            .filter(ApprovalDocument.form_key == 'leave',
                    or_(ApprovalDocument.status == 'approved',
                        ApprovalDocument.effect_active.is_(True)),
                    ApprovalDocument.drafter_id == user_id)
            .all())
    total = 0.0
    detail = []
    for d in docs:
        fd = d.form_data or {}
        sd = _leave_start_date(fd)
        if not sd or not (year_start <= sd < year_end):
            continue
        days = _doc_leave_days(d)
        if days <= 0:
            continue
        total += days
        detail.append({
            'doc_id': d.id, 'doc_no': d.doc_no, 'title': d.title,
            'leave_type': fd.get('leave_type', ''),
            'start': fd.get('start_dt') or fd.get('start_date', ''),
            'end': fd.get('end_dt') or fd.get('end_date', ''),
            'days': days,
            'manual': False,
        })
    # 관리자 수동 사용 등록분 (사용일 기준)
    usages = (db.query(LeaveUsage)
              .filter(LeaveUsage.user_id == user_id,
                      LeaveUsage.used_date >= year_start,
                      LeaveUsage.used_date < year_end)
              .order_by(LeaveUsage.used_date)
              .all())
    for u in usages:
        days = float(u.days or 0)
        if days <= 0:
            continue
        total += days
        detail.append({
            'doc_id': None, 'doc_no': None, 'title': u.reason or '',
            'leave_type': u.leave_type or '연차',
            'start': u.used_date.strftime('%Y-%m-%d'),
            'end': '',
            'days': days,
            'manual': True,
            'usage_id': u.id,
        })
    # 사용일(시작일) 오름차순 정렬
    detail.sort(key=lambda x: str(x.get('start') or ''))
    return total, detail


def leave_summary(db, user, as_of=None):
    """직원 연차 요약: 부여/사용/조정/잔여."""
    as_of = as_of or datetime.date.today()
    hire = user.hire_date
    ys, ye = leave_year_range(hire, as_of)
    granted = annual_entitlement(hire, as_of)
    used, detail = used_leave_days(db, user.id, ys, ye)
    adj_rows = (db.query(LeaveAdjustment)
                .filter(LeaveAdjustment.user_id == user.id,
                        LeaveAdjustment.leave_year == ys.year)
                .all())
    adj = float(sum(a.days for a in adj_rows))
    remaining = round(granted + adj - used, 1)
    return {
        'granted': granted,
        'used': round(used, 1),
        'adjust': round(adj, 1),
        'remaining': remaining,
        'year_start': ys,
        'year_end': ye,
        'detail': detail,
        'adjustments': adj_rows,
        'hire_date': hire,
        'years': _completed_years(hire, as_of) if hire else None,
    }
