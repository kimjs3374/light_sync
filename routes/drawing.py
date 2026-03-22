import datetime
import io
from pathlib import Path, PurePosixPath
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, abort, current_app, jsonify, Response
from modules.auth_decorators import login_required
from werkzeug.utils import secure_filename
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from modules.db_context import get_db
from modules.utils import validate_upload
from modules.models import (
    Project,
    Contract,
    Drawing,
    DrawingVersion,
    DrawingAccessLog,
    DRAWING_TYPE_OPTIONS,
)
from modules.history_board import append_history_log
from modules.storage_adapter import upload_bytes, download_bytes, delete_object, is_storage_enabled

drawing_bp = Blueprint('drawing', __name__)


def _can_write_drawings():
    return session.get('role') == 'admin' or session.get('user_group') == '영업부'


def _can_read_drawings():
    if 'user_id' not in session:
        return False
    if session.get('role') == 'admin':
        return True
    return session.get('user_group') in {'영업부', '생산부', '관리부', '최고관리자'}


def _log_access(db, access_type='VIEW'):
    db.add(DrawingAccessLog(
        share_link_id=None,
        user_id=session.get('user_id'),
        access_type=access_type,
        ip_address=request.remote_addr,
        user_agent=(request.headers.get('User-Agent') or '')[:500],
    ))


# ── 메인 SPA 페이지 ───────────────────────────────────────────────────

@drawing_bp.route('/drawings')
@drawing_bp.route('/drawings/project/<int:project_id>')
@login_required
def drawings_index(project_id=None):
    if not _can_read_drawings():
        flash('도면 열람 권한이 없습니다.', 'danger')
        return redirect(url_for('dashboard.dashboard_view'))

    with get_db() as db:
        from modules.contract_filters import DONE_STATUSES
        status_filter = request.args.get('status', 'active')

        q = (
            db.query(
                Project.id,
                Project.project_no,
                Project.temp_name.label('site_name'),
                func.count(Drawing.id).label('drawing_count'),
            )
            .outerjoin(Drawing, Drawing.project_id == Project.id)
        )
        if status_filter == 'active':
            q = q.outerjoin(Contract, Contract.project_id == Project.id).filter(
                Contract.payment_status.notin_(DONE_STATUSES),
                Contract.is_excluded.isnot(True),
            )
        elif status_filter == 'done':
            q = q.join(Contract, Contract.project_id == Project.id).filter(
                Contract.payment_status.in_(DONE_STATUSES),
            )

        projects = q.group_by(Project.id).order_by(Project.id.desc()).all()

        selected = None
        if project_id:
            selected = db.query(Project).filter(Project.id == project_id).first()
            if not selected:
                abort(404)
        elif projects:
            selected = db.query(Project).filter(Project.id == projects[0].id).first()
            if selected:
                project_id = selected.id

        return render_template(
            'drawings_gallery.html',
            projects=projects,
            selected=selected,
            selected_id=project_id,
            drawing_type_options=DRAWING_TYPE_OPTIONS,
            can_write=_can_write_drawings(),
            status_filter=status_filter,
        )


# ── AJAX API ──────────────────────────────────────────────────────────

@drawing_bp.route('/drawings/api/project/<int:project_id>')
@login_required
def api_project_drawings(project_id):
    if not _can_read_drawings():
        return jsonify({'error': '권한 없음'}), 403

    with get_db() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return jsonify({'error': '현장 없음'}), 404

        drawings = (
            db.query(Drawing)
            .options(joinedload(Drawing.versions))
            .filter(Drawing.project_id == project_id)
            .all()
        )
        drawings = sorted(drawings, key=lambda d: d.updated_at or d.created_at, reverse=True)

        drawings_data = []
        for d in drawings:
            versions = sorted(d.versions, key=lambda v: v.version_no, reverse=True)
            latest = next((v for v in versions if v.is_latest), versions[0] if versions else None)
            drawings_data.append({
                'id': d.id,
                'title': d.title,
                'drawing_type': d.drawing_type,
                'updated_at': (d.updated_at or d.created_at).strftime('%Y-%m-%d'),
                'latest_version_id': latest.id if latest else None,
                'version_count': len(versions),
                'versions': [
                    {
                        'id': v.id,
                        'version_no': v.version_no,
                        'is_latest': v.is_latest,
                        'has_pdf': bool(v.pdf_path),
                        'has_dwg': bool(v.dwg_path and not v.pdf_path),
                        'file_ext': 'pdf' if v.pdf_path else ('dwg' if v.dwg_path else ''),
                    }
                    for v in versions
                ],
            })

        return jsonify({
            'site_name': project.temp_name,
            'project_no': project.project_no,
            'drawings': drawings_data,
        })


@drawing_bp.route('/drawings/api/drawing/<int:drawing_id>', methods=['DELETE'])
@login_required
def api_delete_drawing(drawing_id):
    """도면 전체(모든 버전) 삭제"""
    if not _can_write_drawings():
        return jsonify({'error': '삭제 권한이 없습니다.'}), 403

    with get_db() as db:
        try:
            drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
            if not drawing:
                return jsonify({'error': '도면을 찾을 수 없습니다.'}), 404

            project_id = drawing.project_id
            drawing_title = drawing.title
            versions = db.query(DrawingVersion).filter_by(drawing_id=drawing_id).all()

            for v in versions:
                file_path = v.pdf_path or v.dwg_path
                if file_path and is_storage_enabled():
                    delete_object(file_path)
                db.delete(v)

            db.delete(drawing)
            append_history_log(db, project_id=project_id, user_name='시스템 🤖',
                               content=f"{session.get('full_name') or '사용자'}님이 도면 삭제: {drawing_title} (버전 {len(versions)}개)",
                               scope='design', kind='system')
            db.commit()
            return jsonify({'ok': True})
        except Exception:
            db.rollback()
            current_app.logger.exception('api_delete_drawing failed drawing=%s', drawing_id)
            return jsonify({'error': '삭제 처리 중 오류가 발생했습니다.'}), 500


@drawing_bp.route('/drawings/api/version/<int:version_id>', methods=['DELETE'])
@login_required
def api_delete_version(version_id):
    if not _can_write_drawings():
        return jsonify({'error': '삭제 권한이 없습니다.'}), 403

    with get_db() as db:
        try:
            version = db.query(DrawingVersion).options(joinedload(DrawingVersion.drawing)).get(version_id)
            if not version:
                return jsonify({'error': '버전을 찾을 수 없습니다.'}), 404

            drawing = version.drawing
            project_id = drawing.project_id
            drawing_title = drawing.title
            deleted_version_no = version.version_no
            file_rel_path = version.pdf_path or version.dwg_path

            if file_rel_path and is_storage_enabled():
                delete_object(file_rel_path)

            db.delete(version)
            db.flush()

            remain_versions = db.query(DrawingVersion).filter_by(drawing_id=drawing.id).all()
            drawing_deleted = False
            if not remain_versions:
                db.delete(drawing)
                drawing_deleted = True
                log_content = (
                    f"{session.get('full_name') or '사용자'}님이 도면 삭제: "
                    f"{drawing_title} (마지막 버전 v{deleted_version_no} 삭제)"
                )
            else:
                latest = (
                    db.query(DrawingVersion)
                    .filter_by(drawing_id=drawing.id)
                    .order_by(DrawingVersion.version_no.desc())
                    .first()
                )
                for v in remain_versions:
                    v.is_latest = (v.id == latest.id)
                drawing.updated_at = datetime.datetime.now()
                log_content = (
                    f"{session.get('full_name') or '사용자'}님이 도면 버전 삭제: "
                    f"{drawing_title} / v{deleted_version_no}"
                )

            append_history_log(
                db,
                project_id=project_id,
                user_name='시스템 🤖',
                content=log_content,
                scope='design',
                kind='system',
            )
            db.commit()
            return jsonify({'ok': True, 'drawing_deleted': drawing_deleted})

        except Exception:
            db.rollback()
            current_app.logger.exception('api_delete_version failed version=%s', version_id)
            return jsonify({'error': '삭제 처리 중 오류가 발생했습니다.'}), 500


# ── AJAX 업로드 ───────────────────────────────────────────────────────

@drawing_bp.route('/drawings/api/upload/<int:project_id>', methods=['POST'])
@login_required
def api_upload_drawing(project_id):
    if not _can_write_drawings():
        return jsonify({'error': '업로드 권한이 없습니다.'}), 403

    file = request.files.get('pdf_file')
    title = (request.form.get('title') or '').strip()
    drawing_type = (request.form.get('drawing_type') or '').strip()
    drawing_id_raw = request.form.get('drawing_id')

    valid, msg = validate_upload(file)
    if not valid:
        return jsonify({'error': msg}), 400

    fname_lower = (file.filename or '').lower()
    is_pdf = fname_lower.endswith('.pdf')
    is_dwg = fname_lower.endswith('.dwg')
    if not (is_pdf or is_dwg):
        return jsonify({'error': 'PDF 또는 DWG 파일만 업로드 가능합니다.'}), 400

    with get_db() as db:
        try:
            project = db.query(Project).get(project_id)
            if not project:
                return jsonify({'error': '현장을 찾을 수 없습니다.'}), 404

            drawing = None
            is_new_drawing = False
            if drawing_id_raw:
                try:
                    did = int(drawing_id_raw)
                    drawing = db.query(Drawing).filter_by(id=did, project_id=project_id).first()
                except (TypeError, ValueError):
                    pass

            if not drawing:
                normalized_type = drawing_type if drawing_type in DRAWING_TYPE_OPTIONS else DRAWING_TYPE_OPTIONS[0]
                auto_title = title or Path(file.filename or '').stem or f'도면_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
                drawing = Drawing(
                    project_id=project_id,
                    title=auto_title,
                    drawing_type=normalized_type,
                    created_by=session.get('full_name'),
                )
                db.add(drawing)
                db.flush()
                is_new_drawing = True

            latest_v = db.query(DrawingVersion).filter_by(drawing_id=drawing.id, is_latest=True).first()
            if latest_v:
                latest_v.is_latest = False
            version_no = (latest_v.version_no + 1) if latest_v else 1

            safe_name = secure_filename(file.filename or '')
            if not safe_name:
                ext = '.pdf' if is_pdf else '.dwg'
                safe_name = f"uploaded_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
            rel_path = str(PurePosixPath(
                'storage', 'drawings',
                f'project_{project_id}', f'drawing_{drawing.id}', f'v{version_no}', safe_name,
            ))

            if not is_storage_enabled():
                return jsonify({'error': 'Storage 설정이 없어 업로드할 수 없습니다.'}), 500

            file_bytes = file.read()
            if not file_bytes:
                return jsonify({'error': '빈 파일입니다.'}), 400

            content_type = 'application/pdf' if is_pdf else 'application/octet-stream'
            ok, err = upload_bytes(rel_path, file_bytes, content_type=content_type, upsert=True)
            if not ok:
                return jsonify({'error': f'Storage 업로드 실패: {err}'}), 500

            version = DrawingVersion(
                drawing_id=drawing.id,
                version_no=version_no,
                dwg_path=rel_path if is_dwg else None,
                pdf_path=rel_path if is_pdf else None,
                convert_status='SUCCESS',
                convert_message='PDF 업로드 완료' if is_pdf else 'DWG 업로드 완료',
                converted_at=datetime.datetime.now(),
                created_by=session.get('full_name'),
                is_latest=True,
            )
            drawing.updated_at = datetime.datetime.now()
            db.add(version)

            file_label = 'PDF' if is_pdf else 'DWG'
            log_content = (
                f"{session.get('full_name') or '사용자'}님이 도면 "
                f"{'신규 등록' if is_new_drawing else '버전 업로드'} ({file_label}): "
                f"{drawing.title} ({drawing.drawing_type}) / v{version_no}"
            )
            append_history_log(db, project_id=project_id, user_name='시스템 🤖',
                               content=log_content, scope='design', kind='system')
            db.commit()

            all_versions = (
                db.query(DrawingVersion)
                .filter_by(drawing_id=drawing.id)
                .order_by(DrawingVersion.version_no.desc())
                .all()
            )
            return jsonify({
                'drawing': {
                    'id': drawing.id,
                    'title': drawing.title,
                    'drawing_type': drawing.drawing_type,
                    'updated_at': drawing.updated_at.strftime('%Y-%m-%d'),
                    'latest_version_id': version.id,
                    'version_count': len(all_versions),
                    'is_new': is_new_drawing,
                    'versions': [
                        {
                            'id': v.id, 'version_no': v.version_no, 'is_latest': v.is_latest,
                            'has_pdf': bool(v.pdf_path), 'has_dwg': bool(v.dwg_path and not v.pdf_path),
                            'file_ext': 'pdf' if v.pdf_path else ('dwg' if v.dwg_path else ''),
                        }
                        for v in all_versions
                    ],
                }
            })

        except Exception:
            db.rollback()
            current_app.logger.exception('api_upload_drawing failed project=%s', project_id)
            return jsonify({'error': '업로드 처리 중 오류가 발생했습니다.'}), 500


# ── 업로드 (form POST, 하위 호환) ─────────────────────────────────────

@drawing_bp.route('/drawings/project/<int:project_id>/upload', methods=['POST'])
@login_required
def upload_drawing(project_id):
    if not _can_write_drawings():
        flash('도면 업로드/수정 권한은 영업부(RW)만 가능합니다.', 'danger')
        return redirect(url_for('drawing.drawings_index', project_id=project_id))

    file = request.files.get('pdf_file')
    title = (request.form.get('title') or '').strip()
    drawing_type = (request.form.get('drawing_type') or '').strip()
    drawing_id_raw = request.form.get('drawing_id')

    valid, msg = validate_upload(file)
    if not valid:
        flash(msg, 'warning')
        return redirect(url_for('drawing.drawings_index', project_id=project_id))

    if not file.filename.lower().endswith('.pdf'):
        flash('PDF 파일만 업로드 가능합니다.', 'warning')
        return redirect(url_for('drawing.drawings_index', project_id=project_id))

    with get_db() as db:
        try:
            project = db.query(Project).get(project_id)
            if not project:
                abort(404)

            drawing = None
            is_new_drawing = False
            if drawing_id_raw:
                try:
                    drawing_id = int(drawing_id_raw)
                except (TypeError, ValueError):
                    drawing_id = None
                if drawing_id:
                    drawing = db.query(Drawing).filter_by(id=drawing_id, project_id=project_id).first()

            if not drawing:
                normalized_type = drawing_type if drawing_type in DRAWING_TYPE_OPTIONS else DRAWING_TYPE_OPTIONS[0]
                auto_title = title or Path(file.filename or '').stem or f'도면_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
                drawing = Drawing(
                    project_id=project_id,
                    contract_item_id=request.form.get('contract_item_id', type=int),
                    title=auto_title,
                    drawing_type=normalized_type,
                    created_by=session.get('full_name'),
                )
                db.add(drawing)
                db.flush()
                is_new_drawing = True

            latest = db.query(DrawingVersion).filter_by(drawing_id=drawing.id, is_latest=True).first()
            if latest:
                latest.is_latest = False
            version_no = (latest.version_no + 1) if latest else 1

            safe_name = secure_filename(file.filename or '')
            if not safe_name or not safe_name.lower().endswith('.pdf'):
                safe_name = f"uploaded_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
            rel_pdf_path = str(PurePosixPath(
                'storage', 'drawings',
                f'project_{project_id}', f'drawing_{drawing.id}', f'v{version_no}', safe_name,
            ))

            if not is_storage_enabled():
                raise RuntimeError("Supabase Storage 설정이 없어 업로드할 수 없습니다.")

            file_bytes = file.read()
            if not file_bytes:
                raise RuntimeError("업로드 파일이 비어 있습니다.")

            ok, err = upload_bytes(rel_pdf_path, file_bytes, content_type='application/pdf', upsert=True)
            if not ok:
                raise RuntimeError(f"Supabase Storage 업로드 실패: {err}")

            version = DrawingVersion(
                drawing_id=drawing.id,
                version_no=version_no,
                dwg_path=rel_pdf_path,
                pdf_path=rel_pdf_path,
                convert_status='SUCCESS',
                convert_message='PDF 업로드 완료',
                converted_at=datetime.datetime.now(),
                created_by=session.get('full_name'),
                is_latest=True,
            )
            drawing.updated_at = datetime.datetime.now()
            db.add(version)

            log_content = (
                f"{session.get('full_name') or '사용자'}님이 도면 {'신규 등록' if is_new_drawing else '버전 업로드'}: "
                f"{drawing.title} ({drawing.drawing_type}) / v{version_no}"
            )
            append_history_log(db, project_id=project_id, user_name='시스템 🤖',
                               content=log_content, scope='design', kind='system')
            db.commit()
            flash(f'PDF 업로드 완료 (v{version_no}).', 'success')
            return redirect(url_for('drawing.drawings_index', project_id=project_id))

        except Exception:
            db.rollback()
            current_app.logger.exception('upload_drawing failed project=%s', project_id)
            flash('업로드 처리 중 오류가 발생했습니다.', 'danger')
            return redirect(url_for('drawing.drawings_index', project_id=project_id))


# ── PDF 서빙 ──────────────────────────────────────────────────────────

@drawing_bp.route('/drawings/version/<int:version_id>/view')
@login_required
def view_pdf(version_id):
    if not _can_read_drawings():
        abort(403)

    with get_db() as db:
        version = db.query(DrawingVersion).get(version_id)
        if not version or not version.pdf_path:
            abort(404)

        _log_access(db, access_type='VIEW')
        db.commit()

        if not is_storage_enabled():
            abort(404)
        data = download_bytes(version.pdf_path)
        if data is None:
            abort(404)
        return send_file(io.BytesIO(data), mimetype='application/pdf')


@drawing_bp.route('/drawings/version/<int:version_id>/download')
@login_required
def download_pdf(version_id):
    if not _can_read_drawings():
        abort(403)

    with get_db() as db:
        version = db.query(DrawingVersion).get(version_id)
        file_path = version.pdf_path if (version and version.pdf_path) else (version.dwg_path if version else None)
        if not file_path:
            abort(404)

        _log_access(db, access_type='DOWNLOAD')
        db.commit()

        if not is_storage_enabled():
            abort(404)
        data = download_bytes(file_path)
        if data is None:
            abort(404)
        file_name = PurePosixPath(file_path).name
        mimetype = 'application/pdf' if file_name.lower().endswith('.pdf') else 'application/octet-stream'
        return send_file(io.BytesIO(data), as_attachment=True, download_name=file_name, mimetype=mimetype)
