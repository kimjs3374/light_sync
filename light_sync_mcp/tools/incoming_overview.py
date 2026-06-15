"""발주/입고현황 통합뷰 Tools (생산팀 자재 추적)"""
import datetime
import json
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


_STATUS_LABEL = {
    'pending': '미입고',
    'partial': '부분입고',
    'done':    '입고완료',
    'overdue': '지연',
    'direct':  '직접입고',
}


def _compute_status(qty, recv, due_date, today):
    qty = float(qty or 0)
    recv = float(recv or 0)
    if qty <= 0:
        return 'done'
    if recv >= qty:
        return 'done'
    if recv > 0:
        return 'partial'
    if due_date and due_date < today:
        return 'overdue'
    return 'pending'


def register(mcp: FastMCP):

    @mcp.tool()
    def get_incoming_overview(
        status: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """발주/입고현황 — 발주된 품목의 입고 진행상태 통합 조회.
        ★ '입고 안 된 거', '미입고', '부분입고', '입고지연', '이번주 들어올 자재',
          'OO자재 어디까지 왔어', '발주 후 입고 진행' 등에 사용.

        status: pending(미입고) / partial(부분입고) / done(입고완료) / overdue(지연) / direct(직접입고) / all
        search: 품목명/규격/발주번호/거래처/현장 부분 검색
        date_from / date_to: 발주일 범위 (YYYY-MM-DD)
        limit: 최대 건수 (기본 50, 너무 크게 하지 말 것)
        """
        from modules.models import (
            PurchaseOrder, PurchaseOrderItem,
            Receiving, ReceivingItem,
            Vendor, Project, Contract,
        )
        session = get_session()
        try:
            today = datetime.date.today()
            week_later = today + datetime.timedelta(days=7)

            def _parse_date(s):
                if not s:
                    return None
                try:
                    return datetime.datetime.strptime(s, "%Y-%m-%d").date()
                except ValueError:
                    return None

            df = _parse_date(date_from)
            dt_ = _parse_date(date_to)

            # ── PO 기반 ────────────────────────────────────────────────
            q = session.query(PurchaseOrderItem).join(
                PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id
            ).options(
                joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.vendor),
                joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.project),
                joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.contract),
            ).filter(PurchaseOrder.status != '취소')

            if df:
                q = q.filter(PurchaseOrder.po_date >= df)
            if dt_:
                q = q.filter(PurchaseOrder.po_date <= dt_)
            if search:
                like = f"%{search}%"
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

            po_items = q.order_by(PurchaseOrder.po_date.desc()).all()

            po_item_ids = [pi.id for pi in po_items]
            recv_sums = {}
            if po_item_ids:
                rows = session.query(
                    ReceivingItem.po_item_id,
                    func.coalesce(func.sum(ReceivingItem.received_qty), 0)
                ).filter(
                    ReceivingItem.po_item_id.in_(po_item_ids)
                ).group_by(ReceivingItem.po_item_id).all()
                recv_sums = {pid: float(s or 0) for pid, s in rows}

            items = []
            stats = {'total': 0, 'pending': 0, 'partial': 0, 'done': 0,
                     'overdue': 0, 'direct': 0, 'this_week': 0}

            for pi in po_items:
                po = pi.purchase_order
                if not po:
                    continue
                qty = float(pi.quantity or 0)
                recv = recv_sums.get(pi.id, 0.0)
                remain = max(qty - recv, 0)
                due = pi.delivery_date or pi.expected_in_date
                st = _compute_status(qty, recv, due, today)

                contract_name = po.contract.contract_name if po.contract else ''
                project_name = po.project.temp_name if po.project else ''

                items.append({
                    "po_no": _s(po.po_no),
                    "po_date": _sd(po.po_date),
                    "vendor_name": po.vendor.name if po.vendor else '',
                    "site_name": contract_name or project_name,
                    "item_code": _s(pi.item_code),
                    "item_name": _s(pi.item_name),
                    "item_spec": _s(pi.item_spec),
                    "unit": _s(pi.unit),
                    "ordered_qty": int(qty) if qty == int(qty) else qty,
                    "received_qty": int(recv) if recv == int(recv) else recv,
                    "remain_qty": int(remain) if remain == int(remain) else remain,
                    "delivery_date": _sd(due),
                    "status": st,
                    "status_label": _STATUS_LABEL[st],
                })
                stats['total'] += 1
                stats[st] = stats.get(st, 0) + 1
                if st in ('pending', 'partial', 'overdue') and due and today <= due <= week_later:
                    stats['this_week'] += 1

            # ── 직접입고 (PO 연결 없는 ReceivingItem) ────────────────────
            direct_q = session.query(ReceivingItem).join(
                Receiving, Receiving.id == ReceivingItem.receiving_id
            ).options(
                joinedload(ReceivingItem.receiving).joinedload(Receiving.vendor),
                joinedload(ReceivingItem.receiving).joinedload(Receiving.contract),
            ).filter(ReceivingItem.po_item_id.is_(None))

            if df:
                direct_q = direct_q.filter(Receiving.rcv_date >= df)
            if dt_:
                direct_q = direct_q.filter(Receiving.rcv_date <= dt_)
            if search:
                like = f"%{search}%"
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

            for ri in direct_q.order_by(Receiving.rcv_date.desc()).all():
                rcv = ri.receiving
                if not rcv:
                    continue
                recv = float(ri.received_qty or 0)
                items.append({
                    "po_no": "",
                    "po_date": "",
                    "rcv_no": _s(rcv.rcv_no),
                    "rcv_date": _sd(rcv.rcv_date),
                    "vendor_name": rcv.vendor.name if rcv.vendor else '',
                    "site_name": rcv.contract.contract_name if rcv.contract else '',
                    "item_code": _s(ri.item_cd),
                    "item_name": _s(ri.item_name),
                    "item_spec": _s(ri.item_spec),
                    "unit": _s(ri.unit),
                    "ordered_qty": 0,
                    "received_qty": int(recv) if recv == int(recv) else recv,
                    "remain_qty": 0,
                    "delivery_date": "",
                    "status": "direct",
                    "status_label": _STATUS_LABEL['direct'],
                })
                stats['total'] += 1
                stats['direct'] = stats.get('direct', 0) + 1

            # 상태 필터
            if status and status != 'all':
                items = [it for it in items if it['status'] == status]

            # limit (응답 크기 보호)
            items = items[:limit]

            return json.dumps({
                "stats": stats,
                "filtered_count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
