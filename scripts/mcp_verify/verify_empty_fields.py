"""MCP Tool 반환값 검증기 — 항상 빈값/0인 필드 = 유령 컬럼 의심"""
import sys, json, inspect
sys.path.insert(0, '/web/light_sync')
from dotenv import load_dotenv
load_dotenv('/web/light_sync/.env')

TOOLS = {}


class FakeMCP:
    def tool(self, *a, **k):
        def deco(fn):
            TOOLS[fn.__name__] = fn
            return fn
        return deco

    def resource(self, uri, *a, **k):
        def deco(fn):
            return fn
        return deco


from light_sync_mcp.tools_registry import register_all
register_all(FakeMCP())


def pick(tool, key, **kw):
    try:
        d = json.loads(TOOLS[tool](**kw))
    except Exception:
        return None
    lst = d if isinstance(d, list) else next((v for v in d.values() if isinstance(v, list)), [])
    for it in lst:
        if isinstance(it, dict) and it.get(key) is not None:
            return it[key]
    return None


emp = json.loads(TOOLS['get_employees']())['employees'][0]
mail_user = (emp.get('email') or '').split('@')[0]

CALLS = {
    'get_projects': {}, 'search_projects': {'query': '조명'},
    'get_project_detail': {'project_id': 2933}, 'get_project_timeline': {'project_id': 2933},
    'get_project_contacts': {}, 'get_project_progress': {}, 'get_overdue_projects': {},
    'get_delivery_summary': {},
    'get_contracts': {}, 'get_contract_detail': {'contract_id': 4075},
    'get_g2b_contract_detail': {'search': '조명'}, 'list_recent_g2b_contracts': {},
    'get_warranty_by_g2b': {'search': '조명'},
    'get_revenue_summary': {'year': 2025}, 'get_purchase_summary': {'year': 2025},
    'get_tax_invoices': {'year': 2025}, 'get_financial_overview': {'year': 2025},
    'get_unpaid_invoices': {},
    'get_deliveries': {}, 'get_delivery_detail': {'delivery_id': 95},
    'get_delivery_status_summary': {},
    'get_production_status': {}, 'get_production_by_site': {},
    'get_process_summary': {}, 'get_work_logs': {'date_from': '2020-01-01'},
    'get_inventory': {}, 'get_low_stock': {}, 'get_inventory_valuation': {},
    'get_stock_movements': {}, 'get_inventory_consumption': {},
    'get_inventory_turnover': {'year': 2025},
    'get_bom_list': {}, 'get_bom_detail': {'bom_id': 142},
    'calculate_bom_cost': {'bom_id': 142}, 'get_bom_stock_status': {'bom_id': 142},
    'get_items': {}, 'search_items': {'query': '조명'},
    'get_purchase_orders': {}, 'get_po_detail': {'po_id': 89},
    'get_receiving_history': {}, 'get_receiving_detail': {'rcv_id': 202},
    'get_vendor_list': {}, 'get_material_orders': {},
    'get_material_orders_by_project': {'project_id': 2933},
    'get_incoming_overview': {}, 'get_billing_status': {},
    'get_quotations': {}, 'get_quotation_detail': {'quotation_id': 37},
    'get_quote_templates': {},
    'get_sales_projects': {}, 'get_contract_items_status': {'project_id': 2933},
    'get_warranty_cases': {}, 'get_warranty_case_detail': {'case_id': 166},
    'get_warranty_stats': {},
    'get_drawings': {}, 'get_drawing_versions': {'drawing_id': 71},
    'get_catalog_products': {}, 'get_catalog_price': {'product_name': '조명타워'},
    'get_cert_expiry_alerts': {}, 'get_spec_doc_status': {},
    'get_lighting_layouts': {}, 'get_lighting_layout_detail': {'tower_id': 3},
    'get_illuminance_projects': {}, 'get_illuminance_detail': {'project_id': 10},
    'get_daily_reports': {}, 'get_notifications': {},
    'get_unread_notification_count': {'user_id': 1},
    'get_dashboard_summary': {}, 'search_archive': {'query': '조명'},
    'get_archive_post_detail': {'post_id': 510780}, 'get_site_history': {'project_id': 2933},
    'get_employees': {}, 'get_today_attendance': {},
    'get_leave_balance': {}, 'get_leave_calendar': {},
    'get_leave_promotion_status': {}, 'get_employee_card': {'employee': '김선중'},
    'get_approval_documents': {}, 'get_approval_detail': {'doc_no': 'EA-2026-0008'},
    'get_my_pending_approvals': {'requester_username': 'kkw6266'},
    'get_my_approval_drafts': {'requester_username': 'kkw6266'},
    'get_processing_orders': {}, 'get_processing_order_detail': {'fo_id': 54},
    'get_business_trips': {}, 'get_business_trip_detail': {'trip_id': 135},
    'get_document_list': {}, 'get_document_detail': {'package_id': 93},
    'get_tools_list': {}, 'get_activity_logs': {},
    'get_vehicle_logs': {}, 'get_vehicle_log_summary': {},
    'get_dept_weekly_report': {'dept': '관리부'},
    'get_email_history': {}, 'get_mail_contacts': {},
    'list_mail_accounts': {'requester_username': mail_user},
}

EMPTY = ("", 0, None, False, [], {}, "0")


def collect_rows(obj, depth=0):
    """JSON 안의 dict 리스트들을 (경로, rows) 로 수집"""
    out = []
    if depth > 3:
        return out
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if len(dicts) >= 2:
            out.append(dicts)
        for x in dicts[:3]:
            out += collect_rows(x, depth + 1)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                dicts = [x for x in v if isinstance(x, dict)]
                if len(dicts) >= 2:
                    out.append(dicts)
                for x in dicts[:3]:
                    out += collect_rows(x, depth + 1)
    return out


print(f"검증 대상 {len(CALLS)}개 Tool\n")
suspects = []
errors = []

for name, kw in CALLS.items():
    if name not in TOOLS:
        errors.append((name, 'TOOL 없음'))
        continue
    try:
        raw = TOOLS[name](**kw)
        data = json.loads(raw)
    except Exception as e:
        errors.append((name, f'{type(e).__name__}: {e}'))
        continue

    for rows in collect_rows(data):
        if len(rows) < 2:
            continue
        keys = set()
        for r in rows:
            keys |= set(r.keys())
        for k in sorted(keys):
            vals = [r.get(k) for r in rows]
            if all(v in EMPTY for v in vals):
                suspects.append((name, k, len(rows)))

print("=== 전 행이 빈값/0 인 필드 (유령 컬럼 의심) ===")
if suspects:
    seen = set()
    for n, k, cnt in suspects:
        if (n, k) in seen:
            continue
        seen.add((n, k))
        print(f"  {n:32} .{k:24} ({cnt}행 전부 비어있음)")
else:
    print("  없음")

print("\n=== 호출 오류 ===")
for n, e in errors:
    print(f"  {n:32} {e}")
if not errors:
    print("  없음")
