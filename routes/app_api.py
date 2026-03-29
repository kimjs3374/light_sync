"""
모바일 앱 전용 JSON API
- 기존 웹 화면에 영향 없음
- /api/app/ 접두사
- 토큰 인증 (앱용)
"""
import datetime
import hashlib
import hmac
import json
import time
import bcrypt
from flask import Blueprint, jsonify, request, session, make_response, current_app
from functools import wraps
from modules.db_context import get_db
from modules.contract_filters import active_contract_filter
from modules.models import (
    User, GroupPermission, UserPriorityPermission, Project, HistoryLog,
    Notification, G2bProcurement, Contract, ContractItem,
    PurchaseOrder, PurchaseOrderItem, ActivityLog,
    Delivery, MaterialOrder, Receiving, ReceivingPhotoPost,
    Item, Vendor, Quotation, WarrantyCase, Warranty,
)
from config import MENU_REGISTRY, COMMON_MENU_KEYS
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

app_api_bp = Blueprint('app_api', __name__, url_prefix='/api/app')


# ── 토큰 유틸 ──

def _get_secret():
    return current_app.config.get('SECRET_KEY', 'fallback-secret')


def _make_token(user_id):
    """user_id + 만료시각을 HMAC 서명"""
    expires = int(time.time()) + 8 * 3600  # 8시간
    payload = f'{user_id}:{expires}'
    sig = hmac.new(_get_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f'{payload}:{sig}'


def _verify_token(token):
    """토큰 검증 → user_id 반환, 실패 시 None"""
    try:
        parts = token.split(':')
        if len(parts) != 3:
            return None
        user_id, expires, sig = int(parts[0]), int(parts[1]), parts[2]
        if time.time() > expires:
            return None
        expected = hmac.new(_get_secret().encode(), f'{user_id}:{expires}'.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id
    except Exception:
        return None


def app_auth_required(f):
    """앱 토큰 인증 데코레이터"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ok=False, error='로그인이 필요합니다'), 401
        token = auth_header[7:]
        user_id = _verify_token(token)
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
    user_id = _verify_token(token)
    if not user_id:
        return redirect('/login')
    with get_db() as db:
        user = db.query(User).get(user_id)
        if not user or not user.is_approved:
            return redirect('/login')
        group_data = db.query(GroupPermission).filter(GroupPermission.group_name == user.user_group).first()
        if user.role == 'admin':
            allowed_menus = [k for k in MENU_REGISTRY if k not in COMMON_MENU_KEYS]
            writable_menus = list(allowed_menus)
            hide_financial = False
        else:
            perm_map = {}
            if group_data and group_data.allowed_menus:
                for entry in group_data.allowed_menus.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if ':' in entry:
                        key, perm = entry.rsplit(':', 1)
                    else:
                        key, perm = entry, 'rw'
                    perm_map[key] = perm
            if user.extra_menus:
                for entry in user.extra_menus.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if ':' in entry:
                        key, perm = entry.rsplit(':', 1)
                    else:
                        key, perm = entry, 'rw'
                    perm_map[key] = perm
            allowed_menus = list(perm_map.keys())
            writable_menus = [k for k, v in perm_map.items() if v == 'rw']
            hide_financial = bool(group_data and getattr(group_data, 'hide_financial', False))
            if hasattr(user, 'hide_financial_override') and user.hide_financial_override is not None:
                hide_financial = user.hide_financial_override
        can_manage_priority = bool(
            user.role == 'admin'
            or db.query(UserPriorityPermission).filter(
                UserPriorityPermission.user_id == user.id,
                UserPriorityPermission.is_active.is_(True)
            ).first()
        )
        session.update({
            'user_id': user.id, 'username': user.username, 'full_name': user.full_name,
            'user_group': user.user_group, 'role': user.role, 'position': user.position or '',
            'allowed_menus': allowed_menus, 'writable_menus': writable_menus,
            'hide_financial': hide_financial,
            'can_approve_delete': bool(user.role == 'admin' or user.can_approve_delete),
            'can_manage_priority': can_manage_priority,
        })
    return redirect(next_url)


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

        # 권한 계산
        group_data = db.query(GroupPermission).filter(GroupPermission.group_name == user.user_group).first()
        if user.role == 'admin':
            allowed_menus = [k for k in MENU_REGISTRY if k not in COMMON_MENU_KEYS]
            writable_menus = list(allowed_menus)
            hide_financial = False
        else:
            perm_map = {}
            if group_data and group_data.allowed_menus:
                for entry in group_data.allowed_menus.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if ':' in entry:
                        key, perm = entry.rsplit(':', 1)
                    else:
                        key, perm = entry, 'rw'
                    perm_map[key] = perm
            if user.extra_menus:
                for entry in user.extra_menus.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if ':' in entry:
                        key, perm = entry.rsplit(':', 1)
                    else:
                        key, perm = entry, 'rw'
                    perm_map[key] = perm
            allowed_menus = list(perm_map.keys())
            writable_menus = [k for k, v in perm_map.items() if v == 'rw']
            hide_financial = bool(group_data and getattr(group_data, 'hide_financial', False))
            if hasattr(user, 'hide_financial_override') and user.hide_financial_override is not None:
                hide_financial = user.hide_financial_override

        token = _make_token(user.id)

        return jsonify(ok=True, token=token, user={
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'group': user.user_group,
            'role': user.role,
            'position': user.position or '',
            'allowed_menus': allowed_menus,
            'writable_menus': writable_menus,
            'hide_financial': hide_financial,
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
    """현장 상세 — 계약 + 히스토리"""
    with get_db() as db:
        project = db.query(Project).get(project_id)
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
            # G2B 조달내역에서 발주기관, 금액 가져오기
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

        # 첫 번째 계약에서 계약명 가져오기
        first_contract = db.query(Contract).filter(Contract.project_id == project_id).first()

        return jsonify(ok=True,
            project={
                'id': project.id,
                'name': project.temp_name or '',
                'short_name': project.short_name or '',
                'project_no': project.project_no or '',
                'status': project.status or '',
                'address': project.site_address or '',
                'contract_name': (first_contract.contract_name if first_contract else '') or '',
                'is_contracted': bool(project.is_contracted),
            },
            contracts=contract_list,
            history=history,
        )


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
        user_name = get_user_display_name(user)
        append_history_log(db, project_id, user_name, content, log_scope=scope, user_id=user_id)
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
            photos = []
            try:
                photos = json.loads(post.photos_json or '[]')
            except Exception:
                pass
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
