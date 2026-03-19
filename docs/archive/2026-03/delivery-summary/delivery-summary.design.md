# Delivery Summary Design Document

> **Summary**: G2B 조달내역 기반 년도/모델별/월별 납품집계 피벗 + Chart.js + 엑셀 다운로드
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-19
> **Status**: Draft
> **Planning Doc**: [delivery-summary.plan.md](../01-plan/features/delivery-summary.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- `g2b_procurements` 테이블에서 년도/모델(품명)별 월별 수량·금액 피벗 집계
- 피벗 테이블 + Chart.js 이중축 차트 (수량 막대 + 금액 라인) 동시 제공
- openpyxl 기반 엑셀 다운로드 (피벗 그대로 + 합계행/열)
- 인쇄 최적화 CSS (@media print)
- 기존 `procurement_bp` 라우트에 자연스럽게 통합

### 1.2 Design Principles

- 기존 패턴 준수: Flask Blueprint + SQLAlchemy + Jinja2 + get_db() context manager
- 쿼리 1회로 전체 집계 데이터 로드 → Python에서 피벗 변환 (SQLite 호환)
- Chart.js CDN (이미 프로젝트에서 사용 중) 재활용

---

## 2. Architecture

### 2.1 Component Diagram

```
┌──────────────┐     ┌───────────────────┐     ┌─────────────────┐
│   Browser    │────▶│  Flask Route      │────▶│  SQLite DB      │
│  (HTML/JS)   │     │  /procurement/    │     │  g2b_procurements│
│  Chart.js    │     │  summary          │     │                 │
│  피벗 테이블   │     │  summary/excel    │     │                 │
└──────────────┘     └───────────────────┘     └─────────────────┘
```

### 2.2 Data Flow

```
1. 사용자가 년도/모델 필터 선택 → GET /procurement/summary?years=2025,2026&model=STA-200
2. Route에서 SQLAlchemy 집계 쿼리 실행
3. Python에서 쿼리 결과를 피벗 dict로 변환 (행=모델, 열=1~12월)
4. Jinja2 템플릿에서 피벗 테이블 렌더링 + Chart.js 데이터 주입
5. 엑셀: GET /procurement/summary/excel → openpyxl Workbook → Response (attachment)
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| summary route | G2bProcurement 모델 | 집계 쿼리 대상 |
| 엑셀 다운로드 | openpyxl | .xlsx 생성 |
| 차트 | Chart.js (CDN) | 월별 막대/라인 차트 |
| 필터 UI | Bootstrap 5 (기존) | select, button 컴포넌트 |

---

## 3. Data Model

### 3.1 사용 엔티티 (기존, 변경 없음)

```python
class G2bProcurement(Base):
    __tablename__ = 'g2b_procurements'
    # 집계에 사용되는 필드:
    cntrct_dlvr_req_date  # Date — 년도/월 추출
    prdct_clsfc_no_nm     # String(200) — 품명 (모델 그룹핑 기준)
    dtil_prdct_clsfc_no_nm # String(200) — 세부품명 (보조 표시)
    prdct_qty             # Integer — 수량
    prdct_amt             # Integer — 금액
    prdct_amt > 0         # 취소 건 제외 조건
```

### 3.2 피벗 데이터 구조 (Python dict, DB 변경 없음)

```python
# Route에서 생성하는 피벗 구조
pivot = {
    'models': [
        {
            'name': 'LED 스포츠조명 STA-200',
            'months': {1: {'qty': 10, 'amt': 5000000}, 2: {...}, ...12: {...}},
            'total_qty': 120,
            'total_amt': 60000000,
        },
        ...
    ],
    'grand_total': {
        'months': {1: {'qty': 25, 'amt': 12000000}, ...},
        'total_qty': 300,
        'total_amt': 150000000,
    },
    'years': [2024, 2025, 2026],       # 필터 옵션
    'model_names': ['STA-200', ...],    # 필터 옵션
}
```

---

## 4. API Specification

### 4.1 Endpoint List

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/procurement/summary` | 납품집계 페이지 (HTML) | login_required |
| GET | `/procurement/summary/excel` | 엑셀 다운로드 (.xlsx) | login_required |

### 4.2 GET /procurement/summary

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `years` | string (comma-sep) | 현재년도 | 년도 필터 (예: `2025,2026`) |
| `model` | string | 전체 | 품명(prdct_clsfc_no_nm) 필터 |

**Response**: HTML 페이지 (피벗 테이블 + 차트)

**Template Context:**

```python
{
    'pivot': pivot,           # 피벗 데이터 (위 구조)
    'chart_data': {           # Chart.js용 JSON-safe 데이터
        'labels': ['1월', '2월', ..., '12월'],
        'datasets': [
            {'label': 'STA-200 수량', 'data': [10, 15, ...], 'type': 'bar'},
            {'label': 'STA-200 금액', 'data': [5000000, ...], 'type': 'line', 'yAxisID': 'y1'},
        ]
    },
    'filters': {'years': '2025,2026', 'model': ''},
    'filter_options': {'years': [2024, 2025, 2026], 'models': [...]},
}
```

### 4.3 GET /procurement/summary/excel

**Query Parameters**: `years`, `model` (동일)

**Response**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Content-Disposition: `attachment; filename="납품집계_2026.xlsx"`
- 한글 파일명 URL 인코딩 (RFC 5987)

**엑셀 구조:**
```
| 모델명      | 1월(수량) | 1월(금액) | ... | 12월(수량) | 12월(금액) | 합계(수량) | 합계(금액) |
|------------|----------|----------|-----|-----------|-----------|-----------|-----------|
| STA-200    | 10       | 5,000,000| ... | 8         | 4,000,000 | 120       | 60,000,000|
| ARENA-200  | 5        | 2,500,000| ... | 12        | 6,000,000 | 85        | 42,500,000|
| 합계       | 15       | 7,500,000| ... | 20        |10,000,000 | 205       |102,500,000|
```

---

## 5. UI/UX Design

### 5.1 Screen Layout

```
┌──────────────────────────────────────────────────────────────┐
│ 📋 납품집계                                                    │
│                                                              │
│ [년도: 2026 ▼] [모델명: 전체 ▼]  [검색]  [📥 엑셀]  [🖨 인쇄] │
├──────────────────────────────────────────────────────────────┤
│ 📊 Chart.js 영역 (canvas, height: 300px)                     │
│  - 좌축: 수량 (막대)                                           │
│  - 우축: 금액 (라인)                                           │
│  - 모델별 색상 구분 (최대 10색 팔레트)                            │
│  - 범례: 상단 가로 배치                                         │
├──────────────────────────────────────────────────────────────┤
│ 📋 피벗 테이블                                                 │
│ ┌──────────┬──────┬──────┬─────┬──────┬──────┐              │
│ │ 모델명    │ 1월  │ 2월  │ ... │ 12월 │ 합계 │              │
│ ├──────────┼──────┼──────┼─────┼──────┼──────┤              │
│ │ STA-200  │10/5M │15/7M │ ... │ 8/4M │120/60│              │
│ │ ARENA    │ 5/2M │ 0/0  │ ... │12/6M │ 85/42│              │
│ ├──────────┼──────┼──────┼─────┼──────┼──────┤              │
│ │ 합계     │15/7M │15/7M │ ... │20/10M│205/102│             │
│ └──────────┴──────┴──────┴─────┴──────┴──────┘              │
│                                                              │
│ * 셀 표시: 수량 / 금액(만원) — 금액은 만원 단위 축약             │
│ * 수량 0인 셀은 회색 처리                                       │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 테이블 셀 표시 규칙

| 조건 | 수량 표시 | 금액 표시 | 셀 스타일 |
|------|----------|----------|----------|
| qty > 0, amt > 0 | 숫자 | 만원 단위 (소수점 없음) | 기본 |
| qty = 0, amt = 0 | `-` | `-` | `text-muted` |
| 합계 행/열 | **bold** | **bold** | `table-light fw-bold` |

### 5.3 차트 상세

| 항목 | 설정 |
|------|------|
| 차트 타입 | mixed (bar + line) |
| X축 | 1월 ~ 12월 |
| Y축 좌 | 수량 (건) |
| Y축 우 | 금액 (원) — 천만원 단위 tick |
| 막대 | 모델별 수량 (stacked: false) |
| 라인 | 모델별 금액 (tension: 0.3) |
| 색상 | 10색 팔레트 순환 |
| 범례 | top, horizontal |
| 반응형 | responsive: true, maintainAspectRatio: false |

### 5.4 필터 동작

1. **년도 select**: `<select multiple>` — 여러 년도 동시 선택 가능. 기본값: 현재 년도
2. **모델 select**: `<select>` — 단일 선택. "전체" 옵션 포함. 기본값: 전체
3. **검색 버튼**: form submit → GET with query params → 전체 페이지 리로드
4. **엑셀 버튼**: 현재 필터 params 그대로 `/procurement/summary/excel`로 이동
5. **인쇄 버튼**: `window.print()` — @media print CSS 적용

### 5.5 인쇄 CSS

```
@media print:
  - 차트 영역 숨김 (차트는 인쇄 불필요)
  - 필터/버튼 영역 숨김
  - 테이블 100% 너비, font-size: 10px
  - 사이드바/네비 숨김
  - 페이지 여백 최소화
```

---

## 6. Error Handling

| 상황 | 처리 |
|------|------|
| years 파라미터 비정상 | 무시하고 현재 년도 기본값 |
| 집계 결과 0건 | 빈 테이블 + "조회 결과가 없습니다" 메시지 |
| openpyxl 미설치 | import error → flash 메시지 + 엑셀 버튼 비활성화 |
| 대량 데이터 (모델 50개+) | 상위 20개만 차트에 표시, 테이블은 전체 |

---

## 7. Security Considerations

- [x] `login_required` 데코레이터 적용
- [x] SQL Injection 방지: SQLAlchemy ORM 사용 (raw query 없음)
- [x] 파라미터 검증: years는 int 변환, model은 ORM filter
- [x] 엑셀 파일명 인코딩: URL 인코딩으로 경로 조작 방지

---

## 8. Test Plan

### 8.1 수동 검증 항목

- [ ] 년도 단일 선택 → 해당 년도 데이터만 집계
- [ ] 년도 복수 선택 (2025,2026) → 합산 집계
- [ ] 모델 필터 → 해당 모델만 표시
- [ ] 집계 합계 = 개별 셀 합 (데이터 정합성)
- [ ] 차트 렌더링 정상 (막대 + 라인)
- [ ] 엑셀 다운로드 → 한글 파일명 정상
- [ ] 엑셀 내용 = 화면 테이블과 일치
- [ ] 인쇄 미리보기 → 테이블만 깔끔하게 출력
- [ ] 데이터 0건 → "조회 결과가 없습니다" 표시
- [ ] 취소 건(amt=0, qty=0) 제외 확인

---

## 9. Implementation Guide

### 9.1 File Structure

```
routes/
  procurement.py          # 기존 파일에 2개 route 추가
modules/
  services/
    procurement_summary.py  # [신규] 집계 로직 분리
templates/
  procurement_summary.html  # [신규] 집계 페이지 템플릿
```

### 9.2 Implementation Order

1. **`modules/services/procurement_summary.py`** — 집계 함수
   - `get_summary_pivot(db, years, model)` → 피벗 dict 반환
   - `get_filter_options(db)` → 년도/모델 목록
   - `build_chart_data(pivot)` → Chart.js용 데이터 변환
   - `generate_excel(pivot, years)` → BytesIO (xlsx)

2. **`routes/procurement.py`** — 라우트 추가
   - `GET /procurement/summary` → `procurement_summary()`
   - `GET /procurement/summary/excel` → `procurement_summary_excel()`

3. **`templates/procurement_summary.html`** — UI
   - 필터 바 (년도 multi-select + 모델 select + 버튼)
   - Chart.js canvas + 스크립트
   - 피벗 테이블 (동적 열)
   - @media print CSS

4. **사이드바 메뉴** — `templates/base.html`에 메뉴 항목 추가
   - 조달내역 하위: "납품집계" 링크

### 9.3 집계 함수 핵심 로직

```python
def get_summary_pivot(db, years=None, model=None):
    """G2B 조달내역 월별 피벗 집계"""
    filters = [G2bProcurement.prdct_amt > 0]  # 취소 건 제외

    if years:
        filters.append(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).in_(years)
        )
    if model:
        filters.append(G2bProcurement.prdct_clsfc_no_nm == model)

    rows = db.query(
        G2bProcurement.prdct_clsfc_no_nm,
        extract('month', G2bProcurement.cntrct_dlvr_req_date).label('month'),
        func.sum(G2bProcurement.prdct_qty).label('total_qty'),
        func.sum(G2bProcurement.prdct_amt).label('total_amt'),
    ).filter(*filters).group_by(
        G2bProcurement.prdct_clsfc_no_nm,
        extract('month', G2bProcurement.cntrct_dlvr_req_date),
    ).all()

    # Python에서 피벗 변환
    # ... (행=모델, 열=1~12월, 합계행/열 계산)
```

### 9.4 엑셀 생성 핵심

```python
def generate_excel(pivot, years):
    """피벗 데이터를 xlsx로 변환"""
    wb = Workbook()
    ws = wb.active
    ws.title = '납품집계'

    # 헤더: 모델명 | 1월(수량) | 1월(금액) | ... | 합계
    # 데이터 행
    # 합계 행
    # 스타일: 숫자 포맷, 헤더 색상, 테두리

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
```

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft | ENG |
