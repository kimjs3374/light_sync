# procurement-view Design Document

> **Summary**: 나라장터 조달내역 조회 UI + 계약 연동 상세 설계
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: Claude (PDCA)
> **Date**: 2026-03-17
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/procurement-view.plan.md`

---

## 1. Implementation Files

| # | 파일 | 작업 | Phase |
|---|------|------|-------|
| 1 | `routes/procurement.py` | **신규** | P0 |
| 2 | `templates/procurement_list.html` | **신규** | P0 |
| 3 | `app.py` | 수정 (Blueprint 등록) | P0 |
| 4 | `templates/base.html` | 수정 (사이드바 메뉴) | P0 |
| 5 | `modules/models/entities.py` | 수정 (Contract.g2b_req_no) | P1 |
| 6 | `modules/models/__init__.py` | 수정 (export 추가) | P0 |

---

## 2. Route Design (`routes/procurement.py`)

### 2.1 Blueprint 구조

```python
procurement_bp = Blueprint('procurement', __name__)
```

### 2.2 엔드포인트

| Method | URL | 함수 | 설명 |
|--------|-----|------|------|
| GET | `/procurement` | `procurement_list()` | 목록 조회 (검색/필터/페이지네이션) |
| POST | `/procurement` | `procurement_action()` | 동기화 액션 (admin) |

### 2.3 GET `/procurement` 상세

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `q` | string | '' | 검색어 (계약명, 수요기관, 규격명) |
| `year` | string | '' | 연도 필터 (2015~2026) |
| `product` | string | '' | 세부품목명 필터 |
| `org` | string | '' | 수요기관명 필터 |
| `method` | string | '' | 계약방법 필터 (수의계약/제한경쟁/일반경쟁) |
| `page` | int | 1 | 페이지 번호 |
| `per_page` | int | 30 | 페이지당 건수 |

**응답 데이터 (template context):**

```python
{
    'items': [...],           # G2bProcurement 목록 (페이지네이션 적용)
    'pagination': {...},      # make_pagination 결과
    'stats': {
        'total_count': 1545,       # 전체 건수
        'total_amt': 54700000000,  # 전체 금액
        'year_count': 33,          # 올해 건수
        'year_amt': 519268000,     # 올해 금액
        'top_product': 'LED투광등기구',  # 최다 품목
        'top_product_pct': 27,     # 최다 품목 비율(%)
    },
    'filters': {...},         # 현재 필터값 (폼 유지용)
    'filter_options': {
        'years': [2026, 2025, ...],       # 연도 목록
        'products': ['LED투광등기구', ...], # 세부품목 목록
        'methods': ['수의계약', ...],       # 계약방법 목록
    },
    'is_admin': bool,
}
```

**쿼리 로직:**

```python
query = db.query(G2bProcurement)

# 검색어 (LIKE)
if q:
    query = query.filter(
        or_(
            G2bProcurement.cntrct_dlvr_req_nm.ilike(f'%{q}%'),
            G2bProcurement.dminstt_nm.ilike(f'%{q}%'),
            G2bProcurement.prdct_idnt_no_nm.ilike(f'%{q}%'),
        )
    )

# 연도 필터
if year:
    query = query.filter(
        extract('year', G2bProcurement.cntrct_dlvr_req_date) == int(year)
    )

# 세부품목 필터
if product:
    query = query.filter(G2bProcurement.dtil_prdct_clsfc_no_nm == product)

# 수요기관 필터 (LIKE - 부분일치)
if org:
    query = query.filter(G2bProcurement.dminstt_nm.ilike(f'%{org}%'))

# 계약방법 필터
if method:
    query = query.filter(G2bProcurement.cntrct_mthd_nm == method)

# 정렬: 최신순
query = query.order_by(G2bProcurement.cntrct_dlvr_req_date.desc())
```

### 2.4 POST `/procurement` - 동기화 액션

```python
ACTION_HANDLERS = {
    'sync_daily': handle_sync_daily,      # 일일 동기화
    'sync_bulk': handle_sync_bulk,        # 벌크 동기화 (admin)
}
```

### 2.5 통계 쿼리

```python
# 전체 통계 (필터 무관)
total_count = db.query(G2bProcurement).count()
total_amt = db.query(func.sum(G2bProcurement.prdct_amt)).scalar() or 0

# 올해 통계
current_year = datetime.date.today().year
year_stats = db.query(
    func.count(),
    func.sum(G2bProcurement.prdct_amt)
).filter(
    extract('year', G2bProcurement.cntrct_dlvr_req_date) == current_year
).first()

# 최다 품목
top_product = db.query(
    G2bProcurement.dtil_prdct_clsfc_no_nm,
    func.count().label('cnt')
).group_by(G2bProcurement.dtil_prdct_clsfc_no_nm
).order_by(func.count().desc()).first()
```

---

## 3. Template Design (`templates/procurement_list.html`)

### 3.1 레이아웃 구조

```
{% extends 'base.html' %}
{% block content %}

1. 페이지 헤더 (제목 + 동기화 버튼)
2. 통계 카드 4개 (row > col-md-3)
3. 검색/필터 폼 (card > row)
4. 테이블 (table-responsive > table)
5. 페이지네이션

{% endblock %}
```

### 3.2 통계 카드 (4개)

| # | 라벨 | 값 | 스타일 |
|---|------|----|--------|
| 1 | 전체 건수 | `{{ stats.total_count }}건` | 기본 |
| 2 | 전체 금액 | `{{ (stats.total_amt / 100000000) \| round(1) }}억원` | border-primary |
| 3 | {{ 올해 }}년 실적 | `{{ stats.year_count }}건 / {{ 금액 }}억원` | border-success |
| 4 | 최다 품목 | `{{ stats.top_product }} ({{ stats.top_product_pct }}%)` | border-info |

### 3.3 필터 영역

```html
<form class="card border-0 shadow-sm mb-4" method="GET">
  <div class="card-body row g-2 align-items-end">
    <!-- 검색 (col-md-3) -->
    <input name="q" placeholder="계약명 / 수요기관 / 규격명">

    <!-- 연도 (col-md-2) -->
    <select name="year">
      <option value="">전체</option>
      {% for y in filter_options.years %}
      <option>{{ y }}</option>
      {% endfor %}
    </select>

    <!-- 세부품목 (col-md-2) -->
    <select name="product">...</select>

    <!-- 계약방법 (col-md-2) -->
    <select name="method">...</select>

    <!-- 버튼 (col-md-3) -->
    <a href="..." class="btn btn-outline-secondary btn-sm">초기화</a>
    <button type="submit" class="btn btn-primary btn-sm">검색</button>
  </div>
</form>
```

### 3.4 테이블 컬럼

| # | 헤더 | 필드 | 너비 | 포맷 |
|---|------|------|------|------|
| 1 | 일자 | `cntrct_dlvr_req_date` | 90px | `YYYY-MM-DD` |
| 2 | 세부품목 | `dtil_prdct_clsfc_no_nm` | 120px | - |
| 3 | 규격명 | `prdct_idnt_no_nm` | auto | 말줄임 (max 40자) |
| 4 | 수요기관 | `dminstt_nm` | 150px | - |
| 5 | 수량 | `prdct_qty` | 60px | 우정렬 |
| 6 | 금액 | `prdct_amt` | 100px | `{:,}원` 우정렬 |
| 7 | 계약방법 | `cntrct_mthd_nm` | 90px | 뱃지 |
| 8 | 납품기한 | `dlvr_tmlmt_date` | 90px | `YYYY-MM-DD` |

**계약방법 뱃지 색상:**

| 값 | 색상 |
|----|------|
| 수의계약 | `bg-secondary` |
| 제한경쟁 | `bg-primary` |
| 일반경쟁 | `bg-info` |

**행 클릭 시:** 상세 정보 collapse/accordion (공사명, 납품장소, 단가계약번호 등)

### 3.5 금액 포맷 헬퍼 (Jinja2)

```python
# 템플릿에서 사용
def format_amt(amt):
    if not amt: return '-'
    if amt >= 100_000_000:
        return f'{amt / 100_000_000:.1f}억'
    if amt >= 10_000:
        return f'{amt / 10_000:.0f}만'
    return f'{amt:,}'
```

---

## 4. Model Changes

### 4.1 Contract 모델 확장 (Phase 2 - P1)

```python
# entities.py - Contract 클래스에 추가
g2b_req_no = Column(String(30), nullable=True)  # G2bProcurement.cntrct_dlvr_req_no 연결
```

### 4.2 DB 마이그레이션

```sql
ALTER TABLE contracts ADD COLUMN g2b_req_no VARCHAR(30);
```

---

## 5. app.py 변경

```python
# import 추가
from routes.procurement import procurement_bp

# Blueprint 등록 (catalog_bp 뒤에)
app.register_blueprint(procurement_bp)
```

---

## 6. base.html 사이드바 변경

```html
<!-- 하자관리 아래, 일일업무보고 위에 추가 -->
<a href="{{ url_for('warranty.warranty_list') }}">하자관리</a>
<a href="{{ url_for('procurement.procurement_list') }}">조달내역</a>
<a href="{{ url_for('daily_report.daily_report_view') }}">일일업무보고</a>
```

**접근 권한:** 전체 사용자 (읽기 전용이므로 권한 제한 불필요)

---

## 7. Implementation Order

```
Step 1: routes/procurement.py (Route + 핸들러)
  - Blueprint 생성
  - GET 목록 조회 (검색/필터/통계/페이지네이션)
  - POST 동기화 액션 (admin only)

Step 2: templates/procurement_list.html (UI)
  - base.html 확장
  - 통계 카드 4개
  - 검색/필터 폼
  - 테이블 + 행 클릭 상세
  - 페이지네이션 (기존 make_pagination 재사용)

Step 3: app.py + base.html (연결)
  - Blueprint 등록
  - 사이드바 메뉴 추가

Step 4: Contract.g2b_req_no (P1 - 계약 연동)
  - 모델 컬럼 추가
  - DB 마이그레이션
```

---

## 8. Validation Checklist

- [ ] `/procurement` 접근 시 전체 목록 + 통계 카드 표시
- [ ] 검색어 입력 시 계약명/수요기관/규격명 LIKE 검색
- [ ] 연도 필터 선택 시 해당 연도만 표시
- [ ] 세부품목 필터 선택 시 해당 품목만 표시
- [ ] 계약방법 필터 선택 시 해당 방법만 표시
- [ ] 페이지네이션 30건 단위 정상 동작
- [ ] 통계 카드: 전체 건수/금액, 올해 실적, 최다 품목 정확
- [ ] admin만 동기화 버튼 표시
- [ ] 일일/벌크 동기화 정상 동작
- [ ] 모바일 반응형 (table-responsive)
- [ ] 사이드바에 "조달내역" 메뉴 표시
