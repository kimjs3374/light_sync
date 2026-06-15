"""
발주/입고현황 (Incoming Overview) Blueprint.

생산팀 자재 추적 통합뷰 — 발주된 품목 → 입고예정 → 입고완료 흐름을
품목 단위로 한 화면에서 표시.

- 데이터: PurchaseOrderItem ↔ ReceivingItem (po_item_id FK)
- 상태 분류: 미입고 / 부분입고 / 입고완료 / 지연
- 권한: 생산부, 관리부, 임원진 (읽기)
"""

import datetime
import logging

from flask import Blueprint, render_template, request, abort
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from modules.auth_decorators import login_required, menu_required
from modules.db_context import get_db
from modules.models import (
    PurchaseOrder, PurchaseOrderItem,
    Receiving, ReceivingItem,
    Vendor, Project, Contract,
)


def _fmt_money(val):
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)

logger = logging.getLogger(__name__)

incoming_overview_bp = Blueprint('incoming_overview', __name__)


STATUS_LABEL = {
    'pending': '미입고',
    'partial': '부분입고',
    'done':    '입고완료',
    'overdue': '지연',
    'direct':  '직접입고',  # PO 없이 바로 입고 처리한 항목
}

STATUS_PRIORITY = {  # 정렬 우선순위 (낮을수록 위)
    'overdue': 0,
    'pending': 1,
    'partial': 2,
    'done':    3,
    'direct':  4,  # 직접입고는 이미 끝난 건이라 맨 아래
}


def _compute_status(qty, recv, due_date, today):
    """품목 상태 계산"""
    qty = float(qty or 0)
    recv = float(recv or 0)
    if qty <= 0:
        # 발주량 0인 비정상 데이터는 그냥 done 처리
        return 'done'
    if recv >= qty:
        return 'done'
    if recv > 0:
        # 부분입고 — 지연이어도 부분으로 표기 (이미 일부 들어옴)
        return 'partial'
    if due_date and due_date < today:
        return 'overdue'
    return 'pending'


def _build_dataset(db, *, search='', status_filter='all', date_from=None, date_to=None):
    """공통 집계 — PC 라우트와 모바일 API에서 공유"""
    today = datetime.date.today()
    week_later = today + datetime.timedelta(days=7)

    # 활성 PO만 (취소 제외)
    q = db.query(PurchaseOrderItem).join(
        PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id
    ).options(
        joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.vendor),
        joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.project),
        joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.contract),
    ).filter(PurchaseOrder.status != '취소')

    if date_from:
        q = q.filter(PurchaseOrder.po_date >= date_from)
    if date_to:
        q = q.filter(PurchaseOrder.po_date <= date_to)

    if search:
        like = f'%{search}%'
        q = q.outerjoin(Vendor, Vendor.id == PurchaseOrder.vendor_id) \
             .outerjoin(Project, Project.id == PurchaseOrder.project_id) \
             .outerjoin(Contract, Contract.id == PurchaseOrder.contract_id) \
             .filter(or_(
                 PurchaseOrderItem.item_name.ilike(like),
                 PurchaseOrderItem.item_spec.ilike(like),
                 PurchaseOrder.po_no.ilike(like),
                 Vendor.name.ilike(like),
                 Project.temp_name.ilike(like),
                 Contract.contract_name.ilike(like),
             ))

    po_items = q.all()

    # 입고량 합계 (po_item_id별)
    po_item_ids = [pi.id for pi in po_items]
    recv_sums = {}
    if po_item_ids:
        rows = db.query(
            ReceivingItem.po_item_id,
            func.coalesce(func.sum(ReceivingItem.received_qty), 0)
        ).filter(
            ReceivingItem.po_item_id.in_(po_item_ids)
        ).group_by(ReceivingItem.po_item_id).all()
        recv_sums = {pid: float(s or 0) for pid, s in rows}

    items = []
    stats = {
        'total': 0, 'pending': 0, 'partial': 0, 'done': 0, 'overdue': 0,
        'direct': 0, 'this_week': 0, 'today_in': 0,
    }

    for pi in po_items:
        po = pi.purchase_order
        if not po:
            continue
        qty = float(pi.quantity or 0)
        recv = recv_sums.get(pi.id, 0.0)
        remain = max(qty - recv, 0)
        due = pi.delivery_date or pi.expected_in_date
        status = _compute_status(qty, recv, due, today)

        contract_name = po.contract.contract_name if po.contract else ''
        project_name = po.project.temp_name if po.project else ''
        site_name = contract_name or project_name

        items.append({
            'po_item_id': pi.id,
            'po_id': po.id,
            'po_no': po.po_no or '',
            'po_date': po.po_date.strftime('%Y-%m-%d') if po.po_date else '',
            'vendor_name': po.vendor.name if po.vendor else '',
            'project_name': project_name,
            'contract_name': contract_name,
            'site_name': site_name,
            'item_code': pi.item_code or '',
            'item_name': pi.item_name or '',
            'item_spec': pi.item_spec or '',
            'unit': pi.unit or '',
            'quantity': qty,
            'received_qty': recv,
            'remain': remain,
            'delivery_date': due.strftime('%Y-%m-%d') if due else '',
            'delivery_date_raw': due,  # 정렬용
            'status': status,
            'status_label': STATUS_LABEL[status],
        })

        # 통계
        stats['total'] += 1
        stats[status] = stats.get(status, 0) + 1
        if status in ('pending', 'partial', 'overdue') and due and today <= due <= week_later:
            stats['this_week'] += 1
        # 오늘 입고된 품목 카운트 (입고일 today인 ReceivingItem)
        # — 라이트하게 처리하기 위해 별도 쿼리 1개

    # 오늘 입고 — Receiving.rcv_date == today
    from modules.models import Receiving
    today_in_count = db.query(func.count(ReceivingItem.id)).join(
        Receiving, Receiving.id == ReceivingItem.receiving_id
    ).filter(Receiving.rcv_date == today).scalar() or 0
    stats['today_in'] = today_in_count

    # ── 직접입고: PO 연결 없는 ReceivingItem (po_item_id IS NULL) ──
    direct_q = db.query(ReceivingItem).join(
        Receiving, Receiving.id == ReceivingItem.receiving_id
    ).options(
        joinedload(ReceivingItem.receiving).joinedload(Receiving.vendor),
        joinedload(ReceivingItem.receiving).joinedload(Receiving.contract),
    ).filter(ReceivingItem.po_item_id.is_(None))

    if date_from:
        direct_q = direct_q.filter(Receiving.rcv_date >= date_from)
    if date_to:
        direct_q = direct_q.filter(Receiving.rcv_date <= date_to)

    if search:
        like = f'%{search}%'
        direct_q = direct_q.outerjoin(Vendor, Vendor.id == Receiving.vendor_id) \
            .outerjoin(Contract, Contract.id == Receiving.contract_id) \
            .filter(or_(
                ReceivingItem.item_name.ilike(like),
                ReceivingItem.item_spec.ilike(like),
                ReceivingItem.item_cd.ilike(like),
                Receiving.rcv_no.ilike(like),
                Vendor.name.ilike(like),
                Contract.contract_name.ilike(like),
            ))

    for ri in direct_q.all():
        rcv = ri.receiving
        if not rcv:
            continue
        recv = float(ri.received_qty or 0)
        contract_name = rcv.contract.contract_name if rcv.contract else ''
        items.append({
            'po_item_id': None,
            'po_id': None,
            'po_no': '',
            'po_date': '',
            'rcv_id': rcv.id,
            'rcv_no': rcv.rcv_no or '',
            'rcv_date': rcv.rcv_date.strftime('%Y-%m-%d') if rcv.rcv_date else '',
            'vendor_name': rcv.vendor.name if rcv.vendor else '',
            'project_name': '',
            'contract_name': contract_name,
            'site_name': contract_name,
            'item_code': ri.item_cd or '',
            'item_name': ri.item_name or '',
            'item_spec': ri.item_spec or '',
            'unit': ri.unit or '',
            'quantity': 0,
            'received_qty': recv,
            'remain': 0,
            'delivery_date': '',
            'delivery_date_raw': None,
            'status': 'direct',
            'status_label': STATUS_LABEL['direct'],
        })
        stats['total'] += 1
        stats['direct'] = stats.get('direct', 0) + 1

    # 상태 필터 적용 (이미 통계는 전체 기준으로 집계)
    if status_filter and status_filter != 'all':
        items = [it for it in items if it['status'] == status_filter]

    # 정렬: 발주일 최신순 (직접입고는 입고일 기준), 같은 날이면 상태 우선순위
    items.sort(key=lambda x: (
        x.get('po_date') or x.get('rcv_date') or '',
        -STATUS_PRIORITY.get(x['status'], 99),  # 같은 날짜 내에서는 status 우선순위 유지
    ), reverse=True)

    # JSON 직렬화 위해 raw date 제거
    for it in items:
        it.pop('delivery_date_raw', None)

    return items, stats


@incoming_overview_bp.route('/production/incoming')
@login_required
@menu_required('incoming_overview')
def incoming_overview_view():
    """생산부 발주/입고현황 PC 화면"""
    search = (request.args.get('q') or '').strip()
    status_filter = (request.args.get('status') or 'all').strip()
    date_from = request.args.get('from') or None
    date_to = request.args.get('to') or None

    def _parse(d):
        if not d:
            return None
        try:
            return datetime.datetime.strptime(d, '%Y-%m-%d').date()
        except ValueError:
            return None

    with get_db() as db:
        items, stats = _build_dataset(
            db, search=search, status_filter=status_filter,
            date_from=_parse(date_from), date_to=_parse(date_to),
        )

    return render_template(
        'incoming_overview.html',
        items=items,
        stats=stats,
        filters={'q': search, 'status': status_filter, 'from': date_from or '', 'to': date_to or ''},
        status_labels=STATUS_LABEL,
    )
