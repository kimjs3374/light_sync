import { useState, useEffect } from 'react';
import { api } from '../api/client';

/**
 * 슬랙/디스코드 스타일 리스트 페이지
 */
export default function ListPage({
  icon = '#',
  title,
  endpoint,
  dataKey,
  stats,
  filters,
  renderItem,
  onItemClick,
  defaultParams = {},
}) {
  const [items, setItems] = useState([]);
  const [allData, setAllData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterValues, setFilterValues] = useState({});

  const fetchData = () => {
    setLoading(true);
    const params = new URLSearchParams({ ...defaultParams });
    if (search) params.set('search', search);
    Object.entries(filterValues).forEach(([k, v]) => { if (v) params.set(k, v); });
    const qs = params.toString();
    api.get(`${endpoint}${qs ? '?' + qs : ''}`)
      .then((d) => { setAllData(d); setItems(d[dataKey] || []); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchData, [search, filterValues]);

  const statCards = stats && allData ? stats(allData) : [];

  return (
    <div>
      {/* 채널 헤더 */}
      <div className="channel-header">
        <span className="ch-icon">{icon}</span>
        <h1>{title}</h1>
        <span className="ch-count">{items.length}</span>
      </div>

      {/* 통계 바 */}
      {statCards.length > 0 && (
        <div className="stat-bar">
          {statCards.map((s, i) => (
            <div key={i} className="stat-item">
              <div className="stat-num" style={{ color: s.color ? `var(--${s.color})` : 'var(--text-bright)' }}>
                {s.value ?? 0}
              </div>
              <div className="stat-label">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* 검색 */}
      <div className="search-bar">
        <input
          type="text"
          placeholder="검색..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* 필터 */}
      {filters && filters.length > 0 && (
        <div style={{ display: 'flex', gap: 6, padding: '0 16px 8px', overflowX: 'auto' }}>
          {filters.map((f) => (
            <select
              key={f.key}
              value={filterValues[f.key] || ''}
              onChange={(e) => setFilterValues((p) => ({ ...p, [f.key]: e.target.value }))}
              style={{
                padding: '5px 10px', borderRadius: 4,
                background: 'var(--bg)', border: '1px solid var(--border)',
                color: 'var(--text)', fontSize: 12,
              }}
            >
              {f.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          ))}
        </div>
      )}

      {/* 리스트 */}
      <div className="msg-list">
        {loading ? (
          <div className="page-loader">불러오는 중...</div>
        ) : items.length === 0 ? (
          <div className="page-empty">데이터 없음</div>
        ) : (
          items.map((item, i) => (
            <div
              key={item.id || i}
              className="msg-item"
              onClick={() => onItemClick?.(item)}
            >
              {renderItem(item, i)}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
