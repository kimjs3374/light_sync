import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function ProductionSites() {
  const [sites, setSites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [team, setTeam] = useState('team1');
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    api.get(`/production-sites?team=${team}`).then((d) => {
      setSites(d.sites || []);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [team]);

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>{team === 'team1' ? '생산1팀' : '생산2팀'}</h1>
        <span className="ch-count">{sites.length}</span>
      </div>

      {/* 팀 전환 */}
      <div style={{ display: 'flex', gap: 6, padding: '8px 16px' }}>
        {[{ key: 'team1', label: '생산1팀' }, { key: 'team2', label: '생산2팀' }].map((t) => (
          <button key={t.key} onClick={() => setTeam(t.key)}
            style={{
              flex: 1, padding: '8px 0', borderRadius: 6, fontSize: 13, fontWeight: 600,
              border: 'none', cursor: 'pointer',
              background: team === t.key ? 'var(--accent)' : 'var(--surface)',
              color: team === t.key ? '#fff' : 'var(--text-muted)',
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* 현장 카드 목록 */}
      <div className="msg-list">
        {loading ? (
          <div className="page-loader">불러오는 중...</div>
        ) : sites.length === 0 ? (
          <div className="page-empty">생산 현장이 없습니다</div>
        ) : (
          sites.map((site) => {
            const ddayColor = site.dday != null && site.dday < 0 ? 'var(--red)' : site.dday != null && site.dday <= 7 ? 'var(--orange)' : 'var(--text-muted)';
            const ddayText = site.dday != null ? (site.dday < 0 ? `D+${Math.abs(site.dday)}` : `D-${site.dday}`) : '';
            return (
              <div key={site.project_id} className="msg-item"
                onClick={() => navigate(`/production-site/${site.project_id}?team=${team}`)}>
                <div className="indicator" style={{
                  background: site.pct >= 100 ? 'var(--green)' : site.dday != null && site.dday < 0 ? 'var(--red)' : 'var(--border)',
                }} />
                <div className="msg-body">
                  <div className="msg-title">{site.site_name}</div>
                  <div className="msg-top" style={{ marginTop: 3 }}>
                    <span className="msg-id">{site.project_no}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{site.items_count}품목 · {site.total_proc}공정</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>납기 {site.delivery_date}</span>
                    {ddayText && <span className={`badge badge-${site.dday < 0 ? 'red' : site.dday <= 7 ? 'orange' : 'gray'}`}>{ddayText}</span>}
                  </div>

                  {/* 품목 목록 */}
                  <div style={{ marginTop: 4 }}>
                    {(site.item_summaries || []).map((is_, i) => (
                      <div key={i} style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {is_.category} · {is_.model_name} × {is_.quantity}
                      </div>
                    ))}
                  </div>

                  {/* 진행/완료 + 프로그레스 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      진행 {site.working_proc} · 완료 {site.done_proc}/{site.total_proc}
                    </span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: site.pct >= 100 ? 'var(--green)' : 'var(--accent)' }}>
                      {site.pct}%
                    </span>
                  </div>
                  <div className="progress-bar" style={{ marginTop: 4 }}>
                    <div className="fill" style={{ width: `${site.pct}%`, background: site.pct >= 100 ? 'var(--green)' : 'var(--accent)' }} />
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
