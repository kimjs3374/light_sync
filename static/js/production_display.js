(() => {
    const REFRESH_SEC = 30;
    const columnMeta = JSON.parse(document.getElementById('columnMeta').textContent || '[]');

    // ── 시계 ──
    const clockEl = document.getElementById('pdClock');
    function updateClock() {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
    updateClock();
    setInterval(updateClock, 1000);

    // ── 날씨 (서버 프록시 경유, 10분마다) ──
    function loadWeather() {
        fetch('/api/weather', { credentials: 'same-origin' })
            .then(r => r.json())
            .then(w => {
                document.getElementById('wIcon').textContent = w.icon || '🌤️';
                document.getElementById('wTemp').textContent = (w.temp || '--') + '°C';
                const parts = [w.desc || ''];
                if (w.feels && w.feels !== '--') parts.push('체감 ' + w.feels + '°');
                if (w.humidity && w.humidity !== '--') parts.push('습도 ' + w.humidity + '%');
                document.getElementById('wDesc').textContent = parts.filter(Boolean).join(' · ') || w.location || '';

                // 주간 예보
                const fc = w.forecast || [];
                const fcEl = document.getElementById('wForecast');
                if (fcEl && fc.length) {
                    fcEl.innerHTML = fc.map((d, i) => {
                        const label = i === 0 ? '오늘' : d.weekday || '';
                        return `<div class="pd-forecast-day"><span class="fc-wd">${label}</span><span class="fc-icon">${d.icon}</span><span class="fc-temp">${d.min}/${d.max}°</span></div>`;
                    }).join('');
                }
            })
            .catch(() => {});
    }
    loadWeather();
    setInterval(loadWeather, 600000);

    // ── 자재 티커 롤링 ──
    function initTicker() {
        const scrollEl = document.getElementById('tickerScroll');
        if (scrollEl && scrollEl.children.length > 1) {
            const totalWidth = scrollEl.scrollWidth / 2;
            const speed = 55;
            const duration = Math.max(12, Math.round(totalWidth / speed));
            scrollEl.style.setProperty('--ticker-duration', duration + 's');
            scrollEl.classList.add('is-rolling');
        }
    }
    initTicker();

    // ── 전광판 (한번만 초기화, 갱신 시 건드리지 않음) ──
    let bbItems = [];
    try { bbItems = JSON.parse(document.getElementById('billboardData').textContent || '[]'); } catch(e) {}

    const bbEl = document.getElementById('pdBillboard');
    const bbTitle = document.getElementById('bbTitle');
    const bbMsg = document.getElementById('bbMessage');
    const validLevels = ['info', 'warning', 'danger'];
    let bbIndex = 0;
    let bbTimer = null;

    const bbCounter = document.getElementById('bbCounter');

    function renderBb(idx) {
        if (!bbItems.length) return;
        const item = bbItems[idx] || bbItems[0];
        const level = validLevels.includes(item.level) ? item.level : 'info';
        bbEl.classList.remove('level-info', 'level-warning', 'level-danger');
        bbEl.classList.add('level-' + level);
        bbTitle.textContent = item.title || '공지';
        bbMsg.textContent = item.message || '-';
        bbMsg.classList.remove('fade-out');
        if (bbItems.length > 1) {
            bbCounter.textContent = `${idx + 1}/${bbItems.length}`;
        }

        if (bbTimer) clearTimeout(bbTimer);
        const sec = Math.max(4, Number(item.display_seconds || 6));
        if (bbItems.length > 1) {
            bbTimer = setTimeout(() => {
                bbMsg.classList.add('fade-out');
                setTimeout(() => {
                    bbIndex = (bbIndex + 1) % bbItems.length;
                    renderBb(bbIndex);
                }, 400);
            }, sec * 1000);
        }
    }
    renderBb(0);

    // ── 카드 데이터 저장소 (모달용) — 초기 데이터 로드 ──
    const cardStore = {};
    const initialCards = JSON.parse(document.getElementById('initialCards').textContent || '{}');
    Object.keys(initialCards).forEach(colKey => {
        (initialCards[colKey] || []).forEach(c => {
            cardStore[colKey + '_' + c.contract_item_id] = c;
        });
    });

    // ── 모달 ──
    const modalBackdrop = document.getElementById('pdModal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    const modalDetailLink = document.getElementById('modalDetailLink');

    function closeModal() { modalBackdrop.classList.remove('show'); }
    document.getElementById('modalClose').addEventListener('click', closeModal);
    document.getElementById('modalCloseBtn').addEventListener('click', closeModal);
    modalBackdrop.addEventListener('click', e => { if (e.target === modalBackdrop) closeModal(); });

    function statusBadge(text, color) {
        const colors = { red: '#ef4444', amber: '#f59e0b', green: '#22c55e', blue: '#3b82f6', purple: '#a855f7', cyan: '#06b6d4', slate: '#64748b' };
        const bg = colors[color] || colors.slate;
        return `<span style="background:${bg};color:#fff;font-size:.6rem;font-weight:700;padding:.1rem .3rem;border-radius:4px;white-space:nowrap">${text}</span>`;
    }

    function openModal(cardId, colKey) {
        const card = cardStore[cardId];
        if (!card) return;

        modalTitle.textContent = card.contract_name ? `${card.contract_name} — ${card.project_name}` : `${card.project_name} (${card.project_no})`;
        modalDetailLink.href = card.detail_url || '#';

        let html = '';

        // 기본 정보
        html += `<div class="pd-modal-section">`;
        html += `<div class="pd-modal-label">기본 정보</div>`;
        html += `<div class="pd-modal-row"><span>품목</span><span class="pd-modal-val">${card.category} ${card.model_name}</span></div>`;
        html += `<div class="pd-modal-row"><span>수량</span><span class="pd-modal-val">${card.quantity}EA</span></div>`;
        html += `<div class="pd-modal-row"><span>납기</span><span class="pd-modal-val">${card.dday != null ? (card.dday < 0 ? 'D+' + (-card.dday) : card.dday === 0 ? 'D-Day' : 'D-' + card.dday) : '미정'}</span></div>`;
        html += `<div class="pd-modal-row"><span>상태</span><span>${card.is_urgent ? statusBadge('긴급', 'red') + ' ' : ''}${card.is_priority ? statusBadge('최우선', 'amber') + ' ' : ''}${statusBadge(card.status_prod || '-', colKey === 'negotiation' ? 'purple' : colKey === 'material' ? 'amber' : colKey === 'in_production' ? 'green' : colKey === 'delivery' ? 'cyan' : 'slate')}</span></div>`;
        html += `</div>`;

        // 협의현황
        if (colKey === 'negotiation') {
            html += `<div class="pd-modal-section">`;
            html += `<div class="pd-modal-label">영업 현황</div>`;
            html += `<div class="pd-modal-row"><span>영업 상태</span><span class="pd-modal-val">${card.status_sales || '-'}</span></div>`;
            html += `<div class="pd-modal-row"><span>관리 상태</span><span class="pd-modal-val">${card.status_admin || '-'}</span></div>`;
            html += `<div class="pd-modal-row"><span>생산 상태</span><span class="pd-modal-val">${card.status_prod || '-'}</span></div>`;
            html += `</div>`;
        }

        // 자재 현황 (모든 자재 보여줌)
        if (card.material_total > 0) {
            const pct = card.material_percent;
            const barColor = pct >= 100 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#ef4444';
            html += `<div class="pd-modal-section">`;
            html += `<div class="pd-modal-label">자재 현황 (${card.material_ready}/${card.material_total})</div>`;
            html += `<div class="pd-modal-bar-wrap"><div class="pd-modal-bar"><div class="pd-modal-bar-fill" style="width:${pct}%;background:${barColor}"></div></div><span style="font-size:.75rem;font-weight:800">${pct}%</span></div>`;
            if (card.missing_materials && card.missing_materials.length) {
                card.missing_materials.forEach(m => {
                    const os = m.is_outsourcing ? statusBadge('외주', 'purple') + ' ' : '';
                    let st = '';
                    if (m.status === '발주대기') st = statusBadge('미발주', 'red');
                    else if (m.status === '발주완료') st = statusBadge('발주완료', 'blue');
                    else st = statusBadge(m.status, 'slate');
                    const dt = m.expected_date ? `<span style="color:#64748b;font-size:.68rem;margin-left:.3rem">${m.expected_date}</span>` : '';
                    html += `<div class="pd-modal-mat-item">${os}<span class="pd-modal-mat-name">${m.name}</span>${st}${dt}</div>`;
                });
            } else {
                html += `<div style="font-size:.75rem;color:#4ade80;font-weight:700">전체 입고 완료 ✅</div>`;
            }
            html += `</div>`;
        }

        // 공정 현황
        if (colKey === 'in_production' || colKey === 'production_ready') {
            html += `<div class="pd-modal-section">`;
            html += `<div class="pd-modal-label">공정 진행률</div>`;
            const ppct = card.process_percent;
            const pColor = ppct >= 80 ? '#22c55e' : ppct >= 40 ? '#3b82f6' : '#64748b';
            html += `<div class="pd-modal-bar-wrap"><div class="pd-modal-bar"><div class="pd-modal-bar-fill" style="width:${ppct}%;background:${pColor}"></div></div><span style="font-size:.75rem;font-weight:800">${ppct}%</span></div>`;
            if (card.current_process) html += `<div class="pd-modal-row"><span>현재 공정</span><span class="pd-modal-val">${card.current_process}</span></div>`;
            if (card.next_process) html += `<div class="pd-modal-row"><span>다음 공정</span><span class="pd-modal-val">${card.next_process}</span></div>`;
            html += `</div>`;
        }

        // 납품/완료
        if (colKey === 'delivery') {
            html += `<div class="pd-modal-section">`;
            html += `<div class="pd-modal-label">납품 현황</div>`;
            html += `<div class="pd-modal-row"><span>생산</span><span class="pd-modal-val">${card.status_prod}</span></div>`;
            html += `</div>`;
        }
        if (colKey === 'completed' && card.completed_at) {
            html += `<div class="pd-modal-section">`;
            html += `<div class="pd-modal-label">완료</div>`;
            html += `<div class="pd-modal-row"><span>완료일</span><span class="pd-modal-val">${card.completed_at}</span></div>`;
            html += `</div>`;
        }

        modalBody.innerHTML = html;
        modalBackdrop.classList.add('show');
    }

    // ── 카드에 클릭 이벤트 위임 ──
    document.querySelector('.pd-board').addEventListener('click', e => {
        const cardEl = e.target.closest('.pd-card');
        if (!cardEl) return;
        const id = cardEl.dataset.cardId;
        const col = cardEl.dataset.colKey;
        if (id && col) openModal(id, col);
    });

    // ── 카드 HTML 생성 ──
    function ddayHtml(card) {
        if (card.dday == null) return '';
        const cls = card.dday <= 3 ? 'pd-dday-red' : card.dday <= 7 ? 'pd-dday-yellow' : 'pd-dday-blue';
        const txt = card.dday < 0 ? `D+${-card.dday}` : card.dday === 0 ? 'D-Day' : `D-${card.dday}`;
        return `<span class="pd-dday ${cls}">${txt}</span>`;
    }

    function cardHtml(card, colKey, rank) {
        const cid = `${colKey}_${card.contract_item_id}`;
        cardStore[cid] = card;

        const urgent = card.is_urgent ? ' pd-urgent' : '';
        const priority = card.is_priority ? ' pd-priority' : '';
        const star = card.is_priority ? '<span class="pd-star">★</span>' : '';

        let body = '';
        if (colKey === 'negotiation') {
            body = `<div class="pd-sales-status">${card.status_sales || ''}</div>`;
        } else if (colKey === 'material') {
            body = `<div class="pd-material-bar"><div class="pd-bar-track"><div class="pd-bar-fill pd-fill-amber" style="width:${card.material_percent}%"></div></div><span class="pd-bar-label">${card.material_ready}/${card.material_total}</span></div>`;
            (card.missing_materials || []).slice(0, 2).forEach(m => {
                const osBadge = m.is_outsourcing ? '<span class="pd-badge-outsource">외주</span>' : '';
                let sBadge = '';
                if (m.status === '발주대기') sBadge = '<span class="pd-badge-danger">미발주</span>';
                else if (m.expected_date) sBadge = `<span class="pd-badge-muted">${m.expected_date}</span>`;
                else sBadge = '<span class="pd-badge-muted">미정</span>';
                body += `<div class="pd-missing">${osBadge}<span>${m.name}</span>${sBadge}</div>`;
            });
            if ((card.missing_materials || []).length > 2) {
                body += `<div class="pd-missing"><span class="pd-badge-muted">+${card.missing_materials.length - 2}건</span></div>`;
            }
        } else if (colKey === 'production_ready') {
            body = `<div class="pd-material-ok">자재 ✅</div><div class="pd-ready-rank">#${rank} 투입</div>`;
        } else if (colKey === 'in_production') {
            body = `<div class="pd-process-current">${card.current_process || '공정 확인중'}</div>`;
            body += `<div class="pd-material-bar"><div class="pd-bar-track"><div class="pd-bar-fill pd-fill-green" style="width:${card.process_percent}%"></div></div><span class="pd-bar-label">${card.process_percent}%</span></div>`;
            if (card.next_process) body += `<div class="pd-process-next">다음: ${card.next_process}</div>`;
        } else if (colKey === 'delivery') {
            body = `<div class="pd-delivery-status">${card.status_prod === '생산완료' ? '출고대기' : '납품진행'}</div>`;
        } else if (colKey === 'completed') {
            body = `<div class="pd-completed-date">${card.completed_at || '-'} 완료</div>`;
        }

        return `<div class="pd-card${urgent}${priority}" data-card-id="${cid}" data-col-key="${colKey}">
            <div class="pd-card-header">${star}<span class="pd-card-name">${card.contract_name || card.project_name}</span>${ddayHtml(card)}</div>
            <div class="pd-card-sub">${card.project_name}</div>
            <div class="pd-card-item">${card.category} ${card.model_name} x${card.quantity}</div>
            ${body}
        </div>`;
    }

    // ── AJAX 보드 갱신 (전광판/티커 유지) ──
    function refreshBoard() {
        fetch(location.pathname + '?partial=1', { credentials: 'same-origin' })
            .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(data => {
                const cards = data.cards || {};
                columnMeta.forEach(col => {
                    // 일정 컬럼은 캘린더+연차 정보라 AJAX 갱신 제외
                    if (col.key === 'schedule') return;

                    const colEl = document.getElementById('col-' + col.key);
                    if (!colEl) return;
                    const list = cards[col.key] || [];

                    // 카운트 업데이트
                    const countEl = colEl.querySelector('.pd-column-count');
                    if (countEl) countEl.textContent = list.length;

                    // 카드 영역 갱신
                    const bodyEl = colEl.querySelector('.pd-column-body');
                    if (!bodyEl) return;
                    if (!list.length) {
                        bodyEl.innerHTML = '<div class="pd-empty">없음</div>';
                    } else {
                        bodyEl.innerHTML = list.map((c, i) => cardHtml(c, col.key, i + 1)).join('');
                    }
                });

                // 자재 티커도 갱신
                const ticker = data.ticker || [];
                const tickerEl = document.getElementById('tickerScroll');
                if (tickerEl && ticker.length) {
                    const items = ticker.map(m => {
                        const os = m.is_outsourcing ? ' <span class="pd-badge-outsource">외주</span>' : '';
                        const loc = m.project_name ? `(${m.vendor_name}→${m.project_name})` : (m.vendor_name ? `(${m.vendor_name})` : '');
                        return `<span class="pd-ticker-item">${m.expected_date} ${m.material_name} ${m.quantity}EA ${loc}${os}</span>`;
                    });
                    tickerEl.innerHTML = items.join('') + items.join('');
                    tickerEl.classList.remove('is-rolling');
                    void tickerEl.offsetWidth;
                    const tw = tickerEl.scrollWidth / 2;
                    tickerEl.style.setProperty('--ticker-duration', Math.max(12, Math.round(tw / 55)) + 's');
                    tickerEl.classList.add('is-rolling');
                }
            })
            .catch(() => {});
    }

    setInterval(refreshBoard, REFRESH_SEC * 1000);
})();
