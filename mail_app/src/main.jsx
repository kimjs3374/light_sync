import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { api } from './api/client';
import { goLogin, loginSettled } from './lib/erp';
import './styles.css';
import { applyTheme, loadTheme } from './lib/theme';

// 테마는 그리기 전에 건다 — React 가 그린 뒤에 걸면 흰 화면이 한 번 번쩍인다
applyTheme(loadTheme());

/**
 * 부팅: Bearer 토큰이 없으면 이 호스트의 세션 쿠키로 한 번 교환한다.
 * 교환도 실패하면 ERP 의 로그인을 이어받으러 나간다 (lib/erp.js 의 goLogin).
 */
(async () => {
  const ok = await api.bootstrap();
  if (!ok) {
    goLogin();
    return;
  }
  loginSettled();
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
})();
