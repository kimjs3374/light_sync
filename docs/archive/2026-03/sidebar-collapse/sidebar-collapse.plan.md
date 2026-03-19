# Sidebar Collapse Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | ERP 기능이 20개+ 메뉴로 증가하면서 250px 고정 사이드바가 화면을 잡아먹고, 메뉴 찾기가 번거로움. 부서마다 자주 쓰는 메뉴 3~5개인데 전체 20개를 항상 노출 |
| Solution | 접이식 사이드바(250px↔60px) + 즐겨찾기 핀 기능. 평소 아이콘 모드로 가로폭 확보, 호버/클릭으로 확장. 자주 쓰는 메뉴는 최상단 고정 |
| Function UX Effect | 테이블 화면에서 190px 추가 확보. 즐겨찾기 메뉴 1클릭 접근. 접힘 상태에서도 아이콘으로 그룹 식별 가능 |
| Core Value | 메뉴가 30개, 50개로 늘어도 사이드바 UX가 파탄나지 않는 확장 가능한 네비게이션 구조 확보 |

## 1. Background

### 현재 구조

- `base.html` 사이드바: 250px 고정, `position: fixed`
- `.main-content`: `margin-left: 250px`
- 메뉴 그룹: 아코디언(한 번에 1그룹만 펼침), localStorage로 마지막 그룹 기억
- 모바일(<992px): 숨김 → 햄버거 버튼으로 슬라이드 인
- 메뉴 구성: 공통 3개 + 동적 그룹(영업부/관리부/생산부/공유) + 시스템

### 현재 문제

| # | 문제 | 영향 |
|---|------|------|
| 1 | 250px 항상 차지 | 테이블 가로폭 부족, 특히 발주/입고/BOM 등 컬럼 많은 화면 |
| 2 | 메뉴 20개+ 스크롤 | 아코디언 접어도 그룹 토글 6개가 세로로 나열 |
| 3 | 자주 쓰는 메뉴 접근 | 그룹 열어야 메뉴 보임, 매번 2클릭 |
| 4 | 확장성 한계 | 메뉴 추가할 때마다 사이드바 길이 증가 |

## 2. Requirements

### 2.1 접이식 사이드바

| # | 요구사항 | 우선순위 |
|---|----------|---------|
| R1 | 사이드바 접힘(60px) / 펼침(250px) 토글 | 필수 |
| R2 | 접힘 상태: 그룹 아이콘만 표시 | 필수 |
| R3 | 접힘 상태에서 아이콘 호버 → 해당 그룹 서브메뉴 플라이아웃(툴팁처럼 옆에 표시) | 필수 |
| R4 | 펼침/접힘 상태 localStorage 저장 | 필수 |
| R5 | 펼침↔접힘 전환 시 CSS transition (0.2s ease) | 필수 |
| R6 | 모바일(<992px)은 기존 방식 유지 (풀 사이드바 슬라이드) | 필수 |

### 2.2 즐겨찾기

| # | 요구사항 | 우선순위 |
|---|----------|---------|
| F1 | 메뉴 항목에 ⭐ 토글 버튼 (펼침 상태에서만 표시) | 필수 |
| F2 | 즐겨찾기 메뉴는 사이드바 최상단 "즐겨찾기" 그룹에 표시 | 필수 |
| F3 | 즐겨찾기 데이터는 localStorage 저장 (유저별 브라우저 기준) | 필수 |
| F4 | 접힘 상태에서도 즐겨찾기 아이콘(⭐) 표시, 호버 시 플라이아웃 | 필수 |
| F5 | 최대 8개 제한 | 필수 |

### 2.3 그룹 아이콘 매핑

| 그룹 | 아이콘 | 비고 |
|------|--------|------|
| 즐겨찾기 | ⭐ | 최상단 고정 |
| 현황 | 📊 | 메인현황판, 종합현황 |
| 업무보고 | 📝 | 일일보고, 주간보고 |
| 영업부 | 💼 | 설계/계약/영업/납품 |
| 관리부 | 📋 | 품목/자재/거래처/발주/입고/BOM/매출/재고 |
| 공유 | 🔗 | 조달내역/납품집계/하자관리 |
| 생산부 | 🏭 | 생산관리 |
| 시스템 | ⚙️ | 시스템관리 (admin) |

## 3. Scope

### In Scope
- `base.html` 사이드바 CSS/HTML/JS 수정
- 접이식 토글 버튼 추가
- 즐겨찾기 localStorage 로직
- 그룹별 아이콘 표시
- 플라이아웃 서브메뉴 (접힘 상태)
- `.main-content` margin 동적 변경

### Out of Scope
- 메뉴 그룹 재편 (부서별 → 업무흐름별) — 별도 기능으로 분리
- 서버사이드 즐겨찾기 저장 (DB) — 향후 개선
- Ctrl+K 커맨드 팔레트 — 별도 기능으로 분리
- MENU_REGISTRY / config.py 변경 없음

## 4. Technical Approach

### 4.1 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `templates/base.html` | 사이드바 HTML 구조 변경, CSS 추가, JS 로직 추가 |
| `config.py` | MENU_REGISTRY에 `icon` 필드 추가 (그룹별 아이콘) |

### 4.2 CSS 구조

```
.sidebar                    → width: 250px (기본 펼침)
.sidebar.collapsed          → width: 60px
.sidebar.collapsed .sidebar-label   → display: none (텍스트 숨김)
.sidebar.collapsed .sidebar-icon    → display: block (아이콘만)
.sidebar .flyout            → position: absolute, left: 60px (플라이아웃)
.main-content               → margin-left: 250px
.main-content.shifted       → margin-left: 60px
```

### 4.3 JS 로직

```
1. 토글 버튼 클릭 → .sidebar.collapsed 토글
2. localStorage('sidebar_collapsed') 저장
3. .main-content.shifted 토글
4. 접힘 상태 아이콘 호버 → .flyout 표시
5. 즐겨찾기 ⭐ 클릭 → localStorage('sidebar_favorites') 배열 관리
6. 페이지 로드 시 즐겨찾기 메뉴 최상단 렌더링
```

### 4.4 접힘 상태 플라이아웃 동작

```
[60px 사이드바]     [플라이아웃]
┌──────┐
│  ⭐  │ ← 호버 → ┌─────────────┐
│  📊  │          │ 메인 현황판  │
│  📝  │          │ 종합현황     │
│  💼  │          └─────────────┘
│  📋  │
│  🏭  │
│  ⚙️  │
│ ──── │
│  ◀▶  │ ← 토글 버튼
└──────┘
```

## 5. Implementation Order

| # | 작업 | 예상 범위 |
|---|------|-----------|
| 1 | config.py MENU_REGISTRY에 그룹 아이콘 추가 | 5줄 |
| 2 | base.html 사이드바 HTML 구조 변경 (아이콘 + 라벨 분리) | 30줄 |
| 3 | 접이식 CSS (.collapsed, .flyout, transition) | 50줄 |
| 4 | 토글 버튼 + localStorage 연동 JS | 20줄 |
| 5 | 플라이아웃 호버 로직 JS | 25줄 |
| 6 | 즐겨찾기 기능 (⭐ 토글 + localStorage + 렌더링) | 40줄 |
| 7 | .main-content margin 동적 전환 | 5줄 |
| 8 | 모바일 호환성 확인 (992px 이하 기존 동작 유지) | 검증 |

## 6. Risks

| 리스크 | 대응 |
|--------|------|
| 플라이아웃이 페이지 콘텐츠 위에 겹침 | z-index 관리, 바깥 클릭 시 닫기 |
| 모바일에서 접힘 모드 충돌 | 992px 이하에서는 collapsed 클래스 무시 |
| 즐겨찾기 localStorage 브라우저간 미동기화 | 현 단계에서는 허용, 향후 DB 저장 고려 |
| 기존 사이드바 JS (그룹 토글) 충돌 | 펼침 상태에서는 기존 로직 그대로 유지 |
