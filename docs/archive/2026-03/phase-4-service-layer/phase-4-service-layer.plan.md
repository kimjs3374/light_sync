# Phase 4: Service Layer 추출 — Plan

## Executive Summary

| Perspective | Content |
|---|---|
| **Problem** | `handle_detail_common()` 697줄 단일 함수에 20개 action이 혼재, 테스트/수정 불가능한 구조 |
| **Solution** | Action 핸들러를 도메인별 서비스 모듈로 분리하고, 라우트는 디스패치만 수행 |
| **Function/UX Effect** | 사용자 기능 변경 없음. 개발자가 개별 action을 독립적으로 수정/테스트 가능 |
| **Core Value** | handle_detail_common 697→≤150줄, 도메인별 서비스 모듈로 관심사 분리, 향후 API화 기반 마련 |

---

## 1. Background

### 1.1 Phase 3 결과 (선행 작업)
- project.py: 2,150 → 1,266줄 (41% 감소)
- 중복 유틸 제거, 상수 중앙화, material/barcode Blueprint 분리 완료
- **잔여 과제**: `handle_detail_common()` ~697줄이 project.py의 55%를 차지

### 1.2 현재 구조 문제점
- `handle_detail_common()` (line 344~1040): 20개 `elif action ==` 분기
  - 프로젝트 정보 수정 (4개): update_design_basis, update_project, update_priority_override, update_work_path
  - 자재 관리 (3개): update_material, add_material, delete_material
  - 계약 관리 (4개): update_contract, add_contract, add_contract_item, delete_contract_item
  - 계약 품목 수정 (2개): update_contract_item, update_contract_item_barcodes_manual (*)가장 큰 분기
  - 바코드 관리 (3개): upload_contract_item_barcodes, delete_contract_item_barcode, update_contract_item_barcode_meta
  - 연락처 관리 (3개): add_contact, update_contact, delete_contact
  - 히스토리 (2개): add_chat, add_history_reply
- 단일 함수 내 모든 비즈니스 로직이 혼재 → 수정 시 사이드이펙트 위험
- `_date_to_dt_start()` 중복 (project.py:42, material.py:23)

### 1.3 현재 라인 수 현황

| 파일 | 라인 | 비고 |
|------|-----:|------|
| routes/project.py | 1,265 | handle_detail_common 697줄 포함 |
| routes/production.py | 829 | 로컬 헬퍼 18개 |
| routes/dashboard.py | 908 | |
| routes/material.py | 609 | Phase 3에서 분리됨 |
| routes/sales.py | 460 | |
| routes/delivery.py | 577 | |
| routes/drawing.py | 343 | |
| routes/barcode.py | 216 | Phase 3에서 분리됨 |

---

## 2. Goals

### 2.1 정량 목표
| 지표 | 현재 | 목표 |
|------|-----:|-----:|
| handle_detail_common() 라인 | 697 | ≤150 (디스패치만) |
| project.py 전체 라인 | 1,265 | ≤700 |
| 서비스 모듈 수 | 0 | 4~5개 |
| _date_to_dt_start 중복 | 2곳 | 0 (utils.py로 통합) |

### 2.2 정성 목표
- 각 action 핸들러가 독립 함수로 분리되어 개별 수정 가능
- 서비스 레이어가 라우트와 분리되어 향후 REST API 전환 용이
- production.py 로컬 헬퍼도 정리하여 모듈 일관성 확보

---

## 3. Scope

### 3.1 In-Scope (Phase 4)

| ID | 요구사항 | 우선순위 |
|----|----------|:--------:|
| FR-01 | `_date_to_dt_start()` 중복 제거 → `modules/utils.py` | HIGH |
| FR-02 | 프로젝트 action 서비스 추출 (`modules/services/project_actions.py`) | HIGH |
| FR-03 | 계약 action 서비스 추출 (`modules/services/contract_actions.py`) | HIGH |
| FR-04 | 바코드 action 서비스 추출 (`modules/services/barcode_actions.py`) | HIGH |
| FR-05 | 연락처/히스토리 action 서비스 추출 (`modules/services/contact_actions.py`) | MEDIUM |
| FR-06 | handle_detail_common → 디스패치 함수로 축소 | HIGH |
| FR-07 | production.py 로컬 헬퍼 정리 (spec 관련 → spec_utils.py 통합) | MEDIUM |
| FR-08 | project.py ≤700줄 검증 | HIGH |

### 3.2 Out-of-Scope (Phase 5+)
- REST API 엔드포인트 추가
- 프론트엔드 AJAX 호출 패턴 변경
- 단위 테스트 작성
- dashboard.py 리팩토링 (908줄)
- drawing.py 서비스 분리

---

## 4. Approach

### 4.1 서비스 레이어 패턴

```
routes/project.py (디스패치)
  ↓ action별 분기
modules/services/project_actions.py   (프로젝트 정보 수정)
modules/services/contract_actions.py  (계약/품목 CRUD)
modules/services/barcode_actions.py   (바코드 CRUD)
modules/services/contact_actions.py   (연락처/히스토리)
```

각 서비스 함수 시그니처: `def handle_xxx(db, project, request_form, current_user) -> dict`
- 반환값: `{'success': bool, 'flash_msg': str, 'redirect': bool}`
- 라우트는 결과에 따라 flash/redirect만 수행

### 4.2 Sub-phase 구성

| Phase | 내용 | 예상 체크포인트 |
|-------|------|:--------------:|
| 4-1 | `_date_to_dt_start` 통합 + services 디렉토리 생성 | 2개 |
| 4-2 | project_actions.py 추출 (4 actions) | 2개 |
| 4-3 | contract_actions.py 추출 (4 actions) | 2개 |
| 4-4 | barcode_actions.py 추출 (3 actions) | 2개 |
| 4-5 | contact_actions.py 추출 (5 actions) | 2개 |
| 4-6 | handle_detail_common 디스패치화 + 검증 | 2개 |

---

## 5. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| action 분리 시 DB 세션 컨텍스트 | 트랜잭션 깨짐 | db 세션을 파라미터로 전달, commit은 라우트에서만 |
| 기존 flash/redirect 패턴 | 서비스 함수에서 Flask 의존 | 서비스는 dict 반환, Flask 호출은 라우트에서만 |
| production.py 헬퍼 의존성 | 다른 파일에서 참조 | 점진적 이동, import 호환성 유지 |

---

## 6. File Change Matrix

| Action | File | Type |
|--------|------|------|
| CREATE | `modules/services/__init__.py` | 패키지 초기화 |
| CREATE | `modules/services/project_actions.py` | 프로젝트 action 핸들러 |
| CREATE | `modules/services/contract_actions.py` | 계약 action 핸들러 |
| CREATE | `modules/services/barcode_actions.py` | 바코드 action 핸들러 |
| CREATE | `modules/services/contact_actions.py` | 연락처/히스토리 action 핸들러 |
| MODIFY | `modules/utils.py` | `_date_to_dt_start` 추가 |
| MODIFY | `routes/project.py` | handle_detail_common 축소 |
| MODIFY | `routes/material.py` | `_date_to_dt_start` import 변경 |
| MODIFY | `routes/production.py` | spec 헬퍼 정리 (선택) |
| **Total** | **5 CREATE + 4 MODIFY = 9 files** | |
