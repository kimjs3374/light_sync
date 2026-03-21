/* ═══ 모바일 메뉴 + 모바일 테이블 스택 ═══ */
(function() {
    var sidebar = document.getElementById('sidebar');
    var menuBtn = document.getElementById('mobileMenuBtn');
    var backdrop = document.getElementById('sidebarBackdrop');

    if (!sidebar || !menuBtn || !backdrop) return;

    function closeSidebar() {
        sidebar.classList.remove('show');
        backdrop.classList.remove('show');
    }

    menuBtn.addEventListener('click', function() {
        sidebar.classList.toggle('show');
        backdrop.classList.toggle('show');
    });

    backdrop.addEventListener('click', closeSidebar);

    sidebar.addEventListener('click', function(e) {
        var link = e.target.closest('a[href]');
        if (link && link.getAttribute('href') !== '#' && window.innerWidth <= 991.98) {
            closeSidebar();
        }
    });

    window.addEventListener('resize', function() {
        if (window.innerWidth > 991.98) closeSidebar();
    });
})();

(function () {
    function markStackTables(root) {
        (root || document).querySelectorAll('.main-content table.table').forEach(function (table) {
            if (table.classList.contains('no-stack-table')) return;
            table.classList.add('mobile-stack-table');
        });
    }

    function hydrateMobileTableLabels(root) {
        (root || document).querySelectorAll('table.mobile-stack-table').forEach(function (table) {
            const headers = Array.from(table.querySelectorAll('thead th')).map(function (th) {
                return (th.textContent || '').replace(/\s+/g, ' ').trim();
            });

            table.querySelectorAll('tbody tr').forEach(function (row) {
                Array.from(row.children).forEach(function (cell, index) {
                    if (!cell || cell.tagName !== 'TD') return;

                    const colspan = Number(cell.getAttribute('colspan') || '1');
                    if (colspan > 1) {
                        cell.classList.add('mobile-full-row');
                        cell.setAttribute('data-label', '');
                        return;
                    }

                    if (!cell.getAttribute('data-label')) {
                        cell.setAttribute('data-label', headers[index] || ('항목 ' + (index + 1)));
                    }
                });
            });
        });
    }

    function refreshTables() {
        markStackTables(document);
        hydrateMobileTableLabels(document);
    }

    refreshTables();

    document.querySelectorAll('[data-bs-toggle="collapse"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            window.requestAnimationFrame(refreshTables);
        });
    });

    ['shown.bs.collapse', 'shown.bs.modal', 'shown.bs.tab'].forEach(function (evt) {
        document.addEventListener(evt, refreshTables);
    });

    window.addEventListener('resize', function () {
        if (window.innerWidth <= 1199.98) refreshTables();
    });
})();
