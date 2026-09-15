import { useEffect } from 'react';
import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';
import { Close, Paperclip } from './Icons';

/**
 * 미리보기 — 받는 쪽에서 보이는 모양 그대로 확인한다.
 * 본문 HTML 은 내가 방금 쓴 것이라 그대로 그린다(외부에서 온 메일이 아니다).
 */
export default function PreviewModal({ account }) {
  const c = useCompose();
  const w = c.active;
  const close = () => c.update({ previewing: false });

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const from = account?.display_name
    ? `${account.display_name} <${account.email}>` : (account?.email || '');

  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="preview-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="미리보기">
        <div className="preview-head">
          <span className="preview-badge">미리보기</span>
          <button className="icon-btn" onClick={close} title="닫기"><Close /></button>
        </div>

        <div className="preview-meta">
          <h3 className="preview-subject">{w.subject || '(제목 없음)'}</h3>
          <div className="preview-line"><span>보낸사람</span><b>{from}</b></div>
          <div className="preview-line"><span>받는사람</span><b>{w.to.join(', ') || '(없음)'}</b></div>
          {w.cc.length > 0 && <div className="preview-line"><span>참조</span><b>{w.cc.join(', ')}</b></div>}
          {w.bcc.length > 0 && (
            <div className="preview-line"><span>숨은참조</span><b>{w.bcc.join(', ')}</b>
              <em>받는 쪽에는 보이지 않습니다</em>
            </div>
          )}
          {(w.files.length > 0 || w.forward) && (
            <div className="preview-line">
              <span>첨부</span>
              <b className="preview-attach">
                {w.forward?.names.map((n, i) => (
                  <span key={`f${i}`}><Paperclip size={11} />{n}</span>
                ))}
                {w.files.map((f, i) => (
                  <span key={`u${i}`}><Paperclip size={11} />{f.name} <em>{formatSize(f.size)}</em></span>
                ))}
              </b>
            </div>
          )}
        </div>

        <div className="preview-body">
          <div className="mail-html" dangerouslySetInnerHTML={{ __html: w.bodyHtml }} />
        </div>

        <div className="preview-foot">
          <button className="btn-send" disabled={w.sending}
            onClick={() => { close(); c.send(); }}>
            이대로 보내기
          </button>
          <button className="btn-cancel" onClick={close}>돌아가서 고치기</button>
        </div>
      </div>
    </div>
  );
}
