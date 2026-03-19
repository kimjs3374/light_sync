# Production Display Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 현재 대시보드는 관리자용 종합현황판으로, 생산현장에서 "지금 뭘 만들어야 하는지" 즉시 파악이 불가능. 생산라인 작업자가 자재 입고 상태, 생산 우선순위, 현재 공정을 확인하려면 여러 페이지를 이동해야 함 |
| Solution | 공장 TV/디스플레이 전용 `/production/display` 페이지 신규 개발. 4컬럼 칸반 보드(자재대기→생산대기→생산중→완료) + 자재 입고현황 통합 표시 + 30초 자동갱신 |
| Function UX Effect | 다크 테마 대형 글씨로 3m 거리에서도 가독성 확보. 카드마다 자재 준비율/미입고 품목/현재 공정/D-Day 즉시 확인. 하단 티커로 입고 예정 자재 자동 롤링 |
| Core Value | 생산 현장에서 PC 조작 없이 "다음에 뭐 만들지" 즉시 판단 가능. 자재 병목 사전 인지로 공정 지연 최소화 |

## 1. Background

### 현재 상황
- `/dashboard`는 관리자용 전사 현황판 (영업/자재/생산/납품 종합)
- `/production/management`는 PC에서 개별 조작하는 생산관리 페이지
- 생산현장에 TV를 걸어두고 실시간 확인할 수 있는 전용 화면이 없음

### 핵심 Pain Point
- 생산라인 작업자/관리자가 "자재가 다 들어왔는지" 확인하려면 자재관리 페이지로 이동해야 함
- 어떤 현장을 먼저 생산해야 하는지 우선순위를 매번 확인해야 함
- 현재 공정 진행 상태를 한눈에 볼 수 없음

## 2. Goal
- 공장 TV 디스플레이 전용 페이지 제공 (`/production/display`)
- 자재 준비 상태 → 생산 가능 여부를 카드 내에 즉시 표시
- 납기일 기반 우선순위로 "다음에 뭘 생산할지" 자동 정렬
- 터치/키보드 조작 없이 자동 갱신되는 Read-Only 화면

## 3. Scope

### In Scope
- **신규 라우트**: `GET /production/display` (login_required)
- **4컬럼 칸반 보드**:
  - 자재대기 (`status_prod == '자재대기중'`)
  - 생산대기 (`status_prod == '생산대기중'`)
  - 생산중 (`status_prod == '생산중'`)
  - 금일/최근 완료 (`status_prod == '생산완료'`, 최근 7일)
- **카드 내 자재 정보 표시**:
  - 자재대기 컬럼: `입고 N/M개` 프로그레스바 + 미입고 품목 리스트 + 예정입고일 또는 미발주 경고
  - 생산대기 컬럼: `자재 완료 ✅` + 투입 우선순위 번호 + 주요 거래처명
  - 생산중 컬럼: 현재 공정명 + 진행률 프로그레스바 + 다음 공정
  - 완료 컬럼: 완료일만 간략 표시
- **카드 공통 정보**: 현장명(short_name), 품목 카테고리+모델명, 수량, D-Day 뱃지, 긴급(★) 마크
- **하단 자재 입고 예정 티커**: `expected_in_date` 기준 7일 내 입고 예정 자재 롤링 표시 (품목명, 수량, 거래처→현장)
- **외주 자재 구분**: `is_outsourcing` 품목은 별도 색상 뱃지 (`외주가공중`, `본사입고완료` 등)
- **다크 테마**: 공장 조명 환경 + TV 디스플레이 최적화
- **자동 갱신**: 30초 주기 페이지 새로고침 (meta refresh 또는 JS fetch)
- **반응형**: 1920px(TV) 기준 최적화, 1366px(노트북)까지 대응

### Out of Scope
- 생산 데이터 수정/입력 기능 (Read-Only 전용)
- 생산라인/워크스테이션 개념 추가 (현재 모델에 없음)
- 사용자별 커스텀 뷰 / 필터
- 기존 `/dashboard` 수정

## 4. Success Criteria
- TV에서 3m 거리 가독성 (최소 폰트 16px, 현장명 24px 이상)
- 카드 내 자재 입고율 프로그레스바 정확도 100% (MaterialOrder 기반)
- 페이지 로딩 < 2초 (contracted_projects + material_orders 조인)
- 30초 자동갱신 시 깜빡임 없음 (가능하면 AJAX partial update)
- 칸반 컬럼 내 정렬: D-Day 임박순 → 긴급 플래그 → 수동 최우선 순

## 5. Technical Approach

### 5.1 Route 추가
- `routes/production.py`에 `production_display()` 뷰 함수 추가
- 기존 `contracted_projects` + `material_orders` + `production_processes` 조인 쿼리 활용
- `templates/production_display.html` 신규 생성 (base.html extends 하되, 사이드바 숨김 옵션)

### 5.2 데이터 구조
```python
# 카드 1장에 필요한 데이터
card = {
    'project_name': str,        # short_name or temp_name
    'project_no': str,
    'category': str,            # 품목 카테고리
    'model_name': str,          # 모델명
    'quantity': int,            # 계약 수량
    'status_prod': str,         # 자재대기중/생산대기중/생산중/생산완료
    'dday': int | None,         # 납기까지 남은 일수
    'is_urgent': bool,          # 긴급 플래그
    'is_priority': bool,        # 수동 최우선
    # 자재 정보
    'material_total': int,      # 전체 자재 품목 수
    'material_ready': int,      # 입고완료 품목 수
    'material_percent': int,    # 입고율 %
    'missing_materials': [      # 미입고 품목 리스트 (자재대기 컬럼용)
        {'name': str, 'status': str, 'expected_date': date, 'is_outsourcing': bool}
    ],
    # 공정 정보 (생산중 컬럼용)
    'current_process': str,     # 현재 진행중 공정명
    'process_percent': int,     # 전체 공정 진행률
    'next_process': str,        # 다음 공정명
    'completed_at': date,       # 완료일 (완료 컬럼용)
}
```

### 5.3 자재 입고 예정 티커
```python
# 하단 티커 데이터
upcoming_materials = [
    {
        'expected_date': date,
        'material_name': str,
        'quantity': int,
        'vendor_name': str,       # 거래처명
        'project_name': str,      # 투입 현장명
        'is_outsourcing': bool,
    }
]
# expected_in_date 기준 오늘~7일 후, 날짜순 정렬
```

### 5.4 UI 구조
```
┌─────────────────────────────────────────────────────────────┐
│  헤더: 🏭 Light-Sync 생산현황판  |  날짜시간  |  자동갱신 표시  │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ 📦 자재대기   │ ⏳ 생산대기   │ 🔧 생산중    │ ✅ 완료         │
│   (N건)      │   (N건)      │   (N건)      │   (N건)        │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ [카드]       │ [카드]        │ [카드]        │ [카드]         │
│ [카드]       │ [카드]        │ [카드]        │ [카드]         │
│ ...          │ ...          │ ...          │ ...            │
├──────────────┴──────────────┴──────────────┴────────────────┤
│  📦 자재 입고 예정 ◀ 3/20 LED모듈 120EA (삼성LED→세종시청) ▶   │
└─────────────────────────────────────────────────────────────┘
```

### 5.5 다크 테마 색상 체계
| 요소 | 색상 |
|------|------|
| 배경 | `#0f172a` (slate-900) |
| 카드 배경 | `#1e293b` (slate-800) |
| 텍스트 | `#f1f5f9` (slate-100) |
| 자재대기 | `#f59e0b` (amber) |
| 생산대기 | `#3b82f6` (blue) |
| 생산중 | `#22c55e` (green) |
| 완료 | `#64748b` (slate-500) |
| 긴급/D-3이하 | `#ef4444` (red) |
| 외주 뱃지 | `#8b5cf6` (violet) |

## 6. Implementation Order
1. Route 함수 + 데이터 쿼리 로직 (`routes/production.py`)
2. 카드 데이터 빌더 유틸리티 (`modules/dashboard_utils.py` 또는 별도)
3. 템플릿 HTML/CSS (`templates/production_display.html`)
4. 자재 입고 예정 티커 로직 + UI
5. 자동 갱신 JS (30초 주기)
6. 반응형 + 다크 테마 마무리

## 7. Risk & Mitigation
| Risk | Impact | Mitigation |
|------|--------|------------|
| 대량 프로젝트 시 카드 overflow | 화면에 안 들어감 | 컬럼별 max 표시 수 제한 + 스크롤 또는 페이지네이션 |
| 조인 쿼리 성능 | 로딩 지연 | eager loading + 캐시 (30초 갱신이니 캐시 유효) |
| TV 브라우저 호환성 | CSS 깨짐 | 기본 CSS만 사용, flexbox/grid (모던 브라우저 기준) |
| 자재 데이터 불일치 | 잘못된 표시 | 기존 `are_materials_ready()` 로직 재활용 |
