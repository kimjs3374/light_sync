import { useEffect, useRef, useState } from 'react';
import { mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';
import { suspendRouting } from '../lib/route';
import { Close, Folder } from './Icons';

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
  /* 탐색기처럼 다녀온 길을 들고 있는다 — 뒤로/앞으로가 있어야 폴더를 잘못 열었을 때
     처음부터 다시 찾아 들어가지 않는다. 브라우저 뒤로가기는 쓰지 않는다:
     그건 메일 화면 자체를 떠나 버려서, 쓰던 메일이 사라진 것처럼 보인다. */
  const [hist, setHist] = useState(['']);        // 다녀온 경로들 ('' = 공유폴더 목록)
  const [idx, setIdx] = useState(0);
  const path = hist[idx];
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState([]);      // [{path,name,size}]
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const [busy, setBusy] = useState(false);

  const canBack = idx > 0;
  const canFwd = idx < hist.length - 1;
  const parent = path ? (path.split('/').slice(0, -1).join('/') || '') : null;

  /** 새 폴더로 — 앞으로 갈 길은 여기서 끊긴다(탐색기와 같다) */
  const go = (p) => {
    if (p === path) return;
    setHist((h) => [...h.slice(0, idx + 1), p]);
    setIdx((i) => i + 1);
  };
  const back = () => canBack && setIdx((i) => i - 1);
  const fwd = () => canFwd && setIdx((i) => i + 1);
  const up = () => parent !== null && go(parent);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      // 경로를 적는 칸에서는 글자를 지우는 일이 먼저다
      const typing = ['INPUT', 'TEXTAREA'].includes((e.target.tagName || '').toUpperCase());
      if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); back(); }
      else if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); fwd(); }
      else if (e.key === 'Backspace' && !typing) { e.preventDefault(); up(); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose, idx, hist, path]);

  /**
   * 마우스 옆버튼(뒤로)을 **막지 않고 받아쓴다.**
   *
   * 크롬은 옆버튼을 브라우저가 먼저 처리해서 `preventDefault` 로 막히지 않는다
   * (실제로 눌러 보니 메일 화면째 뒤로 가 버렸다). 그래서 막는 대신,
   * 창이 열릴 때 **주소는 그대로 둔 채 기록 한 칸을 쌓아** 두고,
   * 뒤로가기 신호가 오면 그걸 창 안의 '한 폴더 뒤로' 로 돌려쓴다.
   * 더 뒤로 갈 곳이 없으면 창을 닫는다 — 그게 사람이 기대하는 다음 단계다.
   *
   * 주소(해시)는 바뀌지 않으므로 메일 화면은 그대로 있는다.
   */
  const idxRef = useRef(0);
  const pushedRef = useRef(false);
  useEffect(() => { idxRef.current = idx; }, [idx]);

  useEffect(() => {
    // 뒤로가기를 이 창이 가져다 쓴다 — 라우터가 같이 받아 작성창을 닫으면 안 된다
    const resume = suspendRouting();
    window.history.pushState({ nasPicker: true }, '', window.location.href);
    pushedRef.current = true;

    const onPop = () => {
      if (idxRef.current > 0) {
        setIdx((i) => i - 1);
        // 다시 한 칸 쌓아 둬야 다음 뒤로가기도 창 안에서 받는다
        window.history.pushState({ nasPicker: true }, '', window.location.href);
      } else {
        pushedRef.current = false;   // 이미 소진됐다
        onClose();
      }
    };
    window.addEventListener('popstate', onPop);
    return () => {
      window.removeEventListener('popstate', onPop);
      // 닫기 버튼으로 닫았으면 쌓아 둔 칸이 남는다 — 치워야 뒤로가기가 헛돌지 않는다.
      // 그 back() 이 만드는 신호까지 라우터가 안 보도록, 치운 **뒤에** 풀어 준다.
      if (pushedRef.current) {
        window.history.back();
        /* back() 이 만드는 popstate 는 **다음 차례**에 온다. 0ms 로 풀면 라우터가
           그 신호를 받아 작성 중인 메일을 닫아 버린다. 넉넉히 지나고 푼다. */
        setTimeout(resume, 150);
      } else {
        resume();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          <button className="nas-nav" onClick={back} disabled={!canBack}
            title="뒤로 (Alt+←, 마우스 옆버튼)">←</button>
          <button className="nas-nav" onClick={fwd} disabled={!canFwd}
            title="앞으로 (Alt+→)">→</button>
          <button className="nas-nav" onClick={up} disabled={parent === null}
            title="위 폴더로 (Backspace)">↑</button>
          <span className="nas-sep" />
          <button className="nas-crumb" onClick={() => go('')}>파일서버</button>
          {crumbs.map((c, i) => (
            <span key={i}>
              <span className="nas-sep">/</span>
              <button className="nas-crumb"
                onClick={() => go('/' + crumbs.slice(0, i + 1).join('/'))}>{c}</button>
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
                        onClick={() => (it.is_dir ? go(it.path) : toggle(it))}>
                        <td className="col-pick">
                          {it.is_dir ? <span className="nas-folder"><Folder /></span>
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
