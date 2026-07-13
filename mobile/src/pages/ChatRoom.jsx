import { useState, useEffect, useRef, useLayoutEffect, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { Avatar, PostBody, ImageGrid, FileList, chatImages, useLightbox, authed } from '../components/ArchiveKit';

function MsgRow({ m, openLb, onMediaLoad }) {
  const imgs = chatImages(m.images);
  const files = (m.files || []).map((f) => ({ url: f.url, name: f.name, size: f.size }));
  return (
    <div id={`m${m.id}`} className={`chat-row chat-msg${m.grouped ? ' grouped' : ''}${m.is_reply ? ' reply' : ''}`}>
      {m.grouped ? <div style={{ width: 34, flexShrink: 0 }} /> : <Avatar name={m.user_name} />}
      <div className="chat-col">
        {!m.grouped && <div className="chat-name">{m.user_name}</div>}
        <div className="chat-bubble-wrap">
          {m.body ? <PostBody html={m.body} className="chat-bubble" /> : null}
          <span className="chat-time">{m.time}</span>
        </div>
        {imgs.length > 0 && <div className="chat-media"><ImageGrid images={imgs} onOpen={openLb} onImgLoad={onMediaLoad} /></div>}
        {(m.videos || []).map((v, i) => (
          <video key={i} className="chat-media" controls src={authed(v.url)} onLoadedMetadata={onMediaLoad} style={{ maxWidth: '100%', borderRadius: 8, marginTop: 4 }} />
        ))}
        {files.length > 0 && <div className="chat-media"><FileList files={files} /></div>}
      </div>
    </div>
  );
}

export default function ChatRoom() {
  const { convId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [openLb, lbNode] = useLightbox();
  const scrollRef = useRef(null);
  const anchorRef = useRef(null); // {prevHeight} for prepend scroll preservation
  const loadingRef = useRef(false); // 동시 로드 방지 (스크롤 연속 발생 대비)
  const atBottomRef = useRef(true); // 최신(바닥) 고정 여부 — 초기 이미지 로드 중 흔들림 방지

  const [room, setRoom] = useState(null);
  const [items, setItems] = useState([]);
  const [oldest, setOldest] = useState(1);
  const [newest, setNewest] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [searchMode, setSearchMode] = useState(false);
  const [q, setQ] = useState('');
  const [results, setResults] = useState(null);
  const [jumpId, setJumpId] = useState(searchParams.get('jump') || null);

  // ── 초기/점프 로드 ──
  const loadRoom = useCallback((jump) => {
    setLoading(true);
    const qs = jump ? `?jump=${jump}` : '';
    api.get(`/chat-archive/${convId}${qs}`)
      .then((d) => {
        setRoom(d.room);
        setItems(d.items || []);
        setOldest(d.page);
        setNewest(d.page);
        setTotalPages(d.total_pages);
        anchorRef.current = { scrollTo: jump ? `m${jump}` : 'bottom' };
      })
      .catch(() => {}).finally(() => setLoading(false));
  }, [convId]);

  useEffect(() => { loadRoom(jumpId); /* eslint-disable-next-line */ }, [convId]);

  // 초기/점프 후 스크롤 위치 지정
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !anchorRef.current) return;
    const a = anchorRef.current;
    if (a.scrollTo === 'bottom') {
      el.scrollTop = el.scrollHeight;
      atBottomRef.current = true;
      anchorRef.current = null;
    } else if (a.scrollTo && a.scrollTo.startsWith('m')) {
      atBottomRef.current = false;
      const target = document.getElementById(a.scrollTo);
      if (target) {
        target.scrollIntoView({ block: 'center' });
        target.classList.add('chat-jumped');
      }
      anchorRef.current = null;
    } else if (a.prevHeight != null) {
      // 위쪽 prepend: 스크롤 위치 보존
      el.scrollTop = el.scrollHeight - a.prevHeight + (a.prevTop || 0);
      anchorRef.current = null;
    }
  }, [items]);

  // 위로 스크롤 → 이전(오래된) 페이지 prepend
  const loadOlder = useCallback(() => {
    if (loadingRef.current || oldest <= 1) return;
    loadingRef.current = true; setBusy(true);
    const el = scrollRef.current;
    anchorRef.current = { prevHeight: el.scrollHeight, prevTop: el.scrollTop };
    api.get(`/chat-archive/${convId}/messages?page=${oldest - 1}`)
      .then((d) => {
        setItems((prev) => [...(d.items || []), ...prev]);
        setOldest(d.page);
      })
      .catch(() => { anchorRef.current = null; })
      .finally(() => { loadingRef.current = false; setBusy(false); });
  }, [oldest, convId]);

  // 아래로 스크롤 → 다음(최신) 페이지 append (점프 이후에만 의미)
  const loadNewer = useCallback(() => {
    if (loadingRef.current || newest >= totalPages) return;
    loadingRef.current = true; setBusy(true);
    api.get(`/chat-archive/${convId}/messages?page=${newest + 1}`)
      .then((d) => {
        setItems((prev) => [...prev, ...(d.items || [])]);
        setNewest(d.page);
      })
      .catch(() => {}).finally(() => { loadingRef.current = false; setBusy(false); });
  }, [newest, totalPages, convId]);

  const onScroll = (e) => {
    const el = e.currentTarget;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    if (el.scrollTop < 120) loadOlder();
    else if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) loadNewer();
  };

  // 초기/점프 로드 중 이미지가 뒤늦게 로드되면 바닥(최신) 고정 유지 → 흔들림 방지
  const onMediaLoad = useCallback(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, []);

  // 검색
  useEffect(() => {
    if (!searchMode) return;
    const t = setTimeout(() => {
      const term = q.trim();
      if (!term) { setResults(null); return; }
      api.get(`/chat-archive/${convId}/search?q=${encodeURIComponent(term)}`)
        .then((d) => setResults(d.results || []))
        .catch(() => setResults([]));
    }, 350);
    return () => clearTimeout(t);
  }, [q, searchMode, convId]);

  const doJump = (msgId) => {
    setSearchMode(false); setResults(null); setQ('');
    setJumpId(msgId);
    loadRoom(msgId);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh' }}>
      <div className="channel-header">
        <button onClick={() => navigate('/chat-archive')} style={{ background: 'none', color: 'var(--text-bright)', fontSize: 20, cursor: 'pointer' }}>←</button>
        <h1 style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{room?.name || '대화방'}</h1>
        <button onClick={() => { setSearchMode((v) => !v); setResults(null); setQ(''); }}
          style={{ background: 'none', color: searchMode ? 'var(--accent)' : 'var(--text-muted)', fontSize: 18, cursor: 'pointer' }}>🔍</button>
      </div>

      {searchMode && (
        <div className="search-bar">
          <input autoFocus type="text" placeholder="대화 내용 검색..." value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      )}

      {searchMode && results !== null ? (
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {results.length === 0 ? (
            <div className="page-empty">검색 결과가 없습니다</div>
          ) : results.map((r) => (
            <div key={r.id} className="chat-search-result" onClick={() => doJump(r.id)}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span className="arc-author" style={{ fontSize: 12 }}>{r.user_name}</span>
                <span className="arc-date">{r.when}</span>
              </div>
              <div className="arc-comment-text">{r.snippet}</div>
            </div>
          ))}
        </div>
      ) : loading ? (
        <div className="page-loader">불러오는 중...</div>
      ) : (
        <div ref={scrollRef} className="chat-feed" style={{ flex: 1, overflowY: 'auto', minHeight: 0 }} onScroll={onScroll}>
          {busy && oldest > 1 && <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 12, padding: 6 }}>이전 대화 불러오는 중...</div>}
          {items.map((it, i) => {
            if (it.kind === 'date') return <div key={`d${i}`} className="chat-date"><span>{it.date}</span></div>;
            if (it.kind === 'system') return <div key={`s${i}`} className="chat-system">{it.text}</div>;
            return <MsgRow key={it.id} m={it} openLb={openLb} onMediaLoad={onMediaLoad} />;
          })}
        </div>
      )}
      {lbNode}
    </div>
  );
}
