import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { api } from './api/client';
import './styles.css';

/**
 * 부팅: Bearer 토큰이 없으면 PC 세션 쿠키로 한 번 교환한다.
 * 교환도 실패하면 로그인 화면으로 보낸다 (돌아올 곳을 next 로 남긴다).
 */
(async () => {
  const ok = await api.bootstrap();
  if (!ok) {
    // 돌아올 곳은 지금 서 있는 경로 그대로 —
    // mail.mgnt.kr 은 '/', work.mgnt.kr 은 '/webmail/' 이다
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    return;
  }
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
})();
