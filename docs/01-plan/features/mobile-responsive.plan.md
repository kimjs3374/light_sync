# Plan: mobile-responsive

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 전체 모바일 반응형 최적화 |
| 작성일 | 2026-03-23 |
| 예상 규모 | Large (90+ 템플릿, 14 CSS) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 90개+ 템플릿 중 ~16개만 모바일 대응, 나머지는 테이블 overflow/폼 깨짐으로 현장 외근 시 사용 불가 |
| **Solution** | 공통 CSS 보강 + mobile-stack-table 일괄 적용 + 페이지별 레이아웃 조정 |
| **Function UX Effect** | 현장/차량 이동 중 스마트폰으로 ERP 조회·입력 가능 |
| **Core Value** | 외근 직원의 ERP 접근성 확보 → 실시간 데이터 활용 → 업무 속도 향상 |

---

## 1. 현황 분석

### 1.1 이미 갖춰진 기반 (60%)
- `viewport` 메타태그 설정 완료
- Bootstrap 5.3 반응형 그리드 사용
- 사이드바 모바일 토글 (`mobile-menu-btn` + backdrop) 구현
- `mobile-stack-table` 카드 스택 패턴 정의 (magnatech.css)
- 챗봇 패널 모바일 bottom-sheet 변환 구현
- `table-responsive` 래퍼 57개 템플릿 적용
- `mobile-table.js` 글로벌 로드

### 1.2 핵심 문제점
| 문제 | 영향 범위 | 심각도 |
|------|----------|--------|
| `mobile-stack-table` 미적용 테이블 | ~54개 템플릿 | 상 |
| `min-width: 860~1200px` 인라인 스타일 | ~12개 관리 페이지 | 상 |
| `overflow-x: visible !important` 역효과 | 전체 (magnatech.css) | 상 |
| `#timelinePanel` 고정 380px | base.html | 중 |
| 입력 폼 테이블 모바일 미대응 | po_create, fo_create 등 ~6개 | 중 |
| `page-sticky-bar` 모바일 숨김 (대체 없음) | 전체 | 하 |
| 대시보드 캘린더 요일 라벨 소실 | dashboard.html | 하 |

---

## 2. 작업 범위 및 우선순위

### Phase 1: 공통 CSS 보강 (효과 극대화)
> 이것만으로 전체 60~70% 자동 개선

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| 1-1 | `overflow-x: visible !important` 수정 | magnatech.css | `mobile-stack-table` 컨테이너에만 적용되도록 스코프 제한 |
| 1-2 | `#timelinePanel` 반응형 | magnatech.css / base.html | 인라인 width:380px → CSS max-width:100vw |
| 1-3 | 모바일 기본 여백/폰트 보강 | magnatech.css | 카드 패딩, 테이블 폰트 축소, 버튼 터치 타겟 44px |
| 1-4 | 필터 영역 모바일 접기 | magnatech.css | 리스트 페이지 공통 필터바 collapse 토글 |
| 1-5 | `.no-stack-table` 수평 스크롤 보장 | magnatech.css | 입력 테이블용 안전한 가로 스크롤 |

### Phase 2: 핵심 업무 페이지 (자주 쓰는 화면)
> 현장 외근 시 가장 많이 조회하는 페이지

| # | 페이지 | 파일 | 작업 |
|---|--------|------|------|
| 2-1 | 대시보드 | dashboard.html, dashboard.css | 캘린더 라벨, 티커 버튼 wrap |
| 2-2 | 현장 목록 | project_list.html | mobile-stack-table 적용, min-width 제거 |
| 2-3 | 현장 상세 | project_detail.html | 조도 테이블 래핑, 사이드 정보 스택 |
| 2-4 | 계약 목록 | contract_list.html | mobile-stack-table 적용 |
| 2-5 | 계약 상세 | contract_detail.html | 이미 부분 대응, 미비점 보완 |
| 2-6 | 납품 관리 | delivery_management.html | mobile-stack-table + min-width 제거 |
| 2-7 | 납품 상세 | delivery_detail.html | 폼 레이아웃 조정 |
| 2-8 | A/S 목록 | warranty_list.html | mobile-stack-table 적용 |
| 2-9 | A/S 상세 | warranty_case_detail.html | 카드 스택 |

### Phase 3: 관리 페이지
| # | 페이지 | 파일 | 작업 |
|---|--------|------|------|
| 3-1 | 생산 관리 | production_management.html | min-width 제거, 카드 스택 |
| 3-2 | 자재 관리 | material_management.html | min-width 제거, 카드 스택 |
| 3-3 | 자재 상세 | material_detail.html | 3개 테이블 모두 대응 |
| 3-4 | 발주 목록 | po_list.html | mobile-stack-table 적용 |
| 3-5 | 발주 상세 | po_detail.html | 카드 스택 |
| 3-6 | 입고 목록 | receiving_list.html | mobile-stack-table 적용 |
| 3-7 | 조달 목록 | procurement_list.html | mobile-stack-table 적용 |
| 3-8 | 영업 목록 | sales_list.html | mobile-stack-table 적용 |
| 3-9 | 매출 대시보드 | financial_dashboard.html | 차트 리사이즈 |

### Phase 4: 폼/입력 페이지
| # | 페이지 | 파일 | 작업 |
|---|--------|------|------|
| 4-1 | 발주 생성 | po_create.html | 아이템 테이블 가로 스크롤 or 카드 전환 |
| 4-2 | 가공발주 생성 | fo_create.html | 아이템 테이블 가로 스크롤 |
| 4-3 | BOM 생성 | bom_create.html | no-stack 유지 + 스크롤 보장 |
| 4-4 | 입고 등록 | receiving_create.html | 같은 패턴 |
| 4-5 | 견적 생성 | quotation_create.html | 이미 일부 대응, 보완 |
| 4-6 | 프로젝트 생성 | project_create.html | 폼 레이아웃 확인 |

### Phase 5: 나머지 페이지
| # | 카테고리 | 대상 수 | 작업 |
|---|---------|---------|------|
| 5-1 | 재고 관련 | 7개 | mobile-stack-table 일괄 적용 |
| 5-2 | BOM 상세/목록 | 3개 | min-width 제거 + 스택 |
| 5-3 | 품목 관련 | 4개 | 스택 적용 |
| 5-4 | 도면/사진 갤러리 | 3개 | 이미 그리드 반응형 (확인만) |
| 5-5 | 보고서 | 3개 | 인쇄용이므로 최소 대응 |
| 5-6 | 조명배치도 | 4개 | 카드 스택 |
| 5-7 | 조도검증 | 3개 | 이미 부분 대응, 보완 |
| 5-8 | 알림/아카이브 | 4개 | 단순 리스트, 빠른 대응 |
| 5-9 | 인증서/시방서 | 2개 | 간단 테이블 |
| 5-10 | 로그인/프로필 | 3개 | 폼 확인 |

### 제외 대상
| 페이지 | 사유 |
|--------|------|
| production_display.html | TV 전용 전사현황판 |
| report_weekly*.html | 인쇄 전용 |
| admin_settings.html | 관리자 데스크톱 전용 |

---

## 3. 구현 전략

### 3.1 접근 방식: Top-Down (공통 → 개별)
```
Phase 1 (공통 CSS)  ──→  자동으로 60~70% 개선
     ↓
Phase 2 (핵심 페이지) ──→  가장 많이 쓰는 9개 화면 완성
     ↓
Phase 3~5 (나머지)  ──→  점진적 적용
```

### 3.2 핵심 패턴 (이미 존재하는 것 활용)
1. **`mobile-stack-table`**: 테이블 → 카드형 자동 변환 (magnatech.css에 정의됨)
2. **`table-responsive`**: 가로 스크롤 래퍼 (Bootstrap 기본)
3. **`no-stack-table`**: 입력 테이블용 스택 방지 + 가로 스크롤
4. **Bootstrap 그리드**: `col-md-*` → `col-12` 자동 폴백

### 3.3 테스트 기준
- 대상 뷰포트: 375px (iPhone SE), 390px (iPhone 14), 768px (iPad)
- 체크리스트:
  - [ ] 가로 스크롤 없음 (페이지 레벨)
  - [ ] 터치 타겟 44px 이상
  - [ ] 텍스트 가독성 (최소 14px)
  - [ ] 테이블 데이터 접근 가능 (스택 or 스크롤)
  - [ ] 폼 입력 가능

---

## 4. 리스크

| 리스크 | 대응 |
|--------|------|
| 데스크톱 레이아웃 깨짐 | media query 내부에서만 변경, 기존 스타일 미수정 |
| mobile-stack-table 일괄 적용 시 일부 테이블 깨짐 | data-label 속성 확인 필요 |
| 인라인 min-width 제거 시 데스크톱 테이블 좁아짐 | media query 내부에서만 min-width:0 오버라이드 |

---

## 5. 완료 기준

- [ ] Phase 1 공통 CSS 완료 → 전체 페이지 기본 모바일 지원
- [ ] Phase 2 핵심 9개 페이지 모바일 최적화 완료
- [ ] Phase 3~5 나머지 페이지 순차 적용
- [ ] 375px 뷰포트 기준 가로 스크롤 없음 검증
