"""
품목관리 Blueprint.

- 품목 목록/검색/필터 (카테고리별)
- 품목 상세/수정
- 품목 신규 등록
- 카테고리 목록 API
"""

import json
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import or_, func, distinct, desc
from modules.auth_decorators import login_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    Item, PurchaseOrderItem, PurchaseOrder, ReceivingItem, Receiving,
    ReceivingHistory, BomItem, BomHeader, Vendor,
)

logger = logging.getLogger(__name__)

item_bp = Blueprint('item', __name__)


# ===================================================================
# 1. 품목 목록
# ===================================================================
@item_bp.route('/item')
@login_required
def item_list():
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    active_only = request.args.get('active_only', '1')
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 50)

    with get_db() as db:
        query = db.query(Item)

        if active_only == '1':
            query = query.filter(Item.is_active == True)

        if q:
            like = f'%{q}%'
            query = query.filter(or_(
                Item.icube_item_cd.ilike(like),
                Item.item_name.ilike(like),
                Item.item_spec.ilike(like),
                Item.manufacturer.ilike(like),
            ))

        if category:
            query = query.filter(Item.category == category)

        total = query.count()
        items = query.order_by(Item.item_name).offset((page - 1) * per_page).limit(per_page).all()
        pagination = make_pagination(page, per_page, total)

        # 카테고리 목록 (필터용)
        categories = [r[0] for r in db.query(distinct(Item.category)).filter(
            Item.category.isnot(None), Item.category != ''
        ).order_by(Item.category).all()]

    return render_template('item_list.html',
                           items=items,
                           pagination=pagination,
                           q=q,
                           category=category,
                           active_only=active_only,
                           categories=categories,
                           total=total)


# ===================================================================
# 2. 품목 상세
# ===================================================================
@item_bp.route('/item/<int:item_id>')
@login_required
def item_detail(item_id):
    with get_db() as db:
        item = db.query(Item).get(item_id)
        if not item:
            flash('품목을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('item.item_list'))

        categories = [r[0] for r in db.query(distinct(Item.category)).filter(
            Item.category.isnot(None), Item.category != ''
        ).order_by(Item.category).all()]

        # FR-05: 단가 추이 (icube_item_cd 없어도 item_name 기반으로 조회)
        price_history = []

        # 1) 자체 입고 단가 이력 - item_name 매칭 (부분 매칭 포함)
        name_filter = or_(
            ReceivingItem.item_name == item.item_name,
            ReceivingItem.item_name.ilike(f'%{item.item_name}%'),
        ) if item.item_name else (ReceivingItem.item_name == item.item_name)
        rcv_prices = (
            db.query(Receiving.rcv_date, ReceivingItem.unit_price, Receiving.vendor_id)
            .join(ReceivingItem, ReceivingItem.receiving_id == Receiving.id)
            .filter(
                name_filter,
                ReceivingItem.unit_price > 0,
            )
            .order_by(Receiving.rcv_date)
            .all()
        )
        for r in rcv_prices:
            vendor = db.query(Vendor).get(r.vendor_id) if r.vendor_id else None
            price_history.append({
                'date': r.rcv_date.strftime('%Y-%m-%d') if r.rcv_date else '',
                'price': r.unit_price,
                'vendor': vendor.name if vendor else '-',
                'source': '자체입고',
            })

        # 2) iCUBE 입고이력에서 단가 (icube_item_cd가 있는 경우에만)
        if item.icube_item_cd:
            histories = (
                db.query(ReceivingHistory)
                .filter(ReceivingHistory.items_json.isnot(None))
                .order_by(ReceivingHistory.receive_date)
                .limit(500)
                .all()
            )
            for hist in histories:
                try:
                    items_list = json.loads(hist.items_json) if hist.items_json else []
                except (json.JSONDecodeError, TypeError):
                    continue
                for it in items_list:
                    code = (it.get('item_cd') or '').strip()
                    if code == item.icube_item_cd and (it.get('unit_price') or 0) > 0:
                        price_history.append({
                            'date': hist.receive_date.strftime('%Y-%m-%d') if hist.receive_date else '',
                            'price': it['unit_price'],
                            'vendor': hist.vendor_name or '-',
                            'source': 'iCUBE',
                        })

        price_history.sort(key=lambda x: x['date'])

        # FR-05: 관련 거래처 (이 품목을 납품한 업체들)
        related_vendors = []
        seen_vendors = set()

        # BomItem.supplier에서 - item_code 또는 item_name 매칭
        bom_supplier_filter = []
        if item.icube_item_cd:
            bom_supplier_filter.append(BomItem.item_code == item.icube_item_cd)
        if item.item_name:
            bom_supplier_filter.append(BomItem.item_name == item.item_name)

        if bom_supplier_filter:
            bom_suppliers = (
                db.query(BomItem.supplier)
                .filter(or_(*bom_supplier_filter), BomItem.supplier.isnot(None))
                .distinct()
                .all()
            )
            for (s,) in bom_suppliers:
                if s and s.strip() and s.strip() not in seen_vendors:
                    seen_vendors.add(s.strip())
                    related_vendors.append({'name': s.strip(), 'source': 'BOM'})

        # 단가이력에서 거래처 추출
        for ph in price_history:
            vn = ph.get('vendor', '')
            if vn and vn != '-' and vn not in seen_vendors:
                seen_vendors.add(vn)
                related_vendors.append({'name': vn, 'source': ph['source']})

        # FR-05: 사용되는 BOM 목록 - item_code 또는 item_name 매칭
        used_in_boms = []
        bom_filter = []
        if item.icube_item_cd:
            bom_filter.append(BomItem.item_code == item.icube_item_cd)
        if item.item_name:
            bom_filter.append(BomItem.item_name == item.item_name)

        if bom_filter:
            bom_usages = (
                db.query(BomItem, BomHeader)
                .join(BomHeader, BomItem.bom_id == BomHeader.id)
                .filter(or_(*bom_filter))
                .all()
            )
            seen_bom_ids = set()
            for bi, bh in bom_usages:
                if bh.id not in seen_bom_ids:
                    seen_bom_ids.add(bh.id)
                    used_in_boms.append({
                        'bom_id': bh.id,
                        'product_code': bh.product_code,
                        'product_category': bh.product_category or '',
                        'quantity': bi.quantity,
                    })

    return render_template('item_detail.html',
                           item=item,
                           categories=categories,
                           price_history=price_history,
                           related_vendors=related_vendors,
                           used_in_boms=used_in_boms)


# ===================================================================
# 3. 품목 수정
# ===================================================================
@item_bp.route('/item/<int:item_id>/edit', methods=['POST'])
@login_required
def item_edit(item_id):
    with get_db() as db:
        item = db.query(Item).get(item_id)
        if not item:
            flash('품목을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('item.item_list'))

        item.icube_item_cd = (request.form.get('item_code') or '').strip() or None
        item.item_name = (request.form.get('item_name') or '').strip()
        item.item_spec = (request.form.get('item_spec') or '').strip() or None
        item.unit = (request.form.get('unit') or '').strip() or None
        item.category = (request.form.get('category') or '').strip() or None
        item.manufacturer = (request.form.get('manufacturer') or '').strip() or None
        item.note = (request.form.get('note') or '').strip() or None
        item.is_active = request.form.get('is_active') == '1'

        db.commit()
        flash('품목이 수정되었습니다.', 'success')

    return redirect(url_for('item.item_detail', item_id=item_id))


# ===================================================================
# 4. 품목 신규 등록
# ===================================================================
@item_bp.route('/item/create', methods=['GET', 'POST'])
@login_required
def item_create():
    if request.method == 'POST':
        with get_db() as db:
            item_code = (request.form.get('item_code') or '').strip() or None
            item_name = (request.form.get('item_name') or '').strip()

            if not item_name:
                flash('품명은 필수입니다.', 'warning')
                return redirect(url_for('item.item_create'))

            # 품번 중복 체크
            if item_code:
                existing = db.query(Item).filter_by(icube_item_cd=item_code).first()
                if existing:
                    flash(f'이미 등록된 품번입니다: {item_code}', 'warning')
                    return redirect(url_for('item.item_create'))

            new_item = Item(
                icube_item_cd=item_code,
                item_name=item_name,
                item_spec=(request.form.get('item_spec') or '').strip() or None,
                unit=(request.form.get('unit') or '').strip() or None,
                category=(request.form.get('category') or '').strip() or None,
                manufacturer=(request.form.get('manufacturer') or '').strip() or None,
                note=(request.form.get('note') or '').strip() or None,
                is_active=True,
            )
            db.add(new_item)
            db.commit()
            flash('품목이 등록되었습니다.', 'success')
            return redirect(url_for('item.item_detail', item_id=new_item.id))

    # GET
    with get_db() as db:
        categories = [r[0] for r in db.query(distinct(Item.category)).filter(
            Item.category.isnot(None), Item.category != ''
        ).order_by(Item.category).all()]

    return render_template('item_create.html', categories=categories)


# ===================================================================
# 5. 품목 삭제 (비활성화)
# ===================================================================
@item_bp.route('/item/<int:item_id>/delete', methods=['POST'])
@login_required
def item_delete(item_id):
    with get_db() as db:
        item = db.query(Item).get(item_id)
        if not item:
            flash('품목을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('item.item_list'))

        item.is_active = False
        db.commit()
        flash(f'품목 [{item.item_name}]이 비활성화되었습니다.', 'info')

    return redirect(url_for('item.item_list'))


# ===================================================================
# API: 카테고리 목록
# ===================================================================
@item_bp.route('/api/item/categories')
@login_required
def api_item_categories():
    with get_db() as db:
        categories = [r[0] for r in db.query(distinct(Item.category)).filter(
            Item.category.isnot(None), Item.category != ''
        ).order_by(Item.category).all()]
    return jsonify(categories)
