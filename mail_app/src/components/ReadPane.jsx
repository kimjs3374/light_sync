import { useMail } from '../store/mail';
import { api, mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { formatFullDate, formatSize, senderName, senderEmail } from '../lib/format';
import { Close, Paperclip, Mail } from './Icons';

function AddressLine({ label, list }) {
  if (!list || !list.length) return null;
  return (
    <div className="addr-line">
      <span className="addr-label">{label}</span>
      <span className="addr-value">
        {list.map((a, i) => (
          <span key={i} className="addr-chip" title={a.email}>
            {a.name ? `${a.name} <${a.email}>` : a.email}
          </span>
        ))}
      </span>
    </div>
  );
}

export default function ReadPane() {
  const s = useMail();
  const d = s.detail;

  const download = async (att) => {
    const url = mailApi.attachmentUrl({
      account: s.accountId, folder: s.folder, uid: s.openUid, partId: att.part_id,
    });
    try {
      await api.openBinary(url, att.filename);
    } catch (e) {
      alert(e.message || '첨부를 받지 못했습니다');
    }
  };

  if (!s.openUid) {
    return (
      <div className="read-pane">
        <div className="read-empty">
          <span className="read-empty-icon"><Mail size={34} /></span>
          <p className="read-empty-text">읽을 메일을 선택하세요</p>
          <p className="read-empty-hint">↑ ↓ 키로도 옮겨 다닐 수 있습니다</p>
        </div>
      </div>
    );
  }
  if (s.detailLoading) return <div className="read-pane"><div className="list-state">메일을 여는 중…</div></div>;
  if (s.detailError) return <div className="read-pane"><div className="list-state error">{s.detailError}</div></div>;
  if (!d) return null;

  return (
    <div className="read-pane">
      <div className="read-head">
        <div className="read-subject-row">
          <h2 className="read-subject">{d.subject || '(제목 없음)'}</h2>
          <button className="icon-btn" title="닫기" onClick={s.close}><Close /></button>
        </div>

        <div className="read-actions">
          <button onClick={() => useCompose.getState().open('reply')}>답장</button>
          <button onClick={() => useCompose.getState().open('replyAll')}>전체답장</button>
          <button onClick={() => useCompose.getState().open('forward')}>전달</button>
          <button className="plain" onClick={() => useCompose.getState().open('resend')}>다시 보내기</button>
        </div>

        <div className="read-meta">
          <div className="read-from">
            <strong>{senderName(d.from)}</strong>
            <span className="read-from-email">{senderEmail(d.from)}</span>
          </div>
          <div className="read-date">{formatFullDate(d.date)}</div>
        </div>

        <AddressLine label="받는사람" list={d.to} />
        <AddressLine label="참조" list={d.cc} />

        {d.attachments?.length > 0 && (
          <div className="attach-box">
            <div className="attach-title">첨부 {d.attachments.length}개</div>
            <div className="attach-list">
              {d.attachments.map((a) => (
                <button key={a.part_id} className="attach-item" onClick={() => download(a)}>
                  <Paperclip size={12} />
                  <span className="attach-name">{a.filename}</span>
                  <span className="attach-size">{formatSize(a.size)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="read-body">
        {d.html_body
          ? <div className="mail-html" dangerouslySetInnerHTML={{ __html: d.html_body }} />
          : <pre className="mail-text">{d.text_body}</pre>}
      </div>
    </div>
  );
}
