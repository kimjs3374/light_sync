# 품목 자동완성 입력 - Plan

> **Feature**: product-autocomplete
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Plan

---

## Executive Summary

| Item | Detail |
|------|--------|
| **Feature** | 품목 모델명 입력 시 ProductCatalog DB 기반 자동완성 |
| **PDCA Start** | 2026-03-17 |
| **Estimated Scope** | API 1개 + JS 컴포넌트 1개 + 템플릿 4개 수정 |

### Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 품목 추가 시 모델명을 매번 수기 입력 — 오타 위험, 느린 입력, 카탈로그 267건의 정확한 모델명 기억 불가 |
| **Solution** | 텍스트 입력 시 ProductCatalog에서 실시간 검색하여 후보 목록 표시 (타이핑 자동완성) |
| **Function/UX Effect** | 2~3글자 입력 시 매칭 품목 드롭다운 표시, 선택하면 모델명+규격 자동 채움, 직접 입력도 가능 |
| **Core Value** | 입력 속도 향상, 오타 방지, 카탈로그 단가 정보와 자연스러운 연결 |

---

## 1. 배경 및 목표

### 1.1 현재 상태
- 설계관리(project_create, project_detail)와 계약관리(contract_detail)에서 품목 추가 시 `<input type="text">`로 모델명 수기 입력
- ProductCatalog 테이블에 267건의 자사 제품 데이터 존재 (나라장터 G2B API 동기화)
- 두 데이터가 연결되지 않아, 동일 모델이 다른 이름으로 입력되는 경우 발생

### 1.2 목표
- 모델명 입력 필드에 **타이핑 자동완성** 적용
- ProductCatalog 데이터를 실시간 검색하여 후보 표시
- 선택 시 모델명, 규격 등 관련 정보 자동 채움
- 카탈로그에 없는 신규 모델도 자유롭게 입력 가능 (강제 X)

---

## 2. Functional Requirements

### FR-01: 자동완성 검색 API
- `GET /api/catalog/search?q=ARENA&category=투광등기구`
- ProductCatalog에서 `model_name`, `item_name`, `spec` 기준 LIKE 검색
- category 파라미터로 품목군 필터링 (선택적)
- 최대 10건 반환
- 응답: `[{id, model_name, item_name, spec, unit_price}, ...]`

### FR-02: 자동완성 UI 컴포넌트
- 기존 `<input type="text">` 유지 + 자동완성 기능 추가
- **2글자 이상** 입력 시 검색 시작
- **300ms 디바운스** 적용 (타이핑 중 과도한 API 호출 방지)
- 입력 필드 아래에 후보 목록 드롭다운 표시
- 키보드 탐색 지원 (↑↓ 화살표, Enter 선택, Esc 닫기)
- 후보 표시 형식: `모델명 — 규격 (단가)`

### FR-03: 자동 채움
- 후보 선택 시 model_name 필드에 모델명 자동 입력
- 카테고리가 일치하면 category 필드도 자동 선택
- 선택하지 않고 직접 타이핑 완료도 허용 (자유 입력)

### FR-04: 적용 대상 페이지
| 페이지 | 입력 필드 | 비고 |
|--------|----------|------|
| `project_create.html` | `light_model[]` | 설계 현장 등록 |
| `project_detail.html` | 자재 추가 모델명 | 설계 상세 |
| `contract_detail.html` | `model_name` (신규 품목 추가) | 계약 상세 |
| `contract_detail.html` | `model_name` (기존 품목 수정) | 계약 상세 |

### FR-05: 성능 요구사항
- API 응답 100ms 이내
- 디바운스 300ms + API 100ms = 사용자 체감 0.4초 이내
- 외부 라이브러리 없이 순수 JS로 구현 (Bootstrap 5 스타일 활용)

---

## 3. Non-Functional Requirements

### NFR-01: 하위 호환성
- 자동완성은 **선택적 보조 기능** — 기존 수기 입력 완전 유지
- JavaScript 비활성화 시에도 기본 텍스트 입력 동작

### NFR-02: 보안
- API는 로그인 세션 인증 필수 (`@login_required`)
- SQL Injection 방지 (SQLAlchemy 파라미터 바인딩)

### NFR-03: UX
- 드롭다운이 아닌 **타이핑 자동완성** (품목 267건 → 드롭다운 부적합)
- 모바일에서도 사용 가능한 반응형

---

## 4. 기술 설계 방향

### 4.1 아키텍처
```
[입력 필드] → (2글자+, 300ms 디바운스)
    → GET /api/catalog/search?q=...&category=...
    → [후보 드롭다운] → (선택)
    → model_name 자동 채움
```

### 4.2 구현 파일 (예상)

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `routes/api.py` | 수정 | 검색 API 엔드포인트 추가 |
| `templates/components/autocomplete.html` | 신규 | 재사용 가능한 자동완성 JS+CSS 컴포넌트 |
| `templates/project_create.html` | 수정 | 자동완성 컴포넌트 적용 |
| `templates/project_detail.html` | 수정 | 자동완성 컴포넌트 적용 |
| `templates/contract_detail.html` | 수정 | 자동완성 컴포넌트 적용 |

### 4.3 자동완성 방식: 순수 JS (라이브러리 없음)
- Bootstrap 5 `dropdown-menu` 스타일 재활용
- `fetch` API + `AbortController`로 이전 요청 취소
- 이벤트 위임으로 동적 추가된 입력 필드에도 자동 적용

---

## 5. 리스크 및 제약

| 리스크 | 대응 |
|--------|------|
| 동적 행 추가 시 자동완성 미적용 | 이벤트 위임(delegation)으로 해결 |
| 카탈로그에 없는 모델 입력 차단 우려 | 자유 입력 허용, 자동완성은 보조 기능 |
| API 호출 과다 | 디바운스 300ms + 최소 2글자 조건 |

---

## 6. 구현 우선순위

1. **검색 API** (`/api/catalog/search`) — 핵심 백엔드
2. **자동완성 JS 컴포넌트** — 재사용 가능한 공통 모듈
3. **contract_detail.html 적용** — 가장 자주 사용하는 페이지
4. **project_create.html 적용** — 설계 등록
5. **project_detail.html 적용** — 설계 상세
