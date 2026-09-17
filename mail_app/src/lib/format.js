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

const SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/**
 * 용량 — 사람이 한눈에 읽는 크기로.
 *
 *   980 B · 184 KB · 1.4 MB · 24 MB · 2.1 GB
 *
 * 규칙 두 가지:
 *  - **단위를 끝까지 올린다.** 예전엔 MB 에서 멈춰서 2GB 짜리가 `2048.0MB` 로 나왔다.
 *  - **10 미만일 때만 소수 한 자리.** `1.4 MB` 는 쓸모 있지만 `24.3 MB` 의 .3 은
 *    읽는 데 방해만 된다. 숫자와 단위는 띄운다(붙이면 `184KB` 처럼 뭉쳐 보인다).
 */
export function formatSize(bytes) {
  const n = Number(bytes);
  if (bytes === null || bytes === undefined || !Number.isFinite(n) || n < 0) return '';
  if (n === 0) return '0 B';        // 빈 파일도 크기를 말해 준다 — 빈칸이면 모르는 것처럼 보인다

  let v = n;
  let i = 0;
  while (v >= 1024 && i < SIZE_UNITS.length - 1) {
    v /= 1024;
    i += 1;
  }
  const text = i === 0 || v >= 10 ? String(Math.round(v)) : v.toFixed(1);
  return `${text} ${SIZE_UNITS[i]}`;
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
  // 용량과 같은 잣대로 적는다 — 한 화면에서 둘이 다른 모양이면 눈이 걸린다
  return `${formatSize(bytesPerSec)}/s`;
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
