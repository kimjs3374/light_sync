import { useState, useEffect } from 'react';
import { api } from '../api/client';

const STATUS_OPTIONS = ['예정', '진행중', '완료'];

const fmtDt = (s) => {
  if (!s) return '';
  return s.slice(0, 16).replace('T', ' ');
};

const emptyForm = () => ({
  title: '', destination: '', purpose: '',
  departure_date: '', return_date: '',
  vehicle: '', note: '', members: [],
});

export default function BusinessTrips() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm());
  const [users, setUsers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [detail, setDetail] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [vehicleAvail, setVehicleAvail] = useState({});   // {vehicle: {available, conflicts}}

  // 출발/복귀일 바뀌면 차량 예약 가용성 조회
  useEffect(() => {
    if (!showForm || !form.departure_date) { setVehicleAvail({}); return; }
    const p = new URLSearchParams({ departure: form.departure_date });
    if (form.return_date) p.set('return', form.return_date);
    let cancelled = false;
    api.get(`/business-trips/vehicle-availability?${p}`)
      .then(d => { if (!cancelled) setVehicleAvail(d.availability || {}); })
      .catch(() => { if (!cancelled) setVehicleAvail({}); });
    return () => { cancelled = true; };
  }, [showForm, form.departure_date, form.return_date]);

  const selVehicleConflict = form.vehicle && vehicleAvail[form.vehicle]
    && !vehicleAvail[form.vehicle].available
    ? vehicleAvail[form.vehicle].conflicts : null;

  const load = () => {
    api.get('/business-trips').then(d => setItems(d.business_trips || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  // 폼 열 때 직원/차량 프리셋 로드
  useEffect(() => {
    if (!showForm) return;
    if (users.length === 0) {
      api.get('/users').then(d => setUsers(d.users || [])).catch(() => {});
    }
    if (vehicles.length === 0) {
      api.get('/business-trips/vehicles').then(d => setVehicles(d.vehicles || [])).catch(() => {});
    }
  }, [showForm]);

  const create = async () => {
    if (!form.title || !form.destination) return alert('제목과 목적지를 입력해주세요');
    if (!form.departure_date || !form.return_date) return alert('출발일시와 복귀예상일시를 입력해주세요');
    if (!(form.members || []).some(m => (m.name || '').trim())) return alert('출장인원을 최소 1명 이상 입력해주세요');
    if (selVehicleConflict) {
      const names = selVehicleConflict.map(c => c.label).join('\n');
      if (!confirm(`${form.vehicle}은(는) 해당 기간에 이미 배정되어 있습니다:\n${names}\n\n그래도 등록할까요?`)) return;
    }
    const payload = {
      ...form,
      members: (form.members || []).filter(m => (m.name || '').trim()),
    };
    try {
      await api.post('/business-trips/create', payload);
      setShowForm(false);
      setForm(emptyForm());
      load();
    } catch (e) { alert(e.message); }
  };

  const changeStatus = async (id, status) => {
    try { await api.post(`/business-trips/${id}/status`, { status }); load(); if (detailData?.trip?.id === id) loadDetail(id); } catch (e) { alert(e.message); }
  };

  const deleteTrip = async (id) => {
    if (!confirm('출장을 삭제하시겠습니까?')) return;
    try { await api.post(`/business-trips/${id}/delete`, {}); setDetail(null); setDetailData(null); load(); } catch (e) { alert(e.message); }
  };

  const loadDetail = (id) => {
    setDetail(id);
    api.get(`/business-trips/${id}`).then(setDetailData).catch(() => setDetailData(null));
  };

  // 출장인원 조작
  const addMember = () => {
    setForm(f => ({ ...f, members: [...(f.members || []), { user_id: '', name: '', position: '', department: '' }] }));
  };
  const updateMember = (idx, patch) => {
    setForm(f => ({
      ...f,
      members: f.members.map((m, i) => i === idx ? { ...m, ...patch } : m),
    }));
  };
  const removeMember = (idx) => {
    setForm(f => ({ ...f, members: f.members.filter((_, i) => i !== idx) }));
  };
  const pickUser = (idx, userId) => {
    if (!userId) {
      updateMember(idx, { user_id: '' });
      return;
    }
    const u = users.find(x => String(x.id) === String(userId));
    if (!u) return;
    updateMember(idx, {
      user_id: u.id,
      name: u.name,
      position: u.position || '',
      department: u.user_group || '',
    });
  };

  // 상세 화면
  if (detail && detailData) {
    const t = detailData.trip || {};
    const members = detailData.members || [];
    const sc = t.status === '완료' ? 'green' : t.status === '진행중' ? 'blue' : t.status === '취소' ? 'red' : 'orange';
    return (
      <div>
        <div className="channel-header">
          <button onClick={() => { setDetail(null); setDetailData(null); }} style={s.back}>←</button>
          <h1 style={{ fontSize: 13 }}>{t.title}</h1>
          <span className={`badge badge-${sc}`}>{t.status}</span>
        </div>

        {/* 상태 변경 */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={s.secTitle}>상태</div>
          <div style={{ display: 'flex', gap: 6 }}>
            {STATUS_OPTIONS.map(st => (
              <button key={st} onClick={() => changeStatus(t.id, st)}
                style={{ ...s.btn, background: t.status === st ? `var(--${st === '완료' ? 'green' : st === '진행중' ? 'accent' : 'orange'})` : 'var(--surface)', color: t.status === st ? '#fff' : 'var(--text-muted)' }}>
                {st}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
            출발/복귀 시각에 따라 자동으로 결정됩니다 (수동 변경 가능).
          </div>
        </div>

        {/* 출장 정보 */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={s.secTitle}>출장 정보</div>
          <Row label="제목" value={t.title} />
          <Row label="목적지" value={t.destination} />
          <Row label="출발일시" value={fmtDt(t.departure_date)} />
          <Row label="복귀예상" value={fmtDt(t.return_date)} />
          <Row label="이동수단" value={t.vehicle} />
          {t.purpose && <Row label="출장목적" value={t.purpose} />}
          {t.note && <Row label="비고" value={t.note} />}
        </div>

        {/* 출장인원 */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={s.secTitle}>출장인원 ({members.length}명)</div>
          {members.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '8px 0' }}>등록된 인원 없음</div>
          ) : (
            members.map(m => (
              <div key={m.id} style={{ padding: '6px 0', fontSize: 13, color: 'var(--text-bright)', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontWeight: 600 }}>
                  {m.user_name} {m.position}
                </div>
                {m.department && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{m.department}</div>}
              </div>
            ))
          )}
        </div>

        {/* 삭제 */}
        <div style={{ padding: '16px' }}>
          <button onClick={() => deleteTrip(t.id)} style={{ width: '100%', padding: 12, borderRadius: 6, border: 'none', background: 'rgba(242,63,67,0.15)', color: 'var(--red)', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
            출장 삭제
          </button>
        </div>
      </div>
    );
  }

  // 목록 화면
  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>출장관리</h1>
        <span className="ch-count">{items.length}</span>
      </div>

      <div style={{ padding: '8px 16px' }}>
        {showForm ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--surface)', borderRadius: 8 }}>
            <div style={s.fl}>출장제목 (목적 요약) *</div>
            <input placeholder="예: 에이밍 조정 및 현장 점검" value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} style={s.inp} />

            <div style={s.fl}>출장장소 *</div>
            <input placeholder="예: 서울 강남구 OO체육관" value={form.destination} onChange={e => setForm(f => ({...f, destination: e.target.value}))} style={s.inp} />

            <div><div style={s.fl}>출발일시 *</div><input type="datetime-local" value={form.departure_date} onChange={e => setForm(f => ({...f, departure_date: e.target.value}))} style={s.inp} /></div>
            <div><div style={s.fl}>복귀예상일시 *</div><input type="datetime-local" value={form.return_date} onChange={e => setForm(f => ({...f, return_date: e.target.value}))} style={s.inp} /></div>

            <div style={s.fl}>이동수단</div>
            <select value={form.vehicle} onChange={e => setForm(f => ({...f, vehicle: e.target.value}))} style={s.inp}>
              <option value="">선택</option>
              {vehicles.map(v => {
                const info = vehicleAvail[v];
                const busy = info && !info.available;
                return <option key={v} value={v}>{busy ? `${v} (예약중)` : v}</option>;
              })}
            </select>
            {selVehicleConflict && (
              <div style={{ fontSize: 12, color: 'var(--red)', padding: '2px 2px 0' }}>
                ⚠ 이 기간 <strong>{form.vehicle}</strong>은(는) 이미 배정됨:
                {selVehicleConflict.map((c, i) => (
                  <div key={i} style={{ fontSize: 11, marginTop: 2 }}>· {c.label}</div>
                ))}
              </div>
            )}

            <div style={s.fl}>출장목적 상세</div>
            <textarea placeholder="상세 목적을 입력하세요" value={form.purpose} onChange={e => setForm(f => ({...f, purpose: e.target.value}))} style={{...s.inp, minHeight: 50}} rows={2} />

            <div style={s.fl}>비고</div>
            <textarea placeholder="추가 메모사항" value={form.note} onChange={e => setForm(f => ({...f, note: e.target.value}))} style={{...s.inp, minHeight: 40}} rows={2} />

            {/* 출장인원 */}
            <div style={{ display: 'flex', alignItems: 'center', marginTop: 4 }}>
              <div style={{ ...s.fl, flex: 1, marginBottom: 0 }}>출장인원 ({(form.members || []).length}명)</div>
              <button type="button" onClick={addMember}
                style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--accent)', background: 'transparent', color: 'var(--accent)', fontSize: 11, cursor: 'pointer' }}>
                + 인원추가
              </button>
            </div>
            {(form.members || []).length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--danger, #c0392b)', padding: '4px 0' }}>출장인원을 최소 1명 이상 추가해주세요.</div>
            )}
            {(form.members || []).map((m, idx) => (
              <div key={idx} style={{ padding: 8, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <select value={m.user_id || ''} onChange={e => pickUser(idx, e.target.value)} style={{ ...s.inp, flex: 1, padding: '6px 8px' }}>
                    <option value="">직접입력</option>
                    {users.map(u => (
                      <option key={u.id} value={u.id}>{u.name} {u.position}</option>
                    ))}
                  </select>
                  <button type="button" onClick={() => removeMember(idx)}
                    style={{ padding: '6px 8px', borderRadius: 4, border: 'none', background: 'rgba(242,63,67,0.15)', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>
                    삭제
                  </button>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input placeholder="이름 *" value={m.name} onChange={e => updateMember(idx, { name: e.target.value, user_id: '' })} style={{ ...s.inp, flex: 2 }} />
                  <input placeholder="직급" value={m.position} onChange={e => updateMember(idx, { position: e.target.value })} style={{ ...s.inp, flex: 1 }} />
                </div>
                <input placeholder="부서" value={m.department} onChange={e => updateMember(idx, { department: e.target.value })} style={s.inp} />
              </div>
            ))}

            <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
              <button onClick={create} style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>등록</button>
              <button onClick={() => { setShowForm(false); setForm(emptyForm()); }} style={s.btn}>취소</button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowForm(true)} style={s.addBtn}>+ 출장 등록</button>
        )}
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div> : items.length === 0 ? <div className="page-empty">출장 없음</div> : (
          items.map(t => {
            const sc = t.status === '완료' ? 'green' : t.status === '진행중' ? 'blue' : t.status === '취소' ? 'red' : 'orange';
            return (
              <div key={t.id} className="msg-item" onClick={() => loadDetail(t.id)} style={{ flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', gap: 10 }}>
                  <div className="indicator" style={{ background: `var(--${sc})` }} />
                  <div className="msg-body">
                    <div className="msg-top">
                      <span className="msg-date">{fmtDt(t.departure_date)} ~ {fmtDt(t.return_date)}</span>
                      <span className={`badge badge-${sc}`}>{t.status}</span>
                    </div>
                    <div className="msg-title">{t.title}</div>
                    <div className="msg-meta">
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.destination}</span>
                      {t.members_count > 0 && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.members_count}명</span>}
                      {t.vehicle && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.vehicle}</span>}
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function Row({ label, value }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right' }}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  btn: { flex: 1, padding: '10px', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', background: 'var(--surface)', color: 'var(--text-muted)', textAlign: 'center' },
  addBtn: { width: '100%', padding: '10px', borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', textAlign: 'center' },
};
