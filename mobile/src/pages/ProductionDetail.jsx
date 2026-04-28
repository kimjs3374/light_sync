import { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';

export default function ProductionDetail() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const team = searchParams.get('team') || 'team1';
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api.get(`/production-sites/${id}?team=${team}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [id, team]);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data || !data.ok) return <div className="page-loader">현장을 찾을 수 없습니다</div>;

  const project = data.project || {};
  const items = data.items || [];
  const stats = data.stats || {};
  const history = data.history || [];

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 13 }}>{project.name}</h1>
      </div>

      {/* 통계 */}
      <div className="stat-bar" style={{ borderBottom: '1px solid var(--border)', padding: '4px 8px' }}>
        <SI num={stats.total_proc} label="전체" />
        <SI num={stats.working_proc} label="진행중" color="accent" />
        <SI num={stats.done_proc} label="완료" color="green" />
        <SI num={`${stats.pct || 0}%`} label="완료율" color={stats.pct >= 100 ? 'green' : 'accent'} />
      </div>

      {/* 품목별 공정 카드 */}
      {items.map((ig, idx) => (
        <div key={idx} style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' }}>
              {ig.model_name}
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}> × {ig.quantity}ea</span>
            </div>
            <span style={{ fontSize: 13, fontWeight: 700, color: ig.pct >= 100 ? 'var(--green)' : 'var(--accent)' }}>
              {ig.done_proc}/{ig.total_proc} ({ig.pct}%)
            </span>
          </div>
          <div className="progress-bar" style={{ marginBottom: 10, height: 4 }}>
            <div className="fill" style={{ width: `${ig.pct}%`, background: ig.pct >= 100 ? 'var(--green)' : 'var(--accent)' }} />
          </div>

          {(ig.processes || []).map((proc) => (
            <ProcessCard key={proc.id} proc={proc} totalQty={ig.quantity} onUpdate={load} />
          ))}
        </div>
      ))}

      {/* 히스토리 */}
      {history.length > 0 && (
        <div style={{ padding: '10px 16px' }}>
          <div style={s.secTitle}>히스토리</div>
          {history.slice(0, 15).map((h, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, padding: '6px 0' }}>
              <div style={s.avatar}>{(h.user_name || '?')[0]}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at?.slice(0, 16)}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{h.content}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ProcessCard({ proc, totalQty, onUpdate }) {
  const [qty, setQty] = useState('');
  const [busy, setBusy] = useState(false);

  const isDone = proc.status === '완료' || proc.status === '스킵';
  const isActive = proc.status === '진행중';
  const isWaiting = !isDone && !isActive;
  const pct = proc.progress_pct || 0;

  const handleStart = async () => {
    setBusy(true);
    try {
      await api.post(`/production/process/${proc.id}/toggle`, { active: true });
      onUpdate();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const handleStop = async () => {
    setBusy(true);
    try {
      await api.post(`/production/process/${proc.id}/toggle`, { active: false });
      onUpdate();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const handleComplete = async () => {
    setBusy(true);
    try {
      await api.post(`/production/process/${proc.id}/complete`, { complete: !isDone });
      onUpdate();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const handleDailyLog = async () => {
    const val = parseInt(qty);
    if (!val || val <= 0) return;
    setBusy(true);
    try {
      await api.post(`/production/process/${proc.id}/daily-log`, { daily_qty: val });
      setQty('');
      onUpdate();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  return (
    <div style={{
      padding: '10px 12px', marginBottom: 8, borderRadius: 8,
      background: isDone ? 'rgba(45,199,112,0.08)' : isActive ? 'rgba(74,158,255,0.08)' : 'var(--surface)',
      border: `1px solid ${isDone ? 'var(--green)' : isActive ? 'var(--accent)' : 'var(--border)'}`,
    }}>
      {/* 공정 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{proc.step_name}</span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>{proc.step_order}단계</span>
        </div>
        <span className={`badge badge-${isDone ? 'green' : isActive ? 'blue' : 'gray'}`}>{proc.status}</span>
      </div>

      {/* 수량 + 프로그레스 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>수량 {totalQty}개</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: pct >= 100 ? 'var(--green)' : 'var(--accent)' }}>{pct}%</span>
      </div>
      <div className="progress-bar" style={{ height: 4, marginBottom: 8 }}>
        <div className="fill" style={{ width: `${pct}%`, background: pct >= 100 ? 'var(--green)' : 'var(--accent)' }} />
      </div>

      {/* 액션 버튼 */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {isWaiting && (
          <button onClick={handleStart} disabled={busy || !proc.can_start}
            style={{
              ...s.actionBtn,
              background: proc.can_start ? 'var(--accent)' : 'var(--surface)',
              color: proc.can_start ? '#fff' : 'var(--text-muted)',
              opacity: proc.can_start ? 1 : 0.5,
            }}>
            {proc.can_start ? '시작하기' : '시작불가'}
          </button>
        )}

        {isActive && (
          <>
            {/* 일일 수량 입력 */}
            <input type="number" placeholder="수량" value={qty}
              onChange={(e) => setQty(e.target.value)}
              style={{ ...s.qtyInput, width: 70 }} />
            <button onClick={handleDailyLog} disabled={busy} style={{ ...s.actionBtn, background: 'var(--accent)', color: '#fff' }}>
              입력
            </button>
            <button onClick={handleStop} disabled={busy} style={{ ...s.actionBtn, background: 'var(--surface)', color: 'var(--text-muted)' }}>
              중지
            </button>
            <button onClick={handleComplete} disabled={busy} style={{ ...s.actionBtn, background: 'var(--green)', color: '#fff' }}>
              완료
            </button>
          </>
        )}

        {isDone && (
          <button onClick={handleComplete} disabled={busy} style={{ ...s.actionBtn, background: 'var(--surface)', color: 'var(--text-muted)' }}>
            완료해제
          </button>
        )}
      </div>
    </div>
  );
}

function SI({ num, label, color }) {
  return (
    <div className="stat-item">
      <div className="stat-num" style={{ color: color ? `var(--${color})` : 'var(--text-bright)' }}>{num ?? 0}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  avatar: { width: 26, height: 26, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 },
  actionBtn: { padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none' },
  qtyInput: { padding: '7px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
};
