"""
입고관리 Blueprint (Phase 3).

- 입고 목록/등록/상세
- 발주서 기반 입고 / 직접 입고
- 발주 vs 입고 대사
- 거래명세서 자동 생성
"""

import datetime
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session,
)
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    Vendor, PurchaseOrder, PurchaseOrderItem, MaterialOrder,
    Receiving, ReceivingItem, ReceivingHistory,
    RCV_STATUS_CHOICES, Item, BomItem,
)

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
    """발주서 전체 입고 시 상태 자동 전환 + MaterialOrder 입고완료"""
    if not po_id:
        return

    po = db.query(PurchaseOrder).get(po_id)
    if not po:
        return

    # 발주 품목별 입고 수량 합산
    for po_item in po.items:
        total_received = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
            ReceivingItem.po_item_id == po_item.id,
        ).scalar() or 0

        # 아직 미입고 품목이 있으면 리턴
        if total_received < (po_item.quantity or 0):
            # 일부 입고 상태
            if po.status not in ('입고완료', '취소'):
                po.status = '입고대기'
            return

    # 모든 품목 입고 완료
    po.status = '입고완료'

    # MaterialOrder 입고완료 연동 + 입고 시 stock_qty 증가 (FR-07)
    material_orders = db.query(MaterialOrder).filter(
        MaterialOrder.po_id == po_id,
    ).all()
    for mo in material_orders:
        mo.order_status = '입고완료'
        mo.in_confirmed = True
        mo.in_confirmed_at = datetime.datetime.now()

    # 발주 품목별 입고 수량으로 Item.stock_qty 증가
    for po_item in po.items:
        total_received = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
            ReceivingItem.po_item_id == po_item.id,
        ).scalar() or 0

        # BomItem -> Item 연결이 있으면 stock_qty 증가
        if po_item.bom_item_id:
            bi = db.query(BomItem).get(po_item.bom_item_id)
            if bi and bi.item_id:
                linked_item = db.query(Item).get(bi.item_id)
                if linked_item:
                    linked_item.stock_qty = (linked_item.stock_qty or 0) + total_received


# ===================================================================
# 1. 입고 목록
# ===================================================================
@receiving_bp.route('/receiving')
@login_required
def receiving_list():
    q = (request.args.get('q') or '').strip()
    status = (request.args.get('status') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        query = db.query(Receiving).join(Vendor)

        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (Vendor.name.ilike(like_q)) | (Receiving.rcv_no.ilike(like_q))
            )
        if status and status in RCV_STATUS_CHOICES:
            query = query.filter(Receiving.status == status)

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        receivings_raw = query.order_by(desc(Receiving.rcv_date), desc(Receiving.id)) \
                              .offset(offset).limit(per_page).all()

        # 자체 입고를 플랫 구조로 변환 (기존 이력과 동일 포맷)
        receivings = []
        for rcv in receivings_raw:
            detail_rows = []
            for ri in rcv.items:
                spec = (ri.item_spec or '').strip()
                note = (ri.note or '').strip()
                if not spec and note:
                    spec = note
                    note = ''
                detail_rows.append({
                    'item_name': ri.item_name or '',
                    'spec': spec,
                    'qty': ri.received_qty or 0,
                    'unit': ri.unit or '',
                    'unit_price': ri.unit_price or 0,
                    'amount': ri.amount or 0,
                    'remark': note,
                })
            receivings.append({
                'id': rcv.id,
                'rcv_no': rcv.rcv_no,
                'rcv_date': rcv.rcv_date,
                'vendor_name': rcv.vendor.name if rcv.vendor else '',
                'po_no': rcv.purchase_order.po_no if rcv.purchase_order else '',
                'po_id': rcv.po_id,
                'status': rcv.status,
                'detail_rows': detail_rows,
            })

        # 통계
        stats = {
            'total': db.query(func.count(Receiving.id)).scalar() or 0,
            'pending': db.query(func.count(Receiving.id)).filter(Receiving.status == '검수대기').scalar() or 0,
            'completed': db.query(func.count(Receiving.id)).filter(Receiving.status == '검수완료').scalar() or 0,
            'returned': db.query(func.count(Receiving.id)).filter(Receiving.status == '반품').scalar() or 0,
        }

        # iCUBE 기존 입고이력
        hist_query = db.query(ReceivingHistory)
        if q:
            like_q = f"%{q}%"
            hist_query = hist_query.filter(
                (ReceivingHistory.vendor_name.ilike(like_q)) |
                (ReceivingHistory.icube_rcv_nb.ilike(like_q)) |
                (ReceivingHistory.items_json.ilike(like_q))
            )
        history_count = hist_query.count() if not status else 0
        hist_page = safe_int(request.args.get('hp'), 1)
        hist_per_page = 30
        hist_offset = (hist_page - 1) * hist_per_page
        history_raw = hist_query.order_by(desc(ReceivingHistory.receive_date)) \
                                .offset(hist_offset).limit(hist_per_page).all() if not status else []
        hist_total_pages = (history_count + hist_per_page - 1) // hist_per_page if history_count else 0

        # items_json 미리 파싱
        import json as _json
        history_items = []
        for rh in history_raw:
            try:
                items = _json.loads(rh.items_json or '[]')
            except Exception:
                items = []
            # 규격 빈칸 + 비고 있으면 → 비고를 규격으로 이동
            for item in items:
                spec = (item.get('spec') or '').strip()
                remark = (item.get('remark') or '').strip()
                if not spec and remark:
                    item['spec'] = remark
                    item['remark'] = ''
            history_items.append({
                'id': rh.id,
                'icube_rcv_nb': rh.icube_rcv_nb,
                'receive_date': rh.receive_date,
                'vendor_name': rh.vendor_name or '',
                'warehouse': rh.warehouse or '',
                'total_amount': rh.total_amount or 0,
                'detail_rows': items,
            })

        return render_template(
            'receiving_list.html',
            receivings=receivings,
            history_items=history_items,
            history_count=history_count,
            hist_page=hist_page,
            hist_total_pages=hist_total_pages,
            pagination=pagination,
            stats=stats,
            filters={'q': q, 'status': status},
            status_choices=RCV_STATUS_CHOICES,
            fmt_money=_fmt_money,
        )


# ===================================================================
# 2. 입고 등록
# ===================================================================
@receiving_bp.route('/receiving/create', methods=['GET', 'POST'])
@login_required
def receiving_create():
    with get_db() as db:
        if request.method == 'POST':
            vendor_id = safe_int(request.form.get('vendor_id'), 0)
            po_id = safe_int(request.form.get('po_id'), 0) or None
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

            # 발주서 연결 시 contract_id 자동 설정
            contract_id = None
            if po_id:
                po = db.query(PurchaseOrder).get(po_id)
                if po:
                    contract_id = po.contract_id

            rcv = Receiving(
                rcv_no=_generate_rcv_no(db),
                rcv_date=rcv_date,
                vendor_id=vendor_id,
                po_id=po_id,
                contract_id=contract_id,
                status='검수대기',
                note=note,
                created_by=session.get('user_id'),
            )
            db.add(rcv)
            db.flush()

            # 품목 추가
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

                spec = (item_specs[i] if i < len(item_specs) else '').strip()
                qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
                price = float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0
                unit = (item_units[i] if i < len(item_units) else '').strip()
                item_note = (item_notes[i] if i < len(item_notes) else '').strip()
                linked_po_item_id = safe_int(po_item_ids[i] if i < len(po_item_ids) else '', 0) or None
                amount = qty * price

                ri = ReceivingItem(
                    receiving_id=rcv.id,
                    po_item_id=linked_po_item_id,
                    item_name=name,
                    item_spec=spec,
                    received_qty=qty,
                    unit=unit,
                    unit_price=price,
                    amount=amount,
                    note=item_note,
                )
                db.add(ri)

            # 발주서 상태 업데이트
            if po_id:
                _update_po_status_on_receiving(db, po_id)

            db.commit()
            flash(f'입고 {rcv.rcv_no}가 등록되었습니다.', 'success')
            return redirect(url_for('receiving.receiving_detail', rcv_id=rcv.id))

        # GET: 폼 표시
        # 발주서 기반 입고 시 po_id 파라미터로 전달
        po_id = safe_int(request.args.get('po_id'), 0) or None
        po = None
        po_items = []
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
                po_items = po.items

        return render_template(
            'receiving_create.html',
            po=po,
            po_items=po_items,
        )


# ===================================================================
# 3. 입고 상세
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>')
@login_required
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
            status_choices=RCV_STATUS_CHOICES,
        )


# ===================================================================
# 4. 입고 상태 변경
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>/status', methods=['POST'])
@login_required
def receiving_change_status(rcv_id):
    with get_db() as db:
        rcv = db.query(Receiving).get(rcv_id)
        if not rcv:
            abort(404)

        new_status = request.form.get('status', '')
        if new_status not in RCV_STATUS_CHOICES:
            flash('유효하지 않은 상태입니다.', 'warning')
            return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))

        rcv.status = new_status

        # 반품 처리 시 발주서 상태 재계산
        if new_status == '반품' and rcv.po_id:
            _update_po_status_on_receiving(db, rcv.po_id)

        db.commit()
        flash(f'상태가 "{new_status}"로 변경되었습니다.', 'success')
        return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))


# ===================================================================
# 5. 입고 삭제
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>/delete', methods=['POST'])
@login_required
def receiving_delete(rcv_id):
    with get_db() as db:
        rcv = db.query(Receiving).get(rcv_id)
        if not rcv:
            abort(404)

        if rcv.status == '검수완료':
            flash('검수완료 상태의 입고는 삭제할 수 없습니다.', 'warning')
            return redirect(url_for('receiving.receiving_detail', rcv_id=rcv_id))

        po_id = rcv.po_id
        db.delete(rcv)
        db.flush()

        # 발주서 상태 재계산
        if po_id:
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
                'item_name': pi.item_name,
                'item_spec': pi.item_spec or '',
                'ordered_qty': ordered,
                'received_qty': float(received),
                'diff': diff,
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

    with get_db() as db:
        query = db.query(PurchaseOrder).join(Vendor).filter(
            PurchaseOrder.status.in_(['발송완료', '입고대기'])
        )
        if vendor_id:
            query = query.filter(PurchaseOrder.vendor_id == vendor_id)
        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (PurchaseOrder.po_no.ilike(like_q)) | (Vendor.name.ilike(like_q))
            )

        pos = query.order_by(desc(PurchaseOrder.po_date)).limit(20).all()
        return jsonify([{
            'id': p.id,
            'po_no': p.po_no,
            'po_date': p.po_date.strftime('%Y-%m-%d') if p.po_date else '',
            'vendor_name': p.vendor.name if p.vendor else '',
            'vendor_id': p.vendor_id,
            'status': p.status,
            'total_amount': float(p.total_amount or 0),
        } for p in pos])


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

        return jsonify({
            'rcv_nb': rh.icube_rcv_nb,
            'receive_date': rh.receive_date.strftime('%Y-%m-%d') if rh.receive_date else '',
            'vendor_name': rh.vendor_name or '',
            'warehouse': rh.warehouse or '',
            'remark': rh.remark or '',
            'total_amount': float(rh.total_amount or 0),
            'detail_rows': items,
        })
