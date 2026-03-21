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
from flask import render_template, session

from modules.history_board import append_history_log, get_project_history_context
from modules.models import Project, ProductCatalog, G2bProcurement, HistoryLog
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


def _parse_plan_txt(text):
    """
    .plan.txt 내용을 파싱해서 dict로 반환.
    '항목명: 값' 형식. #으로 시작하는 줄은 주석.
    """
    if not text:
        return {}
    result = {}
    # \\n 이스케이프를 실제 줄바꿈으로 변환
    text = text.replace('\\n', '\n')
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip()
        if not val:
            continue
        result[key] = val
    return result


def _apply_plan_to_project(project, plan_data):
    """plan_data dict를 Project 필드에 반영. 변경된 필드 목록 반환."""
    field_map = {
        '현장명': 'temp_name',
        '약칭': 'short_name',
        '현장주소': 'site_address',
        '납품주소': 'shipping_address',
        '메모': 'site_memo',
        '상태': 'status',
    }
    changes = []
    for label, attr in field_map.items():
        if label in plan_data:
            old_val = getattr(project, attr, None) or ''
            new_val = plan_data[label]
            if str(old_val).strip() != new_val:
                setattr(project, attr, new_val)
                changes.append(f"{label}: '{old_val}' → '{new_val}'")

    if '긴급' in plan_data:
        is_urgent = plan_data['긴급'] in ('예', '네', 'Y', 'y', 'yes', 'Yes')
        if project.is_urgent != is_urgent:
            project.is_urgent = is_urgent
            changes.append(f"긴급: {'예' if is_urgent else '아니오'}")

    if '계약예정일' in plan_data:
        try:
            new_date = datetime.datetime.strptime(plan_data['계약예정일'], '%Y-%m-%d').date()
            if project.expected_contract_date != new_date:
                project.expected_contract_date = new_date
                changes.append(f"계약예정일: {new_date}")
        except ValueError:
            pass

    # 원본폴더명 → 폴더명 변경 추적용
    if '원본폴더명' in plan_data:
        # design_basis에 원본 폴더명 저장 (변경 추적용)
        origin = plan_data['원본폴더명']
        if not project.design_basis or origin not in (project.design_basis or ''):
            project.design_basis = origin
            changes.append(f"원본폴더명: {origin}")

    return changes


def _generate_plan_txt(project, folder_name):
    """Project 데이터로 .plan.txt 내용 생성"""
    lines = [
        "# 설계관리 정보 (.plan.txt)",
        "# ERP에서 자동 생성됨. 수정하면 다음 동기화 시 ERP에 반영됩니다.",
        "",
        f"원본폴더명: {folder_name}",
        "",
        f"현장명: {project.temp_name or ''}",
        f"약칭: {project.short_name or ''}",
        f"현장주소: {project.site_address or ''}",
        f"납품주소: {project.shipping_address or ''}",
        f"계약예정일: {project.expected_contract_date.strftime('%Y-%m-%d') if project.expected_contract_date else ''}",
        f"상태: {project.status or '설계/영업'}",
        f"긴급: {'예' if project.is_urgent else '아니오'}",
        f"메모: {project.site_memo or ''}",
    ]
    return '\n'.join(lines)


def _generate_plan_template(folder_name):
    """빈 .plan.txt 템플릿 생성 (신규 현장용)"""
    lines = [
        "# 설계관리 정보 (.plan.txt)",
        "# 항목명: 뒤에 값을 입력하세요. 빈 항목은 무시됩니다.",
        "",
        f"원본폴더명: {folder_name}",
        "",
        "현장명:",
        "약칭:",
        "현장주소:",
        "납품주소:",
        "계약예정일:",
        "상태: 설계/영업",
        "긴급: 아니오",
        "메모:",
    ]
    return '\n'.join(lines)


@api_bp.route('/sync_nas_folders', methods=['POST'])
def sync_nas_folders():
    """
    NAS 폴더 전체 목록을 받아 ERP 현장과 동기화.
    - 매칭되는 현장 없으면 → 생성
    - work_path 완전 일치 → 스킵
    - 같은 연도 폴더 내 work_path가 있지만 폴더명이 다르면 → 이름/경로 업데이트

    Request JSON:
        {
            "folders": ["2026.03.03_울산공항 계류장", ...],
            "year": "2026"  (optional, 기본값: 올해)
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
    updated = []
    write_plans = []  # .plan.txt 없는 폴더에 생성할 내용

    with get_db() as db:
        # work_path가 있는 현장 전부 로드 → 경로 매핑
        # 정규화: 소문자 + 슬래시 통일 (대소문자/슬래시 차이 무시)
        def _normalize_path(p):
            return (p or '').strip().lower().replace('\\', '/')

        all_projects_with_path = db.query(Project).filter(
            Project.work_path.isnot(None),
            Project.work_path != '',
        ).all()

        path_to_project = {}       # 정규화된 경로 → Project
        path_to_project_raw = {}   # 원본 경로 → Project
        for p in all_projects_with_path:
            wp = (p.work_path or '').strip()
            if wp:
                path_to_project[_normalize_path(wp)] = p
                path_to_project_raw[wp] = p

        # NAS에서 보낸 전체 폴더의 예상 경로 셋 (나중에 rename 감지용)
        incoming_paths = set()
        parsed_folders = []
        for entry in folders:
            # folders 배열: 문자열("폴더명") 또는 객체({"name":"폴더명","plan":"..."}) 둘 다 지원
            if isinstance(entry, dict):
                folder_name = entry.get('name', '')
                plan_text = entry.get('plan', '')
            else:
                folder_name = str(entry)
                plan_text = ''

            parsed = _parse_folder_name(folder_name)
            if not parsed:
                errors.append({'folder': folder_name, 'reason': '폴더명 패턴 불일치'})
                continue
            folder_year = str(parsed['folder_date'].year)
            nas_path = f"\\\\Magnatech\\현장관리\\000. 현장관리\\{folder_year}\\{folder_name}"
            incoming_paths.add(_normalize_path(nas_path))
            parsed_folders.append({
                'folder_name': folder_name,
                'parsed': parsed,
                'folder_year': folder_year,
                'nas_path': nas_path,
                'plan_text': plan_text,
            })

        year_counts = {}

        for item in parsed_folders:
            folder_name = item['folder_name']
            parsed = item['parsed']
            folder_year = item['folder_year']
            nas_path = item['nas_path']

            plan_text = item.get('plan_text', '')
            plan_data = _parse_plan_txt(plan_text)
            has_plan = bool(plan_text.strip())

            # 1) 완전 일치 (정규화 비교)
            nas_path_norm = _normalize_path(nas_path)
            if nas_path_norm in path_to_project:
                proj = path_to_project[nas_path_norm]
                if plan_data:
                    # .plan.txt 있으면 필드 업데이트
                    changes = _apply_plan_to_project(proj, plan_data)
                    if changes:
                        append_history_log(
                            db,
                            project_id=proj.id,
                            user_name="시스템 🤖",
                            content=f".plan.txt 반영: {', '.join(changes)}",
                            scope='design',
                            kind='system'
                        )
                        updated.append({
                            'folder': folder_name,
                            'project_no': proj.project_no,
                            'plan_changes': changes,
                        })
                    else:
                        skipped.append({'folder': folder_name, 'reason': '이미 등록된 현장'})
                elif not has_plan:
                    # 케이스 1: DB에 있지만 .plan.txt 없음 → DB 내용으로 생성
                    write_plans.append({
                        'folder': folder_name,
                        'content': _generate_plan_txt(proj, folder_name),
                    })
                    skipped.append({'folder': folder_name, 'reason': '이미 등록된 현장 (.plan.txt 생성)'})
                else:
                    skipped.append({'folder': folder_name, 'reason': '이미 등록된 현장'})
                continue

            # 2) 폴더명 변경 감지
            year_prefix = f"\\\\Magnatech\\현장관리\\000. 현장관리\\{folder_year}\\"
            rename_match = None

            # 2-a) .plan.txt에 원본폴더명이 있으면 → 원본 경로로 정확 매칭
            if plan_data.get('원본폴더명'):
                origin_folder = plan_data['원본폴더명'].strip()
                origin_parsed = _parse_folder_name(origin_folder)
                if origin_parsed:
                    origin_year = str(origin_parsed['folder_date'].year)
                    origin_path = f"\\\\Magnatech\\현장관리\\000. 현장관리\\{origin_year}\\{origin_folder}"
                    origin_norm = _normalize_path(origin_path)
                    if origin_norm in path_to_project:
                        rename_match = path_to_project[origin_norm]

            # 2-b) 원본폴더명 없으면 → 같은 날짜 + NAS에 없는 경로로 추정
            year_prefix_norm = _normalize_path(year_prefix)
            if not rename_match:
                for old_path_norm, proj in path_to_project.items():
                    if not old_path_norm.startswith(year_prefix_norm):
                        continue
                    if old_path_norm not in incoming_paths:
                        old_folder = old_path_norm[len(year_prefix_norm):]
                        old_parsed = _parse_folder_name(old_folder)
                        if old_parsed and old_parsed['folder_date'] == parsed['folder_date']:
                            rename_match = proj
                            break

            if rename_match:
                old_name = rename_match.temp_name
                old_work_path = rename_match.work_path
                rename_match.temp_name = parsed['site_name']
                rename_match.work_path = nas_path

                # .plan.txt 반영
                plan_changes = _apply_plan_to_project(rename_match, plan_data) if plan_data else []

                # 매핑 갱신 (정규화)
                old_norm = _normalize_path(old_work_path)
                if old_norm in path_to_project:
                    del path_to_project[old_norm]
                path_to_project[nas_path_norm] = rename_match

                log_msg = f"NAS 폴더명 변경 감지: '{old_name}' → '{parsed['site_name']}'"
                if plan_changes:
                    log_msg += f" | .plan.txt 반영: {', '.join(plan_changes)}"
                append_history_log(
                    db,
                    project_id=rename_match.id,
                    user_name="시스템 🤖",
                    content=log_msg,
                    scope='design',
                    kind='system'
                )
                updated.append({
                    'folder': folder_name,
                    'project_no': rename_match.project_no,
                    'old_name': old_name,
                    'new_name': parsed['site_name'],
                })
                continue

            # 3) 신규 생성
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
            path_to_project[nas_path_norm] = new_project

            # .plan.txt 반영 (신규 생성 시)
            if plan_data:
                _apply_plan_to_project(new_project, plan_data)

            # 케이스 2: DB 신규 생성 + .plan.txt 없음 → 템플릿 생성
            if not has_plan:
                write_plans.append({
                    'folder': folder_name,
                    'content': _generate_plan_template(folder_name),
                })

            append_history_log(
                db,
                project_id=new_project.id,
                user_name="시스템 🤖",
                content=f"NAS 폴더 동기화로 현장이 자동 생성되었습니다. (폴더: {folder_name}){' | .plan.txt 반영' if plan_data else ''}",
                scope='design',
                kind='system'
            )
            created.append({
                'folder': folder_name,
                'project_no': new_project.project_no,
                'site_name': parsed['site_name'],
            })

        if created or updated:
            db.commit()
            current_app.logger.info(
                'NAS 폴더 동기화: %d건 생성, %d건 업데이트, %d건 스킵, %d건 오류',
                len(created), len(updated), len(skipped), len(errors)
            )

    # 디버그: DB에 저장된 경로 샘플 (문제 추적용)
    debug_paths = list(path_to_project.keys())[:5]

    return jsonify({
        'ok': True,
        'created': created,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'write_plans': write_plans,
        'debug_db_paths': debug_paths,
        'debug_path_count': len(path_to_project),
        'summary': f"생성 {len(created)}건, 업데이트 {len(updated)}건, 스킵 {len(skipped)}건, .plan생성 {len(write_plans)}건"
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


# ─── 히스토리보드 AJAX API ───────────────────────────────────

@api_bp.route('/history/<int:project_id>/add', methods=['POST'])
@login_required
def history_add_comment(project_id):
    """코멘트/답글 등록 (AJAX) → 히스토리 HTML 조각 반환"""
    db = get_db()
    project = db.query(Project).get(project_id)
    if not project:
        return jsonify({'ok': False, 'error': '현장 없음'}), 404

    action = request.form.get('action', 'add_chat')
    user_name = session.get('full_name', '사용자')

    if action == 'add_chat':
        msg = (request.form.get('chat_message') or '').strip()
        if not msg:
            return jsonify({'ok': False, 'error': '내용을 입력하세요'}), 400
        append_history_log(db, project_id=project.id, user_name=user_name,
                           content=msg, scope='common', kind='comment')
    elif action == 'add_history_reply':
        msg = (request.form.get('reply_message') or '').strip()
        parent_id = request.form.get('parent_log_id', type=int)
        if not msg or not parent_id:
            return jsonify({'ok': False, 'error': '내용을 입력하세요'}), 400
        parent = db.query(HistoryLog).get(parent_id)
        origin = (parent.content or '')[:200] if parent else ''
        append_history_log(db, project_id=project.id, user_name=user_name,
                           content=msg, scope='common', kind='reply',
                           parent_log_id=parent_id,
                           root_log_id=parent.root_log_id or parent_id if parent else parent_id,
                           origin_snapshot=origin)
    else:
        return jsonify({'ok': False, 'error': f'알 수 없는 action: {action}'}), 400

    db.commit()
    return _render_history_fragment(db, project_id, request.form.get('default_scope', 'common'))


@api_bp.route('/history/<int:project_id>/fragment')
@login_required
def history_fragment(project_id):
    """히스토리 HTML 조각만 반환 (AJAX 갱신용)"""
    db = get_db()
    default_scope = request.args.get('default_scope', 'common')
    return _render_history_fragment(db, project_id, default_scope)


def _render_history_fragment(db, project_id, default_scope='common'):
    history, history_counts = get_project_history_context(db, project_id, default_scope=default_scope)
    html = render_template('components/history_board.html',
                           history=history, history_counts=history_counts,
                           history_board_id='ajax-history-board',
                           history_post_action='add_chat',
                           history_default_filter='all')
    return jsonify({'ok': True, 'html': html,
                    'total': history_counts.get('all', 0)})
