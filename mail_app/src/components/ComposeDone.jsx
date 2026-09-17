import { useState } from 'react';
import { useCompose } from '../store/compose';
import { useMail } from '../store/mail';
import { Paperclip, Close } from './Icons';
import TimePicker from './TimePicker';
import SendProgress from './SendProgress';

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

/**
 * 보내기를 누른 뒤의 화면.
 *
 * 네 가지를 한 카드로 보여 준다:
 *   scheduled  예약했습니다 (시각 변경·취소)
 *   sending    큰 첨부를 올리는 중 — 진행률
 *   sent       보냈습니다
 *   failed     보내지 못했습니다 — 쓰던 것으로 되돌아갈 수 있다
 *
 * 큰 첨부는 올리는 데만 몇 분이 걸린다. 작성 화면 위에 창을 띄워 붙들어 두지 않고
 * **곧장 이 화면으로 넘어와서** 얼마나 갔는지 보여 준다 — 그동안 메일함으로 가도 된다.
 */
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

  /* 컴포넌트가 아니라 **그려 둔 조각**이다 — 컴포넌트로 두면 진행률이 1초마다
     갱신될 때 이 덩어리가 통째로 다시 붙는다 */
  const detail = (
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
  );

  /* ── 보내는 중 · 보냈습니다 · 못 보냈습니다 ─────────────────────────── */
  if (done.kind === 'sending' || done.kind === 'sent' || done.kind === 'failed') {
    const sending = done.kind === 'sending';
    const failed = done.kind === 'failed';
    return (
      <div className="compose-done">
        <div className="done-card">
          {/* 보내는 중에는 닫기를 두지 않는다 — 진행 중인 것을 지운 것처럼 보인다.
              대신 아래 '메일함으로' 로 나가면 되고, 보내기는 그대로 계속된다. */}
          {!sending && (
            <button className="compose-close done-x" title="닫기" onClick={() => c.clearDone()}>
              <Close size={16} />
            </button>
          )}

          <div className={`done-mark${failed ? ' failed' : ''}`}>
            {sending ? '보내는 중' : failed ? '보내지 못함' : '발송 완료'}
          </div>

          <h2 className="done-title">
            {sending ? '큰 첨부를 올리고 있습니다'
              : failed ? '메일을 보내지 못했습니다'
                : '메일을 보냈습니다'}
          </h2>
          <p className="done-sub">
            {sending ? '다 올라가면 메일이 나갑니다. 파일이 크면 몇 분 걸립니다.'
              : failed ? (done.error || '알 수 없는 오류입니다.')
                : done.large
                  ? '큰 첨부는 링크로 갔습니다. 받는 분은 링크를 눌러 내려받습니다.'
                  : '보낸편지함에서 다시 보실 수 있습니다.'}
          </p>

          {sending && <SendProgress />}

          {detail}

          {sending && (
            /* 이 말이 없으면 화면을 떠나기가 무서워진다 — 실제로 계속 올라간다.
               다만 PC 파일은 **이 브라우저가** 올리는 중이라 창을 닫으면 멈춘다.
               파일서버 파일은 서버가 옮기므로 창을 닫아도 된다. 그 차이를 적는다. */
            <p className="done-keep">
              이 화면을 떠나셔도 <b>보내기는 계속됩니다.</b>
              메일함을 보고 계셔도 되고, 다른 메일을 쓰셔도 됩니다.
              <br />
              {done.source === 'local'
                ? '다만 이 브라우저가 올리는 중이라, 창을 닫으면 멈춥니다.'
                : '창을 닫으셔도 서버가 마저 보냅니다.'}
            </p>
          )}

          <div className="done-actions">
            <button className="btn-send" onClick={() => c.clearDone()}>메일함으로</button>
            {failed && (
              <button className="done-alt" onClick={() => c.backToCompose()}>
                쓰던 메일로 돌아가기
              </button>
            )}
            {!sending && !failed && (
              <button className="done-more" onClick={() => { c.clearDone(); c.open('new'); }}>
                새 메일 쓰기
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

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

        {detail}

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
