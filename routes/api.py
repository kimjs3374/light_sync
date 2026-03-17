"""
NAS 폴더 동기화 API
- 시놀로지 NAS에서 새 폴더 감지 시 호출
- 폴더명 패턴: YYYY.MM.DD_현장명
"""
import datetime
import os
import re

from flask import Blueprint, current_app, jsonify, request
from flask_wtf.csrf import CSRFProtect

from modules.db_context import get_db
from modules.models import Project

api_bp = Blueprint('api', __name__, url_prefix='/api')

NAS_API_KEY = os.environ.get('NAS_SYNC_API_KEY', '')

# 폴더명 패턴: YYYY.MM.DD_현장명
FOLDER_PATTERN = re.compile(
    r'^(\d{4})\.(\d{2})\.(\d{2})_(.+)$'
)


def _check_api_key():
    """API 키 검증"""
    if not NAS_API_KEY:
        return False, 'NAS_SYNC_API_KEY가 서버에 설정되지 않았습니다.'
    auth = request.headers.get('X-API-Key', '')
    if auth != NAS_API_KEY:
        return False, '유효하지 않은 API 키입니다.'
    return True, ''


def _parse_folder_name(folder_name):
    """폴더명에서 날짜와 현장명 추출"""
    m = FOLDER_PATTERN.match(folder_name.strip())
    if not m:
        return None
    year, month, day, site_name = m.groups()
    try:
        folder_date = datetime.date(int(year), int(month), int(day))
    except ValueError:
        return None
    return {
        'folder_date': folder_date,
        'site_name': site_name.strip(),
        'folder_name': folder_name.strip(),
    }


@api_bp.route('/sync_nas_folders', methods=['POST'])
def sync_nas_folders():
    """
    NAS 폴더 목록을 받아 미등록 현장을 자동 생성.

    Request JSON:
        {
            "folders": ["2026.03.03_울산공항 계류장", ...],
            "year": "2026"  (optional, 기본값: 올해)
        }

    Response JSON:
        {
            "ok": true,
            "created": [...],
            "skipped": [...],
            "errors": [...]
        }
    """
    # API 키 검증
    ok, err_msg = _check_api_key()
    if not ok:
        return jsonify({'ok': False, 'error': err_msg}), 401

    data = request.get_json(silent=True)
    if not data or 'folders' not in data:
        return jsonify({'ok': False, 'error': 'folders 필드가 필요합니다.'}), 400

    folders = data['folders']
    if not isinstance(folders, list):
        return jsonify({'ok': False, 'error': 'folders는 배열이어야 합니다.'}), 400

    year = str(data.get('year', datetime.date.today().year))

    created = []
    skipped = []
    errors = []

    with get_db() as db:
        # 기존 work_path 목록 로드 (중복 체크용)
        existing_paths = set()
        all_projects = db.query(Project.work_path).filter(
            Project.work_path.isnot(None)
        ).all()
        for (wp,) in all_projects:
            if wp:
                existing_paths.add(wp.strip())

        # 현재 연도 프로젝트 번호 카운트
        count = db.query(Project).filter(
            Project.project_no.like(f"{year}-%")
        ).count()

        for folder_name in folders:
            parsed = _parse_folder_name(folder_name)
            if not parsed:
                errors.append({
                    'folder': folder_name,
                    'reason': '폴더명 패턴 불일치 (YYYY.MM.DD_현장명)'
                })
                continue

            # work_path 기준으로 중복 체크
            nas_path = f"/volume1/현장관리/000. 현장관리/{year}/{folder_name}"
            if nas_path in existing_paths:
                skipped.append({
                    'folder': folder_name,
                    'reason': '이미 등록된 현장'
                })
                continue

            # 새 프로젝트 생성 (생성일 = 폴더명의 날짜)
            count += 1
            folder_dt = datetime.datetime.combine(parsed['folder_date'], datetime.time())
            new_project = Project(
                project_no=f"{year}-{count:03d}",
                temp_name=parsed['site_name'],
                work_path=nas_path,
                created_at=folder_dt,
            )
            db.add(new_project)

            created.append({
                'folder': folder_name,
                'project_no': new_project.project_no,
                'site_name': parsed['site_name'],
            })

        if created:
            db.commit()
            current_app.logger.info(
                'NAS 폴더 동기화: %d건 생성, %d건 스킵, %d건 오류',
                len(created), len(skipped), len(errors)
            )

    return jsonify({
        'ok': True,
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'summary': f"생성 {len(created)}건, 스킵 {len(skipped)}건, 오류 {len(errors)}건"
    })


@api_bp.route('/fix_nas_dates', methods=['POST'])
def fix_nas_dates():
    """
    work_path가 NAS 경로인 기존 프로젝트의 created_at을 폴더 날짜로 보정.
    한 번만 실행하면 되는 마이그레이션용 엔드포인트.
    """
    ok, err_msg = _check_api_key()
    if not ok:
        return jsonify({'ok': False, 'error': err_msg}), 401

    fixed = []
    with get_db() as db:
        projects = db.query(Project).filter(
            Project.work_path.like('/volume1/현장관리/%')
        ).all()

        for p in projects:
            # work_path에서 폴더명 추출
            folder_name = p.work_path.rstrip('/').split('/')[-1]
            parsed = _parse_folder_name(folder_name)
            if not parsed:
                continue

            folder_dt = datetime.datetime.combine(parsed['folder_date'], datetime.time())
            if p.created_at != folder_dt:
                old_dt = p.created_at
                p.created_at = folder_dt
                fixed.append({
                    'project_no': p.project_no,
                    'name': p.temp_name,
                    'old': str(old_dt),
                    'new': str(folder_dt),
                })

        if fixed:
            db.commit()

    return jsonify({
        'ok': True,
        'fixed': fixed,
        'summary': f"{len(fixed)}건 날짜 보정 완료"
    })
