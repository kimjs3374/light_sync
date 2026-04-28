import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_OPTIONS = [
  { value: 'waiting', label: '대기', color: 'orange' },
  { value: 'in_progress', label: '진행중', color: 'blue' },
  { value: 'done', label: '완료', color: 'green' },
];

export default function DeliveryDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [changing, setChanging] = useState(false);
  const [showSplitForm, setShowSplitForm] = useState(false);
  const [splitDate, setSplitDate] = useState('');

  const load = () => {
    api.get(`/deliveries/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const changeStatus = async (newStatus) => {
    if (changing) return;
    setChanging(true);
    try {
      await api.post(`/deliveries/${id}/status`, { status: newStatus });
      load();
    } catch (e) { alert(e.message); }
    setChanging(false);
  };

  const addSplit = async () => {
    if (!splitDate) return;
    try {
      await api.post(`/deliveries/${id}/splits`, { scheduled_date: splitDate });
      setSplitDate('');
      setShowSplitForm(false);
      load();
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">납품 정보를 찾을 수 없습니다</div>;

  const d = data.delivery || {};
  const items = data.items || [];
  const history = data.history || [];
  const pct = d.planned_total_qty > 0 ? Math.round((d.delivered_total_qty / d.planned_total_qty) * 100) : 0;

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 14 }}>{d.contract_name}</h1>
      </div>

      {/* 상태 변경 */}
      <Section title="납품 상태">
        <div style={{ display: 'flex', gap: 8 }}>
          {STATUS_OPTIONS.map((opt) => (
            <button key={opt.value} onClick={() => changeStatus(opt.value)} disabled={changing}
              style={{ ...s.statusBtn, background: d.delivery_status === opt.value ? `var(--${opt.color})` : 'var(--surface)', color: d.delivery_status === opt.value ? '#fff' : 'var(--text-muted)' }}>
              {opt.label}
            </button>
          ))}
        </div>
      </Section>

      {/* 납품 정보 */}
      <Section title="납품 정보">
        <Row label="납품기한" value={d.delivery_due_date} />
        <Row label="수량" value={`${d.delivered_total_qty} / ${d.planned_total_qty}`} />
        <Row label="검수" value={d.inspection_status} />
        <Row label="담당자" value={d.contact_name} />
        <Row label="연락처" value={d.contact_phone} />
        {d.planned_total_qty > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
              <span>진행률</span><span>{pct}%</span>
            </div>
            <div className="progress-bar" style={{ height: 6 }}>
              <div className="fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}
      </Section>

      {/* 품목 */}
      {items.length > 0 && (
        <Section title={`품목 (${items.length})`}>
          {items.map((ci, i) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 13, color: 'var(--text-bright)' }}>{ci.model_name || ci.category}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>수량 {ci.quantity}</div>
            </div>
          ))}
        </Section>
      )}

      {/* 분할납품 추가 */}
      <Section title="분할납품">
        {showSplitForm ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="date" value={splitDate} onChange={(e) => setSplitDate(e.target.value)}
              style={s.dateInput} />
            <button onClick={addSplit} style={s.addBtn}>추가</button>
            <button onClick={() => setShowSplitForm(false)} style={s.cancelBtn}>취소</button>
          </div>
        ) : (
          <button onClick={() => setShowSplitForm(true)} style={s.newBtn}>+ 분할납품 추가</button>
        )}
      </Section>

      {/* 히스토리 */}
      <Section title="히스토리">
        {history.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>기록 없음</div>
        ) : (
          history.map((h, i) => (
            <div key={i} style={s.histItem}>
              <div style={s.histAvatar}>{(h.user_name || '?')[0]}</div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at?.slice(0, 16)}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5 }}>{h.content}</div>
              </div>
            </div>
          ))
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

function Row({ label, value }) {
  if (!value) return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={s.rowV}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  statusBtn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500 },
  histItem: { display: 'flex', gap: 10, padding: '6px 0' },
  histAvatar: { width: 26, height: 26, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 },
  dateInput: { flex: 1, padding: '8px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  addBtn: { padding: '8px 14px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none' },
  cancelBtn: { padding: '8px 14px', borderRadius: 6, background: 'var(--surface)', color: 'var(--text-muted)', fontSize: 13, cursor: 'pointer', border: 'none' },
  newBtn: { padding: '10px', borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', width: '100%', textAlign: 'center' },
};
