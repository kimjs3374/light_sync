# 메일이 나가는 길은 두 갈래다

**메일 관련 수정은 항상 두 경로를 같이 본다.** 같은 "메일 보내기"가 두 모듈에 따로 구현돼 있다는 걸
모르면, 한쪽만 고치고 다 고쳤다고 생각하게 된다.

| 경로 | 쓰는 곳 | 보낸편지함 사본 |
|---|---|---|
| `mail_client.MailClient.send_message()` | 웹메일 화면에서 사람이 직접 쓴 메일 | 처음부터 있었음 (IMAP APPEND) |
| `services/email_sender.py` | **발주서·가공발주·연차촉진·비밀번호 메일** | **없었음 — `smtplib.sendmail()` 로 끝** |

그래서 "발주 메일 보낸 거 보낸편지함에서 왜 안 보이냐"가 나왔다. 메일서버엔 나간 기록이 있는데
계정 메일함엔 사본이 없는 상태였다.

2026-09-15 에 `MailClient.append_to_sent()` 를 공용 메서드로 빼고, `email_sender` 양쪽
함수(`send_purchase_order_email`, `send_email_with_attachments`)가 발송 성공 직후 이걸 부르게 했다.
사본은 `\Seen` 으로 넣는다(안읽음 뱃지에 안 잡히게).

---

## 지켜야 할 것

- **보낸편지함 저장은 발송 성공을 절대 뒤집지 않는다.** 호출 시점에 메일은 이미 나갔다.
  IMAP 이 죽어도 경고 로그만 남기고 `success: True` 를 유지한다.

- 발신 공용계정은 `light_sync.mail_accounts` 의 `is_shared=true` 행이다
  (`purchase@` `sales@` `eng@` `etc@` `magna@` `noreply@` `tax@`).
  세 발신계정 모두 IMAP 로그인되고 보낸편지함 폴더명은 `Sent` 다(2026-09-15 실측).

- **ERP 자동발송 기록은 `light_sync.email_history` 테이블에 쌓인다.** 수신자·제목·본문·첨부파일명·
  성공여부·오류까지 있다. 오래 insert 만 있고 읽는 화면이 없었다 — 2026-09-15 에
  `/mail/send-history`(메뉴키 `mail_send_history`, 기본 관리자·임원진만)를 붙였다.

- **과거 건은 보낸편지함에 소급 저장할 수 없다.** `email_history` 에 첨부파일 *이름* 은 있어도
  실제 바이트와 원본 메시지가 없다. 지난 건은 발송이력 화면에서만 본다.

- **CLI 로 메일계정을 다룰 땐 `from app import app` 을 먼저 한다.** `.env` 의 `MAIL_ENCRYPT_KEY` 가
  그때 로드된다. 안 하면 `Fernet key must be 32 url-safe base64-encoded bytes` 로 조용히 실패하고
  계정 조회가 `None` 을 돌려준다 — 계정이 없는 것처럼 보인다.

관련: `.claude/webmail.md` (메일 SPA·대용량 첨부·주기작업), `.claude/deploy.md`
