/**
 * 인라인 SVG 아이콘.
 *
 * 이모지(📎 ★ ↻)를 쓰면 글꼴 유무에 따라 네모로 깨지고, 크기·색·굵기를
 * 맞출 수 없어 화면이 들쭉날쭉해진다. 획 굵기를 1.6로 통일한 SVG 몇 개면
 * 라이브러리 없이 끝난다.
 */

const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

export const Paperclip = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="첨부">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);

export const Star = ({ size = 15, filled = false }) => (
  <svg
    width={size} height={size} viewBox="0 0 24 24"
    {...base} fill={filled ? 'currentColor' : 'none'}
    aria-label={filled ? '중요 표시됨' : '중요 표시'}
  >
    <path d="M12 3.5l2.6 5.3 5.9.85-4.25 4.15 1 5.85L12 16.9l-5.25 2.75 1-5.85L3.5 9.65l5.9-.85z" />
  </svg>
);

export const Refresh = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="새로고침">
    <path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1" />
    <path d="M20.5 4.5V10H15" />
  </svg>
);

export const Close = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="닫기">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);

export const Search = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="검색">
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </svg>
);

export const Mail = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
    <path d="M3.5 7l8.5 6 8.5-6" />
  </svg>
);

export const External = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="외부메일">
    <circle cx="12" cy="12" r="8.5" />
    <path d="M3.5 12h17M12 3.5c2.2 2.4 3.3 5.3 3.3 8.5S14.2 18.1 12 20.5c-2.2-2.4-3.3-5.3-3.3-8.5S9.8 5.9 12 3.5z" />
  </svg>
);

export const Users = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="공용계정">
    <circle cx="9" cy="8.5" r="3.2" />
    <path d="M3 19c0-3.1 2.7-5 6-5s6 1.9 6 5" />
    <path d="M16 6.2a3.2 3.2 0 0 1 0 6.1M17.5 14.4c2.1.6 3.5 2.2 3.5 4.6" />
  </svg>
);

export const Link = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="링크">
    <path d="M10 13.5a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1.5 1.5" />
    <path d="M14 10.5a4 4 0 0 0-5.66 0l-3 3a4 4 0 1 0 5.66 5.66l1.5-1.5" />
  </svg>
);

export const AlignLeft = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="왼쪽 정렬">
    <path d="M4 6h16M4 11h10M4 16h14M4 21h8" />
  </svg>
);

export const AlignCenter = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="가운데 정렬">
    <path d="M4 6h16M7 11h10M5 16h14M8 21h8" />
  </svg>
);

export const ListBullet = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="글머리 기호">
    <path d="M9 7h11M9 12h11M9 17h11" />
    <circle cx="4.5" cy="7" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="4.5" cy="12" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="4.5" cy="17" r="1.3" fill="currentColor" stroke="none" />
  </svg>
);

export const ListNumber = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="번호 매기기">
    <path d="M9 7h11M9 12h11M9 17h11" />
    <path d="M3.4 5.4L4.8 4.7V9M3 14.2c0-.8.7-1.3 1.5-1.3s1.5.5 1.5 1.2c0 1.3-3 1.6-3 3.4h3" strokeWidth="1.3" />
  </svg>
);

export const Divider = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-label="구분선">
    <path d="M3 12h18" />
    <path d="M6 6h12M6 18h12" opacity=".35" />
  </svg>
);
