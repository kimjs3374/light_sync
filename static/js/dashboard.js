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

    function restartRoll() {
        messageEl.classList.remove('is-rolling');
        const track = messageEl.parentElement;
        if (!track) return;
        const overflow = messageEl.scrollWidth - track.clientWidth;
        if (overflow <= 0) return; // 안 넘치면 롤링 안 함
        const dur = Math.max(8, Math.ceil(overflow / 30));
        const shift = -(overflow + 20); // 20px 여유
        messageEl.style.setProperty('--ticker-dur', dur + 's');
        messageEl.style.setProperty('--ticker-shift', shift + 'px');
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
        restartRoll();
        if (timer) clearTimeout(timer);
        const sec = Math.max(2, Number(item.display_seconds || 6));
        timer = setTimeout(() => { idx = (idx + 1) % items.length; render(idx); }, sec * 1000);
    }
    render(idx);
})();
