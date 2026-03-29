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
        if (window.innerWidth > 1199.98) return;
        (root || document).querySelectorAll('.main-content table.table, .main-content table[class*="table"], .main-content table[class*="tbl"], .main-content table.inv-tbl').forEach(function (table) {
            if (table.classList.contains('tree-card-table')) return;
            if (table.closest('.modal')) return;
            // 조도검증 격자/히트맵: 카드 변환 하지 않음
            if (table.classList.contains('ilv-grid') || table.classList.contains('ilv-table') || table.closest('.ilv-grid-wrap') || table.querySelector('.ilv-cell') || table.querySelector('th.ilv-xaxis') || table.id === 'heatmapTable' || table.id === 'diffTable' || table.id === 'measureTable') return;
            // BOM 상세 편집 테이블 제외
            if (table.id === 'bomTable' || table.id === 'itemsTable' || table.id === 'editItemsTable') return;
            // 피벗 테이블 제외 (월별 컬럼)
            if (table.classList.contains('pivot-tbl')) return;
            // no-stack-table도 모바일에서는 카드형으로 변환 (가로 스크롤 제거)
            table.classList.remove('no-stack-table');
            table.style.minWidth = '0';
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
                        // 빈 상태 행: 부모 tr도 스타일 재설정
                        var tr = cell.closest('tr');
                        if (tr) {
                            tr.style.display = 'block';
                            tr.style.border = 'none';
                            tr.style.borderLeft = 'none';
                            tr.style.boxShadow = 'none';
                            tr.style.background = 'transparent';
                            tr.style.padding = '0';
                        }
                        cell.style.display = 'block';
                        cell.style.width = '100%';
                        cell.style.textAlign = 'center';
                        cell.style.padding = '12px 0';
                        cell.style.color = '#94a3b8';
                        cell.style.wordBreak = 'keep-all';
                        cell.style.overflowWrap = 'normal';
                        cell.style.whiteSpace = 'normal';
                        cell.style.fontSize = '.85rem';
                        return;
                    }

                    if (!cell.getAttribute('data-label')) {
                        cell.setAttribute('data-label', headers[index] || ('항목 ' + (index + 1)));
                    }
                });
            });
        });
    }

    function fixCollapseTdWidth() {
        if (window.innerWidth > 1199.98) return;
        document.querySelectorAll('.tree-card-table tr.collapse.show > td[colspan], .tree-card-table tr.collapse > td[colspan]').forEach(function(td) {
            td.style.display = 'block';
            td.style.width = '100%';
            td.style.maxWidth = '100%';
            td.style.boxSizing = 'border-box';
        });
    }

    function refreshTables() {
        markStackTables(document);
        hydrateMobileTableLabels(document);
        fixCollapseTdWidth();
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
