# 메일 SPA (`mail.mgnt.kr`) — 구조와 함정

2026-09-15 작업. 기존 메일 화면(`/mail`)은 **그대로 두고** 새 화면을 나란히 올렸다.
같은 날 새 화면을 `work.mgnt.kr/webmail/` 에서 **`mail.mgnt.kr` 전용 호스트로 옮겼다**(§0).

---

## 0. 주소가 옮겨졌다 — mail.mgnt.kr

| | 지금 |
|---|---|
| 정식 주소 | **`https://mail.mgnt.kr/`** — 루트가 곧 메일 화면 |
| 옛 주소 | `work.mgnt.kr/webmail/` → **301** 로 넘김 |

- `mail.mgnt.kr` 은 **원래 있던 이름이다** — `mgnt.kr` 의 MX(메일 서버)다.
  건드린 건 443 뿐이고 **25/587/993 스트림과는 겹치지 않는다.**
  443 은 예전에 시놀로지 webmail 로 가다 인증서 만료로 끊긴 자리다(VPS `stream` 맵 주석).
- 백엔드는 **work 와 같은 ERP(8501)** 한 벌이다. 앱이 `Host` 를 보고 갈린다
  (`app.py` 의 `_is_mail_host()` / `MAIL_APP_HOST`). 새 서비스·새 포트는 없다.
- **번들 base 는 여전히 `/webmail/`** 이다. `mail.mgnt.kr/` 이 내주는 index.html 이
  `/webmail/assets/*` 를 부른다 → `serve_mail_app()` 은 **호스트를 가리지 않고 파일을 내주고,
  화면 진입(index.html)만** mail 호스트로 모은다. 옛 탭이 자산을 계속 받을 수 있는 이유다.
- **세션 쿠키는 호스트별이다.** 그래서 로그인을 **건네받는다**(`/api/app/handoff`):

  ```
  mail.mgnt.kr/ 부팅 → session-token 401
    → https://work.mgnt.kr/api/app/handoff?to=https://mail.mgnt.kr/
        (work 에 세션 있으면 60초짜리 코드 발급 / 없으면 ERP 로그인부터 → 되돌아옴)
    → https://mail.mgnt.kr/api/app/handoff-land?code=…&next=/
    → mail 호스트에 세션 생성 → /
  ```

  `SESSION_COOKIE_DOMAIN = '.mgnt.kr'` 한 줄이면 끝나지만 **쓰지 않았다** —
  그러면 ERP 세션 쿠키가 team(mattermost)·cloud·docs·db 등 남의 서비스에까지
  매 요청 실려 가고, 플라스크 쿠키는 서명만 돼 있어 **권한 목록까지 읽힌다.**

  - `to` 는 **허용 호스트 목록**으로 묶는다(`_handoff_hosts()`). 없으면 남의 주소로
    코드를 흘리는 열린 리다이렉트가 된다.
  - 코드는 상태 없는 HMAC 이고 **수명 60초**다. 일회성은 아니다.
  - SPA 는 **한 번만** 건네받으려 한다(`sessionStorage` 의 `erp_handoff_tried`).
    받고도 세션이 안 잡히면 그대로 무한히 돈다.
  - **`goLogin()` 은 한 페이지에서 한 번만 나간다.** 401 은 겹쳐서 떨어지는데,
    뒤엣것이 앞의 이동을 취소해 이어받기가 실제로 끊겼다(`net::ERR_ABORTED`).
  - 로그아웃은 아직 호스트별이다 — **ERP 에서 로그아웃해도 메일 세션은 남는다**(최대 8시간).
- 로그인 복귀 주소는 **지금 서 있는 경로**를 쓴다(`window.location.pathname`).
  호스트마다 엔트리가 `/` 와 `/webmail/` 로 달라서다. 새 버전 감지(`isStaleBuild`)도 같다.
- 301 은 **브라우저가 영구 캐시한다.** 되돌리려면 사용자 캐시가 걸림돌이다
  (`app.py` 의 `code=301` 한 자리).
- **호스트를 건너가는 링크는 주소를 박는다** (`src/lib/erp.js`) — 왼쪽 위 로고는
  `MAIL_ORIGIN`(메일 첫 화면), 그 옆 `ERP ↗` 는 `erpUrl()`.
  상대경로로 두면 "ERP로 돌아가기" 가 메일을 다시 여는 꼴이 된다 — 여기선 `/` 가 메일이다.
  반대로 **메일 본문에 실려 나가는 대용량 첨부 링크는 여기와 무관하다** —
  그쪽은 `.env` 의 `FLASK_DOMAIN`(= work.mgnt.kr)을 본다(`routes/mail.py`).

nginx 는 두 군데를 같이 손댔다.

| 어디 | 무엇 |
|---|---|
| VPS `/etc/nginx/nginx.conf` | `listen 4443 ssl; server_name mail.mgnt.kr;` → `100.110.60.7:8501` (work 와 같은 대용량 설정) |
| webserver `sites-available/lan-direct.conf` | work 블록 `server_name` 에 `mail.mgnt.kr` 추가 (사내 DNS 가 가리키면 tailnet 을 건너뛴다) |

---

## 1. 화면이 둘이다

| | 경로 | 코드 | 상태 |
|---|---|---|---|
| 기존 | `/mail`, `/mail/personal`, `/mail/compose` … | `templates/mail_*.html` + `static/js/mail.js` | 유지 (익숙한 사용자용) |
| 신규 | **`mail.mgnt.kr/`** (자산은 `/webmail/`) | `mail_app/` (Vite + React + zustand) | 3-pane 목록·읽기창, 작성 페이지 |

**둘은 같은 `/mail/api/*` 를 공유한다.** 백엔드는 한 벌이므로 API 수정은 양쪽에 같이 먹지만,
화면 동작은 완전히 다르다. **버그 제보가 오면 어느 화면인지부터 확인한다.**

- 빌드: `cd mail_app && npm run build` → `mail_app/dist/` (git 제외, 서버에서 빌드)
- 서빙: `app.py` 의 `serve_mail_app()` + `index()` 의 호스트 분기 — `/m/` 모바일 SPA 와 같은 방식.
  메일 호스트는 **모바일 판별보다 먼저** 본다 — 메일 주소로 들어온 사람에게 `/m/` 은 엉뚱하다.
- 인증: **Bearer 토큰**. 부팅 때 `/api/app/session-token` 으로 PC 세션을 한 번 교환한다.
  세션 쿠키를 안 쓰니 CSRF 토큰이 필요 없다.

### SPA 는 새로고침 전까지 옛 코드를 돈다

재배포해도 열어둔 탭은 그대로다. 겉보기엔 멀쩡한데 **새 기능만 조용히 안 먹는다.**
실제로 대용량 첨부 링크가 이 때문에 빠져서 한참 헤맸다. 번들 파일명이 바뀌면 상단에 띠를
띄우는 `StaleBanner` 를 넣어뒀다. **"안 된다"는 제보가 오면 새로고침부터 시켜본다.**

### 메일함 구성

- **받은편지함 / 내게쓴메일함은 같은 INBOX 를 주소로 나눈다** (`NOT FROM "내주소"` / `FROM "내주소"`)
- 안읽음 뱃지도 같은 조건으로 따로 센다. **`/mail/api/folders` 의 숫자는 쓰지 않는다** —
  워커별 메모리 캐시라 8워커가 서로 다른 값을 준다
- 예약 발송함은 IMAP 폴더가 아니라 `light_sync.mail_scheduled` 를 보여주는 화면이다
- 본문 편집기는 라이브러리 없이 `contenteditable` + `execCommand`.
  의존성은 `react`·`react-dom`·`zustand` 셋뿐 — **UI 라이브러리를 새로 넣지 않는다**

---

## 1-2. 검색 — 기본 · 상세

| | 무엇 | 어디 |
|---|---|---|
| 기본 | 한 낱말을 제목·보낸사람·본문 여러 자리에서 훑는다(OR) | `/mail/api/search` |
| 상세 | 조건을 **모두** 만족하는 것만 남긴다(AND) | `/mail/api/search-advanced` |

상세검색 조건: 보낸사람·받는사람·제목·본문·기간·첨부있음·안읽음·중요.

- **IMAP 검색식은 문자열로 이어붙이지 않는다.** `client.search_advanced()` 에 imapclient
  규격의 **리스트**를 넘긴다 — 따옴표와 한글(UTF-8)은 imapclient 가 처리한다.
  `f'FROM "{addr}"'` 로 만들면 값에 따옴표가 섞이는 순간 검색이 통째로 깨진다.
- `BEFORE` 는 그 날을 포함하지 않는다 — 종료일까지 담으려면 **하루 뒤로 민다.**
- IMAP 에 "첨부 있음" 조건은 없다. 목록이 첨부 아이콘을 띄울 때 보는 것과 같은 잣대
  (`HEADER Content-Type multipart/mixed`)를 쓴다 — 그래야 결과와 아이콘이 어긋나지 않는다.
- **받은편지함/내게쓴메일함은 같은 INBOX 다.** 검색도 그 칸 안에서만 찾아야 하므로
  화면이 `self=exclude|only` 를 보내고 서버가 계정 주소로 `NOT FROM` 을 덧붙인다.
  (기본 검색은 이 구분을 아직 안 한다 — 내게쓴메일이 섞여 나온다)
- 결과는 **최신순 200건까지**. 잘리면 `truncated` 로 알려주고 화면이 그렇게 적는다.
- uid 만 주지 않고 **메시지까지 채워서** 준다 — 목록이 그대로 그릴 수 있어야 한다.
- 조건이 하나도 없으면 400 이다. `ALL` 로 넘어가면 그냥 목록이지 검색이 아니다.

### 툴바 배치

검색·상세·새로고침은 **목록 칸 위**에 둔다(`.list-tools`). 예전엔 `margin-left: auto` 로
읽기창 쪽 끝에 밀려 있어서 **무엇에 대한 검색인지 읽히지 않았다.**
목록 밀도(크게 52 / 보통 42 / 좁게 34px)만 오른쪽 끝이다 — 목록을 다루는 게 아니라 보기 설정이다.

상세검색이 걸리면 **무엇으로 걸렀는지 조건 딱지를 결과 위에 남긴다.** 안 남기면
"왜 이것만 나오는지" 를 화면 어디에서도 읽을 수 없다.

---

## 1-3. 메일쓰기 — 임시저장 상태

닫기(✕) 바로 아래에 **저장했는가 · 몇 번째인가 · 언제인가** 를 함께 띄운다
(`DraftStatus.jsx`). 나가기 전에 마지막으로 눈에 들어와야 하는 게 "저장됐는가"다.

| 표시 | 뜻 |
|---|---|
| 임시저장 안 됨 | 아직 한 번도 안 눌렀다 |
| 저장 중… | 보내는 중 |
| **저장됨** + `v2 · 16:59:10` | 2번째 임시저장, 그 뒤로 손대지 않았다 |
| **저장 후 변경됨** + `v2 · 16:59:10` | 저장한 뒤 내용을 고쳤다 |

- **임시저장은 손으로 눌러야 된다 — 자동저장이 없다.** 그래서 눌렀는지 아닌지가
  화면에 남아야 한다.
- 고쳤는지는 **내용 지문**(`draftSignature()`)으로 가린다. 저장한 순간의 지문을 들고
  있다가 지금 것과 다르면 '변경됨'이다. 첨부는 파일 자체가 아니라 이름·크기만 본다.
- **지문은 요청을 보내기 직전의 내용으로 뜬다.** 응답이 온 시점에 뜨면 저장이 오가는
  동안 고친 것을 "저장됨"으로 삼켜버린다.
- `v` 는 저장 **횟수**다. 서버에는 임시본이 한 통만 남는다(`replace_uid` 로 갈아끼운다).
- 예약 메일 수정(`editScheduled`)에는 안 띄운다 — 거긴 임시저장이 아니라 예약본 고치기다.

**아직 어긋나 있는 것**: 닫기(✕)의 "쓰던 메일이 사라집니다" 경고는 `initial`(열었을 때)과
비교한다. 임시저장을 해둬도 경고가 뜬다 — 이제 지문이 있으니 맞출 수 있다.

---

## 2. 대용량 첨부 (25MB 초과)

메일에 싣지 않고 링크로 보낸다.

```
① 파일을 붙이는 즉시 → Storage 의 mail-temp/ 로 업로드 (아직 DB 레코드 없음)
② 발송/예약이 확정되면 → mail-attachments/ 로 이동(move API, 재업로드 아님)
                         mail_large_files 레코드 + 본문에 링크표 삽입
③ 취소·첨부 제거·탭 닫기 → mail-temp/ 에서 삭제 (놓친 건 매일 03시 cron)
```

### 업로드 경로가 셋

| 크기 | 방식 | 우리 서버 경유 |
|---|---|---|
| ~90MB | 서명 URL 단일 PUT (`/mail/api/upload-sign`) | 안 함 |
| 90MB 초과 | TUS 재개 업로드 48MB 조각 (`/mail/api/upload-token`) | 안 함 |
| 위가 막히면 | 조각 업로드 (`upload-chunk` → `upload-finish`) | 경유 |

브라우저가 Supabase 로 직접 쏜다. service 키는 내주지 않고 서버가 **30분짜리 JWT** 를 발급한다
(`SUPABASE_JWT_SECRET`). 그 토큰으로 되는 건 `company-files/mail-temp/` 아래 쓰기뿐이다 —
`storage.objects` 정책 3개를 넣었다(`sql_editer.sql` 참조).

### 함정

- **막히면 어디서 막혔는지부터 가른다.** 서버 로그에 요청 흔적이 **아예 없으면** 앞단이 막은 것이다
  (Cloudflare 100MB, VPS nginx `client_max_body_size`). 흔적이 있으면 우리 코드다.
- VPS nginx 에도 `client_max_body_size 100m` 이 있었다. `work`·`api` 블록만 `0` 으로 풀고
  **`proxy_request_buffering off`** 를 넣었다. 이게 없으면 VPS 가 파일을 다 받은 다음에야
  전달해서 두 배로 느리다.
- TUS 의 `Location` 헤더는 **스토리지 내부 주소(127.0.0.1:8000)** 를 가리킨다. 경로만 떼어 쓴다.
- 진행률은 **XHR 로 받는다.** `fetch` 는 업로드 진행률을 안 준다 — 처음엔 48MB 조각이 끝날 때만
  갱신돼 33%씩 튀었다.
- **조각 임시폴더에 `/tmp` 를 쓰지 않는다.** systemd PrivateTmp 때문에 서비스마다 `/tmp` 가
  따로 보여 조각을 못 찾는다. `/web/light_sync/.upload_tmp/` 를 쓴다.

### 오래 걸린 버그 하나 — 같은 실수 반복 금지

`api_send()` **함수 안에** `import json` 이 있었다. 파이썬은 함수 안 어디든 import 가 있으면
**그 함수 전체에서 지역변수로 취급**한다 → 함수 앞부분의 `json.loads()` 가 `UnboundLocalError`.
거기에 `try/except Exception` 을 씌워둬서 **오류가 조용히 삼켜지고, 첨부 링크만 사라진 채
메일이 정상 발송됐다.**

→ **부가 데이터를 파싱하는 except 는 반드시 로그를 남긴다.** 조용히 넘기면 기능이 통째로 없어진다.

---

## 3. 주기작업은 crontab 뿐

`app.py` 끝의

```python
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    init_scheduler(app)
```

가 **실행되지 않는다.** `.env` 에 `FLASK_ENV=development` · `FLASK_DEBUG=true` 가 있어
`app.debug` 가 True 이기 때문이다.

로그의 마지막 `[scheduler] 백그라운드 스케줄러 시작` 이 **2026-03-31** 이었다.
**예약발송이 그때부터 한 번도 실행되지 않았다.** 기능이 안 되니 아무도 안 써서 아무도 몰랐다.

**켜서도 안 된다.** gunicorn 이 `-w 8` 이라 워커 8개가 각자 타이머를 돌려 같은 메일이 8번 나간다.

- 주기작업은 `@app.cli.command()` 로 만들고 crontab 에 건다 (이미 15개가 그렇게 돈다)
- **`cd /web/light_sync &&` 를 빠뜨리면** flask 가 app.py 를 못 찾아
  `Error: No such command` 로 조용히 실패한다
- `modules/scheduler.py` 에 자동회신·자동전달(5분) job 이 아직 남아 있다 — **이것도 안 돌고 있다**
- 정리 작업은 `cleanup-mail-files`(매일 03:00) 하나로 모았다: 만료 첨부 + 하루 지난
  `mail-temp/` + `.upload_tmp/` 찌꺼기

---

## 4. 네트워크 경로 (속도 문제는 여기부터 본다)

2026-09-15 실측. **코드에서 찾지 말 것 — 경로가 원인이었다.**

Cloudflare **무료 플랜**이 `mgnt.kr` 을 **미국 서부(SJC/LAX)** 에서 처리하고 있었다.
한국(ICN) 회선비 때문에 무료 존은 서울 엣지를 안 준다. 매 요청이 태평양을 왕복했다.

| | 전 | 후 |
|---|---|---|
| 요청 1건 평균 | 0.690초 | **0.107초** |
| 연결 지연 | 135ms | **22ms** |

→ `work.mgnt.kr` · `api.mgnt.kr` 을 **DNS only** 로 뺐다.
공개 홈페이지 `magnatech.co.kr` 은 Cloudflare 유지 — **공격이 오는 곳과 속도가 필요한 곳이 다르다.**

### 구간별 속도

| 구간 | 실측 |
|---|---|
| webserver ↔ Supabase (같은 장비) | 943 Mbps |
| 사무실 회선 | 403↑ / 435↓ Mbps |
| VPS 회선 | 633↑ / 1630↓ Mbps |
| **VPS ↔ webserver (tailnet)** | **147 Mbps ← 병목** |

tailscale 은 사용자 공간 암호화라 회선의 1/3 밖에 못 낸다. **MTU 1420 은 효과 없었다**(되돌림).

그래서 사내 사용자는 tailnet 을 건너뛴다 — `lan.mgnt.kr` 을 **공개 DNS 에 사설 IP(192.168.0.110)로**
등록했다. 밖에서는 연결이 안 되므로 서버가 **접속 IP 를 보고 사내에게만** 내준다
(`routes/mail.py` 의 `_is_lan_client()`).

**48MB 업로드: 5.5 → 14 → 106 MB/s**

### 알아둘 것

- 사무실 공유기는 **80/443 다 닫혀 있다**(VPS 가 공인 IP + tailnet). 포트를 열 필요 없다.
- VPS 접속: `ssh -i ~/.ssh/id_mgnt root@100.101.44.75`.
  nginx 설정은 **`/etc/nginx/nginx.conf` 한 파일**에 다 있다(sites-enabled 는 비어 있음).
  443 은 `ssl_preread` 로 SNI 를 보고 내부 4443 으로 넘기는 스트림 프록시다.
- 인증서는 VPS 가 발급·갱신한다(`*.mgnt.kr`). webserver 는 `/usr/local/bin/sync-mgnt-cert.sh`
  가 매일 04:40 에 받아온다 — 받은 게 진짜 인증서인지 확인한 뒤에만 교체한다.
- **서버에서 속도를 재면 회선을 두 번 쓴다**(나갔다 되돌아옴). 실제 사용자보다 느리게 나온다.
  구간별로 나눠 재야 병목이 보인다.
