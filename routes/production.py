import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required

from modules.history_board import append_history_log, get_project_history_context
from modules.db_context import get_db
from modules.utils import safe_int
from modules.pagination import make_pagination
from modules.models import (
    Project,
    Contract,
    ContractItem,
    CONTRACT_ITEM_SPEC_SCHEMA,
    normalize_detail_item,
)
from modules.production_logic import (
    sync_production_processes,
    refresh_production_statuses,
)
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)
from modules.services.production_actions import (
    handle_sync_production_processes,
    handle_update_process_status,
    handle_add_daily_log,
    handle_toggle_item_complete,
    handle_toggle_process_active,
    handle_update_process_modal,
    handle_add_chat,
    handle_add_history_reply,
)
from modules.production_display_utils import build_display_cards, build_material_ticker, build_billboard_items, build_schedule_data, fetch_weather

production_bp = Blueprint('production', __name__)


@production_bp.route('/api/weather')
@login_required
def api_weather():
    """날씨 프록시 (서버에서 wttr.in 호출, 10분 캐시)"""
    return jsonify(fetch_weather())


@production_bp.route('/production/display')
@login_required
def production_display():
    """전사 현황판 디스플레이 (TV 전용, Read-Only, 30초 자동갱신)"""
    from modules.models import Delivery

    with get_db() as db:
        today = datetime.date.today()

        contracted_projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(True))
            .options(
                joinedload(Project.contracts)
                    .joinedload(Contract.items)
                    .joinedload(ContractItem.material_orders),
                joinedload(Project.contracts)
                    .joinedload(Contract.items)
                    .joinedload(ContractItem.production_processes),
                joinedload(Project.priority_override),
            )
            .all()
        )

        deliveries = (
            db.query(Delivery)
            .join(Project, Project.id == Delivery.project_id)
            .filter(Project.is_contracted.is_(True))
            .options(joinedload(Delivery.project))
            .all()
        )

        cards = build_display_cards(contracted_projects, deliveries, today)
        ticker = build_material_ticker(db, today)
        billboard = build_billboard_items(db, today)
        schedule = build_schedule_data(db, today)

        # 더미 데이터 테스트: ?test=1
        if request.args.get('test') == '1':
            weekday_names = ['월', '화', '수', '목', '금', '토', '일']
            dummy_ticker = []
            test_materials = [
                ('LED모듈 STA-200', 120, '삼성LED', '세종시청'),
                ('방열판 AL6063', 200, '한국알루미늄', '화성 물류센터'),
                ('렌즈 PMMA 60도', 80, '대한광학', '인천공항 2터미널'),
                ('PCB기판 FR-4', 150, '서울전자', '대전 엑스포공원'),
                ('외주가공 하우징', 40, '금성공업', '파주 산업단지'),
                ('스텐파이프 STS304', 50, '포항스틸', '안산 중앙공원'),
                ('전원장치 200W', 60, '만도전기', '서울숲 공원'),
                ('브라켓 SUS', 100, '대구정밀', '제주 해안도로'),
            ]
            for i, (mat, qty, vendor, proj) in enumerate(test_materials):
                d = today + datetime.timedelta(days=i)
                wd = weekday_names[d.weekday()]
                dummy_ticker.append({
                    'expected_date': f"{d.strftime('%m/%d')}({wd})",
                    'material_name': mat,
                    'quantity': qty,
                    'vendor_name': vendor,
                    'project_name': proj,
                    'is_outsourcing': i == 4,
                })
            ticker = dummy_ticker

            billboard = [
                {'title': '긴급', 'message': '세종시청 STA-200 납기 D-3 — 자재 입고 확인 후 즉시 생산 투입 바랍니다', 'level': 'danger', 'display_seconds': 6},
                {'title': '공지', 'message': '3/22(토) 오전 설비 점검 예정 — 생산라인 A동 09:00~12:00 가동 중단', 'level': 'warning', 'display_seconds': 6},
                {'title': '안내', 'message': '이번 주 금요일 전체 품질회의 14:00 대회의실 — 불량률 개선 현황 공유', 'level': 'info', 'display_seconds': 6},
            ]

            dummy_cards = {
                'negotiation': [
                    {'contract_item_id': 9001, 'project_id': 1, 'project_name': '양주 신도시', 'project_no': 'P2026-031', 'category': '투광등기구', 'model_name': 'STA-400', 'quantity': 60, 'dday': 21, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '스펙 협의중', 'status_admin': '자재확인중', 'status_prod': '자재대기중', 'material_total': 0, 'material_ready': 0, 'material_percent': 0, 'missing_materials': [], 'current_process': None, 'process_percent': 0, 'next_process': None, 'completed_at': None},
                    {'contract_item_id': 9002, 'project_id': 2, 'project_name': '김포 한강공원', 'project_no': 'P2026-032', 'category': '가로등기구', 'model_name': 'ARENA-150', 'quantity': 40, 'dday': 14, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '도면 검토중', 'status_admin': '자재확인중', 'status_prod': '자재대기중', 'material_total': 0, 'material_ready': 0, 'material_percent': 0, 'missing_materials': [], 'current_process': None, 'process_percent': 0, 'next_process': None, 'completed_at': None},
                ],
                'material': [
                    {'contract_item_id': 9003, 'project_id': 3, 'project_name': '화성 물류센터', 'project_no': 'P2026-020', 'category': '투광등기구', 'model_name': 'ARENA-300', 'quantity': 200, 'dday': 12, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고진행중', 'status_prod': '자재대기중', 'material_total': 5, 'material_ready': 3, 'material_percent': 60, 'missing_materials': [{'name': 'LED모듈', 'status': '발주완료', 'expected_date': '03/21', 'is_outsourcing': False, 'outsourcing_status': None}, {'name': '방열판', 'status': '발주대기', 'expected_date': None, 'is_outsourcing': False, 'outsourcing_status': None}], 'current_process': None, 'process_percent': 0, 'next_process': None, 'completed_at': None},
                    {'contract_item_id': 9004, 'project_id': 4, 'project_name': '파주 산업단지', 'project_no': 'P2026-022', 'category': '스텐가로등주', 'model_name': '8M 원형', 'quantity': 50, 'dday': 18, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '발주진행중', 'status_prod': '자재대기중', 'material_total': 4, 'material_ready': 0, 'material_percent': 0, 'missing_materials': [{'name': '스텐파이프', 'status': '발주완료', 'expected_date': '03/25', 'is_outsourcing': False, 'outsourcing_status': None}, {'name': '외주가공 하우징', 'status': '발주완료', 'expected_date': '03/24', 'is_outsourcing': True, 'outsourcing_status': '가공중'}, {'name': '베이스 플레이트', 'status': '발주대기', 'expected_date': None, 'is_outsourcing': False, 'outsourcing_status': None}, {'name': '앙카볼트 세트', 'status': '발주대기', 'expected_date': None, 'is_outsourcing': False, 'outsourcing_status': None}], 'current_process': None, 'process_percent': 0, 'next_process': None, 'completed_at': None},
                ],
                'production_ready': [
                    {'contract_item_id': 9005, 'project_id': 5, 'project_name': '세종시청', 'project_no': 'P2026-015', 'category': '투광등기구', 'model_name': 'STA-200', 'quantity': 120, 'dday': 3, 'is_urgent': True, 'is_priority': True, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고완료', 'status_prod': '생산대기중', 'material_total': 5, 'material_ready': 5, 'material_percent': 100, 'missing_materials': [], 'current_process': None, 'process_percent': 0, 'next_process': None, 'completed_at': None},
                    {'contract_item_id': 9006, 'project_id': 6, 'project_name': '대전 엑스포공원', 'project_no': 'P2026-018', 'category': '보안등기구', 'model_name': 'SEC-100', 'quantity': 80, 'dday': 7, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고완료', 'status_prod': '생산대기중', 'material_total': 6, 'material_ready': 6, 'material_percent': 100, 'missing_materials': [], 'current_process': None, 'process_percent': 0, 'next_process': None, 'completed_at': None},
                ],
                'in_production': [
                    {'contract_item_id': 9007, 'project_id': 7, 'project_name': '인천공항 2터미널', 'project_no': 'P2026-010', 'category': '투광등기구', 'model_name': 'STA-400', 'quantity': 80, 'dday': 5, 'is_urgent': True, 'is_priority': True, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고완료', 'status_prod': '생산중', 'material_total': 8, 'material_ready': 8, 'material_percent': 100, 'missing_materials': [], 'current_process': 'PCB 조립', 'process_percent': 75, 'next_process': '렌즈부 조립', 'completed_at': None},
                    {'contract_item_id': 9008, 'project_id': 8, 'project_name': '서울숲 공원', 'project_no': 'P2026-012', 'category': '가로등기구', 'model_name': 'ARENA-150', 'quantity': 45, 'dday': 10, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고완료', 'status_prod': '생산중', 'material_total': 4, 'material_ready': 4, 'material_percent': 100, 'missing_materials': [], 'current_process': '렌즈부 조립', 'process_percent': 40, 'next_process': '반사판 조립', 'completed_at': None},
                    {'contract_item_id': 9009, 'project_id': 9, 'project_name': '제주 해안도로', 'project_no': 'P2026-008', 'category': '스텐가로등주', 'model_name': '10M 팔각', 'quantity': 20, 'dday': 15, 'is_urgent': False, 'is_priority': False, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고완료', 'status_prod': '생산중', 'material_total': 3, 'material_ready': 3, 'material_percent': 100, 'missing_materials': [], 'current_process': '도장작업', 'process_percent': 60, 'next_process': '브라켓 용접', 'completed_at': None},
                ],
                'delivery': [
                    {'contract_item_id': 9010, 'project_id': 10, 'project_name': '수원역 광장', 'project_no': 'P2026-005', 'category': '투광등기구', 'model_name': 'BATOO-200', 'quantity': 30, 'dday': 1, 'is_urgent': True, 'is_priority': False, 'detail_url': '#', 'status_sales': '협의완료', 'status_admin': '입고완료', 'status_prod': '생산완료', 'material_total': 4, 'material_ready': 4, 'material_percent': 100, 'missing_materials': [], 'current_process': None, 'process_percent': 100, 'next_process': None, 'completed_at': '03/17'},
                ],
            }
            cards = dummy_cards

            # 더미 일정 데이터
            import calendar as calendar_lib
            cal = calendar_lib.Calendar(firstweekday=6)
            dummy_weeks = []
            for week in cal.monthdatescalendar(today.year, today.month):
                cells = []
                for day in week:
                    has = day.day in (3, 5, 10, 15, 19, 22, 25, 28) and day.month == today.month
                    cells.append({
                        'day': day.day, 'in_month': day.month == today.month,
                        'is_today': day == today, 'count': 2 if day.day == 22 else (1 if has else 0),
                        'is_urgent': day.day == 22, 'has_items': has,
                    })
                dummy_weeks.append(cells)
            schedule = {
                'month_label': f"{today.year}.{today.month:02d}",
                'weekdays': ['일', '월', '화', '수', '목', '금', '토'],
                'weeks': dummy_weeks,
                'upcoming': [
                    {'date_str': '03/20(목)', 'day': 20, 'project_name': '세종시청', 'contract_name': 'STA-200 120EA', 'dday': 1},
                    {'date_str': '03/22(토)', 'day': 22, 'project_name': '인천공항 2터미널', 'contract_name': 'STA-400 80EA', 'dday': 3},
                    {'date_str': '03/22(토)', 'day': 22, 'project_name': '화성 물류센터', 'contract_name': 'ARENA-300 200EA', 'dday': 3},
                    {'date_str': '03/25(화)', 'day': 25, 'project_name': '대전 엑스포공원', 'contract_name': 'SEC-100 80EA', 'dday': 6},
                    {'date_str': '03/28(금)', 'day': 28, 'project_name': '서울숲 공원', 'contract_name': 'ARENA-150 45EA', 'dday': 9},
                    {'date_str': '03/31(월)', 'day': 31, 'project_name': '파주 산업단지', 'contract_name': '8M 원형 50본', 'dday': 12},
                ],
            }

        column_meta = [
            {'key': 'negotiation', 'label': '협의현황', 'icon': '\U0001F4AC', 'tone': 'purple'},
            {'key': 'material', 'label': '자재현황', 'icon': '\U0001F4E6', 'tone': 'amber'},
            {'key': 'production_ready', 'label': '생산대기', 'icon': '\u23F3', 'tone': 'blue'},
            {'key': 'in_production', 'label': '생산중', 'icon': '\U0001F527', 'tone': 'green'},
            {'key': 'delivery', 'label': '납품현황', 'icon': '\U0001F69A', 'tone': 'cyan'},
            {'key': 'schedule', 'label': '일정', 'icon': '\U0001F4C5', 'tone': 'indigo'},
        ]

        # AJAX partial update: ?partial=1 → JSON만 반환
        if request.args.get('partial') == '1':
            return jsonify({
                'cards': cards,
                'ticker': ticker,
            })

        return render_template(
            'production_display.html',
            today=today,
            cards=cards,
            ticker=ticker,
            billboard=billboard,
            column_meta=column_meta,
            schedule=schedule,
        )




def _item_progress(item):
    processes = list(item.production_processes or [])
    if not processes:
        return 0.0
    return round(sum(float(p.progress_percent or 0) for p in processes) / len(processes), 2)


BOOLEAN_SPEC_FIELDS = {'has_stabilizer_box', 'is_integrated', 'is_painted'}
SPEC_FIELD_LABELS = {
    'lens_angle': '렌즈각도',
    'spacing_distance': '이격거리',
    'body_type': '일체형/분리형',
    'has_stabilizer_box': '안정기함 유무',
    'stabilizer_vendor_contact': '안정기함 업체 연락처',
    'stabilizer_address': '안정기함 주소',
    'smps_shipment_schedule': 'SMPS 발송 일정',
    'is_integrated': '일체형 여부',
    'tower_height': '조명타워 높이',
    'lamp_count': '등수',
    'replace_or_new': '교체/신설 여부',
    'anchor_spacing': '기초앙카간격',
    'arm_type': '암대타입',
    'is_painted': '도장 여부',
    'paint_color': '도장 색상',
    'stainless_finish_type': '스텐 마감',
}


def _spec_label(field):
    return SPEC_FIELD_LABELS.get(field, field)


def _is_filled_spec_value(field, value):
    if field in BOOLEAN_SPEC_FIELDS:
        return value is not None
    return value not in (None, '', [])


def _required_spec_fields(category, spec):
    category = normalize_detail_item(category, default='투광등기구')
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    fields = list(schema.get('required', []))
    conditional = schema.get('conditional_required', {})
    for trigger, rule in conditional.items():
        expected = rule.get('equals')
        current = spec.get(trigger)
        if current == expected:
            fields.extend(rule.get('fields', []))
    return sorted(set(fields))


def _spec_completion_summary(item):
    spec = dict(item.item_spec or {})
    required_fields = _required_spec_fields(item.category, spec)
    if not required_fields:
        return {'filled': 0, 'total': 0, 'rate': 0, 'missing_fields': []}

    filled = 0
    missing_fields = []
    for field in required_fields:
        if _is_filled_spec_value(field, spec.get(field)):
            filled += 1
        else:
            missing_fields.append(field)
    rate = round((filled / len(required_fields)) * 100) if required_fields else 0
    return {
        'filled': filled,
        'total': len(required_fields),
        'rate': rate,
        'missing_fields': missing_fields,
    }


def _format_spec_value(field, value):
    if value in (None, ''):
        return '-'
    if isinstance(value, bool):
        return '예' if value else '아니오'
    return str(value)


def _sales_summary(item, contract_obj):
    completion = _spec_completion_summary(item)
    spec = dict(item.item_spec or {})
    required_fields = _required_spec_fields(item.category, spec)
    return {
        'status': (item.status_sales or '계약확인'),
        'desired_delivery_date': contract_obj.desired_delivery_date.isoformat() if contract_obj and contract_obj.desired_delivery_date else None,
        'spec_completion': completion,
        'spec_entries': [
            {
                'label': _spec_label(field),
                'value': _format_spec_value(field, spec.get(field)),
                'is_missing': field in completion['missing_fields'],
            }
            for field in required_fields
        ]
    }


def _contract_summary(project_obj, contract_obj, dday):
    return {
        'contract_name': contract_obj.contract_name if contract_obj else '-',
        'contract_date': contract_obj.contract_date.isoformat() if contract_obj and contract_obj.contract_date else None,
        'delivery_due_date': contract_obj.delivery_due_date.isoformat() if contract_obj and contract_obj.delivery_due_date else None,
        'desired_delivery_date': contract_obj.desired_delivery_date.isoformat() if contract_obj and contract_obj.desired_delivery_date else None,
        'is_prof_inspection': bool(contract_obj.is_prof_inspection) if contract_obj else False,
        'is_urgent_prod': bool(contract_obj.is_urgent_prod) if contract_obj else False,
        'is_project_urgent': bool(project_obj.is_urgent),
        'project_site_address': project_obj.site_address or '',
        'project_shipping_address': project_obj.shipping_address or '',
        'design_basis': project_obj.design_basis or '',
        'dday': dday,
    }


def _comparison_warnings(item, contract_obj, dday):
    warnings = []
    sales_status = (item.status_sales or '계약확인').strip()
    prod_status = (item.status_prod or '자재대기중').strip()
    completion = _spec_completion_summary(item)

    for field in completion['missing_fields']:
        warnings.append({
            'level': 'warning',
            'label': f'{_spec_label(field)} 누락',
            'detail': '협의 스펙 필수값이 비어 있습니다.'
        })

    if contract_obj:
        due = contract_obj.delivery_due_date
        desired = contract_obj.desired_delivery_date
        if due and desired and due != desired:
            warnings.append({
                'level': 'danger',
                'label': '납품희망일 불일치',
                'detail': f'계약납기 {due.isoformat()} / 희망납기 {desired.isoformat()}'
            })

    if prod_status in ('생산중', '생산완료') and sales_status != '협의완료':
        warnings.append({
            'level': 'danger',
            'label': '생산 선행 위험',
            'detail': f'영업단계가 {sales_status} 인데 생산상태는 {prod_status} 입니다.'
        })

    if dday is not None and dday < 0 and prod_status != '생산완료':
        warnings.append({
            'level': 'danger',
            'label': '납기 지연',
            'detail': f'D+{-dday} 상태입니다.'
        })
    elif dday is not None and dday <= 7 and prod_status != '생산완료':
        warnings.append({
            'level': 'warning',
            'label': '납기 임박',
            'detail': f'D-{dday} 남았습니다.' if dday > 0 else '오늘이 납기입니다.'
        })

    return warnings


def _panel_payload(project_obj, contract_obj, item, dday):
    return {
        'project_id': project_obj.id,
        'project_no': project_obj.project_no or '-',
        'project_name': project_obj.temp_name or '-',
        'contract_id': contract_obj.id if contract_obj else None,
        'contract_name': contract_obj.contract_name if contract_obj else '-',
        'item_id': item.id,
        'item_category': item.category or '-',
        'item_model_name': item.model_name or '-',
        'item_quantity': int(item.quantity or 0),
        'prod_status': item.status_prod or '자재대기중',
        'prod_progress': item._prod_progress,
        'sales_summary': _sales_summary(item, contract_obj),
        'contract_summary': _contract_summary(project_obj, contract_obj, dday),
        'warnings': _comparison_warnings(item, contract_obj, dday),
        'source_links': {
            'sales': url_for('sales.sales_detail', project_id=project_obj.id) + f'#item-{item.id}',
            'contract': url_for('project.contract_detail', project_id=project_obj.id) + f'#item-{item.id}',
        }
    }


def _project_dday(project_obj, today):
    contracts_sorted = sorted(project_obj.contracts, key=lambda c: c.delivery_due_date or datetime.date.max)
    primary = contracts_sorted[0] if contracts_sorted else None
    due = primary.delivery_due_date if primary else None
    return (due - today).days if due else None


def _project_desired_delivery(project_obj):
    contracts_with_desired = [c for c in (project_obj.contracts or []) if c.desired_delivery_date]
    if not contracts_with_desired:
        return None
    contracts_with_desired.sort(key=lambda c: c.desired_delivery_date)
    return contracts_with_desired[0].desired_delivery_date


ACTION_HANDLERS = {
    'sync_production_processes': handle_sync_production_processes,
    'update_process_status': handle_update_process_status,
    'add_daily_log': handle_add_daily_log,
    'toggle_item_complete': handle_toggle_item_complete,
    'toggle_process_active': handle_toggle_process_active,
    'update_process_modal': handle_update_process_modal,
    'add_chat': handle_add_chat,
    'add_history_reply': handle_add_history_reply,
}

@production_bp.route('/production_management', methods=['GET', 'POST'])
@login_required
def production_management():

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        if request.method == 'POST' and request.form.get('action') == 'sync_production_processes':
            sync_production_processes(db)
            refresh_production_statuses(db)
            first_project = db.query(Project).filter(Project.is_contracted.is_(True)).order_by(Project.id.asc()).first()
            if first_project:
                append_history_log(
                    db,
                    project_id=first_project.id,
                    user_name='시스템 🤖',
                    content=f"{current_user}님이 생산공정 자동생성/동기화를 실행했습니다.",
                    scope='production',
                    kind='system'
                )
            db.commit()
            flash('생산공정 자동생성/동기화가 완료되었습니다.', 'success')
            return redirect(url_for('production.production_management'))

        sync_production_processes(db)
        refresh_production_statuses(db)
        db.commit()

        q = (request.args.get('q') or '').strip().lower()
        status_filter = (request.args.get('status') or 'all').strip()
        due_filter = (request.args.get('due') or 'all').strip()
        sort_by = (request.args.get('sort') or 'due_asc').strip()

        projects = db.query(Project).filter(Project.is_contracted.is_(True)).options(
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.production_processes),
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.material_orders),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        today = datetime.date.today()
        total_items = 0
        waiting_items = 0
        working_items = 0
        done_items = 0

        filtered = []
        for p in projects:
            has_match = False
            p._matched_contracts = []
            p._avg_progress = 0.0
            proj_progress_pool = []

            for c in p.contracts:
                matched_items = []
                for item in c.items:
                    total_items += 1
                    prod_status = (item.status_prod or '').strip() or '자재대기중'
                    if prod_status == '자재대기중':
                        waiting_items += 1
                    elif prod_status == '생산중':
                        working_items += 1
                    elif prod_status == '생산완료':
                        done_items += 1

                    search_pool = ' '.join([
                        p.project_no or '',
                        p.temp_name or '',
                        c.contract_name or '',
                        item.category or '',
                        item.model_name or '',
                        prod_status,
                    ]).lower()

                    if q and q not in search_pool:
                        continue
                    if status_filter != 'all' and prod_status != status_filter:
                        continue

                    item._prod_progress = _item_progress(item)
                    item._spec_completion = _spec_completion_summary(item)
                    proj_progress_pool.append(item._prod_progress)
                    item._panel_payload = _panel_payload(p, c, item, _project_dday(p, today))
                    item._warning_count = len(item._panel_payload['warnings'])
                    matched_items.append(item)

                if matched_items:
                    c._matched_items = matched_items
                    p._matched_contracts.append(c)
                    has_match = True

            p._dday = _project_dday(p, today)
            if due_filter == 'overdue' and (p._dday is None or p._dday >= 0):
                has_match = False
            if due_filter == 'week' and (p._dday is None or p._dday < 0 or p._dday > 7):
                has_match = False
            if due_filter == 'twoweek' and (p._dday is None or p._dday < 0 or p._dday > 14):
                has_match = False

            if has_match:
                p._avg_progress = round(sum(proj_progress_pool) / len(proj_progress_pool), 2) if proj_progress_pool else 0.0
                filtered.append(p)

        if sort_by == 'due_desc':
            filtered.sort(key=lambda p: (p._dday is None, -(p._dday if p._dday is not None else -99999)))
        elif sort_by == 'created_desc':
            filtered.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
        else:
            filtered.sort(key=lambda p: (p._dday is None, p._dday if p._dday is not None else 99999))

        priority_projects = []
        for p in filtered:
            reasons = []
            override = append_manual_priority_reason(reasons, p)
            warning_count = 0
            active_items = 0
            is_urgent_project = bool(p.is_urgent or any(c.is_urgent_prod for c in (p.contracts or [])))

            for c in getattr(p, '_matched_contracts', []) or []:
                for item in getattr(c, '_matched_items', []) or []:
                    warning_count += int(getattr(item, '_warning_count', 0) or 0)
                    if (item.status_prod or '') != '생산완료':
                        active_items += 1

            if is_urgent_project:
                append_priority_reason(reasons, 'urgent')
            append_due_priority_reason(reasons, p._dday, 'production')
            if warning_count > 0:
                append_priority_reason(reasons, 'production_warning', f"경고 {warning_count}건")

            if reasons:
                meta_lines = [
                    f"조회 계약건: {len(getattr(p, '_matched_contracts', []) or [])}건",
                    f"미완료 품목: {active_items}건",
                    f"생산 경고: {warning_count}건",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=p.id,
                    project_no=p.project_no,
                    title=p.temp_name or '-',
                    subtitle=f"평균 공정률: {p._avg_progress}%",
                    detail_url=url_for('production.production_detail', project_id=p.id),
                    reasons=reasons,
                    dday=p._dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)

        page = safe_int(request.args.get('page'), 1)
        per_page = safe_int(request.args.get('per_page'), 20)
        pagination = make_pagination(page, per_page, len(filtered))
        start = (pagination['page'] - 1) * per_page
        projects_page = filtered[start:start + per_page]

        return render_template(
            'production_management.html',
            projects=projects_page,
            priority_projects=priority_projects,
            stats={
                'total_projects': len(projects),
                'filtered_projects': len(filtered),
                'total_items': total_items,
                'waiting_items': waiting_items,
                'working_items': working_items,
                'done_items': done_items,
            },
            pagination=pagination,
            filters={'q': request.args.get('q', ''), 'status': status_filter, 'due': due_filter, 'sort': sort_by}
        )


@production_bp.route('/production_management/<int:project_id>', methods=['GET', 'POST'])
@login_required
def production_detail(project_id):

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        project = db.query(Project).options(
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.production_processes),
            joinedload(Project.contracts)
            .joinedload(Contract.items)
            .joinedload(ContractItem.material_orders)
        ).get(project_id)

        if not project:
            flash('대상을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('production.production_management'))

        if request.method == 'POST':
            action = request.form.get('action')

            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            handler = ACTION_HANDLERS.get(action)
            if handler:
                result = handler(db, project, request.form, current_user)

                if result.get('error'):
                    if is_ajax:
                        return jsonify({'ok': False, 'message': result['error']}), result.get('status_code', 400)
                    flash(result['error'], 'warning')
                    return redirect(url_for('production.production_detail', project_id=project_id))

                db.commit()

                if is_ajax and result.get('ajax_data'):
                    return jsonify(result['ajax_data'])

                if result.get('flash'):
                    flash(*result['flash'])
                for f in result.get('flashes', []):
                    flash(*f)

            return redirect(url_for('production.production_detail', project_id=project_id))

        sync_production_processes(db, project_id=project_id)
        refresh_production_statuses(db, project_id=project_id)
        db.commit()

        for c in project.contracts:
            for item in c.items:
                item._prod_progress = _item_progress(item)
                item._spec_completion = _spec_completion_summary(item)
                item._panel_payload = _panel_payload(project, c, item, _project_dday(project, datetime.date.today()))
                item._warning_count = len(item._panel_payload['warnings'])
                item.production_processes = sorted(item.production_processes or [], key=lambda x: (x.step_order, x.id))
        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope='production',
            limit=300,
        )

        response = render_template(
            'production_detail.html',
            project=project,
            history=history,
            history_counts=history_counts,
            today=datetime.date.today(),
        )
        return response
