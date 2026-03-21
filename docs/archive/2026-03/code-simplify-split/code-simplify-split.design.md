## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 전체 코드 간소화 및 스플릿 |
| 작성일 | 2026-03-21 |
| Plan 참조 | `docs/01-plan/features/code-simplify-split.plan.md` |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 66,376라인 → 대형 파일 다수 → Claude Code 토큰 과다 소비 |
| **Solution** | 4 Phase 분할: CSS/JS 추출 → MCP 분할 → 엔티티 분할 → Route 서비스 분리 |
| **Function UX Effect** | 개별 파일 500라인 이하 → AI가 필요 파일만 정확히 읽기 가능 |
| **Core Value** | 토큰 ~50% 절감, 유지보수성 대폭 개선 |

---

# Design: 전체 코드 간소화 및 스플릿

## 1. Phase 1: base.html CSS/JS 추출 (최우선)

### 1.1 현재 base.html 구조 (1,334라인)

```
line 10~515   : <style> — MAGNATECH Design System CSS (~505라인)
line 516~517  : {% block head %} (페이지별 CSS 주입점)
line 518~656  : HTML 구조 (사이드바 + main-content)
line 660~760  : <style> — FAB/챗봇/인쇄 CSS (~100라인)
line 761~945  : 챗봇 HTML + <script> — 챗봇 JS (~140라인)
line 948~1048 : <script> — 모바일 메뉴 + 모바일 테이블 스택 (~100라인)
line 1051~1086: <script> — CSRF auto-injection (~35라인)
line 1089~1102: <script> — 알림 뱃지 폴링 (~14라인)
line 1103~1329: <script> — 사이드바 접이식+그룹+플라이아웃+즐겨찾기 (~226라인)
line 1330~1334: includes + {% block scripts %}
```

### 1.2 추출 계획

| 원본 위치 | 추출 대상 | 라인 수 |
|-----------|-----------|---------|
| line 10~515 | `static/css/magnatech.css` | ~505 |
| line 660~760 | `static/css/magnatech.css`에 합침 (FAB/챗봇/인쇄) | ~100 |
| line 761~945 | `static/js/chatbot-panel.js` | ~140 |
| line 949~1048 | `static/js/mobile-table.js` | ~100 |
| line 1051~1086 | `static/js/csrf-inject.js` | ~35 |
| line 1089~1102 | `static/js/notification-badge.js` | ~14 |
| line 1103~1329 | `static/js/sidebar.js` | ~226 |

### 1.3 추출 후 base.html 구조 (~220라인)

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <title>Light-Sync ERP</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="...fonts..." rel="stylesheet">
    <link href="{{ url_for('static', filename='css/magnatech.css') }}" rel="stylesheet">
    {% block head %}{% endblock %}
</head>
<body>
    <script>/* 사이드바 FOUC 방지 (5줄, 인라인 유지) */</script>
    <!-- 모바일 메뉴 버튼 -->
    <!-- 사이드바 HTML -->
    <!-- main-content -->
    <!-- 챗봇 HTML (FAB + panel) -->

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="{{ url_for('static', filename='js/csrf-inject.js') }}"></script>
    <script src="{{ url_for('static', filename='js/mobile-table.js') }}"></script>
    <script src="{{ url_for('static', filename='js/notification-badge.js') }}"></script>
    <script src="{{ url_for('static', filename='js/sidebar.js') }}"></script>
    <script src="{{ url_for('static', filename='js/chatbot-panel.js') }}"></script>
    {% include 'components/change_password_modal.html' %}
    {% include 'components/catalog_autocomplete.html' %}
    {% include 'components/vendor_autocomplete.html' %}
    {% block scripts %}{% endblock %}
</body>
</html>
```

**결과**: base.html 1,334 → ~220라인 (-83%)

### 1.4 인라인 유지 항목

- **FOUC 방지 스크립트** (5줄): DOM 파싱 전 실행 필수 → 인라인 유지
- **Jinja2 템플릿 변수**: HTML 구조 내 `{{ session.* }}`, `{% for %}` 등 → 인라인 유지

### 1.5 주의사항

- `chatbot-panel.js`에서 `_panelCsrf` 변수는 인라인에서 `meta[name="csrf-token"]`을 읽으므로 JS 파일로 분리해도 동작
- `magnatech.css` 내 `:root` 변수 → 페이지별 CSS에서도 참조 가능

---

## 2. Phase 1-2: 페이지별 템플릿 CSS/JS 추출

### 2.1 대상 (300라인 이상 인라인 보유 템플릿, 추정 15~20개)

| 템플릿 | 총 라인 | 인라인 추정 |
|--------|---------|------------|
| contract_detail.html | 1,779 | ~600 |
| production_display.html | 1,200 | ~500 |
| illuminance_verification.html | 1,008 | ~400 |
| photo_gallery.html | 979 | ~350 |
| delivery_detail.html | 936 | ~300 |
| drawings_gallery.html | 935 | ~350 |
| illuminance_new.html | 883 | ~300 |
| dashboard.html | 881 | ~300 |
| quotation_create.html | 764 | ~250 |
| production.html | 738 | ~250 |

### 2.2 추출 패턴

**Before (인라인):**
```html
{% block head %}
<style>
    .contract-table { ... }
    /* 200+ lines */
</style>
{% endblock %}

{% block content %}
<!-- HTML -->
{% endblock %}

{% block scripts %}
<script>
    // 300+ lines of JS
</script>
{% endblock %}
```

**After (분리):**
```html
{% block head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/contract_detail.css') }}">
{% endblock %}

{% block content %}
<!-- HTML (unchanged) -->
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/contract_detail.js') }}"></script>
{% endblock %}
```

### 2.3 파일명 규칙

- CSS: `static/css/{template_name}.css` (확장자 제외)
- JS: `static/js/{template_name}.js`
- 예: `contract_detail.html` → `contract_detail.css` + `contract_detail.js`

### 2.4 Jinja2 변수 참조 처리

일부 `<script>` 블록에서 Jinja2 변수를 참조하는 경우:

```html
<!-- 인라인에서 data 속성으로 전달 -->
<div id="page-data"
     data-project-id="{{ project.id }}"
     data-csrf="{{ csrf_token() }}">
</div>

<!-- 외부 JS에서 읽기 -->
<script src="{{ url_for('static', filename='js/contract_detail.js') }}"></script>
```

**또는** JSON 변수 패턴:
```html
<script>
    var PAGE_DATA = {{ page_data | tojson }};
</script>
<script src="{{ url_for('static', filename='js/contract_detail.js') }}"></script>
```

→ 소량의 인라인 변수 주입은 허용 (5줄 이내)

---

## 3. Phase 2: tools_registry.py 분할

### 3.1 현재 상태

- `tools_registry.py` (2,170라인): 17개 `_register_*` 함수 모두 포함
- `tools/*.py` (6개 파일, 1,594라인): bom, financial, inventory, procurement, production, project — **이미 존재하나 registry와 중복**

### 3.2 분할 설계

**중복 제거 후 registry에서만 호출하는 구조로 전환**

기존 `tools/*.py`가 있는 6개 도메인은 registry 내 중복 코드를 삭제하고, 나머지 11개 도메인을 새 파일로 추출합니다.

| 도메인 | 현재 | 작업 |
|--------|------|------|
| inventory | tools/inventory.py 존재 | registry 내 중복 삭제 |
| bom | tools/bom.py 존재 | registry 내 중복 삭제 |
| project | tools/project.py 존재 | registry 내 중복 삭제 |
| production | tools/production.py 존재 | registry 내 중복 삭제 |
| financial | tools/financial.py 존재 | registry 내 중복 삭제 |
| procurement | tools/procurement.py 존재 | registry 내 중복 삭제 |
| quotation | 신규 | → tools/quotation.py |
| delivery | 신규 | → tools/delivery.py |
| warranty | 신규 | → tools/warranty.py |
| sales | 신규 | → tools/sales.py |
| drawing | 신규 | → tools/drawing.py |
| catalog | 신규 | → tools/catalog.py |
| contract | 신규 | → tools/contract.py |
| daily_report | 신규 | → tools/daily_report.py |
| notification | 신규 | → tools/notification.py |
| overview | 신규 | → tools/overview.py |
| resources | 이미 존재 | resources/magnatech.py 유지 |

### 3.3 각 tools/*.py 구조

```python
"""MCP tools — {도메인}"""
from mcp.server.fastmcp import FastMCP
from ..db import get_session

def _s(val, default=""):
    return val if val is not None else default

def register(mcp: FastMCP):
    @mcp.tool()
    def get_xxx(...):
        ...
```

### 3.4 tools_registry.py 최종 형태 (~60라인)

```python
"""모든 tool/resource를 FastMCP 인스턴스에 등록"""
from mcp.server.fastmcp import FastMCP

from .tools import (
    bom, catalog, contract, daily_report, delivery,
    drawing, financial, inventory, notification,
    overview, procurement, production, project,
    quotation, sales, warranty,
)
from .resources import magnatech


def _s(val, default=""):
    return val if val is not None else default

def _sn(val, default=0.0):
    return float(val) if val is not None else default

def _sd(val):
    return val.isoformat() if val else ""


def register_all(mcp: FastMCP):
    inventory.register(mcp)
    bom.register(mcp)
    project.register(mcp)
    production.register(mcp)
    financial.register(mcp)
    procurement.register(mcp)
    quotation.register(mcp)
    delivery.register(mcp)
    warranty.register(mcp)
    sales.register(mcp)
    drawing.register(mcp)
    catalog.register(mcp)
    contract.register(mcp)
    daily_report.register(mcp)
    notification.register(mcp)
    overview.register(mcp)
    magnatech.register(mcp)
```

### 3.5 헬퍼 함수 공유

`_s`, `_sn`, `_sd` 헬퍼를 `tools/_helpers.py`로 추출:

```python
# light_sync_mcp/tools/_helpers.py
def _s(val, default=""):
    return val if val is not None else default

def _sn(val, default=0.0):
    return float(val) if val is not None else default

def _sd(val):
    return val.isoformat() if val else ""
```

각 tools/*.py에서 `from ._helpers import _s, _sn, _sd` 로 import.

---

## 4. Phase 3: entities.py 도메인별 분할

### 4.1 현재: 58개 모델 클래스 in 1,526라인

### 4.2 분할 설계

| 파일 | 엔티티 | 예상 라인 |
|------|--------|-----------|
| `models/project_entities.py` | Project, ProjectPriorityOverride, ProjectDeleteRequest, ProjectPhoto, Contact, SportsModule | ~200 |
| `models/contract_entities.py` | Contract, ContractItem, ContractBarcode | ~130 |
| `models/delivery_entities.py` | Delivery, DeliverySplit, DeliveryPhoto | ~100 |
| `models/production_entities.py` | ProductionProcess, ProductionDailyLog, Material, MaterialOrder | ~180 |
| `models/drawing_entities.py` | Drawing, DrawingVersion, DrawingShareLink, DrawingAccessLog | ~120 |
| `models/procurement_entities.py` | PurchaseOrder, PurchaseOrderItem, PurchaseOrderHistory, Vendor, VendorItem | ~180 |
| `models/receiving_entities.py` | Receiving, ReceivingItem, ReceivingHistory | ~100 |
| `models/inventory_entities.py` | Item, BomHeader, BomItem, StockAudit, StockAuditItem, StockMovement | ~200 |
| `models/financial_entities.py` | TaxInvoice, PaymentRecord, Quotation, QuotationItem, QuoteTemplate, QuoteTemplateItem | ~200 |
| `models/auth_entities.py` | User, GroupPermission, UserPriorityPermission, EmailSignature | ~100 |
| `models/misc_entities.py` | HistoryLog, DashboardNotice, DashboardSetting, Notification, DailyReport, EmailHistory, Warranty, WarrantyCase, WarrantyCaseLog, G2bProcurement, ProductCatalog, IlluminanceProject, IlluminanceArea, IlluminanceMeasured | ~250 |

### 4.3 기술 설계

**circular import 방지**: 모든 모델 파일이 `from .base import Base` 만 import.
relationship의 target은 **문자열 참조** (이미 현재 코드가 이 패턴 사용).

```python
# models/project_entities.py
from .base import Base
from .constants import DETAIL_ITEM_OPTIONS

class Project(Base):
    __tablename__ = 'projects'
    # ... (문자열 참조 relationship)
    contracts = relationship("Contract", back_populates="project", ...)
```

**`entities.py` → 호환성 브릿지** (기존 import 유지):

```python
# models/entities.py — 호환성 유지용 re-export
from .project_entities import *
from .contract_entities import *
from .delivery_entities import *
from .production_entities import *
from .drawing_entities import *
from .procurement_entities import *
from .receiving_entities import *
from .inventory_entities import *
from .financial_entities import *
from .auth_entities import *
from .misc_entities import *
```

→ 기존 `from modules.models.entities import Project` 등이 깨지지 않음

### 4.4 `__init__.py` 변경 없음

현재 `__init__.py`가 `from .entities import ...`로 모든 모델을 re-export하고 있으므로,
entities.py가 도메인 파일들을 re-export하면 `__init__.py` 수정 불필요.

---

## 5. Phase 4: 대형 Route 서비스 분리

### 5.1 분리 대상

| Route | 라인 | 추출 대상 | 새 서비스 파일 |
|-------|------|-----------|---------------|
| bom.py | 1,145 | 엑셀 import/export, BOM 계산 로직 | services/bom_actions.py |
| inventory.py | 1,088 | 실사 처리, 회전율 계산, 변동이력 | services/inventory_actions.py (확장) |
| production.py | 1,026 | 공정 CRUD helper, 일일로그 집계 | services/production_actions.py (확장) |

### 5.2 분리 원칙

**Route 파일에 남는 것:**
- Blueprint 정의 및 URL 매핑
- request 파싱 (form, args, json)
- 권한 체크 (`@login_required`)
- flash/redirect/render_template 호출
- 에러 핸들링 (abort, try-except)

**서비스로 이동하는 것:**
- DB 쿼리 조합 (ORM query builder)
- 비즈니스 로직 (계산, 변환, 집계)
- 엑셀/PDF 생성 로직
- 외부 API 호출

### 5.3 서비스 함수 시그니처 패턴

```python
# services/bom_actions.py
def get_bom_list(db, project_id=None, search=None, page=1, per_page=20):
    """BOM 목록 조회 + 페이지네이션"""
    query = db.query(BomHeader).options(...)
    # ... 필터/정렬/페이지네이션
    return {"items": items, "pagination": pagination}

def export_bom_excel(db, bom_id):
    """BOM 엑셀 다운로드용 BytesIO 반환"""
    # ... openpyxl 처리
    return output  # BytesIO
```

```python
# routes/bom.py (간소화)
@bom_bp.route('/bom')
@login_required
def bom_list():
    with get_db() as db:
        result = bom_actions.get_bom_list(db, ...)
        return render_template('bom_list.html', **result)
```

---

## 6. 구현 순서 (의존성 기반)

```
Step 1: static/css/magnatech.css 추출 (base.html CSS)
Step 2: static/js/*.js 5개 추출 (base.html JS)
Step 3: base.html 정리 (CSS/JS 링크로 교체)
  ↓ (base.html 완료 후)
Step 4: 대형 템플릿 10개 CSS/JS 추출 (병렬 가능)
Step 5: 중형 템플릿 CSS/JS 추출 (병렬 가능)
  ↓ (Phase 1 완료)
Step 6: tools/_helpers.py 생성
Step 7: 기존 tools/*.py 6개 → register() 패턴 통일
Step 8: 신규 tools/*.py 10개 생성 (registry 함수 이동)
Step 9: tools_registry.py 간소화
  ↓ (Phase 2 완료)
Step 10: 11개 도메인 엔티티 파일 생성
Step 11: entities.py → re-export 브릿지
  ↓ (Phase 3 완료)
Step 12: services/bom_actions.py 추출
Step 13: services/inventory_actions.py 확장
Step 14: services/production_actions.py 확장
Step 15: routes 간소화
  ↓ (Phase 4 완료)
Step 16: 전체 동작 검증
```

## 7. 검증 계획

| 검증 항목 | 방법 |
|-----------|------|
| CSS 렌더링 | 브라우저에서 주요 페이지 5개 시각 확인 |
| JS 동작 | 사이드바 토글/플라이아웃/챗봇/CSRF 동작 확인 |
| MCP 서버 | `python -m light_sync_mcp` 실행, 도구 목록 확인 |
| 모델 import | `python -c "from modules.models import Project, User, ..."` |
| Route 동작 | Flask 기동 후 주요 CRUD 시나리오 수동 테스트 |
| 라인 수 측정 | `wc -l` 로 Before/After 비교 |

## 8. 리스크 대응

| 리스크 | 확률 | 대응 |
|--------|------|------|
| CSS 순서 변경으로 스타일 깨짐 | 중 | magnatech.css 내 순서를 base.html 원본과 동일하게 유지 |
| Jinja2 변수 JS 분리 불가 | 낮 | 소량 인라인 유지 (data 속성 패턴) |
| circular import (entities 분할) | 낮 | 문자열 relationship 참조 (이미 사용 중) |
| 기존 tools/*.py와 registry 충돌 | 중 | 기존 파일의 register() 패턴 확인 후 통일 |
