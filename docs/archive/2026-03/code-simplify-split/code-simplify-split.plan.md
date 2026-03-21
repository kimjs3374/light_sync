## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 전체 코드 간소화 및 스플릿 |
| 작성일 | 2026-03-21 |
| 예상 기간 | 3일 (단계별 진행) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 66,376라인 코드베이스가 Claude Code 작업 시 토큰을 과다 소비하여 컨텍스트 효율이 낮음 |
| **Solution** | 인라인 CSS/JS → 정적 파일 추출, 대형 파일 도메인별 분할, 중복 코드 제거 |
| **Function UX Effect** | 개별 파일 500라인 이하 유지 → AI 도구가 필요한 파일만 정확히 읽기 가능 |
| **Core Value** | 토큰 소비 40~60% 절감, 개발 속도 향상, 유지보수성 개선 |

---

# Plan: 전체 코드 간소화 및 스플릿

## 1. 현황 분석

### 1.1 코드 규모
| 영역 | 파일 수 | 라인 수 | 비중 |
|------|---------|---------|------|
| routes/ | 34 | 15,408 | 23% |
| modules/ | 46 | 10,385 | 16% |
| light_sync_mcp/ | 15 | 4,038 | 6% |
| templates/ | 88 | 33,340 | 50% |
| 기타 (app.py, config 등) | 5 | 1,205 | 2% |
| **합계** | **188** | **66,376** | **100%** |

### 1.2 토큰 과다 소비 원인

1. **인라인 CSS/JS** — 56개 템플릿에 `<style>` 블록 내장, 정적 파일 추출 거의 없음
2. **대형 단일 파일** — tools_registry.py(2,170), entities.py(1,526), base.html(1,333)
3. **Route 내 비즈니스 로직 혼재** — bom.py(1,145), inventory.py(1,088), production.py(1,026)
4. **대형 템플릿** — contract_detail(1,779), production_display(1,200), illuminance_verification(1,008)

### 1.3 대형 파일 TOP 10
| 파일 | 라인 | 분할 대상 |
|------|------|-----------|
| tools_registry.py | 2,170 | ✅ 도메인별 모듈로 이관 |
| contract_detail.html | 1,779 | ✅ JS/CSS 추출 |
| entities.py | 1,526 | ✅ 도메인별 분할 |
| base.html | 1,333 | ✅ CSS → magnatech.css |
| production_display.html | 1,200 | ✅ JS/CSS 추출 |
| bom.py | 1,145 | ✅ 서비스 분리 |
| inventory.py | 1,088 | ✅ 서비스 분리 |
| production.py | 1,026 | ✅ 서비스 분리 |
| illuminance_verification.html | 1,008 | ✅ JS/CSS 추출 |
| photo_gallery.html | 979 | ✅ JS/CSS 추출 |

---

## 2. 분할 전략

### Phase 1: 템플릿 CSS/JS 추출 (최대 효과, 최소 리스크)

**목표**: 33,340라인 → ~18,000라인 (인라인 코드 제거)

| 작업 | 대상 | 예상 절감 |
|------|------|-----------|
| base.html Design System CSS → `static/css/magnatech.css` | base.html | ~800라인 |
| base.html 공통 JS → `static/js/common.js` | base.html | ~200라인 |
| 페이지별 인라인 CSS → `static/css/{page}.css` | 56개 템플릿 | ~8,000라인 |
| 페이지별 인라인 JS → `static/js/{page}.js` | 56개 템플릿 | ~6,000라인 |

**규칙**:
- 300라인 이상 인라인 코드가 있는 템플릿부터 우선 처리
- `{% block extra_css %}`, `{% block extra_js %}` 패턴으로 통일
- 정적 파일은 `{{ url_for('static', filename='...') }}` 링크

### Phase 2: MCP tools_registry.py 분할 (이미 부분 진행)

**현재**: tools_registry.py(2,170라인)에 모든 도구 정의
**이미 존재**: tools/bom.py, tools/project.py 등 (하지만 registry에서 여전히 직접 정의)

| 작업 | 세부 |
|------|------|
| 각 `_register_*` 함수를 해당 tools/*.py로 이동 | 16개 도메인 |
| tools_registry.py는 import + register_all() 호출만 유지 | ~50라인 목표 |

### Phase 3: entities.py 도메인별 분할

**현재**: entities.py(1,526라인)에 모든 SQLAlchemy 모델 정의

| 분할 파일 | 포함 엔티티 |
|-----------|-------------|
| models/project.py | Project, Contract, ContractItem |
| models/production.py | ProductionOrder, ProductionProcess |
| models/inventory.py | Item, BomHeader, BomItem, MaterialOrder |
| models/procurement.py | PurchaseOrder, PurchaseOrderItem, Vendor |
| models/delivery.py | Delivery, DeliveryItem |
| models/financial.py | TaxInvoice, Quotation, QuotationItem |
| models/auth.py | User, Department |
| models/misc.py | Notification, Drawing, HistoryLog 등 |

**주의**: `__init__.py`에서 모두 re-export하여 기존 import 호환성 유지

### Phase 4: 대형 Route 파일 서비스 분리

| Route 파일 | 라인 | 분리 대상 |
|------------|------|-----------|
| bom.py | 1,145 | 엑셀 임포트/익스포트 → services/bom_excel.py |
| inventory.py | 1,088 | 실사/회전율 계산 → services/inventory_actions.py |
| production.py | 1,026 | 공정관리 로직 → services/production_actions.py (이미 일부 존재) |
| purchase_order.py | 908 | PDF 생성은 이미 분리, 나머지 helper 정리 |
| project.py | 915 | 초기화/통계 → services/project_actions.py (이미 존재) |

**원칙**: Route는 HTTP 요청/응답 처리만, 비즈니스 로직은 services/로

---

## 3. 우선순위 및 실행 순서

```
Phase 1 (Day 1) ─── 템플릿 CSS/JS 추출
  ├── 1-1. base.html → magnatech.css + common.js
  ├── 1-2. 대형 템플릿 10개 (1000라인+) CSS/JS 추출
  └── 1-3. 중형 템플릿 (500~999라인) CSS/JS 추출

Phase 2 (Day 2) ─── Python 백엔드 분할
  ├── 2-1. tools_registry.py → tools/*.py 이관
  ├── 2-2. entities.py → 도메인별 모델 분할
  └── 2-3. 대형 Route 서비스 분리 (bom, inventory)

Phase 3 (Day 3) ─── 나머지 + 검증
  ├── 3-1. 나머지 Route 서비스 분리
  ├── 3-2. 소형 템플릿 CSS/JS 추출
  └── 3-3. 전체 동작 검증 + 누락 확인
```

## 4. 예상 결과

| 지표 | Before | After | 개선 |
|------|--------|-------|------|
| 최대 파일 크기 | 2,170라인 | ~500라인 | -77% |
| templates 총 라인 | 33,340 | ~18,000 | -46% |
| entities.py | 1,526 | ~200 (index) | -87% |
| tools_registry.py | 2,170 | ~50 (index) | -98% |
| 토큰 소비 (파일 당) | 높음 | 낮음 | -40~60% |

## 5. 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| CSS/JS 추출 시 경로 오류 | `url_for('static')` 사용, 브라우저 DevTools 검증 |
| entities.py 분할 시 circular import | `__init__.py` 단일 진입점 유지, Base 공유 |
| Route 서비스 분리 시 세션/DB 전달 | get_db() 컨텍스트 매니저 패턴 유지 |
| 배포 시 정적 파일 누락 | git add 후 서버에서 pull 검증 |

## 6. 제외 항목 (YAGNI)

- 프론트엔드 프레임워크 전환 (React/Vue 등) — 현재 Jinja2로 충분
- 마이크로서비스 분할 — 단일 Flask 앱 유지
- CSS 프리프로세서 (SCSS/LESS) — 순수 CSS로 충분
- 번들러 도입 (webpack/vite) — CDN + 정적 파일로 충분
