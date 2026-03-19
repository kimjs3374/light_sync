"""
발주서 관리 Blueprint.

- 발주서 목록/생성/수정/삭제
- PDF 생성 및 다운로드
- 이메일 발송 (거래처 EMAIL로 PDF 첨부)
"""

import datetime
import json
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session, make_response,
)
from sqlalchemy import desc, func
from modules.auth_decorators import login_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from sqlalchemy.orm import joinedload
from modules.models import (
    Vendor, Item, PurchaseOrder, PurchaseOrderItem,
    EmailHistory, EmailSignature, PurchaseOrderHistory, PO_STATUS_CHOICES,
    User, Contract, ContractItem, Project, MaterialOrder,
    BomItem, BomHeader,
)

logger = logging.getLogger(__name__)

purchase_order_bp = Blueprint('purchase_order', __name__)


# ===================================================================
# 헬퍼
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


def _fmt_money(val):
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def _sync_po_to_material_orders(db, po):
    """
    발주서 품목 → 자재관리(MaterialOrder) 연동.
    계약 연결된 발주서 발송 시 호출.
    - 이미 연동된 po_item은 스킵
    - contract_item 매칭: 품명/카테고리로 최선 매칭, 없으면 첫 번째 품목에 연결
    """
    if not po.contract_id:
        return

    contract = db.query(Contract).get(po.contract_id)
    if not contract:
        return

    # 계약의 품목 목록
    contract_items = db.query(ContractItem).filter_by(contract_id=contract.id).all()
    if not contract_items:
        return

    # 이미 연동된 po_item_id 목록
    existing_po_item_ids = set()
    existing = db.query(MaterialOrder.po_item_id).filter(
        MaterialOrder.po_id == po.id,
        MaterialOrder.po_item_id.isnot(None),
    ).all()
    for (pid,) in existing:
        existing_po_item_ids.add(pid)

    for po_item in po.items:
        if po_item.id in existing_po_item_ids:
            continue

        # contract_item 매칭: bom_item_id가 있으면 BOM 경로로 정확 매칭
        matched_ci = None
        if hasattr(po_item, 'bom_item_id') and po_item.bom_item_id:
            from modules.models import BomItem, BomHeader
            bom_item = db.query(BomItem).get(po_item.bom_item_id)
            if bom_item:
                bom_header = db.query(BomHeader).get(bom_item.bom_id)
                if bom_header:
                    # BOM 완제품명으로 contract_item 매칭
                    for ci in contract_items:
                        ci_model = (ci.model_name or '').lower()
                        if ci_model and ci_model in (bom_header.product_name or '').lower():
                            matched_ci = ci
                            break
                        if ci_model and ci_model in (bom_header.product_code or '').lower():
                            matched_ci = ci
                            break

        # fallback: 기존 품명 유사도 매칭
        if not matched_ci:
            matched_ci = contract_items[0]
            po_name = (po_item.item_name or '').lower()
            for ci in contract_items:
                ci_cat = (ci.category or '').lower()
                ci_model = (ci.model_name or '').lower()
                if ci_cat and ci_cat in po_name:
                    matched_ci = ci
                    break
                if ci_model and ci_model in po_name:
                    matched_ci = ci
                    break

        mo = MaterialOrder(
            project_id=contract.project_id,
            contract_id=contract.id,
            contract_item_id=matched_ci.id,
            item_category=matched_ci.category or '기타',
            item_model_name=po_item.item_name,
            material_name=f"{po_item.item_name} {po_item.item_spec or ''}".strip(),
            quantity=int(po_item.quantity or 0),
            order_status='발주완료',
            order_date=po.po_date,
            po_id=po.id,
            po_item_id=po_item.id,
            bom_item_id=getattr(po_item, 'bom_item_id', None),
            note=f"발주서 {po.po_no} 자동연동",
        )
        db.add(mo)


# ===================================================================
# 1. 발주서 목록
# ===================================================================
@purchase_order_bp.route('/purchase-order')
@login_required
def po_list():
    q = (request.args.get('q') or '').strip()
    status = (request.args.get('status') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        query = db.query(PurchaseOrder).join(Vendor)

        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (Vendor.name.ilike(like_q)) | (PurchaseOrder.po_no.ilike(like_q))
            )
        if status and status in PO_STATUS_CHOICES:
            query = query.filter(PurchaseOrder.status == status)

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        orders = query.order_by(desc(PurchaseOrder.po_date), desc(PurchaseOrder.id)) \
                      .offset(offset).limit(per_page).all()

        # 통계
        stats = {
            'total': db.query(func.count(PurchaseOrder.id)).scalar() or 0,
            'draft': db.query(func.count(PurchaseOrder.id)).filter(PurchaseOrder.status == '작성중').scalar() or 0,
            'sent': db.query(func.count(PurchaseOrder.id)).filter(PurchaseOrder.status == '발송완료').scalar() or 0,
        }

        # iCUBE 기존 발주이력 (PurchaseOrderHistory)
        hist_query = db.query(PurchaseOrderHistory)
        if q:
            like_q = f"%{q}%"
            hist_query = hist_query.filter(
                (PurchaseOrderHistory.vendor_name.ilike(like_q)) |
                (PurchaseOrderHistory.icube_cls_nb.ilike(like_q))
            )
        history_count = hist_query.count() if not status else 0
        hist_page = safe_int(request.args.get('hp'), 1)
        hist_per_page = 30
        hist_offset = (hist_page - 1) * hist_per_page
        history_orders = hist_query.order_by(desc(PurchaseOrderHistory.order_date)) \
                                   .offset(hist_offset).limit(hist_per_page).all() if not status else []
        hist_total_pages = (history_count + hist_per_page - 1) // hist_per_page if history_count else 0

        return render_template(
            'po_list.html',
            orders=orders,
            history_orders=history_orders,
            history_count=history_count,
            hist_page=hist_page,
            hist_total_pages=hist_total_pages,
            pagination=pagination,
            stats=stats,
            filters={'q': q, 'status': status},
            status_choices=PO_STATUS_CHOICES,
            fmt_money=_fmt_money,
        )


# ===================================================================
# 2. 발주서 생성 폼
# ===================================================================
@purchase_order_bp.route('/purchase-order/create', methods=['GET', 'POST'])
@login_required
def po_create():
    with get_db() as db:
        if request.method == 'POST':
            vendor_id = safe_int(request.form.get('vendor_id'), 0)
            po_date_str = request.form.get('po_date', '')
            note = (request.form.get('note') or '').strip()

            if not vendor_id:
                flash('거래처를 선택해주세요.', 'warning')
                return redirect(url_for('purchase_order.po_create'))

            vendor = db.query(Vendor).get(vendor_id)
            if not vendor:
                flash('거래처를 찾을 수 없습니다.', 'danger')
                return redirect(url_for('purchase_order.po_create'))

            try:
                po_date = datetime.datetime.strptime(po_date_str, '%Y-%m-%d').date()
            except ValueError:
                po_date = datetime.date.today()

            # 발주서 생성
            assigned = safe_int(request.form.get('assigned_to'), 0) or None
            contract = safe_int(request.form.get('contract_id'), 0) or None

            po = PurchaseOrder(
                po_no=_generate_po_no(db),
                po_date=po_date,
                vendor_id=vendor_id,
                assigned_to=assigned or session.get('user_id'),
                contract_id=contract,
                status='작성중',
                note=note,
                created_by=session.get('user_id'),
            )
            db.add(po)
            db.flush()

            # 품목 추가
            item_names = request.form.getlist('item_name[]')
            item_specs = request.form.getlist('item_spec[]')
            item_qtys = request.form.getlist('quantity[]')
            item_prices = request.form.getlist('unit_price[]')
            item_units = request.form.getlist('unit[]')
            item_notes = request.form.getlist('item_note[]')
            item_ids = request.form.getlist('item_id[]')

            total_amount = 0
            for i in range(len(item_names)):
                name = (item_names[i] if i < len(item_names) else '').strip()
                if not name:
                    continue

                spec = (item_specs[i] if i < len(item_specs) else '').strip()
                qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
                price = float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0
                unit = (item_units[i] if i < len(item_units) else '').strip()
                item_note = (item_notes[i] if i < len(item_notes) else '').strip()
                linked_item_id = safe_int(item_ids[i] if i < len(item_ids) else '', 0) or None
                amount = qty * price

                po_item = PurchaseOrderItem(
                    po_id=po.id,
                    item_id=linked_item_id,
                    item_name=name,
                    item_spec=spec,
                    quantity=qty,
                    unit_price=price,
                    amount=amount,
                    unit=unit,
                    note=item_note,
                )
                db.add(po_item)
                total_amount += amount

            po.total_amount = total_amount
            po.tax_amount = round(total_amount * 0.1)
            db.commit()

            flash(f'발주서 {po.po_no}가 생성되었습니다.', 'success')
            return redirect(url_for('purchase_order.po_detail', po_id=po.id))

        # GET: 폼 표시
        users = db.query(User).filter(User.is_active == True, User.is_approved == True).order_by(User.full_name).all()

        return render_template(
            'po_create.html',
            users=users,
        )


# ===================================================================
# 3. 발주서 상세
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>')
@login_required
def po_detail(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items).joinedload(PurchaseOrderItem.bom_item).joinedload(BomItem.bom_header),
            joinedload(PurchaseOrder.vendor),
        ).get(po_id)
        if not po:
            abort(404)

        return render_template(
            'po_detail.html',
            po=po,
            fmt_money=_fmt_money,
            status_choices=PO_STATUS_CHOICES,
        )


# ===================================================================
# 4. 발주서 수정
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>/edit', methods=['POST'])
@login_required
def po_edit(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            abort(404)

        if po.status != '작성중':
            flash('작성중 상태의 발주서만 수정할 수 있습니다.', 'warning')
            return redirect(url_for('purchase_order.po_detail', po_id=po_id))

        po.po_date = datetime.datetime.strptime(
            request.form.get('po_date', ''), '%Y-%m-%d'
        ).date() if request.form.get('po_date') else po.po_date
        po.vendor_id = safe_int(request.form.get('vendor_id'), po.vendor_id)
        po.note = (request.form.get('note') or '').strip()

        # 기존 품목 삭제 후 재등록
        db.query(PurchaseOrderItem).filter_by(po_id=po.id).delete()

        item_names = request.form.getlist('item_name[]')
        item_specs = request.form.getlist('item_spec[]')
        item_qtys = request.form.getlist('quantity[]')
        item_prices = request.form.getlist('unit_price[]')
        item_units = request.form.getlist('unit[]')
        item_notes = request.form.getlist('item_note[]')
        item_ids = request.form.getlist('item_id[]')

        total_amount = 0
        for i in range(len(item_names)):
            name = (item_names[i] if i < len(item_names) else '').strip()
            if not name:
                continue

            spec = (item_specs[i] if i < len(item_specs) else '').strip()
            qty = float(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 0
            price = float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0
            unit = (item_units[i] if i < len(item_units) else '').strip()
            item_note = (item_notes[i] if i < len(item_notes) else '').strip()
            linked_item_id = safe_int(item_ids[i] if i < len(item_ids) else '', 0) or None
            amount = qty * price

            db.add(PurchaseOrderItem(
                po_id=po.id,
                item_id=linked_item_id,
                item_name=name,
                item_spec=spec,
                quantity=qty,
                unit_price=price,
                amount=amount,
                unit=unit,
                note=item_note,
            ))
            total_amount += amount

        po.total_amount = total_amount
        po.tax_amount = round(total_amount * 0.1)
        db.commit()

        flash('발주서가 수정되었습니다.', 'success')
        return redirect(url_for('purchase_order.po_detail', po_id=po_id))


# ===================================================================
# 5. 발주서 삭제
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>/delete', methods=['POST'])
@login_required
def po_delete(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            abort(404)

        # 연결된 입고가 있으면 삭제 불가
        from modules.models import Receiving
        linked_rcv = db.query(Receiving).filter(Receiving.po_id == po_id).first()
        if linked_rcv:
            flash(f'입고({linked_rcv.rcv_no})가 연결되어 삭제할 수 없습니다. 입고를 먼저 삭제해주세요.', 'warning')
            return redirect(url_for('purchase_order.po_detail', po_id=po_id))

        db.delete(po)
        db.commit()
        flash('발주서가 삭제되었습니다.', 'success')
        return redirect(url_for('purchase_order.po_list'))


# ===================================================================
# 6. 발주서 상태 변경
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>/status', methods=['POST'])
@login_required
def po_change_status(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            abort(404)

        new_status = request.form.get('status', '')
        if new_status not in PO_STATUS_CHOICES:
            flash('유효하지 않은 상태입니다.', 'warning')
            return redirect(url_for('purchase_order.po_detail', po_id=po_id))

        po.status = new_status
        db.commit()
        flash(f'상태가 "{new_status}"로 변경되었습니다.', 'success')
        return redirect(url_for('purchase_order.po_detail', po_id=po_id))


# ===================================================================
# 7. PDF 다운로드
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>/pdf')
@login_required
def po_pdf(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            abort(404)

        from modules.services.po_pdf import generate_po_pdf
        pdf_bytes = generate_po_pdf(po, po.vendor, po.items)

        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename="{po.po_no}.pdf"'
        return response


# ===================================================================
# 8. 이메일 발송
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>/send-email', methods=['POST'])
@login_required
def po_send_email(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            abort(404)

        vendor = po.vendor
        if not vendor.email:
            flash('거래처 이메일이 등록되지 않았습니다.', 'warning')
            return redirect(url_for('purchase_order.po_detail', po_id=po_id))

        # PDF 생성
        from modules.services.po_pdf import generate_po_pdf
        pdf_bytes = generate_po_pdf(po, vendor, po.items)

        # 이메일 발송
        from modules.services.email_sender import send_purchase_order_email
        po_date_str = po.po_date.strftime('%y%m%d') if po.po_date else ''
        pdf_filename = f'{po.po_no}.pdf'

        # 제목: (주)매그나텍 첫번째품목명외 N건 발주서 송부의건_YYMMDD
        po_items = po.items
        if po_items:
            first_item_name = po_items[0].item_name or '품목'
            if len(po_items) > 1:
                item_summary = f'{first_item_name}외 {len(po_items) - 1}건'
            else:
                item_summary = first_item_name
        else:
            item_summary = '발주'
        subject = f'(주)매그나텍 {item_summary} 발주서 송부의건_{po_date_str}'

        # 본문
        body_lines = [
            '귀 사의 번창을 기원합니다.',
            '',
            '당사 발주건 관련하여 아래와 같이 발주를 요청하오니 검토하여 주시기 바랍니다.',
            '',
            '',
            '■ 발주내용 요약',
            '',
            f'{"No":<4s} {"품목":<25s} {"규격":<20s} {"수량":>8s} {"단위":<5s}',
            '-' * 65,
        ]
        for idx, item in enumerate(po_items, 1):
            name = (item.item_name or '')[:24]
            spec = (item.item_spec or '')[:19]
            qty = f'{item.quantity:,.0f}' if item.quantity else '0'
            unit = item.unit or ''
            body_lines.append(f'{idx:<4d} {name:<25s} {spec:<20s} {qty:>8s} {unit:<5s}')
        body_lines.extend([
            '',
            '',
            '발주서를 첨부파일로 송부드리오니 업무에 참고바랍니다.',
            '',
            '감사합니다.',
            '',
            '',
            '─' * 40,
            '위 메일 및 첨부자료는 지정된 수신인만을 위한 것이며 관련법령에 의해 보호대상이 되는',
            '기밀사항을 포함할 수 있습니다.',
            '본 메일, 혹은 첨부자료에 포함된 내용을 무단으로 조사, 사용, 복사, 공개 혹은 배포하는',
            '행위는 엄격히 금지되어 있습니다.',
            '이 메일이 잘못 전송된 경우에는 본 메일 및 첨부자료를 복사하거나 공개하지 마시고',
            '발신인에게 알려주시고 메일 및 첨부자료는 즉시 삭제해주시기 바랍니다.',
            '',
        ])

        # 담당자(assigned_to) 또는 로그인 사용자 기준 서명
        sig_user_id = po.assigned_to or session.get('user_id')
        sig_user = db.query(User).get(sig_user_id) if sig_user_id else None

        sig_lines = ['=' * 65]
        title = '(주)매그나텍'
        if sig_user:
            if sig_user.user_group:
                title += f' {sig_user.user_group}'
            title += f' {sig_user.full_name}'
            if sig_user.position:
                title += f' {sig_user.position}'
        sig_lines.append(title)
        if sig_user and sig_user.email:
            sig_lines.append(f'E-mail : {sig_user.email}')
        else:
            sig_lines.append('E-mail : purchase@mgnt.kr')
        if sig_user and sig_user.phone_number:
            sig_lines.append(f'Mobile : {sig_user.phone_number}')
        sig_lines.append(f'Office : {sig_user.office_tel if sig_user and sig_user.office_tel else "061-392-5508"}')
        sig_lines.append(f'Fax    : {sig_user.office_fax if sig_user and sig_user.office_fax else "061-392-5518"}')
        sig_lines.append('주  소 : 전라남도 장성군 동화면 전자농공단지2길 55')
        sig_lines.append('홈페이지 : https://www.magnatech.co.kr')
        sig_lines.append('=' * 65)
        body_lines.extend(sig_lines)

        body = '\n'.join(body_lines)

        result = send_purchase_order_email(
            to_email=vendor.email,
            subject=subject,
            body_text=body,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
        )

        # 이메일 이력 저장
        email_log = EmailHistory(
            sender='purchase@mgnt.kr',
            receiver=vendor.email,
            subject=subject,
            content=body,
            attachment=pdf_filename,
            is_success=result['success'],
            error_message=result['message'] if not result['success'] else None,
            po_id=po.id,
        )
        db.add(email_log)

        if result['success']:
            po.status = '발송완료'
            po.email_sent_at = datetime.datetime.now()
            po.email_to = vendor.email

            # ── 자재관리 연동: 계약 연결된 발주서만 ──
            if po.contract_id:
                _sync_po_to_material_orders(db, po)

            flash(f'이메일 발송 완료: {vendor.email} ({result["message"]})', 'success')
        else:
            flash(f'이메일 발송 실패: {result["message"]}', 'danger')

        db.commit()
        return redirect(url_for('purchase_order.po_detail', po_id=po_id))


# ===================================================================
# 8-0. 자재관리 수동 연동
# ===================================================================
@purchase_order_bp.route('/purchase-order/<int:po_id>/sync-materials', methods=['POST'])
@login_required
def po_sync_materials(po_id):
    with get_db() as db:
        po = db.query(PurchaseOrder).get(po_id)
        if not po:
            abort(404)
        if not po.contract_id:
            flash('계약건이 연결되지 않은 발주서입니다.', 'warning')
            return redirect(url_for('purchase_order.po_detail', po_id=po_id))

        _sync_po_to_material_orders(db, po)
        db.commit()
        flash('자재관리에 연동되었습니다.', 'success')
        return redirect(url_for('purchase_order.po_detail', po_id=po_id))


# ===================================================================
# 8-1. PDF 미리보기 (더미 데이터 - 마이그레이션 전 테스트용)
# ===================================================================
@purchase_order_bp.route('/purchase-order/preview-pdf')
@login_required
def po_preview_pdf():
    """더미 데이터로 발주서 PDF 미리보기"""
    from types import SimpleNamespace
    from modules.services.po_pdf import generate_po_pdf

    dummy_po = SimpleNamespace(
        po_no='PO2026-001',
        po_date=datetime.date.today(),
        note='강진 가로보안등 현장용',
        tax_amount=157_630,
    )
    dummy_vendor = SimpleNamespace(
        name='(주)셀파세미컴',
        tel='02-1234-5678',
        fax='02-1234-5679',
        email='james@selpasemicom.com',
    )
    dummy_items = [
        SimpleNamespace(item_name='HLG-320H-48A', item_spec='LED 드라이버 320W 48V', quantity=96, unit_price=97_600, amount=9_369_600, unit='EA', note=''),
        SimpleNamespace(item_name='CV*2.5SQ*3C', item_spec='', quantity=900, unit_price=1_550, amount=1_395_000, unit='M', note='강진현장'),
        SimpleNamespace(item_name='VCTF 1.5SQ 4C', item_spec='디밍케이블', quantity=300, unit_price=1_100, amount=330_000, unit='M', note=''),
        SimpleNamespace(item_name='KS D 3566 일반구조용탄소강관(BS흑관)', item_spec='Φ216.3 * 4.2T * 6M', quantity=6, unit_price=174_010, amount=1_044_060, unit='본', note='송원스틸'),
        SimpleNamespace(item_name='방수형 누전차단기함', item_spec='', quantity=30, unit_price=16_600, amount=498_000, unit='EA', note=''),
        SimpleNamespace(item_name='와고커넥터(푸쉬콘넥타)', item_spec='413-221', quantity=200, unit_price=600, amount=120_000, unit='EA', note=''),
    ]

    pdf_bytes = generate_po_pdf(dummy_po, dummy_vendor, dummy_items)
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename="preview.pdf"'
    return response


# ===================================================================
# 8-2. 기존 발주이력 상세 (AJAX JSON)
# ===================================================================
@purchase_order_bp.route('/api/po-history/<int:history_id>')
@login_required
def api_po_history_detail(history_id):
    """기존 발주이력(PurchaseOrderHistory) 상세 데이터"""
    import json as _json
    with get_db() as db:
        po = db.query(PurchaseOrderHistory).get(history_id)
        if not po:
            return jsonify({'error': '이력을 찾을 수 없습니다.'}), 404

        items = []
        try:
            items = _json.loads(po.items_json or '[]')
        except Exception:
            pass

        return jsonify({
            'po_nb': po.icube_cls_nb,
            'order_date': po.order_date.strftime('%Y-%m-%d') if po.order_date else '',
            'vendor_name': po.vendor_name or '',
            'remark': po.remark or '',
            'total_amount': float(po.total_amount or 0),
            'items': items,
        })


# ===================================================================
# 9. 거래처 검색 API (AJAX)
# ===================================================================
@purchase_order_bp.route('/api/vendors/search')
@login_required
def api_vendor_search():
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(Vendor).filter(Vendor.is_active.is_(True))
        if q:
            like_q = f"%{q}%"
            query = query.filter(Vendor.name.ilike(like_q))
        vendors = query.order_by(Vendor.name).limit(20).all()
        return jsonify([{
            'id': v.id,
            'name': v.name,
            'email': v.email or '',
            'tel': v.tel or '',
            'note': v.note or '',
        } for v in vendors])


# ===================================================================
# 10. 품목 검색 API (AJAX)
# ===================================================================
@purchase_order_bp.route('/api/items/search')
@login_required
def api_item_search():
    q = (request.args.get('q') or '').strip()
    with get_db() as db:
        query = db.query(Item).filter(Item.is_active == True)
        if q:
            like_q = f"%{q}%"
            query = query.filter(
                (Item.item_name.ilike(like_q)) |
                (Item.icube_item_cd.ilike(like_q)) |
                (Item.item_spec.ilike(like_q))
            )
        items = query.order_by(Item.item_name).limit(20).all()
        return jsonify([{
            'id': i.id,
            'item_cd': i.icube_item_cd or '',
            'item_name': i.item_name,
            'item_spec': i.item_spec or '',
            'unit': i.unit or '',
        } for i in items])


# ===================================================================
# 10-1. 서명 관리 API
# ===================================================================
@purchase_order_bp.route('/api/signature', methods=['GET'])
@login_required
def api_get_signature():
    """현재 사용자 서명 조회"""
    with get_db() as db:
        sig = db.query(EmailSignature).filter_by(user_id=session['user_id']).first()
        if not sig:
            return jsonify({'exists': False})
        return jsonify({
            'exists': True,
            'department': sig.department or '',
            'position': sig.position or '',
            'display_name': sig.display_name or '',
            'email': sig.email or '',
            'mobile': sig.mobile or '',
            'office_tel': sig.office_tel or '',
            'fax': sig.fax or '',
            'is_default': sig.is_default,
        })


@purchase_order_bp.route('/api/signature', methods=['POST'])
@login_required
def api_save_signature():
    """서명 저장/수정"""
    data = request.get_json(silent=True) or {}
    try:
        with get_db() as db:
            sig = db.query(EmailSignature).filter_by(user_id=session['user_id']).first()
            if not sig:
                sig = EmailSignature(user_id=session['user_id'])
                db.add(sig)

            sig.department = (data.get('department') or '').strip() or None
            sig.position = (data.get('position') or '').strip() or None
            sig.display_name = (data.get('display_name') or '').strip() or None
            sig.email = (data.get('email') or '').strip() or None
            sig.mobile = (data.get('mobile') or '').strip() or None
            sig.office_tel = (data.get('office_tel') or '').strip() or None
            sig.fax = (data.get('fax') or '').strip() or None
            sig.is_default = bool(data.get('is_default'))
            db.commit()
            return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)[:100]}), 500


@purchase_order_bp.route('/api/signatures/all')
@login_required
def api_all_signatures():
    """전체 서명 목록 (담당자 선택용)"""
    with get_db() as db:
        sigs = db.query(EmailSignature).all()
        return jsonify([{
            'user_id': s.user_id,
            'display_name': s.display_name or '',
            'department': s.department or '',
            'position': s.position or '',
            'label': f"{s.display_name or ''} {s.position or ''} ({s.department or ''})".strip(),
        } for s in sigs])


# ===================================================================
# 10-2. 계약건 검색 API (발주서 계약 연결용)
# ===================================================================
@purchase_order_bp.route('/api/contracts/search')
@login_required
def api_contract_search():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify([])
    with get_db() as db:
        from sqlalchemy import or_
        from sqlalchemy.orm import joinedload
        contracts = db.query(Contract).join(Project).filter(
            or_(
                Project.temp_name.ilike(f'%{q}%'),
                Contract.contract_name.ilike(f'%{q}%'),
                Project.project_no.ilike(f'%{q}%'),
            )
        ).options(joinedload(Contract.project)).order_by(desc(Contract.id)).limit(15).all()
        return jsonify([{
            'id': c.id,
            'site_name': c.project.temp_name if c.project else '',
            'contract_name': c.contract_name,
            'item_group': c.item_group or '',
            'label': f"{c.project.temp_name if c.project else ''} - {c.contract_name}",
        } for c in contracts])


# ===================================================================
# 11. 거래처 신규등록 API (AJAX)
# ===================================================================
@purchase_order_bp.route('/api/vendors/create', methods=['POST'])
@login_required
def api_vendor_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '거래처명을 입력하세요.'}), 400

    try:
        with get_db() as db:
            vendor = Vendor(
                name=name,
                ceo_name=(data.get('ceo_name') or '').strip() or None,
                business_no=(data.get('business_no') or '').strip() or None,
                tel=(data.get('tel') or '').strip() or None,
                fax=(data.get('fax') or '').strip() or None,
                email=(data.get('email') or '').strip() or None,
                address=(data.get('address') or '').strip() or None,
                note=(data.get('note') or '').strip() or None,
                is_active=True,
            )
            db.add(vendor)
            db.commit()
            return jsonify({
                'id': vendor.id,
                'name': vendor.name,
                'email': vendor.email or '',
                'tel': vendor.tel or '',
            })
    except Exception as e:
        logger.error("거래처 등록 오류: %s", e)
        return jsonify({'error': f'등록 실패: {str(e)[:100]}'}), 500
