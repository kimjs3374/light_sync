import os
import secrets
from collections import OrderedDict
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv(override=True)


# =====================================================================
# 메뉴 권한 레지스트리
# =====================================================================
MENU_REGISTRY = OrderedDict([
    # --- 워크보드 (권한 체크 없이 항상 표시) ---
    ("dashboard",      {"label": "메인 현황판", "group": "워크보드", "endpoint": "dashboard.dashboard_view"}),
    ("overview",       {"label": "종합현황",   "group": "종합현황", "endpoint": "overview.project_overview"}),
    ("daily_report",   {"label": "일일보고",   "group": "업무보고", "endpoint": "daily_report.daily_report_view"}),
    ("weekly_report",  {"label": "주간보고",   "group": "업무보고", "endpoint": "report.weekly_report"}),
    ("approval",       {"label": "전자결재",   "group": "전자결재", "endpoint": "approval.approval_list"}),
    # --- 이메일 ---
    ("mail_shared",    {"label": "공용메일",  "group": "이메일", "endpoint": "mail.mail_shared"}),
    ("mail_personal",  {"label": "개인메일",  "group": "이메일", "endpoint": "mail.mail_personal"}),
    ("mail_external",  {"label": "외부메일",  "group": "이메일", "endpoint": "mail.mail_external"}),
    # --- 영업부 ---
    ("project",        {"label": "설계관리",   "group": "영업부", "endpoint": "project.project_list"}),
    ("contract",       {"label": "계약관리",   "group": "영업부", "endpoint": "project.contract_list"}),
    ("sales",          {"label": "협의관리",   "group": "영업부", "endpoint": "sales.sales_list"}),
    ("quotation",      {"label": "견적관리",   "group": "영업부", "endpoint": "quotation.quotation_list"}),
    ("delivery",       {"label": "납품관리",   "group": "영업부", "endpoint": "delivery.delivery_management"}),
    # --- 관리부 (구매/재무) ---
    ("vendor",         {"label": "거래처관리", "group": "관리부", "endpoint": "vendor.vendor_list"}),
    ("purchase_order", {"label": "발주관리",   "group": "관리부", "endpoint": "purchase_order.po_list"}),
    ("processing_order", {"label": "가공발주", "group": "관리부", "endpoint": "processing_order.fo_list"}),
    ("receiving",      {"label": "입고관리",   "group": "관리부", "endpoint": "receiving.receiving_list"}),
    ("financial",      {"label": "매출/수금",  "group": "관리부", "endpoint": "financial.financial_dashboard"}),
    ("billing",        {"label": "청구관리",  "group": "관리부", "endpoint": "billing.billing_list"}),
    # --- 자재/재고 ---
    ("item",           {"label": "품목관리",   "group": "자재/재고", "endpoint": "item.item_list"}),
    ("bom",            {"label": "BOM관리",   "group": "자재/재고", "endpoint": "bom.bom_list"}),
    ("material",       {"label": "자재관리",   "group": "자재/재고", "endpoint": "material.material_management"}),
    ("inventory",      {"label": "재고관리",  "group": "자재/재고", "endpoint": "inventory.inventory_dashboard"}),
    # --- 공통메뉴 (여러 부서 공통) ---
    ("procurement",    {"label": "조달내역",   "group": "공통메뉴",   "endpoint": "procurement.procurement_list"}),
    ("procurement_summary", {"label": "납품집계", "group": "공통메뉴",   "endpoint": "procurement.procurement_summary"}),
    ("warranty",       {"label": "하자관리",   "group": "공통메뉴",   "endpoint": "warranty.dashboard"}),
    ("receiving_photo", {"label": "입고사진",  "group": "공통메뉴",   "endpoint": "receiving_photo.feed"}),
    ("photos",         {"label": "사진관리",   "group": "공통메뉴",   "endpoint": "photos.photo_list"}),
    ("drawing",        {"label": "도면관리",   "group": "공통메뉴",   "endpoint": "drawing.drawings_index"}),
    ("catalog",        {"label": "제품목록",     "group": "영업부", "endpoint": "catalog.catalog_list"}),
    ("illuminance",    {"label": "조도검증",   "group": "영업부", "endpoint": "illuminance.index"}),
    ("lighting_layout",{"label": "조명배치도", "group": "영업부", "endpoint": "lighting_layout.layout_list"}),
    ("certification",  {"label": "인증서관리", "group": "관리부", "endpoint": "certification.cert_list"}),
    ("hr",             {"label": "인사관리",   "group": "관리부", "endpoint": "hr.hr_list"}),
    ("business_trip",  {"label": "출장관리",   "group": "공통메뉴", "endpoint": "business_trip.trip_list"}),
    ("vehicle_log",    {"label": "운행일지",   "group": "공통메뉴", "endpoint": "vehicle_log.log_list"}),
    ("tools",          {"label": "공구관리",   "group": "공통메뉴", "endpoint": "tools.tool_list"}),
    ("documents",      {"label": "서류관리",   "group": "영업부", "endpoint": "document.document_list"}),
    # --- 생산부 ---
    ("production",     {"label": "생산1팀",   "group": "생산부", "endpoint": "production.production_main_team1"}),
    ("production2",    {"label": "생산2팀",   "group": "생산부", "endpoint": "production.production_main_team2"}),
    ("incoming_overview", {"label": "발주/입고현황", "group": "생산부", "endpoint": "incoming_overview.incoming_overview_view"}),
    ("sample",         {"label": "시료관리",   "group": "생산부", "endpoint": "sample.sample_list"}),
    # --- 시스템 (admin only) ---
    ("admin_settings", {"label": "시스템관리", "group": "시스템", "endpoint": "auth.admin_settings", "admin_only": True}),
    ("workboard",      {"label": "현장관리",   "group": "워크보드", "endpoint": "workboard.workboard_list"}),
    ("asboard",        {"label": "A/S",        "group": "워크보드", "endpoint": "asboard.asboard_list"}),
    # --- 워크보드 (카카오워크 백업 보드, archive.* 동적 endpoint) ---
    ("wb_material",  {"label": "자재 발주 및 입고",      "group": "워크보드", "endpoint": "archive.list_material"}),
    ("wb_contract",  {"label": "계약서",               "group": "워크보드", "endpoint": "archive.list_contract"}),
    ("wb_equipment", {"label": "장비 및 운송비 사용관련", "group": "워크보드", "endpoint": "archive.list_equipment"}),
    ("wb_fab",       {"label": "제작 진행 현황",         "group": "워크보드", "endpoint": "archive.list_fab"}),
    ("wb_meeting",   {"label": "업무협의",             "group": "워크보드", "endpoint": "archive.list_meeting"}),
    ("wb_notice",    {"label": "공지사항",             "group": "워크보드", "endpoint": "archive.list_notice"}),
    ("approval_archive", {"label": "결재 문서대장",     "group": "워크보드", "endpoint": "approval_archive.archive_list"}),
    ("chat_archive",   {"label": "대화방",             "group": "워크보드", "endpoint": "chat_archive.room_list"}),
    ("chatbot_admin",  {"label": "챗봇 권한",  "group": "시스템", "endpoint": "chatbot.admin_page", "admin_only": True}),
    ("office",         {"label": "Office",     "group": "공통메뉴", "endpoint": "office.office_list", "always_show": True}),
])

COMMON_MENU_KEYS = {"dashboard", "overview", "daily_report", "weekly_report", "approval",
                    "mail_personal", "mail_shared", "mail_external"}

# 관리자도 비활성화할 수 없는 핵심 메뉴 (잠금 방지)
#  - dashboard: 로그인 후 기본 이동/리다이렉트 대상
#  - admin_only 메뉴(시스템관리·챗봇 권한): 다시 켜는 화면이므로 항상 유지
PROTECTED_MENU_KEYS = {"dashboard"}

# =====================================================================
# 카카오워크 워크보드 ↔ ERP 아카이브 보드 레지스트리 (단일 기준)
#   - 라우트(routes/archive_boards.py), 정규화(scripts/normalize_workboard.py),
#     메뉴(MENU_REGISTRY)가 모두 이 정의를 따른다.
#   slug     : board_type / URL(/board/<slug>) — 고정값, 변경 시 데이터 재정규화 필요
#   kakao    : public.workboard_posts.board_type (백업 원본 보드명)
#   label    : 사이드바 메뉴 라벨 (카카오워크 명칭 유지)
#   menu_key : MENU_REGISTRY 권한 키 (site/as는 기존 workboard/asboard 재사용)
#   builtin  : True면 별도 블루프린트(workboard/asboard)가 이미 라우트 보유
#              → archive_boards 일반 블루프린트는 등록 생략
# =====================================================================
#   board_id : 카카오워크 보드 id — Supabase Storage 첨부 키 경로에 사용
#              (archive/{board_id}/{post_id}/{att_id}{ext})
WORKBOARDS = OrderedDict([
    ("site",      {"kakao": "현장관리",              "label": "현장관리",              "menu_key": "workboard",    "builtin": True,  "board_id": 55771}),
    ("as",        {"kakao": "A/S 관리",             "label": "A/S",                  "menu_key": "asboard",      "builtin": True,  "board_id": 55773}),
    ("material",  {"kakao": "자재 발주 및 입고",       "label": "자재 발주 및 입고",       "menu_key": "wb_material",  "builtin": False, "board_id": 55772}),
    ("contract",  {"kakao": "계약서",                "label": "계약서",                "menu_key": "wb_contract",  "builtin": False, "board_id": 52401}),
    ("equipment", {"kakao": "장비 및 운송비 사용관련",  "label": "장비 및 운송비 사용관련",  "menu_key": "wb_equipment", "builtin": False, "board_id": 1693184}),
    ("fab",       {"kakao": "제작 진행 현황",          "label": "제작 진행 현황",          "menu_key": "wb_fab",       "builtin": False, "board_id": 55770}),
    ("meeting",   {"kakao": "업무협의",              "label": "업무협의",              "menu_key": "wb_meeting",   "builtin": False, "board_id": 70194}),
    ("notice",    {"kakao": "공지사항",              "label": "공지사항",              "menu_key": "wb_notice",    "builtin": False, "board_id": 52383}),
])

# slug → board_id 빠른 조회용
WORKBOARD_BOARD_IDS = {slug: m["board_id"] for slug, m in WORKBOARDS.items()}

# 사이드바 그룹 아이콘 매핑
GROUP_ICONS = {
    "워크보드": "📊",
    "종합현황": "📊",
    "전자결재": "📋",
    "업무보고": "📝",
    "이메일": "✉️",
    "영업부": "💼",
    "관리부": "📋",
    "자재/재고": "📦",
    "공통메뉴": "🔗",
    "생산부": "🏭",
    "시스템": "⚙️",
}

# 부서별 기본 메뉴 (GroupPermission 초기값 세팅용)
# 형식: "menu_key:r" (읽기전용) / "menu_key:rw" (읽기+쓰기) / "menu_key" (레거시=rw)
DEFAULT_GROUP_MENUS = {
    "영업부": "sample:r,project:rw,contract:rw,sales:rw,quotation:rw,delivery:rw,catalog:r,illuminance:rw,item:r,material:r,bom:r,inventory:r,procurement:rw,procurement_summary:r,warranty:rw,photos:rw,drawing:rw,production:r,production2:r,receiving_photo:rw,business_trip:rw,vehicle_log:rw",
    "관리부": "sample:rw,project:r,contract:r,delivery:r,item:rw,material:rw,vendor:rw,purchase_order:rw,receiving:rw,bom:rw,inventory:rw,certification:rw,procurement:r,procurement_summary:r,warranty:rw,photos:rw,drawing:r,production:r,production2:r,receiving_photo:rw,business_trip:rw,tools:r,incoming_overview:r,vehicle_log:rw",
    "생산부": "sample:rw,contract:r,sales:r,delivery:r,material:r,inventory:r,warranty:rw,photos:rw,drawing:r,production:rw,production2:rw,receiving_photo:rw,business_trip:rw,tools:rw,incoming_overview:r,vehicle_log:rw",
    "임원진": "sample:rw,project:rw,contract:rw,sales:rw,quotation:rw,delivery:rw,catalog:rw,illuminance:rw,item:rw,material:rw,vendor:rw,purchase_order:rw,receiving:rw,bom:rw,inventory:rw,procurement:rw,procurement_summary:rw,warranty:rw,photos:rw,drawing:rw,production:rw,production2:rw,certification:rw,receiving_photo:rw,business_trip:rw,tools:rw,incoming_overview:r,vehicle_log:rw",
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
    SESSION_COOKIE_SECURE = True   # Cloudflare HTTPS 종단 → Secure 쿠키 필수
