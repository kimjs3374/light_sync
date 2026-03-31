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
from sqlalchemy import case, desc, func
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    Vendor, PurchaseOrder, PurchaseOrderItem, MaterialOrder,
    Receiving, ReceivingItem, ReceivingHistory,
    Item, BomItem, Contract, Project,
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
        from modules.models import ProcessingOrder as _FO
        query = db.query(Receiving).join(Vendor).outerjoin(
            ReceivingItem, ReceivingItem.receiving_id == Receiving.id
        ).outerjoin(_FO, _FO.id == Receiving.fo_id)

        if q:
            # 공백으로 분리해서 AND 조건: "태영스텐 10t" → *태영스텐* AND *10t*
            # 거래처명+입고번호+품명+규격 합쳐서 검색
            tokens = [t.strip() for t in q.split() if t.strip()]
            for token in tokens:
                like_t = f"%{token}%"
                query = query.filter(
                    (Vendor.name.ilike(like_t)) |
                    (Receiving.rcv_no.ilike(like_t)) |
                    (ReceivingItem.item_name.ilike(like_t)) |
                    (ReceivingItem.item_spec.ilike(like_t))
                )
            query = query.distinct()
        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        receivings_raw = query.order_by(desc(Receiving.rcv_date), desc(Receiving.id)) \
                              .offset(offset).limit(per_page).all()

        # 자체 입고를 플랫 구조로 변환 (검색어 있으면 매칭 품목만 필터)
        tokens = [t.strip().lower() for t in q.split() if t.strip()] if q else []
        receivings = []
        for rcv in receivings_raw:
            detail_rows = []
            for ri in rcv.items:
                spec = (ri.item_spec or '').strip()
                note = (ri.note or '').strip()
                if not spec and note:
                    spec = note
                    note = ''
                # 품번: ReceivingItem 우선, 없으면 PO 품목에서
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
                # 검색어가 있으면 품목 레벨에서 매칭 필터
                # 거래처명은 입고건 검색에만 사용, 품목 필터는 품명+규격으로만
                if tokens:
                    item_text = f"{ri.item_name or ''} {spec}".lower()
                    vendor_text = (rcv.vendor.name or '').lower()
                    # 각 토큰이 거래처명 또는 품목텍스트에 있는지 체크
                    # 단, 품목텍스트에 하나도 안 걸리는 토큰이 전부 거래처에만 있으면 → 거래처 필터일 뿐이므로 통과
                    item_tokens = [t for t in tokens if t not in vendor_text]
                    # item_tokens: 거래처명에 없는 토큰들 → 이것들은 반드시 품명+규격에 있어야 함
                    row['_matched'] = all(t in item_text for t in item_tokens)
                detail_rows.append(row)
            # 검색 시 매칭 품목만 표시
            if tokens:
                detail_rows = [r for r in detail_rows if r.get('_matched')]
                if not detail_rows:
                    continue
            receivings.append({
                'id': rcv.id,
                'rcv_no': rcv.rcv_no,
                'rcv_date': rcv.rcv_date,
                'vendor_name': rcv.vendor.name if rcv.vendor else '',
                'po_no': rcv.purchase_order.po_no if rcv.purchase_order else '',
                'po_id': rcv.po_id,
                'fo_no': rcv.processing_order.fo_no if getattr(rcv, 'processing_order', None) else '',
                'fo_id': rcv.fo_id,
                'status': rcv.status,
                'detail_rows': detail_rows,
            })

        # 통계
        stats = {
            'total': db.query(func.count(Receiving.id)).scalar() or 0,
        }

        # iCUBE 기존 입고이력
        hist_query = db.query(ReceivingHistory)
        if q:
            tokens = [t.strip() for t in q.split() if t.strip()]
            for token in tokens:
                like_t = f"%{token}%"
                hist_query = hist_query.filter(
                    (ReceivingHistory.vendor_name.ilike(like_t)) |
                    (ReceivingHistory.icube_rcv_nb.ilike(like_t)) |
                    (ReceivingHistory.items_json.ilike(like_t))
                )
        history_count = hist_query.count() if not status else 0
        hist_page = safe_int(request.args.get('hp'), 1)
        hist_per_page = 50
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
            # 검색어 있으면 매칭 품목만 필터
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
            history_items.append({
                'id': rh.id,
                'icube_rcv_nb': rh.icube_rcv_nb,
                'receive_date': rh.receive_date,
                'vendor_name': rh.vendor_name or '',
                'warehouse': rh.warehouse or '',
                'total_amount': rh.total_amount or 0,
                'detail_rows': items,
            })

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
            history_items=history_items,
            history_count=history_count,
            hist_page=hist_page,
            hist_total_pages=hist_total_pages,
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
            new_items = []

            for i in range(len(item_names)):
                name = (item_names[i] if i < len(item_names) else '').strip()
                if not name:
                    continue

                item_cd = (item_cds[i] if i < len(item_cds) else '').strip()
                spec = (item_specs[i] if i < len(item_specs) else '').strip()
                qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
                price = float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0
                unit = (item_units[i] if i < len(item_units) else '').strip()
                item_note = (item_notes[i] if i < len(item_notes) else '').strip()
                linked_po_item_id = safe_int(po_item_ids[i] if i < len(po_item_ids) else '', 0) or None
                amount = qty * price

                # 발주 품목 연결 시 품번 자동 가져오기
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

            # 발주서 상태 업데이트 + po_item.in_confirmed 동기화
            if po_id:
                _update_po_status_on_receiving(db, po_id)
                # 발주 품목별 입고 완료 여부 반영
                po_obj = db.query(PurchaseOrder).options(joinedload(PurchaseOrder.items)).get(po_id)
                if po_obj:
                    now_dt = datetime.datetime.now()
                    for po_item in po_obj.items:
                        total_rcv = db.query(func.coalesce(func.sum(ReceivingItem.received_qty), 0)).filter(
                            ReceivingItem.po_item_id == po_item.id,
                        ).scalar() or 0
                        if total_rcv >= (po_item.quantity or 0) and not po_item.in_confirmed:
                            po_item.in_confirmed = True
                            po_item.in_confirmed_at = now_dt

            log_activity(db, '입고관리', 'create', f'{rcv.rcv_no} 입고 등록 ({vendor.name})', ref_type='Receiving', ref_id=rcv.id)
            db.commit()

            # 알림 메시지
            flash(f'입고 {rcv.rcv_no}가 등록되었습니다.', 'success')
            for ni in new_items:
                flash(f'신규 품목 자동등록: {ni}', 'info')
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

            # 기존 품목 삭제 후 재등록
            for old_item in list(rcv.items):
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
                price = float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0
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
                # 현재 입고건에서의 수량
                current_ri = next((ri for ri in rcv.items if ri.po_item_id == pi.id), None)
                pi._current_qty = float(current_ri.received_qty) if current_ri else 0
                pi._current_note = current_ri.note or '' if current_ri else ''
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
# 5. 입고 삭제
# ===================================================================
@receiving_bp.route('/receiving/<int:rcv_id>/delete', methods=['POST'])
@login_required
@menu_required('receiving')
def receiving_delete(rcv_id):
    with get_db() as db:
        rcv = db.query(Receiving).get(rcv_id)
        if not rcv:
            abort(404)

        po_id = rcv.po_id
        rcv_no = rcv.rcv_no
        log_activity(db, '입고관리', 'delete', f'{rcv_no} 입고 삭제', ref_type='Receiving')
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
