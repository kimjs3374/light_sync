from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from modules.auth_decorators import login_required
import datetime
from sqlalchemy.orm import joinedload
from modules.db_context import get_db
from modules.utils import safe_int
from modules.pagination import make_pagination
from modules.models import (
    Project, MaterialOrder, Contract, ContractItem,
    DETAIL_ITEM_OPTIONS, normalize_detail_item,
    BomHeader, BomItem, PurchaseOrder, PurchaseOrderItem,
)
from sqlalchemy import or_, func
from modules.history_board import append_history_log, get_project_history_context
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    make_priority_entry,
    sort_priority_entries,
)
from modules.production_logic import refresh_production_statuses
from modules.services.material_actions import (
    handle_sync_material_orders,
    handle_update_material_order,
    handle_bulk_update_material_orders,
    handle_add_chat,
    handle_add_history_reply,
)

material_bp = Blueprint('material', __name__)


def _is_pristine_material_order(order):
    out_status = (order.outsourcing_status or '').strip()
    out_default = out_status in ('', '외주입고대기')
    note_empty = not (order.note or '').strip()
    return (
        (order.order_status or '발주대기') == '발주대기'
        and order.order_date is None
        and order.expected_in_date is None
        and not bool(order.in_confirmed)
        and note_empty
        and out_default
    )


def compute_admin_status_from_orders(orders):
    orders = list(orders or [])
    if not orders:
        return '자재확인중'

    statuses = [(o.order_status or '발주대기') for o in orders]
    outsourced = [o for o in orders if o.is_outsourcing]

    all_pristine = all(_is_pristine_material_order(o) for o in orders)
    if all_pristine:
        return '자재확인중'

    all_in_done = all(s == '입고완료' for s in statuses)
    all_out_done = all((o.outsourcing_status or '') == '본사입고완료' for o in outsourced) if outsourced else True
    if all_in_done and all_out_done:
        return '입고완료'

    all_order_done_only = all(s == '발주완료' for s in statuses)
    if all_order_done_only:
        if (not outsourced) or any((o.outsourcing_status or '') != '본사입고완료' for o in outsourced):
            return '입고진행중'
        return '발주완료'

    if all(s in ('발주완료', '입고완료') for s in statuses):
        return '입고진행중'

    return '발주진행중'


def refresh_admin_statuses_from_material_orders(db, project_id=None):
    q = db.query(ContractItem).options(
        joinedload(ContractItem.material_orders),
        joinedload(ContractItem.contract)
    )
    if project_id:
        q = q.join(Contract).filter(Contract.project_id == project_id)

    items = q.all()
    for item in items:
        computed = compute_admin_status_from_orders(item.material_orders)
        if item.status_admin != computed:
            item.status_admin = computed
    refresh_production_statuses(db, project_id=project_id)


def _material_specs_from_contract_item(item):
    category = normalize_detail_item(item.category, default=DETAIL_ITEM_OPTIONS[0])
    model_name = (item.model_name or '').upper()

    if category == '투광등기구':
        if 'STA' in model_name:
            return [
                ('LED', True, '외주입고대기'),
                ('RP', True, '외주입고대기'),
                ('PCB', False, None),
                ('SMPS', False, None),
                ('렌즈', False, None),
                ('외함프레임', False, None),
                ('외함브라켓', False, None),
                ('외함체결부속', False, None),
            ]
        return [
            ('LED', True, '외주입고대기'),
            ('RP', True, '외주입고대기'),
            ('PCB', False, None),
            ('외함', False, None),
            ('SMPS', False, None),
            ('렌즈', False, None),
        ]

    if category in ('가로등기구', '보안등기구', '터널등기구'):
        return [
            ('모듈', False, None),
            ('분배기', False, None),
            ('외함', False, None),
            ('SMPS', False, None),
        ]

    if category == '조명타워':
        specs = [('강관파이프', False, None), ('베이스판', False, None)]
        if '기초앙카' in (item.model_name or ''):
            specs.append(('L앙카', False, None))
        return specs

    if category in ('철제가로등주', '스텐가로등주'):
        return [
            ('파이프', False, None),
            ('베이스판', False, None),
            ('밴딩(암대)', False, None),
            ('부속자재', False, None),
        ]

    return []


def _find_bom_for_contract_item(db, item):
    """계약품목에 매칭되는 BomHeader를 찾는다."""
    model_name = (item.model_name or '').strip()
    category = (item.category or '').strip()

    if model_name:
        bom = db.query(BomHeader).filter(
            BomHeader.is_active == True,
            or_(
                BomHeader.product_code.ilike(f'%{model_name}%'),
                BomHeader.product_name.ilike(f'%{model_name}%'),
            )
        ).first()
        if bom:
            return bom

    if category:
        bom = db.query(BomHeader).filter(
            BomHeader.is_active == True,
            or_(
                BomHeader.product_name.ilike(f'%{category}%'),
                BomHeader.product_code.ilike(f'%{category}%'),
            )
        ).first()
        if bom:
            return bom

    return None


def sync_material_orders_for_contract_item(db, contract, item):
    """계약품목의 MaterialOrder를 BOM 기반으로 동기화.

    1순위: BOM이 있으면 BomItem 기반으로 자재 목록 생성
    2순위: BOM이 없으면 기존 하드코딩 스펙 사용 (fallback)
    """
    bom = _find_bom_for_contract_item(db, item)
    existing_orders = db.query(MaterialOrder).filter(MaterialOrder.contract_item_id == item.id).all()
    existing_map = {o.material_name: o for o in existing_orders}
    qty = safe_int(item.quantity, 0)

    if bom and bom.bom_items:
        # === BOM 기반 자재 생성 ===
        target_names = set()
        for bi in bom.bom_items:
            material_name = bi.item_name
            target_names.add(material_name)

            # 발주 상태 확인 (bom_item_id 기반)
            po_status = _get_po_status_for_bom_item(db, bi.id, contract.id)

            order = existing_map.get(material_name)
            if order:
                order.item_category = item.category
                order.item_model_name = item.model_name
                order.quantity = (bi.quantity or 1) * qty
                order.bom_item_id = bi.id
                # 발주 상태가 진행됐으면 유지, 아니면 PO 기반 업데이트
                if order.order_status == '발주대기' and po_status:
                    order.order_status = po_status
                continue

            db.add(MaterialOrder(
                project_id=contract.project_id,
                contract_id=contract.id,
                contract_item_id=item.id,
                item_category=item.category,
                item_model_name=item.model_name,
                material_name=material_name,
                quantity=(bi.quantity or 1) * qty,
                order_status=po_status or '발주대기',
                bom_item_id=bi.id,
                is_outsourcing=False,
            ))
    else:
        # === Fallback: 기존 하드코딩 스펙 ===
        target_specs = _material_specs_from_contract_item(item)
        target_names = {name for name, _, _ in target_specs}

        for material_name, is_outsourcing, outsourcing_status in target_specs:
            order = existing_map.get(material_name)
            if order:
                order.item_category = item.category
                order.item_model_name = item.model_name
                order.quantity = qty
                order.is_outsourcing = bool(is_outsourcing)
                if not is_outsourcing:
                    order.outsourcing_status = None
                elif not order.outsourcing_status:
                    order.outsourcing_status = outsourcing_status
                continue

            db.add(MaterialOrder(
                project_id=contract.project_id,
                contract_id=contract.id,
                contract_item_id=item.id,
                item_category=item.category,
                item_model_name=item.model_name,
                material_name=material_name,
                quantity=qty,
                order_status='발주대기',
                is_outsourcing=bool(is_outsourcing),
                outsourcing_status=outsourcing_status if is_outsourcing else None,
            ))

    # 목록에서 빠진 기존 MO 삭제 (pristine 상태인 것만)
    for old in existing_orders:
        if old.material_name not in target_names:
            if _is_pristine_material_order(old):
                db.delete(old)


def _get_po_status_for_bom_item(db, bom_item_id, contract_id):
    """BOM 부품에 연결된 발주서 상태를 확인."""
    po_item = (
        db.query(PurchaseOrderItem)
        .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .filter(
            PurchaseOrderItem.bom_item_id == bom_item_id,
            PurchaseOrder.contract_id == contract_id,
            PurchaseOrder.status != '취소',
        )
        .first()
    )
    if not po_item:
        return None
    po = db.query(PurchaseOrder).get(po_item.po_id)
    if not po:
        return None
    if po.status == '입고완료':
        return '입고완료'
    if po.status in ('발송완료', '입고대기'):
        return '발주완료'
    if po.status == '작성중':
        return '발주대기'
    return None


def sync_material_orders(db, project_id=None):
    q = db.query(Contract).options(joinedload(Contract.items))
    if project_id:
        q = q.filter(Contract.project_id == project_id)
    contracts = q.all()
    for contract in contracts:
        for item in contract.items:
            sync_material_orders_for_contract_item(db, contract, item)



ACTION_HANDLERS = {
    'sync_material_orders': handle_sync_material_orders,
    'update_material_order': handle_update_material_order,
    'bulk_update_material_orders': handle_bulk_update_material_orders,
    'add_chat': handle_add_chat,
    'add_history_reply': handle_add_history_reply,
}

@material_bp.route('/material_management', methods=['GET', 'POST'])
@login_required
def material_management():

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        if request.method == 'POST' and request.form.get('action') == 'sync_material_orders':
            sync_material_orders(db)
            refresh_admin_statuses_from_material_orders(db)
            first_order = db.query(MaterialOrder).order_by(MaterialOrder.id.asc()).first()
            if first_order:
                append_history_log(
                    db,
                    project_id=first_order.project_id,
                    user_name='시스템 🤖',
                    content=f"{current_user}님이 자재 자동생성/동기화를 실행했습니다.",
                    scope='material',
                    kind='system'
                )
            db.commit()
            flash('자재 자동생성/동기화가 완료되었습니다.', 'success')
            return redirect(url_for('material.material_management'))

        sync_material_orders(db)
        refresh_admin_statuses_from_material_orders(db)
        db.commit()

        q = (request.args.get('q') or '').strip().lower()
        status = request.args.get('status', 'all')
        outsource = request.args.get('outsource', 'all')
        sort_by = request.args.get('sort', 'due_asc')

        projects = db.query(Project).filter(Project.is_contracted.is_(True)).options(
            joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.material_orders),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        def _match_order(order, project_obj, contract_obj):
            search_pool = ' '.join([
                project_obj.project_no or '',
                project_obj.temp_name or '',
                contract_obj.contract_name or '',
                order.item_category or '',
                order.item_model_name or '',
                order.material_name or '',
                order.order_status or '',
                order.outsourcing_status or ''
            ]).lower()

            if q and q not in search_pool:
                return False
            if status != 'all' and (order.order_status or '') != status:
                return False
            if outsource == 'yes' and not order.is_outsourcing:
                return False
            if outsource == 'no' and order.is_outsourcing:
                return False
            return True

        filtered_projects = []
        total_orders = 0
        filtered_orders = 0
        for p in projects:
            has_any = False
            all_orders_for_project = []
            for c in p.contracts:
                c._matched_items = []
                for item in c.items:
                    item.status_admin = compute_admin_status_from_orders(item.material_orders)
                    all_orders_for_project.extend(item.material_orders)
                    total_orders += len(item.material_orders)
                    item._matched_orders = [o for o in item.material_orders if _match_order(o, p, c)]
                    if item._matched_orders:
                        filtered_orders += len(item._matched_orders)
                        c._matched_items.append(item)
                        has_any = True
            if has_any:
                p._purchase_status = compute_admin_status_from_orders(all_orders_for_project)
                filtered_projects.append(p)

        today = datetime.date.today()
        for p in filtered_projects:
            contracts_sorted = sorted(
                p.contracts,
                key=lambda c: c.delivery_due_date or datetime.date.max
            )
            primary_contract = contracts_sorted[0] if contracts_sorted else None
            p._mat_due_date = primary_contract.delivery_due_date if primary_contract else None
            p._mat_dday = (p._mat_due_date - today).days if p._mat_due_date else None

        if sort_by == 'due_desc':
            filtered_projects.sort(
                key=lambda p: (p._mat_dday is None, -(p._mat_dday if p._mat_dday is not None else -99999))
            )
        elif sort_by == 'created_desc':
            filtered_projects.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
        else:  # due_asc
            filtered_projects.sort(
                key=lambda p: (p._mat_dday is None, p._mat_dday if p._mat_dday is not None else 99999)
            )

        stats = {
            'total_projects': len(projects),
            'filtered_projects': len(filtered_projects),
            'total_orders': total_orders,
            'filtered_orders': filtered_orders,
        }

        priority_projects = []
        for p in filtered_projects:
            reasons = []
            override = append_manual_priority_reason(reasons, p)
            is_urgent_project = bool(p.is_urgent or any(c.is_urgent_prod for c in (p.contracts or [])))
            matched_item_count = 0
            matched_order_count = 0
            active_order_count = 0

            for c in p.contracts:
                for item in getattr(c, '_matched_items', []):
                    orders = list(getattr(item, '_matched_orders', []) or [])
                    matched_item_count += 1
                    matched_order_count += len(orders)
                    active_order_count += sum(1 for order in orders if (order.order_status or '') != '입고완료')

            if is_urgent_project:
                append_priority_reason(reasons, 'urgent')
            append_due_priority_reason(reasons, p._mat_dday, 'material')
            if (p._purchase_status or '') in ('자재확인중', '발주진행중', '입고진행중'):
                append_priority_reason(reasons, 'material_pending', p._purchase_status or '자재확인중')

            if reasons:
                meta_lines = [
                    f"조회 품목: {matched_item_count}건 / 조회 자재건: {matched_order_count}건",
                    f"미완료 자재건: {active_order_count}건",
                    f"계약건 수: {len(p.contracts or [])}건",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=p.id,
                    project_no=p.project_no,
                    title=p.temp_name or '-',
                    subtitle=f"현재 자재상태: {p._purchase_status or '-'}",
                    detail_url=url_for('material.material_detail', project_id=p.id),
                    reasons=reasons,
                    dday=p._mat_dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)

        page = safe_int(request.args.get('page'), 1)
        per_page = safe_int(request.args.get('per_page'), 20)
        pagination = make_pagination(page, per_page, len(filtered_projects))
        start = (pagination['page'] - 1) * per_page
        projects_page = filtered_projects[start:start + per_page]

        return render_template(
            'material_management.html',
            projects=projects_page,
            priority_projects=priority_projects,
            stats=stats,
            pagination=pagination,
            filters={'q': request.args.get('q', ''), 'status': status, 'outsource': outsource, 'sort': sort_by}
        )

@material_bp.route('/material_management/<int:project_id>', methods=['GET', 'POST'])
@login_required
def material_detail(project_id):

    with get_db() as db:
        current_user = session.get('full_name') or '사용자'

        p = db.query(Project).options(
            joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.material_orders)
        ).get(project_id)

        if not p:
            flash('대상을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('material.material_management'))

        if request.method == 'POST':
            action = request.form.get('action')

            handler = ACTION_HANDLERS.get(action)
            if handler:
                ctx = {
                    'sync_fn': sync_material_orders,
                    'refresh_fn': refresh_admin_statuses_from_material_orders,
                }
                result = handler(db, p, request.form, current_user, **ctx)

                db.commit()

                if result.get('flash'):
                    flash(*result['flash'])
                for f in result.get('flashes', []):
                    flash(*f)

            return redirect(url_for('material.material_detail', project_id=project_id))

        sync_material_orders(db, project_id)
        refresh_admin_statuses_from_material_orders(db, project_id)
        db.commit()

        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope='material',
            limit=300
        )

        return render_template(
            'material_detail.html',
            project=p,
            history=history,
            history_counts=history_counts,
            today=datetime.date.today(),
        )
