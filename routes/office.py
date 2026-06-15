"""오피스 — ONLYOFFICE 기반 문서 편집기 (구글 독스 대용)."""

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import logging
import zipfile
from urllib.parse import quote

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, abort, Response
from modules.auth_decorators import login_required
from modules.storage_adapter import upload_bytes, download_bytes, delete_object, get_storage_config

log = logging.getLogger(__name__)

office_bp = Blueprint('office', __name__)

PREFIX_SHARED = 'documents/office/shared/'
PREFIX_PRIVATE = 'documents/office/private/'

FILE_TYPE_MAP = {
    'xlsx': 'cell', 'xls': 'cell', 'csv': 'cell', 'ods': 'cell',
    'docx': 'word', 'doc': 'word', 'odt': 'word', 'txt': 'word', 'rtf': 'word',
    'pptx': 'slide', 'ppt': 'slide', 'odp': 'slide',
    'pdf': 'pdf',
}

MIME_MAP = {
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'xls': 'application/vnd.ms-excel',
    'csv': 'text/csv',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'doc': 'application/msword',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'ppt': 'application/vnd.ms-powerpoint',
    'pdf': 'application/pdf',
}


# ── 경로 헬퍼 ──

def _get_prefix(scope: str) -> str:
    if scope == 'private':
        uid = session.get('user_id', 'unknown')
        return f'{PREFIX_PRIVATE}{uid}/'
    return PREFIX_SHARED


def _get_index_path(scope: str) -> str:
    if scope == 'private':
        uid = session.get('user_id', 'unknown')
        return f'{PREFIX_PRIVATE}{uid}/_index.json'
    return f'{PREFIX_SHARED}_index.json'


# ── 인덱스 관리 ──

def _load_index(scope: str) -> dict:
    data = download_bytes(_get_index_path(scope))
    if data:
        try:
            return json.loads(data)
        except Exception:
            pass
    return {}


def _save_index(scope: str, index: dict):
    content = json.dumps(index, ensure_ascii=False, indent=2).encode('utf-8')
    upload_bytes(_get_index_path(scope), content, content_type='application/json')


def _add_to_index(scope: str, storage_name: str, title: str, ext: str, size: int = 0):
    idx = _load_index(scope)
    now = time.strftime('%Y-%m-%dT%H:%M')
    idx[storage_name] = {
        'title': title,
        'ext': ext,
        'size': size,
        'created': now,
        'updated': now,
        'user': session.get('full_name', ''),
        'user_id': session.get('user_id', ''),
    }
    _save_index(scope, idx)


def _remove_from_index(scope: str, storage_name: str):
    idx = _load_index(scope)
    idx.pop(storage_name, None)
    _save_index(scope, idx)


# ── Supabase 서명 URL ──

def _signed_url(object_path: str) -> str:
    cfg = get_storage_config()
    obj = quote(object_path.replace("\\", "/").lstrip("/"), safe="/")
    import requests
    url = f"{cfg['url']}/storage/v1/object/sign/{cfg['bucket']}/{obj}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json={"expiresIn": 3600}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        signed = data.get("signedURL", "")
        if signed:
            return f"{cfg['url']}/storage/v1{signed}"
    return ""


def _file_url_for_onlyoffice(object_path: str) -> str:
    signed = _signed_url(object_path)
    cb = int(time.time() * 1000)
    if signed:
        sep = '&' if '?' in signed else '?'
        return f"{signed}{sep}_cb={cb}"
    cfg = get_storage_config()
    obj = quote(object_path.replace("\\", "/").lstrip("/"), safe="/")
    return f"{cfg['url']}/storage/v1/object/public/{cfg['bucket']}/{obj}?_cb={cb}"


# ── 파일 목록 빌드 ──

def _build_file_list(scope: str) -> list:
    index = _load_index(scope)

    file_list = []
    for storage_name, meta in index.items():
        ext = meta.get('ext', '')
        file_list.append({
            'storage_name': storage_name,
            'title': meta.get('title', storage_name),
            'ext': ext,
            'doc_type': FILE_TYPE_MAP.get(ext, 'word'),
            'size': meta.get('size', 0),
            'updated': meta.get('updated', meta.get('created', '')),
            'user': meta.get('user', ''),
            'scope': scope,
        })

    file_list.sort(key=lambda x: x['updated'], reverse=True)
    return file_list


# ── 빈 파일 생성 ──

def _create_empty_file(doc_type: str) -> bytes:
    if doc_type == 'xlsx':
        from openpyxl import Workbook
        wb = Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    elif doc_type == 'docx':
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>')
            zf.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '</Relationships>')
            zf.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t></w:t></w:r></w:p></w:body></w:document>')
        return buf.getvalue()
    elif doc_type == 'pptx':
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                '</Types>')
            zf.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
                '</Relationships>')
            zf.writestr('ppt/presentation.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
                ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldMasterIdLst/><p:sldSz cx="12192000" cy="6858000"/>'
                '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
        return buf.getvalue()
    return b''


# ── 라우트 ──

@office_bp.route('/office')
@office_bp.route('/office/tab/<scope>')
@login_required
def office_list(scope='shared'):
    """파일 목록 — 페이지만 렌더, 파일은 AJAX로."""
    if scope not in ('shared', 'private'):
        scope = 'shared'
    return render_template('office_list.html', current_scope=scope)


@office_bp.route('/office/api/files/<scope>')
@login_required
def office_api_files(scope):
    """AJAX용 파일 목록 JSON."""
    if scope not in ('shared', 'private'):
        return jsonify([])
    files = _build_file_list(scope)
    return jsonify(files)


LEGACY_CONVERT_MAP = {'xls': 'xlsx', 'doc': 'docx', 'ppt': 'pptx'}


def _convert_legacy(content: bytes, src_ext: str, dst_ext: str) -> bytes | None:
    """구식 Office 포맷(xls/doc/ppt)을 OOXML(xlsx/docx/pptx)로 변환.
    ONLYOFFICE 8.x는 구식 포맷 저장 시 세션 트래킹을 잃는 이슈가 있어 업로드 시점에 변환.
    gunicorn 워커가 ~/.config/libreoffice 프로필을 공유하면 동시 실행 시 락 충돌이 나므로
    -env:UserInstallation 으로 호출별 임시 프로필을 사용한다."""
    bin_path = (shutil.which('libreoffice') or shutil.which('soffice')
                or next((p for p in ('/usr/bin/libreoffice', '/usr/bin/soffice',
                                     '/usr/local/bin/libreoffice', '/usr/local/bin/soffice')
                         if os.path.isfile(p) and os.access(p, os.X_OK)), None))
    if not bin_path:
        log.error("libreoffice/soffice 실행파일을 찾을 수 없음 (PATH=%s)", os.environ.get('PATH', ''))
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, f'in.{src_ext}')
        with open(src, 'wb') as f:
            f.write(content)
        profile_dir = os.path.join(tmp, 'lo_profile')
        user_install = f'-env:UserInstallation=file://{profile_dir}'
        # systemd PATH가 venv만 포함하므로 libreoffice 래퍼 스크립트가 dirname/sed/grep 등을
        # 못 찾는다. subprocess에 표준 PATH를 명시 주입.
        env = os.environ.copy()
        env['PATH'] = '/usr/bin:/bin:/usr/local/bin:' + env.get('PATH', '')
        env.setdefault('HOME', '/tmp')
        try:
            result = subprocess.run(
                [bin_path, user_install, '--headless', '--norestore', '--nofirststartwizard',
                 '--convert-to', dst_ext, '--outdir', tmp, src],
                capture_output=True, timeout=180, env=env,
            )
        except subprocess.TimeoutExpired as e:
            log.error("libreoffice 변환 타임아웃 (%s→%s): %s", src_ext, dst_ext, e)
            return None
        if result.returncode != 0:
            log.error("libreoffice 변환 실패 (%s→%s) rc=%d stdout=%s stderr=%s",
                      src_ext, dst_ext, result.returncode,
                      result.stdout.decode('utf-8', 'replace')[:500],
                      result.stderr.decode('utf-8', 'replace')[:500])
            return None
        out = os.path.join(tmp, f'in.{dst_ext}')
        if not os.path.exists(out):
            log.error("libreoffice 변환 산출물 없음 (%s→%s) stdout=%s stderr=%s",
                      src_ext, dst_ext,
                      result.stdout.decode('utf-8', 'replace')[:500],
                      result.stderr.decode('utf-8', 'replace')[:500])
            return None
        with open(out, 'rb') as f:
            return f.read()


@office_bp.route('/office/upload', methods=['POST'])
@login_required
def office_upload():
    """파일 업로드 — 구식 포맷(xls/doc/ppt)은 자동으로 OOXML로 변환."""
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': '파일을 선택해주세요'}), 400

    scope = request.form.get('scope', 'shared')
    if scope not in ('shared', 'private'):
        scope = 'shared'

    original = file.filename.strip()
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in FILE_TYPE_MAP:
        return jsonify({'error': f'지원하지 않는 파일 형식입니다: .{ext}'}), 400

    title = original.rsplit('.', 1)[0] if '.' in original else original
    content = file.read()

    if ext in LEGACY_CONVERT_MAP:
        dst_ext = LEGACY_CONVERT_MAP[ext]
        converted = _convert_legacy(content, ext, dst_ext)
        if converted:
            log.info("Office legacy convert: %s (%d) → %s (%d)", ext, len(content), dst_ext, len(converted))
            content = converted
            ext = dst_ext
        else:
            return jsonify({'error': f'.{ext} 파일을 .{dst_ext}로 변환하지 못했습니다. .{dst_ext}로 저장 후 다시 업로드해주세요.'}), 500

    storage_name = f'{uuid.uuid4().hex[:12]}.{ext}'
    prefix = _get_prefix(scope)
    storage_path = f'{prefix}{storage_name}'

    mime = MIME_MAP.get(ext, 'application/octet-stream')
    ok, msg = upload_bytes(storage_path, content, content_type=mime)
    if not ok:
        return jsonify({'error': f'업로드 실패: {msg}'}), 500

    _add_to_index(scope, storage_name, title, ext, size=len(content))
    log.info("Office upload [%s]: %s → %s by %s", scope, original, storage_name, session.get('user_id'))
    return jsonify({'success': True, 'storage_name': storage_name, 'title': title})


@office_bp.route('/office/new', methods=['POST'])
@login_required
def office_new():
    """새 빈 문서 생성."""
    doc_type = request.form.get('type', 'xlsx')
    title = request.form.get('title', '').strip()
    scope = request.form.get('scope', 'shared')

    if doc_type not in ('xlsx', 'docx', 'pptx'):
        return jsonify({'error': '지원하지 않는 문서 타입'}), 400
    if scope not in ('shared', 'private'):
        scope = 'shared'
    if not title:
        title = f'새 문서_{int(time.time())}'

    content = _create_empty_file(doc_type)
    if not content:
        return jsonify({'error': '파일 생성 실패'}), 500

    storage_name = f'{uuid.uuid4().hex[:12]}.{doc_type}'
    prefix = _get_prefix(scope)
    storage_path = f'{prefix}{storage_name}'
    mime = MIME_MAP.get(doc_type, 'application/octet-stream')
    ok, msg = upload_bytes(storage_path, content, content_type=mime)
    if not ok:
        return jsonify({'error': f'생성 실패: {msg}'}), 500

    _add_to_index(scope, storage_name, title, doc_type)
    log.info("Office new [%s]: %s (%s) by %s", scope, title, storage_name, session.get('user_id'))
    return jsonify({'success': True, 'storage_name': storage_name, 'title': title, 'scope': scope})


@office_bp.route('/office/edit/<scope>/<storage_name>')
@login_required
def office_edit(scope, storage_name):
    """ONLYOFFICE 에디터 열기."""
    if scope not in ('shared', 'private'):
        abort(400)

    ext = storage_name.rsplit('.', 1)[-1].lower() if '.' in storage_name else ''
    doc_type = FILE_TYPE_MAP.get(ext)
    if not doc_type:
        abort(400, '지원하지 않는 파일 형식')

    index = _load_index(scope)
    meta = index.get(storage_name, {})
    display_title = meta.get('title', storage_name)
    display_title_ext = f'{display_title}.{ext}' if ext else display_title

    prefix = _get_prefix(scope)
    storage_path = f'{prefix}{storage_name}'
    if not download_bytes(storage_path):
        abort(404, '파일을 찾을 수 없습니다')

    doc_key = f'office_{uuid.uuid4().hex[:16]}'
    cb = int(time.time() * 1000)
    uid = session.get('user_id', '')
    file_url = f'http://host.internal:8501/office/raw/{scope}/{storage_name}?uid={uid}&_cb={cb}'
    callback_url = f'http://host.internal:8501/api/onlyoffice/callback?office_scope={scope}&office_file={storage_name}'
    if scope == 'private':
        callback_url += f'&office_uid={uid}'

    user_name = session.get('full_name', '사용자')
    is_pdf = (ext == 'pdf')

    return render_template('office_editor.html',
                           filename=display_title_ext,
                           storage_name=storage_name,
                           scope=scope,
                           file_url=file_url,
                           doc_type=doc_type,
                           doc_key=doc_key,
                           callback_url=callback_url,
                           user_name=user_name,
                           is_pdf=is_pdf,
                           ext=ext)


@office_bp.route('/office/delete/<scope>/<storage_name>', methods=['POST'])
@login_required
def office_delete(scope, storage_name):
    """파일 삭제."""
    if scope not in ('shared', 'private'):
        abort(400)
    prefix = _get_prefix(scope)
    storage_path = f'{prefix}{storage_name}'
    ok = delete_object(storage_path)
    if ok:
        _remove_from_index(scope, storage_name)
        log.info("Office delete [%s]: %s by %s", scope, storage_name, session.get('user_id'))
        return jsonify({'success': True})
    return jsonify({'error': '삭제 실패'}), 500


@office_bp.route('/office/download/<scope>/<storage_name>')
@login_required
def office_download(scope, storage_name):
    """파일 다운로드."""
    if scope not in ('shared', 'private'):
        abort(400)
    prefix = _get_prefix(scope)
    storage_path = f'{prefix}{storage_name}'
    signed = _signed_url(storage_path)
    if signed:
        return redirect(signed)
    abort(404)


@office_bp.route('/office/raw/<scope>/<storage_name>')
def office_raw(scope, storage_name):
    """ONLYOFFICE 전용 직접 파일 서빙 — CDN 캐시 우회.
    host.internal 경유이므로 외부 노출 없음. uid 파라미터로 private 스코프 처리."""
    if scope not in ('shared', 'private'):
        abort(400)
    if scope == 'private':
        uid = request.args.get('uid', '')
        if not uid:
            abort(400)
        prefix = f'{PREFIX_PRIVATE}{uid}/'
    else:
        prefix = PREFIX_SHARED
    storage_path = f'{prefix}{storage_name}'
    data = download_bytes(storage_path)
    if not data:
        abort(404)
    ext = storage_name.rsplit('.', 1)[-1].lower() if '.' in storage_name else ''
    mime = MIME_MAP.get(ext, 'application/octet-stream')
    return Response(data, mimetype=mime, headers={
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
    })
