import { create } from 'zustand';
import { api } from '../api/client';

/**
 * 주소록 스토어.
 *
 * 주소록은 세 칸으로 갈라져 있고, 화면 어디서나 같은 이름으로 부른다:
 *
 *   personal  내 주소록    나만 본다
 *   shared    회사 공용    전 직원이 함께 본다 (예전에 가져다 둔 것들이 여기 있다)
 *   internal  사내 직원    users 에서 만들어 주는 자리 — 고칠 수 없다
 *
 * 편집창(editing)과 고르기창(picking)은 주소록 화면이 아니라 App/ComposePage 가
 * 그린다. 메일을 읽다가 "주소록 저장", 메일을 쓰다가 "주소록"을 눌러도
 * 주소록 화면으로 옮겨가지 않고 그 자리에서 열려야 하기 때문이다.
 */

export const BOOK_LABEL = {
  personal: '내 주소록',
  shared: '회사 공용',
  internal: '사내 직원',
  all: '전체',
};

const PER_PAGE = 50;
const emptyForm = {
  id: null, name: '', email: '', company: '', phone: '', memo: '', book: 'personal',
};

export const useContacts = create((set, get) => ({
  book: 'personal',
  q: '',
  page: 1,
  items: [],
  total: 0,
  pages: 1,
  counts: { personal: 0, shared: 0, internal: 0, all: 0 },
  loading: false,
  error: '',

  editing: null,      // 추가·수정 창 (null 이면 닫힘)
  saving: false,
  picking: false,     // 메일쓰기에서 여는 고르기 창

  async load() {
    const { book, q, page } = get();
    set({ loading: true, error: '' });
    try {
      const res = await api.get(
        `/mail/api/contacts?book=${book}&page=${page}&per_page=${PER_PAGE}`
        + `&q=${encodeURIComponent(q)}`,
      );
      set({
        items: res.items || [],
        total: res.total || 0,
        pages: res.total_pages || 1,
        counts: res.counts || get().counts,
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: e.message || '주소록을 불러오지 못했습니다' });
    }
  },

  setBook(book) {
    if (get().book === book) return;
    set({ book, page: 1 });
    get().load();
  },

  setQuery(q) {
    set({ q, page: 1 });
    get().load();
  },

  goPage(page) {
    set({ page: Math.max(1, Math.min(page, get().pages)) });
    get().load();
  },

  /** 추가·수정 창 열기. seed 로 이름·메일을 미리 채운다(메일에서 바로 저장할 때) */
  startEdit(seed = {}) {
    const book = seed.book || (get().book === 'internal' ? 'personal' : get().book);
    set({ editing: { ...emptyForm, ...seed, book }, error: '' });
  },

  cancelEdit() {
    set({ editing: null, saving: false });
  },

  patchEdit(patch) {
    set({ editing: { ...get().editing, ...patch } });
  },

  /** 저장. 성공하면 창을 닫고 목록을 다시 읽는다. 실패 사유는 창에 남긴다. */
  async save() {
    const form = get().editing;
    if (!form) return false;
    if (!form.email.trim()) {
      set({ editing: { ...form, error: '메일주소를 입력하세요.' } });
      return false;
    }
    set({ saving: true });
    try {
      const res = await api.post('/mail/api/contacts', {
        id: form.id || undefined,
        name: form.name.trim(),
        email: form.email.trim(),
        company: form.company.trim(),
        phone: form.phone.trim(),
        memo: form.memo.trim(),
        book: form.book,
      });
      if (res.error) throw new Error(res.error);
      set({ editing: null, saving: false });
      await get().load();
      return true;
    } catch (e) {
      set({ saving: false, editing: { ...form, error: e.message || '저장하지 못했습니다' } });
      return false;
    }
  },

  async remove(contact) {
    const res = await api.del(`/mail/api/contacts/${contact.id}`);
    if (res.error) throw new Error(res.error);
    await get().load();
  },

  /**
   * 주소록 파일 가져오기.
   * dryRun 이면 저장하지 않고 무엇이 들어올지만 받아 온다 — 수백 건이
   * 말없이 쏟아지기 전에 사람이 먼저 본다.
   */
  async importFile(file, { book, dryRun }) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('book', book);
    if (dryRun) fd.append('dry_run', '1');
    const res = await api.post('/mail/api/contacts/import', fd);
    if (res.error) throw new Error(res.error);
    if (!dryRun) await get().load();
    return res;
  },

  exportUrl(book, format) {
    return `/mail/api/contacts/export?book=${book}&format=${format}`;
  },
}));
