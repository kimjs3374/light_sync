import { create } from 'zustand';
import { mailApi } from '../api/client';
import { senderName, splitSubject } from '../lib/format';

/**
 * 설정은 브라우저에 남긴다 — 목록 밀도와 경계선 위치는 사람마다 갈린다.
 * splitPct: 목록이 차지하는 가로 비율(%). 읽기창은 늘 오른쪽에 붙는다.
 */
const PREF_KEY = 'webmail_prefs';
/**
 * layout — 목록에서 메일을 눌렀을 때 어떻게 보여줄지.
 *   full    기본(전체보기): 읽기창이 화면을 다 쓴다. 목록은 닫으면 돌아온다
 *   split-v 좌우분할: 목록 왼쪽 · 읽기창 오른쪽 (예전 기본값)
 *   split-h 상하분할: 목록 위 · 읽기창 아래 (제목이 긴 메일함에서 읽기 좋다)
 */
const DEFAULT_PREFS = { density: 'cozy', splitPct: 44, perPage: 50, layout: 'split-v' };
export const LAYOUTS = ['full', 'split-v', 'split-h'];
export const LAYOUT_LABEL = { full: '기본(전체보기)', 'split-v': '좌우분할', 'split-h': '상하분할' };
export const PER_PAGE_CHOICES = [25, 50, 100];
export const SPLIT_MIN = 26;
export const SPLIT_MAX = 72;

const loadPrefs = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(PREF_KEY) || '{}');
    const pct = Number(saved.splitPct);
    return {
      ...DEFAULT_PREFS,
      ...saved,
      perPage: PER_PAGE_CHOICES.includes(Number(saved.perPage))
        ? Number(saved.perPage) : DEFAULT_PREFS.perPage,
      layout: LAYOUTS.includes(saved.layout) ? saved.layout : DEFAULT_PREFS.layout,
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

/** 목록 정렬 기준 — 화면에 그대로 적히는 이름이라 여기 한 곳에서만 정한다 */
export const SORT_KEYS = ['date', 'from', 'subject'];
export const SORT_LABEL = { date: '날짜', from: '보낸사람', subject: '제목' };
export const DEFAULT_SORT = { sortBy: 'date', sortDir: 'desc' };

/** 지금 정렬이 기본값(= 서버가 준 그대로)인가 */
export const isDefaultSort = (s) =>
  s.sortBy === DEFAULT_SORT.sortBy && s.sortDir === DEFAULT_SORT.sortDir;

const sortValue = (m, by) => {
  if (by === 'from') return senderName(m.from);
  // 제목은 [태그] 를 뗀 본문으로 줄을 세운다 — 목록에서 눈이 좇는 글자가 그것이다.
  // 태그째 세우면 `[매그나텍]` 이 붙은 메일끼리만 몰려 제목순으로 안 읽힌다.
  if (by === 'subject') return splitSubject(m.subject).text;
  const t = new Date(m.date).getTime();
  return Number.isFinite(t) ? t : 0;
};

/**
 * 화면에 보일 목록 — 필터를 걸고, 고른 순서로 세운다.
 *
 * 첨부 필터도 정렬도 **지금 보고 있는 쪽 안에서만** 돈다. 서버는 늘 날짜
 * 내림차순으로 한 쪽씩 떼어 주므로, 여기서 세운 순서는 그 쪽의 순서일 뿐이다
 * (2쪽에 더 이른 날짜가 있어도 1쪽으로 올라오지 않는다).
 * 툴바가 그 사실을 화면에 적는다 — 안 적으면 "정렬이 틀렸다"로 읽힌다.
 *
 * 기본값(날짜·내림)일 때는 **손대지 않는다.** 서버가 IMAP SORT 로 세워 준
 * 순서를 흉내내다 같은 시각끼리 자리가 뒤바뀌면, 아무것도 안 고른 사람에게
 * 목록이 달라 보인다.
 */
export const visibleMessages = (s) => {
  const list = s.quickFilter === 'attach'
    ? s.messages.filter((m) => m.has_attachment) : s.messages;
  if (isDefaultSort(s)) return list;
  const dir = s.sortDir === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    const x = sortValue(a, s.sortBy);
    const y = sortValue(b, s.sortBy);
    if (typeof x === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y), 'ko') * dir;
  });
};

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

  /* 사람이 정한 메일함 순서·그룹 (서버에 있다 — 자리를 옮겨도 따라온다) */
  folderPrefs: [],

  /* 읽기창을 화면 꽉 채워 보는 중인가.
     브라우저에 저장하지 않는다 — 켜 둔 채로 새로고침하면 목록도 툴바도 없는
     빈 읽기창만 남아 "메일함이 사라졌다" 가 된다. 메일을 닫으면 저절로 풀린다. */
  readerFull: false,
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
  /**
   * 상세검색이 걸려 있으면 `{ params, criteria, truncated }`.
   * criteria 는 서버가 돌려준 사람이 읽는 조건 문구다 — 화면이 그대로 띄운다.
   */
  searchDetail: null,
  searching: false,

  /**
   * 목록 정렬 — **지금 보고 있는 쪽 안에서만** 적용된다(서버는 날짜순으로만 준다).
   * 메일함을 옮기면 기본값(날짜·내림)으로 돌아온다. 정렬이 따라다니면
   * "받은편지함을 눌렀는데 순서가 이상하다"가 되고, 그 이유는 화면에 안 적혀 있다.
   */
  sortBy: DEFAULT_SORT.sortBy,
  sortDir: DEFAULT_SORT.sortDir,

  /**
   * 라벨로 걸러 보는 중이면 `{ keyword, name }`.
   * keyword 는 IMAP 키워드 그대로다 — 사이드바가 준 값을 손대지 않고 싣는다
   * (라벨 이름으로 키워드를 만들면 안 된다. api/client.js 의 라벨 주석 참고).
   */
  labelFilter: null,

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
      accountId, folder: 'INBOX', page: 1, openUid: null, detail: null, readerFull: false,
      checked: new Set(), quickFilter: 'all', searchQuery: '', searchDetail: null, specialView: null,
      labelFilter: null, ...DEFAULT_SORT,
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
      // 순서·그룹은 따로 읽는다 — 실패해도 메일함은 보여야 하므로 조용히 넘어간다
      try {
        const pref = await mailApi.folderPrefs(accountId);
        set({ folderPrefs: pref.items || [] });
      } catch { /* 순서가 없으면 이름순으로 보인다 */ }
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
      specialView: name, openUid: null, detail: null, readerFull: false,
      checked: new Set(), cursor: 0, searchQuery: '', searchDetail: null, quickFilter: 'all',
      labelFilter: null, ...DEFAULT_SORT,
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
      folder: name, page: 1, openUid: null, detail: null, readerFull: false,
      checked: new Set(), cursor: 0, searchQuery: '', searchDetail: null,
      quickFilter: unreadOnly ? 'unread' : 'all',
      // 라벨 딱지와 정렬은 메일함을 옮기면 떨어진다 — 일회용이다(위 주석 참고)
      labelFilter: null, ...DEFAULT_SORT,
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

      // 라벨은 IMAP 키워드다 — 조건을 겹쳐 실으면 그 라벨이 달린 것만 남는다
      // (IMAP SEARCH 는 AND 다). 키워드 값은 사이드바가 준 것을 그대로 쓴다.
      const { labelFilter } = get();
      if (labelFilter?.keyword) {
        const kw = `KEYWORD ${labelFilter.keyword}`;
        criteria = criteria ? `${criteria} ${kw}` : kw;
      }

      const res = await mailApi.messages({
        account: accountId, folder, page, perPage: get().prefs.perPage,
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
    set({
      searchQuery: query, searchDetail: null, quickFilter: 'all', labelFilter: null,
      cursor: 0, checked: new Set(),
    });
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

  /**
   * 상세검색 — 조건을 모두 만족하는 메일만 남긴다(IMAP SEARCH 는 AND).
   *
   * 기본 검색과 자리를 다투므로 한쪽이 켜지면 다른 쪽은 꺼진다.
   * 빠른 필터(안읽음·중요·첨부)도 함께 푼다 — 조건이 두 군데 걸려 있으면
   * "왜 이것만 나오는지" 를 화면 어디에서도 읽을 수 없다.
   */
  async searchAdvanced(params) {
    const { accountId, folder, specialView } = get();
    if (!accountId) return;
    // 받은편지함/내게쓴메일함은 같은 INBOX 를 보낸사람으로 가른다 — 검색도 그 칸 안에서만
    const self = String(folder).toUpperCase() === 'INBOX'
      ? (specialView === 'selfbox' ? 'only' : 'exclude')
      : undefined;

    set({
      searchQuery: '', quickFilter: 'all', labelFilter: null, cursor: 0, checked: new Set(),
      searching: true, listLoading: true, listError: '',
    });
    try {
      const res = await mailApi.searchAdvanced({ account: accountId, folder, self, ...params });
      if (res.error) {
        set({ listError: res.error, messages: [], listLoading: false, searching: false });
        return;
      }
      set({
        messages: res.messages || [],
        total: res.total || 0,
        page: 1, pages: 1, listLoading: false, searching: false,
        searchDetail: {
          params,
          criteria: res.criteria || [],
          truncated: !!res.truncated,
          shown: res.shown || 0,
        },
      });
    } catch (e) {
      set({ listError: e.message, listLoading: false, searching: false });
    }
  },

  /**
   * 라벨로 걸러 보기 — 사이드바에서 라벨을 누르면 여기로 온다.
   *
   * @param keyword   IMAP 키워드. **사이드바가 준 값을 그대로 넘겨라** —
   *                  라벨 이름으로 키워드를 만들면 안 된다(한글이 잘린다).
   * @param labelName 화면에 적을 사람이 읽는 이름. 없으면 키워드를 그대로 적는다.
   *
   * 보고 있던 메일함 **안에서** 거른다(IMAP SEARCH 는 폴더 단위다). 그래서
   * 받은편지함에서 라벨을 누르면 받은편지함 안의 그 라벨만 나온다.
   * 검색·상세검색과는 자리를 다투므로 한쪽이 켜지면 다른 쪽은 꺼진다 —
   * 조건이 두 군데 걸려 있으면 "왜 이것만 나오는지"를 어디서도 못 읽는다.
   *
   * 메일 목록을 안 그리는 화면(주소록·예약 발송·수신확인)에 서 있었다면 그
   * 화면을 **내리고** 목록으로 돌아온다. 안 내리면 목록만 조용히 걸러지고
   * 화면은 그대로라, 누른 사람에게는 아무 일도 안 일어난 것으로 보인다.
   * 내게쓴메일함(selfbox)만 그대로 둔다 — 그건 목록을 그리는 화면이라
   * "내게쓴메일함 안의 그 라벨"이 말이 된다.
   * (이 판단은 스토어 안에 있어야 한다. 부르는 자리가 늘 때마다 같은 코드를
   *  밖에 또 쓰게 되면 언젠가 한 곳이 빠진다)
   */
  async filterByLabel(keyword, labelName) {
    if (!keyword) return;
    const { specialView } = get();
    set({
      labelFilter: { keyword, name: labelName || keyword },
      specialView: specialView === 'selfbox' ? specialView : null,
      page: 1, cursor: 0, checked: new Set(),
      openUid: null, detail: null, readerFull: false,
      quickFilter: 'all', searchQuery: '', searchDetail: null,
    });
    await get().loadMessages();
  },

  /** 라벨 딱지 떼기 — 보던 메일함으로 그대로 돌아간다 */
  clearLabelFilter() {
    set({ labelFilter: null, page: 1, cursor: 0, checked: new Set() });
    get().loadMessages();
  },

  /**
   * 목록 정렬 바꾸기.
   *
   * 서버를 다시 부르지 않는다 — 지금 받아 둔 쪽을 화면에서 세울 뿐이다
   * (visibleMessages 주석 참고). 커서는 처음으로 돌린다: 줄 순서가 바뀌었는데
   * 커서만 3번째에 남아 있으면 엉뚱한 메일이 열린다.
   */
  setSort(sortBy, sortDir) {
    set({
      sortBy: SORT_KEYS.includes(sortBy) ? sortBy : DEFAULT_SORT.sortBy,
      sortDir: sortDir === 'asc' ? 'asc' : 'desc',
      cursor: 0,
    });
  },

  /**
   * 휴지통·스팸함 비우기 — 그 메일함의 메일을 전부 지운다.
   *
   * 서버가 그 두 곳 외에는 거절한다. 화면에서도 그 두 곳에서만 버튼을 내놓지만,
   * 여기서도 막지 않는다 — 막는 잣대가 두 벌이 되면 어느 쪽이 참인지 흐려진다.
   * 지운 뒤에는 목록과 메일함 뱃지를 다시 읽는다.
   */
  async emptyCurrentFolder() {
    const { accountId, folder } = get();
    if (!accountId) return;
    const res = await mailApi.emptyFolder({ account: accountId, folder });
    if (res?.error) throw new Error(res.error);
    // 보고 있던 메일도 방금 지워졌다 — 읽기창을 닫지 않으면 없는 메일이 남는다
    set({ openUid: null, detail: null, readerFull: false, checked: new Set(), cursor: 0, page: 1 });
    await get().loadMessages();
    get().loadFolders(true);
  },

  /** 상세검색 해제 — 보던 메일함으로 그대로 돌아간다 */
  clearSearchDetail() {
    set({ searchDetail: null, cursor: 0, checked: new Set() });
    get().loadMessages();
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

  close() { set({ openUid: null, detail: null, readerFull: false }); },

  /** 읽기창을 화면 꽉 채우기 / 원래대로 (목록·툴바·메일함 칸을 잠시 접는다) */
  toggleReaderFull() { set({ readerFull: !get().readerFull }); },

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

  /**
   * 한 통의 읽음·안읽음 (읽기창에서 쓴다).
   *
   * 안읽음으로 돌리면 **읽기창을 닫는다.** 열어 둔 채로 두면 다음에 다시 열 때
   * 서버가 또 읽음을 달아(fetch_message 가 \Seen 을 단다) 방금 한 일이 사라진다.
   */
  async setReadOne(uid, read) {
    const { accountId, folder } = get();
    set((s) => ({
      messages: s.messages.map((m) => (m.uid === uid ? { ...m, is_read: read } : m)),
      folders: s.folders.map((f) => (f.name === folder
        ? { ...f, unread: Math.max(0, (f.unread || 0) + (read ? -1 : 1)) }
        : f)),
    }));
    await mailApi.setFlags({
      account: accountId, folder, uids: [uid], flag: '\\Seen', action: read ? 'add' : 'remove',
    });
    if (!read) get().close();
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

