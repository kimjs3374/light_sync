import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required, menu_required
from modules.contract_filters import active_contract_filter

from modules.history_board import get_project_history_context
from modules.services.ical_sync import get_leave_events_for_date
from modules.db_context import get_db
from modules.utils import safe_int
from modules.models import (
    Project,
    Contract,
    ContractItem,
)
from modules.production_logic import (
    sync_production_processes,
    refresh_production_statuses,
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
    # service functions
    get_production_management_data,
    enrich_detail_items,
    get_site_list,
    get_site_detail,
    handle_process_toggle,
    handle_process_daily_log,
    handle_process_complete,
)
from modules.production_display_utils import build_display_cards, build_material_ticker, build_billboard_items, build_schedule_data, fetch_weather
from modules.activity import log_activity

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
            .filter(Project.is_contracted.is_(True), active_contract_filter())
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
            .filter(Project.is_contracted.is_(True), active_contract_filter())
            .options(joinedload(Delivery.project))
            .all()
        )

        cards = build_display_cards(contracted_projects, deliveries, today)
        ticker = build_material_ticker(db, today)
        billboard = build_billboard_items(db, today)
        schedule = build_schedule_data(db, today)

        # 더미 데이터 테스트: ?test=1
        if request.args.get('test') == '1':
            cards, ticker, billboard, schedule = _build_test_display_data(today, ticker, billboard, schedule)

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

        today_leaves = get_leave_events_for_date(today)

        return render_template(
            'production_display.html',
            today=today,
            cards=cards,
            ticker=ticker,
            billboard=billboard,
            column_meta=column_meta,
            schedule=schedule,
            today_leaves=today_leaves,
        )


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
@menu_required('production')
def production_management():
    # GET → 새 카드형 메인으로 redirect
    if request.method == 'GET':
        return redirect(url_for('production.production_main'))

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        if request.method == 'POST' and request.form.get('action') == 'sync_production_processes':
            sync_production_processes(db)
            refresh_production_statuses(db)
            first_project = db.query(Project).filter(Project.is_contracted.is_(True)).order_by(Project.id.asc()).first()
            if first_project:
                from modules.history_board import append_history_log
                append_history_log(
                    db,
                    project_id=first_project.id,
                    user_name='시스템 🤖',
                    content=f"{current_user}님이 생산공정 자동생성/동기화를 실행했습니다.",
                    scope='production',
                    kind='system'
                )
            log_activity(db, '생산관리', 'sync', '생산공정 자동생성/동기화 실행', ref_type='ProductionProcess')
            db.commit()
            flash('생산공정 자동생성/동기화가 완료되었습니다.', 'success')
            return redirect(url_for('production.production_management'))

        q = (request.args.get('q') or '').strip().lower()
        status_filter = (request.args.get('status') or 'all').strip()
        due_filter = (request.args.get('due') or 'all').strip()
        sort_by = (request.args.get('sort') or 'due_asc').strip()
        page = safe_int(request.args.get('page'), 1)
        per_page = safe_int(request.args.get('per_page'), 20)

        data = get_production_management_data(db, q, status_filter, due_filter, sort_by, page, per_page)

        return render_template(
            'production_management.html',
            projects=data['projects'],
            priority_projects=data['priority_projects'],
            stats=data['stats'],
            pagination=data['pagination'],
            filters={'q': request.args.get('q', ''), 'status': status_filter, 'due': due_filter, 'sort': sort_by}
        )


@production_bp.route('/production_management/<int:project_id>', methods=['GET', 'POST'])
@login_required
@menu_required('production')
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

        today = datetime.date.today()
        enrich_detail_items(project, today)
        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope='production',
            limit=300,
            user_id=session.get('user_id'),
        )

        return render_template(
            'production_detail.html',
            project=project,
            history=history,
            history_counts=history_counts,
            today=today,
        )


# ===================================================================
# 카드형 생산관리 (재설계)
# ===================================================================

@production_bp.route('/production')
@login_required
@menu_required('production')
def production_main():
    """생산관리 메인 — 현장 목록 (현장 선택 → 상세)"""
    site_id = safe_int(request.args.get('site'), 0) or None

    with get_db() as db:
        today = datetime.date.today()

        if not site_id:
            # 목록 화면: 동기화 생략 (성능 최적화)
            site_list = get_site_list(db, today)
            return render_template(
                'production.html',
                mode='sites',
                site_list=site_list,
                site_id=None,
                today=today.strftime('%Y-%m-%d'),
            )

        # 현장 선택됨 — 해당 현장만 동기화
        sync_production_processes(db, project_id=site_id)
        refresh_production_statuses(db, project_id=site_id)
        db.commit()

        project = db.query(Project).get(site_id)
        if not project:
            flash('현장을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('production.production_main'))

        item_groups, stats, history, history_counts = get_site_detail(db, project, site_id, today)

    return render_template(
        'production.html',
        mode='detail',
        project=project,
        item_groups=item_groups,
        stats=stats,
        site_id=site_id,
        today=today.strftime('%Y-%m-%d'),
        history=history,
        history_counts=history_counts,
    )


# --- AJAX API ---

@production_bp.route('/api/production/process/<int:process_id>/toggle', methods=['POST'])
@login_required
@menu_required('production')
def api_process_toggle(process_id):
    """공정 ON/OFF 토글 (대기↔진행중)"""
    data = request.get_json() or {}
    is_active = data.get('is_active', True)
    off_reason = (data.get('off_reason') or '').strip()
    current_user = session.get('full_name') or '사용자'

    with get_db() as db:
        result, status_code = handle_process_toggle(db, process_id, is_active, off_reason, current_user)
        return jsonify(result), status_code


@production_bp.route('/api/production/process/<int:process_id>/daily-log', methods=['POST'])
@login_required
@menu_required('production')
def api_process_daily_log(process_id):
    """일일 수량 입력"""
    data = request.get_json() or {}
    current_user = session.get('full_name') or '사용자'

    with get_db() as db:
        result, status_code = handle_process_daily_log(db, process_id, data.get('daily_qty'), current_user)
        return jsonify(result), status_code


@production_bp.route('/api/production/process/<int:process_id>/complete', methods=['POST'])
@login_required
@menu_required('production')
def api_process_complete(process_id):
    """공정 완료/완료해제"""
    data = request.get_json() or {}
    complete = data.get('complete', True)
    current_user = session.get('full_name') or '사용자'

    with get_db() as db:
        result, status_code = handle_process_complete(db, process_id, complete, current_user)
        return jsonify(result), status_code


@production_bp.route('/api/production/sync', methods=['POST'])
@login_required
@menu_required('production')
def api_production_sync():
    """전체 공정 동기화"""
    with get_db() as db:
        sync_production_processes(db)
        refresh_production_statuses(db)
        db.commit()
    return jsonify({'ok': True, 'message': '공정 동기화 완료'})


# --- Test display data helper ---

def _build_test_display_data(today, ticker, billboard, schedule):
    """더미 데이터 생성 (?test=1 용)"""
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

    dummy_billboard = [
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
    dummy_schedule = {
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

    return dummy_cards, dummy_ticker, dummy_billboard, dummy_schedule
