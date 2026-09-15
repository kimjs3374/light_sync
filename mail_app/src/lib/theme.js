/**
 * 밝게 · 어둡게 · 자동.
 *
 * 고른 값은 `<html data-theme="light|dark">` 로 박고, **자동이면 아무것도 안 박는다** —
 * 그때는 CSS 의 `prefers-color-scheme` 이 OS 설정을 따라간다(styles.css 맨 아래).
 *
 * 화면이 뜨기 **전에** 한 번 걸어야 한다. React 가 그린 다음에 걸면
 * 흰 화면이 한 번 번쩍였다가 어두워진다.
 */

const KEY = 'webmail_theme';
export const THEMES = ['auto', 'light', 'dark'];
export const THEME_LABEL = { auto: '자동', light: '밝게', dark: '어둡게' };

export function loadTheme() {
  try {
    const v = localStorage.getItem(KEY);
    return THEMES.includes(v) ? v : 'auto';
  } catch {
    return 'auto';   // 사생활 보호 모드 등 — 저장이 막혀도 화면은 떠야 한다
  }
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'auto') delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export function saveTheme(theme) {
  try { localStorage.setItem(KEY, theme); } catch { /* 저장이 막혀도 이번 판은 바뀐다 */ }
  applyTheme(theme);
}

/** 자동 → 밝게 → 어둡게 → 자동 */
export const nextTheme = (theme) => THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];

/** 지금 실제로 어두운가 — 버튼 아이콘이 '지금 무엇인지' 를 보여줘야 한다 */
export const isDarkNow = (theme) => (
  theme === 'dark'
  || (theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
);
