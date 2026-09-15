/**
 * ERP 주소 + 로그인 이어받기.
 *
 * 메일은 mail.mgnt.kr 에 따로 산다 — 여기서 `/` 는 ERP 가 아니라 메일 화면 자신이다.
 * 그래서 ERP 로 나가는 링크는 호스트를 박아서 내보낸다. 상대경로로 두면
 * "ERP로 돌아가기" 가 메일을 다시 여는 꼴이 된다.
 *
 * 서버가 메일 본문에 넣는 대용량 첨부 링크는 여기와 무관하다 —
 * 그쪽은 `.env` 의 `FLASK_DOMAIN` 을 본다 (routes/mail.py).
 */
export const ERP_ORIGIN = 'https://work.mgnt.kr';

/** ERP 안의 경로를 절대 주소로 — erpUrl('/mail/settings') */
export const erpUrl = (path = '/') => ERP_ORIGIN + path;

// ── 로그인 이어받기 ─────────────────────────────────────────────────────────
// 세션 쿠키는 호스트별이라, work 에 로그인해 있어도 mail 은 그걸 모른다.
// 로그인 화면으로 바로 보내지 않고 ERP 에게 한 번 건네달라고 부탁한다
// (routes/app_api.py 의 /api/app/handoff → handoff-land).
// ERP 도 로그인이 없으면 로그인 화면을 거쳐 되돌아온다.
//
// **한 번만 시도한다.** 건네받고도 세션이 안 잡히면 그대로 다시 나가 무한히 돈다.
const HANDOFF_TRIED = 'erp_handoff_tried';

const flag = {
  get: () => { try { return sessionStorage.getItem(HANDOFF_TRIED); } catch { return '1'; } },
  set: () => { try { sessionStorage.setItem(HANDOFF_TRIED, '1'); } catch { /* 무시 */ } },
  clear: () => { try { sessionStorage.removeItem(HANDOFF_TRIED); } catch { /* 무시 */ } },
};

// 401 은 겹쳐서 떨어진다(목록·설정을 같이 부른다). 먼저 시작한 이동이
// 뒤엣것에 취소되면 이어받기가 중간에 끊긴다 — 실제로 그렇게 끊겼다.
let leaving = false;

/** 로그인이 풀렸을 때 나갈 곳 — 되도록 ERP 세션을 이어받아 온다 */
export function goLogin() {
  if (leaving) return;
  leaving = true;
  const here = window.location.pathname;
  const crossHost = window.location.origin !== ERP_ORIGIN;
  // http(개발 서버)에서는 운영 ERP 로 건너가지 않는다
  const canHandoff = crossHost && window.location.protocol === 'https:';

  if (canHandoff && !flag.get()) {
    flag.set();
    const to = encodeURIComponent(window.location.origin + here);
    window.location.href = `${ERP_ORIGIN}/api/app/handoff?to=${to}`;
    return;
  }
  window.location.href = `/login?next=${encodeURIComponent(here)}`;
}

/** 로그인이 잡혔다 — 다음에 풀리면 다시 건네받을 수 있게 표시를 지운다 */
export const loginSettled = () => flag.clear();
