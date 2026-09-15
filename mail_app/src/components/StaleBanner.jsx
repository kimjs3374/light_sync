import { useEffect, useState } from 'react';
import { isStaleBuild } from '../api/client';

/** 서버에 새 버전이 올라갔으면 알려준다 — 옛 화면은 새 기능이 조용히 안 먹는다 */
export default function StaleBanner() {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      if (!alive || stale) return;
      if (await isStaleBuild()) setStale(true);
    };
    check();
    const id = setInterval(check, 60000);
    window.addEventListener('focus', check);
    return () => { alive = false; clearInterval(id); window.removeEventListener('focus', check); };
  }, [stale]);

  if (!stale) return null;
  return (
    <div className="stale-banner" role="status">
      <span>메일 화면이 새로 배포됐습니다. 새로고침해야 최신 기능이 적용됩니다.</span>
      <button onClick={() => window.location.reload()}>새로고침</button>
    </div>
  );
}
