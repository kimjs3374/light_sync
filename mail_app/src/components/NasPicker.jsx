import { useEffect, useState } from 'react';
import { mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';
import { Close } from './Icons';

/**
 * 사내 파일서버(NAS)에서 첨부 고르기.
 *
 * 고른 것은 **경로만** 들고 간다. 파일 내용은 보낼 때 **서버가 사내망에서 직접** 읽는다.
 * 지금까지는 사람이 NAS → PC 로 내려받아 다시 올려서, 같은 파일이 사내망을 두 번 건넜다.
 *
 * 붙이는 문이 둘이다:
 *  ① 폴더를 눌러 다니며 고르기
 *  ② 탐색기에서 「경로로 복사」 한 것을 붙여넣기
 *     (브라우저는 고른 파일의 경로를 안 알려준다 — C:\fakepath 로만 준다.
 *      그래서 "PC에서 첨부하면 경로를 보고 판단" 은 브라우저 안에서 불가능하다)
 */
export default function NasPicker({ onClose }) {
  const [path, setPath] = useState('');          // '' 면 공유폴더 목록
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState([]);      // [{path,name,size}]
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let alive = true;
    setItems(null); setError('');
    mailApi.nasList(path)
      .then((r) => { if (alive) { if (r.error) setError(r.error); else setItems(r.items || []); } })
      .catch((e) => { if (alive) setError(e.message || '파일서버를 읽지 못했습니다'); });
    return () => { alive = false; };
  }, [path]);

  const has = (p) => picked.some((x) => x.path === p);
  const toggle = (it) => setPicked((prev) => (has(it.path)
    ? prev.filter((x) => x.path !== it.path)
    : [...prev, { path: it.path, name: it.name, size: it.size }]));

  /** 붙여넣은 경로를 서버가 확인해 준 것만 담는다 */
  const addPasted = async () => {
    const lines = pasteText.split('\n').map((x) => x.trim()).filter(Boolean);
    if (!lines.length) return;
    setBusy(true); setError('');
    try {
      const r = await mailApi.nasResolve(lines);
      if (r.error) throw new Error(r.error);
      setPicked((prev) => {
        const next = [...prev];
        for (const f of r.files || []) if (!next.some((x) => x.path === f.path)) next.push(f);
        return next;
      });
      if (r.errors?.length) setError(r.errors.join('\n'));
      else { setPasteText(''); setPasteOpen(false); }
    } catch (e) {
      setError(e.message || '경로를 확인하지 못했습니다');
    } finally { setBusy(false); }
  };

  const attach = () => {
    if (!picked.length) return;
    useCompose.getState().addNasFiles(picked);
    onClose();
  };

  // 빵부스러기 — 지금 어디에 있는지가 늘 보여야 위로 올라갈 수 있다
  const crumbs = path ? path.split('/').filter(Boolean) : [];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="contact-card wide nas-card" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label="파일서버에서 첨부">
        <div className="contact-card-head">
          <h3>파일서버에서 첨부</h3>
          <button className="icon-btn" title="닫기" onClick={onClose}><Close /></button>
        </div>

        <div className="nas-bar">
          <button className="nas-crumb" onClick={() => setPath('')}>파일서버</button>
          {crumbs.map((c, i) => (
            <span key={i}>
              <span className="nas-sep">/</span>
              <button className="nas-crumb"
                onClick={() => setPath('/' + crumbs.slice(0, i + 1).join('/'))}>{c}</button>
            </span>
          ))}
          <button className="set-btn nas-paste-btn" onClick={() => setPasteOpen((v) => !v)}>
            경로 붙여넣기
          </button>
        </div>

        {pasteOpen && (
          <div className="nas-paste">
            <p className="set-note">
              탐색기에서 파일을 <b>Shift+우클릭 → 「경로로 복사」</b> 한 뒤 붙여넣어 주세요.
              여러 개면 한 줄에 하나씩. <b>목록에 없는 폴더도 경로로는 붙습니다.</b>
              <br />
              예: {'\\\\magnatech\\현장관리\\2026\\견적.xlsx'}
            </p>
            <textarea className="set-input wide" rows={3} value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              placeholder={'\\\\magnatech\\현장관리\\...'} />
            <div className="set-foot">
              <button className="set-btn primary" onClick={addPasted} disabled={busy}>
                {busy ? '확인 중…' : '확인해서 담기'}
              </button>
            </div>
          </div>
        )}

        <div className="nas-list">
          {error && <div className="list-state error nas-error">{error}</div>}
          {items === null ? <div className="list-state">불러오는 중…</div>
            : items.length === 0 ? <div className="list-state">비어 있는 폴더입니다.</div>
              : (
                <table className="contact-table">
                  <tbody>
                    {items.map((it) => (
                      <tr key={it.path}
                        className={has(it.path) ? 'picked' : ''}
                        onClick={() => (it.is_dir ? setPath(it.path) : toggle(it))}>
                        <td className="col-pick">
                          {it.is_dir ? <span className="nas-folder">📁</span>
                            : <input type="checkbox" checked={has(it.path)} readOnly />}
                        </td>
                        <td title={it.name}>{it.name}</td>
                        <td className="col-count">{it.is_dir ? '' : formatSize(it.size)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
        </div>

        {/* 고른 것은 늘 보인다 — 폴더를 옮겨 다녀도 무엇을 담았는지 안 잊는다 */}
        <div className="picker-picked">
          {picked.length === 0
            ? <span className="picked-none">붙일 파일을 고르세요</span>
            : picked.map((f) => (
              <span key={f.path} className="addr-tag" title={f.path}>
                {f.name} <em>{formatSize(f.size)}</em>
                <button className="addr-tag-x" aria-label="빼기"
                  onClick={() => setPicked((prev) => prev.filter((x) => x.path !== f.path))}>✕</button>
              </span>
            ))}
        </div>

        <div className="contact-card-foot">
          <button className="btn-send" disabled={!picked.length} onClick={attach}>
            {picked.length ? `${picked.length}개 첨부` : '첨부'}
          </button>
          <button className="btn-cancel" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
