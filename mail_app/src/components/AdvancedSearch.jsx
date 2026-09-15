import { useEffect, useRef, useState } from 'react';
import { useMail } from '../store/mail';
import { folderLabel } from '../lib/folders';

const EMPTY = {
  from: '', to: '', subject: '', body: '',
  date_from: '', date_to: '',
  has_attachment: false, unread: false, flagged: false,
};

const FIELDS = [
  ['from', '보낸사람', '이름 또는 메일주소'],
  ['to', '받는사람', '이름 또는 메일주소'],
  ['subject', '제목', '제목에 들어갈 말'],
  ['body', '본문', '본문에 들어갈 말'],
];

const isEmpty = (f) => Object.entries(f).every(([, v]) => v === '' || v === false);

/**
 * 상세검색 패널.
 *
 * 조건은 **모두 만족**해야 한다(IMAP SEARCH 는 AND). 서버가 조건을 겹쳐 걸므로
 * 여기서는 빈 칸만 걸러 보내면 된다.
 *
 * 찾는 범위는 **지금 열어둔 메일함 하나**다. 그래서 머리말에 어느 함인지 적어둔다 —
 * 안 적으면 "분명히 있는 메일이 안 나온다"가 된다.
 */
export default function AdvancedSearch({ onClose }) {
  const s = useMail();
  const [f, setF] = useState(() => ({ ...EMPTY, ...(s.searchDetail?.params || {}) }));
  const boxRef = useRef(null);
  const firstRef = useRef(null);

  useEffect(() => { firstRef.current?.focus(); }, []);

  // 바깥을 누르거나 Esc 로 닫는다
  useEffect(() => {
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) onClose();
    };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const set = (key) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setF((prev) => ({ ...prev, [key]: v }));
  };

  const badDates = f.date_from && f.date_to && f.date_from > f.date_to;

  const submit = (e) => {
    e.preventDefault();
    if (isEmpty(f) || badDates) return;
    // 빈 칸·꺼진 체크는 보내지 않는다 — 조건으로 새지 않게
    const params = {};
    for (const [k, v] of Object.entries(f)) {
      if (v === true) params[k] = 1;
      else if (typeof v === 'string' && v.trim()) params[k] = v.trim();
    }
    s.searchAdvanced(params);
    onClose();
  };

  const where = s.specialView === 'selfbox' ? '내게쓴메일함' : folderLabel(s.folder);

  return (
    <form className="adv-search" ref={boxRef} onSubmit={submit}>
      <div className="adv-head">
        <strong>상세검색</strong>
        <span className="adv-scope">{where} 안에서</span>
        <button type="button" className="adv-x" title="닫기" onClick={onClose}>✕</button>
      </div>

      {FIELDS.map(([key, label, ph], i) => (
        <label className="adv-row" key={key}>
          <span className="adv-label">{label}</span>
          <input
            ref={i === 0 ? firstRef : undefined}
            value={f[key]}
            onChange={set(key)}
            placeholder={ph}
          />
        </label>
      ))}

      <label className="adv-row">
        <span className="adv-label">기간</span>
        <span className="adv-dates">
          <input type="date" value={f.date_from} onChange={set('date_from')} max={f.date_to || undefined} />
          <em>~</em>
          <input type="date" value={f.date_to} onChange={set('date_to')} min={f.date_from || undefined} />
        </span>
      </label>

      <div className="adv-row">
        <span className="adv-label" />
        <div className="adv-checks">
          <label><input type="checkbox" checked={f.has_attachment} onChange={set('has_attachment')} /> 첨부 있음</label>
          <label><input type="checkbox" checked={f.unread} onChange={set('unread')} /> 안읽음</label>
          <label><input type="checkbox" checked={f.flagged} onChange={set('flagged')} /> 중요</label>
        </div>
      </div>

      {badDates && <p className="adv-warn">시작일이 종료일보다 뒤입니다.</p>}

      <div className="adv-foot">
        <button type="button" className="plain" onClick={() => setF(EMPTY)}>초기화</button>
        <button type="submit" disabled={isEmpty(f) || badDates}>검색</button>
      </div>
    </form>
  );
}
