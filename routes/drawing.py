import datetime
import io
import traceback
from pathlib import Path, PurePosixPath
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, abort
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload
from modules.db_context import get_db
from modules.utils import validate_upload
from modules.models import (
    Project,
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


def _safe_next_url(default_endpoint: str, **default_kwargs):
    from urllib.parse import urlparse
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    if next_url:
        parsed = urlparse(next_url)
        if not parsed.scheme and not parsed.netloc and next_url.startswith('/'):
            return next_url
    return url_for(default_endpoint, **default_kwargs)


def _log_access(db, access_type='VIEW'):
    db.add(DrawingAccessLog(
        share_link_id=None,
        user_id=session.get('user_id'),
        access_type=access_type,
        ip_address=request.remote_addr,
        user_agent=(request.headers.get('User-Agent') or '')[:500],
    ))


@drawing_bp.route('/drawings')
def drawings_index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_read_drawings():
        flash('도면 열람 권한이 없습니다.', 'danger')
        return redirect(url_for('dashboard.dashboard_view'))

    with get_db() as db:
        projects = db.query(Project).options(joinedload(Project.drawings)).order_by(Project.id.desc()).all()
        return render_template('drawings_index.html', projects=projects)


@drawing_bp.route('/drawings/project/<int:project_id>')
def drawings_project(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_read_drawings():
        flash('도면 열람 권한이 없습니다.', 'danger')
        return redirect(url_for('dashboard.dashboard_view'))

    with get_db() as db:
        project = db.query(Project).options(
            joinedload(Project.drawings).joinedload(Drawing.versions)
        ).get(project_id)
        if not project:
            abort(404)

        contract_item_id = request.args.get('contract_item_id', type=int)
        drawings = list(project.drawings)
        if contract_item_id:
            drawings = [d for d in drawings if d.contract_item_id == contract_item_id]
        drawings = sorted(drawings, key=lambda d: d.updated_at or d.created_at, reverse=True)
        return render_template(
            'drawings_project.html',
            project=project,
            drawings=drawings,
            drawing_type_options=DRAWING_TYPE_OPTIONS,
            can_write=_can_write_drawings()
        )


@drawing_bp.route('/drawings/project/<int:project_id>/upload', methods=['POST'])
def upload_drawing(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_write_drawings():
        flash('도면 업로드/수정 권한은 영업부(RW)만 가능합니다.', 'danger')
        return redirect(_safe_next_url('drawing.drawings_project', project_id=project_id))

    file = request.files.get('pdf_file')
    title = (request.form.get('title') or '').strip()
    drawing_type = (request.form.get('drawing_type') or '').strip()
    drawing_id_raw = request.form.get('drawing_id')

    valid, msg = validate_upload(file)
    if not valid:
        flash(msg, 'warning')
        return redirect(_safe_next_url('drawing.drawings_project', project_id=project_id))

    if not file.filename.lower().endswith('.pdf'):
        flash('PDF 파일만 업로드 가능합니다.', 'warning')
        return redirect(url_for('drawing.drawings_project', project_id=project_id))

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
                # 신규 등록 시 입력 누락이 있어도 업로드 자체는 진행되도록 자동 보정
                normalized_type = drawing_type if drawing_type in DRAWING_TYPE_OPTIONS else DRAWING_TYPE_OPTIONS[0]
                auto_title = title or Path(file.filename or '').stem or f'도면_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'

                drawing = Drawing(
                    project_id=project_id,
                    contract_item_id=request.form.get('contract_item_id', type=int),
                    title=auto_title,
                    drawing_type=normalized_type,
                    created_by=session.get('full_name')
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
                'storage',
                'drawings',
                f'project_{project_id}',
                f'drawing_{drawing.id}',
                f'v{version_no}',
                safe_name,
            ))

            # Supabase Storage only: 설정 없으면 업로드 불가 처리
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
                # 하위 호환을 위해 dwg_path 컬럼도 동일 경로를 저장
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
            if is_new_drawing:
                log_content = (
                    f"{session.get('full_name') or '사용자'}님이 도면 신규 등록: "
                    f"{drawing.title} ({drawing.drawing_type}) / v{version_no}"
                )
            else:
                log_content = (
                    f"{session.get('full_name') or '사용자'}님이 도면 버전 업로드: "
                    f"{drawing.title} / v{version_no}"
                )
            append_history_log(
                db,
                project_id=project_id,
                user_name='시스템 🤖',
                content=log_content,
                scope='drawing',
                kind='system'
            )
            db.commit()
            flash(f'PDF 업로드 완료 (v{version_no}).', 'success')
            return redirect(_safe_next_url('drawing.drawings_project', project_id=project_id))
        except Exception as e:
            db.rollback()
            print('[upload_drawing] ERROR:', traceback.format_exc())
            flash(f'업로드 오류: {str(e)}', 'danger')
            return redirect(url_for('drawing.drawings_project', project_id=project_id))


@drawing_bp.route('/drawings/version/<int:version_id>/view')
def view_pdf(version_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_read_drawings():
        abort(403)

    with get_db() as db:
        version = db.query(DrawingVersion).get(version_id)
        if not version or not version.pdf_path:
            abort(404)

        _log_access(db, access_type='VIEW')
        db.commit()

        # Supabase Storage only
        if not (version.pdf_path and is_storage_enabled()):
            abort(404)
        data = download_bytes(version.pdf_path)
        if data is None:
            abort(404)
        return send_file(io.BytesIO(data), mimetype='application/pdf')


@drawing_bp.route('/drawings/version/<int:version_id>/download')
def download_pdf(version_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_read_drawings():
        abort(403)

    with get_db() as db:
        version = db.query(DrawingVersion).get(version_id)
        if not version or not version.pdf_path:
            abort(404)

        _log_access(db, access_type='DOWNLOAD')
        db.commit()

        # Supabase Storage only
        if not (version.pdf_path and is_storage_enabled()):
            abort(404)
        data = download_bytes(version.pdf_path)
        if data is None:
            abort(404)
        file_name = PurePosixPath(version.pdf_path).name
        return send_file(io.BytesIO(data), as_attachment=True, download_name=file_name, mimetype='application/pdf')


@drawing_bp.route('/drawings/version/<int:version_id>/delete', methods=['POST'])
def delete_drawing_version(version_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_write_drawings():
        flash('도면 삭제 권한은 영업부/관리자만 가능합니다.', 'danger')
        return redirect(_safe_next_url('drawing.drawings_index'))

    with get_db() as db:
        try:
            version = db.query(DrawingVersion).options(joinedload(DrawingVersion.drawing)).get(version_id)
            if not version:
                abort(404)

            drawing = version.drawing
            project_id = drawing.project_id
            drawing_title = drawing.title
            deleted_version_no = version.version_no
            file_rel_path = version.pdf_path or version.dwg_path

            # 파일 삭제 시도 (실패해도 DB 정리는 진행)
            if file_rel_path:
                # Supabase Storage 삭제
                if is_storage_enabled():
                    delete_object(file_rel_path)

            db.delete(version)
            db.flush()

            remain_versions = db.query(DrawingVersion).filter_by(drawing_id=drawing.id).all()
            if not remain_versions:
                db.delete(drawing)
                log_content = (
                    f"{session.get('full_name') or '사용자'}님이 도면 삭제: "
                    f"{drawing_title} (마지막 버전 v{deleted_version_no} 삭제)"
                )
            else:
                latest = db.query(DrawingVersion).filter_by(drawing_id=drawing.id).order_by(DrawingVersion.version_no.desc()).first()
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
                scope='drawing',
                kind='system'
            )

            db.commit()
            flash('도면(버전) 삭제가 완료되었습니다.', 'success')
            return redirect(_safe_next_url('drawing.drawings_project', project_id=project_id))
        except Exception as e:
            db.rollback()
            flash(f'삭제 오류: {str(e)}', 'danger')
            return redirect(_safe_next_url('drawing.drawings_index'))











