import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';

/**
 * 큰 첨부를 올리며 보내는 중 — 진행률 막대.
 *
 * 창(모달)이 아니라 **발송 화면 안에 들어가는 조각**이다. 보내기를 누르면 곧바로
 * 발송 화면으로 넘어가고, 여기서 얼마나 갔는지를 보여 준다.
 *
 * 묻는 일은 여기서 하지 않는다 — 스토어(_watchSend)가 1초마다 물어보고,
 * 이 조각은 그 값을 그리기만 한다. 사람이 메일함으로 나가도 감시가 끊기면 안 된다.
 */
export default function SendProgress() {
  const st = useCompose((s) => s.sendJob);
  if (!st) return null;

  const pct = st.total_bytes > 0
    ? Math.min(100, Math.round((st.done_bytes / st.total_bytes) * 100)) : 0;

  return (
    <div className="sendp-panel">
      <p className="sendp-note">
        {st.phase || '준비 중…'}
        {st.file_count > 1 && ` · ${Math.min(st.done_files + 1, st.file_count)}/${st.file_count}번째 파일`}
      </p>
      <div className="sendp-bar"><i style={{ width: `${pct}%` }} /></div>
      <div className="sendp-nums">
        <b>{pct}%</b>
        <span>{formatSize(st.done_bytes)} / {formatSize(st.total_bytes)}</span>
      </div>
    </div>
  );
}
