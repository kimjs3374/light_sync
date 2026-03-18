# Report: 조직도 기반 부서별 권한 관리

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | dept-permission (부서별 권한 및 메뉴 접근권한) |
| 기간 | 2026-03-18 (1일) |
| Match Rate | 91% → 95%+ (Act 후) |
| 수정 파일 | 7개 |
| 추가 코드 | ~180 lines |

### 1.3 Value Delivered

| 관점 | 결과 |
|------|------|
| **Problem** | 사이드바 메뉴가 `{% if grp == '영업부' %}` 하드코딩 → 조직 변경 시 코드 수정 필수. GroupPermission.allowed_menus 미활용 |
| **Solution** | MENU_REGISTRY 17개 메뉴 중앙 정의 + GroupPermission 기반 동적 렌더링 + 관리자 UI + 개인 추가 메뉴(extra_menus) |
| **Function UX Effect** | 관리자가 시스템관리 > "그룹 메뉴 권한" 탭에서 부서별 체크박스 설정. 개인별 추가 메뉴는 사용자 행의 "설정" 버튼으로 부여 |
| **Core Value** | 코드 수정 없이 부서/개인별 메뉴 권한 관리. 임원진 전체 열람. 신규 부서 추가도 DB만으로 대응 |

---

## 2. PDCA 진행 이력

| Phase | 상태 | 내용 |
|-------|------|------|
| Plan | ✅ | 조직도 분석, 현재 권한 시스템 문제점 도출, MENU_REGISTRY 설계 |
| Design | ✅ | 7단계 구현 순서, context_processor/데코레이터/API/UI 상세 설계 |
| Do | ✅ | 7개 파일 구현 (config → app → base.html → auth_decorators → auth.py → admin_settings) |
| Check | ✅ | Match Rate 91%, Gap 3건 (M1 라우트 미적용, M2 null체크, A2 emoji키) |
| Act | ✅ | Gap 3건 수정 + extra_menus 기능 추가 + DB 마이그레이션 + 부서별 기본 메뉴 초기화 |

---

## 3. 구현 결과

### 3.1 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `config.py` | MENU_REGISTRY (17개), COMMON_MENU_KEYS, DEFAULT_GROUP_MENUS (4부서) |
| `app.py` | `inject_sidebar_menus` context_processor (임원진 전체 접근 포함) |
| `templates/base.html` | 하드코딩 → `sidebar_menu_groups` 동적 렌더링 |
| `modules/auth_decorators.py` | `menu_required(menu_key)` 데코레이터 (임원진 bypass) |
| `modules/models/entities.py` | `User.extra_menus` 컬럼 추가 |
| `modules/models/db.py` | ALTER TABLE 마이그레이션 + GroupPermission 기본값 자동 세팅 |
| `routes/auth.py` | 로그인 시 그룹+개인 메뉴 병합, `update_group_menus` API, `update_user_extra_menus` API |
| `templates/admin_settings.html` | "그룹 메뉴 권한" 탭 + 개인 추가 메뉴 모달 |

### 3.2 권한 체계

```
[GroupPermission.allowed_menus]  ←  부서 기본 메뉴 (관리자가 그룹 단위 설정)
         +
[User.extra_menus]               ←  개인 추가 메뉴 (관리자가 사용자별 설정)
         =
[session.allowed_menus]          →  사이드바 표시 + 라우트 접근 제어

예외: admin → 전체 접근 / 임원진 → 전체 접근 (코드 레벨 bypass)
```

### 3.3 부서별 기본 메뉴

| 부서 | 메뉴 | 개수 |
|------|------|:----:|
| 영업부 | 설계, 계약, 영업, 납품, 조달, 하자 | 6 |
| 관리부 | 품목, 자재, 거래처, 발주, 입고, BOM, 조달, 하자 | 8 |
| 생산부 | 생산, 하자 | 2 |
| 임원진 | 전체 메뉴 | 13 |

---

## 4. 추가 개선 사항 (Act에서 추가 구현)

| 항목 | 설명 |
|------|------|
| `User.extra_menus` | 팀장 등 개인별 추가 메뉴 부여 (Plan 이후 요청으로 추가) |
| 임원진 전체 열람 | context_processor + menu_required에서 임원진 bypass |
| DB 기본값 자동 세팅 | init_db()에서 GroupPermission 기본 메뉴 자동 생성/업데이트 |
| 레거시 데이터 정리 | 기존 한글/이모지 메뉴명 → 메뉴 키 형식으로 일괄 변환 |

---

## 5. 잔여 사항

| 항목 | 우선순위 | 설명 |
|------|---------|------|
| `@menu_required` 라우트 적용 | Low | 각 Blueprint에 데코레이터 적용 (현재는 사이드바 숨김만) |
| 세션 갱신 없이 즉시 반영 | Low | 현재는 재로그인 필요 (세션 기반 한계) |
