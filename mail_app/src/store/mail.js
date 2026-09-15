import { create } from 'zustand';
import { mailApi } from '../api/client';

/**
 * 설정은 브라우저에 남긴다 — 목록 밀도와 경계선 위치는 사람마다 갈린다.
 * splitPct: 목록이 차지하는 가로 비율(%). 읽기창은 늘 오른쪽에 붙는다.
 */
const PREF_KEY = 'webmail_prefs';
const DEFAULT_PREFS = { density: 'cozy', splitPct: 44 };
export const SPLIT_MIN = 26;
export const SPLIT_MAX = 72;

const loadPrefs = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(PREF_KEY) || '{}');
    const pct = Number(saved.splitPct);
    return {
      ...DEFAULT_PREFS,
      ...saved,
      splitPct: Number.isFinite(pct) ? Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, pct)) : DEFAULT_PREFS.splitPct,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
};

/** 빠른 필터 → IMAP 검색 조건. 첨부는 IMAP 표준 조건이 없어 화면에서 거른다. */
const FILTER_CRITERIA = {
  all: '',
  unread: 'UNSEEN',
  flagged: 'FLAGGED',
  attach: '',   // clientSide
};

/** 첨부 필터는 서버가 못 걸러주므로 화면에서 건다 (현재 쪽 기준) */
export const visibleMessages = (s) =>
  s.quickFilter === 'attach' ? s.messages.filter((m) => m.has_attachment) : s.messages;

export const useMail = create((set, get) => ({
  // ── 계정 ──
  accounts: [],
  accountId: null,

  // ── 폴더 ──
  folders: [],
  labels: [],
  folder: 'INBOX',
  /**
   * 메일함이 아닌 화면.
   *  'scheduled' — 예약 대기열(우리 DB). 목록 화면을 따로 쓴다.
   *  'selfbox'   — 내게 쓴 메일. 받은편지함에서 보낸사람이 나인 것만 추린다.
   *                (내게 보낸 메일은 보낸편지함에도 남지만, 받은 쪽 한 벌만 보면 된다)
   */
  specialView: null,
  /** 내게쓴메일함 안읽음 수 */
  selfUnread: 0,

  // ── 목록 ──
  messages: [],
  total: 0,
  page: 1,
  pages: 1,
  listLoading: false,
  listError: '',

  // ── 선택/읽기 ──
  checked: new Set(),
  openUid: null,
  cursor: 0,
  detail: null,
  detailLoading: false,
  detailError: '',

  // ── 보기 상태 ──
  quickFilter: 'all',
  searchQuery: '',
  searching: false,
  prefs: loadPrefs(),

  setPref(key, value) {
    const prefs = { ...get().prefs, [key]: value };
    localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
    set({ prefs });
  },

  // ── 초기화 ────────────────────────────────────────────────────────────
  async init() {
    const res = await mailApi.accounts();
    const accounts = res.accounts || [];
    if (!accounts.length) {
      set({ accounts: [], listError: 'no-account' });
      return;
    }
    const saved = parseInt(localStorage.getItem('webmail_account') || '', 10);
    const accountId = accounts.some((a) => a.id === saved) ? saved : accounts[0].id;
    set({ accounts, accountId });
    await get().loadFolders();
    await get().loadMessages();
  },

  async switchAccount(accountId) {
    localStorage.setItem('webmail_account', String(accountId));
    set({
      accountId, folder: 'INBOX', page: 1, openUid: null, detail: null,
      checked: new Set(), quickFilter: 'all', searchQuery: '', specialView: null,
    });
    await get().loadFolders();
    await get().loadMessages();
  },

  async loadFolders(refresh = false) {
    const { accountId } = get();
    if (!accountId) return;
    try {
      const res = await mailApi.folders(accountId, { refresh });
      set({ folders: res.folders || [], labels: res.labels || [] });
    } catch (e) {
      // 폴더는 실패해도 목록은 볼 수 있어야 한다
      console.error('폴더 조회 실패', e);
    }
    get().refreshInboxUnread();
  },

  /**
   * 받은편지함 안읽음 수만 따로 받아 뱃지를 맞춘다.
   *
   * /mail/api/folders 의 안읽음 수는 서버에서 5분 캐시되는데 그 캐시가
   * 워커별 메모리다. gunicorn 이 8워커로 돌아서 읽음 처리한 워커와 다음
   * 요청을 받는 워커가 다르면 낡은 숫자가 그대로 온다. 뱃지가 3인데
   * 눌렀더니 빈 목록이 나오는 상황이 실제로 재현됐다.
   * /mail/api/inbox-unread 는 캐시가 없고 IMAP 왕복 한 번이라 이걸 쓴다.
   *
   * (폴더 목록 자체는 캐시된 걸 그대로 써서 화면은 즉시 뜨고,
   *  숫자만 잠시 뒤에 맞춰진다.)
   */
  /**
   * 받은편지함·내게쓴메일함의 안읽음 수를 따로 센다.
   *
   * 화면에 보이는 목록과 뱃지 숫자의 기준이 같아야 한다 — 뱃지는 1인데
   * 눌렀더니 빈 목록이면 그게 더 혼란스럽다.
   * (/mail/api/folders 의 숫자는 서버 캐시 + 워커별 메모리라 못 믿는다)
   */
  async refreshInboxUnread() {
    const { accountId, accounts } = get();
    if (!accountId) return;
    const me = accounts.find((a) => a.id === accountId)?.email;
    if (!me) return;

    const countOf = async (criteria) => {
      const res = await mailApi.messages({
        account: accountId, folder: 'INBOX', page: 1, perPage: 1, searchCriteria: criteria,
      });
      return typeof res.total === 'number' ? res.total : null;
    };

    try {
      const [inbox, self] = await Promise.all([
        countOf(`UNSEEN NOT FROM "${me}"`),
        countOf(`UNSEEN FROM "${me}"`),
      ]);
      if (get().accountId !== accountId) return;   // 그 사이 계정이 바뀌었으면 버린다
      set((s) => ({
        selfUnread: self ?? s.selfUnread,
        folders: inbox === null ? s.folders : s.folders.map((f) =>
          (f.name.toUpperCase() === 'INBOX' ? { ...f, unread: inbox } : f)),
      }));
    } catch {
      /* 뱃지는 부가 정보 — 실패해도 화면은 그대로 둔다 */
    }
  },


  // ── 메일함 이동 / 목록 ────────────────────────────────────────────────

  /** 예약함·내게쓴메일함처럼 실제 IMAP 폴더가 아닌 화면 열기 */
  openSpecial(name) {
    set({
      specialView: name, openUid: null, detail: null,
      checked: new Set(), cursor: 0, searchQuery: '', quickFilter: 'all',
    });
    if (name === 'selfbox') {
      set({ folder: 'INBOX', page: 1 });
      get().loadMessages();
    }
  },

  /**
   * 메일함 이동.
   *
   * 필터는 일회용이다 — 메일함을 옮기면 항상 '전체'로 돌아온다.
   * 필터가 따라다니면 "받은편지함을 눌렀는데 목록이 비어 있다"가 되고,
   * 그게 왜 비었는지는 화면 어디에도 안 적혀 있다.
   *
   * unreadOnly: 안읽음 뱃지를 눌러 들어온 경우 — 그 메일함으로 옮기면서
   * 안읽은 메일만 걸어 바로 보여준다.
   */
  selectFolder(name, { unreadOnly = false } = {}) {
    set({
      specialView: null,
      folder: name, page: 1, openUid: null, detail: null,
      checked: new Set(), cursor: 0, searchQuery: '',
      quickFilter: unreadOnly ? 'unread' : 'all',
    });
    get().loadMessages();
  },

  setQuickFilter(f) {
    set({ quickFilter: f, page: 1, checked: new Set(), cursor: 0 });
    get().loadMessages();
  },

  goPage(p) {
    set({ page: p, checked: new Set(), cursor: 0 });
    get().loadMessages();
    document.querySelector('.msg-list')?.scrollTo({ top: 0 });
  },

  async loadMessages() {
    const { accountId, folder, page, quickFilter } = get();
    if (!accountId) return;
    set({ listLoading: true, listError: '' });
    try {
      let criteria = FILTER_CRITERIA[quickFilter];
      // 받은편지함과 내게쓴메일함은 같은 INBOX 를 나눠 본다.
      //  - 내게쓴메일함: 보낸사람이 나인 것만
      //  - 받은편지함  : 그 나머지 (내가 나에게 보낸 건 여기 안 보인다)
      const me = get().accounts.find((a) => a.id === accountId)?.email;
      if (me && String(folder).toUpperCase() === 'INBOX') {
        const self = get().specialView === 'selfbox' ? `FROM "${me}"` : `NOT FROM "${me}"`;
        criteria = criteria ? `${self} ${criteria}` : self;
      }

      const res = await mailApi.messages({
        account: accountId, folder, page, perPage: 50,
        unreadOnly: criteria === 'UNSEEN',
        searchCriteria: criteria && criteria !== 'UNSEEN' ? criteria : undefined,
      });
      if (res.error) {
        set({ listError: res.error, messages: [], listLoading: false });
        return;
      }
      set({
        messages: res.messages || [],
        total: res.total || 0,
        page: res.page || 1,
        pages: res.pages || 1,
        listLoading: false,
      });
    } catch (e) {
      set({ listError: e.message, listLoading: false });
    }
  },

  async search(q) {
    const { accountId, folder } = get();
    const query = (q || '').trim();
    // 검색은 그 자체가 하나의 조건 — 걸려 있던 필터는 여기서 푼다
    set({ searchQuery: query, quickFilter: 'all', cursor: 0, checked: new Set() });
    if (!query) return get().loadMessages();
    set({ searching: true, listLoading: true, listError: '' });
    try {
      const res = await mailApi.search({ account: accountId, folder, q: query });
      if (res.error) {
        set({ listError: res.error, messages: [], listLoading: false, searching: false });
        return;
      }
      set({
        messages: res.messages || [], total: res.total || 0,
        page: 1, pages: 1, listLoading: false, searching: false,
      });
    } catch (e) {
      set({ listError: e.message, listLoading: false, searching: false });
    }
  },

  // ── 읽기 ──────────────────────────────────────────────────────────────
  async open(uid) {
    const { accountId, folder, messages } = get();
    const wasUnread = messages.find((m) => m.uid === uid)?.is_read === false;
    // 클릭으로 열어도 커서가 따라오게 — 이후 ↑↓ 가 그 자리에서 이어진다
    const idx = messages.findIndex((m) => m.uid === uid);
    if (idx >= 0) set({ cursor: idx });
    set({ openUid: uid, detail: null, detailLoading: true, detailError: '' });

    // 읽음 처리는 낙관적으로 먼저 — 서버 응답을 기다리면 목록이 늦게 바뀐다
    // (서버는 fetch_message() 안에서 \Seen 을 세우므로 별도 호출이 필요 없다)
    if (wasUnread) {
      set((s) => ({
        messages: s.messages.map((m) => (m.uid === uid ? { ...m, is_read: true } : m)),
        selfUnread: s.specialView === 'selfbox' ? Math.max(0, s.selfUnread - 1) : s.selfUnread,
        folders: s.folders.map((f) =>
          (f.name === folder ? { ...f, unread: Math.max(0, (f.unread || 0) - 1) } : f)),
      }));
    }

    try {
      const res = await mailApi.message({ account: accountId, folder, uid });
      if (res.error) set({ detailError: res.error, detailLoading: false });
      else set({ detail: res, detailLoading: false });
    } catch (e) {
      set({ detailError: e.message, detailLoading: false });
    }
    // 서버가 \Seen 을 세운 뒤 실제 값으로 한 번 더 맞춘다
    if (wasUnread) get().refreshInboxUnread();
  },

  close() { set({ openUid: null, detail: null }); },

  /** 목록 커서 이동. 읽기창이 늘 떠 있으므로 옮기면서 바로 연다. */
  moveCursor(delta) {
    const s = get();
    const list = visibleMessages(s);
    if (!list.length) return;
    const next = Math.min(list.length - 1, Math.max(0, s.cursor + delta));
    set({ cursor: next });
    get().open(list[next].uid);
  },

  setCursor(i) { set({ cursor: i }); },

  // ── 선택 ──────────────────────────────────────────────────────────────
  toggleCheck(uid) {
    set((s) => {
      const next = new Set(s.checked);
      next.has(uid) ? next.delete(uid) : next.add(uid);
      return { checked: next };
    });
  },

  toggleCheckAll() {
    set((s) => {
      const visible = visibleMessages(s).map((m) => m.uid);
      const allOn = visible.length > 0 && visible.every((u) => s.checked.has(u));
      return { checked: allOn ? new Set() : new Set(visible) };
    });
  },

  clearChecked() { set({ checked: new Set() }); },

  // ── 일괄 작업 ─────────────────────────────────────────────────────────
  async markRead(read = true) {
    const { accountId, folder, checked } = get();
    const uids = [...checked];
    if (!uids.length) return;
    await mailApi.setFlags({ account: accountId, folder, uids, flag: '\\Seen', action: read ? 'add' : 'remove' });
    set((s) => ({
      messages: s.messages.map((m) => (checked.has(m.uid) ? { ...m, is_read: read } : m)),
      checked: new Set(),
      // 화면부터 즉시 맞추고, 곧 서버 값으로 다시 확인한다
      folders: s.folders.map((f) => (f.name === folder
        ? { ...f, unread: Math.max(0, (f.unread || 0) + (read ? -uids.length : uids.length)) }
        : f)),
    }));
    get().refreshInboxUnread();
  },

  async toggleStar(uid, on) {
    const { accountId, folder } = get();
    set((s) => ({
      messages: s.messages.map((m) => (m.uid === uid ? { ...m, is_flagged: on } : m)),
    }));
    await mailApi.setFlags({ account: accountId, folder, uids: [uid], flag: '\\Flagged', action: on ? 'add' : 'remove' });
  },

  async moveChecked(destFolder) {
    const { accountId, folder, checked } = get();
    const uids = [...checked];
    if (!uids.length) return;
    const res = await mailApi.move({ account: accountId, srcFolder: folder, destFolder, uids });
    if (res.error) throw new Error(res.error);
    set((s) => ({ messages: s.messages.filter((m) => !checked.has(m.uid)), checked: new Set() }));
    get().loadFolders(true);
  },

  async deleteChecked() {
    const { accountId, folder, checked, openUid } = get();
    const uids = [...checked];
    if (!uids.length) return;
    const res = await mailApi.remove({ account: accountId, folder, uids });
    if (res.error) throw new Error(res.error);
    set((s) => ({
      messages: s.messages.filter((m) => !checked.has(m.uid)),
      checked: new Set(),
      ...(checked.has(openUid) ? { openUid: null, detail: null } : {}),
    }));
    get().loadFolders(true);
  },
}));

