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
import logging

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session, send_file,
)
from sqlalchemy import desc
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    Item, StockAudit, StockAuditItem, StockMovement,
    MOVEMENT_TYPE_LABELS,
)
from modules.services.inventory_utils import (
    record_stock_movement, confirm_audit, calc_turnover_rate,
)
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
