# Phase 5: 전체 라우트 서비스 레이어 추출 — Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| **Problem** | dashboard(908), production(829), material(603), delivery(577), sales(460) 5개 라우트에 비즈니스 로직이 인라인으로 혼재. 35개 action handler가 라우트 함수에 직접 작성되어 있고, 10+개 유틸 함수가 파일 간 중복됨 |
| **Solution** | Phase 4에서 검증된 ACTION_HANDLERS 디스패치 패턴을 5개 라우트에 동일 적용. 중복 유틸리티를 공유 모듈로 통합 |
| **Function/UX Effect** | 사용자 영향 없음 (내부 아키텍처). 개발자가 개별 action을 독립적으로 수정/테스트 가능 |
| **Core Value** | 전체 라우트의 일관된 아키텍처 달성. 서비스 레이어 분리로 향후 REST API 전환 기반 완성 |

---

## 1. Background

Phase 3에서 Blueprint 분리, Phase 4에서 project.py 서비스 레이어 추출을 완료.
동일 패턴을 나머지 5개 대형 라우트에 적용하여 일관된 코드 아키텍처를 달성한다.

### 현재 상태

| File | Lines | Routes | Actions | Large Functions (>100줄) |
|------|:-----:|:------:|:-------:|:------------------------:|
| dashboard.py | 908 | 2 | 4 | 3 (_build_action_tabs 161줄, _build_dashboard_priority_items 113줄, dashboard_view 339줄) |
| production.py | 829 | 2 | 8 | 2 (production_management 172줄, production_detail 372줄) |
| material.py | 603 | 2 | 5 | 2 (material_management 163줄, material_detail 260줄) |
| delivery.py | 577 | 3 | 13 | 2 (delivery_management 143줄, delivery_detail 275줄) |
| sales.py | 460 | 2 | 5 | 2 (sales_list 119줄, sales_detail 195줄) |
| **Total** | **3,377** | **11** | **35** | **11** |

### 중복 유틸리티 문제

| Category | Files | Duplicate Count |
|----------|-------|:--------------:|
| spec 검증 (_is_filled_spec_value 등) | production.py, sales.py | 10개 → 4개로 통합 |
| 날짜 계산 (_days_until, _project_dday) | dashboard.py, production.py | 2개 → utils.py 통합 |
| 권한 체크 (_is_admin 등) | dashboard.py, delivery.py, drawing.py | 3개 → auth_utils.py 통합 |

---

## 2. Goals

### 2.1 Primary Goals

1. **5개 라우트에 ACTION_HANDLERS 디스패치 패턴 적용** (35 actions → 서비스 모듈)
2. **중복 유틸리티 통합** (공유 모듈 생성)
3. **각 라우트 파일 목표 줄수 달성**

### 2.2 Target Line Counts

| File | Before | Target | Reduction |
|------|:------:|:------:|:---------:|
| dashboard.py | 908 | ≤500 | -45% |
| production.py | 829 | ≤400 | -52% |
| material.py | 603 | ≤350 | -42% |
| delivery.py | 577 | ≤300 | -48% |
| sales.py | 460 | ≤250 | -46% |

### 2.3 Non-Goals

- 템플릿 변경 없음
- 새로운 기능 추가 없음
- DB 모델 변경 없음

---

## 3. Implementation Approach

### 3.1 서비스 모듈 구조

Phase 4에서 `modules/services/` 하위에 project 관련 4개 모듈을 생성했음.
Phase 5에서 추가 생성:

```
modules/services/
  ├── __init__.py              (기존)
  ├── project_actions.py       (기존 - Phase 4)
  ├── contract_actions.py      (기존 - Phase 4)
  ├── barcode_actions.py       (기존 - Phase 4)
  ├── contact_actions.py       (기존 - Phase 4)
  ├── production_actions.py    (NEW - 8 handlers)
  ├── material_actions.py      (NEW - 5 handlers)
  ├── delivery_actions.py      (NEW - 13 handlers)
  ├── sales_actions.py         (NEW - 5 handlers)
  └── dashboard_actions.py     (NEW - 4 handlers)
```

### 3.2 공유 유틸리티 통합

```
modules/
  ├── utils.py                 (기존 + 날짜 계산 함수 추가)
  ├── spec_utils.py            (기존 + production/sales spec 함수 통합)
  └── dashboard_utils.py       (NEW - 대시보드 전용 통계/집계 로직)
```

### 3.3 서비스 함수 규약 (Phase 4 동일)

```python
def handle_xxx(db, project, form, current_user, **ctx) -> dict:
    # Flask 의존 없음, db.commit() 호출 안 함
    # return {'flash': (msg, cat), 'ajax_log': dict}
```

---

## 4. Sub-Phases (Size Order)

총 5개 서브페이즈. 각각 독립적으로 구현/검증 가능.

### Sub-Phase 5-1: production.py (829줄, 8 actions)
- production_detail()의 8개 action을 production_actions.py로 추출
- _spec_label 등 5개 spec 관련 함수를 spec_utils.py로 이동
- _as_bool(), _history_payload() 등 공용 유틸 정리

### Sub-Phase 5-2: delivery.py (577줄, 13 actions)
- delivery_detail()의 13개 action을 delivery_actions.py로 추출 (최다 action)
- _status_badge() 등 상태 유틸 정리

### Sub-Phase 5-3: material.py (603줄, 5 actions)
- material_detail()의 5개 action을 material_actions.py로 추출
- 기존 public 함수(sync_material_orders 등)는 유지

### Sub-Phase 5-4: sales.py (460줄, 5 actions)
- sales_detail()의 5개 action을 sales_actions.py로 추출
- _extract_item_spec 등 spec 함수는 spec_utils.py에 이미 통합된 것 활용

### Sub-Phase 5-5: dashboard.py (908줄, 4 actions + 통계로직)
- dashboard_notice_admin()의 4개 action을 dashboard_actions.py로 추출
- _build_action_tabs(), _build_dashboard_priority_items() 등 대형 집계 로직을 dashboard_utils.py로 추출
- dashboard_view() 339줄 → ≤150줄 목표

---

## 5. Risk & Constraints

| Risk | Mitigation |
|------|------------|
| 한 세션에 5개 파일 전부 불가능 | 서브페이즈별 독립 구현, 각각 syntax check |
| spec_utils.py 통합 시 기존 함수 충돌 | production/sales 전용 함수는 prefix로 구분 |
| material.py의 public 함수 의존 | sync_material_orders 등은 라우트에 유지 |
| 점진적 접근 필요 | "하나하나 천천히" 원칙 유지, 서브페이즈별 커밋 |

---

## 6. Success Criteria

- [ ] 5개 라우트 모두 ACTION_HANDLERS 디스패치 패턴 적용
- [ ] 서비스 함수에 Flask import 0개
- [ ] 서비스 함수에 db.commit() 0개
- [ ] 각 라우트 목표 줄수 달성
- [ ] 중복 유틸리티 3개 이상 통합
- [ ] 전체 syntax check 통과
- [ ] Gap Analysis 100%
