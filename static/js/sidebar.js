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
        // 토글 아이콘도 즉시 동기화 (접힌 상태 → ▶)
        var icon = toggleBtn ? toggleBtn.querySelector('.toggle-icon') : null;
        if (icon) icon.textContent = '\u25B6';
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

    // 페이지 로드 시 그룹 복원 + 메뉴 하이라이트
    (function() {
        var activeKey = window.__activeMenuKey || '';
        var restored = false;

        function activateLink(link) {
            link.classList.add('sidebar-active');
            var sub = link.closest('.sidebar-sub');
            var header = sub ? sub.previousElementSibling : null;
            if (sub && header && header.classList.contains('sidebar-group-header')) {
                sub.classList.add('open');
                header.classList.add('open');
                localStorage.setItem(GROUP_KEY, JSON.stringify([header.getAttribute('data-group-id')]));
            }
            restored = true;
        }

        // 1순위: 서버에서 내려준 active_menu_key로 매칭
        if (activeKey) {
            document.querySelectorAll('.sidebar-sub a[data-menu-key]').forEach(function(link) {
                if (restored) return;
                if (link.getAttribute('data-menu-key') === activeKey) activateLink(link);
            });
        }

        // 2순위: URL 정확히 일치
        if (!restored) {
            var currentPath = window.location.pathname;
            document.querySelectorAll('.sidebar-sub a[href]').forEach(function(link) {
                if (restored) return;
                if (link.getAttribute('href') === currentPath) activateLink(link);
            });
        }
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

    /* --- 5. 현재 메뉴 활성 표시 (대시보드 제외) --- */
    (function() {
        var currentPath = window.location.pathname;
        if (currentPath === '/' || currentPath === '/dashboard' || currentPath === '/dashboard/') return;

        // /contract_list → "contract" 같은 base prefix 추출
        function getBasePrefix(path) {
            // 경로에서 첫 세그먼트의 _list, _detail, _create, _import 등 suffix 제거
            var clean = path.replace(/^\//, '').split('/')[0];
            return clean.replace(/_(list|detail|create|edit|import|management|dashboard|view|form|register)$/, '');
        }

        var currentBase = getBasePrefix(currentPath);
        var bestMatch = null;
        var bestLen = 0;

        sidebar.querySelectorAll('a[href]').forEach(function(link) {
            var href = link.getAttribute('href');
            if (!href || href === '#' || href === '/' || href === '/dashboard' || href === '/dashboard/') return;

            var menuBase = getBasePrefix(href);

            // 정확 일치
            if (href === currentPath) {
                link.classList.add('sidebar-active');
                return;
            }
            // 하위 경로 일치
            if (href !== '/' && currentPath.indexOf(href) === 0) {
                link.classList.add('sidebar-active');
                return;
            }
            // base prefix 일치 (contract_list ↔ contract_detail/123)
            if (menuBase && currentBase === menuBase && menuBase.length > bestLen) {
                bestMatch = link;
                bestLen = menuBase.length;
            }
        });

        // prefix 매칭으로 찾은 경우
        if (bestMatch && !sidebar.querySelector('a.sidebar-active')) {
            bestMatch.classList.add('sidebar-active');
        }
    })();

    /* --- 6. 스크롤 시 상단 고정 페이지 바 + KPI + 시계 + 날씨 --- */
    (function() {
        var stickyBar = document.getElementById('pageStickyBar');
        var stickyTitle = document.getElementById('stickyTitle');
        if (!stickyBar || !stickyTitle) return;

        // 대시보드(메인)에서는 상단 바 비활성화
        var path = window.location.pathname;
        if (path === '/' || path === '/dashboard' || path === '/dashboard/') {
            stickyBar.style.display = 'none';
            return;
        }

        // 페이지 제목 감지: main-content 내 첫 h2 또는 h3
        var mainEl = document.querySelector('.main-content');
        var titleEl = mainEl && (mainEl.querySelector('h2') || mainEl.querySelector('h3'));
        if (!titleEl) { stickyBar.style.display = 'none'; return; }

        stickyTitle.textContent = titleEl.textContent.trim();

        // 사이드바 접힘 연동
        requestAnimationFrame(function() {
            requestAnimationFrame(function() {
                stickyBar.classList.add('animated');
            });
        });
        if (document.documentElement.classList.contains('sb-collapsed')) {
            stickyBar.style.left = '60px';
        }

        var shown = false;
        var threshold = 80;
        window.addEventListener('scroll', function() {
            var scrollY = window.scrollY || window.pageYOffset;
            if (scrollY > threshold && !shown) {
                stickyBar.classList.add('visible');
                shown = true;
            } else if (scrollY <= threshold && shown) {
                stickyBar.classList.remove('visible');
                shown = false;
            }
        }, { passive: true });

        // 사이드바 토글 시 left 연동
        if (toggleBtn) {
            toggleBtn.addEventListener('click', function() {
                setTimeout(function() {
                    stickyBar.style.left = sidebar.classList.contains('collapsed') ? '60px' : '250px';
                }, 10);
            });
        }

        // 시계 (1초마다)
        var clockEl = document.getElementById('stickyClock');
        function updateStickyClock() {
            if (!clockEl) return;
            var now = new Date();
            clockEl.textContent = now.toLocaleTimeString('ko-KR', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
        }
        updateStickyClock();
        setInterval(updateStickyClock, 1000);

        // KPI 데이터 fetch
        var stickyDate = document.getElementById('stickyDate');
        var stickyKpi = document.getElementById('stickyKpi');
        fetch('/api/kpi-summary')
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(d) {
                if (!d) return;
                if (stickyDate) stickyDate.textContent = d.today + ' (' + d.weekday + ')';
                if (!stickyKpi) return;
                var html = '';
                html += '<span class="kpi-tag">진행 <b>' + d.contracted_count + '</b></span>';
                html += '<span class="kpi-tag' + (d.urgent_delivery_count > 0 ? ' hot' : '') + '">납품임박 <b>' + d.urgent_delivery_count + '</b></span>';
                html += '<span class="kpi-tag' + (d.overdue_count > 0 ? ' hot' : '') + '">납기지연 <b>' + d.overdue_count + '</b></span>';
                if (d.pending_users > 0) {
                    html += '<span class="kpi-tag warn">승인대기 <b>' + d.pending_users + '</b></span>';
                }
                stickyKpi.innerHTML = html;
            })
            .catch(function() {});

        // 날씨 + 예보 fetch (10분마다)
        var stickyWeather = document.getElementById('stickyWeather');
        var stickyForecast = document.getElementById('stickyForecast');
        function loadStickyWeather() {
            fetch('/api/weather', { credentials: 'same-origin' })
                .then(function(r) { return r.ok ? r.json() : null; })
                .then(function(w) {
                    if (!w) return;
                    if (stickyWeather) {
                        var parts = [];
                        parts.push('<span class="sw-icon">' + (w.icon || '🌤️') + '</span>');
                        parts.push('<span class="sw-temp">' + (w.temp || '--') + '°C</span>');
                        if (w.desc) parts.push('<span>' + w.desc + '</span>');
                        stickyWeather.innerHTML = parts.join('');
                    }
                    if (stickyForecast && w.forecast && w.forecast.length) {
                        var wds = ['오늘'];
                        var fcHtml = w.forecast.slice(0, 4).map(function(d, i) {
                            var label = i === 0 ? '오늘' : (d.weekday || '');
                            return '<span class="sf-day"><span class="sf-label">' + label + '</span>' + d.icon + '<span class="sf-temp">' + d.min + '/' + d.max + '°</span></span>';
                        }).join('');
                        stickyForecast.innerHTML = fcHtml;
                    }
                })
                .catch(function() {});
        }
        loadStickyWeather();
        setInterval(loadStickyWeather, 600000);
    })();
})();
