import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';

/**
 * 첨부를 올리며 보내는 중 — 진행률 막대.
 *
 * 창(모달)이 아니라 **발송 화면 안에 들어가는 조각**이다. 보내기를 누르면 곧바로
 * 발송 화면으로 넘어가고, 여기서 얼마나 갔는지를 보여 준다.
 *
 * 올리는 주체가 둘이라 읽을 곳도 둘이다:
 *   PC 파일     브라우저가 직접 올린다 → 작성창의 largeFiles (여러 개면 합쳐서 본다)
 *   파일서버 파일 서버가 옮긴다 → sendJob (스토어가 1초마다 물어본다)
 * 묻는 일은 여기서 하지 않는다 — 사람이 메일함으로 나가도 감시가 끊기면 안 되므로
 * 스토어가 들고 있고, 이 조각은 그 값을 그리기만 한다.
 */
export default function SendProgress() {
  const job = useCompose((s) => s.sendJob);
  const largeFiles = useCompose((s) => (s.flight || s.active)?.largeFiles);

  let phase = '';
  let done = 0;
  let total = 0;
  let count = 0;
  let doneCount = 0;

  if (job) {
    phase = job.phase || '';
    done = job.done_bytes || 0;
    total = job.total_bytes || 0;
    count = job.file_count || 0;
    doneCount = job.done_files || 0;
  } else if (largeFiles?.length) {
    const pending = largeFiles.filter((l) => l.status !== 'error');
    total = pending.reduce((n, l) => n + (l.size || 0), 0);
    done = pending.reduce((n, l) => n + (l.status === 'done' ? l.size : (l.loaded || 0)), 0);
    count = pending.length;
    doneCount = pending.filter((l) => l.status === 'done').length;
    phase = (pending.find((l) => l.status === 'uploading') || {}).name || '';
  } else {
    return null;
  }

  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <div className="sendp-panel">
      <p className="sendp-note">
        {phase || '준비 중…'}
        {count > 1 && ` · ${Math.min(doneCount + 1, count)}/${count}번째 파일`}
      </p>
      <div className="sendp-bar"><i style={{ width: `${pct}%` }} /></div>
      <div className="sendp-nums">
        <b>{pct}%</b>
        <span>{formatSize(done)} / {formatSize(total)}</span>
      </div>
    </div>
  );
}
