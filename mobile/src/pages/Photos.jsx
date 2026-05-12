import { useState, useEffect } from 'react';
import { api } from '../api/client';

const PHOTO_TYPES = ['설계', '명함', '생산', '상차', '하차', '설치'];

export default function Photos() {
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [grouped, setGrouped] = useState({});
  const [expanded, setExpanded] = useState({});
  const [viewPhoto, setViewPhoto] = useState(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadForm, setUploadForm] = useState({ site_id: '', photo_type: '설계' });
  const [uploading, setUploading] = useState(false);

  const load = () => {
    // 사진 목록만 가져오고 이미지는 lazy load
    api.get('/photos').then(d => {
      const ps = d.photos || [];
      setPhotos(ps);
      const g = {};
      ps.forEach(p => {
        const key = p.project_name || '미분류';
        if (!g[key]) g[key] = { project_id: p.project_id, photos: [] };
        g[key].photos.push(p);
      });
      setGrouped(g);
    }).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    if (!uploadForm.site_id) { e.target.value = ''; return alert('현장을 선택해주세요'); }
    setUploading(true);
    const token = localStorage.getItem('token');
    let okCount = 0;
    const errors = [];
    try {
      for (const original of files) {
        let file;
        try {
          file = await resizeImage(original, 1600);
        } catch (re) {
          errors.push(`${original.name}: ${re.message}`);
          continue;
        }
        const fd = new FormData();
        fd.append('file', file, 'photo.jpg');
        fd.append('site_id', uploadForm.site_id);
        fd.append('photo_type', uploadForm.photo_type);
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 90000);
        try {
          const res = await fetch('/api/app/photos/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: fd,
            signal: ctrl.signal,
          });
          const data = await res.json().catch(() => ({ ok: false, error: `서버 오류 (${res.status})` }));
          if (!data.ok) throw new Error(data.error || '업로드 실패');
          okCount += 1;
        } catch (netErr) {
          const msg = netErr.name === 'AbortError'
            ? '시간 초과'
            : (netErr.message || '네트워크 오류');
          errors.push(`${original.name}: ${msg}`);
        } finally {
          clearTimeout(timer);
        }
      }
    } finally {
      setUploading(false);
      e.target.value = '';
    }
    if (okCount > 0) { setShowUpload(false); load(); }
    if (errors.length > 0) {
      alert(`${okCount}장 업로드 성공, ${errors.length}장 실패\n\n${errors.join('\n')}`);
    }
  };

  const deletePhoto = async (id) => {
    if (!confirm('사진을 삭제하시겠습니까?')) return;
    try { await api.post(`/photos/${id}/delete`, {}); setViewPhoto(null); load(); } catch (e) { alert(e.message); }
  };

  const toggle = (key) => setExpanded(prev => ({ ...prev, [key]: !prev[key] }));
  const groups = Object.entries(grouped).sort((a, b) => b[1].photos.length - a[1].photos.length);
  const token = localStorage.getItem('token');
  const thumbUrl = (id) => `/api/app/photos/${id}/view?_t=${token}&thumb=1`;
  const fullUrl = (id) => `/api/app/photos/${id}/view?_t=${token}`;

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>사진관리</h1>
        <span className="ch-count">{photos.length}</span>
      </div>

      {/* 전체화면 사진 뷰어 */}
      {viewPhoto && (
        <div onClick={() => setViewPhoto(null)} style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 200,
          background: 'rgba(0,0,0,0.9)', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <img src={fullUrl(viewPhoto.id)} alt={viewPhoto.file_name}
            style={{ maxWidth: '100%', maxHeight: '70vh', borderRadius: 8, objectFit: 'contain' }}
            onClick={e => e.stopPropagation()} />
          <div style={{ color: '#fff', marginTop: 12, textAlign: 'center' }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{viewPhoto.file_name}</div>
            <div style={{ fontSize: 12, color: '#aaa', marginTop: 4 }}>
              {viewPhoto.photo_type} · {viewPhoto.uploaded_by} · {viewPhoto.created_at?.slice(0, 16)}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
            <button onClick={() => setViewPhoto(null)} style={s.viewBtn}>닫기</button>
            <button onClick={(e) => { e.stopPropagation(); deletePhoto(viewPhoto.id); }} style={{ ...s.viewBtn, background: 'var(--red)' }}>삭제</button>
          </div>
        </div>
      )}

      {/* 업로드 */}
      <div style={{ padding: '8px 16px' }}>
        {showUpload ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--surface)', borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>현장 검색 *</div>
            <ProjectSearch value={uploadForm.site_id}
              onChange={(id) => setUploadForm(f => ({...f, site_id: id}))} />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>사진 유형</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {PHOTO_TYPES.map(t => (
                <button key={t} onClick={() => setUploadForm(f => ({...f, photo_type: t}))}
                  style={{ padding: '5px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600, border: 'none', cursor: 'pointer',
                    background: uploadForm.photo_type === t ? 'var(--accent)' : 'var(--bg)', color: uploadForm.photo_type === t ? '#fff' : 'var(--text-muted)' }}>
                  {t}
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <label style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                📷 카메라
                <input type="file" accept="image/*" capture="environment" onChange={handleUpload} style={{ display: 'none' }} disabled={uploading} />
              </label>
              <label style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12, borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px solid var(--border)' }}>
                📁 파일 선택
                <input type="file" accept="image/*" multiple onChange={handleUpload} style={{ display: 'none' }} disabled={uploading} />
              </label>
            </div>
            {uploading && <div style={{ textAlign: 'center', color: 'var(--accent)', fontSize: 13, marginTop: 4 }}>업로드중...</div>}
            <button onClick={() => setShowUpload(false)} style={{ padding: 8, borderRadius: 6, background: 'var(--surface)', color: 'var(--text-muted)', fontSize: 13, border: 'none', cursor: 'pointer' }}>취소</button>
          </div>
        ) : (
          <button onClick={() => setShowUpload(true)}
            style={{ width: '100%', padding: 10, borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', textAlign: 'center' }}>
            + 사진 업로드
          </button>
        )}
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div> : groups.length === 0 ? <div className="page-empty">사진 없음</div> : (
          groups.map(([name, data]) => (
            <div key={name} style={{ borderBottom: '1px solid var(--border)' }}>
              {/* 현장 헤더 */}
              <div onClick={() => toggle(name)} style={{
                padding: '10px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer',
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{name}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{data.photos.length}장</div>
                </div>
                <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>{expanded[name] ? '▼' : '▶'}</span>
              </div>

              {/* 갤러리 */}
              {expanded[name] && (
                <PhotoGrid photos={data.photos} thumbUrl={thumbUrl} onView={setViewPhoto} />
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function PhotoGrid({ photos, thumbUrl, onView }) {
  const [show, setShow] = useState(6);
  const visible = photos.slice(0, show);
  const hasMore = show < photos.length;

  return (
    <div style={{ padding: '0 16px 12px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
        {visible.map(p => (
          <LazyThumb key={p.id} photo={p} thumbUrl={thumbUrl} onView={onView} />
        ))}
      </div>
      {hasMore && (
        <button onClick={() => setShow(s => s + 9)} style={{
          width: '100%', padding: 8, marginTop: 6, borderRadius: 6,
          background: 'var(--surface)', color: 'var(--accent)', fontSize: 12, fontWeight: 600,
          border: 'none', cursor: 'pointer',
        }}>
          더보기 ({photos.length - show}장 남음)
        </button>
      )}
    </div>
  );
}

function LazyThumb({ photo, thumbUrl, onView }) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  return (
    <div onClick={() => onView(photo)} style={{
      aspectRatio: '1', borderRadius: 6, overflow: 'hidden', cursor: 'pointer',
      background: 'var(--surface)', position: 'relative',
    }}>
      {!error && (
        <img src={thumbUrl(photo.id)} alt={photo.file_name} loading="lazy"
          style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: loaded ? 1 : 0, transition: 'opacity 0.3s' }}
          onLoad={() => setLoaded(true)}
          onError={() => setError(true)} />
      )}
      {(!loaded || error) && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: 'var(--text-muted)', textAlign: 'center', padding: 4 }}>
          {error ? photo.file_name : '...'}
        </div>
      )}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '2px 4px',
        background: 'rgba(0,0,0,0.6)', fontSize: 9, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {photo.photo_type}
      </div>
    </div>
  );
}

// 서버사이드 디바운스 검색 — 현장명/약칭/설계번호/계약명 모두 매칭
function ProjectSearch({ value, onChange }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(null);  // {id, name, ...}

  // 선택된 현장 라벨 복원 (수정 모드 대비)
  useEffect(() => {
    if (value && (!selected || selected.id !== Number(value))) {
      api.get(`/projects/${value}`).then(d => {
        const p = d.project;
        if (p) setSelected({ id: p.id, name: p.temp_name || p.contract_name || `현장 #${p.id}` });
      }).catch(() => {});
    }
    if (!value) setSelected(null);
  }, [value]);

  // 디바운스 서버 검색
  useEffect(() => {
    if (selected || !query.trim()) { setResults([]); return; }
    const t = setTimeout(() => {
      api.get(`/search/projects?q=${encodeURIComponent(query.trim())}&status=계약`)
        .then(d => setResults(d.results || []))
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(t);
  }, [query, selected]);

  const labelOf = (p) => p.name || p.contract_name || p.short_name || `#${p.project_no || p.id}`;

  return (
    <div style={{ position: 'relative' }}>
      {selected ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)' }}>
          <span style={{ flex: 1, fontSize: 13, color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {labelOf(selected)}
          </span>
          <button onClick={() => { onChange(''); setQuery(''); setSelected(null); }} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 14, cursor: 'pointer' }}>×</button>
        </div>
      ) : (
        <input placeholder="현장명/설계번호/계약명 검색..." value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          style={{ width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 }} />
      )}
      {open && !selected && results.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, maxHeight: 240, overflow: 'auto', marginTop: 2 }}>
          {results.map(p => (
            <div key={p.id} onClick={() => { onChange(String(p.id)); setSelected(p); setQuery(''); setOpen(false); }}
              style={{ padding: '8px 12px', fontSize: 13, color: 'var(--text)', cursor: 'pointer', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 600, color: 'var(--text-bright)' }}>{labelOf(p)}</div>
              {(p.contract_name && p.contract_name !== p.name) && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2,
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.contract_name}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {open && !selected && query.trim() && results.length === 0 && (
        <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--text-muted)' }}>검색 결과 없음</div>
      )}
    </div>
  );
}

// 이미지 → JPEG 리사이즈 (HEIC 디코딩 실패 시 에러 throw)
async function resizeImage(file, maxWidth) {
  let bitmap = null;
  try {
    if (typeof createImageBitmap === 'function') {
      bitmap = await createImageBitmap(file);
    }
  } catch (_) { /* 폴백 */ }

  let srcW, srcH, drawSource;
  if (bitmap) {
    srcW = bitmap.width; srcH = bitmap.height; drawSource = bitmap;
  } else {
    drawSource = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('파일을 읽을 수 없습니다'));
      reader.onload = (e) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('지원하지 않는 이미지 형식'));
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    });
    srcW = drawSource.naturalWidth || drawSource.width;
    srcH = drawSource.naturalHeight || drawSource.height;
  }

  if (!srcW || !srcH) throw new Error('이미지 크기를 인식하지 못했습니다');

  const ratio = Math.min(1, maxWidth / srcW);
  const w = Math.max(1, Math.round(srcW * ratio));
  const h = Math.max(1, Math.round(srcH * ratio));
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(drawSource, 0, 0, w, h);
  if (bitmap && bitmap.close) bitmap.close();

  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((b) => b ? resolve(b) : reject(new Error('JPEG 변환 실패')),
                  'image/jpeg', 0.85);
  });
  return new File([blob], 'photo.jpg', { type: 'image/jpeg' });
}

const s = {
  viewBtn: { padding: '10px 24px', borderRadius: 6, border: 'none', background: 'var(--surface)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' },
};
