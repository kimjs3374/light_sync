# 배포 반영 — 고쳐도 저절로 살아나지 않는다

```
ExecStart=/web/light_sync/venv/bin/gunicorn -w 8 -b 0.0.0.0:8501 --timeout 1800 --worker-class sync app:app
```

`--reload` 가 없다. 그리고 운영 모드라 **Jinja 템플릿도 첫 로드 뒤 메모리에 캐시된다**
(`TEMPLATES_AUTO_RELOAD` 가 `app.debug` 를 따라간다).

| 고친 것 | 반영 시점 |
|---|---|
| `static/**` (JS·CSS) | **즉시** — 디스크에서 그대로 서빙 |
| `routes/*.py`, `modules/**` | `sudo systemctl restart light_sync` |
| `templates/*.html` | 〃 (**캐시라 파일만 바꿔선 안 바뀐다**) |
| `mail_app/**` (SPA) | `cd mail_app && npm run build` — 재시작 불필요 (정적 파일) |

## 여기서 착시가 생긴다

2026-09-15 메일 작업에서 JS 로 만든 사이드바 버튼은 바로 보이는데, 그 버튼이 여는 화면의
템플릿·라우트는 9/5 기동분 그대로였다. 화면에는 **"버튼은 생겼는데 눌러도 아무 일이 없다"** 로만
보여서 코드 버그로 한참 의심했다.

## 지켜야 할 것

- **작업 전에 지금 서버에 뭐가 떠 있는지 먼저 본다.**
  `systemctl show light_sync -p ActiveEnterTimestamp` — 기동 시각이 내 편집보다 앞서면 구버전이다.
  새 라우트는 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501/<경로>` 로 확인한다.
  **404 면 라우트 자체가 안 올라간 것**, 302(→/login) 면 올라간 것이다.

- **재시작은 임의로 하지 않는다.** 업무시간에 도는 실서비스다. 김정수에게 확인받고 한다.

- 재시작 뒤엔 `systemctl is-active` + `journalctl -u light_sync --since "1 minute ago" | grep -i error` 까지 본다.

- 브라우저 쪽은 따로다. `mail_inbox.html`·`mail_read.html` 은 `mail.js` 를 `?v=<숫자>` 로
  캐시버스팅하니 **JS 를 고치면 그 숫자도 같이 올린다**
  (`mail_compose.html` 은 매번 난수라 신경 안 써도 된다).

- **SPA(`/webmail`)는 새로고침 전까지 옛 코드를 돈다.** 빌드해도 열어둔 탭은 그대로다.
  번들 파일명이 바뀌면 띠를 띄우는 `StaleBanner` 가 있지만, 제보가 오면 새로고침부터 시켜본다.

관련: `.claude/webmail.md`, `.claude/mail_send_paths.md`
