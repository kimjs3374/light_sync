/**
 * 메일 SPA API 클라이언트.
 *
 * 인증은 Bearer 토큰 하나로 통일한다. 세션 쿠키를 쓰지 않으므로
 *  - CSRF 토큰(<meta>)이 없는 정적 SPA에서도 POST 가 나가고,
 *  - 나중에 mail.mgnt.kr 같은 다른 출처로 옮겨도 그대로 동작한다.
 * 토큰이 없으면 /api/app/session-token 으로 PC 세션을 한 번 교환한다
 * (모바일 SPA가 쓰는 것과 같은 핸드오프).
 */

const TOKEN_KEY = 'token';   // 모바일 SPA와 같은 키 — 한쪽에서 받은 토큰을 공유한다
const USER_KEY = 'user';

class ApiClient {
  constructor() {
    this.token = localStorage.getItem(TOKEN_KEY) || null;
    this.user = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
  }

  setToken(token) {
    this.token = token;
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  }

  /** PC 세션 쿠키 → Bearer 토큰 교환. 토큰이 이미 있으면 그대로 둔다. */
  async bootstrap() {
    if (this.token) return true;
    try {
      const res = await fetch('/api/app/session-token', { credentials: 'same-origin' });
      if (!res.ok) return false;
      const data = await res.json();
      if (!data.ok || !data.token) return false;
      this.setToken(data.token);
      this.user = data.user;
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      return true;
    } catch {
      return false;
    }
  }

  async _fetch(url, options = {}) {
    const { optional, ...rest } = options;
    options = rest;
    const headers = { ...options.headers };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    if (options.body && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      options = { ...options, body: JSON.stringify(options.body) };
    }
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      // 부가 정보를 받아오는 호출은 401 이어도 로그아웃시키지 않는다.
      // (앱이 뜨는 도중이라 토큰이 아직 없을 수 있다)
      if (optional) throw new Error('인증 없음');
      this.setToken(null);
      // PC에서 로그인하면 session-token 으로 다시 들어온다
      window.location.href = '/login?next=/webmail/';
      throw new Error('인증 만료');
    }
    return res;
  }

  async json(url, options = {}) {
    const res = await this._fetch(url, options);
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(`서버 응답을 읽지 못했습니다 (${res.status})`);
    }
    if (!res.ok && !data.error) throw new Error(`요청 실패 (${res.status})`);
    return data;
  }

  get(url) { return this.json(url); }
  post(url, body) { return this.json(url, { method: 'POST', body }); }
  del(url, body) { return this.json(url, { method: 'DELETE', body }); }

  /** 첨부 등 바이너리 — Bearer 가 필요하므로 blob 으로 받아 연다 */
  async openBinary(url, filename) {
    const res = await this._fetch(url);
    if (!res.ok) throw new Error(`다운로드 실패 (${res.status})`);
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl;
    if (filename) a.download = filename;
    else a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
  }
}

export const api = new ApiClient();

// ── 메일 API 래퍼 ─────────────────────────────────────────────────────────
const qs = (o) => Object.entries(o)
  .filter(([, v]) => v !== undefined && v !== null && v !== '')
  .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
  .join('&');

export const mailApi = {
  // 외부메일(네이버·다음 등)까지 포함 — 이 화면은 계정을 한자리에 모아 보여준다
  accounts: () => api.get('/mail/api/accounts?include_external=1'),

  folders: (account, opts = {}) =>
    api.get(`/mail/api/folders?${qs({ account, refresh: opts.refresh ? 1 : undefined, all_unread: opts.allUnread ? 1 : undefined })}`),

  messages: ({ account, folder, page = 1, perPage = 50, unreadOnly = false, searchCriteria }) =>
    api.get(`/mail/api/messages?${qs({
      account, folder, page, per_page: perPage,
      unread_only: unreadOnly ? 1 : undefined,
      search_criteria: searchCriteria,
    })}`),

  message: ({ account, folder, uid }) =>
    api.get(`/mail/api/messages/${uid}?${qs({ account, folder })}`),

  search: ({ account, folder, q }) =>
    api.get(`/mail/api/search?${qs({ account, folder, q })}`),

  setFlags: ({ account, folder, uids, flag, action }) =>
    api.post('/mail/api/flags', { uids, flag, action, folder, account_id: account }),

  move: ({ account, srcFolder, destFolder, uids }) =>
    api.post('/mail/api/move', { uids, dest_folder: destFolder, src_folder: srcFolder, account_id: account }),

  remove: ({ account, folder, uids }) =>
    api.del('/mail/api/messages', { uids, folder, account_id: account }),

  inboxUnread: (account) => api.get(`/mail/api/inbox-unread?${qs({ account })}`),

  attachmentUrl: ({ account, folder, uid, partId }) =>
    `/mail/api/attachment/${uid}/${partId}?${qs({ account, folder })}`,
};

/**
 * 화면이 옛날 버전인지 확인한다.
 *
 * 이 앱은 한 번 열면 새로고침 없이 계속 쓰는 구조라, 서버에 새 버전이 올라가도
 * 열어둔 탭은 옛날 코드를 계속 돌린다. 겉으로는 멀쩡해 보이는데 새로 생긴
 * 기능만 조용히 안 먹는다 — 실제로 대용량 첨부 링크가 그렇게 빠졌다.
 *
 * index.html 은 캐시하지 않으므로 거기 적힌 번들 파일명을 보면 판별된다.
 */
export async function isStaleBuild() {
  try {
    const mine = [...document.querySelectorAll('script[src]')]
      .map((el) => el.getAttribute('src'))
      .find((src) => src && src.includes('/assets/'));
    if (!mine) return false;

    const html = await (await fetch('/webmail/', { cache: 'no-store' })).text();
    const m = html.match(/src="([^"]*\/assets\/[^"]+\.js)"/);
    if (!m) return false;
    return m[1] !== mine;
  } catch {
    return false;   // 확인 실패는 조용히 넘어간다
  }
}
