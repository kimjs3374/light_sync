"""
견적서 관리 Blueprint.

- 견적서 목록/생성/수정/삭제
- PDF 생성 및 다운로드
- 부과금 (부가세/이윤 등 %) 관리
- 세부견적 템플릿 (품목 세트 재사용)
"""

import datetime
import json
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session, make_response,
)
from sqlalchemy import desc, func, or_
from modules.auth_decorators import login_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import (
    Quotation, QuotationItem, QuoteTemplate, QuoteTemplateItem,
    Item, QUOTE_STATUS_CHOICES,
)

logger = logging.getLogger(__name__)

quotation_bp = Blueprint('quotation', __name__)


# ===================================================================
# 헬퍼
# ===================================================================
def _generate_quote_no(db):
    """견적번호 자동 채번: MT-YYMMDD-순번 (당일 기준)"""
    today = datetime.date.today()
    prefix = f"MT-{today.strftime('%y%m%d')}-"

    last = db.query(Quotation).filter(
        Quotation.quote_no.like(f'{prefix}%')
    ).order_by(desc(Quotation.quote_no)).first()

    if last:
        try:
            last_num = int(last.quote_no.replace(prefix, ''))
            return f'{prefix}{last_num + 1:02d}'
        except ValueError:
            pass
    return f'{prefix}01'


def _fmt_money(val):
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def _parse_items_from_form(form):
    """폼에서 품목 배열 파싱"""
    item_names = form.getlist('item_name[]')
    item_specs = form.getlist('item_spec[]')
    item_qtys = form.getlist('quantity[]')
    item_prices = form.getlist('unit_price[]')
    item_units = form.getlist('unit[]')
    item_notes = form.getlist('item_note[]')
    item_ids = form.getlist('item_id[]')

    items = []
    total = 0
    for i in range(len(item_names)):
        name = (item_names[i] if i < len(item_names) else '').strip()
        if not name:
            continue
        spec = (item_specs[i] if i < len(item_specs) else '').strip()
        qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
        price = float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0
        unit = (item_units[i] if i < len(item_units) else '').strip() or '개'
        note = (item_notes[i] if i < len(item_notes) else '').strip()
        item_id = safe_int(item_ids[i] if i < len(item_ids) else '', 0) or None
        amount = qty * price
        items.append({
            'seq': i + 1, 'item_id': item_id, 'item_name': name,
            'item_spec': spec, 'unit': unit, 'quantity': qty,
            'unit_price': price, 'amount': amount, 'note': note,
        })
        total += amount
    return items, total


def _parse_surcharges_from_form(form, supply_total):
    """폼에서 부과금 배열 파싱"""
    sc_names = form.getlist('sc_name[]')
    sc_rates = form.getlist('sc_rate[]')
    surcharges = []
    sc_total = 0
    for i in range(len(sc_names)):
        name = (sc_names[i] if i < len(sc_names) else '').strip()
        if not name:
            continue
        rate = float(sc_rates[i]) if i < len(sc_rates) and sc_rates[i] else 0
        amount = round(supply_total * rate / 100)
        surcharges.append({'name': name, 'rate': rate, 'amount': amount})
        sc_total += amount
    return surcharges, sc_total


def _save_items(db, quotation_id, items_data):
    """품목 DB 저장"""
    for item_data in items_data:
        db.add(QuotationItem(
            quotation_id=quotation_id,
            seq=item_data['seq'],
            item_id=item_data['item_id'],
            item_name=item_data['item_name'],
            item_spec=item_data['item_spec'],
            unit=item_data['unit'],
            quantity=item_data['quantity'],
            unit_price=item_data['unit_price'],
            amount=item_data['amount'],
            note=item_data['note'],
        ))


# ===================================================================
# 1. 견적서 목록
# ===================================================================
@quotation_bp.route('/quotation')
@login_required
def quotation_list():
    q = (request.args.get('q') or '').strip()
    status = (request.args.get('status') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        query = db.query(Quotation)

        if q:
            like_q = f"%{q}%"
            query = query.filter(or_(
                Quotation.quote_no.ilike(like_q),
                Quotation.customer_name.ilike(like_q),
                Quotation.project_name.ilike(like_q),
            ))
        if status and status in QUOTE_STATUS_CHOICES:
            query = query.filter(Quotation.status == status)
        if date_from:
            try:
                query = query.filter(Quotation.quote_date >= datetime.datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(Quotation.quote_date <= datetime.datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        quotes = query.order_by(desc(Quotation.quote_date), desc(Quotation.id)) \
                      .offset(offset).limit(per_page).all()

        stats = {
            'total': db.query(func.count(Quotation.id)).scalar() or 0,
            'draft': db.query(func.count(Quotation.id)).filter(Quotation.status == '작성중').scalar() or 0,
            'sent': db.query(func.count(Quotation.id)).filter(Quotation.status == '발송').scalar() or 0,
            'total_amount': db.query(func.sum(Quotation.total_amount)).scalar() or 0,
        }

        return render_template(
            'quotation_list.html',
            quotes=quotes,
            pagination=pagination,
            stats=stats,
            filters={'q': q, 'status': status, 'date_from': date_from, 'date_to': date_to},
            status_choices=QUOTE_STATUS_CHOICES,
            fmt_money=_fmt_money,
        )


# ===================================================================
# 2. 견적서 생성
# ===================================================================
@quotation_bp.route('/quotation/create', methods=['GET', 'POST'])
@login_required
def quotation_create():
    with get_db() as db:
        if request.method == 'POST':
            quote_date_str = request.form.get('quote_date', '')
            try:
                quote_date = datetime.datetime.strptime(quote_date_str, '%Y-%m-%d').date()
            except ValueError:
                quote_date = datetime.date.today()

            # 품목 파싱
            items_data, supply_total = _parse_items_from_form(request.form)

            # 부과금 파싱
            surcharges, sc_total = _parse_surcharges_from_form(request.form, supply_total)

            quotation = Quotation(
                quote_no=_generate_quote_no(db),
                quote_date=quote_date,
                validity_period=(request.form.get('validity_period') or '견적일로부터 1개월').strip(),
                delivery_date=(request.form.get('delivery_date') or '협의').strip(),
                payment_method=(request.form.get('payment_method') or '현금').strip(),
                bank_account=(request.form.get('bank_account') or '').strip() or None,
                project_name=(request.form.get('project_name') or '').strip() or None,
                customer_name=(request.form.get('customer_name') or '').strip() or None,
                customer_contact=(request.form.get('customer_contact') or '').strip() or None,
                customer_address=(request.form.get('customer_address') or '').strip() or None,
                customer_tel=(request.form.get('customer_tel') or '').strip() or None,
                customer_fax=(request.form.get('customer_fax') or '').strip() or None,
                customer_email=(request.form.get('customer_email') or '').strip() or None,
                note=(request.form.get('note') or '').strip() or None,
                tax_included='tax_included' in request.form,
                total_amount=supply_total,
                surcharges_json=json.dumps(surcharges, ensure_ascii=False) if surcharges else None,
                grand_total=supply_total + sc_total,
                status='작성중',
                created_by=session.get('user_id'),
            )
            db.add(quotation)
            db.flush()

            _save_items(db, quotation.id, items_data)
            db.commit()

            flash(f'견적서 {quotation.quote_no}가 생성되었습니다.', 'success')
            return redirect(url_for('quotation.quotation_detail', quote_id=quotation.id))

        # GET - 템플릿 목록도 전달
        templates = db.query(QuoteTemplate).order_by(desc(QuoteTemplate.id)).all()
        return render_template('quotation_create.html', templates=templates)


# ===================================================================
# 3. 견적서 상세
# ===================================================================
@quotation_bp.route('/quotation/<int:quote_id>')
@login_required
def quotation_detail(quote_id):
    with get_db() as db:
        quotation = db.query(Quotation).get(quote_id)
        if not quotation:
            abort(404)

        templates = db.query(QuoteTemplate).order_by(desc(QuoteTemplate.id)).all()

        return render_template(
            'quotation_detail.html',
            q=quotation,
            fmt_money=_fmt_money,
            status_choices=QUOTE_STATUS_CHOICES,
            templates=templates,
        )


# ===================================================================
# 4. 견적서 수정
# ===================================================================
@quotation_bp.route('/quotation/<int:quote_id>/edit', methods=['POST'])
@login_required
def quotation_edit(quote_id):
    with get_db() as db:
        quotation = db.query(Quotation).get(quote_id)
        if not quotation:
            abort(404)

        quotation.quote_date = datetime.datetime.strptime(
            request.form.get('quote_date', ''), '%Y-%m-%d'
        ).date() if request.form.get('quote_date') else quotation.quote_date
        quotation.validity_period = (request.form.get('validity_period') or '견적일로부터 1개월').strip()
        quotation.delivery_date = (request.form.get('delivery_date') or '협의').strip()
        quotation.payment_method = (request.form.get('payment_method') or '현금').strip()
        quotation.bank_account = (request.form.get('bank_account') or '').strip() or None
        quotation.project_name = (request.form.get('project_name') or '').strip() or None
        quotation.customer_name = (request.form.get('customer_name') or '').strip() or None
        quotation.customer_contact = (request.form.get('customer_contact') or '').strip() or None
        quotation.customer_address = (request.form.get('customer_address') or '').strip() or None
        quotation.customer_tel = (request.form.get('customer_tel') or '').strip() or None
        quotation.customer_fax = (request.form.get('customer_fax') or '').strip() or None
        quotation.customer_email = (request.form.get('customer_email') or '').strip() or None
        quotation.note = (request.form.get('note') or '').strip() or None
        quotation.tax_included = 'tax_included' in request.form

        # 기존 품목 삭제 후 재등록
        db.query(QuotationItem).filter_by(quotation_id=quotation.id).delete()

        items_data, supply_total = _parse_items_from_form(request.form)
        surcharges, sc_total = _parse_surcharges_from_form(request.form, supply_total)

        _save_items(db, quotation.id, items_data)
        quotation.total_amount = supply_total
        quotation.surcharges_json = json.dumps(surcharges, ensure_ascii=False) if surcharges else None
        quotation.grand_total = supply_total + sc_total
        db.commit()

        flash('견적서가 수정되었습니다.', 'success')
        return redirect(url_for('quotation.quotation_detail', quote_id=quote_id))


# ===================================================================
# 5. 견적서 삭제
# ===================================================================
@quotation_bp.route('/quotation/<int:quote_id>/delete', methods=['POST'])
@login_required
def quotation_delete(quote_id):
    with get_db() as db:
        quotation = db.query(Quotation).get(quote_id)
        if not quotation:
            abort(404)

        db.delete(quotation)
        db.commit()
        flash('견적서가 삭제되었습니다.', 'success')
        return redirect(url_for('quotation.quotation_list'))


# ===================================================================
# 6. 견적서 상태 변경
# ===================================================================
@quotation_bp.route('/quotation/<int:quote_id>/status', methods=['POST'])
@login_required
def quotation_change_status(quote_id):
    with get_db() as db:
        quotation = db.query(Quotation).get(quote_id)
        if not quotation:
            abort(404)

        new_status = request.form.get('status', '')
        if new_status not in QUOTE_STATUS_CHOICES:
            flash('유효하지 않은 상태입니다.', 'warning')
            return redirect(url_for('quotation.quotation_detail', quote_id=quote_id))

        quotation.status = new_status
        db.commit()
        flash(f'상태가 "{new_status}"로 변경되었습니다.', 'success')
        return redirect(url_for('quotation.quotation_detail', quote_id=quote_id))


# ===================================================================
# 7. PDF 다운로드
# ===================================================================
@quotation_bp.route('/quotation/<int:quote_id>/pdf')
@login_required
def quotation_pdf(quote_id):
    with get_db() as db:
        quotation = db.query(Quotation).get(quote_id)
        if not quotation:
            abort(404)

        from modules.services.quote_pdf import generate_quote_pdf
        pdf_bytes = generate_quote_pdf(quotation, quotation.items)

        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename="{quotation.quote_no}.pdf"'
        return response


# ===================================================================
# 8. 세부견적 템플릿 API
# ===================================================================
@quotation_bp.route('/api/quote-templates', methods=['GET'])
@login_required
def api_template_list():
    """템플릿 목록 (검색)"""
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(QuoteTemplate)
        if q:
            query = query.filter(QuoteTemplate.template_name.ilike(f'%{q}%'))
        templates = query.order_by(desc(QuoteTemplate.id)).limit(30).all()
        return jsonify([{
            'id': t.id,
            'name': t.template_name,
            'note': t.note or '',
            'item_count': len(t.items),
            'total': sum(i.amount for i in t.items),
        } for t in templates])


@quotation_bp.route('/api/quote-templates/<int:tpl_id>', methods=['GET'])
@login_required
def api_template_detail(tpl_id):
    """템플릿 상세 (품목 포함)"""
    with get_db() as db:
        tpl = db.query(QuoteTemplate).get(tpl_id)
        if not tpl:
            return jsonify({'error': '템플릿을 찾을 수 없습니다.'}), 404
        return jsonify({
            'id': tpl.id,
            'name': tpl.template_name,
            'note': tpl.note or '',
            'items': [{
                'item_name': i.item_name,
                'item_spec': i.item_spec or '',
                'unit': i.unit or '개',
                'quantity': i.quantity,
                'unit_price': i.unit_price,
                'amount': i.amount,
                'note': i.note or '',
            } for i in tpl.items],
        })


@quotation_bp.route('/api/quote-templates', methods=['POST'])
@login_required
def api_template_create():
    """현재 품목을 템플릿으로 저장"""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '템플릿 이름을 입력하세요.'}), 400

    items = data.get('items', [])
    if not items:
        return jsonify({'error': '품목이 없습니다.'}), 400

    try:
        with get_db() as db:
            tpl = QuoteTemplate(
                template_name=name,
                note=(data.get('note') or '').strip() or None,
                created_by=session.get('user_id'),
            )
            db.add(tpl)
            db.flush()

            for idx, item in enumerate(items):
                qty = float(item.get('quantity') or 0)
                price = float(item.get('unit_price') or 0)
                db.add(QuoteTemplateItem(
                    template_id=tpl.id,
                    seq=idx + 1,
                    item_name=(item.get('item_name') or '').strip(),
                    item_spec=(item.get('item_spec') or '').strip(),
                    unit=(item.get('unit') or '개').strip(),
                    quantity=qty,
                    unit_price=price,
                    amount=qty * price,
                    note=(item.get('note') or '').strip(),
                ))
            db.commit()
            return jsonify({'ok': True, 'id': tpl.id, 'name': tpl.template_name})
    except Exception as e:
        logger.error("템플릿 저장 오류: %s", e)
        return jsonify({'error': f'저장 실패: {str(e)[:100]}'}), 500


@quotation_bp.route('/api/quote-templates/<int:tpl_id>', methods=['DELETE'])
@login_required
def api_template_delete(tpl_id):
    """템플릿 삭제"""
    with get_db() as db:
        tpl = db.query(QuoteTemplate).get(tpl_id)
        if not tpl:
            return jsonify({'error': '템플릿을 찾을 수 없습니다.'}), 404
        db.delete(tpl)
        db.commit()
        return jsonify({'ok': True})
