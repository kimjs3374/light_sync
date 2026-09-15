/**
 * 메일 SPA API 클라이언트.
 *
 * 인증은 Bearer 토큰 하나로 통일한다. 세션 쿠키를 쓰지 않으므로
 *  - CSRF 토큰(<meta>)이 없는 정적 SPA에서도 POST 가 나가고,
 *  - 출처가 달라져도 그대로 동작한다 (2026-09-15 mail.mgnt.kr 로 이사함).
 * 토큰이 없으면 /api/app/session-token 으로 PC 세션을 한 번 교환한다
 * (모바일 SPA가 쓰는 것과 같은 핸드오프).
 */

import { goLogin } from '../lib/erp';

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
      // ERP 에 로그인이 살아 있으면 이어받아 그대로 돌아온다
      goLogin();
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

  /** HTML·원문처럼 JSON 이 아닌 응답 (인쇄 화면, 메일 원문) */
  async text(url) {
    const res = await this._fetch(url);
    if (!res.ok) throw new Error(`불러오지 못했습니다 (${res.status})`);
    return res.text();
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

  // 상세검색 — 빈 칸은 qs() 가 알아서 떨군다. self 는 INBOX 를 받은편지함/
  // 내게쓴메일함으로 가르는 조건('exclude' | 'only')이다.
  searchAdvanced: ({ account, folder, self, ...fields }) =>
    api.get(`/mail/api/search-advanced?${qs({ account, folder, self, ...fields })}`),

  setFlags: ({ account, folder, uids, flag, action }) =>
    api.post('/mail/api/flags', { uids, flag, action, folder, account_id: account }),

  move: ({ account, srcFolder, destFolder, uids }) =>
    api.post('/mail/api/move', { uids, dest_folder: destFolder, src_folder: srcFolder, account_id: account }),

  remove: ({ account, folder, uids }) =>
    api.del('/mail/api/messages', { uids, folder, account_id: account }),

  inboxUnread: (account) => api.get(`/mail/api/inbox-unread?${qs({ account })}`),

  // 메일함 관리 — IMAP 폴더를 직접 만들고 고치고 지운다(아웃룩·휴대폰에도 그대로 보인다)
  createFolder: ({ account, name, parent }) =>
    api.post('/mail/api/folders', { account_id: account, name, parent }),
  renameFolder: ({ account, name, newName }) =>
    api.post('/mail/api/folders/rename', { account_id: account, name, new_name: newName }),
  deleteFolder: ({ account, name, force }) =>
    api.del('/mail/api/folders', { account_id: account, name, force }),

  // 메일함 순서·그룹 — IMAP 에는 순서가 없어 우리가 든다
  folderPrefs: (account) => api.get(`/mail/api/folder-prefs?${qs({ account })}`),
  saveFolderPrefs: ({ account, items }) =>
    api.post('/mail/api/folder-prefs', { account_id: account, items }),

  // 스팸 — 수신차단/수신허용 목록. 메일서버(mailcow)의 스팸필터와는 별개다
  spamList: (account) => api.get(`/mail/api/spam/list?${qs({ account })}`),
  spamAdd: ({ account, kind, value, memo }) =>
    api.post('/mail/api/spam/list', { account_id: account, kind, value, memo }),
  spamDelete: (id) => api.del(`/mail/api/spam/list/${id}`),
  // only 를 주면 그 주소만 훑는다 — 방금 차단한 주소는 즉시 치워져야 한다
  spamApply: (account, only) => api.post('/mail/api/spam/apply', { account_id: account, only }),
  spamEmpty: (account) => api.post('/mail/api/spam/empty', { account_id: account }),

  // 자동회신·자동전달·자동분류가 실제로 돌고 있는지
  automationStatus: () => api.get('/mail/api/automation-status'),

  // 인쇄 화면(서버가 그려 준다)과 원문 — Bearer 로 받아서 쓴다.
  // 주소만 새 창에 띄우면 세션 쿠키가 없을 때 로그인 화면이 대신 뜬다.
  printUrl: ({ account, folder, uid }) => `/mail/print/${uid}?${qs({ account, folder })}`,
  rawUrl: ({ account, folder, uid, download }) =>
    `/mail/api/messages/${uid}/raw?${qs({ account, folder, download: download ? 1 : undefined })}`,

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

    // 지금 서 있는 주소를 다시 읽는다 — 호스트마다 엔트리 경로가 다르다
    const html = await (await fetch(window.location.pathname, { cache: 'no-store' })).text();
    const m = html.match(/src="([^"]*\/assets\/[^"]+\.js)"/);
    if (!m) return false;
    return m[1] !== mine;
  } catch {
    return false;   // 확인 실패는 조용히 넘어간다
  }
}
