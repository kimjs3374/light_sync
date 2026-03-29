"""
BOM 관리 Blueprint (Phase 4).

- BOM 목록/생성/수정/삭제
- 프로젝트별 소요 자재 자동 계산
"""

import json
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session, send_file,
)
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    BomHeader, BomItem, BomModelAlias, Contract, Project,
)
from modules.activity import log_activity
from modules.services.bom_actions import (
    parse_option_filter_text,
    get_latest_receiving_prices,
    rebuild_option_schema,
    update_bom_items,
    export_bom_excel,
    parse_bom_excel,
    compare_bom_with_db,
    save_import_cache,
    load_import_cache,
    apply_bom_import,
    calculate_material_requirement,
    create_po_from_material_requirement,
)

logger = logging.getLogger(__name__)

bom_bp = Blueprint('bom', __name__)


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

        for bom in boms:
            bom._item_count = db.query(func.count(BomItem.id)).filter(
                BomItem.bom_id == bom.id
            ).scalar() or 0
            bom._total_amount = db.query(func.sum(BomItem.amount)).filter(
                BomItem.bom_id == bom.id
            ).scalar() or 0

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
@menu_required('bom')
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
@menu_required('bom')
def bom_detail(bom_id):
    with get_db() as db:
        bom = db.query(BomHeader).options(
            joinedload(BomHeader.bom_items),
        ).get(bom_id)
        if not bom:
            abort(404)

        latest_prices = get_latest_receiving_prices(db, bom.bom_items)

        option_schema = None
        if bom.option_schema:
            try:
                option_schema = json.loads(bom.option_schema)
            except (json.JSONDecodeError, TypeError):
                pass

        aliases = db.query(BomModelAlias).filter(
            BomModelAlias.bom_id == bom.id
        ).order_by(BomModelAlias.alias_name).all()

        for bi in bom.bom_items:
            bi._option_display = ''
            if bi.option_filter:
                try:
                    pf = json.loads(bi.option_filter)
                    bi._option_display = ', '.join(f'{k}={v}' for k, v in pf.items())
                except (json.JSONDecodeError, TypeError):
                    pass

        return render_template(
            'bom_detail.html',
            bom=bom,
            latest_prices=latest_prices,
            option_schema=option_schema,
            aliases=aliases,
        )


# ===================================================================
# 3-1. BOM 별칭 추가
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>/alias', methods=['POST'])
@login_required
@menu_required('bom')
def bom_add_alias(bom_id):
    """BOM 별칭 추가"""
    data = request.get_json(silent=True) or {}
    alias_name = (data.get('alias_name') or '').strip()
    if not alias_name:
        return jsonify({'error': '별칭을 입력해주세요.'}), 400

    with get_db() as db:
        bom = db.query(BomHeader).get(bom_id)
        if not bom:
            return jsonify({'error': 'BOM을 찾을 수 없습니다.'}), 404

        # 중복 체크 (다른 BOM에 이미 등록된 경우)
        existing = db.query(BomModelAlias).filter(
            BomModelAlias.alias_name == alias_name
        ).first()
        if existing:
            if existing.bom_id == bom_id:
                return jsonify({'error': f'이미 등록된 별칭입니다.'}), 409
            other_bom = db.query(BomHeader).get(existing.bom_id)
            other_name = other_bom.product_name if other_bom else f'BOM #{existing.bom_id}'
            return jsonify({'error': f'다른 BOM({other_name})에 등록된 별칭입니다.'}), 409

        alias = BomModelAlias(
            bom_id=bom_id,
            alias_name=alias_name,
            alias_type='manual',
            created_by=session.get('full_name', ''),
        )
        db.add(alias)
        db.flush()

        log_activity(db, 'BOM', 'alias_add',
                     f'{bom.product_name} 별칭 추가: {alias_name}',
                     ref_type='BomHeader', ref_id=bom_id)
        db.commit()

        return jsonify({'id': alias.id, 'alias_name': alias.alias_name}), 201


# ===================================================================
# 3-2. BOM 별칭 삭제
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>/alias/<int:alias_id>', methods=['DELETE'])
@login_required
@menu_required('bom')
def bom_delete_alias(bom_id, alias_id):
    """BOM 별칭 삭제"""
    with get_db() as db:
        alias = db.query(BomModelAlias).filter(
            BomModelAlias.id == alias_id,
            BomModelAlias.bom_id == bom_id,
        ).first()
        if not alias:
            return jsonify({'error': '별칭을 찾을 수 없습니다.'}), 404

        bom = db.query(BomHeader).get(bom_id)
        alias_name = alias.alias_name

        db.delete(alias)
        log_activity(db, 'BOM', 'alias_delete',
                     f'{bom.product_name if bom else "BOM"} 별칭 삭제: {alias_name}',
                     ref_type='BomHeader', ref_id=bom_id)
        db.commit()

    return jsonify({'ok': True})


# ===================================================================
# 4. BOM 수정
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>/edit', methods=['POST'])
@login_required
@menu_required('bom')
def bom_edit(bom_id):
    with get_db() as db:
        bom = db.query(BomHeader).get(bom_id)
        if not bom:
            abort(404)

        bom.product_name = (request.form.get('product_name') or bom.product_name).strip()
        bom.version = (request.form.get('version') or bom.version).strip()
        bom.note = (request.form.get('note') or '').strip()
        bom.is_active = request.form.get('is_active') == 'on'

        form_data = {
            'item_name[]': request.form.getlist('item_name[]'),
            'item_spec[]': request.form.getlist('item_spec[]'),
            'quantity[]': request.form.getlist('quantity[]'),
            'unit[]': request.form.getlist('unit[]'),
            'item_note[]': request.form.getlist('item_note[]'),
            'unit_price[]': request.form.getlist('unit_price[]'),
            'option_filter[]': request.form.getlist('option_filter[]'),
        }
        update_bom_items(db, bom, form_data)

        db.commit()
        flash('BOM이 수정되었습니다.', 'success')
        return redirect(url_for('bom.bom_detail', bom_id=bom_id))


# ===================================================================
# 5. BOM 삭제
# ===================================================================
@bom_bp.route('/bom/<int:bom_id>/delete', methods=['POST'])
@login_required
@menu_required('bom')
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
# 5-1. BOM 일괄 삭제
# ===================================================================
@bom_bp.route('/bom/bulk-delete', methods=['POST'])
@login_required
@menu_required('bom')
def bom_bulk_delete():
    ids = request.form.getlist('bom_ids')
    if not ids:
        flash('삭제할 BOM을 선택해주세요.', 'warning')
        return redirect(url_for('bom.bom_list'))

    with get_db() as db:
        deleted = 0
        for bom_id_str in ids:
            bom_id = safe_int(bom_id_str, 0)
            if not bom_id:
                continue
            bom = db.query(BomHeader).get(bom_id)
            if bom:
                db.delete(bom)
                deleted += 1
        db.commit()

    flash(f'BOM {deleted}건이 삭제되었습니다.', 'success')
    return redirect(url_for('bom.bom_list'))


# ===================================================================
# 5-1b. BOM 일괄 비활성화
# ===================================================================
@bom_bp.route('/bom/bulk-deactivate', methods=['POST'])
@login_required
@menu_required('bom')
def bom_bulk_deactivate():
    ids = request.form.getlist('bom_ids')
    if not ids:
        flash('비활성화할 BOM을 선택해주세요.', 'warning')
        return redirect(url_for('bom.bom_list'))

    with get_db() as db:
        count = 0
        for bom_id_str in ids:
            bom_id = safe_int(bom_id_str, 0)
            if not bom_id:
                continue
            bom = db.query(BomHeader).get(bom_id)
            if bom and bom.is_active:
                bom.is_active = False
                count += 1
        db.commit()

    flash(f'BOM {count}건이 비활성화되었습니다.', 'info')
    return redirect(url_for('bom.bom_list'))


# ===================================================================
# 5-2. BOM 엑셀 다운로드
# ===================================================================
@bom_bp.route('/bom/export')
@login_required
def bom_export():
    with get_db() as db:
        output = export_bom_excel(db)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='BOM_목록.xlsx',
    )


# ===================================================================
# 5-3. BOM 엑셀 임포트
# ===================================================================
@bom_bp.route('/bom/import', methods=['GET', 'POST'])
@login_required
@menu_required('bom')
def bom_import():
    if request.method == 'POST':
        action = request.form.get('action', '')

        # --- 1단계: 엑셀 업로드 → 비교 ---
        if action == 'upload':
            file = request.files.get('file')
            if not file or not file.filename.endswith(('.xlsx', '.xls')):
                flash('엑셀 파일(.xlsx)을 선택해주세요.', 'warning')
                return redirect(url_for('bom.bom_import'))

            parsed_boms, error = parse_bom_excel(file)
            if error:
                flash(f'엑셀 파일 읽기 실패: {error}', 'danger')
                return redirect(url_for('bom.bom_import'))

            if not parsed_boms:
                flash('엑셀에서 BOM 데이터를 찾을 수 없습니다. 헤더(완제품코드/품목명 등)를 확인해주세요.', 'warning')
                return redirect(url_for('bom.bom_import'))

            with get_db() as db:
                results = compare_bom_with_db(db, parsed_boms)

            cache_id = save_import_cache(parsed_boms, results)

            new_count = sum(1 for r in results if r['status'] == 'new')
            changed_count = sum(1 for r in results if r['status'] == 'changed')
            same_count = sum(1 for r in results if r['status'] == 'same')

            return render_template('bom_import.html',
                                   results=results,
                                   new_count=new_count,
                                   changed_count=changed_count,
                                   same_count=same_count,
                                   cache_id=cache_id,
                                   step='compare')

        # --- 2단계: 선택 항목 적용 ---
        elif action == 'apply':
            cache_id = request.form.get('cache_id', '')
            cache_data = load_import_cache(cache_id)
            if not cache_data:
                flash('비교 데이터가 만료되었습니다. 다시 업로드해주세요.', 'warning')
                return redirect(url_for('bom.bom_import'))

            selected = set(request.form.getlist('selected'))

            with get_db() as db:
                added_boms, updated_boms = apply_bom_import(
                    db, cache_data['parsed'], cache_data['results'], selected
                )
                db.commit()

            msg_parts = []
            if added_boms:
                msg_parts.append(f'신규 {added_boms}건 생성')
            if updated_boms:
                msg_parts.append(f'{updated_boms}건 갱신')
            flash(', '.join(msg_parts) + ' 완료!', 'success')
            return redirect(url_for('bom.bom_list'))

    # GET
    return render_template('bom_import.html', step='upload')


# ===================================================================
# 6. 프로젝트별 소요 자재 자동 계산
# ===================================================================
@bom_bp.route('/bom/material-requirement')
@login_required
@menu_required('bom')
def material_requirement():
    contract_id = safe_int(request.args.get('contract_id'), 0)

    with get_db() as db:
        contracts = db.query(Contract).join(Project).filter(
            Project.status != '완료'
        ).order_by(desc(Contract.id)).limit(50).all()

        selected_contract = None
        requirement = []

        if contract_id:
            selected_contract, requirement = calculate_material_requirement(db, contract_id)

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
@menu_required('bom')
def create_po_from_requirement():
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
        created_pos = create_po_from_material_requirement(
            db, contract_id, selected_items, session.get('user_id')
        )
        if not created_pos:
            flash('계약을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('bom.material_requirement'))
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
