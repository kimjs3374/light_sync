import os
import logging
import warnings
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")
from logging.handlers import RotatingFileHandler
from flask import Flask, redirect, url_for, request, session, render_template
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import ProductionConfig, DevelopmentConfig, MENU_REGISTRY, COMMON_MENU_KEYS
from modules.models import init_db
from routes.auth import auth_bp
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
from routes.bom import bom_bp
from routes.item import item_bp
from modules.pagination import pagination_query

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
app.json.ensure_ascii = False

# Logging
os.makedirs('logs', exist_ok=True)
file_handler = RotatingFileHandler('logs/light_sync.log', maxBytes=10_000_000, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s [%(name)s] %(message)s'
))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.jinja_env.auto_reload = app.config.get("TEMPLATES_AUTO_RELOAD", True)
app.jinja_env.globals['pagination_query'] = pagination_query

# CSRF Protection
csrf = CSRFProtect(app)

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
app.register_blueprint(bom_bp)
app.register_blueprint(item_bp)
app.register_blueprint(api_bp)

# NAS 동기화 API는 외부(NAS cron)에서 호출하므로 CSRF 면제
csrf.exempt(api_bp)


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

    menu_groups = {}
    for key, info in MENU_REGISTRY.items():
        if key in COMMON_MENU_KEYS:
            continue
        if info.get("admin_only") and not is_admin:
            continue
        if is_admin or is_executive or key in allowed:
            menu_groups.setdefault(info["group"], []).append({
                "key": key,
                "label": info["label"],
                "url": url_for(info["endpoint"]),
            })

    return {
        "sidebar_menu_groups": menu_groups,
        "is_admin": is_admin,
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


@app.route('/')
def index():
    return redirect(url_for('dashboard.dashboard_view'))


# =====================================================================
# Flask CLI Commands (crontab에서 호출)
# =====================================================================
import click

@app.cli.command('sync-g2b')
@click.option('--mode', default='daily', help='daily: 전일 동기화, bulk: 전체 동기화')
@click.option('--start-year', default=2012, help='벌크 동기화 시작 연도')
def sync_g2b_cli(mode, start_year):
    """나라장터 조달내역 동기화 (crontab용)"""
    from modules.db_context import get_db
    from modules.services.g2b_procurement_sync import sync_daily, sync_bulk

    with get_db() as db:
        if mode == 'bulk':
            result = sync_bulk(db, start_year=start_year)
        else:
            result = sync_daily(db)
        db.commit()

    click.echo(f"[G2B] {mode} 완료: 신규 {result['created']}건, 갱신 {result['updated']}건"
               + (f", 오류 {result['errors']}건" if result.get('errors') else ''))


if __name__ == '__main__':
    init_db()
    host = app.config.get("HOST", "0.0.0.0")
    port = app.config.get("PORT", 8501)
    debug = app.config.get("DEBUG", True)
    app.run(host=host, debug=debug, port=port, use_reloader=debug)
