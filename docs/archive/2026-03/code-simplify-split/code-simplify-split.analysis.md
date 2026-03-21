# Gap Analysis: code-simplify-split (Iteration 2)

| 항목 | 내용 |
|------|------|
| Feature | 전체 코드 간소화 및 스플릿 |
| 분석일 | 2026-03-21 |
| Match Rate | **100%** (66/66 항목) |
| Iteration | 2 (Iteration 1: 80% → Iteration 2: 100%) |

---

## Phase별 점수

| Phase | Iter 1 | Iter 2 | 상태 |
|-------|:------:|:------:|:----:|
| Phase 1: base.html CSS/JS 추출 | 100% | 100% | PASS |
| Phase 1-2: 페이지별 템플릿 CSS/JS 추출 | 40% | 100% | PASS |
| Phase 2: tools_registry.py 분할 | 100% | 100% | PASS |
| Phase 3: entities.py 도메인별 분할 | 100% | 100% | PASS |
| Phase 4: 대형 Route 서비스 분리 | 83% | 100% | PASS |
| **Overall** | **80%** | **100%** | **PASS** |

---

## Phase 1-2: 페이지별 템플릿 CSS/JS 추출 — 100%

| 템플릿 | Before | After | 감소율 | CSS | JS |
|--------|-------:|------:|------:|:---:|:--:|
| contract_detail | 1,779 | 966 | -46% | PASS | PASS |
| production_display | 1,200 | 222 | -82% | PASS | PASS |
| illuminance_verification | 1,008 | 178 | -82% | PASS | PASS |
| photo_gallery | 979 | 166 | -83% | PASS | PASS |
| delivery_detail | 936 | 613 | -35% | PASS | PASS |
| drawings_gallery | 935 | 189 | -80% | PASS | PASS |
| illuminance_new | 883 | 288 | -67% | PASS | PASS |
| dashboard | 881 | 292 | -67% | PASS | PASS |
| quotation_create | 764 | 266 | -65% | PASS | PASS |
| production | 738 | 226 | -69% | PASS | PASS |

## Phase 4: 대형 Route 서비스 분리 — 100%

| Route | 목표 | 실제 | 서비스 파일 | 달성 |
|-------|:----:|:----:|:----------:|:----:|
| bom.py | <=500 | 408 | bom_actions.py (676줄) | PASS |
| inventory.py | <=500 | 472 | inventory_actions.py (565줄) | PASS |
| production.py | <=500 | 364 | production_actions.py (1,026줄) | PASS |

---

## 결론

Iteration 1에서 7건 Gap(미추출 템플릿 6개 + delivery JS)을 모두 해소하여 **Match Rate 100%** 달성. `/pdca report code-simplify-split` 진행 가능.
