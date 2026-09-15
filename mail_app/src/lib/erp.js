/**
 * ERP 주소.
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
