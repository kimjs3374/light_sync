import { create } from 'zustand';

/**
 * 설정 창 열림 상태만 든다.
 *
 * 설정값 자체는 여기 모으지 않는다 — 화면 설정은 이미 `useMail.prefs`(브라우저)에,
 * 자동응답·자동전달·자동분류는 서버에 있다. 여기로 한 번 더 복사해 두면
 * 어느 쪽이 진짜인지가 흐려진다. 각 칸이 열릴 때 제 것을 읽어 온다.
 */
export const SETTING_SECTIONS = [
  { key: 'display', label: '화면' },
  { key: 'folders', label: '메일함 관리' },
  { key: 'sending', label: '보내기' },
  { key: 'autoreply', label: '부재중 자동응답' },
  { key: 'forward', label: '자동 전달' },
  { key: 'rules', label: '자동 분류' },
  { key: 'spam', label: '스팸 · 수신차단' },
  { key: 'help', label: '단축키 · 도움말' },
];

export const useSettings = create((set) => ({
  open: false,
  /* 화면 안내(가이드) — 설정 창과 별개로 뜬다. 안내가 가리킬 버튼들이
     설정 창에 가려지면 안 되므로, 안내를 켤 때 설정 창은 닫는다. */
  tour: false,
  startTour: () => set({ tour: true, open: false }),
  endTour: () => set({ tour: false }),
  section: 'display',
  openSettings: (section = 'display') => set({ open: true, section }),
  goSection: (section) => set({ section }),
  close: () => set({ open: false }),
}));
