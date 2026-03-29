"""
재고관리 Blueprint (Inventory Management).

- 재고 현황 대시보드
- 가용재고 조회
- 재고실사 (생성/상세/저장/확정)
- 재고 변동 이력
- 재고회전율 분석
- 엑셀 다운로드
- 수동 재고 조정 / 안전재고 설정
"""

import datetime
import json
import logging

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session, send_file,
)
from sqlalchemy import desc, or_
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    Item, StockAudit, StockAuditItem, StockMovement,
    StockConsumption, StockConsumptionItem, MOVEMENT_TYPE_LABELS,
)
from modules.services.inventory_utils import (
    record_stock_movement, confirm_audit, calc_turnover_rate,
)
from modules.activity import log_activity
from modules.services.inventory_actions import (
    fmt_money,
    get_dashboard_data, get_bom_stock_data, search_bom_headers,
    get_filtered_items, create_audit, get_audit_categories,
    get_audit_detail, save_audit_quantities,
    build_audit_template_excel, parse_audit_upload,
    calc_audit_report_stats, build_audit_report_excel,
    build_inventory_export_excel,
    get_inventory_summary, get_low_stock_items,
    query_movements, load_items_map, get_category_list,
    get_shortage_data, get_bom_breakdown, register_consumption,
)

logger = logging.getLogger(__name__)

inventory_bp = Blueprint('inventory', __name__)


# -- 1. 재고 현황 대시보드 --
@inventory_bp.route('/inventory')
@login_required
def inventory_dashboard():
    with get_db() as db:
        data = get_dashboard_data(db)
        return render_template(
            'inventory_dashboard.html',
            fmt_money=fmt_money,
            movement_labels=MOVEMENT_TYPE_LABELS,
            **data,
        )


# -- 1-1. BOM 기준 가용재고 조회 --
@inventory_bp.route('/inventory/bom-stock')
@login_required
def bom_stock():
    q = (request.args.get('q') or '').strip()
    bom_id = safe_int(request.args.get('bom_id'), 0)

    with get_db() as db:
        data = get_bom_stock_data(db, q, bom_id)
        return render_template(
            'inventory_bom_stock.html',
            q=q, bom_id=bom_id,
            **data,
        )


@inventory_bp.route('/api/inventory/bom-search')
@login_required
def api_bom_search():
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify([])
    with get_db() as db:
        return jsonify(search_bom_headers(db, q))


# -- 2. 가용재고 조회 --
@inventory_bp.route('/inventory/items')
@login_required
def inventory_items():
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    stock_status = (request.args.get('stock_status') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 50

    with get_db() as db:
        filtered, categories = get_filtered_items(db, q, category, stock_status)

        total = len(filtered)
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page
        page_items = filtered[offset:offset + per_page]

        return render_template(
            'inventory_items.html',
            items=page_items,
            pagination=pagination,
            q=q, category=category, stock_status=stock_status,
            categories=categories,
            total=total,
            fmt_money=fmt_money,
        )


# -- 3. 재고실사 목록 --
@inventory_bp.route('/inventory/audit')
@login_required
def audit_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        query = db.query(StockAudit).order_by(desc(StockAudit.audit_date), desc(StockAudit.id))
        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page
        audits = query.offset(offset).limit(per_page).all()

        return render_template(
            'inventory_audit_list.html',
            audits=audits,
            pagination=pagination,
        )


# -- 4. 재고실사 생성 --
@inventory_bp.route('/inventory/audit/create', methods=['GET', 'POST'])
@login_required
@menu_required('inventory')
def audit_create():
    with get_db() as db:
        if request.method == 'POST':
            auditor_name = (request.form.get('auditor_name') or '').strip()
            if not auditor_name:
                auditor_name = session.get('full_name', '사용자')

            audit, count = create_audit(
                db,
                audit_date_str=request.form.get('audit_date', ''),
                auditor_name=auditor_name,
                note=(request.form.get('note') or '').strip(),
                target_category=(request.form.get('target_category') or '').strip(),
                auditor_id=session.get('user_id'),
            )
            log_activity(db, '재고관리', 'audit', f'재고 실사 생성 {audit.audit_no} ({count}개 품목)', ref_type='StockAudit', ref_id=audit.id)
            flash(f'실사 {audit.audit_no}이 생성되었습니다. ({count}개 품목)', 'success')
            return redirect(url_for('inventory.audit_detail', audit_id=audit.id))

        # GET
        categories = get_audit_categories(db)
        return render_template(
            'inventory_audit_create.html',
            categories=categories,
            today=datetime.date.today().strftime('%Y-%m-%d'),
            user_name=session.get('full_name', ''),
        )


# -- 5. 재고실사 상세 (수량 입력) --
@inventory_bp.route('/inventory/audit/<int:audit_id>')
@login_required
@menu_required('inventory')
def audit_detail(audit_id):
    with get_db() as db:
        audit, audit_items, items_map = get_audit_detail(db, audit_id)
        if not audit:
            abort(404)
        return render_template(
            'inventory_audit_detail.html',
            audit=audit,
            audit_items=audit_items,
            items_map=items_map,
        )


# -- 6. 재고실사 수량 저장 (임시저장) --
@inventory_bp.route('/inventory/audit/<int:audit_id>/save', methods=['POST'])
@login_required
@menu_required('inventory')
def audit_save(audit_id):
    with get_db() as db:
        audit = db.query(StockAudit).get(audit_id)
        if not audit or audit.status != '진행중':
            flash('저장할 수 없는 상태입니다.', 'warning')
            return redirect(url_for('inventory.audit_list'))

        saved_count = save_audit_quantities(db, audit_id, request.form)
        log_activity(db, '재고관리', 'audit_save', f'재고 실사 수량 저장 {audit.audit_no} ({saved_count}건)', ref_type='StockAudit', ref_id=audit_id)
        flash(f'{saved_count}건이 저장되었습니다.', 'success')
        return redirect(url_for('inventory.audit_detail', audit_id=audit_id))


# -- 7. 재고실사 조정 확정 --
@inventory_bp.route('/inventory/audit/<int:audit_id>/confirm', methods=['POST'])
@login_required
@menu_required('inventory')
def audit_confirm(audit_id):
    with get_db() as db:
        audit = db.query(StockAudit).get(audit_id)
        if not audit or audit.status != '진행중':
            flash('확정할 수 없는 상태입니다.', 'warning')
            return redirect(url_for('inventory.audit_list'))

        confirmed_by = session.get('full_name', '사용자')
        count = confirm_audit(db, audit_id, confirmed_by)
        log_activity(db, '재고관리', 'audit', f'재고 실사 확정 {audit.audit_no} ({count}건 조정)', ref_type='StockAudit', ref_id=audit.id)
        db.commit()

        if count > 0:
            flash(f'실사 조정 확정 완료: {count}건 재고가 조정되었습니다.', 'success')
        else:
            flash('조정할 차이 항목이 없습니다.', 'info')

        return redirect(url_for('inventory.audit_detail', audit_id=audit_id))


# -- 7-0. 실사 삭제 --
@inventory_bp.route('/inventory/audit/<int:audit_id>/delete', methods=['POST'])
@login_required
@menu_required('inventory')
def audit_delete(audit_id):
    with get_db() as db:
        audit = db.query(StockAudit).get(audit_id)
        if not audit:
            abort(404)
        if audit.status == '완료':
            flash('확정된 실사는 삭제할 수 없습니다.', 'warning')
            return redirect(url_for('inventory.audit_detail', audit_id=audit_id))

        db.query(StockAuditItem).filter(StockAuditItem.audit_id == audit_id).delete()
        log_activity(db, '재고관리', 'delete', f'재고 실사 삭제 {audit.audit_no}', ref_type='StockAudit')
        db.delete(audit)
        db.commit()
        flash(f'실사 {audit.audit_no}이 삭제되었습니다.', 'success')
        return redirect(url_for('inventory.audit_list'))


# -- 7-1. 실사 엑셀 템플릿 다운로드 --
@inventory_bp.route('/inventory/audit/<int:audit_id>/template-download')
@login_required
def audit_template_download(audit_id):
    with get_db() as db:
        audit, audit_items, items_map = get_audit_detail(db, audit_id)
        if not audit:
            abort(404)

        buf = build_audit_template_excel(audit, audit_items, items_map)
        fname = f'실사템플릿_{audit.audit_no}_{audit.audit_date}.xlsx'
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# -- 7-2. 실사 엑셀 업로드 (실재고 반영) --
@inventory_bp.route('/inventory/audit/<int:audit_id>/upload', methods=['POST'])
@login_required
@menu_required('inventory')
def audit_upload(audit_id):
    with get_db() as db:
        audit = db.query(StockAudit).get(audit_id)
        if not audit or audit.status != '진행중':
            flash('업로드할 수 없는 상태입니다.', 'warning')
            return redirect(url_for('inventory.audit_list'))

        file = request.files.get('audit_file')
        if not file or not file.filename.endswith(('.xlsx', '.xls')):
            flash('엑셀 파일(.xlsx)을 선택해주세요.', 'danger')
            return redirect(url_for('inventory.audit_detail', audit_id=audit_id))

        try:
            updated, errors = parse_audit_upload(db, audit_id, file)
        except Exception as e:
            flash(f'엑셀 파일 읽기 실패: {e}', 'danger')
            return redirect(url_for('inventory.audit_detail', audit_id=audit_id))

        msg = f'엑셀 업로드 완료: {updated}건 반영'
        if errors:
            msg += f', {len(errors)}건 오류 ({", ".join(errors[:5])})'
        flash(msg, 'success' if updated > 0 else 'warning')
        return redirect(url_for('inventory.audit_detail', audit_id=audit_id))


# -- 7-3. 실사 차이 보고서 --
@inventory_bp.route('/inventory/audit/<int:audit_id>/report')
@login_required
def audit_report(audit_id):
    with get_db() as db:
        audit, audit_items, items_map = get_audit_detail(db, audit_id)
        if not audit:
            abort(404)

        stats = calc_audit_report_stats(audit_items, items_map)

        if request.args.get('format') == 'excel':
            buf = build_audit_report_excel(audit, audit_items, items_map, stats)
            fname = f'실사보고서_{audit.audit_no}_{audit.audit_date}.xlsx'
            return send_file(buf, as_attachment=True, download_name=fname,
                             mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        return render_template(
            'inventory_audit_report.html',
            audit=audit,
            audit_items=audit_items,
            items_map=items_map,
            diff_items=stats['diff_items_list'],
            total_items=stats['total_items'],
            counted_items=stats['counted_items'],
            match_items=stats['match_items'],
            total_system_value=stats['total_system_value'],
            total_actual_value=stats['total_actual_value'],
            total_diff_value=stats['total_diff_value'],
        )


# -- 8. 재고 변동 이력 --
@inventory_bp.route('/inventory/movements')
@login_required
def movement_list():
    q = (request.args.get('q') or '').strip()
    m_type = (request.args.get('type') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 50

    with get_db() as db:
        q_obj = query_movements(db, q, m_type, date_from, date_to)

        total = q_obj.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page
        movements = q_obj.order_by(desc(StockMovement.created_at)).offset(offset).limit(per_page).all()

        items_map = load_items_map(db, list(set(m.item_id for m in movements)))

        return render_template(
            'inventory_movements.html',
            movements=movements,
            items_map=items_map,
            pagination=pagination,
            movement_labels=MOVEMENT_TYPE_LABELS,
            filters={'q': q, 'type': m_type, 'date_from': date_from, 'date_to': date_to},
            fmt_money=fmt_money,
        )


# -- 9. 재고회전율 분석 --
@inventory_bp.route('/inventory/turnover')
@login_required
def turnover_report():
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    category = (request.args.get('category') or '').strip()

    if not date_from:
        date_from = (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
    if not date_to:
        date_to = datetime.date.today().strftime('%Y-%m-%d')

    with get_db() as db:
        try:
            start_dt = datetime.datetime.strptime(date_from, '%Y-%m-%d')
            end_dt = datetime.datetime.strptime(date_to, '%Y-%m-%d') + datetime.timedelta(days=1)
        except ValueError:
            start_dt = datetime.datetime.now() - datetime.timedelta(days=90)
            end_dt = datetime.datetime.now()

        results = calc_turnover_rate(db, start_dt, end_dt, category or None)
        results.sort(key=lambda x: x['turnover'], reverse=True)

        return render_template(
            'inventory_turnover.html',
            results=results,
            categories=get_category_list(db),
            filters={'date_from': date_from, 'date_to': date_to, 'category': category},
            fmt_money=fmt_money,
        )


# -- 10. 수동 재고 조정 --
@inventory_bp.route('/inventory/item/<int:item_id>/adjust', methods=['POST'])
@login_required
@menu_required('inventory')
def item_adjust(item_id):
    with get_db() as db:
        item = db.query(Item).get(item_id)
        if not item:
            abort(404)

        adjust_qty_raw = request.form.get('adjust_qty', '').strip()
        adjust_reason = (request.form.get('adjust_reason') or '').strip()

        if not adjust_qty_raw:
            flash('조정 수량을 입력해주세요.', 'warning')
            return redirect(url_for('inventory.inventory_items'))
        if not adjust_reason:
            flash('조정 사유를 입력해주세요.', 'warning')
            return redirect(url_for('inventory.inventory_items'))

        try:
            adjust_qty = float(adjust_qty_raw)
        except (ValueError, TypeError):
            flash('유효한 수량을 입력해주세요.', 'warning')
            return redirect(url_for('inventory.inventory_items'))

        movement_type = 'IN_ADJUST' if adjust_qty > 0 else 'OUT_ADJUST'
        user_name = session.get('full_name', '사용자')

        record_stock_movement(
            db, item_id,
            movement_type=movement_type,
            quantity=adjust_qty,
            note=f'수동조정: {adjust_reason}',
            created_by=user_name,
        )
        log_activity(db, '재고관리', 'movement', f'{item.item_name} 수동조정 {adjust_qty:+g}', ref_type='StockMovement', ref_id=item.id)
        db.commit()
        flash(f'[{item.item_name}] 재고가 {adjust_qty:+g} 조정되었습니다.', 'success')

    return redirect(url_for('inventory.inventory_items'))


# -- 11. 안전재고 설정 --
@inventory_bp.route('/inventory/item/<int:item_id>/safety-stock', methods=['POST'])
@login_required
@menu_required('inventory')
def item_safety_stock(item_id):
    with get_db() as db:
        item = db.query(Item).get(item_id)
        if not item:
            abort(404)

        safety_raw = request.form.get('safety_stock', '').strip()
        try:
            item.safety_stock = max(0, float(safety_raw))
        except (ValueError, TypeError):
            item.safety_stock = 0

        log_activity(db, '재고관리', 'update', f'{item.item_name} 안전재고 설정 {item.safety_stock}', ref_type='Item', ref_id=item.id)
        db.commit()
        flash(f'[{item.item_name}] 안전재고가 {item.safety_stock}으로 설정되었습니다.', 'success')

    return redirect(url_for('inventory.inventory_items'))


# -- 12. 엑셀 다운로드 --
@inventory_bp.route('/inventory/export')
@login_required
def inventory_export():
    with get_db() as db:
        output = build_inventory_export_excel(db)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'재고현황_{datetime.date.today().strftime("%Y%m%d")}.xlsx',
    )


# -- API: 대시보드 통계 JSON --
@inventory_bp.route('/api/inventory/summary')
@login_required
def api_inventory_summary():
    with get_db() as db:
        return jsonify(get_inventory_summary(db))


# -- API: 저재고 품목 JSON --
@inventory_bp.route('/api/inventory/low-stock')
@login_required
def api_low_stock():
    with get_db() as db:
        return jsonify(get_low_stock_items(db))


# -- 13. 부족자재 뷰 --
@inventory_bp.route('/inventory/shortage')
@login_required
def shortage_view():
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    exclude_processing = request.args.get('exclude_processing', '1') == '1'

    with get_db() as db:
        data = get_shortage_data(db, category=category, q=q, exclude_processing=exclude_processing)
        categories = get_category_list(db)
        return render_template(
            'inventory_shortage.html',
            items=data,
            q=q, category=category,
            exclude_processing=exclude_processing,
            categories=categories,
            fmt_money=fmt_money,
        )


# -- 14. 소진 등록 폼 --
@inventory_bp.route('/inventory/consume')
@login_required
@menu_required('inventory')
def consume_form():
    with get_db() as db:
        # 최근 소진 이력
        recent = db.query(StockConsumption).order_by(desc(StockConsumption.created_at)).limit(10).all()

        return render_template(
            'inventory_consume.html',
            recent_consumptions=recent,
            today=datetime.date.today().strftime('%Y-%m-%d'),
        )


# -- 15. 소진 실행 --
@inventory_bp.route('/inventory/consume', methods=['POST'])
@login_required
@menu_required('inventory')
def consume_execute():
    with get_db() as db:
        model_name = (request.form.get('model_name') or '').strip()
        quantity = safe_int(request.form.get('quantity'), 0)
        bom_id = safe_int(request.form.get('bom_id'), 0) or None
        tx_date_str = (request.form.get('tx_date') or '').strip()
        project_id = safe_int(request.form.get('project_id'), 0) or None
        contract_item_id = safe_int(request.form.get('contract_item_id'), 0) or None
        note = (request.form.get('note') or '').strip()

        if not model_name or quantity <= 0:
            flash('모델명과 수량을 입력해주세요.', 'warning')
            return redirect(url_for('inventory.consume_form'))

        try:
            tx_date = datetime.datetime.strptime(tx_date_str, '%Y-%m-%d').date()
        except ValueError:
            tx_date = datetime.date.today()

        # 폼에서 자재별 소진수량 파싱
        items_data = []
        item_ids = request.form.getlist('item_id[]')
        for i, item_id_str in enumerate(item_ids):
            item_id = safe_int(item_id_str, 0)
            if not item_id:
                continue
            consumed_qty = float(request.form.getlist('consumed_qty[]')[i] or 0)
            if consumed_qty <= 0:
                continue
            bom_item_id = safe_int(request.form.getlist('bom_item_id[]')[i], 0) or None
            required_qty = float(request.form.getlist('required_qty[]')[i] or 0)
            item_note = (request.form.getlist('item_note[]')[i] if i < len(request.form.getlist('item_note[]')) else '')
            items_data.append({
                'item_id': item_id,
                'bom_item_id': bom_item_id,
                'required_qty': required_qty,
                'consumed_qty': consumed_qty,
                'note': item_note,
            })

        if not items_data:
            flash('소진할 자재를 선택해주세요.', 'warning')
            return redirect(url_for('inventory.consume_form'))

        created_by = session.get('full_name', '사용자')
        consumption = register_consumption(
            db, model_name, quantity, bom_id, tx_date,
            project_id, contract_item_id, items_data, note, created_by
        )

        log_activity(db, '재고관리', 'consumption',
                     f'{model_name} x{quantity} 소진등록 ({len(items_data)}개 자재)',
                     ref_type='StockConsumption', ref_id=consumption.id)
        db.commit()

        flash(f'{model_name} x{quantity} 소진이 등록되었습니다. ({len(items_data)}개 자재 차감)', 'success')
        return redirect(url_for('inventory.consume_form'))


# -- 16. BOM 분해 미리보기 API --
@inventory_bp.route('/api/inventory/bom-breakdown')
@login_required
def api_bom_breakdown():
    bom_id = safe_int(request.args.get('bom_id'), 0)
    quantity = safe_int(request.args.get('quantity'), 1)
    option_filter_str = request.args.get('option_filter', '')
    option_filter = None
    if option_filter_str:
        try:
            option_filter = json.loads(option_filter_str)
        except (json.JSONDecodeError, TypeError):
            pass
    if not bom_id:
        return jsonify([])
    with get_db() as db:
        data = get_bom_breakdown(db, bom_id, quantity, option_filter=option_filter)
        db.commit()  # BOM 미연결 부품 자동생성 시 반영
        return jsonify(data)


# -- 17. 재고 조정 폼 --
@inventory_bp.route('/inventory/adjust')
@login_required
@menu_required('inventory')
def adjust_form():
    with get_db() as db:
        categories = get_category_list(db)
        # 최근 조정 이력
        recent = db.query(StockMovement).filter(
            StockMovement.movement_type.in_(['IN_ADJUST', 'OUT_ADJUST'])
        ).order_by(desc(StockMovement.created_at)).limit(10).all()
        items_map = load_items_map(db, [m.item_id for m in recent])
        return render_template(
            'inventory_adjust.html',
            categories=categories,
            recent_adjustments=recent,
            items_map=items_map,
            movement_labels=MOVEMENT_TYPE_LABELS,
            today=datetime.date.today().strftime('%Y-%m-%d'),
        )


# -- 18. 재고 조정 실행 (다건) --
@inventory_bp.route('/inventory/adjust', methods=['POST'])
@login_required
@menu_required('inventory')
def adjust_execute():
    with get_db() as db:
        item_ids = request.form.getlist('item_id[]')
        adjust_qtys = request.form.getlist('adjust_qty[]')
        reasons = request.form.getlist('reason[]')
        tx_date_str = (request.form.get('tx_date') or '').strip()

        try:
            tx_date = datetime.datetime.strptime(tx_date_str, '%Y-%m-%d').date()
        except ValueError:
            tx_date = datetime.date.today()

        created_by = session.get('full_name', '사용자')
        adjusted_count = 0

        for i, item_id_str in enumerate(item_ids):
            item_id = safe_int(item_id_str, 0)
            if not item_id:
                continue
            try:
                qty = float(adjust_qtys[i])
            except (ValueError, IndexError):
                continue
            if qty == 0:
                continue
            reason = reasons[i] if i < len(reasons) else ''

            movement_type = 'IN_ADJUST' if qty > 0 else 'OUT_ADJUST'
            record_stock_movement(
                db, item_id,
                movement_type=movement_type,
                quantity=qty,
                note=f'재고조정: {reason}',
                created_by=created_by,
                tx_date=tx_date,
            )
            adjusted_count += 1

        if adjusted_count > 0:
            log_activity(db, '재고관리', 'adjustment',
                         f'재고조정 {adjusted_count}건 ({tx_date})',
                         ref_type='StockMovement')
            db.commit()
            flash(f'{adjusted_count}건의 재고가 조정되었습니다.', 'success')
        else:
            flash('조정할 항목이 없습니다.', 'warning')

        return redirect(url_for('inventory.adjust_form'))


# -- 19. API: 품목 검색 (자동완성) --
@inventory_bp.route('/api/inventory/item-search')
@login_required
def api_item_search():
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify([])
    with get_db() as db:
        items = db.query(Item).filter(
            Item.is_active == True,
            or_(Item.item_name.ilike(f'%{q}%'),
                Item.icube_item_cd.ilike(f'%{q}%'),
                Item.item_spec.ilike(f'%{q}%'))
        ).limit(20).all()
        return jsonify([{
            'id': i.id,
            'item_name': i.item_name,
            'item_code': i.icube_item_cd or '',
            'item_spec': i.item_spec or '',
            'category': i.category or '',
            'stock_qty': i.stock_qty or 0,
        } for i in items])


# -- 20. API: 계약 검색 (소진등록용) --
@inventory_bp.route('/api/inventory/contract-search')
@login_required
def api_contract_search():
    """계약명 검색 → 계약 목록 반환 (소진등록용)"""
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify([])
    with get_db() as db:
        from modules.models import Contract, Project
        contracts = db.query(Contract).filter(
            Contract.contract_name.ilike(f'%{q}%')
        ).order_by(desc(Contract.id)).limit(15).all()
        result = []
        for c in contracts:
            project = db.query(Project).get(c.project_id) if c.project_id else None
            result.append({
                'id': c.id,
                'contract_name': c.contract_name,
                'project_id': c.project_id,
                'project_name': project.temp_name if project else '',
            })
        return jsonify(result)


# -- 21. API: 계약 품목 조회 (소진등록용) --
@inventory_bp.route('/api/inventory/contract-items/<int:contract_id>')
@login_required
def api_contract_items(contract_id):
    """계약의 품목 목록 + BOM 매칭 정보 반환"""
    with get_db() as db:
        from modules.models import ContractItem, Contract
        from modules.services.bom_actions import find_bom_by_model_name
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify([])

        items = db.query(ContractItem).filter(
            ContractItem.contract_id == contract_id
        ).order_by(ContractItem.id).all()

        result = []
        for ci in items:
            # BOM 매칭 (별칭 우선 → product_code → product_name fallback)
            bom = find_bom_by_model_name(db, ci.model_name) if ci.model_name else None

            result.append({
                'contract_item_id': ci.id,
                'category': ci.category or '',
                'model_name': ci.model_name or '',
                'quantity': ci.quantity or 0,
                'status_prod': ci.status_prod or '',
                'bom_id': bom.id if bom else None,
                'bom_name': bom.product_name if bom else '',
                'option_schema': json.loads(bom.option_schema) if bom and bom.option_schema else None,
                'item_spec': ci.item_spec or {},
            })

        return jsonify({
            'contract_name': contract.contract_name,
            'project_id': contract.project_id,
            'items': result,
        })


# -- 22. 소진 이력 목록 --
@inventory_bp.route('/inventory/consumption-history')
@login_required
def consumption_history():
    q = (request.args.get('q') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 30

    with get_db() as db:
        from modules.models import Project
        query = db.query(StockConsumption).order_by(desc(StockConsumption.tx_date), desc(StockConsumption.id))

        if q:
            query = query.filter(or_(
                StockConsumption.model_name.ilike(f'%{q}%'),
                StockConsumption.note.ilike(f'%{q}%'),
                StockConsumption.created_by.ilike(f'%{q}%'),
            ))
        if date_from:
            try:
                query = query.filter(StockConsumption.tx_date >= datetime.datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(StockConsumption.tx_date <= datetime.datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page
        consumptions = query.offset(offset).limit(per_page).all()

        # 현장명 매핑
        project_ids = [c.project_id for c in consumptions if c.project_id]
        projects_map = {}
        if project_ids:
            projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
            projects_map = {p.id: p.temp_name for p in projects}

        # 소진 자재건수
        item_counts = {}
        if consumptions:
            cids = [c.id for c in consumptions]
            from sqlalchemy import func as sqlfunc
            counts = db.query(
                StockConsumptionItem.consumption_id,
                sqlfunc.count(StockConsumptionItem.id)
            ).filter(StockConsumptionItem.consumption_id.in_(cids)).group_by(
                StockConsumptionItem.consumption_id
            ).all()
            item_counts = dict(counts)

        return render_template(
            'inventory_consumption_history.html',
            consumptions=consumptions,
            projects_map=projects_map,
            item_counts=item_counts,
            pagination=pagination,
            filters={'q': q, 'date_from': date_from, 'date_to': date_to},
            total=total,
        )


# -- 23. 소진 상세 조회 --
@inventory_bp.route('/inventory/consumption/<int:consumption_id>')
@login_required
def consumption_detail(consumption_id):
    with get_db() as db:
        from modules.models import Project
        consumption = db.query(StockConsumption).get(consumption_id)
        if not consumption:
            abort(404)

        # 소진 상세 자재
        sci_list = db.query(StockConsumptionItem).filter(
            StockConsumptionItem.consumption_id == consumption_id
        ).order_by(StockConsumptionItem.id).all()

        items_map = load_items_map(db, [s.item_id for s in sci_list])
        project_name = ''
        if consumption.project_id:
            proj = db.query(Project).get(consumption.project_id)
            project_name = proj.temp_name if proj else ''

        bom_name = ''
        if consumption.bom_id:
            from modules.models import BomHeader
            bom = db.query(BomHeader).get(consumption.bom_id)
            bom_name = bom.product_name if bom else ''

        return render_template(
            'inventory_consumption_detail.html',
            c=consumption,
            sci_list=sci_list,
            items_map=items_map,
            project_name=project_name,
            bom_name=bom_name,
        )


# -- 24. 소진 수정 --
@inventory_bp.route('/inventory/consumption/<int:consumption_id>/edit', methods=['POST'])
@login_required
@menu_required('inventory')
def consumption_edit(consumption_id):
    with get_db() as db:
        consumption = db.query(StockConsumption).get(consumption_id)
        if not consumption:
            abort(404)

        # 기본 정보 수정
        new_note = request.form.get('note', '').strip()
        new_tx_date_str = request.form.get('tx_date', '').strip()

        if new_tx_date_str:
            try:
                consumption.tx_date = datetime.datetime.strptime(new_tx_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        consumption.note = new_note

        # 자재별 소진수량 수정 (차이만큼 재고 보정)
        sci_ids = request.form.getlist('sci_id[]')
        new_qtys = request.form.getlist('new_consumed_qty[]')
        adjusted_count = 0
        user_name = session.get('full_name', '사용자')

        for i, sci_id_str in enumerate(sci_ids):
            sci_id = safe_int(sci_id_str, 0)
            if not sci_id:
                continue
            sci = db.query(StockConsumptionItem).get(sci_id)
            if not sci or sci.consumption_id != consumption_id:
                continue
            try:
                new_qty = float(new_qtys[i])
            except (ValueError, IndexError):
                continue
            if new_qty < 0:
                new_qty = 0

            old_qty = sci.consumed_qty or 0
            diff = new_qty - old_qty
            if abs(diff) < 0.001:
                continue

            # 재고 보정: diff > 0 → 추가 차감, diff < 0 → 복원
            record_stock_movement(
                db, sci.item_id,
                movement_type='OUT_CONSUMPTION' if diff > 0 else 'IN_ADJUST',
                quantity=-abs(diff) if diff > 0 else abs(diff),
                reference_type='stock_consumption_edit',
                reference_id=consumption.id,
                note=f'소진수정: {consumption.model_name} ({old_qty}→{new_qty})',
                created_by=user_name,
                model_name=consumption.model_name,
                project_id=consumption.project_id,
                tx_date=consumption.tx_date,
            )
            sci.consumed_qty = new_qty
            adjusted_count += 1

        if adjusted_count > 0:
            log_activity(db, '재고관리', 'consumption_edit',
                         f'{consumption.model_name} 소진수정 ({adjusted_count}개 자재)',
                         ref_type='StockConsumption', ref_id=consumption.id)
        db.commit()
        flash(f'소진 이력이 수정되었습니다.', 'success')
        return redirect(url_for('inventory.consumption_detail', consumption_id=consumption_id))


# -- 25. 소진 삭제 (재고 롤백) --
@inventory_bp.route('/inventory/consumption/<int:consumption_id>/delete', methods=['POST'])
@login_required
@menu_required('inventory')
def consumption_delete(consumption_id):
    with get_db() as db:
        consumption = db.query(StockConsumption).get(consumption_id)
        if not consumption:
            abort(404)

        user_name = session.get('full_name', '사용자')

        # 소진 상세 자재 조회 → 재고 복원
        sci_list = db.query(StockConsumptionItem).filter(
            StockConsumptionItem.consumption_id == consumption_id
        ).all()

        restored_count = 0
        for sci in sci_list:
            if sci.consumed_qty and sci.consumed_qty > 0:
                record_stock_movement(
                    db, sci.item_id,
                    movement_type='IN_ADJUST',
                    quantity=abs(sci.consumed_qty),
                    reference_type='stock_consumption_delete',
                    reference_id=consumption.id,
                    note=f'소진삭제 복원: {consumption.model_name}',
                    created_by=user_name,
                    model_name=consumption.model_name,
                    project_id=consumption.project_id,
                    tx_date=consumption.tx_date,
                )
                restored_count += 1

        model_name = consumption.model_name
        quantity = consumption.quantity

        # 상세 삭제 → 마스터 삭제
        db.query(StockConsumptionItem).filter(
            StockConsumptionItem.consumption_id == consumption_id
        ).delete()
        db.delete(consumption)

        log_activity(db, '재고관리', 'consumption_delete',
                     f'{model_name} x{quantity} 소진삭제 ({restored_count}개 자재 복원)',
                     ref_type='StockConsumption')
        db.commit()
        flash(f'{model_name} x{quantity} 소진이 삭제되고 재고가 복원되었습니다.', 'success')
        return redirect(url_for('inventory.consumption_history'))
