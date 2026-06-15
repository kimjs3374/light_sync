import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => Math.round(v || 0).toLocaleString();

export default function PurchaseOrderCreate() {
  const nav = useNavigate();
  const [base, setBase] = useState({
    po_date: today(),
    vendor_id: '', vendor_name: '',
    assigned_to: '',
    contract_id: '', contract_label: '',
    note: '',
  });
  const [items, setItems] = useState([
    { item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '', note: '', delivery_date: '', item_id: null, item_code: '' },
  ]);
  const [users, setUsers] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    // 담당자 목록 (delivery-projects API에서 users 가져오는 패턴 재사용)
    api.get('/vendors/search?q=').catch(() => {}); // warmup
  }, []);

  const supplyTotal = useMemo(() =>
    items.reduce((s, it) => s + (parseFloat(it.quantity) || 0) * (parseFloat(it.unit_price) || 0), 0),
    [items]);
  const tax = Math.round(supplyTotal * 0.1);
  const grandTotal = supplyTotal + tax;

  const addItem = () => setItems([...items, { item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '', note: '', delivery_date: '', item_id: null, item_code: '' }]);
  const updItem = (i, k, v) => setItems(items.map((it, idx) => idx === i ? { ...it, [k]: v } : it));
  const updItemMulti = (i, patch) => setItems(items.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  const delItem = (i) => setItems(items.filter((_, idx) => idx !== i));

  const submit = async () => {
    setError('');
    if (!base.vendor_id) { setError('거래처를 선택해주세요'); return; }
    const real = items.filter(it => (it.item_name || '').trim());
    if (real.length === 0) { setError('품목을 최소 1개 이상 입력해주세요'); return; }
    setSubmitting(true);
    try {
      const data = await api.post('/purchase-orders/create', {
        po_date: base.po_date,
        vendor_id: base.vendor_id,
        assigned_to: base.assigned_to || null,
        contract_id: base.contract_id || null,
        note: base.note,
        items: real.map(it => ({
          ...it,
          quantity: parseFloat(it.quantity) || 0,
          unit_price: parseFloat(it.unit_price) || 0,
        })),
      });
      nav(`/purchase-orders/${data.po_id}`);
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  return (
    <div style={{ paddingBottom: 170 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1>발주서 작성</h1>
      </div>

      {error && <div style={{ margin: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(242,63,67,0.12)', color: 'var(--red)', fontSize: 13 }}>{error}</div>}

      <Section num="1" title="기본정보">
        <Field label="발주일" required>
          <input type="date" value={base.po_date} onChange={e => setBase({ ...base, po_date: e.target.value })} style={inp} required />
        </Field>
        <Field label="거래처" required>
          <VendorAutocomplete
            value={base.vendor_name}
            onChange={(v) => setBase({ ...base, vendor_name: v })}
            onPick={(v) => setBase({ ...base, vendor_id: v.id, vendor_name: v.name })}
          />
        </Field>
        <Field label="담당자">
          <UserSelect value={base.assigned_to} onChange={(uid) => setBase({ ...base, assigned_to: uid })} />
        </Field>
        <Field label="계약 연결 (선택)">
          <ContractAutocomplete
            value={base.contract_label}
            onChange={(v) => setBase({ ...base, contract_label: v })}
            onPick={(c) => setBase({ ...base, contract_id: c.id, contract_label: c.label })}
          />
        </Field>
        <Field label="비고">
          <textarea rows={2} value={base.note} onChange={e => setBase({ ...base, note: e.target.value })} style={{ ...inp, resize: 'vertical' }} />
        </Field>
      </Section>

      <Section num="2" title="품목" actions={<SmBtn onClick={addItem} primary>+ 품목 추가</SmBtn>}>
        {items.map((it, i) => {
          const amt = (parseFloat(it.quantity) || 0) * (parseFloat(it.unit_price) || 0);
          return (
            <div key={i} style={itemCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>#{i + 1}</span>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>{money(amt)}원</span>
                  {items.length > 1 && <button onClick={() => delItem(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>}
                </div>
              </div>
              <ItemNameAutocomplete
                value={it.item_name}
                onChange={(v) => updItem(i, 'item_name', v)}
                onPick={(p) => updItemMulti(i, {
                  item_name: p.item_name,
                  item_spec: p.item_spec || it.item_spec,
                  unit: p.unit || it.unit || 'EA',
                  unit_price: p.last_unit_price ? String(p.last_unit_price) : it.unit_price,
                  item_id: p.id,
                  item_code: p.item_cd || '',
                })}
              />
              <input placeholder="규격" value={it.item_spec} onChange={e => updItem(i, 'item_spec', e.target.value)} style={{ ...inp, marginBottom: 6 }} />
              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input placeholder="단위" value={it.unit} onChange={e => updItem(i, 'unit', e.target.value)} style={{ ...inp, width: 60, textAlign: 'center' }} />
                <input placeholder="수량" type="number" step="any" value={it.quantity} onChange={e => updItem(i, 'quantity', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
                <input placeholder="단가" type="number" step="any" value={it.unit_price} onChange={e => updItem(i, 'unit_price', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
              </div>
              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input type="date" value={it.delivery_date} onChange={e => updItem(i, 'delivery_date', e.target.value)} style={{ ...inp, flex: 1 }} placeholder="납기일" />
                <input placeholder="비고" value={it.note} onChange={e => updItem(i, 'note', e.target.value)} style={{ ...inp, flex: 1 }} />
              </div>
            </div>
          );
        })}
      </Section>

      <div style={{
        position: 'fixed', bottom: 56, left: 0, right: 0, zIndex: 10,
        background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)',
        padding: '10px 16px', fontSize: 12,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
          <span style={{ color: 'var(--text-muted)' }}>공급가액</span>
          <span style={{ color: 'var(--text-bright)', fontWeight: 600 }}>{money(supplyTotal)}원</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
          <span style={{ color: 'var(--text-muted)' }}>부가세 10%</span>
          <span style={{ color: 'var(--text-bright)' }}>{money(tax)}원</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, paddingTop: 6, borderTop: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>합계</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)' }}>{money(grandTotal)}원</span>
        </div>
        <button onClick={submit} disabled={submitting} style={{
          width: '100%', marginTop: 8, padding: 10, borderRadius: 6,
          background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 700,
          border: 'none', cursor: 'pointer',
        }}>{submitting ? '저장중...' : '발주서 저장'}</button>
      </div>
    </div>
  );
}

/* ── 컴포넌트 ───────────────────────────────── */
function Section({ num, title, actions, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--accent)', color: '#fff', fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{num}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>{title}</span>
        </div>
        {actions && <div style={{ display: 'flex', gap: 4 }}>{actions}</div>}
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
      api.get(`/vendors/search?q=${encodeURIComponent(q)}`)
        .then((d) => { setResults(d.vendors || []); setOpen(true); })
        .catch(() => setResults([]));
    }, 300);
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
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {v.ceo_name}{v.tel ? ` · ${v.tel}` : ''}{v.email ? ` · ${v.email}` : ''}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function ContractAutocomplete({ value, onChange, onPick }) {
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
    if (!q || q.length < 2) { setResults([]); return; }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.get(`/contracts/search?q=${encodeURIComponent(q)}`)
        .then((d) => { setResults(d.contracts || []); setOpen(true); })
        .catch(() => setResults([]));
    }, 300);
  };
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input placeholder="현장명 또는 계약명 검색..." value={value} autoComplete="off"
        onChange={(e) => { onChange(e.target.value); search(e.target.value); }}
        onFocus={() => value && search(value)} style={inp} />
      {open && results.length > 0 && (
        <div style={dropdown}>
          {results.map((c) => (
            <div key={c.id} onClick={() => { onPick(c); setOpen(false); }} style={row}>
              <div style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 600 }}>{c.site_name}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{c.contract_name}{c.item_group ? ` · ${c.item_group}` : ''}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ItemNameAutocomplete({ value, onChange, onPick }) {
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
      api.get(`/items/search?q=${encodeURIComponent(q)}`)
        .then((d) => { setResults(d.items || []); setOpen(true); })
        .catch(() => setResults([]));
    }, 300);
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

function UserSelect({ value, onChange }) {
  const [users, setUsers] = useState([]);
  useEffect(() => {
    api.get('/users').then((d) => setUsers(d.users || [])).catch(() => setUsers([]));
  }, []);
  return (
    <select value={value || ''} onChange={(e) => onChange(e.target.value)} style={inp}>
      <option value="">-- 기본(본인) --</option>
      {users.map((u) => (
        <option key={u.id} value={u.id}>
          {u.name}{u.position ? ` ${u.position}` : ''}{u.user_group ? ` (${u.user_group})` : ''}
        </option>
      ))}
    </select>
  );
}

const inp = { width: '100%', padding: '9px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 };
const itemCard = { padding: 10, borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)', marginBottom: 8 };
const dropdown = { position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, maxHeight: 280, overflowY: 'auto', marginTop: 2, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' };
const row = { padding: '8px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)' };
const emptyRow = { padding: 10, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 };
