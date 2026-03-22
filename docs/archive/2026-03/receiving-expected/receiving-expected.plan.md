# 입고예정 관리 — Plan (v2)

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 발주 후 입고예정일을 설정할 곳이 자재관리 상세뿐이라 접근성이 나쁘고, 발주건 전체를 한눈에 보면서 예정일을 관리할 수 없음 |
| Solution | 입고관리 "입고예정" 탭에서 발주완료 건 전체를 보여주고, 입고예정일을 인라인으로 입력/수정 + D-Day/지연 표시 + 입고확인 처리 |
| Function UX Effect | 입고관리 한 화면에서 모든 발주건의 예정일 설정·조회·지연파악·입고확인까지 원스톱 처리 |
| Core Value | 입고예정일 관리 허들 제거 → 실제 데이터 축적 → 지연 조기 감지 → 납기 차질 방지 |

---

## 1. Background

### 현재 데이터 소스

| 모델 | 필드 | 설명 |
|------|------|------|
| `MaterialOrder` | `expected_in_date` | 자재별 입고예정일 (Date, nullable) |
| `MaterialOrder` | `order_status` | 발주대기/발주완료/입고완료 |
| `MaterialOrder` | `in_confirmed` | 입고확인 여부 |
| `MaterialOrder` | `po_id` → `PurchaseOrder` | 발주서 연결 |
| `PurchaseOrder` | `vendor`, `po_no`, `po_date` | 거래처, 발주번호, 발주일 |
| `Contract` | `desired_delivery_date` | 계약 납품기일 |

### 현재 문제

1. **입고예정일 입력 경로가 묻혀있음** — 자재관리 → 현장 상세 → 개별 자재 편집에서만 설정 가능
2. **발주건 전체 목록을 한 화면에서 볼 수 없음** — 현장별로 흩어져 있어 전체 파악 불가
3. **입고예정일이 비어있는 발주건이 대부분** — 입력이 불편하니 아무도 안 채움
4. 기존 구현은 `expected_in_date IS NOT NULL` 필터로 조회만 하는 구조 → 예정일 없는 건은 아예 안 보임

---

## 2. Requirements

### 2.1 입고예정 탭 (핵심)

| # | 요구사항 |
|---|----------|
| R1 | 입고관리 페이지 "입고예정" 탭에서 **발주완료 + 미입고** 전체 건 표시 (예정일 유무 관계없이) |
| R2 | **입고예정일 인라인 편집**: 날짜 셀 클릭 → date input → 변경 시 AJAX 즉시 저장 |
| R3 | 테이블 컬럼: 현장 \| 거래처 \| 자재명 \| 수량 \| 발주일 \| 입고예정일(편집) \| D-Day \| 납품기일 \| 납기위험 \| 액션 |
| R4 | D-Day: 예정일 없으면 "미정" 표시, 지연 빨강, 오늘 주황, 임박 노랑, 여유 초록 |
| R5 | 납기위험도: 납품기일 - 입고예정일 - 생산소요일 기준 (🔴못맞춤/🟡빠듯/🟢여유/⚪미정) |
| R6 | 필터: 상태(전체/지연/오늘/이번주/미정), 현장별, 거래처별 |
| R7 | 정렬: 입고예정일 ASC (미정은 맨 위에 → 예정일 입력 유도) |
| R8 | 입고확인 버튼: AJAX 처리 (in_confirmed=True, order_status='입고완료') |

### 2.2 대시보드 입고예정 카드

| # | 요구사항 |
|---|----------|
| D1 | 대시보드에 입고예정 요약 카드 (지연 N건, 오늘 N건, 이번주 N건, **미정 N건**) |
| D2 | 클릭 시 입고관리 입고예정 탭으로 이동 |

### 2.3 알림 연동

| # | 요구사항 |
|---|----------|
| N1 | 대시보드 로드 시 지연 건 알림 자동 생성 (관리부, 1일 1회 중복 방지) |

---

## 3. Scope

### In Scope
- `routes/receiving.py` — 입고예정 쿼리 수정 (전체 발주건 조회 + 예정일 인라인 저장 API)
- `templates/receiving_list.html` — 입고예정 탭 테이블 수정 (인라인 date input + 미정 건 포함)
- `routes/dashboard.py` — dash_expected 통계에 미정 건수 추가
- `templates/dashboard.html` — 입고예정 카드 미정 칩 추가

### Out of Scope
- 모델 변경 없음 (MaterialOrder.expected_in_date 필드 이미 존재)
- 발주서 상세 페이지 변경 없음
- 외부 알림 (이메일/카톡) — ERP 내 알림센터만

---

## 4. Technical Approach

### 4.1 핵심 변경: 쿼리 필터 수정

**기존 (잘못됨)**:
```python
# expected_in_date가 있는 건만 → 대부분 안 보임
MaterialOrder.order_status == '발주완료',
MaterialOrder.in_confirmed == False,
MaterialOrder.expected_in_date.isnot(None),  # ← 이게 문제
```

**변경**:
```python
# 발주완료 + 미입고 전체
MaterialOrder.order_status == '발주완료',
MaterialOrder.in_confirmed == False,
# expected_in_date 필터 제거 → 전부 표시
```

### 4.2 입고예정일 인라인 편집 API

```
POST /api/receiving/update-expected-date/<int:mo_id>
Body: { "expected_in_date": "2026-04-01" }  (빈 문자열이면 null)
Response: { "ok": true }
```

### 4.3 정렬 전략

```
ORDER BY:
  CASE WHEN expected_in_date IS NULL THEN 0 ELSE 1 END ASC,  -- 미정 먼저
  expected_in_date ASC                                         -- 그다음 날짜순
```

### 4.4 대시보드 통계

```python
dash_expected = {
    'overdue': expected_in_date < today,
    'today': expected_in_date == today,
    'this_week': today <= expected_in_date <= today+7,
    'unknown': expected_in_date IS NULL,  # ← 신규
}
```

---

## 5. Implementation Order

| # | 작업 | 파일 |
|---|------|------|
| 1 | receiving.py — 쿼리 수정 (전체 발주건 + 미정 먼저 정렬) | routes/receiving.py |
| 2 | receiving.py — 입고예정일 인라인 저장 API 추가 | routes/receiving.py |
| 3 | receiving_list.html — 테이블 수정 (인라인 date input + 미정 표시) | templates/receiving_list.html |
| 4 | dashboard.py — dash_expected에 unknown 추가 | routes/dashboard.py |
| 5 | dashboard.html — 미정 칩 추가 | templates/dashboard.html |

---

## 6. Risks

| 리스크 | 대응 |
|--------|------|
| 발주완료 건이 많으면 목록이 길어짐 | 현장/거래처 필터 + 페이지네이션 고려 |
| 인라인 편집 시 실수로 잘못된 날짜 입력 | date input 자체 제약 + 확인 없이 즉시 저장 (UX 단순화 우선) |
| expected_in_date가 null인 건이 대부분 | 미정을 맨 위에 놓아 입력 유도 |
