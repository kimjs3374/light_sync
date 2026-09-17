import { useEffect, useRef, useState } from 'react';
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
 * **여는 일은 전부 이 브라우저가 한다. 서버는 파일만 내준다.**
 * 예전에는 오피스 문서를 회사 문서서버(ONLYOFFICE)로 보내 열었는데,
 *  - 웹메일 서버가 하는 일은 IMAP 중계와 첨부 내주기가 전부라, 문서 변환을 얹으면
 *    그게 그 서버에서 제일 무거운 일이 된다(한 건에 CPU 몇 초).
 *  - 남에게 파는 제품에 얹기에는 라이선스(AGPL)도 걸린다.
 * 오피스 문서는 ZIP 안의 XML 이라 JS 로 읽힌다 — 그래서 여기서 직접 그린다.
 *
 * 다섯 갈래다:
 *   이미지·PDF   원본 그대로 (blob)
 *   엑셀         SheetJS 로 읽어 표로
 *   워드         docx-preview 로 그대로
 *   한글 hwp     서버가 HTML 로 세워 준다 (rhwp)
 * 무거운 라이브러리는 **열 때 비로소 내려받는다**(dynamic import) — 메일함을 여는
 * 사람 대부분은 문서를 안 열어 보기 때문이다.
 *
 * 남이 보낸 파일에서 나온 내용이므로 **늘 iframe 안에** 넣는다. 스크립트는 못 돈다
 * (sandbox 에 allow-scripts 를 주지 않는다). 그림이 보이려면 같은 출처여야 해서
 * allow-same-origin 만 준다.
 */

const IMAGE_EXT = /\.(jpe?g|png|gif|webp)$/i;
const PDF_EXT = /\.pdf$/i;
const HWP_EXT = /\.(hwp|hwpx)$/i;
const EXCEL_EXT = /\.(xlsx|xlsm|xlsb|xls|csv)$/i;
const WORD_EXT = /\.docx$/i;
const ZIP_EXT = /\.zip$/i;

/* 브라우저에서 그리기에 너무 큰 것은 열지 않는다 — 탭이 통째로 멈춘다 */
const MAX_RENDER = 25 * 1024 * 1024;
/* 압축파일은 **목록만** 읽는다(풀지 않는다). 그래서 좀 더 큰 것까지 받아 준다 —
   사진 묶음처럼 "안에 뭐가 들었나" 가 궁금한 것은 대개 크다. */
const MAX_ZIP = 200 * 1024 * 1024;
/* 목록이 수만 개면 화면만 무거워진다 */
const ZIP_ROWS = 500;

/** 미리보기로 열 수 있는 첨부인가 — 'image'|'pdf'|'hwp'|'excel'|'word'|'zip'|null */
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
  if (EXCEL_EXT.test(name)) return 'excel';
  if (WORD_EXT.test(name)) return 'word';
  if (ZIP_EXT.test(name)) return 'zip';
  // .ppt·.doc 같은 옛 형식은 미리보기를 걸지 않는다 — 어설프게 깨진 화면보다 낫다
  return null;
}

const esc = (v) => String(v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * 압축파일 안에 뭐가 들었는지 — **풀지 않고 목록만** 읽는다.
 *
 * 받은 zip 이 맞는 것인지 확인하려고 매번 내려받아 풀어 보는 일이 잦다.
 * 이름·크기·날짜만 보면 대개 판가름이 난다.
 *
 * 한글 이름이 깨지는 함정: 윈도우 탐색기·알집으로 만든 zip 은 이름을 **CP949**
 * 로 적는다(UTF-8 표시 깃발이 없다). 그대로 읽으면 「�븳湲�」 가 된다.
 * UTF-8 로 엄격하게 읽어 보고 실패하면 EUC-KR 로 되읽는다.
 */
async function zipListHtml(buf) {
  const JSZip = (await import('jszip')).default;
  const utf8 = new TextDecoder('utf-8', { fatal: true });
  let euckr = null;
  try { euckr = new TextDecoder('euc-kr'); } catch { euckr = null; }

  const zip = await JSZip.loadAsync(buf, {
    decodeFileName: (bytes) => {
      try { return utf8.decode(bytes); } catch { /* UTF-8 이 아니다 */ }
      return euckr ? euckr.decode(bytes) : String.fromCharCode(...bytes);
    },
  });

  const rows = [];
  zip.forEach((path, f) => {
    if (f.dir) return;
    rows.push({
      path,
      size: f._data?.uncompressedSize ?? 0,
      packed: f._data?.compressedSize ?? 0,
      date: f.date,
    });
  });
  rows.sort((a, b) => a.path.localeCompare(b.path, 'ko'));

  const total = rows.reduce((n, r) => n + r.size, 0);
  const shown = rows.slice(0, ZIP_ROWS);
  const when = (d) => (d instanceof Date && !Number.isNaN(d.getTime())
    ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    : '');

  const body = shown.map((r) => {
    const cut = r.path.lastIndexOf('/');
    const dir = cut >= 0 ? r.path.slice(0, cut + 1) : '';
    const name = cut >= 0 ? r.path.slice(cut + 1) : r.path;
    return `<tr><td class="n">${dir ? `<i>${esc(dir)}</i>` : ''}${esc(name)}</td>`
      + `<td class="r">${esc(formatSize(r.size))}</td>`
      + `<td class="r">${esc(when(r.date))}</td></tr>`;
  }).join('');

  return `<p class="sum">파일 ${rows.length.toLocaleString()}개 · 압축 풀면 ${esc(formatSize(total))}</p>`
    + `<table class="zip"><tr><td class="n">이름</td><td class="r">크기</td><td class="r">날짜</td></tr>${body}</table>`
    + (rows.length > shown.length
      ? `<p class="sum">…앞의 ${ZIP_ROWS.toLocaleString()}개만 보여 드립니다.</p>` : '');
}

/** iframe 안에 빈 문서를 세우고 그 body 를 돌려준다 (같은 출처라 손댈 수 있다) */
function blankDoc(frame, css) {
  const doc = frame.contentDocument;
  doc.open();
  doc.write(`<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body></body></html>`);
  doc.close();
  return doc;
}

const BASE_CSS = `
  body { margin: 0; padding: 14px; font: 13px/1.6 -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
         color: #0f172a; background: #fff; }
  h4 { margin: 18px 0 6px; font-size: 12px; color: #64748b; font-weight: 600; }
  h4:first-child { margin-top: 0; }
  table { border-collapse: collapse; font-size: 12px; }
  td, th { border: 1px solid #e2e8f0; padding: 3px 7px; white-space: nowrap; }
  tr:first-child td { background: #f8fafc; font-weight: 600; }
  .sum { margin: 0 0 10px; font-size: 12px; color: #64748b; }
  table.zip { width: 100%; }
  table.zip td { white-space: normal; word-break: break-all; }
  table.zip td.n i { color: #94a3b8; font-style: normal; }
  table.zip td.r { white-space: nowrap; text-align: right; color: #64748b;
                   font-variant-numeric: tabular-nums; width: 1%; }
`;

export default function AttachPreview({ account, folder, uid, att, onClose }) {
  const [url, setUrl] = useState('');       // 이미지·PDF (blob)
  const [html, setHtml] = useState('');     // 한글 문서를 세운 HTML
  const [ready, setReady] = useState(false);  // 엑셀·워드를 다 그렸나
  const [error, setError] = useState('');
  const frameRef = useRef(null);
  const kind = previewKind(att);
  const inFrame = kind === 'excel' || kind === 'word' || kind === 'zip';

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
        const cap = kind === 'zip' ? MAX_ZIP : MAX_RENDER;
        if (inFrame && att.size > cap) {
          throw new Error(`파일이 커서(${formatSize(att.size)}) 화면에서 열지 않습니다. 내려받아 보십시오.`);
        }

        // 한글은 서버가 세워 준 HTML 을 받는다. 나머지는 원본 그대로.
        const url0 = kind === 'hwp'
          ? mailApi.attachmentPreviewUrl({ account, folder, uid, partId: att.part_id })
          : mailApi.attachmentUrl({ account, folder, uid, partId: att.part_id });

        // api 에 blob 을 받는 공개 함수가 아직 없다(openBinary 는 곧바로 내려받는다).
        // _fetch 는 Bearer 와 401 처리를 함께 들고 있으므로 그것을 쓴다.
        const res = await api._fetch(url0);
        if (!res.ok) {
          // 서버가 못 연 이유를 사람 말로 준다 — 그걸 그대로 띄운다
          let msg = `첨부를 열지 못했습니다 (${res.status})`;
          try { msg = (await res.json()).error || msg; } catch { /* JSON 이 아니면 그대로 */ }
          throw new Error(msg);
        }

        if (kind === 'hwp') {
          const text = await res.text();
          if (!alive) return;
          setHtml(text);
          return;
        }

        if (inFrame) {
          const buf = await res.arrayBuffer();
          if (!alive) return;
          const frame = frameRef.current;
          if (!frame) return;
          const doc = blankDoc(frame, BASE_CSS);

          if (kind === 'zip') {
            doc.body.innerHTML = await zipListHtml(buf);
          } else if (kind === 'excel') {
            const XLSX = await import('xlsx');
            const wb = XLSX.read(buf, { type: 'array' });
            if (!alive) return;
            // 시트 탭을 만들려면 스크립트가 필요한데 이 안에서는 안 돈다.
            // 확인용이므로 시트를 이름과 함께 차례로 늘어놓는다.
            doc.body.innerHTML = wb.SheetNames.map((n) => {
              const table = XLSX.utils.sheet_to_html(wb.Sheets[n], { editable: false });
              return `<h4>${n}</h4>${table}`;
            }).join('');
          } else {
            const { renderAsync } = await import('docx-preview');
            await renderAsync(buf, doc.body, doc.head, {
              className: 'docx', inWrapper: true, ignoreLastRenderedPageBreak: true,
            });
          }
          if (alive) setReady(true);
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
  }, [account, folder, uid, att.part_id, att.size, kind, inFrame]);

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

  const waiting = !error && !url && !html && !ready;

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
          {error && <div className="list-state error">{error}</div>}

          {waiting && !error && (
            <div className="list-state">
              {kind === 'hwp' ? '한글 문서를 세우는 중입니다… 잠시만 기다려 주세요.'
                : kind === 'zip' ? '압축파일 안을 들여다보는 중입니다…'
                  : inFrame ? '문서를 여는 중입니다…'
                  : '첨부를 여는 중…'}
            </div>
          )}

          {/* 엑셀·워드는 그리기 전에도 자리가 있어야 한다 — 그 안에 그린다 */}
          {inFrame && !error && (
            <iframe ref={frameRef} className="att-frame" sandbox="allow-same-origin"
              title={att.filename} style={ready ? undefined : { display: 'none' }} />
          )}

          {!inFrame && !error && (
            kind === 'image' ? (url && <img className="att-image" src={url} alt={att.filename} />)
              : kind === 'hwp' ? (
                /* sandbox 를 비워 두면 스크립트도, 바깥으로 나가는 링크도 못 돈다 */
                html && <iframe className="att-frame" srcDoc={html} sandbox="" title={att.filename} />
              )
                : (url && <iframe className="att-frame" src={url} title={att.filename} />)
          )}
        </div>

        <div className="contact-card-foot">
          <button className="set-btn primary" onClick={save}>내려받기</button>
          <button className="btn-cancel" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
