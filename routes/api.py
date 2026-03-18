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

from sqlalchemy import or_

from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.history_board import append_history_log
from modules.models import Project, ProductCatalog, G2bProcurement
from modules.services.g2b_procurement_sync import sync_daily, sync_bulk

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

        # 연도별 프로젝트 번호 카운트 캐시
        year_counts = {}

        for folder_name in folders:
            parsed = _parse_folder_name(folder_name)
            if not parsed:
                errors.append({
                    'folder': folder_name,
                    'reason': '폴더명 패턴 불일치 (YYYY.MM.DD_현장명)'
                })
                continue

            # work_path: 폴더명 앞 4자리(YYYY)로 연도 디렉토리 결정
            folder_year = str(parsed['folder_date'].year)
            nas_path = f"\\\\Magnatech\\현장관리\\000. 현장관리\\{folder_year}\\{folder_name}"
            old_path = f"/volume1/현장관리/000. 현장관리/{folder_year}/{folder_name}"
            if nas_path in existing_paths or old_path in existing_paths:
                skipped.append({
                    'folder': folder_name,
                    'reason': '이미 등록된 현장'
                })
                continue

            # 새 프로젝트 생성 (생성일 = 폴더명의 날짜, 관리번호 = 폴더연도 기준)
            if folder_year not in year_counts:
                year_counts[folder_year] = db.query(Project).filter(
                    Project.project_no.like(f"{folder_year}-%")
                ).count()
            year_counts[folder_year] += 1
            folder_dt = datetime.datetime.combine(parsed['folder_date'], datetime.time())
            new_project = Project(
                project_no=f"{folder_year}-{year_counts[folder_year]:03d}",
                temp_name=parsed['site_name'],
                work_path=nas_path,
                created_at=folder_dt,
            )
            db.add(new_project)
            db.flush()

            append_history_log(
                db,
                project_id=new_project.id,
                user_name="시스템 🤖",
                content=f"NAS 폴더 동기화로 현장이 자동 생성되었습니다. (폴더: {folder_name})",
                scope='design',
                kind='system'
            )

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


@api_bp.route('/catalog/search')
@login_required
def catalog_search():
    """ProductCatalog 자동완성 검색 API."""
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()

    if len(q) < 2:
        return jsonify({'results': []})

    with get_db() as db:
        like_q = f'%{q}%'
        query = db.query(ProductCatalog).filter(
            or_(
                ProductCatalog.model_name.ilike(like_q),
                ProductCatalog.item_name.ilike(like_q),
                ProductCatalog.spec.ilike(like_q),
            )
        )
        if category:
            query = query.filter(ProductCatalog.item_name.ilike(f'%{category}%'))

        results = query.order_by(ProductCatalog.model_name).limit(10).all()
        return jsonify({'results': [
            {
                'id': r.id,
                'model_name': r.model_name or '',
                'item_name': r.item_name or '',
                'spec': r.spec or '',
                'unit_price': r.unit_price or 0,
                'unit': r.unit or '',
            } for r in results
        ]})


@api_bp.route('/fix_nas_paths', methods=['POST'])
def fix_nas_paths():
    """
    기존 리눅스 경로(/volume1/...)를 SMB 경로(\\\\Magnatech\\...)로 일괄 보정.
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
            old_path = p.work_path
            # /volume1/현장관리/000. 현장관리/2026/폴더명 → \\Magnatech\현장관리\000. 현장관리\2026\폴더명
            new_path = old_path.replace('/volume1/현장관리/', '\\\\Magnatech\\현장관리\\').replace('/', '\\')
            p.work_path = new_path
            fixed.append({
                'project_no': p.project_no,
                'name': p.temp_name,
                'old': old_path,
                'new': new_path,
            })

        if fixed:
            db.commit()

    return jsonify({
        'ok': True,
        'fixed': fixed,
        'summary': f"{len(fixed)}건 경로 보정 완료"
    })


# =====================================================================
# 나라장터 조달내역 동기화 API
# =====================================================================

@api_bp.route('/sync_g2b_procurement', methods=['POST'])
def sync_g2b_procurement():
    """
    나라장터 특정물품조달내역 동기화.
    - 일일 동기화 (기본): 전일 계약건 조회
    - 벌크 동기화: mode=bulk&start_year=2020 으로 전체 이력 수집

    Request JSON (optional):
        {"mode": "daily"}   → 전일 데이터만 (기본값, cron용)
        {"mode": "bulk", "start_year": 2020}  → 초기 벌크

    Headers: X-API-Key (NAS와 동일 키 사용)
    """
    ok, err_msg = _check_api_key()
    if not ok:
        return jsonify({'ok': False, 'error': err_msg}), 401

    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'daily')

    with get_db() as db:
        if mode == 'bulk':
            start_year = int(data.get('start_year', 2020))
            result = sync_bulk(db, start_year=start_year)
        else:
            result = sync_daily(db)

        db.commit()

    total = result.get('created', 0) + result.get('updated', 0)
    return jsonify({
        'ok': True,
        'mode': mode,
        'result': result,
        'summary': f"동기화 완료: 신규 {result['created']}건, 갱신 {result['updated']}건"
                   + (f", 오류 {result['errors']}건" if result.get('errors') else '')
    })
