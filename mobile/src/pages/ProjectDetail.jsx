import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState('');
  const [posting, setPosting] = useState(false);

  const load = () => {
    api.get(`/projects/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const handleComment = async (e) => {
    e?.preventDefault?.();
    if (!comment.trim()) return;
    setPosting(true);
    try {
      await api.post(`/projects/${id}/comment`, { content: comment.trim() });
      setComment('');
      load();
    } catch {}
    setPosting(false);
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">현장 정보를 찾을 수 없습니다</div>;

  const p = data.project || {};
  const contracts = data.contracts || [];
  const history = data.history || [];

  return (
    <div style={{ paddingBottom: 80 }}>
      {/* 헤더 */}
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={{
          background: 'none', border: 'none', color: 'var(--accent)',
          fontSize: 14, cursor: 'pointer', padding: '4px 0',
        }}>←</button>
        <h1>{p.site_name || p.project_name}</h1>
      </div>

      {/* 정보 */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <InfoRow label="설계번호" value={p.design_number} />
        <InfoRow label="상태" value={p.status} />
        <InfoRow label="납품기한" value={p.delivery_deadline} />
        <InfoRow label="담당자" value={p.manager} />
      </div>

      {/* 계약 */}
      {contracts.length > 0 && (
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            계약 정보
          </div>
          {contracts.map((c, i) => (
            <div key={i} style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 13, color: 'var(--text-bright)' }}>{c.contract_name}</div>
              {c.amount && <div className="money" style={{ marginTop: 2 }}>{Number(c.amount).toLocaleString()}원</div>}
            </div>
          ))}
        </div>
      )}

      {/* 히스토리 (슬랙 대화 스타일) */}
      <div style={{ padding: '12px 0' }}>
        <div style={{ padding: '0 16px', fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          히스토리
        </div>
        {history.length === 0 ? (
          <div className="page-empty">기록이 없습니다</div>
        ) : (
          history.slice(0, 30).map((h, i) => (
            <div key={i} style={{
              padding: '6px 16px', display: 'flex', gap: 10,
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700, color: 'var(--accent)',
              }}>
                {(h.user_name || '?')[0]}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at?.slice(0, 16)}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5 }}>
                  {h.content}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 코멘트 입력 */}
      <div style={{
        position: 'fixed', bottom: 56, left: 0, right: 0,
        padding: '8px 12px', background: 'var(--bg-secondary)',
        borderTop: '1px solid var(--border)',
        display: 'flex', gap: 8,
      }}>
        <input
          type="text" placeholder="코멘트 입력..."
          value={comment} onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleComment()}
          style={{
            flex: 1, padding: '8px 12px', borderRadius: 6,
            background: 'var(--bg)', border: '1px solid var(--border)',
            color: 'var(--text)', fontSize: 13,
          }}
        />
        <button
          onClick={handleComment} disabled={posting}
          style={{
            padding: '8px 16px', borderRadius: 6,
            background: 'var(--accent)', color: '#fff',
            fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none',
          }}
        >
          전송
        </button>
      </div>
    </div>
  );
}

function InfoRow({ label, value }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0' }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)' }}>{value}</span>
    </div>
  );
}
