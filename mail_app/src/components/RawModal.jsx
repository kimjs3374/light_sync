import { useEffect, useState } from 'react';
import { api, mailApi } from '../api/client';
import { Close } from './Icons';

/**
 * 원문 보기 — 헤더까지 그대로.
 *
 * "이 메일이 진짜 그 사람이 보낸 게 맞나", "왜 스팸함으로 갔나" 는 본문이 아니라
 * **헤더**(Received, SPF/DKIM, Return-Path)에 적혀 있다. 화면이 예쁘게 정리해
 * 보여주는 값들 뒤에 뭐가 있었는지 볼 자리가 하나는 있어야 한다.
 *
 * 원문을 열어도 **읽음 상태는 바뀌지 않는다**(서버가 PEEK 로 읽는다).
 */
export default function RawModal({ account, folder, uid, onClose }) {
  const [text, setText] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    api.text(mailApi.rawUrl({ account, folder, uid }))
      .then(setText)
      .catch((e) => setError(e.message || '원문을 읽지 못했습니다'));
  }, [account, folder, uid]);

  const save = async () => {
    try {
      await api.openBinary(mailApi.rawUrl({ account, folder, uid, download: true }), `mail_${uid}.eml`);
    } catch (e) { window.alert(e.message || '내려받지 못했습니다'); }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(text || ''); } catch { /* 권한이 없으면 포기 */ }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="contact-card wide raw-card" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label="원문 보기">
        <div className="contact-card-head">
          <h3>원문 보기</h3>
          <button className="icon-btn" title="닫기" onClick={onClose}><Close /></button>
        </div>

        <div className="raw-body">
          {error ? <div className="list-state error">{error}</div>
            : text === null ? <div className="list-state">원문을 불러오는 중…</div>
              : <pre className="raw-text">{text}</pre>}
        </div>

        <div className="contact-card-foot">
          <button className="set-btn primary" onClick={save}>.eml 파일로 저장</button>
          <button className="set-btn" onClick={copy} disabled={!text}>원문 복사</button>
          <button className="btn-cancel" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
