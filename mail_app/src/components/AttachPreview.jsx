import { useEffect, useState } from 'react';
import { api, mailApi } from '../api/client';
import { formatSize } from '../lib/format';
import { Close } from './Icons';

/**
 * 첨부 미리보기 — 내려받지 않고 화면에서 바로 본다.
 *
 * 받은 파일이 맞는지 확인하려고 매번 내려받아 열고, 아니면 지우는 일이 잦다.
 * 그 자리에서 보이면 그 왕복이 없어진다.
 * (내려받기는 그대로 둔다 — 여기서 보는 것은 확인용이다)
 *
 * 네 갈래다:
 *   이미지·PDF   원본 그대로 (blob)
 *   한글 hwp/hwpx 서버가 HTML 로 세워 준다 (rhwp) — **sandbox 건 iframe** 에 넣는다
 *   오피스 문서   회사 문서서버(ONLYOFFICE)가 **원본 그대로** 연다
 * 뒤 둘은 준비에 몇 초 걸린다. 그 사이에 무엇을 하고 있는지 적어 준다.
 *
 * 주소를 그대로 <img src> 에 걸 수 없다. 첨부 주소는 Bearer 토큰을 요구하는데
 * 브라우저가 이미지·iframe 을 받아올 때는 헤더를 못 붙인다. 그래서 blob 으로
 * 받아 createObjectURL 로 띄우고, **닫을 때 반드시 revoke** 한다(안 하면 그
 * 파일이 탭이 닫힐 때까지 메모리에 남는다).
 */

const IMAGE_EXT = /\.(jpe?g|png|gif|webp)$/i;
const PDF_EXT = /\.pdf$/i;
const HWP_EXT = /\.(hwp|hwpx)$/i;
/* 서버가 PDF 로 바꿔 줄 수 있는 것들. 실제로 되는지는 서버에 깔린 구성 요소에 달렸다 —
   안 되면 서버가 "내려받아 보십시오" 라고 알려 주고, 화면은 그 말을 그대로 띄운다. */
const OFFICE_EXT = /\.(xlsx?|csv|ods|docx?|rtf|odt|pptx?|odp)$/i;

/** 미리보기로 열 수 있는 첨부인가 — 'image' | 'pdf' | 'hwp' | 'office' | null */
export function previewKind(att) {
  const type = String(att?.content_type || '').toLowerCase();
  const name = String(att?.filename || '');
  // content_type 을 먼저 본다. 메일 클라이언트에 따라 전부
  // application/octet-stream 으로 붙여 보내는 곳이 있어 이름으로도 한 번 더 본다.
  if (type.startsWith('image/') && !type.includes('svg')) return 'image';
  if (type === 'application/pdf') return 'pdf';
  if (IMAGE_EXT.test(name)) return 'image';
  if (PDF_EXT.test(name)) return 'pdf';
  if (HWP_EXT.test(name)) return 'hwp';
  if (OFFICE_EXT.test(name)) return 'office';
  return null;
}

export default function AttachPreview({ account, folder, uid, att, onClose }) {
  const [url, setUrl] = useState('');
  const [html, setHtml] = useState('');   // 한글 문서를 세운 HTML
  const [viewUrl, setViewUrl] = useState('');   // 문서서버 보기 화면 주소
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
        /* 워드·엑셀·PPT 는 회사 문서서버가 원본 그대로 연다. 우리가 PDF 로 바꾸면
           서식이 틀어지고, 이 서버에는 워드·PPT 를 여는 구성 요소도 없다.
           문서서버는 자기가 파일을 가지러 오므로 **먼저 자리를 만들고 주소를 받는다.** */
        if (kind === 'office') {
          const r = await mailApi.attachmentOffice({ account, folder, uid, partId: att.part_id });
          if (r.error) throw new Error(r.error);
          if (!alive) return;
          setViewUrl(r.view_url);
          return;
        }

        // 한글은 서버가 세워 준 HTML 을 받는다. 이미지·PDF 는 원본 그대로.
        const url0 = kind === 'hwp'
          ? mailApi.attachmentPreviewUrl({ account, folder, uid, partId: att.part_id })
          : mailApi.attachmentUrl({ account, folder, uid, partId: att.part_id });

        // api 에 blob 을 받는 공개 함수가 아직 없다(openBinary 는 곧바로 내려받는다).
        // _fetch 는 Bearer 와 401 처리를 함께 들고 있으므로 그것을 쓴다.
        const res = await api._fetch(url0);
        if (!res.ok) {
          // 서버가 못 바꾼 이유를 사람 말로 준다 — 그걸 그대로 띄운다
          let msg = `첨부를 열지 못했습니다 (${res.status})`;
          try { msg = (await res.json()).error || msg; } catch { /* JSON 이 아니면 그대로 */ }
          throw new Error(msg);
        }
        if (kind === 'hwp') {
          // 남이 보낸 파일에서 나온 내용이다 — 문서로 심지 말고 sandbox 안에 넣는다
          const text = await res.text();
          if (!alive) return;
          setHtml(text);
          return;
        }
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
  }, [account, folder, uid, att.part_id, kind]);

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
            : !url && !html && !viewUrl ? (
              <div className="list-state">
                {kind === 'office' ? '문서를 여는 중입니다… 잠시만 기다려 주세요.'
                  : kind === 'hwp' ? '한글 문서를 세우는 중입니다… 잠시만 기다려 주세요.'
                    : '첨부를 여는 중…'}
              </div>
            )
              : viewUrl ? (
                /* 문서서버 화면은 우리 서버가 내주는 우리 페이지다(같은 출처) */
                <iframe className="att-frame" src={viewUrl} title={att.filename} />
              )
              : kind === 'image' ? <img className="att-image" src={url} alt={att.filename} />
                : kind === 'hwp' ? (
                  /* sandbox 를 비워 두면 스크립트도, 바깥으로 나가는 링크도 못 돈다 */
                  <iframe className="att-frame" srcDoc={html} sandbox="" title={att.filename} />
                )
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
