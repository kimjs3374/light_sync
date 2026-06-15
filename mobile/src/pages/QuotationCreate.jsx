import { useState, useMemo, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => Math.round(v || 0).toLocaleString();

export default function QuotationCreate() {
  const nav = useNavigate();
  const [base, setBase] = useState({
    quote_date: today(),
    delivery_date: '협의',
    payment_method: '현금',
    validity_period: '견적일로부터 1개월',
    project_name: '',
    bank_account: '',
  });
  const [cust, setCust] = useState({
    customer_name: '', customer_contact: '', customer_tel: '',
    customer_address: '', customer_fax: '', customer_email: '',
  });
  const [items, setItems] = useState([
    { item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '', note: '', item_id: null },
  ]);
  const [surcharges, setSurcharges] = useState([]);
  const [note, setNote] = useState('');
  const [taxIncluded, setTaxIncluded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const supplyTotal = useMemo(() =>
    items.reduce((s, it) => s + (parseFloat(it.quantity) || 0) * (parseFloat(it.unit_price) || 0), 0),
    [items]);
  const scCalc = useMemo(() =>
    surcharges.map(sc => ({ ...sc, amount: Math.round(supplyTotal * (parseFloat(sc.rate) || 0) / 100) })),
    [surcharges, supplyTotal]);
  const scTotal = useMemo(() => scCalc.reduce((s, sc) => s + sc.amount, 0), [scCalc]);
  const grandTotal = supplyTotal + scTotal;

  const addItem = () => setItems([...items, { item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '', note: '', item_id: null }]);
  const updItem = (i, k, v) => setItems(items.map((it, idx) => idx === i ? { ...it, [k]: v } : it));
  const updItemMulti = (i, patch) => setItems(items.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  const delItem = (i) => setItems(items.filter((_, idx) => idx !== i));
  const clearItems = () => {
    if (!confirm('품목을 모두 초기화할까요?')) return;
    setItems([{ item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '', note: '', item_id: null }]);
  };

  const addSc = () => setSurcharges([...surcharges, { name: '', rate: '' }]);
  const addVat = () => {
    if (surcharges.some(sc => sc.name === '부가세')) return;
    setSurcharges([...surcharges, { name: '부가세', rate: 10 }]);
  };
  const updSc = (i, k, v) => setSurcharges(surcharges.map((sc, idx) => idx === i ? { ...sc, [k]: v } : sc));
  const delSc = (i) => setSurcharges(surcharges.filter((_, idx) => idx !== i));

  const submit = async () => {
    setError('');
    if (!base.quote_date) { setError('견적일은 필수입니다'); return; }
    const realItems = items.filter(it => (it.item_name || '').trim());
    if (realItems.length === 0) { setError('품목을 최소 1개 이상 입력해주세요'); return; }
    setSubmitting(true);
    try {
      const data = await api.post('/quotations/create', {
        ...base, ...cust,
        items: realItems.map(it => ({
          ...it,
          quantity: parseFloat(it.quantity) || 0,
          unit_price: parseFloat(it.unit_price) || 0,
        })),
        surcharges: surcharges.filter(sc => (sc.name || '').trim()).map(sc => ({
          name: sc.name, rate: parseFloat(sc.rate) || 0,
        })),
        note,
        tax_included: taxIncluded,
      });
      nav(`/quotations/${data.quotation_id}`);
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  return (
    <div style={{ paddingBottom: 100 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1>견적서 작성</h1>
      </div>

      {error && <div style={{ margin: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(242,63,67,0.12)', color: 'var(--red)', fontSize: 13 }}>{error}</div>}

      {/* 1. 기본정보 */}
      <Section num="1" title="기본정보">
        <Field label="견적일" required>
          <input type="date" value={base.quote_date} onChange={e => setBase({ ...base, quote_date: e.target.value })} style={inp} required />
        </Field>
        <Field label="납기일">
          <input value={base.delivery_date} onChange={e => setBase({ ...base, delivery_date: e.target.value })} style={inp} />
        </Field>
        <Field label="대금지불">
          <input value={base.payment_method} onChange={e => setBase({ ...base, payment_method: e.target.value })} style={inp} />
        </Field>
        <Field label="견적유효">
          <input value={base.validity_period} onChange={e => setBase({ ...base, validity_period: e.target.value })} style={inp} />
        </Field>
        <Field label="건명">
          <input value={base.project_name} onChange={e => setBase({ ...base, project_name: e.target.value })} style={inp} placeholder="건명을 입력하세요" />
        </Field>
        <Field label="계좌번호">
          <input value={base.bank_account} onChange={e => setBase({ ...base, bank_account: e.target.value })} style={inp} placeholder="선택 입력" />
        </Field>
      </Section>

      {/* 2. 수급자 정보 */}
      <Section num="2" title="수급자 정보">
        <Field label="수급자명"><input value={cust.customer_name} onChange={e => setCust({ ...cust, customer_name: e.target.value })} style={inp} /></Field>
        <Field label="담당자"><input value={cust.customer_contact} onChange={e => setCust({ ...cust, customer_contact: e.target.value })} style={inp} /></Field>
        <Field label="Tel"><input value={cust.customer_tel} onChange={e => setCust({ ...cust, customer_tel: e.target.value })} style={inp} /></Field>
        <Field label="주소"><input value={cust.customer_address} onChange={e => setCust({ ...cust, customer_address: e.target.value })} style={inp} /></Field>
        <Field label="Fax"><input value={cust.customer_fax} onChange={e => setCust({ ...cust, customer_fax: e.target.value })} style={inp} /></Field>
        <Field label="E-mail"><input type="email" value={cust.customer_email} onChange={e => setCust({ ...cust, customer_email: e.target.value })} style={inp} /></Field>
      </Section>

      {/* 3. 품목 */}
      <Section num="3" title="품목" actions={
        <>
          <SmBtn onClick={clearItems} danger>초기화</SmBtn>
          <SmBtn onClick={addItem} primary>+ 품목 추가</SmBtn>
        </>
      }>
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
                onPick={(picked) => updItemMulti(i, {
                  item_name: picked.item_name,
                  item_spec: picked.item_spec || it.item_spec,
                  unit: picked.unit || it.unit || 'EA',
                  unit_price: picked.last_unit_price ? String(picked.last_unit_price) : it.unit_price,
                  item_id: picked.id,
                })}
              />
              <input placeholder="규격" value={it.item_spec} onChange={e => updItem(i, 'item_spec', e.target.value)} style={{ ...inp, marginBottom: 6 }} />
              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input placeholder="단위" value={it.unit} onChange={e => updItem(i, 'unit', e.target.value)} style={{ ...inp, width: 70, textAlign: 'center' }} />
                <input placeholder="수량" type="number" step="any" value={it.quantity} onChange={e => updItem(i, 'quantity', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
                <UnitPriceWithHistory
                  itemName={it.item_name}
                  value={it.unit_price}
                  onChange={(v) => updItem(i, 'unit_price', v)}
                />
              </div>
              <input placeholder="비고" value={it.note} onChange={e => updItem(i, 'note', e.target.value)} style={inp} />
            </div>
          );
        })}
      </Section>

      {/* 4. 부과금 */}
      <Section num="4" title="부과금" subtitle="공급가액의 %" actions={
        <>
          <SmBtn onClick={addVat}>부가세 10%</SmBtn>
          <SmBtn onClick={addSc} primary>+ 추가</SmBtn>
        </>
      }>
        {scCalc.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>부과금 없음</div>
        ) : scCalc.map((sc, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
            <input placeholder="이름" value={sc.name} onChange={e => updSc(i, 'name', e.target.value)} style={{ ...inp, flex: 2 }} />
            <input placeholder="rate" type="number" step="any" value={sc.rate} onChange={e => updSc(i, 'rate', e.target.value)} style={{ ...inp, width: 60, textAlign: 'right' }} />
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>%</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)', minWidth: 80, textAlign: 'right' }}>{money(sc.amount)}원</span>
            <button onClick={() => delSc(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 14, cursor: 'pointer' }}>✕</button>
          </div>
        ))}
      </Section>

      {/* 5. 비고 */}
      <Section num="5" title="비고">
        <textarea rows={3} value={note} onChange={e => setNote(e.target.value)} placeholder="비고 사항 (PDF에 표시, \ 로 줄바꿈)" style={{ ...inp, resize: 'vertical' }} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer' }}>
          <input type="checkbox" checked={taxIncluded} onChange={e => setTaxIncluded(e.target.checked)} />
          부가세 포함
        </label>
      </Section>

      {/* 합계 바 (하단 sticky) */}
      <div style={{
        position: 'fixed', bottom: 56, left: 0, right: 0, zIndex: 10,
        background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)',
        padding: '10px 16px', fontSize: 12,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
          <span style={{ color: 'var(--text-muted)' }}>공급가액</span>
          <span style={{ color: 'var(--text-bright)', fontWeight: 600 }}>{money(supplyTotal)}원</span>
        </div>
        {scCalc.map((sc, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <span style={{ color: 'var(--text-muted)' }}>{sc.name} ({sc.rate}%)</span>
            <span style={{ color: 'var(--text-bright)' }}>{money(sc.amount)}원</span>
          </div>
        ))}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, paddingTop: 6, borderTop: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>합계</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)' }}>{money(grandTotal)}원</span>
        </div>
        <button onClick={submit} disabled={submitting} style={{
          width: '100%', marginTop: 8, padding: 10, borderRadius: 6,
          background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 700,
          border: 'none', cursor: 'pointer',
        }}>{submitting ? '저장중...' : '견적서 저장'}</button>
      </div>
    </div>
  );
}

function Section({ num, title, subtitle, actions, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--accent)', color: '#fff', fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{num}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>{title}</span>
          {subtitle && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{subtitle}</span>}
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
function SmBtn({ children, onClick, primary, danger }) {
  return (
    <button onClick={onClick} type="button" style={{
      padding: '5px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
      background: primary ? 'var(--accent)' : danger ? 'rgba(242,63,67,0.15)' : 'var(--surface)',
      color: primary ? '#fff' : danger ? 'var(--red)' : 'var(--text-bright)',
    }}>{children}</button>
  );
}

const inp = {
  width: '100%', padding: '9px 10px', borderRadius: 6,
  background: 'var(--bg)', border: '1px solid var(--border)',
  color: 'var(--text)', fontSize: 13,
};
const itemCard = {
  padding: 10, borderRadius: 6, background: 'var(--surface)',
  border: '1px solid var(--border)', marginBottom: 8,
};

/* ── 품명 자동완성 ─────────────────────────────────────────────── */
function ItemNameAutocomplete({ value, onChange, onPick }) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const search = (q) => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setLoading(true);
      api.get(`/items/search?q=${encodeURIComponent(q)}`)
        .then((d) => { setResults(d.items || []); setOpen(true); })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
  };

  return (
    <div ref={boxRef} style={{ position: 'relative', marginBottom: 6 }}>
      <input
        placeholder="품명 * (자동완성)"
        value={value}
        onChange={(e) => { onChange(e.target.value); search(e.target.value); }}
        onFocus={() => { if (value) search(value); else { search(''); } }}
        style={inp}
        autoComplete="off"
      />
      {open && (
        <div style={acDropdown}>
          {loading && <div style={acEmpty}>검색중...</div>}
          {!loading && results.length === 0 && <div style={acEmpty}>검색 결과 없음</div>}
          {!loading && results.map((r) => (
            <div
              key={r.id}
              onClick={() => { onPick(r); setOpen(false); }}
              style={acRow}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: 'var(--text-bright)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.item_name}
                  </div>
                  {(r.item_spec || r.item_cd) && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.item_cd && <span>{r.item_cd} · </span>}{r.item_spec}{r.unit && ` · ${r.unit}`}
                    </div>
                  )}
                </div>
                {r.last_unit_price > 0 && (
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', whiteSpace: 'nowrap' }}>
                    {Number(r.last_unit_price).toLocaleString()}원
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── 단가 추천 (과거 견적 이력) ───────────────────────────────── */
function UnitPriceWithHistory({ itemName, value, onChange }) {
  const [history, setHistory] = useState([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const loadHistory = () => {
    const n = (itemName || '').trim();
    if (!n) { setHistory([]); return; }
    api.get(`/quote-price-history?item_name=${encodeURIComponent(n)}`)
      .then((d) => setHistory(d.history || []))
      .catch(() => setHistory([]));
  };

  return (
    <div ref={boxRef} style={{ position: 'relative', flex: 1 }}>
      <input
        placeholder="단가"
        type="number"
        step="any"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => { loadHistory(); setOpen(true); }}
        style={{ ...inp, textAlign: 'right' }}
      />
      {open && history.length > 0 && (
        <div style={acDropdown}>
          <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>과거 견적 단가</div>
          {history.map((h, i) => (
            <div
              key={i}
              onClick={() => { onChange(String(h.price)); setOpen(false); }}
              style={acRow}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>
                  {Number(h.price).toLocaleString()}원
                </span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {h.last_date}{h.count > 1 ? ` · ${h.count}회` : ''}
                </span>
              </div>
              {h.spec && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{h.spec}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const acDropdown = {
  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
  background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6,
  maxHeight: 280, overflowY: 'auto', marginTop: 2,
  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
};
const acRow = {
  padding: '8px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)',
};
const acEmpty = { padding: '10px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 };
