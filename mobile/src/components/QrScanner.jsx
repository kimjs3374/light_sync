import { useEffect, useRef, useState } from 'react';

/**
 * QR 스캐너 — 브라우저 내장 BarcodeDetector 사용 (외부 라이브러리 없음).
 *
 * 지원: Android Chrome, 데스크톱 Chrome/Edge
 * 미지원(iOS Safari 등): 폰 기본 카메라로 QR을 찍으면 공개 페이지가 열리므로
 *   그쪽으로 안내하고, 시료번호 직접 입력 경로를 제공한다.
 *
 * props
 *   onDetect(value) : QR 원문(보통 https://.../s/<token>)
 *   onManual(text)  : 시료번호 직접 입력
 *   onClose()
 */
export default function QrScanner({ onDetect, onManual, onClose }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const doneRef = useRef(false);

  const supported = typeof window !== 'undefined' && 'BarcodeDetector' in window;

  const [error, setError] = useState('');
  // 미지원 브라우저는 카메라를 아예 안 켜므로 준비중 상태로 두지 않는다
  const [starting, setStarting] = useState(supported);
  const [manual, setManual] = useState('');

  // 카메라 정리 — 화면을 벗어나도 카메라가 켜져 있으면 안 된다
  const stopAll = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
  };

  useEffect(() => {
    if (!supported) return stopAll;

    let detector;
    (async () => {
      try {
        detector = new window.BarcodeDetector({ formats: ['qr_code'] });
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' } },
          audio: false,
        });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setStarting(false);

        timerRef.current = setInterval(async () => {
          if (doneRef.current || !videoRef.current || videoRef.current.readyState < 2) return;
          try {
            const codes = await detector.detect(videoRef.current);
            if (codes && codes.length) {
              const value = (codes[0].rawValue || '').trim();
              if (value) {
                doneRef.current = true;
                stopAll();
                onDetect(value);
              }
            }
          } catch { /* 프레임 단위 실패는 무시하고 다음 프레임 */ }
        }, 350);
      } catch (e) {
        setStarting(false);
        if (e && (e.name === 'NotAllowedError' || e.name === 'SecurityError')) {
          setError('카메라 권한이 거부되었습니다. 브라우저 설정에서 카메라를 허용해주세요.');
        } else if (e && e.name === 'NotFoundError') {
          setError('사용할 수 있는 카메라가 없습니다.');
        } else {
          setError('카메라를 열 수 없습니다. 시료번호로 직접 검색해주세요.');
        }
      }
    })();

    return stopAll;
  }, [supported, onDetect]);

  const submitManual = () => {
    const v = manual.trim();
    if (!v) return;
    stopAll();
    onManual(v);
  };

  return (
    <div style={s.backdrop}>
      <div style={s.sheet}>
        <div style={s.head}>
          <span style={{ fontSize: 14, fontWeight: 700 }}>QR 스캔</span>
          <button onClick={() => { stopAll(); onClose(); }} style={s.close}>✕</button>
        </div>

        {supported && !error && (
          <div style={s.videoWrap}>
            <video ref={videoRef} playsInline muted style={s.video} />
            <div style={s.reticle} />
            <div style={s.hint}>
              {starting ? '카메라 준비 중...' : '시료에 붙은 QR을 사각형 안에 맞춰주세요'}
            </div>
          </div>
        )}

        {!supported && (
          <div style={s.notice}>
            <b>이 브라우저는 앱 내 스캔을 지원하지 않습니다.</b><br />
            폰 <b>기본 카메라</b>로 QR을 찍으면 시료 페이지가 바로 열립니다.<br />
            또는 아래에 시료번호를 입력하세요.
          </div>
        )}

        {error && <div style={{ ...s.notice, color: 'var(--red)' }}>{error}</div>}

        <div style={{ padding: '10px 14px 14px' }}>
          <div style={s.fl}>시료번호로 찾기</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={manual}
              onChange={e => setManual(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submitManual(); }}
              placeholder="ARENA-200S-001"
              style={{ ...s.inp, flex: 1 }}
            />
            <button onClick={submitManual} style={s.go}>찾기</button>
          </div>
        </div>
      </div>
    </div>
  );
}

const s = {
  backdrop: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,.75)', zIndex: 3000,
    display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
  },
  sheet: {
    width: '100%', maxWidth: 520, background: 'var(--surface)',
    borderRadius: '12px 12px 0 0', overflow: 'hidden', paddingBottom: 4,
  },
  head: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 14px', borderBottom: '1px solid var(--border)',
  },
  close: { background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 16, cursor: 'pointer' },
  videoWrap: { position: 'relative', background: '#000', aspectRatio: '4 / 3', overflow: 'hidden' },
  video: { width: '100%', height: '100%', objectFit: 'cover', display: 'block' },
  reticle: {
    position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
    width: '62%', aspectRatio: '1 / 1', border: '3px solid rgba(255,255,255,.9)',
    borderRadius: 12, boxShadow: '0 0 0 9999px rgba(0,0,0,.35)',
  },
  hint: {
    position: 'absolute', bottom: 10, left: 0, right: 0, textAlign: 'center',
    fontSize: 12, color: '#fff', textShadow: '0 1px 3px rgba(0,0,0,.8)',
  },
  notice: { padding: '14px', fontSize: 13, lineHeight: 1.7, color: 'var(--text)' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 },
  inp: {
    padding: '10px 12px', borderRadius: 6, background: 'var(--bg)',
    border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13,
  },
  go: {
    padding: '10px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
    background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600,
  },
};
