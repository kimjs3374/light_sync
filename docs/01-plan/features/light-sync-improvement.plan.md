# Light-Sync Improvement Planning Document

> **Summary**: Light-Sync ERP 시스템의 보안 취약점 해결, 코드 품질 개선, 성능 최적화 및 안정성 강화
>
> **Project**: Light-Sync (LED 조명기구 제조/납품 ERP)
> **Version**: 1.0
> **Author**: Claude Code + User
> **Date**: 2026-03-17
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 운영 중인 ERP 시스템에 9개 긴급 보안 취약점(크리덴셜 노출, debug 모드, CSRF 미적용)과 코드 품질 점수 32/100의 기술 부채가 누적되어 있음 |
| **Solution** | 4단계 개선 계획: 긴급 보안 패치 → 안정성 확보 → 코드 리팩토링 → 기능 개선/최적화 |
| **Function/UX Effect** | 보안 사고 예방, 페이지 로드 속도 향상(GET 동기화 제거), DB 연결 안정성 확보, 에러 발생 시 사용자 친화적 처리 |
| **Core Value** | 사내 운영 시스템의 보안성과 안정성을 확보하여 비즈니스 연속성 보장 |

---

## 1. Overview

### 1.1 Purpose

Light-Sync는 LED 조명기구 제조/납품 전 과정(견적→설계/계약→자재→생산→납품→기술지원)을 관리하는 사내 ERP 시스템이다. Cline으로 개발되어 핵심 기능은 80-85% 구현되었으나, 보안 취약점과 코드 품질 문제가 발견되어 체계적 개선이 필요하다.

### 1.2 Background

- **운영 환경**: Synology NAS 리버스 프록시, 도메인 `work.mgnt.kr`, 포트 8501
- **기술 스택**: Flask + SQLAlchemy + Supabase/PostgreSQL + Bootstrap 5
- **코드 규모**: Python 31개 파일(11,000+ 라인), HTML 48개 템플릿
- **코드 품질 점수**: 32/100 (code-analyzer 분석 결과)
- **긴급 보안 이슈 9건**, 개선 필요 사항 20건, 참고 사항 9건 발견

### 1.3 Related Documents

- 기존 문서: `MASTER_GUIDE.md`, `architecture.md`, `dashboard.md`, `new_dashboard_plan.md`
- 개발 계획: `plan/plan_meterial.md`, `plan/plan_production.md`

---

## 2. Scope

### 2.1 In Scope

- [ ] **Phase 1**: 긴급 보안 패치 (9개 Critical 이슈)
- [ ] **Phase 2**: 안정성 확보 (DB 세션 관리, 에러 핸들링, 세션 보안)
- [ ] **Phase 3**: 코드 리팩토링 (중복 제거, 대형 파일 분할, 서비스 레이어)
- [ ] **Phase 4**: 성능 최적화 및 기능 개선 (GET 동기화 제거, DB 인덱스, 로깅)

### 2.2 Out of Scope

- 모바일 앱 / 반응형 모바일 UI (별도 프로젝트로 진행)
- DWG → PDF 자동 변환 (MASTER_GUIDE에서 명시적 제외)
- 이메일 알림 시스템
- 복잡한 BOM/ERP 마스터 데이터 연동
- WebSocket 실시간 알림

---

## 3. Requirements

### 3.1 Functional Requirements

#### Phase 1: 긴급 보안 패치

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | `.env` 파일 Git 이력에서 제거, 크리덴셜 교체 | Critical | Pending |
| FR-02 | `app.secret_key`를 환경변수 기반 랜덤 키로 교체 | Critical | Pending |
| FR-03 | `debug=False` 설정 (운영 환경 분리) | Critical | Pending |
| FR-04 | Flask-WTF CSRF 보호 적용 (전체 POST 폼) | Critical | Pending |
| FR-05 | `approve_user`, `reject_user` 엔드포인트 관리자 권한 체크 + POST 변경 | Critical | Pending |
| FR-06 | 기본 admin 비밀번호 환경변수화 또는 첫 로그인 시 변경 강제 | Critical | Pending |
| FR-07 | 회원가입 입력값 검증 (길이, 형식, 중복 체크) | Critical | Pending |
| FR-08 | 세션 만료 시간 설정 (8시간) | Critical | Pending |
| FR-09 | 세션 쿠키 보안 설정 (HttpOnly, Secure, SameSite) | Critical | Pending |

#### Phase 2: 안정성 확보

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-10 | DB 세션 `try/finally` 또는 컨텍스트 매니저 패턴 적용 (전 라우트) | High | Pending |
| FR-11 | `int()` 캐스팅 안전 처리 (production.py, sales.py) | High | Pending |
| FR-12 | 파일 업로드 크기/타입 검증 추가 | High | Pending |
| FR-13 | 로그인 Rate Limiting 적용 (Flask-Limiter) | High | Pending |
| FR-14 | `bare except:` → `except Exception:` + 로깅 | Medium | Pending |
| FR-15 | Open redirect 방지 (drawing.py `_safe_next_url`) | Medium | Pending |

#### Phase 3: 코드 리팩토링

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-16 | 중복 유틸 함수 통합 (`_parse_date`, `_to_int`, `_is_true_value`) → `modules/utils.py` | High | Pending |
| FR-17 | 중복 spec 추출/검증 로직 통합 → `modules/spec_utils.py` | High | Pending |
| FR-18 | `routes/project.py` (2,100줄) 분할 → project, material, barcode 라우트 | High | Pending |
| FR-19 | 비즈니스 로직 서비스 레이어 분리 (status 계산, sync 로직) | Medium | Pending |
| FR-20 | SQLite 마이그레이션 데드코드 제거 (db.py 170줄) | Low | Pending |
| FR-21 | 매 부팅 데이터 정규화 → 일회성 마이그레이션 스크립트로 전환 | Medium | Pending |

#### Phase 4: 성능 최적화 및 기능 개선

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-22 | GET 요청 시 동기화 제거 (production, delivery, material) → 이벤트 기반 | High | Pending |
| FR-23 | DB 인덱스 추가 (project_id, delivery_due_date, status 등 주요 조회 컬럼) | High | Pending |
| FR-24 | `storage_adapter.py` 설정 캐싱 (`@lru_cache`) | Medium | Pending |
| FR-25 | `SERVER_NAME` 설정 제거 (리버스 프록시 위임) | Medium | Pending |
| FR-26 | 구조화된 로깅 프레임워크 도입 (Python logging) | Medium | Pending |
| FR-27 | `Query.get()` → SQLAlchemy 2.0 `session.get()` 마이그레이션 | Low | Pending |
| FR-28 | 대시보드 UI 리디자인 (new_dashboard_plan.md 기반) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Security | OWASP Top 10 주요 항목 대응 (CSRF, XSS, Injection) | code-analyzer 재검사 |
| Performance | 페이지 로드 시 불필요한 DB 쓰기 0건 | GET 요청 로그 분석 |
| Reliability | DB 세션 누수 0건 | `try/finally` 적용률 100% |
| Maintainability | 단일 파일 최대 500줄 이내 | 코드 라인수 검사 |
| Code Quality | 품질 점수 70/100 이상 | code-analyzer 재검사 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] Phase 1 완료: 9개 Critical 보안 이슈 모두 해결
- [ ] Phase 2 완료: DB 세션 안전 처리, 입력값 검증, Rate Limiting 적용
- [ ] Phase 3 완료: 중복 코드 제거, project.py 분할, 서비스 레이어 분리
- [ ] Phase 4 완료: GET 동기화 제거, DB 인덱스 추가, 로깅 도입
- [ ] code-analyzer 재검사 품질 점수 70/100 이상
- [ ] 기존 기능 정상 동작 확인

### 4.2 Quality Criteria

- [ ] 보안 Critical 이슈 0건
- [ ] 단일 파일 500줄 이내
- [ ] 모든 라우트 `try/finally` DB 세션 관리
- [ ] 전체 POST 폼 CSRF 토큰 적용

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| CSRF 적용 시 기존 AJAX 요청 깨짐 | High | High | 단계적 적용, AJAX 헤더에 CSRF 토큰 포함 패턴 적용 |
| project.py 분할 시 import 순환 참조 | Medium | Medium | 서비스 레이어를 별도 모듈로 먼저 분리 후 라우트 분할 |
| 크리덴셜 교체 시 서비스 중단 | High | Low | 점검 시간 확보, .env 환경변수 방식으로 무중단 전환 |
| GET 동기화 제거 시 데이터 불일치 | Medium | Medium | POST 이벤트 기반 동기화로 대체, 수동 동기화 버튼 추가 |
| debug=False 전환 시 에러 추적 어려움 | Medium | High | Python logging 프레임워크 먼저 도입 후 전환 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites, portfolios | |
| **Dynamic** | Feature-based modules, BaaS integration | Web apps with backend, SaaS MVPs | **V** |
| **Enterprise** | Strict layer separation, DI, microservices | High-traffic systems | |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| Framework | Flask (유지) | Flask | 기존 코드베이스 유지, 전면 재작성 불필요 |
| Database | Supabase PostgreSQL (유지) | Supabase | 이미 마이그레이션 완료, 안정적 운영 중 |
| Authentication | Session 기반 (유지) + 보안 강화 | Flask Session + bcrypt | 기존 방식 유지하며 보안만 강화 |
| CSRF Protection | Flask-WTF | Flask-WTF CSRFProtect | Flask 생태계 표준 |
| Rate Limiting | Flask-Limiter | Flask-Limiter | 간단한 설정으로 적용 가능 |
| Logging | Python logging | logging + RotatingFileHandler | 표준 라이브러리, 추가 의존성 없음 |

### 6.3 Target Architecture (After Improvement)

```
Improved Architecture:
┌─────────────────────────────────────────────────────┐
│ routes/                                              │
│   auth.py, dashboard.py, project.py, contract.py,   │
│   sales.py, production.py, delivery.py, drawing.py, │
│   technical.py, material.py (NEW), barcode.py (NEW) │
├─────────────────────────────────────────────────────┤
│ modules/services/ (NEW - Business Logic Layer)       │
│   material_service.py, production_service.py,        │
│   delivery_service.py, status_service.py             │
├─────────────────────────────────────────────────────┤
│ modules/utils.py (NEW - Shared Utilities)            │
│ modules/spec_utils.py (NEW - Spec Extraction)        │
├─────────────────────────────────────────────────────┤
│ modules/models/ (Existing - ORM Layer)               │
│   base.py, entities.py, db.py, constants.py          │
└─────────────────────────────────────────────────────┘
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `MASTER_GUIDE.md` 개발 원칙 존재
- [ ] `CLAUDE.md` 없음 → 생성 권장
- [ ] ESLint/Prettier 해당 없음 (Python 프로젝트)
- [ ] Python linter (flake8/ruff) 설정 없음

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **DB Session 패턴** | 비일관적 (수동 close) | `try/finally` 또는 context manager 필수 | High |
| **에러 핸들링** | 없음 | flask errorhandler + 표준 패턴 | High |
| **환경변수 관리** | .env 파일 직접 참조 | python-dotenv + 중앙 config.py | High |
| **파일 크기 제한** | 없음 (2,100줄 존재) | 단일 파일 500줄 이내 | Medium |
| **Import 순서** | 비일관적 | stdlib → 3rd party → local | Medium |

### 7.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `SECRET_KEY` | Flask 세션 암호화 키 | Server | **V** |
| `FLASK_DEBUG` | 디버그 모드 On/Off | Server | **V** |
| `DATABASE_URL` | Supabase PostgreSQL 연결 | Server | **V** |
| `SUPABASE_URL` | Supabase API URL | Server | **V** |
| `SUPABASE_KEY` | Supabase 서비스 키 | Server | **V** |
| `KAKAOWORK_BOT_TOKEN` | 카카오워크 봇 토큰 | Server | **V** |
| `ADMIN_DEFAULT_PASSWORD` | 초기 관리자 비밀번호 | Server | **V** |

---

## 8. Implementation Phases & Timeline

### Phase 1: 긴급 보안 패치 (FR-01 ~ FR-09)
- 환경변수 기반 설정 전환 (config.py 생성)
- secret_key, debug 모드 분리
- CSRF 보호 적용
- 권한 체크 추가
- 세션 보안 설정

### Phase 2: 안정성 확보 (FR-10 ~ FR-15)
- DB 세션 관리 패턴 전환
- 입력값 검증 강화
- Rate Limiting 적용
- 에러 핸들링 표준화

### Phase 3: 코드 리팩토링 (FR-16 ~ FR-21)
- 공통 유틸리티 추출
- project.py 분할
- 서비스 레이어 도입
- 데드코드 제거

### Phase 4: 성능 최적화 (FR-22 ~ FR-28)
- GET 동기화 → 이벤트 기반 전환
- DB 인덱스 추가
- 로깅 프레임워크 도입
- 대시보드 개선

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`/pdca design light-sync-improvement`)
2. [ ] Phase 1 보안 패치 즉시 착수
3. [ ] 크리덴셜 교체 (사용자 직접 수행 필요)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft based on code-analyzer results | Claude Code |
