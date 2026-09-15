/** 날짜: 오늘이면 시각, 올해면 월/일, 그 외 연도까지 — 네이버/다음 목록 표기 */
export function formatListDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  if (d.getFullYear() === now.getFullYear()) {
    return `${d.getMonth() + 1}. ${d.getDate()}.`;
  }
  return `${String(d.getFullYear()).slice(2)}. ${d.getMonth() + 1}. ${d.getDate()}.`;
}

export function formatFullDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const days = ['일', '월', '화', '수', '목', '금', '토'];
  return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}. (${days[d.getDay()]}) `
    + `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function formatSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / 1048576).toFixed(1)}MB`;
}

/** 보낸사람 표시: 이름이 있으면 이름, 없으면 주소의 로컬파트 */
export function senderName(from) {
  if (!from) return '(발신자 없음)';
  if (typeof from === 'string') return from;
  return from.name || (from.email || '').split('@')[0] || '(발신자 없음)';
}

export const senderEmail = (from) =>
  (!from ? '' : typeof from === 'string' ? from : from.email || '');

/**
 * 제목 앞머리의 [태그]를 떼어낸다.
 *
 * 이 메일함은 받은메일 47통 중 30통(64%)이 `[중진공 호남연수원]`,
 * `[매그나텍]` 처럼 대괄호 태그로 시작한다 (보낸메일은 9%).
 * 태그를 칩으로 빼면 제목 본문과 껍데기가 갈려 훑을 때 눈이 덜 흔들린다
 * (칩 너비가 제각각이라 세로로 줄이 서지는 않는다).
 * 태그가 너무 길면(제목 대신 대괄호를 쓴 경우) 떼지 않고 그대로 둔다.
 */
export function splitSubject(subject) {
  const raw = subject || '';
  const m = raw.match(/^\s*\[([^\]]{1,24})\]\s*(.*)$/);
  if (!m) return { tag: '', text: raw || '(제목 없음)' };
  const [, tag, rest] = m;
  if (!rest.trim()) return { tag: '', text: raw };  // 제목이 통째로 태그면 그대로
  return { tag: tag.trim(), text: rest.trim() };
}

/** 업로드 속도 — 12.3MB/s 처럼 */
export function formatSpeed(bytesPerSec) {
  if (!bytesPerSec || bytesPerSec < 1) return '';
  if (bytesPerSec < 1024 * 1024) return `${Math.round(bytesPerSec / 1024)}KB/s`;
  return `${(bytesPerSec / 1048576).toFixed(1)}MB/s`;
}

/** 남은 시간 — 1분 미만은 초로, 그 위는 분으로 */
export function formatRemain(sec) {
  if (sec === null || sec === undefined || !Number.isFinite(sec)) return '';
  if (sec < 1) return '곧 끝남';
  if (sec < 60) return `${Math.ceil(sec)}초 남음`;
  const m = Math.floor(sec / 60);
  const r = Math.round(sec % 60);
  return r ? `${m}분 ${r}초 남음` : `${m}분 남음`;
}
