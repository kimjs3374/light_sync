import os
from flask import Flask, redirect, url_for, request, session
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import ProductionConfig, DevelopmentConfig
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
app.jinja_env.auto_reload = app.config.get("TEMPLATES_AUTO_RELOAD", True)

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
    """운영 도메인 강제: 다른 Host로 접근 시 work.mgnt.kr로 리다이렉트"""
    host_only = (request.host or '').split(':')[0].lower()
    if host_only and host_only not in {LOCKED_DOMAIN, 'localhost', '127.0.0.1'}:
        target = f"https://{LOCKED_DOMAIN}{request.full_path}"
        if target.endswith('?'):
            target = target[:-1]
        return redirect(target, code=301)


# =====================================================================
# Blueprint 등록
# =====================================================================
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(project_bp)
app.register_blueprint(contract_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(production_bp)
app.register_blueprint(delivery_bp)
app.register_blueprint(tech_bp)
app.register_blueprint(drawing_bp)


@app.route('/')
def index():
    return redirect(url_for('dashboard.dashboard_view'))


if __name__ == '__main__':
    init_db()
    host = app.config.get("HOST", "0.0.0.0")
    port = app.config.get("PORT", 8501)
    debug = app.config.get("DEBUG", False)
    app.run(host=host, debug=debug, port=port, use_reloader=debug)
