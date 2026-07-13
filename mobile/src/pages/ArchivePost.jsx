import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Avatar, PostBody, ImageGrid, FileList, wbImages, wbFiles, useLightbox } from '../components/ArchiveKit';

function Comment({ c, openLb }) {
  return (
    <div className="arc-comment">
      <Avatar name={c.author} size="sm" />
      <div className="arc-comment-body">
        <div className="arc-comment-meta">
          <span className="arc-author" style={{ fontSize: 12 }}>{c.author}</span>
          <span className="arc-date">· {c.created_fmt}</span>
        </div>
        <PostBody html={c.body_html} className="arc-comment-text" />
        <ImageGrid images={wbImages(c.attachments)} onOpen={openLb} />
        <FileList files={wbFiles(c.attachments)} />
      </div>
    </div>
  );
}

export default function ArchivePost() {
  const { slug, id } = useParams();
  const navigate = useNavigate();
  const [openLb, lbNode] = useLightbox();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get(`/archive/board/${slug}/${id}`)
      .then((d) => setData(d))
      .catch(() => {}).finally(() => setLoading(false));
  }, [slug, id]);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data?.post) return <div className="page-empty">게시글을 찾을 수 없습니다</div>;

  const post = data.post;
  const comments = post.comments || [];

  return (
    <div>
      <div className="channel-header">
        <button onClick={() => navigate(`/archive/${slug}`)} style={{ background: 'none', color: 'var(--text-bright)', fontSize: 20, cursor: 'pointer' }}>←</button>
        <h1>{data.board?.label || '게시글'}</h1>
      </div>

      <div className="arc-feed">
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
          <ImageGrid images={wbImages(post.attachments)} onOpen={openLb} />
          <FileList files={wbFiles(post.attachments)} />

          {post.contract_id && (
            <div className="arc-link" onClick={() => navigate(`/contracts/${post.contract_id}`)}>
              🔗 {post.contract_name || '연결된 현장 보기'}
            </div>
          )}

          {comments.length > 0 && (
            <div className="arc-comments">
              <div className="arc-foot" style={{ marginTop: 0, marginBottom: 4 }}>💬 댓글 {comments.length}</div>
              {comments.map((c) => <Comment key={c.id} c={c} openLb={openLb} />)}
            </div>
          )}
        </div>
      </div>
      {lbNode}
    </div>
  );
}
