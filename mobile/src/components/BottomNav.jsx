import { useLocation, useNavigate } from 'react-router-dom';

const TABS = [
  { path: '/', label: '홈' },
  { path: '/projects', label: '현장' },
  { path: '/notifications', label: '알림' },
  { path: '/more', label: '더보기' },
];

export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();

  const isActive = (path) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <nav style={styles.nav}>
      {TABS.map((tab) => {
        const active = isActive(tab.path);
        return (
          <button
            key={tab.path}
            onClick={() => navigate(tab.path)}
            style={{ ...styles.item, color: active ? '#4a9eff' : '#8b8d91' }}
          >
            <span style={{ ...styles.dot, background: active ? '#4a9eff' : 'transparent' }} />
            <span style={styles.label}>{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

const styles = {
  nav: {
    position: 'fixed', bottom: 0, left: 0, right: 0,
    display: 'flex', background: '#222529',
    borderTop: '1px solid #35383d',
    paddingBottom: 'env(safe-area-inset-bottom, 0px)',
    zIndex: 100,
  },
  item: {
    flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
    padding: '8px 0 6px', background: 'none', border: 'none',
    cursor: 'pointer', gap: 3,
  },
  dot: { width: 4, height: 4, borderRadius: '50%' },
  label: { fontSize: 11, fontWeight: 500 },
};
