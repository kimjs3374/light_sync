/* ═══ 신규 메일시스템(mail.mgnt.kr) 전환 안내 ═══
 * 사이드바/즐겨찾기/플라이아웃 어디서 눌러도 동일하게 뜨도록
 * document 캡처 단계에서 메일함 링크를 가로챈다.
 */
(function() {
    var NEW_MAIL_URL = 'https://mail.mgnt.kr';
    var LEGACY_PATHS = ['/mail/shared', '/mail/personal', '/mail/external'];

    var modalEl = document.getElementById('mailMigrationModal');
    if (!modalEl) return;

    var titleEl = modalEl.querySelector('[data-role="legacy-name"]');
    var okBtn = modalEl.querySelector('[data-role="go-new"]');
    var cancelBtn = modalEl.querySelector('[data-role="go-legacy"]');
    var modal = new bootstrap.Modal(modalEl);
    var pendingLegacyUrl = '';

    function legacyPathOf(link) {
        var href = link.getAttribute('href') || '';
        if (!href || href.charAt(0) === '#') return '';
        var path;
        try {
            var u = new URL(href, window.location.origin);
            if (u.origin !== window.location.origin) return '';
            path = u.pathname;
        } catch (e) {
            return '';
        }
        return LEGACY_PATHS.indexOf(path.replace(/\/$/, '')) >= 0 ? path : '';
    }

    document.addEventListener('click', function(e) {
        if (e.defaultPrevented) return;
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // 새 탭 열기는 그대로
        if (!e.target || !e.target.closest) return;
        if (e.target.closest('.fav-toggle')) return;   // 즐겨찾기 별표는 그대로 동작
        var link = e.target.closest('a[href]');
        if (!link) return;
        if (link.target && link.target !== '_self') return;
        if (!legacyPathOf(link)) return;

        e.preventDefault();
        e.stopPropagation();
        pendingLegacyUrl = link.href;
        if (titleEl) {
            titleEl.textContent = link.getAttribute('data-menu-label')
                || (link.textContent || '').trim() || '기존 웹메일';
        }
        modal.show();
    }, true);

    if (okBtn) {
        okBtn.addEventListener('click', function() {
            modal.hide();
            window.location.href = NEW_MAIL_URL;
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            modal.hide();
            if (pendingLegacyUrl) window.location.href = pendingLegacyUrl;
        });
    }
})();
