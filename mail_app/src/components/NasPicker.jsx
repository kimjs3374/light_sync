import { useEffect, useMemo, useRef, useState } from 'react';
import { mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { formatSize } from '../lib/format';
import { suspendRouting } from '../lib/route';
import { Close, Refresh, Search as SearchIcon } from './Icons';
import FileIcon, { fileKindLabel } from './FileIcons';

/**
 * 사내 파일서버(NAS)에서 첨부 고르기 — **윈도우 탐색기와 같은 모양**으로.
 *
 * 고른 것은 **경로만** 들고 간다. 파일 내용은 보낼 때 **서버가 사내망에서 직접** 읽는다.
 * 지금까지는 사람이 NAS → PC 로 내려받아 다시 올려, 같은 파일이 사내망을 두 번 건넜다.
 *
 * 탐색기를 흉내 낸 이유는 멋이 아니라 **배울 것이 없어야 해서**다.
 * 왼쪽에 공유폴더, 위에 ← → ↑ 와 주소줄, 가운데에 이름·수정한 날짜·유형·크기 —
 * 매일 보던 자리에 같은 것이 있으면 설명이 필요 없다.
 */

const fmtTime = (mtime) => {
  if (!mtime) return '';
  const d = new Date(Number(mtime) * 1000);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export default function NasPicker({ onClose }) {
  /* 다녀온 길 — 뒤로/앞으로가 있어야 폴더를 잘못 열었을 때 처음부터 다시 찾지 않는다 */
  const [hist, setHist] = useState(['']);
  const [idx, setIdx] = useState(0);
  const path = hist[idx];

  const [shares, setShares] = useState([]);      // 왼쪽 칸
  const [items, setItems] = useState(null);      // 지금 폴더 내용
  const [error, setError] = useState('');
  const [picked, setPicked] = useState([]);
  const [filter, setFilter] = useState('');      // 이 폴더 안에서 이름 걸러보기
  const [sort, setSort] = useState({ by: 'name', dir: 1 });
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  const canBack = idx > 0;
  const canFwd = idx < hist.length - 1;
  const parent = path ? (path.split('/').slice(0, -1).join('/') || '') : null;

  const go = (p) => {
    if (p === path) return;
    setHist((h) => [...h.slice(0, idx + 1), p]);
    setIdx((i) => i + 1);
    setFilter('');
  };
  const back = () => canBack && setIdx((i) => i - 1);
  const fwd = () => canFwd && setIdx((i) => i + 1);
  const up = () => parent !== null && go(parent);

  /* 마우스 옆버튼은 크롬이 먼저 처리해서 preventDefault 로 못 막는다(실제로 눌러 보니
     메일 화면째 뒤로 갔다). 막는 대신 **받아쓴다** — 창이 열릴 때 주소는 그대로 둔 채
     기록 한 칸을 쌓아 두고, 뒤로가기 신호가 오면 '한 폴더 뒤로' 로 쓴다.
     같은 신호를 lib/route.js 가 받으면 쓰던 메일을 닫아 버리므로 잠깐 재워 둔다. */
  const idxRef = useRef(0);
  const pushedRef = useRef(false);
  useEffect(() => { idxRef.current = idx; }, [idx]);

  useEffect(() => {
    const resume = suspendRouting();
    window.history.pushState({ nasPicker: true }, '', window.location.href);
    pushedRef.current = true;

    const onPop = () => {
      if (idxRef.current > 0) {
        setIdx((i) => i - 1);
        window.history.pushState({ nasPicker: true }, '', window.location.href);
      } else {
        pushedRef.current = false;
        onClose();
      }
    };
    window.addEventListener('popstate', onPop);

    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      const typing = ['INPUT', 'TEXTAREA'].includes((e.target.tagName || '').toUpperCase());
      if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); back(); }
      else if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); fwd(); }
      else if (e.key === 'Backspace' && !typing) { e.preventDefault(); up(); }
    };
    document.addEventListener('keydown', onKey);

    return () => {
      window.removeEventListener('popstate', onPop);
      document.removeEventListener('keydown', onKey);
      if (pushedRef.current) {
        window.history.back();
        // back() 이 만드는 신호는 다음 차례에 온다 — 0ms 로 풀면 라우터가 그걸 받는다
        setTimeout(resume, 150);
      } else { resume(); }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 왼쪽 칸(공유폴더)은 한 번만 읽는다
  useEffect(() => {
    mailApi.nasList('')
      .then((r) => { if (!r.error) setShares(r.items || []); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    setItems(null); setError('');
    mailApi.nasList(path)
      .then((r) => { if (alive) { if (r.error) setError(r.error); else setItems(r.items || []); } })
      .catch((e) => { if (alive) setError(e.message || '파일서버를 읽지 못했습니다'); });
    return () => { alive = false; };
  }, [path, reload]);

  const has = (p) => picked.some((x) => x.path === p);
  const toggle = (it) => setPicked((prev) => (has(it.path)
    ? prev.filter((x) => x.path !== it.path)
    : [...prev, { path: it.path, name: it.name, size: it.size }]));

  /** 붙여넣은 경로는 서버가 확인해 준 것만 담는다 */
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
    } catch (e) { setError(e.message || '경로를 확인하지 못했습니다'); }
    finally { setBusy(false); }
  };

  const attach = () => {
    if (!picked.length) return;
    useCompose.getState().addNasFiles(picked);
    onClose();
  };

  /* 정렬 — 폴더가 늘 먼저다(탐색기와 같다). 그 다음 고른 칸으로 줄 세운다 */
  const rows = useMemo(() => {
    if (!items) return null;
    const q = filter.trim().toLowerCase();
    const out = q ? items.filter((i) => i.name.toLowerCase().includes(q)) : [...items];
    const key = {
      name: (x) => x.name.toLowerCase(),
      time: (x) => Number(x.mtime) || 0,
      size: (x) => Number(x.size) || 0,
      kind: (x) => fileKindLabel(x.name, x.is_dir),
    }[sort.by];
    out.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      const ka = key(a);
      const kb = key(b);
      if (ka < kb) return -1 * sort.dir;
      if (ka > kb) return 1 * sort.dir;
      return 0;
    });
    return out;
  }, [items, filter, sort]);

  const sortBy = (by) => setSort((s) => (s.by === by ? { by, dir: -s.dir } : { by, dir: 1 }));
  const arrow = (by) => (sort.by === by ? (sort.dir > 0 ? ' ▲' : ' ▼') : '');
  const crumbs = path ? path.split('/').filter(Boolean) : [];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="exp" onClick={(e) => e.stopPropagation()} role="dialog"
        aria-label="파일서버에서 첨부">
        <div className="exp-title">
          <h3>파일서버에서 첨부</h3>
          <button className="icon-btn" title="닫기" onClick={onClose}><Close /></button>
        </div>

        {/* 위 줄 — 탐색기와 같은 자리에 같은 것 */}
        <div className="exp-tools">
          <button className="exp-nav" onClick={back} disabled={!canBack}
            title="뒤로 (Alt+←, 마우스 옆버튼)">←</button>
          <button className="exp-nav" onClick={fwd} disabled={!canFwd} title="앞으로 (Alt+→)">→</button>
          <button className="exp-nav" onClick={up} disabled={parent === null}
            title="위 폴더로 (Backspace)">↑</button>

          <div className="exp-addr">
            <button className="exp-crumb" onClick={() => go('')}>파일서버</button>
            {crumbs.map((c, i) => (
              <span key={i} className="exp-crumb-wrap">
                <span className="exp-arrow">›</span>
                <button className="exp-crumb"
                  onClick={() => go('/' + crumbs.slice(0, i + 1).join('/'))}>{c}</button>
              </span>
            ))}
          </div>

          <div className="exp-find">
            <SearchIcon size={13} />
            <input value={filter} onChange={(e) => setFilter(e.target.value)}
              placeholder="이 폴더에서 찾기" />
          </div>
          <button className="exp-nav" onClick={() => setReload((n) => n + 1)} title="새로고침">
            <Refresh size={13} />
          </button>
          <button className={`set-btn${pasteOpen ? ' primary' : ''}`}
            onClick={() => setPasteOpen((v) => !v)}>경로 붙여넣기</button>
        </div>

        {pasteOpen && (
          <div className="exp-paste">
            <p className="set-note">
              탐색기에서 파일을 <b>Shift+우클릭 → 「경로로 복사」</b> 한 뒤 붙여넣어 주세요.
              여러 개면 한 줄에 하나씩. <b>왼쪽 목록에 없는 폴더도 경로로는 붙습니다.</b>
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

        <div className="exp-body">
          {/* 왼쪽 — 공유폴더 */}
          <nav className="exp-side">
            <div className="exp-side-title">파일서버</div>
            {shares.map((s) => (
              <button key={s.path}
                className={`exp-side-item${path.startsWith(s.path) ? ' on' : ''}`}
                onClick={() => go(s.path)} title={s.name}>
                <FileIcon isDir size={15} />
                <span>{s.name}</span>
              </button>
            ))}
          </nav>

          {/* 오른쪽 — 자세히 보기 */}
          <div className="exp-main">
            {error && <div className="exp-error">{error}</div>}
            <table className="exp-table">
              <thead>
                <tr>
                  <th className="exp-c-pick"></th>
                  <th className="exp-c-name" onClick={() => sortBy('name')}>이름{arrow('name')}</th>
                  <th className="exp-c-time" onClick={() => sortBy('time')}>수정한 날짜{arrow('time')}</th>
                  <th className="exp-c-kind" onClick={() => sortBy('kind')}>유형{arrow('kind')}</th>
                  <th className="exp-c-size" onClick={() => sortBy('size')}>크기{arrow('size')}</th>
                </tr>
              </thead>
              <tbody>
                {rows === null ? (
                  <tr><td colSpan={5} className="exp-empty">불러오는 중…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={5} className="exp-empty">
                    {filter ? `'${filter}' 에 맞는 것이 없습니다` : '비어 있는 폴더입니다'}
                  </td></tr>
                ) : rows.map((it) => (
                  <tr key={it.path} className={has(it.path) ? 'on' : ''}
                    onDoubleClick={() => it.is_dir && go(it.path)}
                    onClick={() => (it.is_dir ? go(it.path) : toggle(it))}>
                    <td className="exp-c-pick">
                      {it.is_dir ? null
                        : <input type="checkbox" checked={has(it.path)} readOnly />}
                    </td>
                    <td className="exp-c-name" title={it.name}>
                      <FileIcon name={it.name} isDir={it.is_dir} />
                      <span className="exp-name">{it.name}</span>
                    </td>
                    <td className="exp-c-time">{fmtTime(it.mtime)}</td>
                    <td className="exp-c-kind">{fileKindLabel(it.name, it.is_dir)}</td>
                    <td className="exp-c-size">{it.is_dir ? '' : formatSize(it.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 고른 것은 늘 보인다 — 폴더를 옮겨 다녀도 무엇을 담았는지 안 잊는다 */}
        <div className="exp-picked">
          {picked.length === 0
            ? <span className="picked-none">붙일 파일을 고르세요 · 폴더는 눌러서 들어갑니다</span>
            : picked.map((f) => (
              <span key={f.path} className="addr-tag" title={f.path}>
                <FileIcon name={f.name} size={13} />
                {f.name}{f.size > 0 && <em>{formatSize(f.size)}</em>}
                <button className="addr-tag-x" aria-label="빼기"
                  onClick={() => setPicked((prev) => prev.filter((x) => x.path !== f.path))}>✕</button>
              </span>
            ))}
        </div>

        <div className="exp-foot">
          <span className="exp-count">
            {rows ? `${rows.filter((r) => !r.is_dir).length}개 파일 · 폴더 ${rows.filter((r) => r.is_dir).length}개` : ''}
          </span>
          <button className="btn-send" disabled={!picked.length} onClick={attach}>
            {picked.length ? `${picked.length}개 첨부` : '첨부'}
          </button>
          <button className="btn-cancel" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
