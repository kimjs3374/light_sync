"""
청구관리 Blueprint — 납품완료 건의 대금청구 상태 관리.

핵심 흐름: 납품완료 → 청구완료(세금계산서 발행) → 입금완료
- 미청구: 납품 끝났지만 세금계산서 미발행 → 청구 대상
- 청구완료: 세금계산서 발행됨, 입금 대기 중
- 입금완료/변경완료/취소: 최종 완료 (매출/수금 화면에서 관리)
"""

import datetime

from flask import Blueprint, render_template, request, jsonify, session
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from modules.auth_decorators import login_required, menu_required
from modules.db_context import get_db
from modules.history_board import append_history_log
from modules.notification_engine import notify
from modules.models import Project, Contract, Delivery, TaxInvoice, G2bProcurement
from modules.pagination import make_pagination
from modules.utils import safe_int

billing_bp = Blueprint('billing', __name__)


@billing_bp.route('/billing')
@login_required
@menu_required('billing')
def billing_list():
    """청구관리 목록 — 납품완료 건 중심으로 청구 상태 관리"""
    q = (request.args.get('q') or '').strip()
    tab = (request.args.get('tab') or 'pending').strip()   # pending | billed | all
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 50)

    with get_db() as db:
        today = datetime.date.today()

        # 기본: 납품완료 상태의 delivery가 있는 계약만
        base = (
            db.query(Contract)
            .join(Project, Contract.project_id == Project.id)
            .join(Delivery, Delivery.contract_id == Contract.id)
            .filter(
                Contract.is_excluded.isnot(True),
                Delivery.delivery_status == 'done',
            )
        )

        # 탭 필터
        if tab == 'pending':
            base = base.filter(Contract.payment_status == '미청구')
        elif tab == 'partial':
            base = base.filter(Contract.payment_status == '부분입금')
        elif tab == 'billed':
            base = base.filter(Contract.payment_status == '청구완료')
        else:  # all
            base = base.filter(
                Contract.payment_status.in_(['미청구', '청구완료', '부분입금'])
            )

        # 검색
        if q:
            like_q = f'%{q}%'
            base = base.filter(or_(
                Contract.contract_name.ilike(like_q),
                Project.temp_name.ilike(like_q),
                Contract.g2b_contract_no.ilike(like_q),
            ))

        # 중복 제거 (하나의 계약에 여러 delivery가 있을 수 있으므로)
        contract_ids_q = base.with_entities(Contract.id, Contract.delivery_due_date).distinct()
        total = contract_ids_q.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        contract_ids = [
            r[0] for r in contract_ids_q.order_by(
                Contract.delivery_due_date.asc().nullslast()
            ).offset(offset).limit(per_page).all()
        ]
        contracts = (
            db.query(Contract)
            .filter(Contract.id.in_(contract_ids))
            .options(
                joinedload(Contract.project),
                joinedload(Contract.deliveries),
            )
            .order_by(Contract.delivery_due_date.asc().nullslast())
            .all()
        ) if contract_ids else []

        # G2B 계약금액 일괄 조회
        g2b_nos = [c.g2b_contract_no for c in contracts if c.g2b_contract_no]
        amt_map = {}
        invoiced_set = set()
        if g2b_nos:
            amt_rows = db.query(
                G2bProcurement.cntrct_dlvr_req_no,
                func.sum(G2bProcurement.prdct_amt),
            ).filter(
                G2bProcurement.cntrct_dlvr_req_no.in_(g2b_nos),
            ).group_by(G2bProcurement.cntrct_dlvr_req_no).all()
            amt_map = {r[0]: r[1] or 0 for r in amt_rows}

            # 세금계산서 매칭 여부
            invoiced_rows = db.query(TaxInvoice.g2b_contract_no).filter(
                TaxInvoice.g2b_contract_no.in_(g2b_nos),
                TaxInvoice.match_status.in_(['자동매칭', '수동매칭']),
            ).distinct().all()
            invoiced_set = {r[0] for r in invoiced_rows}

        # 통계
        stats_base = (
            db.query(Contract.payment_status, func.count(func.distinct(Contract.id)))
            .join(Delivery, Delivery.contract_id == Contract.id)
            .filter(
                Contract.is_excluded.isnot(True),
                Delivery.delivery_status == 'done',
                Contract.payment_status.in_(['미청구', '청구완료', '부분입금']),
            )
            .group_by(Contract.payment_status)
            .all()
        )
        stats = {'미청구': 0, '청구완료': 0, '부분입금': 0}
        for ps, cnt in stats_base:
            stats[ps] = cnt

        rows = []
        for c in contracts:
            rows.append({
                'contract': c,
                'project': c.project,
                'is_invoiced': c.g2b_contract_no in invoiced_set,
                'amount': amt_map.get(c.g2b_contract_no, 0),
                'dday': (c.delivery_due_date - today).days if c.delivery_due_date else None,
            })

    return render_template(
        'billing_list.html',
        rows=rows,
        tab=tab,
        q=q,
        pagination=pagination,
        stats=stats,
        hide_financial=session.get('hide_financial', False),
    )


@billing_bp.route('/billing/api/mark-billed', methods=['POST'])
@login_required
@menu_required('billing')
def mark_billed():
    """미청구 → 청구완료 전환"""
    data = request.get_json() or {}
    contract_id = safe_int(data.get('contract_id'))
    if not contract_id:
        return jsonify({'ok': False, 'error': '계약 ID 없음'}), 400

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'ok': False, 'error': '계약을 찾을 수 없습니다'}), 404
        if contract.payment_status not in ('미청구', '부분입금'):
            return jsonify({'ok': False, 'error': f'현재 상태가 "{contract.payment_status}"입니다. 미청구/부분입금 건만 변경 가능합니다.'}), 400

        contract.payment_status = '청구완료'
        contract.invoice_date = contract.invoice_date or datetime.date.today()

        user_name = session.get('full_name', '사용자')
        if contract.project_id:
            append_history_log(
                db,
                project_id=contract.project_id,
                user_name=user_name,
                content=f"대금청구 완료 처리 — {contract.contract_name}",
                scope="billing",
                kind="status",
            )
        notify(db, 'billing.completed', {
            'contract_name': contract.contract_name,
            'user_name': user_name,
            'project_id': contract.project_id or '',
        })
        db.commit()

    return jsonify({'ok': True, 'message': '청구완료 처리되었습니다.'})


@billing_bp.route('/billing/api/revert-billed', methods=['POST'])
@login_required
@menu_required('billing')
def revert_billed():
    """청구완료 → 미청구 복원"""
    data = request.get_json() or {}
    contract_id = safe_int(data.get('contract_id'))
    if not contract_id:
        return jsonify({'ok': False, 'error': '계약 ID 없음'}), 400

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'ok': False, 'error': '계약을 찾을 수 없습니다'}), 404
        if contract.payment_status != '청구완료':
            return jsonify({'ok': False, 'error': f'현재 상태가 "{contract.payment_status}"입니다. 청구완료 건만 복원 가능합니다.'}), 400

        contract.payment_status = '미청구'
        contract.invoice_date = None

        user_name = session.get('full_name', '사용자')
        if contract.project_id:
            append_history_log(
                db,
                project_id=contract.project_id,
                user_name=user_name,
                content=f"대금청구 복원(미청구) — {contract.contract_name}",
                scope="billing",
                kind="status",
            )
        notify(db, 'billing.reverted', {
            'contract_name': contract.contract_name,
            'user_name': user_name,
            'project_id': contract.project_id or '',
        })
        db.commit()

    return jsonify({'ok': True, 'message': '미청구로 복원되었습니다.'})
