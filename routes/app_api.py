"""
모바일 앱 전용 JSON API
- 기존 웹 화면에 영향 없음
- /api/app/ 접두사
- 토큰 인증 (앱용)
"""
import datetime
import json
import time
import bcrypt
from flask import Blueprint, jsonify, request, session, make_response, current_app
from functools import wraps
from modules.db_context import get_db
from modules.contract_filters import active_contract_filter
from modules.auth_decorators import (
    make_app_token,
    verify_app_token,
    compute_user_permissions,
)
from modules.models import (
    User, GroupPermission, UserPriorityPermission, Project, HistoryLog,
    Notification, G2bProcurement, Contract, ContractItem,
    PurchaseOrder, PurchaseOrderItem, ActivityLog,
    Delivery, MaterialOrder, Receiving, ReceivingPhotoPost,
    Item, Vendor, Quotation, WarrantyCase, Warranty,
    ProcessingOrder, TaxInvoice, Certification, BomHeader,
    Drawing, DrawingVersion, BusinessTrip, BusinessTripMember,
    Tool, ProjectPhoto, StockMovement,
    BomItem, QuotationItem, DeliverySplit, ProcessingOrderItem,
    Contact, Material, DeliverySplit, DeliverySplitItem, DeliveryPhoto,
)
from modules.models.constants import DETAIL_ITEM_OPTIONS
from modules.models.document_entities import DocumentPackage
from modules.activity import log_activity
from config import MENU_REGISTRY, COMMON_MENU_KEYS
from sqlalchemy import desc, func, extract
from sqlalchemy.orm import joinedload

app_api_bp = Blueprint('app_api', __name__, url_prefix='/api/app')


# ── 토큰 유틸 (modules.auth_decorators 로 이동, 하위 호환 alias 유지) ──

_make_token = make_app_token
_verify_token = verify_app_token


def app_auth_required(f):
    """앱 토큰 인증 데코레이터 — 모바일 전용 엔드포인트(PC 세션 허용 안 함)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ok=False, error='로그인이 필요합니다'), 401
        token = auth_header[7:]
        user_id = verify_app_token(token)
        if not user_id:
            return jsonify(ok=False, error='세션이 만료되었습니다. 다시 로그인해주세요'), 401
        request._app_user_id = user_id
        return f(*args, **kwargs)
    return decorated


@app_api_bp.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


@app_api_bp.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    resp = make_response()
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp


@app_api_bp.route('/webview-auth')
def webview_auth():
    """WebView 자동 로그인 — 토큰으로 세션 생성 후 리다이렉트"""
    from flask import redirect
    token = request.args.get('token', '')
    next_url = request.args.get('next', '/dashboard')
    user_id = verify_app_token(token)
    if not user_id:
        return redirect('/login')
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user or not user.is_approved:
            return redirect('/login')
        session.update(compute_user_permissions(db, user))
    return redirect(next_url)


@app_api_bp.route('/session-token')
def app_session_token():
    """PC↔모바일 로그인 공유: PC 세션 쿠키로 로그인된 사용자에게 모바일 앱 토큰을 발급.

    SPA 부트스트랩에서 localStorage 토큰이 없을 때 호출 → PC에서 이미 로그인했다면
    재로그인 없이 모바일 토큰을 받아 그대로 진입한다. 동일 출처 요청이라 세션 쿠키가
    자동 전송된다. 세션이 없으면 401 → SPA 가 /m/login 으로 보낸다.
    """
    if 'user_id' not in session:
        return jsonify(ok=False, error='세션이 없습니다'), 401
    with get_db() as db:
        user = db.query(User).get(session['user_id'])
        if not user or not user.is_approved or user.is_active is False:
            return jsonify(ok=False, error='유효하지 않은 사용자입니다'), 401
        perms = compute_user_permissions(db, user)
        token = make_app_token(user.id)
        return jsonify(ok=True, token=token, user={
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'group': user.user_group,
            'role': user.role,
            'position': user.position or '',
            'allowed_menus': perms['allowed_menus'],
            'writable_menus': perms['writable_menus'],
            'hide_financial': perms['hide_financial'],
        })


@app_api_bp.route('/logout', methods=['POST'])
def app_logout():
    """로그아웃 통합: 모바일에서 로그아웃 시 PC 세션 쿠키도 함께 제거한다.

    SPA 는 이 호출 후 localStorage 토큰을 비운다 → 동일 브라우저에서 모바일·PC
    양쪽 세션이 모두 종료된다.
    """
    session.clear()
    resp = jsonify(ok=True)
    resp.delete_cookie('session')
    return resp


@app_api_bp.route('/login', methods=['POST'])
def app_login():
    """앱 로그인 — 토큰 발급"""
    data = request.get_json(silent=True) or {}
    login_id = data.get('username', '').strip()
    login_pw = data.get('password', '')

    if not login_id or not login_pw:
        return jsonify(ok=False, error='아이디와 비밀번호를 입력해주세요'), 400

    with get_db() as db:
        user = db.query(User).filter(User.username == login_id).first()
        if not user or not bcrypt.checkpw(login_pw.encode('utf-8'), user.password_hash.encode('utf-8')):
            return jsonify(ok=False, error='아이디 또는 비밀번호가 올바르지 않습니다'), 401

        if not user.is_approved:
            return jsonify(ok=False, error='승인 대기 중입니다. 관리자에게 문의하세요'), 403
        if user.is_active is False:
            return jsonify(ok=False, error='비활성화된 계정입니다. 관리자에게 문의하세요'), 403

        perms = compute_user_permissions(db, user)
        token = make_app_token(user.id)

        # PC↔모바일 로그인 공유: 모바일 로그인 시 PC 세션 쿠키도 함께 발급한다.
        # app_login 은 Bearer 요청이 아니므로(g.token_auth 미설정) TokenAwareSessionInterface
        # 가 응답에 세션 쿠키를 정상 발급 → 이후 동일 출처의 PC 페이지 이동이 자동 로그인된다.
        session.update(perms)
        session.permanent = True

        return jsonify(ok=True, token=token, user={
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'group': user.user_group,
            'role': user.role,
            'position': user.position or '',
            'allowed_menus': perms['allowed_menus'],
            'writable_menus': perms['writable_menus'],
            'hide_financial': perms['hide_financial'],
        })


# ── 대시보드 ──

@app_api_bp.route('/dashboard')
@app_auth_required
def app_dashboard():
    """앱 대시보드 — KPI + 워크플로우 + 캘린더 + 입고예정 통합"""
    with get_db() as db:
        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)
        weekdays = ['월', '화', '수', '목', '금', '토', '일']

        # ── KPI ──
        contracted_count = db.query(Project).filter(
            Project.is_contracted.is_(True), active_contract_filter()
        ).count()

        active_project_ids = [
            pid for (pid,) in db.query(Project.id).filter(
                Project.is_contracted.is_(True), active_contract_filter()
            ).all()
        ]

        urgent_delivery_count = db.query(Contract).join(
            Project, Project.id == Contract.project_id
        ).filter(
            Project.is_contracted.is_(True),
            Contract.delivery_due_date.isnot(None),
            Contract.delivery_due_date >= today,
            Contract.delivery_due_date <= week_later,
        ).count()

        overdue_count = 0
        if active_project_ids:
            overdue_count = db.query(Contract.project_id).join(
                ContractItem, ContractItem.contract_id == Contract.id
            ).filter(
                Contract.project_id.in_(active_project_ids),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date < today,
                ContractItem.status_prod != '생산완료',
            ).distinct().count()

        pending_users = db.query(User).filter(
            User.is_approved.is_(False)
        ).count()

        # ── 워크플로우 단계별 카운트 ──
        workflow = []
        if active_project_ids:
            contracts = db.query(Contract).options(
                joinedload(Contract.items)
            ).filter(
                Contract.project_id.in_(active_project_ids)
            ).all()

            stage_counts = {'영업/설계': 0, '자재확인': 0, '생산중': 0, '출고대기': 0, '납품완료': 0}
            for c in contracts:
                for item in c.items:
                    sp = getattr(item, 'status_prod', '') or ''
                    sa = getattr(item, 'status_admin', '') or ''
                    if sp in ('생산완료', '출고완료'):
                        stage_counts['출고대기'] += 1
                    elif sp in ('생산중', '생산대기'):
                        stage_counts['생산중'] += 1
                    elif sa in ('자재확보', '발주완료', '입고완료'):
                        stage_counts['자재확인'] += 1
                    else:
                        stage_counts['영업/설계'] += 1

            tones = {'영업/설계': 'primary', '자재확인': 'warning', '생산중': 'info', '출고대기': 'success'}
            for stage, count in stage_counts.items():
                if stage == '납품완료':
                    continue
                workflow.append({'title': stage, 'count': count, 'tone': tones.get(stage, 'primary')})

        # ── 납품 캘린더 (다가오는 일정 10개) ──
        upcoming = []
        if active_project_ids:
            rows = db.query(Contract).join(
                Project, Project.id == Contract.project_id
            ).filter(
                Contract.project_id.in_(active_project_ids),
                Contract.delivery_due_date.isnot(None),
                Contract.delivery_due_date >= today,
            ).order_by(Contract.delivery_due_date).limit(10).all()

            for c in rows:
                p = c.project
                dday = (c.delivery_due_date - today).days
                upcoming.append({
                    'project_id': c.project_id,
                    'project_name': getattr(p, 'short_name', '') or p.temp_name if p else '',
                    'contract_name': getattr(c, 'contract_name', '') or '',
                    'delivery_date': str(c.delivery_due_date),
                    'dday': dday,
                })

        # ── 입고예정 통계 ──
        _base = db.query(PurchaseOrderItem).join(
            PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id
        ).filter(
            PurchaseOrder.status.in_(['발송완료', '입고대기']),
            (PurchaseOrderItem.in_confirmed == False) | (PurchaseOrderItem.in_confirmed.is_(None)),
        )
        _has_date = _base.filter(PurchaseOrderItem.expected_in_date.isnot(None))
        receiving = {
            'overdue': _has_date.filter(PurchaseOrderItem.expected_in_date < today).count(),
            'today': _has_date.filter(PurchaseOrderItem.expected_in_date == today).count(),
            'this_week': _has_date.filter(
                PurchaseOrderItem.expected_in_date >= today,
                PurchaseOrderItem.expected_in_date <= week_later,
            ).count(),
            'unknown': _base.filter(PurchaseOrderItem.expected_in_date.is_(None)).count(),
        }

        # ── 타임라인 (최근 활동) ──
        timeline = []
        try:
            acts = db.query(ActivityLog).order_by(desc(ActivityLog.created_at)).limit(20).all()
            for a in acts:
                timeline.append({
                    'time': a.created_at.strftime('%m/%d %H:%M') if a.created_at else '',
                    'user': getattr(a, 'user_name', '') or '',
                    'text': getattr(a, 'summary', '') or '',
                    'site': getattr(a, 'ref_label', '') or '',
                    'scope': getattr(a, 'module', '') or 'common',
                })
        except Exception:
            pass
        try:
            logs = db.query(HistoryLog).options(
                joinedload(HistoryLog.project)
            ).order_by(desc(HistoryLog.created_at)).limit(20).all()
            for h in logs:
                timeline.append({
                    'time': h.created_at.strftime('%m/%d %H:%M') if h.created_at else '',
                    'user': getattr(h, 'user_name', '') or '',
                    'text': h.content or '',
                    'site': (h.project.temp_name if h.project else ''),
                    'scope': getattr(h, 'log_scope', '') or 'common',
                })
        except Exception:
            pass
        timeline.sort(key=lambda x: x['time'], reverse=True)
        timeline = timeline[:30]

        # ── 오늘 부재 ──
        today_leaves = []
        try:
            from modules.services.ical_sync import get_leave_events_for_date
            leaves = get_leave_events_for_date(today)
            today_leaves = [{'name': l.get('name', ''), 'type': l.get('leave_type', '')} for l in leaves]
        except Exception:
            pass

        return jsonify(ok=True,
            today=today.strftime('%Y.%m.%d'),
            weekday=weekdays[today.weekday()],
            kpi={
                'contracted': contracted_count,
                'urgent_delivery': urgent_delivery_count,
                'overdue': overdue_count,
                'pending_users': pending_users,
            },
            workflow=workflow,
            upcoming=upcoming,
            receiving=receiving,
            timeline=timeline,
            today_leaves=today_leaves,
        )


# ── 현장 ──

@app_api_bp.route('/projects')
@app_auth_required
def app_projects():
    """현장 목록 (완료건 제외)"""
    status = request.args.get('status', '계약')
    with get_db() as db:
        q = db.query(Project)
        if status:
            q = q.filter(Project.status == status)
        if status == '계약':
            q = q.filter(Project.is_contracted.is_(True), active_contract_filter())
        q = q.order_by(desc(Project.id))
        projects = q.limit(100).all()
        # 계약 일괄 로딩 (N+1 방지)
        project_ids = [p.id for p in projects]
        contracts_map = {}
        if project_ids:
            all_contracts = db.query(Contract).filter(
                Contract.project_id.in_(project_ids)
            ).order_by(Contract.delivery_due_date).all()
            for c in all_contracts:
                if c.project_id not in contracts_map:
                    contracts_map[c.project_id] = c  # 첫 번째(납기 빠른) 계약
        # G2B 조달내역 일괄 로딩
        g2b_nos = [c.g2b_contract_no for c in contracts_map.values() if c.g2b_contract_no]
        g2b_map = {}
        if g2b_nos:
            for g in db.query(G2bProcurement).filter(G2bProcurement.cntrct_dlvr_req_no.in_(g2b_nos)).all():
                g2b_map[g.cntrct_dlvr_req_no] = g

        result = []
        for p in projects:
            contract = contracts_map.get(p.id)
            g2b = g2b_map.get(contract.g2b_contract_no) if contract and contract.g2b_contract_no else None
            result.append({
                'id': p.id,
                'name': p.temp_name or '',
                'short_name': p.short_name or '',
                'project_no': p.project_no or '',
                'contract_name': (contract.contract_name if contract else '') or '',
                'status': p.status or '',
                'is_contracted': bool(p.is_contracted),
                'is_urgent': bool(p.is_urgent),
                'delivery_date': str(contract.delivery_due_date) if contract and contract.delivery_due_date else '',
                'payment_status': (contract.payment_status if contract else '') or '',
                'address': p.site_address or '',
                'ordering_org': (g2b.dminstt_nm if g2b else '') or '',
                'contract_amount': (g2b.prdct_amt if g2b else 0) or 0,
            })
        return jsonify(ok=True, projects=result)


@app_api_bp.route('/projects/<int:project_id>')
@app_auth_required
def app_project_detail(project_id):
    """현장 상세 — 설계관리/계약관리 공통 상세"""
    with get_db() as db:
        project = db.query(Project).options(
            joinedload(Project.materials),
            joinedload(Project.contacts),
            joinedload(Project.drawings).joinedload(Drawing.versions),
        ).get(project_id)
        if not project:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404

        # 계약 정보
        contracts = db.query(Contract).filter(
            Contract.project_id == project_id
        ).all()
        contract_list = []
        for c in contracts:
            items = []
            for item in (c.items or []):
                items.append({
                    'id': item.id,
                    'category': item.category or '',
                    'model_name': item.model_name or '',
                    'quantity': item.quantity or 0,
                    'status_sales': item.status_sales or '',
                    'status_admin': item.status_admin or '',
                    'status_prod': item.status_prod or '',
                })
            g2b = None
            if c.g2b_contract_no:
                g2b = db.query(G2bProcurement).filter(
                    G2bProcurement.cntrct_dlvr_req_no == c.g2b_contract_no
                ).first()
            contract_list.append({
                'id': c.id,
                'contract_name': c.contract_name or '',
                'g2b_contract_no': c.g2b_contract_no or '',
                'delivery_due_date': str(c.delivery_due_date) if c.delivery_due_date else '',
                'contract_date': str(c.contract_date) if c.contract_date else '',
                'payment_status': c.payment_status or '미청구',
                'is_excluded': bool(c.is_excluded),
                'ordering_org': (g2b.dminstt_nm if g2b else '') or '',
                'contract_amount': (g2b.prdct_amt if g2b else 0) or 0,
                'items': items,
            })

        # 히스토리
        logs = db.query(HistoryLog).filter(
            HistoryLog.project_id == project_id
        ).order_by(desc(HistoryLog.created_at)).limit(50).all()
        history = [{
            'id': h.id,
            'user_name': h.user_name or '',
            'content': h.content or '',
            'scope': h.log_scope or '',
            'kind': h.log_kind or 'system',
            'created_at': h.created_at.strftime('%m/%d %H:%M') if h.created_at else '',
        } for h in logs]

        # 자재 (설계 반영)
        materials = [{
            'id': m.id,
            'category': m.category or '',
            'model_name': m.model_name or '',
            'quantity': m.quantity or '',
        } for m in (project.materials or [])]

        # 컨택트
        contacts = [{
            'id': ct.id,
            'category': ct.category or '',
            'name': ct.name or '',
            'phone': ct.phone or '',
            'email': ct.email or '',
        } for ct in (project.contacts or [])]

        # 도면 (버전 정보 포함)
        drawings = []
        for d in (project.drawings or []):
            latest = None
            for v in (d.versions or []):
                if v.is_latest:
                    latest = v
                    break
            if not latest and d.versions:
                latest = d.versions[0]
            drawings.append({
                'id': d.id,
                'title': d.title or '',
                'drawing_type': d.drawing_type or '',
                'created_by': d.created_by or '',
                'version_count': len(d.versions or []),
                'latest_version_no': latest.version_no if latest else 0,
                'convert_status': latest.convert_status if latest else '',
            })

        # 조도 기구 목록
        illuminance_fixtures = []
        if project.illuminance_fixtures:
            try:
                illuminance_fixtures = json.loads(project.illuminance_fixtures)
            except Exception:
                illuminance_fixtures = []

        first_contract = db.query(Contract).filter(Contract.project_id == project_id).first()

        return jsonify(ok=True,
            project={
                'id': project.id,
                'name': project.temp_name or '',
                'temp_name': project.temp_name or '',
                'short_name': project.short_name or '',
                'project_no': project.project_no or '',
                'status': project.status or '',
                'address': project.site_address or '',
                'site_address': project.site_address or '',
                'shipping_address': project.shipping_address or '',
                'site_memo': project.site_memo or '',
                'design_basis': project.design_basis or '',
                'work_path': project.work_path or '',
                'illuminance_facility_type': project.illuminance_facility_type or '',
                'expected_contract_date': project.expected_contract_date.strftime('%Y-%m-%d') if project.expected_contract_date else '',
                'contract_name': (first_contract.contract_name if first_contract else '') or '',
                'is_contracted': bool(project.is_contracted),
            },
            contracts=contract_list,
            history=history,
            materials=materials,
            contacts=contacts,
            drawings=drawings,
            illuminance_fixtures=illuminance_fixtures,
            detail_item_options=DETAIL_ITEM_OPTIONS,
        )


@app_api_bp.route('/projects/<int:project_id>/action', methods=['POST'])
@app_auth_required
def app_project_action(project_id):
    """현장 상세 편집 — 웹 ERP의 handle_detail_common과 동일 action 디스패치"""
    from modules.services.project_actions import (
        handle_update_design_basis, handle_update_project, handle_update_work_path,
        handle_update_material,
    )
    from modules.services.contact_actions import (
        handle_add_contact, handle_update_contact, handle_delete_contact,
        handle_add_material,
    )
    from modules.services.contract_actions import handle_delete_material
    from modules.history_board import append_history_log

    data = request.get_json(silent=True) or {}
    action = data.get('action', '')

    ACTIONS = {
        'update_project': handle_update_project,
        'update_design_basis': handle_update_design_basis,
        'update_work_path': handle_update_work_path,
        'add_material': handle_add_material,
        'update_material': handle_update_material,
        'delete_material': handle_delete_material,
        'add_contact': handle_add_contact,
        'update_contact': handle_update_contact,
        'delete_contact': handle_delete_contact,
    }

    handler = ACTIONS.get(action)
    if not handler:
        return jsonify(ok=False, error=f'알 수 없는 action: {action}'), 400

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 401
        current_user = f"{user.full_name} {user.position or ''}".strip()

        project = db.query(Project).get(project_id)
        if not project:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404

        page_scope = 'contract' if project.is_contracted else 'design'
        ctx = {
            'page_scope': page_scope,
            'user_id': user_id,
            'user_group': user.user_group or '',
            'role': user.role if hasattr(user, 'role') else '',  # User.role 존재 검증은 런타임 안전
            'can_manage_priority': False,
            'files': {},
        }
        try:
            result = handler(db, project, data, current_user, **ctx)
            db.commit()
            return jsonify(ok=True, action=action, flash=result.get('flash'))
        except Exception as e:
            db.rollback()
            current_app.logger.exception('app_project_action failed action=%s project=%s', action, project_id)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/projects/<int:project_id>/convert-to-contract', methods=['POST'])
@app_auth_required
def app_project_convert_to_contract(project_id):
    """설계관리 → 계약관리 전환 (웹 convert_to_contract와 동일)"""
    from collections import defaultdict
    from modules.history_board import append_history_log
    from modules.utils import safe_int
    from modules.models import normalize_detail_item

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 401
        current_user = f"{user.full_name} {user.position or ''}".strip()
        if (user.user_group or '') == '생산부':
            return jsonify(ok=False, error='생산부는 계약 전환 권한이 없습니다'), 403

        p = db.query(Project).options(joinedload(Project.materials)).get(project_id)
        if not p:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404
        if p.is_contracted:
            return jsonify(ok=False, error='이미 계약 현장으로 전환된 건입니다'), 400

        try:
            p.is_contracted = True
            p.contract_date = datetime.date.today()
            if not p.contracts:
                grouped = defaultdict(list)
                for mat in p.materials:
                    group_key = normalize_detail_item(mat.category, default=DETAIL_ITEM_OPTIONS[0])
                    grouped[group_key].append(mat)
                if grouped:
                    for group_name, mats in grouped.items():
                        new_c = Contract(
                            project_id=project_id,
                            contract_name=f"{p.temp_name} - {group_name}",
                            item_group=group_name,
                            contract_date=datetime.date.today(),
                            delivery_due_date=datetime.date.today() + datetime.timedelta(days=30)
                        )
                        db.add(new_c)
                        db.flush()
                        for mat in mats:
                            db.add(ContractItem(
                                contract_id=new_c.id,
                                category=group_name,
                                model_name=mat.model_name,
                                quantity=safe_int(mat.quantity, 0)
                            ))
                else:
                    db.add(Contract(
                        project_id=project_id,
                        contract_name=f"{p.temp_name} 기본 계약",
                        item_group=DETAIL_ITEM_OPTIONS[0],
                        contract_date=datetime.date.today(),
                        delivery_due_date=datetime.date.today() + datetime.timedelta(days=30)
                    ))
            append_history_log(
                db, project_id=project_id, user_name="시스템 🤖",
                content=f"{current_user}님이 계약 현장으로 전환하였습니다. (품목군별 자동 분리 적용)",
                scope='contract', kind='system'
            )
            db.commit()
            return jsonify(ok=True)
        except Exception as e:
            db.rollback()
            current_app.logger.exception('app convert_to_contract failed project=%s', project_id)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/projects/<int:project_id>/delete-request', methods=['POST'])
@app_auth_required
def app_project_delete_request(project_id):
    """삭제요청 접수 (웹 project_delete_request와 동일)"""
    from modules.models import ProjectDeleteRequest
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify(ok=False, error='삭제 사유는 필수입니다'), 400

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 401
        if (user.user_group or '') == '생산부':
            return jsonify(ok=False, error='생산부는 삭제요청 권한이 없습니다'), 403

        p = db.query(Project).get(project_id)
        if not p:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404

        exists_pending = db.query(ProjectDeleteRequest).filter(
            ProjectDeleteRequest.project_id == project_id,
            ProjectDeleteRequest.status == 'PENDING'
        ).first()
        if exists_pending:
            return jsonify(ok=False, error='이미 대기중인 삭제요청이 있습니다'), 400

        try:
            db.add(ProjectDeleteRequest(
                project_id=project_id,
                project_no_snapshot=p.project_no,
                project_name_snapshot=p.temp_name,
                requester_id=user_id,
                requester_name=user.full_name or '사용자',
                requester_group=(user.user_group or '-'),
                request_reason=reason,
                status='PENDING'
            ))
            db.commit()
            return jsonify(ok=True)
        except Exception as e:
            db.rollback()
            current_app.logger.exception('app delete_request failed project=%s', project_id)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/projects/<int:project_id>/comment', methods=['POST'])
@app_auth_required
def app_add_comment(project_id):
    """현장 코멘트 추가"""
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    content = data.get('content', '').strip()
    scope = data.get('scope', 'common')
    if not content:
        return jsonify(ok=False, error='내용을 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 401
        user_name = f"{user.full_name} {user.position or ''}".strip()
        append_history_log(db, project_id, user_name, content, scope=scope)
        db.commit()
    return jsonify(ok=True)


# ── 알림 ──

@app_api_bp.route('/notifications')
@app_auth_required
def app_notifications():
    """알림 목록"""
    user_id = request._app_user_id
    with get_db() as db:
        notifications = db.query(Notification).filter(
            Notification.user_id == user_id
        ).order_by(desc(Notification.id)).limit(50).all()
        return jsonify(ok=True, notifications=[{
            'id': n.id,
            'title': n.title or '',
            'message': n.message or '',
            'noti_type': n.noti_type or 'system',
            'is_read': n.is_read,
            'created_at': str(n.created_at) if n.created_at else '',
            'link': n.link or '',
        } for n in notifications])


# ── 계약관리 ──

@app_api_bp.route('/contracts')
@app_auth_required
def app_contracts():
    """계약 목록 (완료건 제외)"""
    search = request.args.get('search', '').strip()
    show_all = request.args.get('all', '') == '1'
    with get_db() as db:
        q = db.query(Contract).join(Project, Project.id == Contract.project_id, isouter=True)
        if not show_all:
            q = q.filter(
                Contract.payment_status.notin_(('입금완료', '변경완료', '취소')),
                Contract.is_excluded.isnot(True),
            )
        if search:
            q = q.filter(
                (Contract.contract_name.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
            )
        contracts = q.order_by(desc(Contract.id)).limit(100).all()
        result = []
        for c in contracts:
            p = c.project
            # G2B 조달내역에서 발주기관, 금액 가져오기
            g2b = None
            if c.g2b_contract_no:
                g2b = db.query(G2bProcurement).filter(
                    G2bProcurement.cntrct_dlvr_req_no == c.g2b_contract_no
                ).first()
            result.append({
                'id': c.id,
                'contract_name': c.contract_name or '',
                'contract_no': getattr(c, 'g2b_contract_no', '') or '',
                'project_id': c.project_id,
                'project_name': (p.temp_name if p else '') or '',
                'delivery_due_date': str(c.delivery_due_date) if c.delivery_due_date else '',
                'contract_date': str(c.contract_date) if c.contract_date else '',
                'payment_status': c.payment_status or '미청구',
                'is_excluded': bool(c.is_excluded),
                'ordering_org': (g2b.dminstt_nm if g2b else '') or '',
                'contract_amount': (g2b.prdct_amt if g2b else 0) or 0,
                'region': (g2b.dminstt_rgn_nm if g2b else '') or '',
            })
        return jsonify(ok=True, contracts=result)


# ── 협의관리 ──

@app_api_bp.route('/sales')
@app_auth_required
def app_sales():
    """협의 목록 (영업 진행 상태 기준)"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(ContractItem).join(
            Contract, Contract.id == ContractItem.contract_id
        ).join(
            Project, Project.id == Contract.project_id, isouter=True
        ).filter(active_contract_filter())
        if search:
            q = q.filter(
                (Contract.contract_name.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
                | (ContractItem.model_name.ilike(f'%{search}%'))
            )
        items = q.order_by(desc(ContractItem.id)).limit(100).all()
        result = []
        for ci in items:
            c = ci.contract
            p = c.project if c else None
            result.append({
                'id': ci.id,
                'contract_id': ci.contract_id,
                'project_id': c.project_id if c else None,
                'contract_name': (c.contract_name if c else '') or '',
                'project_name': (p.temp_name if p else '') or '',
                'delivery_due_date': str(c.delivery_due_date) if c and c.delivery_due_date else '',
                'model_name': ci.model_name or '',
                'category': ci.category or '',
                'quantity': ci.quantity or 0,
                'status_sales': ci.status_sales or '',
                'status_admin': ci.status_admin or '',
                'status_prod': ci.status_prod or '',
            })
        return jsonify(ok=True, sales=result)


# ── 납품관리 ──

@app_api_bp.route('/deliveries')
@app_auth_required
def app_deliveries():
    """납품 목록"""
    search = request.args.get('search', '').strip()
    show_all = request.args.get('all', '') == '1'
    with get_db() as db:
        q = db.query(Delivery).join(
            Project, Project.id == Delivery.project_id, isouter=True
        ).join(
            Contract, Contract.id == Delivery.contract_id, isouter=True
        )
        if not show_all:
            q = q.filter(active_contract_filter())
        if search:
            q = q.filter(
                (Contract.contract_name.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
            )
        deliveries = q.order_by(desc(Delivery.id)).limit(100).all()
        result = []
        for d in deliveries:
            p = d.project
            c = d.contract
            result.append({
                'id': d.id,
                'project_id': d.project_id,
                'contract_id': d.contract_id,
                'project_name': (p.temp_name if p else '') or '',
                'contract_name': (c.contract_name if c else '') or '',
                'delivery_due_date': str(c.delivery_due_date) if c and c.delivery_due_date else '',
                'delivery_status': d.delivery_status or '',
                'inspection_status': d.inspection_status or '미검수',
                'inspection_date': str(d.inspection_date) if d.inspection_date else '',
                'planned_total_qty': d.planned_total_qty or 0,
                'delivered_total_qty': d.delivered_total_qty or 0,
                'contact_name': d.contact_name or '',
                'contact_phone': d.contact_phone or '',
                'created_at': d.created_at.strftime('%Y-%m-%d') if d.created_at else '',
            })
        return jsonify(ok=True, deliveries=result)


# ── 생산관리 ──

@app_api_bp.route('/production-sites')
@app_auth_required
def app_production_sites():
    """생산관리 — 현장 단위 목록 (웹 ERP 동일 구조)"""
    import datetime as _dt
    from modules.services.production_actions import get_site_list
    team = request.args.get('team', 'team1')
    from modules.models.constants import PRODUCTION_TEAM_MAP
    team_categories = PRODUCTION_TEAM_MAP.get(team)
    with get_db() as db:
        today = _dt.date.today()
        sites = get_site_list(db, today, team_categories=team_categories)
        return jsonify(ok=True, sites=sites)


@app_api_bp.route('/production-sites/<int:project_id>')
@app_auth_required
def app_production_site_detail(project_id):
    """생산관리 — 현장 상세 (품목별 공정 카드)"""
    import datetime as _dt
    from modules.services.production_actions import get_site_detail
    from modules.models.constants import PRODUCTION_TEAM_MAP
    team = request.args.get('team', 'team1')
    team_categories = PRODUCTION_TEAM_MAP.get(team)
    with get_db() as db:
        today = _dt.date.today()
        project = db.query(Project).get(project_id)
        if not project:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404
        item_groups, stats, history, _ = get_site_detail(db, project, project_id, today, team_categories=team_categories)

        # 직렬화
        items_json = []
        for ig in item_groups:
            processes = []
            for card in ig.get('cards', []):
                processes.append({
                    'id': card.get('process_id', 0),
                    'step_name': card.get('process_name', ''),
                    'status': card.get('status', ''),
                    'step_order': card.get('step_order', 0),
                    'progress_pct': card.get('progress_pct', 0),
                    'materials_ready': card.get('materials_ready', False),
                    'can_start': card.get('can_start', False),
                })
            items_json.append({
                'item_id': ig.get('item_id', 0),
                'category': ig.get('category', ''),
                'model_name': ig.get('model_name', ''),
                'quantity': ig.get('quantity', 0),
                'total_proc': ig.get('total_proc', 0),
                'done_proc': ig.get('done_proc', 0),
                'pct': ig.get('pct', 0),
                'processes': processes,
            })

        history_json = []
        for h in (history or []):
            history_json.append({
                'user_name': h.user_name or '',
                'content': h.content or '',
                'created_at': str(h.created_at) if h.created_at else '',
            })

        # stats 키 통일
        stats_json = {
            'total_proc': stats.get('total', 0),
            'working_proc': stats.get('working', 0),
            'done_proc': stats.get('done', 0),
            'pct': round(stats.get('done', 0) / stats.get('total', 1) * 100, 1) if stats.get('total', 0) > 0 else 0,
        }
        return jsonify(ok=True,
            project={'id': project.id, 'name': project.temp_name or '', 'project_no': project.project_no or ''},
            stats=stats_json,
            items=items_json,
            history=history_json,
        )


@app_api_bp.route('/production')
@app_auth_required
def app_production():
    """현장별 생산현황"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(ContractItem).join(
            Contract, Contract.id == ContractItem.contract_id
        ).join(
            Project, Project.id == Contract.project_id
        ).filter(
            Project.is_contracted.is_(True),
            active_contract_filter(),
        )
        if search:
            q = q.filter(
                (Contract.contract_name.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
                | (ContractItem.model_name.ilike(f'%{search}%'))
            )
        items = q.order_by(desc(ContractItem.id)).limit(100).all()
        result = []
        for ci in items:
            c = ci.contract
            p = c.project if c else None
            result.append({
                'id': ci.id,
                'contract_id': ci.contract_id,
                'project_id': c.project_id if c else None,
                'project_name': (p.temp_name if p else '') or '',
                'contract_name': (c.contract_name if c else '') or '',
                'delivery_due_date': str(c.delivery_due_date) if c and c.delivery_due_date else '',
                'model_name': ci.model_name or '',
                'category': ci.category or '',
                'quantity': ci.quantity or 0,
                'status_sales': ci.status_sales or '',
                'status_prod': ci.status_prod or '',
                'status_admin': ci.status_admin or '',
            })
        return jsonify(ok=True, production=result)


# ── 발주관리 ──

@app_api_bp.route('/purchase-orders')
@app_auth_required
def app_purchase_orders():
    """발주 목록"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.vendor),
            joinedload(PurchaseOrder.project),
            joinedload(PurchaseOrder.items),
        )
        if search:
            q = q.join(Vendor, Vendor.id == PurchaseOrder.vendor_id, isouter=True).join(
                Project, Project.id == PurchaseOrder.project_id, isouter=True
            ).filter(
                (PurchaseOrder.po_no.ilike(f'%{search}%'))
                | (Vendor.name.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
            )
        pos = q.order_by(desc(PurchaseOrder.id)).limit(100).all()
        result = []
        for po in pos:
            # 품목 수 카운트
            item_count = len(po.items) if po.items else 0
            result.append({
                'id': po.id,
                'po_no': po.po_no or '',
                'po_date': str(po.po_date) if po.po_date else '',
                'vendor_name': (po.vendor.name if po.vendor else '') or '',
                'project_name': (po.project.temp_name if po.project else '') or '',
                'status': po.status or '',
                'total_amount': po.total_amount or 0,
                'tax_amount': po.tax_amount or 0,
                'item_count': item_count,
                'email_sent_at': po.email_sent_at.strftime('%Y-%m-%d %H:%M') if po.email_sent_at else '',
                'note': po.note or '',
            })
        return jsonify(ok=True, purchase_orders=result)


# ── 입고관리 ──

@app_api_bp.route('/receivings')
@app_auth_required
def app_receivings():
    """입고 목록"""
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    with get_db() as db:
        q = db.query(Receiving).options(
            joinedload(Receiving.vendor),
            joinedload(Receiving.purchase_order),
            joinedload(Receiving.items),
        )
        if status:
            q = q.filter(Receiving.status == status)
        if search:
            q = q.join(Vendor, Vendor.id == Receiving.vendor_id, isouter=True).filter(
                (Receiving.rcv_no.ilike(f'%{search}%'))
                | (Vendor.name.ilike(f'%{search}%'))
            )
        receivings = q.order_by(desc(Receiving.id)).limit(100).all()
        result = []
        for r in receivings:
            # 품목 합계 금액 계산
            total_amount = sum((item.amount or 0) for item in (r.items or []))
            item_count = len(r.items) if r.items else 0
            result.append({
                'id': r.id,
                'rcv_no': r.rcv_no or '',
                'rcv_date': str(r.rcv_date) if r.rcv_date else '',
                'vendor_name': (r.vendor.name if r.vendor else '') or '',
                'po_no': (r.purchase_order.po_no if r.purchase_order else '') or '',
                'status': r.status or '',
                'item_count': item_count,
                'total_amount': total_amount,
                'note': r.note or '',
                'created_at': r.created_at.strftime('%Y-%m-%d') if r.created_at else '',
            })
        return jsonify(ok=True, receivings=result)


# ── 자재관리 ──

@app_api_bp.route('/materials')
@app_auth_required
def app_materials():
    """자재 목록 (MaterialOrder)"""
    search = request.args.get('search', '').strip()
    show_all = request.args.get('all', '') == '1'
    with get_db() as db:
        q = db.query(MaterialOrder).join(
            Project, Project.id == MaterialOrder.project_id, isouter=True
        ).join(
            Contract, Contract.id == MaterialOrder.contract_id, isouter=True
        )
        if not show_all:
            q = q.filter(active_contract_filter())
        if search:
            q = q.filter(
                (MaterialOrder.material_name.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
                | (Contract.contract_name.ilike(f'%{search}%'))
            )
        materials = q.order_by(desc(MaterialOrder.id)).limit(100).all()
        # contract_name 일괄 로딩 (lazy load 방지)
        contract_ids = list({m.contract_id for m in materials if m.contract_id})
        cmap = {}
        if contract_ids:
            cmap = {c.id: c.contract_name for c in db.query(Contract.id, Contract.contract_name).filter(Contract.id.in_(contract_ids)).all()}
        result = []
        for m in materials:
            result.append({
                'id': m.id,
                'project_id': m.project_id,
                'contract_id': m.contract_id,
                'project_name': (m.project.temp_name if m.project else '') or '',
                'contract_name': cmap.get(m.contract_id, '') or '',
                'material_name': m.material_name or '',
                'item_category': m.item_category or '',
                'item_model_name': m.item_model_name or '',
                'quantity': m.quantity or 0,
                'order_status': m.order_status or '',
                'order_date': str(m.order_date) if m.order_date else '',
                'expected_in_date': str(m.expected_in_date) if m.expected_in_date else '',
                'in_confirmed': bool(m.in_confirmed),
                'is_outsourcing': bool(m.is_outsourcing),
                'outsourcing_status': m.outsourcing_status or '',
            })
        return jsonify(ok=True, materials=result)


# ── 견적관리 ──

@app_api_bp.route('/quotations')
@app_auth_required
def app_quotations():
    """견적 목록"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(Quotation)
        if search:
            q = q.filter(
                (Quotation.quote_no.ilike(f'%{search}%'))
                | (Quotation.project_name.ilike(f'%{search}%'))
                | (Quotation.customer_name.ilike(f'%{search}%'))
            )
        quotations = q.order_by(desc(Quotation.id)).limit(100).all()
        result = []
        for qt in quotations:
            result.append({
                'id': qt.id,
                'quote_no': qt.quote_no or '',
                'quote_date': str(qt.quote_date) if qt.quote_date else '',
                'project_name': qt.project_name or '',
                'customer_name': qt.customer_name or '',
                'grand_total': qt.grand_total or 0,
                'status': qt.status or '작성중',
                'created_at': qt.created_at.strftime('%Y-%m-%d') if qt.created_at else '',
            })
        return jsonify(ok=True, quotations=result)


# ── 재고관리 ──

@app_api_bp.route('/inventory')
@app_auth_required
def app_inventory():
    """재고 현황"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(Item).filter(Item.is_active.is_(True))
        if search:
            q = q.filter(
                (Item.item_name.ilike(f'%{search}%'))
                | (Item.icube_item_cd.ilike(f'%{search}%'))
                | (Item.category.ilike(f'%{search}%'))
            )
        items = q.order_by(desc(Item.id)).limit(100).all()
        result = []
        for it in items:
            result.append({
                'id': it.id,
                'item_code': it.icube_item_cd or '',
                'item_name': it.item_name or '',
                'item_spec': it.item_spec or '',
                'category': it.category or '',
                'unit': it.unit or '',
                'stock_qty': it.stock_qty or 0,
                'available_qty': it.stock_qty or 0,
                'safety_stock': it.safety_stock or 0,
                'is_low_stock': (it.stock_qty or 0) < (it.safety_stock or 0),
            })
        return jsonify(ok=True, inventory=result)


# ── 품목관리 ──

@app_api_bp.route('/items')
@app_auth_required
def app_items():
    """품목 목록"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(Item)
        if search:
            q = q.filter(
                (Item.item_name.ilike(f'%{search}%'))
                | (Item.icube_item_cd.ilike(f'%{search}%'))
                | (Item.item_spec.ilike(f'%{search}%'))
                | (Item.category.ilike(f'%{search}%'))
            )
        items = q.order_by(desc(Item.id)).limit(100).all()
        result = []
        for it in items:
            result.append({
                'id': it.id,
                'item_code': it.icube_item_cd or '',
                'item_name': it.item_name or '',
                'item_spec': it.item_spec or '',
                'category': it.category or '',
                'unit': it.unit or '',
                'manufacturer': it.manufacturer or '',
                'stock_qty': it.stock_qty or 0,
                'is_active': bool(it.is_active),
            })
        return jsonify(ok=True, items=result)


# ── 거래처관리 ──

@app_api_bp.route('/vendors')
@app_auth_required
def app_vendors():
    """거래처 목록"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(Vendor).filter(Vendor.is_active.is_(True))
        if search:
            q = q.filter(
                (Vendor.name.ilike(f'%{search}%'))
                | (Vendor.business_no.ilike(f'%{search}%'))
                | (Vendor.ceo_name.ilike(f'%{search}%'))
            )
        vendors = q.order_by(desc(Vendor.id)).limit(100).all()
        result = []
        for v in vendors:
            result.append({
                'id': v.id,
                'name': v.name or '',
                'ceo_name': v.ceo_name or '',
                'business_no': v.business_no or '',
                'tel': v.tel or '',
                'email': v.email or '',
                'address': v.address or '',
                'business': v.business or '',
            })
        return jsonify(ok=True, vendors=result)


# ── 하자관리 ──

@app_api_bp.route('/warranty-cases')
@app_auth_required
def app_warranty_cases():
    """AS 케이스 목록"""
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')
    with get_db() as db:
        q = db.query(WarrantyCase).join(
            Warranty, Warranty.id == WarrantyCase.warranty_id, isouter=True
        ).join(
            Project, Project.id == WarrantyCase.project_id, isouter=True
        )
        if status:
            q = q.filter(WarrantyCase.status == status)
        if search:
            q = q.filter(
                (WarrantyCase.case_no.ilike(f'%{search}%'))
                | (WarrantyCase.contract_name.ilike(f'%{search}%'))
                | (WarrantyCase.symptom.ilike(f'%{search}%'))
                | (Project.temp_name.ilike(f'%{search}%'))
            )
        cases = q.order_by(desc(WarrantyCase.id)).limit(100).all()
        result = []
        for wc in cases:
            p = wc.project
            result.append({
                'id': wc.id,
                'case_no': wc.case_no or '',
                'warranty_id': wc.warranty_id,
                'project_id': wc.project_id,
                'status': wc.status or '접수',
                'defect_type': wc.defect_type or '',
                'symptom': wc.symptom or '',
                'contract_name': wc.contract_name or '',
                'model_name': wc.model_name or '',
                'item_group': wc.item_group or '',
                'project_name': (p.temp_name if p else '') or '',
                'reported_date': str(wc.reported_date) if wc.reported_date else '',
                'reported_by': wc.reported_by or '',
                'assigned_to': wc.assigned_to or '',
                'is_chargeable': bool(wc.is_chargeable),
                'customer_name': wc.customer_name or '',
                'customer_phone': wc.customer_phone or '',
                'site_visit_date': str(wc.site_visit_date) if wc.site_visit_date else '',
                'completed_date': str(wc.completed_date) if wc.completed_date else '',
            })
        return jsonify(ok=True, warranty_cases=result)


# ── 조달내역 ──

@app_api_bp.route('/procurements')
@app_auth_required
def app_procurements():
    """G2B 조달내역 목록"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(G2bProcurement)
        if search:
            q = q.filter(
                (G2bProcurement.cntrct_dlvr_req_nm.ilike(f'%{search}%'))
                | (G2bProcurement.cntrct_dlvr_req_no.ilike(f'%{search}%'))
                | (G2bProcurement.dminstt_nm.ilike(f'%{search}%'))
                | (G2bProcurement.prdct_clsfc_no_nm.ilike(f'%{search}%'))
            )
        procs = q.order_by(desc(G2bProcurement.id)).limit(100).all()
        result = []
        for g in procs:
            result.append({
                'id': g.id,
                'cntrct_dlvr_req_no': g.cntrct_dlvr_req_no or '',
                'cntrct_dlvr_req_nm': g.cntrct_dlvr_req_nm or '',
                'dminstt_nm': g.dminstt_nm or '',
                'dminstt_rgn_nm': g.dminstt_rgn_nm or '',
                'prdct_clsfc_no_nm': g.prdct_clsfc_no_nm or '',
                'dtil_prdct_clsfc_no_nm': g.dtil_prdct_clsfc_no_nm or '',
                'prdct_idnt_no_nm': g.prdct_idnt_no_nm or '',
                'prdct_qty': g.prdct_qty or 0,
                'prdct_uprc': g.prdct_uprc or 0,
                'prdct_amt': g.prdct_amt or 0,
                'dlvr_tmlmt_date': str(g.dlvr_tmlmt_date) if g.dlvr_tmlmt_date else '',
                'cntrct_dlvr_req_date': str(g.cntrct_dlvr_req_date) if g.cntrct_dlvr_req_date else '',
                'dlvr_plce_nm': g.dlvr_plce_nm or '',
                'cntrct_div_nm': g.cntrct_div_nm or '',
            })
        return jsonify(ok=True, procurements=result)


# ── 입고사진 ──

@app_api_bp.route('/receiving-photos')
@app_auth_required
def app_receiving_photos():
    """입고사진 피드 목록"""
    search = request.args.get('search', '').strip()
    with get_db() as db:
        q = db.query(ReceivingPhotoPost).options(
            joinedload(ReceivingPhotoPost.author)
        )
        if search:
            q = q.filter(
                (ReceivingPhotoPost.content.ilike(f'%{search}%'))
                | (ReceivingPhotoPost.vendor_name.ilike(f'%{search}%'))
                | (ReceivingPhotoPost.po_no.ilike(f'%{search}%'))
            )
        posts = q.order_by(desc(ReceivingPhotoPost.id)).limit(50).all()
        result = []
        for post in posts:
            raw = post.photos_json
            if isinstance(raw, list):
                photos = raw
            elif isinstance(raw, str):
                try:
                    photos = json.loads(raw)
                except Exception:
                    import ast
                    try:
                        photos = ast.literal_eval(raw)
                    except Exception:
                        photos = []
            else:
                photos = []
            result.append({
                'id': post.id,
                'content': post.content or '',
                'vendor_name': post.vendor_name or '',
                'po_no': post.po_no or '',
                'photos': photos,
                'author_name': (post.author.full_name if post.author else '') or '',
                'created_at': post.created_at.strftime('%Y-%m-%d %H:%M') if post.created_at else '',
            })
        return jsonify(ok=True, receiving_photos=result)


# ── 설계관리 ──

@app_api_bp.route('/projects/design')
@app_auth_required
def app_design_projects():
    """설계관리 — 설계/영업 또는 G- 미접두 프로젝트"""
    with get_db() as db:
        projects = db.query(Project).filter(
            (Project.status == '설계/영업') | (~Project.project_no.like('G-%'))
        ).order_by(desc(Project.id)).limit(200).all()

        result = []
        for p in projects:
            result.append({
                'id': p.id,
                'project_no': p.project_no or '',
                'name': p.temp_name or '',
                'status': p.status or '',
                'short_name': p.short_name or '',
                'site_address': p.site_address or '',
                'created_at': str(p.created_at) if p.created_at else '',
            })
        return jsonify(ok=True, projects=result)


# ── 가공발주 ──

@app_api_bp.route('/processing-orders')
@app_auth_required
def app_processing_orders():
    """가공발주 목록"""
    with get_db() as db:
        orders = db.query(ProcessingOrder).options(
            joinedload(ProcessingOrder.vendor),
            joinedload(ProcessingOrder.project),
            joinedload(ProcessingOrder.items),
        ).order_by(desc(ProcessingOrder.id)).limit(100).all()

        result = []
        for o in orders:
            result.append({
                'id': o.id,
                'fo_no': o.fo_no or '',
                'fo_date': str(o.fo_date) if o.fo_date else '',
                'vendor_name': o.vendor.name if o.vendor else '',
                'project_name': o.project.temp_name if o.project else '',
                'status': o.status or '',
                'processing_type': o.processing_type or '',
                'item_count': len(o.items) if o.items else 0,
                'total_amount': o.total_amount or 0,
                'note': o.note or '',
            })
        return jsonify(ok=True, processing_orders=result)


# ── 매출/수금 ──

@app_api_bp.route('/financial')
@app_auth_required
def app_financial():
    """매출/수금 요약 — 계약별 payment_status 집계"""
    with get_db() as db:
        total_contracts = db.query(Contract).filter(active_contract_filter()).count()
        total_amount = db.query(func.sum(G2bProcurement.prdct_amt)).scalar() or 0

        paid_count = db.query(Contract).filter(
            Contract.payment_status == '입금완료'
        ).count()
        unpaid_count = db.query(Contract).filter(
            active_contract_filter(),
            Contract.payment_status.in_(['미청구', '부분입금'])
        ).count()

        return jsonify(ok=True, financial={
            'total_contracts': total_contracts,
            'total_amount': total_amount,
            'paid_count': paid_count,
            'unpaid_count': unpaid_count,
        })


# ── 청구관리 ──

# /billing 엔드포인트는 Contract 기반으로 파일 끝에서 재정의됨.


# ── 인증서관리 ──

@app_api_bp.route('/certifications')
@app_auth_required
def app_certifications():
    """인증서 목록 — 만료일순"""
    with get_db() as db:
        certs = db.query(Certification).filter(
            Certification.is_active.is_(True)
        ).order_by(Certification.expiry_date).all()

        result = []
        for c in certs:
            result.append({
                'id': c.id,
                'cert_name': c.cert_name or '',
                'cert_type': c.cert_type or '',
                'cert_no': c.cert_no or '',
                'issuer': c.issued_by or '',
                'issue_date': str(c.issued_date) if c.issued_date else '',
                'expiry_date': str(c.expiry_date) if c.expiry_date else '',
                'expiry_status': c.expiry_status,
                'days_until_expiry': c.days_until_expiry,
                'product_model': c.product_model or '',
                'file_path': c.file_path or '',
            })
        return jsonify(ok=True, certifications=result)


# ── BOM관리 ──

@app_api_bp.route('/bom')
@app_auth_required
def app_bom():
    """BOM 목록"""
    with get_db() as db:
        boms = db.query(BomHeader).options(
            joinedload(BomHeader.bom_items),
        ).order_by(desc(BomHeader.id)).limit(100).all()

        result = []
        for b in boms:
            result.append({
                'id': b.id,
                'product_code': b.product_code or '',
                'product_name': b.product_name or '',
                'category': b.product_category or '',
                'version': b.version or '',
                'is_active': b.is_active,
                'item_count': len(b.bom_items) if b.bom_items else 0,
            })
        return jsonify(ok=True, bom_list=result)


# ── 사진관리 ──

@app_api_bp.route('/photos')
@app_auth_required
def app_photos():
    """현장 사진 목록"""
    with get_db() as db:
        photos = db.query(ProjectPhoto).options(
            joinedload(ProjectPhoto.project),
        ).order_by(desc(ProjectPhoto.id)).limit(100).all()

        result = []
        for p in photos:
            result.append({
                'id': p.id,
                'project_id': p.project_id,
                'project_name': p.project.temp_name if p.project else '',
                'photo_type': p.photo_type or '',
                'file_name': p.file_name or '',
                'storage_path': p.storage_path or '',
                'uploaded_by': p.uploaded_by or '',
                'created_at': str(p.created_at) if p.created_at else '',
            })
        return jsonify(ok=True, photos=result)


# ── 도면관리 ──

@app_api_bp.route('/drawings')
@app_auth_required
def app_drawings():
    """도면 목록"""
    with get_db() as db:
        drawings = db.query(Drawing).options(
            joinedload(Drawing.versions),
            joinedload(Drawing.project),
        ).order_by(desc(Drawing.id)).limit(100).all()

        result = []
        for d in drawings:
            latest = d.versions[0] if d.versions else None
            result.append({
                'id': d.id,
                'title': d.title or '',
                'drawing_type': d.drawing_type or '',
                'project_name': d.project.temp_name if d.project else '',
                'revision_count': len(d.versions) if d.versions else 0,
                'latest_version': latest.version_no if latest else 0,
                'convert_status': latest.convert_status if latest else '',
                'created_by': d.created_by or '',
                'created_at': str(d.created_at) if d.created_at else '',
            })
        return jsonify(ok=True, drawings=result)


# ── 출장관리 ──

@app_api_bp.route('/business-trips')
@app_auth_required
def app_business_trips():
    """출장 목록"""
    with get_db() as db:
        trips = db.query(BusinessTrip).options(
            joinedload(BusinessTrip.members),
        ).order_by(desc(BusinessTrip.id)).limit(50).all()

        result = []
        for t in trips:
            result.append({
                'id': t.id,
                'title': t.title or '',
                'destination': t.destination or '',
                'departure_date': str(t.departure_date) if t.departure_date else '',
                'return_date': str(t.return_date) if t.return_date else '',
                'status': t.effective_status,
                'vehicle': t.vehicle or '',
                'members_count': len(t.members) if t.members else 0,
                'member_names': t.member_names,
                'note': t.note or '',
            })
        return jsonify(ok=True, business_trips=result)


# ── 공구관리 ──

@app_api_bp.route('/tools')
@app_auth_required
def app_tools():
    """공구 목록"""
    with get_db() as db:
        tools = db.query(Tool).order_by(Tool.category, Tool.tool_name).all()

        result = []
        for t in tools:
            result.append({
                'id': t.id,
                'tool_name': t.tool_name or '',
                'category': t.category or '',
                'team': t.team or '',
                'total_qty': t.total_qty or 0,
                'available_qty': t.available_qty or 0,
                'current_location': t.current_location or '',
                'status': t.status or '',
                'note': t.note or '',
            })
        return jsonify(ok=True, tools=result)


# ── 납품집계 ──

@app_api_bp.route('/procurement-summary')
@app_auth_required
def app_procurement_summary():
    """납품집계 — G2B 조달내역 연/월별 집계"""
    with get_db() as db:
        rows = db.query(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).label('year'),
            extract('month', G2bProcurement.cntrct_dlvr_req_date).label('month'),
            func.count(G2bProcurement.id).label('count'),
            func.sum(G2bProcurement.prdct_amt).label('total_amount'),
        ).filter(
            G2bProcurement.cntrct_dlvr_req_date.isnot(None)
        ).group_by('year', 'month').order_by(
            desc('year'), desc('month')
        ).all()

        result = []
        for r in rows:
            result.append({
                'year': int(r.year) if r.year else 0,
                'month': int(r.month) if r.month else 0,
                'count': r.count or 0,
                'total_amount': r.total_amount or 0,
            })
        return jsonify(ok=True, procurement_summary=result)


# ══════════════════════════════════════════════════════════════════════
# 쓰기 API — 모바일에서 실무 행위 수행
# ══════════════════════════════════════════════════════════════════════

# ── 계약 상세 ──

@app_api_bp.route('/contracts/<int:contract_id>')
@app_auth_required
def app_contract_detail(contract_id):
    """계약 상세 — 계약정보 + 품목 + 히스토리"""
    from modules.history_board import get_project_history_context
    with get_db() as db:
        c = db.query(Contract).options(
            joinedload(Contract.items),
            joinedload(Contract.project),
        ).get(contract_id)
        if not c:
            return jsonify(ok=False, error='계약을 찾을 수 없습니다'), 404

        g2b = None
        if c.g2b_contract_no:
            g2b = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_no == c.g2b_contract_no
            ).first()

        items = [{
            'id': ci.id,
            'category': ci.category or '',
            'model_name': ci.model_name or '',
            'quantity': ci.quantity or 0,
            'status_admin': ci.status_admin or '',
            'status_prod': ci.status_prod or '',
            'status_sales': ci.status_sales or '',
        } for ci in (c.items or [])]

        history = []
        if c.project_id:
            hist_rows, _ = get_project_history_context(db, c.project_id, limit=30)
            for h in hist_rows:
                history.append({
                    'user_name': h.user_name or '',
                    'content': h.content or '',
                    'created_at': str(h.created_at) if h.created_at else '',
                    'log_scope': h.log_scope or '',
                })

        return jsonify(ok=True, contract={
            'id': c.id,
            'contract_name': c.contract_name or '',
            'contract_no': c.g2b_contract_no or '',
            'contract_date': str(c.contract_date) if c.contract_date else '',
            'delivery_due_date': str(c.delivery_due_date) if c.delivery_due_date else '',
            'payment_status': c.payment_status or '미청구',
            'project_id': c.project_id,
            'ordering_org': (g2b.dminstt_nm if g2b else '') or '',
            'contract_amount': (g2b.prdct_amt if g2b else 0) or 0,
        }, items=items, history=history)


# ── 납품 상태 변경 ──

@app_api_bp.route('/deliveries/<int:delivery_id>/status', methods=['POST'])
@app_auth_required
def app_delivery_status(delivery_id):
    """납품 상태 변경"""
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if new_status not in ('waiting', 'in_progress', 'done'):
        return jsonify(ok=False, error='유효하지 않은 상태입니다'), 400

    user_id = request._app_user_id
    with get_db() as db:
        delivery = db.query(Delivery).get(delivery_id)
        if not delivery:
            return jsonify(ok=False, error='납품 정보를 찾을 수 없습니다'), 404

        old_status = delivery.delivery_status
        delivery.delivery_status = new_status
        status_map = {'waiting': '대기', 'in_progress': '진행중', 'completed': '완료'}

        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        if delivery.project_id:
            append_history_log(
                db, delivery.project_id, user_name,
                f'납품 상태 변경: {status_map.get(old_status, old_status)} → {status_map.get(new_status, new_status)}',
                scope='납품관리',
            )
        log_activity(db, '납품관리', 'status_change',
                     f'납품 {delivery.id} 상태변경 {old_status}→{new_status}',
                     ref_type='Delivery', project_id=delivery.project_id)
        db.commit()
    return jsonify(ok=True)


# ── 발주 상태 변경 ──

@app_api_bp.route('/purchase-orders/<int:po_id>/status', methods=['POST'])
@app_auth_required
def app_po_status(po_id):
    """발주서 상태 변경 — ERP PO_STATUS_CHOICES 동일"""
    from modules.models.procurement_entities import PO_STATUS_CHOICES
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if new_status not in PO_STATUS_CHOICES:
        return jsonify(ok=False, error=f'유효하지 않은 상태. 허용: {", ".join(PO_STATUS_CHOICES)}'), 400

    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404
        po.status = new_status
        log_activity(db, '발주관리', 'status_change',
                     f'{po.po_no} 상태변경 → {new_status}',
                     ref_type='PurchaseOrder', ref_id=po.id, ref_label=po.po_no)
        db.commit()
    return jsonify(ok=True)


# ── 발주 상세 ──

@app_api_bp.route('/purchase-orders/<int:po_id>')
@app_auth_required
def app_po_detail(po_id):
    """발주서 상세 — po + items + vendor + project + contract + assignee"""
    from modules.models.procurement_entities import PO_STATUS_CHOICES
    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.vendor),
            joinedload(PurchaseOrder.project),
            joinedload(PurchaseOrder.contract),
            joinedload(PurchaseOrder.assignee),
            joinedload(PurchaseOrder.items),
        ).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404

        items = [{
            'id': i.id,
            'item_id': i.item_id,
            'item_code': i.item_code or '',
            'item_name': i.item_name or '',
            'item_spec': i.item_spec or '',
            'quantity': i.quantity or 0,
            'unit_price': i.unit_price or 0,
            'amount': i.amount or 0,
            'unit': i.unit or '',
            'note': i.note or '',
            'delivery_date': str(i.delivery_date) if i.delivery_date else '',
            'expected_in_date': str(i.expected_in_date) if i.expected_in_date else '',
            'in_confirmed': bool(i.in_confirmed),
            'in_confirmed_at': i.in_confirmed_at.strftime('%Y-%m-%d %H:%M') if i.in_confirmed_at else '',
        } for i in (po.items or [])]

        assignee_name = ''
        if po.assignee:
            assignee_name = f"{po.assignee.full_name} {po.assignee.position or ''}".strip()

        return jsonify(ok=True, purchase_order={
            'id': po.id,
            'po_no': po.po_no or '',
            'po_date': str(po.po_date) if po.po_date else '',
            'status': po.status or '',
            'vendor_id': po.vendor_id,
            'vendor_name': (po.vendor.name if po.vendor else '') or '',
            'vendor_ceo': (po.vendor.ceo_name if po.vendor else '') or '',
            'vendor_tel': (po.vendor.tel if po.vendor else '') or '',
            'vendor_email': (po.vendor.email if po.vendor else '') or '',
            'vendor_business_no': (po.vendor.business_no if po.vendor else '') or '',
            'project_id': po.project_id,
            'project_name': (po.project.temp_name if po.project else '') or '',
            'contract_id': po.contract_id,
            'contract_name': (po.contract.contract_name if po.contract else '') or '',
            'assigned_to': po.assigned_to,
            'assignee_name': assignee_name,
            'total_amount': po.total_amount or 0,
            'tax_amount': po.tax_amount or 0,
            'grand_total': (po.total_amount or 0) + (po.tax_amount or 0),
            'note': po.note or '',
            'email_sent_at': po.email_sent_at.strftime('%Y-%m-%d %H:%M') if po.email_sent_at else '',
            'email_to': po.email_to or '',
            'created_at': po.created_at.strftime('%Y-%m-%d %H:%M') if po.created_at else '',
        }, items=items, status_choices=PO_STATUS_CHOICES)


# ── 발주 수정 ──

@app_api_bp.route('/purchase-orders/<int:po_id>/edit', methods=['POST'])
@app_auth_required
def app_po_edit(po_id):
    """발주서 수정 — ERP po_edit 로직 그대로 (작성중만 수정 가능, 품목 재등록)"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404
        if po.status != '작성중':
            return jsonify(ok=False, error='작성중 상태의 발주서만 수정할 수 있습니다'), 400

        try:
            if data.get('po_date'):
                po.po_date = datetime.datetime.strptime(data['po_date'], '%Y-%m-%d').date()
            if 'vendor_id' in data and data['vendor_id']:
                po.vendor_id = int(data['vendor_id'])
            if 'assigned_to' in data:
                po.assigned_to = int(data['assigned_to']) if data['assigned_to'] else None
            if 'contract_id' in data:
                po.contract_id = int(data['contract_id']) if data['contract_id'] else None
            po.note = (data.get('note') or '').strip()

            # 기존 품목 삭제 후 재등록
            db.query(PurchaseOrderItem).filter_by(po_id=po.id).delete()
            total_amount = 0
            for it in (data.get('items') or []):
                name = (it.get('item_name') or '').strip()
                if not name:
                    continue
                qty = float(it.get('quantity') or 0)
                price = float(it.get('unit_price') or 0)
                amount = qty * price
                dlv_date = None
                if it.get('delivery_date'):
                    try:
                        dlv_date = datetime.date.fromisoformat(it['delivery_date'])
                    except ValueError:
                        pass
                db.add(PurchaseOrderItem(
                    po_id=po.id,
                    item_id=(int(it['item_id']) if it.get('item_id') else None),
                    item_code=(it.get('item_code') or '').strip() or None,
                    item_name=name,
                    item_spec=(it.get('item_spec') or '').strip(),
                    quantity=qty,
                    unit_price=price,
                    amount=amount,
                    unit=(it.get('unit') or '').strip(),
                    note=(it.get('note') or '').strip(),
                    delivery_date=dlv_date,
                ))
                total_amount += amount

            po.total_amount = total_amount
            po.tax_amount = round(total_amount * 0.1)
            log_activity(db, '발주관리', 'edit', f'{po.po_no} 수정', ref_type='PurchaseOrder', ref_id=po.id, ref_label=po.po_no)
            db.commit()
            return jsonify(ok=True)
        except Exception as e:
            db.rollback()
            current_app.logger.exception('app po_edit failed po=%s', po_id)
            return jsonify(ok=False, error=str(e)), 500


# ── 발주 삭제 ──

@app_api_bp.route('/purchase-orders/<int:po_id>/delete', methods=['POST'])
@app_auth_required
def app_po_delete(po_id):
    """발주서 삭제 — 연결 입고가 있으면 불가 (ERP 동일)"""
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404
        linked_rcv = db.query(Receiving).filter(Receiving.po_id == po_id).first()
        if linked_rcv:
            return jsonify(ok=False, error=f'입고({linked_rcv.rcv_no})가 연결되어 삭제할 수 없습니다'), 400
        po_no = po.po_no
        log_activity(db, '발주관리', 'delete', f'{po_no} 발주서 삭제', ref_type='PurchaseOrder', ref_label=po_no)
        db.delete(po)
        db.commit()
        return jsonify(ok=True)


# ── 입고 검수 완료 ──

@app_api_bp.route('/receivings/<int:rcv_id>/confirm', methods=['POST'])
@app_auth_required
def app_receiving_confirm(rcv_id):
    """입고 검수 완료 처리"""
    with get_db() as db:
        rcv = db.query(Receiving).get(rcv_id)
        if not rcv:
            return jsonify(ok=False, error='입고 정보를 찾을 수 없습니다'), 404
        rcv.status = '검수완료'
        log_activity(db, '입고관리', 'confirm',
                     f'{rcv.rcv_no} 검수완료',
                     ref_type='Receiving')
        db.commit()
    return jsonify(ok=True)


# ── 생산 공정 토글 ──

# ── 생산 공정 토글 (ProductionProcess ID) ──

@app_api_bp.route('/production/process/<int:process_id>/toggle', methods=['POST'])
@app_auth_required
def app_process_toggle(process_id):
    """생산 공정 ON/OFF 토글"""
    from modules.services.production_actions import handle_process_toggle
    data = request.get_json(silent=True) or {}
    is_active = data.get('active', True)

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        current_user = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        result, status_code = handle_process_toggle(db, process_id, is_active, '', current_user)
        if not result.get('ok', True):
            return jsonify(ok=False, error=result.get('message', '오류')), status_code or 400
        db.commit()
    return jsonify(ok=True)


@app_api_bp.route('/production/process/<int:process_id>/daily-log', methods=['POST'])
@app_auth_required
def app_process_daily_log(process_id):
    """생산 공정 일일 수량 입력"""
    from modules.services.production_actions import handle_process_daily_log
    data = request.get_json(silent=True) or {}
    daily_qty = data.get('daily_qty')

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        current_user = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        result, status_code = handle_process_daily_log(db, process_id, daily_qty, current_user)
        if not result.get('ok', True):
            return jsonify(ok=False, error=result.get('message', '오류')), status_code or 400
        db.commit()
    return jsonify(ok=True, progress_qty=result.get('progress_qty', 0), progress_pct=result.get('progress_pct', 0))


@app_api_bp.route('/production/process/<int:process_id>/complete', methods=['POST'])
@app_auth_required
def app_process_complete(process_id):
    """생산 공정 완료/완료해제"""
    from modules.services.production_actions import handle_process_complete
    data = request.get_json(silent=True) or {}
    complete = data.get('complete', True)

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        current_user = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        result, status_code = handle_process_complete(db, process_id, complete, current_user)
        if not result.get('ok', True):
            return jsonify(ok=False, error=result.get('message', '오류')), status_code or 400
        db.commit()
    return jsonify(ok=True)


@app_api_bp.route('/production/<int:item_id>/status', methods=['POST'])
@app_auth_required
def app_production_status(item_id):
    """생산 품목 상태 변경"""
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if not new_status:
        return jsonify(ok=False, error='상태를 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        ci = db.query(ContractItem).get(item_id)
        if not ci:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404
        old_status = ci.status_prod
        ci.status_prod = new_status

        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'

        contract = ci.contract
        project_id = contract.project_id if contract else None
        if project_id:
            append_history_log(
                db, project_id, user_name,
                f'생산상태 변경: {ci.model_name or ci.category} — {old_status} → {new_status}',
                scope='생산관리', user_id=user_id,
            )
        log_activity(db, '생산관리', 'status_change',
                     f'품목 {ci.id} 생산상태 {old_status}→{new_status}',
                     ref_type='ContractItem')
        db.commit()
    return jsonify(ok=True)


# ── AS 케이스 상태 변경 ──

@app_api_bp.route('/warranty-cases/<int:case_id>/status', methods=['POST'])
@app_auth_required
def app_warranty_status(case_id):
    """AS 케이스 상태 변경"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if new_status not in ('접수', '처리중', '완료'):
        return jsonify(ok=False, error='유효하지 않은 상태입니다'), 400

    with get_db() as db:
        case = db.query(WarrantyCase).get(case_id)
        if not case:
            return jsonify(ok=False, error='AS 케이스를 찾을 수 없습니다'), 404
        case.status = new_status
        if new_status == '완료':
            case.completed_date = datetime.date.today()
        log_activity(db, 'AS관리', 'status_change',
                     f'{case.case_no} 상태변경 → {new_status}',
                     ref_type='WarrantyCase')
        db.commit()
    return jsonify(ok=True)


# ── 납품 상세 ──

@app_api_bp.route('/delivery-projects/<int:project_id>')
@app_auth_required
def app_delivery_project_detail(project_id):
    """납품관리 — 프로젝트 단위 상세 (ERP delivery_detail과 동일 데이터)"""
    from modules.services.delivery_actions import sync_deliveries, normalize_photo_type
    from modules.history_board import get_project_history_context
    from modules.models import User as _User
    today = datetime.date.today()

    with get_db() as db:
        project = db.query(Project).options(
            joinedload(Project.contacts),
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.deliveries).joinedload(Delivery.splits).joinedload(DeliverySplit.split_items).joinedload(DeliverySplitItem.contract_item),
            joinedload(Project.deliveries).joinedload(Delivery.photos),
        ).get(project_id)
        if not project:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404

        sync_deliveries(db, project_id=project_id)
        db.commit()

        # 동기화 후 다시 로드 (최신 상태)
        project = db.query(Project).options(
            joinedload(Project.contacts),
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.deliveries).joinedload(Delivery.splits).joinedload(DeliverySplit.split_items).joinedload(DeliverySplitItem.contract_item),
            joinedload(Project.deliveries).joinedload(Delivery.photos),
        ).get(project_id)

        contacts = [{
            'id': ct.id, 'category': ct.category or '', 'name': ct.name or '',
            'phone': ct.phone or '', 'email': ct.email or '',
        } for ct in (project.contacts or [])]

        deliveries_out = []
        for d in (project.deliveries or []):
            # 모델별 집계
            item_stats = {}
            c = d.contract
            if c:
                for ci in (c.items or []):
                    item_stats[ci.id] = {
                        'item_id': ci.id,
                        'category': ci.category or '',
                        'model_name': ci.model_name or '',
                        'planned': ci.quantity or 0,
                        'delivered': 0,
                    }
            today_split_count = 0
            overdue_split_count = 0
            for sp in (d.splits or []):
                is_done = (sp.status or '') in ('done', '완료')
                for si in (sp.split_items or []):
                    cid = si.contract_item_id
                    if cid not in item_stats:
                        ci = si.contract_item
                        item_stats[cid] = {
                            'item_id': cid,
                            'category': ci.category if ci else '',
                            'model_name': ci.model_name if ci else '',
                            'planned': 0,
                            'delivered': 0,
                        }
                    if is_done:
                        item_stats[cid]['delivered'] += (si.quantity or 0)
                base_date = sp.confirmed_date or sp.scheduled_date
                if base_date == today:
                    today_split_count += 1
                if base_date and base_date < today and (sp.status or '') not in ('done', '완료'):
                    overdue_split_count += 1

            # 사진 분류
            photo_counts = {'production_done': 0, 'loading': 0, 'delivery_done': 0, 'etc': 0}
            photos_out = []
            for ph in (d.photos or []):
                t = normalize_photo_type(ph.photo_type)
                photo_counts[t] = photo_counts.get(t, 0) + 1
                photos_out.append({
                    'id': ph.id, 'photo_type': t, 'file_name': ph.file_name or '',
                    'uploaded_by': ph.uploaded_by or '',
                    'created_at': ph.created_at.strftime('%m/%d %H:%M') if ph.created_at else '',
                    'split_id': ph.split_id,
                })

            splits_out = []
            for sp in sorted(d.splits or [], key=lambda s: s.split_no or 0):
                base_date = sp.confirmed_date or sp.scheduled_date
                splits_out.append({
                    'id': sp.id, 'split_no': sp.split_no or 0,
                    'quantity': sp.quantity or 0,
                    'scheduled_date': str(sp.scheduled_date) if sp.scheduled_date else '',
                    'confirmed_date': str(sp.confirmed_date) if sp.confirmed_date else '',
                    'loading_done_at': sp.loading_done_at.strftime('%Y-%m-%dT%H:%M') if sp.loading_done_at else '',
                    'delivered_done_at': sp.delivered_done_at.strftime('%Y-%m-%dT%H:%M') if sp.delivered_done_at else '',
                    'status': sp.status or 'waiting',
                    'note': sp.note or '',
                    'is_today': base_date == today,
                    'is_overdue': bool(base_date and base_date < today and (sp.status or '') not in ('done', '완료')),
                    'split_items': [{
                        'contract_item_id': si.contract_item_id,
                        'category': (si.contract_item.category if si.contract_item else ''),
                        'model_name': (si.contract_item.model_name if si.contract_item else ''),
                        'quantity': si.quantity or 0,
                    } for si in (sp.split_items or [])],
                })

            progress_pct = round(((d.delivered_total_qty or 0) / (d.planned_total_qty or 1)) * 100, 1) if (d.planned_total_qty or 0) > 0 else 0
            needs_done_photo = bool((d.planned_total_qty or 0) > 0 and (d.delivered_total_qty or 0) >= (d.planned_total_qty or 0) and photo_counts.get('delivery_done', 0) == 0)

            deliveries_out.append({
                'id': d.id,
                'contract_id': d.contract_id,
                'contract_name': (d.contract.contract_name if d.contract else '미연결 계약'),
                'delivery_status': d.delivery_status or 'waiting',
                'planned_total_qty': d.planned_total_qty or 0,
                'delivered_total_qty': d.delivered_total_qty or 0,
                'progress_pct': progress_pct,
                'contact_name': d.contact_name or '',
                'contact_phone': d.contact_phone or '',
                'inspection_status': d.inspection_status or '미검수',
                'inspection_date': str(d.inspection_date) if d.inspection_date else '',
                'inspection_note': d.inspection_note or '',
                'inspector': d.inspector or '',
                'item_stats': list(item_stats.values()),
                'today_split_count': today_split_count,
                'overdue_split_count': overdue_split_count,
                'needs_done_photo': needs_done_photo,
                'photo_counts': photo_counts,
                'photos': photos_out,
                'splits': splits_out,
                'is_unassigned': not bool((d.contact_name or '').strip()),
            })

        # 히스토리
        hist_rows, history_counts = get_project_history_context(db, project_id=project_id, default_scope='delivery', limit=200)
        history = [{
            'id': h.id,
            'user_name': h.user_name or '',
            'content': h.content or '',
            'scope': h.log_scope or '',
            'kind': h.log_kind or 'system',
            'created_at': h.created_at.strftime('%m/%d %H:%M') if h.created_at else '',
        } for h in hist_rows]

        # 담당자 지정용 사용자 목록
        users = db.query(_User).filter(_User.is_approved.is_(True), _User.is_active.is_(True)).order_by(_User.full_name.asc()).all()
        users_out = [{'id': u.id, 'name': u.full_name or '', 'position': u.position or '', 'phone': u.phone_number or ''} for u in users]

        return jsonify(ok=True,
            project={
                'id': project.id,
                'temp_name': project.temp_name or '',
                'project_no': project.project_no or '',
                'contract_count': len(project.contracts or []),
                'delivery_count': len(project.deliveries or []),
                'contact_count': len(project.contacts or []),
            },
            deliveries=deliveries_out,
            contacts=contacts,
            history=history,
            users=users_out,
        )


@app_api_bp.route('/delivery-projects/<int:project_id>/action', methods=['POST'])
@app_auth_required
def app_delivery_project_action(project_id):
    """납품관리 편집 — ERP ACTION_HANDLERS 재사용"""
    from modules.services.delivery_actions import (
        handle_sync_deliveries, handle_add_split, handle_update_split, handle_delete_split,
        handle_assign_delivery_owner, handle_assign_me, handle_delete_photo,
        handle_add_contact, handle_update_contact, handle_delete_contact,
        handle_update_inspection,
    )
    from modules.activity import log_activity

    ACTIONS = {
        'sync_deliveries': handle_sync_deliveries,
        'add_split': handle_add_split,
        'update_split': handle_update_split,
        'delete_split': handle_delete_split,
        'assign_delivery_owner': handle_assign_delivery_owner,
        'assign_me': handle_assign_me,
        'delete_photo': handle_delete_photo,
        'add_contact': handle_add_contact,
        'update_contact': handle_update_contact,
        'delete_contact': handle_delete_contact,
        'update_inspection': handle_update_inspection,
    }

    data = request.get_json(silent=True) or {}
    action = data.get('action', '')
    handler = ACTIONS.get(action)
    if not handler:
        return jsonify(ok=False, error=f'알 수 없는 action: {action}'), 400

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 401
        current_user = f"{user.full_name} {user.position or ''}".strip()

        project = db.query(Project).options(
            joinedload(Project.contacts),
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.deliveries).joinedload(Delivery.splits),
        ).get(project_id)
        if not project:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404

        # item_qtys는 data["item_qtys"]: {contract_item_id: qty} 로 받아서 form dict에 item_qty_{cid}로 주입
        form = dict(data)
        if isinstance(data.get('item_qtys'), dict):
            for cid, qty in data['item_qtys'].items():
                form[f'item_qty_{cid}'] = qty

        user_group = (user.user_group or '').strip()
        can_assign = bool(user.role == 'admin' or user_group in ('영업부서장', '관리부서장', '생산부서장', '부서장'))

        try:
            result = handler(db, project, form, current_user,
                             user_id=user_id, files={}, can_assign_owner=can_assign)
            log_activity(db, '납품관리', action, f'{project.temp_name or project.project_no} 납품 {action}',
                         ref_type='Delivery', project_id=project.id)
            db.commit()
            return jsonify(ok=True, action=action, flash=result.get('flash'))
        except Exception as e:
            db.rollback()
            current_app.logger.exception('app delivery action failed action=%s project=%s', action, project_id)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/delivery-projects/<int:project_id>/photo', methods=['POST'])
@app_auth_required
def app_delivery_add_photo(project_id):
    """납품 사진 업로드 — multipart/form-data (delivery_id, split_id, contract_item_id, photo_type, photo_file)"""
    from modules.services.delivery_actions import handle_add_photo
    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 401
        current_user = f"{user.full_name} {user.position or ''}".strip()

        project = db.query(Project).get(project_id)
        if not project:
            return jsonify(ok=False, error='현장을 찾을 수 없습니다'), 404

        try:
            result = handle_add_photo(db, project, request.form, current_user,
                                      user_id=user_id, files=request.files, can_assign_owner=False)
            db.commit()
            return jsonify(ok=True, flash=result.get('flash'))
        except Exception as e:
            db.rollback()
            current_app.logger.exception('app delivery photo upload failed project=%s', project_id)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/delivery-photo/<int:photo_id>')
@app_auth_required
def app_delivery_view_photo(photo_id):
    """납품 사진 뷰어 (웹 view_delivery_photo와 동일)"""
    from flask import send_file
    from modules.storage_adapter import download_bytes
    import io as _io, os as _os
    with get_db() as db:
        photo = db.query(DeliveryPhoto).get(photo_id)
        if not photo:
            return jsonify(ok=False, error='사진을 찾을 수 없습니다'), 404
        data = download_bytes(photo.storage_path)
        if data is None:
            return jsonify(ok=False, error='파일을 읽을 수 없습니다'), 404
        ext = _os.path.splitext(photo.file_name or '')[1].lower()
        mimetype = 'image/png' if ext == '.png' else 'image/jpeg'
        return send_file(_io.BytesIO(data), mimetype=mimetype, as_attachment=False, download_name=photo.file_name or 'photo.jpg')


@app_api_bp.route('/deliveries/<int:delivery_id>')
@app_auth_required
def app_delivery_detail(delivery_id):
    """납품 상세 — 납품정보 + 분할납품 + 히스토리"""
    from modules.history_board import get_project_history_context
    with get_db() as db:
        d = db.query(Delivery).options(
            joinedload(Delivery.contract).joinedload(Contract.items),
        ).get(delivery_id)
        if not d:
            return jsonify(ok=False, error='납품 정보를 찾을 수 없습니다'), 404

        items = []
        if d.contract and d.contract.items:
            for ci in d.contract.items:
                items.append({
                    'id': ci.id,
                    'category': ci.category or '',
                    'model_name': ci.model_name or '',
                    'quantity': ci.quantity or 0,
                })

        history = []
        if d.project_id:
            hist_rows, _ = get_project_history_context(db, d.project_id, default_scope='납품관리', limit=20)
            for h in hist_rows:
                history.append({
                    'user_name': h.user_name or '',
                    'content': h.content or '',
                    'created_at': str(h.created_at) if h.created_at else '',
                })

        due_date = d.contract.delivery_due_date if d.contract else None
        return jsonify(ok=True, delivery={
            'id': d.id,
            'contract_name': (d.contract.contract_name if d.contract else '') or '',
            'project_id': d.project_id,
            'delivery_status': d.delivery_status or '납품대기',
            'delivery_due_date': str(due_date) if due_date else '',
            'planned_total_qty': d.planned_total_qty or 0,
            'delivered_total_qty': d.delivered_total_qty or 0,
            'inspection_status': d.inspection_status or '',
            'contact_name': d.contact_name or '',
            'contact_phone': d.contact_phone or '',
        }, items=items, history=history)


# ── 알림 읽음 처리 ──

# ── 계약 결제상태 변경 ──

@app_api_bp.route('/contracts/<int:contract_id>/payment-status', methods=['POST'])
@app_auth_required
def app_contract_payment_status(contract_id):
    """계약 결제상태 변경"""
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    valid = ('미청구', '청구완료', '부분입금', '입금완료')
    if new_status not in valid:
        return jsonify(ok=False, error=f'유효하지 않은 상태입니다. ({", ".join(valid)})'), 400

    user_id = request._app_user_id
    with get_db() as db:
        c = db.query(Contract).get(contract_id)
        if not c:
            return jsonify(ok=False, error='계약을 찾을 수 없습니다'), 404
        old = c.payment_status
        c.payment_status = new_status
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        if c.project_id:
            append_history_log(db, c.project_id, user_name,
                f'결제상태 변경: {old} → {new_status}', scope='common')
        log_activity(db, '계약관리', 'payment_status', f'{c.contract_name} 결제상태 {old}→{new_status}', ref_type='Contract')
        db.commit()
    return jsonify(ok=True)


# ── 품목 상태 변경 (관리/생산/영업) ──

@app_api_bp.route('/contract-items/<int:item_id>/status', methods=['POST'])
@app_auth_required
def app_contract_item_status(item_id):
    """품목별 부서 상태 변경"""
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    field = data.get('field', '')  # status_admin, status_prod, status_sales
    new_status = data.get('status', '').strip()
    if field not in ('status_admin', 'status_prod', 'status_sales') or not new_status:
        return jsonify(ok=False, error='field와 status를 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        ci = db.query(ContractItem).get(item_id)
        if not ci:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404
        old = getattr(ci, field)
        setattr(ci, field, new_status)
        field_label = {'status_admin': '관리상태', 'status_prod': '생산상태', 'status_sales': '영업상태'}[field]
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        contract = ci.contract
        if contract and contract.project_id:
            append_history_log(db, contract.project_id, user_name,
                f'{ci.model_name or ci.category} {field_label} 변경: {old} → {new_status}',
                scope='common')
        log_activity(db, '계약관리', 'item_status', f'품목 {ci.id} {field_label} {old}→{new_status}', ref_type='ContractItem')
        db.commit()
    return jsonify(ok=True)


# ── 납품 분할납품 생성 ──

@app_api_bp.route('/deliveries/<int:delivery_id>/splits', methods=['POST'])
@app_auth_required
def app_delivery_add_split(delivery_id):
    """분할납품 추가"""
    from modules.models.delivery_entities import DeliverySplit
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    scheduled_date = data.get('scheduled_date', '').strip()
    if not scheduled_date:
        return jsonify(ok=False, error='예정일을 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        d = db.query(Delivery).get(delivery_id)
        if not d:
            return jsonify(ok=False, error='납품 정보를 찾을 수 없습니다'), 404
        max_no = max([s.split_no or 0 for s in (d.splits or [])] or [0])
        split = DeliverySplit(
            delivery_id=d.id,
            split_no=max_no + 1,
            scheduled_date=scheduled_date,
            status='pending',
        )
        db.add(split)
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        if d.project_id:
            append_history_log(db, d.project_id, user_name,
                f'분할납품 {max_no+1}차 추가 (예정: {scheduled_date})', scope='납품관리')
        db.commit()
    return jsonify(ok=True)


# ── 발주서 생성 ──

@app_api_bp.route('/purchase-orders/create', methods=['POST'])
@app_auth_required
def app_po_create():
    """발주서 신규 생성 — ERP po_create POST와 동일 로직"""
    from routes.purchase_order import _generate_po_no
    data = request.get_json(silent=True) or {}
    vendor_id = data.get('vendor_id')
    if not vendor_id:
        return jsonify(ok=False, error='거래처를 선택해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        vendor = db.query(Vendor).get(int(vendor_id))
        if not vendor:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404

        try:
            po_date = datetime.datetime.strptime(data.get('po_date', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            po_date = datetime.date.today()

        assigned = data.get('assigned_to')
        contract_id = data.get('contract_id')
        project_id = None
        if contract_id:
            c = db.query(Contract).get(int(contract_id))
            if c:
                project_id = c.project_id

        po = PurchaseOrder(
            po_no=_generate_po_no(db),
            po_date=po_date,
            vendor_id=vendor.id,
            project_id=project_id,
            contract_id=int(contract_id) if contract_id else None,
            assigned_to=int(assigned) if assigned else user_id,
            status='작성중',
            note=(data.get('note') or '').strip(),
            created_by=user_id,
        )
        db.add(po)
        db.flush()

        total_amount = 0
        for it in (data.get('items') or []):
            name = (it.get('item_name') or '').strip()
            if not name:
                continue
            qty = float(it.get('quantity') or 0)
            price = float(it.get('unit_price') or 0)
            amount = qty * price
            dlv_date = None
            if it.get('delivery_date'):
                try:
                    dlv_date = datetime.date.fromisoformat(it['delivery_date'])
                except ValueError:
                    pass
            db.add(PurchaseOrderItem(
                po_id=po.id,
                item_id=(int(it['item_id']) if it.get('item_id') else None),
                item_code=(it.get('item_code') or '').strip() or None,
                item_name=name,
                item_spec=(it.get('item_spec') or '').strip(),
                quantity=qty,
                unit_price=price,
                amount=amount,
                unit=(it.get('unit') or '').strip(),
                note=(it.get('note') or '').strip(),
                delivery_date=dlv_date,
            ))
            total_amount += amount

        po.total_amount = total_amount
        po.tax_amount = round(total_amount * 0.1)
        log_activity(db, '발주관리', 'create',
                     f'{po.po_no} 발주서 등록 ({vendor.name})',
                     ref_type='PurchaseOrder', ref_id=po.id, ref_label=po.po_no, project_id=po.project_id)
        db.commit()
        return jsonify(ok=True, po_id=po.id, po_no=po.po_no)


# ── 사용자 목록 (담당자 지정용) ──

@app_api_bp.route('/users')
@app_auth_required
def app_users_list():
    """승인된 활성 사용자 목록"""
    with get_db() as db:
        users = db.query(User).filter(User.is_approved.is_(True), User.is_active.is_(True)).order_by(User.full_name).all()
        return jsonify(ok=True, users=[{
            'id': u.id,
            'name': u.full_name or '',
            'position': u.position or '',
            'user_group': u.user_group or '',
            'email': u.email or '',
            'phone': u.phone_number or '',
        } for u in users])


# ── 거래처 검색 (PO 생성폼 자동완성) ──

@app_api_bp.route('/vendors/search')
@app_auth_required
def app_vendor_search():
    """거래처 자동완성 (웹 api_vendor_search와 동일)"""
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(Vendor).filter(Vendor.is_active.is_(True))
        if q:
            query = query.filter(Vendor.name.ilike(f'%{q}%'))
        vendors = query.order_by(Vendor.name).limit(20).all()
        return jsonify(ok=True, vendors=[{
            'id': v.id, 'name': v.name,
            'email': v.email or '', 'tel': v.tel or '',
            'ceo_name': v.ceo_name or '',
            'business_no': v.business_no or '',
        } for v in vendors])


# ── 계약 검색 (PO 생성폼 자동완성) ──

@app_api_bp.route('/contracts/search')
@app_auth_required
def app_contract_search():
    """계약 자동완성 (웹 api_contract_search와 동일)"""
    from sqlalchemy import or_
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(Contract).join(Project, Project.id == Contract.project_id)
        if q:
            query = query.filter(or_(
                Project.temp_name.ilike(f'%{q}%'),
                Contract.contract_name.ilike(f'%{q}%'),
                Project.project_no.ilike(f'%{q}%'),
            ))
        contracts = query.options(joinedload(Contract.project)).order_by(desc(Contract.id)).limit(20).all()
        return jsonify(ok=True, contracts=[{
            'id': c.id,
            'project_id': c.project_id,
            'site_name': c.project.temp_name if c.project else '',
            'contract_name': c.contract_name or '',
            'item_group': c.item_group or '',
            'label': f"{c.project.temp_name if c.project else ''} - {c.contract_name or ''}",
        } for c in contracts])


# ── 발주 PDF 다운로드 ──

@app_api_bp.route('/purchase-orders/<int:po_id>/pdf')
def app_po_pdf(po_id):
    """발주서 PDF 다운로드 — 토큰 쿼리스트링 인증, ERP generate_po_pdf(po, vendor, items)"""
    if not _verify_token_from_request():
        return jsonify(ok=False, error='인증이 필요합니다'), 401
    from flask import make_response
    from modules.services.po_pdf import generate_po_pdf
    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.vendor),
            joinedload(PurchaseOrder.items),
        ).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404
        try:
            pdf_bytes = generate_po_pdf(po, po.vendor, po.items)
            resp = make_response(pdf_bytes)
            resp.headers['Content-Type'] = 'application/pdf'
            resp.headers['Content-Disposition'] = f'inline; filename="{po.po_no}.pdf"'
            return resp
        except Exception as e:
            current_app.logger.exception('app po_pdf failed po=%s', po_id)
            return jsonify(ok=False, error=str(e)), 500


# ── 발주 이메일 전송 (웹 po_send_email 전체 로직 이식) ──

@app_api_bp.route('/purchase-orders/<int:po_id>/send-email', methods=['POST'])
@app_auth_required
def app_po_send_email(po_id):
    """발주서 이메일 전송 — 웹 po_send_email과 동일 본문/제목/서명/이력저장"""
    from modules.services.po_pdf import generate_po_pdf
    from modules.services.email_sender import send_purchase_order_email
    from modules.models import EmailHistory
    from routes.purchase_order import _sync_po_to_material_orders

    user_id = request._app_user_id
    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.vendor),
            joinedload(PurchaseOrder.items),
        ).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404

        vendor = po.vendor
        if not vendor or not vendor.email:
            return jsonify(ok=False, error='거래처 이메일이 등록되지 않았습니다'), 400

        pdf_bytes = generate_po_pdf(po, vendor, po.items)
        po_date_str = po.po_date.strftime('%y%m%d') if po.po_date else ''
        pdf_filename = f'{po.po_no}.pdf'
        po_items = po.items or []
        if po_items:
            first_name = po_items[0].item_name or '품목'
            item_summary = f'{first_name}외 {len(po_items) - 1}건' if len(po_items) > 1 else first_name
        else:
            item_summary = '발주'
        subject = f'(주)매그나텍 {item_summary} 발주서 송부의건_{po_date_str}'

        body_lines = [
            '귀 사의 번창을 기원합니다.', '',
            '당사 발주건 관련하여 아래와 같이 발주를 요청하오니 검토하여 주시기 바랍니다.', '', '',
            '■ 발주내용 요약', '',
            f'{"No":<4s} {"품목":<25s} {"규격":<20s} {"수량":>8s} {"단위":<5s}',
            '-' * 65,
        ]
        for idx, item in enumerate(po_items, 1):
            name = (item.item_name or '')[:24]
            spec = (item.item_spec or '')[:19]
            qty = f'{item.quantity:,.0f}' if item.quantity else '0'
            unit = item.unit or ''
            body_lines.append(f'{idx:<4d} {name:<25s} {spec:<20s} {qty:>8s} {unit:<5s}')
        body_lines.extend([
            '', '', '발주서를 첨부파일로 송부드리오니 업무에 참고바랍니다.', '', '감사합니다.', '', '',
            '─' * 40,
            '위 메일 및 첨부자료는 지정된 수신인만을 위한 것이며 관련법령에 의해 보호대상이 되는',
            '기밀사항을 포함할 수 있습니다.',
            '본 메일, 혹은 첨부자료에 포함된 내용을 무단으로 조사, 사용, 복사, 공개 혹은 배포하는',
            '행위는 엄격히 금지되어 있습니다.',
            '이 메일이 잘못 전송된 경우에는 본 메일 및 첨부자료를 복사하거나 공개하지 마시고',
            '발신인에게 알려주시고 메일 및 첨부자료는 즉시 삭제해주시기 바랍니다.', '',
        ])

        sig_user_id = po.assigned_to or user_id
        sig_user = db.query(User).get(sig_user_id) if sig_user_id else None
        sig_lines = ['=' * 65]
        title = '(주)매그나텍'
        if sig_user:
            if sig_user.user_group:
                title += f' {sig_user.user_group}'
            title += f' {sig_user.full_name}'
            if sig_user.position:
                title += f' {sig_user.position}'
        sig_lines.append(title)
        sig_lines.append(f'E-mail : {sig_user.email if sig_user and sig_user.email else "purchase@mgnt.kr"}')
        if sig_user and sig_user.phone_number:
            sig_lines.append(f'Mobile : {sig_user.phone_number}')
        sig_lines.append(f'Office : {sig_user.office_tel if sig_user and sig_user.office_tel else "061-392-5508"}')
        sig_lines.append(f'Fax    : {sig_user.office_fax if sig_user and sig_user.office_fax else "061-392-5518"}')
        sig_lines.append('주  소 : 전라남도 장성군 동화면 전자농공단지2길 55')
        sig_lines.append('홈페이지 : https://www.magnatech.co.kr')
        sig_lines.append('=' * 65)
        body_lines.extend(sig_lines)
        body = '\n'.join(body_lines)

        result = send_purchase_order_email(
            to_email=vendor.email, subject=subject, body_text=body,
            pdf_bytes=pdf_bytes, pdf_filename=pdf_filename,
        )

        db.add(EmailHistory(
            sender='purchase@mgnt.kr',
            receiver=vendor.email,
            subject=subject,
            content=body,
            attachment=pdf_filename,
            is_success=result['success'],
            error_message=result['message'] if not result['success'] else None,
            po_id=po.id,
        ))

        if result['success']:
            po.status = '발송완료'
            po.email_sent_at = datetime.datetime.now()
            po.email_to = vendor.email
            if po.contract_id:
                _sync_po_to_material_orders(db, po)
            log_activity(db, '발주관리', 'email',
                         f'{po.po_no} 이메일 발송 → {vendor.email}',
                         ref_type='PurchaseOrder', ref_id=po.id, ref_label=po.po_no, project_id=po.project_id)
            db.commit()
            return jsonify(ok=True, email_to=vendor.email,
                           sent_at=po.email_sent_at.strftime('%Y-%m-%d %H:%M'),
                           message=result['message'])
        else:
            db.commit()
            return jsonify(ok=False, error=f'이메일 발송 실패: {result["message"]}'), 500


# ── 입고 생성 ──

# /receivings/create 는 파일 끝에서 items 배열 + PO/FO 연결 방식으로 재정의됨.


# ── 영업 협의 상태 변경 ──

# ── 현장/계약/모델 자동완성 검색 ──

@app_api_bp.route('/search/projects')
@app_auth_required
def app_search_projects():
    """현장 검색 자동완성 — 현장명/약칭/설계번호/계약명 다중 검색
    옵션: status=계약 → 활성 계약건만 (사진관리 등 현장 선택용)
    """
    q = (request.args.get('q') or '').strip()
    only_active = request.args.get('status') == '계약'
    if len(q) < 1:
        return jsonify(ok=True, results=[])
    like = f'%{q}%'
    with get_db() as db:
        # 계약명 검색을 위해 Contract와 outer join
        from sqlalchemy import or_, exists
        contract_match = exists().where(
            (Contract.project_id == Project.id) & (Contract.contract_name.ilike(like))
        )
        query = db.query(Project).filter(
            or_(
                Project.temp_name.ilike(like),
                Project.short_name.ilike(like),
                Project.project_no.ilike(like),
                contract_match,
            )
        )
        if only_active:
            query = query.filter(Project.is_contracted.is_(True), active_contract_filter())
        projects = query.order_by(desc(Project.id)).limit(30).all()

        # 첫 계약명 일괄 로딩 (표시용)
        project_ids = [p.id for p in projects]
        contract_name_map = {}
        if project_ids:
            for c in db.query(Contract).filter(Contract.project_id.in_(project_ids))\
                       .order_by(Contract.delivery_due_date).all():
                contract_name_map.setdefault(c.project_id, c.contract_name or '')

        return jsonify(ok=True, results=[{
            'id': p.id,
            'name': p.temp_name or '',
            'short_name': p.short_name or '',
            'project_no': p.project_no or '',
            'contract_name': contract_name_map.get(p.id, ''),
            'status': p.status or '',
        } for p in projects])


@app_api_bp.route('/search/warranties')
@app_auth_required
def app_search_warranties():
    """보증 검색 (AS접수용) — 현장명/계약명/모델명 검색"""
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify(ok=True, results=[])
    with get_db() as db:
        warranties = db.query(Warranty).filter(
            (Warranty.contract_name.ilike(f'%{q}%'))
            | (Warranty.item_group.ilike(f'%{q}%'))
            | (Warranty.model_name.ilike(f'%{q}%'))
        ).order_by(desc(Warranty.id)).limit(15).all()
        return jsonify(ok=True, results=[{
            'id': w.id,
            'contract_name': w.contract_name or '',
            'item_group': w.item_group or '',
            'model_name': w.model_name or '',
            'project_id': w.project_id,
            'warranty_start': str(w.warranty_start) if w.warranty_start else '',
            'warranty_end': str(w.warranty_end) if w.warranty_end else '',
        } for w in warranties])


@app_api_bp.route('/warranty-defect-types')
@app_auth_required
def app_warranty_defect_types():
    """하자유형 목록"""
    from modules.models import DEFECT_TYPES
    return jsonify(ok=True, defect_types=[{'code': c, 'label': l} for c, l in DEFECT_TYPES])


# ── 가공발주 상세 ──

@app_api_bp.route('/processing-orders/<int:fo_id>')
@app_auth_required
def app_processing_order_detail(fo_id):
    """가공발주 상세 — 정보 + 품목 + 첨부파일 + 히스토리 (ERP fo_detail 동일)"""
    import json as _json
    from modules.models.procurement_entities import ProcessingOrderFile, FO_STATUS_CHOICES, FO_TYPE_CHOICES
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(
            joinedload(ProcessingOrder.vendor),
            joinedload(ProcessingOrder.project),
            joinedload(ProcessingOrder.contract),
            joinedload(ProcessingOrder.items),
            joinedload(ProcessingOrder.files),
            joinedload(ProcessingOrder.assignee),
        ).get(fo_id)
        if not fo:
            return jsonify(ok=False, error='가공발주를 찾을 수 없습니다'), 404

        items_list = [{
            'id': it.id, 'item_id': it.item_id,
            'item_name': it.item_name or '', 'item_spec': it.item_spec or '',
            'quantity': it.quantity or 0, 'unit': it.unit or '',
            'unit_price': it.unit_price or 0, 'amount': it.amount or 0,
            'delivery_date': str(it.delivery_date) if it.delivery_date else '',
            'processing_note': it.processing_note or '', 'note': it.note or '',
            'in_confirmed': bool(it.in_confirmed),
            'in_confirmed_at': it.in_confirmed_at.strftime('%m/%d %H:%M') if it.in_confirmed_at else '',
        } for it in (fo.items or [])]

        files_list = [{
            'id': f.id, 'file_name': f.file_name or '',
            'file_type': (f.file_type or '').lower(), 'file_size': f.file_size or 0,
            'is_reference': bool(f.is_reference),
            'is_image': (f.file_type or '').lower() in ('jpg', 'jpeg', 'png', 'webp', 'gif'),
            'uploaded_at': str(f.uploaded_at) if f.uploaded_at else '',
        } for f in (fo.files or [])]

        history = []
        if fo.history_log:
            try:
                history = _json.loads(fo.history_log)
            except Exception:
                history = []

        return jsonify(ok=True, fo={
            'id': fo.id, 'fo_no': fo.fo_no or '',
            'fo_date': str(fo.fo_date) if fo.fo_date else '',
            'vendor_id': fo.vendor_id,
            'vendor_name': fo.vendor.name if fo.vendor else '',
            'vendor_email': fo.vendor.email if fo.vendor else '',
            'project_id': fo.project_id,
            'project_name': fo.project.temp_name if fo.project else '',
            'contract_id': fo.contract_id,
            'contract_name': fo.contract.contract_name if fo.contract else '',
            'assigned_to': fo.assigned_to,
            'assignee_name': fo.assignee.full_name if fo.assignee else '',
            'processing_type': fo.processing_type or '',
            'status': fo.status or '',
            'total_amount': fo.total_amount or 0,
            'tax_amount': fo.tax_amount or 0,
            'note': fo.note or '',
        }, items=items_list, files=files_list, history=history,
           status_choices=FO_STATUS_CHOICES, type_choices=FO_TYPE_CHOICES)


# ── 가공발주 첨부파일 서빙 ──

@app_api_bp.route('/processing-orders/files/<int:file_id>/view')
def app_fo_file_view(file_id):
    """가공발주 첨부파일 서빙 (토큰 인증)"""
    import os
    from flask import Response, abort
    from modules.storage_adapter import download_bytes
    from modules.models.procurement_entities import ProcessingOrderFile

    token = request.args.get('_t', '')
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
    if not token or not _verify_token(token):
        abort(401)

    # 썸네일
    thumb = request.args.get('thumb', '') == '1'

    with get_db() as db:
        f = db.query(ProcessingOrderFile).get(file_id)
        if not f:
            abort(404)
        data = download_bytes(f.file_path)
        if not data:
            abort(404)

        ext = os.path.splitext(f.file_name)[1].lower().lstrip('.')
        is_image = ext in ('jpg', 'jpeg', 'png', 'webp', 'gif')

        if thumb and is_image:
            cache_dir = '/tmp/fo_thumb_cache'
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, f'{file_id}.jpg')
            if os.path.exists(cache_path):
                with open(cache_path, 'rb') as cf:
                    resp = Response(cf.read(), mimetype='image/jpeg')
                    resp.headers['Cache-Control'] = 'public, max-age=86400'
                    return resp
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(data))
                img.thumbnail((300, 300))
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=60)
                data = buf.getvalue()
                with open(cache_path, 'wb') as cf:
                    cf.write(data)
            except Exception:
                pass
            resp = Response(data, mimetype='image/jpeg')
            resp.headers['Cache-Control'] = 'public, max-age=86400'
            return resp

        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'pdf': 'application/pdf', 'dwg': 'application/octet-stream'}
        return Response(data, mimetype=mime_map.get(ext, 'application/octet-stream'))


# ── 입고사진 글쓰기 ──

@app_api_bp.route('/receiving-photos/create', methods=['POST'])
@app_auth_required
def app_receiving_photo_create():
    """입고사진 피드 글쓰기 (multipart)"""
    import datetime as _dt
    from modules.storage_adapter import upload_bytes

    content = (request.form.get('content') or '').strip()
    vendor_name = (request.form.get('vendor_name') or '').strip()
    po_no = (request.form.get('po_no') or '').strip()

    if not content:
        return jsonify(ok=False, error='내용을 입력해주세요'), 400

    photos = []
    files = request.files.getlist('photos')
    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else ''
        if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
            continue
        file_content = f.read()
        if len(file_content) > 20 * 1024 * 1024:
            continue
        safe_name = f"{_dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
        object_path = f'storage/receiving-photos/{safe_name}'
        ok, msg = upload_bytes(object_path, file_content, f.content_type or 'image/jpeg')
        if ok:
            photos.append({'file_name': f.filename, 'file_path': object_path, 'file_size': len(file_content)})

    user_id = request._app_user_id
    with get_db() as db:
        post = ReceivingPhotoPost(
            content=content,
            photos_json=json.dumps(photos, ensure_ascii=False),
            vendor_name=vendor_name,
            po_no=po_no,
            created_by=user_id,
        )
        db.add(post)
        db.commit()
        log_activity(db, '입고사진', 'create', f'입고사진 등록: {content[:30]}', ref_type='ReceivingPhoto', ref_id=post.id)
        db.commit()
    return jsonify(ok=True, post_id=post.id, photo_count=len(photos))


# ── 입고사진 이미지 서빙 ──

@app_api_bp.route('/receiving-photos/view')
def app_receiving_photo_view():
    """입고사진 이미지 서빙 (file_path 쿼리)"""
    import os
    from flask import Response, abort
    from modules.storage_adapter import download_bytes

    token = request.args.get('_t', '')
    if not token or not _verify_token(token):
        abort(401)

    file_path = request.args.get('path', '')
    if not file_path or '..' in file_path:
        abort(400)

    thumb = request.args.get('thumb', '') == '1'

    if thumb:
        import hashlib
        cache_dir = '/tmp/rcv_photo_thumb'
        os.makedirs(cache_dir, exist_ok=True)
        cache_key = hashlib.md5(file_path.encode()).hexdigest()
        cache_path = os.path.join(cache_dir, f'{cache_key}.jpg')
        if os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                resp = Response(f.read(), mimetype='image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=86400'
                return resp

    data = download_bytes(file_path)
    if not data:
        abort(404)

    if thumb:
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            img.thumbnail((300, 300))
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=60)
            data = buf.getvalue()
            with open(cache_path, 'wb') as f:
                f.write(data)
        except Exception:
            pass
        resp = Response(data, mimetype='image/jpeg')
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    return Response(data, mimetype='image/jpeg')


# ── 사진 서빙 (토큰 인증) ──

@app_api_bp.route('/photos/<int:photo_id>/view')
def app_photo_view(photo_id):
    """사진 이미지 서빙 (토큰 or 헤더 인증)"""
    import os
    from flask import Response, abort
    from modules.storage_adapter import download_bytes
    # 쿼리 파라미터 또는 헤더에서 토큰 확인
    token = request.args.get('_t', '')
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
    if not token or not _verify_token(token):
        abort(401)
    thumb = request.args.get('thumb', '') == '1'
    # 썸네일 캐시 먼저 확인 (DB/Storage 호출 없이)
    if thumb:
        import hashlib
        cache_dir = '/tmp/photo_thumb_cache'
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f'{photo_id}.jpg')
        if os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                resp = Response(f.read(), mimetype='image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=86400'
                return resp

    with get_db() as db:
        photo = db.query(ProjectPhoto).filter(ProjectPhoto.id == photo_id).first()
        if not photo:
            abort(404)
        data = download_bytes(photo.storage_path)
        if not data:
            abort(404)

        if thumb:
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(data))
                img.thumbnail((300, 300))
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=60)
                data = buf.getvalue()
                with open(cache_path, 'wb') as f:
                    f.write(data)
            except Exception:
                pass
            resp = Response(data, mimetype='image/jpeg')
            resp.headers['Cache-Control'] = 'public, max-age=86400'
            return resp

        ext = os.path.splitext(photo.file_name)[1].lower().lstrip('.')
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}
        return Response(data, mimetype=mime_map.get(ext, 'image/jpeg'))


# ── 사진 업로드 ──

@app_api_bp.route('/photos/upload', methods=['POST'])
@app_auth_required
def app_photo_upload():
    """사진 업로드 (multipart/form-data)"""
    import os
    import datetime as _dt
    from werkzeug.utils import secure_filename
    from modules.storage_adapter import upload_bytes

    file = request.files.get('file')
    site_id = request.form.get('site_id', type=int)
    photo_type = request.form.get('photo_type', '기타')

    if not file or not site_id:
        return jsonify(ok=False, error='파일과 현장 ID가 필요합니다'), 400

    allowed = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        return jsonify(ok=False, error='지원하지 않는 파일 형식입니다'), 400

    data = file.read()
    if len(data) > 10 * 1024 * 1024:
        return jsonify(ok=False, error='파일 크기는 10MB 이하여야 합니다'), 400

    ts = _dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    storage_path = f"storage/photos/project_{site_id}/{ts}{ext}"

    ok, err = upload_bytes(storage_path, data, file.mimetype or 'image/jpeg')
    if not ok:
        return jsonify(ok=False, error=err), 500

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        photo = ProjectPhoto(
            project_id=site_id,
            photo_type=photo_type,
            file_name=secure_filename(file.filename),
            storage_path=storage_path,
            uploaded_by=user_name,
        )
        db.add(photo)
        log_activity(db, '사진관리', 'upload', f'{photo.file_name} 업로드', ref_type='ProjectPhoto', project_id=site_id)
        db.commit()
        return jsonify(ok=True, photo_id=photo.id)


# ── 출장 상세 ──

@app_api_bp.route('/business-trips/<int:trip_id>')
@app_auth_required
def app_business_trip_detail(trip_id):
    """출장 상세"""
    with get_db() as db:
        trip = db.query(BusinessTrip).get(trip_id)
        if not trip:
            return jsonify(ok=False, error='출장을 찾을 수 없습니다'), 404
        members = db.query(BusinessTripMember).filter(BusinessTripMember.trip_id == trip_id).all()
        member_list = []
        for m in members:
            member_list.append({
                'id': m.id,
                'user_id': m.user_id,
                'user_name': m.user_name or '',
                'position': m.position or '',
                'department': m.department or '',
            })
        return jsonify(ok=True, trip={
            'id': trip.id,
            'title': trip.title or '',
            'destination': trip.destination or '',
            'purpose': trip.purpose or '',
            'departure_date': str(trip.departure_date) if trip.departure_date else '',
            'return_date': str(trip.return_date) if trip.return_date else '',
            'status': trip.effective_status,
            'vehicle': trip.vehicle or '',
            'note': trip.note or '',
        }, members=member_list)


# ── 출장 삭제 ──

@app_api_bp.route('/business-trips/<int:trip_id>/delete', methods=['POST'])
@app_auth_required
def app_business_trip_delete(trip_id):
    """출장 삭제"""
    with get_db() as db:
        trip = db.query(BusinessTrip).get(trip_id)
        if not trip:
            return jsonify(ok=False, error='출장을 찾을 수 없습니다'), 404
        db.delete(trip)
        log_activity(db, '출장관리', 'delete', f'{trip.title} 삭제', ref_type='BusinessTrip')
        db.commit()
    return jsonify(ok=True)


# ── 서류관리 ──

@app_api_bp.route('/documents')
@app_auth_required
def app_documents():
    """서류 패키지 목록 — 웹 document_list와 동일 쿼리 (납품요구번호 그룹핑, 4단계 상태)"""
    from modules.models.document_entities import DocumentPackage
    from modules.contract_filters import DONE_STATUSES
    q = (request.args.get('search') or request.args.get('q') or '').strip()

    with get_db() as db:
        active_req_nos_subq = db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None),
            Contract.payment_status.notin_(DONE_STATUSES),
            Contract.is_excluded.isnot(True),
        ).subquery()

        query = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.max(G2bProcurement.cntrct_dlvr_req_nm).label('business_name'),
            func.max(G2bProcurement.dminstt_nm).label('demand_org'),
            func.sum(G2bProcurement.prdct_amt).label('supply_amount'),
            func.max(G2bProcurement.dlvr_tmlmt_date).label('delivery_due'),
            func.max(G2bProcurement.cntrct_dlvr_req_date).label('req_date'),
            func.count(G2bProcurement.id).label('item_count'),
        ).filter(
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y',
            G2bProcurement.cntrct_dlvr_req_no.in_(active_req_nos_subq),
        ).group_by(G2bProcurement.cntrct_dlvr_req_no)

        if q:
            like = f'%{q}%'
            query = query.filter(
                G2bProcurement.cntrct_dlvr_req_nm.ilike(like) |
                G2bProcurement.cntrct_dlvr_req_no.ilike(like) |
                G2bProcurement.dminstt_nm.ilike(like)
            )

        groups = query.order_by(func.max(G2bProcurement.cntrct_dlvr_req_date).desc()).all()

        req_nos = [g.cntrct_dlvr_req_no for g in groups]
        packages = {}
        if req_nos:
            pkgs = db.query(DocumentPackage).filter(
                DocumentPackage.procurement_req_no.in_(req_nos)
            ).all()
            packages = {p.procurement_req_no: p for p in pkgs}

        items = []
        for g in groups:
            pkg = packages.get(g.cntrct_dlvr_req_no)
            if pkg and pkg.delivery_generated:
                status = '완료'
            elif pkg and pkg.commencement_generated:
                status = '납품계 생성가능'
            elif pkg and pkg.req_pdf_path:
                status = '착수계 생성가능'
            else:
                status = '계약서 미등록'

            items.append({
                'req_no': g.cntrct_dlvr_req_no or '',
                'procurement_req_no': g.cntrct_dlvr_req_no or '',  # 호환
                'business_name': g.business_name or '-',
                'title': g.business_name or '-',
                'project_name': g.business_name or '',
                'demand_org': g.demand_org or '-',
                'supply_amount': g.supply_amount or 0,
                'delivery_due': str(g.delivery_due) if g.delivery_due else '',
                'req_date': str(g.req_date) if g.req_date else '',
                'item_count': g.item_count or 0,
                'status': status,
                'commencement_generated': bool(pkg and pkg.commencement_generated),
                'delivery_generated': bool(pkg and pkg.delivery_generated),
                'has_contract_pdf': bool(pkg and pkg.req_pdf_path),
            })

        stats = {
            'total': len(items),
            'no_contract': sum(1 for i in items if i['status'] == '계약서 미등록'),
            'commencement_ready': sum(1 for i in items if i['status'] == '착수계 생성가능'),
            'delivery_ready': sum(1 for i in items if i['status'] == '납품계 생성가능'),
            'done': sum(1 for i in items if i['status'] == '완료'),
        }

        return jsonify(ok=True, documents=items, stats=stats)


# ── 서류 패키지 상세 (ERP document_detail과 동일 데이터) ──

def _get_or_create_doc_package(db, req_no, user_name=None):
    """웹 document_detail GET의 auto-create 로직과 동일"""
    from modules.models.document_entities import DocumentPackage, determine_org_type
    package = db.query(DocumentPackage).filter(
        DocumentPackage.procurement_req_no == req_no
    ).first()
    if package:
        return package
    first = db.query(G2bProcurement).filter(
        G2bProcurement.cntrct_dlvr_req_no == req_no,
        G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
    ).first()
    if not first:
        return None
    package = DocumentPackage(
        procurement_req_no=req_no,
        business_name=first.cntrct_dlvr_req_nm,
        demand_org=first.dminstt_nm,
        demand_org_no=first.dminstt_cd,
        org_type=determine_org_type(first.dminstt_nm),
        created_by=user_name or '',
    )
    if first.cntrct_dlvr_req_no:
        contract = db.query(Contract).filter(
            Contract.g2b_contract_no == first.cntrct_dlvr_req_no
        ).first()
        if contract:
            package.contract_id = contract.id
            package.project_id = contract.project_id
    db.add(package)
    try:
        db.commit()
    except Exception:
        db.rollback()
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
    return package


@app_api_bp.route('/documents/<req_no>/detail')
@app_auth_required
def app_document_detail(req_no):
    """서류 패키지 상세 — 웹 document_detail GET과 동일 데이터"""
    from modules.models.document_entities import DocumentAttachment, DOC_ATTACH_TYPES
    user_id = request._app_user_id
    with get_db() as db:
        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()
        if not procurements:
            return jsonify(ok=False, error='해당 납품요구번호의 조달내역이 없습니다'), 404

        user = db.query(User).get(user_id)
        current_user = f"{user.full_name} {user.position or ''}".strip() if user else ''
        package = _get_or_create_doc_package(db, req_no, user_name=current_user)
        if not package:
            return jsonify(ok=False, error='서류 패키지를 생성할 수 없습니다'), 500

        attachments = db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).order_by(DocumentAttachment.sort_order).all()

        agents = db.query(User).filter(User.is_approved == True).order_by(User.full_name).all()

        total_supply = sum(p.prdct_amt or 0 for p in procurements)

        # 현장대리인 이름 표시용
        agent_name = ''
        if package.commencement_agent_id:
            agent = db.query(User).get(package.commencement_agent_id)
            if agent:
                agent_name = f"{agent.full_name} {agent.position or ''}".strip()

        return jsonify(ok=True,
            package={
                'id': package.id,
                'procurement_req_no': package.procurement_req_no or '',
                'business_name': package.business_name or '',
                'demand_org': package.demand_org or '',
                'demand_org_no': package.demand_org_no or '',
                'org_type': package.org_type or '',
                'contract_no': package.contract_no or '',
                'contract_date': str(package.contract_date) if package.contract_date else '',
                'fee': package.fee or 0,
                'supply_amount': package.supply_amount or total_supply,
                'total_amount': package.total_amount or 0,
                'warranty_period': package.warranty_period or '',
                'inspection_org': package.inspection_org or '',
                'acceptance_org': package.acceptance_org or '',
                'req_pdf_path': package.req_pdf_path or '',
                'commencement_doc_no': package.commencement_doc_no or '',
                'commencement_date': str(package.commencement_date) if package.commencement_date else '',
                'commencement_agent_id': package.commencement_agent_id,
                'commencement_agent_name': agent_name,
                'commencement_generated': bool(package.commencement_generated),
                'delivery_doc_no': package.delivery_doc_no or '',
                'delivery_date': str(package.delivery_date) if package.delivery_date else '',
                'delivery_generated': bool(package.delivery_generated),
            },
            procurements=[{
                'id': p.id,
                'dtil_prdct_clsfc_no_nm': p.dtil_prdct_clsfc_no_nm or '',
                'prdct_clsfc_no_nm': p.prdct_clsfc_no_nm or '',
                'prdct_idnt_no_nm': p.prdct_idnt_no_nm or '',
                'prdct_uprc': p.prdct_uprc or 0,
                'prdct_qty': p.prdct_qty or 0,
                'prdct_amt': p.prdct_amt or 0,
                'dlvr_tmlmt_date': str(p.dlvr_tmlmt_date) if p.dlvr_tmlmt_date else '',
                'cntrct_dlvr_req_date': str(p.cntrct_dlvr_req_date) if p.cntrct_dlvr_req_date else '',
            } for p in procurements],
            attachments=[{
                'id': a.id,
                'file_type': a.file_type or '',
                'file_type_label': DOC_ATTACH_TYPES.get(a.file_type, a.file_type),
                'file_name': a.file_name or '',
                'storage_path': a.storage_path or '',
                'sort_order': a.sort_order or 0,
            } for a in attachments],
            agents=[{'id': u.id, 'name': u.full_name or '', 'position': u.position or ''} for u in agents],
            total_supply=total_supply,
            doc_attach_types=DOC_ATTACH_TYPES,
        )


@app_api_bp.route('/documents/<req_no>/upload-contract', methods=['POST'])
@app_auth_required
def app_document_upload_contract(req_no):
    """계약서(납품요구서) PDF 업로드 + 자동 파싱 — 웹 _handle_upload_contract_pdf 재사용"""
    from routes.document import _handle_upload_contract_pdf
    with get_db() as db:
        package = _get_or_create_doc_package(db, req_no)
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()
        try:
            _handle_upload_contract_pdf(db, package, procurements)
            return jsonify(ok=True,
                contract_no=package.contract_no,
                contract_date=str(package.contract_date) if package.contract_date else '',
                fee=package.fee,
                warranty_period=package.warranty_period,
                inspection_org=package.inspection_org,
                acceptance_org=package.acceptance_org,
                org_type=package.org_type,
            )
        except Exception as e:
            db.rollback()
            current_app.logger.exception('document upload-contract failed req_no=%s', req_no)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/documents/<req_no>/save-commencement', methods=['POST'])
@app_auth_required
def app_document_save_commencement(req_no):
    """착수계 정보 저장 — 웹 _handle_save_commencement 동일 로직"""
    from modules.models.document_entities import generate_doc_number
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        package = _get_or_create_doc_package(db, req_no)
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        try:
            cdate = data.get('commencement_date') or None
            if cdate:
                package.commencement_date = datetime.date.fromisoformat(cdate)
            else:
                package.commencement_date = None
            agent_id = data.get('agent_id')
            package.commencement_agent_id = int(agent_id) if agent_id else None
            if not package.commencement_doc_no:
                package.commencement_doc_no = generate_doc_number(db, package.commencement_date)
            db.commit()
            return jsonify(ok=True, commencement_doc_no=package.commencement_doc_no)
        except Exception as e:
            db.rollback()
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/documents/<req_no>/save-delivery', methods=['POST'])
@app_auth_required
def app_document_save_delivery(req_no):
    """납품계 정보 저장 — 웹 _handle_save_delivery 동일 로직"""
    from modules.models.document_entities import generate_doc_number
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        package = _get_or_create_doc_package(db, req_no)
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        try:
            ddate = data.get('delivery_date') or None
            if ddate:
                package.delivery_date = datetime.date.fromisoformat(ddate)
            else:
                package.delivery_date = None
            if not package.delivery_doc_no:
                package.delivery_doc_no = generate_doc_number(db, package.delivery_date)
            db.commit()
            return jsonify(ok=True, delivery_doc_no=package.delivery_doc_no)
        except Exception as e:
            db.rollback()
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/documents/<req_no>/upload-attachment', methods=['POST'])
@app_auth_required
def app_document_upload_attachment(req_no):
    """첨부파일 업로드 — 웹 _handle_upload_attachment 재사용"""
    from routes.document import _handle_upload_attachment
    with get_db() as db:
        package = _get_or_create_doc_package(db, req_no)
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        try:
            _handle_upload_attachment(db, package)
            return jsonify(ok=True)
        except Exception as e:
            db.rollback()
            current_app.logger.exception('document upload-attachment failed req_no=%s', req_no)
            return jsonify(ok=False, error=str(e)), 500


@app_api_bp.route('/documents/<req_no>/attachments/<int:att_id>/delete', methods=['POST'])
@app_auth_required
def app_document_delete_attachment(req_no, att_id):
    """첨부파일 삭제"""
    from modules.models.document_entities import DocumentAttachment
    with get_db() as db:
        package = _get_or_create_doc_package(db, req_no)
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        att = db.query(DocumentAttachment).get(att_id)
        if not att or att.package_id != package.id:
            return jsonify(ok=False, error='첨부파일을 찾을 수 없습니다'), 404
        db.delete(att)
        db.commit()
        return jsonify(ok=True)


# ── 서류 PDF/파일 뷰어 (토큰 쿼리스트링 지원) ──

def _verify_token_from_request():
    """Authorization 헤더 or ?token= 쿼리스트링에서 토큰 추출"""
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else request.args.get('token', '')
    return _verify_token(token) if token else None


@app_api_bp.route('/documents/<req_no>/commencement-pdf')
def app_document_commencement_pdf(req_no):
    """착수계 PDF 다운로드 — 웹 download_commencement_pdf와 동일, 토큰 인증"""
    if not _verify_token_from_request():
        return jsonify(ok=False, error='인증이 필요합니다'), 401
    from flask import send_file
    from modules.services.commencement_pdf import generate_commencement_pdf
    from modules.models.document_entities import DocumentPackage, DocumentAttachment
    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()
        agent_user = db.query(User).get(package.commencement_agent_id) if package.commencement_agent_id else None
        att_list = db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).order_by(DocumentAttachment.sort_order).all()
        pdf_buf = generate_commencement_pdf(package, procurements, agent_user=agent_user, attachments=att_list)
        if not package.commencement_generated:
            package.commencement_generated = True
            db.commit()
        return send_file(pdf_buf, mimetype='application/pdf',
                         as_attachment=True, download_name=f"착수계_{package.business_name or req_no}.pdf")


@app_api_bp.route('/documents/<req_no>/delivery-pdf')
def app_document_delivery_pdf(req_no):
    """납품계 PDF 다운로드 — 웹 download_delivery_pdf와 동일, 토큰 인증"""
    if not _verify_token_from_request():
        return jsonify(ok=False, error='인증이 필요합니다'), 401
    from flask import send_file
    from modules.services.delivery_doc_pdf import generate_delivery_doc_pdf
    from modules.models.document_entities import DocumentPackage, DocumentAttachment
    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404
        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()
        stamp_path = official_stamp_path = None
        for att in db.query(DocumentAttachment).filter(DocumentAttachment.package_id == package.id).all():
            if att.file_type == 'stamp_corporate':
                stamp_path = att.storage_path
            elif att.file_type == 'stamp_official':
                official_stamp_path = att.storage_path
        pdf_buf = generate_delivery_doc_pdf(package, procurements, stamp_path=stamp_path, official_stamp_path=official_stamp_path)
        if not package.delivery_generated:
            package.delivery_generated = True
            db.commit()
        return send_file(pdf_buf, mimetype='application/pdf',
                         as_attachment=True, download_name=f"납품계_{package.business_name or req_no}.pdf")


@app_api_bp.route('/document-file')
def app_document_view_file():
    """저장된 PDF/첨부파일 뷰어 — 토큰 인증, local filesystem or storage"""
    if not _verify_token_from_request():
        return jsonify(ok=False, error='인증이 필요합니다'), 401
    from flask import send_file
    path = request.args.get('path', '').strip()
    if not path:
        return jsonify(ok=False, error='경로 누락'), 400
    # 보안: 서류 관련 경로만 허용
    if not (path.startswith('static/uploads/documents') or path.startswith('documents/')):
        return jsonify(ok=False, error='허용되지 않은 경로'), 403

    import os as _os
    # 1) 로컬 파일
    abs_path = _os.path.join(current_app.root_path, path) if not _os.path.isabs(path) else path
    if _os.path.exists(abs_path):
        return send_file(abs_path)
    # 2) Supabase Storage
    from modules.storage_adapter import download_bytes
    data = download_bytes(path)
    if data is None:
        return jsonify(ok=False, error='파일을 찾을 수 없습니다'), 404
    import io as _io
    ext = _os.path.splitext(path)[1].lower()
    mt = {'.pdf': 'application/pdf', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}.get(ext, 'application/octet-stream')
    return send_file(_io.BytesIO(data), mimetype=mt, download_name=_os.path.basename(path))


# ── 견적 상세 ──

@app_api_bp.route('/quotations/<int:quote_id>')
@app_auth_required
def app_quotation_detail(quote_id):
    """견적서 상세 — 견적정보 + 품목 목록"""
    with get_db() as db:
        q = db.query(Quotation).get(quote_id)
        if not q:
            return jsonify(ok=False, error='견적서를 찾을 수 없습니다'), 404

        items = [{
            'id': i.id,
            'seq': i.seq,
            'item_name': i.item_name or '',
            'item_spec': i.item_spec or '',
            'unit': i.unit or '',
            'quantity': i.quantity or 0,
            'unit_price': i.unit_price or 0,
            'amount': i.amount or 0,
            'note': i.note or '',
        } for i in (q.items or [])]

        surcharges = q.surcharges or []

        return jsonify(ok=True, quotation={
            'id': q.id,
            'quote_no': q.quote_no or '',
            'quote_date': str(q.quote_date) if q.quote_date else '',
            'project_name': q.project_name or '',
            'customer_name': q.customer_name or '',
            'customer_contact': q.customer_contact or '',
            'customer_tel': q.customer_tel or '',
            'customer_email': q.customer_email or '',
            'customer_address': q.customer_address or '',
            'validity_period': q.validity_period or '',
            'delivery_date': q.delivery_date or '',
            'payment_method': q.payment_method or '',
            'total_amount': q.total_amount or 0,
            'grand_total': q.grand_total or 0,
            'tax_included': q.tax_included,
            'note': q.note or '',
            'status': q.status or '',
        }, items=items, surcharges=surcharges)


# ── 영업(협의관리) BOM 옵션 ──

@app_api_bp.route('/bom-options/<path:model_name>')
@app_auth_required
def app_bom_options(model_name):
    """모델명으로 BOM option_schema 반환"""
    import json as _json
    from modules.services.bom_actions import find_bom_by_model_name
    with get_db() as db:
        bom = find_bom_by_model_name(db, model_name)
        if not bom or not bom.option_schema:
            return jsonify(ok=True, options=None)
        try:
            schema = _json.loads(bom.option_schema)
        except (ValueError, TypeError):
            return jsonify(ok=True, options=None)
        return jsonify(ok=True, options=schema, bom_code=bom.product_code)


# ── 영업(협의관리) 품목 스펙 조회 ──

@app_api_bp.route('/sales/<int:item_id>')
@app_auth_required
def app_sales_detail(item_id):
    """영업 품목 상세 — 스펙 + 히스토리"""
    from modules.models.constants import CONTRACT_ITEM_SPEC_SCHEMA
    from modules.history_board import get_project_history_context
    with get_db() as db:
        ci = db.query(ContractItem).options(
            joinedload(ContractItem.contract).joinedload(Contract.project),
        ).get(item_id)
        if not ci:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404

        contract = ci.contract
        project = contract.project if contract else None
        spec = ci.item_spec or {}
        schema = CONTRACT_ITEM_SPEC_SCHEMA.get(ci.category, {})
        required_fields = schema.get('required', [])

        # BOM 옵션 (드롭다운용)
        bom_options = None
        if ci.model_name:
            import json as _json
            from modules.services.bom_actions import find_bom_by_model_name
            bom = find_bom_by_model_name(db, ci.model_name)
            if bom and bom.option_schema:
                try:
                    bom_options = _json.loads(bom.option_schema)
                    # 색온도: 3000K/3K 포함 시에만
                    if bom_options and '색온도' in bom_options and not any(k in (ci.model_name or '') for k in ('3000K', '3K')):
                        bom_options.pop('색온도', None)
                except Exception:
                    pass

        # 히스토리
        history = []
        if project:
            hist_rows, _ = get_project_history_context(db, project.id, default_scope='sales', limit=30)
            for h in hist_rows:
                history.append({
                    'user_name': h.user_name or '',
                    'content': h.content or '',
                    'created_at': str(h.created_at) if h.created_at else '',
                })

        return jsonify(ok=True, item={
            'id': ci.id,
            'category': ci.category or '',
            'model_name': ci.model_name or '',
            'quantity': ci.quantity or 0,
            'status_sales': ci.status_sales or '',
            'status_admin': ci.status_admin or '',
            'status_prod': ci.status_prod or '',
            'spec': spec,
            'required_fields': required_fields,
            'contract_name': (contract.contract_name if contract else '') or '',
            'project_id': project.id if project else None,
            'project_name': (project.temp_name if project else '') or '',
            'delivery_due_date': str(contract.delivery_due_date) if contract and contract.delivery_due_date else '',
            'desired_delivery_date': str(contract.desired_delivery_date) if contract and contract.desired_delivery_date else '',
            'bom_options': bom_options,
        }, history=history)


# ── 영업(협의관리) 스펙 수정 ──

@app_api_bp.route('/sales/<int:item_id>/spec', methods=['POST'])
@app_auth_required
def app_sales_update_spec(item_id):
    """영업 품목 스펙(협의내용) 수정"""
    from modules.services.sales_actions import _diff_spec, _derive_sales_status
    from modules.history_board import append_history_log
    from modules.notification_engine import notify
    data = request.get_json(silent=True) or {}
    new_spec = data.get('spec', {})
    planned_delivery = data.get('planned_delivery_date', '')

    user_id = request._app_user_id
    with get_db() as db:
        ci = db.query(ContractItem).options(
            joinedload(ContractItem.contract).joinedload(Contract.project),
        ).get(item_id)
        if not ci:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404

        user = db.query(User).get(user_id)
        current_user = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'

        old_status = ci.status_sales or '계약확인'
        old_spec = dict(ci.item_spec or {})

        merged_spec = dict(old_spec)
        merged_spec.update(new_spec)
        ci.item_spec = merged_spec
        ci.status_sales = _derive_sales_status(ci.category, merged_spec)

        contract = ci.contract
        old_planned = contract.desired_delivery_date if contract else None
        if contract and planned_delivery:
            from modules.utils import parse_date
            contract.desired_delivery_date = parse_date(planned_delivery)

        project = contract.project if contract else None
        changed_lines = []
        if old_status != ci.status_sales:
            changed_lines.append(f"영업단계: {old_status} → {ci.status_sales}")
        spec_changes = _diff_spec(old_spec, merged_spec)
        if spec_changes:
            changed_lines.append('협의내용 변경: ' + '; '.join(spec_changes))
        if contract and old_planned != contract.desired_delivery_date:
            changed_lines.append(f"납품예정일: {old_planned or '-'} → {contract.desired_delivery_date or '-'}")

        if changed_lines and project:
            log_content = (
                f"[협의관리] {current_user}님이 협의내용 수정\n"
                f"대상: {ci.category}/{ci.model_name}({ci.quantity})\n"
                + "\n".join(changed_lines)
            )
            append_history_log(db, project.id, '시스템 🤖', log_content, scope='sales')

            project_name = project.temp_name or project.short_name or f"현장#{project.id}"
            _first_c = contract
            _contract_name = _first_c.contract_name if _first_c else project_name
            notify(db, 'issue.flagged', {
                'contract_name': _contract_name,
                'project_name': project_name,
                'project_id': project.id,
                'detail': f"{ci.category}/{ci.model_name} — {', '.join(changed_lines)}",
                'content': log_content,
                'detail_url': f"https://work.mgnt.kr/sales_management/{project.id}",
            })

        db.commit()
    return jsonify(ok=True, new_status=ci.status_sales)


# ── 영업 협의 단계 변경 ──

@app_api_bp.route('/sales/<int:item_id>/stage', methods=['POST'])
@app_auth_required
def app_sales_stage(item_id):
    """영업 품목 영업단계 변경"""
    from modules.history_board import append_history_log, get_user_display_name
    data = request.get_json(silent=True) or {}
    new_stage = data.get('stage', '').strip()
    if not new_stage:
        return jsonify(ok=False, error='단계를 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        ci = db.query(ContractItem).get(item_id)
        if not ci:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404
        old = ci.status_sales
        ci.status_sales = new_stage
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '시스템'
        contract = ci.contract
        if contract and contract.project_id:
            append_history_log(db, contract.project_id, user_name,
                f'영업단계 변경: {ci.model_name or ci.category} — {old} → {new_stage}',
                scope='sales')
        db.commit()
    return jsonify(ok=True)


# ── 견적서 생성 ──

@app_api_bp.route('/items/search')
@app_auth_required
def app_item_search():
    """품목 자동완성 (웹 api_item_search와 동일 — last_unit_price fallback 포함)"""
    from modules.models import ReceivingItem, ReceivingHistory
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(Item).filter(Item.is_active == True)
        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (Item.item_name.ilike(like_q)) |
                (Item.icube_item_cd.ilike(like_q)) |
                (Item.item_spec.ilike(like_q))
            )
        items = query.order_by(Item.item_name).limit(20).all()

        result = []
        for i in items:
            price = i.last_unit_price or 0
            if not price:
                rcv = db.query(ReceivingItem.unit_price).filter(
                    ReceivingItem.item_name == i.item_name,
                    ReceivingItem.unit_price > 0,
                ).order_by(ReceivingItem.id.desc()).first()
                if rcv:
                    price = rcv[0]
            if not price and i.icube_item_cd:
                histories = db.query(ReceivingHistory.items_json).filter(
                    ReceivingHistory.items_json.ilike(f'%{i.icube_item_cd}%'),
                ).order_by(ReceivingHistory.id.desc()).limit(5).all()
                for (json_str,) in histories:
                    try:
                        for hi in json.loads(json_str or '[]'):
                            if hi.get('item_cd') == i.icube_item_cd and hi.get('unit_price', 0) > 0:
                                price = hi['unit_price']
                                break
                    except Exception:
                        pass
                    if price:
                        break
            result.append({
                'id': i.id,
                'item_cd': i.icube_item_cd or '',
                'item_name': i.item_name,
                'item_spec': i.item_spec or '',
                'unit': i.unit or '',
                'last_unit_price': price,
            })
        return jsonify(ok=True, items=result)


@app_api_bp.route('/quote-price-history')
@app_auth_required
def app_quote_price_history():
    """품명 기준 과거 견적 단가 목록 (웹 api_quote_price_history와 동일)"""
    item_name = (request.args.get('item_name') or '').strip()
    if not item_name:
        return jsonify(ok=True, history=[])

    with get_db() as db:
        rows = db.query(
            QuotationItem.unit_price,
            QuotationItem.item_spec,
            func.max(Quotation.quote_date).label('last_date'),
            func.count(QuotationItem.id).label('cnt'),
        ).join(Quotation, Quotation.id == QuotationItem.quotation_id).filter(
            QuotationItem.item_name == item_name,
            QuotationItem.unit_price > 0,
        ).group_by(
            QuotationItem.unit_price, QuotationItem.item_spec,
        ).order_by(
            func.max(Quotation.quote_date).desc(),
        ).limit(10).all()

        return jsonify(ok=True, history=[{
            'price': r.unit_price,
            'spec': r.item_spec or '',
            'last_date': str(r.last_date) if r.last_date else '',
            'count': r.cnt,
        } for r in rows])


@app_api_bp.route('/quotations/create', methods=['POST'])
@app_auth_required
def app_quotation_create():
    """견적서 신규 생성 — 웹 quotation_create POST 로직과 동일.
    바디: {quote_date, delivery_date, payment_method, validity_period, project_name,
           bank_account, customer_*, items: [...], surcharges: [...], note, tax_included}
    """
    from routes.quotation import _generate_quote_no, _save_items, _auto_register_quote_items
    from modules.utils import safe_int
    from sqlalchemy.exc import IntegrityError

    data = request.get_json(silent=True) or {}

    try:
        quote_date = datetime.datetime.strptime(data.get('quote_date', ''), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        quote_date = datetime.date.today()

    # 품목 파싱 (웹 _parse_items_from_form과 동일 로직)
    items_in = data.get('items') or []
    items_data = []
    supply_total = 0
    for i, it in enumerate(items_in):
        name = (it.get('item_name') or '').strip()
        if not name:
            continue
        qty = float(it.get('quantity') or 0)
        price = float(it.get('unit_price') or 0)
        unit = (it.get('unit') or '').strip() or '개'
        spec = (it.get('item_spec') or '').strip()
        note = (it.get('note') or '').strip()
        item_id = safe_int(it.get('item_id') or '', 0) or None
        amount = qty * price
        items_data.append({
            'seq': i + 1, 'item_id': item_id, 'item_name': name,
            'item_spec': spec, 'unit': unit, 'quantity': qty,
            'unit_price': price, 'amount': amount, 'note': note,
        })
        supply_total += amount

    # 부과금 파싱
    sc_in = data.get('surcharges') or []
    surcharges = []
    sc_total = 0
    for sc in sc_in:
        name = (sc.get('name') or '').strip()
        if not name:
            continue
        rate = float(sc.get('rate') or 0)
        amount = round(supply_total * rate / 100)
        surcharges.append({'name': name, 'rate': rate, 'amount': amount})
        sc_total += amount

    user_id = request._app_user_id
    with get_db() as db:
        quotation = None
        for retry in range(5):
            try:
                quotation = Quotation(
                    quote_no=_generate_quote_no(db, retry=retry),
                    quote_date=quote_date,
                    validity_period=(data.get('validity_period') or '견적일로부터 1개월').strip(),
                    delivery_date=(data.get('delivery_date') or '협의').strip(),
                    payment_method=(data.get('payment_method') or '현금').strip(),
                    bank_account=(data.get('bank_account') or '').strip() or None,
                    project_name=(data.get('project_name') or '').strip() or None,
                    customer_name=(data.get('customer_name') or '').strip() or None,
                    customer_contact=(data.get('customer_contact') or '').strip() or None,
                    customer_address=(data.get('customer_address') or '').strip() or None,
                    customer_tel=(data.get('customer_tel') or '').strip() or None,
                    customer_fax=(data.get('customer_fax') or '').strip() or None,
                    customer_email=(data.get('customer_email') or '').strip() or None,
                    note=(data.get('note') or '').strip() or None,
                    tax_included=bool(data.get('tax_included')),
                    total_amount=supply_total,
                    surcharges_json=json.dumps(surcharges, ensure_ascii=False) if surcharges else None,
                    grand_total=supply_total + sc_total,
                    status='작성중',
                    created_by=user_id,
                )
                db.add(quotation)
                db.flush()
                break
            except IntegrityError:
                db.rollback()
                quotation = None
                continue

        if not quotation:
            return jsonify(ok=False, error='견적번호 생성에 실패했습니다. 다시 시도해주세요'), 500

        _save_items(db, quotation.id, items_data)
        _auto_register_quote_items(db, items_data)
        db.commit()
        return jsonify(ok=True, quotation_id=quotation.id, quote_no=quotation.quote_no)


# ── AS 케이스 생성 ──

@app_api_bp.route('/warranty-cases/create', methods=['POST'])
@app_auth_required
def app_warranty_create():
    """AS 케이스 신규 등록"""
    data = request.get_json(silent=True) or {}
    project_name = data.get('project_name', '').strip()
    symptom = data.get('symptom', '').strip()
    if not symptom:
        return jsonify(ok=False, error='증상을 입력해주세요'), 400

    with get_db() as db:
        import datetime as _dt
        year = _dt.date.today().year
        from sqlalchemy import func
        max_seq = db.query(func.count(WarrantyCase.id)).filter(
            WarrantyCase.case_no.like(f'AS-{year}-%')
        ).scalar() or 0
        case_no = f'AS-{year}-{max_seq + 1:03d}'

        case = WarrantyCase(
            case_no=case_no,
            project_name=project_name,
            contract_name=data.get('contract_name', ''),
            model_name=data.get('model_name', ''),
            defect_type=data.get('defect_type', ''),
            symptom=symptom,
            status='접수',
            reported_date=_dt.date.today(),
            customer_phone=data.get('customer_phone', ''),
            is_chargeable=data.get('is_chargeable', False),
        )
        db.add(case)
        log_activity(db, 'AS관리', 'create', f'{case_no} 접수', ref_type='WarrantyCase')
        db.commit()
        return jsonify(ok=True, case_id=case.id, case_no=case_no)


# ── 가공발주 상태변경 ──

@app_api_bp.route('/processing-orders/<int:fo_id>/status', methods=['POST'])
@app_auth_required
def app_processing_order_status(fo_id):
    """가공발주 상태변경"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if not new_status:
        return jsonify(ok=False, error='상태를 입력해주세요'), 400

    with get_db() as db:
        fo = db.query(ProcessingOrder).filter(ProcessingOrder.id == fo_id).first()
        if not fo:
            return jsonify(ok=False, error='가공발주를 찾을 수 없습니다'), 404
        old_status = fo.status
        fo.status = new_status
        log_activity(db, '가공발주', 'status_change',
                     f'{fo.fo_no} 상태변경: {old_status}→{new_status}',
                     ref_type='ProcessingOrder')
        db.commit()
        return jsonify(ok=True, fo_no=fo.fo_no, old_status=old_status, new_status=new_status)


# ── 가공발주 생성 ──

# /processing-orders/create 는 파일 끝에서 multipart + items 방식으로 재정의됨.


# /billing/<id>/payment-status 는 폐기 — ERP는 Contract.payment_status 단일 기준.


# /certifications/create 는 파일 끝에서 multipart 대응으로 재정의됨.


# ── 인증서 삭제 ──

@app_api_bp.route('/certifications/<int:cert_id>/delete', methods=['POST'])
@app_auth_required
def app_certification_delete(cert_id):
    """인증서 삭제"""
    with get_db() as db:
        cert = db.query(Certification).filter(Certification.id == cert_id).first()
        if not cert:
            return jsonify(ok=False, error='인증서를 찾을 수 없습니다'), 404
        cert_name = cert.cert_name
        db.delete(cert)
        log_activity(db, '인증서', 'delete', f'{cert_name} 삭제',
                     ref_type='Certification')
        db.commit()
        return jsonify(ok=True)


# ── BOM 생성 ──

@app_api_bp.route('/bom/create', methods=['POST'])
@app_auth_required
def app_bom_create():
    """BOM 신규 생성"""
    data = request.get_json(silent=True) or {}
    product_code = data.get('product_code', '').strip()
    product_name = data.get('product_name', '').strip()
    if not product_code or not product_name:
        return jsonify(ok=False, error='제품코드와 제품명을 입력해주세요'), 400

    with get_db() as db:
        existing = db.query(BomHeader).filter(BomHeader.product_code == product_code).first()
        if existing:
            return jsonify(ok=False, error='이미 존재하는 제품코드입니다'), 400

        bom = BomHeader(
            product_code=product_code,
            product_name=product_name,
            product_category=data.get('category', ''),
        )
        db.add(bom)
        log_activity(db, 'BOM', 'create', f'{product_code} {product_name} 생성',
                     ref_type='BomHeader')
        db.commit()
        return jsonify(ok=True, bom_id=bom.id)


# ── 도면 업로드(메타데이터) ──

@app_api_bp.route('/drawings/create', methods=['POST'])
@app_auth_required
def app_drawing_create():
    """도면 메타데이터 생성"""
    data = request.get_json(silent=True) or {}
    title = data.get('title', '').strip()
    project_id = data.get('project_id')
    if not title or not project_id:
        return jsonify(ok=False, error='제목과 프로젝트를 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()
        drawing = Drawing(
            title=title,
            drawing_type=data.get('drawing_type', '제작도면'),
            project_id=project_id,
            created_by=user.full_name if user else '사용자',
        )
        db.add(drawing)
        log_activity(db, '도면', 'create', f'{title} 등록',
                     ref_type='Drawing')
        db.commit()
        return jsonify(ok=True, drawing_id=drawing.id)


# ── 출장 생성 ──

@app_api_bp.route('/business-trips/vehicles')
@app_auth_required
def app_business_trip_vehicles():
    """출장 이동수단 프리셋 (PC 출장폼과 동일)"""
    from routes.business_trip import _get_vehicle_choices
    with get_db() as db:
        return jsonify(ok=True, vehicles=_get_vehicle_choices(db))


@app_api_bp.route('/business-trips/create', methods=['POST'])
@app_auth_required
def app_business_trip_create():
    """출장 신규 등록 (PC 출장폼과 동일 필드: 제목, 장소, 출발/복귀일시, 이동수단, 목적, 비고, 출장인원)"""
    from modules.notification_engine import notify
    data = request.get_json(silent=True) or {}
    title = data.get('title', '').strip()
    destination = data.get('destination', '').strip()
    departure_date = data.get('departure_date', '').strip()
    if not title or not destination or not departure_date:
        return jsonify(ok=False, error='제목, 출장장소, 출발일을 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        import datetime as _dt
        trip = BusinessTrip(
            title=title,
            destination=destination,
            purpose=(data.get('purpose') or '').strip() or None,
            departure_date=_dt.datetime.fromisoformat(departure_date),
            return_date=_dt.datetime.fromisoformat(data['return_date']) if data.get('return_date') else None,
            vehicle=(data.get('vehicle') or '').strip() or None,
            note=(data.get('note') or '').strip() or None,
            status='예정',
            created_by=user_id,
        )
        db.add(trip)
        db.flush()

        # 출장인원 저장 (PC _save_members와 동일 형태)
        members_in = data.get('members') or []
        for m in members_in:
            name = (m.get('name') or '').strip()
            if not name:
                continue
            uid = m.get('user_id') or None
            db.add(BusinessTripMember(
                trip_id=trip.id,
                user_id=int(uid) if uid else None,
                user_name=name,
                position=(m.get('position') or '').strip() or None,
                department=(m.get('department') or '').strip() or None,
            ))
        db.flush()

        log_activity(db, '출장', 'create', f'{title} ({destination}) 등록',
                     ref_type='BusinessTrip', ref_id=trip.id)
        db.commit()

        # 카카오워크 그룹채팅 알림 (PC와 동일)
        member_labels = [
            f"{m.user_name} {m.position}".strip() if m.position else m.user_name
            for m in trip.members if m.user_name
        ]
        creator_user = db.query(User).get(user_id)
        creator_label = '-'
        if creator_user:
            creator_label = creator_user.full_name
            if creator_user.position:
                creator_label = f"{creator_user.full_name} {creator_user.position}"
        dep_str = trip.departure_date.strftime('%Y-%m-%d %H:%M') if trip.departure_date else '-'
        ret_str = trip.return_date.strftime('%Y-%m-%d %H:%M') if trip.return_date else '-'
        kakao_text = (
            f"[출장등록] {trip.title}\n"
            f"목적지: {trip.destination}\n"
            f"출발: {dep_str}\n"
            f"귀환: {ret_str}\n"
            f"차량: {trip.vehicle or '-'}\n"
            f"인원: {', '.join(member_labels) or '-'}\n"
            f"등록자: {creator_label}"
        )
        try:
            notify(db, 'trip.created', {
                'destination': trip.destination or trip.title,
                'detail': f"{dep_str}~{ret_str} · {', '.join(member_labels) or '-'}",
                'trip_id': trip.id,
                'departure_date': dep_str,
                'return_date': ret_str,
                'members': ', '.join(member_labels) or '-',
            }, kakao_text_override=kakao_text)
        except Exception:
            pass

        return jsonify(ok=True, trip_id=trip.id)


# ── 출장 상태변경 ──

@app_api_bp.route('/business-trips/<int:trip_id>/status', methods=['POST'])
@app_auth_required
def app_business_trip_status(trip_id):
    """출장 상태변경"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if not new_status:
        return jsonify(ok=False, error='상태를 입력해주세요'), 400

    with get_db() as db:
        trip = db.query(BusinessTrip).filter(BusinessTrip.id == trip_id).first()
        if not trip:
            return jsonify(ok=False, error='출장을 찾을 수 없습니다'), 404
        old_status = trip.status
        trip.status = new_status
        log_activity(db, '출장', 'status_change',
                     f'{trip.title} 상태변경: {old_status}→{new_status}',
                     ref_type='BusinessTrip')
        db.commit()
        return jsonify(ok=True, old_status=old_status, new_status=new_status)


# ── 공구 생성 ──

@app_api_bp.route('/tools/create', methods=['POST'])
@app_auth_required
def app_tool_create():
    """공구 신규 등록"""
    data = request.get_json(silent=True) or {}
    tool_name = data.get('tool_name', '').strip()
    if not tool_name:
        return jsonify(ok=False, error='공구명을 입력해주세요'), 400

    with get_db() as db:
        tool = Tool(
            tool_name=tool_name,
            category=data.get('category', '전동공구'),
            total_qty=data.get('total_qty', 1),
            available_qty=data.get('total_qty', 1),
            current_location=data.get('current_location', '사무실'),
            status='보관중',
        )
        db.add(tool)
        log_activity(db, '공구', 'create', f'{tool_name} 등록',
                     ref_type='Tool')
        db.commit()
        return jsonify(ok=True, tool_id=tool.id)


# ── 공구 상태변경 ──

@app_api_bp.route('/tools/<int:tool_id>/status', methods=['POST'])
@app_auth_required
def app_tool_status(tool_id):
    """공구 상태변경"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if not new_status:
        return jsonify(ok=False, error='상태를 입력해주세요'), 400

    with get_db() as db:
        tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if not tool:
            return jsonify(ok=False, error='공구를 찾을 수 없습니다'), 404
        old_status = tool.status
        tool.status = new_status
        log_activity(db, '공구', 'status_change',
                     f'{tool.tool_name} 상태변경: {old_status}→{new_status}',
                     ref_type='Tool')
        db.commit()
        return jsonify(ok=True, old_status=old_status, new_status=new_status)


# ── 거래처 생성 ──

@app_api_bp.route('/vendors/create', methods=['POST'])
# /vendors/create 및 /vendors/<id>/edit 은 파일 끝에서 확장 필드로 재정의됨.


# ── 품목 생성 ──

@app_api_bp.route('/items/create', methods=['POST'])
@app_auth_required
def app_item_create():
    """품목 신규 등록"""
    data = request.get_json(silent=True) or {}
    item_name = data.get('item_name', '').strip()
    if not item_name:
        return jsonify(ok=False, error='품명을 입력해주세요'), 400

    with get_db() as db:
        item = Item(
            item_name=item_name,
            icube_item_cd=data.get('item_code', ''),
            category=data.get('category', ''),
            unit=data.get('unit', ''),
            manufacturer=data.get('manufacturer', ''),
        )
        db.add(item)
        log_activity(db, '품목', 'create', f'{item_name} 등록',
                     ref_type='Item')
        db.commit()
        return jsonify(ok=True, item_id=item.id)


# ── 재고 소진 ──

@app_api_bp.route('/inventory/<int:item_id>/consume', methods=['POST'])
@app_auth_required
def app_inventory_consume(item_id):
    """재고 소진 처리"""
    data = request.get_json(silent=True) or {}
    quantity = data.get('quantity')
    if not quantity or float(quantity) <= 0:
        return jsonify(ok=False, error='소진수량을 입력해주세요'), 400

    quantity = float(quantity)
    user_id = request._app_user_id
    with get_db() as db:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404
        if item.stock_qty < quantity:
            return jsonify(ok=False, error=f'재고 부족 (현재: {item.stock_qty})'), 400

        before_qty = item.stock_qty
        item.stock_qty -= quantity

        user = db.query(User).filter(User.id == user_id).first()
        movement = StockMovement(
            item_id=item_id,
            movement_type='소진',
            quantity=-quantity,
            before_qty=before_qty,
            after_qty=item.stock_qty,
            note=data.get('note', ''),
            created_by=user.full_name if user else '사용자',
        )
        db.add(movement)
        log_activity(db, '재고', 'consume',
                     f'{item.item_name} {quantity}개 소진 ({data.get("project_name", "")})',
                     ref_type='Item')
        db.commit()
        return jsonify(ok=True, before_qty=before_qty, after_qty=item.stock_qty)


# ── 재고 조정 ──

@app_api_bp.route('/inventory/<int:item_id>/adjust', methods=['POST'])
@app_auth_required
def app_inventory_adjust(item_id):
    """재고 수량 조정"""
    data = request.get_json(silent=True) or {}
    new_qty = data.get('new_qty')
    if new_qty is None:
        return jsonify(ok=False, error='조정수량을 입력해주세요'), 400

    new_qty = float(new_qty)
    user_id = request._app_user_id
    with get_db() as db:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404

        before_qty = item.stock_qty
        diff = new_qty - before_qty
        item.stock_qty = new_qty

        user = db.query(User).filter(User.id == user_id).first()
        movement = StockMovement(
            item_id=item_id,
            movement_type='조정',
            quantity=diff,
            before_qty=before_qty,
            after_qty=new_qty,
            note=data.get('reason', ''),
            created_by=user.full_name if user else '사용자',
        )
        db.add(movement)
        log_activity(db, '재고', 'adjust',
                     f'{item.item_name} 재고조정: {before_qty}→{new_qty} ({data.get("reason", "")})',
                     ref_type='Item')
        db.commit()
        return jsonify(ok=True, before_qty=before_qty, after_qty=new_qty)


# ── 사진 삭제 ──

@app_api_bp.route('/photos/<int:photo_id>/delete', methods=['POST'])
@app_auth_required
def app_photo_delete(photo_id):
    """프로젝트 사진 삭제"""
    with get_db() as db:
        photo = db.query(ProjectPhoto).filter(ProjectPhoto.id == photo_id).first()
        if not photo:
            return jsonify(ok=False, error='사진을 찾을 수 없습니다'), 404
        file_name = photo.file_name
        db.delete(photo)
        log_activity(db, '사진', 'delete', f'{file_name} 삭제',
                     ref_type='ProjectPhoto')
        db.commit()
        return jsonify(ok=True)


# ── 서류 착수계 생성 ──

@app_api_bp.route('/documents/<int:doc_id>/generate-commencement', methods=['POST'])
@app_auth_required
def app_document_generate_commencement(doc_id):
    """DEPRECATED — 플래그 독립 set은 실제 PDF 생성 없이 상태만 바꿔 사고 유발.
    착수계 생성 플래그는 /documents/<req_no>/commencement-pdf 호출 시에만 True로 전환됨."""
    return jsonify(ok=False, error='해당 API는 폐기되었습니다. 착수계 PDF 다운로드로 생성하세요.'), 410


@app_api_bp.route('/documents/<int:doc_id>/generate-delivery', methods=['POST'])
@app_auth_required
def app_document_generate_delivery(doc_id):
    """DEPRECATED — 실제 PDF 생성 없이 플래그만 바꾸는 경로 제거."""
    return jsonify(ok=False, error='해당 API는 폐기되었습니다. 납품계 PDF 다운로드로 생성하세요.'), 410


# ── 재고 안전재고 설정 ──

@app_api_bp.route('/inventory/<int:item_id>/safety-stock', methods=['POST'])
@app_auth_required
def app_inventory_safety_stock(item_id):
    """안전재고 기준 수정"""
    data = request.get_json(silent=True) or {}
    safety_stock = data.get('safety_stock')
    if safety_stock is None:
        return jsonify(ok=False, error='안전재고 수량을 입력해주세요'), 400

    safety_stock = float(safety_stock)
    if safety_stock < 0:
        return jsonify(ok=False, error='안전재고는 0 이상이어야 합니다'), 400

    with get_db() as db:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404
        old_val = item.safety_stock
        item.safety_stock = safety_stock
        log_activity(db, '재고', 'update',
                     f'{item.item_name} 안전재고 변경: {old_val}→{safety_stock}',
                     ref_type='Item', ref_id=item.id)
        db.commit()
        return jsonify(ok=True, old_safety_stock=old_val, new_safety_stock=safety_stock)


# ── 재고 일괄조정 ──

@app_api_bp.route('/inventory/batch-adjust', methods=['POST'])
@app_auth_required
def app_inventory_batch_adjust():
    """재고 일괄 조정"""
    data = request.get_json(silent=True) or {}
    adjustments = data.get('adjustments', [])
    if not adjustments:
        return jsonify(ok=False, error='조정할 항목을 입력해주세요'), 400

    user_id = request._app_user_id
    results = []
    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()
        user_name = user.full_name if user else '사용자'
        for adj in adjustments:
            item_id = adj.get('item_id')
            new_qty = adj.get('new_qty')
            reason = adj.get('reason', '')
            if item_id is None or new_qty is None:
                continue
            new_qty = float(new_qty)
            item = db.query(Item).filter(Item.id == item_id).first()
            if not item:
                results.append({'item_id': item_id, 'ok': False, 'error': '품목 없음'})
                continue
            before_qty = item.stock_qty
            diff = new_qty - before_qty
            item.stock_qty = new_qty
            movement = StockMovement(
                item_id=item_id,
                movement_type='조정',
                quantity=diff,
                before_qty=before_qty,
                after_qty=new_qty,
                note=reason,
                created_by=user_name,
            )
            db.add(movement)
            results.append({'item_id': item_id, 'ok': True, 'before_qty': before_qty, 'after_qty': new_qty})
        log_activity(db, '재고', 'batch_adjust',
                     f'일괄 재고조정 {len(results)}건',
                     ref_type='Item')
        db.commit()
    return jsonify(ok=True, results=results)


# ── BOM 품목 추가 ──

@app_api_bp.route('/bom/<int:bom_id>/items', methods=['POST'])
@app_auth_required
def app_bom_add_item(bom_id):
    """BOM 소요부품 추가"""
    data = request.get_json(silent=True) or {}
    item_name = data.get('item_name', '').strip()
    if not item_name:
        return jsonify(ok=False, error='부품명을 입력해주세요'), 400

    with get_db() as db:
        bom = db.query(BomHeader).filter(BomHeader.id == bom_id).first()
        if not bom:
            return jsonify(ok=False, error='BOM을 찾을 수 없습니다'), 404

        bom_item = BomItem(
            bom_id=bom_id,
            item_name=item_name,
            item_spec=data.get('item_spec', ''),
            quantity=float(data.get('quantity', 1)),
            unit_price=float(data.get('unit_price', 0)) if data.get('unit_price') else None,
            unit=data.get('unit', ''),
            supplier=data.get('supplier', ''),
            note=data.get('note', ''),
        )
        db.add(bom_item)
        log_activity(db, 'BOM', 'add_item',
                     f'{bom.product_code} 부품 추가: {item_name}',
                     ref_type='BomHeader', ref_id=bom.id)
        db.commit()
        return jsonify(ok=True, bom_item_id=bom_item.id)


# ── BOM 삭제 ──

@app_api_bp.route('/bom/<int:bom_id>/delete', methods=['POST'])
@app_auth_required
def app_bom_delete(bom_id):
    """BOM 헤더 삭제 (cascade로 품목도 함께 삭제)"""
    with get_db() as db:
        bom = db.query(BomHeader).filter(BomHeader.id == bom_id).first()
        if not bom:
            return jsonify(ok=False, error='BOM을 찾을 수 없습니다'), 404
        product_code = bom.product_code
        product_name = bom.product_name
        db.delete(bom)
        log_activity(db, 'BOM', 'delete',
                     f'{product_code} {product_name} 삭제',
                     ref_type='BomHeader')
        db.commit()
        return jsonify(ok=True)


# ── 품목 수정 ──

@app_api_bp.route('/items/<int:item_id>/edit', methods=['POST'])
@app_auth_required
def app_item_edit(item_id):
    """품목 마스터 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404

        changes = []
        for field in ['item_name', 'category', 'unit', 'manufacturer', 'item_spec', 'note']:
            if field in data:
                old_val = getattr(item, field, '')
                new_val = data[field]
                if old_val != new_val:
                    setattr(item, field, new_val)
                    changes.append(field)

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, '품목', 'update',
                     f'{item.item_name} 수정 ({", ".join(changes)})',
                     ref_type='Item', ref_id=item.id)
        db.commit()
        return jsonify(ok=True, updated_fields=changes)


# ── 품목 삭제 ──

@app_api_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@app_auth_required
def app_item_delete(item_id):
    """품목 삭제 (재고 참조 확인)"""
    with get_db() as db:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return jsonify(ok=False, error='품목을 찾을 수 없습니다'), 404

        # 재고가 남아있으면 삭제 불가
        if item.stock_qty and item.stock_qty > 0:
            return jsonify(ok=False, error=f'재고가 남아있어 삭제할 수 없습니다 (현재: {item.stock_qty})'), 400

        # StockMovement 참조 확인
        movement_count = db.query(StockMovement).filter(StockMovement.item_id == item_id).count()
        if movement_count > 0:
            return jsonify(ok=False, error=f'재고 이동이력이 {movement_count}건 존재합니다. 비활성화를 권장합니다'), 400

        item_name = item.item_name
        db.delete(item)
        log_activity(db, '품목', 'delete', f'{item_name} 삭제',
                     ref_type='Item')
        db.commit()
        return jsonify(ok=True)


# ── 가공발주 품목 추가 ──

@app_api_bp.route('/processing-orders/<int:fo_id>/items', methods=['POST'])
@app_auth_required
def app_processing_order_add_item(fo_id):
    """가공발주 품목 추가"""
    data = request.get_json(silent=True) or {}
    item_name = data.get('item_name', '').strip()
    if not item_name:
        return jsonify(ok=False, error='품목명을 입력해주세요'), 400

    with get_db() as db:
        fo = db.query(ProcessingOrder).filter(ProcessingOrder.id == fo_id).first()
        if not fo:
            return jsonify(ok=False, error='가공발주서를 찾을 수 없습니다'), 404

        quantity = float(data.get('quantity', 0))
        unit_price = float(data.get('unit_price', 0))
        fo_item = ProcessingOrderItem(
            fo_id=fo_id,
            item_name=item_name,
            item_spec=data.get('spec', ''),
            quantity=quantity,
            unit_price=unit_price,
            amount=quantity * unit_price,
            unit=data.get('unit', ''),
            note=data.get('note', ''),
        )
        db.add(fo_item)

        # 합계 재계산
        db.flush()
        total = sum(i.amount or 0 for i in fo.items)
        fo.total_amount = total
        fo.tax_amount = round(total * 0.1)

        log_activity(db, '가공발주', 'add_item',
                     f'{fo.fo_no} 품목 추가: {item_name}',
                     ref_type='ProcessingOrder', ref_id=fo.id)
        db.commit()
        return jsonify(ok=True, item_id=fo_item.id)


# ── 가공발주 삭제 ──

@app_api_bp.route('/processing-orders/<int:fo_id>/delete', methods=['POST'])
@app_auth_required
def app_processing_order_delete(fo_id):
    """가공발주 삭제"""
    with get_db() as db:
        fo = db.query(ProcessingOrder).filter(ProcessingOrder.id == fo_id).first()
        if not fo:
            return jsonify(ok=False, error='가공발주서를 찾을 수 없습니다'), 404
        if fo.status not in ('작성중', '취소'):
            return jsonify(ok=False, error=f'"{fo.status}" 상태에서는 삭제할 수 없습니다'), 400
        fo_no = fo.fo_no
        db.delete(fo)
        log_activity(db, '가공발주', 'delete', f'{fo_no} 삭제',
                     ref_type='ProcessingOrder')
        db.commit()
        return jsonify(ok=True)


# ── 납품 분할 수정 ──

@app_api_bp.route('/deliveries/<int:delivery_id>/splits/<int:split_id>/update', methods=['POST'])
@app_auth_required
def app_delivery_split_update(delivery_id, split_id):
    """납품 분할회차 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        split = db.query(DeliverySplit).filter(
            DeliverySplit.id == split_id,
            DeliverySplit.delivery_id == delivery_id,
        ).first()
        if not split:
            return jsonify(ok=False, error='납품 분할을 찾을 수 없습니다'), 404

        import datetime as _dt
        changes = []
        if 'scheduled_date' in data and data['scheduled_date']:
            split.scheduled_date = _dt.date.fromisoformat(data['scheduled_date'])
            changes.append('예정일')
        if 'status' in data:
            split.status = data['status']
            changes.append('상태')
        if 'quantity' in data:
            split.quantity = int(data['quantity'])
            changes.append('수량')
        if 'note' in data:
            split.note = data['note']
            changes.append('비고')

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, '납품', 'update',
                     f'납품분할 {split.split_no}회차 수정 ({", ".join(changes)})',
                     ref_type='DeliverySplit', ref_id=split.id)
        db.commit()
        return jsonify(ok=True, updated=changes)


# ── 납품 분할 삭제 ──

@app_api_bp.route('/deliveries/<int:delivery_id>/splits/<int:split_id>/delete', methods=['POST'])
@app_auth_required
def app_delivery_split_delete(delivery_id, split_id):
    """납품 분할회차 삭제"""
    with get_db() as db:
        split = db.query(DeliverySplit).filter(
            DeliverySplit.id == split_id,
            DeliverySplit.delivery_id == delivery_id,
        ).first()
        if not split:
            return jsonify(ok=False, error='납품 분할을 찾을 수 없습니다'), 404
        split_no = split.split_no
        db.delete(split)
        log_activity(db, '납품', 'delete',
                     f'납품분할 {split_no}회차 삭제',
                     ref_type='DeliverySplit')
        db.commit()
        return jsonify(ok=True)


# ── 도면 삭제 ──

@app_api_bp.route('/drawings/<int:drawing_id>/delete', methods=['POST'])
@app_auth_required
def app_drawing_delete(drawing_id):
    """도면 삭제 (cascade로 버전도 함께 삭제)"""
    with get_db() as db:
        drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
        if not drawing:
            return jsonify(ok=False, error='도면을 찾을 수 없습니다'), 404
        title = drawing.title
        db.delete(drawing)
        log_activity(db, '도면', 'delete', f'{title} 삭제',
                     ref_type='Drawing')
        db.commit()
        return jsonify(ok=True)


# ── 출장 수정 ──

@app_api_bp.route('/business-trips/<int:trip_id>/edit', methods=['POST'])
@app_auth_required
def app_business_trip_edit(trip_id):
    """출장 정보 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        trip = db.query(BusinessTrip).filter(BusinessTrip.id == trip_id).first()
        if not trip:
            return jsonify(ok=False, error='출장을 찾을 수 없습니다'), 404

        import datetime as _dt
        changes = []
        if 'title' in data:
            trip.title = data['title']
            changes.append('제목')
        if 'destination' in data:
            trip.destination = data['destination']
            changes.append('출장장소')
        if 'departure_date' in data and data['departure_date']:
            trip.departure_date = _dt.datetime.fromisoformat(data['departure_date'])
            changes.append('출발일')
        if 'return_date' in data and data['return_date']:
            trip.return_date = _dt.datetime.fromisoformat(data['return_date'])
            changes.append('복귀일')
        if 'note' in data:
            trip.note = data['note']
            changes.append('비고')
        if 'vehicle' in data:
            trip.vehicle = data['vehicle']
            changes.append('이동수단')
        if 'purpose' in data:
            trip.purpose = data['purpose']
            changes.append('목적')

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, '출장', 'update',
                     f'{trip.title} 수정 ({", ".join(changes)})',
                     ref_type='BusinessTrip', ref_id=trip.id)
        db.commit()
        return jsonify(ok=True, updated=changes)


# ── 출장 인원 추가 ──

@app_api_bp.route('/business-trips/<int:trip_id>/members', methods=['POST'])
@app_auth_required
def app_business_trip_add_member(trip_id):
    """출장 참여인원 추가"""
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify(ok=False, error='사용자를 선택해주세요'), 400

    with get_db() as db:
        trip = db.query(BusinessTrip).filter(BusinessTrip.id == trip_id).first()
        if not trip:
            return jsonify(ok=False, error='출장을 찾을 수 없습니다'), 404

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify(ok=False, error='사용자를 찾을 수 없습니다'), 404

        # 중복 확인
        existing = db.query(BusinessTripMember).filter(
            BusinessTripMember.trip_id == trip_id,
            BusinessTripMember.user_id == user_id,
        ).first()
        if existing:
            return jsonify(ok=False, error='이미 추가된 인원입니다'), 400

        member = BusinessTripMember(
            trip_id=trip_id,
            user_id=user.id,
            user_name=user.full_name,
            position=user.position or '',
            department=user.user_group or '',
        )
        db.add(member)
        log_activity(db, '출장', 'add_member',
                     f'{trip.title} 인원 추가: {user.full_name}',
                     ref_type='BusinessTrip', ref_id=trip.id)
        db.commit()
        return jsonify(ok=True, member_id=member.id)


# ── 공구 수정 ──

@app_api_bp.route('/tools/<int:tool_id>/edit', methods=['POST'])
@app_auth_required
def app_tool_edit(tool_id):
    """공구 정보 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if not tool:
            return jsonify(ok=False, error='공구를 찾을 수 없습니다'), 404

        changes = []
        for field in ['tool_name', 'category', 'team', 'total_qty', 'available_qty',
                       'current_location', 'note']:
            if field in data:
                old_val = getattr(tool, field, '')
                new_val = data[field]
                if field in ('total_qty', 'available_qty'):
                    new_val = int(new_val)
                if old_val != new_val:
                    setattr(tool, field, new_val)
                    changes.append(field)

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, '공구', 'update',
                     f'{tool.tool_name} 수정 ({", ".join(changes)})',
                     ref_type='Tool', ref_id=tool.id)
        db.commit()
        return jsonify(ok=True, updated_fields=changes)


# ── 공구 삭제 ──

@app_api_bp.route('/tools/<int:tool_id>/delete', methods=['POST'])
@app_auth_required
def app_tool_delete(tool_id):
    """공구 삭제"""
    with get_db() as db:
        tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if not tool:
            return jsonify(ok=False, error='공구를 찾을 수 없습니다'), 404
        tool_name = tool.tool_name
        db.delete(tool)
        log_activity(db, '공구', 'delete', f'{tool_name} 삭제',
                     ref_type='Tool')
        db.commit()
        return jsonify(ok=True)


# ── 견적 수정 ──

@app_api_bp.route('/quotations/<int:quote_id>/edit', methods=['POST'])
@app_auth_required
def app_quotation_edit(quote_id):
    """견적서 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
        if not quote:
            return jsonify(ok=False, error='견적서를 찾을 수 없습니다'), 404

        changes = []
        for field in ['project_name', 'customer_name', 'customer_contact',
                       'customer_address', 'customer_tel', 'customer_fax',
                       'customer_email', 'validity_period', 'delivery_date',
                       'payment_method', 'bank_account', 'note']:
            if field in data:
                old_val = getattr(quote, field, '')
                new_val = data[field]
                if old_val != new_val:
                    setattr(quote, field, new_val)
                    changes.append(field)

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, '견적', 'update',
                     f'{quote.quote_no} 수정 ({", ".join(changes)})',
                     ref_type='Quotation', ref_id=quote.id)
        db.commit()
        return jsonify(ok=True, updated_fields=changes)


# ── 견적 품목 추가 ──

@app_api_bp.route('/quotations/<int:quote_id>/items', methods=['POST'])
@app_auth_required
def app_quotation_add_item(quote_id):
    """견적 품목 추가"""
    data = request.get_json(silent=True) or {}
    item_name = data.get('item_name', '').strip()
    if not item_name:
        return jsonify(ok=False, error='품목명을 입력해주세요'), 400

    with get_db() as db:
        quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
        if not quote:
            return jsonify(ok=False, error='견적서를 찾을 수 없습니다'), 404

        # 순번 계산
        max_seq = db.query(func.max(QuotationItem.seq)).filter(
            QuotationItem.quotation_id == quote_id
        ).scalar() or 0

        quantity = float(data.get('quantity', 0))
        unit_price = float(data.get('unit_price', 0))
        qi = QuotationItem(
            quotation_id=quote_id,
            seq=max_seq + 1,
            item_name=item_name,
            item_spec=data.get('item_spec', ''),
            unit=data.get('unit', '개'),
            quantity=quantity,
            unit_price=unit_price,
            amount=quantity * unit_price,
            note=data.get('note', ''),
        )
        db.add(qi)

        # 합계 재계산
        db.flush()
        total = sum(i.amount or 0 for i in quote.items)
        quote.total_amount = total

        log_activity(db, '견적', 'add_item',
                     f'{quote.quote_no} 품목 추가: {item_name}',
                     ref_type='Quotation', ref_id=quote.id)
        db.commit()
        return jsonify(ok=True, item_id=qi.id)


# ── 견적 품목 삭제 ──

@app_api_bp.route('/quotations/<int:quote_id>/items/<int:item_id>/delete', methods=['POST'])
@app_auth_required
def app_quotation_delete_item(quote_id, item_id):
    """견적 품목 삭제"""
    with get_db() as db:
        qi = db.query(QuotationItem).filter(
            QuotationItem.id == item_id,
            QuotationItem.quotation_id == quote_id,
        ).first()
        if not qi:
            return jsonify(ok=False, error='견적 품목을 찾을 수 없습니다'), 404

        quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
        item_name = qi.item_name
        db.delete(qi)

        # 합계 재계산
        db.flush()
        if quote:
            total = sum(i.amount or 0 for i in quote.items)
            quote.total_amount = total

        log_activity(db, '견적', 'delete_item',
                     f'{quote.quote_no if quote else quote_id} 품목 삭제: {item_name}',
                     ref_type='Quotation', ref_id=quote_id)
        db.commit()
        return jsonify(ok=True)


# ── 견적 상태변경 ──

@app_api_bp.route('/quotations/<int:quote_id>/status', methods=['POST'])
@app_auth_required
def app_quotation_status(quote_id):
    """견적 상태 변경"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    if not new_status:
        return jsonify(ok=False, error='상태를 입력해주세요'), 400

    with get_db() as db:
        quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
        if not quote:
            return jsonify(ok=False, error='견적서를 찾을 수 없습니다'), 404
        old_status = quote.status
        quote.status = new_status
        log_activity(db, '견적', 'status_change',
                     f'{quote.quote_no} 상태변경: {old_status}→{new_status}',
                     ref_type='Quotation', ref_id=quote.id)
        db.commit()
        return jsonify(ok=True, old_status=old_status, new_status=new_status)


# ── 견적 삭제 ──

@app_api_bp.route('/quotations/<int:quote_id>/delete', methods=['POST'])
@app_auth_required
def app_quotation_delete(quote_id):
    """견적서 삭제"""
    with get_db() as db:
        quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
        if not quote:
            return jsonify(ok=False, error='견적서를 찾을 수 없습니다'), 404
        if quote.status not in ('작성중', '취소'):
            return jsonify(ok=False, error=f'"{quote.status}" 상태에서는 삭제할 수 없습니다'), 400
        quote_no = quote.quote_no
        db.delete(quote)
        log_activity(db, '견적', 'delete', f'{quote_no} 삭제',
                     ref_type='Quotation')
        db.commit()
        return jsonify(ok=True)


# ── AS 케이스 수정 ──

@app_api_bp.route('/warranty-cases/<int:case_id>/edit', methods=['POST'])
@app_auth_required
def app_warranty_case_edit(case_id):
    """AS 케이스 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        case = db.query(WarrantyCase).filter(WarrantyCase.id == case_id).first()
        if not case:
            return jsonify(ok=False, error='AS 케이스를 찾을 수 없습니다'), 404

        import datetime as _dt
        changes = []
        for field in ['symptom', 'defect_type', 'model_name', 'assigned_to',
                       'cause_analysis', 'action_taken', 'replaced_parts',
                       'reported_by', 'request_channel', 'customer_name',
                       'customer_phone', 'shipping_method', 'shipping_tracking',
                       'manual_site_name', 'manual_contract_name', 'manual_model_name']:
            if field in data:
                old_val = getattr(case, field, '')
                new_val = data[field]
                if old_val != new_val:
                    setattr(case, field, new_val)
                    changes.append(field)

        # 날짜 필드 처리
        for date_field in ['reported_date', 'site_visit_date', 'completed_date',
                           'shipping_date', 'manual_delivery_date']:
            if date_field in data and data[date_field]:
                new_date = _dt.date.fromisoformat(data[date_field])
                if getattr(case, date_field, None) != new_date:
                    setattr(case, date_field, new_date)
                    changes.append(date_field)

        # Boolean/숫자 필드
        if 'is_chargeable' in data:
            case.is_chargeable = bool(data['is_chargeable'])
            changes.append('유상여부')
        if 'charge_amount' in data:
            case.charge_amount = int(data['charge_amount'])
            changes.append('청구금액')

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, 'AS', 'update',
                     f'{case.case_no} 수정 ({", ".join(changes)})',
                     ref_type='WarrantyCase', ref_id=case.id)
        db.commit()
        return jsonify(ok=True, updated_fields=changes)


# ── 서류 패키지 수정 ──

@app_api_bp.route('/documents/<int:doc_id>/edit', methods=['POST'])
@app_auth_required
def app_document_edit(doc_id):
    """서류 패키지 수정"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        doc = db.query(DocumentPackage).filter(DocumentPackage.id == doc_id).first()
        if not doc:
            return jsonify(ok=False, error='서류 패키지를 찾을 수 없습니다'), 404

        import datetime as _dt
        changes = []
        for field in ['commencement_doc_no', 'delivery_doc_no', 'business_name',
                       'demand_org', 'contract_no', 'warranty_period',
                       'inspection_org', 'acceptance_org']:
            if field in data:
                old_val = getattr(doc, field, '')
                new_val = data[field]
                if old_val != new_val:
                    setattr(doc, field, new_val)
                    changes.append(field)

        # 날짜 필드
        for date_field in ['commencement_date', 'delivery_date', 'contract_date']:
            if date_field in data and data[date_field]:
                new_date = _dt.date.fromisoformat(data[date_field])
                if getattr(doc, date_field, None) != new_date:
                    setattr(doc, date_field, new_date)
                    changes.append(date_field)

        # 숫자 필드
        for int_field in ['fee', 'total_amount', 'supply_amount']:
            if int_field in data and data[int_field] is not None:
                new_val = int(data[int_field])
                if getattr(doc, int_field, None) != new_val:
                    setattr(doc, int_field, new_val)
                    changes.append(int_field)

        # 현장대리인
        if 'commencement_agent_id' in data:
            doc.commencement_agent_id = int(data['commencement_agent_id']) if data['commencement_agent_id'] else None
            changes.append('현장대리인')

        if not changes:
            return jsonify(ok=True, message='변경사항 없음')

        log_activity(db, '서류', 'update',
                     f'{doc.procurement_req_no} 수정 ({", ".join(changes)})',
                     ref_type='DocumentPackage', ref_id=doc.id)
        db.commit()
        return jsonify(ok=True, updated_fields=changes)


# ── 자재 입고확인 ──

@app_api_bp.route('/materials/<int:material_id>/confirm', methods=['POST'])
@app_auth_required
def app_material_confirm(material_id):
    """자재발주 품목 입고확인"""
    with get_db() as db:
        item = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.id == material_id).first()
        if not item:
            return jsonify(ok=False, error='자재 품목을 찾을 수 없습니다'), 404
        if item.in_confirmed:
            return jsonify(ok=False, error='이미 입고확인 처리되었습니다'), 400

        import datetime as _dt
        item.in_confirmed = True
        item.in_confirmed_at = _dt.datetime.now()

        log_activity(db, '자재', 'confirm',
                     f'{item.item_name} 입고확인',
                     ref_type='PurchaseOrderItem', ref_id=item.id)
        db.commit()
        return jsonify(ok=True)


# ── 자재 입고예정일 수정 ──

@app_api_bp.route('/materials/<int:material_id>/expected-date', methods=['POST'])
@app_auth_required
def app_material_expected_date(material_id):
    """자재발주 품목 입고예정일 수정"""
    data = request.get_json(silent=True) or {}
    expected_date = data.get('expected_in_date', '').strip()
    if not expected_date:
        return jsonify(ok=False, error='입고예정일을 입력해주세요'), 400

    with get_db() as db:
        item = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.id == material_id).first()
        if not item:
            return jsonify(ok=False, error='자재 품목을 찾을 수 없습니다'), 404

        import datetime as _dt
        item.expected_in_date = _dt.date.fromisoformat(expected_date)

        log_activity(db, '자재', 'update',
                     f'{item.item_name} 입고예정일 변경: {expected_date}',
                     ref_type='PurchaseOrderItem', ref_id=item.id)
        db.commit()
        return jsonify(ok=True)


# ── 알림 읽음 처리 ──

@app_api_bp.route('/notifications/<int:noti_id>/read', methods=['POST'])
@app_auth_required
def app_notification_read(noti_id):
    """알림 읽음 처리"""
    user_id = request._app_user_id
    with get_db() as db:
        noti = db.query(Notification).filter(
            Notification.id == noti_id,
            Notification.user_id == user_id,
        ).first()
        if noti:
            noti.is_read = True
            db.commit()
    return jsonify(ok=True)


# ============================================================
# ── 관리부 6개 메뉴 ERP 100% 매칭 신규 API 블록 ──
# ============================================================

# ─────────── 1. 청구관리 (Contract 기반) ───────────

@app_api_bp.route('/billing')
@app_auth_required
def app_billing():
    """청구관리 목록 — 납품완료 Contract 중심. ERP routes/billing.py와 동일 로직."""
    from sqlalchemy import or_
    q = (request.args.get('search') or request.args.get('q') or '').strip()
    tab = (request.args.get('tab') or 'pending').strip()

    with get_db() as db:
        today = datetime.date.today()
        base = (
            db.query(Contract)
            .join(Project, Contract.project_id == Project.id)
            .join(Delivery, Delivery.contract_id == Contract.id)
            .filter(
                Contract.is_excluded.isnot(True),
                Delivery.delivery_status == 'done',
            )
        )
        if tab == 'pending':
            base = base.filter(Contract.payment_status == '미청구')
        elif tab == 'partial':
            base = base.filter(Contract.payment_status == '부분입금')
        elif tab == 'billed':
            base = base.filter(Contract.payment_status == '청구완료')
        else:
            base = base.filter(Contract.payment_status.in_(['미청구', '청구완료', '부분입금']))

        if q:
            like_q = f'%{q}%'
            base = base.filter(or_(
                Contract.contract_name.ilike(like_q),
                Project.temp_name.ilike(like_q),
                Contract.g2b_contract_no.ilike(like_q),
            ))

        contract_ids = [r[0] for r in base.with_entities(Contract.id).distinct().all()]
        contracts = (
            db.query(Contract)
            .filter(Contract.id.in_(contract_ids))
            .options(joinedload(Contract.project))
            .order_by(Contract.delivery_due_date.asc().nullslast())
            .limit(200).all()
        ) if contract_ids else []

        g2b_nos = [c.g2b_contract_no for c in contracts if c.g2b_contract_no]
        amt_map, invoiced_set = {}, set()
        if g2b_nos:
            amt_rows = db.query(
                G2bProcurement.cntrct_dlvr_req_no,
                func.sum(G2bProcurement.prdct_amt),
            ).filter(G2bProcurement.cntrct_dlvr_req_no.in_(g2b_nos)) \
             .group_by(G2bProcurement.cntrct_dlvr_req_no).all()
            amt_map = {r[0]: r[1] or 0 for r in amt_rows}
            invoiced_rows = db.query(TaxInvoice.g2b_contract_no).filter(
                TaxInvoice.g2b_contract_no.in_(g2b_nos),
                TaxInvoice.match_status.in_(['자동매칭', '수동매칭']),
            ).distinct().all()
            invoiced_set = {r[0] for r in invoiced_rows}

        stats = {'미청구': 0, '청구완료': 0, '부분입금': 0}
        stats_rows = (
            db.query(Contract.payment_status, func.count(func.distinct(Contract.id)))
            .join(Delivery, Delivery.contract_id == Contract.id)
            .filter(
                Contract.is_excluded.isnot(True),
                Delivery.delivery_status == 'done',
                Contract.payment_status.in_(['미청구', '청구완료', '부분입금']),
            ).group_by(Contract.payment_status).all()
        )
        for ps, cnt in stats_rows:
            stats[ps] = cnt

        result = []
        for c in contracts:
            p = c.project
            dday = (c.delivery_due_date - today).days if c.delivery_due_date else None
            result.append({
                'id': c.id,
                'g2b_contract_no': c.g2b_contract_no or '',
                'contract_name': c.contract_name or '',
                'project_id': p.id if p else None,
                'project_name': (p.temp_name if p else '') or '',
                'delivery_due_date': str(c.delivery_due_date) if c.delivery_due_date else '',
                'dday': dday,
                'amount': int(amt_map.get(c.g2b_contract_no, 0) or 0),
                'is_invoiced': c.g2b_contract_no in invoiced_set,
                'payment_status': c.payment_status or '',
                'invoice_date': str(c.invoice_date) if c.invoice_date else '',
                'payment_date': str(c.payment_date) if c.payment_date else '',
            })
    return jsonify(ok=True, contracts=result, stats=stats, tab=tab)


@app_api_bp.route('/billing/<int:contract_id>')
@app_auth_required
def app_billing_detail(contract_id):
    """청구관리 상세 — Contract + Project + TaxInvoices + 히스토리"""
    with get_db() as db:
        c = db.query(Contract).options(
            joinedload(Contract.project),
            joinedload(Contract.deliveries),
        ).filter(Contract.id == contract_id).first()
        if not c:
            return jsonify(ok=False, error='계약을 찾을 수 없습니다'), 404

        p = c.project
        amount = 0
        invoiced = False
        tax_invoices = []
        if c.g2b_contract_no:
            amount = db.query(func.coalesce(func.sum(G2bProcurement.prdct_amt), 0)).filter(
                G2bProcurement.cntrct_dlvr_req_no == c.g2b_contract_no
            ).scalar() or 0
            invs = db.query(TaxInvoice).filter(
                TaxInvoice.g2b_contract_no == c.g2b_contract_no
            ).order_by(desc(TaxInvoice.issue_date)).all()
            for inv in invs:
                tax_invoices.append({
                    'id': inv.id,
                    'approval_no': inv.approval_no or '',
                    'issue_date': str(inv.issue_date) if inv.issue_date else '',
                    'invoice_type': inv.invoice_type or '',
                    'buyer_name': inv.buyer_name or '',
                    'supply_amount': inv.supply_amount or 0,
                    'tax_amount': inv.tax_amount or 0,
                    'total_amount': inv.total_amount or 0,
                    'match_status': inv.match_status or '',
                    'payment_status': inv.payment_status or '',
                })
            invoiced = any(i['match_status'] in ('자동매칭', '수동매칭') for i in tax_invoices)

        history = []
        if c.project_id:
            logs = db.query(HistoryLog).filter(
                HistoryLog.project_id == c.project_id,
                HistoryLog.log_scope == 'billing',
            ).order_by(desc(HistoryLog.created_at)).limit(30).all()
            history = [{
                'user_name': h.user_name or '',
                'content': h.content or '',
                'created_at': str(h.created_at) if h.created_at else '',
            } for h in logs]

        return jsonify(ok=True,
            contract={
                'id': c.id,
                'contract_name': c.contract_name or '',
                'g2b_contract_no': c.g2b_contract_no or '',
                'contract_date': str(c.contract_date) if c.contract_date else '',
                'delivery_due_date': str(c.delivery_due_date) if c.delivery_due_date else '',
                'payment_status': c.payment_status or '',
                'invoice_date': str(c.invoice_date) if c.invoice_date else '',
                'payment_date': str(c.payment_date) if c.payment_date else '',
                'is_excluded': bool(c.is_excluded),
            },
            project={
                'id': p.id if p else None,
                'temp_name': (p.temp_name if p else '') or '',
                'project_no': (p.project_no if p else '') or '',
            } if p else {},
            amount=int(amount),
            is_invoiced=invoiced,
            tax_invoices=tax_invoices,
            history=history,
        )


@app_api_bp.route('/billing/mark-billed', methods=['POST'])
@app_auth_required
def app_billing_mark_billed():
    """미청구/부분입금 → 청구완료"""
    from modules.history_board import append_history_log
    from modules.notification_engine import notify
    data = request.get_json(silent=True) or {}
    contract_id = data.get('contract_id')
    if not contract_id:
        return jsonify(ok=False, error='계약 ID 없음'), 400
    user_id = request._app_user_id
    with get_db() as db:
        c = db.query(Contract).get(int(contract_id))
        if not c:
            return jsonify(ok=False, error='계약을 찾을 수 없습니다'), 404
        if c.payment_status not in ('미청구', '부분입금'):
            return jsonify(ok=False, error=f'현재 상태 "{c.payment_status}"는 변경 불가'), 400
        c.payment_status = '청구완료'
        c.invoice_date = c.invoice_date or datetime.date.today()
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '사용자'
        if c.project_id:
            append_history_log(db, project_id=c.project_id, user_name=user_name,
                content=f"대금청구 완료 처리 — {c.contract_name}",
                scope="billing", kind="system")
        try:
            notify(db, 'billing.completed', {
                'contract_name': c.contract_name, 'user_name': user_name,
                'project_id': c.project_id or '',
            })
        except Exception:
            pass
        db.commit()
        return jsonify(ok=True, message='청구완료 처리되었습니다.')


@app_api_bp.route('/billing/revert-billed', methods=['POST'])
@app_auth_required
def app_billing_revert_billed():
    """청구완료 → 미청구 복원"""
    from modules.history_board import append_history_log
    data = request.get_json(silent=True) or {}
    contract_id = data.get('contract_id')
    if not contract_id:
        return jsonify(ok=False, error='계약 ID 없음'), 400
    user_id = request._app_user_id
    with get_db() as db:
        c = db.query(Contract).get(int(contract_id))
        if not c:
            return jsonify(ok=False, error='계약을 찾을 수 없습니다'), 404
        if c.payment_status != '청구완료':
            return jsonify(ok=False, error=f'현재 상태 "{c.payment_status}"는 복원 불가'), 400
        c.payment_status = '미청구'
        c.invoice_date = None
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '사용자'
        if c.project_id:
            append_history_log(db, project_id=c.project_id, user_name=user_name,
                content=f"대금청구 복원(미청구) — {c.contract_name}",
                scope="billing", kind="system")
        db.commit()
        return jsonify(ok=True, message='미청구로 복원되었습니다.')


@app_api_bp.route('/billing/<int:contract_id>/edit', methods=['POST'])
@app_auth_required
def app_billing_edit(contract_id):
    """청구/입금 일자 직접 수정 (payment_status는 수동 변경 금지)"""
    from modules.history_board import append_history_log
    data = request.get_json(silent=True) or {}
    user_id = request._app_user_id
    with get_db() as db:
        c = db.query(Contract).get(contract_id)
        if not c:
            return jsonify(ok=False, error='계약을 찾을 수 없습니다'), 404
        inv = data.get('invoice_date')
        pay = data.get('payment_date')
        c.invoice_date = datetime.date.fromisoformat(inv) if inv else None
        c.payment_date = datetime.date.fromisoformat(pay) if pay else None
        user = db.query(User).get(user_id)
        user_name = f"{user.full_name} {user.position or ''}".strip() if user else '사용자'
        if c.project_id:
            append_history_log(db, project_id=c.project_id, user_name=user_name,
                content=f"청구/입금일 수정 — 발행일 {c.invoice_date or '-'}, 입금일 {c.payment_date or '-'}",
                scope="billing", kind="system")
        db.commit()
        return jsonify(ok=True)


# ─────────── 2. 매출/수금 대시보드 ───────────

@app_api_bp.route('/financial/dashboard')
@app_auth_required
def app_financial_dashboard():
    """매출현황 대시보드 — ERP financial_dashboard 로직 재사용"""
    from sqlalchemy import extract
    with get_db() as db:
        today = datetime.date.today()
        current_month_start = today.replace(day=1)
        next_month = (current_month_start + datetime.timedelta(days=32)).replace(day=1)

        matched_filter = TaxInvoice.match_status.in_(['자동매칭', '수동매칭'])
        normal_filter = TaxInvoice.invoice_type == '세금계산서'

        monthly_supply = db.query(func.coalesce(func.sum(TaxInvoice.supply_amount), 0)).filter(
            normal_filter, matched_filter,
            TaxInvoice.issue_date >= current_month_start,
            TaxInvoice.issue_date < next_month
        ).scalar() or 0
        total_supply = db.query(func.coalesce(func.sum(TaxInvoice.supply_amount), 0)).filter(
            normal_filter, matched_filter
        ).scalar() or 0
        total_cnt = db.query(func.count(TaxInvoice.id)).filter(
            normal_filter, matched_filter
        ).scalar() or 0

        months = []
        for i in range(11, -1, -1):
            d = today - datetime.timedelta(days=i * 30)
            months.append(d.replace(day=1))
        monthly_labels, monthly_amounts, monthly_counts = [], [], []
        for m in months:
            m_end = (m + datetime.timedelta(days=32)).replace(day=1)
            row = db.query(
                func.coalesce(func.sum(TaxInvoice.supply_amount), 0),
                func.count(TaxInvoice.id),
            ).filter(
                normal_filter, matched_filter,
                TaxInvoice.issue_date >= m, TaxInvoice.issue_date < m_end
            ).first()
            monthly_labels.append(f"{m.month}월")
            monthly_amounts.append(int(row[0] or 0))
            monthly_counts.append(int(row[1] or 0))

        top_buyers = db.query(
            TaxInvoice.buyer_name,
            func.sum(TaxInvoice.supply_amount).label('total')
        ).filter(
            normal_filter, matched_filter,
            TaxInvoice.buyer_name.isnot(None)
        ).group_by(TaxInvoice.buyer_name).order_by(
            func.sum(TaxInvoice.supply_amount).desc()
        ).limit(10).all()

        invoiced_nos = set(
            r[0] for r in db.query(TaxInvoice.g2b_contract_no).filter(
                normal_filter, matched_filter,
                TaxInvoice.g2b_contract_no.isnot(None),
            ).all()
        )
        yearly_rows = db.query(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).label('yr'),
            func.count(G2bProcurement.id),
            func.sum(G2bProcurement.prdct_amt),
        ).filter(
            G2bProcurement.cntrct_dlvr_req_date.isnot(None),
        ).group_by('yr').order_by(desc('yr')).all()

        yearly_data = []
        for yr_val, cnt, contract_amt in yearly_rows:
            yr = int(yr_val) if yr_val else 0
            if yr < 2013:
                continue
            contract_amt = int(contract_amt or 0)
            invoiced_amt = 0
            if invoiced_nos:
                invoiced_amt = db.query(
                    func.coalesce(func.sum(G2bProcurement.prdct_amt), 0)
                ).filter(
                    extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                    G2bProcurement.cntrct_dlvr_req_no.in_(invoiced_nos),
                ).scalar() or 0
            yr_all_nos = set(
                r[0] for r in db.query(G2bProcurement.cntrct_dlvr_req_no).filter(
                    extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                ).distinct().all()
            )
            yr_uninvoiced_nos = yr_all_nos - invoiced_nos
            uninvoiced_cnt, uninvoiced_amt = 0, 0
            if yr_uninvoiced_nos:
                row = db.query(
                    func.count(G2bProcurement.id),
                    func.coalesce(func.sum(G2bProcurement.prdct_amt), 0),
                ).filter(
                    G2bProcurement.cntrct_dlvr_req_no.in_(yr_uninvoiced_nos),
                    extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                ).first()
                if row:
                    uninvoiced_cnt = row[0] or 0
                    uninvoiced_amt = int(row[1] or 0)
            sales_rate = round(int(invoiced_amt) / contract_amt * 100, 1) if contract_amt > 0 else 0
            yearly_data.append({
                'year': yr, 'contract_cnt': cnt, 'contract_amt': contract_amt,
                'invoiced_amt': int(invoiced_amt), 'sales_rate': sales_rate,
                'carryover_cnt': uninvoiced_cnt, 'carryover_amt': uninvoiced_amt,
            })

        recent_yearly = list(reversed(yearly_data[:5]))
        yearly_chart = {
            'labels': [str(d['year']) for d in recent_yearly],
            'contract': [d['contract_amt'] for d in recent_yearly],
            'invoiced': [d['invoiced_amt'] for d in recent_yearly],
            'carryover': [d['carryover_amt'] for d in recent_yearly],
        }

        yearly_invoice_rows = db.query(
            extract('year', TaxInvoice.issue_date).label('yr'),
            func.sum(TaxInvoice.total_amount),
            func.count(TaxInvoice.id),
        ).filter(
            matched_filter, TaxInvoice.issue_date.isnot(None),
        ).group_by('yr').order_by('yr').all()
        yearly_invoice_chart = {
            'labels': [str(int(r[0])) for r in yearly_invoice_rows if r[0] and int(r[0]) >= 2013],
            'amounts': [int(r[1] or 0) for r in yearly_invoice_rows if r[0] and int(r[0]) >= 2013],
            'counts': [int(r[2] or 0) for r in yearly_invoice_rows if r[0] and int(r[0]) >= 2013],
        }

        return jsonify(ok=True,
            kpi={'monthly_supply': int(monthly_supply),
                 'total_supply': int(total_supply),
                 'total_cnt': int(total_cnt)},
            monthly={'labels': monthly_labels,
                     'amounts': monthly_amounts,
                     'counts': monthly_counts},
            top_buyers={'labels': [r[0] or '(미상)' for r in top_buyers],
                        'amounts': [int(r[1] or 0) for r in top_buyers]},
            yearly_data=yearly_data,
            yearly_chart=yearly_chart,
            yearly_invoice_chart=yearly_invoice_chart,
        )


# ─────────── 3. 거래처 상세/등록/수정/메모/삭제 ───────────

@app_api_bp.route('/vendors/<int:vendor_id>')
@app_auth_required
def app_vendor_detail(vendor_id):
    """거래처 상세 + 발주/입고 이력 통합 — ERP vendor_detail 동일"""
    from modules.models import (
        PurchaseOrderHistory, ReceivingHistory, ProcessingOrder,
    )
    def _parse_items_json(s):
        if not s:
            return []
        try:
            return json.loads(s)
        except Exception:
            return []

    with get_db() as db:
        v = db.query(Vendor).filter(Vendor.id == vendor_id).first()
        if not v:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404

        vendor = {
            'id': v.id,
            'icube_tr_cd': v.icube_tr_cd or '',
            'name': v.name or '',
            'ceo_name': v.ceo_name or '',
            'business_no': v.business_no or '',
            'email': v.email or '',
            'tel': v.tel or '',
            'fax': v.fax or '',
            'address': v.address or '',
            'business': v.business or '',
            'jongmok': v.jongmok or '',
            'is_active': bool(v.is_active),
            'note': v.note or '',
        }

        purchase_orders = []
        for po in db.query(PurchaseOrder).filter(PurchaseOrder.vendor_id == v.id)\
                    .order_by(desc(PurchaseOrder.po_date)).all():
            detail_rows = [{
                'ITEM_NM': pi.item_name or '', 'ITEM_CD': pi.item_code or '',
                'ITEM_DC': pi.item_spec or '', 'UNIT_DC': pi.unit or '',
                'CLS_QT': pi.quantity or 0, 'CLS_UM': pi.unit_price or 0,
                'CLSH_AM': pi.amount or 0, 'ITEM_REMARK': pi.note or '',
            } for pi in po.items]
            purchase_orders.append({
                'CLS_NB': po.po_no, 'CLS_DT': po.po_date.strftime('%Y-%m-%d') if po.po_date else '',
                'REMARK_DC': po.note or '', 'detail_rows': detail_rows,
                'total': int(po.total_amount or 0), 'po_id': po.id, 'source': 'po',
            })
        for fo in db.query(ProcessingOrder).filter(ProcessingOrder.vendor_id == v.id)\
                    .order_by(desc(ProcessingOrder.fo_date)).all():
            detail_rows = [{
                'ITEM_NM': fi.item_name or '', 'ITEM_CD': '',
                'ITEM_DC': fi.item_spec or '', 'UNIT_DC': fi.unit or '',
                'CLS_QT': fi.quantity or 0, 'CLS_UM': fi.unit_price or 0,
                'CLSH_AM': fi.amount or 0, 'ITEM_REMARK': fi.note or '',
            } for fi in fo.items]
            purchase_orders.append({
                'CLS_NB': fo.fo_no, 'CLS_DT': fo.fo_date.strftime('%Y-%m-%d') if fo.fo_date else '',
                'REMARK_DC': fo.note or '', 'detail_rows': detail_rows,
                'total': int(fo.total_amount or 0), 'fo_id': fo.id, 'source': 'fo',
            })
        if v.icube_tr_cd:
            for po in db.query(PurchaseOrderHistory).filter(
                PurchaseOrderHistory.vendor_tr_cd == v.icube_tr_cd
            ).order_by(desc(PurchaseOrderHistory.order_date)).all():
                items = _parse_items_json(po.items_json)
                detail_rows = [{
                    'ITEM_NM': it.get('item_name',''), 'ITEM_CD': it.get('item_cd',''),
                    'ITEM_DC': it.get('spec',''), 'UNIT_DC': it.get('unit',''),
                    'CLS_QT': it.get('qty',0), 'CLS_UM': it.get('unit_price',0),
                    'CLSH_AM': it.get('amount',0), 'ITEM_REMARK': it.get('remark',''),
                } for it in items]
                purchase_orders.append({
                    'CLS_NB': po.icube_cls_nb,
                    'CLS_DT': po.order_date.strftime('%Y-%m-%d') if po.order_date else '',
                    'REMARK_DC': po.remark or '', 'detail_rows': detail_rows,
                    'total': int(po.total_amount or 0), 'source': 'icube',
                })
        purchase_orders.sort(key=lambda x: x['CLS_DT'] or '', reverse=True)

        receivings = []
        for rcv in db.query(Receiving).filter(Receiving.vendor_id == v.id)\
                    .order_by(desc(Receiving.rcv_date)).all():
            detail_rows = [{
                'ITEM_NM': ri.item_name or '', 'ITEM_CD': ri.item_cd or '',
                'ITEM_DC': ri.item_spec or '', 'UNIT_DC': ri.unit or '',
                'RCV_QT': ri.received_qty or 0, 'RCV_UM': ri.unit_price or 0,
                'RCVH_AM': ri.amount or 0, 'REMARK_DC': ri.note or '',
            } for ri in rcv.items]
            receivings.append({
                'RCV_NB': rcv.rcv_no,
                'RCV_DT': rcv.rcv_date.strftime('%Y-%m-%d') if rcv.rcv_date else '',
                'detail_rows': detail_rows,
                'total': int(sum(ri.amount or 0 for ri in rcv.items)),
                'rcv_id': rcv.id, 'source': 'new',
            })
        if v.icube_tr_cd:
            for rcv in db.query(ReceivingHistory).filter(
                ReceivingHistory.vendor_tr_cd == v.icube_tr_cd
            ).order_by(desc(ReceivingHistory.receive_date)).all():
                items = _parse_items_json(rcv.items_json)
                detail_rows = [{
                    'ITEM_NM': it.get('item_name',''), 'ITEM_CD': it.get('item_cd',''),
                    'ITEM_DC': it.get('spec',''), 'UNIT_DC': it.get('unit',''),
                    'RCV_QT': it.get('qty',0), 'RCV_UM': it.get('unit_price',0),
                    'RCVH_AM': it.get('amount',0), 'REMARK_DC': it.get('remark',''),
                } for it in items]
                receivings.append({
                    'RCV_NB': rcv.icube_rcv_nb,
                    'RCV_DT': rcv.receive_date.strftime('%Y-%m-%d') if rcv.receive_date else '',
                    'detail_rows': detail_rows,
                    'total': int(rcv.total_amount or 0), 'source': 'icube',
                })
        receivings.sort(key=lambda x: x['RCV_DT'] or '', reverse=True)

        trade_stats = {
            'po_count': len(purchase_orders),
            'po_total': sum(p['total'] for p in purchase_orders),
            'rcv_count': len(receivings),
            'rcv_total': sum(r['total'] for r in receivings),
            'last_po_date': purchase_orders[0]['CLS_DT'] if purchase_orders else '-',
            'last_rcv_date': receivings[0]['RCV_DT'] if receivings else '-',
        }
        return jsonify(ok=True, vendor=vendor,
                       purchase_orders=purchase_orders,
                       receivings=receivings,
                       trade_stats=trade_stats)


@app_api_bp.route('/vendors/create', methods=['POST'])
@app_auth_required
def app_vendor_create():
    """거래처 신규 등록 — 모든 필드 수용"""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify(ok=False, error='거래처명을 입력해주세요'), 400
    with get_db() as db:
        vendor = Vendor(
            name=name,
            ceo_name=(data.get('ceo_name') or '').strip() or None,
            business_no=(data.get('business_no') or '').strip() or None,
            tel=(data.get('tel') or '').strip() or None,
            fax=(data.get('fax') or '').strip() or None,
            email=(data.get('email') or '').strip() or None,
            address=(data.get('address') or '').strip() or None,
            business=(data.get('business') or '').strip() or None,
            jongmok=(data.get('jongmok') or '').strip() or None,
            note=(data.get('note') or '').strip() or None,
            is_active=True,
        )
        db.add(vendor)
        db.flush()
        log_activity(db, '거래처', 'create', f'{name} 등록',
                     ref_type='Vendor', ref_id=vendor.id, ref_label=name)
        db.commit()
        return jsonify(ok=True, vendor_id=vendor.id)


@app_api_bp.route('/vendors/<int:vendor_id>/edit', methods=['POST'])
@app_auth_required
def app_vendor_edit(vendor_id):
    """거래처 수정 — 확장 필드 수용 + is_active 토글"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
        if not vendor:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404
        for key in ('name', 'ceo_name', 'business_no', 'tel', 'fax',
                    'email', 'address', 'business', 'jongmok', 'note'):
            if key in data:
                val = (data.get(key) or '').strip()
                setattr(vendor, key, val or None)
        if 'is_active' in data:
            vendor.is_active = bool(data['is_active'])
        log_activity(db, '거래처', 'update', f'{vendor.name} 수정',
                     ref_type='Vendor', ref_id=vendor.id, ref_label=vendor.name)
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/vendors/<int:vendor_id>/note', methods=['POST'])
@app_auth_required
def app_vendor_note(vendor_id):
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        v = db.query(Vendor).filter(Vendor.id == vendor_id).first()
        if not v:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404
        v.note = (data.get('note') or '').strip() or None
        log_activity(db, '거래처', 'update', f'{v.name} 메모 수정',
                     ref_type='Vendor', ref_id=v.id, ref_label=v.name)
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/vendors/<int:vendor_id>/delete', methods=['POST'])
@app_auth_required
def app_vendor_delete(vendor_id):
    """거래처 삭제 — 이력 있으면 비활성화만"""
    with get_db() as db:
        v = db.query(Vendor).filter(Vendor.id == vendor_id).first()
        if not v:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404
        has_po = db.query(PurchaseOrder).filter(PurchaseOrder.vendor_id == v.id).first()
        has_rcv = db.query(Receiving).filter(Receiving.vendor_id == v.id).first()
        if has_po or has_rcv:
            v.is_active = False
            log_activity(db, '거래처', 'deactivate', f'{v.name} 비활성화 (이력 존재)',
                         ref_type='Vendor', ref_id=v.id, ref_label=v.name)
            db.commit()
            return jsonify(ok=True, deactivated=True)
        name = v.name
        db.delete(v)
        log_activity(db, '거래처', 'delete', f'{name} 삭제',
                     ref_type='Vendor', ref_label=name)
        db.commit()
        return jsonify(ok=True, deleted=True)


# ─────────── 4. 인증서 상세/수정/등록(multipart)/파일뷰어 ───────────

@app_api_bp.route('/certifications/<int:cert_id>')
@app_auth_required
def app_certification_detail(cert_id):
    """인증서 상세"""
    today = datetime.date.today()
    with get_db() as db:
        c = db.query(Certification).get(cert_id)
        if not c or not c.is_active:
            return jsonify(ok=False, error='인증서를 찾을 수 없습니다'), 404
        days = (c.expiry_date - today).days if c.expiry_date else None
        return jsonify(ok=True, cert={
            'id': c.id,
            'cert_type': c.cert_type or '',
            'cert_name': c.cert_name or '',
            'cert_no': c.cert_no or '',
            'issued_by': c.issued_by or '',
            'issuer': c.issued_by or '',
            'issued_date': str(c.issued_date) if c.issued_date else '',
            'issue_date': str(c.issued_date) if c.issued_date else '',
            'expiry_date': str(c.expiry_date) if c.expiry_date else '',
            'expiry_status': c.expiry_status if hasattr(c, 'expiry_status') else 'unknown',
            'days_until_expiry': days,
            'product_model': c.product_model or '',
            'alert_days': c.alert_days or 30,
            'note': c.note or '',
            'file_path': c.file_path or '',
            'has_file': bool(c.file_path),
        })


@app_api_bp.route('/certifications/create', methods=['POST'])
@app_auth_required
def app_certification_create():
    """인증서 신규 등록 — multipart/form-data 또는 JSON 지원"""
    from werkzeug.utils import secure_filename
    from modules.storage_adapter import upload_bytes

    if request.content_type and 'multipart/form-data' in request.content_type:
        src = request.form
    else:
        src = request.get_json(silent=True) or {}

    cert_name = (src.get('cert_name') or '').strip()
    if not cert_name:
        return jsonify(ok=False, error='인증서명을 입력해주세요'), 400

    def _pd(s):
        if not s:
            return None
        try:
            return datetime.date.fromisoformat(s)
        except Exception:
            return None
    def _si(v, default):
        try:
            return int(v) if v not in (None, '') else default
        except Exception:
            return default

    file_path = None
    upload = request.files.get('cert_file') if request.files else None
    if upload and upload.filename:
        data = upload.read()
        if data:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            safe = secure_filename(upload.filename)
            file_path = f"storage/certifications/{ts}_{safe}"
            ok, err = upload_bytes(file_path, data, upload.mimetype or 'application/pdf')
            if not ok:
                return jsonify(ok=False, error=f'파일 업로드 실패: {err}'), 500

    with get_db() as db:
        cert = Certification(
            cert_name=cert_name,
            cert_type=src.get('cert_type') or '기타',
            cert_no=(src.get('cert_no') or '').strip() or None,
            issued_by=(src.get('issued_by') or src.get('issuer') or '').strip() or None,
            issued_date=_pd(src.get('issued_date') or src.get('issue_date')),
            expiry_date=_pd(src.get('expiry_date')),
            product_model=(src.get('product_model') or '').strip() or None,
            alert_days=_si(src.get('alert_days'), 30),
            note=(src.get('note') or '').strip() or None,
            file_path=file_path,
        )
        db.add(cert)
        db.flush()
        log_activity(db, '인증서', 'create', f'{cert_name} 등록',
                     ref_type='Certification', ref_id=cert.id)
        db.commit()
        return jsonify(ok=True, cert_id=cert.id)


@app_api_bp.route('/certifications/<int:cert_id>/edit', methods=['POST'])
@app_auth_required
def app_certification_edit(cert_id):
    """인증서 수정 — multipart"""
    from werkzeug.utils import secure_filename
    from modules.storage_adapter import upload_bytes

    def _pd(s):
        if not s:
            return None
        try:
            return datetime.date.fromisoformat(s)
        except Exception:
            return None
    def _si(v, default):
        try:
            return int(v) if v not in (None, '') else default
        except Exception:
            return default

    with get_db() as db:
        cert = db.query(Certification).get(cert_id)
        if not cert:
            return jsonify(ok=False, error='인증서를 찾을 수 없습니다'), 404

        f = request.form
        if f.get('cert_type'):
            cert.cert_type = f.get('cert_type')
        cert.cert_name = (f.get('cert_name') or '').strip() or cert.cert_name
        cert.cert_no = (f.get('cert_no') or '').strip() or None
        cert.issued_by = (f.get('issued_by') or '').strip() or None
        cert.issued_date = _pd(f.get('issued_date'))
        cert.expiry_date = _pd(f.get('expiry_date'))
        cert.product_model = (f.get('product_model') or '').strip() or None
        cert.alert_days = _si(f.get('alert_days'), 30)
        cert.note = (f.get('note') or '').strip() or None

        upload = request.files.get('cert_file')
        if upload and upload.filename:
            data = upload.read()
            if data:
                ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                safe = secure_filename(upload.filename)
                path = f"storage/certifications/{ts}_{safe}"
                ok, err = upload_bytes(path, data, upload.mimetype or 'application/pdf')
                if not ok:
                    return jsonify(ok=False, error=f'파일 업로드 실패: {err}'), 500
                cert.file_path = path

        log_activity(db, '인증서', 'edit', f'{cert.cert_name} 수정',
                     ref_type='Certification', ref_id=cert.id)
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/certifications/<int:cert_id>/file')
def app_certification_file(cert_id):
    """인증서 파일 뷰어 — 토큰 쿼리 인증"""
    import os as _os
    from flask import Response, abort, send_file, redirect
    from modules.storage_adapter import download_bytes

    if not _verify_token_from_request():
        abort(401)

    with get_db() as db:
        cert = db.query(Certification).get(cert_id)
        if not cert or not cert.file_path:
            abort(404)
        if cert.file_path.startswith('http'):
            return redirect(cert.file_path)
        data = download_bytes(cert.file_path)
        if not data:
            local = _os.path.join(current_app.static_folder, cert.file_path) if current_app.static_folder else None
            if local and _os.path.exists(local):
                return send_file(local)
            abort(404)
        ext = _os.path.splitext(cert.file_path)[1].lower().lstrip('.')
        mime_map = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'png': 'image/png', 'webp': 'image/webp'}
        return Response(data, mimetype=mime_map.get(ext, 'application/octet-stream'),
                        headers={'Content-Disposition': f'inline; filename="{_os.path.basename(cert.file_path)}"'})


# ─────────── 5. 입고 상세/생성(items)/수정/삭제/PO소스/PO검색/대사 ───────────

@app_api_bp.route('/receivings/<int:rcv_id>')
@app_auth_required
def app_receiving_detail(rcv_id):
    """입고 상세 — ERP receiving_detail 동일 데이터"""
    with get_db() as db:
        rcv = db.query(Receiving).options(
            joinedload(Receiving.items).joinedload(ReceivingItem.po_item),
            joinedload(Receiving.vendor),
            joinedload(Receiving.purchase_order),
            joinedload(Receiving.processing_order),
            joinedload(Receiving.contract),
        ).get(rcv_id)
        if not rcv:
            return jsonify(ok=False, error='입고를 찾을 수 없습니다'), 404
        items = [{
            'id': it.id,
            'po_item_id': it.po_item_id,
            'fo_item_id': it.fo_item_id,
            'item_cd': it.item_cd or (it.po_item.item_code if it.po_item else '') or '',
            'item_name': it.item_name or '',
            'item_spec': it.item_spec or '',
            'received_qty': it.received_qty or 0,
            'unit': it.unit or '',
            'unit_price': it.unit_price or 0,
            'amount': it.amount or 0,
            'note': it.note or '',
        } for it in (rcv.items or [])]
        return jsonify(ok=True, receiving={
            'id': rcv.id,
            'rcv_no': rcv.rcv_no,
            'rcv_date': str(rcv.rcv_date) if rcv.rcv_date else '',
            'status': rcv.status or '검수대기',
            'vendor_id': rcv.vendor_id,
            'vendor_name': rcv.vendor.name if rcv.vendor else '',
            'po_id': rcv.po_id,
            'po_no': rcv.purchase_order.po_no if rcv.purchase_order else '',
            'fo_id': rcv.fo_id,
            'fo_no': rcv.processing_order.fo_no if rcv.processing_order else '',
            'contract_id': rcv.contract_id,
            'contract_name': rcv.contract.contract_name if rcv.contract else '',
            'note': rcv.note or '',
        }, items=items)


@app_api_bp.route('/receivings/source')
@app_auth_required
def app_receiving_source():
    """PO 또는 FO ID로 거래처/품목(잔량) 조회"""
    from modules.models import ProcessingOrderItem
    po_id = request.args.get('po_id', type=int)
    fo_id = request.args.get('fo_id', type=int)
    with get_db() as db:
        if po_id:
            po = db.query(PurchaseOrder).options(
                joinedload(PurchaseOrder.items),
                joinedload(PurchaseOrder.vendor),
            ).get(po_id)
            if not po:
                return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404
            items = []
            for pi in po.items:
                already = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                    ReceivingItem.po_item_id == pi.id,
                ).scalar() or 0
                items.append({
                    'id': pi.id,
                    'item_code': pi.item_code or '',
                    'item_name': pi.item_name or '',
                    'item_spec': pi.item_spec or '',
                    'quantity': float(pi.quantity or 0),
                    'already_received': float(already),
                    'remaining': max(0, float(pi.quantity or 0) - float(already)),
                    'unit': pi.unit or '',
                    'unit_price': float(pi.unit_price or 0),
                })
            return jsonify(ok=True, source_type='po', source_no=po.po_no,
                           vendor_id=po.vendor_id,
                           vendor_name=po.vendor.name if po.vendor else '',
                           items=items)
        elif fo_id:
            fo = db.query(ProcessingOrder).options(
                joinedload(ProcessingOrder.items),
                joinedload(ProcessingOrder.vendor),
            ).get(fo_id)
            if not fo:
                return jsonify(ok=False, error='가공발주서를 찾을 수 없습니다'), 404
            items = []
            for fi in fo.items:
                already = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                    ReceivingItem.fo_item_id == fi.id,
                ).scalar() or 0
                items.append({
                    'id': fi.id,
                    'item_code': '',
                    'item_name': fi.item_name or '',
                    'item_spec': fi.item_spec or '',
                    'quantity': float(fi.quantity or 0),
                    'already_received': float(already),
                    'remaining': max(0, float(fi.quantity or 0) - float(already)),
                    'unit': fi.unit or '',
                    'unit_price': float(fi.unit_price or 0),
                })
            return jsonify(ok=True, source_type='fo', source_no=fo.fo_no,
                           vendor_id=fo.vendor_id,
                           vendor_name=fo.vendor.name if fo.vendor else '',
                           items=items)
        return jsonify(ok=False, error='po_id 또는 fo_id 필요'), 400


@app_api_bp.route('/receivings/po-search')
@app_auth_required
def app_receiving_po_search():
    """입고 등록 시 PO/FO 검색"""
    q = (request.args.get('q') or '').strip()
    vendor_id = request.args.get('vendor_id', type=int)
    with get_db() as db:
        po_query = db.query(PurchaseOrder).join(Vendor, PurchaseOrder.vendor_id == Vendor.id).filter(
            PurchaseOrder.status.in_(['발송완료', '입고대기'])
        )
        if vendor_id:
            po_query = po_query.filter(PurchaseOrder.vendor_id == vendor_id)
        if q:
            like_q = f'%{q}%'
            po_query = po_query.filter(
                (PurchaseOrder.po_no.ilike(like_q)) | (Vendor.name.ilike(like_q))
            )
        pos = po_query.order_by(desc(PurchaseOrder.po_date)).limit(20).all()
        results = [{
            'id': p.id, 'po_no': p.po_no,
            'po_date': p.po_date.strftime('%Y-%m-%d') if p.po_date else '',
            'vendor_name': p.vendor.name if p.vendor else '',
            'vendor_id': p.vendor_id,
            'status': p.status,
            'total_amount': float(p.total_amount or 0),
            'order_type': 'po',
        } for p in pos]

        fo_query = db.query(ProcessingOrder).join(Vendor, ProcessingOrder.vendor_id == Vendor.id).filter(
            ProcessingOrder.status.in_(['발주완료', '가공중'])
        )
        if vendor_id:
            fo_query = fo_query.filter(ProcessingOrder.vendor_id == vendor_id)
        if q:
            like_q = f'%{q}%'
            fo_query = fo_query.filter(
                (ProcessingOrder.fo_no.ilike(like_q)) | (Vendor.name.ilike(like_q))
            )
        fos = fo_query.order_by(desc(ProcessingOrder.fo_date)).limit(20).all()
        results += [{
            'id': f.id, 'po_no': f.fo_no,
            'po_date': f.fo_date.strftime('%Y-%m-%d') if f.fo_date else '',
            'vendor_name': f.vendor.name if f.vendor else '',
            'vendor_id': f.vendor_id,
            'status': f.status,
            'total_amount': float(f.total_amount or 0),
            'order_type': 'fo',
        } for f in fos]
        return jsonify(ok=True, results=results)


@app_api_bp.route('/receivings/po-comparison/<int:po_id>')
@app_auth_required
def app_receiving_po_comparison(po_id):
    """발주 vs 입고 대사"""
    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items),
            joinedload(PurchaseOrder.vendor),
        ).get(po_id)
        if not po:
            return jsonify(ok=False, error='발주서를 찾을 수 없습니다'), 404
        comparison = []
        for pi in po.items:
            received = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                ReceivingItem.po_item_id == pi.id,
            ).scalar() or 0
            ordered = float(pi.quantity or 0)
            diff = float(received) - ordered
            status = '완료'
            if diff < 0:
                status = '미입고'
            elif diff > 0:
                status = '과입고'
            comparison.append({
                'item_code': pi.item_code or '',
                'item_name': pi.item_name, 'item_spec': pi.item_spec or '',
                'ordered_qty': int(ordered), 'received_qty': int(received),
                'diff': int(diff), 'unit': pi.unit or '', 'status': status,
            })
        return jsonify(ok=True, po_no=po.po_no,
                       vendor_name=po.vendor.name if po.vendor else '',
                       items=comparison)


@app_api_bp.route('/receivings/create', methods=['POST'])
@app_auth_required
def app_receiving_create():
    """입고 신규 생성 — ERP receiving_create POST 동일"""
    from modules.models import (
        PurchaseOrderItem, ProcessingOrderItem, Item,
    )
    from routes.receiving import _generate_rcv_no, _update_po_status_on_receiving

    data = request.get_json(silent=True) or {}
    vendor_id = data.get('vendor_id')
    if not vendor_id:
        return jsonify(ok=False, error='거래처를 선택해주세요'), 400
    items_in = data.get('items') or []
    if not items_in:
        return jsonify(ok=False, error='품목을 최소 1개 입력해주세요'), 400

    user_id = request._app_user_id
    with get_db() as db:
        vendor = db.query(Vendor).get(int(vendor_id))
        if not vendor:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404
        try:
            rcv_date = datetime.datetime.strptime(data.get('rcv_date') or '', '%Y-%m-%d').date()
        except ValueError:
            rcv_date = datetime.date.today()
        po_id = data.get('po_id') or None
        fo_id = data.get('fo_id') or None
        contract_id = None
        if po_id:
            po = db.query(PurchaseOrder).get(int(po_id))
            if po:
                contract_id = po.contract_id
        elif fo_id:
            fo = db.query(ProcessingOrder).get(int(fo_id))
            if fo:
                contract_id = fo.contract_id

        rcv = Receiving(
            rcv_no=_generate_rcv_no(db),
            rcv_date=rcv_date,
            vendor_id=vendor.id,
            po_id=int(po_id) if po_id else None,
            fo_id=int(fo_id) if fo_id else None,
            contract_id=contract_id,
            note=(data.get('note') or '').strip(),
            created_by=user_id,
        )
        db.add(rcv)
        db.flush()

        for it in items_in:
            name = (it.get('item_name') or '').strip()
            if not name:
                continue
            qty = float(it.get('received_qty') or 0)
            price = float(it.get('unit_price') or 0)
            po_item_id = it.get('po_item_id') or None
            fo_item_id = it.get('fo_item_id') or None
            item_cd = (it.get('item_cd') or '').strip()
            if po_item_id and not item_cd:
                poi = db.query(PurchaseOrderItem).get(int(po_item_id))
                if poi:
                    item_cd = poi.item_code or ''

            db.add(ReceivingItem(
                receiving_id=rcv.id,
                po_item_id=int(po_item_id) if po_item_id else None,
                fo_item_id=int(fo_item_id) if fo_item_id else None,
                item_cd=item_cd or None,
                item_name=name,
                item_spec=(it.get('item_spec') or '').strip(),
                received_qty=qty,
                unit=(it.get('unit') or '').strip(),
                unit_price=price,
                amount=qty * price,
                note=(it.get('note') or '').strip(),
            ))

        if po_id:
            _update_po_status_on_receiving(db, int(po_id))
            po_obj = db.query(PurchaseOrder).options(joinedload(PurchaseOrder.items)).get(int(po_id))
            if po_obj:
                now_dt = datetime.datetime.now()
                for pi in po_obj.items:
                    total_rcv = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                        ReceivingItem.po_item_id == pi.id,
                    ).scalar() or 0
                    if total_rcv >= (pi.quantity or 0) and not pi.in_confirmed:
                        pi.in_confirmed = True
                        pi.in_confirmed_at = now_dt
        if fo_id:
            fo_obj = db.query(ProcessingOrder).options(joinedload(ProcessingOrder.items)).get(int(fo_id))
            if fo_obj:
                now_dt = datetime.datetime.now()
                all_conf = True
                for fi in fo_obj.items:
                    total_rcv = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                        ReceivingItem.fo_item_id == fi.id,
                    ).scalar() or 0
                    if total_rcv >= (fi.quantity or 0) and not fi.in_confirmed:
                        fi.in_confirmed = True
                        fi.in_confirmed_at = now_dt
                    if not fi.in_confirmed:
                        all_conf = False
                if all_conf and fo_obj.status != '입고완료':
                    fo_obj.status = '입고완료'

        log_activity(db, '입고관리', 'create',
                     f'{rcv.rcv_no} 입고 등록 ({vendor.name})',
                     ref_type='Receiving', ref_id=rcv.id, ref_label=rcv.rcv_no)
        db.commit()
        return jsonify(ok=True, rcv_id=rcv.id, rcv_no=rcv.rcv_no)


@app_api_bp.route('/receivings/<int:rcv_id>/update', methods=['POST'])
@app_auth_required
def app_receiving_update(rcv_id):
    """입고 수정 — ERP receiving_edit 동일 (items 전량 삭제 후 재등록)"""
    from modules.models import PurchaseOrderItem
    from routes.receiving import _update_po_status_on_receiving

    data = request.get_json(silent=True) or {}
    with get_db() as db:
        rcv = db.query(Receiving).options(joinedload(Receiving.items)).get(rcv_id)
        if not rcv:
            return jsonify(ok=False, error='입고를 찾을 수 없습니다'), 404

        vendor_id = data.get('vendor_id')
        if not vendor_id:
            return jsonify(ok=False, error='거래처를 선택해주세요'), 400
        vendor = db.query(Vendor).get(int(vendor_id))
        if not vendor:
            return jsonify(ok=False, error='거래처를 찾을 수 없습니다'), 404

        try:
            rcv.rcv_date = datetime.datetime.strptime(data.get('rcv_date') or '', '%Y-%m-%d').date()
        except ValueError:
            pass
        rcv.vendor_id = vendor.id
        rcv.note = (data.get('note') or '').strip()

        for old in list(rcv.items):
            db.delete(old)
        db.flush()

        for it in (data.get('items') or []):
            name = (it.get('item_name') or '').strip()
            if not name:
                continue
            qty = float(it.get('received_qty') or 0)
            price = float(it.get('unit_price') or 0)
            po_item_id = it.get('po_item_id') or None
            fo_item_id = it.get('fo_item_id') or None
            item_cd = (it.get('item_cd') or '').strip()
            if po_item_id and not item_cd:
                poi = db.query(PurchaseOrderItem).get(int(po_item_id))
                if poi:
                    item_cd = poi.item_code or ''
            db.add(ReceivingItem(
                receiving_id=rcv.id,
                po_item_id=int(po_item_id) if po_item_id else None,
                fo_item_id=int(fo_item_id) if fo_item_id else None,
                item_cd=item_cd or None,
                item_name=name,
                item_spec=(it.get('item_spec') or '').strip(),
                received_qty=qty,
                unit=(it.get('unit') or '').strip(),
                unit_price=price,
                amount=qty * price,
                note=(it.get('note') or '').strip(),
            ))

        if rcv.po_id:
            _update_po_status_on_receiving(db, rcv.po_id)

        log_activity(db, '입고관리', 'update',
                     f'{rcv.rcv_no} 입고 수정 ({vendor.name})',
                     ref_type='Receiving', ref_id=rcv.id, ref_label=rcv.rcv_no)
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/receivings/<int:rcv_id>/delete', methods=['POST'])
@app_auth_required
def app_receiving_delete(rcv_id):
    """입고 삭제 — ERP receiving_delete 동일"""
    from routes.receiving import _update_po_status_on_receiving
    with get_db() as db:
        rcv = db.query(Receiving).get(rcv_id)
        if not rcv:
            return jsonify(ok=False, error='입고를 찾을 수 없습니다'), 404
        po_id = rcv.po_id
        rcv_no = rcv.rcv_no
        log_activity(db, '입고관리', 'delete', f'{rcv_no} 입고 삭제',
                     ref_type='Receiving', ref_label=rcv_no)
        db.delete(rcv)
        db.flush()
        if po_id:
            _update_po_status_on_receiving(db, po_id)
        db.commit()
        return jsonify(ok=True)


# ─────────── 6. 가공발주 신규 생성 / 수정 / 업로드 / 이메일 ───────────

@app_api_bp.route('/processing-orders/create', methods=['POST'])
@app_auth_required
def app_processing_order_create():
    """가공발주 신규 생성 — multipart(files) or JSON"""
    from routes.processing_order import (
        _generate_fo_no, _parse_fo_items, _append_fo_history,
        _register_as_drawing, _allowed_file, MAX_FILE_SIZE,
    )
    from modules.storage_adapter import upload_bytes, is_storage_enabled
    from modules.models import ProcessingOrderFile

    user_id = request._app_user_id
    is_multipart = request.content_type and 'multipart/form-data' in request.content_type
    form = request.form if is_multipart else None
    data = None if is_multipart else (request.get_json(silent=True) or {})

    src = form if is_multipart else data
    vendor_id = int(src.get('vendor_id') or 0) if src else 0
    if not vendor_id:
        return jsonify(ok=False, error='가공업체를 선택해주세요'), 400

    with get_db() as db:
        vendor = db.query(Vendor).get(vendor_id)
        if not vendor:
            return jsonify(ok=False, error='가공업체를 찾을 수 없습니다'), 404

        try:
            fo_date = datetime.date.fromisoformat(src.get('fo_date') or datetime.date.today().isoformat())
        except Exception:
            fo_date = datetime.date.today()

        fo = ProcessingOrder(
            fo_no=_generate_fo_no(db),
            fo_date=fo_date,
            vendor_id=vendor_id,
            processing_type=src.get('processing_type') or '외주가공',
            project_id=int(src.get('project_id')) if src.get('project_id') else None,
            contract_id=int(src.get('contract_id')) if src.get('contract_id') else None,
            assigned_to=int(src.get('assigned_to')) if src.get('assigned_to') else user_id,
            note=(src.get('note') or '').strip() or None,
            status='작성중',
            created_by=user_id,
        )

        if is_multipart:
            items, total = _parse_fo_items(form)
            for item in items:
                fo.items.append(item)
            fo.total_amount = total
            fo.tax_amount = round(total * 0.1)
        else:
            total = 0
            for it in (data.get('items') or []):
                name = (it.get('item_name') or '').strip()
                if not name:
                    continue
                qty = float(it.get('quantity') or 0)
                price = float(it.get('unit_price') or 0)
                amt = qty * price
                dd = None
                if it.get('delivery_date'):
                    try:
                        dd = datetime.date.fromisoformat(it['delivery_date'])
                    except Exception:
                        pass
                fo.items.append(ProcessingOrderItem(
                    item_id=int(it['item_id']) if it.get('item_id') else None,
                    item_name=name,
                    item_spec=(it.get('item_spec') or '').strip(),
                    quantity=qty,
                    unit_price=price,
                    amount=amt,
                    unit=(it.get('unit') or 'EA').strip(),
                    delivery_date=dd,
                    processing_note=(it.get('processing_note') or '').strip(),
                    note=(it.get('note') or '').strip(),
                ))
                total += amt
            fo.total_amount = total
            fo.tax_amount = round(total * 0.1)

        _append_fo_history(fo, '가공발주 등록(모바일)', '')
        db.add(fo)
        db.flush()

        # 파일 업로드 (multipart)
        if is_multipart:
            for f in request.files.getlist('files'):
                if not f or not f.filename or not _allowed_file(f.filename):
                    continue
                content = f.read()
                if not content or len(content) > MAX_FILE_SIZE:
                    continue
                ext = f.filename.rsplit('.', 1)[1].lower()
                safe_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
                obj_path = f'storage/processing-orders/{fo.fo_no}/{safe_name}'
                if is_storage_enabled():
                    ok, _ = upload_bytes(obj_path, content, f.content_type or 'application/octet-stream')
                    if not ok:
                        continue
                rec = ProcessingOrderFile(
                    fo_id=fo.id, file_name=f.filename, file_path=obj_path,
                    file_size=len(content), file_type=ext,
                    is_reference=ext in ('jpg', 'jpeg', 'png'),
                    uploaded_by=user_id,
                )
                db.add(rec)
                db.flush()
                try:
                    _register_as_drawing(db, fo, rec)
                except Exception:
                    pass

        log_activity(db, '가공발주', 'create', f'{fo.fo_no} 등록 ({vendor.name})',
                     ref_type='ProcessingOrder', ref_id=fo.id, ref_label=fo.fo_no,
                     project_id=fo.project_id)
        db.commit()
        return jsonify(ok=True, fo_id=fo.id, fo_no=fo.fo_no)


@app_api_bp.route('/processing-orders/<int:fo_id>/edit', methods=['POST'])
@app_auth_required
def app_processing_order_edit(fo_id):
    """가공발주 수정 — JSON"""
    from routes.processing_order import _append_fo_history
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        fo = db.query(ProcessingOrder).get(fo_id)
        if not fo:
            return jsonify(ok=False, error='가공발주를 찾을 수 없습니다'), 404
        if data.get('fo_date'):
            try:
                fo.fo_date = datetime.date.fromisoformat(data['fo_date'])
            except Exception:
                pass
        if data.get('processing_type'):
            fo.processing_type = data['processing_type']
        fo.note = (data.get('note') or '').strip() or None

        db.query(ProcessingOrderItem).filter_by(fo_id=fo.id).delete()
        total = 0
        for it in (data.get('items') or []):
            name = (it.get('item_name') or '').strip()
            if not name:
                continue
            qty = float(it.get('quantity') or 0)
            price = float(it.get('unit_price') or 0)
            amt = qty * price
            dd = None
            if it.get('delivery_date'):
                try:
                    dd = datetime.date.fromisoformat(it['delivery_date'])
                except Exception:
                    pass
            db.add(ProcessingOrderItem(
                fo_id=fo.id,
                item_id=int(it['item_id']) if it.get('item_id') else None,
                item_name=name,
                item_spec=(it.get('item_spec') or '').strip(),
                quantity=qty, unit_price=price, amount=amt,
                unit=(it.get('unit') or 'EA').strip(),
                delivery_date=dd,
                processing_note=(it.get('processing_note') or '').strip(),
                note=(it.get('note') or '').strip(),
            ))
            total += amt
        fo.total_amount = total
        fo.tax_amount = round(total * 0.1)
        fo.updated_at = datetime.datetime.now()
        _append_fo_history(fo, '가공발주 수정(모바일)', '')
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/processing-orders/<int:fo_id>/upload', methods=['POST'])
@app_auth_required
def app_processing_order_upload(fo_id):
    """가공발주 파일 업로드"""
    from routes.processing_order import (
        _allowed_file, _register_as_drawing, _append_fo_history, MAX_FILE_SIZE,
    )
    from modules.storage_adapter import upload_bytes, is_storage_enabled
    from modules.models import ProcessingOrderFile

    user_id = request._app_user_id
    with get_db() as db:
        fo = db.query(ProcessingOrder).get(fo_id)
        if not fo:
            return jsonify(ok=False, error='가공발주를 찾을 수 없습니다'), 404
        if not is_storage_enabled():
            return jsonify(ok=False, error='Supabase Storage 미설정'), 500
        results = []
        for f in request.files.getlist('files'):
            if not f or not f.filename or not _allowed_file(f.filename):
                continue
            content = f.read()
            if len(content) > MAX_FILE_SIZE:
                continue
            ext = f.filename.rsplit('.', 1)[1].lower()
            safe_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
            obj_path = f'storage/processing-orders/{fo.fo_no}/{safe_name}'
            ok, msg = upload_bytes(obj_path, content, f.content_type or 'application/octet-stream')
            if not ok:
                continue
            rec = ProcessingOrderFile(
                fo_id=fo.id, file_name=f.filename, file_path=obj_path,
                file_size=len(content), file_type=ext,
                is_reference=ext in ('jpg', 'jpeg', 'png'),
                uploaded_by=user_id,
            )
            db.add(rec)
            db.flush()
            try:
                _register_as_drawing(db, fo, rec)
            except Exception:
                pass
            results.append({'id': rec.id, 'name': f.filename, 'ok': True})
        _append_fo_history(fo, f'파일 {len(results)}건 업로드(모바일)', '')
        db.commit()
        return jsonify(ok=True, results=results)


@app_api_bp.route('/processing-orders/<int:fo_id>/file/<int:fid>/toggle-reference', methods=['POST'])
@app_auth_required
def app_processing_order_toggle_reference(fo_id, fid):
    from modules.models import ProcessingOrderFile
    with get_db() as db:
        rec = db.query(ProcessingOrderFile).filter_by(id=fid, fo_id=fo_id).first()
        if not rec:
            return jsonify(ok=False, error='파일을 찾을 수 없습니다'), 404
        rec.is_reference = not rec.is_reference
        db.commit()
        return jsonify(ok=True, is_reference=rec.is_reference)


@app_api_bp.route('/processing-orders/<int:fo_id>/file/<int:fid>/delete', methods=['POST'])
@app_auth_required
def app_processing_order_file_delete(fo_id, fid):
    """가공발주 파일 삭제"""
    from routes.processing_order import _append_fo_history
    from modules.storage_adapter import delete_object
    from modules.models import ProcessingOrderFile, Drawing, DrawingVersion
    with get_db() as db:
        rec = db.query(ProcessingOrderFile).filter_by(id=fid, fo_id=fo_id).first()
        if not rec:
            return jsonify(ok=False, error='파일을 찾을 수 없습니다'), 404
        linked_ver = db.query(DrawingVersion).filter_by(dwg_path=rec.file_path).first()
        if linked_ver:
            drawing = db.query(Drawing).get(linked_ver.drawing_id)
            db.delete(linked_ver)
            if drawing:
                remaining = db.query(DrawingVersion).filter_by(drawing_id=drawing.id)\
                    .filter(DrawingVersion.id != linked_ver.id).count()
                if remaining == 0:
                    db.delete(drawing)
        try:
            delete_object(rec.file_path)
        except Exception:
            pass
        fname = rec.file_name
        db.delete(rec)
        fo = db.query(ProcessingOrder).get(fo_id)
        if fo:
            _append_fo_history(fo, f'파일 삭제: {fname}(모바일)', '')
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/processing-orders/<int:fo_id>/sync-production', methods=['POST'])
@app_auth_required
def app_processing_order_sync_production(fo_id):
    """가공발주 → 생산관리 연동"""
    from routes.processing_order import _append_fo_history
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(joinedload(ProcessingOrder.items)).get(fo_id)
        if not fo:
            return jsonify(ok=False, error='가공발주를 찾을 수 없습니다'), 404
        if not fo.contract_id:
            return jsonify(ok=False, error='계약 연결 필요'), 400
        linked = 0
        for item in fo.items:
            if item.material_order_id:
                continue
            mat = db.query(MaterialOrder).filter_by(contract_id=fo.contract_id, is_outsourcing=True)\
                .filter(MaterialOrder.material_name.ilike(f'%{item.item_name}%')).first()
            if mat:
                item.material_order_id = mat.id
                mat.outsourcing_status = fo.status if fo.status in ('가공중', '발주완료') else '가공중'
                mat.order_date = fo.fo_date
                linked += 1
        if linked:
            _append_fo_history(fo, f'생산관리 연동: {linked}건(모바일)', '')
        db.commit()
        return jsonify(ok=True, linked=linked)


# ============================================================
# ── 관리부 6개 메뉴 API 블록 끝 ──
# ============================================================


# ============================================================
# ── 조도검증 (Illuminance Verification) API ──
# ERP: routes/illuminance.py 로직 모바일 이식
# session.get('username') → User(id=user_id).username
# ============================================================

@app_api_bp.route('/illuminance')
@app_auth_required
def app_illuminance_list():
    """조도검증 프로젝트 목록"""
    from modules.models import IlluminanceProject
    with get_db() as db:
        projects = db.query(IlluminanceProject).options(
            joinedload(IlluminanceProject.areas),
        ).order_by(desc(IlluminanceProject.created_at)).all()

        result = []
        for p in projects:
            areas = p.areas or []
            measured_cnt = 0
            pass_cnt = 0
            fail_cnt = 0
            for a in areas:
                if a.measurements:
                    measured_cnt += 1
                    latest = a.latest_measurement
                    if latest and latest.ks_pass == 'PASS':
                        pass_cnt += 1
                    elif latest and latest.ks_pass == 'FAIL':
                        fail_cnt += 1
            result.append({
                'id': p.id,
                'project_name': p.project_name or '',
                'customer': p.customer or '',
                'location': p.location or '',
                'install_date': str(p.install_date) if p.install_date else '',
                'facility_type': p.facility_type or '',
                'status': p.status or 'design',
                'erp_project_id': p.erp_project_id,
                'area_count': len(areas),
                'measured_count': measured_cnt,
                'pass_count': pass_cnt,
                'fail_count': fail_cnt,
                'created_by': p.created_by or '',
                'created_at': str(p.created_at) if p.created_at else '',
            })
        return jsonify(ok=True, illuminance_projects=result)


@app_api_bp.route('/illuminance/<int:project_id>')
@app_auth_required
def app_illuminance_detail(project_id):
    """조도검증 프로젝트 상세 — 구역 요약 포함"""
    from modules.models import IlluminanceProject
    with get_db() as db:
        p = db.query(IlluminanceProject).options(
            joinedload(IlluminanceProject.areas),
        ).get(project_id)
        if not p:
            return jsonify(ok=False, error='프로젝트를 찾을 수 없습니다'), 404

        areas_out = []
        for a in sorted(p.areas, key=lambda x: x.area_index or 0):
            latest = a.latest_measurement
            areas_out.append({
                'id': a.id,
                'area_name': a.area_name or '',
                'area_index': a.area_index,
                'installation_height': a.installation_height,
                'lamp_type': a.lamp_type or '',
                'lamp_watt': a.lamp_watt,
                'lamp_qty': a.lamp_qty,
                'tower_qty': a.tower_qty,
                'design_eav': a.design_eav,
                'design_emin': a.design_emin,
                'design_emax': a.design_emax,
                'design_uo': a.design_uo,
                'design_ud': a.design_ud,
                'grid_rows': a.grid_rows,
                'grid_cols': a.grid_cols,
                'ks_eav_min': a.ks_eav_min,
                'ks_uo_min': a.ks_uo_min,
                'measurement_count': len(a.measurements) if a.measurements else 0,
                'latest_measure_date': str(latest.measure_date) if latest and latest.measure_date else '',
                'latest_measured_eav': latest.measured_eav if latest else None,
                'latest_measured_uo': latest.measured_uo if latest else None,
                'latest_ks_pass': latest.ks_pass if latest else None,
                'latest_eav_achievement': latest.eav_achievement if latest else None,
                'latest_uo_achievement': latest.uo_achievement if latest else None,
            })

        return jsonify(ok=True, project={
            'id': p.id,
            'project_name': p.project_name or '',
            'customer': p.customer or '',
            'location': p.location or '',
            'install_date': str(p.install_date) if p.install_date else '',
            'facility_type': p.facility_type or '',
            'status': p.status or 'design',
            'pdf_filename': p.pdf_filename or '',
            'notes': p.notes or '',
            'erp_project_id': p.erp_project_id,
            'created_by': p.created_by or '',
            'created_at': str(p.created_at) if p.created_at else '',
        }, areas=areas_out)


@app_api_bp.route('/illuminance/<int:project_id>/area/<int:area_id>')
@app_auth_required
def app_illuminance_area(project_id, area_id):
    """조도검증 구역 상세 — 격자/실측/KS 기준 포함"""
    from modules.models import IlluminanceProject, IlluminanceArea
    with get_db() as db:
        p = db.query(IlluminanceProject).get(project_id)
        a = db.query(IlluminanceArea).get(area_id)
        if not p or not a or a.project_id != project_id:
            return jsonify(ok=False, error='구역을 찾을 수 없습니다'), 404

        area_fixtures = []
        if a.fixtures:
            try:
                area_fixtures = json.loads(a.fixtures)
            except Exception:
                pass

        measurements = []
        for m in a.measurements:
            measurements.append({
                'id': m.id,
                'measure_date': str(m.measure_date) if m.measure_date else '',
                'measured_by': m.measured_by or '',
                'weather': m.weather or '',
                'instrument': m.instrument or '',
                'measured_eav': m.measured_eav,
                'measured_emin': m.measured_emin,
                'measured_emax': m.measured_emax,
                'measured_uo': m.measured_uo,
                'measured_ud': m.measured_ud,
                'measured_grid': m.measured_grid_parsed,
                'ks_pass': m.ks_pass or '',
                'eav_achievement': m.eav_achievement,
                'uo_achievement': m.uo_achievement,
                'notes': m.notes or '',
                'created_at': str(m.created_at) if m.created_at else '',
            })
        latest_grid = a.latest_measurement.measured_grid_parsed if a.latest_measurement else None

        return jsonify(ok=True,
                       project_id=project_id,
                       project_name=p.project_name or '',
                       facility_type=p.facility_type or '',
                       area={
                           'id': a.id,
                           'area_name': a.area_name or '',
                           'area_index': a.area_index,
                           'installation_height': a.installation_height,
                           'lamp_type': a.lamp_type or '',
                           'lamp_watt': a.lamp_watt,
                           'lamp_qty': a.lamp_qty,
                           'tower_qty': a.tower_qty,
                           'simulation_date': str(a.simulation_date) if a.simulation_date else '',
                           'design_eav': a.design_eav,
                           'design_emin': a.design_emin,
                           'design_emax': a.design_emax,
                           'design_uo': a.design_uo,
                           'design_ud': a.design_ud,
                           'maintenance_factor': a.maintenance_factor,
                           'total_flux': a.total_flux,
                           'total_power': a.total_power,
                           'power_per_area': a.power_per_area,
                           'grid_rows': a.grid_rows or 0,
                           'grid_cols': a.grid_cols or 0,
                           'x_labels': a.x_labels_parsed,
                           'y_labels': a.y_labels_parsed,
                           'design_grid': a.design_grid_parsed,
                           'ks_eav_min': a.ks_eav_min,
                           'ks_uo_min': a.ks_uo_min,
                           'ks_ud_min': a.ks_ud_min,
                           'fixtures': area_fixtures,
                           'latest_grid': latest_grid,
                       },
                       measurements=measurements)


@app_api_bp.route('/illuminance/<int:project_id>/area/<int:area_id>/measure', methods=['POST'])
@app_auth_required
def app_illuminance_save_measure(project_id, area_id):
    """실측값 저장 — 통계 자동 계산 + KS 판정"""
    from modules.models import IlluminanceProject, IlluminanceArea, IlluminanceMeasured
    from modules.services.illuminance_pdf_parser import judge_ks
    with get_db() as db:
        user = db.query(User).get(request._app_user_id)
        a = db.query(IlluminanceArea).get(area_id)
        if not a or a.project_id != project_id:
            return jsonify(ok=False, error='구역을 찾을 수 없습니다'), 404

        data = request.get_json(silent=True) or {}
        grid = data.get('grid_data')
        if not isinstance(grid, list):
            return jsonify(ok=False, error='grid_data 형식 오류'), 400

        flat = [v for row in grid for v in row if isinstance(v, (int, float))]
        if flat:
            eav = sum(flat) / len(flat)
            emin = min(flat)
            emax = max(flat)
            uo = emin / eav if eav else 0
            ud = emin / emax if emax else 0
        else:
            eav = emin = emax = uo = ud = None

        ks_pass = judge_ks(eav, uo, a.ks_eav_min, a.ks_uo_min)
        eav_ach = (eav / a.design_eav * 100) if (eav and a.design_eav) else None
        uo_ach = (uo / a.design_uo * 100) if (uo and a.design_uo) else None

        measure_date = _parse_date_safe(data.get('measure_date')) or datetime.date.today()

        m = IlluminanceMeasured(
            area_id=area_id,
            measure_date=measure_date,
            measured_by=(data.get('measured_by') or (user.full_name if user else '') or '').strip() or None,
            weather=(data.get('weather') or '').strip() or None,
            instrument=(data.get('instrument') or '').strip() or None,
            measured_eav=round(eav, 1) if eav else None,
            measured_emin=emin,
            measured_emax=emax,
            measured_uo=round(uo, 3) if uo else None,
            measured_ud=round(ud, 3) if ud else None,
            measured_grid=json.dumps(grid, ensure_ascii=False),
            ks_pass=ks_pass,
            eav_achievement=round(eav_ach, 1) if eav_ach else None,
            uo_achievement=round(uo_ach, 1) if uo_ach else None,
            notes=(data.get('notes') or '').strip() or None,
        )
        db.add(m)
        project = db.query(IlluminanceProject).get(project_id)
        if project and project.status == 'design':
            project.status = 'measured'
        db.commit()
        return jsonify(ok=True,
                       id=m.id,
                       ks_pass=ks_pass,
                       measured_eav=m.measured_eav,
                       measured_uo=m.measured_uo,
                       eav_achievement=m.eav_achievement,
                       uo_achievement=m.uo_achievement)


@app_api_bp.route('/illuminance/<int:project_id>/area/<int:area_id>/measure/<int:measure_id>/delete', methods=['POST'])
@app_auth_required
def app_illuminance_delete_measure(project_id, area_id, measure_id):
    from modules.models import IlluminanceMeasured
    with get_db() as db:
        m = db.query(IlluminanceMeasured).get(measure_id)
        if not m or m.area_id != area_id:
            return jsonify(ok=False, error='기록을 찾을 수 없습니다'), 404
        db.delete(m)
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/illuminance/<int:project_id>/area/<int:area_id>/edit-name', methods=['POST'])
@app_auth_required
def app_illuminance_edit_area_name(project_id, area_id):
    from modules.models import IlluminanceArea
    with get_db() as db:
        a = db.query(IlluminanceArea).get(area_id)
        if not a or a.project_id != project_id:
            return jsonify(ok=False, error='구역을 찾을 수 없습니다'), 404
        data = request.get_json(silent=True) or {}
        name = (data.get('area_name') or '').strip()
        if not name:
            return jsonify(ok=False, error='이름을 입력해주세요'), 400
        a.area_name = name
        db.commit()
        return jsonify(ok=True, area_name=name)


@app_api_bp.route('/illuminance/<int:project_id>/edit', methods=['POST'])
@app_auth_required
def app_illuminance_edit_project(project_id):
    from modules.models import IlluminanceProject
    with get_db() as db:
        p = db.query(IlluminanceProject).get(project_id)
        if not p:
            return jsonify(ok=False, error='프로젝트를 찾을 수 없습니다'), 404
        data = request.get_json(silent=True) or {}
        p.project_name = (data.get('project_name') or '').strip() or p.project_name
        p.customer = (data.get('customer') or '').strip() or None
        p.location = (data.get('location') or '').strip() or None
        if 'facility_type' in data:
            p.facility_type = (data.get('facility_type') or '').strip() or None
        install_date = _parse_date_safe(data.get('install_date'))
        if install_date:
            p.install_date = install_date
        if 'notes' in data:
            p.notes = (data.get('notes') or '').strip() or None
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/illuminance/<int:project_id>/delete', methods=['POST'])
@app_auth_required
def app_illuminance_delete_project(project_id):
    from modules.models import IlluminanceProject
    with get_db() as db:
        p = db.query(IlluminanceProject).get(project_id)
        if not p:
            return jsonify(ok=False, error='프로젝트를 찾을 수 없습니다'), 404
        db.delete(p)
        db.commit()
        return jsonify(ok=True)


def _parse_date_safe(val):
    if not val:
        return None
    try:
        return datetime.datetime.strptime(str(val)[:10], '%Y-%m-%d').date()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 발주/입고현황 (생산팀 통합뷰) — incoming_overview 라우트와 같은 집계 로직 재사용
# ─────────────────────────────────────────────────────────────
@app_api_bp.route('/incoming-overview')
@app_auth_required
def app_incoming_overview():
    """발주 품목별 입고 흐름 통합 — 모바일용 JSON"""
    from routes.incoming_overview import _build_dataset, STATUS_LABEL

    search = (request.args.get('search') or request.args.get('q') or '').strip()
    status_filter = (request.args.get('status') or 'all').strip()

    with get_db() as db:
        items, stats = _build_dataset(db, search=search, status_filter=status_filter)

    return jsonify(
        ok=True,
        items=items,
        stats=stats,
        status_labels=STATUS_LABEL,
    )


# ===================================================================
# 🚗 운행일지 (Vehicle Log)
# ===================================================================

@app_api_bp.route('/vehicle-logs/vehicles')
@app_auth_required
def app_vehicle_log_vehicles():
    """회사 차량 목록 + 각 차량의 직전 odometer"""
    from routes.vehicle_log import _get_company_vehicles, _get_last_odometer
    from modules.models import VehicleLog
    with get_db() as db:
        vehicles = _get_company_vehicles(db)
        result = []
        for v in vehicles:
            result.append({
                'name': v,
                'last_odometer': _get_last_odometer(db, v),
            })
        return jsonify(ok=True, vehicles=result)


@app_api_bp.route('/vehicle-logs')
@app_auth_required
def app_vehicle_logs():
    """운행일지 목록 — vehicle=차량명 / mine=1 본인 기록만"""
    from modules.models import VehicleLog
    mine = request.args.get('mine') == '1'
    vehicle = (request.args.get('vehicle') or '').strip()
    limit = int(request.args.get('limit') or 30)
    user_id = request._app_user_id
    with get_db() as db:
        q = db.query(VehicleLog)
        if mine:
            q = q.filter(VehicleLog.user_id == user_id)
        if vehicle:
            q = q.filter(VehicleLog.vehicle == vehicle)
        logs = q.order_by(desc(VehicleLog.use_date), desc(VehicleLog.id)).limit(limit).all()
        items = []
        for log in logs:
            items.append({
                'id': log.id,
                'use_date': log.use_date.strftime('%Y-%m-%d') if log.use_date else None,
                'vehicle': log.vehicle,
                'user_name': log.user_name,
                'user_department': log.user_department,
                'odometer_start': log.odometer_start,
                'odometer_end': log.odometer_end,
                'distance_km': log.distance_km,
                'fuel_amount': log.fuel_amount,
                'origin': log.origin,
                'destination': log.destination,
                'purpose': log.purpose,
                'has_receipt': bool(log.receipt_url),
                'is_mine': log.user_id == user_id,
            })
        return jsonify(ok=True, items=items)


@app_api_bp.route('/vehicle-logs/<int:log_id>')
@app_auth_required
def app_vehicle_log_detail(log_id):
    from modules.models import VehicleLog
    with get_db() as db:
        log = db.query(VehicleLog).get(log_id)
        if not log:
            return jsonify(ok=False, error='not_found'), 404
        return jsonify(ok=True, item={
            'id': log.id,
            'use_date': log.use_date.strftime('%Y-%m-%d') if log.use_date else None,
            'vehicle': log.vehicle,
            'user_id': log.user_id,
            'user_name': log.user_name,
            'user_department': log.user_department,
            'user_position': log.user_position,
            'odometer_start': log.odometer_start,
            'odometer_end': log.odometer_end,
            'distance_km': log.distance_km,
            'fuel_amount': log.fuel_amount,
            'origin': log.origin,
            'destination': log.destination,
            'purpose': log.purpose,
            'receipt_url': f'/vehicle-logs/{log.id}/receipt' if log.receipt_url else None,
            'is_mine': log.user_id == request._app_user_id,
        })


@app_api_bp.route('/vehicle-logs/create', methods=['POST'])
@app_auth_required
def app_vehicle_log_create():
    """운행일지 신규 등록 — multipart/form-data 또는 JSON"""
    import os
    from werkzeug.utils import secure_filename
    from modules.models import VehicleLog
    from routes.vehicle_log import _get_company_vehicles
    from modules.storage_adapter import upload_bytes

    if request.content_type and 'multipart/form-data' in request.content_type:
        src = request.form
    else:
        src = request.get_json(silent=True) or {}

    use_date_str = (src.get('use_date') or '').strip()
    vehicle = (src.get('vehicle') or '').strip()
    odo_start = src.get('odometer_start')
    odo_end = src.get('odometer_end')
    fuel = src.get('fuel_amount')
    origin = (src.get('origin') or '').strip()
    destination = (src.get('destination') or '').strip()
    purpose = (src.get('purpose') or '').strip()

    # 필수 검증
    if not vehicle:
        return jsonify(ok=False, error='차량을 선택해주세요'), 400
    if not odo_end:
        return jsonify(ok=False, error='주행 후 km을 입력해주세요'), 400
    if not origin or not destination or not purpose:
        return jsonify(ok=False, error='출발지/도착지/사용목적을 입력해주세요'), 400

    try:
        odometer_end = int(odo_end)
        odometer_start = int(odo_start) if odo_start not in (None, '') else None
        fuel_amount = int(fuel) if fuel not in (None, '') else None
    except (ValueError, TypeError):
        return jsonify(ok=False, error='주행거리/주유금액은 숫자여야 합니다'), 400

    if odometer_start is not None and odometer_end < odometer_start:
        return jsonify(ok=False, error='주행 후 km이 주행 전보다 작습니다'), 400

    distance_km = (odometer_end - odometer_start) if odometer_start is not None else 0
    if distance_km < 0:
        distance_km = 0

    try:
        use_date = datetime.date.fromisoformat(use_date_str) if use_date_str else datetime.date.today()
    except ValueError:
        use_date = datetime.date.today()

    user_id = request._app_user_id
    with get_db() as db:
        # 차량 화이트리스트 검증
        if vehicle not in _get_company_vehicles(db):
            return jsonify(ok=False, error='허용되지 않은 차량입니다'), 400

        user = db.query(User).get(user_id)
        log = VehicleLog(
            use_date=use_date,
            vehicle=vehicle,
            user_id=user_id,
            user_name=user.full_name if user else '',
            user_department=user.user_group if user else None,
            user_position=getattr(user, 'position', None) if user else None,
            odometer_start=odometer_start,
            odometer_end=odometer_end,
            distance_km=distance_km,
            fuel_amount=fuel_amount,
            origin=origin,
            destination=destination,
            purpose=purpose,
        )
        db.add(log)
        db.flush()  # log.id 확보

        # 영수증 업로드
        upload = request.files.get('receipt') if request.files else None
        if upload and upload.filename:
            data = upload.read()
            if data and len(data) <= 5 * 1024 * 1024:
                ext = os.path.splitext(secure_filename(upload.filename))[1].lower() or '.jpg'
                if ext.lstrip('.') in {'jpg', 'jpeg', 'png', 'webp'}:
                    storage_path = f"documents/vehicle_logs/{log.id}{ext}"
                    ok, err = upload_bytes(storage_path, data,
                                            upload.mimetype or f'image/{ext.lstrip(".")}')
                    if ok:
                        log.receipt_url = storage_path

        log_activity(db, 'vehicle_log', 'create',
                     f"운행일지 등록 #{log.id} ({log.vehicle} {log.use_date})",
                     ref_type='vehicle_log', ref_id=log.id,
                     ref_label=f"{log.vehicle} {log.use_date}")
        db.commit()
        return jsonify(ok=True, id=log.id, distance_km=log.distance_km)


@app_api_bp.route('/vehicle-logs/<int:log_id>/delete', methods=['POST'])
@app_auth_required
def app_vehicle_log_delete(log_id):
    from modules.models import VehicleLog
    from modules.storage_adapter import delete_object
    user_id = request._app_user_id
    with get_db() as db:
        log = db.query(VehicleLog).get(log_id)
        if not log:
            return jsonify(ok=False, error='not_found'), 404
        # 본인 또는 admin
        user = db.query(User).get(user_id)
        if log.user_id != user_id and (not user or user.role != 'admin'):
            return jsonify(ok=False, error='forbidden'), 403

        if log.receipt_url:
            try:
                delete_object(log.receipt_url)
            except Exception:
                pass
        log_activity(db, 'vehicle_log', 'delete',
                     f"운행일지 삭제 #{log.id} ({log.vehicle} {log.use_date})",
                     ref_type='vehicle_log', ref_id=log.id)
        db.delete(log)
        db.commit()
        return jsonify(ok=True)


@app_api_bp.route('/vehicle-logs/<int:log_id>/receipt')
def app_vehicle_log_receipt(log_id):
    """운행일지 영수증 뷰어 — 토큰 쿼리 인증"""
    import os as _os
    from flask import Response, abort
    from modules.storage_adapter import download_bytes
    from modules.models import VehicleLog

    if not _verify_token_from_request():
        abort(401)

    with get_db() as db:
        log = db.query(VehicleLog).get(log_id)
        if not log or not log.receipt_url:
            abort(404)
        data = download_bytes(log.receipt_url)
        if not data:
            abort(404)
        ext = _os.path.splitext(log.receipt_url)[1].lower().lstrip('.')
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'png': 'image/png', 'webp': 'image/webp'}
        return Response(data, mimetype=mime_map.get(ext, 'application/octet-stream'))


# ═══════════════════════════════════════════════════════════════
# 전자결재 (모바일)
# ═══════════════════════════════════════════════════════════════

def _ea_doc_brief(doc, uid):
    """목록용 문서 요약 dict"""
    cur = next((s for s in doc.steps if s.status == 'current'), None)
    return {
        'id': doc.id,
        'doc_no': doc.doc_no or '',
        'form_key': doc.form_key,
        'form_name': doc.form_name,
        'title': doc.title,
        'drafter_name': doc.drafter_name,
        'drafter_position': doc.drafter_position or '',
        'status': doc.status,
        'status_label': doc.status_label,
        'my_turn': bool(cur and cur.approver_id == uid),
        'current_approver': cur.approver_name if cur else '',
        'date': (doc.submitted_at or doc.created_at).strftime('%Y-%m-%d') if (doc.submitted_at or doc.created_at) else '',
        'step_count': len(doc.steps),
        'approved_steps': sum(1 for s in doc.steps if s.status == 'approved'),
    }


@app_api_bp.route('/approvals')
@app_auth_required
def app_approvals():
    """결재 목록 — tab: inbox/drafted/done"""
    from modules.models import ApprovalDocument, ApprovalStep, ApprovalReference
    from modules.services import approval_service as svc
    from sqlalchemy import or_
    uid = request._app_user_id
    tab = request.args.get('tab', 'all')
    with get_db() as db:
        svc.seed_form_templates(db); db.commit()
        base = db.query(ApprovalDocument)
        if tab == 'all':
            # 권한 내 모든 문서: 내가 기안 OR 결재선 포함 OR 참조/수신
            docs = (base.filter(or_(
                        ApprovalDocument.drafter_id == uid,
                        ApprovalDocument.steps.any(ApprovalStep.approver_id == uid),
                        ApprovalDocument.references.any(ApprovalReference.user_id == uid)))
                    .order_by(ApprovalDocument.created_at.desc()).all())
        elif tab == 'inbox':
            docs = (base.join(ApprovalStep)
                    .filter(ApprovalDocument.status == 'pending',
                            ApprovalStep.approver_id == uid,
                            ApprovalStep.status == 'current')
                    .order_by(ApprovalDocument.submitted_at.desc()).all())
        elif tab == 'progress':
            # 내가 결재선에 있는 진행중 문서 (내 차례 전/후 포함)
            docs = (base.filter(ApprovalDocument.status == 'pending',
                                ApprovalDocument.steps.any(ApprovalStep.approver_id == uid))
                    .order_by(ApprovalDocument.submitted_at.desc()).all())
        elif tab == 'drafted':
            docs = (base.filter(ApprovalDocument.drafter_id == uid)
                    .order_by(ApprovalDocument.created_at.desc()).all())
        elif tab == 'referenced':
            docs = (base.join(ApprovalReference)
                    .filter(ApprovalReference.user_id == uid)
                    .order_by(ApprovalDocument.submitted_at.desc().nullslast()).all())
        else:  # done
            docs = (base.join(ApprovalStep)
                    .filter(ApprovalDocument.status.in_(['approved', 'rejected']),
                            ApprovalStep.approver_id == uid)
                    .order_by(ApprovalDocument.completed_at.desc().nullslast()).distinct().all())
        inbox_count = (db.query(ApprovalDocument).join(ApprovalStep)
                       .filter(ApprovalDocument.status == 'pending',
                               ApprovalStep.approver_id == uid,
                               ApprovalStep.status == 'current').count())
        return jsonify(ok=True, approvals=[_ea_doc_brief(d, uid) for d in docs],
                       inbox_count=inbox_count, tab=tab)


@app_api_bp.route('/approvals/forms')
@app_auth_required
def app_approval_forms():
    """결재 양식 목록 + 양식별 기본 결재선(현재 사용자 기준)"""
    from modules.models import User
    from modules.services import approval_service as svc
    uid = request._app_user_id
    with get_db() as db:
        svc.seed_form_templates(db); db.commit()
        me = db.query(User).get(uid)
        forms = svc.get_active_forms(db)
        out = []
        for f in forms:
            line = svc.resolve_default_line(db, me, f.default_line)
            refs = [{'id': r.id, 'name': r.full_name, 'position': r.position or ''}
                    for r in svc.resolve_default_refs(db, f.form_key) if r.id != me.id]
            out.append({
                'form_key': f.form_key, 'name': f.name, 'icon': f.icon or '📄',
                'description': f.description or '', 'fields': f.field_schema or [],
                'default_line': line, 'default_refs': refs,
            })
        # 결재자 선택용 사용자 목록
        users = (db.query(User).filter(User.is_active.is_(True), User.user_group != '최고관리자')
                 .order_by(User.user_group, User.full_name).all())
        user_list = [{'id': u.id, 'name': u.full_name, 'position': u.position or '',
                      'dept': u.user_group or ''} for u in users]
        leave_balance = None
        try:
            from modules.services import hr_service
            _s = hr_service.leave_summary(db, me)
            leave_balance = {'granted': _s['granted'], 'used': _s['used'],
                             'adjust': _s['adjust'], 'remaining': _s['remaining']}
        except Exception:
            pass
        holidays = []
        try:
            from modules.services import holiday_service
            _y = datetime.date.today().year
            holidays = holiday_service.holiday_list([_y, _y + 1])
        except Exception:
            pass
        return jsonify(ok=True, forms=out, users=user_list,
                       leave_balance=leave_balance, holidays=holidays)


@app_api_bp.route('/approvals/<int:doc_id>')
@app_auth_required
def app_approval_detail(doc_id):
    from modules.models import ApprovalDocument, ApprovalFormTemplate
    uid = request._app_user_id
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            return jsonify(ok=False, error='문서를 찾을 수 없습니다'), 404
        # 열람권한
        allowed = (doc.drafter_id == uid or any(s.approver_id == uid for s in doc.steps)
                   or any(r.user_id == uid for r in doc.references))
        if not allowed:
            return jsonify(ok=False, error='열람 권한이 없습니다'), 403
        form = db.query(ApprovalFormTemplate).filter_by(form_key=doc.form_key).first()
        my_step = next((s for s in doc.steps if s.approver_id == uid and s.status == 'current'), None)
        fields = []
        for fld in (form.field_schema if form else []):
            if fld.get('type') == 'lineitems':
                fields.append({'label': fld['label'], 'type': 'lineitems',
                               'columns': fld.get('columns', []),
                               'rows': (doc.form_data or {}).get(fld['key']) or []})
            else:
                v = (doc.form_data or {}).get(fld['key'], '')
                fields.append({'label': fld['label'], 'value': v, 'suffix': fld.get('suffix', '')})
        return jsonify(ok=True, doc={
            'amount': int(doc.amount) if doc.amount else None,
            'attachments': [{'id': a.id, 'name': a.filename} for a in doc.attachments],
            'id': doc.id, 'doc_no': doc.doc_no or '', 'form_name': doc.form_name,
            'title': doc.title, 'status': doc.status, 'status_label': doc.status_label,
            'drafter_name': doc.drafter_name, 'drafter_position': doc.drafter_position or '',
            'drafter_dept': doc.drafter_dept or '',
            'date': (doc.submitted_at or doc.created_at).strftime('%Y-%m-%d %H:%M') if (doc.submitted_at or doc.created_at) else '',
            'content': doc.content or '',
            'fields': fields,
            'steps': [{'order': s.step_order, 'name': s.approver_name, 'position': s.approver_position or '',
                       'role': s.role_label, 'status': s.status, 'status_label': s.status_label,
                       'comment': s.comment or '',
                       'acted_at': s.acted_at.strftime('%m-%d %H:%M') if s.acted_at else ''} for s in doc.steps],
            'references': [{'name': r.user_name, 'type': r.ref_label} for r in doc.references],
            'my_turn': bool(my_step),
            'can_cancel': doc.drafter_id == uid and doc.status == 'pending' and not any(s.status == 'approved' for s in doc.steps),
        })


@app_api_bp.route('/approvals', methods=['POST'])
@app_auth_required
def app_approval_create():
    """기안 작성 + 즉시 상신 (모바일 1탭 원칙)"""
    from modules.models import User, ApprovalDocument, ApprovalFormTemplate, ApprovalStep
    from modules.services import approval_service as svc
    uid = request._app_user_id
    data = request.get_json(silent=True) or {}
    form_key = (data.get('form_key') or '').strip()
    title = (data.get('title') or '').strip()
    form_data = data.get('form_data') or {}
    content = (data.get('content') or '').strip()
    approver_ids = data.get('approver_ids') or []  # 비면 기본 결재선 사용
    with get_db() as db:
        me = db.query(User).get(uid)
        form = db.query(ApprovalFormTemplate).filter_by(form_key=form_key, is_active=True).first()
        if not form:
            return jsonify(ok=False, error='양식을 찾을 수 없습니다'), 400
        if not title:
            return jsonify(ok=False, error='제목을 입력하세요'), 400

        # 라인아이템(지출명세 등) 합계 계산 → amount
        for field in (form.field_schema or []):
            if field.get('type') == 'lineitems':
                rows = form_data.get(field['key']) or []
                total = 0
                clean = []
                for r in rows:
                    if not any((str(v or '').strip()) for v in r.values()):
                        continue
                    try:
                        total += int(str(r.get('amount', '') or '0').replace(',', '') or 0)
                    except ValueError:
                        pass
                    clean.append(r)
                form_data[field['key']] = clean
                form_data['amount'] = total

        amount = None
        if form.amount_field and form_data.get(form.amount_field):
            try:
                amount = int(str(form_data[form.amount_field]).replace(',', ''))
            except ValueError:
                pass

        doc = ApprovalDocument(
            form_key=form.form_key, form_name=form.name, title=title,
            drafter_id=me.id, drafter_name=me.full_name, drafter_dept=me.user_group,
            drafter_position=me.position, form_data=form_data, content=content,
            amount=amount, status='draft')
        db.add(doc); db.flush()

        # 결재선: 지정값 우선, 없으면 기본 결재선
        if approver_ids:
            order = 1
            seen = set()
            for aid in approver_ids:
                try:
                    aid = int(aid)
                except (ValueError, TypeError):
                    continue
                if aid in seen or aid == me.id:
                    continue
                u = db.query(User).get(aid)
                if not u:
                    continue
                seen.add(aid)
                doc.steps.append(ApprovalStep(step_order=order, approver_id=u.id,
                    approver_name=u.full_name, approver_position=u.position,
                    approver_dept=u.user_group, role='approval', status='waiting'))
                order += 1
        else:
            for i, s in enumerate(svc.resolve_default_line(db, me, form.default_line), 1):
                doc.steps.append(ApprovalStep(step_order=i, status='waiting', **s))

        # 양식별 기본 참조자 (휴가/지출 → 서은미 과장)
        from modules.models import ApprovalReference
        ref_seen = set()
        for ru in svc.resolve_default_refs(db, form.form_key):
            if ru.id == me.id or ru.id in ref_seen:
                continue
            ref_seen.add(ru.id)
            doc.references.append(ApprovalReference(
                user_id=ru.id, user_name=ru.full_name, ref_type='reference'))
        db.flush()

        try:
            svc.submit_document(db, doc)
        except ValueError as e:
            db.rollback()
            return jsonify(ok=False, error=str(e)), 400
        log_activity(db, 'approval', 'submit', f'[{doc.doc_no}] {doc.title} 상신',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.commit()
        return jsonify(ok=True, doc_id=doc.id, doc_no=doc.doc_no)


@app_api_bp.route('/approvals/<int:doc_id>/approve', methods=['POST'])
@app_auth_required
def app_approval_approve(doc_id):
    from modules.models import ApprovalDocument
    from modules.services import approval_service as svc
    uid = request._app_user_id
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            return jsonify(ok=False, error='문서를 찾을 수 없습니다'), 404
        step = next((s for s in doc.steps if s.approver_id == uid and s.status == 'current'), None)
        if not step:
            return jsonify(ok=False, error='현재 결재 차례가 아닙니다'), 400
        try:
            svc.approve_step(db, doc, step, (data.get('comment') or '').strip())
        except ValueError as e:
            db.rollback()
            return jsonify(ok=False, error=str(e)), 400
        log_activity(db, 'approval', 'approve', f'[{doc.doc_no}] {doc.title} 승인',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.commit()
        return jsonify(ok=True, status=doc.status)


@app_api_bp.route('/approvals/<int:doc_id>/reject', methods=['POST'])
@app_auth_required
def app_approval_reject(doc_id):
    from modules.models import ApprovalDocument
    from modules.services import approval_service as svc
    uid = request._app_user_id
    data = request.get_json(silent=True) or {}
    comment = (data.get('comment') or '').strip()
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            return jsonify(ok=False, error='문서를 찾을 수 없습니다'), 404
        step = next((s for s in doc.steps if s.approver_id == uid and s.status == 'current'), None)
        if not step:
            return jsonify(ok=False, error='현재 결재 차례가 아닙니다'), 400
        if not comment:
            return jsonify(ok=False, error='반려 사유를 입력하세요'), 400
        try:
            svc.reject_step(db, doc, step, comment)
        except ValueError as e:
            db.rollback()
            return jsonify(ok=False, error=str(e)), 400
        log_activity(db, 'approval', 'reject', f'[{doc.doc_no}] {doc.title} 반려',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.commit()
        return jsonify(ok=True, status=doc.status)


@app_api_bp.route('/approvals/<int:doc_id>/cancel', methods=['POST'])
@app_auth_required
def app_approval_cancel(doc_id):
    from modules.models import ApprovalDocument
    from modules.services import approval_service as svc
    uid = request._app_user_id
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc or doc.drafter_id != uid:
            return jsonify(ok=False, error='권한이 없습니다'), 403
        try:
            svc.cancel_document(db, doc)
        except ValueError as e:
            db.rollback()
            return jsonify(ok=False, error=str(e)), 400
        db.commit()
        return jsonify(ok=True, status=doc.status)


@app_api_bp.route('/approvals/<int:doc_id>/attachment', methods=['POST'])
@app_auth_required
def app_approval_attachment(doc_id):
    """모바일 결재 첨부(증빙) 업로드 — multipart file=<...>."""
    import os as _o
    from werkzeug.utils import secure_filename as _sf
    from modules.models import ApprovalDocument, ApprovalAttachment
    from modules.storage_adapter import upload_bytes as _upload
    _ALLOWED = {'pdf', 'jpg', 'jpeg', 'png', 'webp', 'xlsx', 'xls', 'docx', 'doc', 'hwp', 'hwpx', 'zip'}
    uid = request._app_user_id
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            return jsonify(ok=False, error='문서를 찾을 수 없습니다'), 404
        if doc.drafter_id != uid:
            return jsonify(ok=False, error='권한이 없습니다'), 403
        if doc.status not in ('draft', 'pending'):
            return jsonify(ok=False, error='첨부할 수 없는 상태입니다'), 400
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify(ok=False, error='파일이 없습니다'), 400
        data = f.read()
        if not data or len(data) > 20 * 1024 * 1024:
            return jsonify(ok=False, error='20MB 이하만 가능합니다'), 400
        fname = _sf(f.filename) or 'file'
        ext = _o.path.splitext(fname)[1].lstrip('.').lower()
        if ext not in _ALLOWED:
            return jsonify(ok=False, error='허용되지 않는 형식입니다'), 400
        idx = len(doc.attachments) + 1
        path = f"documents/approval/{doc.id}/{idx}_{fname}"
        ok, err = _upload(path, data, f.mimetype or 'application/octet-stream')
        if not ok:
            return jsonify(ok=False, error=err), 500
        db.add(ApprovalAttachment(document_id=doc.id, filename=f.filename,
                                  storage_path=path, content_type=f.mimetype, size=len(data)))
        db.commit()
        return jsonify(ok=True)
