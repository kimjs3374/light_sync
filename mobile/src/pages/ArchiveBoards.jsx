import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const ICON = {
  site: '🏗️', as: '🔧', material: '📦', contract: '📄',
  equipment: '🚚', fab: '🏭', meeting: '💬', notice: '📢',
};

export default function ArchiveBoards() {
  const navigate = useNavigate();
  const [boards, setBoards] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/archive/boards')
      .then((d) => setBoards(d.boards || []))
      .catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">🗂️</span>
        <h1>워크보드 아카이브</h1>
      </div>
      {loading ? (
        <div className="page-loader">불러오는 중...</div>
      ) : (
        <div className="arc-board-list">
          {boards.map((b) => (
            <div key={b.slug} className="arc-board-card" onClick={() => navigate(`/archive/${b.slug}`)}>
              <div className="arc-board-ico">{ICON[b.slug] || '🗂️'}</div>
              <div style={{ flex: 1 }}>
                <div className="arc-board-name">{b.label}</div>
                <div className="arc-board-count">게시글 {b.count.toLocaleString()}건</div>
              </div>
              <span style={{ color: 'var(--text-muted)', fontSize: 18 }}>›</span>
            </div>
          ))}
          <div
            className="arc-board-card" onClick={() => navigate('/chat-archive')}
            style={{ marginTop: 14 }}
          >
            <div className="arc-board-ico">🗨️</div>
            <div style={{ flex: 1 }}>
              <div className="arc-board-name">대화방 아카이브</div>
              <div className="arc-board-count">카카오워크 대화방 백업</div>
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: 18 }}>›</span>
          </div>
        </div>
      )}
    </div>
  );
}
