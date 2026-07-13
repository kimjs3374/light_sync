import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Avatar } from '../components/ArchiveKit';

export default function ChatRooms() {
  const navigate = useNavigate();
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/chat-archive/rooms')
      .then((d) => setRooms(d.rooms || []))
      .catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="channel-header">
        <button onClick={() => navigate('/archive')} style={{ background: 'none', color: 'var(--text-bright)', fontSize: 20, cursor: 'pointer' }}>←</button>
        <h1>대화방 아카이브</h1>
        <span className="ch-count">{rooms.length}</span>
      </div>
      {loading ? (
        <div className="page-loader">불러오는 중...</div>
      ) : rooms.length === 0 ? (
        <div className="page-empty">대화방이 없습니다</div>
      ) : (
        <div className="arc-board-list">
          {rooms.map((r) => (
            <div key={r.id} className="arc-board-card" onClick={() => navigate(`/chat-archive/${r.id}`)}>
              <Avatar name={r.name} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="arc-board-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                <div className="arc-board-count">메시지 {r.count.toLocaleString()}건 · {r.last_date}</div>
              </div>
              <span style={{ color: 'var(--text-muted)', fontSize: 18 }}>›</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
