/* ═══ Photo Gallery — JavaScript ═══ */

document.addEventListener('DOMContentLoaded', () => {
    const q = new URLSearchParams(location.search).get('q') || '';
    if (q) {
        const input = document.getElementById('siteSearchInput');
        if (input) { input.value = q; filterSites(q); }
    }
    if (State.siteId) {
        fetch(`/photos/api/site/${State.siteId}`).then(r=>r.json()).then(renderSiteHeader).catch(()=>{});
        loadPhotos(State.siteId);
    }
    document.addEventListener('keydown', e => {
        const lb = document.getElementById('lightbox-overlay');
        if (!lb.classList.contains('show')) return;
        if (e.key === 'Escape')      closeLightbox(null, true);
        if (e.key === 'ArrowLeft')   lightboxNav(-1);
        if (e.key === 'ArrowRight')  lightboxNav(1);
    });
});

/* ── 현장 선택 ── */
function selectSite(siteId, siteName) {
    if (!siteId) return;
    document.querySelectorAll('.site-item').forEach(el =>
        el.classList.toggle('active', el.dataset.siteId === String(siteId)));
    State.siteId = siteId;
    // 현장 선택 시 URL 업데이트 (검색어 유지)
    const url = new URL(location.href);
    url.pathname = `/photos/project/${siteId}`;
    history.pushState(null, '', url);

    fetch(`/photos/api/site/${siteId}`)
        .then(r => r.json())
        .then(renderSiteHeader)
        .catch(() => {});

    document.getElementById('noSiteMsg')?.remove();
    document.getElementById('uploadCard').classList.remove('d-none');
    document.getElementById('gallerySection').classList.remove('d-none');
    loadPhotos(siteId);
}

function renderSiteHeader(data) {
    let card = document.getElementById('siteHeaderCard');
    if (!card) {
        card = document.createElement('div');
        card.id = 'siteHeaderCard';
        card.className = 'site-header-card';
        document.getElementById('galleryPanel').insertBefore(
            card, document.getElementById('uploadCard'));
    }

    // 계약 목록 저장
    State.contracts = data.contracts || [];

    // 계약 목록 렌더
    const contractsHtml = (data.contracts || []).map(c => {
        const badges = c.items.map(it =>
            `<span class="badge bg-light text-dark border" style="font-size:.72rem;">${esc(it.item_name)} <span class="text-muted">×${it.qty}</span></span>`
        ).join('');
        return `<div class="contract-row" id="crow-${c.id}" onclick="setContractFilter(event,${c.id})">
            <div class="contract-row-name">${esc(c.contract_name)}${c.contract_no ? ' <span class="text-muted fw-normal" style="font-size:.75rem;">('+esc(c.contract_no)+')</span>' : ''}</div>
            <div class="d-flex flex-wrap gap-1 mt-1">${badges || '<span class="text-muted" style="font-size:.72rem;">품목 없음</span>'}</div>
        </div>`;
    }).join('');

    card.innerHTML = `
        <div class="site-title-row site-title-row-active" id="siteTitleRow" onclick="clearContractFilter()">
            <div class="site-title">${esc(data.site_name)}</div>
            <div class="site-contract-no">${esc(data.project_no || '')}</div>
        </div>
        <div class="site-header-badges">${contractsHtml || '<span class="text-muted" style="font-size:.78rem;padding:.4rem .75rem;display:block;">등록된 계약 없음</span>'}</div>`;
}

/* ── 현장 검색 ── */
function filterSites(q) {
    const needle = (q || '').toLowerCase();
    document.querySelectorAll('#siteList .site-item').forEach(el => {
        const name = (el.dataset.siteName || '').toLowerCase();
        const no   = (el.querySelector('.site-item-meta')?.textContent || '').toLowerCase();
        el.style.display = (!needle || name.includes(needle) || no.includes(needle)) ? '' : 'none';
    });
    // URL 쿼리 파라미터 유지
    const url = new URL(location.href);
    if (q) url.searchParams.set('q', q);
    else url.searchParams.delete('q');
    history.replaceState(null, '', url);
}

/* ── 모바일 현장 검색 ── */
function filterMobileSites(q) {
    const needle = (q || '').toLowerCase();
    const sel = document.getElementById('mobileSiteSelect');
    if (!sel) return;
    Array.from(sel.options).forEach(opt => {
        if (!opt.value) return; // placeholder
        const name = (opt.dataset.name || opt.textContent || '').toLowerCase();
        opt.hidden = needle ? !name.includes(needle) : false;
    });
}

/* ── 사진 로드 ── */
async function loadPhotos(siteId) {
    renderSkeletons();
    State.selected.clear();
    try {
        const r = await fetch(`/photos/api/photos?site_id=${siteId}`);
        const data = await r.json();
        State.photos = data.photos || [];
        State.contractFilter = null;
        updateCounts();
        applyFilter();
    } catch {
        document.getElementById('photoGrid').innerHTML =
            '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:#dc2626;font-size:.82rem;">사진을 불러오지 못했습니다.</div>';
    }
}

function renderSkeletons(n=8) {
    document.getElementById('photoGrid').innerHTML =
        Array.from({length:n}, () => `
            <div class="skeleton-card">
                <div class="skeleton skeleton-thumb"></div>
                <div class="skeleton skeleton-line"></div>
                <div class="skeleton skeleton-line-sm"></div>
            </div>`).join('');
}

/* ── 필터 ── */
function updateCounts() {
    const base = State.contractFilter !== null
        ? State.photos.filter(p => p.contract_id === State.contractFilter)
        : State.photos;
    ['전체','설계','명함','생산','상차','하차','설치'].forEach(t => {
        const cnt = t === '전체' ? base.length : base.filter(p=>p.photo_type===t).length;
        const el = document.getElementById(`cnt-${t}`);
        if (el) el.textContent = cnt;
    });
}

function setFilter(btn, type) {
    document.querySelectorAll('.photo-filter-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    State.currentFilter = type;
    applyFilter();
}

function selectPhotoType(btn) {
    document.querySelectorAll('#photoTypeBtns .photo-type-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function clearContractFilter() {
    State.contractFilter = null;
    State.selected.clear();
    document.querySelectorAll('.contract-row').forEach(row => row.classList.remove('contract-row-active'));
    document.getElementById('siteTitleRow')?.classList.add('site-title-row-active');
    updateCounts();
    applyFilter();
}

function setContractFilter(e, contractId) {
    // 같은 계약 재클릭 시 전체로 해제
    if (State.contractFilter === contractId) contractId = null;
    State.contractFilter = contractId;
    State.selected.clear();
    const titleRow = document.getElementById('siteTitleRow');
    if (contractId === null) {
        titleRow?.classList.add('site-title-row-active');
    } else {
        titleRow?.classList.remove('site-title-row-active');
    }
    document.querySelectorAll('.contract-row').forEach(row => {
        row.classList.toggle('contract-row-active', row.id === `crow-${contractId}`);
    });
    updateCounts();
    applyFilter();
}

function applyFilter() {
    let list = [...State.photos];
    if (State.contractFilter !== null) {
        list = list.filter(p => p.contract_id === State.contractFilter);
    }
    if (State.currentFilter !== '전체') {
        list = list.filter(p => p.photo_type === State.currentFilter);
    }
    State.filtered = list;
    renderPhotos();
    updateDownloadToolbar();
}

/* ── 갤러리 렌더링 ── */
const BADGE = {'설계':'badge-type-설계','명함':'badge-type-명함','생산':'badge-type-생산','상차':'badge-type-상차','하차':'badge-type-하차','설치':'badge-type-설치'};

function renderPhotos() {
    const grid = document.getElementById('photoGrid');
    if (!State.filtered.length) {
        grid.innerHTML = '<div class="empty-gallery" style="grid-column:1/-1;"><span class="empty-icon">🖼️</span><p>사진이 없습니다.</p></div>';
        return;
    }
    grid.innerHTML = State.filtered.map((p,i) => `
        <div class="photo-card" data-photoid="${p.id}">
            <div class="photo-thumb-wrap" onclick="openLightbox(${i})">
                <img src="${esc(p.url)}" alt="${esc(p.photo_type||'사진')}" loading="lazy" onerror="this.style.display='none'">
                <button class="photo-delete-btn" title="삭제" onclick="deletePhoto(event,${p.id})">✕</button>
            </div>
            <div class="photo-card-body">
                <div class="d-flex align-items-center justify-content-between gap-1">
                    <label class="d-flex align-items-center gap-1 mb-0" style="cursor:pointer;" onclick="event.stopPropagation()">
                        <input type="checkbox" class="photo-check" ${State.selected.has(p.id)?'checked':''} onchange="toggleSelect(${p.id},this.checked)">
                        <span class="photo-type-badge ${BADGE[p.photo_type]||'badge-type-기타'}">${esc(p.photo_type||'기타')}</span>
                    </label>
                    <span class="photo-card-date">${esc((p.uploaded_at||'').slice(0,10))}</span>
                </div>
            </div>
        </div>`).join('');
}

/* ── 선택 & 다운로드 ── */
function toggleSelect(id, checked) {
    if (checked) State.selected.add(id);
    else State.selected.delete(id);
    updateDownloadToolbar();
}

function toggleSelectAll() {
    const allSelected = State.filtered.every(p => State.selected.has(p.id));
    if (allSelected) {
        State.filtered.forEach(p => State.selected.delete(p.id));
    } else {
        State.filtered.forEach(p => State.selected.add(p.id));
    }
    renderPhotos();
    updateDownloadToolbar();
}

function updateDownloadToolbar() {
    const cnt = State.selected.size;
    const downloadBtn = document.getElementById('downloadBtn');
    const deleteBtn = document.getElementById('deleteSelectedBtn');
    const info = document.getElementById('selectedInfo');
    const dlCount = document.getElementById('downloadCount');
    const delCount = document.getElementById('deleteCount');
    if (downloadBtn) { downloadBtn.disabled = cnt === 0; }
    if (deleteBtn) { deleteBtn.disabled = cnt === 0; }
    if (dlCount) dlCount.textContent = cnt ? `(${cnt}건)` : '';
    if (delCount) delCount.textContent = cnt ? `(${cnt}건)` : '';
    if (info) { info.style.display = cnt ? '' : 'none'; info.textContent = `${cnt}장 선택됨`; }
}

async function deleteSelected() {
    const ids = [...State.selected];
    if (!ids.length) return;
    if (!confirm(`선택한 사진 ${ids.length}장을 삭제할까요?`)) return;
    const btn = document.getElementById('deleteSelectedBtn');
    btn.disabled = true;
    btn.innerHTML = '삭제 중... <span id="deleteCount"></span>';
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const headers = csrfMeta ? {'X-CSRFToken': csrfMeta.content} : {};

    const results = await Promise.all(
        ids.map(id => fetch(`/photos/api/photos/${id}`, {method:'DELETE', headers})
            .then(r => ({id, ok: r.ok}))
            .catch(() => ({id, ok: false}))
        )
    );

    let failed = 0, deleted = 0;
    results.forEach(({id, ok}) => {
        if (ok) { State.photos = State.photos.filter(p => p.id !== id); State.selected.delete(id); deleted++; }
        else failed++;
    });

    // 버튼 복구를 updateDownloadToolbar 호출 전에 수행 (deleteCount span 복원 필요)
    btn.innerHTML = '선택삭제 <span id="deleteCount"></span>';

    if (deleted) bumpSiteCount(State.siteId, -deleted);
    if (failed) showToast(`${failed}건 삭제 실패`, 'warning');
    else showToast(`${deleted}장 삭제됨`, 'success');
    updateCounts(); applyFilter();
}

async function downloadSelected() {
    const ids = [...State.selected];
    if (!ids.length) return;
    const btn = document.getElementById('downloadBtn');
    btn.disabled = true;
    btn.innerHTML = '준비 중... <span id="downloadCount"></span>';
    try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const r = await fetch('/photos/api/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(csrfMeta ? {'X-CSRFToken': csrfMeta.content} : {}),
            },
            body: JSON.stringify({ids}),
        });
        if (!r.ok) throw new Error('서버 오류');
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        const ts = new Date().toISOString().slice(0,10);
        a.download = `photos_${ts}.zip`;
        a.click();
        URL.revokeObjectURL(a.href);
    } catch(e) {
        alert('다운로드 실패: ' + e.message);
    } finally {
        btn.disabled = State.selected.size === 0;
        btn.innerHTML = `다운로드 <span id="downloadCount">(${State.selected.size}건)</span>`;
    }
}

/* ── 라이트박스 ── */
function openLightbox(idx) {
    State.lbIdx = idx;
    showLbImage();
    document.getElementById('lightbox-overlay').classList.add('show');
    document.body.style.overflow = 'hidden';
}
function showLbImage() {
    const p = State.filtered[State.lbIdx];
    if (!p) return;
    const img = document.getElementById('lightbox-img');
    img.src = p.url;
    document.getElementById('lightbox-caption').textContent =
        `${p.photo_type||'기타'} · ${(p.uploaded_at||'').slice(0,16).replace('T',' ')} · ${State.lbIdx+1}/${State.filtered.length}`;
}
function lightboxNav(d) {
    const n = State.filtered.length;
    State.lbIdx = (State.lbIdx + d + n) % n;
    const img = document.getElementById('lightbox-img');
    img.style.opacity = '0';
    setTimeout(()=>{ showLbImage(); img.style.opacity='1'; }, 100);
}
function closeLightbox(e, force=false) {
    if (force || e?.target?.id==='lightbox-overlay') {
        document.getElementById('lightbox-overlay').classList.remove('show');
        document.body.style.overflow='';
    }
}

/* ── 업로드 ── */
function handleDragOver(e) { e.preventDefault(); document.getElementById('dropZone').classList.add('drag-over'); }
function handleDragLeave()  { document.getElementById('dropZone').classList.remove('drag-over'); }
function handleDrop(e) {
    e.preventDefault();
    document.getElementById('dropZone').classList.remove('drag-over');
    handleFileSelect(e.dataTransfer.files);
}
function handleFileSelect(files) {
    if (!State.siteId) { alert('먼저 현장을 선택하세요.'); return; }
    Array.from(files).forEach(f => {
        if (f.size > 20*1024*1024) { showToast(`${f.name}: 20MB 초과`, 'danger'); return; }
        uploadFile(f);
    });
}

function uploadFile(file) {
    const uid = `up-${Date.now()}`;
    const list = document.getElementById('uploadProgressList');
    const item = document.createElement('div');
    item.id = uid; item.className = 'upload-progress-item';
    item.innerHTML = `
        <div class="d-flex justify-content-between">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%;">${esc(file.name)}</span>
            <span class="text-muted" id="${uid}-pct">0%</span>
        </div>
        <div class="progress"><div class="progress-bar bg-primary" id="${uid}-bar" style="width:0%"></div></div>`;
    list.appendChild(item);

    const fd = new FormData();
    fd.append('file', file);
    fd.append('site_id', State.siteId);
    fd.append('photo_type', document.querySelector('#photoTypeBtns .active')?.dataset.type || '설계');
    if (State.contractFilter) fd.append('contract_id', State.contractFilter);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/photos/api/upload');
    // X-CSRFToken은 base.html send() 오버라이드에서 자동 주입됨 (중복 설정 시 400 오류)

    xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
            const pct = Math.round(e.loaded/e.total*100);
            document.getElementById(`${uid}-bar`).style.width = pct+'%';
            document.getElementById(`${uid}-pct`).textContent = pct+'%';
        }
    };
    xhr.onload = () => {
        item.remove();
        if (xhr.status === 200) {
            try {
                const d = JSON.parse(xhr.responseText);
                State.photos.unshift(d.photo);
                updateCounts(); applyFilter(State.currentFilter);
                bumpSiteCount(State.siteId, 1);
                showToast('업로드 완료', 'success');
            } catch { showToast('업로드됐지만 응답 오류', 'warning'); }
        } else {
            try { const e = JSON.parse(xhr.responseText); showToast('업로드 실패: '+(e.error||xhr.status), 'danger'); }
            catch { showToast('업로드 실패 '+xhr.status, 'danger'); }
        }
    };
    xhr.onerror = () => { item.remove(); showToast('네트워크 오류', 'danger'); };
    xhr.send(fd);
}

/* ── 삭제 ── */
async function deletePhoto(e, photoId) {
    e.stopPropagation();
    if (!confirm('이 사진을 삭제하시겠습니까?')) return;
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const r = await fetch(`/photos/api/photos/${photoId}`, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': csrfMeta?.content || '', 'Content-Type': 'application/json' },
    });
    if (r.ok) {
        State.photos = State.photos.filter(p=>p.id!==photoId);
        updateCounts(); applyFilter(State.currentFilter);
        bumpSiteCount(State.siteId, -1);
        showToast('삭제되었습니다.', 'success');
    } else { showToast('삭제 실패', 'danger'); }
}

function bumpSiteCount(siteId, d) {
    const el = document.querySelector(`.site-item[data-site-id="${siteId}"] .site-item-count`);
    if (el) el.textContent = Math.max(0, parseInt(el.textContent||'0')+d);
}

/* ── 유틸 ── */
function esc(s) {
    return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function showToast(msg, type='info') {
    const c = {success:'#16a34a',danger:'#dc2626',warning:'#d97706',info:'#2563eb'};
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;background:${c[type]||c.info};color:#fff;padding:.55rem 1rem;border-radius:.5rem;font-size:.82rem;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.2);opacity:0;transition:opacity .25s;`;
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(()=>{ t.style.opacity='1'; });
    setTimeout(()=>{ t.style.opacity='0'; setTimeout(()=>t.remove(),300); }, 3000);
}
