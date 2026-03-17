# product-catalog Design Document

> **Summary**: 나라장터(G2B) API 연동 제품 카탈로그 모델 설계, Route/Service/Template 상세 구현 명세
>
> **Project**: Light-Sync ERP
> **Version**: 1.0
> **Author**: CTO Lead (PDCA Team)
> **Date**: 2026-03-17
> **Status**: Draft
> **Planning Doc**: [product-catalog.plan.md](../../01-plan/features/product-catalog.plan.md)

---

## 1. Overview

### 1.1 설계 목표

- ProductCatalog 테이블을 신규 생성하여 나라장터 계약단가를 ERP에 통합 관리
- 기존 ContractItem 스키마는 수정하지 않고, 문자열 매칭으로 단가를 참조
- 기존 프로젝트 패턴(Blueprint, ACTION_HANDLERS, get_db(), make_pagination) 100% 준수
- 영업관리/주간보고서에 금액 정보를 서버사이드 렌더링으로 추가

### 1.2 설계 원칙

- **기존 패턴 준수**: entities.py 모델 추가, routes/ Blueprint, templates/ Jinja2 패턴 동일하게 적용
- **스키마 분리**: ContractItem은 변경하지 않으며, ProductCatalog는 독립 테이블로 운영
- **단가 보존**: API 동기화 시 price_source='manual'인 기존 수기 단가는 덮어쓰지 않음
- **점진적 통합**: 매칭 실패 품목은 시각적으로 구분하여 수기 보완 유도

---

## 2. Architecture

### 2.1 컴포넌트 다이어그램

```
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Browser    │───>│  Flask Server    │───>│  SQLite DB       │
│  (Jinja2)    │    │                  │    │                  │
│              │    │  routes/         │    │  product_catalog │
│  catalog_    │    │   catalog.py     │    │  contract_items  │
│  list.html   │    │                  │    │  contracts       │
│              │    │  modules/        │    │  projects        │
│  sales_      │    │   services/      │    │                  │
│  list.html   │    │    g2b_catalog_  │    └──────────────────┘
│  (수정)       │    │    sync.py      │
│              │    │                  │    ┌──────────────────┐
│  report_     │    │   models/        │───>│  나라장터 API     │
│  weekly.html │    │    entities.py   │    │  (data.go.kr)    │
│  (수정)       │    │                  │    │  - MAS 품목조회   │
└──────────────┘    └──────────────────┘    │  - 제3자단가조회   │
                                            └──────────────────┘
```

### 2.2 데이터 흐름

```
[관리자] API 동기화 클릭
  -> POST /product_catalog (action=sync_catalog)
  -> handle_sync_catalog(db)
  -> g2b_catalog_sync.sync_from_g2b(db)
    -> getMASCntrctPrdctInfoList API 호출 (226건)
    -> getThptyUcntrctPrdctInfoList API 호출 (41건)
    -> prdct_idnt_no 기준 중복 제거
    -> DB Upsert (price_source='manual'인 기존 단가 보존)
  -> Flash 메시지 ("동기화 완료: 갱신 N건, 신규 N건")
  -> redirect -> GET /product_catalog

[사용자] 카탈로그 목록 조회
  -> GET /product_catalog?q=&price_source=&method=&page=1
  -> DB 검색/필터/페이지네이션
  -> render catalog_list.html

[사용자] 영업관리 목록 조회
  -> GET /sales_management
  -> ContractItem.model_name -> match_catalog_price(db, model_name)
  -> unit_price 매칭 -> quantity * unit_price = 금액
  -> render sales_list.html (금액 컬럼 추가)
```

### 2.3 의존성

| 컴포넌트 | 의존 대상 | 용도 |
|----------|----------|------|
| `routes/catalog.py` | `modules/services/g2b_catalog_sync.py` | API 동기화 호출 |
| `routes/catalog.py` | `modules/models/entities.py` | ProductCatalog 모델 |
| `routes/catalog.py` | `modules/pagination.py` | 페이지네이션 |
| `routes/sales.py` | `modules/services/g2b_catalog_sync.py` | 단가 매칭 함수 |
| `routes/report.py` | `modules/services/g2b_catalog_sync.py` | 예상금액 계산 |
| `g2b_catalog_sync.py` | `requests` (기존 설치 완료) | API HTTP 호출 |
| `g2b_catalog_sync.py` | `os.environ` (.env) | API 키, 사업자번호 |

---

## 3. Data Model

### 3.1 ProductCatalog 모델 (SQLAlchemy)

`modules/models/entities.py`에 추가:

```python
# -------------------------------------------------------------------
# 10. 제품 카탈로그 (나라장터 G2B 연동)
# -------------------------------------------------------------------
class ProductCatalog(Base):
    __tablename__ = 'product_catalog'

    id = Column(Integer, primary_key=True, autoincrement=True)
    prdct_idnt_no = Column(String(30), unique=True, nullable=False)  # 물품식별번호
    krn_prdct_nm = Column(String(300), nullable=False)               # 한글품명
    prdct_clsfc_no = Column(String(30), nullable=True)               # 물품분류번호
    dtl_prdct_nm = Column(String(500), nullable=True)                # 상세품명
    unit = Column(String(20), nullable=True)                         # 단위
    unit_price = Column(Integer, nullable=True)                      # 계약단가 (원)
    price_source = Column(String(10), nullable=False, default='api') # api / manual
    g2b_contract_method = Column(String(20), nullable=True)          # MAS / 제3자단가
    g2b_cntrct_no = Column(String(50), nullable=True)                # 계약번호
    cntrct_bgn_date = Column(Date, nullable=True)                    # 계약시작일
    cntrct_end_date = Column(Date, nullable=True)                    # 계약종료일
    last_synced_at = Column(DateTime, nullable=True)                 # 마지막 동기화 시각
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
```

### 3.2 모델 export 추가

`modules/models/__init__.py`에 추가:

```python
# entities.py import에 추가
from .entities import (
    ...
    ProductCatalog,
)

# __all__ 리스트에 추가
"ProductCatalog",
```

### 3.3 엔티티 관계

```
[ContractItem]                    [ProductCatalog]
  model_name  ── 문자열 매칭 ──>   krn_prdct_nm
  quantity                          unit_price
                                    price_source
  (FK 없음, 문자열 정규화 매칭)      (독립 테이블)
```

> ContractItem과 ProductCatalog 사이에 FK는 설정하지 않는다.
> `match_catalog_price()` 함수에서 문자열 정규화 후 매칭한다.

---

## 4. API/Route 설계

### 4.1 routes/catalog.py (신규)

```python
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.models import ProductCatalog
from modules.services.g2b_catalog_sync import sync_from_g2b

catalog_bp = Blueprint('catalog', __name__)

# ─── ACTION_HANDLERS ─────────────────────────────────────
def handle_sync_catalog(db, form, user_name):
    """나라장터 API 동기화 (관리자 전용)"""
    if session.get('role') != 'admin':
        return {'flash': ('권한이 없습니다.', 'danger')}
    result = sync_from_g2b(db)
    db.commit()
    msg = f"동기화 완료: 신규 {result['created']}건, 갱신 {result['updated']}건"
    if result.get('errors'):
        msg += f", 오류 {result['errors']}건"
    return {'flash': (msg, 'success')}


def handle_update_price(db, form, user_name):
    """수기 단가 수정 (관리자 전용)"""
    if session.get('role') != 'admin':
        return {'flash': ('권한이 없습니다.', 'danger')}
    catalog_id = safe_int(form.get('catalog_id'))
    new_price = safe_int(form.get('unit_price'))
    if not catalog_id:
        return {'flash': ('대상을 찾을 수 없습니다.', 'warning')}

    item = db.query(ProductCatalog).get(catalog_id)
    if not item:
        return {'flash': ('대상을 찾을 수 없습니다.', 'warning')}

    item.unit_price = new_price if new_price and new_price > 0 else None
    item.price_source = 'manual'
    return {'flash': (f'{item.krn_prdct_nm} 단가 수정 완료', 'success')}


ACTION_HANDLERS = {
    'sync_catalog': handle_sync_catalog,
    'update_price': handle_update_price,
}


# ─── ROUTES ──────────────────────────────────────────────
@catalog_bp.route('/product_catalog', methods=['GET'])
@login_required
def catalog_list():
    """제품 카탈로그 목록 (검색, 필터, 페이지네이션)"""
    q = (request.args.get('q') or '').strip().lower()
    price_source = request.args.get('price_source', '')       # api / manual / missing
    method = request.args.get('method', '')                   # MAS / 제3자단가
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 30)

    with get_db() as db:
        query = db.query(ProductCatalog)

        # 검색: 품명 또는 물품식별번호
        if q:
            query = query.filter(
                (ProductCatalog.krn_prdct_nm.ilike(f'%{q}%')) |
                (ProductCatalog.prdct_idnt_no.ilike(f'%{q}%')) |
                (ProductCatalog.dtl_prdct_nm.ilike(f'%{q}%'))
            )

        # 필터: 단가출처
        if price_source == 'api':
            query = query.filter(ProductCatalog.price_source == 'api')
        elif price_source == 'manual':
            query = query.filter(ProductCatalog.price_source == 'manual')
        elif price_source == 'missing':
            query = query.filter(ProductCatalog.unit_price.is_(None))

        # 필터: 계약방식
        if method:
            query = query.filter(ProductCatalog.g2b_contract_method == method)

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        items = query.order_by(ProductCatalog.krn_prdct_nm).offset(offset).limit(per_page).all()

        # 통계
        total_all = db.query(ProductCatalog).count()
        missing_count = db.query(ProductCatalog).filter(
            ProductCatalog.unit_price.is_(None)
        ).count()
        last_sync = db.query(ProductCatalog.last_synced_at).filter(
            ProductCatalog.last_synced_at.isnot(None)
        ).order_by(ProductCatalog.last_synced_at.desc()).first()

        stats = {
            'total': total_all,
            'filtered': total,
            'missing_price': missing_count,
            'has_price': total_all - missing_count,
            'last_synced': last_sync[0].strftime('%Y-%m-%d %H:%M') if last_sync and last_sync[0] else '-',
        }

    return render_template(
        'catalog_list.html',
        items=items,
        stats=stats,
        pagination=pagination,
        filters={
            'q': q,
            'price_source': price_source,
            'method': method,
        },
        is_admin=(session.get('role') == 'admin'),
    )


@catalog_bp.route('/product_catalog', methods=['POST'])
@login_required
def catalog_action():
    """POST 액션 처리 (sync_catalog, update_price)"""
    action = request.form.get('action')
    user_name = session.get('full_name') or '사용자'

    with get_db() as db:
        handler = ACTION_HANDLERS.get(action)
        if handler:
            result = handler(db, request.form, user_name)
            if result.get('flash'):
                flash(*result['flash'])
            db.commit()

    return redirect(url_for('catalog.catalog_list'))
```

### 4.2 엔드포인트 요약

| Method | Path | 설명 | 인증 | 비고 |
|--------|------|------|------|------|
| GET | `/product_catalog` | 카탈로그 목록 | `@login_required` | 검색/필터/페이지네이션 |
| POST | `/product_catalog` | 액션 처리 | `@login_required` | action 파라미터로 분기 |
| POST (action=sync_catalog) | | API 동기화 | 관리자 전용 | Flash 메시지 반환 |
| POST (action=update_price) | | 수기 단가 수정 | 관리자 전용 | catalog_id, unit_price |

---

## 5. Service 모듈 설계

### 5.1 modules/services/g2b_catalog_sync.py (신규)

```python
import os
import re
import logging
import datetime
import requests
from modules.models import ProductCatalog

logger = logging.getLogger(__name__)

# 나라장터 종합쇼핑몰 API Base URL
G2B_BASE_URL = 'https://apis.data.go.kr/1230000/HrcspSsstndrdInfoService'

# API Endpoints
MAS_ENDPOINT = f'{G2B_BASE_URL}/getMASCntrctPrdctInfoList'
THPTY_ENDPOINT = f'{G2B_BASE_URL}/getThptyUcntrctPrdctInfoList'


def _get_api_params():
    """공통 API 파라미터 반환"""
    return {
        'serviceKey': os.environ.get('DATA_GO_KR_API_KEY', ''),
        'numOfRows': '300',
        'pageNo': '1',
        'type': 'json',
        'cntrctCorpBizNo': os.environ.get('COMPANY_BIZ_NO', '4088168519'),
    }


def _fetch_g2b_items(endpoint, method_label):
    """나라장터 API 호출 -> 아이템 리스트 반환"""
    params = _get_api_params()
    try:
        resp = requests.get(endpoint, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # 응답 구조: response > body > items (리스트)
        body = data.get('response', {}).get('body', {})
        items = body.get('items', [])
        if isinstance(items, dict):
            items = items.get('item', [])
        if not isinstance(items, list):
            items = [items] if items else []

        logger.info(f"[G2B] {method_label} API 조회: {len(items)}건")
        return items
    except requests.RequestException as e:
        logger.error(f"[G2B] {method_label} API 오류: {e}")
        return []


def _parse_date(date_str):
    """'YYYYMMDD' 또는 'YYYY-MM-DD' -> date 객체"""
    if not date_str:
        return None
    try:
        cleaned = date_str.replace('-', '')
        return datetime.date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    except (ValueError, IndexError):
        return None


def _parse_price(price_val):
    """가격 문자열 -> int 또는 None"""
    if price_val is None:
        return None
    try:
        price = int(float(str(price_val)))
        return price if price > 0 else None
    except (ValueError, TypeError):
        return None


def sync_from_g2b(db):
    """
    나라장터 API에서 제품 목록을 가져와 DB에 Upsert.
    - price_source='manual'인 기존 수기 단가는 덮어쓰지 않음
    - prdct_idnt_no 기준 중복 제거

    Returns:
        dict: {'created': int, 'updated': int, 'errors': int}
    """
    now = datetime.datetime.now()
    created = 0
    updated = 0
    errors = 0

    # 1. MAS(다수공급자) 품목 조회
    mas_items = _fetch_g2b_items(MAS_ENDPOINT, 'MAS')

    # 2. 제3자단가 품목 조회
    thpty_items = _fetch_g2b_items(THPTY_ENDPOINT, '제3자단가')

    # 3. prdct_idnt_no 기준 중복 제거 (MAS 우선)
    merged = {}
    for item in mas_items:
        idnt_no = str(item.get('prdctIdntNo', '')).strip()
        if idnt_no:
            merged[idnt_no] = (item, 'MAS')
    for item in thpty_items:
        idnt_no = str(item.get('prdctIdntNo', '')).strip()
        if idnt_no and idnt_no not in merged:
            merged[idnt_no] = (item, '제3자단가')

    # 4. DB Upsert
    for idnt_no, (item, contract_method) in merged.items():
        try:
            existing = db.query(ProductCatalog).filter_by(
                prdct_idnt_no=idnt_no
            ).first()

            api_price = _parse_price(item.get('cntrctPrceAmt'))
            krn_nm = str(item.get('prdctNm', '')).strip()
            clsfc_no = str(item.get('prdctClsfcNo', '')).strip() or None
            dtl_nm = str(item.get('dtlPrdctNm', '')).strip() or None
            unit = str(item.get('prdctUnit', '')).strip() or None
            cntrct_no = str(item.get('cntrctNo', '')).strip() or None
            bgn_date = _parse_date(item.get('cntrctBgnDate'))
            end_date = _parse_date(item.get('cntrctEndDate'))

            if existing:
                # 업데이트 (수기 단가는 보존)
                existing.krn_prdct_nm = krn_nm or existing.krn_prdct_nm
                existing.prdct_clsfc_no = clsfc_no or existing.prdct_clsfc_no
                existing.dtl_prdct_nm = dtl_nm or existing.dtl_prdct_nm
                existing.unit = unit or existing.unit
                existing.g2b_contract_method = contract_method
                existing.g2b_cntrct_no = cntrct_no or existing.g2b_cntrct_no
                existing.cntrct_bgn_date = bgn_date or existing.cntrct_bgn_date
                existing.cntrct_end_date = end_date or existing.cntrct_end_date
                existing.last_synced_at = now

                # 수기 단가 보존 로직
                if existing.price_source != 'manual':
                    existing.unit_price = api_price
                    existing.price_source = 'api'

                updated += 1
            else:
                # 신규 생성
                new_item = ProductCatalog(
                    prdct_idnt_no=idnt_no,
                    krn_prdct_nm=krn_nm,
                    prdct_clsfc_no=clsfc_no,
                    dtl_prdct_nm=dtl_nm,
                    unit=unit,
                    unit_price=api_price,
                    price_source='api' if api_price else 'api',
                    g2b_contract_method=contract_method,
                    g2b_cntrct_no=cntrct_no,
                    cntrct_bgn_date=bgn_date,
                    cntrct_end_date=end_date,
                    last_synced_at=now,
                )
                db.add(new_item)
                created += 1

        except Exception as e:
            logger.error(f"[G2B] Upsert 오류 ({idnt_no}): {e}")
            errors += 1

    return {'created': created, 'updated': updated, 'errors': errors}


# ─── 매칭 함수 ──────────────────────────────────────────────

def _normalize_name(name):
    """매칭용 문자열 정규화: 소문자, 공백/특수문자 제거"""
    if not name:
        return ''
    s = str(name).strip().lower()
    # 괄호 내용 제거: (60W), [LED] 등
    s = re.sub(r'[\(\[\{].*?[\)\]\}]', '', s)
    # 공백, 하이픈, 언더스코어, 슬래시 제거
    s = re.sub(r'[\s\-_/.,·]', '', s)
    return s


def match_catalog_price(db, model_name):
    """
    ContractItem.model_name으로 ProductCatalog에서 단가를 매칭.

    Args:
        db: SQLAlchemy session
        model_name: ContractItem의 model_name 값

    Returns:
        dict: {'unit_price': int|None, 'matched': bool, 'catalog_name': str|None}
    """
    if not model_name:
        return {'unit_price': None, 'matched': False, 'catalog_name': None}

    normalized_input = _normalize_name(model_name)
    if not normalized_input:
        return {'unit_price': None, 'matched': False, 'catalog_name': None}

    # 1차: DB LIKE 검색으로 후보군 축소
    candidates = db.query(ProductCatalog).filter(
        ProductCatalog.krn_prdct_nm.ilike(f'%{model_name[:10]}%')
    ).all()

    # 후보군이 없으면 전체 검색
    if not candidates:
        candidates = db.query(ProductCatalog).all()

    # 2차: 정규화 문자열 비교
    for cat in candidates:
        if _normalize_name(cat.krn_prdct_nm) == normalized_input:
            return {
                'unit_price': cat.unit_price,
                'matched': True,
                'catalog_name': cat.krn_prdct_nm,
            }

    # 3차: 부분 포함 매칭 (정규화된 입력이 카탈로그명에 포함되거나 그 반대)
    for cat in candidates:
        norm_cat = _normalize_name(cat.krn_prdct_nm)
        if normalized_input in norm_cat or norm_cat in normalized_input:
            return {
                'unit_price': cat.unit_price,
                'matched': True,
                'catalog_name': cat.krn_prdct_nm,
            }

    return {'unit_price': None, 'matched': False, 'catalog_name': None}


def get_catalog_price_map(db):
    """
    전체 카탈로그의 정규화된 이름 -> unit_price 매핑 딕셔너리 생성.
    목록 페이지에서 N+1 쿼리 방지를 위해 일괄 로드.

    Returns:
        dict: {normalized_name: {'unit_price': int|None, 'catalog_name': str}}
    """
    catalogs = db.query(ProductCatalog).all()
    price_map = {}
    for cat in catalogs:
        norm = _normalize_name(cat.krn_prdct_nm)
        if norm:
            price_map[norm] = {
                'unit_price': cat.unit_price,
                'catalog_name': cat.krn_prdct_nm,
            }
    return price_map


def match_from_price_map(price_map, model_name):
    """
    사전 로드된 price_map에서 model_name 매칭.
    목록 렌더링 시 성능 최적화용.

    Returns:
        dict: {'unit_price': int|None, 'matched': bool, 'catalog_name': str|None}
    """
    if not model_name:
        return {'unit_price': None, 'matched': False, 'catalog_name': None}

    norm = _normalize_name(model_name)
    if not norm:
        return {'unit_price': None, 'matched': False, 'catalog_name': None}

    # 정확 매칭
    if norm in price_map:
        entry = price_map[norm]
        return {
            'unit_price': entry['unit_price'],
            'matched': True,
            'catalog_name': entry['catalog_name'],
        }

    # 부분 포함 매칭
    for cat_norm, entry in price_map.items():
        if norm in cat_norm or cat_norm in norm:
            return {
                'unit_price': entry['unit_price'],
                'matched': True,
                'catalog_name': entry['catalog_name'],
            }

    return {'unit_price': None, 'matched': False, 'catalog_name': None}
```

---

## 6. Template 설계

### 6.1 templates/catalog_list.html (신규)

```
{% extends 'base.html' %}
{% block content %}

구조:
┌──────────────────────────────────────────────────────────────┐
│  h2: "제품 카탈로그"                                           │
├──────────────────────────────────────────────────────────────┤
│  통계 카드 (4개 가로 배치)                                      │
│  ┌───────────┬───────────┬───────────┬───────────┐           │
│  │ 전체 제품  │ 단가 등록  │ 미등록     │ 최종 동기화 │           │
│  │ {{ total }}│ {{ has }} │ {{ miss }}│ {{ sync }}│           │
│  └───────────┴───────────┴───────────┴───────────┘           │
├──────────────────────────────────────────────────────────────┤
│  검색/필터 폼                                                  │
│  [검색어 input] [단가출처 select] [계약방식 select] [검색 btn]    │
│  (관리자) [API 동기화 btn]                                     │
├──────────────────────────────────────────────────────────────┤
│  테이블 (mobile-stack-table)                                   │
│  ┌────┬──────────┬────────┬──────┬──────┬──────┬──────┬────┐ │
│  │ No │ 물품식별번호│ 품명   │ 분류  │ 단가  │ 출처  │ 계약  │수정│ │
│  ├────┼──────────┼────────┼──────┼──────┼──────┼──────┼────┤ │
│  │ 1  │ 24835... │ LED... │ 3911│ 45000│ api  │ MAS  │ [E]│ │
│  │ 2  │ 24836... │ ...    │ ... │ -    │ -    │ MAS  │ [E]│ │  <- 노란 배경 (미등록)
│  └────┴──────────┴────────┴──────┴──────┴──────┴──────┴────┘ │
├──────────────────────────────────────────────────────────────┤
│  pagination component                                        │
└──────────────────────────────────────────────────────────────┘
```

주요 요소:
- 통계 카드: `stats.total`, `stats.has_price`, `stats.missing_price`, `stats.last_synced`
- 검색 폼: GET 방식, `q`, `price_source`, `method` 파라미터
- API 동기화 버튼: `is_admin`일 때만 표시, POST form (action=sync_catalog)
- 테이블 헤더: No / 물품식별번호 / 품명 / 분류번호 / 단가 / 출처 / 계약방식 / 수정
- 단가 미등록 행: `style="background: #fffbeb;"` (노란 배경, FR-09)
- 단가 표시: `{{ "{:,}".format(item.unit_price) }}원` 또는 `-`
- 수정 컬럼 (관리자): inline form, input + 저장 btn (action=update_price, catalog_id, unit_price)
- 페이지네이션: `{% include 'components/pagination.html' %}`

### 6.2 templates/sales_list.html 수정

기존 contract-subtable 테이블의 `<thead>` 및 `<tbody>`에 금액 컬럼 추가:

```html
<!-- thead에 추가 -->
<th>단가</th><th>금액</th>

<!-- tbody item 행에 추가 -->
<td>
    {% if item._catalog_price and item._catalog_price.matched %}
        {{ "{:,}".format(item._catalog_price.unit_price) if item._catalog_price.unit_price else '-' }}
    {% else %}
        <span class="text-muted">-</span>
    {% endif %}
</td>
<td>
    {% if item._catalog_price and item._catalog_price.matched and item._catalog_price.unit_price %}
        <strong>{{ "{:,}".format(item.quantity * item._catalog_price.unit_price) }}</strong>
    {% else %}
        <span class="text-muted">-</span>
    {% endif %}
</td>
```

> **주의**: `item._catalog_price`는 `routes/sales.py`에서 아이템에 동적으로 할당하는 속성이다.
> sales.py의 `sales_list()` 함수에서 price_map을 로드하고 각 item에 매칭 결과를 할당한다.

### 6.3 templates/report_weekly.html 수정

섹션 4 "금주 계약 전환 현장" 테이블에 **예상금액** 컬럼 추가:

```html
<!-- thead에 추가 -->
<th>예상금액</th>

<!-- tbody에 추가 -->
<td>
    {% if p._estimated_amount %}
        {{ "{:,}".format(p._estimated_amount) }}원
    {% else %}
        -
    {% endif %}
</td>
```

> `p._estimated_amount`는 `routes/report.py`에서 계산하여 할당한다.

---

## 7. 기존 코드 수정 사항

### 7.1 routes/sales.py 수정

`sales_list()` 함수에서 price_map 로드 및 ContractItem에 매칭 결과 할당:

```python
# import 추가
from modules.services.g2b_catalog_sync import get_catalog_price_map, match_from_price_map

# sales_list() 함수 내, with get_db() as db: 블록에서
# projects 로딩 후 enriched 루프 전에:
price_map = get_catalog_price_map(db)

# enriched 루프 내에서 각 contract의 items에 매칭 결과 할당:
for c in (p.contracts or []):
    for item in (c.items or []):
        item._catalog_price = match_from_price_map(price_map, item.model_name)
```

### 7.2 routes/report.py 수정

`weekly_report()` 함수에서 계약 전환 프로젝트에 예상금액 계산:

```python
# import 추가
from modules.services.g2b_catalog_sync import get_catalog_price_map, match_from_price_map

# with get_db() as db: 블록 내, converted_projects 로딩 후:
price_map = get_catalog_price_map(db)

for p in converted_projects:
    total_amount = 0
    for c in (p.contracts or []):
        for item in (c.items or []):
            match = match_from_price_map(price_map, item.model_name)
            if match['matched'] and match['unit_price']:
                total_amount += item.quantity * match['unit_price']
    p._estimated_amount = total_amount if total_amount > 0 else None
```

### 7.3 app.py 수정

Blueprint 등록 추가:

```python
# import 추가
from routes.catalog import catalog_bp

# Blueprint 등록 (report_bp 뒤에)
app.register_blueprint(catalog_bp)
```

### 7.4 templates/base.html 수정

사이드바 메뉴에 제품 카탈로그 링크 추가:

```html
<!-- "하자보증/AS" 링크 앞에 추가 -->
<a href="{{ url_for('catalog.catalog_list') }}">제품 카탈로그</a>
```

---

## 8. 매칭 로직 상세

### 8.1 문자열 정규화 규칙

`_normalize_name(name)` 함수의 정규화 단계:

| 단계 | 처리 | 예시 |
|------|------|------|
| 1 | strip() + lower() | `" LED 투광기(60W) "` -> `"led 투광기(60w)"` |
| 2 | 괄호 내용 제거 | `"led 투광기(60w)"` -> `"led 투광기"` |
| 3 | 공백/특수문자 제거 | `"led 투광기"` -> `"led투광기"` |

### 8.2 매칭 우선순위

| 우선순위 | 방법 | 설명 |
|----------|------|------|
| 1차 | DB LIKE 검색 | model_name 앞 10자로 후보군 축소 |
| 2차 | 정규화 정확 매칭 | `_normalize(model) == _normalize(catalog)` |
| 3차 | 부분 포함 매칭 | 정규화 문자열 간 포함 관계 확인 |

### 8.3 N+1 쿼리 방지 전략

- 목록 페이지(`sales_list`, `weekly_report`)에서는 `get_catalog_price_map(db)` 호출로 전체 카탈로그를 1번만 로드
- 개별 매칭은 메모리 상의 딕셔너리에서 수행 (`match_from_price_map`)
- 241건 수준이므로 메모리 부담 없음

---

## 9. 보안 고려사항

- [x] API 키는 `.env`에서 `os.environ.get('DATA_GO_KR_API_KEY')` 으로 읽기 (하드코딩 금지)
- [x] API 동기화/수기 수정은 `session.get('role') == 'admin'` 체크
- [x] CSRF 보호: 기존 CSRFProtect + POST form 패턴 그대로 사용
- [x] SQL Injection 방지: SQLAlchemy ORM 사용 (raw query 없음)
- [x] XSS 방지: Jinja2 autoescaping 기본 활성화
- [x] API 호출 timeout 30초 설정

---

## 10. 에러 처리

### 10.1 에러 시나리오

| 시나리오 | 처리 방식 | 사용자 피드백 |
|----------|----------|-------------|
| API 키 미설정 | 빈 응답 반환, 로그 기록 | Flash: "API 설정을 확인하세요" |
| API 호출 timeout | requests.RequestException catch | Flash: "나라장터 API 응답 지연" |
| API 응답 파싱 오류 | 개별 아이템 skip, errors 카운트 | Flash에 오류 건수 표시 |
| 매칭 실패 | unit_price=None, matched=False | 템플릿에서 `-` 표시 |
| 수기 단가 음수/비정상 | None 처리 | Flash: "단가를 확인하세요" |

---

## 11. 구현 순서 체크리스트

| Step | 작업 | 파일 경로 | 함수/클래스 | 의존성 |
|------|------|----------|------------|--------|
| 1 | ProductCatalog 모델 추가 | `modules/models/entities.py` | `class ProductCatalog(Base)` | 없음 |
| 2 | 모델 export 추가 | `modules/models/__init__.py` | `ProductCatalog` import/all | Step 1 |
| 3 | G2B 동기화 서비스 작성 | `modules/services/g2b_catalog_sync.py` | `sync_from_g2b()`, `match_catalog_price()`, `get_catalog_price_map()`, `match_from_price_map()` | Step 1 |
| 4 | 카탈로그 Route 작성 | `routes/catalog.py` | `catalog_bp`, `catalog_list()`, `catalog_action()`, `handle_sync_catalog()`, `handle_update_price()` | Step 1, 3 |
| 5 | 카탈로그 템플릿 작성 | `templates/catalog_list.html` | Jinja2 템플릿 | Step 4 |
| 6 | app.py Blueprint 등록 + 사이드바 메뉴 | `app.py`, `templates/base.html` | `catalog_bp` 등록, 사이드바 `<a>` 추가 | Step 4 |
| 7 | 영업관리 금액 표시 | `routes/sales.py`, `templates/sales_list.html` | price_map 로드 + 템플릿 컬럼 추가 | Step 3 |
| 8 | 주간보고서 예상금액 | `routes/report.py`, `templates/report_weekly.html` | _estimated_amount 계산 + 컬럼 추가 | Step 3 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft | CTO Lead (PDCA Team) |
