import os
import secrets
from collections import OrderedDict
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


# =====================================================================
# 메뉴 권한 레지스트리
# =====================================================================
MENU_REGISTRY = OrderedDict([
    # --- 공통 (권한 체크 없이 항상 표시) ---
    ("dashboard",      {"label": "메인 현황판", "group": "공통",   "endpoint": "dashboard.dashboard_view"}),
    ("overview",       {"label": "종합현황",   "group": "공통",   "endpoint": "overview.project_overview"}),
    ("daily_report",   {"label": "업무보고",   "group": "공통",   "endpoint": "daily_report.daily_report_view"}),
    # --- 영업부 ---
    ("project",        {"label": "설계관리",   "group": "영업부", "endpoint": "project.project_list"}),
    ("contract",       {"label": "계약관리",   "group": "영업부", "endpoint": "project.contract_list"}),
    ("sales",          {"label": "영업관리",   "group": "영업부", "endpoint": "sales.sales_list"}),
    ("delivery",       {"label": "납품관리",   "group": "영업부", "endpoint": "delivery.delivery_management"}),
    # --- 관리부 ---
    ("item",           {"label": "품목관리",   "group": "관리부", "endpoint": "item.item_list"}),
    ("material",       {"label": "자재관리",   "group": "관리부", "endpoint": "material.material_management"}),
    ("vendor",         {"label": "거래처관리", "group": "관리부", "endpoint": "vendor.vendor_list"}),
    ("purchase_order", {"label": "발주관리",   "group": "관리부", "endpoint": "purchase_order.po_list"}),
    ("receiving",      {"label": "입고관리",   "group": "관리부", "endpoint": "receiving.receiving_list"}),
    ("bom",            {"label": "BOM관리",   "group": "관리부", "endpoint": "bom.bom_list"}),
    ("financial",      {"label": "매출/수금",  "group": "관리부", "endpoint": "financial.financial_dashboard"}),
    ("inventory",      {"label": "재고관리",  "group": "관리부", "endpoint": "inventory.inventory_dashboard"}),
    # --- 공유 (여러 부서 공통) ---
    ("procurement",    {"label": "조달내역",   "group": "공유",   "endpoint": "procurement.procurement_list"}),
    ("procurement_summary", {"label": "납품집계", "group": "공유",   "endpoint": "procurement.procurement_summary"}),
    ("warranty",       {"label": "하자관리",   "group": "공유",   "endpoint": "warranty.warranty_list"}),
    # --- 생산부 ---
    ("production",     {"label": "생산관리",   "group": "생산부", "endpoint": "production.production_management"}),
    # --- 시스템 (admin only) ---
    ("admin_settings", {"label": "시스템관리", "group": "시스템", "endpoint": "auth.admin_settings", "admin_only": True}),
])

COMMON_MENU_KEYS = {"dashboard", "overview", "daily_report"}

# 부서별 기본 메뉴 (GroupPermission 초기값 세팅용)
DEFAULT_GROUP_MENUS = {
    "영업부": "project,contract,sales,delivery,procurement,procurement_summary,warranty",
    "관리부": "item,material,vendor,purchase_order,receiving,bom,financial,inventory,procurement,procurement_summary,warranty",
    "생산부": "production,warranty",
    "임원진": "project,contract,sales,delivery,item,material,vendor,purchase_order,receiving,bom,financial,inventory,procurement,procurement_summary,warranty,production",
}


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    DEBUG = True
    WTF_CSRF_SSL_STRICT = False  # HTTPS Referer 검증 비활성화 (AJAX CSRF 호환)

    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Server
    HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
    PORT = int(os.environ.get('FLASK_PORT', 8501))
    DOMAIN = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')

    # File upload limit
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

    # Template auto reload
    TEMPLATES_AUTO_RELOAD = True


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
