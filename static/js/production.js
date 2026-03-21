(function() {
    'use strict';

    /* ── CSRF token ── */
    function getCsrf() {
        return document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    /* ── JSON POST helper ── */
    async function apiPost(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrf()
            },
            body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    /* ── Section collapse ── */
    window.toggleSection = function(hdr) {
        const body = hdr.nextElementSibling;
        const collapsed = hdr.classList.toggle('collapsed');
        body.style.display = collapsed ? 'none' : '';
    };

    /* ── Client-side filter (AND logic) ── */
    window.applyFilters = function() {
        const searchEl = document.getElementById('filterSearch');
        const search = searchEl ? searchEl.value.toLowerCase().trim() : '';

        document.querySelectorAll('.proc-card').forEach(card => {
            const matchSrch = !search || (card.dataset.search || '').toLowerCase().includes(search);
            card.style.display = matchSrch ? '' : 'none';
        });
    };

    /* ── Autosave: daily qty ── */
    let saveTimers = {};

    window.saveDailyQty = function(pid, input) {
        const dot = document.getElementById('dot-' + pid);
        const qty = parseInt(input.value, 10);
        if (isNaN(qty) || qty < 0) return;

        dot.className = 'save-dot saving';
        clearTimeout(saveTimers[pid]);
        saveTimers[pid] = setTimeout(async () => {
            try {
                await apiPost('/api/production/process/' + pid + '/daily-log', { daily_qty: qty });
                dot.className = 'save-dot saved';
                setTimeout(() => { dot.className = 'save-dot'; }, 2500);
            } catch(e) {
                dot.className = 'save-dot error';
                console.error('daily-log error:', e);
            }
        }, 800);
    };

    /* ── Start process ── */
    window.doStart = async function(pid) {
        const btn = document.querySelector('#card-' + pid + ' .btn-start');
        if (!btn) return;
        btn.disabled = true;
        btn.textContent = '처리중…';
        try {
            await apiPost('/api/production/process/' + pid + '/toggle', { is_active: true });
            location.reload();
        } catch(e) {
            btn.disabled = false;
            btn.textContent = '시작하기';
            alert('오류가 발생했습니다. 다시 시도해주세요.');
        }
    };

    /* ── Complete / Uncomplete ── */
    window.doComplete = async function(pid, complete) {
        var label = complete ? '완료' : '되돌리기';
        var confirmed = confirm(complete
            ? '이 공정을 완료 처리하시겠습니까?'
            : '완료를 취소하고 진행중으로 되돌리시겠습니까?');
        if (!confirmed) return;
        try {
            await apiPost('/api/production/process/' + pid + '/complete', { complete: complete });
            location.reload();
        } catch(e) {
            alert('오류가 발생했습니다. 다시 시도해주세요.');
        }
    };

    /* ── Sync ── */
    window.doSync = async function() {
        const btn     = document.getElementById('btnSync');
        const spinner = document.getElementById('syncSpinner');
        btn.disabled  = true;
        spinner.classList.remove('d-none');
        try {
            await apiPost('/api/production/sync', {});
            location.reload();
        } catch(e) {
            alert('동기화 중 오류가 발생했습니다.');
            btn.disabled = false;
            spinner.classList.add('d-none');
        }
    };

})();
