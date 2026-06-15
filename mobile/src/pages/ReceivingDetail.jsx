import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

/* 입고 상세 + 인라인 편집
   ERP 대응: routes/receiving.py receiving_detail / receiving_edit / receiving_delete / api_po_comparison
   ERP 100% 동일 필드: rcv_no, rcv_date, vendor, po, fo, note, items[item_cd/item_name/item_spec/received_qty/unit/unit_price/amount/note]
*/

const money = (v) => Math.round(v || 0).toLocaleString();

export default function ReceivingDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);
  const [comparison, setComparison] = useState(null);

  const load = () => {
    setLoading(true);
    api.get(`/receivings/${id}`)
      .then((d) => {
        setData(d);
        setForm({
          rcv_date: d.receiving?.rcv_date || '',
          vendor_id: d.receiving?.vendor_id || '',
          vendor_name: d.receiving?.vendor_name || '',
          note: d.receiving?.note || '',
          items: (d.items || []).map((it) => ({
            id: it.id,
            po_item_id: it.po_item_id || null,
            fo_item_id: it.fo_item_id || null,
            item_cd: it.item_cd || '',
            item_name: it.item_name || '',
            item_spec: it.item_spec || '',
            received_qty: it.received_qty ?? 0,
            unit: it.unit || '',
            unit_price: it.unit_price ?? 0,
            note: it.note || '',
          })),
        });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [id]);

  // 발주 vs 입고 대사
  useEffect(() => {
    if (data?.receiving?.po_id) {
      api.get(`/receivings/po-comparison/${data.receiving.po_id}`)
        .then(setComparison).catch(() => setComparison(null));
    }
  }, [data?.receiving?.po_id]);

  const totals = useMemo(() => {
    const rows = editing ? (form?.items || []) : (data?.items || []);
    const supply = rows.reduce((s, it) => {
      const q = parseFloat(it.received_qty) || 0;
      const p = parseFloat(it.unit_price) || 0;
      return s + q * p;
    }, 0);
    const tax = Math.round(supply * 0.1);
    return { supply: Math.round(supply), tax, grand: Math.round(supply) + tax };
  }, [editing, form, data]);

  const confirmRcv = async () => {
    if (!confirm('검수완료 처리하시겠습니까?')) return;
    setBusy(true);
    try {
      await api.post(`/receivings/${id}/confirm`, {});
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const saveEdit = async () => {
    if (!form.vendor_id) { alert('거래처를 선택해주세요'); return; }
    const real = form.items.filter((it) => (it.item_name || '').trim());
    if (real.length === 0) { alert('품목을 최소 1개 입력해주세요'); return; }
    setBusy(true);
    try {
      await api.post(`/receivings/${id}/update`, {
        rcv_date: form.rcv_date,
        vendor_id: form.vendor_id,
        note: form.note,
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
      setEditing(false);
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const deleteRcv = async () => {
    if (!confirm('이 입고를 삭제하시겠습니까? 연관된 재고 이력이 영향을 받을 수 있습니다.')) return;
    try {
      await api.post(`/receivings/${id}/delete`, {});
      nav('/receivings');
    } catch (e) { alert(e.message); }
  };

  const updItem = (i, k, v) => setForm({ ...form, items: form.items.map((it, idx) => idx === i ? { ...it, [k]: v } : it) });
  const addItem = () => setForm({ ...form, items: [...form.items, { po_item_id: null, fo_item_id: null, item_cd: '', item_name: '', item_spec: '', received_qty: 0, unit: 'EA', unit_price: 0, note: '' }] });
  const delItem = (i) => setForm({ ...form, items: form.items.filter((_, idx) => idx !== i) });

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data || !data.receiving) return <div className="page-loader">입고 정보를 찾을 수 없습니다</div>;

  const rcv = data.receiving;
  const items = data.items || [];
  const isDone = rcv.status === '검수완료';
  const statusColor = isDone ? 'green' : rcv.status === '반품' ? 'red' : 'orange';

  return (
    <div style={{ paddingBottom: editing ? 170 : 80 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={backBtn}>←</button>
        <h1 style={{ fontSize: 14, fontFamily: 'monospace' }}>{rcv.rcv_no}</h1>
        <span className={`badge badge-${statusColor}`}>{rcv.status || '검수대기'}</span>
      </div>

      {/* 액션 */}
      {!editing && (
        <div style={actionBar}>
          {!isDone && (
            <button onClick={confirmRcv} disabled={busy} style={btn('var(--green)', '#fff')}>검수완료</button>
          )}
          <button onClick={() => setEditing(true)} style={btn('var(--surface)', 'var(--text-bright)')}>수정</button>
          <button onClick={deleteRcv} style={btn('rgba(242,63,67,0.15)', 'var(--red)')}>삭제</button>
          {rcv.po_id && (
            <button onClick={() => nav(`/purchase-orders/${rcv.po_id}`)} style={btn('var(--surface)', 'var(--accent)')}>발주서</button>
          )}
        </div>
      )}

      {/* 기본정보 */}
      <Section title="기본정보">
        {editing ? (
          <>
            <Field label="입고일">
              <input type="date" value={form.rcv_date || ''} onChange={(e) => setForm({ ...form, rcv_date: e.target.value })} style={inp} />
            </Field>
            <Field label="거래처">
              <VendorSelect
                value={form.vendor_name}
                onChange={(v) => setForm({ ...form, vendor_name: v })}
                onPick={(v) => setForm({ ...form, vendor_id: v.id, vendor_name: v.name })}
              />
            </Field>
            <Field label="비고">
              <textarea rows={2} value={form.note || ''} onChange={(e) => setForm({ ...form, note: e.target.value })} style={{ ...inp, resize: 'vertical' }} />
            </Field>
          </>
        ) : (
          <>
            <Row label="입고번호" value={rcv.rcv_no} mono />
            <Row label="입고일" value={rcv.rcv_date} />
            <Row label="거래처" value={rcv.vendor_name} />
            {rcv.po_no && <Row label="발주서" value={rcv.po_no} mono />}
            {rcv.fo_no && <Row label="가공발주" value={rcv.fo_no} mono />}
            {rcv.contract_name && <Row label="계약" value={rcv.contract_name} />}
            {rcv.note && <Row label="비고" value={rcv.note} />}
          </>
        )}
      </Section>

      {/* 품목 */}
      <Section title={`입고 품목 (${editing ? form.items.length : items.length})`}
        actions={editing && <SmBtn onClick={addItem} primary>+ 품목 추가</SmBtn>}>
        {editing ? (
          form.items.map((it, i) => (
            <div key={i} style={itemCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  #{i + 1}{it.po_item_id ? ' · 발주연결' : it.fo_item_id ? ' · 가공발주연결' : ' · 직접입고'}
                </span>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>
                    {money((parseFloat(it.received_qty) || 0) * (parseFloat(it.unit_price) || 0))}원
                  </span>
                  {form.items.length > 1 && (
                    <button onClick={() => delItem(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>
                  )}
                </div>
              </div>
              <input placeholder="품번" value={it.item_cd}
                onChange={(e) => updItem(i, 'item_cd', e.target.value)}
                readOnly={!!it.po_item_id || !!it.fo_item_id}
                style={{ ...inp, marginBottom: 6, opacity: (it.po_item_id || it.fo_item_id) ? 0.7 : 1 }} />
              <input placeholder="품명 *" value={it.item_name}
                onChange={(e) => updItem(i, 'item_name', e.target.value)}
                readOnly={!!it.po_item_id || !!it.fo_item_id}
                style={{ ...inp, marginBottom: 6, opacity: (it.po_item_id || it.fo_item_id) ? 0.7 : 1 }} />
              <input placeholder="규격" value={it.item_spec}
                onChange={(e) => updItem(i, 'item_spec', e.target.value)}
                readOnly={!!it.po_item_id || !!it.fo_item_id}
                style={{ ...inp, marginBottom: 6, opacity: (it.po_item_id || it.fo_item_id) ? 0.7 : 1 }} />
              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input placeholder="단위" value={it.unit} onChange={(e) => updItem(i, 'unit', e.target.value)} style={{ ...inp, width: 60, textAlign: 'center' }} />
                <input placeholder="수량" type="number" step="any" value={it.received_qty} onChange={(e) => updItem(i, 'received_qty', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
                <input placeholder="단가" type="number" step="any" value={it.unit_price} onChange={(e) => updItem(i, 'unit_price', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
              </div>
              <input placeholder="비고" value={it.note} onChange={(e) => updItem(i, 'note', e.target.value)} style={inp} />
            </div>
          ))
        ) : items.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>등록된 품목이 없습니다</div>
        ) : items.map((it, i) => (
          <div key={it.id} style={{ padding: '8px 0', borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{it.item_name}</div>
                {it.item_spec && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{it.item_spec}</div>}
                {it.item_cd && <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: 2 }}>{it.item_cd}</div>}
                {it.note && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{it.note}</div>}
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>{money(it.amount)}원</div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
              <span>{Number(it.received_qty).toLocaleString()} {it.unit}</span>
              <span>@{Number(it.unit_price).toLocaleString()}</span>
              {it.po_item_id && <span className="badge badge-blue" style={{ fontSize: 9 }}>발주연결</span>}
              {it.fo_item_id && <span className="badge badge-purple" style={{ fontSize: 9 }}>가공발주</span>}
            </div>
          </div>
        ))}
      </Section>

      {/* 금액 */}
      <Section title="금액">
        <AmountRow label="공급가액" value={money(totals.supply)} />
        <AmountRow label="부가세 10%" value={money(totals.tax)} />
        <AmountRow label="합계" value={money(totals.grand)} total />
      </Section>

      {/* 발주 vs 입고 대사 */}
      {!editing && rcv.po_id && comparison && comparison.items && (
        <Section title={`발주 vs 입고 대사 (${comparison.po_no || ''})`}>
          {comparison.items.map((row, i) => {
            const badge = row.status === '완료' ? 'green' : row.status === '과입고' ? 'orange' : 'red';
            return (
              <div key={i} style={{ padding: '6px 0', borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 600 }}>{row.item_name}</div>
                    {row.item_spec && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{row.item_spec}</div>}
                  </div>
                  <span className={`badge badge-${badge}`} style={{ fontSize: 9, alignSelf: 'flex-start' }}>{row.status}</span>
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 3, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>발주 {row.ordered_qty}{row.unit}</span>
                  <span>입고 {row.received_qty}{row.unit}</span>
                  <span style={{ color: row.diff < 0 ? 'var(--red)' : row.diff > 0 ? 'var(--orange)' : 'var(--green)' }}>차이 {row.diff > 0 ? '+' : ''}{row.diff}</span>
                </div>
              </div>
            );
          })}
        </Section>
      )}

      {/* 편집 푸터 */}
      {editing && (
        <div style={editFooter}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2, fontSize: 12 }}>
            <span style={{ color: 'var(--text-muted)' }}>공급가액</span>
            <span style={{ color: 'var(--text-bright)', fontWeight: 600 }}>{money(totals.supply)}원</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, paddingTop: 6, borderTop: '1px solid var(--border)' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>합계</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)' }}>{money(totals.grand)}원</span>
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <button onClick={() => { setEditing(false); load(); }} style={{ flex: 1, padding: 10, borderRadius: 6, border: 'none', background: 'var(--surface)', color: 'var(--text-bright)', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>취소</button>
            <button onClick={saveEdit} disabled={busy} style={{ flex: 2, padding: 10, borderRadius: 6, border: 'none', background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {busy ? '저장중...' : '저장'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 컴포넌트 ────────────────────────────────── */
function Section({ title, actions, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{title}</div>
        {actions}
      </div>
      {children}
    </div>
  );
}
function Row({ label, value, mono }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', gap: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)', fontFamily: mono ? 'monospace' : undefined, textAlign: 'right', maxWidth: '65%', wordBreak: 'break-all' }}>{value}</span>
    </div>
  );
}
function AmountRow({ label, value, total }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderTop: total ? '2px solid var(--text-bright)' : '1px solid var(--border)', marginTop: total ? 4 : 0 }}>
      <span style={{ fontSize: total ? 13 : 12, color: 'var(--text-muted)', fontWeight: total ? 700 : 400 }}>{label}</span>
      <span style={{ fontSize: total ? 15 : 12, color: total ? 'var(--accent)' : 'var(--text-bright)', fontFamily: 'monospace', fontWeight: total ? 700 : 500 }}>{value}원</span>
    </div>
  );
}
function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
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

function VendorSelect({ value, onChange, onPick }) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const search = (q) => {
    api.get(`/vendors/search?q=${encodeURIComponent(q || '')}`)
      .then((d) => { setResults(d.vendors || []); setOpen(true); })
      .catch(() => setResults([]));
  };
  return (
    <div style={{ position: 'relative' }}>
      <input placeholder="거래처 검색..." value={value || ''} autoComplete="off"
        onChange={(e) => { onChange(e.target.value); search(e.target.value); }}
        onFocus={() => search(value)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
        style={inp} />
      {open && results.length > 0 && (
        <div style={dropdown}>
          {results.map((v) => (
            <div key={v.id} onClick={() => { onPick(v); setOpen(false); }} style={row}>
              <div style={{ fontSize: 13, color: 'var(--text-bright)', fontWeight: 600 }}>{v.name}</div>
              {v.tel && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{v.tel}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const backBtn = { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' };
const actionBar = { padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap' };
const btn = (bg, color) => ({ padding: '7px 12px', borderRadius: 4, fontSize: 12, fontWeight: 600, border: 'none', cursor: 'pointer', whiteSpace: 'nowrap', background: bg, color });
const inp = { width: '100%', padding: '9px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 };
const itemCard = { padding: 10, borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)', marginBottom: 8 };
const dropdown = { position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, maxHeight: 240, overflowY: 'auto', marginTop: 2, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' };
const row = { padding: '8px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)' };
const editFooter = {
  position: 'fixed', bottom: 56, left: 0, right: 0, zIndex: 10,
  background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)', padding: '10px 16px',
};
