import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * 주소 입력칸 — 넣은 주소는 칩이 되고, 입력 중에는 주소록을 제안한다.
 * 쉼표·세미콜론·탭·엔터로 확정하고, 빈 칸에서 Backspace 면 마지막 칩을 지운다.
 */
export default function AddressInput({ label, value, onChange, autoFocus, trailing }) {
  const [text, setText] = useState('');
  const [suggest, setSuggest] = useState([]);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const timer = useRef(null);

  useEffect(() => {
    clearTimeout(timer.current);
    const q = text.trim();
    if (q.length < 1) { setSuggest([]); return; }
    // 글자마다 쏘면 IMAP 서버가 아니라 DB 라도 아깝다 — 200ms 묶어서 한 번
    timer.current = setTimeout(async () => {
      try {
        const res = await api.get(`/mail/api/contacts/suggest?q=${encodeURIComponent(q)}&limit=8`);
        setSuggest(Array.isArray(res) ? res : []);
        setActive(0);
      } catch { setSuggest([]); }
    }, 200);
    return () => clearTimeout(timer.current);
  }, [text]);

  const add = (email) => {
    const e = (email || '').trim().replace(/^.*<|>.*$/g, '').trim();
    if (!e) return;
    if (!value.some((v) => v.toLowerCase() === e.toLowerCase())) onChange([...value, e]);
    setText('');
    setSuggest([]);
  };

  const onKeyDown = (e) => {
    if (suggest.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : -1) + suggest.length) % suggest.length);
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab' || e.key === ',' || e.key === ';') {
      if (e.key === 'Tab' && !text.trim() && !suggest.length) return;   // 다음 칸으로 넘어가게 둔다
      e.preventDefault();
      add(suggest.length && e.key === 'Enter' ? suggest[active].email : text);
      return;
    }
    if (e.key === 'Backspace' && !text && value.length) {
      onChange(value.slice(0, -1));
    }
    if (e.key === 'Escape') setSuggest([]);
  };

  return (
    <div className="addr-field" ref={boxRef}>
      <span className="addr-field-label">{label}</span>
      <div className="addr-chips">
        {value.map((v, i) => (
          <span key={v + i} className={`addr-tag${EMAIL_RE.test(v) ? '' : ' bad'}`} title={EMAIL_RE.test(v) ? v : '주소 형식을 확인하세요'}>
            {v}
            <button type="button" className="addr-tag-x"
              onClick={() => onChange(value.filter((_, idx) => idx !== i))} aria-label="삭제">✕</button>
          </span>
        ))}
        <input
          className="addr-text"
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => { if (text.trim()) add(text); setTimeout(() => setSuggest([]), 150); }}
          placeholder={value.length ? '' : '이름 또는 메일주소'}
        />
      </div>
      {/* 행 맨 오른쪽 — 참조 줄의 '숨은참조' 버튼이 여기 붙는다 */}
      {trailing && <div className="addr-trailing">{trailing}</div>}

      {suggest.length > 0 && (
        <div className="addr-suggest">
          {suggest.map((c, i) => (
            <button
              key={c.email + i}
              type="button"
              className={`suggest-item${i === active ? ' active' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); add(c.email); }}
              onMouseEnter={() => setActive(i)}
            >
              <span className="suggest-name">{c.name || c.email.split('@')[0]}</span>
              <span className="suggest-email">{c.email}</span>
              {c.type === 'internal' && <span className="suggest-tag">사내</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
