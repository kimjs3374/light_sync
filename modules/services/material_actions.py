import datetime
import logging

from modules.utils import safe_int, parse_date, date_to_dt_start
from modules.models import (
    MaterialOrder, HistoryLog, Item, BomItem, BomHeader,
    Vendor, PurchaseOrder, PurchaseOrderItem, Contract,
)
from modules.history_board import append_history_log
from modules.services.inventory_utils import record_stock_movement
from sqlalchemy import desc

logger = logging.getLogger(__name__)


def handle_sync_material_orders(db, project, form, current_user, **ctx):
    sync_fn = ctx['sync_fn']
    refresh_fn = ctx['refresh_fn']
    sync_fn(db, project.id)
    refresh_fn(db, project.id)
    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템 🤖',
        content=f"{current_user}님이 자재 자동생성/동기화를 실행했습니다.",
        scope='material',
        kind='system'
    )
    return {'flash': ('자재 자동생성/동기화가 완료되었습니다.', 'success')}


def handle_update_material_order(db, project, form, current_user, **ctx):
    refresh_fn = ctx['refresh_fn']
    order_id = safe_int(form.get('material_order_id'))
    order = db.query(MaterialOrder).get(order_id)
    if not (order and order.project_id == project.id):
        return {}

    old_status = order.order_status or '발주대기'
    old_out = order.outsourcing_status or '-'

    order.order_date = parse_date(form.get('order_date'))
    order.expected_in_date = parse_date(form.get('expected_in_date'))
    in_confirmed_date = parse_date(form.get('in_confirmed_date'))
    order.note = form.get('note')

    new_status = form.get('order_status') or old_status
    if new_status in ('발주대기', '발주완료', '입고완료', '재고이용'):
        order.order_status = new_status

    if order.is_outsourcing:
        new_out = form.get('outsourcing_status')
        if new_out in ('외주입고대기', '외주입고', '가공중', '본사입고완료'):
            order.outsourcing_status = new_out
            if new_out == '본사입고완료':
                order.order_status = '입고완료'
                order.in_confirmed = True
                order.in_confirmed_at = datetime.datetime.now()

    in_confirmed = form.get('in_confirmed') == 'on'
    order.in_confirmed = in_confirmed
    if in_confirmed:
        order.order_status = '입고완료'
        if in_confirmed_date:
            order.in_confirmed_at = date_to_dt_start(in_confirmed_date)
        elif not order.in_confirmed_at:
            order.in_confirmed_at = datetime.datetime.now()
    else:
        order.in_confirmed_at = None

    if order.order_status == '발주완료' and not order.order_date:
        order.order_date = datetime.date.today()

    append_history_log(
        db,
        project_id=order.project_id,
        user_name='시스템 🤖',
        content=(
            f"{current_user}님이 자재상태 수정: {order.item_model_name or '-'} / {order.material_name}"
            f"\n상태: {old_status} ➡️ {order.order_status}"
            f"\n외주: {old_out} ➡️ {order.outsourcing_status or '-'}"
        ),
        scope='material',
        kind='system'
    )
    refresh_fn(db, project.id)
    return {'flash': ('자재 정보가 저장되었습니다.', 'success')}


def handle_bulk_update_material_orders(db, project, form, current_user, **ctx):
    refresh_fn = ctx['refresh_fn']
    raw_ids = form.getlist('selected_order_ids')
    selected_ids = []
    for v in raw_ids:
        if (v or '').isdigit():
            selected_ids.append(int(v))
    selected_ids = sorted(set(selected_ids))

    if not selected_ids:
        return {'flash': ('일괄적용할 자재를 선택해 주세요.', 'warning')}

    orders = db.query(MaterialOrder).filter(
        MaterialOrder.project_id == project.id,
        MaterialOrder.id.in_(selected_ids)
    ).all()

    bulk_status = form.get('bulk_order_status') or ''
    bulk_order_date = parse_date(form.get('bulk_order_date'))
    bulk_expected_in_date = parse_date(form.get('bulk_expected_in_date'))
    bulk_in_confirmed = form.get('bulk_in_confirmed') or ''
    bulk_in_confirmed_date = parse_date(form.get('bulk_in_confirmed_date'))
    bulk_outsourcing_status = form.get('bulk_outsourcing_status') or ''
    bulk_note_mode = form.get('bulk_note_mode') or 'append'
    bulk_note_text = (form.get('bulk_note_text') or '').strip()

    valid_statuses = {'발주대기', '발주완료', '입고완료', '재고이용'}
    valid_out_statuses = {'외주입고대기', '외주입고', '가공중', '본사입고완료'}

    updated_count = 0
    skip_outsource_count = 0
    for order in orders:
        changed = False

        if bulk_status in valid_statuses and order.order_status != bulk_status:
            order.order_status = bulk_status
            changed = True

        if bulk_order_date and order.order_date != bulk_order_date:
            order.order_date = bulk_order_date
            changed = True

        if bulk_expected_in_date and order.expected_in_date != bulk_expected_in_date:
            order.expected_in_date = bulk_expected_in_date
            changed = True

        if bulk_outsourcing_status in valid_out_statuses:
            if order.is_outsourcing:
                if order.outsourcing_status != bulk_outsourcing_status:
                    order.outsourcing_status = bulk_outsourcing_status
                    changed = True
                if bulk_outsourcing_status == '본사입고완료':
                    if order.order_status != '입고완료':
                        order.order_status = '입고완료'
                        changed = True
                    if not order.in_confirmed:
                        order.in_confirmed = True
                        changed = True
                    if not order.in_confirmed_at:
                        order.in_confirmed_at = datetime.datetime.now()
                        changed = True
            else:
                skip_outsource_count += 1

        if bulk_in_confirmed == 'yes':
            if not order.in_confirmed:
                order.in_confirmed = True
                changed = True
            if order.order_status != '입고완료':
                order.order_status = '입고완료'
                changed = True
            target_confirm_dt = date_to_dt_start(bulk_in_confirmed_date) if bulk_in_confirmed_date else datetime.datetime.now()
            if order.in_confirmed_at != target_confirm_dt:
                order.in_confirmed_at = target_confirm_dt
                changed = True
        elif bulk_in_confirmed == 'no':
            if order.in_confirmed:
                order.in_confirmed = False
                changed = True
            if order.in_confirmed_at is not None:
                order.in_confirmed_at = None
                changed = True

        if bulk_note_text:
            if bulk_note_mode == 'replace':
                if (order.note or '') != bulk_note_text:
                    order.note = bulk_note_text
                    changed = True
            else:
                merged = f"{order.note}\n{bulk_note_text}".strip() if order.note else bulk_note_text
                if (order.note or '') != merged:
                    order.note = merged
                    changed = True

        if order.order_status == '발주완료' and not order.order_date:
            order.order_date = datetime.date.today()
            changed = True

        if changed:
            updated_count += 1

    if updated_count:
        refresh_fn(db, project.id)
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템 🤖',
            content=(
                f"{current_user}님이 자재 {updated_count}건 일괄적용"
                f" (선택 {len(selected_ids)}건"
                f"{', 외주미대상 ' + str(skip_outsource_count) + '건 스킵' if skip_outsource_count else ''})"
            ),
            scope='material',
            kind='system'
        )
        return {'flash': (f'일괄적용 완료: {updated_count}건 반영', 'success')}
    return {'flash': ('변경된 내용이 없습니다. 적용값을 확인해 주세요.', 'info')}


def handle_add_chat(db, project, form, current_user, **ctx):
    msg = (form.get('chat_message') or '').strip()
    if msg:
        append_history_log(
            db,
            project_id=project.id,
            user_name=current_user,
            content=msg,
            scope='material',
            kind='comment'
        )
    return {}


def handle_add_history_reply(db, project, form, current_user, **ctx):
    parent_id_raw = form.get('parent_log_id')
    reply_message = (form.get('reply_message') or '').strip()
    if parent_id_raw and reply_message:
        parent = db.query(HistoryLog).get(int(parent_id_raw))
        if parent and parent.project_id == project.id:
            origin_full = (parent.content or '').strip()
            origin_snapshot = origin_full[:220] + '...' if len(origin_full) > 220 else origin_full
            append_history_log(
                db,
                project_id=project.id,
                user_name=current_user,
                content=reply_message,
                scope='material',
                kind='reply',
                parent_log_id=parent.id,
                root_log_id=parent.root_log_id or parent.id,
                origin_snapshot=origin_snapshot,
            )
    return {}


# ===================================================================
# 재고 예약/취소 액션 핸들러
# ===================================================================
def handle_cancel_reservation(db, project, form, current_user, **ctx):
    """재고이용 -> 발주대기 전환 (예약 취소, 가용재고 복원)"""
    refresh_fn = ctx['refresh_fn']
    order_id = safe_int(form.get('material_order_id'))
    order = db.query(MaterialOrder).get(order_id)
    if not (order and order.project_id == project.id):
        return {'flash': ('대상을 찾을 수 없습니다.', 'warning')}

    if order.order_status != '재고이용':
        return {'flash': ('재고이용 상태가 아닙니다.', 'warning')}

    # BomItem -> Item 연결로 reserved_qty 감소 + StockMovement 기록
    if order.bom_item_id:
        bi = db.query(BomItem).get(order.bom_item_id)
        if bi and bi.item_id:
            linked_item = db.query(Item).get(bi.item_id)
            if linked_item:
                cancel_qty = order.quantity or 0
                linked_item.reserved_qty = max(0, (linked_item.reserved_qty or 0) - cancel_qty)
                record_stock_movement(
                    db, linked_item.id,
                    movement_type='IN_CANCEL_RESERVE',
                    quantity=0,  # reserved_qty 변동이지 stock_qty 변동은 아님
                    reference_type='material_order',
                    reference_id=order.id,
                    note=f'예약취소: {order.material_name} (수량 {cancel_qty})',
                    created_by=current_user,
                )

    order.order_status = '발주대기'

    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템',
        content=f"{current_user}님이 [{order.material_name}] 재고 예약을 취소했습니다. (재고이용 -> 발주대기)",
        scope='material',
        kind='system'
    )
    refresh_fn(db, project.id)
    return {'flash': (f'[{order.material_name}] 예약이 취소되었습니다.', 'success')}


def handle_reserve_stock(db, project, form, current_user, **ctx):
    """발주대기 -> 재고이용 전환 (재예약, 가용재고 차감)"""
    refresh_fn = ctx['refresh_fn']
    order_id = safe_int(form.get('material_order_id'))
    order = db.query(MaterialOrder).get(order_id)
    if not (order and order.project_id == project.id):
        return {'flash': ('대상을 찾을 수 없습니다.', 'warning')}

    if order.order_status != '발주대기':
        return {'flash': ('발주대기 상태가 아닙니다.', 'warning')}

    # BomItem -> Item 연결로 가용재고 체크 및 예약
    if not order.bom_item_id:
        return {'flash': ('BOM 연결이 없어 재고 전환이 불가합니다.', 'warning')}

    bi = db.query(BomItem).get(order.bom_item_id)
    if not (bi and bi.item_id):
        return {'flash': ('품목 마스터 연결이 없어 재고 전환이 불가합니다.', 'warning')}

    linked_item = db.query(Item).get(bi.item_id)
    if not linked_item:
        return {'flash': ('품목을 찾을 수 없습니다.', 'warning')}

    available = max(0, (linked_item.stock_qty or 0) - (linked_item.reserved_qty or 0))
    needed = order.quantity or 0

    if needed > available:
        return {'flash': (f'가용재고 부족: 필요 {needed}, 가용 {available}', 'warning')}

    linked_item.reserved_qty = (linked_item.reserved_qty or 0) + needed
    order.order_status = '재고이용'

    # StockMovement 기록 (예약은 stock_qty 변동 없이 reserved_qty만 변동)
    record_stock_movement(
        db, linked_item.id,
        movement_type='OUT_RESERVE',
        quantity=0,  # reserved_qty 변동이지 stock_qty 변동은 아님
        reference_type='material_order',
        reference_id=order.id,
        note=f'재고예약: {order.material_name} (예약수량 {needed})',
        created_by=current_user,
    )

    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템',
        content=f"{current_user}님이 [{order.material_name}] 재고로 전환했습니다. (발주대기 -> 재고이용, 예약수량 {needed})",
        scope='material',
        kind='system'
    )
    refresh_fn(db, project.id)
    return {'flash': (f'[{order.material_name}] 재고이용으로 전환되었습니다.', 'success')}


# ===================================================================
# 자재관리 -> 발주서 바로 생성 (FR-13)
# ===================================================================
def _generate_po_no(db):
    """발주번호 자동 채번: PO{YYYY}-{NNN}"""
    year = datetime.date.today().year
    prefix = f'PO{year}-'
    last_po = db.query(PurchaseOrder).filter(
        PurchaseOrder.po_no.like(f'{prefix}%')
    ).order_by(desc(PurchaseOrder.po_no)).first()
    if last_po:
        try:
            last_num = int(last_po.po_no.replace(prefix, ''))
            return f'{prefix}{last_num + 1:03d}'
        except ValueError:
            pass
    return f'{prefix}001'


def handle_create_po_from_material(db, project, form, current_user, **ctx):
    """자재관리에서 발주서 바로 생성 (단건)"""
    refresh_fn = ctx['refresh_fn']
    order_id = safe_int(form.get('material_order_id'))
    order = db.query(MaterialOrder).get(order_id)
    if not (order and order.project_id == project.id):
        return {'flash': ('대상을 찾을 수 없습니다.', 'warning')}

    if order.order_status not in ('발주대기',):
        return {'flash': ('발주대기 상태만 발주서 생성이 가능합니다.', 'warning')}

    # BomItem 정보로 거래처 매칭
    bi = db.query(BomItem).get(order.bom_item_id) if order.bom_item_id else None
    supplier_name = (bi.supplier or '').strip() if bi else ''

    # 거래처 매칭 (ilike)
    vendor = None
    if supplier_name:
        vendor = db.query(Vendor).filter(
            Vendor.name.ilike(f'%{supplier_name}%'),
            Vendor.is_active == True,
        ).first()

    # 거래처 없으면 자동 생성
    if not vendor and supplier_name:
        vendor = Vendor(name=supplier_name, is_active=True)
        db.add(vendor)
        db.flush()

    if not vendor:
        return {'flash': ('거래처 정보가 없습니다. BOM에 납품업체를 등록해주세요.', 'warning')}

    # 계약 정보
    contract = db.query(Contract).get(order.contract_id)

    # 발주서 생성
    po_no = _generate_po_no(db)
    po = PurchaseOrder(
        po_no=po_no,
        po_date=datetime.date.today(),
        vendor_id=vendor.id,
        project_id=project.id,
        contract_id=order.contract_id,
        status='작성중',
        note=f"자재관리에서 자동 생성 ({project.temp_name or ''} / {order.material_name})",
    )
    db.add(po)
    db.flush()

    # 발주 품목 생성
    po_item = PurchaseOrderItem(
        po_id=po.id,
        item_name=bi.item_name if bi else order.material_name,
        item_spec=bi.item_spec if bi else '',
        quantity=order.quantity or 0,
        unit_price=0,
        amount=0,
        unit=bi.unit if bi else 'EA',
        bom_item_id=bi.id if bi else None,
    )
    db.add(po_item)
    db.flush()

    # MaterialOrder에 PO 연결
    order.po_id = po.id
    order.po_item_id = po_item.id

    append_history_log(
        db,
        project_id=project.id,
        user_name='시스템',
        content=f"{current_user}님이 [{order.material_name}] 발주서를 생성했습니다. (발주번호: {po_no}, 거래처: {vendor.name})",
        scope='material',
        kind='system'
    )
    refresh_fn(db, project.id)
    return {'flash': (f'발주서 {po_no}가 생성되었습니다. (거래처: {vendor.name})', 'success')}


def handle_bulk_create_po(db, project, form, current_user, **ctx):
    """발주대기 자재 일괄 발주서 생성 (거래처별 그룹핑, FR-14/FR-15)"""
    refresh_fn = ctx['refresh_fn']

    # 발주대기인 MO 중 bom_item_id가 있는 것만 대상
    pending_orders = db.query(MaterialOrder).filter(
        MaterialOrder.project_id == project.id,
        MaterialOrder.order_status == '발주대기',
        MaterialOrder.bom_item_id.isnot(None),
    ).all()

    if not pending_orders:
        return {'flash': ('발주대기 상태인 자재가 없습니다.', 'info')}

    # 거래처별 그룹핑 (BomItem.supplier 기준)
    groups = {}
    for mo in pending_orders:
        bi = db.query(BomItem).get(mo.bom_item_id)
        supplier = (bi.supplier or '미지정').strip() if bi else '미지정'
        if supplier not in groups:
            groups[supplier] = []
        groups[supplier].append((mo, bi))

    created_pos = []
    for supplier_name, items in groups.items():
        if supplier_name == '미지정':
            continue

        # 거래처 매칭/생성
        vendor = db.query(Vendor).filter(
            Vendor.name.ilike(f'%{supplier_name}%'),
            Vendor.is_active == True,
        ).first()
        if not vendor:
            vendor = Vendor(name=supplier_name, is_active=True)
            db.add(vendor)
            db.flush()

        # 발주서 생성
        po_no = _generate_po_no(db)
        po = PurchaseOrder(
            po_no=po_no,
            po_date=datetime.date.today(),
            vendor_id=vendor.id,
            project_id=project.id,
            contract_id=items[0][0].contract_id,
            status='작성중',
            note=f"자재관리 일괄발주 ({project.temp_name or ''}, {len(items)}건)",
        )
        db.add(po)
        db.flush()

        for mo, bi in items:
            po_item = PurchaseOrderItem(
                po_id=po.id,
                item_name=bi.item_name if bi else mo.material_name,
                item_spec=bi.item_spec if bi else '',
                quantity=mo.quantity or 0,
                unit_price=0,
                amount=0,
                unit=bi.unit if bi else 'EA',
                bom_item_id=bi.id if bi else None,
            )
            db.add(po_item)
            db.flush()

            mo.po_id = po.id
            mo.po_item_id = po_item.id

        created_pos.append(po_no)

    if created_pos:
        append_history_log(
            db,
            project_id=project.id,
            user_name='시스템',
            content=f"{current_user}님이 일괄발주서 {len(created_pos)}건을 생성했습니다. ({', '.join(created_pos)})",
            scope='material',
            kind='system'
        )
        refresh_fn(db, project.id)
        return {'flash': (f'일괄발주서 {len(created_pos)}건 생성 완료: {", ".join(created_pos)}', 'success')}

    return {'flash': ('발주 가능한 자재가 없습니다. (거래처 미지정 등)', 'warning')}
