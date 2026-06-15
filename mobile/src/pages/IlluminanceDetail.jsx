import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const FACILITIES = [
  '풋살장', '풋살장_훈련', '풋살장_경기',
  '축구장', '축구장_훈련',
  '테니스장', '테니스장_경기',
  '체육관', '공장', '물류창고',
  '주차장', '주차장_실외', '도로',
  '보행로_일반',
];

const ksColor = (s) => s === 'PASS' ? 'green' : s === 'WARNING' ? 'orange' : s === 'FAIL' ? 'red' : 'gray';

export default function IlluminanceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/illuminance/${id}`)
      .then((d) => setData(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const startEdit = () => {
    const p = data.project;
    setForm({
      project_name: p.project_name || '',
      customer: p.customer || '',
      location: p.location || '',
      facility_type: p.facility_type || '',
      install_date: p.install_date || '',
      notes: p.notes || '',
    });
    setEditing(true);
  };

  const save = async () => {
    if (!form.project_name?.trim()) return alert('프로젝트명을 입력해주세요');
    setSaving(true);
    try {
      await api.post(`/illuminance/${id}/edit`, form);
      setEditing(false);
      load();
    } catch (e) { alert(e.message); }
    setSaving(false);
  };

  const remove = async () => {
    if (!confirm('이 프로젝트를 삭제하시겠습니까? 구역/실측기록도 함께 삭제됩니다.')) return;
    try {
      await api.post(`/illuminance/${id}/delete`, {});
      navigate('/illuminance');
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data?.project) return <div className="page-loader">프로젝트를 찾을 수 없습니다</div>;

  const p = data.project;
  const areas = data.areas || [];
  const measured = areas.filter(a => a.measurement_count > 0).length;
  const passed = areas.filter(a => a.latest_ks_pass === 'PASS').length;
  const failed = areas.filter(a => a.latest_ks_pass === 'FAIL').length;

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate('/illuminance')} style={s.back}>←</button>
        <h1>{p.project_name}</h1>
      </div>

      {/* 요약 */}
      <div className="stat-bar">
        <div className="stat-item">
          <div className="stat-num">{areas.length}</div>
          <div className="stat-label">구역</div>
        </div>
        <div className="stat-item">
          <div className="stat-num" style={{ color: 'var(--accent)' }}>{measured}</div>
          <div className="stat-label">실측</div>
        </div>
        <div className="stat-item">
          <div className="stat-num" style={{ color: 'var(--green)' }}>{passed}</div>
          <div className="stat-label">PASS</div>
        </div>
        <div className="stat-item">
          <div className="stat-num" style={{ color: 'var(--red)' }}>{failed}</div>
          <div className="stat-label">FAIL</div>
        </div>
      </div>

      {/* 프로젝트 정보 */}
      <Sec title="프로젝트 정보">
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Field label="프로젝트명 *" value={form.project_name} onChange={v => setForm(f => ({ ...f, project_name: v }))} />
            <Field label="발주처" value={form.customer} onChange={v => setForm(f => ({ ...f, customer: v }))} />
            <Field label="위치" value={form.location} onChange={v => setForm(f => ({ ...f, location: v }))} />
            <div>
              <div style={s.fl}>시설 종류</div>
              <select value={form.facility_type || ''} onChange={e => setForm(f => ({ ...f, facility_type: e.target.value }))} style={s.inp}>
                <option value="">(미지정)</option>
                {FACILITIES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <Field label="설치일" type="date" value={form.install_date} onChange={v => setForm(f => ({ ...f, install_date: v }))} />
            <div>
              <div style={s.fl}>비고</div>
              <textarea value={form.notes || ''} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                rows={2} style={{ ...s.inp, minHeight: 50, resize: 'vertical' }} />
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button onClick={save} disabled={saving} style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>
                {saving ? '저장중...' : '저장'}
              </button>
              <button onClick={() => setEditing(false)} style={s.btn}>취소</button>
            </div>
          </div>
        ) : (
          <>
            <Row label="프로젝트명" value={p.project_name} accent />
            <Row label="발주처" value={p.customer} />
            <Row label="위치" value={p.location} />
            <Row label="시설 종류" value={p.facility_type} />
            <Row label="설치일" value={p.install_date} />
            <Row label="상태" value={
              { design: '설계', measured: '실측완료', reported: '리포트완료' }[p.status] || p.status
            } />
            <Row label="등록자" value={p.created_by} />
            <Row label="등록일" value={p.created_at?.slice(0, 10)} />
            <Row label="비고" value={p.notes} />
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button onClick={startEdit} style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)' }}>수정</button>
              <button onClick={remove} style={{ ...s.btn, background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>삭제</button>
            </div>
          </>
        )}
      </Sec>

      {/* 구역 목록 */}
      <Sec title={`구역 목록 (${areas.length})`}>
        {areas.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
            구역이 없습니다. PC 버전에서 PDF를 업로드해 구역을 생성해주세요.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {areas.map(a => (
              <div key={a.id} onClick={() => navigate(`/illuminance/${id}/area/${a.id}`)}
                style={s.areaCard}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-bright)' }}>
                    {a.area_name}
                  </div>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {a.latest_ks_pass && (
                      <span className={`badge badge-${ksColor(a.latest_ks_pass)}`}>
                        {a.latest_ks_pass}
                      </span>
                    )}
                    {a.measurement_count > 0 && (
                      <span className="badge badge-blue">실측 {a.measurement_count}</span>
                    )}
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <span>격자 {a.grid_rows || 0}×{a.grid_cols || 0}</span>
                  {a.lamp_type && <span>{a.lamp_type}</span>}
                  {a.lamp_watt > 0 && <span>{a.lamp_watt}W</span>}
                  {a.lamp_qty > 0 && <span>×{a.lamp_qty}</span>}
                  {a.installation_height && <span>H={a.installation_height}m</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10, marginTop: 4 }}>
                  <span>설계 Eav={fmt(a.design_eav)} Uo={fmt(a.design_uo, 3)}</span>
                  {a.latest_measured_eav != null && (
                    <span style={{ color: 'var(--accent)' }}>
                      실측 Eav={fmt(a.latest_measured_eav)} Uo={fmt(a.latest_measured_uo, 3)}
                    </span>
                  )}
                </div>
                {a.latest_eav_achievement != null && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                    달성률 Eav {fmt(a.latest_eav_achievement)}% / Uo {fmt(a.latest_uo_achievement)}%
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Sec>
    </div>
  );
}

function fmt(v, digits = 1) {
  if (v == null) return '-';
  return Number(v).toFixed(digits);
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
  if (value == null || value === '') return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={{ ...s.rowV, ...(accent ? { color: 'var(--accent)' } : {}) }}>{value}</span>
    </div>
  );
}

function Field({ label, value, onChange, type = 'text' }) {
  return (
    <div>
      <div style={s.fl}>{label}</div>
      <input type={type} value={value || ''} onChange={e => onChange(e.target.value)} style={s.inp} />
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  btn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center', background: 'var(--surface)', color: 'var(--text-muted)' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)', gap: 8 },
  rowL: { fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right', wordBreak: 'break-all' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  areaCard: { padding: 10, borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--border)', cursor: 'pointer' },
};
