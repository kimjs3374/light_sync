import { useState, useCallback, useEffect } from 'react';
import '../styles/archive.css';

const PALETTE = ['#a0d468', '#4fc1e9', '#fc6e51', '#ed5565', '#ac92ec', '#48cfad', '#ffce54', '#5d9cec'];

export function avatarColor(name) {
  const s = String(name || '');
  return PALETTE[s.length % PALETTE.length];
}

/* 동일출처 프록시 URL(/api/app/archive-file)에 토큰 부착 (<img>/<a>는 헤더 못 실음) */
export function authed(url) {
  if (url && url.startsWith('/api/app/archive-file')) {
    return url + '&_t=' + encodeURIComponent(localStorage.getItem('token') || '');
  }
  return url;
}

export function Avatar({ name, size = 'md' }) {
  return (
    <div className={`arc-avatar${size === 'sm' ? ' sm' : ''}`} style={{ background: avatarColor(name) }}>
      {String(name || '?').slice(0, 1)}
    </div>
  );
}

/* 서버에서 이스케이프/살균된 HTML (ProseMirror·평문 렌더 결과) */
export function PostBody({ html, className = 'arc-body' }) {
  if (!html) return null;
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}

/* 워크보드 첨부(attachments) → {full,thumb,name,w,h} 이미지 배열 */
export function wbImages(atts = []) {
  return atts.filter((a) => a.is_image && a.local_url)
    .map((a) => ({ full: a.local_url, thumb: a.thumb_url || a.local_url, name: a.file_name, w: a.width, h: a.height }));
}
export function wbFiles(atts = []) {
  return atts.filter((a) => !a.is_image)
    .map((a) => ({ url: a.local_url || a.original_url, name: a.file_name, size: a.file_size_fmt, ext: a.ext, type: a.file_type }));
}
/* 대화방 이미지/파일은 이미 {url,thumb,name,w,h}/{url,name,size} 형태 */
export function chatImages(imgs = []) {
  return imgs.map((i) => ({ full: i.url, thumb: i.thumb || i.url, name: i.name, w: i.w, h: i.h }));
}

/* 개별 이미지 — 썸네일 실패 시 원본 시도, 그마저 실패(백업 안 됨)면 깨진 아이콘 대신 플레이스홀더 */
function ArcImg({ img, style, onOpen, onImgLoad }) {
  const [stage, setStage] = useState('thumb'); // thumb → full → missing
  if (stage === 'missing') {
    return (
      <div className="arc-img-box arc-img-missing" style={style} title={img.name || '이미지'}>
        <span style={{ fontSize: 22 }}>🖼️</span>
        <span className="arc-img-missing-t">백업 안 된 사진</span>
      </div>
    );
  }
  const src = stage === 'thumb' ? authed(img.thumb) : authed(img.full);
  return (
    <div className="arc-img-box" style={style} onClick={onOpen}>
      <img className="arc-img" src={src} alt={img.name} loading="lazy"
        onLoad={onImgLoad}
        onError={() => setStage((s) => (s === 'thumb' ? 'full' : 'missing'))} />
    </div>
  );
}

/* 이미지 로드 전에도 자리를 차지하도록 aspect-ratio 로 박스 예약 → 레이아웃 흔들림 방지 */
export function ImageGrid({ images, onOpen, onImgLoad }) {
  if (!images || !images.length) return null;
  const single = images.length === 1;
  return (
    <div className={`arc-imgs${single ? ' single' : ''}`}>
      {images.map((img, i) => {
        const style = single && img.w && img.h ? { aspectRatio: `${img.w} / ${img.h}` } : undefined;
        return (
          <ArcImg key={i} img={img} style={style} onImgLoad={onImgLoad}
            onOpen={() => onOpen(images, i)} />
        );
      })}
    </div>
  );
}

export function FileList({ files }) {
  if (!files || !files.length) return null;
  return (
    <>
      {files.map((f, i) => (
        <a key={i} className="arc-file" href={authed(f.url)} target="_blank" rel="noopener noreferrer">
          <span className="arc-file-ico">{f.ext === 'pdf' ? '📄' : f.type === 'video' ? '🎬' : '📎'}</span>
          <span className="arc-file-name">{f.name}</span>
          {f.size && <span className="arc-file-size">{f.size}</span>}
        </a>
      ))}
    </>
  );
}

/* 라이트박스 훅: [openLightbox, node] */
export function useLightbox() {
  const [state, setState] = useState(null); // {images, idx}
  const open = useCallback((images, idx) => setState({ images, idx }), []);
  const close = useCallback(() => setState(null), []);
  const nav = useCallback((dir) => setState((s) => s && ({ ...s, idx: (s.idx + dir + s.images.length) % s.images.length })), []);

  useEffect(() => {
    if (!state) return;
    const onKey = (e) => {
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowLeft') nav(-1);
      if (e.key === 'ArrowRight') nav(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state, close, nav]);

  const node = state ? (
    <div className="arc-lightbox" onClick={close}>
      {state.images.length > 1 && (
        <button className="arc-lb-btn arc-lb-prev" onClick={(e) => { e.stopPropagation(); nav(-1); }}>‹</button>
      )}
      <img src={authed(state.images[state.idx].full)} alt="" onClick={(e) => e.stopPropagation()} />
      {state.images.length > 1 && (
        <button className="arc-lb-btn arc-lb-next" onClick={(e) => { e.stopPropagation(); nav(1); }}>›</button>
      )}
      <button className="arc-lb-close" onClick={(e) => { e.stopPropagation(); close(); }}>✕</button>
      {state.images.length > 1 && (
        <div className="arc-lb-count">{state.idx + 1} / {state.images.length}</div>
      )}
    </div>
  ) : null;

  return [open, node];
}
