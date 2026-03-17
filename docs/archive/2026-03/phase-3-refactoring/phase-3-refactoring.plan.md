# Phase 3: Code Refactoring Plan

> **Feature**: phase-3-refactoring
> **Project**: Light-Sync (LED ERP)
> **Author**: Claude Code + User
> **Created**: 2026-03-17
> **Status**: Draft
> **PDCA Cycle**: #2

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | `routes/project.py`가 2,150줄로 비대화되고, 중복 유틸 함수(`_parse_date` 4곳, `_is_true_value` 2곳, `_to_int` 3곳)가 8개 라우트 파일에 산재하여 유지보수성과 코드 품질이 저하됨 |
| **Solution** | project.py를 material.py + barcode.py로 분할하고, 중복 유틸을 `modules/utils.py`로 통합하며, 상태 상수와 스펙 로직을 전용 모듈로 분리 |
| **Function/UX Effect** | 단일 파일 최대 줄 수 2,150 → ~600줄 (72% 감소), 중복 함수 12개 → 0개, 개발자 코드 탐색 및 수정 시간 단축 |
| **Core Value** | 코드베이스 유지보수성 확보로 향후 기능 추가/버그 수정 속도 향상 및 Phase 4 (성능 최적화) 진행 기반 마련 |

---

## 1. Background & Motivation

### 1.1 Previous PDCA Cycle Results

Phase 1 (Security) + Phase 2 (Stability) 완료 후 Design Match Rate 100% 달성.
아카이브: `docs/archive/2026-03/light-sync-improvement/`

### 1.2 Current Pain Points

| # | Issue | Severity | Evidence |
|---|-------|----------|----------|
| 1 | `project.py` 2,150줄 - 5개 이상 도메인 혼재 | Critical | 프로젝트/자재/바코드/계약/삭제 워크플로우 혼합 |
| 2 | `_parse_date()` 4곳 중복 정의 | High | project.py, production.py, delivery.py, sales.py |
| 3 | `_to_int()` 3곳 중복 정의 | High | project.py, production.py, delivery.py |
| 4 | `_is_true_value()` + `TRUE_VALUES` 2곳 중복 | Medium | project.py, sales.py |
| 5 | `_safe_int()` dashboard.py 로컬 중복 | Low | dashboard.py (utils.py에 이미 존재) |
| 6 | 상태 상수 산재 | Medium | project.py, production.py, sales.py에 분산 정의 |
| 7 | 스펙 추출/검증 로직 중복 | Medium | project.py, sales.py에 유사 로직 |
| 8 | 권한 체크 헬퍼 비표준화 | Low | 5개+ 파일에서 각자 세션 체크 |

---

## 2. Goals & Success Criteria

### 2.1 Goals

| # | Goal | Metric | Target |
|---|------|--------|--------|
| G-1 | project.py 크기 축소 | 줄 수 | 2,150 → ≤700줄 |
| G-2 | 중복 유틸 함수 제거 | 중복 함수 수 | 12개 → 0개 |
| G-3 | 상수/스펙 로직 중앙화 | 산재 정의 수 | 6곳 → 1곳 |
| G-4 | 기능 회귀 없음 | 기존 기능 정상 동작 | 100% |

### 2.2 Non-Goals (Scope 제외)

- 성능 최적화 (Phase 4 범위)
- GET 요청 시 sync 로직 제거 (Phase 4 범위)
- 모델 파일 분할 (entities.py 550줄 - 현재 관리 가능)
- UI/템플릿 변경 (url_for 경로만 필요 시 수정)
- 테스트 자동화 도입 (별도 PDCA 사이클)

---

## 3. Scope & Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Effort |
|----|------------|----------|--------|
| FR-01 | `routes/material.py` 신규 Blueprint 분리 (자재 관리 라우트 + 동기화 로직) | High | ~3hr |
| FR-02 | `routes/barcode.py` 신규 Blueprint 분리 (바코드 업로드/다운로드/파싱) | High | ~3hr |
| FR-03 | `modules/utils.py`에 `parse_date()`, `to_int()` 추가 및 전체 라우트 통합 | High | ~2hr |
| FR-04 | `_is_true_value()` + `TRUE_VALUES` → `modules/utils.py` 통합 | Medium | ~1hr |
| FR-05 | `dashboard.py` 로컬 `_safe_int()` → `modules/utils.py` 교체 | Low | ~15min |
| FR-06 | 스펙 추출/검증 로직 → `modules/spec_utils.py` 분리 | Medium | ~2hr |
| FR-07 | 상태 상수 → `modules/models/constants.py` 중앙화 | Medium | ~1hr |
| FR-08 | `app.py` Blueprint 등록 업데이트 (material_bp, barcode_bp) | High | ~15min |
| FR-09 | 분할 후 url_for 경로 정합성 검증 (템플릿 포함) | High | ~1hr |

### 3.2 Route File Target Structure

```
Before (현재):                          After (목표):
routes/project.py    (2,150줄)  →  routes/project.py    (~600줄)
                                    routes/material.py   (~300줄) NEW
                                    routes/barcode.py    (~250줄) NEW
                                    modules/spec_utils.py (~150줄) NEW

routes/dashboard.py  (914줄)    →  routes/dashboard.py  (~900줄) _safe_int 교체
routes/production.py (841줄)    →  routes/production.py (~830줄) 중복 제거
routes/delivery.py   (593줄)    →  routes/delivery.py   (~580줄) 중복 제거
routes/sales.py      (474줄)    →  routes/sales.py      (~460줄) 중복 제거
```

### 3.3 project.py 분할 상세

| Section | Lines | Destination | Description |
|---------|-------|-------------|-------------|
| 자재 관리 라우트 | 644-904 | `routes/material.py` | material_management, sync 함수 |
| 바코드 헬퍼 | 282-443 | `routes/barcode.py` | CSV/XLSX 파싱, 빌드 함수 |
| 바코드 라우트 | 185-213 | `routes/barcode.py` | barcode_template 다운로드 |
| 스펙 로직 | 47-123 | `modules/spec_utils.py` | extract/validate/format 함수 |
| 유틸 함수 | 215-268 | `modules/utils.py` | parse_date, to_int, 권한 체크 |
| 프로젝트 핵심 | 나머지 | `routes/project.py` | list, create, detail, delete |

---

## 4. Implementation Order

### Phase 3-1: 유틸 함수 통합 (FR-03, FR-04, FR-05)

1. `modules/utils.py`에 `to_int()`, 기존 `parse_date()` 확인/보강
2. `modules/utils.py`에 `TRUE_VALUES`, `is_true_value()` 이미 존재 확인
3. 8개 라우트 파일에서 로컬 중복 함수 제거 → import 교체
4. `dashboard.py`의 `_safe_int()` → `from modules.utils import safe_int`

**영향 파일**: project.py, production.py, delivery.py, sales.py, dashboard.py

### Phase 3-2: 스펙 로직 분리 (FR-06)

1. `modules/spec_utils.py` 생성
2. project.py에서 `_extract_contract_item_spec()`, `_validate_contract_item_spec()`, `_format_spec_summary()` 이동
3. sales.py에서 `_extract_item_spec()` → 통합 또는 래퍼 함수
4. import 경로 업데이트

**영향 파일**: project.py, sales.py, production.py

### Phase 3-3: 상태 상수 중앙화 (FR-07)

1. `modules/models/constants.py`에 상태 상수 추가
2. 각 라우트에서 로컬 상수 정의 제거 → import
3. 기존 상수 (`DRAWING_TYPE_OPTIONS` 등) 패턴 따름

**영향 파일**: project.py, production.py, sales.py, delivery.py

### Phase 3-4: material.py Blueprint 분리 (FR-01)

1. `routes/material.py` 생성, `material_bp` Blueprint 정의
2. 자재 관리 관련 라우트 이동 (material_management)
3. sync 함수 이동 (`_sync_material_orders`, `_sync_material_orders_for_contract_item`)
4. `app.py`에 `material_bp` 등록
5. 템플릿의 `url_for('project.material_management')` → `url_for('material.material_management')` 변경

**영향 파일**: project.py, app.py, 관련 템플릿

### Phase 3-5: barcode.py Blueprint 분리 (FR-02)

1. `routes/barcode.py` 생성, `barcode_bp` Blueprint 정의
2. 바코드 관련 헬퍼 함수 이동 (CSV/XLSX 파싱, 빌드)
3. barcode_template 라우트 이동
4. `app.py`에 `barcode_bp` 등록
5. 템플릿 url_for 경로 업데이트

**영향 파일**: project.py, app.py, 관련 템플릿

### Phase 3-6: 정합성 검증 (FR-08, FR-09)

1. `app.py` Blueprint 등록 확인
2. 전체 `url_for` 경로 grep으로 broken link 검출
3. 수동 기능 테스트 (프로젝트 CRUD, 자재, 바코드)

---

## 5. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| url_for 경로 누락으로 404 발생 | Medium | High | grep으로 전수 검사, 단계별 테스트 |
| 순환 import 발생 | Low | Medium | Blueprint 간 의존성 최소화, 유틸은 modules/에 집중 |
| handle_detail_common() 분리 실패 | Medium | High | Phase 3에서는 project.py에 유지, Phase 4에서 서비스 레이어 도입 시 분리 |
| 템플릿 내 하드코딩된 경로 | Low | Medium | Jinja2의 url_for만 사용 확인 |

---

## 6. Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Phase 1+2 완료 | ✅ Archived | 보안/안정성 기반 확보 완료 |
| modules/utils.py 존재 | ✅ | Phase 2에서 생성됨 |
| modules/models/constants.py 존재 | ✅ | 기존 상수 정의 파일 |
| Flask Blueprint 구조 이해 | ✅ | 현재 9개 Blueprint 운영 중 |

---

## 7. Estimated Timeline

| Phase | Task | Duration |
|-------|------|----------|
| 3-1 | 유틸 함수 통합 | ~2hr |
| 3-2 | 스펙 로직 분리 | ~2hr |
| 3-3 | 상태 상수 중앙화 | ~1hr |
| 3-4 | material.py 분리 | ~3hr |
| 3-5 | barcode.py 분리 | ~3hr |
| 3-6 | 정합성 검증 | ~1hr |
| **Total** | | **~12hr** |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial Phase 3 Plan | Claude Code |
