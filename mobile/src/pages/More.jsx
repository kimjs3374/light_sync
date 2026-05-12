import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

const CHANNELS = [
  { group: '💼 영업부', items: [
    { label: '설계관리', path: '/design' },
    { label: '계약관리', path: '/contracts' },
    { label: '협의관리', path: '/sales' },
    { label: '견적관리', path: '/quotations' },
    { label: '납품관리', path: '/deliveries' },
    { label: '서류관리', path: '/documents' },
    { label: '조도검증', path: '/illuminance' },
  ]},
  { group: '📋 관리부', items: [
    { label: '거래처관리', path: '/vendors' },
    { label: '발주관리', path: '/purchase-orders' },
    { label: '가공발주', path: '/processing-orders' },
    { label: '입고관리', path: '/receivings' },
    { label: '매출/수금', path: '/financial' },
    { label: '청구관리', path: '/billing' },
    { label: '인증서관리', path: '/certifications' },
  ]},
  { group: '📦 자재/재고', items: [
    { label: '품목관리', path: '/items' },
    { label: 'BOM관리', path: '/bom' },
    { label: '자재관리', path: '/materials' },
    { label: '재고관리', path: '/inventory' },
  ]},
  { group: '🏭 생산부', items: [
    { label: '생산1팀', path: '/production' },
    { label: '생산2팀', path: '/production?team=team2' },
    { label: '발주/입고현황', path: '/incoming' },
  ]},
  { group: '🔗 공통메뉴', items: [
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

export default function More() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>더보기</h1>
      </div>

      {/* 프로필 */}
      <div style={{
        padding: '14px 16px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: '50%', background: 'var(--accent)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 700, color: '#fff', flexShrink: 0,
        }}>
          {(user?.full_name || '?')[0]}
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-bright)' }}>{user?.full_name}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{user?.group} · {user?.position}</div>
        </div>
      </div>

      {/* 신규 생성 */}
      <div style={{ padding: '8px 12px 0' }}>
        <div style={s.groupLabel}>신규 생성</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {[
            { label: '+ 발주서', path: '/purchase-orders/create' },
            { label: '+ 가공발주', path: '/processing-orders/create' },
            { label: '+ 입고', path: '/receivings/create' },
            { label: '+ 견적서', path: '/quotations/create' },
            { label: '+ AS접수', path: '/warranty/create' },
            { label: '+ 출장', path: '/create?type=business-trip' },
            { label: '+ 거래처', path: '/vendors/create' },
            { label: '+ 품목', path: '/create?type=item' },
            { label: '+ 공구', path: '/create?type=tool' },
            { label: '+ 인증서', path: '/certifications/create' },
          ].map((btn) => (
            <button key={btn.path} onClick={() => navigate(btn.path)} style={s.createBtn}>
              {btn.label}
            </button>
          ))}
        </div>
      </div>

      {/* PC 버전 — /?pc=1로 진입하면 세션에 force_pc 플래그 저장되어 이후 리다이렉트 체인에서도 PC 유지 */}
      <div onClick={() => window.open('/?pc=1', '_blank')}
        style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 13, color: 'var(--accent)' }}>
        PC 버전 열기 →
      </div>

      {/* 채널 목록 */}
      <div style={{ padding: '8px 0 100px' }}>
        {CHANNELS.map((group) => (
          <div key={group.group}>
            <div style={s.groupLabel}>{group.group}</div>
            {group.items.map((item) => (
              <div key={item.path} onClick={() => navigate(item.path)}
                style={s.menuItem}>
                <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>#</span>
                {item.label}
              </div>
            ))}
          </div>
        ))}

        <div style={{ padding: '16px' }}>
          <button onClick={() => { logout(); navigate('/login', { replace: true }); }} style={s.logoutBtn}>
            로그아웃
          </button>
        </div>
      </div>
    </div>
  );
}

const s = {
  groupLabel: { padding: '10px 16px 4px', fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: 0.5 },
  menuItem: { padding: '8px 16px 8px 28px', cursor: 'pointer', fontSize: 14, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 },
  createBtn: { padding: '8px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: 'var(--surface)', color: 'var(--accent)', border: '1px solid var(--border)', cursor: 'pointer' },
  logoutBtn: { width: '100%', padding: 10, borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--red)', fontSize: 13, cursor: 'pointer' },
};
