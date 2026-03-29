"""서류관리 라우트 — 착수계/납품계 PDF 생성 허브."""

import datetime
import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify
from modules.auth_decorators import login_required, menu_required
from sqlalchemy import func, text
from sqlalchemy.orm import joinedload

from modules.db_context import get_db
from sqlalchemy import and_, or_, not_
from modules.models import (
    G2bProcurement, Project, Contract, User,
    DocumentPackage, DocumentAttachment, DOC_ATTACH_TYPES, REUSABLE_ATTACH_TYPES,
    determine_org_type, generate_doc_number,
)
from modules.contract_filters import DONE_STATUSES
from modules.activity import log_activity
from modules.storage_adapter import upload_bytes, download_bytes, is_storage_enabled

document_bp = Blueprint('document', __name__)

# 공통 서류 Supabase 경로 (영문 키)
COMMON_DOCS = {
    'biz_registration': {'label': '사업자등록증', 'path': 'documents/common/biz_registration.pdf'},
    'factory_cert': {'label': '공장등록증명서', 'path': 'documents/common/factory_cert.pdf'},
    'direct_production_light': {'label': '직접생산확인증명서 (등기구)', 'path': 'documents/common/direct_production_light.pdf'},
    'direct_production_pole': {'label': '직접생산확인증명서 (등주)', 'path': 'documents/common/direct_production_pole.pdf'},
    'direct_production_tower': {'label': '직접생산확인증명서 (조명타워)', 'path': 'documents/common/direct_production_tower.pdf'},
}

DRAWINGS_PREFIX = 'documents/drawings/'


def _fmt_money(val):
    """금액 포맷 (1,234,567)."""
    if val is None:
        return '-'
    return f"{int(val):,}"


@document_bp.route('/documents')
@login_required
@menu_required('documents')
def document_list():
    """서류관리 목록 — 납품요구번호별 그룹핑."""
    with get_db() as db:
        q = request.args.get('q', '').strip()

        # 활성 계약(완료/예외 제외)이 있는 건만 표시
        active_req_nos_subq = db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None),
            Contract.payment_status.notin_(DONE_STATUSES),
            Contract.is_excluded.isnot(True),
        ).subquery()

        query = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.max(G2bProcurement.cntrct_dlvr_req_nm).label('business_name'),
            func.max(G2bProcurement.dminstt_nm).label('demand_org'),
            func.sum(G2bProcurement.prdct_amt).label('supply_amount'),
            func.max(G2bProcurement.dlvr_tmlmt_date).label('delivery_due'),
            func.max(G2bProcurement.cntrct_dlvr_req_date).label('req_date'),
            func.count(G2bProcurement.id).label('item_count'),
        ).filter(
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y',
            G2bProcurement.cntrct_dlvr_req_no.in_(active_req_nos_subq),
        ).group_by(
            G2bProcurement.cntrct_dlvr_req_no
        )

        if q:
            query = query.filter(
                G2bProcurement.cntrct_dlvr_req_nm.ilike(f'%{q}%') |
                G2bProcurement.cntrct_dlvr_req_no.ilike(f'%{q}%') |
                G2bProcurement.dminstt_nm.ilike(f'%{q}%')
            )

        query = query.order_by(func.max(G2bProcurement.cntrct_dlvr_req_date).desc())
        groups = query.all()

        req_nos = [g.cntrct_dlvr_req_no for g in groups]
        packages = {}
        if req_nos:
            pkgs = db.query(DocumentPackage).filter(
                DocumentPackage.procurement_req_no.in_(req_nos)
            ).all()
            packages = {p.procurement_req_no: p for p in pkgs}

        items = []
        for g in groups:
            pkg = packages.get(g.cntrct_dlvr_req_no)
            if pkg and pkg.delivery_generated:
                status = '완료'
                status_color = '#dcfce7'
                status_text_color = '#166534'
            elif pkg and pkg.commencement_generated:
                status = '납품계 생성가능'
                status_color = '#dbeafe'
                status_text_color = '#1e40af'
            elif pkg and pkg.req_pdf_path:
                status = '착수계 생성가능'
                status_color = '#fef3c7'
                status_text_color = '#92400e'
            else:
                status = '계약서 미등록'
                status_color = '#f1f5f9'
                status_text_color = '#64748b'

            items.append({
                'req_no': g.cntrct_dlvr_req_no,
                'business_name': g.business_name or '-',
                'demand_org': g.demand_org or '-',
                'supply_amount': g.supply_amount or 0,
                'delivery_due': g.delivery_due,
                'req_date': g.req_date,
                'item_count': g.item_count,
                'status': status,
                'status_color': status_color,
                'status_text_color': status_text_color,
            })

        stats = {
            'total': len(items),
            'no_contract': sum(1 for i in items if i['status'] == '계약서 미등록'),
            'commencement_ready': sum(1 for i in items if i['status'] == '착수계 생성가능'),
            'delivery_ready': sum(1 for i in items if i['status'] == '납품계 생성가능'),
            'done': sum(1 for i in items if i['status'] == '완료'),
        }

        # 공통 서류 등록 상태 — 모달 열 때만 확인 (AJAX)
        common_docs_status = {k: {'label': v['label'], 'exists': None} for k, v in COMMON_DOCS.items()}

        return render_template('document_list.html',
                               items=items, stats=stats, q=q, fmt_money=_fmt_money,
                               common_docs_status=common_docs_status,
                               storage_enabled=is_storage_enabled())


@document_bp.route('/documents/common-status')
@login_required
def common_docs_status_api():
    """공통 서류 등록 상태 확인 (AJAX)."""
    result = {}
    for key, info in COMMON_DOCS.items():
        doc_bytes = download_bytes(info['path'])
        result[key] = {
            'label': info['label'],
            'exists': doc_bytes is not None and len(doc_bytes) > 0,
        }
    return jsonify(result)


@document_bp.route('/documents/common-upload', methods=['POST'])
@login_required
@menu_required('documents')
def upload_common_doc():
    """공통 서류 업로드 (Supabase)."""
    doc_type = request.form.get('doc_type')
    file = request.files.get('file')
    if not doc_type or doc_type not in COMMON_DOCS:
        flash('잘못된 서류 유형입니다.', 'warning')
        return redirect(url_for('document.document_list'))
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return redirect(url_for('document.document_list'))

    storage_path = COMMON_DOCS[doc_type]['path']
    ok, msg = upload_bytes(storage_path, file.read(), content_type='application/pdf')
    if ok:
        flash(f'{COMMON_DOCS[doc_type]["label"]} 업로드 완료', 'success')
    else:
        flash(f'업로드 실패: {msg}', 'danger')
    return redirect(url_for('document.document_list'))


@document_bp.route('/documents/drawing-upload', methods=['POST'])
@login_required
@menu_required('documents')
def upload_drawing():
    """제작도면 업로드 (모델별, Supabase)."""
    model_code = request.form.get('model_code', '').strip()
    file = request.files.get('file')
    if not model_code:
        flash('모델코드를 입력해주세요.', 'warning')
        return redirect(url_for('document.document_list'))
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return redirect(url_for('document.document_list'))

    storage_path = DRAWINGS_PREFIX + model_code + '.pdf'
    ok, msg = upload_bytes(storage_path, file.read(), content_type='application/pdf')
    if ok:
        flash(f'{model_code} 제작도면 업로드 완료', 'success')
    else:
        flash(f'업로드 실패: {msg}', 'danger')
    return redirect(url_for('document.document_list'))


@document_bp.route('/documents/<req_no>', methods=['GET', 'POST'])
@login_required
@menu_required('documents')
def document_detail(req_no):
    """서류관리 상세 — 서류 허브."""
    with get_db() as db:
        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        if not procurements:
            flash('해당 납품요구번호의 조달내역이 없습니다.', 'warning')
            return redirect(url_for('document.document_list'))

        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()

        if not package:
            first = procurements[0]
            package = DocumentPackage(
                procurement_req_no=req_no,
                business_name=first.cntrct_dlvr_req_nm,
                demand_org=first.dminstt_nm,
                demand_org_no=first.dminstt_cd,
                org_type=determine_org_type(first.dminstt_nm),
                created_by=session.get('username'),
            )
            if first.cntrct_dlvr_req_no:
                contract = db.query(Contract).filter(
                    Contract.g2b_contract_no == first.cntrct_dlvr_req_no
                ).first()
                if contract:
                    package.contract_id = contract.id
                    package.project_id = contract.project_id
            db.add(package)
            db.commit()

        if request.method == 'POST':
            action = request.form.get('action', '')
            _handle_document_action(db, package, procurements, action)
            return redirect(url_for('document.document_detail', req_no=req_no))

        attachments = db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).order_by(DocumentAttachment.sort_order).all()

        agents = db.query(User).filter(User.is_approved == True).order_by(User.full_name).all()

        total_supply = sum(p.prdct_amt or 0 for p in procurements)

        return render_template('document_detail.html',
                               package=package,
                               procurements=procurements,
                               attachments=attachments,
                               agents=agents,
                               total_supply=total_supply,
                               fmt_money=_fmt_money,
                               DOC_ATTACH_TYPES=DOC_ATTACH_TYPES)


@document_bp.route('/documents/<req_no>/commencement-pdf')
@login_required
@menu_required('documents')
def download_commencement_pdf(req_no):
    """착수계 PDF 다운로드."""
    from flask import send_file
    from modules.services.commencement_pdf import generate_commencement_pdf

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        agent_user = None
        if package.commencement_agent_id:
            agent_user = db.query(User).get(package.commencement_agent_id)

        # 첨부파일 목록
        att_list = db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).order_by(DocumentAttachment.sort_order).all()

        pdf_buf = generate_commencement_pdf(
            package, procurements, agent_user=agent_user,
            attachments=att_list
        )

        if not package.commencement_generated:
            package.commencement_generated = True
            db.commit()

        filename = f"착수계_{package.business_name or req_no}.pdf"
        return send_file(pdf_buf, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)


@document_bp.route('/documents/<req_no>/delivery-pdf')
@login_required
@menu_required('documents')
def download_delivery_pdf(req_no):
    """납품서류 PDF 다운로드."""
    from flask import send_file
    from modules.services.delivery_doc_pdf import generate_delivery_doc_pdf

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        stamp_path = None
        official_stamp_path = None
        for att in db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).all():
            if att.file_type == 'stamp_corporate':
                stamp_path = att.storage_path
            elif att.file_type == 'stamp_official':
                official_stamp_path = att.storage_path

        pdf_buf = generate_delivery_doc_pdf(
            package, procurements,
            stamp_path=stamp_path, official_stamp_path=official_stamp_path
        )

        if not package.delivery_generated:
            package.delivery_generated = True
            db.commit()

        filename = f"납품계_{package.business_name or req_no}.pdf"
        return send_file(pdf_buf, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)


def _handle_document_action(db, package, procurements, action):
    """서류관리 POST 액션 처리."""
    if action == 'upload_contract_pdf':
        _handle_upload_contract_pdf(db, package, procurements)
    elif action == 'save_commencement':
        _handle_save_commencement(db, package)
    elif action == 'save_delivery':
        _handle_save_delivery(db, package)
    elif action == 'upload_attachment':
        _handle_upload_attachment(db, package)
    elif action == 'delete_attachment':
        att_id = request.form.get('attachment_id')
        if att_id:
            att = db.query(DocumentAttachment).get(int(att_id))
            if att and att.package_id == package.id:
                db.delete(att)
                db.commit()
                flash('첨부파일이 삭제되었습니다.', 'success')


def _handle_upload_contract_pdf(db, package, procurements):
    """납품요구서 PDF 업로드 + 자동 파싱."""
    from modules.services.contract_pdf_parser import parse_contract_pdf, update_procurement_from_pdf

    file = request.files.get('contract_pdf')
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return

    file_bytes = file.read()

    upload_dir = os.path.join('static', 'uploads', 'documents')
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{package.procurement_req_no}_{file.filename}"
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, 'wb') as f:
        f.write(file_bytes)

    package.req_pdf_path = filepath

    try:
        parsed = parse_contract_pdf(file_bytes)

        package.contract_no = parsed.get('contract_no')
        package.contract_date = parsed.get('contract_date')
        package.fee = parsed.get('fee')
        package.total_amount = parsed.get('total_amount')
        package.supply_amount = parsed.get('supply_amount')
        package.warranty_period = parsed.get('warranty_period')
        package.inspection_org = parsed.get('inspection_org')
        package.acceptance_org = parsed.get('acceptance_org')
        package.org_type = determine_org_type(package.demand_org)

        update_procurement_from_pdf(db, parsed)

        fee_str = f"{parsed['fee']:,}" if parsed.get('fee') else '-'
        flash(f'납품요구서 파싱 완료 — 계약번호: {parsed.get("contract_no")}, 수수료: {fee_str}원', 'success')
    except Exception as e:
        flash(f'PDF 파싱 중 오류: {e}', 'danger')

    db.commit()


def _handle_save_commencement(db, package):
    """착수계 정보 저장."""
    package.commencement_date = request.form.get('commencement_date') or None
    agent_id = request.form.get('agent_id')
    package.commencement_agent_id = int(agent_id) if agent_id else None

    if not package.commencement_doc_no:
        doc_date = None
        if package.commencement_date:
            try:
                doc_date = datetime.date.fromisoformat(package.commencement_date) if isinstance(package.commencement_date, str) else package.commencement_date
            except (ValueError, TypeError):
                pass
        package.commencement_doc_no = generate_doc_number(db, doc_date)

    db.commit()
    flash('착수계 정보가 저장되었습니다.', 'success')


def _handle_save_delivery(db, package):
    """납품계 정보 저장."""
    package.delivery_date = request.form.get('delivery_date') or None

    if not package.delivery_doc_no:
        doc_date = None
        if package.delivery_date:
            try:
                doc_date = datetime.date.fromisoformat(package.delivery_date) if isinstance(package.delivery_date, str) else package.delivery_date
            except (ValueError, TypeError):
                pass
        package.delivery_doc_no = generate_doc_number(db, doc_date)

    db.commit()
    flash('납품계 정보가 저장되었습니다.', 'success')


def _handle_upload_attachment(db, package):
    """첨부파일 업로드."""
    file = request.files.get('attachment_file')
    file_type = request.form.get('file_type', 'other')
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return

    upload_dir = os.path.join('static', 'uploads', 'documents', 'attachments')
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{package.id}_{file_type}_{file.filename}"
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    att = DocumentAttachment(
        package_id=package.id,
        file_type=file_type,
        file_name=file.filename,
        storage_path=filepath,
        sort_order=len(package.attachments) + 1,
    )
    db.add(att)
    db.commit()
    flash(f'{DOC_ATTACH_TYPES.get(file_type, file_type)} 업로드 완료', 'success')
