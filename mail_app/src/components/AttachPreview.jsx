import { useEffect, useState } from 'react';
import { api, mailApi } from '../api/client';
import { formatSize } from '../lib/format';
import { Close } from './Icons';

/**
 * 첨부 미리보기 — 내려받지 않고 화면에서 바로 본다.
 *
 * 받은 파일이 맞는지 확인하려고 매번 내려받아 열고, 아니면 지우는 일이 잦다.
 * 이미지와 PDF 는 그 자리에서 보이면 그 왕복이 없어진다.
 * (내려받기는 그대로 둔다 — 여기서 보는 것은 확인용이다)
 *
 * 주소를 그대로 <img src> 에 걸 수 없다. 첨부 주소는 Bearer 토큰을 요구하는데
 * 브라우저가 이미지·iframe 을 받아올 때는 헤더를 못 붙인다. 그래서 blob 으로
 * 받아 createObjectURL 로 띄우고, **닫을 때 반드시 revoke** 한다(안 하면 그
 * 파일이 탭이 닫힐 때까지 메모리에 남는다).
 */

const IMAGE_EXT = /\.(jpe?g|png|gif|webp)$/i;
const PDF_EXT = /\.pdf$/i;

/** 미리보기로 열 수 있는 첨부인가 — 'image' | 'pdf' | null */
export function previewKind(att) {
  const type = String(att?.content_type || '').toLowerCase();
  const name = String(att?.filename || '');
  // content_type 을 먼저 본다. 메일 클라이언트에 따라 전부
  // application/octet-stream 으로 붙여 보내는 곳이 있어 이름으로도 한 번 더 본다.
  if (type.startsWith('image/') && !type.includes('svg')) return 'image';
  if (type === 'application/pdf') return 'pdf';
  if (IMAGE_EXT.test(name)) return 'image';
  if (PDF_EXT.test(name)) return 'pdf';
  return null;
}

export default function AttachPreview({ account, folder, uid, att, onClose }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const kind = previewKind(att);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let objUrl = '';
    let alive = true;
    (async () => {
      try {
        // api 에 blob 을 받는 공개 함수가 아직 없다(openBinary 는 곧바로 내려받는다).
        // _fetch 는 Bearer 와 401 처리를 함께 들고 있으므로 그것을 쓴다.
        const res = await api._fetch(mailApi.attachmentUrl({
          account, folder, uid, partId: att.part_id,
        }));
        if (!res.ok) throw new Error(`첨부를 열지 못했습니다 (${res.status})`);
        const blob = await res.blob();
        if (!alive) return;
        objUrl = URL.createObjectURL(blob);
        setUrl(objUrl);
      } catch (e) {
        if (alive) setError(e.message || '첨부를 열지 못했습니다');
      }
    })();
    return () => {
      alive = false;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [account, folder, uid, att.part_id]);

  const save = async () => {
    try {
      await api.openBinary(
        mailApi.attachmentUrl({ account, folder, uid, partId: att.part_id }),
        att.filename,
      );
    } catch (e) {
      window.alert(e.message || '첨부를 받지 못했습니다');
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="contact-card wide att-card" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label={`${att.filename} 미리보기`}>
        <div className="contact-card-head">
          <h3 className="att-head-name" title={att.filename}>{att.filename}</h3>
          <span className="att-head-size">{formatSize(att.size)}</span>
          <button className="icon-btn" title="닫기" onClick={onClose}><Close /></button>
        </div>

        <div className="att-body">
          {error ? <div className="list-state error">{error}</div>
            : !url ? <div className="list-state">첨부를 여는 중…</div>
              : kind === 'image'
                ? <img className="att-image" src={url} alt={att.filename} />
                : <iframe className="att-frame" src={url} title={att.filename} />}
        </div>

        <div className="contact-card-foot">
          <button className="set-btn primary" onClick={save}>내려받기</button>
          <button className="btn-cancel" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
