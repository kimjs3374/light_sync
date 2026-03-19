# history-board-ux Planning Document

> **Summary**: 상세페이지에 인라인 배치된 히스토리보드를 offcanvas 슬라이드 패널로 전환하여 화면 공간 효율 극대화
>
> **Project**: Light-Sync ERP
> **Author**: CTO Lead (PDCA)
> **Date**: 2026-03-19
> **Status**: Approved

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 히스토리보드가 상세페이지 col-4 영역을 상시 점유하여 핵심 콘텐츠 공간이 col-8로 제한됨. 연락처도 사이드바 점유. 매그나텍 업무 9단계 중 검수(PHASE 7)/대금(PHASE 8)/하자AS(PHASE 9) 이벤트가 히스토리에 미기록. technical scope 미사용, reply 카운트 누락 |
| **Solution** | 히스토리보드를 offcanvas-end 슬라이드 패널로 이동. 연락처를 접히는 바로 전환. 검수/대금 이벤트 히스토리 기록 추가. 상단 한줄 바에 최근 로그 요약 + 빨간 펄스 알림 |
| **Function/UX Effect** | 본문 col-12 확장 + 연락처/히스토리 접근성 유지 + 매그나텍 업무 흐름(설계→계약→생산→납품→검수→대금)이 히스토리로 추적 가능 |
| **Core Value** | 화면 공간 33% 회복 + 업무 프로세스 추적 완성도 향상 + 버그 수정으로 데이터 정합성 확보 |

---

## 1. Overview

### 1.1 Purpose

현재 6개 상세페이지(project, contract, sales, material, production, delivery)에 인라인 배치된 히스토리보드를 offcanvas 슬라이드 패널 방식으로 전환하여 화면 효율을 극대화한다.

### 1.2 Background

- 히스토리보드가 col-md-4 영역을 상시 점유 → 본문 콘텐츠가 col-md-8로 제한
- 연락처 테이블도 사이드바(col-md-4) 또는 풀카드로 메인 공간 점유
- 생산관리 상세는 이미 prodInfoPanel offcanvas(560px, 4탭)가 있어 별도 offcanvas 추가 시 충돌 우려
- 진단 결과 3가지 추가 문제 발견: technical scope 미사용, drawing 보드 부재, reply 카운트 누락
- 매그나텍 업무 프로세스 9단계(magnatech_memory.md) 대조 결과, PHASE 7(검수)/8(대금)/9(하자AS) 이벤트가 히스토리에 미기록
- technical scope가 비어있는 근본 원인: PHASE 9 하자보증/AS 기능이 ERP에 없음

### 1.3 Related Documents

- `modules/history_board.py` - 핵심 모듈
- `templates/components/history_board.html` - UI 컴포넌트
- 각 상세페이지 템플릿 6개

---

## 2. Scope

### 2.1 In Scope

**A. UX 개선 (완료)**
- [x] 히스토리보드 offcanvas 슬라이드 패널 컴포넌트 생성
- [x] production_detail: 기존 prodInfoPanel에 "히스토리" 탭 추가
- [x] project/contract/sales/material/delivery_detail: 독립 offcanvas-end 패널 생성
- [x] 상단 한줄 바: 최근 로그 1건 + 전체 건수 뱃지 + 빨간 펄스 + 클릭 시 패널 오픈
- [x] technical scope 탭 제거 (history_board.html에서 숨김)
- [x] drawing scope: 히스토리 기록은 유지, 보드에서는 표시만
- [x] reply 카운트 누락 수정 (build_history_view)

**B. 연락처 재배치 (완료)**
- [x] 연락처를 접히는 한줄 바(contact_collapse_bar.html)로 전환
- [x] contract_detail/sales_detail: col-md-4 사이드바 제거 → 본문 col-12 확장
- [x] project_detail: 풀카드 → 접히는 바
- [x] delivery_detail: side-card → 접히는 바

**C. 매그나텍 업무 프로세스 히스토리 연동 (신규)**
- [ ] 검수 이벤트 기록: 납품 상세에 검수결과(합격/불합격/보완) + `delivery` scope 히스토리 자동 기록
- [ ] 대금 이벤트 기록: 세금계산서 발행/대금 입금확인 → `contract` scope 히스토리 자동 기록
- [ ] 설계 이력 보강: 시뮬레이션 파일 등록, 시방서 반영 확인 → `design` scope 히스토리 기록

### 2.2 Out of Scope

- 하자보증/AS 관리 기능 신규 개발 (PHASE 9) — 별도 PDCA로 분리 권장
- 실시간 WebSocket 알림 (향후 과제)
- drawing_detail.html 신규 생성
- 대금 관리 전용 화면 (기존 계약 상세에 필드 추가로 대체)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 히스토리보드를 offcanvas 슬라이드 패널로 이동 | High | Pending |
| FR-02 | production_detail: prodInfoPanel에 "히스토리" 탭 추가 | High | Pending |
| FR-03 | 나머지 5개 상세페이지: 독립 offcanvas-end 패널 생성 | High | Pending |
| FR-04 | 상단 한줄 바: 최근 1건 + 전체 건수 뱃지 + 클릭 시 패널 오픈 | High | Pending |
| FR-05 | 새 로그 시 한줄 바 빨간 펄스 애니메이션 | Medium | Pending |
| FR-06 | technical scope 탭 제거 | Low | Pending |
| FR-07 | reply 카운트 누락 수정 (build_history_view) | High | Pending |
| FR-08 | 연락처를 접히는 바로 전환 (4개 상세페이지) | High | Done |
| FR-09 | contract/sales 사이드바 제거 → 본문 col-12 확장 | High | Done |
| FR-10 | 납품 검수 이벤트 → delivery scope 히스토리 기록 | High | Pending |
| FR-11 | 대금 이벤트(세금계산서/입금) → contract scope 히스토리 기록 | Medium | Pending |
| FR-12 | 설계 이력 보강(시뮬레이션/시방서 반영) → design scope 히스토리 기록 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | offcanvas 오픈 200ms 이내 | 체감 테스트 |
| Compatibility | 기존 히스토리 post action 동작 유지 | 기능 테스트 |
| UX | 모바일에서도 offcanvas 정상 표시 | 반응형 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [x] 6개 상세페이지에서 인라인 히스토리보드 제거
- [x] offcanvas 패널에서 히스토리 조회/등록/답글 정상 동작
- [x] 상단 한줄 바 정상 표시 + 클릭 시 패널 오픈
- [x] build_history_view reply 카운트 반영
- [x] technical scope 탭 숨김 처리

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| production_detail offcanvas 충돌 | High | Medium | 기존 prodInfoPanel에 탭 추가 방식으로 충돌 회피 |
| 히스토리 post form action 깨짐 | High | Low | 기존 history_post_url, history_post_action 변수 그대로 유지 |
| 한줄 바 데이터 전달 | Medium | Low | Jinja2 변수로 최근 로그/건수 전달 |
| 검수/대금 필드 DB 추가 필요 | Medium | High | ALTER TABLE 직접 실행 + db.py 마이그레이션 로직 추가 |
| 연락처 접히는 바에서 수정/삭제 모달 연동 | Medium | Low | 기존 openContactEditFromBtn 함수 재사용 |

---

## 6. Architecture Considerations

### 6.1 Project Level

Flask + Jinja2 + SQLite + Bootstrap 5 (Monolith)

### 6.2 Key Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 생산 상세 패널 방식 | A) 기존 prodInfoPanel에 탭 추가 / B) 별도 offcanvas | A) 탭 추가 | 동시에 2개 offcanvas 열면 UX 혼란 |
| 나머지 상세 패널 방식 | 독립 offcanvas-end | 독립 offcanvas | 기존 offcanvas 없으므로 깔끔한 구현 가능 |
| technical scope | 제거 vs 숨김 | 숨김 | DB에 기존 데이터가 있을 수 있으므로 UI만 숨김 |

---

## 7. 매그나텍 업무 프로세스 연동 상세

> 출처: `.claude/magnatech_memory.md` — 관급자재 업무 프로세스 9단계

### 7.1 검수 이벤트 (FR-10) — PHASE 7 대응

납품 상세(delivery_detail)에 검수 관련 필드/버튼 추가:
- Delivery 모델에 `inspection_status` (합격/불합격/보완/미검수), `inspection_date`, `inspection_note` 추가
- 검수 상태 변경 시 `append_history_log(scope='delivery', kind='system')` 자동 기록
- 검수 체크리스트: 모델명·수량 일치, 외관 손상, 부속품, G2B식별번호·인증마크, 납품서류

### 7.2 대금 이벤트 (FR-11) — PHASE 8 대응

계약 상세(contract_detail)에 대금 관련 필드/버튼 추가:
- Contract 모델에 `payment_status` (미청구/청구완료/입금완료), `invoice_date`, `payment_date` 추가
- 상태 변경 시 `append_history_log(scope='contract', kind='system')` 자동 기록
- 대금지급 기한 알림: 검수 후 30일 이내 (지방자치단체 기준)

### 7.3 설계 이력 보강 (FR-12) — PHASE 2-3 대응

설계 상세(project_detail)에서 설계 관련 이벤트 기록 강화:
- 조도 시뮬레이션 파일 등록/변경 시 `design` scope 히스토리 자동 기록
- 시방서 반영 확인 체크 시 `design` scope 히스토리 기록
- 기존 "설계 기준 변경" 기록은 유지

---

## 8. Next Steps

1. [x] Design document 작성
2. [x] 구현 — UX 개선 (A: offcanvas + 한줄 바)
3. [x] 구현 — 연락처 재배치 (B: 접히는 바)
4. [ ] 구현 — 매그나텍 연동 (C: 검수/대금/설계 이벤트)
5. [ ] Gap Analysis (Check phase)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-19 | Initial plan — UX 개선 + 버그 수정 | CTO Lead |
| 1.1 | 2026-03-19 | 연락처 접히는 바 + 매그나텍 업무 프로세스 연동 추가 | User + Claude |
