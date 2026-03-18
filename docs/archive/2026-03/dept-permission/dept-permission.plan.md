# Plan: 조직도 기반 부서별 권한 관리

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | dept-permission (부서별 권한 및 메뉴 접근권한) |
| 작성일 | 2026-03-18 |
| 예상 규모 | Medium (모델 1파일 + 라우트 2파일 + 템플릿 2파일 수정) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 사이드바 메뉴가 `user_group` 하드코딩 기반이라 조직 변경 시 코드 수정 필요. GroupPermission의 `allowed_menus` 필드가 실제 메뉴 제어에 활용되지 않음 |
| **Solution** | GroupPermission 테이블 기반 동적 메뉴 권한 + 관리자 UI에서 부서별 메뉴 on/off |
| **Function UX Effect** | 관리자가 시스템관리에서 부서별 접근 가능 메뉴를 체크박스로 설정, 즉시 반영 |
| **Core Value** | 코드 수정 없이 조직 변경·메뉴 추가에 대응 가능한 유연한 권한 체계 |

---

## 1. 현황 분석

### 1.1 조직도

```
매그나텍
├── 임원진 (대표이사, 임원)
├── 관리부 (팀장 + 팀원)
├── 영업부 (팀장 + 팀원)
└── 생산부 (팀장)
     ├── 생산1팀 (팀원)
     └── 생산2팀 (팀원)
```

### 1.2 현재 권한 시스템

| 항목 | 현재 상태 | 문제점 |
|------|----------|--------|
| `GroupPermission` 테이블 | `group_name` + `allowed_menus`(CSV) | 로그인 시 세션에 저장되지만 실제 사이드바에서 미사용 |
| `base.html` 사이드바 | `{% if is_admin or grp == '영업부' %}` 하드코딩 | 부서 추가/변경 시 템플릿 수정 필요 |
| `User.role` | `admin` / `user` 2종 | 팀장·임원 등 중간 역할 없음 |
| `User.user_group` | GroupPermission FK | 부서 소속만 있고 직급 개념 없음 |

### 1.3 현재 메뉴 구조

| 메뉴 그룹 | 하위 메뉴 | 현재 접근 |
|-----------|----------|----------|
| 공통 | 메인 현황판, 종합현황, 업무보고 | 전체 |
| 영업부 | 설계관리, 계약관리, 영업관리, 납품관리, 조달내역, 하자관리 | admin, 영업부 |
| 관리부 | 품목관리, 자재관리, 거래처관리, 발주관리, 입고관리, BOM관리, 조달내역, 하자관리 | admin, 관리부 |
| 생산부 | 생산관리, 하자관리 | admin, 생산부 |
| 시스템관리 | 시스템관리 | admin only |

---

## 2. 구현 범위

### 2.1 GroupPermission 활용 정상화

**현재:** `allowed_menus` 컬럼이 있지만 사이드바에서 미사용 (하드코딩)
**변경:** `allowed_menus`를 실제 메뉴 제어에 활용

**메뉴 키 정의:**
```python
MENU_REGISTRY = {
    # 공통 (항상 표시)
    "dashboard": {"label": "메인 현황판", "group": "공통"},
    "overview": {"label": "종합현황", "group": "공통"},
    "daily_report": {"label": "업무보고", "group": "공통"},
    # 영업부
    "project": {"label": "설계관리", "group": "영업부"},
    "contract": {"label": "계약관리", "group": "영업부"},
    "sales": {"label": "영업관리", "group": "영업부"},
    "delivery": {"label": "납품관리", "group": "영업부"},
    # 관리부
    "item": {"label": "품목관리", "group": "관리부"},
    "material": {"label": "자재관리", "group": "관리부"},
    "vendor": {"label": "거래처관리", "group": "관리부"},
    "purchase_order": {"label": "발주관리", "group": "관리부"},
    "receiving": {"label": "입고관리", "group": "관리부"},
    "bom": {"label": "BOM관리", "group": "관리부"},
    # 공유 메뉴
    "procurement": {"label": "조달내역", "group": "공유"},
    "warranty": {"label": "하자관리", "group": "공유"},
    # 생산부
    "production": {"label": "생산관리", "group": "생산부"},
    # 시스템
    "admin_settings": {"label": "시스템관리", "group": "시스템"},
}
```

**`allowed_menus` 저장 형식:** 메뉴 키 CSV
- 예: `"project,contract,sales,delivery,procurement,warranty"`

### 2.2 사이드바 동적 렌더링 (`base.html`)

**변경 전:**
```html
{% if is_admin or grp == '영업부' %}
<div class="sidebar-group">
    <a href="#" class="sidebar-group-toggle">영업부 ▾</a>
    ...
{% endif %}
```

**변경 후:**
```html
{% for group_name, menus in sidebar_menu_groups.items() %}
{% if menus %}
<div class="sidebar-group">
    <a href="#" class="sidebar-group-toggle" data-target="menu-{{ loop.index }}">{{ group_name }} ▾</a>
    <div class="sidebar-sub" id="menu-{{ loop.index }}">
        {% for m in menus %}
        <a href="{{ m.url }}">{{ m.label }}</a>
        {% endfor %}
    </div>
</div>
{% endif %}
{% endfor %}
```

**메뉴 데이터 주입:** `app.py`의 `@app.context_processor`에서 세션의 `allowed_menus`와 `MENU_REGISTRY`를 조합하여 `sidebar_menu_groups` 전달

### 2.3 관리자 UI - 그룹별 메뉴 권한 설정 (`admin_settings.html`)

시스템관리 페이지에 **"그룹 메뉴 권한"** 탭 추가:

| UI 요소 | 내용 |
|---------|------|
| 그룹 선택 | 드롭다운: 영업부, 관리부, 생산부, 임원진 |
| 메뉴 체크박스 | MENU_REGISTRY 기반 전체 메뉴 목록, 현재 허용 메뉴 체크 표시 |
| 저장 버튼 | POST → GroupPermission.allowed_menus 업데이트 |

### 2.4 라우트 권한 체크 (선택적)

**현재:** 사이드바만 숨기고 URL 직접 접근은 차단 안 함
**추가:** 데코레이터로 라우트 레벨 권한 체크

```python
def menu_required(menu_key):
    """세션의 allowed_menus에 menu_key가 있는지 확인"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            allowed = session.get('allowed_menus', [])
            if session.get('role') == 'admin' or menu_key in allowed:
                return f(*args, **kwargs)
            abort(403)
        return wrapped
    return decorator
```

---

## 3. 수정 대상 파일

| 파일 | 변경 내용 | 규모 |
|------|----------|------|
| `modules/models/entities.py` | GroupPermission 모델은 유지 (이미 적절) | 없음 |
| `modules/auth_decorators.py` | `menu_required` 데코레이터 추가 | 소 |
| `app.py` | context_processor에 메뉴 데이터 주입 | 소 |
| `routes/auth.py` | 그룹 메뉴 권한 저장 API 추가 | 소 |
| `templates/base.html` | 사이드바 동적 렌더링으로 교체 | 중 |
| `templates/admin_settings.html` | 그룹 메뉴 권한 탭 추가 | 중 |

---

## 4. 구현 순서

1. `MENU_REGISTRY` 딕셔너리 정의 (app.py 또는 별도 config)
2. `app.py` context_processor에서 `sidebar_menu_groups` 생성 로직
3. `base.html` 사이드바 동적 렌더링 교체
4. `admin_settings.html`에 그룹 메뉴 권한 관리 탭 추가
5. `routes/auth.py`에 메뉴 권한 저장 API 추가
6. `menu_required` 데코레이터 추가 (선택)
7. 기존 GroupPermission 데이터 마이그레이션 (현재 메뉴를 키 형식으로 변환)

---

## 5. 제약 조건 및 참고사항

- **하위 호환:** 기존 `allowed_menus` CSV 형식 유지, 값만 메뉴 키로 변경
- **admin 역할:** admin은 모든 메뉴 자동 접근 (기존 로직 유지)
- **공통 메뉴:** 대시보드, 종합현황, 업무보고는 권한 체크 제외 (전체 접근)
- **세션 갱신:** 그룹 권한 변경 시 해당 그룹 사용자는 재로그인 필요 (세션 기반이므로)
- **임원진 그룹:** 기본적으로 전체 메뉴 접근 가능하도록 초기 설정
