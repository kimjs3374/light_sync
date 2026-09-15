import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { formatSize } from '../lib/format';
import { Close, Paperclip } from './Icons';

const DAYS = ['일', '월', '화', '수', '목', '금', '토'];
const pad = (n) => String(n).padStart(2, '0');

const whenText = (str) => {
  const d = new Date(String(str).replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return str;
  return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}. (${DAYS[d.getDay()]}) `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** 예약해 둔 메일의 본문·첨부를 보여준다 — 보내기 전에 무엇을 보내는지 확인할 수 있어야 한다 */
export default function ScheduledDetail({ id, onClose, onCancel, onEdit }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    api.get(`/mail/api/schedule/${id}`)
      .then((r) => { if (!alive) return; r.error ? setError(r.error) : setData(r); })
      .catch((e) => alive && setError(e.message || '불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [id]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const download = async (a) => {
    try {
      await api.openBinary(`/mail/api/schedule/${id}/attachment/${a.index}`, a.filename);
    } catch (e) {
      window.alert(e.message || '첨부를 받지 못했습니다.');
    }
  };

  const Line = ({ label, children }) => (
    <div className="preview-line"><span>{label}</span><b>{children}</b></div>
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="preview-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="예약 메일">
        <div className="preview-head">
          <span className="preview-badge">예약 메일</span>
          <button className="icon-btn" onClick={onClose} title="닫기"><Close /></button>
        </div>

        {error && <div className="list-state error">{error}</div>}
        {!data && !error && <div className="list-state">불러오는 중…</div>}

        {data && (
          <>
            <div className="preview-meta">
              <h3 className="preview-subject">{data.subject || '(제목 없음)'}</h3>
              <Line label="보낼시각"><b className="sched-hl">{whenText(data.scheduled_at)}</b></Line>
              <Line label="받는사람">{data.to || '(없음)'}</Line>
              {data.cc && <Line label="참조">{data.cc}</Line>}
              {data.bcc && <Line label="숨은참조">{data.bcc}</Line>}
              {data.attachments.length > 0 && (
                <div className="preview-line">
                  <span>첨부</span>
                  <b className="preview-attach">
                    {data.attachments.map((a) => (
                      <button key={a.index} className="attach-item" onClick={() => download(a)}>
                        <Paperclip size={12} />
                        <span className="attach-name">{a.filename}</span>
                        <span className="attach-size">{formatSize(a.size)}</span>
                      </button>
                    ))}
                  </b>
                </div>
              )}
            </div>

            <div className="preview-body">
              <div className="mail-html" dangerouslySetInnerHTML={{ __html: data.body }} />
            </div>

            <div className="preview-foot">
              <button className="btn-send" onClick={() => { onClose(); onEdit(); }}>수정</button>
              <button className="btn-cancel" onClick={onClose}>닫기</button>
              <button className="done-cancel" onClick={() => { onClose(); onCancel(); }}>예약 취소</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
