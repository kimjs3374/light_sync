"""시방서/규격서 추적 + 조도 시뮬레이션 설계 보고서 관리 (매그나텍 PHASE 2~3)"""
import datetime
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.models import (
    Project, SpecDocument, DesignSimulationDoc,
    SPEC_DOC_STATUS, SPEC_DOC_TYPES, SIMULATION_DOC_TYPES,
)
from modules.history_board import append_history_log

spec_doc_bp = Blueprint("spec_doc", __name__)

UPLOAD_SUBDIR = 'spec_docs'


def _save_file(file_obj, subdir):
    if not file_obj or not file_obj.filename:
        return None
    upload_dir = os.path.join(current_app.static_folder, 'uploads', subdir)
    os.makedirs(upload_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    safe_name = file_obj.filename.replace(' ', '_')
    fname = f"{ts}_{safe_name}"
    file_obj.save(os.path.join(upload_dir, fname))
    return f"uploads/{subdir}/{fname}"


# ═══════════════════════════════════════════
# 시방서/규격서 추적 (PHASE 3)
# ═══════════════════════════════════════════
@spec_doc_bp.route('/spec-documents')
@login_required
def spec_doc_list():
    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    with get_db() as db:
        query = db.query(SpecDocument).join(SpecDocument.project)

        if q:
            query = query.filter(
                (Project.temp_name.ilike(f'%{q}%'))
                | (SpecDocument.title.ilike(f'%{q}%'))
            )
        if status_filter:
            query = query.filter(SpecDocument.doc_status == status_filter)

        docs = query.order_by(SpecDocument.created_at.desc()).all()

        # 통계
        all_docs = db.query(SpecDocument).all()
        stats = {s: sum(1 for d in all_docs if d.doc_status == s) for s in SPEC_DOC_STATUS}
        stats['total'] = len(all_docs)

        # 시방서 등록 가능한 프로젝트 목록
        projects = db.query(Project).filter(
            Project.status == '설계'
        ).order_by(Project.id.desc()).all()

    return render_template(
        'spec_doc_list.html',
        docs=docs,
        stats=stats,
        projects=projects,
        doc_types=SPEC_DOC_TYPES,
        doc_statuses=SPEC_DOC_STATUS,
        filters={'q': q, 'status': status_filter},
    )


@spec_doc_bp.route('/spec-documents/create', methods=['POST'])
@login_required
def spec_doc_create():
    with get_db() as db:
        project_id = safe_int(request.form.get('project_id'))
        if not project_id:
            flash('현장을 선택해주세요.', 'warning')
            return redirect(url_for('spec_doc.spec_doc_list'))

        file_path = _save_file(request.files.get('doc_file'), 'spec_docs')
        doc = SpecDocument(
            project_id=project_id,
            doc_type=request.form.get('doc_type', '시방서'),
            doc_status=request.form.get('doc_status', '미제출'),
            title=request.form.get('title', '').strip() or None,
            file_path=file_path,
            submitted_date=parse_date(request.form.get('submitted_date')),
            note=request.form.get('note', '').strip() or None,
            created_by=request.form.get('created_by', '').strip() or None,
        )
        db.add(doc)
        db.flush()

        append_history_log(
            db, project_id=project_id, user_name="System",
            content=f"[시방서] {doc.doc_type} '{doc.title or '-'}' 등록 ({doc.doc_status})",
            scope="design", kind="system",
        )
        db.commit()
        flash('시방서/규격서 등록 완료', 'success')

    return redirect(url_for('spec_doc.spec_doc_list'))


@spec_doc_bp.route('/spec-documents/<int:doc_id>/update', methods=['POST'])
@login_required
def spec_doc_update(doc_id):
    with get_db() as db:
        doc = db.query(SpecDocument).get(doc_id)
        if not doc:
            flash('문서를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('spec_doc.spec_doc_list'))

        old_status = doc.doc_status
        doc.doc_status = request.form.get('doc_status', doc.doc_status)
        doc.title = request.form.get('title', '').strip() or doc.title
        doc.note = request.form.get('note', '').strip() or None
        doc.confirmed_date = parse_date(request.form.get('confirmed_date'))

        new_file = request.files.get('doc_file')
        if new_file and new_file.filename:
            doc.file_path = _save_file(new_file, 'spec_docs')

        if old_status != doc.doc_status:
            append_history_log(
                db, project_id=doc.project_id, user_name="System",
                content=f"[시방서] {doc.doc_type} 상태 변경: {old_status} → {doc.doc_status}",
                scope="design", kind="system",
            )

        db.commit()
        flash('시방서/규격서 수정 완료', 'success')

    return redirect(url_for('spec_doc.spec_doc_list'))


@spec_doc_bp.route('/spec-documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def spec_doc_delete(doc_id):
    with get_db() as db:
        doc = db.query(SpecDocument).get(doc_id)
        if doc:
            db.delete(doc)
            db.commit()
            flash('삭제 완료', 'success')
    return redirect(url_for('spec_doc.spec_doc_list'))


# ═══════════════════════════════════════════
# 조도 시뮬레이션 설계 보고서 (PHASE 2)
# ═══════════════════════════════════════════
@spec_doc_bp.route('/design-simulations')
@login_required
def simulation_list():
    q = request.args.get('q', '').strip()

    with get_db() as db:
        query = db.query(DesignSimulationDoc).join(DesignSimulationDoc.project)

        if q:
            query = query.filter(
                (Project.temp_name.ilike(f'%{q}%'))
                | (DesignSimulationDoc.title.ilike(f'%{q}%'))
            )

        docs = query.order_by(DesignSimulationDoc.created_at.desc()).all()

        # 등록 가능한 프로젝트 (설계 단계)
        projects = db.query(Project).filter(
            Project.status == '설계'
        ).order_by(Project.id.desc()).all()

    return render_template(
        'simulation_list.html',
        docs=docs,
        projects=projects,
        doc_types=SIMULATION_DOC_TYPES,
        filters={'q': q},
    )


@spec_doc_bp.route('/design-simulations/create', methods=['POST'])
@login_required
def simulation_create():
    with get_db() as db:
        project_id = safe_int(request.form.get('project_id'))
        if not project_id:
            flash('현장을 선택해주세요.', 'warning')
            return redirect(url_for('spec_doc.simulation_list'))

        file_path = _save_file(request.files.get('doc_file'), 'simulations')

        doc = DesignSimulationDoc(
            project_id=project_id,
            doc_type=request.form.get('doc_type', 'DIALux'),
            title=request.form.get('title', '').strip() or None,
            file_path=file_path,
            simulation_date=parse_date(request.form.get('simulation_date')),
            target_lux=float(request.form.get('target_lux') or 0) or None,
            achieved_lux=float(request.form.get('achieved_lux') or 0) or None,
            uniformity=float(request.form.get('uniformity') or 0) or None,
            note=request.form.get('note', '').strip() or None,
            created_by=request.form.get('created_by', '').strip() or None,
        )
        db.add(doc)
        db.flush()

        append_history_log(
            db, project_id=project_id, user_name="System",
            content=f"[조도설계] {doc.doc_type} '{doc.title or '-'}' 보고서 등록",
            scope="design", kind="system",
        )
        db.commit()
        flash('시뮬레이션 보고서 등록 완료', 'success')

    return redirect(url_for('spec_doc.simulation_list'))


@spec_doc_bp.route('/design-simulations/<int:doc_id>/delete', methods=['POST'])
@login_required
def simulation_delete(doc_id):
    with get_db() as db:
        doc = db.query(DesignSimulationDoc).get(doc_id)
        if doc:
            db.delete(doc)
            db.commit()
            flash('삭제 완료', 'success')
    return redirect(url_for('spec_doc.simulation_list'))
