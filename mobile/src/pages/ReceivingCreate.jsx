import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';

/* 입고 등록
   ERP 대응: routes/receiving.py receiving_create (GET/POST) + api_po_search
   - PO/FO 선택 시: 품목 자동채움(잔량 기본값), 거래처 고정
   - 직접입고: 거래처 자동완성 + 품목 자동완성
*/

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => Math.round(v || 0).toLocaleString();

export default function ReceivingCreate() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const poIdParam = sp.get('po_id');
  const foIdParam = sp.get('fo_id');

  const [sourceInfo, setSourceInfo] = useState(null); // {po/fo, vendor, items}
  const [loadingSrc, setLoadingSrc] = useState(!!(poIdParam || foIdParam));

  const [base, setBase] = useState({
    rcv_date: today(),
    vendor_id: '', vendor_name: '',
    po_id: poIdParam ? Number(poIdParam) : null,
    fo_id: foIdParam ? Number(foIdParam) : null,
    note: '',
  });

  const [items, setItems] = useState([
    { po_item_id: null, fo_item_id: null, item_cd: '', item_name: '', item_spec: '', received_qty: '', unit: 'EA', unit_price: '', note: '', _remaining: null },
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  /* PO/FO 로드 시 기본값 채움 */
  useEffect(() => {
    if (!poIdParam && !foIdParam) return;
    const url = poIdParam ? `/receivings/source?po_id=${poIdParam}` : `/receivings/source?fo_id=${foIdParam}`;
    api.get(url).then((d) => {
      setSourceInfo(d);
      setBase((b) => ({
        ...b,
        vendor_id: d.vendor_id || '',
        vendor_name: d.vendor_name || '',
        rcv_date: today(),
      }));
      setItems((d.items || []).map((it) => ({
        po_item_id: poIdParam ? it.id : null,
        fo_item_id: foIdParam ? it.id : null,
        item_cd: it.item_code || '',
        item_name: it.item_name || '',
        item_spec: it.item_spec || '',
        received_qty: String(it.remaining ?? 0),
        unit: it.unit || '',
        unit_price: String(it.unit_price ?? 0),
        note: '',
        _remaining: it.remaining ?? 0,
      })));
    }).catch((e) => setError(e.message)).finally(() => setLoadingSrc(false));
  }, [poIdParam, foIdParam]);

  const isSrc = !!(poIdParam || foIdParam);

  const totals = useMemo(() => {
    const supply = items.reduce((s, it) => {
      const q = parseFloat(it.received_qty) || 0;
      const p = parseFloat(it.unit_price) || 0;
      return s + q * p;
    }, 0);
    const tax = Math.round(supply * 0.1);
    return { supply: Math.round(supply), tax, grand: Math.round(supply) + tax };
  }, [items]);

  const updItem = (i, k, v) => setItems(items.map((it, idx) => idx === i ? { ...it, [k]: v } : it));
  const updItemMulti = (i, patch) => setItems(items.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  const addItem = () => setItems([...items, { po_item_id: null, fo_item_id: null, item_cd: '', item_name: '', item_spec: '', received_qty: '', unit: 'EA', unit_price: '', note: '', _remaining: null }]);
  const delItem = (i) => setItems(items.filter((_, idx) => idx !== i));

  const submit = async () => {
    setError('');
    if (!base.vendor_id) { setError('거래처를 선택해주세요'); return; }
    const real = items.filter((it) => (it.item_name || '').trim());
    if (real.length === 0) { setError('품목을 최소 1개 입력해주세요'); return; }
    setSubmitting(true);
    try {
      const data = await api.post('/receivings/create', {
        rcv_date: base.rcv_date,
        vendor_id: base.vendor_id,
        po_id: base.po_id || null,
        fo_id: base.fo_id || null,
        note: base.note,
        items: real.map((it) => ({
          po_item_id: it.po_item_id || null,
          fo_item_id: it.fo_item_id || null,
          item_cd: it.item_cd || '',
          item_name: it.item_name,
          item_spec: it.item_spec || '',
          received_qty: parseFloat(it.received_qty) || 0,
          unit: it.unit || '',
          unit_price: parseFloat(it.unit_price) || 0,
          note: it.note || '',
        })),
      });
      nav(`/receivings/${data.rcv_id}`);
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  if (loadingSrc) return <div className="page-loader">불러오는 중...</div>;

  const srcLabel = sourceInfo
    ? (poIdParam ? `발주: ${sourceInfo.source_no}` : `가공발주: ${sourceInfo.source_no}`)
    : '직접 입고';

  return (
    <div style={{ paddingBottom: 170 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={backBtn}>←</button>
        <h1>입고 등록</h1>
      </div>

      {error && <div style={errorBox}>{error}</div>}

      <Section num="1" title="기본정보">
        <Field label="입고일" required>
          <input type="date" value={base.rcv_date} onChange={(e) => setBase({ ...base, rcv_date: e.target.value })} style={inp} />
        </Field>
        <Field label="거래처" required>
          {isSrc ? (
            <input value={base.vendor_name} readOnly style={{ ...inp, opacity: 0.7 }} />
          ) : (
            <VendorAutocomplete
              value={base.vendor_name}
              onChange={(v) => setBase({ ...base, vendor_name: v })}
              onPick={(v) => setBase({ ...base, vendor_id: v.id, vendor_name: v.name })}
            />
          )}
        </Field>
        <Field label="발주/가공발주 연결">
          {isSrc ? (
            <input value={srcLabel} readOnly style={{ ...inp, opacity: 0.7 }} />
          ) : (
            <PoAutocomplete
              vendorId={base.vendor_id}
              onPick={(p) => {
                if (p.order_type === 'fo') nav(`/receivings/create?fo_id=${p.id}`);
                else nav(`/receivings/create?po_id=${p.id}`);
              }}
            />
          )}
        </Field>
        <Field label="비고">
          <textarea rows={2} value={base.note} onChange={(e) => setBase({ ...base, note: e.target.value })} style={{ ...inp, resize: 'vertical' }} />
        </Field>
      </Section>

      <Section num="2" title="입고 품목" actions={!isSrc && <SmBtn onClick={addItem} primary>+ 품목 추가</SmBtn>}>
        {items.map((it, i) => {
          const amt = (parseFloat(it.received_qty) || 0) * (parseFloat(it.unit_price) || 0);
          const locked = !!(it.po_item_id || it.fo_item_id);
          return (
            <div key={i} style={itemCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  #{i + 1}{locked && it._remaining != null && ` · 잔량 ${it._remaining}`}
                </span>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>{money(amt)}원</span>
                  {!isSrc && items.length > 1 && (
                    <button onClick={() => delItem(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>
                  )}
                </div>
              </div>
              {!locked ? (
                <ItemAutocomplete
                  value={it.item_name}
                  onChange={(v) => updItem(i, 'item_name', v)}
                  onPick={(p) => updItemMulti(i, {
                    item_name: p.item_name,
                    item_spec: p.item_spec || it.item_spec,
                    item_cd: p.item_cd || '',
                    unit: p.unit || it.unit || 'EA',
                    unit_price: p.last_unit_price ? String(p.last_unit_price) : it.unit_price,
                  })}
                />
              ) : (
                <input value={it.item_name} readOnly style={{ ...inp, marginBottom: 6, opacity: 0.7 }} />
              )}
              <input placeholder="품번" value={it.item_cd}
                onChange={(e) => updItem(i, 'item_cd', e.target.value)}
                readOnly={locked}
                style={{ ...inp, marginBottom: 6, opacity: locked ? 0.7 : 1 }} />
              <input placeholder="규격" value={it.item_spec}
                onChange={(e) => updItem(i, 'item_spec', e.target.value)}
                readOnly={locked}
                style={{ ...inp, marginBottom: 6, opacity: locked ? 0.7 : 1 }} />
              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input placeholder="단위" value={it.unit} onChange={(e) => updItem(i, 'unit', e.target.value)} readOnly={locked} style={{ ...inp, width: 60, textAlign: 'center', opacity: locked ? 0.7 : 1 }} />
                <input placeholder="수량" type="number" step="any" value={it.received_qty} onChange={(e) => updItem(i, 'received_qty', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
                <input placeholder="단가" type="number" step="any" value={it.unit_price} onChange={(e) => updItem(i, 'unit_price', e.target.value)} readOnly={locked} style={{ ...inp, flex: 1, textAlign: 'right', opacity: locked ? 0.7 : 1 }} />
              </div>
              <input placeholder="비고" value={it.note} onChange={(e) => updItem(i, 'note', e.target.value)} style={inp} />
            </div>
          );
        })}
      </Section>

      <div style={footer}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 2 }}>
          <span style={{ color: 'var(--text-muted)' }}>공급가액</span>
          <span style={{ color: 'var(--text-bright)', fontWeight: 600 }}>{money(totals.supply)}원</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 2 }}>
          <span style={{ color: 'var(--text-muted)' }}>부가세 10%</span>
          <span style={{ color: 'var(--text-bright)' }}>{money(totals.tax)}원</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, paddingTop: 6, borderTop: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>합계</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)' }}>{money(totals.grand)}원</span>
        </div>
        <button onClick={submit} disabled={submitting} style={saveBtn}>
          {submitting ? '저장중...' : '입고 등록'}
        </button>
      </div>
    </div>
  );
}

/* ── 컴포넌트 ────────────────────────────────── */
function Section({ num, title, actions, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--accent)', color: '#fff', fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{num}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>{title}</span>
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}
function Field({ label, required, children }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
        {label}{required && <span style={{ color: 'var(--red)' }}> *</span>}
      </div>
      {children}
    </div>
  );
}
function SmBtn({ children, onClick, primary }) {
  return (
    <button onClick={onClick} type="button" style={{
      padding: '5px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
      background: primary ? 'var(--accent)' : 'var(--surface)',
      color: primary ? '#fff' : 'var(--text-bright)',
    }}>{children}</button>
  );
}

function VendorAutocomplete({ value, onChange, onPick }) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const timer = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const search = (q) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.get(`/vendors/search?q=${encodeURIComponent(q || '')}`)
        .then((d) => { setResults(d.vendors || []); setOpen(true); })
        .catch(() => setResults([]));
    }, 250);
  };
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input placeholder="거래처 검색..." value={value} autoComplete="off"
        onChange={(e) => { onChange(e.target.value); search(e.target.value); }}
        onFocus={() => search(value)} style={inp} />
      {open && (
        <div style={dropdown}>
          {results.length === 0 ? <div style={emptyRow}>검색 결과 없음</div> :
            results.map((v) => (
              <div key={v.id} onClick={() => { onPick(v); setOpen(false); }} style={row}>
                <div style={{ fontSize: 13, color: 'var(--text-bright)', fontWeight: 600 }}>{v.name}</div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{v.ceo_name}{v.tel ? ` · ${v.tel}` : ''}</div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function PoAutocomplete({ vendorId, onPick }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const timer = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const search = (val) => {
    clearTimeout(timer.current);
    if (!val || val.length < 2) { setResults([]); return; }
    timer.current = setTimeout(() => {
      api.get(`/receivings/po-search?q=${encodeURIComponent(val)}&vendor_id=${vendorId || ''}`)
        .then((d) => { setResults(d.results || []); setOpen(true); })
        .catch(() => setResults([]));
    }, 300);
  };
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input placeholder="발주번호 검색 (선택)" value={q} autoComplete="off"
        onChange={(e) => { setQ(e.target.value); search(e.target.value); }}
        style={inp} />
      {open && (
        <div style={dropdown}>
          {results.length === 0 ? <div style={emptyRow}>검색 결과 없음</div> :
            results.map((p) => (
              <div key={`${p.order_type}-${p.id}`} onClick={() => { onPick(p); setOpen(false); }} style={row}>
                <div style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 600 }}>
                  {p.order_type === 'fo' ? '[가공] ' : ''}{p.po_no}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{p.vendor_name} · {p.po_date} · {p.status}</div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function ItemAutocomplete({ value, onChange, onPick }) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const timer = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const search = (q) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.get(`/items/search?q=${encodeURIComponent(q || '')}`)
        .then((d) => { setResults(d.items || []); setOpen(true); })
        .catch(() => setResults([]));
    }, 250);
  };
  return (
    <div ref={ref} style={{ position: 'relative', marginBottom: 6 }}>
      <input placeholder="품명 * (자동완성)" value={value} autoComplete="off"
        onChange={(e) => { onChange(e.target.value); search(e.target.value); }}
        onFocus={() => search(value)} style={inp} />
      {open && (
        <div style={dropdown}>
          {results.length === 0 ? <div style={emptyRow}>검색 결과 없음</div> :
            results.map((r) => (
              <div key={r.id} onClick={() => { onPick(r); setOpen(false); }} style={row}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: 'var(--text-bright)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.item_name}</div>
                    {(r.item_spec || r.item_cd) && (
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        {r.item_cd && <span>{r.item_cd} · </span>}{r.item_spec}{r.unit && ` · ${r.unit}`}
                      </div>
                    )}
                  </div>
                  {r.last_unit_price > 0 && (
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)' }}>{Number(r.last_unit_price).toLocaleString()}원</span>
                  )}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

const backBtn = { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' };
const inp = { width: '100%', padding: '9px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 };
const itemCard = { padding: 10, borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)', marginBottom: 8 };
const dropdown = { position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, maxHeight: 280, overflowY: 'auto', marginTop: 2, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' };
const row = { padding: '8px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)' };
const emptyRow = { padding: 10, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 };
const errorBox = { margin: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(242,63,67,0.12)', color: 'var(--red)', fontSize: 13 };
const footer = {
  position: 'fixed', bottom: 56, left: 0, right: 0, zIndex: 10,
  background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)', padding: '10px 16px',
};
const saveBtn = { width: '100%', marginTop: 8, padding: 10, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 700, border: 'none', cursor: 'pointer' };
