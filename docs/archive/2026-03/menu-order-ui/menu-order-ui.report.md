# PDCA Completion Report: menu-order-ui

> 메뉴 순서 편집 UI + 제품목록 명칭 변경

## Executive Summary

### 1.1 Overview

| 항목 | 내용 |
|------|------|
| Feature | 메뉴 순서 편집 UI |
| 시작일 | 2026-03-28 |
| 완료일 | 2026-03-28 |
| 소요시간 | ~1시간 (단일 세션) |
| Match Rate | ~95% |

### 1.2 Results

| 항목 | 수치 |
|------|------|
| 수정 파일 | 2개 |
| 추가 코드 | ~250줄 (JS+HTML+CSS) |
| 기존 버그 수정 | 1건 (newExtraRw 미선언) |
| 신규 버그 | 0건 |

### 1.3 Value Delivered

| 관점 | 문제 | 해결 | 기능 UX 효과 | 핵심 가치 |
|------|------|------|-------------|----------|
| Problem | 메뉴 순서를 변경할 수단이 없었음. API와 DB 저장 로직은 존재했으나 편집 UI 부재 | 사용자관리 페이지에 "메뉴 순서" 탭 추가, 드래그&드롭+버튼 방식 순서 편집 | 관리자가 사이드바 메뉴 노출순서를 직관적으로 조정 가능 | 관리자 자율성 확보 — 업무 우선순위에 맞는 메뉴 배치 |

---

## 2. Implementation Summary

### 2.1 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `config.py:42` | MENU_REGISTRY catalog label: "제품카탈로그" → "제품목록" |
| `templates/partials/admin_menu_perms.html` | 메뉴 순서 편집 UI 전체 추가 + 기존 버그 수정 |

### 2.2 구현 상세

#### A. 모드 탭 (메뉴 권한 / 메뉴 순서)
- 기존 메뉴 권한 패널을 `gmPermsWrap`으로 래핑
- `gmOrderPanel`을 병렬 배치, 탭 버튼으로 전환
- 탭 전환 시 상태 독립 유지

#### B. 메뉴 순서 편집 패널
- **그룹 카드**: 각 부서 그룹을 카드로 표시, 그룹 간 드래그 이동 + ▲▼ 버튼
- **메뉴 아이템**: 그룹 내 메뉴를 리스트로 표시, 드래그 이동 + ▲▼ 버튼
- **번호 자동 갱신**: 이동 시마다 1, 2, 3... 리넘버링 + 그룹 카운트 갱신
- **드래그 시각 피드백**: CSS `.gm-drop-above` / `.gm-drop-below` 파란색 보더

#### C. 저장/초기화
- **저장**: 기존 `/admin/api/menu_order` POST API 재사용 (데이터 형식 동일)
- **초기화**: DELETE API로 DB에서 menu_order 삭제 → MENU_REGISTRY 기본 순서 복원
- **토스트 피드백**: "메뉴 순서가 저장되었습니다" + 버튼 색상 변환

#### D. 누락 메뉴 자동 보충
- `gmGetCurrentOrder()`에서 DB 저장 순서에 없는 메뉴를 원래 그룹에 추가
- `app.py:361-364`의 사이드바 잔여 메뉴 처리와 동일 패턴

#### E. 기존 버그 수정
- `gmSave()` 내 user 모드에서 `newExtraRw` 변수 미선언 → `const newExtraRw = {}` 추가

---

## 3. Verification

### 3.1 정합성 검증

| 검증 항목 | 결과 | 비고 |
|----------|------|------|
| JS→API 데이터 형식 | ✅ | `{groups: [...], "영업부": [...]}` 동일 |
| API→DB 저장 형식 | ✅ | DashboardSetting JSON 직렬화 |
| DB→사이드바 읽기 | ✅ | `app.py:349` 동일 형식 파싱 |
| HTML div 매칭 | ✅ | 62 open / 62 close |
| Jinja2 블록 매칭 | ✅ | 16 open / 16 close |
| CSRF 토큰 | ✅ | 기존 `GM_CSRF` 재사용 |
| 명칭 변경 전파 | ✅ | MENU_REGISTRY만 변경, 자동 반영 |

### 3.2 Edge Case 검증

| 시나리오 | 처리 |
|----------|------|
| DB에 menu_order 없음 | MENU_REGISTRY 기본 순서 사용 |
| DB에 신규 메뉴 누락 | 원래 그룹에 자동 추가 |
| 시스템 메뉴 (admin_only) | 순서 패널에서 제외 (configurable_menus 미포함) |
| 워크보드 common 메뉴 | 순서 편집 대상 아님 (COMMON_MENU_KEYS 제외) |
| 그룹 간 메뉴 이동 | API에서 GroupPermission 자동 이전 (기존 로직) |

### 3.3 주의사항

- 메뉴를 다른 그룹으로 드래그 이동하면 해당 그룹의 권한 설정도 자동 변경됨 (API 기존 동작)
- 순서 저장 후 사이드바 반영은 페이지 새로고침 필요

---

## 4. Key Decisions & Outcomes

| 결정 | 이유 | 결과 |
|------|------|------|
| 기존 API 재사용 | menu_order POST/DELETE API가 이미 완전히 구현됨 | 백엔드 변경 0줄 |
| HTML5 네이티브 드래그&드롭 | 외부 라이브러리 의존 없이 구현 | 경량, 추가 번들 불필요 |
| ▲▼ 버튼 병행 | 드래그가 불편한 환경 대비 | 접근성 향상 |
| 워크보드 common 제외 | dashboard/overview/daily_report는 항상 고정 | 혼란 방지 |
| 인라인 CSS/JS | 기존 admin_menu_perms.html 패턴 유지 | 일관성 |

---

## 5. Files Changed

```
config.py                                    # 1줄 (label 변경)
templates/partials/admin_menu_perms.html     # ~260줄 추가 (UI+JS+CSS)
```
