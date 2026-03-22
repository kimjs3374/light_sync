"""
가공발주 관리 Blueprint.

- 외주 가공업체 발주 등록/수정/삭제
- DWG 도면 파일 첨부/다운로드
- 품목별 입고 확인 → 생산관리(MaterialOrder) 연동
"""

import datetime
import io
import json
import logging

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, session, send_file,
)
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.storage_adapter import upload_bytes, download_bytes, delete_object, is_storage_enabled
from modules.models import (
    Vendor, Item, Contract, Project, User, MaterialOrder,
    BomItem, BomHeader, EmailHistory,
    Drawing, DrawingVersion,
    ProcessingOrder, ProcessingOrderItem, ProcessingOrderFile,
    FO_STATUS_CHOICES, FO_TYPE_CHOICES,
)
from modules.services.email_sender import send_email_with_attachments
from modules.activity import log_activity

logger = logging.getLogger(__name__)

processing_order_bp = Blueprint('processing_order', __name__)

ALLOWED_EXTENSIONS = {'dwg', 'dxf', 'pdf', 'jpg', 'jpeg', 'png', 'zip'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ===================================================================
# 헬퍼
# ===================================================================
def _generate_fo_no(db):
    """가공발주번호 자동 채번: FO{YYYY}-{NNN}"""
    year = datetime.date.today().year
    prefix = f'FO{year}-'
    last = db.query(ProcessingOrder).filter(
        ProcessingOrder.fo_no.like(f'{prefix}%')
    ).order_by(desc(ProcessingOrder.fo_no)).first()
    if last:
        try:
            return f'{prefix}{int(last.fo_no.replace(prefix, "")) + 1:03d}'
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


def _append_fo_history(fo, text, user_name=''):
    """가공발주 히스토리 로그 추가"""
    logs = json.loads(fo.history_log) if fo.history_log else []
    logs.append({
        'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'user': user_name,
        'text': text,
    })
    fo.history_log = json.dumps(logs, ensure_ascii=False)


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _delivery_badge(delivery_date):
    """납기일 D-day 계산 및 뱃지 클래스 반환"""
    if not delivery_date:
        return '', '', ''
    today = datetime.date.today()
    delta = (delivery_date - today).days
    if delta < 0:
        return f'D+{abs(delta)}', 'bg-danger text-white', '지연'
    elif delta <= 3:
        return f'D-{delta}', 'bg-warning text-dark', ''
    else:
        return delivery_date.strftime('%m/%d'), '', ''


def _register_as_drawing(db, fo, file_record):
    """DWG/DXF 파일을 도면관리에 '발주도면'으로 자동 등록"""
    if file_record.file_type not in ('dwg', 'dxf'):
        return
    if not fo.project_id:
        return

    # 같은 파일명으로 이미 등록된 도면이 있으면 스킵
    existing = db.query(DrawingVersion).filter(
        DrawingVersion.dwg_path == file_record.file_path
    ).first()
    if existing:
        return

    title = f'[가공] {file_record.file_name}'
    drawing = Drawing(
        project_id=fo.project_id,
        title=title,
        drawing_type='발주도면',
        created_by=session.get('full_name', ''),
    )
    db.add(drawing)
    db.flush()

    version = DrawingVersion(
        drawing_id=drawing.id,
        version_no=1,
        dwg_path=file_record.file_path,
        convert_status='UPLOADED',
        created_by=session.get('full_name', ''),
        is_latest=True,
    )
    db.add(version)


def _parse_fo_items(form):
    """폼에서 가공발주 품목 파싱"""
    names = form.getlist('item_name[]')
    specs = form.getlist('item_spec[]')
    qtys = form.getlist('quantity[]')
    prices = form.getlist('unit_price[]')
    units = form.getlist('unit[]')
    del_dates = form.getlist('delivery_date[]')
    proc_notes = form.getlist('processing_note[]')
    item_notes = form.getlist('item_note[]')
    item_ids = form.getlist('item_id[]')

    items = []
    total = 0
    for i, name in enumerate(names):
        if not name.strip():
            continue
        qty = float((qtys[i] or '0').replace(',', '')) if i < len(qtys) else 0
        price = float((prices[i] or '0').replace(',', '')) if i < len(prices) else 0
        amount = qty * price
        total += amount

        dd = None
        if i < len(del_dates) and del_dates[i]:
            try:
                dd = datetime.date.fromisoformat(del_dates[i])
            except ValueError:
                pass

        items.append(ProcessingOrderItem(
            item_id=safe_int(item_ids[i]) or None,
            item_name=name.strip(),
            item_spec=specs[i].strip() if i < len(specs) else '',
            quantity=qty,
            unit_price=price,
            amount=amount,
            unit=units[i].strip() if i < len(units) else 'EA',
            delivery_date=dd,
            processing_note=proc_notes[i].strip() if i < len(proc_notes) else '',
            note=item_notes[i].strip() if i < len(item_notes) else '',
        ))
    return items, total


# ===================================================================
# 목록
# ===================================================================
@processing_order_bp.route('/processing-orders')
@login_required
@menu_required('processing_order')
def fo_list():
    with get_db() as db:
        q = request.args.get('q', '').strip()
        status_filter = request.args.get('status', '')
        type_filter = request.args.get('type', '')
        page = safe_int(request.args.get('page', 1), 1)

        query = db.query(ProcessingOrder).options(
            joinedload(ProcessingOrder.vendor),
            joinedload(ProcessingOrder.project),
            joinedload(ProcessingOrder.contract),
            joinedload(ProcessingOrder.items),
            joinedload(ProcessingOrder.files),
        )

        if q:
            like = f'%{q}%'
            query = query.filter(
                (ProcessingOrder.fo_no.ilike(like)) |
                (ProcessingOrder.vendor.has(Vendor.name.ilike(like)))
            )
        if status_filter:
            query = query.filter(ProcessingOrder.status == status_filter)
        if type_filter:
            query = query.filter(ProcessingOrder.processing_type == type_filter)

        query = query.order_by(desc(ProcessingOrder.fo_date), desc(ProcessingOrder.id))

        total = query.count()
        per_page = 30
        orders = query.offset((page - 1) * per_page).limit(per_page).all()
        pagination = make_pagination(page, per_page, total)

        # 통계
        all_orders = db.query(ProcessingOrder).all()
        stats = {
            'total': len(all_orders),
            'draft': sum(1 for o in all_orders if o.status == '작성중'),
            'ordered': sum(1 for o in all_orders if o.status == '발주완료'),
            'processing': sum(1 for o in all_orders if o.status == '가공중'),
            'done': sum(1 for o in all_orders if o.status == '입고완료'),
        }

        hide_financial = session.get('hide_financial', False)

        return render_template('fo_list.html',
            orders=orders,
            stats=stats,
            filters={'q': q, 'status': status_filter, 'type': type_filter},
            status_choices=FO_STATUS_CHOICES,
            type_choices=FO_TYPE_CHOICES,
            pagination=pagination,
            hide_financial=hide_financial,
            fmt_money=_fmt_money,
            delivery_badge=_delivery_badge,
        )


# ===================================================================
# 등록
# ===================================================================
@processing_order_bp.route('/processing-order/create', methods=['GET', 'POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_create():
    with get_db() as db:
        if request.method == 'POST':
            vendor_id = safe_int(request.form.get('vendor_id'))
            if not vendor_id:
                flash('가공업체를 선택하세요.', 'warning')
                return redirect(url_for('processing_order.fo_create'))

            fo = ProcessingOrder(
                fo_no=_generate_fo_no(db),
                fo_date=datetime.date.fromisoformat(request.form.get('fo_date', datetime.date.today().isoformat())),
                vendor_id=vendor_id,
                processing_type=request.form.get('processing_type', '외주가공'),
                project_id=safe_int(request.form.get('project_id')) or None,
                contract_id=safe_int(request.form.get('contract_id')) or None,
                assigned_to=safe_int(request.form.get('assigned_to')) or None,
                note=request.form.get('note', '').strip() or None,
                created_by=session.get('user_id'),
            )

            items, total = _parse_fo_items(request.form)
            for item in items:
                fo.items.append(item)

            fo.total_amount = total
            fo.tax_amount = round(total * 0.1)
            _append_fo_history(fo, '가공발주 등록', session.get('full_name', ''))

            db.add(fo)
            db.flush()

            # 파일 업로드 (multipart/form-data)
            file_count = 0
            for f in request.files.getlist('files'):
                if not f or not f.filename:
                    continue
                if not _allowed_file(f.filename):
                    continue
                content = f.read()
                if not content or len(content) > MAX_FILE_SIZE:
                    continue
                ext = f.filename.rsplit('.', 1)[1].lower()
                safe_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
                obj_path = f'storage/processing-orders/{fo.fo_no}/{safe_name}'
                if is_storage_enabled():
                    ok, msg = upload_bytes(obj_path, content, f.content_type or 'application/octet-stream')
                    if not ok:
                        logger.error(f'FO 파일 업로드 실패: {f.filename} - {msg}')
                        flash(f'파일 업로드 실패: {f.filename} ({msg})', 'warning')
                        continue
                else:
                    flash('Supabase Storage 미설정 — 파일 메타만 저장됩니다.', 'warning')
                file_rec = ProcessingOrderFile(
                    fo_id=fo.id, file_name=f.filename, file_path=obj_path,
                    file_size=len(content), file_type=ext,
                    uploaded_by=session.get('user_id'),
                )
                db.add(file_rec)
                db.flush()
                _register_as_drawing(db, fo, file_rec)
                file_count += 1

            if file_count:
                _append_fo_history(fo, f'파일 {file_count}건 첨부', session.get('full_name', ''))

            log_activity(db, '가공발주', 'create', f'{fo.fo_no} 가공발주 등록 ({fo.vendor.name})',
                         ref_type='ProcessingOrder', ref_id=fo.id, ref_label=fo.fo_no, project_id=fo.project_id)
            db.commit()
            flash(f'{fo.fo_no} 가공발주가 등록되었습니다.', 'success')
            return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))

        users = db.query(User).filter_by(is_active=True).order_by(User.full_name).all()
        hide_financial = session.get('hide_financial', False)

        return render_template('fo_create.html',
            users=users,
            type_choices=FO_TYPE_CHOICES,
            hide_financial=hide_financial,
        )


# ===================================================================
# 상세
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>')
@login_required
@menu_required('processing_order')
def fo_detail(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(
            joinedload(ProcessingOrder.vendor),
            joinedload(ProcessingOrder.project),
            joinedload(ProcessingOrder.contract),
            joinedload(ProcessingOrder.items).joinedload(ProcessingOrderItem.bom_item),
            joinedload(ProcessingOrder.items).joinedload(ProcessingOrderItem.material_order),
            joinedload(ProcessingOrder.files),
            joinedload(ProcessingOrder.assignee),
        ).get(fo_id)
        if not fo:
            abort(404)

        hide_financial = session.get('hide_financial', False)
        history = json.loads(fo.history_log) if fo.history_log else []

        return render_template('fo_detail.html',
            fo=fo,
            status_choices=FO_STATUS_CHOICES,
            type_choices=FO_TYPE_CHOICES,
            hide_financial=hide_financial,
            fmt_money=_fmt_money,
            delivery_badge=_delivery_badge,
            history=history,
        )


# ===================================================================
# 수정
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/edit', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_edit(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).get(fo_id)
        if not fo:
            abort(404)

        fo.fo_date = datetime.date.fromisoformat(request.form.get('fo_date', fo.fo_date.isoformat()))
        fo.processing_type = request.form.get('processing_type', fo.processing_type)
        fo.note = request.form.get('note', '').strip() or None
        fo.contract_id = safe_int(request.form.get('contract_id')) or fo.contract_id
        fo.updated_at = datetime.datetime.now()

        # 기존 품목 삭제 후 재생성
        for old_item in fo.items:
            db.delete(old_item)
        db.flush()

        items, total = _parse_fo_items(request.form)
        for item in items:
            item.fo_id = fo.id
            db.add(item)

        fo.total_amount = total
        fo.tax_amount = round(total * 0.1)

        _append_fo_history(fo, '가공발주 수정', session.get('full_name', ''))
        db.commit()
        flash('가공발주가 수정되었습니다.', 'success')
        return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))


# ===================================================================
# 삭제
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/delete', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_delete(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).get(fo_id)
        if not fo:
            abort(404)
        fo_no = fo.fo_no
        for f in fo.files:
            delete_object(f.file_path)
        db.delete(fo)
        db.commit()
        flash(f'{fo_no} 가공발주가 삭제되었습니다.', 'success')
        return redirect(url_for('processing_order.fo_list'))


# ===================================================================
# 상태 변경
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/status', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_change_status(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).get(fo_id)
        if not fo:
            abort(404)

        new_status = request.form.get('status', '')
        if new_status not in FO_STATUS_CHOICES:
            flash('잘못된 상태입니다.', 'danger')
            return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))

        old_status = fo.status
        fo.status = new_status
        fo.updated_at = datetime.datetime.now()
        _append_fo_history(fo, f'상태변경: {old_status} → {new_status}', session.get('full_name', ''))
        log_activity(db, '가공발주', 'status_change', f'{fo.fo_no} {old_status}→{new_status}',
                     ref_type='ProcessingOrder', ref_id=fo.id, ref_label=fo.fo_no, project_id=fo.project_id)
        db.commit()
        flash(f'상태가 {new_status}(으)로 변경되었습니다.', 'success')
        return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))


# ===================================================================
# 파일 업로드
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/upload', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_upload_file(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).get(fo_id)
        if not fo:
            return jsonify({'error': '가공발주를 찾을 수 없습니다.'}), 404

        if not is_storage_enabled():
            return jsonify({'error': 'Supabase Storage 설정이 없습니다.'}), 500

        uploaded = request.files.getlist('files')
        results = []

        for f in uploaded:
            if not f or not f.filename:
                continue
            if not _allowed_file(f.filename):
                results.append({'name': f.filename, 'error': '허용되지 않는 파일 형식'})
                continue

            content = f.read()
            if len(content) > MAX_FILE_SIZE:
                results.append({'name': f.filename, 'error': '파일 크기 초과 (50MB 제한)'})
                continue

            ext = f.filename.rsplit('.', 1)[1].lower()
            safe_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
            object_path = f'storage/processing-orders/{fo.fo_no}/{safe_name}'

            ok, msg = upload_bytes(object_path, content, f.content_type or 'application/octet-stream')
            if not ok:
                results.append({'name': f.filename, 'error': msg})
                continue

            file_record = ProcessingOrderFile(
                fo_id=fo.id,
                file_name=f.filename,
                file_path=object_path,
                file_size=len(content),
                file_type=ext,
                uploaded_by=session.get('user_id'),
            )
            db.add(file_record)
            db.flush()
            _register_as_drawing(db, fo, file_record)
            results.append({'name': f.filename, 'ok': True, 'id': file_record.id})

        _append_fo_history(fo, f'파일 {len([r for r in results if r.get("ok")])}건 업로드', session.get('full_name', ''))
        db.commit()

        for r in results:
            if r.get('ok'):
                rec = db.query(ProcessingOrderFile).filter_by(fo_id=fo.id, file_name=r['name']).first()
                if rec:
                    r['id'] = rec.id

        return jsonify({'results': results})


# ===================================================================
# 파일 삭제
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/file/<int:fid>/delete', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_delete_file(fo_id, fid):
    with get_db() as db:
        rec = db.query(ProcessingOrderFile).filter_by(id=fid, fo_id=fo_id).first()
        if not rec:
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404

        # 도면관리에 연결된 레코드도 삭제
        linked_ver = db.query(DrawingVersion).filter_by(dwg_path=rec.file_path).first()
        if linked_ver:
            drawing = db.query(Drawing).get(linked_ver.drawing_id)
            db.delete(linked_ver)
            if drawing:
                remaining = db.query(DrawingVersion).filter_by(drawing_id=drawing.id).filter(DrawingVersion.id != linked_ver.id).count()
                if remaining == 0:
                    db.delete(drawing)

        delete_object(rec.file_path)
        fname = rec.file_name
        db.delete(rec)

        fo = db.query(ProcessingOrder).get(fo_id)
        if fo:
            _append_fo_history(fo, f'파일 삭제: {fname}', session.get('full_name', ''))

        db.commit()
        return jsonify({'ok': True})


# ===================================================================
# 파일 다운로드
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/file/<int:fid>/download')
@login_required
@menu_required('processing_order')
def fo_download_file(fo_id, fid):
    with get_db() as db:
        rec = db.query(ProcessingOrderFile).filter_by(id=fid, fo_id=fo_id).first()
        if not rec:
            abort(404)

        content = download_bytes(rec.file_path)
        if content is None:
            abort(404)

        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=rec.file_name,
        )


# ===================================================================
# 품목 입고 확인
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/confirm-item/<int:item_id>', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_confirm_item(fo_id, item_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(joinedload(ProcessingOrder.items)).get(fo_id)
        if not fo:
            return jsonify({'error': '가공발주를 찾을 수 없습니다.'}), 404

        item = next((i for i in fo.items if i.id == item_id), None)
        if not item:
            return jsonify({'error': '품목을 찾을 수 없습니다.'}), 404

        now = datetime.datetime.now()

        if item.in_confirmed:
            item.in_confirmed = False
            item.in_confirmed_at = None
            _append_fo_history(fo, f'입고취소: {item.item_name}', session.get('full_name', ''))
            if item.material_order_id:
                mat = db.query(MaterialOrder).get(item.material_order_id)
                if mat:
                    mat.outsourcing_status = '가공중'
                    mat.in_confirmed = False
                    mat.in_confirmed_at = None
        else:
            item.in_confirmed = True
            item.in_confirmed_at = now
            _append_fo_history(fo, f'입고확인: {item.item_name}', session.get('full_name', ''))
            log_activity(db, '가공발주', 'confirm', f'{fo.fo_no} 입고확인: {item.item_name}',
                         ref_type='ProcessingOrder', ref_id=fo.id, ref_label=fo.fo_no, project_id=fo.project_id)
            if item.material_order_id:
                mat = db.query(MaterialOrder).get(item.material_order_id)
                if mat:
                    mat.outsourcing_status = '본사입고완료'
                    mat.in_confirmed = True
                    mat.in_confirmed_at = now

        all_confirmed = all(i.in_confirmed for i in fo.items) if fo.items else False
        if all_confirmed and fo.status != '입고완료':
            fo.status = '입고완료'
            _append_fo_history(fo, '전체 입고 완료 → 상태변경', session.get('full_name', ''))

        fo.updated_at = now
        db.commit()

        return jsonify({
            'ok': True,
            'confirmed': item.in_confirmed,
            'confirmed_at': item.in_confirmed_at.strftime('%m/%d %H:%M') if item.in_confirmed_at else '',
            'fo_status': fo.status,
        })


# ===================================================================
# 생산 연동 (MaterialOrder 연결)
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/sync-production', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_sync_production(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(joinedload(ProcessingOrder.items)).get(fo_id)
        if not fo:
            abort(404)

        if not fo.contract_id:
            flash('계약이 연결되지 않은 가공발주는 생산관리 연동이 불가합니다.', 'warning')
            return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))

        linked = 0
        for item in fo.items:
            if item.material_order_id:
                continue
            mat = db.query(MaterialOrder).filter_by(
                contract_id=fo.contract_id,
                is_outsourcing=True,
            ).filter(
                MaterialOrder.material_name.ilike(f'%{item.item_name}%')
            ).first()

            if mat:
                item.material_order_id = mat.id
                mat.outsourcing_status = fo.status if fo.status in ('가공중', '발주완료') else '가공중'
                mat.order_date = fo.fo_date
                linked += 1

        if linked:
            _append_fo_history(fo, f'생산관리 연동: {linked}건', session.get('full_name', ''))
            db.commit()
            flash(f'{linked}건 생산관리에 연동되었습니다.', 'success')
        else:
            flash('연동 가능한 자재가 없습니다.', 'info')

        return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))


# ===================================================================
# 이메일 미리보기 (AJAX → 모달에서 수정 가능)
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/email-preview')
@login_required
@menu_required('processing_order')
def fo_email_preview(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(
            joinedload(ProcessingOrder.vendor),
            joinedload(ProcessingOrder.items),
            joinedload(ProcessingOrder.files),
            joinedload(ProcessingOrder.assignee),
        ).get(fo_id)
        if not fo:
            return jsonify({'error': 'not found'}), 404

        vendor = fo.vendor
        fo_date_str = fo.fo_date.strftime('%y%m%d') if fo.fo_date else ''

        if fo.items:
            first = fo.items[0].item_name or '품목'
            item_summary = f'{first}외 {len(fo.items) - 1}건' if len(fo.items) > 1 else first
        else:
            item_summary = '가공발주'
        subject = f'(주)매그나텍 {item_summary} 가공발주 송부의건_{fo_date_str}'

        type_label = fo.processing_type or '외주가공'
        body_lines = [
            '귀 사의 번창을 기원합니다.',
            '',
            f'당사 가공발주건({type_label}) 관련하여 아래와 같이 발주를 요청하오니 검토하여 주시기 바랍니다.',
            '', '',
            '■ 가공발주 내용', '',
        ]
        for idx, item in enumerate(fo.items, 1):
            line = f'{idx}. {item.item_name or ""}'
            if item.item_spec:
                line += f' ({item.item_spec})'
            line += f'  {item.quantity:,.0f}{item.unit or ""}' if item.quantity else ''
            body_lines.append(line)
        body_lines.extend(['', '', '첨부된 도면/파일을 참고하시어 업무에 활용 바랍니다.', '', '감사합니다.'])

        sig_user_id = fo.assigned_to or session.get('user_id')
        sig_user = db.query(User).get(sig_user_id) if sig_user_id else None
        sig_lines = ['', '─' * 40]
        title = '(주)매그나텍'
        if sig_user:
            if sig_user.user_group:
                title += f' {sig_user.user_group}'
            title += f' {sig_user.full_name}'
            if sig_user.position:
                title += f' {sig_user.position}'
        sig_lines.append(title)
        if sig_user and sig_user.email:
            sig_lines.append(f'E-mail: {sig_user.email}')
        if sig_user and getattr(sig_user, 'phone_number', None):
            sig_lines.append(f'Mobile: {sig_user.phone_number}')
        sig_lines.append(f'Office: {getattr(sig_user, "office_tel", None) or "061-392-5508"}')
        body_lines.extend(sig_lines)

        return jsonify({
            'to': vendor.email if vendor else '',
            'vendor_name': vendor.name if vendor else '',
            'subject': subject,
            'body': '\n'.join(body_lines),
            'files': [f.file_name for f in fo.files],
        })


# ===================================================================
# 이메일 발송 (모달에서 수정된 제목/본문으로 발송)
# ===================================================================
@processing_order_bp.route('/processing-order/<int:fo_id>/send-email', methods=['POST'])
@login_required
@menu_required('processing_order', 'w')
def fo_send_email(fo_id):
    with get_db() as db:
        fo = db.query(ProcessingOrder).options(
            joinedload(ProcessingOrder.vendor),
            joinedload(ProcessingOrder.files),
            joinedload(ProcessingOrder.assignee),
        ).get(fo_id)
        if not fo:
            abort(404)

        vendor = fo.vendor
        to_email = request.form.get('email_to', vendor.email if vendor else '').strip()
        subject = request.form.get('email_subject', '').strip()
        body = request.form.get('email_body', '').strip()

        # 발신자: 담당자 이메일 (없으면 로그인 사용자, 최종 fallback purchase@mgnt.kr)
        sig_user_id = fo.assigned_to or session.get('user_id')
        sig_user = db.query(User).get(sig_user_id) if sig_user_id else None
        from_email = (sig_user.email if sig_user and sig_user.email else None) or 'purchase@mgnt.kr'

        if not to_email or not subject or not body:
            flash('수신자, 제목, 본문을 모두 입력해주세요.', 'warning')
            return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))

        attachments = []
        for f in fo.files:
            content = download_bytes(f.file_path)
            if content:
                attachments.append((f.file_name, content))

        result = send_email_with_attachments(
            to_email=to_email, subject=subject, body_text=body,
            attachments=attachments, from_email=from_email,
        )

        db.add(EmailHistory(
            sender=from_email, receiver=to_email, subject=subject, content=body,
            attachment=', '.join(f.file_name for f in fo.files),
            is_success=result['success'],
            error_message=result['message'] if not result['success'] else None,
        ))

        if result['success']:
            fo.status = '발주완료'
            fo.updated_at = datetime.datetime.now()
            _append_fo_history(fo, f'이메일 발송: {to_email} (첨부 {len(attachments)}건)', session.get('full_name', ''))
            log_activity(db, '가공발주', 'email', f'{fo.fo_no} 이메일 발송 → {to_email}',
                         ref_type='ProcessingOrder', ref_id=fo.id, ref_label=fo.fo_no, project_id=fo.project_id)
            flash(f'이메일 발송 완료: {to_email} ({result["message"]})', 'success')
        else:
            _append_fo_history(fo, f'이메일 발송 실패: {result["message"]}', session.get('full_name', ''))
            flash(f'이메일 발송 실패: {result["message"]}', 'danger')

        db.commit()
        return redirect(url_for('processing_order.fo_detail', fo_id=fo.id))
