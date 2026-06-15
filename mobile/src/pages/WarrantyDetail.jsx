import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_OPTIONS = [
  { value: '접수', color: 'orange' },
  { value: '처리중', color: 'blue' },
  { value: '완료', color: 'green' },
];

export default function WarrantyDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});

  useEffect(() => {
    api.get('/warranty-cases').then((d) => {
      const w = (d.warranty_cases || []).find(c => c.id === Number(id));
      setData(w || null);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  const changeStatus = async (newStatus) => {
    try {
      await api.post(`/warranty-cases/${id}/status`, { status: newStatus });
      setData(prev => prev ? { ...prev, status: newStatus } : prev);
    } catch (e) { alert(e.message); }
  };

  const saveEdit = async () => {
    try {
      await api.post(`/warranty-cases/${id}/edit`, form);
      setData(prev => ({ ...prev, ...form }));
      setEditing(false);
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">AS 케이스를 찾을 수 없습니다</div>;

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>{data.case_no}</h1>
      </div>

      <Sec title="AS 상태">
        <div style={{ display: 'flex', gap: 8 }}>
          {STATUS_OPTIONS.map((opt) => (
            <button key={opt.value} onClick={() => changeStatus(opt.value)}
              style={{ ...s.btn, background: data.status === opt.value ? `var(--${opt.color})` : 'var(--surface)', color: data.status === opt.value ? '#fff' : 'var(--text-muted)' }}>
              {opt.value}
            </button>
          ))}
        </div>
      </Sec>

      <Sec title="케이스 정보">
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[['symptom','증상',true],['defect_type','결함유형'],['model_name','모델명'],['assigned_to','담당자'],['customer_phone','고객연락처']].map(([k,l,multi]) => (
              <div key={k}>
                <div style={s.fl}>{l}</div>
                {multi ? <textarea value={form[k]||''} onChange={e => setForm(f => ({...f,[k]:e.target.value}))} style={{...s.inp, minHeight:60}} rows={3} />
                : <input value={form[k]||''} onChange={e => setForm(f => ({...f,[k]:e.target.value}))} style={s.inp} />}
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={saveEdit} style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>저장</button>
              <button onClick={() => setEditing(false)} style={s.btn}>취소</button>
            </div>
          </div>
        ) : (
          <>
            <Row label="케이스번호" value={data.case_no} accent />
            <Row label="접수일" value={data.reported_date} />
            <Row label="완료일" value={data.completed_date} />
            <Row label="현장명" value={data.contract_name || data.project_name} />
            <Row label="결함유형" value={data.defect_type} />
            <Row label="모델명" value={data.model_name} />
            <Row label="품목" value={data.item_group} />
            <Row label="증상" value={data.symptom} />
            <Row label="고객연락처" value={data.customer_phone} />
            <Row label="담당자" value={data.assigned_to} />
            <Row label="현장방문일" value={data.site_visit_date} />
            {data.is_chargeable && <div style={{ marginTop: 8 }}><span className="badge badge-red">유상</span></div>}
            <button onClick={() => { setForm(data); setEditing(true); }}
              style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)', marginTop: 8, width: '100%' }}>수정</button>
          </>
        )}
      </Sec>
    </div>
  );
}

function Sec({ title, children }) {
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
  btn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center', background: 'var(--surface)', color: 'var(--text-muted)' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
};
