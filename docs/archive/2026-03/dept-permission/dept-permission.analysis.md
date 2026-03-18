# Analysis: dept-permission (조직도 기반 부서별 권한 관리)

> Design: `docs/02-design/features/dept-permission.design.md`
> 분석일: 2026-03-18

---

## Overall Match Rate: 91%

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 88% | ⚠️ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 95% | ✅ |
| **Overall** | **91%** | ✅ |

---

## Gap Summary

### Missing (Design O, Implementation X) — 2건

| # | 항목 | Impact | 설명 |
|---|------|--------|------|
| M1 | `menu_required` 라우트 미적용 | **HIGH** | 데코레이터 정의만 되어 있고, 부서별 라우트에 적용되지 않음. URL 직접 접근 차단 불가 |
| M2 | allowed_menus null 체크 누락 | Medium | `routes/auth.py` 로그인 시 `group_data.allowed_menus` 빈 문자열이면 `['']` 반환 |

### Added (Design X, Implementation O) — 4건

| # | 항목 | Impact | 설명 |
|---|------|--------|------|
| A1 | group_name 빈값 방어 | Low | 개선 사항 |
| A2 | admin emoji 키 추가 | Medium | `allowed_menus.append("👑 시스템 및 권한 관리")` — 불필요한 비표준 키 |
| A3 | 탭 설명 텍스트 | Low | UX 개선 |
| A4 | URL 해시 탭 복원 | Low | UX 개선 |

### Changed (Design != Implementation) — 4건 (cosmetic)

모두 비기능적 차이: data-target ID 명명, current_menus 타입(set vs list), 탭 HTML 요소, JS 메서드.

---

## 권장 조치 (우선순위)

1. **M1: `@menu_required` 적용** — Plan에서 "선택적"으로 명시했으나, 보안상 적용 권장
2. **A2: emoji 키 제거** — `routes/auth.py`의 `allowed_menus.append("👑 시스템 및 권한 관리")` 삭제 (admin은 데코레이터에서 bypass)
3. **M2: null 체크 보강** — `group_data.allowed_menus` 존재 여부 추가 체크

---

## 100% 매칭 항목

- `config.py` MENU_REGISTRY + COMMON_MENU_KEYS
- `app.py` context_processor inject_sidebar_menus
- `modules/auth_decorators.py` menu_required 데코레이터 (정의)
- `routes/auth.py` update_group_menus API
- `templates/admin_settings.html` 그룹 메뉴 권한 탭
- `templates/base.html` 동적 사이드바 렌더링
