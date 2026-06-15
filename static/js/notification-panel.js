/* ═══ 알림 드롭다운 패널 + 토스트 ═══ */
(function() {
    var panel = document.getElementById('notiDropdown');
    var btn = document.getElementById('notiBtn');
    if (!panel || !btn) return;

    var isOpen = false;
    var lastCount = -1;

    // 드롭다운 토글
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        isOpen = !isOpen;
        panel.style.display = isOpen ? 'block' : 'none';
        if (isOpen) loadRecent();
    });

    // 외부 클릭 시 닫기
    document.addEventListener('click', function(e) {
        if (isOpen && !panel.contains(e.target) && !btn.contains(e.target)) {
            isOpen = false;
            panel.style.display = 'none';
        }
    });

    // noti_type → 색상
    var typeColors = {
        delivery_urgent: '#dc2626', delivery_overdue: '#dc2626',
        delivery: '#2563eb', contract: '#2563eb',
        production: '#16a34a',
        material: '#d97706', inventory: '#d97706',
        issue: '#dc2626',
        trip: '#7c3aed', document: '#6366f1',
        warranty: '#ea580c', cert: '#ea580c',
        system: '#64748b',
    };

    function loadRecent() {
        fetch('/api/notifications/recent')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var list = panel.querySelector('.noti-list');
                if (!list) return;
                if (!d.items || d.items.length === 0) {
                    list.innerHTML = '<div style="padding:1.5rem;text-align:center;color:#94a3b8;font-size:.82rem;">알림이 없습니다</div>';
                    return;
                }
                var html = '';
                var items = d.items.slice(0, 10);
                for (var i = 0; i < items.length; i++) {
                    var n = items[i];
                    var color = typeColors[n.noti_type] || '#64748b';
                    var unread = !n.is_read;
                    html += '<a href="' + (n.link || '#') + '" class="noti-item' + (unread ? ' unread' : '') + '" data-id="' + n.id + '" onclick="markNotiRead(' + n.id + ')">'
                        + '<div class="noti-color-bar" style="background:' + color + '"></div>'
                        + '<div class="noti-body">'
                        + '<div class="noti-title">' + (unread ? '<span class="noti-new">N</span>' : '') + escHtml(n.title) + '</div>'
                        + (n.message ? '<div class="noti-msg">' + escHtml(n.message).substring(0, 60) + '</div>' : '')
                        + '<div class="noti-time">' + (n.created_at || '') + '</div>'
                        + '</div></a>';
                }
                list.innerHTML = html;
            })
            .catch(function() {});
    }

    // 전역 함수: 읽음 처리
    window.markNotiRead = function(id) {
        fetch('/api/notifications/' + id + '/read', {method: 'POST'}).catch(function() {});
    };

    // 전체 읽음
    var readAllBtn = panel.querySelector('.noti-read-all');
    if (readAllBtn) {
        readAllBtn.addEventListener('click', function(e) {
            e.preventDefault();
            fetch('/api/notifications/read-all', {method: 'POST'}).then(function() {
                loadRecent();
                checkNoti();
            });
        });
    }

    // ── 토스트 알림 ──
    function showToast(item) {
        var container = document.getElementById('notiToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notiToastContainer';
            container.style.cssText = 'position:fixed;bottom:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column-reverse;gap:.5rem;max-width:340px;';
            document.body.appendChild(container);
        }

        var color = typeColors[item.noti_type] || '#64748b';
        var toast = document.createElement('a');
        toast.href = item.link || '#';
        toast.style.cssText = 'display:block;text-decoration:none;background:#fff;border:1px solid #e2e8f0;border-left:3px solid ' + color + ';border-radius:.5rem;padding:.65rem .75rem;box-shadow:0 8px 24px rgba(0,0,0,.1);animation:notiSlideIn .3s ease;cursor:pointer;';
        toast.innerHTML = '<div style="font-size:.8rem;font-weight:700;color:#0f172a;margin-bottom:2px;">' + escHtml(item.title) + '</div>'
            + (item.message ? '<div style="font-size:.75rem;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(item.message).substring(0, 50) + '</div>' : '');
        toast.onclick = function() { markNotiRead(item.id); };

        container.appendChild(toast);
        setTimeout(function() {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity .3s';
            setTimeout(function() { toast.remove(); }, 300);
        }, 5000);
    }

    // ── 폴링 + 토스트 트리거 ──
    function checkNoti() {
        fetch('/api/notifications/unread-count')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var badge = document.getElementById('notiBadge');
                if (badge) {
                    if (d.count > 0) {
                        badge.textContent = d.count > 99 ? '99+' : d.count;
                        badge.style.display = '';
                    } else {
                        badge.style.display = 'none';
                    }
                }
                // 새 알림이 추가된 경우 토스트
                if (lastCount >= 0 && d.count > lastCount) {
                    fetch('/api/notifications/recent')
                        .then(function(r) { return r.json(); })
                        .then(function(rd) {
                            if (rd.items && rd.items.length > 0 && !rd.items[0].is_read) {
                                showToast(rd.items[0]);
                            }
                        });
                }
                lastCount = d.count;
            })
            .catch(function() {});
    }
    checkNoti();
    setInterval(checkNoti, 30000);

    // sticky bar 보일 때 fixed 벨 숨기기 (겹침 방지)
    var fixedBell = document.getElementById('notiFixedBell');
    var stickyBar = document.getElementById('pageStickyBar');
    if (fixedBell && stickyBar) {
        var _bellObs = new MutationObserver(function() {
            var visible = stickyBar.classList.contains('visible');
            fixedBell.style.display = visible ? 'none' : '';
            // sticky bar 내 뱃지 동기화
            var sb = document.getElementById('stickyNotiBadge');
            var mb = document.getElementById('notiBadge');
            if (sb && mb) { sb.textContent = mb.textContent; sb.style.display = mb.style.display; }
        });
        _bellObs.observe(stickyBar, { attributes: true, attributeFilter: ['class'] });
    }

    function escHtml(s) {
        if (!s) return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }
})();
