import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => Math.round(Number(v) || 0).toLocaleString();
const TYPE_CHOICES = ['외주가공', '사급가공'];

const API_BASE = '/api/app';

export default function ProcessingOrderCreate() {
  const nav = useNavigate();
  const [base, setBase] = useState({
    fo_date: today(),
    vendor_id: '',
    vendor_name: '',
    contract_id: '',
    contract_label: '',
    project_id: '',
    processing_type: '외주가공',
    assigned_to: '',
    note: '',
  });
  const [items, setItems] = useState([newItem()]);
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  function newItem() {
    return {
      item_id: null, item_name: '', item_spec: '',
      quantity: '', unit: 'EA', unit_price: '',
      delivery_date: '', processing_note: '', note: '',
    };
  }

  const supplyTotal = useMemo(() =>
    items.reduce((s, it) => s + (parseFloat(it.quantity) || 0) * (parseFloat(it.unit_price) || 0), 0),
    [items]);
  const tax = Math.round(supplyTotal * 0.1);
  const grandTotal = supplyTotal + tax;

  const addItem = () => setItems([...items, newItem()]);
  const updItem = (i, k, v) => setItems(items.map((it, idx) => idx === i ? { ...it, [k]: v } : it));
  const updItemMulti = (i, patch) => setItems(items.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  const delItem = (i) => setItems(items.filter((_, idx) => idx !== i));

  const addFiles = (list) => {
    if (!list) return;
    const newList = [...files];
    for (let i = 0; i < list.length; i++) newList.push(list[i]);
    setFiles(newList);
  };
  const removeFile = (i) => setFiles(files.filter((_, idx) => idx !== i));

  const submit = async () => {
    setError('');
    if (!base.vendor_id) { setError('가공업체를 선택해주세요'); return; }
    const real = items.filter(it => (it.item_name || '').trim());
    if (real.length === 0) { setError('품목을 1개 이상 입력해주세요'); return; }

    setSubmitting(true);
    try {
      // ERP fo_create 는 multipart/form-data 를 받음 -> 파일 있는 경우 FormData로 전송
      const token = localStorage.getItem('token');
      const fd = new FormData();
      fd.append('fo_date', base.fo_date);
      fd.append('vendor_id', String(base.vendor_id));
      fd.append('processing_type', base.processing_type);
      fd.append('note', base.note || '');
      if (base.contract_id) fd.append('contract_id', String(base.contract_id));
      if (base.project_id) fd.append('project_id', String(base.project_id));
      if (base.assigned_to) fd.append('assigned_to', String(base.assigned_to));

      for (const it of real) {
        fd.append('item_id[]', it.item_id ? String(it.item_id) : '');
        fd.append('item_name[]', it.item_name || '');
        fd.append('item_spec[]', it.item_spec || '');
        fd.append('quantity[]', String(parseFloat(it.quantity) || 0));
        fd.append('unit[]', it.unit || 'EA');
        fd.append('unit_price[]', String(parseFloat(it.unit_price) || 0));
        fd.append('delivery_date[]', it.delivery_date || '');
        fd.append('processing_note[]', it.processing_note || '');
        fd.append('item_note[]', it.note || '');
      }
      for (const f of files) fd.append('files', f);

      const res = await fetch(`${API_BASE}/processing-orders/create`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: fd,
      });
      const j = await res.json();
      if (!res.ok || j.ok === false) throw new Error(j.error || '저장 실패');
      nav(`/processing-orders/${j.fo_id}`);
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  return (
    <div style={{ paddingBottom: 180 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1>신규 가공발주</h1>
      </div>

      {error && <div style={errorBox}>{error}</div>}

      {/* 1. 기본정보 */}
      <Section num="1" title="가공발주 기본정보">
        <Field label="가공업체" required>
          <VendorAutocomplete
            value={base.vendor_name}
            onChange={(v) => setBase({ ...base, vendor_name: v })}
            onPick={(v) => setBase({ ...base, vendor_id: v.id, vendor_name: v.name })}
          />
        </Field>
        <Field label="연결 현장 (선택)">
          <ContractAutocomplete
            value={base.contract_label}
            onChange={(v) => setBase({ ...base, contract_label: v })}
            onPick={(c) => setBase({ ...base, contract_id: c.id, project_id: c.project_id || '', contract_label: c.label || c.contract_name || c.site_name })}
          />
        </Field>
        <Field label="발주일" required>
          <input type="date" value={base.fo_date} onChange={e => setBase({ ...base, fo_date: e.target.value })} style={inp} required />
        </Field>
        <Field label="가공유형" required>
          <div style={{ display: 'flex', gap: 8 }}>
            {TYPE_CHOICES.map(t => (
              <label key={t} style={{
                flex: 1, padding: '9px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', textAlign: 'center',
                background: base.processing_type === t ? 'var(--accent)' : 'var(--surface)',
                color: base.processing_type === t ? '#fff' : 'var(--text)',
              }}>
                <input type="radio" checked={base.processing_type === t} onChange={() => setBase({ ...base, processing_type: t })} style={{ display: 'none' }} />
                {t}
              </label>
            ))}
          </div>
        </Field>
        <Field label="담당자">
          <UserSelect value={base.assigned_to} onChange={(uid) => setBase({ ...base, assigned_to: uid })} />
        </Field>
        <Field label="비고">
          <input value={base.note} onChange={e => setBase({ ...base, note: e.target.value })} style={inp} placeholder="선택 입력" />
        </Field>
      </Section>

      {/* 2. 품목 */}
      <Section num="2" title="가공 품목" actions={<SmBtn onClick={addItem} primary>+ 품목 추가</SmBtn>}>
        {items.map((it, i) => {
          const amt = (parseFloat(it.quantity) || 0) * (parseFloat(it.unit_price) || 0);
          return (
            <div key={i} style={itemCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>#{i + 1}</span>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>{money(amt)}원</span>
                  {items.length > 1 && (
                    <button onClick={() => delItem(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>
                  )}
                </div>
              </div>
              <ItemNameAutocomplete
                value={it.item_name}
                onChange={(v) => updItem(i, 'item_name', v)}
                onPick={(p) => updItemMulti(i, {
                  item_id: p.id,
                  item_name: p.item_name,
                  item_spec: p.item_spec || it.item_spec,
                  unit: p.unit || it.unit || 'EA',
                  unit_price: p.last_unit_price ? String(p.last_unit_price) : it.unit_price,
                })}
              />
              <input placeholder="규격" value={it.item_spec} onChange={e => updItem(i, 'item_spec', e.target.value)} style={{ ...inp, marginBottom: 6 }} />
              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input placeholder="수량" type="number" step="any" value={it.quantity} onChange={e => updItem(i, 'quantity', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
                <input placeholder="단위" value={it.unit} onChange={e => updItem(i, 'unit', e.target.value)} style={{ ...inp, width: 60, textAlign: 'center' }} />
                <input placeholder="단가" type="number" step="any" value={it.unit_price} onChange={e => updItem(i, 'unit_price', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <input type="date" value={it.delivery_date} onChange={e => updItem(i, 'delivery_date', e.target.value)} style={{ ...inp, flex: 1 }} />
                <input placeholder="가공메모" value={it.processing_note} onChange={e => updItem(i, 'processing_note', e.target.value)} style={{ ...inp, flex: 1 }} />
              </div>
            </div>
          );
        })}
      </Section>

      {/* 3. 파일 */}
      <Section num="3" title="도면/파일 첨부">
        <label style={{
          display: 'block', padding: 24, borderRadius: 8,
          border: '2px dashed var(--border)', background: 'var(--surface)',
          textAlign: 'center', color: 'var(--text-muted)', cursor: 'pointer',
          fontSize: 12,
        }}>
          📎 파일을 선택하세요
          <br />
          <small style={{ fontSize: 10 }}>DWG, DXF, PDF, JPG, PNG, ZIP (최대 50MB)</small>
          <input type="file" multiple accept=".dwg,.dxf,.pdf,.jpg,.jpeg,.png,.zip"
            onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
            style={{ display: 'none' }} />
        </label>
        {files.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {files.map((f, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                <span>📎</span>
                <span style={{ flex: 1, color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {f.size > 1048576 ? (f.size / 1048576).toFixed(1) + 'MB' : Math.round(f.size / 1024) + 'KB'}
                </span>
                <button onClick={() => removeFile(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 14, cursor: 'pointer' }}>×</button>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* 하단 합계 + 저장 */}
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
        }}>{submitting ? '저장중...' : '가공발주 저장'}</button>
      </div>
    </div>
  );
}

/* ── 공통 컴포넌트 ── */
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

/* ── Autocomplete 공통 로직 ── */
function useAutocomplete(fetcher, minChars = 0) {
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
    if (q.length < minChars) { setResults([]); if (minChars > 0) return; }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      fetcher(q).then(d => { setResults(d); setOpen(true); }).catch(() => setResults([]));
    }, 300);
  };

  return { results, open, setOpen, ref, search };
}

function VendorAutocomplete({ value, onChange, onPick }) {
  const { results, open, setOpen, ref, search } = useAutocomplete(
    (q) => api.get(`/vendors/search?q=${encodeURIComponent(q)}`).then(d => d.vendors || [])
  );
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input placeholder="업체명 (자동완성)" value={value} autoComplete="off"
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
  const { results, open, setOpen, ref, search } = useAutocomplete(
    (q) => api.get(`/contracts/search?q=${encodeURIComponent(q)}`).then(d => d.contracts || []),
    2
  );
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
  const { results, open, setOpen, ref, search } = useAutocomplete(
    (q) => api.get(`/items/search?q=${encodeURIComponent(q)}`).then(d => d.items || [])
  );
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
const errorBox = { margin: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(242,63,67,0.12)', color: 'var(--red)', fontSize: 13 };
