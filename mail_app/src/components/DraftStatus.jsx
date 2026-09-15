import { useCompose } from '../store/compose';
import { draftSignature } from '../lib/compose';

const pad = (n) => String(n).padStart(2, '0');
const clock = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

/**
 * 임시저장 상태 — 닫기(✕) 바로 아래.
 *
 * 세 가지를 한자리에서 읽게 한다: **저장했는가 · 몇 번째인가 · 언제인가.**
 * 임시저장은 손으로 눌러야 되는 일이라, 눌렀는지 아닌지가 화면에 안 남으면
 * "저장한 줄 알았는데 안 돼 있었다"가 된다.
 *
 * 저장한 뒤 글자 한 자라도 고치면 '변경됨'으로 돌아간다 — 지문(draftSignature)이
 * 저장 순간의 것과 다른지로 판단한다.
 */
export default function DraftStatus() {
  const c = useCompose();
  const w = c.active;
  if (!w) return null;

  // 예약 메일 수정은 임시저장이 아니라 예약본을 고치는 것이라 표시하지 않는다
  if (w.mode === 'editScheduled') return null;

  const dirty = draftSignature(w) !== w.savedSig;

  let state = 'none';                      // 아직 한 번도 저장 안 함
  if (w.saving) state = 'saving';
  else if (w.savedAt) state = dirty ? 'dirty' : 'saved';

  const LABEL = {
    none: '임시저장 안 됨',
    saving: '저장 중…',
    saved: '저장됨',
    dirty: '저장 후 변경됨',
  };

  return (
    <div className={`draft-status is-${state}`} aria-live="polite">
      <span className="ds-state"><i className="ds-dot" />{LABEL[state]}</span>
      {w.savedAt && (
        <span className="ds-meta">v{w.draftVersion} · {clock(w.savedAt)}</span>
      )}
    </div>
  );
}
