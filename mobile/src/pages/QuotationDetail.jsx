import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_OPTIONS = ['작성중', '발송', '수주', '실주'];

export default function QuotationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showItemForm, setShowItemForm] = useState(false);
  const [itemForm, setItemForm] = useState({ item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '' });
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});

  const load = () => {
    api.get(`/quotations/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const changeStatus = async (status) => {
    try { await api.post(`/quotations/${id}/status`, { status }); load(); } catch (e) { alert(e.message); }
  };

  const deleteQuote = async () => {
    if (!confirm('견적서를 삭제하시겠습니까?')) return;
    try { await api.post(`/quotations/${id}/delete`, {}); navigate('/quotations'); } catch (e) { alert(e.message); }
  };

  const addItem = async () => {
    if (!itemForm.item_name) return;
    try {
      await api.post(`/quotations/${id}/items`, {
        ...itemForm, quantity: parseFloat(itemForm.quantity) || 0, unit_price: parseFloat(itemForm.unit_price) || 0,
      });
      setItemForm({ item_name: '', item_spec: '', unit: 'EA', quantity: '', unit_price: '' });
      setShowItemForm(false);
      load();
    } catch (e) { alert(e.message); }
  };

  const deleteItem = async (itemId) => {
    if (!confirm('품목을 삭제하시겠습니까?')) return;
    try { await api.post(`/quotations/${id}/items/${itemId}/delete`, {}); load(); } catch (e) { alert(e.message); }
  };

  const saveEdit = async () => {
    try { await api.post(`/quotations/${id}/edit`, editForm); setEditing(false); load(); } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">견적서를 찾을 수 없습니다</div>;

  const q = data.quotation || {};
  const items = data.items || [];
  const surcharges = data.surcharges || [];
  const money = (v) => v ? Number(v).toLocaleString() + '원' : '';

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 13 }}>{q.quote_no}</h1>
        <span className={`badge badge-${q.status === '발송' ? 'green' : q.status === '수주' ? 'blue' : 'orange'}`}>{q.status}</span>
      </div>

      {/* 상태 변경 */}
      <Sec title="상태">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {STATUS_OPTIONS.map(s => (
            <button key={s} onClick={() => changeStatus(s)}
              style={{ ...st.statusBtn, background: q.status === s ? 'var(--accent)' : 'var(--surface)', color: q.status === s ? '#fff' : 'var(--text-muted)' }}>
              {s}
            </button>
          ))}
          <button onClick={deleteQuote} style={{ ...st.statusBtn, background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>삭제</button>
        </div>
      </Sec>

      {/* 견적 정보 (편집) */}
      <Sec title="견적 정보">
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[['project_name','건명'],['customer_name','수급자'],['customer_contact','담당자'],['customer_tel','전화'],['customer_email','이메일'],['validity_period','유효기간'],['delivery_date','납기'],['payment_method','결제조건'],['note','비고']].map(([k,l]) => (
              <div key={k}>
                <div style={st.fl}>{l}</div>
                <input value={editForm[k]||''} onChange={e => setEditForm(f => ({...f,[k]:e.target.value}))} style={st.inp} />
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={saveEdit} style={{ ...st.statusBtn, background: 'var(--accent)', color: '#fff', flex: 1 }}>저장</button>
              <button onClick={() => setEditing(false)} style={{ ...st.statusBtn, flex: 1 }}>취소</button>
            </div>
          </div>
        ) : (
          <>
            <Row label="견적번호" value={q.quote_no} accent />
            <Row label="견적일" value={q.quote_date} />
            <Row label="건명" value={q.project_name} />
            <Row label="수급자" value={q.customer_name} />
            <Row label="담당자" value={q.customer_contact} />
            <Row label="전화" value={q.customer_tel} />
            <Row label="이메일" value={q.customer_email} />
            <Row label="유효기간" value={q.validity_period} />
            <Row label="납기" value={q.delivery_date} />
            <Row label="결제조건" value={q.payment_method} />
            {q.note && <Row label="비고" value={q.note} />}
            <button onClick={() => { setEditForm(q); setEditing(true); }}
              style={{ ...st.statusBtn, background: 'var(--surface)', color: 'var(--accent)', marginTop: 8, width: '100%' }}>수정</button>
          </>
        )}
      </Sec>

      {/* 품목 */}
      <Sec title={`품목 (${items.length})`}>
        {items.map((item) => (
          <div key={item.id} style={st.itemRow}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div style={{ flex: 1 }}>
                <div style={st.itemName}>{item.item_name}</div>
                {item.item_spec && <div style={st.itemSpec}>{item.item_spec}</div>}
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={st.itemAmt}>{money(item.amount)}</div>
                <button onClick={() => deleteItem(item.id)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>
              </div>
            </div>
            <div style={st.itemMeta}>
              <span>{item.quantity} {item.unit}</span>
              <span>@{Number(item.unit_price).toLocaleString()}</span>
            </div>
          </div>
        ))}

        {showItemForm ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
            <input placeholder="품목명 *" value={itemForm.item_name} onChange={e => setItemForm(f => ({...f, item_name: e.target.value}))} style={st.inp} />
            <input placeholder="규격" value={itemForm.item_spec} onChange={e => setItemForm(f => ({...f, item_spec: e.target.value}))} style={st.inp} />
            <div style={{ display: 'flex', gap: 8 }}>
              <input placeholder="수량" type="number" value={itemForm.quantity} onChange={e => setItemForm(f => ({...f, quantity: e.target.value}))} style={{...st.inp, flex:1}} />
              <input placeholder="단가" type="number" value={itemForm.unit_price} onChange={e => setItemForm(f => ({...f, unit_price: e.target.value}))} style={{...st.inp, flex:1}} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={addItem} style={{ ...st.statusBtn, background: 'var(--accent)', color: '#fff', flex: 1 }}>추가</button>
              <button onClick={() => setShowItemForm(false)} style={{ ...st.statusBtn, flex: 1 }}>취소</button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowItemForm(true)} style={st.addBtn}>+ 품목 추가</button>
        )}
      </Sec>

      {/* 금액 */}
      <Sec title="금액">
        <Row label="공급가액" value={money(q.total_amount)} />
        {surcharges.map((sc, i) => <Row key={i} label={`${sc.name} (${sc.rate}%)`} value={money(sc.amount)} />)}
        <div style={st.totalRow}>
          <span style={st.totalLabel}>합계</span>
          <span style={st.totalValue}>{money(q.grand_total)}</span>
        </div>
      </Sec>
    </div>
  );
}

function Sec({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={st.secTitle}>{title}</div>
      {children}
    </div>
  );
}
function Row({ label, value, accent }) {
  if (!value) return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={{ ...s.rowV, ...(accent ? { color: 'var(--accent)', fontFamily: "'SF Mono','Consolas',monospace" } : {}) }}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right' },
};
const st = {
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  statusBtn: { padding: '8px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none', background: 'var(--surface)', color: 'var(--text-muted)' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  itemRow: { padding: '8px 0', borderBottom: '1px solid var(--border)' },
  itemName: { fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' },
  itemSpec: { fontSize: 11, color: 'var(--text-muted)', marginTop: 2 },
  itemAmt: { fontSize: 13, fontWeight: 600, color: 'var(--accent)', fontFamily: "'SF Mono','Consolas',monospace" },
  itemMeta: { display: 'flex', gap: 10, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' },
  addBtn: { padding: '10px', borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', width: '100%', textAlign: 'center', marginTop: 8 },
  totalRow: { display: 'flex', justifyContent: 'space-between', padding: '8px 0', marginTop: 4 },
  totalLabel: { fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' },
  totalValue: { fontSize: 16, fontWeight: 700, color: 'var(--accent)', fontFamily: "'SF Mono','Consolas',monospace" },
};
