# Webmail Feature Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | ERP 내장 웹메일 |
| 작성일 | 2026-04-01 |
| 목표 | Synology → Mailcow 메일서버 전환 + ERP 통합 웹메일 UI 구축 |

### Value Delivered

| 관점 | 설명 |
|------|------|
| **Problem** | 현재 다우오피스/Synology 웹메일을 별도로 사용해야 하며, ERP 업무와 메일이 분리되어 업무 전환 비용 발생 |
| **Solution** | ERP 내에 IMAP/SMTP 기반 웹메일 통합, Mailcow로 메일서버 자체 운영 |
| **Function UX Effect** | ERP 사이드바에서 바로 메일 확인/발송, 업무 컨텍스트 전환 없이 메일 처리 |
| **Core Value** | 업무 도구 일원화로 생산성 향상 + 메일서버 자체 운영으로 외부 서비스 의존도 제거 |

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 메일과 ERP가 분리되어 업무 전환 비용 발생 + Synology 메일서버 한계(스팸 사건, 관리 어려움) |
| **WHO** | 매그나텍 LED 조명사업부 전 직원 (10~30명) |
| **RISK** | 메일 이전 시 데이터 유실, Mailcow 포트 충돌, 기존 발송 기능 호환성 |
| **SUCCESS** | ERP에서 메일 송수신 가능, Mailcow 안정 운영, 기존 purchase@ 발송 기능 유지 |
| **SCOPE** | Phase 1: ERP 웹메일 UI (현재 Synology IMAP 연동) → Phase 2: Mailcow 전환 + 마이그레이션 |

---

## 1. 배경 및 목적

### 1.1 현재 상황
- 메일서버: Synology MailPlus (192.168.0.101)
- 외부 수신: VPS(158.247.210.252) → Tailscale → Synology
- 발송: Synology → glb.kr 릴레이 경유 (사무실 IP CSS 블랙)
- ERP 발송: 192.168.0.101:25 직접 연결 (purchase@ 발주서 발송 등)
- 웹메일: 다우오피스 또는 Synology MailPlus 웹 별도 접속
- 문제: 2026-03-31 스팸 사건으로 사무실 IP 블랙리스트 등록

### 1.2 목표
1. **ERP 내장 웹메일**: ERP 로그인 후 바로 메일 사용
2. **Mailcow 전환**: 192.168.0.110에 이미 설치된 Mailcow 활성화
3. **Synology 메일서버 폐기**: 최종적으로 Synology에서 메일 서비스 제거

### 1.3 단계별 로드맵
- **Phase 1** (현재): ERP 웹메일 UI 개발 — Synology IMAP/SMTP 연동으로 테스트
- **Phase 2**: Mailcow 기동 + 계정/메일 마이그레이션
- **Phase 3**: DNS/라우팅 전환 + Synology 메일 폐기

---

## 2. 요구사항

### 2.1 기능 요구사항

#### 메일 읽기
- [ ] 받은편지함 목록 (발신자, 제목, 날짜, 읽음/안읽음, 첨부여부)
- [ ] 보낸편지함 목록
- [ ] 폴더 관리 (IMAP 폴더 목록 표시, 생성/삭제/이동)
- [ ] 메일 본문 보기 (HTML 렌더링, 인라인 이미지)
- [ ] 첨부파일 다운로드
- [ ] 메일 검색 (제목, 발신자, 본문)
- [ ] 페이징 / 무한스크롤

#### 메일 쓰기
- [ ] 새 메일 작성 (To, CC, BCC, 제목, 본문)
- [ ] 답장 / 전체답장 / 전달
- [ ] 첨부파일 업로드
- [ ] 서명 설정 (사용자별)
- [ ] 임시저장 (Draft 폴더)

#### 메일 관리
- [ ] 메일 삭제 (휴지통 이동)
- [ ] 읽음/안읽음 표시
- [ ] 별표/중요 표시
- [ ] 폴더 간 이동

#### 계정 관리
- [ ] 1인 1계정: ERP 사용자 ↔ 개인 메일계정(IMAP/SMTP) 연동
- [ ] 공용계정 접근: purchase@, info@ 등 공용 메일함 지원
  - 관리자가 공용계정 IMAP/SMTP credential을 `mail_accounts(is_shared=true)`에 등록
  - `mail_shared_access` 테이블로 접근 가능 사용자 지정 (can_send, can_delete 권한)
  - 사용자는 공용계정 비밀번호를 몰라도 ERP 로그인만으로 접근
  - 실제 IMAP/SMTP 연결은 공용계정 credential로 수행 (사용자에게 투명)
- [ ] Alias 수신: alias 주소로 온 메일이 본인 메일함에 도착 (메일서버 측 설정)
- [ ] 관리자 설정: 사용자별 메일 서버 정보 일괄 관리 (admin)
- [ ] 내정보에서 개인 메일 설정 가능 (서명, 표시이름 등)
- [ ] 공용계정 발송 시 From 헤더에 공용주소 사용 (개인주소 노출 안 됨)

#### 주소록
- [ ] ERP 직원 목록 자동 연동 (사내 주소록)
- [ ] 외부 연락처 수동 등록
- [ ] 메일 작성 시 자동완성

### 2.2 비기능 요구사항
- IMAP 연결 풀링 또는 캐싱으로 성능 확보
- 메일 본문 HTML 렌더링 시 XSS 방지 (sanitize)
- IMAP 비밀번호 암호화 저장
- 기존 `email_sender.py` 발송 기능과 호환 유지
- 모바일 반응형 (Bootstrap 5 기반)

### 2.3 제외 범위 (Phase 1)
- 캘린더/일정 연동
- 메일 규칙/필터 자동화
- POP3 지원 (IMAP만)
- 메일 암호화 (PGP/S-MIME)
- Mailcow 마이그레이션 (Phase 2)

---

## 3. 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | Flask + Python `imaplib` / `smtplib` / `email` 표준 라이브러리 |
| Frontend | Jinja2 + Bootstrap 5 + 기존 ERP UI 패턴 |
| 메일서버 | Phase 1: Synology IMAP (192.168.0.101:993) / Phase 2: Mailcow |
| HTML 렌더링 | `bleach` 또는 `nh3` (HTML sanitizer) |
| IMAP 라이브러리 | `imapclient` (imaplib 래퍼, 더 편리한 API) |
| 비밀번호 암호화 | `cryptography.fernet` (앱 키로 대칭 암호화) |

---

## 4. 데이터 모델

### 4.1 새 테이블

```sql
-- 사용자별 메일 계정 설정
CREATE TABLE light_sync.mail_accounts (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES light_sync.users(id),
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    imap_host VARCHAR(255) NOT NULL DEFAULT '192.168.0.101',
    imap_port INT NOT NULL DEFAULT 993,
    smtp_host VARCHAR(255) NOT NULL DEFAULT '192.168.0.101',
    smtp_port INT NOT NULL DEFAULT 587,
    username VARCHAR(255) NOT NULL,
    password_encrypted TEXT NOT NULL,
    use_ssl BOOLEAN DEFAULT TRUE,
    is_primary BOOLEAN DEFAULT FALSE,
    is_shared BOOLEAN DEFAULT FALSE,  -- 공용계정 여부
    signature TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 공용계정 접근 권한
CREATE TABLE light_sync.mail_shared_access (
    id SERIAL PRIMARY KEY,
    mail_account_id INT NOT NULL REFERENCES light_sync.mail_accounts(id),
    user_id INT NOT NULL REFERENCES light_sync.users(id),
    can_send BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 외부 주소록
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

---

## 5. 화면 구성

### 5.1 메인 레이아웃 (3컬럼)
```
┌──────────┬────────────────────┬─────────────────────┐
│ 폴더목록  │   메일 목록         │   메일 본문 (미리보기) │
│          │                    │                     │
│ 받은편지함 │ ☐ 김철수 - 견적요청  │  제목: 견적요청...    │
│ 보낸편지함 │ ☐ 이영희 - 납품확인  │  From: 김철수        │
│ 임시보관함 │ ☐ 박민수 - 회의록    │  Date: 2026-04-01   │
│ 휴지통    │                    │                     │
│ ─────── │                    │  본문 내용...         │
│ 공용메일함 │                    │                     │
│ purchase@ │                    │  📎 견적서.pdf       │
│ info@    │                    │                     │
└──────────┴────────────────────┴─────────────────────┘
```

### 5.2 페이지 목록
| 페이지 | URL | 설명 |
|--------|-----|------|
| 메일함 | `/mail` | 메인 화면 (3컬럼 레이아웃) |
| 메일 보기 | `/mail/<uid>` | 메일 상세 (모바일용 별도 페이지) |
| 메일 쓰기 | `/mail/compose` | 새 메일 / 답장 / 전달 |
| 설정 | `/mail/settings` | 계정 설정, 서명 관리 |
| 주소록 | `/mail/contacts` | 외부 연락처 관리 |
| 관리자 | `/mail/admin` | 계정 일괄 관리 (admin only) |

---

## 6. 구현 순서 (Phase 1)

### Step 1: 기반 구축
1. DB 테이블 생성 (mail_accounts, mail_shared_access, mail_contacts)
2. `modules/services/mail_client.py` — IMAP/SMTP 클라이언트 래퍼
3. `routes/mail.py` — Blueprint 등록
4. 비밀번호 암호화 유틸리티

### Step 2: 메일 읽기
1. 폴더 목록 조회 (IMAP LIST)
2. 메일 목록 조회 (IMAP FETCH — envelope, flags)
3. 메일 본문 조회 (IMAP FETCH — body, attachments)
4. 첨부파일 다운로드
5. 메일함 UI (목록 + 미리보기)

### Step 3: 메일 쓰기
1. 새 메일 작성 폼 + SMTP 발송
2. 답장/전체답장/전달
3. 첨부파일 업로드 + 발송
4. 임시저장 (Draft)
5. 서명 설정

### Step 4: 메일 관리
1. 삭제 (휴지통 이동)
2. 읽음/안읽음 토글
3. 별표 표시
4. 폴더 이동
5. 메일 검색

### Step 5: 계정/주소록
1. 내정보에 메일 설정 탭 추가
2. 공용계정 설정 + 접근 권한
3. 관리자 일괄 설정
4. 사내 주소록 자동완성
5. 외부 연락처 CRUD

---

## 7. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| IMAP 연결 지연 | 페이지 로딩 느림 | 연결 풀링 + 비동기 AJAX 로딩 |
| HTML 메일 XSS | 보안 취약점 | nh3/bleach sanitizer 적용 |
| 메일 비밀번호 유출 | 보안 사고 | Fernet 대칭 암호화 + 앱 시크릿 키 |
| Synology IMAP 부하 | 서버 과부하 | 목록 캐싱(30초) + 배치 조회 |
| 대용량 첨부파일 | 메모리 초과 | 스트리밍 다운로드 + 용량 제한(25MB) |
| 기존 email_sender 충돌 | 발주서 메일 장애 | 기존 모듈 유지, 웹메일은 별도 SMTP 세션 |

---

## 8. 성공 기준

| # | 기준 | 측정 방법 |
|---|------|----------|
| SC-1 | ERP 로그인 후 메일함 조회 가능 | 받은편지함 목록 1초 내 로딩 |
| SC-2 | 메일 읽기/쓰기/답장/전달 정상 작동 | 기능 테스트 통과 |
| SC-3 | 공용계정(purchase@) 접근 가능 | 권한 부여된 사용자만 접근 확인 |
| SC-4 | 첨부파일 다운로드/업로드 정상 | 10MB PDF 파일 테스트 |
| SC-5 | HTML 메일 안전하게 렌더링 | XSS 페이로드 차단 확인 |
| SC-6 | 기존 발주서 메일 발송 기능 영향 없음 | 기존 purchase_order 이메일 테스트 |
| SC-7 | 모바일에서 메일 확인 가능 | 반응형 레이아웃 확인 |
