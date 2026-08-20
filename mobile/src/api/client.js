const API_BASE = import.meta.env.VITE_API_BASE || '/api/app';

// 진행 중인 쓰기 요청 키 → Promise. 같은 요청이 겹쳐 들어오면 새로 쏘지 않고 붙여준다.
// (모바일 이중 탭으로 출장/입고 등이 2건 생기는 사고 방지)
function formDataKey(fd) {
  const parts = [];
  for (const [k, v] of fd.entries()) {
    parts.push(v instanceof File ? `${k}=${v.name}:${v.size}:${v.lastModified}` : `${k}=${v}`);
  }
  return parts.join('&');
}

class ApiClient {
  constructor() {
    this.token = localStorage.getItem('token') || null;
    this._inflight = new Map();
  }

  // key 가 이미 진행 중이면 그 Promise 를 그대로 돌려준다.
  // 응답은 이미 파싱된 객체라 여러 호출자가 공유해도 안전 (Response body 재사용 문제 없음).
  _dedupe(key, run) {
    if (this._inflight.has(key)) return this._inflight.get(key);
    const p = run();
    this._inflight.set(key, p);
    const clear = () => this._inflight.delete(key);
    p.then(clear, clear);
    return p;
  }

  setToken(token) {
    this.token = token;
    if (token) {
      localStorage.setItem('token', token);
    } else {
      localStorage.removeItem('token');
    }
  }

  request(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    if (method === 'GET' || method === 'HEAD') return this._request(path, options);
    // 쓰기 요청만 중복 차단 — 조회는 그대로 통과
    const key = `${method} ${path} ${options.body || ''}`;
    return this._dedupe(key, () => this._request(path, options));
  }

  async _request(path, options = {}) {
    // absolute=true 일 때 path 를 그대로 사용 (e.g. /mail/api/* 호출용)
    const { absolute, ...rest } = options;
    const url = absolute ? path : `${API_BASE}${path}`;
    const headers = { 'Content-Type': 'application/json', ...rest.headers };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const res = await fetch(url, { ...rest, headers });

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
      console.error('API 파싱 실패:', path, res.status, text.slice(0, 300));
      throw new Error(`[${path}] 서버 오류 (${res.status})`);
    }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || '요청 실패');
    }
    return data;
  }

  get(path, options = {}) {
    return this.request(path, options);
  }

  post(path, body, options = {}) {
    return this.request(path, {
      ...options,
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  del(path, body, options = {}) {
    return this.request(path, {
      ...options,
      method: 'DELETE',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  // FormData POST (multipart) — 첨부 메일 발송 등
  postForm(path, formData, options = {}) {
    // 파일명·크기까지 키에 넣어 같은 첨부 재전송만 막는다 (다른 파일 동시 업로드는 통과)
    const key = `POSTFORM ${path} ${formDataKey(formData)}`;
    return this._dedupe(key, () => this._postForm(path, formData, options));
  }

  async _postForm(path, formData, options = {}) {
    const { absolute } = options;
    const url = absolute ? path : `${API_BASE}${path}`;
    const headers = {};
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    // FormData 는 fetch 가 Content-Type(boundary 포함) 자동 설정 — 직접 지정 금지
    const res = await fetch(url, { method: 'POST', body: formData, headers });
    if (res.status === 401) {
      this.setToken(null);
      window.location.href = '/m/login';
      throw new Error('인증 만료');
    }
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { throw new Error(`[${path}] 서버 오류 (${res.status})`); }
    if (!res.ok || data.error) throw new Error(data.error || '발송 실패');
    return data;
  }

  // 첨부 등 binary 응답 (Bearer 토큰 포함) — Blob 반환
  async fetchBlob(url) {
    const headers = {};
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(`다운로드 실패 (${res.status})`);
    return res.blob();
  }
}

export const api = new ApiClient();
