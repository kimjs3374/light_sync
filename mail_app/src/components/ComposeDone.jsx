import { useState } from 'react';
import { useCompose } from '../store/compose';
import { useMail } from '../store/mail';
import { Paperclip, Close } from './Icons';
import TimePicker from './TimePicker';

const DAYS = ['일', '월', '화', '수', '목', '금', '토'];
const pad = (n) => String(n).padStart(2, '0');

function humanWhen(d) {
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}. (${DAYS[d.getDay()]}) `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 지금부터 얼마 뒤인지 — "언제 나가지?"가 바로 읽히게 */
function untilText(d) {
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return '곧';
  const min = Math.round(ms / 60000);
  if (min < 60) return `${min}분 뒤`;
  const hour = Math.round(min / 60);
  if (hour < 24) return `${hour}시간 뒤`;
  return `${Math.round(hour / 24)}일 뒤`;
}

export default function ComposeDone({ done }) {
  const c = useCompose();
  const accounts = useMail((s) => s.accounts);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const account = accounts.find((a) => a.id === done.accountId);
  const when = done.when instanceof Date ? done.when : new Date(done.at);

  const cancel = async () => {
    if (!window.confirm('예약을 취소하고 이 메일을 보내지 않도록 할까요?')) return;
    setBusy(true);
    const ok = await c.cancelScheduled();
    setBusy(false);
    if (!ok) window.alert('예약을 취소하지 못했습니다. 잠시 후 다시 시도해주세요.');
  };

  const change = async (value) => {
    setPicking(false);
    setBusy(true);
    const r = await c.reschedule(value);
    setBusy(false);
    if (r?.error) window.alert(r.error);
  };

  const Line = ({ label, children }) => (
    <div className="done-line"><span>{label}</span><b>{children}</b></div>
  );

  return (
    <div className="compose-done">
      <div className="done-card">
        <button className="compose-close done-x" title="닫기" onClick={() => c.clearDone()}>
          <Close size={16} />
        </button>

        <div className={`done-mark${done.canceled ? ' canceled' : ''}`}>
          {done.canceled ? '취소됨' : '예약 완료'}
        </div>

        {done.canceled ? (
          <>
            <h2 className="done-title">예약을 취소했습니다</h2>
            <p className="done-sub">이 메일은 보내지 않습니다.</p>
          </>
        ) : (
          <>
            <h2 className="done-title">{humanWhen(when)} 에 보냅니다</h2>
            <p className="done-sub">지금부터 {untilText(when)}입니다. 그전까지는 취소할 수 있습니다.</p>
          </>
        )}

        <div className="done-detail">
          <Line label="보내는사람">
            {account?.display_name ? `${account.display_name} <${account.email}>` : account?.email}
          </Line>
          <Line label="받는사람">{done.to.join(', ')}</Line>
          {done.cc.length > 0 && <Line label="참조">{done.cc.join(', ')}</Line>}
          {done.bcc.length > 0 && <Line label="숨은참조">{done.bcc.join(', ')}</Line>}
          <Line label="제목">{done.subject || '(제목 없음)'}</Line>
          {done.attachments > 0 && (
            <Line label="첨부">
              <span className="done-attach"><Paperclip size={12} />{done.attachments}개 함께 보냅니다</span>
            </Line>
          )}
        </div>

        <div className="done-actions">
          <button className="btn-send" onClick={() => c.clearDone()}>메일함으로</button>
          {!done.canceled && (
            <div className="done-change">
              <button className="done-alt" disabled={busy} onClick={() => setPicking((v) => !v)}>
                예약 변경
              </button>
              {picking && (
                <TimePicker
                  title="예약 시각 변경"
                  confirm="이 시각으로 변경"
                  initial={when}
                  onPick={change}
                  onClose={() => setPicking(false)}
                />
              )}
            </div>
          )}
          {!done.canceled && (
            <button className="done-cancel" disabled={busy} onClick={cancel}>
              {busy ? '취소하는 중…' : '예약 취소'}
            </button>
          )}
          <button className="done-more" onClick={() => { c.clearDone(); c.open('new'); }}>
            새 메일 쓰기
          </button>
        </div>
      </div>
    </div>
  );
}
