# Sidebar Collapse Design

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | 250px 고정 사이드바가 테이블 가로폭을 잡아먹고, 20개+ 메뉴에서 자주 쓰는 3~5개 찾기 번거로움 |
| Solution | CSS transition 기반 접이식(250px↔60px) + localStorage 즐겨찾기. base.html 단일 파일 + config.py 아이콘 추가 |
| Function UX Effect | 접힘 시 190px 가로폭 확보, 즐겨찾기 1클릭 접근, 아이콘 호버로 플라이아웃 메뉴 |
| Core Value | 메뉴 확장에 강건한 네비게이션. 서버 변경 최소화(config.py 아이콘만), 나머지 전부 프론트엔드 |

> Plan 참조: `docs/01-plan/features/sidebar-collapse.plan.md`

---

## 1. Architecture Overview

### 1.1 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `config.py` | 수정 | MENU_REGISTRY 그룹에 대응하는 GROUP_ICONS dict 추가 |
| `app.py` | 수정 | context_processor에서 GROUP_ICONS를 템플릿에 전달 |
| `templates/base.html` | 수정 | 사이드바 HTML 구조 + CSS + JS 전면 개편 |

### 1.2 변경하지 않는 것

- MENU_REGISTRY 구조 (key/label/group/endpoint) — 그대로
- COMMON_MENU_KEYS — 그대로
- DEFAULT_GROUP_MENUS — 그대로
- 각 페이지 템플릿 — 변경 없음
- routes/*.py — 변경 없음
- DB 모델 — 변경 없음

---

## 2. Detailed Design

### 2.1 config.py — GROUP_ICONS 추가

```python
# MENU_REGISTRY 아래에 추가
GROUP_ICONS = {
    "공통":   "📊",
    "영업부": "💼",
    "관리부": "📋",
    "공유":   "🔗",
    "생산부": "🏭",
    "시스템": "⚙️",
}
```

- MENU_REGISTRY 자체는 건드리지 않음
- 별도 dict로 그룹명 → 아이콘 매핑

### 2.2 app.py — context_processor 수정

```python
# 기존 inject_sidebar_menus 함수 내 return 부분
from config import GROUP_ICONS

return {
    "sidebar_menu_groups": menu_groups,
    "sidebar_group_icons": GROUP_ICONS,  # 추가
    "is_admin": is_admin,
}
```

### 2.3 base.html — HTML 구조

#### 2.3.1 사이드바 전체 구조

```html
<div class="sidebar" id="sidebar">
    <!-- 브랜드 (펼침: 텍스트, 접힘: 아이콘) -->
    <a href="/dashboard" class="sidebar-brand">
        <span class="sidebar-label"><h4>⚡ Light-Sync</h4></span>
        <span class="sidebar-icon-only">⚡</span>
    </a>

    <!-- 유저 정보 (펼침에서만 표시) -->
    <div class="sidebar-user sidebar-label">
        <small>{{ session.user_group }}</small><br>
        <strong>👤 {{ session.full_name }}</strong> 님
        ...로그아웃/비번변경 버튼...
    </div>
    <hr class="sidebar-label" style="border-color:#334155;">

    <!-- 즐겨찾기 그룹 (JS로 동적 렌더링) -->
    <div class="sidebar-group" id="favGroup" style="display:none;">
        <div class="sidebar-group-header" data-group-id="fav">
            <span class="sidebar-icon">⭐</span>
            <span class="sidebar-label">즐겨찾기</span>
        </div>
        <div class="sidebar-sub sidebar-flyout" id="favSub">
            <!-- JS가 채움 -->
        </div>
    </div>

    <!-- 공통 메뉴: 현황 -->
    <div class="sidebar-group">
        <div class="sidebar-group-header" data-group-id="common">
            <span class="sidebar-icon">📊</span>
            <span class="sidebar-label">현황</span>
        </div>
        <div class="sidebar-sub sidebar-flyout" id="menu-grp-common">
            <a href="{{ url_for('dashboard.dashboard_view') }}"
               data-menu-key="dashboard" data-menu-label="메인 현황판">
                <span class="sidebar-label">메인 현황판</span>
                <span class="fav-toggle sidebar-label" title="즐겨찾기">☆</span>
            </a>
            <a href="{{ url_for('overview.project_overview') }}"
               data-menu-key="overview" data-menu-label="종합현황">
                <span class="sidebar-label">종합현황</span>
                <span class="fav-toggle sidebar-label" title="즐겨찾기">☆</span>
            </a>
        </div>
    </div>

    <!-- 공통 메뉴: 업무보고 -->
    <div class="sidebar-group">
        <div class="sidebar-group-header" data-group-id="report">
            <span class="sidebar-icon">📝</span>
            <span class="sidebar-label">업무보고</span>
        </div>
        <div class="sidebar-sub sidebar-flyout" id="menu-grp-report">
            <a href="{{ url_for('daily_report.daily_report_view') }}"
               data-menu-key="daily_report" data-menu-label="일일보고">
                <span class="sidebar-label">일일보고</span>
                <span class="fav-toggle sidebar-label" title="즐겨찾기">☆</span>
            </a>
            <a href="{{ url_for('report.weekly_report') }}"
               data-menu-key="weekly_report" data-menu-label="주간보고">
                <span class="sidebar-label">주간보고</span>
                <span class="fav-toggle sidebar-label" title="즐겨찾기">☆</span>
            </a>
        </div>
    </div>

    <!-- 동적 그룹 (Jinja 루프) -->
    {% for group_name, menus in (sidebar_menu_groups or {}).items() %}
    {% if group_name != '시스템' and menus %}
    <div class="sidebar-group">
        <div class="sidebar-group-header" data-group-id="grp-{{ loop.index }}">
            <span class="sidebar-icon">{{ sidebar_group_icons.get(group_name, '📁') }}</span>
            <span class="sidebar-label">{{ group_name }}</span>
        </div>
        <div class="sidebar-sub sidebar-flyout" id="menu-grp-{{ loop.index }}">
            {% for m in menus %}
            <a href="{{ m.url }}" data-menu-key="{{ m.key }}" data-menu-label="{{ m.label }}">
                <span class="sidebar-label">{{ m.label }}</span>
                <span class="fav-toggle sidebar-label" title="즐겨찾기">☆</span>
            </a>
            {% endfor %}
        </div>
    </div>
    {% endif %}
    {% endfor %}

    <!-- 시스템 (admin) -->
    {% if is_admin %}
    <hr class="sidebar-label" style="border-color:#334155; margin:8px 15px;">
    <div class="sidebar-group">
        <div class="sidebar-group-header" data-group-id="system">
            <span class="sidebar-icon">⚙️</span>
            <span class="sidebar-label">시스템</span>
        </div>
        <div class="sidebar-sub sidebar-flyout" id="menu-grp-system">
            <a href="{{ url_for('auth.admin_settings') }}"
               data-menu-key="admin_settings" data-menu-label="시스템관리">
                <span class="sidebar-label">시스템관리</span>
            </a>
        </div>
    </div>
    {% endif %}

    <!-- 토글 버튼 (하단 고정) -->
    <div class="sidebar-toggle-area">
        <button id="sidebarToggleBtn" class="sidebar-toggle-btn" title="사이드바 접기/펼치기">
            <span class="toggle-icon">◀</span>
        </button>
    </div>
</div>
```

**핵심 변경점:**
- 모든 텍스트에 `.sidebar-label` 클래스 → 접힘 시 `display:none`
- 모든 그룹에 `.sidebar-icon` 스팬 → 접힘 시 아이콘만 표시
- `.sidebar-group-header`가 기존 `.sidebar-group-toggle` 대체
- 메뉴 링크에 `data-menu-key`, `data-menu-label` 속성 → 즐겨찾기용
- `.fav-toggle` 스팬 → 즐겨찾기 별표 토글
- `.sidebar-flyout` 클래스 → 접힘 상태 플라이아웃용

#### 2.3.2 CSS

```css
/* === 사이드바 기본 === */
.sidebar {
    height: 100vh;
    background-color: #0f172a;
    color: white;
    padding-top: 20px;
    position: fixed;
    width: 250px;
    transition: width 0.2s ease;
    overflow-x: hidden;
    overflow-y: auto;
    z-index: 1050;
    display: flex;
    flex-direction: column;
}
.sidebar a {
    color: #cbd5e1;
    text-decoration: none;
    padding: 10px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-radius: 5px;
    margin: 2px 10px;
    white-space: nowrap;
}
.sidebar a:hover { background-color: #1e293b; color: white; }

/* 아이콘 / 라벨 */
.sidebar-icon {
    font-size: 1.2rem;
    min-width: 28px;
    text-align: center;
    flex-shrink: 0;
}
.sidebar-icon-only { display: none; }
.sidebar-label { transition: opacity 0.2s ease; }

/* 그룹 헤더 */
.sidebar-group { margin: 2px 0; position: relative; }
.sidebar-group-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    cursor: pointer;
    color: #cbd5e1;
    border-radius: 5px;
    margin: 2px 10px;
}
.sidebar-group-header:hover { background-color: #1e293b; color: white; }
.sidebar-group-header.open { color: #60a5fa; }
.sidebar-sub { display: none; }
.sidebar-sub.open { display: block; }
.sidebar-sub a { padding-left: 48px; }

/* 즐겨찾기 별표 */
.fav-toggle {
    cursor: pointer;
    font-size: 0.8rem;
    opacity: 0.4;
    transition: opacity 0.15s;
    flex-shrink: 0;
    padding: 2px 4px;
}
.fav-toggle:hover { opacity: 1; }
.fav-toggle.active { opacity: 1; color: #fbbf24; }

/* 토글 버튼 영역 (하단 고정) */
.sidebar-toggle-area {
    margin-top: auto;
    padding: 10px;
    border-top: 1px solid #334155;
}
.sidebar-toggle-btn {
    width: 100%;
    background: #1e293b;
    color: #94a3b8;
    border: none;
    border-radius: 5px;
    padding: 8px;
    cursor: pointer;
    font-size: 0.9rem;
}
.sidebar-toggle-btn:hover { background: #334155; color: white; }

/* main-content */
.main-content {
    margin-left: 250px;
    padding: 30px;
    transition: margin-left 0.2s ease;
    min-width: 0;
}

/* === 접힘 상태 === */
.sidebar.collapsed { width: 60px; }
.sidebar.collapsed .sidebar-label { display: none; }
.sidebar.collapsed .sidebar-icon-only { display: block; text-align: center; }
.sidebar.collapsed .sidebar-user { display: none; }
.sidebar.collapsed .sidebar-brand h4 { display: none; }

.sidebar.collapsed .sidebar-group-header {
    justify-content: center;
    padding: 10px 0;
    margin: 2px 5px;
}
.sidebar.collapsed .sidebar-sub { display: none !important; }
.sidebar.collapsed .sidebar-toggle-btn .toggle-icon { transform: rotate(180deg); }

.sidebar.collapsed + .main-content,
.main-content.shifted { margin-left: 60px; }

/* === 플라이아웃 (접힘 상태 호버) === */
.sidebar.collapsed .sidebar-group:hover > .sidebar-flyout {
    display: block !important;
    position: fixed;
    left: 60px;
    background: #1e293b;
    border-radius: 0 8px 8px 0;
    padding: 8px 0;
    min-width: 180px;
    box-shadow: 4px 4px 12px rgba(0,0,0,0.3);
    z-index: 1060;
}
.sidebar.collapsed .sidebar-flyout a {
    padding: 8px 16px !important;
    margin: 0;
}
.sidebar.collapsed .sidebar-flyout .sidebar-label { display: inline !important; }
.sidebar.collapsed .sidebar-flyout .fav-toggle { display: none; }

/* === 모바일: 접힘 무시, 기존 방식 유지 === */
@media (max-width: 991.98px) {
    .sidebar {
        width: 250px !important;
        transform: translateX(-100%);
        transition: transform 0.25s ease;
    }
    .sidebar.show { transform: translateX(0); }
    .sidebar.collapsed { width: 250px !important; }
    .sidebar.collapsed .sidebar-label { display: unset; }
    .sidebar.collapsed .sidebar-icon-only { display: none; }
    .sidebar.collapsed .sidebar-sub { display: revert !important; }
    .sidebar.collapsed .sidebar-user { display: block; }
    .sidebar-toggle-area { display: none; }
    .main-content { margin-left: 0 !important; }
}
```

#### 2.3.3 JavaScript

```javascript
// =========================================
// 1. 사이드바 접힘/펼침 토글
// =========================================
(function() {
    var sidebar = document.getElementById('sidebar');
    var toggleBtn = document.getElementById('sidebarToggleBtn');
    var mainContent = document.querySelector('.main-content');
    var COLLAPSE_KEY = 'sidebar_collapsed';

    if (!sidebar || !toggleBtn) return;

    // 페이지 로드 시 저장된 상태 복원
    if (localStorage.getItem(COLLAPSE_KEY) === '1') {
        sidebar.classList.add('collapsed');
        if (mainContent) mainContent.classList.add('shifted');
    }

    toggleBtn.addEventListener('click', function() {
        sidebar.classList.toggle('collapsed');
        if (mainContent) mainContent.classList.toggle('shifted');
        localStorage.setItem(COLLAPSE_KEY, sidebar.classList.contains('collapsed') ? '1' : '0');
    });
})();

// =========================================
// 2. 그룹 토글 (펼침 상태 아코디언)
// =========================================
(function() {
    var STORAGE_KEY = 'sidebar_open_groups';

    function getOpenGroups() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || []; }
        catch(e) { return []; }
    }
    function saveOpenGroups(arr) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
    }

    document.querySelectorAll('.sidebar-group-header').forEach(function(header) {
        var groupId = header.getAttribute('data-group-id');
        var sub = header.nextElementSibling;
        if (!sub || !sub.classList.contains('sidebar-sub')) return;

        header.addEventListener('click', function(e) {
            e.preventDefault();
            var sidebar = document.getElementById('sidebar');
            if (sidebar && sidebar.classList.contains('collapsed')) return; // 접힘 상태에서는 무시

            var isOpen = sub.classList.contains('open');
            // 전체 닫기
            document.querySelectorAll('.sidebar-sub').forEach(function(s) { s.classList.remove('open'); });
            document.querySelectorAll('.sidebar-group-header').forEach(function(h) { h.classList.remove('open'); });

            if (!isOpen) {
                sub.classList.add('open');
                header.classList.add('open');
                saveOpenGroups([groupId]);
            } else {
                saveOpenGroups([]);
            }
        });
    });

    // 페이지 로드 시 복원
    var openGroups = getOpenGroups();
    var currentPath = window.location.pathname;
    var restored = false;

    // 1순위: 현재 경로가 속한 그룹
    document.querySelectorAll('.sidebar-group-header').forEach(function(header) {
        var sub = header.nextElementSibling;
        if (!sub) return;
        sub.querySelectorAll('a').forEach(function(link) {
            if (link.getAttribute('href') === currentPath && !restored) {
                sub.classList.add('open');
                header.classList.add('open');
                restored = true;
            }
        });
    });
    // 2순위: 저장된 그룹
    if (!restored && openGroups.length > 0) {
        document.querySelectorAll('.sidebar-group-header').forEach(function(header) {
            if (openGroups.indexOf(header.getAttribute('data-group-id')) >= 0) {
                var sub = header.nextElementSibling;
                if (sub) { sub.classList.add('open'); header.classList.add('open'); }
            }
        });
    }
})();

// =========================================
// 3. 플라이아웃 위치 보정 (접힘 상태)
// =========================================
(function() {
    document.querySelectorAll('.sidebar-group').forEach(function(group) {
        group.addEventListener('mouseenter', function() {
            var sidebar = document.getElementById('sidebar');
            if (!sidebar || !sidebar.classList.contains('collapsed')) return;

            var flyout = group.querySelector('.sidebar-flyout');
            if (!flyout) return;

            // 그룹 헤더의 Y 좌표에 맞춰 플라이아웃 위치 조정
            var header = group.querySelector('.sidebar-group-header');
            if (header) {
                var rect = header.getBoundingClientRect();
                flyout.style.top = rect.top + 'px';
                // 화면 하단 넘침 방지
                var flyoutHeight = flyout.offsetHeight || 150;
                if (rect.top + flyoutHeight > window.innerHeight) {
                    flyout.style.top = Math.max(0, window.innerHeight - flyoutHeight - 10) + 'px';
                }
            }
        });
    });
})();

// =========================================
// 4. 즐겨찾기 기능
// =========================================
(function() {
    var FAV_KEY = 'sidebar_favorites';
    var MAX_FAVS = 8;

    function getFavs() {
        try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
        catch(e) { return []; }
    }
    function saveFavs(arr) {
        localStorage.setItem(FAV_KEY, JSON.stringify(arr));
    }

    // 즐겨찾기 그룹 렌더링
    function renderFavGroup() {
        var favs = getFavs();
        var favGroup = document.getElementById('favGroup');
        var favSub = document.getElementById('favSub');
        if (!favGroup || !favSub) return;

        favSub.innerHTML = '';
        if (favs.length === 0) {
            favGroup.style.display = 'none';
            return;
        }
        favGroup.style.display = '';

        favs.forEach(function(fav) {
            var a = document.createElement('a');
            a.href = fav.url;
            a.setAttribute('data-menu-key', fav.key);
            a.innerHTML = '<span class="sidebar-label">' + fav.label + '</span>';
            favSub.appendChild(a);
        });

        // 즐겨찾기 그룹은 항상 펼침
        favSub.classList.add('open');
        var header = favGroup.querySelector('.sidebar-group-header');
        if (header) header.classList.add('open');
    }

    // 별표 상태 동기화
    function syncStars() {
        var favs = getFavs();
        var favKeys = favs.map(function(f) { return f.key; });
        document.querySelectorAll('.fav-toggle').forEach(function(star) {
            var link = star.closest('a');
            if (!link) return;
            var key = link.getAttribute('data-menu-key');
            if (favKeys.indexOf(key) >= 0) {
                star.textContent = '★';
                star.classList.add('active');
            } else {
                star.textContent = '☆';
                star.classList.remove('active');
            }
        });
    }

    // 별표 클릭 이벤트
    document.querySelectorAll('.fav-toggle').forEach(function(star) {
        star.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            var link = star.closest('a');
            if (!link) return;
            var key = link.getAttribute('data-menu-key');
            var label = link.getAttribute('data-menu-label');
            var url = link.getAttribute('href');
            var favs = getFavs();
            var idx = favs.findIndex(function(f) { return f.key === key; });

            if (idx >= 0) {
                // 제거
                favs.splice(idx, 1);
            } else {
                // 추가 (최대 제한)
                if (favs.length >= MAX_FAVS) {
                    alert('즐겨찾기는 최대 ' + MAX_FAVS + '개까지 가능합니다.');
                    return;
                }
                favs.push({ key: key, label: label, url: url });
            }
            saveFavs(favs);
            syncStars();
            renderFavGroup();
        });
    });

    // 초기화
    renderFavGroup();
    syncStars();
})();
```

---

## 3. 상태 관리 (localStorage)

| Key | 타입 | 예시 | 용도 |
|-----|------|------|------|
| `sidebar_collapsed` | `"0"` / `"1"` | `"1"` | 접힘 상태 |
| `sidebar_open_groups` | JSON 배열 | `["grp-2"]` | 펼침 상태에서 열린 그룹 |
| `sidebar_favorites` | JSON 배열 | `[{"key":"production","label":"생산관리","url":"/production"}]` | 즐겨찾기 목록 |

기존 `sidebar_last_group` 키는 더 이상 사용하지 않음 (하위 호환: 남아있어도 무해).

---

## 4. 동작 시나리오

### 4.1 펼침 상태 (기본)

```
┌─────────────────────┐
│ ⚡ Light-Sync       │
│ 관리부              │
│ 👤 홍길동 님 🔔     │
│ [로그아웃] [비번변경]│
│─────────────────────│
│ ⭐ 즐겨찾기         │  ← 즐겨찾기 있으면 표시
│   품목관리          │
│   발주관리          │
│─────────────────────│
│ 📊 현황             │  ← 클릭하면 아코디언 펼침
│ 📝 업무보고         │
│ 💼 영업부 ▴        │  ← 현재 열린 그룹
│   설계관리      ☆   │
│   계약관리      ★   │  ← 즐겨찾기 등록됨
│   영업관리      ☆   │
│   납품관리      ☆   │
│ 📋 관리부           │
│ 🔗 공유             │
│ 🏭 생산부           │
│─────────────────────│
│      [ ◀ 접기 ]     │  ← 토글 버튼
└─────────────────────┘
```

### 4.2 접힘 상태

```
┌────┐
│ ⚡ │
│────│
│ ⭐ │ ← 호버 시 플라이아웃
│ 📊 │
│ 📝 │
│ 💼 │ ← 호버 →  ┌──────────┐
│ 📋 │           │ 설계관리  │
│ 🔗 │           │ 계약관리  │
│ 🏭 │           │ 영업관리  │
│ ⚙️ │           │ 납품관리  │
│────│           └──────────┘
│ ▶  │
└────┘
```

### 4.3 모바일 (<992px)

기존과 동일:
- 사이드바 숨김, 햄버거(☰) 버튼으로 슬라이드
- collapsed 클래스 무시, 항상 250px 풀 모드로 표시
- 토글 버튼 숨김

---

## 5. Implementation Order

| # | 작업 | 파일 | 의존 |
|---|------|------|------|
| 1 | config.py에 GROUP_ICONS dict 추가 | `config.py` | - |
| 2 | app.py context_processor에 GROUP_ICONS 전달 | `app.py` | #1 |
| 3 | base.html 사이드바 HTML 구조 변경 | `base.html` | #2 |
| 4 | base.html CSS 추가 (접이식 + 플라이아웃 + 즐겨찾기) | `base.html` | #3 |
| 5 | base.html JS: 토글 + localStorage | `base.html` | #4 |
| 6 | base.html JS: 그룹 아코디언 (기존 로직 교체) | `base.html` | #5 |
| 7 | base.html JS: 플라이아웃 위치 보정 | `base.html` | #5 |
| 8 | base.html JS: 즐겨찾기 기능 | `base.html` | #5 |
| 9 | 모바일 호환 검증 | `base.html` | #4 |

---

## 6. Edge Cases

| 케이스 | 처리 |
|--------|------|
| 즐겨찾기 0개 | 즐겨찾기 그룹 `display:none` |
| 즐겨찾기 메뉴가 권한 변경으로 사라짐 | 렌더링 시 href가 404면 무시 (현 단계 허용, localStorage 정리는 향후) |
| 접힘 상태에서 브라우저 리사이즈 → 모바일 | CSS media query가 강제로 250px 복원 |
| 플라이아웃이 화면 하단 넘침 | JS로 top 위치 보정 (window.innerHeight 기준) |
| localStorage 비활성 | 기본값 사용 (펼침 상태, 즐겨찾기 없음) |
| 기존 `sidebar_last_group` 키 | 무시됨, 충돌 없음 |

---

## 7. Migration Notes

- 기존 사이드바 CSS/JS를 **전면 교체** (부분 패치 불가 — 구조가 다름)
- 기존 `.sidebar-group-toggle` → `.sidebar-group-header`로 변경
- 기존 그룹 토글 JS (closeAllGroups, openGroup) → 새 로직으로 교체
- `sidebar_last_group` localStorage → `sidebar_open_groups`로 마이그레이션 불필요 (새 키)
