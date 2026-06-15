import { useState, useEffect } from 'react';
import { api } from '../api/client';

const STATUS_OPTIONS = ['사용가능', '사용중', '수리중', '폐기'];

export default function Tools() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ tool_name: '', category: '', total_qty: '1', current_location: '' });

  const load = () => {
    api.get('/tools').then(d => setItems(d.tools || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const create = async () => {
    if (!form.tool_name) return alert('공구명을 입력해주세요');
    try { await api.post('/tools/create', form); setShowForm(false); setForm({ tool_name: '', category: '', total_qty: '1', current_location: '' }); load(); } catch (e) { alert(e.message); }
  };

  const changeStatus = async (id, status) => {
    try { await api.post(`/tools/${id}/status`, { status }); load(); } catch (e) { alert(e.message); }
  };

  const deleteTool = async (id) => {
    if (!confirm('삭제하시겠습니까?')) return;
    try { await api.post(`/tools/${id}/delete`, {}); load(); } catch (e) { alert(e.message); }
  };

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>공구관리</h1>
        <span className="ch-count">{items.length}</span>
      </div>

      <div style={{ padding: '8px 16px' }}>
        {showForm ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--surface)', borderRadius: 8 }}>
            <input placeholder="공구명 *" value={form.tool_name} onChange={e => setForm(f => ({...f, tool_name: e.target.value}))} style={s.inp} />
            <input placeholder="분류" value={form.category} onChange={e => setForm(f => ({...f, category: e.target.value}))} style={s.inp} />
            <div style={{ display: 'flex', gap: 8 }}>
              <input placeholder="수량" type="number" value={form.total_qty} onChange={e => setForm(f => ({...f, total_qty: e.target.value}))} style={{...s.inp, flex:1}} />
              <input placeholder="보관위치" value={form.current_location} onChange={e => setForm(f => ({...f, current_location: e.target.value}))} style={{...s.inp, flex:1}} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={create} style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>등록</button>
              <button onClick={() => setShowForm(false)} style={s.btn}>취소</button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowForm(true)} style={s.addBtn}>+ 공구 등록</button>
        )}
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div> : items.length === 0 ? <div className="page-empty">공구 없음</div> : (
          items.map(t => {
            const sc = t.status === '사용가능' ? 'green' : t.status === '사용중' ? 'blue' : t.status === '수리중' ? 'orange' : 'red';
            return (
              <div key={t.id} className="msg-item" style={{ flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', gap: 10 }}>
                  <div className="indicator" style={{ background: `var(--${sc})` }} />
                  <div className="msg-body">
                    <div className="msg-top">
                      <span className={`badge badge-${sc}`}>{t.status}</span>
                      {t.category && <span className="badge badge-gray">{t.category}</span>}
                    </div>
                    <div className="msg-title">{t.tool_name}</div>
                    <div className="msg-meta">
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>보유 {t.total_qty} / 가용 {t.available_qty}</span>
                      {t.current_location && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.current_location}</span>}
                      {t.team && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.team}</span>}
                    </div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 4, marginLeft: 14, flexWrap: 'wrap' }}>
                  {STATUS_OPTIONS.map(st => (
                    <button key={st} onClick={() => changeStatus(t.id, st)}
                      style={{ padding: '4px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, border: 'none', cursor: 'pointer',
                        background: t.status === st ? `var(--${st === '사용가능' ? 'green' : st === '사용중' ? 'accent' : st === '수리중' ? 'orange' : 'red'})` : 'var(--surface)',
                        color: t.status === st ? '#fff' : 'var(--text-muted)' }}>
                      {st}
                    </button>
                  ))}
                  <button onClick={() => deleteTool(t.id)}
                    style={{ padding: '4px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, border: 'none', cursor: 'pointer', background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>
                    삭제
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

const s = {
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  btn: { flex: 1, padding: '10px', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', background: 'var(--surface)', color: 'var(--text-muted)', textAlign: 'center' },
  addBtn: { width: '100%', padding: '10px', borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', textAlign: 'center' },
};
