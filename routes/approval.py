"""전자결재 라우트 (PC)

탭: 결재대기(받은결재) / 올린문서 / 참조문서 / 완료함
순차 결재 + 직급/부서 기반 기본 결재선(수정 가능) + 참조/수신.
"""
import datetime
import os

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, jsonify, Response, abort)
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_

from modules.auth_decorators import menu_required, admin_required
from modules.db_context import get_db
from modules.activity import log_activity
from modules.storage_adapter import upload_bytes, download_bytes, delete_object
from modules.models import (
    ApprovalDocument, ApprovalFormTemplate, ApprovalStep,
    ApprovalReference, ApprovalAttachment, ApprovalComment, User,
)
from modules.services import approval_service as svc

approval_bp = Blueprint('approval', __name__, url_prefix='/approval')

ALLOWED_EXT = {'pdf', 'jpg', 'jpeg', 'png', 'webp', 'xlsx', 'xls', 'docx', 'doc', 'hwp', 'hwpx', 'zip'}
MAX_SIZE = 20 * 1024 * 1024  # 20MB


def _me():
    return session.get('user_id')


def _safe_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _leave_balance(db, user):
    """휴가 양식용 본인 연차 요약 (잔여 등). 실패 시 None."""
    try:
        import datetime as _dt
        from modules.services import hr_service
        s = hr_service.leave_summary(db, user)
        ys, ye = s.get('year_start'), s.get('year_end')
        period_start = ys.strftime('%Y-%m-%d') if ys else None
        # year_end는 exclusive(마지막 사용일 다음 날) → 하루 빼서 표기
        period_end = (ye - _dt.timedelta(days=1)).strftime('%Y-%m-%d') if ye else None
        return {'granted': s['granted'], 'used': s['used'],
                'adjust': s['adjust'], 'remaining': s['remaining'],
                'period_start': period_start, 'period_end': period_end}
    except Exception:
        return None


def _holiday_list():
    """올해~내년 법정공휴일 ['YYYY-MM-DD', ...]. 실패 시 빈 리스트."""
    try:
        from modules.services import holiday_service
        y = datetime.date.today().year
        return holiday_service.holiday_list([y, y + 1])
    except Exception:
        return []


def _can_view(doc):
    """기안자/결재자/참조자/admin만 열람 가능"""
    uid = _me()
    if session.get('role') == 'admin':
        return True
    if doc.drafter_id == uid:
        return True
    if any(s.approver_id == uid for s in doc.steps):
        return True
    if any(r.user_id == uid for r in doc.references):
        return True
    return False


# ────────────────────────────────────────────────────────
# 목록
# ────────────────────────────────────────────────────────

@approval_bp.route('')
@menu_required('approval')
def approval_list():
    tab = request.args.get('tab', 'all')
    uid = _me()
    with get_db() as db:
        svc.seed_form_templates(db)
        db.commit()

        base = db.query(ApprovalDocument)
        if tab == 'all':
            # 권한 내 모든 문서: 내가 기안 OR 결재선 포함 OR 참조/수신
            docs = (base.filter(or_(
                        ApprovalDocument.drafter_id == uid,
                        ApprovalDocument.steps.any(ApprovalStep.approver_id == uid),
                        ApprovalDocument.references.any(ApprovalReference.user_id == uid)))
                    .order_by(ApprovalDocument.created_at.desc()).all())
        elif tab == 'inbox':
            # 내가 현재 결재할 차례인 진행중 문서
            docs = (base.join(ApprovalStep)
                    .filter(ApprovalDocument.status == 'pending',
                            ApprovalStep.approver_id == uid,
                            ApprovalStep.status == 'current')
                    .order_by(ApprovalDocument.submitted_at.desc())
                    .all())
        elif tab == 'drafted':
            docs = (base.filter(ApprovalDocument.drafter_id == uid)
                    .order_by(ApprovalDocument.created_at.desc()).all())
        elif tab == 'referenced':
            docs = (base.join(ApprovalReference)
                    .filter(ApprovalReference.user_id == uid)
                    .order_by(ApprovalDocument.submitted_at.desc().nullslast())
                    .all())
        elif tab == 'progress':
            # 내가 결재선에 있고 아직 내 차례가 안 온/지난 진행중 문서
            docs = (base.join(ApprovalStep)
                    .filter(ApprovalDocument.status == 'pending',
                            ApprovalStep.approver_id == uid)
                    .order_by(ApprovalDocument.submitted_at.desc())
                    .distinct().all())
        else:  # done
            docs = (base.join(ApprovalStep)
                    .filter(ApprovalDocument.status.in_(['approved', 'rejected']),
                            or_(ApprovalStep.approver_id == uid,
                                ApprovalDocument.drafter_id == uid))
                    .order_by(ApprovalDocument.completed_at.desc().nullslast())
                    .distinct().all())

        # 통계 카운트
        inbox_count = (db.query(ApprovalDocument).join(ApprovalStep)
                       .filter(ApprovalDocument.status == 'pending',
                               ApprovalStep.approver_id == uid,
                               ApprovalStep.status == 'current').count())
        progress_count = (db.query(ApprovalDocument).join(ApprovalStep)
                          .filter(ApprovalDocument.status == 'pending',
                                  ApprovalStep.approver_id == uid).distinct().count())
        drafted_count = (db.query(ApprovalDocument)
                         .filter(ApprovalDocument.drafter_id == uid).count())
        done_count = (db.query(ApprovalDocument).join(ApprovalStep)
                      .filter(ApprovalDocument.status.in_(['approved', 'rejected']),
                              or_(ApprovalStep.approver_id == uid,
                                  ApprovalDocument.drafter_id == uid)).distinct().count())
        stats = {'inbox': inbox_count, 'progress': progress_count,
                 'drafted': drafted_count, 'done': done_count}
        forms = svc.get_active_forms(db)
        return render_template('approval_list.html',
                               docs=docs, tab=tab, forms=forms,
                               inbox_count=inbox_count, stats=stats)


# ────────────────────────────────────────────────────────
# 기안 작성
# ────────────────────────────────────────────────────────

@approval_bp.route('/new')
@menu_required('approval')
def approval_new():
    form_key = request.args.get('form')
    with get_db() as db:
        svc.seed_form_templates(db)
        db.commit()
        forms = svc.get_active_forms(db)
        form = None
        if form_key:
            form = db.query(ApprovalFormTemplate).filter_by(form_key=form_key, is_active=True).first()
        users = (db.query(User)
                 .filter(User.is_active.is_(True), User.user_group != '최고관리자')
                 .order_by(User.user_group, User.full_name).all())
        user_dicts = [{'id': u.id, 'name': u.full_name, 'dept': u.user_group or '',
                       'position': u.position or ''} for u in users]

        default_line = []
        leave_balance = None
        holidays = []
        me = db.query(User).get(_me())
        # 본인 전결 대상: 자동 결재선이 비는 최상위 기안자
        self_approval = not svc.resolve_default_line(db, me)
        default_refs = []
        if form:
            steps = svc.resolve_default_line(db, me, form.default_line)
            default_line = steps
            # 양식별 기본 수신자 (휴가/지출 → 관리부 서은미 과장). 본인 제외.
            default_refs = [{'user_id': r.id, 'user_name': r.full_name, 'ref_type': 'receiver'}
                            for r in svc.resolve_default_refs(db, form.form_key) if r.id != me.id]
            if form.form_key == 'leave':
                leave_balance = _leave_balance(db, me)
                holidays = _holiday_list()
        return render_template('approval_form.html',
                               forms=forms, form=form,
                               users=user_dicts, default_line=default_line,
                               doc=None, leave_balance=leave_balance, holidays=holidays,
                               self_approval=self_approval, refs=default_refs)


@approval_bp.route('/<int:doc_id>/edit')
@menu_required('approval')
def approval_edit(doc_id):
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        is_admin = session.get('role') == 'admin'
        if doc.drafter_id != _me() and not is_admin:
            flash('본인이 기안한 문서만 수정할 수 있습니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        # 작성중 문서는 기안자/관리자 모두, 상신된 문서는 관리자만 수정 가능
        if doc.status != 'draft' and not is_admin:
            flash('작성중(임시저장) 문서만 수정할 수 있습니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))

        forms = svc.get_active_forms(db)
        form = db.query(ApprovalFormTemplate).filter_by(form_key=doc.form_key).first()
        users = (db.query(User)
                 .filter(User.is_active.is_(True), User.user_group != '최고관리자')
                 .order_by(User.user_group, User.full_name).all())
        user_dicts = [{'id': u.id, 'name': u.full_name, 'dept': u.user_group or '',
                       'position': u.position or ''} for u in users]
        default_line = [{'approver_id': s.approver_id, 'approver_name': s.approver_name,
                         'approver_position': s.approver_position or '',
                         'approver_dept': s.approver_dept or '', 'role': s.role}
                        for s in doc.steps]
        refs = [{'user_id': r.user_id, 'user_name': r.user_name, 'ref_type': r.ref_type}
                for r in doc.references]
        leave_balance = None
        holidays = []
        drafter = db.query(User).get(doc.drafter_id)
        self_approval = not svc.resolve_default_line(db, drafter) if drafter else False
        if form and form.form_key == 'leave':
            leave_balance = _leave_balance(db, drafter)
            holidays = _holiday_list()
        return render_template('approval_form.html',
                               forms=forms, form=form, users=user_dicts,
                               default_line=default_line, doc=doc, refs=refs,
                               leave_balance=leave_balance, holidays=holidays,
                               self_approval=self_approval)


@approval_bp.route('/save', methods=['POST'])
@menu_required('approval')
def approval_save():
    """임시저장(draft) 또는 상신(submit)."""
    action = request.form.get('action', 'draft')
    doc_id = _safe_int(request.form.get('doc_id'))
    form_key = request.form.get('form_key', '').strip()
    title = request.form.get('title', '').strip()

    with get_db() as db:
        me = db.query(User).get(_me())
        if not me:
            abort(403)
        form = db.query(ApprovalFormTemplate).filter_by(form_key=form_key).first()
        if not form:
            flash('양식을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('approval.approval_list'))

        if not title:
            flash('제목을 입력하세요.', 'warning')
            return redirect(request.referrer or url_for('approval.approval_new', form=form_key))

        # 양식 필드값 수집
        form_data = {}
        amount = None
        for field in (form.field_schema or []):
            key = field['key']
            if field.get('type') == 'lineitems':
                cols = field.get('columns', [])
                col_vals = {c['key']: request.form.getlist(f"li_{c['key']}") for c in cols}
                n = max((len(v) for v in col_vals.values()), default=0)
                rows = []
                total = 0
                for i in range(n):
                    row = {}
                    has_val = False
                    for c in cols:
                        cv = (col_vals[c['key']][i] if i < len(col_vals[c['key']]) else '').strip()
                        row[c['key']] = cv
                        if cv:
                            has_val = True
                    if not has_val:
                        continue
                    amt = _safe_int(str(row.get('amount', '')).replace(',', ''))
                    if amt:
                        total += amt
                    rows.append(row)
                form_data[key] = rows
                form_data['amount'] = total
                amount = total or amount
                continue
            val = request.form.get(f'field_{key}', '').strip()
            form_data[key] = val
            if form.amount_field and key == form.amount_field and val:
                amount = _safe_int(val.replace(',', ''))
        content = request.form.get('content', '').strip()

        # 문서 생성/수정
        is_admin = session.get('role') == 'admin'
        admin_override = False
        if doc_id:
            doc = db.query(ApprovalDocument).get(doc_id)
            if not doc or (doc.drafter_id != me.id and not is_admin):
                abort(403)
            if doc.status != 'draft':
                # 상신된 문서는 관리자만 내용 수정 가능 (결재선·상태 보존)
                if not is_admin:
                    flash('이미 상신된 문서입니다.', 'warning')
                    return redirect(url_for('approval.approval_detail', doc_id=doc_id))
                admin_override = True
        else:
            doc = ApprovalDocument(
                form_key=form.form_key, form_name=form.name,
                drafter_id=me.id, drafter_name=me.full_name,
                drafter_dept=me.user_group, drafter_position=me.position,
                status='draft',
            )
            db.add(doc)

        doc.title = title
        doc.form_name = form.name
        doc.form_data = form_data
        doc.content = content
        doc.amount = amount
        db.flush()

        # 증빙서류 등 첨부파일 (생성·수정 시 업로드)
        _save_uploaded_attachments(db, doc)

        # 관리자가 상신된 문서를 수정하는 경우: 결재선·상태 보존, 내용만 갱신
        if admin_override:
            log_activity(db, 'approval', 'admin_edit',
                         f'[{doc.doc_no or "임시"}] {doc.title} 관리자 수정 (결재선·상태 유지)',
                         ref_type='approval', ref_id=doc.id, ref_label=doc.title)
            db.commit()
            flash('관리자 권한으로 수정되었습니다. (결재선·진행상태는 유지)', 'success')
            return redirect(url_for('approval.approval_detail', doc_id=doc.id))

        # 결재선 재구성
        _rebuild_steps(db, doc)
        # 참조/수신 재구성
        _rebuild_references(db, doc)
        db.flush()

        if action == 'submit':
            try:
                svc.submit_document(db, doc)
            except ValueError as e:
                db.rollback()
                flash(str(e), 'warning')
                return redirect(url_for('approval.approval_edit', doc_id=doc.id) if doc.id
                                else url_for('approval.approval_new', form=form_key))
            log_activity(db, 'approval', 'submit', f'[{doc.doc_no}] {doc.title} 상신',
                         ref_type='approval', ref_id=doc.id, ref_label=doc.title)
            db.commit()
            flash(f'상신되었습니다. ({doc.doc_no})', 'success')
            return redirect(url_for('approval.approval_detail', doc_id=doc.id))

        db.commit()
        flash('임시저장되었습니다.', 'success')
        return redirect(url_for('approval.approval_edit', doc_id=doc.id))


def _save_uploaded_attachments(db, doc):
    """폼에서 업로드된 첨부파일(증빙서류 등)을 저장. name='attachments'."""
    files = request.files.getlist('attachments')
    for f in files:
        if not f or not f.filename:
            continue
        data = f.read()
        if not data or len(data) > MAX_SIZE:
            continue
        fname = secure_filename(f.filename) or 'file'
        ext = os.path.splitext(fname)[1].lstrip('.').lower()
        if ext not in ALLOWED_EXT:
            continue
        idx = len(doc.attachments) + 1
        storage_path = f"documents/approval/{doc.id}/{idx}_{fname}"
        ok, err = upload_bytes(storage_path, data, f.mimetype or 'application/octet-stream')
        if not ok:
            continue
        doc.attachments.append(ApprovalAttachment(
            filename=f.filename, storage_path=storage_path,
            content_type=f.mimetype, size=len(data)))


def _rebuild_steps(db, doc):
    """폼에서 받은 결재선으로 ApprovalStep 재생성 (draft 상태에서만).
    relationship append로 doc.steps 컬렉션을 즉시 동기화 (submit 검증용)."""
    for s in list(doc.steps):
        db.delete(s)
    db.flush()
    doc.steps.clear()
    approver_ids = request.form.getlist('approver_id')
    roles = request.form.getlist('approver_role')
    order = 1
    seen = set()
    for i, aid in enumerate(approver_ids):
        uid = _safe_int(aid)
        if not uid or uid in seen:
            continue
        u = db.query(User).get(uid)
        if not u:
            continue
        seen.add(uid)
        role = roles[i] if i < len(roles) else 'approval'
        doc.steps.append(ApprovalStep(
            step_order=order,
            approver_id=u.id, approver_name=u.full_name,
            approver_position=u.position, approver_dept=u.user_group,
            role=role if role in ('approval', 'agreement') else 'approval',
            status='waiting',
        ))
        order += 1


def _rebuild_references(db, doc):
    for r in list(doc.references):
        db.delete(r)
    db.flush()
    doc.references.clear()
    ref_ids = request.form.getlist('ref_id')
    ref_types = request.form.getlist('ref_type')
    seen = set()
    for i, rid in enumerate(ref_ids):
        uid = _safe_int(rid)
        if not uid or uid in seen:
            continue
        u = db.query(User).get(uid)
        if not u:
            continue
        seen.add(uid)
        rtype = ref_types[i] if i < len(ref_types) else 'reference'
        doc.references.append(ApprovalReference(
            user_id=u.id, user_name=u.full_name,
            ref_type=rtype if rtype in ('reference', 'receiver') else 'reference',
        ))


# ────────────────────────────────────────────────────────
# 상세 + 결재 액션
# ────────────────────────────────────────────────────────

@approval_bp.route('/<int:doc_id>')
@menu_required('approval')
def approval_detail(doc_id):
    uid = _me()
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        if not _can_view(doc):
            flash('열람 권한이 없습니다.', 'danger')
            return redirect(url_for('approval.approval_list'))

        # 참조자 열람 표시
        for r in doc.references:
            if r.user_id == uid and not r.is_read:
                r.is_read = True
                r.read_at = datetime.datetime.now()
        db.commit()

        form = db.query(ApprovalFormTemplate).filter_by(form_key=doc.form_key).first()
        my_step = next((s for s in doc.steps
                        if s.approver_id == uid and s.status == 'current'), None)
        is_admin = session.get('role') == 'admin'
        can_cancel = (doc.drafter_id == uid and doc.status == 'pending'
                      and not any(s.status == 'approved' for s in doc.steps))
        # 관리자는 상태 무관 수정/삭제 가능, 기안자는 작성중(수정)·작성중/회수/반려(삭제)
        can_edit = is_admin or (doc.drafter_id == uid and doc.status == 'draft')
        can_delete = is_admin or (doc.drafter_id == uid
                                  and doc.status in ('draft', 'canceled', 'rejected'))
        return render_template('approval_detail.html',
                               doc=doc, form=form, my_step=my_step,
                               can_cancel=can_cancel, can_edit=can_edit,
                               can_delete=can_delete, is_admin=is_admin)


@approval_bp.route('/<int:doc_id>/approve', methods=['POST'])
@menu_required('approval')
def approval_approve(doc_id):
    comment = request.form.get('comment', '').strip()
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        step = next((s for s in doc.steps
                     if s.approver_id == _me() and s.status == 'current'), None)
        if not step:
            flash('현재 결재 차례가 아닙니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        try:
            svc.approve_step(db, doc, step, comment)
        except ValueError as e:
            db.rollback()
            flash(str(e), 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        log_activity(db, 'approval', 'approve', f'[{doc.doc_no}] {doc.title} 승인',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.commit()
        flash('승인했습니다.', 'success')
        return redirect(url_for('approval.approval_detail', doc_id=doc_id))


@approval_bp.route('/<int:doc_id>/reject', methods=['POST'])
@menu_required('approval')
def approval_reject(doc_id):
    comment = request.form.get('comment', '').strip()
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        step = next((s for s in doc.steps
                     if s.approver_id == _me() and s.status == 'current'), None)
        if not step:
            flash('현재 결재 차례가 아닙니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        if not comment:
            flash('반려 사유를 입력하세요.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        try:
            svc.reject_step(db, doc, step, comment)
        except ValueError as e:
            db.rollback()
            flash(str(e), 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        log_activity(db, 'approval', 'reject', f'[{doc.doc_no}] {doc.title} 반려',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.commit()
        flash('반려했습니다.', 'info')
        return redirect(url_for('approval.approval_detail', doc_id=doc_id))


@approval_bp.route('/<int:doc_id>/cancel', methods=['POST'])
@menu_required('approval')
def approval_cancel(doc_id):
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        if doc.drafter_id != _me():
            abort(403)
        try:
            svc.cancel_document(db, doc)
        except ValueError as e:
            db.rollback()
            flash(str(e), 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        log_activity(db, 'approval', 'cancel', f'[{doc.doc_no}] {doc.title} 회수',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.commit()
        flash('회수되었습니다.', 'info')
        return redirect(url_for('approval.approval_detail', doc_id=doc_id))


@approval_bp.route('/<int:doc_id>/delete', methods=['POST'])
@menu_required('approval')
def approval_delete(doc_id):
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        is_admin = session.get('role') == 'admin'
        if doc.drafter_id != _me() and not is_admin:
            abort(403)
        # 진행/완료 문서는 관리자만 삭제 가능 (기안자는 작성중/회수/반려만)
        if not is_admin and doc.status not in ('draft', 'canceled', 'rejected'):
            flash('진행 중인 문서는 삭제할 수 없습니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        for att in doc.attachments:
            try:
                delete_object(att.storage_path)
            except Exception:
                pass
        # 휴가신청서 삭제 시 연차 차감은 자동 환원(used_leave_days가 현존 문서만 조회)
        log_activity(db, 'approval', 'delete',
                     f'[{doc.doc_no or "임시"}] {doc.title} 삭제 (상태: {doc.status})',
                     ref_type='approval', ref_id=doc.id, ref_label=doc.title)
        db.delete(doc)
        db.commit()
        flash('삭제되었습니다.', 'success')
        return redirect(url_for('approval.approval_list', tab='drafted'))


@approval_bp.route('/<int:doc_id>/comment', methods=['POST'])
@menu_required('approval')
def approval_comment(doc_id):
    content = request.form.get('content', '').strip()
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        if not _can_view(doc):
            abort(403)
        if content:
            me = db.query(User).get(_me())
            db.add(ApprovalComment(document_id=doc.id, user_id=me.id,
                                   user_name=me.full_name, content=content))
            db.commit()
        return redirect(url_for('approval.approval_detail', doc_id=doc_id))


# ────────────────────────────────────────────────────────
# 첨부파일
# ────────────────────────────────────────────────────────

@approval_bp.route('/<int:doc_id>/attachment', methods=['POST'])
@menu_required('approval')
def approval_attachment_upload(doc_id):
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        if doc.drafter_id != _me() and session.get('role') != 'admin':
            abort(403)
        if doc.status not in ('draft', 'pending'):
            flash('완료/반려된 문서에는 첨부할 수 없습니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        file_obj = request.files.get('file')
        if not file_obj or not file_obj.filename:
            flash('파일을 선택하세요.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        data = file_obj.read()
        if len(data) > MAX_SIZE:
            flash('첨부파일은 20MB 이하여야 합니다.', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        fname = secure_filename(file_obj.filename) or 'file'
        ext = os.path.splitext(fname)[1].lstrip('.').lower()
        if ext not in ALLOWED_EXT:
            flash(f'허용되지 않는 형식입니다. ({", ".join(sorted(ALLOWED_EXT))})', 'warning')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        # 한글 파일명 보존: storage path는 id 기반, 표시명은 원본
        idx = len(doc.attachments) + 1
        storage_path = f"documents/approval/{doc.id}/{idx}_{fname}"
        ok, err = upload_bytes(storage_path, data,
                               file_obj.mimetype or 'application/octet-stream')
        if not ok:
            flash(f'업로드 실패: {err}', 'danger')
            return redirect(url_for('approval.approval_detail', doc_id=doc_id))
        db.add(ApprovalAttachment(
            document_id=doc.id, filename=file_obj.filename,
            storage_path=storage_path, content_type=file_obj.mimetype, size=len(data)))
        db.commit()
        flash('첨부되었습니다.', 'success')
        return redirect(url_for('approval.approval_detail', doc_id=doc_id))


@approval_bp.route('/<int:doc_id>/attachment/<int:att_id>')
@menu_required('approval')
def approval_attachment_download(doc_id, att_id):
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc or not _can_view(doc):
            abort(404)
        att = db.query(ApprovalAttachment).get(att_id)
        if not att or att.document_id != doc.id:
            abort(404)
        data = download_bytes(att.storage_path)
        if data is None:
            abort(404)
        from urllib.parse import quote
        disp = quote(att.filename)
        return Response(data, mimetype=att.content_type or 'application/octet-stream',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{disp}"})


@approval_bp.route('/<int:doc_id>/attachment/<int:att_id>/delete', methods=['POST'])
@menu_required('approval')
def approval_attachment_delete(doc_id, att_id):
    with get_db() as db:
        doc = db.query(ApprovalDocument).get(doc_id)
        if not doc:
            abort(404)
        if doc.drafter_id != _me() and session.get('role') != 'admin':
            abort(403)
        att = db.query(ApprovalAttachment).get(att_id)
        if att and att.document_id == doc.id:
            try:
                delete_object(att.storage_path)
            except Exception:
                pass
            db.delete(att)
            db.commit()
        return redirect(url_for('approval.approval_detail', doc_id=doc_id))


# ────────────────────────────────────────────────────────
# API (결재선 자동 구성)
# ────────────────────────────────────────────────────────

@approval_bp.route('/api/default-line')
@menu_required('approval')
def api_default_line():
    form_key = request.args.get('form')
    with get_db() as db:
        form = db.query(ApprovalFormTemplate).filter_by(form_key=form_key).first()
        me = db.query(User).get(_me())
        if not form or not me:
            return jsonify({'steps': []})
        steps = svc.resolve_default_line(db, me, form.default_line)
        return jsonify({'steps': steps})


# ────────────────────────────────────────────────────────
# 관리자: 양식 템플릿 편집
# ────────────────────────────────────────────────────────

@approval_bp.route('/admin/templates')
@admin_required
def admin_templates():
    with get_db() as db:
        svc.seed_form_templates(db)
        db.commit()
        forms = (db.query(ApprovalFormTemplate)
                 .order_by(ApprovalFormTemplate.sort_order, ApprovalFormTemplate.id).all())
        # 양식별 사용 문서 수
        usage = {}
        for f in forms:
            usage[f.id] = (db.query(ApprovalDocument)
                           .filter(ApprovalDocument.form_key == f.form_key).count())
        return render_template('approval_templates_admin.html',
                               forms=forms, usage=usage, edit_form=None)


@approval_bp.route('/admin/templates/new')
@admin_required
def admin_template_new():
    with get_db() as db:
        forms = (db.query(ApprovalFormTemplate)
                 .order_by(ApprovalFormTemplate.sort_order, ApprovalFormTemplate.id).all())
        return render_template('approval_templates_admin.html',
                               forms=forms, usage={}, edit_form={'is_new': True})


@approval_bp.route('/admin/templates/<int:tid>/edit')
@admin_required
def admin_template_edit(tid):
    with get_db() as db:
        forms = (db.query(ApprovalFormTemplate)
                 .order_by(ApprovalFormTemplate.sort_order, ApprovalFormTemplate.id).all())
        ef = db.query(ApprovalFormTemplate).get(tid)
        if not ef:
            abort(404)
        edit = {
            'is_new': False, 'id': ef.id, 'form_key': ef.form_key, 'name': ef.name,
            'icon': ef.icon or '', 'description': ef.description or '',
            'field_schema': ef.field_schema or [], 'default_line': ef.default_line or [],
            'has_amount': ef.has_amount, 'amount_field': ef.amount_field or '',
            'effect_on_dept_head': ef.effect_on_dept_head,
            'sort_order': ef.sort_order or 0, 'is_active': ef.is_active,
        }
        return render_template('approval_templates_admin.html',
                               forms=forms, usage={}, edit_form=edit)


@approval_bp.route('/admin/templates/save', methods=['POST'])
@admin_required
def admin_template_save():
    tid = _safe_int(request.form.get('tid'))
    form_key = (request.form.get('form_key') or '').strip().lower()
    name = (request.form.get('name') or '').strip()
    with get_db() as db:
        if not name:
            flash('양식명을 입력하세요.', 'warning')
            return redirect(url_for('approval.admin_templates'))

        # field_schema 조립
        keys = request.form.getlist('field_key')
        labels = request.form.getlist('field_label')
        types = request.form.getlist('field_type')
        requireds = request.form.getlist('field_required')  # "1" per row included only if checked → use index map
        # required는 체크박스라 인덱스 매칭이 어려움 → field_required_<i> 패턴 사용
        suffixes = request.form.getlist('field_suffix')
        options_raw = request.form.getlist('field_options')
        schema = []
        for i, k in enumerate(keys):
            k = (k or '').strip()
            lbl = (labels[i] if i < len(labels) else '').strip()
            if not k or not lbl:
                continue
            ftype = types[i] if i < len(types) else 'text'
            fld = {'key': k, 'label': lbl, 'type': ftype,
                   'required': request.form.get(f'field_required_{i}') == '1'}
            if ftype == 'select':
                opts = [o.strip() for o in re.split(r'[,\n]', options_raw[i] if i < len(options_raw) else '') if o.strip()]
                fld['options'] = opts
            sfx = (suffixes[i] if i < len(suffixes) else '').strip()
            if sfx:
                fld['suffix'] = sfx
            schema.append(fld)

        # default_line
        line = ['drafter']
        if request.form.get('line_dept_head') == '1':
            line.append('dept_head')
        if request.form.get('line_executive') == '1':
            line.append('executive')

        amount_field = (request.form.get('amount_field') or '').strip()
        has_amount = bool(amount_field)
        sort_order = _safe_int(request.form.get('sort_order'), 0)
        is_active = request.form.get('is_active') == '1'
        effect_on_dept_head = request.form.get('effect_on_dept_head') == '1'
        icon = (request.form.get('icon') or '').strip()
        description = (request.form.get('description') or '').strip()

        if tid:
            ef = db.query(ApprovalFormTemplate).get(tid)
            if not ef:
                abort(404)
        else:
            if not form_key:
                flash('양식 키(form_key)를 입력하세요. (영문 소문자)', 'warning')
                return redirect(url_for('approval.admin_template_new'))
            if db.query(ApprovalFormTemplate).filter_by(form_key=form_key).first():
                flash(f'이미 존재하는 양식 키입니다: {form_key}', 'warning')
                return redirect(url_for('approval.admin_template_new'))
            ef = ApprovalFormTemplate(form_key=form_key)
            db.add(ef)

        ef.name = name
        ef.icon = icon
        ef.description = description
        ef.field_schema = schema
        ef.default_line = line
        ef.has_amount = has_amount
        ef.amount_field = amount_field or None
        ef.effect_on_dept_head = effect_on_dept_head
        ef.sort_order = sort_order
        ef.is_active = is_active
        log_activity(db, 'approval', 'template_save', f'전자결재 양식 저장: {name}',
                     ref_type='approval_template', ref_id=ef.id, ref_label=name)
        db.commit()
        flash('양식이 저장되었습니다.', 'success')
        return redirect(url_for('approval.admin_template_edit', tid=ef.id))


@approval_bp.route('/admin/templates/<int:tid>/toggle', methods=['POST'])
@admin_required
def admin_template_toggle(tid):
    with get_db() as db:
        ef = db.query(ApprovalFormTemplate).get(tid)
        if not ef:
            abort(404)
        ef.is_active = not ef.is_active
        db.commit()
        flash(f'양식을 {"활성화" if ef.is_active else "비활성화"}했습니다.', 'success')
        return redirect(url_for('approval.admin_templates'))


@approval_bp.route('/admin/templates/<int:tid>/delete', methods=['POST'])
@admin_required
def admin_template_delete(tid):
    with get_db() as db:
        ef = db.query(ApprovalFormTemplate).get(tid)
        if not ef:
            abort(404)
        used = db.query(ApprovalDocument).filter(ApprovalDocument.form_key == ef.form_key).count()
        if used:
            flash(f'이미 {used}건의 문서가 이 양식을 사용 중입니다. 삭제 대신 비활성화하세요.', 'warning')
            return redirect(url_for('approval.admin_templates'))
        db.delete(ef)
        db.commit()
        flash('양식이 삭제되었습니다.', 'success')
        return redirect(url_for('approval.admin_templates'))
