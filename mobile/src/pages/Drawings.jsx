import { useState, useEffect } from 'react';
import { api } from '../api/client';

export default function Drawings() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api.get('/drawings').then(d => setItems(d.drawings || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const deleteDrawing = async (id) => {
    if (!confirm('도면을 삭제하시겠습니까?')) return;
    try { await api.post(`/drawings/${id}/delete`, {}); load(); } catch (e) { alert(e.message); }
  };

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>도면관리</h1>
        <span className="ch-count">{items.length}</span>
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div> : items.length === 0 ? <div className="page-empty">도면 없음</div> : (
          items.map(d => (
            <div key={d.id} className="msg-item" style={{ flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', gap: 10 }}>
                <div className="indicator" style={{ background: d.convert_status === 'done' ? 'var(--green)' : 'var(--orange)' }} />
                <div className="msg-body">
                  <div className="msg-top">
                    <span className="msg-date">{d.created_at?.slice(0, 10)}</span>
                    <span className={`badge badge-${d.drawing_type === '제작도면' ? 'blue' : 'gray'}`}>{d.drawing_type}</span>
                    <span className={`badge badge-${d.convert_status === 'done' ? 'green' : 'orange'}`}>{d.convert_status}</span>
                  </div>
                  <div className="msg-title">{d.title}</div>
                  <div className="msg-meta">
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{d.project_name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Rev.{d.revision_count}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{d.created_by}</span>
                  </div>
                </div>
              </div>
              <div style={{ marginLeft: 14 }}>
                <button onClick={() => deleteDrawing(d.id)}
                  style={{ padding: '4px 10px', borderRadius: 4, fontSize: 10, fontWeight: 600, border: 'none', cursor: 'pointer', background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>
                  삭제
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
