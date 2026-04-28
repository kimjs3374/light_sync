import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_OPTIONS = [
  { value: '작성중', color: 'orange' },
  { value: '발주완료', color: 'blue' },
  { value: '입고완료', color: 'green' },
];

export default function PurchaseOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [changing, setChanging] = useState(false);
  const [showItemForm, setShowItemForm] = useState(false);
  const [itemForm, setItemForm] = useState({ item_name: '', spec: '', quantity: '', unit_price: '' });

  useEffect(() => {
    api.get('/purchase-orders').then((d) => {
      const po = (d.purchase_orders || []).find(p => p.id === Number(id));
      setData(po || null);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  const changeStatus = async (newStatus) => {
    if (changing) return;
    setChanging(true);
    try {
      await api.post(`/purchase-orders/${id}/status`, { status: newStatus });
      setData(prev => prev ? { ...prev, status: newStatus } : prev);
    } catch (e) { alert(e.message); }
    setChanging(false);
  };

  const addItem = async () => {
    if (!itemForm.item_name) return;
    try {
      await api.post(`/purchase-orders/${id}/items`, {
        item_name: itemForm.item_name,
        spec: itemForm.spec,
        quantity: parseInt(itemForm.quantity) || 0,
        unit_price: parseInt(itemForm.unit_price) || 0,
      });
      setItemForm({ item_name: '', spec: '', quantity: '', unit_price: '' });
      setShowItemForm(false);
      alert('품목이 추가되었습니다');
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">발주서를 찾을 수 없습니다</div>;

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>{data.po_no}</h1>
      </div>

      {/* 상태 변경 */}
      <Section title="발주 상태">
        <div style={{ display: 'flex', gap: 8 }}>
          {STATUS_OPTIONS.map((opt) => (
            <button key={opt.value} onClick={() => changeStatus(opt.value)} disabled={changing}
              style={{ ...s.statusBtn, background: data.status === opt.value ? `var(--${opt.color})` : 'var(--surface)', color: data.status === opt.value ? '#fff' : 'var(--text-muted)' }}>
              {opt.value}
            </button>
          ))}
        </div>
      </Section>

      {/* 정보 */}
      <Section title="발주 정보">
        <Row label="발주번호" value={data.po_no} accent />
        <Row label="발주일" value={data.po_date} />
        <Row label="거래처" value={data.vendor_name} />
        <Row label="현장" value={data.project_name} />
        <Row label="품목수" value={`${data.item_count}건`} />
        {data.total_amount > 0 && <Row label="금액" value={Number(data.total_amount).toLocaleString() + '원'} />}
        {data.email_sent_at && <Row label="메일발송" value={data.email_sent_at} />}
        {data.note && <Row label="비고" value={data.note} />}
      </Section>

      {/* 품목 추가 */}
      <Section title="품목 추가">
        {showItemForm ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input placeholder="품목명 *" value={itemForm.item_name} onChange={(e) => setItemForm(f => ({ ...f, item_name: e.target.value }))} style={s.input} />
            <input placeholder="규격" value={itemForm.spec} onChange={(e) => setItemForm(f => ({ ...f, spec: e.target.value }))} style={s.input} />
            <div style={{ display: 'flex', gap: 8 }}>
              <input placeholder="수량" type="number" value={itemForm.quantity} onChange={(e) => setItemForm(f => ({ ...f, quantity: e.target.value }))} style={{ ...s.input, flex: 1 }} />
              <input placeholder="단가" type="number" value={itemForm.unit_price} onChange={(e) => setItemForm(f => ({ ...f, unit_price: e.target.value }))} style={{ ...s.input, flex: 1 }} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={addItem} style={s.addBtn}>추가</button>
              <button onClick={() => setShowItemForm(false)} style={s.cancelBtn}>취소</button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowItemForm(true)} style={s.newBtn}>+ 품목 추가</button>
        )}
      </Section>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>{title}</div>
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
  statusBtn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500 },
  input: { padding: '10px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  addBtn: { flex: 1, padding: '10px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none' },
  cancelBtn: { flex: 1, padding: '10px', borderRadius: 6, background: 'var(--surface)', color: 'var(--text-muted)', fontSize: 13, cursor: 'pointer', border: 'none' },
  newBtn: { padding: '10px', borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', width: '100%', textAlign: 'center' },
};
