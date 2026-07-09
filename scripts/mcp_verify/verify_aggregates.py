"""집계 Tool 반환값 vs DB 직접 쿼리 대조"""
import sys, json
sys.path.insert(0, '/web/light_sync')
from dotenv import load_dotenv
load_dotenv('/web/light_sync/.env')
import os
from sqlalchemy import create_engine, text

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

eng = create_engine(os.getenv('DATABASE_URL'))


def db(sql):
    with eng.connect() as c:
        return c.execute(text(sql)).scalar()


def call(name, **kw):
    return json.loads(TOOLS[name](**kw))


results = []


def check(label, tool_val, db_val):
    ok = tool_val == db_val
    results.append((ok, label, tool_val, db_val))


# 1. 직원 수
check("get_employees.total",
      call('get_employees')['total'],
      db("select count(*) from light_sync.users where role <> 'pending'"))

# 2. 안전재고 미달
lo = call('get_low_stock')
lo_n = lo['count'] if isinstance(lo, dict) and 'count' in lo else len(
    lo if isinstance(lo, list) else lo.get('items', []))
check("get_low_stock 건수", lo_n,
      db("select count(*) from light_sync.items where safety_stock is not null "
         "and stock_qty < safety_stock"))

# 3. 재고 평가액
iv = call('get_inventory_valuation')
tot = iv.get('total_value') or iv.get('total_valuation') or iv.get('grand_total')
check("get_inventory_valuation 총액", tot,
      db("select round(sum(stock_qty * coalesce(last_unit_price,0)))::bigint "
         "from light_sync.items where is_active"))

# 4. 하자 케이스 총건수
ws = call('get_warranty_stats')
check("get_warranty_stats total", ws.get('total_cases') or ws.get('total'),
      db("select count(*) from light_sync.warranty_cases"))

# 5. 공정 집계 총건수
check("get_process_summary total_processes",
      call('get_process_summary')['total_processes'],
      db("select count(*) from light_sync.production_processes"))

# 6. 매출 (2025 공급가)
check("get_revenue_summary 2025 공급가",
      call('get_revenue_summary', year=2025)['grand_total_supply'],
      db("select sum(supply_amount) from light_sync.tax_invoices "
         "where direction='매출' and extract(year from issue_date)=2025"))

# 7. 매입 (2025 합계)
check("get_purchase_summary 2025 합계",
      call('get_purchase_summary', year=2025)['grand_total'],
      db("select sum(total_amount) from light_sync.tax_invoices "
         "where direction='매입' and extract(year from issue_date)=2025"))

# 8. 거래처 총수
check("get_vendor_list total", call('get_vendor_list')['total'],
      db("select count(*) from light_sync.vendors"))

# 9. FAB→공정 전체 (get_production_status total)
check("get_production_status total", call('get_production_status')['total'],
      db("select count(*) from light_sync.production_processes"))

# 10. 오늘 근무인원
att = call('get_today_attendance')
check("get_today_attendance total_employees", att['total_employees'],
      db("select count(*) from light_sync.users where role <> 'pending'"))

# 11. 연차 잔여 — 김선중 (hr_service 와 동일해야)
lb = call('get_leave_balance', employee='김선중')['items'][0]
check("get_leave_balance 김선중 granted+adjust-used=remaining",
      round(lb['granted'] + lb['adjust'] - lb['used'], 1), lb['remaining'])

# 12. 전자결재 총 문서수
check("get_approval_documents 건수 (limit 100)",
      call('get_approval_documents', limit=100)['count'],
      db("select count(*) from light_sync.approval_documents"))

# 13. 공구 목록
tl = call('get_tools_list')
tl_n = tl['total'] if isinstance(tl, dict) and 'total' in tl else len(
    tl if isinstance(tl, list) else tl.get('items', []))
check("get_tools_list 건수", tl_n, db("select count(*) from light_sync.tools"))

# 14. 인증서 만료 임박 (60일) — 만료된 것도 포함하므로 상한만 비교
ce = call('get_cert_expiry_alerts', days=60)
check("get_cert_expiry_alerts(60) total", ce['total'],
      db("select count(*) from light_sync.certifications "
         "where is_active and expiry_date <= current_date + 60"))
check("get_cert_expiry_alerts(60) 만료", ce['expired'],
      db("select count(*) from light_sync.certifications "
         "where is_active and expiry_date < current_date"))

# 15. 미수금 건수
check("get_unpaid_invoices 건수", call('get_unpaid_invoices', include_old=True)['count'],
      db("select count(*) from light_sync.contracts "
         "where payment_status in ('미청구','부분입금')"))

print("=" * 92)
for ok, label, tv, dv in results:
    mark = "일치  " if ok else "불일치"
    print(f"{mark} {label:48} tool={tv!r:>20}  db={dv!r}")
print("=" * 92)
bad = [r for r in results if not r[0]]
print(f"\n{len(results)}건 중 불일치 {len(bad)}건")
