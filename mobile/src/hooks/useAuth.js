import { create } from 'zustand';
import { api } from '../api/client';

export const useAuth = create((set) => ({
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  isLoggedIn: !!localStorage.getItem('token'),

  login: async (username, password) => {
    const data = await api.post('/login', { username, password });
    api.setToken(data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    set({ user: data.user, isLoggedIn: true });
    return data;
  },

  // PC↔모바일 로그인 공유: 토큰이 없을 때 PC 세션 쿠키로 토큰 발급 시도.
  // PC에서 이미 로그인했다면 재로그인 없이 그대로 진입한다.
  bootstrap: async () => {
    if (localStorage.getItem('token')) return;
    try {
      const res = await fetch('/api/app/session-token', { credentials: 'same-origin' });
      if (!res.ok) return;
      const data = await res.json();
      if (data.ok && data.token) {
        api.setToken(data.token);
        localStorage.setItem('user', JSON.stringify(data.user));
        set({ user: data.user, isLoggedIn: true });
      }
    } catch { /* 세션 없음 → 로그인 화면으로 */ }
  },

  // 로그아웃 통합: 서버 세션 쿠키까지 제거 → 동일 브라우저의 PC도 함께 로그아웃.
  logout: async () => {
    try {
      await fetch('/api/app/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: api.token ? { Authorization: `Bearer ${api.token}` } : {},
      });
    } catch { /* 네트워크 실패해도 로컬은 정리 */ }
    api.setToken(null);
    localStorage.removeItem('user');
    set({ user: null, isLoggedIn: false });
  },
}));
