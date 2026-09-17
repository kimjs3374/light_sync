import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';

/**
 * 큰 첨부를 올리며 보내는 중 — 진행률 화면.
 *
 * 30GB 짜리를 붙이면 NAS → Storage 로 옮기는 데만 몇 분이 걸린다. 그동안 멈춘
 * 화면을 보여주면 사람은 고장으로 여기고 새로고침한다. 그래서 **얼마나 갔는지**를
 * 적어 준다 — 서버가 뒤에서 옮기고, 이 화면은 1초마다 물어본다.
 *
 * 실패하면 작성 화면을 그대로 돌려준다. 여기서 닫아 버리면 쓴 것이 사라진다.
 */
export default function SendProgress({ job, onDone, onFail }) {
  const [st, setSt] = useState({
    status: 'uploading', phase: '', done_bytes: 0,
    total_bytes: job.total_bytes || 0, file_count: job.file_count || 0, done_files: 0,
  });
  const timer = useRef(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.get(`/mail/api/send-job/${job.job_id}`);
        if (!alive) return;
        if (r.error && !r.status) { onFail(r.error); return; }
        setSt(r);
        if (r.status === 'done') { onDone(); return; }
        if (r.status === 'error') { onFail(r.error || '보내지 못했습니다'); return; }
      } catch (e) {
        if (alive) onFail(e.message || '진행 상황을 읽지 못했습니다');
        return;
      }
      timer.current = setTimeout(tick, 1000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.job_id]);

  const pct = st.total_bytes > 0
    ? Math.min(100, Math.round((st.done_bytes / st.total_bytes) * 100)) : 0;

  return (
    <div className="modal-backdrop">
      <div className="sendp" role="dialog" aria-label="보내는 중">
        <h3 className="sendp-title">
          {st.status === 'sending' ? '메일을 보내는 중입니다' : '큰 첨부를 올리는 중입니다'}
        </h3>
        <p className="sendp-note">
          {st.phase || '준비 중…'}
          {st.file_count > 1 && ` · ${Math.min(st.done_files + 1, st.file_count)}/${st.file_count}번째 파일`}
        </p>

        <div className="sendp-bar"><i style={{ width: `${pct}%` }} /></div>
        <div className="sendp-nums">
          <b>{pct}%</b>
          <span>{formatSize(st.done_bytes)} / {formatSize(st.total_bytes)}</span>
        </div>

        {/* 창을 닫아도 서버는 계속 옮긴다 — 그 말을 안 적으면 닫기가 무서워진다 */}
        <p className="sendp-hint">
          이 창을 닫으셔도 <b>보내기는 계속됩니다.</b>
          <br />
          파일이 크면 몇 분 걸립니다. 다 올라가면 메일이 나갑니다.
        </p>
        <div className="sendp-foot">
          <button className="btn-cancel" onClick={() => useCompose.setState({ sendJob: null })}>
            창 닫기
          </button>
        </div>
      </div>
    </div>
  );
}
