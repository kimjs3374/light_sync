import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const TABS = [
  { key: 'all', label: '전체' },
  { key: 'inbox', label: '결재대기' },
  { key: 'progress', label: '진행중' },
  { key: 'referenced', label: '참조/수신' },
  { key: 'done', label: '완료' },
];

const statusColor = (st) => ({
  draft: 'var(--text-muted)', pending: 'var(--warning, #d97706)',
  approved: 'var(--success, #16a34a)', rejected: 'var(--danger, #dc2626)',
  canceled: 'var(--text-muted)',
}[st] || 'var(--text-muted)');

export default function Approvals() {
  const navigate = useNavigate();
  const [tab, setTab] = useState('all');
  const [items, setItems] = useState([]);
  const [inbox, setInbox] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.get(`/approvals?tab=${tab}`)
      .then(d => { setItems(d.approvals || []); setInbox(d.inbox_count || 0); })
      .catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [tab]);

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">📋</span>
        <h1>전자결재</h1>
        <button onClick={() => navigate('/approvals/new')} style={s.newBtn}>✏️ 새 기안</button>
      </div>

      {/* 탭 */}
      <div style={s.tabBar}>
        {TABS.map(t => (
          <div key={t.key} onClick={() => setTab(t.key)}
               style={{ ...s.tab, ...(tab === t.key ? s.tabOn : {}) }}>
            {t.label}{t.key === 'inbox' && inbox > 0 ? ` (${inbox})` : ''}
          </div>
        ))}
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div>
          : items.length === 0 ? <div className="page-empty">문서가 없습니다</div>
          : items.map(d => (
            <div key={d.id} className="msg-item" onClick={() => navigate(`/approvals/${d.id}`)}
                 style={{ flexDirection: 'column', gap: 6, alignItems: 'stretch' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="indicator" style={{ background: statusColor(d.status) }} />
                <div className="msg-body" style={{ flex: 1 }}>
                  <div className="msg-top">
                    <span className="msg-date">{d.doc_no || '임시저장'} · {d.form_name}</span>
                    <span style={{ ...s.badge, color: statusColor(d.status),
                      border: `1px solid ${statusColor(d.status)}` }}>{d.status_label}</span>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-bright)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                    {d.drafter_name} {d.drafter_position} · {d.date}
                    {d.status === 'pending' && ` · ${d.approved_steps}/${d.step_count} 결재`}
                    {d.my_turn && <span style={s.turnTag}>내 차례</span>}
                    {!d.my_turn && d.my_ref && <span style={s.refTag}>{d.my_ref}</span>}
                  </div>
                </div>
              </div>
            </div>
          ))}
      </div>
    </div>
  );
}


const s = {
  newBtn: { marginLeft: 'auto', background: 'var(--accent)', color: '#fff', border: 'none',
    borderRadius: 6, padding: '6px 10px', fontSize: 13, fontWeight: 600, cursor: 'pointer' },
  tabBar: { display: 'flex', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 1 },
  tab: { flex: 1, textAlign: 'center', padding: '10px 0', fontSize: 13, color: 'var(--text-muted)', cursor: 'pointer', borderBottom: '2px solid transparent' },
  tabOn: { color: 'var(--accent)', borderBottomColor: 'var(--accent)', fontWeight: 700 },
  badge: { fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' },
  turnTag: { marginLeft: 6, background: 'var(--danger, #dc2626)', color: '#fff', fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4 },
  refTag: { marginLeft: 6, background: 'var(--accent)', color: '#fff', fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4 },
};
