# Production Redesign Design Document

> **Summary**: 생산관리 전면 재설계 — 작업자 중심 카드형 UI + 인라인 AJAX + 모바일 최적화
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-19
> **Status**: Draft
> **Planning Doc**: [production-redesign.plan.md](../01-plan/features/production-redesign.plan.md)

---

## 1. Overview

### 1.1 Design Goals
- 기존 3페이지(목록/상세/모달)를 **1페이지 카드형**으로 통합
- 모든 조작(상태변경, 수량입력)은 **AJAX** — 페이지 새로고침 0
- **모바일/태블릿** 완벽 지원 (카드 그리드, 터치 토글)
- 기존 `production_logic.py`, `production_actions.py`, DB 모델 **최대 재활용**

### 1.2 Design Principles
- 작업자의 행동은 2개: "오늘 뭐 해야 됨?" + "몇 개 했음?" — 이 2개에 최적화
- 관리자 조망은 `/production/display` (기존 TV 현황판)로 충분
- 공정 카드 1장에 모든 정보 + 액션 포함 (다른 페이지 이동 불필요)

---

## 2. Architecture

### 2.1 라우트 구조

| Method | Path | Description | 비고 |
|--------|------|-------------|------|
| GET | `/production` | 카드형 통합 메인 (HTML) | **신규** — 기존 목록+상세 대체 |
| GET | `/production/display` | TV 현황판 | 유지 |
| GET | `/api/weather` | 날씨 프록시 | 유지 |
| POST | `/api/production/process/<id>/toggle` | 공정 ON/OFF 토글 | **신규** AJAX |
| POST | `/api/production/process/<id>/daily-log` | 일일 수량 입력 | **신규** AJAX |
| POST | `/api/production/process/<id>/complete` | 공정 완료 처리 | **신규** AJAX |
| POST | `/api/production/sync/<project_id>` | 공정 동기화 | **리팩토링** (기존 form POST → AJAX) |
| GET | `/production_management` | redirect → `/production` | 하위 호환 |
| GET | `/production_management/<id>` | redirect → `/production?site=<id>` | 하위 호환 |

### 2.2 Data Flow

```
[카드 토글 클릭]
  → POST /api/production/process/<id>/toggle {is_active: true/false}
  → production_actions.handle_toggle_process_active() 재활용
  → JSON {ok, process_status, item_status, progress_pct, history_log}
  → JS가 카드 DOM 업데이트 (상태뱃지, 프로그레스바)

[수량 입력 엔터]
  → POST /api/production/process/<id>/daily-log {daily_qty: N}
  → production_actions.handle_add_daily_log() 재활용
  → JSON {ok, progress_qty, progress_pct, item_status, remain}
  → JS가 카드 DOM 업데이트 (수량, 프로그레스바, autosave dot)
```

---

## 3. Data Model

### 3.1 DB 변경 없음
기존 `ProductionProcess`, `ProductionDailyLog`, `ContractItem` 그대로 사용.

### 3.2 메인 페이지 데이터 구조

Route에서 전체 공정을 한번에 로드하여 상태별로 그룹핑:

```python
# /production route context
{
    'groups': {
        'working': [...],   # status == '진행중'
        'ready': [...],     # status == '대기' and materials_ready and can_start
        'waiting': [...],   # status == '대기' and (not materials_ready or not can_start)
        'done': [...],      # status in ('완료', '스킵')
    },
    'stats': {
        'total': 45, 'working': 12, 'ready': 5, 'waiting': 8, 'done': 20
    },
    'today_logs': [...],    # 오늘 날짜 ProductionDailyLog
    'filter_options': {
        'sites': [{'id': 1, 'name': '강릉'}, ...],
        'categories': ['투광등기구', '가로등기구', ...],
    },
}
```

### 3.3 공정 카드 데이터 (1장)

```python
{
    'process_id': 123,
    'process_name': 'PCB 조립',
    'step_order': 3,
    'status': '진행중',
    'is_forced': False,
    'progress_qty': 12,
    'progress_pct': 60.0,
    'started_at': '2026-03-18 09:30',
    # 품목 정보
    'item_id': 45,
    'model_name': 'ARENA-400',
    'category': '투광등기구',
    'quantity': 20,
    # 현장 정보
    'project_id': 10,
    'site_name': '강릉시 종합운동장',
    'project_no': 'P2026-015',
    # 납기
    'delivery_date': '2026-04-15',
    'dday': 27,
    # 자재 상태
    'materials_ready': True,
    # 의존관계
    'can_start': True,
    'prev_process': '히트파이프 조립 (완료)',
    # 오늘 수량
    'today_qty': 5,  # 오늘 이미 입력한 수량
}
```

---

## 4. API Specification

### 4.1 POST `/api/production/process/<id>/toggle`

공정 ON(진행중) / OFF(대기) 토글.

**Request:**
```json
{"is_active": true}
```
OFF 시: `{"is_active": false, "off_reason": "자재 입고 지연"}`

**Response (200):**
```json
{
    "ok": true,
    "process_id": 123,
    "process_status": "진행중",
    "item_id": 45,
    "item_status": "생산중",
    "progress_pct": 60.0,
    "started_at": "2026-03-19 14:30"
}
```

### 4.2 POST `/api/production/process/<id>/daily-log`

일일 수량 입력 (오늘 날짜 자동).

**Request:**
```json
{"daily_qty": 5}
```

**Response (200):**
```json
{
    "ok": true,
    "process_id": 123,
    "progress_qty": 17,
    "progress_pct": 85.0,
    "remain": 3,
    "item_status": "생산중",
    "today_total": 5
}
```

### 4.3 POST `/api/production/process/<id>/complete`

공정 완료 처리 (progress와 무관하게 강제 완료).

**Request:**
```json
{"complete": true}
```
완료 해제: `{"complete": false}`

**Response (200):**
```json
{
    "ok": true,
    "process_id": 123,
    "process_status": "완료",
    "item_status": "생산중",
    "completed_at": "2026-03-19 16:00"
}
```

---

## 5. UI/UX Design

### 5.1 전체 레이아웃

```
┌──────────────────────────────────────────────────────┐
│ 🏭 생산관리          [공정 동기화]                      │
├──────────────────────────────────────────────────────┤
│ [공정별] [현장별] [오늘생산]                             │
│ [상태▼] [카테고리▼] [현장검색____]                      │
│                                                      │
│ 📊 총 45 | 진행중 12 | 대기 13 | 완료 20              │
├──────────────────────────────────────────────────────┤
│                                                      │
│ 🔴 진행중 (12)                                        │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │
│ │ PCB 조립      │ │ 렌즈부 조립   │ │ 파이프 재단   │  │
│ │              │ │              │ │              │  │
│ │ ARENA-400    │ │ ARENA-400    │ │ MTPS-201-5   │  │
│ │ 강릉 종합운동장│ │ 강릉 종합운동장│ │ 서울 OO공원  │  │
│ │ 20ea D-27    │ │ 20ea D-27    │ │ 30ea D-14    │  │
│ │              │ │              │ │              │  │
│ │ [████████60%]│ │ [██░░░░░░0%] │ │ [██████░40%] │  │
│ │ 12/20        │ │ 0/20         │ │ 12/30        │  │
│ │              │ │              │ │              │  │
│ │ 오늘: [5 ] ✓ │ │ 오늘: [__ ]  │ │ 오늘: [3 ] ✓ │  │
│ │ [완료처리]    │ │              │ │              │  │
│ └──────────────┘ └──────────────┘ └──────────────┘  │
│                                                      │
│ 🟢 시작 가능 (5)                                      │
│ ┌──────────────┐ ┌──────────────┐                   │
│ │ 전면유리 조립  │ │ 암대 용접    │                   │
│ │ ARENA-400    │ │ MTPS-201-5   │                   │
│ │ [시작하기]    │ │ [시작하기]    │                   │
│ └──────────────┘ └──────────────┘                   │
│                                                      │
│ 🔴 대기 — 자재/선행 미충족 (8)                         │
│  (접힌 상태, 클릭 펼침)                                │
│                                                      │
│ ✅ 최근 완료 (20)                                     │
│  (접힌 상태, 클릭 펼침)                                │
└──────────────────────────────────────────────────────┘
```

### 5.2 공정 카드 상세

```
┌──────────────────────────────┐
│ [ON/OFF 토글]  PCB 조립  3/7 │  ← 토글 + 공정명 + step순서
│──────────────────────────────│
│ ARENA-400 × 20ea             │  ← 모델 + 수량
│ 강릉시 종합운동장    D-27     │  ← 현장명 + 납기
│──────────────────────────────│
│ [████████████████████░░] 60% │  ← 프로그레스바
│ 누적 12/20                   │
│──────────────────────────────│
│ 오늘 수량: [    5    ] ✓     │  ← 인라인 입력 + autosave dot
│                    [완료처리] │  ← 공정 완료 버튼
└──────────────────────────────┘
```

**카드 상태별 스타일:**

| 상태 | 배경 | 좌측 border | 비고 |
|------|------|------------|------|
| 진행중 | white | 4px `#f59e0b` (amber) | 수량입력 활성 |
| 시작 가능 (대기+조건충족) | white | 4px `#3b82f6` (blue) | "시작하기" 버튼 |
| 대기 (조건 미충족) | `#f9fafb` | 4px `#d1d5db` (gray) | 비활성, 사유 표시 |
| 완료 | `#f0fdf4` | 4px `#22c55e` (green) | 취소선 스타일 |
| 자재대기 | `#fef2f2` | 4px `#ef4444` (red) | 🔴 자재대기 뱃지 |

### 5.3 뷰 모드

| 뷰 | URL param | 그룹핑 | 정렬 |
|-----|-----------|--------|------|
| **공정별** (기본) | `?view=process` | 상태별 (진행중→시작가능→대기→완료) | 납기 ASC |
| **현장별** | `?view=site` | 현장명별 → 품목별 → 공정순서 | 현장명 ASC |
| **오늘 생산** | `?view=today` | 오늘 로그가 있거나 진행중인 것만 | 최근 입력순 |

### 5.4 필터

| 필터 | 타입 | 동작 |
|------|------|------|
| 상태 | select | 전체/진행중/대기/완료 |
| 카테고리 | select | 전체/투광등기구/가로등기구/... |
| 현장 검색 | text | 현장명·모델명 검색 (JS 클라이언트 필터) |

필터 적용은 **JS 클라이언트 필터** — 전체 데이터를 HTML에 렌더링하고 JS로 show/hide. 공정 수가 수백 개 이내이므로 서버 필터 불필요.

### 5.5 모바일 반응형

```css
/* 카드 그리드 */
.process-grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(3, 1fr);  /* 데스크탑 3열 */
}
@media (max-width: 991.98px) {
    .process-grid { grid-template-columns: repeat(2, 1fr); }  /* 태블릿 2열 */
}
@media (max-width: 575.98px) {
    .process-grid { grid-template-columns: 1fr; }  /* 모바일 1열 */
}
```

### 5.6 인라인 수량입력 동작

1. 카드 하단 `<input type="number">` — 포커스 시 키패드 자동 올라옴 (모바일)
2. **입력 → 엔터 또는 blur** → AJAX POST `/api/production/process/<id>/daily-log`
3. autosave dot: `⚪idle → 🟡saving → 🟢saved (1.5s후 idle)`
4. 에러 시: `🔴error` + 입력값 복원
5. 응답에서 `progress_qty`, `progress_pct` 받아 프로그레스바 업데이트
6. `remain == 0`이면 "완료처리" 버튼 자동 강조

---

## 6. Error Handling

| 상황 | 처리 |
|------|------|
| 선행 공정 미완료 시 시작 시도 | toast "선행 공정 완료 후 시작 가능" + 카드 shake |
| 자재 미입고 시 시작 시도 | 카드 비활성 + "🔴 자재대기" 뱃지 |
| 수량 초과 입력 | clamp 후 toast "N개만 반영 (잔여 M개)" |
| 네트워크 에러 | autosave dot 🔴 + toast "저장 실패, 재시도 해주세요" |
| 동시 편집 | last-write-wins (단일 공장, 동시성 낮음) |

---

## 7. Security

- [x] `login_required` 모든 route
- [x] AJAX API에 CSRF 토큰 (`X-CSRFToken` 헤더)
- [x] process_id로 조회 시 project 소속 검증 (기존 핸들러 유지)
- [x] 수량 입력 서버측 clamp (음수 방지, 계약수량 초과 방지)

---

## 8. Implementation Guide

### 8.1 파일 구조

```
routes/
  production.py              — 대폭 수정
    GET /production          → production_main() [신규]
    POST /api/production/... → AJAX API 3개 [신규]
    GET /production_management → redirect [변경]
    GET /production_management/<id> → redirect [변경]
    (display, weather 유지)

templates/
  production.html            — [신규] 카드형 통합 메인
  production_management.html — 삭제
  production_detail.html     — 삭제
  production_display.html    — 유지

modules/
  production_logic.py        — 유지 (변경 없음)
  services/production_actions.py — 유지 (기존 핸들러 AJAX 래퍼에서 호출)
```

### 8.2 Implementation Order

1. **AJAX API 엔드포인트 3개** (`/api/production/process/<id>/toggle|daily-log|complete`)
   - 기존 `production_actions.py` 핸들러를 JSON 응답으로 래핑
   - CSRF 토큰 검증

2. **데이터 로더** (`production_main()` route)
   - 전체 공정 쿼리 + 상태별 그룹핑 + 오늘 로그 합산
   - filter_options (현장목록, 카테고리) 생성

3. **카드형 템플릿** (`production.html`)
   - 뷰 탭 (공정별/현장별/오늘생산)
   - 필터 바
   - KPI 요약
   - 상태별 섹션 + 카드 그리드
   - 카드 컴포넌트 (토글, 프로그레스, 인라인 입력, 완료 버튼)

4. **카드 JS** (인라인 `<script>`)
   - 토글 클릭 → AJAX → DOM 업데이트
   - 수량 입력 → 엔터/blur → AJAX → 프로그레스 업데이트
   - 완료 → AJAX → 카드 이동 (진행중→완료 섹션)
   - autosave dot 애니메이션
   - 클라이언트 필터 (JS show/hide)
   - 뷰 전환 (탭 클릭 → 그룹핑 변경)

5. **기존 라우트 redirect** + `production_management.html`, `production_detail.html` 삭제

6. **사이드바 메뉴** endpoint 변경 (`production.production_management` → `production.production_main`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft | ENG |
