"""
입고사진 피드 — 워크보드 스타일 사진 게시판.
간단한 글 + 사진으로 입고 현황 공유.
"""

import datetime
import json
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, send_file, session,
)
import io
from sqlalchemy import desc
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import ReceivingPhotoPost, User
from modules.activity import log_activity

logger = logging.getLogger(__name__)

receiving_photo_bp = Blueprint('receiving_photo', __name__, url_prefix='/receiving-photos')

ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'gif'}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def _parse_photos(raw):
    """photos_json → list. DB가 JSONB면 이미 list, Text면 str."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []


# ===================================================================
# 피드 목록
# ===================================================================
@receiving_photo_bp.route('')
@login_required
@menu_required('receiving_photo')
def feed():
    page = safe_int(request.args.get('page'), 1)
    per_page = 50

    with get_db() as db:
        query = db.query(ReceivingPhotoPost).order_by(desc(ReceivingPhotoPost.created_at))
        total = query.count()
        pagination = make_pagination(page, per_page, total)
        posts = query.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

        feed_items = []
        for p in posts:
            photos = _parse_photos(p.photos_json)
            # 프록시 URL 생성
            for i, photo in enumerate(photos):
                photo['url'] = url_for('receiving_photo.image', post_id=p.id, idx=i)
            feed_items.append({
                'id': p.id,
                'content': p.content,
                'photos': photos,
                'author': p.author.full_name if p.author else '',
                'created_at': p.created_at,
            })

    return render_template(
        'receiving_photos.html',
        posts=feed_items,
        pagination=pagination,
    )


# ===================================================================
# 게시물 등록 (글 + 사진)
# ===================================================================
@receiving_photo_bp.route('/create', methods=['POST'])
@login_required
@menu_required('receiving_photo', write=True)
def create():
    from modules.storage_adapter import upload_bytes, is_storage_enabled

    content = (request.form.get('content') or '').strip()

    if not content:
        flash('내용을 입력해주세요.', 'warning')
        return redirect(url_for('receiving_photo.feed'))

    if not is_storage_enabled():
        flash('스토리지 설정이 없어 사진을 업로드할 수 없습니다.', 'danger')
        return redirect(url_for('receiving_photo.feed'))

    photos = []
    files = request.files.getlist('photos')
    upload_errors = 0

    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else ''
        if ext not in ALLOWED_EXT:
            upload_errors += 1
            continue

        file_content = f.read()
        if len(file_content) > MAX_FILE_SIZE:
            upload_errors += 1
            continue

        safe_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
        object_path = f'storage/receiving-photos/{safe_name}'

        ok, msg = upload_bytes(object_path, file_content, f.content_type or 'image/jpeg')
        if ok:
            photos.append({
                'file_name': f.filename,
                'file_path': object_path,
                'file_size': len(file_content),
            })
        else:
            logger.error('입고사진 업로드 실패: %s — %s', f.filename, msg)
            upload_errors += 1

    if not photos and not upload_errors:
        flash('사진을 1장 이상 첨부해주세요.', 'warning')
        return redirect(url_for('receiving_photo.feed'))

    if not photos and upload_errors:
        flash(f'사진 {upload_errors}장 업로드에 실패했습니다. 파일 형식(jpg/png/gif)과 크기(20MB)를 확인해주세요.', 'danger')
        return redirect(url_for('receiving_photo.feed'))

    with get_db() as db:
        post = ReceivingPhotoPost(
            content=content,
            photos_json=json.dumps(photos, ensure_ascii=False),
            created_by=session.get('user_id'),
        )
        db.add(post)
        db.commit()

        log_activity(db, '입고사진', 'create',
                     f'입고사진 등록: {content[:30]}',
                     ref_type='ReceivingPhoto', ref_id=post.id)
        db.commit()

    msg = f'입고사진 {len(photos)}장이 등록되었습니다.'
    if upload_errors:
        msg += f' ({upload_errors}장 실패)'
    flash(msg, 'success' if not upload_errors else 'warning')
    return redirect(url_for('receiving_photo.feed'))


# ===================================================================
# 게시물 삭제
# ===================================================================
@receiving_photo_bp.route('/<int:post_id>/delete', methods=['POST'])
@login_required
@menu_required('receiving_photo', write=True)
def delete(post_id):
    from modules.storage_adapter import delete_object

    with get_db() as db:
        post = db.query(ReceivingPhotoPost).get(post_id)
        if not post:
            flash('게시물을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('receiving_photo.feed'))

        # 본인 또는 admin만 삭제 가능
        if post.created_by != session.get('user_id') and session.get('role') != 'admin':
            flash('삭제 권한이 없습니다.', 'danger')
            return redirect(url_for('receiving_photo.feed'))

        # 스토리지 파일 삭제
        for photo in _parse_photos(post.photos_json):
            try:
                delete_object(photo.get('file_path', ''))
            except Exception:
                pass

        db.delete(post)
        db.commit()

    flash('삭제되었습니다.', 'success')
    return redirect(url_for('receiving_photo.feed'))


# ===================================================================
# 사진 이미지 서빙 (Supabase Storage 프록시 + 브라우저 캐시)
# ===================================================================
@receiving_photo_bp.route('/image/<int:post_id>/<int:idx>')
@login_required
def image(post_id, idx):
    from modules.storage_adapter import download_bytes
    from flask import make_response

    with get_db() as db:
        post = db.query(ReceivingPhotoPost).get(post_id)
        if not post:
            return '', 404

        photos = _parse_photos(post.photos_json)

        if idx < 0 or idx >= len(photos):
            return '', 404

        photo = photos[idx]
        content = download_bytes(photo.get('file_path', ''))
        if content is None:
            return '', 404

        ext = photo.get('file_name', '').rsplit('.', 1)[-1].lower()
        mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif'}.get(ext, 'image/jpeg')

        resp = make_response(send_file(io.BytesIO(content), mimetype=mime))
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

