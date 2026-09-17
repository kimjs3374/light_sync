import { create } from 'zustand';
import { api, mailApi } from '../api/client';
import { useMail } from './mail';

/**
 * 라벨 — 만들기·이름/색 바꾸기·지우기.
 *
 * 라벨은 메일함이 아니다. 메일은 있던 자리에 그대로 있고, 표시만 하나 더 붙는다
 * (IMAP 키워드). 그래서 라벨을 지워도 메일은 사라지지 않는다.
 *
 * 목록의 진짜 주인은 사이드바가 쓰는 `useMail.labels` 다. 여기서 목록을 고친 뒤에는
 * 반드시 `useMail.loadFolders(true)` 를 불러 사이드바를 따라오게 한다 —
 * 설정 창 안에서만 바뀌고 왼쪽은 옛날 라벨인 상태가 제일 헷갈린다.
 */

/**
 * 고를 수 있는 라벨 색.
 *
 * 색을 직접 적게 하지 않는 이유: 라벨은 **색이 곧 이름표**라 옆 라벨과 구별돼야
 * 쓸모가 있는데, 자유 입력으로는 비슷한 색이 줄줄이 생긴다. 어두운 화면에서도
 * 보이는 것들만 골라 두었다.
 */
export const LABEL_COLORS = [
  { value: '#ef4444', label: '빨강' },
  { value: '#f97316', label: '주황' },
  { value: '#eab308', label: '노랑' },
  { value: '#22c55e', label: '초록' },
  { value: '#06b6d4', label: '청록' },
  { value: '#3b82f6', label: '파랑' },
  { value: '#8b5cf6', label: '보라' },
  { value: '#ec4899', label: '분홍' },
  { value: '#64748b', label: '회색' },
];

export const DEFAULT_LABEL_COLOR = '#64748b';   // 서버가 색 없이 만들 때 쓰는 값과 같다

/**
 * 메일에 달 때 쓰는 IMAP 키워드.
 *
 * **이름이 아니라 키워드로 걸러야 한다.** 이름은 사람이 바꾸는 글자이고,
 * 메일에 실제로 박혀 있는 것은 키워드다 — 이름을 바꾼 순간 이름으로 거른 목록은
 * 텅 빈다.
 *
 * 형식은 서버(modules/services/mail_classifier.py 의 `label_keyword`)가 정한다:
 * **이름이 아니라 id 로 만든다** — `label_12`. 한글로 키워드를 만들면 IMAP 서버가
 * 삼켜 버리고, 이름을 바꿀 때마다 이미 달아 둔 메일이 떨어져 나간다.
 *
 * 그래서 여기서는 **이름으로 키워드를 짓지 않는다.** 서버가 준 keyword 를 쓰고,
 * 그게 없으면 id 로 같은 규칙을 따른다. 둘 다 없으면 빈 값을 돌려준다 —
 * 아무 일도 안 일어나는 편이, 아무것도 안 걸리는 목록을 내미는 것보다 낫다.
 */
export function labelKeyword(label) {
  if (!label) return '';
  if (label.keyword) return label.keyword;
  return label.id ? `label_${label.id}` : '';
}

/**
 * 라벨 목록을 읽는다.
 *
 * 먼저 라벨만 주는 가벼운 주소로 물어본다. 그 주소가 **아직 없는 서버**(405)에서는
 * 응답이 JSON 이 아니라 api.get 이 던지고, 그때만 메일함 목록에 딸려 오는 라벨로
 * 대신한다. 두 응답의 라벨 모양은 서버에서 같은 함수로 만들어 한 글자도 다르지 않다.
 *
 * **서버가 대답을 주긴 했는데 그게 error 인 경우(권한 없음 403 등)에는 물러서지
 * 않는다.** 그때 조용히 다른 길로 가면 남의 계정을 찔렀다는 사실이 화면 어디에도
 * 안 남고, 빈 목록만 보인다.
 *
 * 서버가 이 주소를 갖춘 뒤에도 폴백을 안 지운 이유: 이 저장소는 static(dist)이
 * **즉시** 올라가고 파이썬은 restart 해야 반영된다(.claude/deploy.md). 그래서
 * 새 화면이 옛 서버와 만나는 창이 배포 때마다 다시 열린다.
 *
 * 함정 하나: 토큰이 끊긴 401 도 api.get 이 던지므로 이 catch 로 들어와 folders 를
 * 한 번 더 부른다. 그 호출도 401 이라 헛걸음이지만, 401 자리에서 client.js 가
 * 이미 로그인 화면으로 보내고 있어 그대로 둔다.
 */
async function fetchLabels(accountId) {
  let r;
  try {
    r = await api.get(`/mail/api/labels?account=${accountId}`);
  } catch {
    const f = await mailApi.folders(accountId);
    if (f.error) throw new Error(f.error);
    return f.labels || [];
  }
  if (r && r.error) throw new Error(r.error);
  const arr = Array.isArray(r) ? r : r.labels;
  return Array.isArray(arr) ? arr : [];
}

export const useLabels = create((set, get) => ({
  accountId: null,
  items: [],
  loading: false,
  error: '',

  async load(accountId) {
    if (!accountId) { set({ accountId: null, items: [], loading: false, error: '' }); return; }
    set({ accountId, loading: true, error: '' });
    try {
      const items = await fetchLabels(accountId);
      // 계정을 바꾼 뒤에 늦게 도착한 응답은 버린다 — 안 버리면 방금 고른 계정 자리에
      // 이전 계정의 라벨이 앉는다
      if (get().accountId !== accountId) return;
      set({ items, loading: false });
    } catch (e) {
      if (get().accountId !== accountId) return;
      set({ items: [], loading: false, error: e.message || '라벨을 불러오지 못했습니다' });
    }
  },

  /** 고친 뒤 — 사이드바(useMail.labels)까지 새로 읽는다 */
  async refresh() {
    await useMail.getState().loadFolders(true);
    await get().load(get().accountId);
  },

  /** 새로 만들기(id 없음) · 이름·색 바꾸기(id 있음). 둘 다 한 곳에서 한다 */
  async save({ id, name, color, sortOrder }) {
    const r = await mailApi.saveLabel({
      account: get().accountId, id, name, color, sortOrder,
    });
    if (r.error) throw new Error(r.error);
    await get().refresh();
    return r;
  },

  async remove(id) {
    const r = await mailApi.deleteLabel(id);
    if (r.error) throw new Error(r.error);
    await get().refresh();
  },
}));
