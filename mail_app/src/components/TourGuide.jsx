import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { TOUR_STEPS, markTourSeen } from '../lib/tour';
import { Close } from './Icons';

/**
 * 화면 안내 — 가리키는 자리에 구멍을 내고 그 옆에 설명을 붙인다.
 *
 * 구멍은 **테두리에 아주 큰 그림자**를 깔아서 만든다(box-shadow 9999px).
 * 실제로 화면을 오려낼 방법은 없고, 이 방법이면 어떤 배경 위에서도 그 자리만 밝게 남는다.
 *
 * 가리킬 자리가 지금 화면에 없으면(그 버튼이 안 보이는 상태면) **그 걸음은 건너뛴다.**
 * 허공을 가리키는 안내가 제일 못 미덥다.
 */

const PAD = 6;          // 구멍을 대상보다 조금 크게
const GAP = 14;         // 대상과 설명 상자 사이
const EDGE = 12;        // 화면 가장자리 여백

/**
 * 설명 상자를 놓을 자리.
 *
 * 아래 → 위 → 오른쪽 → 왼쪽 순으로 **들어가는 곳**을 고르고, 넷 다 안 되면
 * 대상 안쪽에 얹는다. 목록처럼 화면 높이를 거의 다 쓰는 대상은 위아래 어디에도
 * 안 들어가서, 예전에는 상자가 화면 밖으로 밀려 나갔다(7번 걸음).
 * 마지막에는 **무조건 화면 안으로 되민다** — 어떤 경우에도 상자가 잘리면 안 된다.
 */
function placePopup(rect, pw, ph) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const fits = (p) => p.top >= EDGE && p.left >= EDGE
    && p.top + ph <= vh - EDGE && p.left + pw <= vw - EDGE;

  const spots = [
    { top: rect.bottom + GAP, left: rect.left },          // 아래
    { top: rect.top - ph - GAP, left: rect.left },        // 위
    { top: rect.top, left: rect.right + GAP },            // 오른쪽
    { top: rect.top, left: rect.left - pw - GAP },        // 왼쪽
  ];
  const chosen = spots.find(fits) || { top: rect.top + 16, left: rect.left + 16 };
  return {
    top: Math.min(Math.max(EDGE, chosen.top), Math.max(EDGE, vh - ph - EDGE)),
    left: Math.min(Math.max(EDGE, chosen.left), Math.max(EDGE, vw - pw - EDGE)),
  };
}

export default function TourGuide({ onClose }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);
  const [pos, setPos] = useState(null);
  const popRef = useRef(null);
  const step = TOUR_STEPS[i];

  const finish = useCallback(() => {
    markTourSeen();
    onClose();
  }, [onClose]);

  /** 지금 걸음이 가리킬 자리를 찾는다. 없으면 가던 방향으로 한 칸 더 간다. */
  const locate = useCallback((idx, dir = 1) => {
    let n = idx;
    while (n >= 0 && n < TOUR_STEPS.length) {
      const s = TOUR_STEPS[n];
      if (!s.target) return { n, el: null };
      const el = document.querySelector(s.target);
      if (el && el.getBoundingClientRect().width > 0) return { n, el };
      n += dir;            // 지금 화면에 없는 자리는 건너뛴다
    }
    return null;
  }, []);

  const go = useCallback((idx, dir) => {
    const found = locate(idx, dir);
    if (!found) { finish(); return; }
    setI(found.n);
    if (found.el) {
      found.el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      setRect(found.el.getBoundingClientRect());
    } else {
      setRect(null);
    }
  }, [locate, finish]);

  useEffect(() => { go(0, 1); /* eslint-disable-next-line */ }, []);

  // 상자 크기는 글 길이에 따라 다르다 — **그린 직후 재서** 자리를 잡는다.
  // 크기를 어림잡으면 긴 설명에서 또 화면 밖으로 나간다.
  useLayoutEffect(() => {
    const el = popRef.current;
    if (!el) return;
    if (!rect) { setPos(null); return; }
    setPos(placePopup(rect, el.offsetWidth, el.offsetHeight));
  }, [rect, i]);

  // 창 크기가 바뀌거나 스크롤되면 구멍도 따라가야 한다
  useEffect(() => {
    const sync = () => {
      const s = TOUR_STEPS[i];
      if (!s?.target) { setRect(null); return; }
      const el = document.querySelector(s.target);
      setRect(el ? el.getBoundingClientRect() : null);
    };
    window.addEventListener('resize', sync);
    window.addEventListener('scroll', sync, true);
    return () => {
      window.removeEventListener('resize', sync);
      window.removeEventListener('scroll', sync, true);
    };
  }, [i]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); finish(); }
      else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); go(i + 1, 1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(i - 1, -1); }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [i, go, finish]);

  if (!step) return null;
  const last = i === TOUR_STEPS.length - 1;

  return (
    <div className="tour-layer" role="dialog" aria-label="화면 안내">
      {/* 클릭을 먹는 판 — 안내 중에는 화면을 건드리지 않게 한다 */}
      <div className="tour-catch" onClick={() => go(i + 1, 1)} />

      {rect && (
        <div
          className="tour-hole"
          style={{
            top: rect.top - PAD, left: rect.left - PAD,
            width: rect.width + PAD * 2, height: rect.height + PAD * 2,
          }}
        />
      )}

      <div
        ref={popRef}
        className={`tour-pop${rect ? '' : ' centered'}`}
        style={pos ? { top: pos.top, left: pos.left } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="tour-head">
          <span className="tour-step">{i + 1} / {TOUR_STEPS.length}</span>
          <strong>{step.title}</strong>
          <button className="icon-btn" title="안내 닫기" onClick={finish}><Close /></button>
        </div>
        <p className="tour-body">{step.body}</p>
        <div className="tour-foot">
          <button className="tour-skip" onClick={finish}>그만 보기</button>
          <span className="tour-dots" aria-hidden="true">
            {TOUR_STEPS.map((_, n) => (
              <i key={n} className={n === i ? 'on' : ''} />
            ))}
          </span>
          <button className="set-btn" disabled={i === 0} onClick={() => go(i - 1, -1)}>이전</button>
          <button className="set-btn primary" onClick={() => (last ? finish() : go(i + 1, 1))}>
            {last ? '알겠습니다' : '다음'}
          </button>
        </div>
      </div>
    </div>
  );
}
