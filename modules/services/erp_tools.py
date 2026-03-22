"""ERP 챗봇 툴 브릿지 — light_sync_mcp/tools_registry.py를 직접 호출
MCP만 업데이트하면 챗봇 툴도 자동으로 최신화됨
"""
from light_sync_mcp.tools_registry import register_all

# 조회 권한 설정 — 챗봇 관리 UI 표시용
ALL_TOOLS = [
    # 재고 (5)
    ("get_inventory",           "재고 현황",          "전체"),
    ("get_low_stock",           "재고 부족 목록",      "전체"),
    ("get_inventory_turnover",  "재고 회전율",         "전체"),
    ("get_stock_movements",     "재고 변동 이력",      "전체"),
    ("get_inventory_valuation", "재고 평가액",         "전체"),
    # 현장/프로젝트 (6)
    ("get_projects",            "현장 목록/검색",      "전체"),
    ("get_project_detail",      "현장 상세",           "전체"),
    ("search_projects",         "현장 통합검색",       "전체"),
    ("get_overdue_projects",    "납기 초과 현장",      "전체"),
    ("get_delivery_summary",    "납품 집계",           "전체"),
    ("get_project_timeline",    "현장 타임라인",       "전체"),
    # 생산 (4)
    ("get_production_status",   "생산 현황",           "전체"),
    ("get_production_by_site",  "현장별 생산 카드",    "전체"),
    ("get_worker_assignments",  "작업자 배치",         "전체"),
    ("get_fab_status",          "FAB 공정 현황",       "전체"),
    # BOM/품목 (6)
    ("get_bom_list",            "BOM 목록",            "전체"),
    ("get_bom_detail",          "BOM 상세",            "전체"),
    ("get_bom_stock_status",    "BOM 재고 충족 여부",  "전체"),
    ("calculate_bom_cost",      "BOM 원가 계산",       "전체"),
    ("get_items",               "품목 목록",           "전체"),
    ("search_items",            "품목 검색",           "전체"),
    # 조달/발주 (4)
    ("get_purchase_orders",     "발주서 목록",         "전체"),
    ("get_po_detail",           "발주서 상세",         "전체"),
    ("get_receiving_history",   "입고 이력",           "전체"),
    ("get_vendor_list",         "거래처 목록",         "전체"),
    # 재무 (4)
    ("get_revenue_summary",     "매출 집계",           "관리부/임원진"),
    ("get_financial_overview",  "재무 대시보드",       "관리부/임원진"),
    ("get_unpaid_invoices",     "미수금 현황",         "관리부/임원진"),
    ("get_tax_invoices",        "세금계산서 목록",     "관리부/임원진"),
    # 견적서 (3)
    ("get_quotations",          "견적서 목록",         "전체"),
    ("get_quotation_detail",    "견적서 상세",         "전체"),
    ("get_quote_templates",     "견적 템플릿",         "전체"),
    # 납품 (3)
    ("get_deliveries",          "납품 현황",           "전체"),
    ("get_delivery_detail",     "납품 상세",           "전체"),
    ("get_delivery_status_summary", "납품 상태 요약",  "전체"),
    # AS/보증 (3)
    ("get_warranty_cases",      "AS 케이스 목록",      "전체"),
    ("get_warranty_case_detail","AS 케이스 상세",      "전체"),
    ("get_warranty_stats",      "AS 통계",             "전체"),
    # 영업 (2)
    ("get_sales_projects",      "영업 현장 목록",      "전체"),
    ("get_contract_items_status","계약품목 상태",      "전체"),
    # 도면 (2)
    ("get_drawings",            "도면 목록",           "전체"),
    ("get_drawing_versions",    "도면 버전",           "전체"),
    # 카탈로그 (2)
    ("get_catalog_products",    "제품 카탈로그",       "전체"),
    ("get_catalog_price",       "제품 단가 조회",      "전체"),
    # 계약 (2)
    ("get_contracts",           "계약 목록",           "전체"),
    ("get_contract_detail",     "계약 상세",           "전체"),
    # 일일업무보고 (2)
    ("get_daily_reports",       "일일보고 목록",       "전체"),
    ("get_daily_report_detail", "일일보고 상세",       "전체"),
    # 알림 (2)
    ("get_notifications",       "알림 목록",           "전체"),
    ("get_unread_notification_count", "미읽은 알림 수","전체"),
    # 오버뷰 (1)
    ("get_project_progress",    "프로젝트 진행률",     "전체"),
    # 아카이브 (2)
    ("search_archive",          "아카이브 검색",       "전체"),
    ("get_archive_post_detail", "아카이브 상세",       "전체"),
    # G2B 조달 (2)
    ("get_g2b_contract_detail", "G2B 계약 상세",       "전체"),
    ("get_warranty_by_g2b",     "G2B 하자보증 조회",   "전체"),
    # 인증서 (1)
    ("get_cert_expiry_alerts",  "인증서 만료 알림",    "전체"),
    # 시방서 (1)
    ("get_spec_doc_status",     "시방서 현황",         "전체"),
    # 조명배치도 (2)
    ("get_lighting_layouts",    "조명배치도 목록",     "전체"),
    ("get_lighting_layout_detail", "배치도 상세",      "전체"),
    # 조도검증 (2)
    ("get_illuminance_projects","조도 프로젝트 목록",  "전체"),
    ("get_illuminance_detail",  "조도 상세/KS판정",    "전체"),
    # 직원/근무 (2)
    ("get_employees",           "직원 목록",           "전체"),
    ("get_today_attendance",    "오늘 근무인원",       "전체"),
    # 가공발주 (2)
    ("get_processing_orders",   "가공발주 목록",       "전체"),
    ("get_processing_order_detail", "가공발주 상세",   "전체"),
]

RESTRICTED_TOOLS = {
    "get_revenue_summary", "get_financial_overview",
    "get_unpaid_invoices", "get_tax_invoices",
}


class _MCPBridge:
    """FastMCP를 duck-typing하여 툴 함수를 직접 캡처"""
    def __init__(self):
        self._tools = {}

    def tool(self, **kwargs):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator

    def resource(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


_bridge = _MCPBridge()
register_all(_bridge)
TOOL_FUNCTIONS: dict = _bridge._tools


def check_permission(erp_username: str, tool_name: str) -> bool:
    if tool_name not in RESTRICTED_TOOLS:
        return True
    from modules.models.entities import User
    from modules.db_context import get_db
    with get_db() as db:
        user = db.query(User).filter_by(username=erp_username).first()
    group = user.user_group if user else ""
    return group in ("관리부", "최고관리자", "임원진")
