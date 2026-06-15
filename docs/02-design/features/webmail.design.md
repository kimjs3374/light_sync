# Webmail Design Document

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 메일과 ERP가 분리되어 업무 전환 비용 발생 + Synology 메일서버 한계 |
| **WHO** | 매그나텍 LED 조명사업부 전 직원 (10~30명) |
| **RISK** | IMAP 연결 지연, HTML XSS, 비밀번호 유출, Synology 부하 |
| **SUCCESS** | ERP에서 메일 송수신, 공용계정 접근, 첨부파일 처리, 기존 발송 기능 유지 |
| **SCOPE** | Phase 1: ERP 웹메일 UI (Synology IMAP 연동) |

---

## 1. Overview

ERP 내장 웹메일. Flask + IMAP/SMTP 기반. Option C (실용적 균형) 아키텍처 선택.

**핵심 결정**: IMAP 클라이언트를 `mail_client.py`로 분리하여 Phase 2 Mailcow 전환 시 이 파일만 수정.

---

## 2. Architecture

### 2.1 파일 구조

```
routes/mail.py                      # Blueprint + 라우트 + 비즈니스 로직
modules/services/mail_client.py     # IMAP/SMTP 클라이언트 래퍼
modules/models/mail_entities.py     # DB 모델 (mail_accounts 등)
templates/mail_inbox.html           # 메일함 메인 화면
templates/mail_compose.html         # 메일 작성
templates/mail_read.html            # 메일 상세 보기
templates/mail_settings.html        # 계정/서명 설정
static/js/mail.js                   # 클라이언트 로직
static/css/mail.css                 # 스타일
```

### 2.2 의존 관계

```
routes/mail.py
  ├── modules/services/mail_client.py  (IMAP/SMTP 연결)
  ├── modules/models/mail_entities.py  (DB 모델)
  ├── modules/auth_decorators.py       (기존 인증)
  └── modules/db_context.py            (기존 DB)

mail_client.py
  ├── imapclient (pip)
  └── smtplib (stdlib)
```

---

## 3. Data Model

### 3.1 mail_accounts

```sql
CREATE TABLE light_sync.mail_accounts (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES light_sync.users(id),  -- NULL이면 공용계정
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    imap_host VARCHAR(255) NOT NULL DEFAULT '192.168.0.101',
    imap_port INT NOT NULL DEFAULT 993,
    smtp_host VARCHAR(255) NOT NULL DEFAULT '192.168.0.101',
    smtp_port INT NOT NULL DEFAULT 587,
    username VARCHAR(255) NOT NULL,
    password_encrypted TEXT NOT NULL,
    use_ssl BOOLEAN DEFAULT TRUE,
    is_shared BOOLEAN DEFAULT FALSE,
    signature TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.2 mail_shared_access

```sql
CREATE TABLE light_sync.mail_shared_access (
    id SERIAL PRIMARY KEY,
    mail_account_id INT NOT NULL REFERENCES light_sync.mail_accounts(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES light_sync.users(id),
    can_send BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mail_account_id, user_id)
);
```

### 3.3 mail_contacts

```sql
CREATE TABLE light_sync.mail_contacts (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES light_sync.users(id),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    company VARCHAR(200),
    memo TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.4 SQLAlchemy 모델 (mail_entities.py)

```python
class MailAccount(Base):
    __tablename__ = 'mail_accounts'
    __table_args__ = {'schema': 'light_sync'}
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('light_sync.users.id'), nullable=True)
    email = Column(String(255), nullable=False)
    display_name = Column(String(100))
    imap_host = Column(String(255), default='192.168.0.101')
    imap_port = Column(Integer, default=993)
    smtp_host = Column(String(255), default='192.168.0.101')
    smtp_port = Column(Integer, default=587)
    username = Column(String(255), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    use_ssl = Column(Boolean, default=True)
    is_shared = Column(Boolean, default=False)
    signature = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

class MailSharedAccess(Base):
    __tablename__ = 'mail_shared_access'
    __table_args__ = {'schema': 'light_sync'}
    
    id = Column(Integer, primary_key=True)
    mail_account_id = Column(Integer, ForeignKey('light_sync.mail_accounts.id'))
    user_id = Column(Integer, ForeignKey('light_sync.users.id'))
    can_send = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class MailContact(Base):
    __tablename__ = 'mail_contacts'
    __table_args__ = {'schema': 'light_sync'}
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('light_sync.users.id'))
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False)
    company = Column(String(200))
    memo = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

---

## 4. API Design (Routes)

### 4.1 페이지 라우트

| Method | URL | 함수 | 설명 |
|--------|-----|------|------|
| GET | `/mail` | `mail_inbox()` | 메일함 메인 (받은편지함) |
| GET | `/mail/folder/<folder>` | `mail_folder(folder)` | 특정 폴더 보기 |
| GET | `/mail/read/<int:uid>` | `mail_read(uid)` | 메일 상세 보기 |
| GET | `/mail/compose` | `mail_compose()` | 새 메일 작성 |
| GET | `/mail/compose?reply=<uid>` | `mail_compose()` | 답장 |
| GET | `/mail/compose?forward=<uid>` | `mail_compose()` | 전달 |
| GET | `/mail/settings` | `mail_settings()` | 계정/서명 설정 |
| GET | `/mail/contacts` | `mail_contacts()` | 주소록 |
| GET | `/mail/admin` | `mail_admin()` | 관리자 설정 |

### 4.2 API 라우트 (AJAX)

| Method | URL | 설명 |
|--------|-----|------|
| GET | `/mail/api/messages?folder=INBOX&page=1&per_page=50` | 메일 목록 JSON |
| GET | `/mail/api/messages/<uid>` | 메일 본문 JSON |
| POST | `/mail/api/send` | 메일 발송 |
| POST | `/mail/api/draft` | 임시저장 |
| POST | `/mail/api/move` | 폴더 이동 `{uids, dest_folder}` |
| POST | `/mail/api/flags` | 플래그 변경 `{uids, flag, action}` |
| DELETE | `/mail/api/messages` | 삭제 (휴지통 이동) `{uids}` |
| GET | `/mail/api/folders` | 폴더 목록 |
| POST | `/mail/api/folders` | 폴더 생성 `{name}` |
| DELETE | `/mail/api/folders/<name>` | 폴더 삭제 |
| GET | `/mail/api/search?q=keyword&folder=INBOX` | 메일 검색 |
| GET | `/mail/api/attachment/<uid>/<part_id>` | 첨부파일 다운로드 |
| POST | `/mail/api/upload` | 첨부파일 업로드 (임시) |
| GET | `/mail/api/contacts/suggest?q=keyword` | 주소록 자동완성 |
| POST | `/mail/api/account/switch` | 계정 전환 `{account_id}` |

### 4.3 계정 전환 로직

```
사용자 로그인 → session['user_id'] 확인
  → mail_accounts에서 user_id 매칭 (개인 계정)
  → mail_shared_access에서 user_id 매칭 (공용 계정 목록)
  → session['mail_account_id'] = 기본 개인 계정
  → 사이드바에 계정 드롭다운 표시 (개인 + 공용)
  → 계정 전환 시 /mail/api/account/switch 호출
```

---

## 5. mail_client.py 설계

### 5.1 클래스 구조

```python
class MailClient:
    """IMAP/SMTP 클라이언트 래퍼.
    
    Phase 1: Synology IMAP (192.168.0.101:993)
    Phase 2: Mailcow 전환 시 이 클래스만 수정
    """
    
    def __init__(self, imap_host, imap_port, smtp_host, smtp_port, 
                 username, password, use_ssl=True):
        self._imap = None
        self._config = { ... }
    
    # === IMAP 연결 관리 ===
    def connect_imap(self) -> IMAPClient:
        """IMAP 연결. with 문 지원."""
    
    def disconnect(self):
        """IMAP 연결 종료."""
    
    # === 폴더 ===
    def list_folders(self) -> list[dict]:
        """폴더 목록. [{name, delimiter, flags, unread_count}]"""
    
    def create_folder(self, name: str):
    def delete_folder(self, name: str):
    
    # === 메일 목록 ===
    def fetch_messages(self, folder='INBOX', page=1, per_page=50) -> dict:
        """메일 목록 조회.
        Returns: {messages: [...], total: int, page: int, pages: int}
        각 message: {uid, from, to, subject, date, flags, has_attachment, snippet}
        """
    
    def search_messages(self, query: str, folder='INBOX') -> list:
        """IMAP SEARCH로 메일 검색."""
    
    # === 메일 본문 ===
    def fetch_message(self, uid: int, folder='INBOX') -> dict:
        """메일 상세 조회.
        Returns: {uid, from, to, cc, subject, date, html_body, text_body, 
                  attachments: [{part_id, filename, size, content_type}]}
        """
    
    def fetch_attachment(self, uid: int, part_id: str, folder='INBOX') -> tuple:
        """첨부파일 바이너리 반환. Returns: (filename, content_type, bytes)"""
    
    # === 플래그/이동 ===
    def set_flags(self, uids: list, flag: str, action: str):
        """플래그 설정. flag: \\Seen, \\Flagged 등. action: add/remove"""
    
    def move_messages(self, uids: list, dest_folder: str, src_folder='INBOX'):
        """메일 폴더 이동."""
    
    def delete_messages(self, uids: list, folder='INBOX'):
        """휴지통으로 이동."""
    
    # === 발송 ===
    def send_message(self, from_addr, to, cc, bcc, subject, html_body, 
                     attachments=None) -> dict:
        """SMTP 발송. attachments: [(filename, bytes)]"""
    
    def save_draft(self, from_addr, to, subject, body, attachments=None):
        """Draft 폴더에 저장."""
```

### 5.2 비밀번호 암호화

```python
# modules/services/mail_client.py 내부

from cryptography.fernet import Fernet
import os

_FERNET_KEY = os.environ.get('MAIL_ENCRYPT_KEY', '')

def encrypt_password(plain: str) -> str:
    """메일 비밀번호 암호화 (Fernet)."""
    f = Fernet(_FERNET_KEY.encode())
    return f.encrypt(plain.encode()).decode()

def decrypt_password(encrypted: str) -> str:
    """메일 비밀번호 복호화."""
    f = Fernet(_FERNET_KEY.encode())
    return f.decrypt(encrypted.encode()).decode()
```

### 5.3 HTML Sanitizer

```python
import nh3

def sanitize_html(html_body: str) -> str:
    """메일 HTML 본문 XSS 방지.
    허용: 기본 태그 + img(src만) + style(인라인)
    차단: script, iframe, form, on* 이벤트
    """
    return nh3.clean(
        html_body,
        tags={'p','br','div','span','a','img','table','tr','td','th',
              'thead','tbody','b','i','u','strong','em','ul','ol','li',
              'h1','h2','h3','h4','h5','h6','blockquote','pre','code','hr'},
        attributes={
            'a': {'href', 'title'},
            'img': {'src', 'alt', 'width', 'height'},
            '*': {'style', 'class'},
        },
        url_schemes={'http', 'https', 'cid'},  # cid: 인라인 이미지
    )
```

---

## 6. UI Design

### 6.1 메일함 메인 (mail_inbox.html)

**데스크톱: 3컬럼 레이아웃**

```
┌──────────────────────────────────────────────────────────────────┐
│ [계정 드롭다운: 김철수 <kim@mgnt.kr> ▼]  [🔍 검색]  [✏️ 새 메일] │
├────────┬──────────────────────┬───────────────────────────────────┤
│ 폴더   │ 메일 목록             │ 미리보기                          │
│        │                      │                                   │
│📥 받은(3)│ ☐ 김철수 14:30      │ From: 김철수 <kim@company.com>    │
│📤 보낸  │   견적서 요청 건      │ To: 나 <me@mgnt.kr>              │
│📝 임시  │ ☐ 이영희 13:15      │ Date: 2026-04-01 14:30           │
│🗑️ 휴지통│   납품일정 확인       │                                   │
│        │ ☐ 박민수 11:00      │ 안녕하세요, 견적서 요청드립니다...  │
│── 공용 ─│   회의록 공유         │                                   │
│📮purchase│                     │ 📎 견적요청서.xlsx (245KB)        │
│📮info   │                      │                                   │
│        │ [◀ 1 / 5 ▶]        │ [↩️답장] [↩️전체] [➡️전달] [🗑️]   │
└────────┴──────────────────────┴───────────────────────────────────┘
```

**모바일: 1컬럼 (목록 → 상세 전환)**

```
┌─────────────────────────┐
│ 📥 받은편지함 (3)  [✏️] │
│ [계정: kim@mgnt.kr ▼]   │
├─────────────────────────┤
│ 김철수         14:30  📎│
│ 견적서 요청 건           │
│─────────────────────────│
│ 이영희         13:15    │
│ 납품일정 확인            │
│─────────────────────────│
│ 박민수         11:00    │
│ 회의록 공유              │
└─────────────────────────┘
```

### 6.2 메일 작성 (mail_compose.html)

```
┌──────────────────────────────────────────────┐
│ 새 메일 작성                           [보내기] │
├──────────────────────────────────────────────┤
│ 보내는 사람: [kim@mgnt.kr ▼]                  │
│ 받는 사람:   [자동완성 입력 _______________]   │
│ 참조(CC):    [자동완성 입력 _______________]   │
│ 숨은참조:    [자동완성 입력 _______________]   │
│ 제목:        [___________________________]   │
├──────────────────────────────────────────────┤
│ [B] [I] [U] [링크] [이미지]   편집 도구바     │
│                                              │
│ 본문 영역                                     │
│                                              │
│                                              │
├──────────────────────────────────────────────┤
│ 📎 첨부파일: 견적서.pdf (2.1MB) [x]           │
│ [+ 파일 추가]                                 │
├──────────────────────────────────────────────┤
│ -- 서명 --                                    │
│ 김철수 대리 | 매그나텍 LED조명사업부             │
│ T. 031-xxx-xxxx | kim@mgnt.kr               │
└──────────────────────────────────────────────┘
```

### 6.3 AJAX 동작 흐름

```
1. 페이지 로드 → /mail/api/folders (폴더 목록 + 읽지않은 수)
2. 폴더 클릭 → /mail/api/messages?folder=X&page=1 (목록)
3. 메일 클릭 → /mail/api/messages/<uid> (본문) + 자동 읽음 처리
4. 삭제 버튼 → DELETE /mail/api/messages {uids} (휴지통 이동)
5. 보내기 → POST /mail/api/send (multipart/form-data)
6. 주소 입력 → GET /mail/api/contacts/suggest?q=김 (자동완성)
```

---

## 7. Security

### 7.1 인증/권한
- 모든 /mail/* 라우트: `@login_required` + `@menu_required('webmail')`
- 공용계정 접근: `mail_shared_access` 테이블 기반 권한 확인
- API 라우트: CSRF 토큰 검증 (기존 csrf-inject.js 활용)

### 7.2 데이터 보호
- IMAP 비밀번호: Fernet 대칭 암호화 (`MAIL_ENCRYPT_KEY` 환경변수)
- HTML 본문: `nh3` sanitizer로 XSS 차단
- 첨부파일: Content-Disposition 헤더 강제, MIME 타입 검증
- 메일 목록 API: 본인 계정 + 공유 권한 확인

### 7.3 IMAP 연결
- SSL/TLS 필수 (포트 993)
- 연결 타임아웃 30초
- 에러 시 사용자에게 generic 메시지 (서버 정보 노출 방지)

---

## 8. Performance

### 8.1 IMAP 최적화
- 메일 목록: ENVELOPE + FLAGS만 FETCH (BODY 제외) → 빠른 목록 로딩
- 본문: 클릭 시에만 BODY FETCH
- 첨부파일: 스트리밍 다운로드 (메모리 절약)
- 연결: 요청 당 connect/disconnect (연결 풀은 복잡성 대비 효과 적음)

### 8.2 프론트엔드
- 메일 목록: AJAX 페이징 (50건 단위)
- 미리보기 패널: 클릭 시 AJAX 로드
- 폴더 목록: 30초 간격 자동 갱신 (안읽은 메일 수)
- 모바일: 목록/상세 전환 (3컬럼 → 1컬럼)

---

## 9. Integration

### 9.1 기존 시스템 연동
- `config.py` MENU_REGISTRY에 `webmail` 항목 추가 (공통메뉴 그룹)
- `app.py`에 `mail_bp` Blueprint 등록
- `.env`에 `MAIL_ENCRYPT_KEY` 추가
- `requirements.txt`에 `imapclient`, `nh3`, `cryptography` 추가
- 기존 `email_sender.py`는 수정 없음 (발주서 발송은 기존 방식 유지)
- 기존 `EmailSignature` 모델 → `mail_accounts.signature`로 통합 검토

### 9.2 Mailcow 전환 시 변경점 (Phase 2)
- `mail_client.py`: 서버 주소/포트만 변경 (IMAP/SMTP 프로토콜 동일)
- `mail_accounts` 테이블: host 필드 일괄 업데이트
- `.env`: SMTP_HOST 변경 (기존 email_sender도 Mailcow로)
- DNS: MX/SPF/DKIM 레코드 변경

---

## 10. Dependencies

### 10.1 새로 설치

```
pip install imapclient nh3 cryptography
```

| 패키지 | 용도 | 크기 |
|--------|------|------|
| `imapclient` | IMAP 클라이언트 (imaplib 래퍼) | ~100KB |
| `nh3` | HTML sanitizer (Rust 기반, 빠름) | ~2MB |
| `cryptography` | Fernet 대칭 암호화 | ~40MB (이미 설치 가능) |

### 10.2 환경변수 추가

```
# .env
MAIL_ENCRYPT_KEY=<Fernet.generate_key()로 생성>
```

---

## 11. Implementation Guide

### 11.1 구현 순서

| # | 모듈 | 파일 | 예상 규모 |
|---|------|------|----------|
| 1 | DB 모델 + 마이그레이션 | `mail_entities.py` + SQL | ~100줄 |
| 2 | IMAP/SMTP 클라이언트 | `mail_client.py` | ~350줄 |
| 3 | 라우트 (페이지 + API) | `routes/mail.py` | ~500줄 |
| 4 | 메일함 UI | `mail_inbox.html` + `mail.js` + `mail.css` | ~800줄 |
| 5 | 메일 작성 UI | `mail_compose.html` | ~300줄 |
| 6 | 설정/주소록 | `mail_settings.html` | ~200줄 |
| 7 | 앱 등록 + 메뉴 | `app.py` + `config.py` | ~20줄 |

**총 예상**: ~2,300줄, 8개 파일 생성 + 3개 파일 수정

### 11.2 파일별 상세

**생성 파일:**
1. `modules/models/mail_entities.py` — MailAccount, MailSharedAccess, MailContact 모델
2. `modules/services/mail_client.py` — MailClient 클래스 + encrypt/decrypt + sanitize
3. `routes/mail.py` — mail_bp Blueprint, 페이지 라우트 + API 라우트
4. `templates/mail_inbox.html` — 3컬럼 메일함 (폴더/목록/미리보기)
5. `templates/mail_compose.html` — 메일 작성 (답장/전달 포함)
6. `templates/mail_settings.html` — 계정 설정 + 서명 + 공용계정 관리
7. `static/js/mail.js` — AJAX 호출, 목록/미리보기 제어, 자동완성
8. `static/css/mail.css` — 3컬럼 레이아웃, 메일 목록 스타일

**수정 파일:**
1. `app.py` — mail_bp import + register_blueprint
2. `config.py` — MENU_REGISTRY에 webmail 추가
3. `requirements.txt` — imapclient, nh3, cryptography 추가

### 11.3 Session Guide

| Session | 모듈 | Scope Key | 의존성 |
|---------|------|-----------|--------|
| Session 1 | DB + 클라이언트 + 앱등록 | `module-1` | 없음 |
| Session 2 | 메일함 UI (목록 + 읽기) | `module-2` | module-1 |
| Session 3 | 메일 작성 (발송 + 답장) | `module-3` | module-2 |
| Session 4 | 설정/주소록/관리자 | `module-4` | module-3 |

**권장**: Session 1~2를 한 세션에서 처리 (기반 + 메일 읽기까지 확인 가능)
