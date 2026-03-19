"""
BOM 관리 Blueprint (Phase 4).

- BOM 목록/생성/수정/삭제
- 프로젝트별 소요 자재 자동 계산
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
import json
from modules.models import (
    BomHeader, BomItem, Contract, ContractItem, Project,
    PurchaseOrder, PurchaseOrderItem, MaterialOrder,
    Receiving, ReceivingItem, ReceivingHistory, Item,
    Vendor,
)

logger = logging.getLogger(__name__)

bom_bp = Blueprint('bom', __name__)


def _get_latest_receiving_prices(db, bom_items):
    """BOM 품목들의 최신 입고 단가를 조회.

    1순위: 자체 입고(receivings + receiving_items) - item_name 매칭
    2순위: iCUBE 입고이력(receiving_history) - items_json 내 item_cd 매칭

    Returns: {item_code: {'unit_price': float, 'date': str, 'source': str}}
    """
    result = {}
    item_codes = {bi.item_code for bi in bom_items if bi.item_code}
    item_names = {bi.item_name for bi in bom_items if bi.item_name}
    if not item_codes and not item_names:
        return result

    # 1) 자체 입고에서 최신 단가 (item_name 매칭)
    for name in item_names:
        row = (
            db.query(ReceivingItem.unit_price, Receiving.rcv_date)
            .join(Receiving, ReceivingItem.receiving_id == Receiving.id)
            .filter(
                ReceivingItem.item_name == name,
                ReceivingItem.unit_price > 0,
            )
            .order_by(desc(Receiving.rcv_date))
            .first()
        )
        if row:
            # item_name → item_code 매핑 찾기
            matched_bi = next((bi for bi in bom_items if bi.item_name == name), None)
            key = matched_bi.item_code if matched_bi and matched_bi.item_code else name
            result[key] = {
                'unit_price': row.unit_price,
                'date': row.rcv_date.strftime('%Y-%m-%d') if row.rcv_date else '',
                'source': '자체입고',
            }

    # 2) iCUBE 입고이력에서 최신 단가 (item_cd 매칭) — 자체 입고에 없는 것만
    remaining_codes = item_codes - set(result.keys())
    if remaining_codes:
        histories = (
            db.query(ReceivingHistory)
            .filter(ReceivingHistory.items_json.isnot(None))
            .order_by(desc(ReceivingHistory.receive_date))
            .limit(500)
            .all()
        )
        for hist in histories:
            if not remaining_codes:
                break
            try:
                items_list = json.loads(hist.items_json) if hist.items_json else []
            except (json.JSONDecodeError, TypeError):
                continue
            for it in items_list:
                code = (it.get('item_cd') or '').strip()
                price = it.get('unit_price') or 0
                if code in remaining_codes and price > 0:
                    result[code] = {
                        'unit_price': price,
                        'date': hist.receive_date.strftime('%Y-%m-%d') if hist.receive_date else '',
                        'source': 'iCUBE',
                    }
                    remaining_codes.discard(code)

    return result


# ===================================================================
# 1. BOM 목록
# ===================================================================
@bom_bp.route('/bom')
@login_required
def bom_list():
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        query = db.query(BomHeader)

        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (BomHeader.product_name.ilike(like_q)) |
                (BomHeader.product_code.ilike(like_q))
            )

        if category:
            query = query.filter(BomHeader.product_category == category)

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        boms = query.order_by(BomHeader.product_category, BomHeader.product_code) \
                    .offset(offset).limit(per_page).all()

        # 각 BOM의 부품 수 + 총 금액
        for bom in boms:
            bom._item_count = db.query(func.count(BomItem.id)).filter(
                BomItem.bom_id == bom.id
            ).scalar() or 0
            bom._total_amount = db.query(func.sum(BomItem.amount)).filter(
                BomItem.bom_id == bom.id
            ).scalar() or 0

        # 제품군별 카운트
        cat_counts = db.query(
            BomHeader.product_category, func.count(BomHeader.id)
        ).filter(
            BomHeader.product_category.isnot(None)
        ).group_by(BomHeader.product_category).order_by(
            func.count(BomHeader.id).desc()
        ).all()

        stats = {
            'total': db.query(func.count(BomHeader.id)).scalar() or 0,
            'active': db.query(func.count(BomHeader.id)).filter(BomHeader.is_active == True).scalar() or 0,
            'categories': [(c, n) for c, n in cat_counts],
        }

        return render_template(
            'bom_list.html',
            boms=boms,
            pagination=pagination,
            stats=stats,
            filters={'q': q, 'category': category},
        )


# ===================================================================
# 2. BOM 생성
# ===================================================================
@bom_bp.route('/bom/create', methods=['GET', 'POST'])
@login_required
def bom_create():
    with get_db() as db:
        if request.method == 'POST':
            product_code = (request.form.get('product_code') or '').strip()
            product_name = (request.form.get('product_name') or '').strip()
            version = (request.form.get('version') or '1.0').strip()
            note = (request.form.get('note') or '').strip()

            if not product_code or not product_name:
                flash('제품코드와 제품명을 입력해주세요.', 'warning')
                return redirect(url_for('bom.bom_create'))

            # 중복 체크
            existing = db.query(BomHeader).filter_by(product_code=product_code).first()
            if existing:
                flash(f'제품코드 "{product_code}"는 이미 존재합니다.', 'warning')
                return redirect(url_for('bom.bom_create'))

            bom = BomHeader(
                product_code=product_code,
                product_name=product_name,
                version=version,
                is_active=True,
                note=note,
            )
            db.add(bom)
            db.flush()

            # BOM 품목 추가
            item_names = request.form.getlist('item_name[]')
            item_specs = request.form.getlist('item_spec[]')
            item_qtys = request.form.getlist('quantity[]')
            item_units = request.form.getlist('unit[]')
            item_notes = request.form.getlist('item_note[]')

            for i in range(len(item_names)):
                name = (item_names[i] if i < len(item_names) else '').strip()
                if not name:
                    continue

                spec = (item_specs[i] if i < len(item_specs) else '').strip()
                qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 1
                unit = (item_units[i] if i < len(item_units) else '').strip()
                item_note = (item_notes[i] if i < len(item_notes) else '').strip()

                db.add(BomItem(
                    bom_id=bom.id,
                    item_name=name,
                    item_spec=spec,
                    quantity=qty,
                    unit=unit,
                    note=item_note,
                ))

            db.commit()
            flash(f'BOM "{product_name}"이 생성되었습니다.', 'success')
            return redirect(url_for('bom.bom_detail', bom_id=bom.id))

        return render_template('bom_create.html')


# ===================================================================
# 3. BOM 상세
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>')
@login_required
def bom_detail(bom_id):
    with get_db() as db:
        bom = db.query(BomHeader).options(
            joinedload(BomHeader.bom_items),
        ).get(bom_id)
        if not bom:
            abort(404)

        # 최신 입고 단가 조회 (품목코드 기준)
        latest_prices = _get_latest_receiving_prices(db, bom.bom_items)

        return render_template(
            'bom_detail.html',
            bom=bom,
            latest_prices=latest_prices,
        )


# ===================================================================
# 4. BOM 수정
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>/edit', methods=['POST'])
@login_required
def bom_edit(bom_id):
    with get_db() as db:
        bom = db.query(BomHeader).get(bom_id)
        if not bom:
            abort(404)

        bom.product_name = (request.form.get('product_name') or bom.product_name).strip()
        bom.version = (request.form.get('version') or bom.version).strip()
        bom.note = (request.form.get('note') or '').strip()
        bom.is_active = request.form.get('is_active') == 'on'

        # 기존 품목 업데이트 방식 (item_code, bom_item_id 연결 보존)
        existing_items = db.query(BomItem).filter_by(bom_id=bom.id).order_by(BomItem.id).all()

        item_names = request.form.getlist('item_name[]')
        item_specs = request.form.getlist('item_spec[]')
        item_qtys = request.form.getlist('quantity[]')
        item_units = request.form.getlist('unit[]')
        item_notes = request.form.getlist('item_note[]')
        unit_prices = request.form.getlist('unit_price[]')

        # 기존 아이템 업데이트 + 신규 추가
        for i in range(len(item_names)):
            name = (item_names[i] if i < len(item_names) else '').strip()
            if not name:
                continue

            spec = (item_specs[i] if i < len(item_specs) else '').strip()
            qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 1
            unit = (item_units[i] if i < len(item_units) else '').strip()
            item_note = (item_notes[i] if i < len(item_notes) else '').strip()

            up_str = (unit_prices[i] if i < len(unit_prices) else '').strip()
            up = float(up_str) if up_str else None
            amount = (up * qty) if up else None

            if i < len(existing_items):
                # 기존 아이템 업데이트
                bi = existing_items[i]
                bi.item_name = name
                bi.item_spec = spec
                bi.quantity = qty
                bi.unit = unit
                bi.note = item_note
                # 단가 변경 시 직전 단가 기록
                if up is not None and bi.unit_price is not None and up != bi.unit_price:
                    bi.prev_unit_price = bi.unit_price
                bi.unit_price = up
                bi.amount = amount
            else:
                # 신규 추가
                db.add(BomItem(
                    bom_id=bom.id,
                    item_name=name,
                    item_spec=spec,
                    quantity=qty,
                    unit=unit,
                    note=item_note,
                    unit_price=up,
                    amount=amount,
                ))

        # form에서 제거된 아이템 삭제
        if len(item_names) < len(existing_items):
            for j in range(len(item_names), len(existing_items)):
                db.delete(existing_items[j])

        db.commit()
        flash('BOM이 수정되었습니다.', 'success')
        return redirect(url_for('bom.bom_detail', bom_id=bom_id))


# ===================================================================
# 5. BOM 삭제
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>/delete', methods=['POST'])
@login_required
def bom_delete(bom_id):
    with get_db() as db:
        bom = db.query(BomHeader).get(bom_id)
        if not bom:
            abort(404)

        db.delete(bom)
        db.commit()
        flash('BOM이 삭제되었습니다.', 'success')
        return redirect(url_for('bom.bom_list'))


# ===================================================================
# 6. 프로젝트별 소요 자재 자동 계산
# ===================================================================
@bom_bp.route('/bom/material-requirement')
@login_required
def material_requirement():
    """프로젝트별 소요 자재 계산 페이지"""
    contract_id = safe_int(request.args.get('contract_id'), 0)

    with get_db() as db:
        contracts = db.query(Contract).join(Project).filter(
            Project.status != '완료'
        ).order_by(desc(Contract.id)).limit(50).all()

        requirement = []
        selected_contract = None

        if contract_id:
            selected_contract = db.query(Contract).options(
                joinedload(Contract.items),
                joinedload(Contract.project),
            ).get(contract_id)

            if selected_contract:
                # 계약 품목 x BOM = 소요 자재
                for ci in selected_contract.items:
                    # BOM 매칭: 품목 카테고리/모델명으로 검색
                    bom = None
                    if ci.model_name:
                        bom = db.query(BomHeader).filter(
                            BomHeader.is_active == True,
                            (BomHeader.product_name.ilike(f'%{ci.model_name}%')) |
                            (BomHeader.product_code.ilike(f'%{ci.model_name}%'))
                        ).first()
                    if not bom and ci.category:
                        bom = db.query(BomHeader).filter(
                            BomHeader.is_active == True,
                            (BomHeader.product_name.ilike(f'%{ci.category}%')) |
                            (BomHeader.product_code.ilike(f'%{ci.category}%'))
                        ).first()

                    if bom:
                        for bi in bom.bom_items:
                            needed = (bi.quantity or 0) * (ci.quantity or 0)

                            # 1차: bom_item_id 기반 PurchaseOrderItem 발주량 (정확)
                            ordered_via_po = db.query(
                                func.coalesce(func.sum(PurchaseOrderItem.quantity), 0)
                            ).join(
                                PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id
                            ).filter(
                                PurchaseOrderItem.bom_item_id == bi.id,
                                PurchaseOrder.contract_id == contract_id,
                                PurchaseOrder.status != '취소',
                            ).scalar() or 0

                            # 2차: MaterialOrder 기반 (하위 호환, bom_item_id 없는 기존 데이터)
                            ordered_via_mo = db.query(
                                func.coalesce(func.sum(MaterialOrder.quantity), 0)
                            ).filter(
                                MaterialOrder.contract_item_id == ci.id,
                                MaterialOrder.order_status.in_(['발주완료', '입고완료']),
                            ).scalar() or 0

                            # 둘 중 큰 값 사용 (중복 방지)
                            ordered = max(float(ordered_via_po), float(ordered_via_mo))

                            # 입고량: bom_item_id 기반 우선, fallback MaterialOrder
                            received_via_mo = db.query(
                                func.coalesce(func.sum(MaterialOrder.quantity), 0)
                            ).filter(
                                MaterialOrder.contract_item_id == ci.id,
                                MaterialOrder.order_status == '입고완료',
                            ).scalar() or 0

                            shortage = max(0, needed - ordered)

                            requirement.append({
                                'contract_item': ci,
                                'bom_item': bi,
                                'product_qty': ci.quantity or 0,
                                'per_unit': bi.quantity or 0,
                                'needed': needed,
                                'ordered': ordered,
                                'received': float(received_via_mo),
                                'shortage': shortage,
                            })
                    else:
                        # BOM 매칭 없음
                        requirement.append({
                            'contract_item': ci,
                            'bom_item': None,
                            'product_qty': ci.quantity or 0,
                            'per_unit': 0,
                            'needed': 0,
                            'ordered': 0,
                            'received': 0,
                            'shortage': 0,
                            'no_bom': True,
                        })

        return render_template(
            'bom_requirement.html',
            contracts=contracts,
            selected_contract=selected_contract,
            requirement=requirement,
            contract_id=contract_id,
        )


# ===================================================================
# 6-1. 소요자재 부족분 -> 발주서 자동 생성
# ===================================================================
@bom_bp.route('/bom/create-po-from-requirement', methods=['POST'])
@login_required
def create_po_from_requirement():
    """소요자재 부족분에서 거래처별 발주서 자동 생성"""
    from routes.purchase_order import _generate_po_no

    contract_id = safe_int(request.form.get('contract_id'), 0)
    selected_items_json = request.form.get('selected_items', '[]')

    if not contract_id:
        flash('계약 정보가 없습니다.', 'warning')
        return redirect(url_for('bom.material_requirement'))

    try:
        selected_items = json.loads(selected_items_json)
    except (json.JSONDecodeError, TypeError):
        flash('선택 항목 데이터가 올바르지 않습니다.', 'danger')
        return redirect(url_for('bom.material_requirement', contract_id=contract_id))

    if not selected_items:
        flash('발주할 자재를 선택해주세요.', 'warning')
        return redirect(url_for('bom.material_requirement', contract_id=contract_id))

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            flash('계약을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('bom.material_requirement'))

        # supplier 기준 그룹핑
        from collections import defaultdict
        groups = defaultdict(list)
        for item in selected_items:
            supplier = (item.get('supplier') or '미지정').strip()
            groups[supplier].append(item)

        created_pos = []
        for supplier_name, items in groups.items():
            # Vendor 매칭 (ilike)
            vendor = db.query(Vendor).filter(
                Vendor.name.ilike(f'%{supplier_name}%'),
                Vendor.is_active == True,
            ).first()

            # 없으면 자동 생성
            if not vendor:
                vendor = Vendor(name=supplier_name, is_active=True)
                db.add(vendor)
                db.flush()

            # PurchaseOrder 생성
            po = PurchaseOrder(
                po_no=_generate_po_no(db),
                po_date=datetime.date.today(),
                vendor_id=vendor.id,
                contract_id=contract_id,
                project_id=contract.project_id,
                assigned_to=session.get('user_id'),
                status='작성중',
                note=f'BOM 소요자재 자동생성',
                created_by=session.get('user_id'),
            )
            db.add(po)
            db.flush()

            total_amount = 0
            for item in items:
                qty = float(item.get('quantity') or 0)
                price = float(item.get('unit_price') or 0)
                amount = qty * price

                po_item = PurchaseOrderItem(
                    po_id=po.id,
                    item_name=item.get('item_name', ''),
                    item_spec=item.get('item_spec', ''),
                    quantity=qty,
                    unit_price=price,
                    amount=amount,
                    unit=item.get('unit', ''),
                    bom_item_id=safe_int(item.get('bom_item_id'), 0) or None,
                )
                db.add(po_item)
                total_amount += amount

            po.total_amount = total_amount
            po.tax_amount = round(total_amount * 0.1)
            created_pos.append(po)

        db.commit()

        if len(created_pos) == 1:
            flash(f'발주서 {created_pos[0].po_no}가 생성되었습니다.', 'success')
            return redirect(url_for('purchase_order.po_detail', po_id=created_pos[0].id))
        else:
            po_nos = ', '.join(p.po_no for p in created_pos)
            flash(f'발주서 {len(created_pos)}건이 생성되었습니다: {po_nos}', 'success')
            return redirect(url_for('purchase_order.po_list'))


# ===================================================================
# 7. BOM 검색 API (AJAX)
# ===================================================================
@bom_bp.route('/api/bom/search')
@login_required
def api_bom_search():
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(BomHeader).filter(BomHeader.is_active == True)
        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (BomHeader.product_name.ilike(like_q)) |
                (BomHeader.product_code.ilike(like_q))
            )
        boms = query.order_by(BomHeader.product_name).limit(20).all()
        return jsonify([{
            'id': b.id,
            'product_code': b.product_code,
            'product_name': b.product_name,
            'version': b.version,
        } for b in boms])
