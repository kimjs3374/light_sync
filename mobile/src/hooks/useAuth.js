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

  logout: () => {
    api.setToken(null);
    localStorage.removeItem('user');
    set({ user: null, isLoggedIn: false });
  },
}));
