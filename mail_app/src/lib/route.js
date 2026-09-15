/**
 * 브라우저 뒤로가기 · 앞으로가기.
 *
 * 이 화면은 주소가 하나뿐인 SPA 라 히스토리에 아무것도 안 쌓였다. 메일을 열고
 * 메일함을 옮겨 다녀도 브라우저가 볼 때는 **첫 화면 그대로**라, 뒤로가기를 누르면
 * 메일이 아니라 ERP(또는 그 전에 보던 사이트)로 나가 버렸다.
 *
 * 그래서 화면이 바뀔 때마다 주소에 적고(pushState), 뒤로/앞으로 갈 때
 * 그 주소대로 화면을 되돌린다(popstate).
 *
 * **주소는 해시(`#/…`)로 쓴다.** 경로(`/INBOX`)로 쓰면 그 상태에서 새로고침했을 때
 * 서버가 ERP 라우트로 받아 404 가 난다 — 메일 SPA 는 `/`(mail 호스트)와
 * `/webmail/`(work 호스트) 두 자리에서 열리므로 경로를 늘릴 수 없다.
 *
 *   #/mail/INBOX          받은편지함
 *   #/mail/INBOX/1234     그 메일함의 1234번 메일을 연 상태
 *   #/selfbox  #/scheduled  #/contacts/personal
 *
 * 메일쓰기는 **주소에 적지 않는다.** 뒤로가기로 빈 작성창이 되살아나면
 * 쓰던 내용이 없는 껍데기라 더 헷갈린다. 대신 작성 중에 뒤로가기를 누르면
 * 작성창을 닫고 가려던 화면으로 간다 — 쓰던 게 있으면 늘 하던 대로 물어보고,
 * 취소하면 히스토리를 한 칸 앞으로 되밀어 자리를 지킨다.
 */

import { useMail } from '../store/mail';
import { useCompose } from '../store/compose';
import { useContacts } from '../store/contacts';

let applying = false;    // 뒤로가기를 적용하는 동안에는 새 기록을 쌓지 않는다
let started = false;     // StrictMode 이중 실행 방지
let skipNextPop = false; // 되민 것(history.forward)이 되돌아오는 popstate 한 번은 흘린다

/** 지금 화면을 주소 한 줄로. 메일쓰기 중이면 그 아래 깔린 화면을 적는다. */
export function currentHash() {
  const m = useMail.getState();
  if (m.specialView === 'contacts') return `#/contacts/${useContacts.getState().book}`;
  if (m.specialView === 'scheduled') return '#/scheduled';
  const base = m.specialView === 'selfbox' ? '#/selfbox' : `#/mail/${encodeURIComponent(m.folder)}`;
  return m.openUid ? `${base}/${m.openUid}` : base;
}

/** 주소 한 줄 → 화면. 모르는 주소는 null (받은편지함으로 둔다) */
export function parseHash(hash) {
  const parts = String(hash || '').replace(/^#\/?/, '').split('/').filter(Boolean);
  if (!parts.length) return null;
  const [head, ...rest] = parts;
  if (head === 'contacts') return { kind: 'contacts', book: rest[0] || 'personal' };
  if (head === 'scheduled') return { kind: 'scheduled' };
  if (head === 'selfbox') return { kind: 'selfbox', uid: rest[0] };
  if (head === 'mail' && rest.length) {
    return { kind: 'folder', folder: decodeURIComponent(rest[0]), uid: rest[1] };
  }
  return null;
}

/** 주소대로 화면을 되돌린다. 화면이 이미 그 상태면 아무것도 하지 않는다. */
async function applyView(v) {
  // 쓰던 메일이 있으면 늘 하던 대로 물어본다. 취소하면 자리를 지킨다.
  if (useCompose.getState().active && !useCompose.getState().close()) {
    // 되밀면 popstate 가 한 번 더 온다 — 그때 또 물어보면 두 번 묻는 꼴이다
    skipNextPop = true;
    window.history.forward();
    return;
  }

  const m = useMail.getState();
  if (v.kind === 'contacts') {
    useContacts.getState().setBook(v.book);
    if (m.specialView !== 'contacts') m.openSpecial('contacts');
    return;
  }
  if (v.kind === 'scheduled') {
    if (m.specialView !== 'scheduled') m.openSpecial('scheduled');
    return;
  }

  if (v.kind === 'selfbox') {
    if (m.specialView !== 'selfbox') m.openSpecial('selfbox');
  } else if (m.specialView || m.folder !== v.folder) {
    m.selectFolder(v.folder);
  }

  const st = useMail.getState();
  if (v.uid && String(st.openUid) !== String(v.uid)) await st.open(Number(v.uid));
  else if (!v.uid && st.openUid) st.close();
}

/** 화면이 바뀌었으면 주소에 한 줄 쌓는다 */
function record() {
  if (applying) return;
  const hash = currentHash();
  if (hash === window.location.hash) return;
  window.history.pushState({ mail: hash }, '', hash);
}

/**
 * 히스토리 연결. 부팅(init) 이 끝난 뒤 한 번 부른다.
 * 주소에 화면이 적혀 있으면(새로고침·즐겨찾기) 그 화면으로 맞추고 시작한다.
 */
export function startRouting() {
  if (started) return () => {};
  started = true;

  const first = parseHash(window.location.hash);
  if (first) {
    applying = true;
    Promise.resolve(applyView(first)).finally(() => {
      applying = false;
      window.history.replaceState({ mail: currentHash() }, '', currentHash());
    });
  } else {
    window.history.replaceState({ mail: currentHash() }, '', currentHash());
  }

  const onPop = async () => {
    if (skipNextPop) { skipNextPop = false; return; }
    const v = parseHash(window.location.hash) || { kind: 'folder', folder: 'INBOX' };
    applying = true;
    try { await applyView(v); } finally { applying = false; }
  };
  window.addEventListener('popstate', onPop);

  // 스토어가 바뀔 때마다 본다 — 화면을 옮기는 자리마다 기록을 심는 것보다
  // 한 곳에서 보는 편이 빠뜨리지 않는다
  const stop = [
    useMail.subscribe(record),
    useContacts.subscribe(record),
    useCompose.subscribe(record),
  ];

  return () => {
    window.removeEventListener('popstate', onPop);
    stop.forEach((fn) => fn());
    started = false;
  };
}
