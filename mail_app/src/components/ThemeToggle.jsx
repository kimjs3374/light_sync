import { useEffect, useState } from 'react';
import { loadTheme, saveTheme, nextTheme, isDarkNow, THEME_LABEL } from '../lib/theme';
import { Sun, Moon, Auto } from './Icons';

/**
 * 테마 버튼 — 자동 → 밝게 → 어둡게 를 한 자리에서 돌린다.
 * 아이콘은 **고른 것**을 보여주고(자동이면 자동 표시), 지금 실제로 어느 쪽인지는
 * 설명에 적는다. 자동인데 달 모양만 띄우면 "어둡게로 고정했다" 로 읽힌다.
 */
export default function ThemeToggle() {
  const [theme, setTheme] = useState(loadTheme);

  // 자동일 때는 OS 설정이 바뀌면 따라 바뀐다 — 설명 글자도 같이 고쳐야 한다
  useEffect(() => {
    if (theme !== 'auto' || !window.matchMedia) return undefined;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setTheme('auto');   // 다시 그리기만 하면 된다
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [theme]);

  const go = () => {
    const next = nextTheme(theme);
    saveTheme(next);
    setTheme(next);
  };

  const Icon = theme === 'auto' ? Auto : theme === 'dark' ? Moon : Sun;
  const now = isDarkNow(theme) ? '어두움' : '밝음';

  return (
    <button
      className="theme-toggle"
      onClick={go}
      title={`화면: ${THEME_LABEL[theme]}${theme === 'auto' ? ` (지금 ${now})` : ''} — 눌러서 ${THEME_LABEL[nextTheme(theme)]}`}
      aria-label={`화면 테마 ${THEME_LABEL[theme]}`}
    >
      <Icon />
    </button>
  );
}
