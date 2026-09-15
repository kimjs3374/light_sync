import { useCallback, useEffect, useRef } from 'react';
import { useMail, SPLIT_MIN, SPLIT_MAX } from '../store/mail';

const clamp = (v) => Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, v));

/**
 * 목록과 읽기창 사이의 경계선.
 *
 * 끄는 동안에는 CSS 변수만 직접 고친다 — 매 픽셀마다 스토어를 갱신하면
 * 메일 50줄이 전부 다시 그려져 끌리는 느낌이 뚝뚝 끊긴다.
 * 손을 뗄 때 한 번만 스토어(=localStorage)에 남긴다.
 */
export default function Splitter() {
  const setPref = useMail((s) => s.setPref);
  const splitPct = useMail((s) => s.prefs.splitPct);
  const ref = useRef(null);
  const dragging = useRef(false);
  const latest = useRef(splitPct);

  const apply = useCallback((pct) => {
    latest.current = pct;
    const body = ref.current?.parentElement;
    if (body) body.style.setProperty('--split', `${pct}%`);
  }, []);

  const onPointerDown = (e) => {
    const body = ref.current?.parentElement;
    if (!body) return;
    dragging.current = true;
    ref.current.setPointerCapture(e.pointerId);
    document.body.classList.add('is-splitting');
  };

  const onPointerMove = (e) => {
    if (!dragging.current) return;
    const body = ref.current?.parentElement;
    if (!body) return;
    const rect = body.getBoundingClientRect();
    apply(clamp(((e.clientX - rect.left) / rect.width) * 100));
  };

  const endDrag = (e) => {
    if (!dragging.current) return;
    dragging.current = false;
    try { ref.current?.releasePointerCapture(e.pointerId); } catch { /* 이미 해제됨 */ }
    document.body.classList.remove('is-splitting');
    setPref('splitPct', Math.round(latest.current * 10) / 10);
  };

  /** 키보드로도 옮길 수 있어야 한다 — 마우스가 없거나 미세조정할 때 */
  const onKeyDown = (e) => {
    const step = e.shiftKey ? 5 : 1;
    if (e.key === 'ArrowLeft') { e.preventDefault(); setPref('splitPct', clamp(latest.current - step)); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); setPref('splitPct', clamp(latest.current + step)); }
    else if (e.key === 'Home') { e.preventDefault(); setPref('splitPct', 44); }
  };

  // 스토어 값이 바뀌면(키보드 조작·초기화) CSS 변수도 따라간다
  useEffect(() => { apply(splitPct); }, [splitPct, apply]);

  return (
    <div
      ref={ref}
      className="splitter"
      role="separator"
      aria-orientation="vertical"
      aria-label="목록과 읽기창 경계"
      aria-valuenow={Math.round(splitPct)}
      aria-valuemin={SPLIT_MIN}
      aria-valuemax={SPLIT_MAX}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={() => setPref('splitPct', 44)}
      title="끌어서 너비 조절 (두 번 클릭하면 기본값)"
    >
      <span className="splitter-grip" aria-hidden="true" />
    </div>
  );
}
