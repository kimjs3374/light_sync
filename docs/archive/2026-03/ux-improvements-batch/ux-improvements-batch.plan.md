# UX 개선 5종 일괄 계획서

> **Summary**: 설계관리 검색/필터, 비밀번호 변경, 페이지네이션, 알림센터, 프로젝트 종합현황 뷰 일괄 구현
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 설계관리 리스트에만 검색이 없고, 비밀번호 변경 불가, 데이터 증가 시 성능 저하, 업무 알림 누락, 프로젝트 전체 진행 파악 어려움 |
| **Solution** | 기존 패턴(계약리스트 검색/필터) 재활용 + 신규 3개 기능(비밀번호, 알림센터, 종합현황) 추가 |
| **Function/UX Effect** | 모든 리스트에서 즉시 검색 가능, 사용자 자율 비밀번호 관리, 빠른 페이지 로딩, 실시간 업무 알림, 한눈에 프로젝트 진행률 파악 |
| **Core Value** | 업무 효율성 향상 및 데이터 증가에 대한 확장성 확보 |

---

## 1. Overview

### 1.1 Purpose

Light-Sync ERP의 핵심 워크플로우(설계→계약→영업→자재→생산→납품)는 완성되었으나, 일상 업무 편의성을 높이는 부가 기능 5종이 부족하여 이를 일괄 구현한다.

### 1.2 Background

- 계약/자재/생산/납품 리스트는 검색/필터가 있으나 **설계관리 리스트만 누락**
- 사용자가 비밀번호를 변경할 수 있는 방법이 없음 (관리자 초기화만 가능)
- 현재 모든 리스트가 전체 데이터를 한번에 로딩 → 데이터 증가 시 성능 문제
- KakaoWork 알림은 있으나 앱 내부에서 알림을 확인/관리하는 기능 없음
- 프로젝트 단위로 전체 진행률을 한 화면에서 볼 수 없음

### 1.3 Related Documents

- 기존 코드: `routes/project.py`, `routes/auth.py`, `routes/contract.py`
- 기존 템플릿: `templates/contract_list.html` (검색/필터 참조 패턴)

---

## 2. Scope

### 2.1 In Scope

- [x] Feature 1: 설계관리 리스트 검색/필터 추가
- [x] Feature 2: 비밀번호 변경 기능
- [x] Feature 3: 리스트 페이지 페이지네이션 (설계, 계약, 영업, 자재, 생산, 납품)
- [x] Feature 4: 앱 내 알림센터
- [x] Feature 5: 프로젝트 종합현황 뷰

### 2.2 Out of Scope

- 엑셀 내보내기 (별도 Feature로 추후 진행)
- 웹 푸시 알림 (Service Worker 기반)
- 모바일 앱
- 실시간 WebSocket 알림 (Polling 방식으로 우선 구현)

---

## 3. Requirements

### Feature 1: 설계관리 검색/필터

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| F1-01 | 관리번호/현장명/약칭 텍스트 검색 | High | Pending |
| F1-02 | 상태 필터 (설계중/계약전환/전체) | High | Pending |
| F1-03 | 계약예정일 기준 D-Day 필터 (지연/7일내/14일내/전체) | Medium | Pending |
| F1-04 | 정렬 (계약예정일순/최신등록순) | Medium | Pending |
| F1-05 | 조회결과 건수 표시 | Low | Pending |

**구현 참조**: `contract_list.html` + `routes/contract.py`의 기존 필터 패턴을 그대로 적용

### Feature 2: 비밀번호 변경

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| F2-01 | 로그인 사용자 본인 비밀번호 변경 (현재PW + 새PW + 확인PW) | High | Pending |
| F2-02 | 현재 비밀번호 검증 후 변경 | High | Pending |
| F2-03 | 새 비밀번호 최소 6자 이상 검증 | High | Pending |
| F2-04 | 관리자의 타 사용자 비밀번호 초기화 (admin_settings) | Medium | Pending |
| F2-05 | 변경 성공 시 세션 유지, flash 알림 | Low | Pending |

**접근 위치**: 사이드바 하단 사용자 정보 영역 또는 별도 모달

### Feature 3: 페이지네이션

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| F3-01 | 공통 페이지네이션 유틸리티 함수 (page, per_page, total) | High | Pending |
| F3-02 | 설계관리 리스트 페이지네이션 적용 | High | Pending |
| F3-03 | 계약관리 리스트 페이지네이션 적용 | High | Pending |
| F3-04 | 영업관리 리스트 페이지네이션 적용 | High | Pending |
| F3-05 | 자재관리 리스트 페이지네이션 적용 | High | Pending |
| F3-06 | 생산관리 리스트 페이지네이션 적용 | High | Pending |
| F3-07 | 납품관리 리스트 페이지네이션 적용 | High | Pending |
| F3-08 | 페이지당 건수 선택 (20/50/100) | Medium | Pending |
| F3-09 | 검색/필터 조건과 페이지네이션 연동 (쿼리스트링 유지) | High | Pending |

**기본값**: 페이지당 20건

### Feature 4: 앱 내 알림센터

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| F4-01 | Notification 모델 (user_id, title, message, noti_type, is_read, link, created_at) | High | Pending |
| F4-02 | 사이드바 또는 헤더에 알림 아이콘 + 미확인 개수 배지 | High | Pending |
| F4-03 | 알림 드롭다운/패널 (최근 20건) | High | Pending |
| F4-04 | 알림 클릭 시 해당 페이지 이동 + 읽음 처리 | High | Pending |
| F4-05 | 전체 읽음 처리 버튼 | Medium | Pending |
| F4-06 | 자동 알림 생성 트리거: 납기 7일 이내, 자재 미입고, 생산 지연 | High | Pending |
| F4-07 | 알림 전체 목록 페이지 | Low | Pending |

**알림 유형**: delivery_due, material_pending, production_delay, contract_new, system

### Feature 5: 프로젝트 종합현황 뷰

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| F5-01 | 프로젝트별 전체 워크플로우 진행률 표시 (설계→계약→영업→자재→생산→납품) | High | Pending |
| F5-02 | 각 단계별 상태 표시 (완료/진행중/대기) | High | Pending |
| F5-03 | 프로그레스바 시각화 | Medium | Pending |
| F5-04 | 검색/필터 (현장명, 상태별) | Medium | Pending |
| F5-05 | 클릭 시 해당 단계 상세 페이지로 이동 | Medium | Pending |

**접근 위치**: 사이드바 메뉴 "📊 종합현황" 또는 대시보드 내 탭

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 5개 Feature 전체 구현 완료
- [ ] 기존 기능과의 호환성 유지 (기존 URL/동작 변경 없음)
- [ ] 모바일 반응형 동작 확인
- [ ] 관리자/일반사용자 권한별 동작 확인

### 4.2 Quality Criteria

- [ ] 모든 리스트 페이지 검색/필터/페이지네이션 정상 동작
- [ ] 비밀번호 변경 시 bcrypt 해싱 정상
- [ ] 알림 생성/읽음처리/링크이동 정상
- [ ] 종합현황 뷰에서 실시간 데이터 반영

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 페이지네이션 적용 시 기존 검색/필터 쿼리스트링 깨짐 | Medium | Medium | 공통 유틸리티에서 쿼리스트링 보존 로직 통합 |
| 알림 테이블 데이터 증가 | Low | High | 30일 이상 된 읽은 알림 자동 정리 |
| 종합현황 뷰 쿼리 성능 | Medium | Medium | 프로젝트 단위 JOIN 최적화, 필요시 캐시 |

---

## 6. Architecture Considerations

### 6.1 Project Level

| Level | Selected |
|-------|:--------:|
| **Dynamic** | ✅ |

### 6.2 Key Architectural Decisions

| Decision | Selected | Rationale |
|----------|----------|-----------|
| Framework | Flask (기존) | 기존 아키텍처 유지 |
| DB | PostgreSQL + SQLAlchemy (기존) | 기존 스택 활용 |
| 템플릿 | Jinja2 (기존) | 서버사이드 렌더링 유지 |
| 페이지네이션 | 직접 구현 (SQLAlchemy offset/limit) | 경량, 외부 의존성 불필요 |
| 알림 조회 | Polling (페이지 로드 시 + AJAX 30초 간격) | WebSocket 대비 구현 간단 |

### 6.3 구현 순서 (의존성 기반)

```
1. 페이지네이션 유틸리티 (공통 기반)
   ↓
2. 설계관리 검색/필터 + 페이지네이션 (1번 활용)
   ↓ (동시 가능)
3. 비밀번호 변경 (독립)
4. 나머지 리스트 페이지네이션 적용 (1번 활용)
   ↓
5. 알림센터 (신규 모델 + UI)
   ↓
6. 프로젝트 종합현황 뷰 (전체 데이터 조회)
```

---

## 7. Convention Prerequisites

### 7.1 기존 프로젝트 컨벤션

- [x] Flask Blueprint 패턴 사용
- [x] `get_db()` 컨텍스트 매니저로 DB 세션 관리
- [x] `@login_required` / `@admin_required` 데코레이터
- [x] flash 메시지로 사용자 피드백
- [x] Bootstrap 5 기반 UI
- [x] 검색/필터: GET 쿼리스트링 방식 (`?q=&status=&sort=`)

### 7.2 신규 파일 계획

| 유형 | 파일 | 목적 |
|------|------|------|
| 유틸리티 | `modules/pagination.py` | 공통 페이지네이션 헬퍼 |
| 모델 | `modules/models/entities.py` 수정 | Notification 모델 추가 |
| 라우트 | `routes/notification.py` | 알림 API 엔드포인트 |
| 라우트 | `routes/overview.py` | 종합현황 뷰 |
| 템플릿 | `templates/notification_center.html` | 알림 전체 목록 |
| 템플릿 | `templates/project_overview.html` | 종합현황 페이지 |
| 템플릿 | `templates/components/pagination.html` | 공통 페이지네이션 컴포넌트 |
| 템플릿 | `templates/components/notification_dropdown.html` | 알림 드롭다운 |
| 템플릿 | `templates/components/change_password_modal.html` | 비밀번호 변경 모달 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`/pdca design ux-improvements-batch`)
2. [ ] 구현 시작 (페이지네이션 유틸 → 검색/필터 → 비밀번호 → 알림센터 → 종합현황)
3. [ ] Gap 분석 (`/pdca analyze ux-improvements-batch`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft - 5개 기능 일괄 계획 | ENG |
