# Design: 조직도 기반 부서별 권한 관리

> Plan 참조: `docs/01-plan/features/dept-permission.plan.md`

---

## 1. 데이터 설계

### 1.1 기존 모델 (변경 없음)

```python
# entities.py - GroupPermission (그대로 활용)
class GroupPermission(Base):
    __tablename__ = 'group_permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(50), unique=True, nullable=False)
    allowed_menus = Column(Text, nullable=False)  # CSV: "project,contract,sales,..."
```

- `allowed_menus`에 저장되는 값을 한글 메뉴명 → **메뉴 키** 로 변환
- 기존 CSV 형식 유지, 값만 변경

### 1.2 MENU_REGISTRY 정의 (`config.py`)

```python
from collections import OrderedDict

MENU_REGISTRY = OrderedDict([
    # --- 공통 (권한 체크 없이 항상 표시) ---
    ("dashboard",      {"label": "메인 현황판", "group": "공통",   "endpoint": "dashboard.dashboard_view"}),
    ("overview",       {"label": "종합현황",   "group": "공통",   "endpoint": "overview.project_overview"}),
    ("daily_report",   {"label": "업무보고",   "group": "공통",   "endpoint": "daily_report.daily_report_view"}),
    # --- 영업부 ---
    ("project",        {"label": "설계관리",   "group": "영업부", "endpoint": "project.project_list"}),
    ("contract",       {"label": "계약관리",   "group": "영업부", "endpoint": "project.contract_list"}),
    ("sales",          {"label": "영업관리",   "group": "영업부", "endpoint": "sales.sales_list"}),
    ("delivery",       {"label": "납품관리",   "group": "영업부", "endpoint": "delivery.delivery_management"}),
    # --- 관리부 ---
    ("item",           {"label": "품목관리",   "group": "관리부", "endpoint": "item.item_list"}),
    ("material",       {"label": "자재관리",   "group": "관리부", "endpoint": "material.material_management"}),
    ("vendor",         {"label": "거래처관리", "group": "관리부", "endpoint": "vendor.vendor_list"}),
    ("purchase_order", {"label": "발주관리",   "group": "관리부", "endpoint": "purchase_order.po_list"}),
    ("receiving",      {"label": "입고관리",   "group": "관리부", "endpoint": "receiving.receiving_list"}),
    ("bom",            {"label": "BOM관리",   "group": "관리부", "endpoint": "bom.bom_list"}),
    # --- 공유 (여러 부서 공통) ---
    ("procurement",    {"label": "조달내역",   "group": "공유",   "endpoint": "procurement.procurement_list"}),
    ("warranty",       {"label": "하자관리",   "group": "공유",   "endpoint": "warranty.warranty_list"}),
    # --- 생산부 ---
    ("production",     {"label": "생산관리",   "group": "생산부", "endpoint": "production.production_management"}),
    # --- 시스템 (admin only, MENU_REGISTRY에는 포함하되 admin 전용 플래그) ---
    ("admin_settings", {"label": "시스템관리", "group": "시스템", "endpoint": "auth.admin_settings", "admin_only": True}),
])

# 공통 메뉴 키 (권한 체크 제외)
COMMON_MENU_KEYS = {"dashboard", "overview", "daily_report"}
```

---

## 2. 백엔드 설계

### 2.1 context_processor — 사이드바 메뉴 데이터 주입 (`app.py`)

```python
from config import MENU_REGISTRY, COMMON_MENU_KEYS

@app.context_processor
def inject_sidebar_menus():
    """세션의 allowed_menus 기반으로 사이드바 메뉴 그룹 데이터 생성"""
    if 'user_id' not in session:
        return {}

    is_admin = session.get('role') == 'admin'
    allowed = set(session.get('allowed_menus', []))

    # 그룹별 메뉴 빌드 (OrderedDict 순서 유지)
    menu_groups = {}  # {"영업부": [{"key": "project", "label": "설계관리", "url": "/project/list"}, ...]}
    for key, info in MENU_REGISTRY.items():
        group = info["group"]
        # 공통 메뉴는 별도 처리 (항상 표시)
        if key in COMMON_MENU_KEYS:
            continue
        # 시스템 메뉴는 admin만
        if info.get("admin_only") and not is_admin:
            continue
        # admin이면 전체 접근, 아니면 allowed 체크
        if is_admin or key in allowed:
            menu_groups.setdefault(group, []).append({
                "key": key,
                "label": info["label"],
                "url": url_for(info["endpoint"]),
            })

    return {
        "sidebar_menu_groups": menu_groups,
        "is_admin": is_admin,
    }
```

### 2.2 menu_required 데코레이터 (`modules/auth_decorators.py`)

```python
def menu_required(menu_key):
    """allowed_menus 세션 기반 라우트 접근 제어"""
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if session.get('role') == 'admin':
                return f(*args, **kwargs)
            allowed = session.get('allowed_menus', [])
            if menu_key in allowed:
                return f(*args, **kwargs)
            flash('접근 권한이 없습니다.', 'danger')
            return redirect(url_for('dashboard.dashboard_view'))
        return decorated
    return decorator
```

### 2.3 그룹 메뉴 권한 저장 API (`routes/auth.py`)

```python
@auth_bp.route('/admin/update_group_menus', methods=['POST'])
@admin_required
def update_group_menus():
    """그룹별 allowed_menus 업데이트"""
    group_name = request.form.get('group_name', '').strip()
    selected_menus = request.form.getlist('menus')  # 체크박스 다중 값

    with get_db() as db:
        group = db.query(GroupPermission).filter(
            GroupPermission.group_name == group_name
        ).first()
        if not group:
            flash('존재하지 않는 그룹입니다.', 'danger')
            return redirect(url_for('auth.admin_settings'))

        group.allowed_menus = ",".join(selected_menus)
        db.commit()
        flash(f'{group_name} 메뉴 권한이 업데이트되었습니다.', 'success')

    return redirect(url_for('auth.admin_settings'))
```

### 2.4 로그인 시 세션 저장 수정 (`routes/auth.py`)

```python
# 기존: allowed_menus를 CSV 문자열 split
group_data = db.query(GroupPermission).filter(
    GroupPermission.group_name == user.user_group
).first()
allowed_menus = group_data.allowed_menus.split(",") if group_data and group_data.allowed_menus else []

# 변경 없음 - 이미 CSV split으로 리스트 저장 중
# 단, 메뉴 키 형식으로 데이터가 들어가므로 자연스럽게 호환
```

### 2.5 admin_settings에 그룹 데이터 전달 (`routes/auth.py`)

```python
# admin_settings 함수 내 기존 코드에 추가
from config import MENU_REGISTRY, COMMON_MENU_KEYS

# 그룹 목록 + 각 그룹의 현재 allowed_menus
group_permissions = db.query(GroupPermission).all()
group_menu_data = []
for gp in group_permissions:
    current_menus = set(gp.allowed_menus.split(",")) if gp.allowed_menus else set()
    group_menu_data.append({
        "group_name": gp.group_name,
        "current_menus": current_menus,
    })

# 권한 설정 가능한 메뉴 목록 (공통/시스템 제외)
configurable_menus = [
    {"key": k, "label": v["label"], "group": v["group"]}
    for k, v in MENU_REGISTRY.items()
    if k not in COMMON_MENU_KEYS and not v.get("admin_only")
]

return render_template('admin_settings.html',
    # ... 기존 변수들 ...
    group_menu_data=group_menu_data,
    configurable_menus=configurable_menus,
)
```

---

## 3. 프론트엔드 설계

### 3.1 사이드바 (`templates/base.html`)

**교체 대상:** 라인 310~357 (부서별 하드코딩 블록)

```html
{# === 공통 메뉴 === #}
<a href="{{ url_for('dashboard.dashboard_view') }}">메인 현황판</a>
<a href="{{ url_for('overview.project_overview') }}">종합현황</a>
<a href="{{ url_for('daily_report.daily_report_view') }}">업무보고</a>

{# === 부서별 동적 메뉴 === #}
{% for group_name, menus in sidebar_menu_groups.items() %}
{% if group_name != '시스템' and menus %}
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

{% if is_admin %}
<hr style="border-color: #334155; margin: 8px 15px;">
<a href="{{ url_for('auth.admin_settings') }}">시스템관리</a>
{% endif %}
```

### 3.2 관리자 설정 - 그룹 메뉴 권한 탭 (`templates/admin_settings.html`)

기존 nav-tabs에 탭 추가:

```html
<!-- 탭 헤더에 추가 -->
<li class="nav-item">
    <a class="nav-link" data-bs-toggle="tab" href="#tab-group-menus">그룹 메뉴 권한</a>
</li>

<!-- 탭 콘텐츠 -->
<div class="tab-pane fade" id="tab-group-menus">
    <div class="card mt-3">
        <div class="card-header"><strong>부서별 메뉴 접근 권한 설정</strong></div>
        <div class="card-body">
            <!-- 그룹 선택 드롭다운 -->
            <select id="groupSelector" class="form-select mb-3" style="max-width:300px;">
                <option value="">그룹 선택...</option>
                {% for gd in group_menu_data %}
                <option value="{{ gd.group_name }}"
                        data-menus="{{ gd.current_menus | join(',') }}">
                    {{ gd.group_name }}
                </option>
                {% endfor %}
            </select>

            <!-- 메뉴 체크박스 폼 -->
            <form id="groupMenuForm" method="POST"
                  action="{{ url_for('auth.update_group_menus') }}" style="display:none;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="group_name" id="selectedGroupName">

                <div class="row">
                    {% for menu in configurable_menus %}
                    <div class="col-md-4 col-6 mb-2">
                        <div class="form-check">
                            <input class="form-check-input menu-checkbox"
                                   type="checkbox" name="menus"
                                   value="{{ menu.key }}" id="menu_{{ menu.key }}">
                            <label class="form-check-label" for="menu_{{ menu.key }}">
                                <small class="text-muted">[{{ menu.group }}]</small>
                                {{ menu.label }}
                            </label>
                        </div>
                    </div>
                    {% endfor %}
                </div>

                <div class="mt-3">
                    <button type="submit" class="btn btn-primary btn-sm">저장</button>
                    <button type="button" class="btn btn-outline-secondary btn-sm"
                            onclick="selectAllMenus()">전체 선택</button>
                    <button type="button" class="btn btn-outline-secondary btn-sm"
                            onclick="deselectAllMenus()">전체 해제</button>
                </div>
            </form>
        </div>
    </div>
</div>
```

**JavaScript:**

```javascript
document.getElementById('groupSelector').addEventListener('change', function() {
    const form = document.getElementById('groupMenuForm');
    const groupName = this.value;
    if (!groupName) { form.style.display = 'none'; return; }

    document.getElementById('selectedGroupName').value = groupName;
    form.style.display = 'block';

    // 현재 허용 메뉴 체크
    const currentMenus = this.selectedOptions[0].dataset.menus.split(',');
    document.querySelectorAll('.menu-checkbox').forEach(cb => {
        cb.checked = currentMenus.includes(cb.value);
    });
});

function selectAllMenus() {
    document.querySelectorAll('.menu-checkbox').forEach(cb => cb.checked = true);
}
function deselectAllMenus() {
    document.querySelectorAll('.menu-checkbox').forEach(cb => cb.checked = false);
}
```

---

## 4. 데이터 마이그레이션

### 4.1 기존 allowed_menus 값 → 메뉴 키 변환

현재 `GroupPermission.allowed_menus`에 한글 메뉴명이 저장되어 있을 수 있음.
마이그레이션 스크립트 또는 수동 변환 필요:

```python
# 한글→키 매핑 (1회성)
LEGACY_MAPPING = {
    "설계관리": "project", "계약관리": "contract", "영업관리": "sales",
    "납품관리": "delivery", "품목관리": "item", "자재관리": "material",
    "거래처관리": "vendor", "발주관리": "purchase_order", "입고관리": "receiving",
    "BOM관리": "bom", "조달내역": "procurement", "하자관리": "warranty",
    "생산관리": "production", "시스템관리": "admin_settings",
}
```

관리자가 시스템관리 > 그룹 메뉴 권한 탭에서 저장하면 자동으로 키 형식으로 전환되므로,
**마이그레이션 대신 관리자 직접 재설정** 방식 권장 (4개 그룹이므로 1분 소요).

---

## 5. 구현 순서

| 순서 | 작업 | 파일 | 의존성 |
|------|------|------|--------|
| 1 | MENU_REGISTRY + COMMON_MENU_KEYS 정의 | `config.py` | 없음 |
| 2 | context_processor 추가 | `app.py` | 1 |
| 3 | base.html 사이드바 동적 렌더링 교체 | `templates/base.html` | 2 |
| 4 | menu_required 데코레이터 추가 | `modules/auth_decorators.py` | 없음 |
| 5 | admin_settings에 그룹 메뉴 데이터 전달 | `routes/auth.py` | 1 |
| 6 | update_group_menus API 추가 | `routes/auth.py` | 1 |
| 7 | admin_settings.html 탭 추가 | `templates/admin_settings.html` | 5, 6 |

---

## 6. 검증 항목

| # | 검증 내용 | 예상 결과 |
|---|----------|----------|
| V1 | 영업부 사용자 로그인 → 사이드바 | 영업부 메뉴 + 공통 메뉴만 표시 |
| V2 | 관리부 사용자 로그인 → 사이드바 | 관리부 메뉴 + 공통 메뉴만 표시 |
| V3 | admin 로그인 → 사이드바 | 전체 메뉴 + 시스템관리 표시 |
| V4 | 영업부 사용자 → 품목관리 URL 직접 접근 | 403 또는 대시보드 리다이렉트 |
| V5 | admin → 그룹 메뉴 권한 탭 → 영업부 선택 | 현재 허용 메뉴 체크 표시 |
| V6 | 메뉴 체크 변경 → 저장 | GroupPermission.allowed_menus 업데이트 |
| V7 | 임원진 그룹 → 전체 메뉴 체크 | 모든 메뉴 접근 가능 |
