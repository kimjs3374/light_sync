import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../hooks/useAuth';

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const user = useAuth((s) => s.user);
  const navigate = useNavigate();

  useEffect(() => {
    api.get('/dashboard').then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">데이터를 불러올 수 없습니다</div>;

  const kpi = data.kpi || {};
  const timeline = data.timeline || [];
  const receiving = data.receiving || {};

  const channels = [
    { group: '영업부', items: [
      { label: '계약관리', path: '/contracts', count: kpi.contracted },
      { label: '협의관리', path: '/sales' },
      { label: '납품관리', path: '/deliveries', count: kpi.urgent_delivery, alert: true },
      { label: '견적관리', path: '/quotations' },
      { label: '설계관리', path: '/design' },
      { label: '서류관리', path: '/documents' },
    ]},
    { group: '관리부', items: [
      { label: '발주관리', path: '/purchase-orders' },
      { label: '가공발주', path: '/processing-orders' },
      { label: '입고관리', path: '/receivings', count: receiving.today },
      { label: '거래처관리', path: '/vendors' },
      { label: '매출/수금', path: '/financial' },
      { label: '청구관리', path: '/billing' },
      { label: '인증서관리', path: '/certifications' },
    ]},
    { group: '생산부', items: [
      { label: '생산관리', path: '/production' },
    ]},
    { group: '자재/재고', items: [
      { label: '자재관리', path: '/materials' },
      { label: '재고관리', path: '/inventory' },
      { label: '품목관리', path: '/items' },
      { label: 'BOM관리', path: '/bom' },
    ]},
    { group: '공통', items: [
      { label: '조달내역', path: '/procurements' },
      { label: '하자관리', path: '/warranty' },
      { label: '사진관리', path: '/photos' },
      { label: '도면관리', path: '/drawings' },
      { label: '입고사진', path: '/receiving-photos' },
      { label: '출장관리', path: '/business-trips' },
      { label: '운행일지', path: '/vehicle-logs' },
      { label: '공구관리', path: '/tools' },
    ]},
  ];

  return (
    <div style={{ paddingBottom: 80 }}>
      {/* 서버 정보 */}
      <div style={{
        padding: '14px 16px 10px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-bright)' }}>
          MAGNATECH
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
          {data.today} · {user?.full_name}
        </div>
      </div>

      {/* KPI */}
      <div className="stat-bar" style={{ borderBottom: '1px solid var(--border)', padding: '4px 8px' }}>
        <StatItem num={kpi.contracted} label="진행" />
        <StatItem num={kpi.urgent_delivery} label="납품임박" color="orange" />
        <StatItem num={kpi.overdue} label="지연" color="red" />
        <StatItem num={receiving.unknown || 0} label="자재대기" color="purple" />
      </div>

      {/* 채널 목록 (부서별) */}
      <div style={{ padding: '8px 0' }}>
        {channels.map((group) => (
          <div key={group.group}>
            <div style={{ padding: '8px 16px 2px', fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: 0.5 }}>
              {group.group}
            </div>
            {group.items.map((ch) => (
              <div key={ch.path} onClick={() => navigate(ch.path)}
                style={{ padding: '6px 16px 6px 28px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>#</span>
                <span style={{ flex: 1, fontSize: 14, color: ch.alert ? 'var(--text-bright)' : 'var(--text)', fontWeight: ch.alert ? 600 : 400 }}>
                  {ch.label}
                </span>
                {ch.count > 0 && (
                  <span style={{
                    fontSize: 11, fontWeight: 700, padding: '1px 6px', borderRadius: 8,
                    background: ch.alert ? 'var(--red)' : 'var(--text-muted)',
                    color: '#fff', minWidth: 18, textAlign: 'center',
                  }}>
                    {ch.count}
                  </span>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 타임라인 */}
      {timeline.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border)', padding: '8px 0' }}>
          <div style={{
            padding: '6px 16px', fontSize: 11, fontWeight: 700,
            color: 'var(--text-muted)', textTransform: 'uppercase',
            letterSpacing: 0.5,
          }}>
            최근 활동
          </div>
          {timeline.slice(0, 15).map((t, i) => (
            <div key={i} style={{
              padding: '6px 16px', display: 'flex', gap: 10,
              borderBottom: i < Math.min(timeline.length, 15) - 1 ? '1px solid var(--border)' : 'none',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700, color: 'var(--accent)',
              }}>
                {(t.user || '?')[0]}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{t.user}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{t.time}</span>
                </div>
                <div style={{
                  fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.4,
                  display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                }}>
                  {t.text}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatItem({ num, label, color }) {
  return (
    <div className="stat-item">
      <div className="stat-num" style={{ color: color ? `var(--${color})` : 'var(--text-bright)' }}>
        {num ?? 0}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
