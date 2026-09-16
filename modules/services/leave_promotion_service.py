"""연차사용촉진제 (근로기준법 제61조) 로직.

입사일 기준 연차연도(hr_service.leave_year_range)를 그대로 활용해,
직원별로 1차 촉구 / 2차(회사 지정) 시점을 산출하고 leave_promotions에 이력을 남긴다.

1년 이상(제61조 제1항)과 1년 미만(제61조 제2항)은 **일정이 다르다.**
예전엔 둘 다 6개월/9개월을 썼는데, 1년 미만자에게 3개월 이른 촉구가 나갔다.
법정 기간을 벗어난 촉구는 촉진 효과(미사용 수당 면제)가 인정되지 않는다.

1년 이상 — 제61조 제1항 (연차연도 1년 기준)
  · first  : 끝나기 6개월 전 기준 10일 이내 서면 촉구
  · second : 미지정 시 끝나기 2개월 전까지 회사 지정 통보
             (여유를 두려고 끝나기 3개월 전부터 목록에 올린다)

1년 미만 — 제61조 제2항 (최초 1년 기준). 두 벌이 돈다.
  · first  : 끝나기 3개월 전 기준 10일 이내 촉구
             — 끝나기 1개월 전까지 발생한 연차가 대상
  · second : 미지정 시 끝나기 1개월 전까지 회사 지정 통보
  · extra  : 끝나기 1개월 전 기준 5일 이내 촉구
             — 그 뒤 발생분(마지막 개근 1일)이 대상
  · extra2 : 미지정 시 끝나기 10일 전까지 회사 지정 통보
"""
import datetime
from calendar import monthrange

from modules.models import LeavePromotion, User
from modules.services import hr_service

# ── 시점 상수 (연차연도 시작 기준 N개월 후) ──────────────────
FIRST_MONTHS_AFTER_START = 6   # 1년 이상 1회차 촉구 (= 끝나기 6개월 전)
SECOND_MONTHS_AFTER_START = 9  # 1년 이상 2회차 (= 끝나기 3개월 전부터 목록에)

ACTION_WINDOW_DAYS = 10   # 촉구 발송 권장 기간(기준일로부터 10일 이내)
DESIGNATE_DAYS = 10       # 직원 사용시기 지정 기한(촉구일로부터 10일)

STAGE_LABEL = {'first': '1회차 촉구', 'second': '2회차 지정통보',
               'extra': '추가 촉구', 'extra2': '추가 지정통보'}
EMP_TYPE_LABEL = {'over1y': '1년 이상', 'under1y': '1년 미만'}


def _add_months(d, n):
    """date에 n개월 더하기(말일 보정)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return datetime.date(y, m, min(d.day, monthrange(y, m)[1]))


def _emp_window(hire_date, as_of):
    """현재 연차연도의 촉구 단계별 기준일 계산.

    반환: (ys, ye, last_day, stages)
      stages: [(emp_type, stage, anchor, second_stage, second_anchor), ...]
              촉구 한 벌 = 1회차 + 그에 딸린 회사지정. 1년 미만은 두 벌이다.
    """
    ys, ye = hr_service.leave_year_range(hire_date, as_of)
    under1y = hr_service._completed_years(hire_date, ys) < 1
    emp_type = 'under1y' if under1y else 'over1y'
    last = ye - datetime.timedelta(days=1)
    if under1y:
        # 제61조 제2항 — 기준은 '최초 1년이 끝나기 N개월 전'이다.
        # ys 가 입사일이므로 ye(=+1년) 에서 거꾸로 센다.
        m3 = _add_months(ye, -3)    # 끝나기 3개월 전
        m1 = _add_months(ye, -1)    # 끝나기 1개월 전
        stages = [
            (emp_type, 'first', m3, 'second', m1),
            (emp_type, 'extra', m1, 'extra2',
             m1 + datetime.timedelta(days=DESIGNATE_DAYS)),
        ]
    else:
        stages = [(emp_type, 'first',
                   _add_months(ys, FIRST_MONTHS_AFTER_START),
                   'second', _add_months(ys, SECOND_MONTHS_AFTER_START))]
    return ys, ye, last, stages


def _active_employees(db):
    """촉진 대상 활성 직원(입사일 보유, 최고관리자 제외)."""
    return (db.query(User)
            .filter(User.is_active.is_(True),
                    User.user_group != '최고관리자',
                    User.hire_date.isnot(None))
            .order_by(User.user_group, User.full_name)
            .all())


def _existing_by_stage(db, user_id, leave_year):
    """재발송 판정용 — **회수된 회차는 없는 셈** 친다.

    회수(cancel)의 목적이 '다시 보낼 수 있게'이므로 여기서만 제외한다.
    이력 조회·서면 출력에서는 회수분도 그대로 보인다(증빙이라 지우지 않는다).
    """
    rows = (db.query(LeavePromotion)
            .filter(LeavePromotion.user_id == user_id,
                    LeavePromotion.leave_year == leave_year,
                    LeavePromotion.cancelled_at.is_(None))
            .all())
    return {r.stage: r for r in rows}


def cancel_promotion(db, promo_id, by):
    """촉구 회수 — 행을 지우지 않고 회수 표시만 한다.

    이미 나간 메일은 되돌릴 수 없다. 이 행이 '보냈다'는 유일한 증빙이므로
    지우면 근로기준법 제61조 입증 수단이 사라진다(실제로 한 건 사라졌다).
    """
    p = db.get(LeavePromotion, promo_id)
    if not p or p.cancelled_at:
        return p
    p.cancelled_at = datetime.datetime.now()
    p.cancelled_by = by
    db.flush()
    return p


def uncancel_promotion(db, promo_id):
    """회수 취소 — 같은 회차가 이미 다시 발송됐으면 되돌리지 않는다."""
    p = db.get(LeavePromotion, promo_id)
    if not p or not p.cancelled_at:
        return p, None
    dup = _existing_by_stage(db, p.user_id, p.leave_year).get(p.stage)
    if dup:
        return p, dup
    p.cancelled_at = None
    p.cancelled_by = None
    db.flush()
    return p, None


def candidates(db, as_of=None):
    """촉진 대상자 산출. 발송/기록은 하지 않고 '대상 목록'만 반환.

    반환: {'first': [...], 'second': [...]}
      first  : 1차/추가 촉구가 필요한 직원 (아직 미발송)
      second : 1차 후 직원이 미지정해 회사 지정(2차)이 필요한 직원
    """
    as_of = as_of or datetime.date.today()
    out = {'first': [], 'second': []}
    for u in _active_employees(db):
        ys, ye, last, stages = _emp_window(u.hire_date, as_of)
        existing = _existing_by_stage(db, u.id, ys.year)

        for emp_type, stage, anchor, sec_stage, sec_anchor in stages:
            # 1차/추가 촉구 대상 (기준일 도래 + 연차연도 내 + 미발송)
            if anchor <= as_of <= last and stage not in existing:
                out['first'].append({
                    'user': u, 'emp_type': emp_type, 'stage': stage,
                    'leave_year': ys.year, 'anchor': anchor,
                    'late': as_of > anchor + datetime.timedelta(days=ACTION_WINDOW_DAYS),
                })

            # 회사지정 대상 (그 벌의 촉구가 나갔고 직원 미지정 + 시점 도래 + 미발송)
            if as_of < sec_anchor or sec_stage in existing:
                continue
            src = existing.get(stage)
            if src and not src.employee_dates and (
                    not src.designate_due or as_of >= src.designate_due):
                out['second'].append({
                    'user': u, 'emp_type': emp_type, 'leave_year': ys.year,
                    'source': src, 'stage': sec_stage,
                    'second_anchor': sec_anchor,
                })
    return out


def record_promotion(db, user, emp_type, stage, by='system',
                     channel='email', email_sent=False, as_of=None):
    """촉구(1차/추가) 이력 생성 + 연차 스냅샷 기록. 중복(stage) 시 기존 반환."""
    as_of = as_of or datetime.date.today()
    s = hr_service.leave_summary(db, user, as_of)
    ly = s['year_start'].year
    existing = _existing_by_stage(db, user.id, ly).get(stage)
    if existing:
        return existing
    p = LeavePromotion(
        user_id=user.id, leave_year=ly, emp_type=emp_type, stage=stage,
        year_start=s['year_start'],
        year_end=s['year_end'] - datetime.timedelta(days=1),  # 마지막 사용일
        granted_days=s['granted'], used_days=s['used'],
        remaining_days=s['remaining'],
        notified_at=datetime.datetime.now(), notified_by=by,
        channel=channel, email_to=getattr(user, 'email', None),
        email_sent=email_sent,
        designate_due=as_of + datetime.timedelta(days=DESIGNATE_DAYS),
        status='sent',
    )
    db.add(p)
    db.flush()
    return p


def record_second(db, user, emp_type, admin_dates, by, as_of=None,
                  stage='second'):
    """회사지정 통보 이력 생성. 1년 미만은 추가분(extra2)도 같은 길을 쓴다."""
    as_of = as_of or datetime.date.today()
    s = hr_service.leave_summary(db, user, as_of)
    ly = s['year_start'].year
    existing = _existing_by_stage(db, user.id, ly).get(stage)
    if existing:
        existing.admin_dates = admin_dates
        existing.admin_by = by
        existing.admin_at = datetime.datetime.now()
        existing.status = 'admin_designated'
        db.flush()
        return existing
    p = LeavePromotion(
        user_id=user.id, leave_year=ly, emp_type=emp_type, stage=stage,
        year_start=s['year_start'],
        year_end=s['year_end'] - datetime.timedelta(days=1),
        granted_days=s['granted'], used_days=s['used'],
        remaining_days=s['remaining'],
        notified_at=datetime.datetime.now(), notified_by=by, channel='email',
        email_to=getattr(user, 'email', None),
        admin_dates=admin_dates, admin_by=by, admin_at=datetime.datetime.now(),
        status='admin_designated',
    )
    db.add(p)
    db.flush()
    return p


def promo_asof(promo, as_of=None):
    """촉진 레코드가 속한 **연차연도 안**으로 clamp된 기준일.

    leave_summary/leave_year_range는 as_of가 속한 연차연도를 잡는다.
    촉진 문서는 항상 그 레코드의 연차연도(year_start~year_end)를 봐야 하므로,
    오늘이 그 범위 밖(=이미 끝난 직전 연차연도)이면 year_end로 고정한다.
    이 clamp를 빠뜨리면 다음 연차연도(=올해) 사용분이 서면에 섞여 들어간다.
    """
    as_of = as_of or datetime.date.today()
    if not promo or not promo.year_start or not promo.year_end:
        return as_of
    if as_of < promo.year_start:
        return promo.year_start
    if as_of > promo.year_end:
        return promo.year_end
    return as_of


def promo_summary(db, promo, user, as_of=None):
    """촉진 레코드의 연차연도 기준 leave_summary. 실패 시 None."""
    if not user:
        return None
    try:
        return hr_service.leave_summary(db, user, promo_asof(promo, as_of))
    except Exception:
        return None


def live_leave(db, promo, user, as_of=None):
    """촉진 레코드의 '실시간' 잔여/사용/부여 + 전자결재 승인 연차 일자.

    remaining_days 등은 촉구 발송 시점의 스냅샷이라 이후 전자결재로 승인된
    연차가 반영되지 않는다. 이 함수는 leave_summary로 현재 시점(또는 해당
    연차연도 기준)의 값을 다시 계산해 준다.
    반환: {'remaining','used','granted','approved':[{date,type}]}
    """
    res = {'remaining': promo.remaining_days, 'used': promo.used_days,
           'granted': promo.granted_days, 'approved': []}
    if not user or not promo.year_start or not promo.year_end:
        return res
    as_of = promo_asof(promo, as_of)
    try:
        s = hr_service.leave_summary(db, user, as_of)
    except Exception:
        return res
    res['remaining'] = s['remaining']
    res['used'] = s['used']
    res['granted'] = s['granted']
    res['approved'] = hr_service.approved_leave_entries(
        db, user.id, s['year_start'], s['year_end'])
    return res


def entry_days(t):
    """연차=1.0 / 반차=0.5."""
    return 0.5 if t == '반차' else 1.0


def normalize_entries(entries):
    """[{date,type}] 또는 ['YYYY-MM-DD'] → [{date,type,days}] (중복 date 제거)."""
    out, seen = [], set()
    for e in (entries or []):
        if isinstance(e, dict):
            d = (e.get('date') or '').strip()
            t = '반차' if e.get('type') == '반차' else '연차'
        else:
            d = str(e).strip()
            t = '연차'
        if d and d not in seen:
            seen.add(d)
            out.append({'date': d, 'type': t, 'days': entry_days(t)})
    return out


def entries_total(entries):
    return round(sum(x['days'] for x in entries), 1)


def in_leave_year(promo, date_str):
    """date_str('YYYY-MM-DD')이 촉진 레코드의 연차연도 안인가."""
    if not promo or not promo.year_start or not promo.year_end:
        return True
    d = str(date_str or '')[:10]
    return (promo.year_start.strftime('%Y-%m-%d') <= d
            <= promo.year_end.strftime('%Y-%m-%d'))


def filter_in_leave_year(promo, entries):
    """연차연도 밖 entries 제거. 반환 (남은 entries, 제외 건수).

    entries는 [{date,..}] / ['YYYY-MM-DD'] 두 형태 모두 허용.
    """
    def _d(e):
        return e.get('date') if isinstance(e, dict) else e
    keep = [e for e in (entries or []) if in_leave_year(promo, _d(e))]
    return keep, len(entries or []) - len(keep)


def employee_designate(db, promo_id, entries, user_id=None):
    """직원 셀프 — 사용시기 지정. entries: [{date,type}] 또는 ['YYYY-MM-DD']."""
    p = db.get(LeavePromotion, promo_id)
    if not p:
        return None
    if user_id is not None and p.user_id != user_id:
        return None
    p.employee_dates = normalize_entries(entries)
    p.designated_at = datetime.datetime.now()
    p.status = 'designated'
    db.flush()
    return p


def clear_employee_designation(db, promo_id, user_id=None):
    """관리자 — 직원이 지정한 사용시기(employee_dates)를 삭제하고 미지정으로 되돌린다.

    잘못 지정했거나 재지정이 필요할 때 사용. status가 'designated'였다면 'sent'로
    복원해 직원이 다시 지정할 수 있게 한다. 회사지정분(admin_dates)은 건드리지 않는다.
    """
    p = db.get(LeavePromotion, promo_id)
    if not p:
        return None
    if user_id is not None and p.user_id != user_id:
        return None
    p.employee_dates = None
    p.designated_at = None
    if p.status == 'designated':
        p.status = 'sent'
    db.flush()
    return p


def set_doc_dates(db, promo_id, entries, by, as_of=None, set_status=True):
    """서면 증빙용 회사 확정/임의지정 사용일 저장(admin_dates).

    회사 임의지정(관리자 수기 입력)이 기본 경로 — 직원 미지정(sent) 상태였다면
    회사지정(2차) 성립으로 status 전환, 그 외(직원지정 등)는 status 유지.

    set_status=False 는 '실제 사용일 반영' 전용. 실제로 쓴 날을 서면에 옮겨
    적는 것뿐이므로 회사가 임의지정했다는 뜻이 되면 안 된다(status 불변).
    """
    p = db.get(LeavePromotion, promo_id)
    if not p:
        return None
    p.admin_dates = normalize_entries(entries)
    p.admin_by = by
    p.admin_at = datetime.datetime.now()
    if set_status and p.status == 'sent':
        p.status = 'admin_designated'
    db.flush()
    return p


def _d(s):
    try:
        return datetime.datetime.strptime(str(s).strip()[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError, AttributeError):
        return None


def _expand_detail_row(row):
    """leave_summary.detail 1행 → 일자별 [{date,type,days}].

    detail은 결재문서/수동등록 1건이 1행이라 다일 연차(7/28~7/31, 4일)가
    시작일 하나로 뭉쳐 있다. 서면에는 날짜가 모두 찍혀야 하므로 전개한다.

    기간은 **근무일만** 편다. 일수 자체가 근무일 기준으로 차감되므로(주말·공휴일
    제외), 달력일을 그대로 펴면 8/3~8/14 가 10일인데 서면에는 12일이 찍혀
    주말이 '실제로 썼는데 서면에 없는 날'로 잡힌다.

    종료일이 없는데 days>1 인 행(옛 관리자 수동등록분)은 어느 날짜인지 원본에
    정보가 없다 → 날짜를 지어내지 않고 unresolved 로 표시해 올려보낸다.
    """
    s = _d(row.get('start'))
    if not s:
        return []
    e = _d(row.get('end')) or s
    if e < s:
        e = s
    days = float(row.get('days') or 0)
    span = (e - s).days + 1
    if span == 1:
        if days > 1:   # 종료일 미기재 다일 연차 — 전개 불가
            return [{'date': s.strftime('%Y-%m-%d'), 'type': '연차',
                     'days': days, 'unresolved': True}]
        return [{'date': s.strftime('%Y-%m-%d'),
                 'type': '반차' if days == 0.5 else '연차',
                 'days': days or 1.0}]
    dates = [s + datetime.timedelta(days=i) for i in range(span)]
    try:
        from modules.services import holiday_service
        work = [d for d in dates
                if d.weekday() < 5 and not holiday_service.is_holiday(d)]
    except Exception:
        work = []
    if work:
        dates = work          # 전부 휴일인 이상 행은 달력일 그대로 둔다
    out = [{'date': d.strftime('%Y-%m-%d'), 'type': '연차', 'days': 1.0}
           for d in dates]
    # 마지막 날만 반차인 경우(예: 3일 구간 2.5일) 보정
    if days and abs(len(out) - days - 0.5) < 0.001:
        out[-1] = {'date': out[-1]['date'], 'type': '반차', 'days': 0.5}
    return out


def actual_usage_entries(summ, since=None, until=None):
    """leave_summary.detail → 서면 채우기용 [{date,type,days}] (일자별 전개).

    since/until(date)로 기간을 자른다. until은 반드시 해당 촉진의 연차연도
    종료일을 넘겨야 한다 — 상한이 없으면 다음 연차연도 사용분이 섞인다.
    """
    lo = since.strftime('%Y-%m-%d') if since else None
    hi = until.strftime('%Y-%m-%d') if until else None
    out, seen = [], set()
    for row in (summ.get('detail') if summ else []) or []:
        for e in _expand_detail_row(row):
            ds = e['date']
            if (lo and ds < lo) or (hi and ds > hi) or ds in seen:
                continue
            seen.add(ds)
            out.append(e)
    return sorted(out, key=lambda x: x['date'])


# ── 지정 사용일 ↔ 실제 사용일 대사 ──────────────────────────
def actual_for_promo(db, promo, user, as_of=None):
    """이 **회차**의 실제 사용일 = 통보일(notified_at) ~ 연차연도 종료일.

    회차별로 통보일이 다르므로 1차/2차가 같은 연차연도에 있으면 2차 통보 이후
    사용분은 양쪽에 모두 들어간다(2차 이후 사용분도 1차 촉구의 결과이므로).
    """
    summ = promo_summary(db, promo, user, as_of)
    if not summ:
        return []
    since = promo.notified_at.date() if promo.notified_at else promo.year_start
    return actual_usage_entries(summ, since=since, until=promo.year_end)


def _date_type_map(entries):
    out = {}
    for e in (entries or []):
        if isinstance(e, dict):
            d, t = e.get('date'), ('반차' if e.get('type') == '반차' else '연차')
        else:
            d, t = str(e), '연차'
        if d:
            out[str(d)[:10]] = t
    return out


def doc_dates_diff(db, promo, user, as_of=None):
    """서면 인쇄용 지정 사용일(admin_dates) vs 이 회차 실제 사용일 대사.

    반환: {'actual','designated','missing','extra','changed','matched',
           'in_sync','has_actual'}
      missing : 실제로 썼는데 서면에 없는 날
      extra   : 서면에 있는데 실제로는 안 쓴 날
      changed : 날짜는 같으나 연차/반차 구분이 다른 날
    """
    actual = actual_for_promo(db, promo, user, as_of)
    designated = normalize_entries(promo.admin_dates)
    # 종료일 미기재 다일 연차 — 날짜를 특정할 수 없어 대사 대상에서 뺀다
    unresolved = [e for e in actual if e.get('unresolved')]
    am, dm = _date_type_map(actual), _date_type_map(designated)
    for e in unresolved:
        am.pop(e['date'], None)
    missing = sorted(set(am) - set(dm))
    extra = sorted(set(dm) - set(am))
    changed = sorted(d for d in (set(am) & set(dm)) if am[d] != dm[d])
    return {
        'actual': actual, 'designated': designated, 'unresolved': unresolved,
        'missing': missing, 'extra': extra, 'changed': changed,
        'matched': sorted(d for d in (set(am) & set(dm)) if am[d] == dm[d]),
        'in_sync': not (missing or extra or changed),
        'has_actual': bool(actual),
    }


def sync_doc_dates_to_actual(db, promo, user, by, as_of=None):
    """서면 인쇄용 지정 사용일을 이 회차 실제 사용일과 일치시킨다.

    직원이 사전에 낸 지정(employee_dates)은 근로기준법상 '근로자의 사용시기
    지정' 증빙이라 건드리지 않는다. status도 바꾸지 않는다(set_status=False).
    반환: (promo, diff_before) — 이미 일치하면 쓰기 없이 (promo, diff) 반환.
    """
    diff = doc_dates_diff(db, promo, user, as_of)
    if diff['in_sync']:
        return promo, diff
    # 날짜 특정 불가분(unresolved)은 제외 — 서면에 지어낸 날짜를 넣지 않는다
    entries = [e for e in diff['actual'] if not e.get('unresolved')]
    set_doc_dates(db, promo.id, entries, by=by, set_status=False)
    return promo, diff


def mark_printed(db, promo_id):
    p = db.get(LeavePromotion, promo_id)
    if p:
        p.printed_at = datetime.datetime.now()
        db.flush()
    return p


def promotions_for_user(db, user_id, leave_year=None):
    """직원 본인의 촉진 이력(셀프 지정 화면용)."""
    q = db.query(LeavePromotion).filter(LeavePromotion.user_id == user_id)
    if leave_year is not None:
        q = q.filter(LeavePromotion.leave_year == leave_year)
    return q.order_by(LeavePromotion.notified_at.desc()).all()


def all_promotions(db, leave_year=None, status=None):
    """관리자 화면 — 전체 촉진 이력. **회수분도 포함**한다(증빙이므로)."""
    q = db.query(LeavePromotion)
    if leave_year is not None:
        q = q.filter(LeavePromotion.leave_year == leave_year)
    if status:
        q = q.filter(LeavePromotion.status == status)
    return q.order_by(LeavePromotion.notified_at.desc()).all()


# ── 자동화: 관리자 명단 알림 + 직원 메일 발송 ──────────────────
SENDER_EMAIL = 'noreply@mgnt.kr'   # 자동발송 전용 공용계정
SENDER_NAME = '매그나텍 자동알림'


def hr_manager_user_ids(db):
    """인사관리(hr) 권한자 user_id 목록 — admin / 임원진 / hr 메뉴 보유 그룹·개인."""
    from modules.models import User, GroupPermission

    def _has_hr(csv):
        return 'hr' in [e.split(':')[0].strip()
                        for e in (csv or '').split(',') if e.strip()]

    hr_groups = {g.group_name for g in db.query(GroupPermission).all()
                 if _has_hr(g.allowed_menus)}
    ids = set()
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        if (u.role == 'admin' or u.user_group == '임원진'
                or u.user_group in hr_groups or _has_hr(u.extra_menus)):
            ids.add(u.id)
    return sorted(ids)


def _employee_email(user):
    """직원 수신 메일 = 회사 메일(username@mgnt.kr)."""
    un = getattr(user, 'username', None)
    if un:
        return f'{un}@mgnt.kr'
    return getattr(user, 'email', None)


def send_promotion_email(db, promo, user):
    """직원에게 연차사용촉진 통보 메일 발송(회사메일). 성공 시 email_sent=True."""
    to_addr = _employee_email(user)
    if not user or not to_addr:
        return False
    from modules.services.email_sender import send_email_with_attachments
    base = (__import__('os').environ.get('ERP_BASE_URL') or 'https://erp.mgnt.kr').rstrip('/')
    due = promo.designate_due.strftime('%Y-%m-%d') if promo.designate_due else '-'
    is_second = (promo.stage == 'second')
    round_label = '2회차(최종)' if is_second else '1회차'
    extra = ('\n기한 내 미지정 시 근로기준법 제61조에 따라 회사가 사용시기를 직접 지정합니다.\n'
             if is_second else
             '\n미지정 시 2회차 촉구 후 회사가 사용시기를 지정할 수 있습니다.\n')
    link = f'{base}/hr/my-promotion'
    body = (
        f"{user.full_name}님,\n\n"
        f"근로기준법 제61조(연차 유급휴가 사용촉진)에 따라 {round_label} 통보드립니다.\n\n"
        f"  · 연차연도: {promo.year_start} ~ {promo.year_end} ({promo.leave_year}년도)\n"
        f"  · 미사용 잔여 연차: {promo.remaining_days}일\n"
        f"  · 사용시기 지정 기한: {due} (통보일로부터 10일)\n"
        f"{extra}\n"
        f"아래 링크에서 연차 사용 예정일을 지정해 주시기 바랍니다.\n\n"
        f"  ▶ 사용시기 지정: {link}\n\n"
        f"(주)매그나텍 인사담당"
    )
    body_html = (
        f'<div style="font-family:Malgun Gothic,sans-serif;font-size:14px;color:#222;line-height:1.7">'
        f'<p>{user.full_name}님,</p>'
        f'<p>근로기준법 제61조(연차 유급휴가 사용촉진)에 따라 <b>{round_label}</b> 통보드립니다.</p>'
        f'<ul style="padding-left:18px">'
        f'<li>연차연도: {promo.year_start} ~ {promo.year_end} ({promo.leave_year}년도)</li>'
        f'<li>미사용 잔여 연차: <b>{promo.remaining_days}일</b></li>'
        f'<li>사용시기 지정 기한: <b>{due}</b> (통보일로부터 10일)</li>'
        f'</ul>'
        f'<p>{extra.strip()}</p>'
        f'<p>아래 버튼에서 연차 사용 예정일을 지정해 주시기 바랍니다.</p>'
        f'<p style="margin:18px 0">'
        f'<a href="{link}" style="display:inline-block;background:#2563eb;color:#fff;'
        f'text-decoration:none;padding:11px 22px;border-radius:6px;font-weight:700">'
        f'사용시기 지정하기</a></p>'
        f'<p style="font-size:12px;color:#888">버튼이 안 보이면 다음 주소로 접속하세요: '
        f'<a href="{link}">{link}</a></p>'
        f'<p style="margin-top:20px">(주)매그나텍 인사담당</p>'
        f'</div>'
    )
    try:
        r = send_email_with_attachments(
            to_email=to_addr,
            subject=f'[연차사용촉진 {round_label}] {promo.leave_year}년도 미사용 연차 사용시기 지정 요청',
            body_text=body, body_html=body_html,
            from_account_email=SENDER_EMAIL, from_name=SENDER_NAME,
        )
        ok = bool(r and r.get('success'))
    except Exception:
        ok = False
    if ok:
        promo.email_sent = True
        promo.channel = 'email'
        db.flush()
    return ok


def run_promotion_cycle(db, as_of=None, do_email=True, do_notify=True, by='system'):
    """촉진 1회 점검 — 대상 산출 → 1차/추가 이력 기록 + 직원 메일/알림 +
    인사관리자 명단 알림. cron/수동 공용. 결과 요약 dict 반환.

    do_email/do_notify=False 면 해당 부수효과를 건너뜀(테스트용).
    """
    from modules.notification_engine import notify

    as_of = as_of or datetime.datetime.now().date()
    cand = candidates(db, as_of)
    out = {'recorded': 0, 'emailed': 0, 'second': 0, 'second_pending': len(cand['second']),
           'names': []}

    # 1회차 + 회사지정 모두 자동 촉구 — stage 는 candidates 가 산출한 것을 쓴다.
    # ('first'/'second' 로 박아두면 1년 미만자의 추가분(extra/extra2)이
    #  1회차로 잘못 기록돼 정작 필요한 회차가 영영 안 나간다)
    rounds = ([c for c in cand['first']] + [c for c in cand['second']])
    for c in rounds:
        u = c['user']
        stage = c['stage']
        p = record_promotion(db, u, c['emp_type'], stage, by=by)
        out['recorded'] += 1
        if stage in ('second', 'extra2'):
            out['second'] += 1
        else:
            out['names'].append(u.full_name)
        if do_email:
            if send_promotion_email(db, p, u):
                out['emailed'] += 1
        # 직원 본인 ERP 인앱 알림 (deep-link)
        if do_notify:
            try:
                notify(db, 'leave.promotion_employee', {
                    'leave_year': p.leave_year,
                    'remaining': p.remaining_days, 'due': (
                        p.designate_due.strftime('%Y-%m-%d') if p.designate_due else '-'),
                }, target_override=['user:%d' % u.id],
                    dedupe_key='lp_emp_%d_%d_%s' % (u.id, p.leave_year, stage))
            except Exception:
                pass

    # 인사관리자 명단 알림
    if do_notify and rounds:
        mgr_ids = hr_manager_user_ids(db)
        from modules import notification_format as nf
        # 0명인 회차는 줄을 아예 빼야 '없음'만 늘어놓은 알림이 안 된다
        detail = nf.body(
            nf.kv('1회차 촉구 %d명' % len(cand['first']),
                  ', '.join(out['names'])),
            nf.kv('2회차 미지정 %d명' % len(cand['second']),
                  ', '.join(c['user'].full_name for c in cand['second'])),
        ) or '대상자 없음'
        try:
            notify(db, 'leave.promotion_admin',
                   {'count': len(cand['first']) + len(cand['second']), 'detail': detail},
                   target_override=['user:%d' % i for i in mgr_ids],
                   dedupe_key='lp_admin_%s' % as_of.isoformat())
        except Exception:
            pass
    return out
