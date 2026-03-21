/* ═══ 사이드바 접이식 + 그룹 토글 + 플라이아웃 + 즐겨찾기 ═══ */
(function() {
    var sidebar = document.getElementById('sidebar');
    var toggleBtn = document.getElementById('sidebarToggleBtn');
    var flyout = document.getElementById('flyoutPopup');
    var COLLAPSE_KEY = 'sidebar_collapsed';
    var GROUP_KEY = 'sidebar_open_groups';
    var FAV_KEY = 'sidebar_favorites';
    var MAX_FAVS = 8;
    var flyoutTimer = null;

    if (!sidebar) return;

    /* --- 1. 접힘/펼침 토글 --- */
    function isCollapsed() { return sidebar.classList.contains('collapsed'); }

    var mainContent = document.querySelector('.main-content');

    function applyCollapsed(collapsed) {
        sidebar.classList.toggle('collapsed', collapsed);
        if (mainContent) mainContent.classList.toggle('sidebar-collapsed', collapsed);
        document.documentElement.classList.toggle('sb-collapsed', collapsed);
        var icon = toggleBtn ? toggleBtn.querySelector('.toggle-icon') : null;
        var label = toggleBtn ? toggleBtn.querySelector('.toggle-label') : null;
        if (icon) icon.textContent = collapsed ? '\u25B6' : '\u25C0';
        if (label) label.textContent = collapsed ? '' : '접기';
    }

    // 페이지 로드: html.sb-collapsed가 CSS로 이미 처리했으므로 JS 클래스만 동기화
    if (document.documentElement.classList.contains('sb-collapsed')) {
        sidebar.classList.add('collapsed');
        if (mainContent) mainContent.classList.add('sidebar-collapsed');
    }
    // DOM 렌더 후 transition 활성화
    requestAnimationFrame(function() {
        requestAnimationFrame(function() {
            sidebar.classList.add('animated');
            if (mainContent) mainContent.classList.add('animated');
        });
    });
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            var next = !isCollapsed();
            applyCollapsed(next);
            localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
        });
    }

    /* --- 2. 그룹 아코디언 (펼침 상태) --- */
    function getOpenGroups() {
        try { return JSON.parse(localStorage.getItem(GROUP_KEY)) || []; } catch(e) { return []; }
    }

    document.querySelectorAll('.sidebar-group-header').forEach(function(header) {
        var groupId = header.getAttribute('data-group-id');
        if (groupId === 'fav') return; // 즐겨찾기는 항상 펼침
        var sub = header.nextElementSibling;
        if (!sub || !sub.classList.contains('sidebar-sub')) return;

        header.addEventListener('click', function(e) {
            e.preventDefault();
            if (isCollapsed()) return;
            var isOpen = sub.classList.contains('open');
            // 전체 닫기 (즐겨찾기 제외)
            document.querySelectorAll('.sidebar-group-header').forEach(function(h) {
                if (h.getAttribute('data-group-id') === 'fav') return;
                h.classList.remove('open');
                var s = h.nextElementSibling;
                if (s) s.classList.remove('open');
            });
            if (!isOpen) {
                sub.classList.add('open');
                header.classList.add('open');
                localStorage.setItem(GROUP_KEY, JSON.stringify([groupId]));
            } else {
                localStorage.setItem(GROUP_KEY, '[]');
            }
        });
    });

    // 페이지 로드 시 그룹 복원
    (function() {
        var currentPath = window.location.pathname;
        var restored = false;
        // 1순위: 현재 경로가 속한 그룹
        document.querySelectorAll('.sidebar-group-header').forEach(function(header) {
            if (restored || header.getAttribute('data-group-id') === 'fav') return;
            var sub = header.nextElementSibling;
            if (!sub) return;
            sub.querySelectorAll('a[href]').forEach(function(link) {
                if (!restored && link.getAttribute('href') === currentPath) {
                    sub.classList.add('open'); header.classList.add('open'); restored = true;
                    localStorage.setItem(GROUP_KEY, JSON.stringify([header.getAttribute('data-group-id')]));
                }
            });
        });
        // 2순위: 저장된 그룹
        if (!restored) {
            var saved = getOpenGroups();
            if (saved.length > 0) {
                document.querySelectorAll('.sidebar-group-header').forEach(function(header) {
                    if (saved.indexOf(header.getAttribute('data-group-id')) >= 0) {
                        var sub = header.nextElementSibling;
                        if (sub) { sub.classList.add('open'); header.classList.add('open'); }
                    }
                });
            }
        }
    })();

    /* --- 3. 플라이아웃 (접힘 상태 호버) --- */
    function showFlyout(group) {
        if (!flyout || !isCollapsed()) return;
        var header = group.querySelector('.sidebar-group-header');
        var sub = group.querySelector('.sidebar-sub');
        if (!header || !sub) return;

        var title = header.querySelector('.sidebar-label');
        var titleText = title ? title.textContent.trim() : '';
        var links = sub.querySelectorAll('a[href]');
        if (links.length === 0) return;

        var html = '<div class="flyout-title">' + titleText + '</div>';
        links.forEach(function(a) {
            html += '<a href="' + a.getAttribute('href') + '">' + (a.getAttribute('data-menu-label') || a.textContent.trim()) + '</a>';
        });
        flyout.innerHTML = html;

        var rect = header.getBoundingClientRect();
        flyout.style.top = rect.top + 'px';
        flyout.classList.add('show');

        // 하단 넘침 보정
        requestAnimationFrame(function() {
            var fh = flyout.offsetHeight;
            if (rect.top + fh > window.innerHeight) {
                flyout.style.top = Math.max(0, window.innerHeight - fh - 8) + 'px';
            }
        });
    }

    function hideFlyout() {
        if (flyout) { flyout.classList.remove('show'); flyout.innerHTML = ''; }
    }

    document.querySelectorAll('.sidebar-group').forEach(function(group) {
        group.addEventListener('mouseenter', function() {
            clearTimeout(flyoutTimer);
            showFlyout(group);
        });
        group.addEventListener('mouseleave', function() {
            flyoutTimer = setTimeout(hideFlyout, 100);
        });
    });
    if (flyout) {
        flyout.addEventListener('mouseenter', function() { clearTimeout(flyoutTimer); });
        flyout.addEventListener('mouseleave', function() { flyoutTimer = setTimeout(hideFlyout, 100); });
    }

    /* --- 4. 즐겨찾기 --- */
    function getFavs() {
        try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; } catch(e) { return []; }
    }
    function saveFavs(arr) { localStorage.setItem(FAV_KEY, JSON.stringify(arr)); }

    function renderFavGroup() {
        var favs = getFavs();
        var favGroup = document.getElementById('favGroup');
        var favSub = document.getElementById('favSub');
        if (!favGroup || !favSub) return;
        favSub.innerHTML = '';
        if (favs.length === 0) { favGroup.style.display = 'none'; return; }
        favGroup.style.display = '';
        favs.forEach(function(fav) {
            var a = document.createElement('a');
            a.href = fav.url;
            a.setAttribute('data-menu-key', fav.key);
            a.setAttribute('data-menu-label', fav.label);
            a.innerHTML = '<span class="sidebar-label">' + fav.label + '</span>';
            favSub.appendChild(a);
        });
    }

    function syncStars() {
        var favs = getFavs();
        var favKeys = favs.map(function(f) { return f.key; });
        document.querySelectorAll('.fav-toggle').forEach(function(star) {
            var link = star.closest('a');
            if (!link) return;
            var key = link.getAttribute('data-menu-key');
            if (favKeys.indexOf(key) >= 0) {
                star.textContent = '\u2605'; star.classList.add('active');
            } else {
                star.textContent = '\u2606'; star.classList.remove('active');
            }
        });
    }

    document.querySelectorAll('.fav-toggle').forEach(function(star) {
        star.addEventListener('click', function(e) {
            e.preventDefault(); e.stopPropagation();
            var link = star.closest('a');
            if (!link) return;
            var key = link.getAttribute('data-menu-key');
            var label = link.getAttribute('data-menu-label');
            var url = link.getAttribute('href');
            if (!key) return;
            var favs = getFavs();
            var idx = -1;
            favs.forEach(function(f, i) { if (f.key === key) idx = i; });
            if (idx >= 0) {
                favs.splice(idx, 1);
            } else {
                if (favs.length >= MAX_FAVS) { alert('즐겨찾기는 최대 ' + MAX_FAVS + '개까지 가능합니다.'); return; }
                favs.push({ key: key, label: label, url: url });
            }
            saveFavs(favs);
            syncStars();
            renderFavGroup();
        });
    });

    renderFavGroup();
    syncStars();
})();
