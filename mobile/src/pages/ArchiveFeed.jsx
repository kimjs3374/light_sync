import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Avatar, PostBody, ImageGrid, FileList, wbImages, wbFiles, useLightbox } from '../components/ArchiveKit';

function Comment({ c, openLb }) {
  const imgs = wbImages(c.attachments);
  return (
    <div className="arc-comment">
      <Avatar name={c.author} size="sm" />
      <div className="arc-comment-body">
        <div className="arc-comment-meta">
          <span className="arc-author" style={{ fontSize: 12 }}>{c.author}</span>
          <span className="arc-date">· {c.created_fmt}</span>
        </div>
        <PostBody html={c.body_html} className="arc-comment-text" />
        <ImageGrid images={imgs} onOpen={openLb} />
        <FileList files={wbFiles(c.attachments)} />
      </div>
    </div>
  );
}

function PostCard({ post, slug, openLb }) {
  const navigate = useNavigate();
  const imgs = wbImages(post.attachments);
  const files = wbFiles(post.attachments);
  const comments = post.comments || [];
  const shown = comments.slice(0, 2);
  const rest = comments.length - shown.length;

  return (
    <div className="arc-post">
      <div className="arc-head">
        <Avatar name={post.author} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div>
            {post.is_notice && <span className="arc-notice">공지</span>}
            <span className="arc-author">{post.author}</span>
            {post.is_updated && <span className="arc-edited">수정됨</span>}
          </div>
          <div className="arc-date">{post.created_fmt}</div>
        </div>
      </div>

      <PostBody html={post.body_html} />
      <ImageGrid images={imgs} onOpen={openLb} />
      <FileList files={files} />

      {post.contract_id && (
        <div className="arc-link" onClick={() => navigate(`/contracts/${post.contract_id}`)}>
          🔗 {post.contract_name || '연결된 현장 보기'}
        </div>
      )}

      {shown.map((c) => <Comment key={c.id} c={c} openLb={openLb} />)}
      {rest > 0 && (
        <div className="arc-more-comments" onClick={() => navigate(`/archive/${slug}/${post.id}`)}>
          댓글 {rest}개 더보기 →
        </div>
      )}
      {comments.length > 0 && rest <= 0 && (
        <div className="arc-foot">💬 댓글 {comments.length}</div>
      )}
    </div>
  );
}

export default function ArchiveFeed() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [openLb, lbNode] = useLightbox();

  const [label, setLabel] = useState('');
  const [posts, setPosts] = useState([]);
  const [authors, setAuthors] = useState([]);
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [author, setAuthor] = useState('');
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const fetchPage = useCallback((pg, replace) => {
    const params = new URLSearchParams({ page: String(pg) });
    if (q) params.set('q', q);
    if (author) params.set('author', author);
    (pg === 1 ? setLoading : setLoadingMore)(true);
    api.get(`/archive/board/${slug}?${params.toString()}`)
      .then((d) => {
        setLabel(d.board?.label || '');
        setAuthors(d.authors || []);
        setTotal(d.total || 0);
        setHasMore(d.has_more);
        setPage(d.page);
        setPosts((prev) => (replace ? d.posts : [...prev, ...(d.posts || [])]));
      })
      .catch(() => {})
      .finally(() => { setLoading(false); setLoadingMore(false); });
  }, [slug, q, author]);

  // slug/검색/작성자 변경 → 1페이지부터 다시
  useEffect(() => { fetchPage(1, true); }, [fetchPage]);

  // 검색어 디바운스
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(t);
  }, [qInput]);

  return (
    <div>
      <div className="channel-header">
        <button onClick={() => navigate('/archive')} style={{ background: 'none', color: 'var(--text-bright)', fontSize: 20, cursor: 'pointer' }}>←</button>
        <h1>{label || '워크보드'}</h1>
        <span className="ch-count">{total.toLocaleString()}</span>
      </div>

      <div className="search-bar">
        <input type="text" placeholder="키워드 검색..." value={qInput}
          onChange={(e) => setQInput(e.target.value)} />
      </div>
      <div className="arc-filter-bar">
        <select value={author} onChange={(e) => setAuthor(e.target.value)}>
          <option value="">전체 작성자</option>
          {authors.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="page-loader">불러오는 중...</div>
      ) : posts.length === 0 ? (
        <div className="page-empty">게시글이 없습니다</div>
      ) : (
        <div className="arc-feed">
          {posts.map((p) => <PostCard key={p.id} post={p} slug={slug} openLb={openLb} />)}
          {hasMore && (
            <button className="arc-loadmore" disabled={loadingMore}
              onClick={() => fetchPage(page + 1, false)}>
              {loadingMore ? '불러오는 중...' : '이전 글 더보기'}
            </button>
          )}
        </div>
      )}
      {lbNode}
    </div>
  );
}
