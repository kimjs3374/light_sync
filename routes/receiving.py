"""
입고관리 Blueprint (Phase 3).

- 입고 목록/등록/상세
- 발주서 기반 입고 / 직접 입고
- 발주 vs 입고 대사
- 거래명세서 자동 생성
"""

import datetime
import json as _json
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session,
)
from sqlalchemy import case, desc, func, extract
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int, parse_money
from modules.db_context import get_db
from modules.models import (
    Vendor, PurchaseOrder, PurchaseOrderItem, MaterialOrder,
    Receiving, ReceivingItem, ReceivingHistory,
    Item, BomItem, Contract, Project,
    ProcessingOrder, ProcessingOrderItem,
)
from sqlalchemy.orm import joinedload
from modules.services.inventory_utils import record_stock_movement
from modules.activity import log_activity

logger = logging.getLogger(__name__)

receiving_bp = Blueprint('receiving', __name__)


# ===================================================================
# 헬퍼
# ===================================================================
def _generate_rcv_no(db):
    """입고번호 자동 채번: RCV{YYYY}-{NNN}"""
    year = datetime.date.today().year
    prefix = f'RCV{year}-'

    last = db.query(Receiving).filter(
        Receiving.rcv_no.like(f'{prefix}%')
    ).order_by(desc(Receiving.rcv_no)).first()

    if last:
        try:
            last_num = int(last.rcv_no.replace(prefix, ''))
            return f'{prefix}{last_num + 1:03d}'
        except ValueError:
            pass

    return f'{prefix}001'


def _fmt_money(val):
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def _update_po_status_on_receiving(db, po_id):
    """발주서 전체 입고 시 상태 자동 전환 + MaterialOrder 입고완료.

    완료 판정 기준 (둘 중 하나):
    - po_item.in_confirmed = True (사용자가 입고확인 처리)
    - total_received >= po_item.quantity (자동 전량 입고)
    """
    if not po_id:
        return

    po = db.query(PurchaseOrder).get(po_id)
    if not po:
        return

    # 발주 품목별 입고 완료 여부 판정
    any_in = False
    for po_item in po.items:
        total_received = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
            ReceivingItem.po_item_id == po_item.id,
        ).scalar() or 0
        if total_received > 0:
            any_in = True

        is_done = bool(po_item.in_confirmed) or total_received >= (po_item.quantity or 0)
        if not is_done:
            # 미완료 품목 존재 — 일부 입고 상태
            if po.status not in ('입고완료', '취소'):
                po.status = '입고대기' if any_in or any(p.in_confirmed for p in po.items) else po.status
            return

    # 모든 품목 입고 완료 (실수량 기준 또는 강제확인 기준)
    po.status = '입고완료'

    # MaterialOrder 입고완료 연동 + 입고 시 stock_qty 증가 (FR-07)
    material_orders = db.query(MaterialOrder).filter(
        MaterialOrder.po_id == po_id,
    ).all()
    for mo in material_orders:
        mo.order_status = '입고완료'
        mo.in_confirmed = True
        mo.in_confirmed_at = datetime.datetime.now()

    # 발주 품목별 입고 수량으로 Item.stock_qty 증가 + StockMovement 기록
    # 발주서에 연결된 입고 ID 찾기 (가장 최근)
    latest_rcv = db.query(Receiving).filter(
        Receiving.po_id == po_id,
    ).order_by(desc(Receiving.id)).first()
    rcv_id = latest_rcv.id if latest_rcv else None
    rcv_no = latest_rcv.rcv_no if latest_rcv else ''

    for po_item in po.items:
        total_received = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
            ReceivingItem.po_item_id == po_item.id,
        ).scalar() or 0

        # BomItem -> Item 연결이 있으면 record_stock_movement 사용
        if po_item.bom_item_id:
            bi = db.query(BomItem).get(po_item.bom_item_id)
            if bi and bi.item_id:
                linked_item = db.query(Item).get(bi.item_id)
                if linked_item:
                    record_stock_movement(
                        db, linked_item.id,
                        movement_type='IN_RECEIVING',
                        quantity=total_received,
                        reference_type='receiving',
                        reference_id=rcv_id,
                        unit_price=po_item.unit_price,
                        note=f'입고 {rcv_no}',
                    )
                    # last_unit_price 갱신
                    if po_item.unit_price and po_item.unit_price > 0:
                        linked_item.last_unit_price = po_item.unit_price


# ===================================================================
# 1. 입고 목록
# ===================================================================
@receiving_bp.route('/receiving')
@login_required
def receiving_list():
    q = (request.args.get('q') or '').strip()
    status = (request.args.get('status') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 50

    with get_db() as db:
        import json as _json
        from modules.models import ProcessingOrder as _FO

        tokens = [t.strip().lower() for t in q.split() if t.strip()] if q else []

        # ── (A) 신규 입고 (receivings 테이블) ──
        new_query = db.query(Receiving).join(Vendor).outerjoin(
            ReceivingItem, ReceivingItem.receiving_id == Receiving.id
        ).outerjoin(_FO, _FO.id == Receiving.fo_id)

        if q:
            for token in [t.strip() for t in q.split() if t.strip()]:
                like_t = f"%{token}%"
                new_query = new_query.filter(
                    (Vendor.name.ilike(like_t)) |
                    (Receiving.rcv_no.ilike(like_t)) |
                    (ReceivingItem.item_name.ilike(like_t)) |
                    (ReceivingItem.item_spec.ilike(like_t))
                )
            new_query = new_query.distinct()

        receivings_raw = new_query.order_by(desc(Receiving.rcv_date), desc(Receiving.id)).all()

        all_receivings = []
        for rcv in receivings_raw:
            detail_rows = []
            for ri in rcv.items:
                spec = (ri.item_spec or '').strip()
                note = (ri.note or '').strip()
                if not spec and note:
                    spec = note
                    note = ''
                item_cd = ri.item_cd or ''
                if not item_cd and ri.po_item:
                    item_cd = ri.po_item.item_code or ''
                row = {
                    'item_cd': item_cd,
                    'item_name': ri.item_name or '',
                    'spec': spec,
                    'qty': ri.received_qty or 0,
                    'unit': ri.unit or '',
                    'unit_price': ri.unit_price or 0,
                    'amount': ri.amount or 0,
                    'remark': note,
                }
                if tokens:
                    item_text = f"{ri.item_name or ''} {spec}".lower()
                    vendor_text = (rcv.vendor.name or '').lower()
                    item_tokens = [t for t in tokens if t not in vendor_text]
                    row['_matched'] = all(t in item_text for t in item_tokens)
                detail_rows.append(row)
            if tokens:
                detail_rows = [r for r in detail_rows if r.get('_matched')]
                if not detail_rows:
                    continue
            all_receivings.append({
                'id': rcv.id,
                'rcv_no': rcv.rcv_no,
                'rcv_date': rcv.rcv_date,
                'sort_date': rcv.rcv_date.isoformat() if rcv.rcv_date else '',
                'vendor_name': rcv.vendor.name if rcv.vendor else '',
                'po_no': rcv.purchase_order.po_no if rcv.purchase_order else '',
                'po_id': rcv.po_id,
                'fo_no': rcv.processing_order.fo_no if getattr(rcv, 'processing_order', None) else '',
                'fo_id': rcv.fo_id,
                'status': rcv.status,
                'detail_rows': detail_rows,
                'source': 'new',
            })

        # ── (B) iCUBE 기존 입고이력 (receiving_history 테이블) ──
        hist_query = db.query(ReceivingHistory)
        if q:
            for token in [t.strip() for t in q.split() if t.strip()]:
                like_t = f"%{token}%"
                hist_query = hist_query.filter(
                    (ReceivingHistory.vendor_name.ilike(like_t)) |
                    (ReceivingHistory.icube_rcv_nb.ilike(like_t)) |
                    (ReceivingHistory.items_json.ilike(like_t))
                )

        history_raw = hist_query.order_by(desc(ReceivingHistory.receive_date)).all()

        for rh in history_raw:
            try:
                items = _json.loads(rh.items_json or '[]')
            except Exception:
                items = []
            for item in items:
                spec = (item.get('spec') or '').strip()
                remark = (item.get('remark') or '').strip()
                if not spec and remark:
                    item['spec'] = remark
                    item['remark'] = ''
            if tokens:
                vendor_lower = (rh.vendor_name or '').lower()
                item_tokens = [t.lower() for t in tokens if t.lower() not in vendor_lower]
                if item_tokens:
                    items = [item for item in items if all(
                        t in f"{item.get('item_name','')} {item.get('spec','')}".lower()
                        for t in item_tokens
                    )]
                    if not items:
                        continue
            all_receivings.append({
                'id': None,
                'history_id': rh.id,
                'rcv_no': rh.icube_rcv_nb,
                'rcv_date': rh.receive_date,
                'sort_date': rh.receive_date.isoformat() if rh.receive_date else '',
                'vendor_name': rh.vendor_name or '',
                'po_no': '',
                'po_id': None,
                'fo_no': '',
                'fo_id': None,
                'status': '',
                'detail_rows': [
                    {
                        'item_cd': item.get('item_cd', ''),
                        'item_name': item.get('item_name', ''),
                        'spec': item.get('spec', ''),
                        'qty': item.get('qty', 0),
                        'unit': item.get('unit', ''),
                        'unit_price': item.get('unit_price', 0) or 0,
                        'amount': round((item.get('qty', 0) or 0) * (item.get('unit_price', 0) or 0)),
                        'remark': item.get('remark', ''),
                    } for item in items
                ],
                'source': 'icube',
            })

        # 날짜 내림차순 통합 정렬
        all_receivings.sort(key=lambda x: x['sort_date'] or '', reverse=True)

        # 통합 페이지네이션
        total = len(all_receivings)
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page
        receivings = all_receivings[offset:offset + per_page]

        # 통계
        new_count = sum(1 for r in all_receivings if r['source'] == 'new')
        icube_count = sum(1 for r in all_receivings if r['source'] == 'icube')
        stats = {
            'total': total,
            'new_count': new_count,
            'icube_count': icube_count,
        }

        # ── 입고예정 데이터 (발주서 품목 직접 조회) ──
        from datetime import date as _date
        from modules.services.dashboard_actions import get_dashboard_setting_int
        today = _date.today()
        production_lead_days = get_dashboard_setting_int(db, 'production_lead_days', 7)

        # 발송완료/입고대기 상태 발주서의 미확인 품목
        expected_qs = db.query(PurchaseOrderItem).join(
            PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id
        ).options(
            joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.vendor),
            joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.project),
            joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.contract).joinedload(Contract.project),
        ).filter(
            PurchaseOrder.status.in_(['발송완료', '입고대기']),
            (PurchaseOrderItem.in_confirmed == False) | (PurchaseOrderItem.in_confirmed.is_(None)),
        ).order_by(
            case(
                (PurchaseOrderItem.expected_in_date.is_(None), 0),
                else_=1
            ).asc(),
            PurchaseOrderItem.expected_in_date.asc(),
        ).all()

        for poi in expected_qs:
            po = poi.purchase_order
            if poi.expected_in_date:
                d = (poi.expected_in_date - today).days
                poi._dday = d
                poi._dday_state = 'overdue' if d < 0 else 'today' if d == 0 else 'week' if d <= 7 else 'ok'
            else:
                poi._dday = None
                poi._dday_state = 'unknown'
            # 납기위험도
            delivery_due = po.contract.desired_delivery_date if po and po.contract else None
            if delivery_due and poi.expected_in_date:
                margin = (delivery_due - poi.expected_in_date).days - production_lead_days
                poi._risk = 'danger' if margin < 0 else 'warning' if margin <= 7 else 'ok'
            else:
                poi._risk = 'none'
            poi._delivery_due = delivery_due
            poi._vendor_name = po.vendor.name if po and po.vendor else ''
            # 현장: PO.project 우선, 없으면 계약 경유
            if po and po.project:
                poi._project = po.project
            elif po and po.contract and po.contract.project:
                poi._project = po.contract.project
            else:
                poi._project = None

        expected_stats = {
            'total': len(expected_qs),
            'overdue': sum(1 for p in expected_qs if p._dday_state == 'overdue'),
            'today': sum(1 for p in expected_qs if p._dday_state == 'today'),
            'this_week': sum(1 for p in expected_qs if p._dday_state == 'week'),
            'unknown': sum(1 for p in expected_qs if p._dday_state == 'unknown'),
        }

        active_tab = request.args.get('tab', 'list')

        return render_template(
            'receiving_list.html',
            receivings=receivings,
            pagination=pagination,
            stats=stats,
            filters={'q': q},
            fmt_money=_fmt_money,
            expected_items=expected_qs,
            expected_stats=expected_stats,
            active_tab=active_tab,
            production_lead_days=production_lead_days,
        )


# ===================================================================
# 2. 입고 등록
# ===================================================================
@receiving_bp.route('/receiving/create', methods=['GET', 'POST'])
@login_required
@menu_required('receiving')
def receiving_create():
    with get_db() as db:
        if request.method == 'POST':
            vendor_id = safe_int(request.form.get('vendor_id'), 0)
            po_id = safe_int(request.form.get('po_id'), 0) or None
            fo_id = safe_int(request.form.get('fo_id'), 0) or None
            rcv_date_str = request.form.get('rcv_date', '')
            note = (request.form.get('note') or '').strip()

            if not vendor_id:
                flash('거래처를 선택해주세요.', 'warning')
                return redirect(url_for('receiving.receiving_create'))

            vendor = db.query(Vendor).get(vendor_id)
            if not vendor:
                flash('거래처를 찾을 수 없습니다.', 'danger')
                return redirect(url_for('receiving.receiving_create'))

            try:
                rcv_date = datetime.datetime.strptime(rcv_date_str, '%Y-%m-%d').date()
            except ValueError:
                rcv_date = datetime.date.today()

            # 발주서/가공발주 연결 시 contract_id 자동 설정
            contract_id = None
            if po_id:
                po = db.query(PurchaseOrder).get(po_id)
                if po:
                    contract_id = po.contract_id
            elif fo_id:
                fo = db.query(ProcessingOrder).get(fo_id)
                if fo:
                    contract_id = fo.contract_id

            rcv = Receiving(
                rcv_no=_generate_rcv_no(db),
                rcv_date=rcv_date,
                vendor_id=vendor_id,
                po_id=po_id,
                fo_id=fo_id,
                contract_id=contract_id,
                note=note,
                created_by=session.get('user_id'),
            )
            db.add(rcv)
            db.flush()

            # 품목 추가
            item_cds = request.form.getlist('item_cd[]')
            item_names = request.form.getlist('item_name[]')
            item_specs = request.form.getlist('item_spec[]')
            item_qtys = request.form.getlist('received_qty[]')
            item_prices = request.form.getlist('unit_price[]')
            item_units = request.form.getlist('unit[]')
            item_notes = request.form.getlist('item_note[]')
            po_item_ids = request.form.getlist('po_item_id[]')
            fo_item_ids = request.form.getlist('fo_item_id[]')
            new_items = []

            for i in range(len(item_names)):
                name = (item_names[i] if i < len(item_names) else '').strip()
                if not name:
                    continue

                item_cd = (item_cds[i] if i < len(item_cds) else '').strip()
                spec = (item_specs[i] if i < len(item_specs) else '').strip()
                qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
                price = parse_money(item_prices[i]) if i < len(item_prices) else 0
                unit = (item_units[i] if i < len(item_units) else '').strip()
                item_note = (item_notes[i] if i < len(item_notes) else '').strip()
                linked_po_item_id = safe_int(po_item_ids[i] if i < len(po_item_ids) else '', 0) or None
                linked_fo_item_id = safe_int(fo_item_ids[i] if i < len(fo_item_ids) else '', 0) or None
                amount = qty * price

                # 발주 품목 연결 시 품번 자동 가져오기
                if linked_po_item_id and not item_cd:
                    po_item = db.query(PurchaseOrderItem).get(linked_po_item_id)
                    if po_item:
                        item_cd = po_item.item_code or ''

                ri = ReceivingItem(
                    receiving_id=rcv.id,
                    po_item_id=linked_po_item_id,
                    fo_item_id=linked_fo_item_id,
                    item_cd=item_cd or None,
                    item_name=name,
                    item_spec=spec,
                    received_qty=qty,
                    unit=unit,
                    unit_price=price,
                    amount=amount,
                    note=item_note,
                )
                db.add(ri)

                # 품목 자동등록 + 재고 반영 (직접입고 시)
                if qty > 0 and not linked_po_item_id:
                    item = db.query(Item).filter(
                        Item.item_name == name,
                        Item.item_spec == spec,
                    ).first()
                    is_new_item = item is None
                    if not item:
                        item = Item(
                            item_name=name,
                            item_spec=spec,
                            unit=unit or 'EA',
                            is_active=True,
                        )
                        db.add(item)
                        db.flush()
                        new_items.append(f'{item.icube_item_cd or "-"}|{name}|{spec or "-"}')
                    if price > 0:
                        item.last_unit_price = price
                    record_stock_movement(
                        db, item_id=item.id, movement_type='IN_RECEIVING',
                        quantity=qty, reference_type='receiving',
                        reference_id=rcv.id, unit_price=price,
                        note=f'직접입고 {rcv.rcv_no}',
                    )

            # 입고예정 단건 흐름: 강제 입고확인 처리할 PO 품목 ID
            force_confirm_poi = safe_int(request.form.get('force_confirm_poi'), 0) or None

            # 발주서 상태 업데이트 + po_item.in_confirmed 동기화
            if po_id:
                # 발주 품목별 입고 완료 여부 반영 (먼저 동기화 → status 계산이 in_confirmed 참조)
                po_obj = db.query(PurchaseOrder).options(joinedload(PurchaseOrder.items)).get(po_id)
                if po_obj:
                    now_dt = datetime.datetime.now()
                    for po_item in po_obj.items:
                        total_rcv = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                            ReceivingItem.po_item_id == po_item.id,
                        ).scalar() or 0
                        # 자동 완료: 전량 입고 시
                        if total_rcv >= (po_item.quantity or 0) and not po_item.in_confirmed:
                            po_item.in_confirmed = True
                            po_item.in_confirmed_at = now_dt
                        # 강제 완료: 입고예정 단건 흐름에서 사용자가 확인한 품목 (수량 부족이어도)
                        if force_confirm_poi and po_item.id == force_confirm_poi and not po_item.in_confirmed:
                            po_item.in_confirmed = True
                            po_item.in_confirmed_at = now_dt
                _update_po_status_on_receiving(db, po_id)

            # 가공발주 품목 입고확인 동기화
            if fo_id:
                fo_obj = db.query(ProcessingOrder).options(joinedload(ProcessingOrder.items)).get(fo_id)
                if fo_obj:
                    now_dt = datetime.datetime.now()
                    all_confirmed = True
                    for fo_item in fo_obj.items:
                        total_rcv = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                            ReceivingItem.fo_item_id == fo_item.id,
                        ).scalar() or 0
                        if total_rcv >= (fo_item.quantity or 0) and not fo_item.in_confirmed:
                            fo_item.in_confirmed = True
                            fo_item.in_confirmed_at = now_dt
                        if not fo_item.in_confirmed:
                            all_confirmed = False
                    if all_confirmed and fo_obj.status != '입고완료':
                        fo_obj.status = '입고완료'

            log_activity(db, '입고관리', 'create', f'{rcv.rcv_no} 입고 등록 ({vendor.name})', ref_type='Receiving', ref_id=rcv.id)
            db.commit()

            # 알림 메시지
            flash(f'입고 {rcv.rcv_no}가 등록되었습니다.', 'success')
            for ni in new_items:
                flash(f'신규 품목 자동등록: {ni}', 'info')
            return redirect(url_for('receiving.receiving_detail', rcv_id=rcv.id))

        # GET: 폼 표시
        # 발주서 기반 입고 시 po_id 또는 fo_id 파라미터로 전달
        po_id = safe_int(request.args.get('po_id'), 0) or None
        fo_id = safe_int(request.args.get('fo_id'), 0) or None
        # 입고예정 탭 → 단일 품목 입고확인 흐름: 강조할 PO 품목 ID
        highlight_poi = safe_int(request.args.get('highlight_poi'), 0) or None
        po = None
        fo = None
        po_items = []
        fo_items = []
        if po_id:
            po = db.query(PurchaseOrder).options(
                joinedload(PurchaseOrder.items),
                joinedload(PurchaseOrder.vendor),
            ).get(po_id)
            if po:
                # 발주 품목별 이미 입고된 수량 계산
                for pi in po.items:
                    already = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                        ReceivingItem.po_item_id == pi.id,
                    ).scalar() or 0
                    pi._already_received = float(already)
                    pi._remaining = max(0, float(pi.quantity or 0) - float(already))
                    # 단일 품목 입고확인 모드: 강조 대상이 아닌 행은 prefill 0
                    pi._is_highlighted = (highlight_poi is not None and pi.id == highlight_poi)
                    if highlight_poi is not None:
                        pi._prefill_qty = pi._remaining if pi._is_highlighted else 0
                    else:
                        pi._prefill_qty = pi._remaining
                po_items = po.items
        elif fo_id:
            fo = db.query(ProcessingOrder).options(
                joinedload(ProcessingOrder.items),
                joinedload(ProcessingOrder.vendor),
            ).get(fo_id)
            if fo:
                for fi in fo.items:
                    already = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                        ReceivingItem.fo_item_id == fi.id,
                    ).scalar() or 0
                    fi._already_received = float(already)
                    fi._remaining = max(0, float(fi.quantity or 0) - float(already))
                fo_items = fo.items

        return render_template(
            'receiving_create.html',
            po=po,
            po_items=po_items,
            fo=fo,
            fo_items=fo_items,
            highlight_poi=highlight_poi,
        )


# ===================================================================
# 3. 입고 상세
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>')
@login_required
@menu_required('receiving')
def receiving_detail(rcv_id):
    with get_db() as db:
        rcv = db.query(Receiving).options(
            joinedload(Receiving.items),
            joinedload(Receiving.vendor),
            joinedload(Receiving.purchase_order),
        ).get(rcv_id)
        if not rcv:
            abort(404)

        # 거래명세서 총액 계산
        total_amount = sum(item.amount or 0 for item in rcv.items)
        tax_amount = round(total_amount * 0.1)

        return render_template(
            'receiving_detail.html',
            rcv=rcv,
            total_amount=total_amount,
            tax_amount=tax_amount,
            fmt_money=_fmt_money,
        )


# ===================================================================
# 4. 입고 수정
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>/edit', methods=['GET', 'POST'])
@login_required
@menu_required('receiving')
def receiving_edit(rcv_id):
    with get_db() as db:
        rcv = db.query(Receiving).options(
            joinedload(Receiving.items).joinedload(ReceivingItem.po_item),
            joinedload(Receiving.vendor),
            joinedload(Receiving.purchase_order).joinedload(PurchaseOrder.items),
            joinedload(Receiving.purchase_order).joinedload(PurchaseOrder.vendor),
        ).get(rcv_id)
        if not rcv:
            abort(404)

        if request.method == 'POST':
            vendor_id = safe_int(request.form.get('vendor_id'), 0)
            rcv_date_str = request.form.get('rcv_date', '')
            note = (request.form.get('note') or '').strip()

            if not vendor_id:
                flash('거래처를 선택해주세요.', 'warning')
                return redirect(url_for('receiving.receiving_edit', rcv_id=rcv_id))

            vendor = db.query(Vendor).get(vendor_id)
            if not vendor:
                flash('거래처를 찾을 수 없습니다.', 'danger')
                return redirect(url_for('receiving.receiving_edit', rcv_id=rcv_id))

            try:
                rcv.rcv_date = datetime.datetime.strptime(rcv_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

            rcv.vendor_id = vendor_id
            rcv.note = note

            # 다건 PO 연동 보호: 현재 폼이 다루는 범위(=주발주서 PO + 직접입고)만 삭제,
            # 다른 PO에 연결된 ReceivingItem은 보존
            primary_po_item_ids = set()
            if rcv.po_id and rcv.purchase_order:
                primary_po_item_ids = {pi.id for pi in rcv.purchase_order.items}
            for old_item in list(rcv.items):
                if old_item.po_item_id is None or old_item.po_item_id in primary_po_item_ids:
                    db.delete(old_item)
            db.flush()

            # 품목 추가
            item_cds = request.form.getlist('item_cd[]')
            item_names = request.form.getlist('item_name[]')
            item_specs = request.form.getlist('item_spec[]')
            item_qtys = request.form.getlist('received_qty[]')
            item_prices = request.form.getlist('unit_price[]')
            item_units = request.form.getlist('unit[]')
            item_notes = request.form.getlist('item_note[]')
            po_item_ids = request.form.getlist('po_item_id[]')

            for i in range(len(item_names)):
                name = (item_names[i] if i < len(item_names) else '').strip()
                if not name:
                    continue

                item_cd = (item_cds[i] if i < len(item_cds) else '').strip()
                spec = (item_specs[i] if i < len(item_specs) else '').strip()
                qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
                price = parse_money(item_prices[i]) if i < len(item_prices) else 0
                unit = (item_units[i] if i < len(item_units) else '').strip()
                item_note = (item_notes[i] if i < len(item_notes) else '').strip()
                linked_po_item_id = safe_int(po_item_ids[i] if i < len(po_item_ids) else '', 0) or None
                amount = qty * price

                if linked_po_item_id and not item_cd:
                    po_item = db.query(PurchaseOrderItem).get(linked_po_item_id)
                    if po_item:
                        item_cd = po_item.item_code or ''

                ri = ReceivingItem(
                    receiving_id=rcv.id,
                    po_item_id=linked_po_item_id,
                    item_cd=item_cd or None,
                    item_name=name,
                    item_spec=spec,
                    received_qty=qty,
                    unit=unit,
                    unit_price=price,
                    amount=amount,
                    note=item_note,
                )
                db.add(ri)

            # 발주서 상태 재계산
            if rcv.po_id:
                _update_po_status_on_receiving(db, rcv.po_id)

            log_activity(db, '입고관리', 'update', f'{rcv.rcv_no} 입고 수정 ({vendor.name})', ref_type='Receiving', ref_id=rcv.id)
            db.commit()

            flash(f'입고 {rcv.rcv_no}가 수정되었습니다.', 'success')
            return redirect(url_for('receiving.receiving_detail', rcv_id=rcv.id))

        # GET: 수정 폼
        po = rcv.purchase_order
        po_items = []
        if po:
            for pi in po.items:
                already = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                    ReceivingItem.po_item_id == pi.id,
                    ReceivingItem.receiving_id != rcv.id,  # 현재 입고건 제외
                ).scalar() or 0
                pi._already_received = float(already)
                pi._remaining = max(0, float(pi.quantity or 0) - float(already))
                # 현재 입고건에서의 값 (receiving_item 우선)
                current_ri = next((ri for ri in rcv.items if ri.po_item_id == pi.id), None)
                pi._current_qty = float(current_ri.received_qty) if current_ri else 0
                pi._current_note = (current_ri.note or '') if current_ri else ''
                pi._current_price = float(current_ri.unit_price) if current_ri and current_ri.unit_price else float(pi.unit_price or 0)
            po_items = po.items

        # 직접입고 품목 (po_item_id 없는 것들)
        direct_items = [ri for ri in rcv.items if not ri.po_item_id]

        return render_template(
            'receiving_edit.html',
            rcv=rcv,
            po=po,
            po_items=po_items,
            direct_items=direct_items,
        )


# ===================================================================
# 4-1. 직접입고 → 발주서 사후 연동 (다건 PO + 품목 선택 + 부분입고)
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>/link-po', methods=['POST'])
@login_required
@menu_required('receiving', write=True)
def receiving_link_po(rcv_id):
    """직접입고 건에 발주서를 사후 연동. 같은 입고건에 여러 발주서를 반복 연결할 수 있다.

    Form data:
        po_id (int)               : 연결할 발주서 (필수)
        po_item_id[] (int[])      : 이번 연결에서 처리할 발주 품목 ID 목록
        link_qty[] (float[])      : 각 품목의 이번 입고 수량 (잔량 prefill)
        link_unit_price[] (float[]): 각 품목의 단가 (PO 단가 prefill)

    동작:
        - rcv.po_id가 비어있으면 첫 연결분으로 set (legacy 표시용)
        - 선택된 각 PO 품목에 대해:
            * 직접입고 ReceivingItem 중 매칭(item_cd → name+spec → name)되는 것이 있으면
              po_item_id 세팅 (수량은 사용자가 입력한 값으로 갱신)
            * 매칭 없으면 ReceivingItem을 새로 생성 (입력 수량/단가 기준)
            * 입고수량 합계 >= 발주수량 이면 in_confirmed=True (전량입고)
              부족하면 in_confirmed=False 유지 (부분입고)
        - PO 상태 자동 재계산
    """
    po_id_form = safe_int(request.form.get('po_id'), 0) or None
    if not po_id_form:
        flash('연동할 발주서를 선택해주세요.', 'warning')
        return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))

    poi_ids = request.form.getlist('po_item_id[]')
    link_qtys = request.form.getlist('link_qty[]')
    link_prices = request.form.getlist('link_unit_price[]')

    if not poi_ids:
        flash('연결할 품목을 1개 이상 선택해주세요.', 'warning')
        return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))

    with get_db() as db:
        rcv = db.query(Receiving).options(joinedload(Receiving.items)).get(rcv_id)
        if not rcv:
            abort(404)

        po = db.query(PurchaseOrder).options(joinedload(PurchaseOrder.items)).get(po_id_form)
        if not po:
            flash('선택한 발주서를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))

        warn_vendor_mismatch = (po.vendor_id != rcv.vendor_id)

        # legacy: 첫 연결분만 rcv.po_id에 보존 (상세 페이지 일부 호환)
        if not rcv.po_id:
            rcv.po_id = po.id
        if po.contract_id and not rcv.contract_id:
            rcv.contract_id = po.contract_id

        now_dt = datetime.datetime.now()
        matched = 0
        created = 0

        for idx, poi_str in enumerate(poi_ids):
            poi_id = safe_int(poi_str, 0) or None
            if not poi_id:
                continue
            target_pi = next((pi for pi in po.items if pi.id == poi_id), None)
            if not target_pi:
                continue

            try:
                qty = float(link_qtys[idx]) if idx < len(link_qtys) and link_qtys[idx] else 0
            except (ValueError, TypeError):
                qty = 0
            if qty <= 0:
                continue

            try:
                unit_price = parse_money(link_prices[idx]) if idx < len(link_prices) and link_prices[idx] else float(target_pi.unit_price or 0)
            except (ValueError, TypeError):
                unit_price = float(target_pi.unit_price or 0)

            # 직접입고 ReceivingItem 중 매칭 시도
            ri_match = None
            pi_code = (target_pi.item_code or '').strip()
            pi_name = (target_pi.item_name or '').strip()
            pi_spec = (target_pi.item_spec or '').strip()
            for ri in rcv.items:
                if ri.po_item_id:
                    continue
                if pi_code and (ri.item_cd or '').strip() == pi_code:
                    ri_match = ri
                    break
            if not ri_match:
                for ri in rcv.items:
                    if ri.po_item_id:
                        continue
                    if (ri.item_name or '').strip() == pi_name and (ri.item_spec or '').strip() == pi_spec:
                        ri_match = ri
                        break
            if not ri_match:
                for ri in rcv.items:
                    if ri.po_item_id:
                        continue
                    if (ri.item_name or '').strip() == pi_name:
                        ri_match = ri
                        break

            if ri_match:
                ri_match.po_item_id = target_pi.id
                ri_match.received_qty = qty
                if unit_price > 0:
                    ri_match.unit_price = unit_price
                ri_match.amount = qty * (ri_match.unit_price or 0)
                if not ri_match.item_cd and pi_code:
                    ri_match.item_cd = pi_code
                matched += 1
            else:
                # 새 ReceivingItem 생성
                new_ri = ReceivingItem(
                    receiving_id=rcv.id,
                    po_item_id=target_pi.id,
                    item_cd=pi_code or None,
                    item_name=pi_name,
                    item_spec=pi_spec,
                    received_qty=qty,
                    unit=target_pi.unit or '',
                    unit_price=unit_price,
                    amount=qty * unit_price,
                )
                db.add(new_ri)
                rcv.items.append(new_ri)
                created += 1

            # 발주수량 대비 입고수량 합계 확인 → 전량이면 in_confirmed
            db.flush()
            total_rcv = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                ReceivingItem.po_item_id == target_pi.id,
            ).scalar() or 0
            if total_rcv >= (target_pi.quantity or 0) and not target_pi.in_confirmed:
                target_pi.in_confirmed = True
                target_pi.in_confirmed_at = now_dt
            elif total_rcv < (target_pi.quantity or 0) and target_pi.in_confirmed:
                # 사용자가 부족 수량으로 재조정한 케이스 → 부분입고로 되돌림
                target_pi.in_confirmed = False
                target_pi.in_confirmed_at = None

        # PO 상태 재계산
        _update_po_status_on_receiving(db, po.id)

        log_activity(
            db, '입고관리', 'link_po',
            f'{rcv.rcv_no} ↔ {po.po_no} 사후 연동 (매칭 {matched}건, 신규 {created}건)',
            ref_type='Receiving', ref_id=rcv.id,
        )
        db.commit()

    total_processed = matched + created
    msg = f'입고 {rcv.rcv_no}가 발주서 {po.po_no}에 연동되었습니다. (품목 {total_processed}건 처리)'
    if warn_vendor_mismatch:
        msg += ' ⚠️ 거래처가 다릅니다 — 확인 필요'
    flash(msg, 'success' if total_processed > 0 else 'warning')
    return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))


# ===================================================================
# 4-2. 사후 연동용 PO 품목 조회 API (잔량/단가 포함)
# ===================================================================
@receiving_bp.route('/api/receiving/po-items/<int:po_id>')
@login_required
def api_po_items_for_link(po_id):
    """사후 연동 모달 2단계: 선택된 PO의 미입고 잔량 품목 목록.

    잔량 = (발주수량 - 다른 입고건에서 이미 입고된 합계). 0이하인 품목은 제외.
    """
    rcv_id = safe_int(request.args.get('rcv_id'), 0) or None

    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items),
            joinedload(PurchaseOrder.vendor),
        ).get(po_id)
        if not po:
            return jsonify({'error': 'PO not found'}), 404

        items = []
        for pi in po.items:
            # 현재 입고건은 잔량 계산에서 제외 (재연결 가능하도록)
            q = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                ReceivingItem.po_item_id == pi.id,
            )
            if rcv_id:
                q = q.filter(ReceivingItem.receiving_id != rcv_id)
            already = float(q.scalar() or 0)
            ordered = float(pi.quantity or 0)
            remaining = max(0, ordered - already)
            if remaining <= 0 and not pi.in_confirmed:
                # 잔량 없으면서 미확인이면 표시 (드문 케이스)
                pass
            if remaining <= 0:
                continue
            items.append({
                'id': pi.id,
                'item_code': pi.item_code or '',
                'item_name': pi.item_name or '',
                'item_spec': pi.item_spec or '',
                'unit': pi.unit or '',
                'ordered': int(ordered),
                'already': int(already),
                'remaining': int(remaining),
                'unit_price': float(pi.unit_price or 0),
            })

        return jsonify({
            'po_no': po.po_no,
            'vendor_name': po.vendor.name if po.vendor else '',
            'items': items,
        })


# ===================================================================
# 5. 입고 삭제
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>/delete', methods=['POST'])
@login_required
@menu_required('receiving')
def receiving_delete(rcv_id):
    with get_db() as db:
        rcv = db.query(Receiving).options(joinedload(Receiving.items).joinedload(ReceivingItem.po_item)).get(rcv_id)
        if not rcv:
            abort(404)

        # 다건 PO 대응: 이 입고건이 연결된 모든 PO id 수집
        po_ids = set()
        if rcv.po_id:
            po_ids.add(rcv.po_id)
        for ri in rcv.items:
            if ri.po_item and ri.po_item.po_id:
                po_ids.add(ri.po_item.po_id)

        rcv_no = rcv.rcv_no
        log_activity(db, '입고관리', 'delete', f'{rcv_no} 입고 삭제', ref_type='Receiving')
        db.delete(rcv)
        db.flush()

        # 연결된 모든 발주서 상태 재계산
        for po_id in po_ids:
            _update_po_status_on_receiving(db, po_id)

        db.commit()
        flash('입고가 삭제되었습니다.', 'success')
        return redirect(url_for('receiving.receiving_list'))


# ===================================================================
# 6. 발주 vs 입고 대사 (AJAX)
# ===================================================================
@receiving_bp.route('/api/receiving/po-comparison/<int:po_id>')
@login_required
def api_po_comparison(po_id):
    """발주서 품목별 입고 수량 비교"""
    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items),
            joinedload(PurchaseOrder.vendor),
        ).get(po_id)
        if not po:
            return jsonify({'error': '발주서를 찾을 수 없습니다.'}), 404

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
                'item_name': pi.item_name,
                'item_spec': pi.item_spec or '',
                'ordered_qty': int(ordered),
                'received_qty': int(received),
                'diff': int(diff),
                'unit': pi.unit or '',
                'status': status,
            })

        return jsonify({
            'po_no': po.po_no,
            'vendor_name': po.vendor.name if po.vendor else '',
            'items': comparison,
        })


# ===================================================================
# 7. 발주서 목록 검색 API (입고 등록 시 발주서 선택)
# ===================================================================
@receiving_bp.route('/api/receiving/po-search')
@login_required
def api_po_search():
    q = (request.args.get('q') or '').strip()
    vendor_id = safe_int(request.args.get('vendor_id'), 0)
    # link 모드: 사후 연동용 — 입고완료까지 포함해서 검색 (취소만 제외)
    include_complete = (request.args.get('include_complete') in ('1', 'true', 'yes'))

    with get_db() as db:
        # ── 자재발주서 ──
        po_statuses = ['발송완료', '입고대기', '입고완료'] if include_complete else ['발송완료', '입고대기']
        po_query = db.query(PurchaseOrder).join(Vendor, PurchaseOrder.vendor_id == Vendor.id).filter(
            PurchaseOrder.status.in_(po_statuses)
        )
        if vendor_id:
            po_query = po_query.filter(PurchaseOrder.vendor_id == vendor_id)
        if q:
            like_q = f"%{q}%"
            po_query = po_query.filter(
                (PurchaseOrder.po_no.ilike(like_q)) | (Vendor.name.ilike(like_q))
            )
        pos = po_query.order_by(desc(PurchaseOrder.po_date)).limit(20).all()

        results = [{
            'id': p.id,
            'po_no': p.po_no,
            'po_date': p.po_date.strftime('%Y-%m-%d') if p.po_date else '',
            'vendor_name': p.vendor.name if p.vendor else '',
            'vendor_id': p.vendor_id,
            'status': p.status,
            'total_amount': float(p.total_amount or 0),
            'order_type': 'po',
        } for p in pos]

        # ── 가공발주서 ──
        fo_query = db.query(ProcessingOrder).join(Vendor, ProcessingOrder.vendor_id == Vendor.id).filter(
            ProcessingOrder.status.in_(['발주완료', '가공중'])
        )
        if vendor_id:
            fo_query = fo_query.filter(ProcessingOrder.vendor_id == vendor_id)
        if q:
            like_q = f"%{q}%"
            fo_query = fo_query.filter(
                (ProcessingOrder.fo_no.ilike(like_q)) | (Vendor.name.ilike(like_q))
            )
        fos = fo_query.order_by(desc(ProcessingOrder.fo_date)).limit(20).all()

        results += [{
            'id': f.id,
            'po_no': f.fo_no,
            'po_date': f.fo_date.strftime('%Y-%m-%d') if f.fo_date else '',
            'vendor_name': f.vendor.name if f.vendor else '',
            'vendor_id': f.vendor_id,
            'status': f.status,
            'total_amount': float(f.total_amount or 0),
            'order_type': 'fo',
        } for f in fos]

        return jsonify(results)


# ===================================================================
# 8. iCUBE 입고이력 상세 (AJAX JSON)
# ===================================================================
@receiving_bp.route('/api/receiving-history/<int:history_id>')
@login_required
def api_receiving_history_detail(history_id):
    import json as _json
    with get_db() as db:
        rh = db.query(ReceivingHistory).get(history_id)
        if not rh:
            return jsonify({'error': '이력을 찾을 수 없습니다.'}), 404

        items = []
        try:
            items = _json.loads(rh.items_json or '[]')
        except Exception:
            pass

        # amount를 공급가(qty * unit_price)로 재계산해서 반환
        for item in items:
            item['amount'] = round((item.get('qty', 0) or 0) * (item.get('unit_price', 0) or 0))
        supply_total = sum(i['amount'] for i in items)

        return jsonify({
            'rcv_nb': rh.icube_rcv_nb,
            'receive_date': rh.receive_date.strftime('%Y-%m-%d') if rh.receive_date else '',
            'vendor_name': rh.vendor_name or '',
            'warehouse': rh.warehouse or '',
            'remark': rh.remark or '',
            'total_amount': supply_total,
            'detail_rows': items,
        })



# ===================================================================
# 8-1. iCUBE 입고이력 단가/금액 수정
# ===================================================================
@receiving_bp.route('/api/receiving-history/<int:history_id>/update-item', methods=['POST'])
@login_required
@menu_required('receiving')
def api_update_history_item(history_id):
    """iCUBE 입고이력 품목의 단가/금액을 수정한다. (공급가 기준으로 입력받아 부가세포함가로 저장)"""
    import json as _json
    data = request.get_json(silent=True) or {}
    item_index = data.get('index')
    new_unit_price = data.get('unit_price')
    new_qty = data.get('qty')

    if item_index is None:
        return jsonify({'error': '품목 인덱스가 필요합니다.'}), 400

    with get_db() as db:
        rh = db.query(ReceivingHistory).get(history_id)
        if not rh:
            return jsonify({'error': '이력을 찾을 수 없습니다.'}), 404

        try:
            items = _json.loads(rh.items_json or '[]')
        except Exception:
            return jsonify({'error': 'items_json 파싱 실패'}), 500

        idx = int(item_index)
        if idx < 0 or idx >= len(items):
            return jsonify({'error': '잘못된 품목 인덱스'}), 400

        item = items[idx]
        if new_unit_price is not None:
            item['unit_price'] = float(str(new_unit_price).replace(',', ''))
        if new_qty is not None:
            item['qty'] = float(str(new_qty).replace(',', ''))

        qty = item.get('qty', 0) or 0
        up = item.get('unit_price', 0) or 0
        item['amount'] = round(qty * up)

        old_up = float(str(data.get('_old_unit_price', up)).replace(',', '')) if data.get('_old_unit_price') else None
        rh.items_json = _json.dumps(items, ensure_ascii=False)
        rh.total_amount = sum(i.get('amount', 0) or 0 for i in items)

        item_name = item.get('item_name', '')
        log_msg = f'{rh.icube_rcv_nb} iCUBE 입고 단가수정 [{item_name}]'
        if new_unit_price is not None:
            log_msg += f' 단가: {old_up or "?"} → {up}'
        if new_qty is not None:
            log_msg += f' 수량: {qty}'
        log_activity(db, '입고관리', 'update', log_msg, ref_type='ReceivingHistory', ref_id=rh.id)
        db.commit()

        return jsonify({
            'ok': True,
            'unit_price': round(item['unit_price']),
            'amount': round(item['amount']),
            'total_amount': round(rh.total_amount),
        })


# ===================================================================
# 9. 입고예정 — 입고확인 AJAX
# ===================================================================
@receiving_bp.route('/api/receiving/confirm-expected/<int:poi_id>', methods=['POST'])
@login_required
@menu_required('receiving')
def api_confirm_expected(poi_id):
    """입고예정 목록에서 입고확인 처리 (PurchaseOrderItem.in_confirmed = True)"""
    import datetime as _dt
    from modules.history_board import append_history_log, get_user_display_name
    with get_db() as db:
        poi = db.query(PurchaseOrderItem).get(poi_id)
        if not poi:
            return jsonify({'ok': False, 'error': '품목을 찾을 수 없습니다.'}), 404
        poi.in_confirmed = True
        poi.in_confirmed_at = _dt.datetime.now()

        # 재고 반영: item_id 직접 연결 또는 bom_item → item 연결
        linked_item = None
        if poi.item_id:
            linked_item = db.query(Item).get(poi.item_id)
        elif poi.bom_item_id:
            bi = db.query(BomItem).get(poi.bom_item_id)
            if bi and bi.item_id:
                linked_item = db.query(Item).get(bi.item_id)

        confirm_qty = poi.quantity or 0
        if linked_item and confirm_qty > 0:
            record_stock_movement(
                db, linked_item.id,
                movement_type='IN_RECEIVING',
                quantity=confirm_qty,
                reference_type='purchase_order_item',
                reference_id=poi.id,
                unit_price=poi.unit_price,
                note=f'입고확인 (발주품목 #{poi.id})',
            )
            if poi.unit_price and poi.unit_price > 0:
                linked_item.last_unit_price = poi.unit_price

        # 해당 발주서의 모든 품목이 확인되면 발주서 상태 변경
        po = poi.purchase_order
        if po:
            all_confirmed = all(item.in_confirmed for item in po.items if item.id != poi.id)
            if all_confirmed:
                po.status = '입고완료'

            # 연결된 MaterialOrder도 동기화
            linked_mo = db.query(MaterialOrder).filter(
                MaterialOrder.po_item_id == poi.id,
            ).first()
            if linked_mo:
                linked_mo.in_confirmed = True
                linked_mo.in_confirmed_at = _dt.datetime.now()
                linked_mo.order_status = '입고완료'

            project_id = po.project_id
            if project_id:
                append_history_log(
                    db,
                    project_id=project_id,
                    user_name=get_user_display_name('시스템'),
                    content=f"입고확인: {poi.item_name} ({confirm_qty}개) → 재고반영{'✓' if linked_item else '✗(품목미연결)'}",
                    scope='material',
                    kind='system'
                )
        log_activity(db, '입고관리', 'confirm', f'{poi.item_name} 입고확인 ({confirm_qty}개)', ref_type='Receiving')

        # 알림: 자재 입고 완료
        try:
            from modules.notification_engine import notify
            from modules.models import Contract
            _proj = po.project if po else None
            _proj_name = _proj.temp_name if _proj else '미지정'
            _c = db.query(Contract).filter(Contract.project_id == po.project_id).first() if po and po.project_id else None
            notify(db, 'material.received', {
                'material_name': poi.item_name or f'자재#{poi.id}',
                'contract_name': _c.contract_name if _c and _c.contract_name else _proj_name,
                'project_name': _proj_name,
            })
        except Exception:
            pass

        db.commit()
    return jsonify({'ok': True})


# ===================================================================
# 10. 입고예정 — 입고예정일 인라인 수정 AJAX
# ===================================================================
@receiving_bp.route('/api/receiving/update-expected-date/<int:poi_id>', methods=['POST'])
@login_required
@menu_required('receiving')
def api_update_expected_date(poi_id):
    """입고예정일 인라인 편집 저장"""
    import datetime as _dt
    from modules.history_board import append_history_log, get_user_display_name

    with get_db() as db:
        poi = db.query(PurchaseOrderItem).get(poi_id)
        if not poi:
            return jsonify({'ok': False, 'message': '품목을 찾을 수 없습니다.'}), 404

        data = request.get_json(silent=True) or {}
        date_str = (data.get('expected_in_date') or '').strip()

        if date_str:
            try:
                new_date = _dt.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'ok': False, 'message': '날짜 형식 오류'}), 400
            poi.expected_in_date = new_date
        else:
            poi.expected_in_date = None

        # 연결된 MaterialOrder도 동기화
        linked_mo = db.query(MaterialOrder).filter(
            MaterialOrder.po_item_id == poi.id,
        ).first()
        if linked_mo:
            linked_mo.expected_in_date = poi.expected_in_date

        po = poi.purchase_order
        project_id = po.project_id if po else None
        if project_id:
            append_history_log(
                db,
                project_id=project_id,
                user_name=get_user_display_name('시스템'),
                content=f"입고예정일 변경: {poi.item_name} → {date_str or '미정'}",
                scope='material',
                kind='system'
            )
        log_activity(db, '입고관리', 'update', f'{poi.item_name} 입고예정일 변경 → {date_str or "미정"}', ref_type='Receiving')
        db.commit()

        today = _dt.date.today()
        if poi.expected_in_date:
            d = (poi.expected_in_date - today).days
            dday_state = 'overdue' if d < 0 else 'today' if d == 0 else 'week' if d <= 7 else 'ok'
        else:
            d = None
            dday_state = 'unknown'

        return jsonify({'ok': True, 'dday': d, 'dday_state': dday_state})


# ===================================================================
# 월별 거래처 마감
# ===================================================================
@receiving_bp.route('/receiving/monthly')
@login_required
def receiving_monthly():
    """월별 거래처 입고 마감 — 해당월 입고 거래처별 정리"""
    today = datetime.date.today()
    year = safe_int(request.args.get('year'), today.year)
    month = safe_int(request.args.get('month'), today.month)

    with get_db() as db:
        # (A) 신규 입고
        new_rcvs = db.query(Receiving).join(Vendor).options(
            joinedload(Receiving.items).joinedload(ReceivingItem.po_item),
            joinedload(Receiving.vendor),
        ).filter(
            extract('year', Receiving.rcv_date) == year,
            extract('month', Receiving.rcv_date) == month,
        ).order_by(Receiving.vendor_id, Receiving.rcv_date).all()

        # (B) iCUBE 입고
        icube_rcvs = db.query(ReceivingHistory).filter(
            extract('year', ReceivingHistory.receive_date) == year,
            extract('month', ReceivingHistory.receive_date) == month,
        ).order_by(ReceivingHistory.vendor_tr_cd, ReceivingHistory.receive_date).all()

        # vendor_tr_cd → Vendor 매핑 (iCUBE용)
        icube_tr_cds = list({r.vendor_tr_cd for r in icube_rcvs if r.vendor_tr_cd})
        vendor_map = {}
        if icube_tr_cds:
            vendors = db.query(Vendor).filter(Vendor.icube_tr_cd.in_(icube_tr_cds)).all()
            vendor_map = {v.icube_tr_cd: v for v in vendors}

        # 거래처별로 그룹핑 (key: vendor_id 또는 vendor_tr_cd)
        from collections import OrderedDict
        vendor_groups = OrderedDict()

        # 신규 입고 → 그룹핑
        for rcv in new_rcvs:
            vid = rcv.vendor_id
            if vid not in vendor_groups:
                v = rcv.vendor
                vendor_groups[vid] = {
                    'vendor_name': v.name if v else '',
                    'business_no': v.business_no if v else '',
                    'tel': v.tel if v else '',
                    'rows': [],
                    'total': 0,
                }
            for ri in rcv.items:
                spec = (ri.item_spec or '').strip()
                note = (ri.note or '').strip()
                if not spec and note:
                    spec = note
                    note = ''
                amt = ri.amount or 0
                item_cd = ri.item_cd or ''
                if not item_cd and ri.po_item:
                    item_cd = ri.po_item.item_code or ''
                vendor_groups[vid]['rows'].append({
                    'rcv_no': rcv.rcv_no,
                    'rcv_date': rcv.rcv_date.strftime('%m-%d') if rcv.rcv_date else '',
                    'item_cd': item_cd,
                    'item_name': ri.item_name or '',
                    'spec': spec,
                    'qty': ri.received_qty or 0,
                    'unit': ri.unit or '',
                    'unit_price': ri.unit_price or 0,
                    'amount': amt,
                    'remark': note,
                })
                vendor_groups[vid]['total'] += amt

        # iCUBE 입고 → 그룹핑
        for rh in icube_rcvs:
            tr_cd = rh.vendor_tr_cd or ''
            v_obj = vendor_map.get(tr_cd)
            # vendor_id가 있으면 기존 그룹에 합치기
            vid = v_obj.id if v_obj else f'icube_{tr_cd}'
            if vid not in vendor_groups:
                vendor_groups[vid] = {
                    'vendor_name': v_obj.name if v_obj else (rh.vendor_name or tr_cd),
                    'business_no': v_obj.business_no if v_obj else '',
                    'tel': v_obj.tel if v_obj else '',
                    'rows': [],
                    'total': 0,
                }
            try:
                items = _json.loads(rh.items_json or '[]')
            except Exception:
                items = []
            for item in items:
                raw_up = item.get('unit_price', 0) or 0
                raw_amt = item.get('amount', 0) or 0
                supply_up = round(raw_up)
                supply_amt = round(raw_up * (item.get('qty', 0) or 0))
                vendor_groups[vid]['rows'].append({
                    'rcv_no': rh.icube_rcv_nb,
                    'rcv_date': rh.receive_date.strftime('%m-%d') if rh.receive_date else '',
                    'item_cd': item.get('item_cd', ''),
                    'item_name': item.get('item_name', ''),
                    'spec': item.get('spec', ''),
                    'qty': item.get('qty', 0),
                    'unit': item.get('unit', ''),
                    'unit_price': supply_up,
                    'amount': supply_amt,
                    'remark': item.get('remark', ''),
                })
                vendor_groups[vid]['total'] += supply_amt

        # 거래처명 기준 정렬
        sorted_groups = sorted(vendor_groups.values(), key=lambda g: g['vendor_name'])

        # 전체 합계
        grand_total = sum(g['total'] for g in sorted_groups)
        total_items = sum(len(g['rows']) for g in sorted_groups)

        return render_template(
            'receiving_monthly.html',
            year=year,
            month=month,
            vendor_groups=sorted_groups,
            vendor_count=len(sorted_groups),
            grand_total=grand_total,
            total_items=total_items,
        )
