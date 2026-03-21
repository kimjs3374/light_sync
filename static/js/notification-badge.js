/* ═══ 알림 뱃지 폴링 ═══ */
(function() {
    function checkNoti() {
        fetch('/api/notifications/unread-count')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var badge = document.getElementById('notiBadge');
                if (!badge) return;
                if (d.count > 0) {
                    badge.textContent = d.count > 99 ? '99+' : d.count;
                    badge.style.display = '';
                } else {
                    badge.style.display = 'none';
                }
            })
            .catch(function() {});
    }
    checkNoti();
    setInterval(checkNoti, 30000);
})();
