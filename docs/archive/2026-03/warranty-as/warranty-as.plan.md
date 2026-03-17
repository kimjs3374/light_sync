# 하자보증/AS 관리 Planning Document

> **Summary**: 납품 완료 후 하자보증 기간 추적, AS 접수→현장확인→수리/교체→완료 워크플로우 관리
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 납품 완료 후 하자보증 기간/보증금 추적 수단이 없고, AS 접수~처리 이력이 체계적으로 관리되지 않아 대응이 늦어지거나 누락됨 |
| **Solution** | 프로젝트/계약 단위 하자보증 정보 등록 + AS 접수→현장확인→수리/교체→완료 4단계 워크플로우 + 하자유형별 통계 |
| **Function/UX Effect** | 보증 만료 임박 자동 알림, AS 현황 리스트에서 전체 진행상황 파악, 하자유형별 분석으로 품질 개선 데이터 확보 |
| **Core Value** | 고객 신뢰도 향상(10년 품질보증 실현) + AS 대응 속도 단축 + 반복 하자 패턴 파악으로 품질 선순환 |

---

## 1. Overview

### 1.1 Purpose

매그나텍의 관급자재 업무 프로세스 Phase 9(하자보증 및 AS)를 ERP에서 관리한다. 현재 납품관리까지는 구현되어 있으나, 납품 완료 후의 하자보증 기간 추적과 AS 처리 이력이 시스템 밖에서 관리되고 있다.

### 1.2 Background

- 매그나텍은 LED 조명 **10년 이상 품질·하자 보증**을 제공 (업계 차별점)
- 관급자재 계약 시 하자보증기간 1~3년, 하자보증금 2~5% 설정
- 하자보증보험증권 제출 → 기간 만료 시 반환 처리 필요
- 주요 하자 유형: LED모듈 불량, SMPS 고장, 방열이상, 렌즈/리플렉터 손상, 결로/침수, 제어불량
- AS 워크플로우: 접수 → 현장확인 → 원인분석 → 수리/교체 → 완료보고
- 현재 이 과정이 전화/메모/엑셀로 관리되어 누락 위험 있음

### 1.3 Related Documents

- 업무 프로세스: `.claude/magnatech_memory.md` Phase 9 섹션
- 기존 모델: `modules/models/entities.py` (Project, Contract, Delivery)
- 납품관리: `routes/delivery.py`

---

## 2. Scope

### 2.1 In Scope

- [ ] 하자보증 정보 등록 (보증기간, 보증금, 보험증권번호)
- [ ] 하자보증 만료 임박 알림 (30일/7일 전)
- [ ] AS 접수 등록 (하자유형, 증상, 접수일, 접수자)
- [ ] AS 처리 워크플로우 (접수→현장확인→수리/교체→완료)
- [ ] AS 이력 타임라인 (프로젝트/계약 단위)
- [ ] AS 관리 리스트 (검색/필터/페이지네이션)
- [ ] 하자유형별 통계 대시보드
- [ ] 기존 납품관리와의 연계 (납품완료 → 하자보증 시작)

### 2.2 Out of Scope

- 하자보증보험증권 파일 업로드/관리 (추후 별도 기능)
- 대금/정산 관리 (별도 Feature)
- 검수 프로세스 (별도 Feature)
- AS 외부 고객 포탈 (내부 ERP 전용)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 계약 단위 하자보증 정보 등록 (시작일, 종료일, 보증금액, 보험증권번호) | High | Pending |
| FR-02 | 하자보증 만료 임박 알림 (Notification 연동, 30일/7일 전) | High | Pending |
| FR-03 | AS 접수 등록 (프로젝트/계약 연결, 하자유형 선택, 증상 설명, 접수일) | High | Pending |
| FR-04 | AS 처리 상태 관리 (접수→현장확인→수리중→완료 / 보류) | High | Pending |
| FR-05 | AS 처리 내역 기록 (현장확인 메모, 원인분석, 처리내용, 교체부품, 완료일) | High | Pending |
| FR-06 | AS 관리 리스트 (검색/필터/정렬/페이지네이션) | High | Pending |
| FR-07 | 프로젝트 상세에서 AS 이력 조회 | Medium | Pending |
| FR-08 | 하자유형별 집계 (LED모듈/SMPS/방열/렌즈/결로/제어) | Medium | Pending |
| FR-09 | AS 상세 페이지 (접수~완료 타임라인 + 처리 내역) | High | Pending |
| FR-10 | 납품완료 시 하자보증 정보 입력 안내 (flash 알림) | Low | Pending |

### 3.2 하자유형 코드

| 코드 | 유형 | 증상 예시 |
|------|------|----------|
| LED_MODULE | LED 모듈 불량 | 부분 소등, 깜빡임 |
| SMPS | SMPS 고장 | 전체 소등, 불안정 점등 |
| HEAT | 방열 이상 | 과열, 조기 광속 저하 |
| LENS | 렌즈/리플렉터 손상 | 배광 이상, 광효율 저하 |
| MOISTURE | 결로/침수 | 내부 수분, 절연 저하 |
| CONTROL | 제어 불량 | 디밍 미작동, 통신 두절 |
| OTHER | 기타 | - |

### 3.3 Non-Functional Requirements

| Category | Criteria |
|----------|----------|
| Performance | AS 리스트 20건/페이지 기본, 1초 내 로딩 |
| 보안 | 기존 login_required 적용, 부서별 접근 제어 |
| UX | 기존 ERP UI 패턴(Bootstrap 5, mobile-stack-table) 동일 적용 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 하자보증 정보 CRUD 완료
- [ ] AS 접수~완료 워크플로우 동작
- [ ] AS 리스트 검색/필터/페이지네이션 동작
- [ ] 하자유형별 집계 표시
- [ ] 기존 프로젝트/계약/납품 페이지와 연계
- [ ] 모바일 반응형 정상 동작

### 4.2 Quality Criteria

- [ ] Python 문법 오류 없음
- [ ] Jinja2 템플릿 파싱 정상
- [ ] 기존 기능 호환성 유지

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 기존 Contract 모델에 보증 필드 추가 시 마이그레이션 | Medium | Medium | 별도 Warranty 모델로 분리하여 FK 연결 |
| AS 데이터 증가 시 리스트 성능 | Low | Medium | 페이지네이션 + DB 인덱스 |
| 알림 테이블 데이터 폭증 (만료 알림 반복 생성) | Medium | Medium | 동일 보증건 알림 중복 방지 로직 |

---

## 6. Architecture Considerations

### 6.1 Project Level: Dynamic (기존 유지)

### 6.2 Key Architectural Decisions

| Decision | Selected | Rationale |
|----------|----------|-----------|
| 하자보증 모델 | 별도 Warranty 모델 (Contract FK) | Contract 모델 비대화 방지 |
| AS 모델 | 별도 WarrantyCase 모델 (Warranty FK) | AS건별 독립 워크플로우 |
| AS 처리기록 | WarrantyCaseLog 모델 (WarrantyCase FK) | 타임라인 히스토리 |
| Blueprint | `routes/warranty.py` (신규) | 기존 패턴 유지 |
| 알림 연동 | 기존 notification_utils.py 활용 | 이미 구현된 인프라 재사용 |

### 6.3 구현 순서

```
1. Warranty, WarrantyCase, WarrantyCaseLog 모델 추가
   ↓
2. routes/warranty.py — 하자보증 CRUD + AS 리스트
   ↓
3. templates/warranty_list.html — 보증/AS 리스트
4. templates/warranty_detail.html — AS 상세/처리
   ↓
5. base.html 사이드바 메뉴 추가
6. app.py Blueprint 등록
   ↓
7. 보증만료 알림 로직 (notification_utils 활용)
8. 하자유형별 통계 위젯
```

---

## 7. Convention Prerequisites

### 7.1 기존 프로젝트 컨벤션 준수

- [x] Flask Blueprint 패턴
- [x] `get_db()` 컨텍스트 매니저
- [x] `@login_required` 데코레이터
- [x] flash 메시지 피드백
- [x] Bootstrap 5 UI + mobile-stack-table
- [x] 검색/필터: GET 쿼리스트링 방식
- [x] 페이지네이션: `make_pagination()` 공통 유틸

### 7.2 신규 파일 계획

| 유형 | 파일 | 목적 |
|------|------|------|
| 모델 | `modules/models/entities.py` 수정 | Warranty, WarrantyCase, WarrantyCaseLog 추가 |
| 라우트 | `routes/warranty.py` | 하자보증/AS 엔드포인트 |
| 서비스 | `modules/services/warranty_actions.py` | AS 처리 비즈니스 로직 |
| 템플릿 | `templates/warranty_list.html` | 보증/AS 관리 리스트 |
| 템플릿 | `templates/warranty_detail.html` | AS건 상세 + 처리 |
| 템플릿 | `templates/warranty_create.html` | AS 접수 폼 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`/pdca design warranty-as`)
2. [ ] 구현 시작
3. [ ] Gap 분석 (`/pdca analyze warranty-as`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft | ENG |
