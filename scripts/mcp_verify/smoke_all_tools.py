"""MCP 전체 Tool 헬스체크 — read-only tool 실전 호출"""
import sys, os, json, inspect, traceback, time
sys.path.insert(0, '/web/light_sync')
from dotenv import load_dotenv
load_dotenv('/web/light_sync/.env')

TOOLS = {}
RESOURCES = {}


class FakeMCP:
    def tool(self, *a, **k):
        def deco(fn):
            TOOLS[fn.__name__] = fn
            return fn
        return deco

    def resource(self, uri, *a, **k):
        def deco(fn):
            RESOURCES[uri] = fn
            return fn
        return deco


from light_sync_mcp.tools_registry import register_all
register_all(FakeMCP())

print(f"등록된 Tool: {len(TOOLS)}개, Resource: {len(RESOURCES)}개")

reads = [n for n in TOOLS if not n.startswith('write_')]
writes = [n for n in TOOLS if n.startswith('write_')]
print(f"read-only {len(reads)} / write_preview {len(writes)}")

results = []

def required_params(fn):
    sig = inspect.signature(fn)
    return [p.name for p in sig.parameters.values() if p.default is inspect._empty]

# 필수 인자 툴에 넣을 프로브 값 (실제 데이터에서 채움)
probe = {}


def call(name, kwargs):
    fn = TOOLS[name]
    t0 = time.time()
    try:
        out = fn(**kwargs)
        ms = int((time.time() - t0) * 1000)
        try:
            data = json.loads(out)
        except Exception:
            return (name, 'NONJSON', ms, str(out)[:80], kwargs)
        if isinstance(data, dict) and data.get('error'):
            return (name, 'ERROR', ms, str(data['error'])[:120], kwargs)
        # 건수 추정
        n = None
        if isinstance(data, list):
            n = len(data)
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    n = len(v)
                    break
            if n is None:
                n = data.get('total') or data.get('count')
        return (name, 'OK', ms, f"n={n}", kwargs)
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return (name, 'EXC', ms, f"{type(e).__name__}: {e}"[:160], kwargs)


# 1) 인자 없이 호출 가능한 툴
no_arg = [n for n in reads if not required_params(TOOLS[n])]
need_arg = [n for n in reads if required_params(TOOLS[n])]

for n in sorted(no_arg):
    results.append(call(n, {}))

# 2) 프로브 값 수집
def first_id(name, key, **kw):
    try:
        d = json.loads(TOOLS[name](**kw))
    except Exception:
        return None
    lst = d if isinstance(d, list) else next((v for v in d.values() if isinstance(v, list)), [])
    for item in lst:
        if isinstance(item, dict) and item.get(key) is not None:
            return item[key]
    return None

PROBES = {
    'project_id': lambda: first_id('get_projects', 'id'),
    'contract_id': lambda: first_id('get_contracts', 'id'),
    'bom_id': lambda: first_id('get_bom_list', 'id'),
    'po_id': lambda: first_id('get_purchase_orders', 'id'),
    'quotation_id': lambda: first_id('get_quotations', 'id'),
    'delivery_id': lambda: first_id('get_deliveries', 'id'),
    'case_id': lambda: first_id('get_warranty_cases', 'id'),
    'report_id': lambda: first_id('get_daily_reports', 'id'),
    'trip_id': lambda: first_id('get_business_trips', 'id'),
    'order_id': lambda: first_id('get_processing_orders', 'id'),
    'layout_id': lambda: first_id('get_lighting_layouts', 'id'),
    'receiving_id': lambda: first_id('get_receiving_history', 'id'),
    'document_id': lambda: first_id('get_document_list', 'id'),
    'post_id': lambda: first_id('search_archive', 'id', query='현장'),
    'query': lambda: '조명',
    'search': lambda: '조명',
    'keyword': lambda: '조명',
    'model_code': lambda: first_id('get_drawings', 'model_code'),
    'item_code': lambda: first_id('get_items', 'item_cd'),
    'dept': lambda: '관리부',
}

for n in sorted(need_arg):
    req = required_params(TOOLS[n])
    kw = {}
    missing = []
    for p in req:
        if p in PROBES:
            if p not in probe:
                try:
                    probe[p] = PROBES[p]()
                except Exception:
                    probe[p] = None
            if probe[p] is not None:
                kw[p] = probe[p]
            else:
                missing.append(p)
        else:
            missing.append(p)
    if missing:
        results.append((n, 'SKIP', 0, f"필수인자 프로브없음: {missing}", {}))
    else:
        results.append(call(n, kw))

print("\n=== 결과 ===")
bad = []
for name, st, ms, info, kw in sorted(results, key=lambda r: (r[1] != 'OK', r[0])):
    line = f"{st:7} {ms:5}ms  {name:35} {info}"
    if kw:
        line += f"  args={kw}"
    print(line)
    if st in ('EXC', 'ERROR', 'NONJSON'):
        bad.append(name)

from collections import Counter
c = Counter(r[1] for r in results)
print(f"\n요약: {dict(c)}  (write_preview {len(writes)}개는 미호출)")
print("문제:", bad)
