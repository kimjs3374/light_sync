import { useState, useEffect } from 'react';
import { api } from '../api/client';

const s = { inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 } };

export default function ReceivingPhotos() {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewImg, setViewImg] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ content: '', vendor_name: '', po_no: '' });
  const [files, setFiles] = useState([]);
  const [posting, setPosting] = useState(false);

  const load = () => {
    api.get('/receiving-photos').then(d => setPosts(d.receiving_photos || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const handlePost = async () => {
    if (!form.content.trim()) return alert('내용을 입력해주세요');
    setPosting(true);
    try {
      const fd = new FormData();
      fd.append('content', form.content);
      fd.append('vendor_name', form.vendor_name);
      fd.append('po_no', form.po_no);
      files.forEach(f => fd.append('photos', f));
      const token = localStorage.getItem('token');
      const res = await fetch('/api/app/receiving-photos/create', {
        method: 'POST', headers: { 'Authorization': `Bearer ${token}` }, body: fd,
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || '등록 실패');
      setShowForm(false);
      setForm({ content: '', vendor_name: '', po_no: '' });
      setFiles([]);
      load();
    } catch (e) { alert(e.message); }
    setPosting(false);
  };

  const token = localStorage.getItem('token');
  const imgUrl = (path, thumb) => `/api/app/receiving-photos/view?_t=${token}&path=${encodeURIComponent(path)}${thumb ? '&thumb=1' : ''}`;

  return (
    <div>
      {/* 전체화면 뷰어 */}
      {viewImg && (
        <div onClick={() => setViewImg(null)} style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 200,
          background: 'rgba(0,0,0,0.9)', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <img src={imgUrl(viewImg.file_path, false)} alt={viewImg.file_name}
            style={{ maxWidth: '100%', maxHeight: '70vh', borderRadius: 8, objectFit: 'contain' }}
            onClick={e => e.stopPropagation()} />
          <div style={{ color: '#fff', marginTop: 12, fontSize: 13 }}>{viewImg.file_name}</div>
          <button onClick={() => setViewImg(null)} style={{ marginTop: 12, padding: '10px 24px', borderRadius: 6, border: 'none', background: 'var(--surface)', color: '#fff', fontSize: 14, cursor: 'pointer' }}>닫기</button>
        </div>
      )}

      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>입고사진</h1>
        <span className="ch-count">{posts.length}</span>
      </div>

      {/* 글쓰기 */}
      <div style={{ padding: '8px 16px' }}>
        {showForm ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--surface)', borderRadius: 8 }}>
            <textarea placeholder="입고 내용 *" value={form.content} onChange={e => setForm(f => ({...f, content: e.target.value}))}
              style={{ ...s.inp, minHeight: 60 }} rows={3} />
            <div style={{ display: 'flex', gap: 8 }}>
              <input placeholder="거래처" value={form.vendor_name} onChange={e => setForm(f => ({...f, vendor_name: e.target.value}))} style={{ ...s.inp, flex: 1 }} />
              <input placeholder="발주번호" value={form.po_no} onChange={e => setForm(f => ({...f, po_no: e.target.value}))} style={{ ...s.inp, flex: 1 }} />
            </div>
            {/* 사진 선택 */}
            <div style={{ display: 'flex', gap: 8 }}>
              <label style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 10, borderRadius: 6, background: 'var(--bg)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px solid var(--border)' }}>
                📷 카메라
                <input type="file" accept="image/*" capture="environment" onChange={e => e.target.files[0] && setFiles(f => [...f, e.target.files[0]])} style={{ display: 'none' }} />
              </label>
              <label style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 10, borderRadius: 6, background: 'var(--bg)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px solid var(--border)' }}>
                📁 파일 ({files.length}장)
                <input type="file" accept="image/*" multiple onChange={e => setFiles(f => [...f, ...Array.from(e.target.files)])} style={{ display: 'none' }} />
              </label>
            </div>
            {files.length > 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {files.map((f, i) => <span key={i} style={{ marginRight: 6 }}>{f.name}</span>)}
                <button onClick={() => setFiles([])} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>전체삭제</button>
              </div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={handlePost} disabled={posting} style={{ flex: 1, padding: 10, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none' }}>
                {posting ? '등록중...' : '등록'}
              </button>
              <button onClick={() => { setShowForm(false); setFiles([]); }} style={{ flex: 1, padding: 10, borderRadius: 6, background: 'var(--surface)', color: 'var(--text-muted)', fontSize: 13, cursor: 'pointer', border: 'none' }}>취소</button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowForm(true)} style={{ width: '100%', padding: 10, borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', textAlign: 'center' }}>
            + 입고사진 등록
          </button>
        )}
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div> : posts.length === 0 ? <div className="page-empty">입고사진 없음</div> : (
          posts.map(post => (
            <div key={post.id} style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
              {/* 헤더 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{post.author_name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>{post.created_at}</span>
                </div>
                {post.po_no && <span className="msg-id">{post.po_no}</span>}
              </div>

              {/* 내용 */}
              {post.content && (
                <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.5, marginBottom: 8, whiteSpace: 'pre-wrap' }}>
                  {post.content}
                </div>
              )}

              {post.vendor_name && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>거래처: {post.vendor_name}</div>
              )}

              {/* 사진 갤러리 */}
              {post.photos && post.photos.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: post.photos.length === 1 ? '1fr' : 'repeat(2, 1fr)', gap: 4 }}>
                  {post.photos.map((p, i) => (
                    <div key={i} onClick={() => setViewImg(p)} style={{
                      aspectRatio: post.photos.length === 1 ? '16/9' : '1',
                      borderRadius: 8, overflow: 'hidden', cursor: 'pointer', background: 'var(--surface)',
                    }}>
                      <img src={imgUrl(p.file_path, true)} alt={p.file_name} loading="lazy"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
