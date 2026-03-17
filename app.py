from flask import Flask, redirect, url_for, request
import os
from modules.models import init_db
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.project import project_bp
from routes.contract import contract_bp
from routes.technical import tech_bp # 💡 사장님 조도계산 모듈 복구
from routes.drawing import drawing_bp
from routes.sales import sales_bp
from routes.production import production_bp
from routes.delivery import delivery_bp

# =====================================================================
# ⚠️ 운영 고정 설정 잠금 구역 (수정 금지)
# - 외부 접속 도메인: work.mgnt.kr
# - 서버 바인딩: 0.0.0.0:8501
# - 아래 값은 운영 접속/라우팅 기준값이므로 변경하지 마세요.
# - 변경이 필요하면 app.py 직접 수정 대신 배포 담당자 승인 후 진행.
# =====================================================================
LOCKED_DOMAIN = "work.mgnt.kr"
LOCKED_HOST = "0.0.0.0"
LOCKED_PORT = 8501
LOCKED_DEBUG = True
LOCKED_AUTO_RELOAD = True

app = Flask(__name__)
app.secret_key = "light_sync_secret"
app.config["SERVER_NAME"] = LOCKED_DOMAIN
app.config["PREFERRED_URL_SCHEME"] = "https"
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.before_request
def force_locked_domain():
    """운영 도메인 강제: 다른 Host로 접근 시 work.mgnt.kr로 리다이렉트"""
    host_only = (request.host or '').split(':')[0].lower()
    if host_only and host_only not in {LOCKED_DOMAIN, 'localhost', '127.0.0.1'}:
        target = f"https://{LOCKED_DOMAIN}{request.full_path}"
        if target.endswith('?'):
            target = target[:-1]
        return redirect(target, code=301)

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(project_bp)
app.register_blueprint(contract_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(production_bp)
app.register_blueprint(delivery_bp)
app.register_blueprint(tech_bp) # 💡 등록 확인
app.register_blueprint(drawing_bp)

@app.route('/')
def index():
    return redirect(url_for('dashboard.dashboard_view'))

if __name__ == '__main__':
    init_db()
    # ⚠️ 운영 고정값: app.py 수정으로 바뀌지 않도록 환경변수보다 고정 상수를 우선 사용
    # (필요 시 배포 담당자가 LOCKED_* 값만 공식 절차로 변경)
    host = LOCKED_HOST
    port = LOCKED_PORT
    debug = LOCKED_DEBUG
    app.run(host=host, debug=debug, port=port, use_reloader=LOCKED_AUTO_RELOAD)