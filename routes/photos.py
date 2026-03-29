import io
import os
import datetime
import zipfile

from flask import Blueprint, render_template, request, jsonify, session, abort, Response
from sqlalchemy import func
from werkzeug.utils import secure_filename

from modules.auth_decorators import login_required, menu_required
from modules.db_context import get_db
from modules.models import Project, Contract, ContractItem, ProjectPhoto
from modules.storage_adapter import upload_bytes, download_bytes, delete_object

photos_bp = Blueprint('photos', __name__, url_prefix='/photos')

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'heic'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── 페이지 라우트 ──────────────────────────────────────────────────────

@photos_bp.route('')
@photos_bp.route('/project/<int:project_id>')
@login_required
def photo_list(project_id=None):
    with get_db() as db:
        from modules.contract_filters import DONE_STATUSES
        status_filter = request.args.get('status', 'active')

        q = (
            db.query(
                Project.id,
                Project.project_no,
                Project.temp_name.label('site_name'),
                func.count(ProjectPhoto.id).label('photo_count'),
            )
            .outerjoin(ProjectPhoto, ProjectPhoto.project_id == Project.id)
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

        sites = q.group_by(Project.id).order_by(Project.id.desc()).all()

        selected = None
        if project_id:
            selected = db.query(Project).filter(Project.id == project_id).first()
            if not selected:
                abort(404)
        elif sites:
            selected = db.query(Project).filter(Project.id == sites[0].id).first()
            if selected:
                project_id = selected.id

        return render_template(
            'photo_gallery.html',
            sites=sites,
            selected=selected,
            selected_id=project_id,
            status_filter=status_filter,
        )


# ── Ajax API ───────────────────────────────────────────────────────────

@photos_bp.route('/api/site/<int:project_id>')
@login_required
def api_site(project_id):
    with get_db() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return jsonify({'error': '현장 없음'}), 404

        contracts = (
            db.query(Contract)
            .filter(Contract.project_id == project_id)
            .order_by(Contract.id)
            .all()
        )
        contracts_data = []
        for c in contracts:
            items = (
                db.query(ContractItem)
                .filter(ContractItem.contract_id == c.id)
                .all()
            )
            contracts_data.append({
                'id': c.id,
                'contract_name': c.contract_name,
                'contract_no': c.g2b_contract_no,
                'items': [{'item_name': f"{r.category} {r.model_name or ''}".strip(), 'qty': r.quantity} for r in items],
            })

        return jsonify({
            'site_name': project.temp_name,
            'project_no': project.project_no,
            'contracts': contracts_data,
        })


@photos_bp.route('/api/photos')
@login_required
def api_photos():
    site_id = request.args.get('site_id', type=int)
    photo_type = request.args.get('photo_type')
    if not site_id:
        return jsonify({'error': 'site_id 필요'}), 400

    with get_db() as db:
        q = db.query(ProjectPhoto).filter(ProjectPhoto.project_id == site_id)
        if photo_type and photo_type != '전체':
            q = q.filter(ProjectPhoto.photo_type == photo_type)
        photos = q.order_by(ProjectPhoto.created_at.desc()).all()

        return jsonify({'photos': [{
            'id':          p.id,
            'url':         f'/photos/{p.id}/view',
            'photo_type':  p.photo_type,
            'contract_id': p.contract_id,
            'uploaded_at': p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '',
            'uploaded_by': p.uploaded_by or '',
            'file_name':   p.file_name,
        } for p in photos]})


@photos_bp.route('/api/upload', methods=['POST'])
@login_required
@menu_required('photos')
def api_upload():
    file = request.files.get('file')
    site_id = request.form.get('site_id', type=int)
    photo_type = request.form.get('photo_type', '설계')
    contract_id = request.form.get('contract_id', type=int) or None

    if not file or not site_id:
        return jsonify({'error': '파일과 현장 ID가 필요합니다'}), 400
    if not _allowed(file.filename):
        return jsonify({'error': '지원하지 않는 파일 형식입니다'}), 400

    data = file.read()
    if len(data) > MAX_FILE_SIZE:
        return jsonify({'error': '파일 크기는 10MB 이하여야 합니다'}), 400

    ext = os.path.splitext(secure_filename(file.filename))[1].lower() or '.jpg'
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    storage_path = f"storage/photos/project_{site_id}/{ts}{ext}"

    ok, err = upload_bytes(storage_path, data, file.mimetype or 'image/jpeg')
    if not ok:
        return jsonify({'error': err}), 500

    from modules.history_board import get_user_display_name
    current_user = get_user_display_name()
    with get_db() as db:
        photo = ProjectPhoto(
            project_id=site_id,
            contract_id=contract_id,
            photo_type=photo_type,
            file_name=secure_filename(file.filename),
            storage_path=storage_path,
            uploaded_by=current_user,
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)

        return jsonify({'photo': {
            'id':          photo.id,
            'url':         f'/photos/{photo.id}/view',
            'photo_type':  photo.photo_type,
            'contract_id': photo.contract_id,
            'uploaded_at': photo.created_at.strftime('%Y-%m-%d %H:%M'),
            'uploaded_by': photo.uploaded_by,
            'file_name':   photo.file_name,
        }})


@photos_bp.route('/api/photos/<int:photo_id>', methods=['DELETE'])
@login_required
@menu_required('photos')
def api_delete(photo_id):
    with get_db() as db:
        photo = db.query(ProjectPhoto).filter(ProjectPhoto.id == photo_id).first()
        if not photo:
            return jsonify({'error': '사진 없음'}), 404
        delete_object(photo.storage_path)
        db.delete(photo)
        db.commit()
    return jsonify({'ok': True})


@photos_bp.route('/api/download', methods=['POST'])
@login_required
@menu_required('photos')
def api_download():
    photo_ids = request.json.get('ids', []) if request.is_json else []
    if not photo_ids:
        return jsonify({'error': 'ids 필요'}), 400

    buf = io.BytesIO()
    with get_db() as db:
        photos = db.query(ProjectPhoto).filter(ProjectPhoto.id.in_(photo_ids)).all()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            seen = {}
            for p in photos:
                data = download_bytes(p.storage_path)
                if not data:
                    continue
                name = p.file_name or f'photo_{p.id}.jpg'
                # 중복 파일명 처리
                if name in seen:
                    seen[name] += 1
                    base, ext = os.path.splitext(name)
                    name = f"{base}_{seen[name]}{ext}"
                else:
                    seen[name] = 0
                zf.writestr(name, data)

    buf.seek(0)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return Response(
        buf.read(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename="photos_{ts}.zip"'}
    )


@photos_bp.route('/<int:photo_id>/view')
@login_required
def photo_view(photo_id):
    with get_db() as db:
        photo = db.query(ProjectPhoto).filter(ProjectPhoto.id == photo_id).first()
        if not photo:
            abort(404)
        data = download_bytes(photo.storage_path)
        if not data:
            abort(404)
        ext = os.path.splitext(photo.file_name)[1].lower().lstrip('.')
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                    'webp': 'image/webp', 'heic': 'image/heic'}
        mime = mime_map.get(ext, 'image/jpeg')
        return Response(data, mimetype=mime)
