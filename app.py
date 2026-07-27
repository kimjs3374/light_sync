import os
import datetime
from dotenv import load_dotenv
load_dotenv()
import logging
import warnings
from collections import OrderedDict
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")
from logging.handlers import RotatingFileHandler
from flask import Flask, redirect, url_for, request, session, render_template, send_from_directory
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import ProductionConfig, DevelopmentConfig, MENU_REGISTRY, COMMON_MENU_KEYS, GROUP_ICONS
from modules.models import init_db
from routes.auth import auth_bp
from routes.mattermost_action import mattermost_action_bp
from routes.mattermost_slash import mattermost_slash_bp
from routes.kakaowork_action import kakaowork_action_bp
from routes.dashboard import dashboard_bp
from routes.project import project_bp
from routes.contract import contract_bp
from routes.technical import tech_bp
from routes.drawing import drawing_bp
from routes.sales import sales_bp
from routes.production import production_bp
from routes.delivery import delivery_bp
from routes.material import material_bp
from routes.barcode import barcode_bp
from routes.notification import notification_bp
from routes.overview import overview_bp
from routes.warranty import warranty_bp
from routes.report import report_bp
from routes.catalog import catalog_bp
from routes.procurement import procurement_bp
from routes.api import api_bp
from routes.daily_report import daily_report_bp
from routes.vendor import vendor_bp
from routes.purchase_order import purchase_order_bp
from routes.receiving import receiving_bp
from routes.receiving_photo import receiving_photo_bp
from routes.bom import bom_bp
from routes.item import item_bp
from routes.financial import financial_bp
from routes.hometax import hometax_bp
from routes.billing import billing_bp
from routes.inventory import inventory_bp
from routes.quotation import quotation_bp
from routes.photos import photos_bp
from routes.chatbot import chatbot_bp
from routes.illuminance import ilv_bp
from routes.workboard import workboard_bp
from routes.asboard import asboard_bp
from routes.archive_boards import archive_bp
from routes.approval_archive import approval_archive_bp
from routes.chat_archive import chat_archive_bp
from routes.channel_chat import channel_chat_bp
from routes.certification import cert_bp
from routes.lighting_layout import lighting_layout_bp
from routes.processing_order import processing_order_bp
from routes.business_trip import business_trip_bp
from routes.vehicle_log import vehicle_log_bp
from routes.approval import approval_bp
from routes.hr import hr_bp
from routes.tools import tools_bp
from routes.document import document_bp
from routes.app_api import app_api_bp
from routes.incoming_overview import incoming_overview_bp
from routes.mail import mail_bp
from routes.office import office_bp
from routes.mockups import mockups_bp
from routes.oauth import oauth_bp
from modules.pagination import pagination_query
from modules.scheduler import init_scheduler

# =====================================================================
# App 생성 및 설정
# =====================================================================
app = Flask(__name__)

# 환경에 따른 설정 로딩
if os.environ.get('FLASK_DEBUG', 'false').lower() == 'true':
    app.config.from_object(DevelopmentConfig)
else:
    app.config.from_object(ProductionConfig)

app.config["PREFERRED_URL_SCHEME"] = "https"
app.config["SESSION_COOKIE_SECURE"] = True  # HTTPS 환경 강제

# Cloudflare → VPS → gunicorn: 프록시 헤더 신뢰
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB (대용량 메일 첨부)
app.json.ensure_ascii = False

# Logging
os.makedirs('logs', exist_ok=True)
file_handler = RotatingFileHandler('logs/light_sync.log', maxBytes=10_000_000, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s [%(name)s] %(message)s'
))
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
app.logger.setLevel(logging.INFO)
app.jinja_env.auto_reload = app.config.get("TEMPLATES_AUTO_RELOAD", True)
app.jinja_env.globals['pagination_query'] = pagination_query

# 진단(최우선 실행) — origin에 도달하는 모든 관련 POST를 CSRF 검사 이전에 무조건 기록
from flask import request as _rq0
@app.before_request
def _log_promotion_posts():
    try:
        if _rq0.method == 'POST' and 'promotion' in _rq0.path:
            app.logger.warning('RAW_POST path=%s ct=%s len=%s ua=%r',
                               _rq0.path, _rq0.content_type,
                               _rq0.content_length,
                               _rq0.headers.get('User-Agent', '')[:120])
    except Exception:
        pass

# CSRF Protection
csrf = CSRFProtect(app)

# 진단 — CSRF 거부가 조용히 400을 뱉어 "반응 없음"처럼 보이는지 추적(모바일 지정 이슈)
from flask_wtf.csrf import CSRFError as _CSRFError
from flask import request as _rq
@app.errorhandler(_CSRFError)
def _log_csrf_error(e):
    try:
        app.logger.warning('CSRF_FAIL method=%s path=%s reason=%s ua=%r',
                            _rq.method, _rq.path, e.description,
                            _rq.headers.get('User-Agent', '')[:120])
    except Exception:
        pass
    return e.description, 400

# Bearer 토큰 인증 경로에서 세션 쿠키 누출 차단 + CSRF 우회
from modules.auth_decorators import init_auth_security
init_auth_security(app, csrf)

# ── HTML 세정 필터 (이메일 XSS 방지) ──
import nh3

def _sanitize_html(value):
    """이메일 HTML에서 악성 스크립트 제거. 안전한 태그/속성만 허용."""
    if not value:
        return ''
    return nh3.clean(
        value,
        tags={'p', 'div', 'span', 'br', 'b', 'i', 'u', 'strong', 'em', 'a', 'ul', 'ol', 'li',
              'table', 'thead', 'tbody', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
              'blockquote', 'pre', 'code', 'hr', 'img', 'sub', 'sup', 'font', 'center'},
        attributes={
            '*': {'style', 'class', 'id', 'align', 'valign', 'width', 'height', 'bgcolor', 'color'},
            'a': {'href', 'title', 'target'},
            'img': {'src', 'alt', 'width', 'height'},
            'font': {'size', 'color', 'face'},
            'td': {'colspan', 'rowspan'},
            'th': {'colspan', 'rowspan'},
        },
        url_schemes={'http', 'https', 'mailto'},
    )

app.jinja_env.filters['sanitize_html'] = _sanitize_html

# Rate Limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)

# 세션 영구화 (PERMANENT_SESSION_LIFETIME 적용을 위해)
@app.before_request
def make_session_permanent():
    session.permanent = True


# 세션 권한 실시간 갱신 (관리자가 권한 변경 시 재로그인 없이 반영)
@app.before_request
def refresh_session_permissions():
    user_id = session.get('user_id')
    if not user_id or request.endpoint in ('auth.login', 'auth.logout', 'static'):
        return
    # 매 요청마다 하면 부하 → 30초 캐시
    import time
    last_check = session.get('_perm_checked', 0)
    if time.time() - last_check < 30:
        return
    from modules.db_context import get_db
    from modules.models import User, GroupPermission, UserPriorityPermission
    with get_db() as db:
        user = db.get(User, user_id)
        if not user or not user.is_approved or user.is_active is False:
            session.clear()
            return
        group_data = db.query(GroupPermission).filter(
            GroupPermission.group_name == user.user_group
        ).first()
        if user.role == 'admin':
            allowed_menus = [k for k in MENU_REGISTRY if k not in COMMON_MENU_KEYS]
            writable_menus = list(allowed_menus)
            hide_financial = False
        else:
            perm_map = {}
            if group_data and group_data.allowed_menus:
                for entry in group_data.allowed_menus.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if ':' in entry:
                        key, perm = entry.rsplit(':', 1)
                    else:
                        key, perm = entry, 'rw'
                    perm_map[key] = perm
            if user.extra_menus:
                for entry in user.extra_menus.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if ':' in entry:
                        key, perm = entry.rsplit(':', 1)
                    else:
                        key, perm = entry, 'rw'
                    perm_map[key] = perm
            allowed_menus = list(perm_map.keys())
            writable_menus = [k for k, v in perm_map.items() if v == 'rw']
            hide_financial = bool(group_data and getattr(group_data, 'hide_financial', False))
            if hasattr(user, 'hide_financial_override') and user.hide_financial_override is not None:
                hide_financial = user.hide_financial_override
        session['allowed_menus'] = allowed_menus
        session['writable_menus'] = writable_menus
        session['hide_financial'] = hide_financial
        session['role'] = user.role
        session['user_group'] = user.user_group
        session['position'] = user.position or ''
        session['can_approve_delete'] = bool(user.role == 'admin' or user.can_approve_delete)
        # 관리자 전역 메뉴 비활성 설정 (모든 사용자에게 동일 적용)
        from modules.services.dashboard_actions import get_disabled_menus
        session['disabled_menus'] = list(get_disabled_menus(db))
        session['_perm_checked'] = time.time()


# 비밀번호 초기화 후 강제 변경
@app.before_request
def check_must_change_password():
    if not session.get('must_change_password'):
        return
    allowed = {'auth.force_change_password', 'auth.logout', 'static'}
    if request.endpoint not in allowed:
        return redirect(url_for('auth.force_change_password'))


# =====================================================================
# 운영 도메인 강제 리다이렉트
# =====================================================================
LOCKED_DOMAIN = app.config.get("DOMAIN", "work.mgnt.kr")

@app.before_request
def force_locked_domain():
    """운영 도메인 강제: 다른 Host로 접근 시 work.mgnt.kr로 리다이렉트 (개발환경에서는 비활성화)"""
    if os.environ.get('FLASK_ENV') != 'production':
        return None
    host_only = (request.host or '').split(':')[0].lower()
    if host_only and host_only not in {LOCKED_DOMAIN, 'localhost', '127.0.0.1'}:
        target = f"https://{LOCKED_DOMAIN}{request.full_path}"
        if target.endswith('?'):
            target = target[:-1]
        return redirect(target, code=301)


# =====================================================================
# Rate Limiting (엔드포인트별)
# =====================================================================
limiter.limit("10 per minute")(auth_bp)


# =====================================================================
# Blueprint 등록
# =====================================================================
app.register_blueprint(auth_bp)
app.register_blueprint(mattermost_action_bp)
csrf.exempt(mattermost_action_bp)  # 외부(Mattermost 서버)에서 호출되는 webhook이라 CSRF 면제
app.register_blueprint(mattermost_slash_bp)
csrf.exempt(mattermost_slash_bp)   # 슬래시 커맨드도 외부 호출
app.register_blueprint(kakaowork_action_bp)
csrf.exempt(kakaowork_action_bp)   # 카카오워크 봇 콜백(외부 호출)이라 CSRF 면제

# 개별 엔드포인트 rate limit (Blueprint 등록 후 적용)
with app.app_context():
    view_func = app.view_functions.get('auth.register')
    if view_func:
        app.view_functions['auth.register'] = limiter.limit("3 per minute")(view_func)
app.register_blueprint(dashboard_bp)
app.register_blueprint(project_bp)
app.register_blueprint(contract_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(production_bp)
app.register_blueprint(incoming_overview_bp)
app.register_blueprint(delivery_bp)
app.register_blueprint(tech_bp)
app.register_blueprint(drawing_bp)
app.register_blueprint(material_bp)
app.register_blueprint(barcode_bp)
app.register_blueprint(notification_bp)
app.register_blueprint(overview_bp)
app.register_blueprint(warranty_bp)
app.register_blueprint(report_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(procurement_bp)
app.register_blueprint(daily_report_bp)
app.register_blueprint(vendor_bp)
app.register_blueprint(purchase_order_bp)
app.register_blueprint(receiving_bp)
app.register_blueprint(receiving_photo_bp)
app.register_blueprint(bom_bp)
app.register_blueprint(item_bp)
app.register_blueprint(financial_bp)
app.register_blueprint(hometax_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(quotation_bp)
app.register_blueprint(photos_bp)
app.register_blueprint(chatbot_bp)
app.register_blueprint(api_bp)
app.register_blueprint(ilv_bp)
app.register_blueprint(workboard_bp)
app.register_blueprint(asboard_bp)
app.register_blueprint(archive_bp)
app.register_blueprint(approval_archive_bp)
app.register_blueprint(chat_archive_bp)
app.register_blueprint(channel_chat_bp)
csrf.exempt(channel_chat_bp)  # bot/worker callback (non-browser) CSRF exempt
app.register_blueprint(cert_bp)
app.register_blueprint(lighting_layout_bp)
app.register_blueprint(processing_order_bp)
app.register_blueprint(business_trip_bp)
app.register_blueprint(vehicle_log_bp)
app.register_blueprint(approval_bp)
app.register_blueprint(hr_bp)
app.register_blueprint(tools_bp)
app.register_blueprint(document_bp)
app.register_blueprint(app_api_bp)
app.register_blueprint(mail_bp)
app.register_blueprint(office_bp)
app.register_blueprint(mockups_bp)
app.register_blueprint(oauth_bp)
csrf.exempt(oauth_bp)
csrf.exempt(office_bp)

# ONLYOFFICE callback Blueprint (CSRF 면제)
from flask import Blueprint as _Bp
_onlyoffice_bp = _Bp('onlyoffice', __name__)

@_onlyoffice_bp.route('/api/onlyoffice/callback', methods=['POST'])
def onlyoffice_callback():
    from flask import jsonify as _jsonify
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        body = request.get_json(force=True, silent=True) or {}
        status = body.get('status', 0)
        _log.info("ONLYOFFICE callback: status=%s, key=%s", status, body.get('key'))

        # status 2 = 문서 저장됨 (편집 종료), 6 = 강제 저장
        if status in (2, 6):
            download_url = body.get('url')
            office_file = request.args.get('office_file', '')
            office_scope = request.args.get('office_scope', 'shared')
            _log.info("ONLYOFFICE save trigger: status=%s, url=%s, office_file=%s, args=%s",
                      status, bool(download_url), office_file, dict(request.args))
            if not download_url:
                _log.warning("ONLYOFFICE status=%s but no download_url in body. body keys=%s", status, list(body.keys()))
            else:
                try:
                    import requests as _requests
                    resp = _requests.get(download_url, timeout=30)
                    if resp.status_code != 200:
                        _log.error("ONLYOFFICE download failed: HTTP %s, url=%s", resp.status_code, download_url)
                    else:
                        from modules.storage_adapter import upload_bytes
                        content = resp.content

                        req_no = request.args.get('req_no', '')
                        tpl_type = request.args.get('tpl_type', '')
                        office_uid = request.args.get('office_uid', '')

                        if office_file:
                            # Office 범용 파일 저장 (scope 구분)
                            ext = office_file.rsplit('.', 1)[-1].lower() if '.' in office_file else 'xlsx'
                            mime_map = {
                                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                'xls':  'application/vnd.ms-excel',
                                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                'doc':  'application/msword',
                                'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                            }
                            office_mime = mime_map.get(ext, 'application/octet-stream')
                            if office_scope == 'private' and office_uid:
                                office_path = f'documents/office/private/{office_uid}/{office_file}'
                            else:
                                office_path = f'documents/office/shared/{office_file}'
                            ok_o, msg_o = upload_bytes(office_path, content, content_type=office_mime)
                            _log.info("Office save [%s]: %s → ok=%s, %s", office_scope, office_file, ok_o, msg_o)
                            if not ok_o:
                                _log.error("Office upload_bytes FAILED: %s", msg_o)
                        elif tpl_type:
                            # 템플릿 저장 (Supabase + 로컬)
                            mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            tpl_paths = {
                                'commencement': 'documents/templates/commencement_template.xlsx',
                                'delivery': 'documents/templates/delivery_template.xlsx',
                            }
                            tpl_local = {
                                'commencement': '/web/light_sync/static/templates/commencement_template.xlsx',
                                'delivery': '/web/light_sync/static/templates/delivery_template.xlsx',
                            }
                            if tpl_type in tpl_paths:
                                upload_bytes(tpl_paths[tpl_type], content, content_type=mime)
                                with open(tpl_local[tpl_type], 'wb') as f:
                                    f.write(content)
                                _log.info("Template saved: %s", tpl_type)
                        elif req_no:
                            # 현장 서류 저장 (Supabase + 로컬)
                            mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            storage_path = f'documents/commencement/{req_no}.xlsx'
                            ok, msg = upload_bytes(storage_path, content, content_type=mime)
                            for local_dir in ['/web/light_sync/static/documents/commencement',
                                              '/web/light_sync/static/documents/delivery']:
                                local_path = f'{local_dir}/{req_no}.xlsx'
                                if os.path.exists(local_path):
                                    with open(local_path, 'wb') as lf:
                                        lf.write(content)
                                    _log.info("Local file saved: %s", local_path)
                                    break
                            _log.info("ONLYOFFICE commencement save: %s, %s", ok, msg)
                        else:
                            _log.warning("ONLYOFFICE status=%s: no office_file/tpl_type/req_no in args=%s", status, dict(request.args))
                except Exception as e:
                    _log.error("ONLYOFFICE save error: %s", e, exc_info=True)
    except Exception as e:
        _log.error("ONLYOFFICE callback error: %s", e)
    return _jsonify({"error": 0}), 200

app.register_blueprint(_onlyoffice_bp)
csrf.exempt(_onlyoffice_bp)

# 사내망 대용량 업로드 CORS (192.168.x.x → 8501 직접 요청)
@app.after_request
def add_security_headers(response):
    # CORS (사내망 + 도메인)
    origin = request.headers.get('Origin', '')
    if origin and ('work.mgnt.kr' in origin or '192.168.' in origin or 'localhost' in origin):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-CSRFToken, X-Requested-With'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    # 보안 헤더
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# 워크보드 이미지 썸네일 서빙 (on-the-fly 생성 + 디스크 캐싱)
@app.route('/static-archive/thumb/<path:filename>')
def serve_archive_thumb(filename):
    import os as _os
    from pathlib import Path

    orig_path = Path('storage/archive') / filename
    if not orig_path.is_file():
        return send_from_directory('storage/archive', filename)

    # 썸네일 캐시 경로
    thumb_dir = Path('storage/archive/.thumbs') / _os.path.dirname(filename)
    thumb_path = thumb_dir / _os.path.basename(filename)

    if thumb_path.is_file():
        return send_from_directory(str(thumb_dir), _os.path.basename(filename))

    # Pillow로 썸네일 생성
    try:
        from PIL import Image
        thumb_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(str(orig_path)) as img:
            img.thumbnail((300, 300), Image.LANCZOS)
            # EXIF 회전 보정
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img) or img
            # JPEG로 저장 (투명 PNG 제외)
            if img.mode in ('RGBA', 'P'):
                img.save(str(thumb_path), format='PNG', optimize=True)
            else:
                img = img.convert('RGB')
                img.save(str(thumb_path), format='JPEG', quality=75, optimize=True)
        return send_from_directory(str(thumb_dir), _os.path.basename(filename))
    except Exception:
        # 썸네일 실패 시 원본 반환
        return send_from_directory('storage/archive', filename)

# 워크보드 아카이브 첨부파일 원본 서빙
@app.route('/static-archive/<path:filename>')
def serve_archive_file(filename):
    return send_from_directory('storage/archive', filename)

# NAS 동기화 API는 외부(NAS cron)에서 호출하므로 CSRF 면제
csrf.exempt(api_bp)

# Channel 콜백/폴링은 CSRF 면제 (reply: 서버 간 호출, poll: 반복 AJAX)
from routes.channel_chat import channel_reply as _cr, chat_poll as _cp
csrf.exempt(_cr)
csrf.exempt(_cp)

# 모바일 앱 API는 CSRF 면제
csrf.exempt(app_api_bp)

# 모바일 API는 토큰 인증 + 사내 공유IP(NAT) 환경 → IP기반 200/hour 기본제한 제외.
# (아카이브 이미지 프록시는 화면당 수십 요청 → 200/hour 즉시 초과로 이미지가 429로 전멸했음)
# 단, 로그인(app_login)은 무차별 대입 방지 위해 기본 제한 유지 → 제외 대상에서 뺀다.
_RATELIMIT_KEEP = {'app_api.app_login'}
with app.app_context():
    for _ep, _vf in list(app.view_functions.items()):
        if _ep.startswith('app_api.') and _ep not in _RATELIMIT_KEEP:
            limiter.exempt(_vf)

# 대용량 업로드만 CSRF exempt (사내망 직접 요청)
with app.app_context():
    _upload_view = app.view_functions.get('mail.api_upload_large')
    if _upload_view:
        csrf.exempt(_upload_view)



# =====================================================================
# 사이드바 메뉴 동적 주입
# =====================================================================
@app.context_processor
def inject_sidebar_menus():
    """세션의 allowed_menus 기반으로 사이드바 메뉴 그룹 데이터 생성"""
    if 'user_id' not in session:
        return {}

    is_admin = session.get('role') == 'admin'
    is_executive = session.get('user_group') == '임원진'
    allowed = set(session.get('allowed_menus', []))
    disabled = set(session.get('disabled_menus', []))

    # 사용자가 접근 가능한 메뉴 풀 생성 (key → menu dict)
    all_menus = {}
    for key, info in MENU_REGISTRY.items():
        if key in COMMON_MENU_KEYS:
            continue
        if key in disabled:
            continue  # 관리자가 비활성화한 메뉴는 누구에게도 표시 안 함
        if info.get("admin_only") and not is_admin:
            continue
        always_show = info.get("always_show", False)
        if always_show or is_admin or is_executive or key in allowed:
            try:
                menu_url = url_for(info["endpoint"])
            except Exception:
                continue
            all_menus[key] = {
                "key": key,
                "label": info["label"],
                "url": menu_url,
                "orig_group": info["group"],
            }

    # 메뉴 순서 + 그룹 이동 적용 (DB 저장값)
    import json as _json
    from modules.db_context import get_db
    from modules.models import DashboardSetting
    _order = None
    try:
        with get_db() as db:
            _mo = db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_order').first()
            if _mo:
                _order = _json.loads(_mo.setting_value)
    except Exception:
        pass

    menu_groups = OrderedDict()
    if _order and 'groups' in _order:
        placed = set()
        for gname in _order['groups']:
            keys_in_group = _order.get(gname, [])
            group_menus = []
            for k in keys_in_group:
                if k in all_menus and k not in placed:
                    group_menus.append(all_menus[k])
                    placed.add(k)
            if group_menus:
                menu_groups[gname] = group_menus
        # 순서에 없는 잔여 메뉴 → 원래 그룹에 추가
        for key, m in all_menus.items():
            if key not in placed:
                g = m["orig_group"]
                menu_groups.setdefault(g, []).append(m)
    else:
        # DB 순서 없으면 MENU_REGISTRY 기본 순서
        for key, m in all_menus.items():
            menu_groups.setdefault(m["orig_group"], []).append(m)

    writable = set(session.get('writable_menus', []))
    hide_financial = session.get('hide_financial', False)
    # admin/임원진은 항상 전체 쓰기 + 금액 표시
    if is_admin or is_executive:
        hide_financial = False

    return {
        "sidebar_menu_groups": menu_groups,
        "sidebar_group_icons": GROUP_ICONS,
        "is_admin": is_admin,
        "writable_menus": writable,
        "hide_financial": hide_financial,
        "disabled_menus": disabled,
    }


# =====================================================================
# Error Handlers
# =====================================================================
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error_code=404, error_message='페이지를 찾을 수 없습니다.'), 404

@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"Internal error: {e}")
    return render_template('error.html', error_code=500, error_message='서버 내부 오류가 발생했습니다.'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', error_code=403, error_message='접근 권한이 없습니다.'), 403


def _is_mobile_ua(ua: str) -> bool:
    """User-Agent가 모바일이면 True. 태블릿(iPad)은 PC 취급."""
    if not ua:
        return False
    ua_l = ua.lower()
    if 'ipad' in ua_l or 'tablet' in ua_l:
        return False
    return any(k in ua_l for k in ('iphone', 'android', 'mobile', 'webos', 'blackberry', 'iemobile', 'opera mini'))


def _should_force_mobile() -> bool:
    """모바일 UA + 세션에 PC 강제 플래그 없을 때 True."""
    if session.get('force_pc'):
        return False
    return _is_mobile_ua(request.headers.get('User-Agent', ''))


@app.route('/')
def index():
    # ?pc=1 쿼리로 PC 강제 진입 → 세션에 저장하여 이후 리다이렉트 체인에서 유지
    if request.args.get('pc') == '1':
        session['force_pc'] = True
    elif request.args.get('pc') == '0':
        session.pop('force_pc', None)
    if _should_force_mobile():
        return redirect('/m/')
    return redirect(url_for('dashboard.dashboard_view'))


# =====================================================================
# 모바일 SPA 서빙 (/m/ 경로)
# =====================================================================
_mobile_dist = os.path.join(os.path.dirname(__file__), 'mobile', 'dist')

@app.route('/m/')
@app.route('/m/<path:path>')
def serve_mobile(path=''):
    """모바일 SPA — 빌드된 정적 파일 서빙"""
    if path and os.path.isfile(os.path.join(_mobile_dist, path)):
        return send_from_directory(_mobile_dist, path)
    # SPA 엔트리(index.html)는 절대 캐시하지 않음 → 재배포 시 항상 최신 번들 로드
    resp = send_from_directory(_mobile_dist, 'index.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


# =====================================================================
# Flask CLI Commands (crontab에서 호출)
# =====================================================================
import click

@app.cli.command('sync-g2b')
@click.option('--mode', default='daily', help='daily: 전일 동기화, bulk: 전체 동기화')
@click.option('--start-year', default=2012, help='벌크 동기화 시작 연도')
@click.option('--no-auto-contract', is_flag=True, help='자동 계약 생성 비활성화')
def sync_g2b_cli(mode, start_year, no_auto_contract):
    """나라장터 조달내역 동기화 + 자동 계약 생성 (crontab용)"""
    from modules.db_context import get_db
    from modules.services.g2b_procurement_sync import sync_daily, sync_bulk, auto_create_contracts

    with get_db() as db:
        if mode == 'bulk':
            result = sync_bulk(db, start_year=start_year)
        else:
            result = sync_daily(db)
        db.commit()

        # 자동 계약 생성
        auto_result = {'created': 0, 'skipped': 0}
        if not no_auto_contract:
            auto_result = auto_create_contracts(db)
            db.commit()

    click.echo(f"[G2B] {mode} 완료: 신규 {result['created']}건, 갱신 {result['updated']}건"
               + (f", 오류 {result['errors']}건" if result.get('errors') else ''))
    if auto_result['created']:
        click.echo(f"[G2B] 자동계약: {auto_result['created']}건 생성, {auto_result['skipped']}건 스킵")


@app.cli.command('sync-g2b-changes')
def sync_g2b_changes_cli():
    """활성 계약 대상 변경계약 + 납품기한 변경 감지 (crontab용)"""
    from modules.db_context import get_db
    from modules.services.g2b_procurement_sync import sync_changes

    with get_db() as db:
        result = sync_changes(db)
        db.commit()

    click.echo(
        f"[G2B변경] 완료: 갱신 {result['updated']}건, "
        f"납품기한수정 {result.get('date_fixed', 0)}건, "
        f"수량수정 {result.get('qty_fixed', 0)}건, "
        f"품목재정렬 {result.get('reconciled', 0)}건, "
        f"계약취소 {result.get('cancelled', 0)}건, "
        f"수동확인 {result.get('needs_review', 0)}건"
    )


@app.cli.command('sync-g2b-quantities')
@click.option('--apply', 'do_apply', is_flag=True, help='실제 반영 (없으면 미리보기만)')
def sync_g2b_quantities_cli(do_apply):
    """G2B 최종 변경차수 수량 → 계약품목/납품 계획수량 반영 (기존건 백필용).

    기본은 미리보기(dry-run). 실제 반영은 --apply 필요.
    """
    from modules.db_context import get_db
    from modules.services.g2b_procurement_sync import sync_item_quantities

    with get_db() as db:
        result = sync_item_quantities(db, dry_run=not do_apply)
        if do_apply:
            db.commit()

    mode = '반영' if do_apply else '미리보기'
    for c in result['changes']:
        click.echo(f"  [수량] {c['g2b_no']} {c['chg_ord']}차({c['method']}) — {c['detail']}"
                   f"  | {(c['contract_name'] or '')[:35]}")
    for c in result['reconciles']:
        click.echo(f"  [품목] {c['g2b_no']} {c['chg_ord']}차 — {c['detail']}"
                   f"  | {(c['contract_name'] or '')[:35]}")
    for c in result['cancels']:
        click.echo(f"  [취소] {c['g2b_no']} {c['chg_ord']}차 — {c['detail']}"
                   f"  | {(c['contract_name'] or '')[:35]}")
    for r in result['reviews']:
        click.echo(f"  [확인] {r['g2b_no']} — {r['reason']}  | {(r['contract_name'] or '')[:35]}")
    click.echo(
        f"[G2B수량:{mode}] 수량수정 {result['qty_fixed']}건(품목 {result['items_fixed']}), "
        f"품목재정렬 {result['reconciled']}건, 계약취소 {result['cancelled']}건, "
        f"수동확인 {result['needs_review']}건"
    )


@app.cli.command('check-delivery-overdue')
@click.option('--dry-run', is_flag=True, help='발송 없이 대상만 출력')
def check_delivery_overdue_cli(dry_run):
    """납품예정시각 경과 회차 → 담당자에게 카카오워크 확인 DM (crontab용).

    scheduled_time 이 없으면 DELIVERY_DUE_HOUR(기본 18시)를 마감시각으로 본다.
    같은 회차에 하루 두 번 묻지 않는다.
    """
    from modules.db_context import get_db
    from modules.services.delivery_reminder import run_delivery_checks

    with get_db() as db:
        result = run_delivery_checks(db, dry_run=dry_run)
        if not dry_run:
            db.commit()

    for it in result['items']:
        click.echo(f"  [DM] {it['label']} → {it['owner']} ({it['elapsed']}일 경과)")
    for u in result['unassigned_items']:
        click.echo(f"  [담당자없음] {u['label']} (contact_name={u['contact_name']!r})")
    click.echo(
        f"[납품확인{':미리보기' if dry_run else ''}] 대상 {result['total']}건 — "
        f"DM {result['sent']}건, 담당자없음 {result['unassigned']}건, 오늘이미발송 {result['skipped']}건"
    )


@app.cli.command('audit-g2b-drift')
def audit_g2b_drift_cli():
    """G2B 원본 ↔ ERP 전 필드 대조 감사 (읽기 전용, crontab용).

    G2B→ERP는 '생성 시 1회 복사' 구조라 원본이 바뀌어도 ERP는 스냅샷으로 남는다.
    어긋난 필드를 사람이 발견하기 전에 로그로 먼저 드러내는 것이 목적.
    수정하지 않고 알림도 보내지 않는다 — 로그만 남긴다.
    """
    from modules.db_context import get_db
    from modules.services.g2b_drift_audit import audit_g2b_drift

    with get_db() as db:
        result = audit_g2b_drift(db)

    findings = result['findings']
    total = sum(len(v) for v in findings.values())
    click.echo(f"[G2B감사] 활성 계약 {result['total']}건 대조 — 불일치 {total}건")
    for category in sorted(findings):
        rows = findings[category]
        click.echo(f"  ── {category} {len(rows)}건")
        for r in rows:
            click.echo(f"     {r['g2b_no']} | {(r['contract_name'] or '')[:30]} | {r['detail']}")


@app.cli.command('fix-contract-item-groups')
@click.option('--apply', 'do_apply', is_flag=True, help='실제 반영 (없으면 미리보기만)')
def fix_contract_item_groups_cli(do_apply):
    """계약 뱃지(item_group)를 실제 계약품목 기준으로 정정.

    item_group 이 실제 품목군에 없는 계약만 고친다 (담당자가 고른 유효값은 보존).
    """
    from modules.db_context import get_db
    from modules.services.g2b_drift_audit import sync_contract_item_groups

    with get_db() as db:
        result = sync_contract_item_groups(db, dry_run=not do_apply)
        if do_apply:
            db.commit()

    for c in result['changes']:
        mark = '[활성]' if c['active'] else '     '
        click.echo(f"  {mark} {c['g2b_no']}: '{c['old']}' → '{c['new']}'  실제={c['cats']}"
                   f"  | {(c['contract_name'] or '')[:32]}")
    click.echo(
        f"[품목군:{'반영' if do_apply else '미리보기'}] {result['fixed']}건 "
        f"(활성 {result['logged']}건만 히스토리 기록)"
    )


@app.cli.command('normalize-project-org-names')
@click.option('--apply', 'do_apply', is_flag=True, help='실제 반영 (없으면 미리보기만)')
def normalize_project_org_names_cli(do_apply):
    """현장 수요기관명(projects.short_name)에 전남광주 통합 표기 적용.

    G2B 값으로 덮어쓰지 않고 기존 값에 normalize_org_name()만 적용한다
    (short_name은 담당자가 직접 수정하는 필드라 수정분을 보존해야 함).
    """
    from modules.db_context import get_db
    from modules.services.g2b_drift_audit import normalize_project_org_names

    with get_db() as db:
        result = normalize_project_org_names(db, dry_run=not do_apply)
        if do_apply:
            db.commit()

    for c in result['changes']:
        if c['active']:
            click.echo(f"  [활성] {c['project_no']}: {c['old']} → {c['new']}")
    click.echo(
        f"[수요기관명:{'반영' if do_apply else '미리보기'}] "
        f"{result['fixed']}건 (활성 {result['logged']}건만 히스토리 기록)"
    )


@app.cli.command('cleanup-mail-files')
def cleanup_mail_files_cli():
    """만료된 대용량 메일 첨부파일 삭제 (crontab용)"""
    from modules.db_context import get_db
    from modules.models.mail_entities import MailLargeFile
    from modules import storage_adapter

    now = datetime.datetime.now()
    deleted = 0
    with get_db() as db:
        expired = db.query(MailLargeFile).filter(
            MailLargeFile.expires_at < now,
            MailLargeFile.is_deleted == False,
        ).all()
        for record in expired:
            storage_adapter.delete_object(record.storage_path)
            ext = os.path.splitext(record.storage_path)[1] or ''
            cache_file = f'/tmp/mail_dl_cache/{record.file_id}{ext}'
            if os.path.exists(cache_file):
                os.remove(cache_file)
            record.is_deleted = True
            deleted += 1
        db.commit()
    click.echo(f"[메일정리] 만료 파일 {deleted}건 삭제")


@app.cli.command('update-trip-status')
def update_trip_status_cli():
    """출장 저장 status 를 날짜 기준 실제 상태로 보정 (crontab용, 멱등).

    표시(MCP/웹/대시보드)는 이미 유효상태를 계산하므로 이 보정 없이도 정상 동작하나,
    DB 직접 열람·저장값 의존 화면의 정합성을 위해 주기 실행한다."""
    from modules.db_context import get_db
    from modules.services.business_trip_status import reconcile_stored_status

    with get_db() as db:
        result = reconcile_stored_status(db)
        db.commit()
    detail = ", ".join(f"{k} {v}건" for k, v in result["changes"].items()) or "변경 없음"
    click.echo(f"[출장상태] 보정 {result['updated']}건 — {detail}")


@app.cli.command('sync-hometax-invoices')
@click.option('--from', 'from_date', default=None, help='수집 시작일 YYYY-MM-DD (없으면 최근 10일)')
@click.option('--to', 'to_date', default=None, help='수집 종료일 YYYY-MM-DD (없으면 오늘)')
def sync_hometax_invoices_cli(from_date, to_date):
    """홈택스 공동인증서로 매입/매출 세금계산서 수집 (crontab용).

    초기 대량 소급은 연도별로 분할 실행 권장:
      flask sync-hometax-invoices --from 2011-01-01 --to 2011-12-31
    """
    from modules.services.hometax_collector import run_collection

    begin = datetime.datetime.strptime(from_date, '%Y-%m-%d').date() if from_date else None
    end = datetime.datetime.strptime(to_date, '%Y-%m-%d').date() if to_date else None

    result = run_collection(begin, end)
    if result.get('ok'):
        click.echo(f"[홈택스] {result['message']}")
    else:
        click.echo(f"[홈택스] 실패: {result['message']}")


@app.route('/health')
def health_check():
    """헬스체크 — 로드밸런서/모니터링용"""
    from flask import jsonify as _jsonify
    from modules.db_context import get_db
    from sqlalchemy import text as _text
    try:
        with get_db() as db:
            db.execute(_text('SELECT 1'))
        return _jsonify({'status': 'healthy', 'timestamp': datetime.datetime.now().isoformat()}), 200
    except Exception as e:
        return _jsonify({'status': 'unhealthy', 'error': str(e)}), 503


@app.cli.command('check-notifications')
def check_notifications_cli():
    """일일 알림 점검 — 납품기한/입고지연/안전재고/서류마감/하자보증/인증서 (crontab: 매일 08:30)"""
    from modules.services.notification_scheduler import run_daily_notification_checks
    run_daily_notification_checks()
    click.echo("[알림] 일일 알림 점검 완료")


@app.cli.command('cleanup-notifications')
def cleanup_notifications_cli():
    """90일 이상 된 읽은 알림 삭제 (crontab: 매주 일 03:00)"""
    from modules.services.notification_scheduler import cleanup_old_notifications
    cleanup_old_notifications()
    click.echo("[알림] 만료 알림 정리 완료")


@app.cli.command('check-leave-promotions')
@click.option('--dry', is_flag=True, help='기록/발송 없이 대상자만 미리보기 (read-only)')
def check_leave_promotions_cli(dry):
    """연차사용촉진 점검 — 대상 산출 → 1차 촉구 메일 + 인사관리자 명단 알림 (crontab: 매일 09:00)"""
    from modules.db_context import get_db
    from modules.services import leave_promotion_service as lp
    with get_db() as db:
        if dry:
            cand = lp.candidates(db)
            names = ', '.join('%s(%s)' % (c['user'].full_name, c['stage'])
                              for c in cand['first']) or '없음'
            click.echo("[연차촉진/DRY] 1회차 대상 %d명: %s | 2회차 대상 %d명 (기록·발송 안 함)"
                       % (len(cand['first']), names, len(cand['second'])))
            return
        out = lp.run_promotion_cycle(db, do_email=True, do_notify=True)
        db.commit()
    click.echo("[연차촉진] 발송 %d (2회차 %d) · 메일 %d"
               % (out['recorded'], out['second'], out['emailed']))


@app.cli.command('remind-pending-approvals')
def remind_pending_approvals_cli():
    """미결재(현재 차례) 결재문서 독촉 — 결재자별 ERP+MM+카카오 DM (crontab: 매일 09:00)"""
    from modules.db_context import get_db
    from modules.services import approval_service as svc
    with get_db() as db:
        n_appr, n_docs = svc.send_pending_reminders(db)
        db.commit()
    click.echo("[미결재알림] 결재자 %d명 / 문서 %d건 발송" % (n_appr, n_docs))


# =====================================================================
# 백그라운드 스케줄러 (출장 상태 자동 업데이트 등)
# - 개발: Werkzeug reloader 자식 프로세스에서만 실행 (이중 실행 방지)
# - 운영: gunicorn 프로세스에서 바로 실행
# =====================================================================
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    init_scheduler(app)


if __name__ == '__main__':
    init_db()
    host = app.config.get("HOST", "0.0.0.0")
    port = app.config.get("PORT", 8501)
    debug = app.config.get("DEBUG", True)
    app.run(host=host, debug=debug, port=port, use_reloader=debug)
