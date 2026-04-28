const API_BASE = import.meta.env.VITE_API_BASE || '/api/app';

class ApiClient {
  constructor() {
    this.token = localStorage.getItem('token') || null;
  }

  setToken(token) {
    this.token = token;
    if (token) {
      localStorage.setItem('token', token);
    } else {
      localStorage.removeItem('token');
    }
  }

  async request(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

    if (res.status === 401 && path !== '/login') {
      this.setToken(null);
      window.location.href = '/m/login';
      throw new Error('인증 만료');
    }

    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      const preview = text.slice(0, 80);
      console.error('API 파싱 실패:', path, res.status, text.slice(0, 300));
      throw new Error(`[${path}] 서버 오류 (${res.status})`);
    }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || '요청 실패');
    }
    return data;
  }

  get(path) {
    return this.request(path);
  }

  post(path, body) {
    return this.request(path, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }
}

export const api = new ApiClient();
