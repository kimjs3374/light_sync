import { useEffect, useRef, useState } from 'react';

const pad = (n) => String(n).padStart(2, '0');

export const toLocalInput = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** 연도는 네 자리까지. 브라우저 날짜칸은 max 가 없으면 275760년까지 받는다. */
export const MAX_WHEN = '9999-12-31T23:59';

export const toServerTime = (localValue) => {
  const d = new Date(localValue);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
};

/** 자주 쓰는 시각 — 매번 달력을 헤집지 않도록 */
export function quickTimes() {
  const now = new Date();
  const inHour = new Date(now.getTime() + 60 * 60 * 1000);

  const tomorrow9 = new Date(now);
  tomorrow9.setDate(now.getDate() + 1);
  tomorrow9.setHours(9, 0, 0, 0);

  const monday9 = new Date(now);
  const daysToMon = ((8 - now.getDay()) % 7) || 7;   // 다음 주 월요일
  monday9.setDate(now.getDate() + daysToMon);
  monday9.setHours(9, 0, 0, 0);

  return [
    { label: '1시간 뒤', at: inHour },
    { label: '내일 오전 9시', at: tomorrow9 },
    { label: '다음 월요일 9시', at: monday9 },
  ];
}

export const shortWhen = (d) =>
  `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** 바깥을 누르면 닫히는 작은 메뉴 */
export function Popover({ onClose, children, className = '' }) {
  const ref = useRef(null);
  useEffect(() => {
    const onDown = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    const t = setTimeout(() => document.addEventListener('mousedown', onDown), 0);
    document.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);
  return <div className={`popover ${className}`} ref={ref}>{children}</div>;
}

/**
 * 시각 고르기 메뉴 — 예약 걸 때와 예약 시각 바꿀 때가 같은 모양이어야 한다.
 * @param title    메뉴 제목
 * @param note     제목 아래 안내 (없으면 생략)
 * @param confirm  확정 버튼 글자
 * @param initial  처음 채워둘 Date
 * @param onPick   고른 값(로컬 입력 문자열)을 받는다
 */
export default function TimePicker({ title, note, confirm, initial, onPick, onClose }) {
  const [when, setWhen] = useState(() =>
    toLocalInput(initial instanceof Date && !Number.isNaN(initial.getTime())
      ? initial
      : new Date(Date.now() + 60 * 60 * 1000)));

  return (
    <Popover onClose={onClose} className="pop-schedule">
      <div className="pop-title">{title}</div>
      {note && <p className="pop-note">{note}</p>}

      {quickTimes().map((q) => (
        <button key={q.label} className="pop-item" onClick={() => onPick(toLocalInput(q.at))}>
          <span>{q.label}</span>
          <em>{shortWhen(q.at)}</em>
        </button>
      ))}

      <div className="pop-sep" />
      <label className="pop-field">
        <span>직접 지정</span>
        <input
          type="datetime-local"
          value={when}
          min={toLocalInput(new Date())}
          max={MAX_WHEN}
          onChange={(e) => setWhen(e.target.value)}
        />
      </label>
      <button className="pop-primary" onClick={() => onPick(when)}>{confirm}</button>
    </Popover>
  );
}
