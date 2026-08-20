import { useState, useEffect } from 'react';
import { api } from '../api/client';

export default function Notifications() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/notifications').then((d) => setItems(d.notifications || [])).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loader">불러오는 중...</div>;

  const unread = items.filter(n => !n.is_read).length;

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>알림</h1>
        {unread > 0 && <span className="ch-count" style={{ background: 'var(--red)', color: '#fff' }}>{unread}</span>}
      </div>

      <div className="msg-list">
        {items.length === 0 ? (
          <div className="page-empty">새로운 알림이 없습니다</div>
        ) : (
          items.map((n, i) => (
            <div key={i} className="msg-item" onClick={() => {
              if (!n.is_read) {
                api.post(`/notifications/${n.id}/read`, {}).catch(() => {});
                setItems(prev => prev.map((x, j) => j === i ? { ...x, is_read: true } : x));
              }
              if (n.link) window.open(n.link, '_blank');
            }}>
              <div className="indicator" style={{ background: n.is_read ? 'var(--border)' : 'var(--accent)' }} />
              <div className="msg-body">
                <div className="msg-top">
                  <NotiTypeBadge type={n.noti_type} />
                  <span className="msg-date">{n.created_at?.slice(5, 16)}</span>
                </div>
                {n.title && <div className="msg-title">{n.title}</div>}
                <div style={{
                  fontSize: 12, color: 'var(--text-muted)', marginTop: 2, lineHeight: 1.4,
                  whiteSpace: 'pre-line', overflowWrap: 'anywhere',
                  display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                }}>
                  {n.message}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function NotiTypeBadge({ type }) {
  const map = {
    delivery: { label: '납품', color: 'blue' },
    payment: { label: '입금', color: 'green' },
    issue: { label: '이슈', color: 'orange' },
    warranty: { label: 'AS', color: 'red' },
    document: { label: '서류', color: 'gray' },
    procurement: { label: '조달', color: 'purple' },
  };
  const m = map[type] || { label: type || '알림', color: 'gray' };
  return <span className={`badge badge-${m.color}`}>{m.label}</span>;
}
