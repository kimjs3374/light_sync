(() => {
    const dataEl = document.getElementById('billboardData');
    if (!dataEl) return;
    let items = [];
    try { items = JSON.parse(dataEl.textContent || '[]'); } catch(e) { return; }
    if (!items.length) return;

    const tickerEl = document.getElementById('globalTicker');
    const titleEl = document.getElementById('tickerTitle');
    const messageEl = document.getElementById('tickerMessage');
    const linkEl = document.getElementById('tickerLink');
    if (!tickerEl || !titleEl || !messageEl || !linkEl) return;

    const validLevels = ['info','warning','danger'];
    let idx = 0, timer = null;

    function restartRoll(text) {
        const dur = Math.max(10, Math.min(24, Math.ceil((text||'').length / 4)));
        messageEl.classList.remove('is-rolling');
        messageEl.style.setProperty('--ticker-dur', dur + 's');
        void messageEl.offsetWidth;
        messageEl.classList.add('is-rolling');
    }

    function render(i) {
        const item = items[i] || items[0];
        const level = validLevels.includes(item.level) ? item.level : 'info';
        tickerEl.classList.remove('level-info','level-warning','level-danger');
        tickerEl.classList.add('level-' + level);
        titleEl.textContent = item.title || '공지';
        messageEl.textContent = item.message || '-';
        linkEl.href = item.detail_url || linkEl.dataset.fallbackUrl || '#';
        restartRoll(item.message || '');
        if (timer) clearTimeout(timer);
        const sec = Math.max(2, Number(item.display_seconds || 6));
        timer = setTimeout(() => { idx = (idx + 1) % items.length; render(idx); }, sec * 1000);
    }
    render(idx);
})();
