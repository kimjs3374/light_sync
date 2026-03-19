"""
전사 현황판 디스플레이 데이터 빌더.
/production/display 에서 사용하는 6컬럼 카드 데이터 + 자재 티커 + 전광판 + 날씨.
"""
import datetime
import logging
import urllib.request
import json as _json

from flask import url_for
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)

import calendar as calendar_lib

from modules.models import (
    MaterialOrder, Contract, ContractItem, Project,
    PurchaseOrder, Vendor, Delivery, DashboardNotice,
)
from modules.dashboard_utils import project_detail_link, days_until


READY_STATUSES = ('입고완료', '재고이용')


def _days_until(target_date, today):
    if not target_date:
        return None
    return (target_date - today).days


def _sort_key(card):
    return (
        not card['is_priority'],
        not card['is_urgent'],
        card['dday'] if card['dday'] is not None else 9999,
        card['project_id'],
    )


def _build_card(item, contract, project, today):
    orders = list(item.material_orders or [])
    total = len(orders)
    ready = sum(1 for o in orders if (o.order_status or '') in READY_STATUSES)
    percent = round(ready / total * 100) if total > 0 else 100

    missing = []
    for o in orders:
        if (o.order_status or '') not in READY_STATUSES:
            missing.append({
                'name': o.material_name or '자재',
                'status': o.order_status or '발주대기',
                'expected_date': o.expected_in_date.strftime('%m/%d') if o.expected_in_date else None,
                'is_outsourcing': bool(o.is_outsourcing),
                'outsourcing_status': o.outsourcing_status,
            })

    processes = sorted(item.production_processes or [], key=lambda p: (p.step_order or 0, p.id))
    current_process = None
    next_process = None
    process_percent = 0
    completed_at = None

    if processes:
        total_pct = sum(float(p.progress_percent or 0) for p in processes)
        process_percent = round(total_pct / len(processes))

        for i, p in enumerate(processes):
            if (p.status or '대기') == '진행중':
                current_process = p.process_name
                if i + 1 < len(processes):
                    next_process = processes[i + 1].process_name
                break

        last = processes[-1]
        if last.completed_at:
            completed_at = last.completed_at.strftime('%m/%d')
        elif all((p.status or '대기') in ('완료', '스킵') for p in processes):
            completed_at = (last.updated_at or datetime.datetime.now()).strftime('%m/%d')

    dday = _days_until(contract.delivery_due_date, today) if contract else None
    priority_override = getattr(project, 'priority_override', None)

    return {
        'project_id': project.id,
        'contract_item_id': item.id,
        'project_name': project.short_name or project.temp_name or '미지정',
        'project_no': project.project_no or '',
        'category': item.category or '',
        'model_name': item.model_name or '',
        'quantity': item.quantity or 0,
        'status_prod': (item.status_prod or '').strip(),
        'status_sales': (item.status_sales or '').strip(),
        'status_admin': (item.status_admin or '').strip(),
        'dday': dday,
        'is_urgent': bool(getattr(project, 'is_urgent', False) or getattr(contract, 'is_urgent_prod', False)),
        'is_priority': bool(priority_override),
        'detail_url': project_detail_link(project),
        'material_total': total,
        'material_ready': ready,
        'material_percent': percent,
        'missing_materials': missing,
        'current_process': current_process,
        'process_percent': process_percent,
        'next_process': next_process,
        'completed_at': completed_at,
    }


def build_display_cards(contracted_projects, deliveries, today):
    columns = {
        'negotiation': [],      # 협의현황 (status_sales != '협의완료')
        'material': [],         # 자재현황 (자재대기중)
        'production_ready': [], # 생산대기
        'in_production': [],    # 생산중
        'delivery': [],         # 납품현황
    }

    # 납품 진행중인 프로젝트 ID 수집
    delivery_project_ids = set()
    for d in (deliveries or []):
        ds = (d.delivery_status or '').strip()
        if ds in ('coordinating', 'in_progress', '납품협의중', '납품진행중'):
            delivery_project_ids.add(d.project_id)

    for project in contracted_projects:
        for contract in (project.contracts or []):
            for item in (contract.items or []):
                card = _build_card(item, contract, project, today)
                sales = card['status_sales']
                prod = card['status_prod']

                # 협의현황: 영업 상태가 협의완료가 아닌 품목
                if sales and sales != '협의완료':
                    columns['negotiation'].append(card)
                    continue

                # 생산완료 → 납품현황 (출고대기/납품진행)
                if prod == '생산완료':
                    columns['delivery'].append(card)
                    continue

                # 자재대기중 → 자재현황
                if prod == '자재대기중':
                    columns['material'].append(card)
                elif prod == '생산대기중':
                    columns['production_ready'].append(card)
                elif prod == '생산중':
                    columns['in_production'].append(card)

    for key in columns:
        columns[key].sort(key=_sort_key)

    return columns


def build_material_ticker(db, today):
    week_later = today + datetime.timedelta(days=7)

    orders = (
        db.query(MaterialOrder)
        .filter(
            MaterialOrder.expected_in_date.isnot(None),
            MaterialOrder.expected_in_date >= today,
            MaterialOrder.expected_in_date <= week_later,
            MaterialOrder.order_status.notin_(READY_STATUSES),
        )
        .options(
            joinedload(MaterialOrder.purchase_order).joinedload(PurchaseOrder.vendor),
            joinedload(MaterialOrder.contract_item)
                .joinedload(ContractItem.contract)
                .joinedload(Contract.project),
        )
        .order_by(MaterialOrder.expected_in_date.asc(), MaterialOrder.id.asc())
        .all()
    )

    weekday_names = ['월', '화', '수', '목', '금', '토', '일']
    result = []
    for o in orders:
        vendor_name = '미지정'
        if o.purchase_order and o.purchase_order.vendor:
            vendor_name = o.purchase_order.vendor.name or '미지정'

        project_name = '미지정'
        if o.contract_item and o.contract_item.contract and o.contract_item.contract.project:
            p = o.contract_item.contract.project
            project_name = p.short_name or p.temp_name or '미지정'

        wd = weekday_names[o.expected_in_date.weekday()]
        result.append({
            'expected_date': f"{o.expected_in_date.strftime('%m/%d')}({wd})",
            'material_name': o.material_name or '자재',
            'quantity': o.quantity or 0,
            'vendor_name': vendor_name,
            'project_name': project_name,
            'is_outsourcing': bool(o.is_outsourcing),
        })

    return result


def build_schedule_data(db, today):
    """캘린더 + 다가오는 일정 데이터."""
    month_start = today.replace(day=1)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1, day=1)

    contracts = (
        db.query(Contract)
        .join(Project, Project.id == Contract.project_id)
        .filter(
            Project.is_contracted.is_(True),
            Contract.delivery_due_date.isnot(None),
            Contract.delivery_due_date >= month_start,
            Contract.delivery_due_date < next_month_start,
        )
        .options(joinedload(Contract.project))
        .order_by(Contract.delivery_due_date.asc(), Contract.id.asc())
        .all()
    )

    # 날짜별 아이템
    items_by_date = {}
    upcoming = []
    for c in contracts:
        if not c.project:
            continue
        dday = days_until(c.delivery_due_date, today)
        entry = {
            'date': c.delivery_due_date,
            'project_name': c.project.short_name or c.project.temp_name or '-',
            'project_no': c.project.project_no or '',
            'contract_name': c.contract_name or '',
            'dday': dday,
        }
        items_by_date.setdefault(c.delivery_due_date, []).append(entry)
        if c.delivery_due_date >= today:
            upcoming.append(entry)

    # 미니 캘린더 (일요일 시작)
    cal = calendar_lib.Calendar(firstweekday=6)
    weeks = []
    for week in cal.monthdatescalendar(today.year, today.month):
        cells = []
        for day in week:
            day_items = items_by_date.get(day, [])
            cells.append({
                'day': day.day,
                'in_month': day.month == today.month,
                'is_today': day == today,
                'count': len(day_items),
                'is_urgent': any((it.get('dday') is not None and it['dday'] <= 3) for it in day_items),
                'has_items': bool(day_items),
            })
        weeks.append(cells)

    weekday_names = ['월', '화', '수', '목', '금', '토', '일']
    upcoming_list = []
    for item in upcoming[:8]:
        wd = weekday_names[item['date'].weekday()]
        upcoming_list.append({
            'date_str': f"{item['date'].strftime('%m/%d')}({wd})",
            'day': item['date'].day,
            'project_name': item['project_name'],
            'contract_name': item['contract_name'],
            'dday': item['dday'],
        })

    return {
        'month_label': f"{today.year}.{today.month:02d}",
        'weekdays': ['일', '월', '화', '수', '목', '금', '토'],
        'weeks': weeks,
        'upcoming': upcoming_list,
    }


def build_billboard_items(db, today):
    """전광판 공지 데이터 (대시보드와 동일 소스)."""
    from modules.services.dashboard_actions import get_dashboard_setting_int
    from modules.dashboard_utils import build_auto_alert_items

    week_later = today + datetime.timedelta(days=7)
    global_seconds = max(2, get_dashboard_setting_int(db, 'billboard_global_seconds', 6))

    manual_notices = (
        db.query(DashboardNotice)
        .filter(DashboardNotice.is_active.is_(True))
        .order_by(DashboardNotice.sort_order.asc(), DashboardNotice.id.asc())
        .all()
    )

    items = []
    for n in manual_notices:
        items.append({
            'title': n.title or '공지',
            'message': n.message,
            'level': n.level or 'info',
            'display_seconds': global_seconds,
        })

    for b in build_auto_alert_items(db, today, week_later):
        items.append({
            'title': b['label'],
            'message': b['message'],
            'level': b['level'],
            'display_seconds': global_seconds,
        })

    if not items:
        items.append({
            'title': '정상',
            'message': '현재 전광판 알림이 없습니다. 정상 운영 중입니다.',
            'level': 'info',
            'display_seconds': global_seconds,
        })

    return items


# ── 날씨 (서버 사이드, 10분 캐시, 광주 기준 — 장성 인접) ──

_weather_cache = {'data': None, 'fetched_at': None}
_WEATHER_ICONS = {
    '113': '☀️', '116': '⛅', '119': '☁️', '122': '☁️',
    '143': '🌫️', '176': '🌦️', '179': '🌨️', '182': '🌨️',
    '200': '⛈️', '227': '🌨️', '230': '❄️', '248': '🌫️',
    '263': '🌦️', '266': '🌧️', '293': '🌦️', '296': '🌧️',
    '299': '🌧️', '302': '🌧️', '305': '🌧️', '308': '🌧️',
    '323': '🌨️', '326': '🌨️', '329': '❄️', '332': '❄️',
    '335': '❄️', '338': '❄️', '353': '🌦️', '356': '🌧️',
    '386': '⛈️', '389': '⛈️', '395': '❄️',
}
_WEATHER_DESC_KO = {
    'Sunny': '맑음', 'Clear': '맑음', 'Partly cloudy': '구름조금',
    'Cloudy': '흐림', 'Overcast': '흐림', 'Mist': '안개',
    'Fog': '안개', 'Freezing fog': '결빙안개',
    'Patchy rain possible': '비 가능', 'Patchy rain nearby': '비 가능',
    'Light rain': '약한비', 'Moderate rain': '비', 'Heavy rain': '강한비',
    'Light rain shower': '소나기', 'Moderate or heavy rain shower': '강한소나기',
    'Thundery outbreaks possible': '뇌우 가능',
    'Patchy light rain with thunder': '뇌우', 'Moderate or heavy rain with thunder': '강한뇌우',
    'Light snow': '약한눈', 'Moderate snow': '눈', 'Heavy snow': '폭설',
    'Patchy snow possible': '눈 가능', 'Light snow showers': '소낙눈',
    'Blizzard': '눈보라', 'Blowing snow': '눈날림',
    'Patchy light drizzle': '이슬비', 'Light drizzle': '이슬비',
    'Freezing drizzle': '결빙이슬비',
    'Patchy light snow': '약한눈', 'Light sleet': '진눈깨비',
    'Moderate or heavy sleet': '강한진눈깨비',
}


def _parse_desc(raw_desc_list):
    """영어 날씨 설명을 한글로 변환."""
    if not raw_desc_list:
        return ''
    en = raw_desc_list[0].get('value', '').strip()
    return _WEATHER_DESC_KO.get(en, en)


def fetch_weather():
    """광주(장성 인접) 현재 날씨 + 3일 예보. 10분 캐시."""
    now = datetime.datetime.now()

    if (_weather_cache['data'] is not None
            and _weather_cache['fetched_at'] is not None
            and (now - _weather_cache['fetched_at']).total_seconds() < 600):
        return _weather_cache['data']

    fallback = {
        'icon': '🌤️', 'temp': '--', 'feels': '--', 'humidity': '--',
        'desc': '', 'location': '장성',
        'forecast': [],
    }

    try:
        url = 'https://wttr.in/Gwangju?format=j1'
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = _json.loads(resp.read().decode('utf-8'))

        inner = raw.get('data', raw)
        cur = (inner.get('current_condition') or [{}])[0]
        code = cur.get('weatherCode', '116')
        temp_c = cur.get('temp_C', '--')
        feels = cur.get('FeelsLikeC', temp_c)
        humidity = cur.get('humidity', '--')
        desc = _parse_desc(cur.get('weatherDesc', []))

        weekday_names = ['월', '화', '수', '목', '금', '토', '일']
        forecast = []
        for day in (inner.get('weather') or [])[:3]:
            date_str = day.get('date', '')
            max_t = day.get('maxtempC', '--')
            min_t = day.get('mintempC', '--')
            hourly = day.get('hourly', [])
            noon = hourly[4] if len(hourly) > 4 else (hourly[0] if hourly else {})
            day_code = noon.get('weatherCode', '116')
            day_desc = _parse_desc(noon.get('weatherDesc', []))

            wd_label = ''
            try:
                dt = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                wd_label = weekday_names[dt.weekday()]
            except (ValueError, TypeError):
                pass

            forecast.append({
                'date': date_str,
                'weekday': wd_label,
                'icon': _WEATHER_ICONS.get(day_code, '🌤️'),
                'desc': day_desc,
                'max': max_t,
                'min': min_t,
            })

        result = {
            'icon': _WEATHER_ICONS.get(code, '🌤️'),
            'temp': temp_c,
            'feels': feels,
            'humidity': humidity,
            'desc': desc,
            'location': '장성',
            'forecast': forecast,
        }
        _weather_cache['data'] = result
        _weather_cache['fetched_at'] = now
        return result
    except Exception as e:
        logger.debug('날씨 조회 실패: %s', e)
        if _weather_cache['data'] is not None:
            return _weather_cache['data']
        return fallback
