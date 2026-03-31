"""공구관리 라우트 — 불출/반납 추적 + 현재 위치 관리"""
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy import func, desc
from sqlalchemy.orm import joinedload
from modules.auth_decorators import menu_required
from modules.db_context import get_db
from modules.utils import safe_int
from modules.pagination import make_pagination
from modules.activity import log_activity
from modules.models import Tool, ToolCheckout, User, TOOL_STATUS_CHOICES

tools_bp = Blueprint("tools", __name__)


# ── 목록 ──────────────────────────────────────────────
@tools_bp.route('/tools')
@menu_required('tools')
def tool_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 50
    search = request.args.get('search', '').strip()
    team_filter = request.args.get('team', '').strip()
    status_filter = request.args.get('status', '').strip()

    with get_db() as db:
        query = db.query(Tool).order_by(Tool.team, Tool.tool_name)
        if search:
            query = query.filter(Tool.tool_name.ilike(f'%{search}%'))
        if team_filter:
            query = query.filter(Tool.team == team_filter)
        if status_filter:
            query = query.filter(Tool.status == status_filter)

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        tools = query.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

        # 통계
        stats = {
            'total': db.query(Tool).count(),
            'in_use': db.query(Tool).filter(Tool.status == '사용중').count(),
            'available': db.query(Tool).filter(Tool.status == '보관중').count(),
            'checkout_active': db.query(ToolCheckout).filter(ToolCheckout.status == '불출').count(),
        }

        # 팀 목록 (필터용)
        teams = [r[0] for r in db.query(Tool.team).distinct().filter(Tool.team.isnot(None)).order_by(Tool.team).all()]

        return render_template('tools_list.html',
                               tools=tools,
                               pagination=pagination,
                               stats=stats,
                               teams=teams,
                               status_choices=TOOL_STATUS_CHOICES,
                               filters={'search': search, 'team': team_filter, 'status': status_filter})


# ── 상세 ──────────────────────────────────────────────
@tools_bp.route('/tools/<int:tool_id>')
@menu_required('tools')
def tool_detail(tool_id):
    with get_db() as db:
        tool = db.query(Tool).options(
            joinedload(Tool.checkouts)
        ).get(tool_id)
        if not tool:
            flash('공구 정보를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('tools.tool_list'))

        # 현재 사용중인 불출건
        active_checkouts = [c for c in tool.checkouts if c.status == '불출']
        # 최근 이력 (최근 20건)
        history = tool.checkouts[:20]

        users = db.query(User).filter(
            User.is_active.is_(True),
            User.is_approved.is_(True)
        ).order_by(User.full_name).all()

        return render_template('tool_detail.html',
                               tool=tool,
                               active_checkouts=active_checkouts,
                               history=history,
                               users=users)


# ── 공구 등록 ─────────────────────────────────────────
@tools_bp.route('/tools/create', methods=['POST'])
@menu_required('tools', write=True)
def tool_create():
    name = request.form.get('tool_name', '').strip()
    if not name:
        flash('공구명을 입력해주세요.', 'warning')
        return redirect(url_for('tools.tool_list'))

    with get_db() as db:
        tool = Tool(
            tool_name=name,
            category=request.form.get('category', '전동공구').strip(),
            team=request.form.get('team', '').strip() or None,
            total_qty=safe_int(request.form.get('total_qty'), 1),
            available_qty=safe_int(request.form.get('total_qty'), 1),
            current_location=request.form.get('current_location', '사무실').strip(),
            note=request.form.get('note', '').strip() or None,
        )
        db.add(tool)
        db.flush()
        log_activity(db, '공구관리', 'create',
                     f'공구 등록: {tool.tool_name} ({tool.team or "미지정"})',
                     ref_type='Tool', ref_id=tool.id, ref_label=tool.tool_name)
        db.commit()
        flash(f'{tool.tool_name} 등록 완료', 'success')
    return redirect(url_for('tools.tool_list'))


# ── 공구 수정 ─────────────────────────────────────────
@tools_bp.route('/tools/<int:tool_id>/edit', methods=['POST'])
@menu_required('tools', write=True)
def tool_edit(tool_id):
    with get_db() as db:
        tool = db.query(Tool).get(tool_id)
        if not tool:
            flash('공구를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('tools.tool_list'))

        tool.tool_name = request.form.get('tool_name', tool.tool_name).strip()
        tool.category = request.form.get('category', tool.category).strip()
        tool.team = request.form.get('team', '').strip() or None
        tool.total_qty = safe_int(request.form.get('total_qty'), tool.total_qty)
        tool.current_location = request.form.get('current_location', tool.current_location).strip()
        tool.note = request.form.get('note', '').strip() or None

        log_activity(db, '공구관리', 'update',
                     f'공구 수정: {tool.tool_name}',
                     ref_type='Tool', ref_id=tool.id, ref_label=tool.tool_name)
        db.commit()
        flash('공구 정보가 수정되었습니다.', 'success')
    return redirect(url_for('tools.tool_detail', tool_id=tool_id))


# ── 공구 삭제 ─────────────────────────────────────────
@tools_bp.route('/tools/<int:tool_id>/delete', methods=['POST'])
@menu_required('tools', write=True)
def tool_delete(tool_id):
    with get_db() as db:
        tool = db.query(Tool).get(tool_id)
        if tool:
            log_activity(db, '공구관리', 'delete',
                         f'공구 삭제: {tool.tool_name}',
                         ref_type='Tool', ref_id=tool.id, ref_label=tool.tool_name)
            db.delete(tool)
            db.commit()
            flash('공구가 삭제되었습니다.', 'success')
    return redirect(url_for('tools.tool_list'))


# ── 불출 ──────────────────────────────────────────────
@tools_bp.route('/tools/<int:tool_id>/checkout', methods=['POST'])
@menu_required('tools', write=True)
def tool_checkout(tool_id):
    with get_db() as db:
        tool = db.query(Tool).get(tool_id)
        if not tool:
            flash('공구를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('tools.tool_list'))

        if tool.available_qty <= 0:
            flash('가용 수량이 없습니다.', 'warning')
            return redirect(url_for('tools.tool_detail', tool_id=tool_id))

        user_id = safe_int(request.form.get('user_id'))
        user_name = request.form.get('user_name', '').strip()
        purpose = request.form.get('purpose', '').strip()
        location = request.form.get('location', '').strip()

        # 사용자 선택 시 이름 자동 세팅
        if user_id:
            user = db.query(User).get(user_id)
            if user:
                user_name = user.full_name

        if not user_name:
            flash('불출자를 선택해주세요.', 'warning')
            return redirect(url_for('tools.tool_detail', tool_id=tool_id))

        # 불출일시 파싱
        checkout_dt_str = request.form.get('checkout_at', '').strip()
        if checkout_dt_str:
            try:
                checkout_dt = datetime.datetime.strptime(checkout_dt_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                checkout_dt = datetime.datetime.now()
        else:
            checkout_dt = datetime.datetime.now()

        # 반납예정일 파싱
        expected_str = request.form.get('expected_return_at', '').strip()
        expected_dt = None
        if expected_str:
            try:
                expected_dt = datetime.datetime.strptime(expected_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                pass

        checkout = ToolCheckout(
            tool_id=tool.id,
            checkout_user_id=user_id if user_id else None,
            checkout_user_name=user_name,
            purpose=purpose or None,
            location=location or None,
            checkout_at=checkout_dt,
            expected_return_at=expected_dt,
            status='불출',
        )
        db.add(checkout)

        # 가용수량 감소 + 상태 갱신
        tool.available_qty = max(0, tool.available_qty - 1)
        if tool.available_qty == 0:
            tool.status = '사용중'
        tool.current_location = location or tool.current_location

        log_activity(db, '공구관리', 'checkout',
                     f'{tool.tool_name} 불출 → {user_name} ({location or "미지정"})',
                     ref_type='Tool', ref_id=tool.id, ref_label=tool.tool_name)
        db.commit()
        flash(f'{tool.tool_name} 불출 완료', 'success')
    return redirect(url_for('tools.tool_detail', tool_id=tool_id))


# ── 반납 ──────────────────────────────────────────────
@tools_bp.route('/tools/checkout/<int:checkout_id>/return', methods=['POST'])
@menu_required('tools', write=True)
def tool_return(checkout_id):
    with get_db() as db:
        checkout = db.query(ToolCheckout).options(
            joinedload(ToolCheckout.tool)
        ).get(checkout_id)
        if not checkout or checkout.status != '불출':
            flash('반납할 수 없는 건입니다.', 'warning')
            return redirect(url_for('tools.tool_list'))

        checkout.status = '반납'
        checkout.return_at = datetime.datetime.now()
        checkout.return_note = request.form.get('return_note', '').strip() or None

        tool = checkout.tool
        tool.available_qty = min(tool.total_qty, tool.available_qty + 1)
        if tool.available_qty > 0:
            tool.status = '보관중'
        tool.current_location = request.form.get('return_location', '사무실').strip()

        log_activity(db, '공구관리', 'return',
                     f'{tool.tool_name} 반납 ← {checkout.checkout_user_name}',
                     ref_type='Tool', ref_id=tool.id, ref_label=tool.tool_name)
        db.commit()
        flash(f'{tool.tool_name} 반납 완료', 'success')
    return redirect(url_for('tools.tool_detail', tool_id=checkout.tool_id))
