import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import QrScanner from '../components/QrScanner';

const STATUS_COLOR = {
  '제작중': 'gray', '보관중': 'green', '시험중': 'blue',
  '반출': 'orange', '반납완료': 'blue', '폐기': 'red',
};
const EXPIRY_BADGE = {
  expired: { text: '성적서 만료', color: 'red' },
  critical: { text: '성적서 7일', color: 'red' },
  warning: { text: '성적서 30일', color: 'orange' },
};

export default function Samples() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState({});
  const [purposes, setPurposes] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [purpose, setPurpose] = useState('');
  const [scanning, setScanning] = useState(false);

  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (q) p.set('q', q);
    if (status) p.set('status', status);
    if (purpose) p.set('purpose', purpose);
    setLoading(true);
    api.get(`/samples?${p.toString()}`)
      .then(d => {
        setItems(d.samples || []);
        setStats(d.stats || {});
        setPurposes(d.purpose_choices || []);
        setStatuses(d.status_choices || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [q, status, purpose]);

  // 필터 변경은 바로, 검색어 입력은 350ms 디바운스
  useEffect(() => {
    const t = setTimeout(load, q ? 350 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  // QR 스캔 → 시료 상세로 직행
  const onDetect = async (value) => {
    setScanning(false);
    try {
      const d = await api.get(`/samples/resolve?v=${encodeURIComponent(value)}`);
      navigate(`/samples/${d.sample_id}`);
    } catch (e) {
      alert(e.message || '등록되지 않은 QR입니다');
    }
  };

  // 시료번호 직접 입력 → 정확히 1건이면 직행, 아니면 검색 결과로
  const onManual = async (text) => {
    setScanning(false);
    try {
      const d = await api.get(`/samples?q=${encodeURIComponent(text)}`);
      const list = d.samples || [];
      if (list.length === 1) return navigate(`/samples/${list[0].id}`);
      setQ(text);
      if (!list.length) alert('일치하는 시료가 없습니다');
    } catch (e) {
      alert(e.message);
    }
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>시료관리</h1>
        <span className="ch-count">{items.length}</span>
      </div>

      {/* 스캔 / 등록 — 1탭 직행 */}
      <div style={{ display: 'flex', gap: 8, padding: '10px 16px 4px' }}>
        <button onClick={() => setScanning(true)} style={s.scanBtn}>📷 QR 스캔</button>
        <button onClick={() => navigate('/samples/create')} style={s.addBtn}>+ 시료 등록</button>
      </div>

      {/* 검색 */}
      <div style={{ padding: '4px 16px 8px' }}>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="시료번호 · 모델명 · 보관위치 검색"
          style={s.inp}
        />
      </div>

      {/* 상태 필터 */}
      <div style={s.chipRow}>
        <Chip on={!status && !purpose} onClick={() => { setStatus(''); setPurpose(''); }}>
          전체 {stats.total ?? 0}
        </Chip>
        {statuses.map(st => (
          <Chip key={st} on={status === st} onClick={() => setStatus(status === st ? '' : st)}>
            {st}
            {st === '보관중' && stats.stored != null ? ` ${stats.stored}` : ''}
            {st === '시험중' && stats.testing != null ? ` ${stats.testing}` : ''}
            {st === '반출' && stats.out != null ? ` ${stats.out}` : ''}
          </Chip>
        ))}
      </div>

      {/* 용도 필터 */}
      <div style={{ ...s.chipRow, paddingTop: 0 }}>
        {purposes.map(p => (
          <Chip key={p} on={purpose === p} onClick={() => setPurpose(purpose === p ? '' : p)} small>
            {p}
          </Chip>
        ))}
      </div>

      <div className="msg-list">
        {loading ? (
          <div className="page-loader">불러오는 중...</div>
        ) : items.length === 0 ? (
          <div className="page-empty">시료 없음</div>
        ) : (
          items.map(sm => {
            const sc = STATUS_COLOR[sm.status] || 'gray';
            const eb = EXPIRY_BADGE[sm.expiry_status];
            return (
              <div key={sm.id} className="msg-item" onClick={() => navigate(`/samples/${sm.id}`)}
                   style={{ cursor: 'pointer' }}>
                <div className="indicator" style={{ background: `var(--${sc})` }} />
                <div className="msg-body">
                  <div className="msg-top">
                    <span className={`badge badge-${sc}`}>{sm.status}</span>
                    <span className="badge badge-gray">{sm.purpose}</span>
                    {eb && <span className={`badge badge-${eb.color}`}>{eb.text}</span>}
                  </div>
                  <div className="msg-title" style={{ fontFamily: 'monospace', fontWeight: 700 }}>
                    {sm.sample_no}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text)' }}>{sm.model_name}</div>
                  <div className="msg-meta">
                    <span style={s.meta}>시험 {sm.test_count}건</span>
                    {sm.location && <span style={s.meta}>{sm.location}</span>}
                    {sm.mfg_date && <span style={s.meta}>{sm.mfg_date}</span>}
                    {sm.scan_count > 0 && <span style={s.meta}>스캔 {sm.scan_count}</span>}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {scanning && (
        <QrScanner
          onDetect={onDetect}
          onManual={onManual}
          onClose={() => setScanning(false)}
        />
      )}
    </div>
  );
}

function Chip({ on, onClick, children, small }) {
  return (
    <button onClick={onClick} style={{
      padding: small ? '4px 9px' : '5px 11px',
      borderRadius: 14, border: 'none', cursor: 'pointer', flexShrink: 0,
      fontSize: small ? 11 : 12, fontWeight: 600,
      background: on ? 'var(--accent)' : 'var(--surface)',
      color: on ? '#fff' : 'var(--text-muted)',
    }}>{children}</button>
  );
}

const s = {
  inp: {
    width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)',
    border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13,
  },
  scanBtn: {
    flex: 1, padding: '11px', borderRadius: 6, border: 'none', cursor: 'pointer',
    background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 700,
  },
  addBtn: {
    flex: 1, padding: '11px', borderRadius: 6, cursor: 'pointer',
    background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600,
    border: '1px dashed var(--border)',
  },
  chipRow: {
    display: 'flex', gap: 6, overflowX: 'auto', padding: '6px 16px',
    scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch',
  },
  meta: { fontSize: 11, color: 'var(--text-muted)' },
};
