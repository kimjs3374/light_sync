/* ═══ Drawing Gallery — JavaScript ═══ */

const PAGE_DATA = JSON.parse(document.getElementById('page-data').textContent);

const State = {
    siteId: PAGE_DATA.siteId,
    drawings: [],
    filtered: [],
    currentFilter: '전체',
    lbIdx: 0,
    lbVersionId: null,
    selectMode: false,
    selectedIds: new Set(),
};

const TYPE_BG    = {'제작도면': 'badge-bg-제작도면', '발주도면': 'badge-bg-발주도면'};
const TYPE_BADGE = {'제작도면': 'badge-type-제작도면', '발주도면': 'badge-type-발주도면'};
const TYPE_ICON  = {'제작도면': '📐', '발주도면': '📋'};

document.addEventListener('DOMContentLoaded', () => {
    const q = new URLSearchParams(location.search).get('q') || '';
    if (q) {
        const input = document.getElementById('siteSearchInput');
        if (input) { input.value = q; filterSites(q); }
    }
    if (State.siteId) loadDrawings(State.siteId);
    document.addEventListener('keydown', e => {
        if (!document.getElementById('pdf-lightbox').classList.contains('show')) return;
        if (e.key === 'Escape')     closeLightbox();
        if (e.key === 'ArrowLeft')  lbNav(-1);
        if (e.key === 'ArrowRight') lbNav(1);
    });
});

/* ── 현장 선택 ── */
function selectSite(siteId, siteName) {
    if (!siteId) return;
    document.querySelectorAll('.site-item').forEach(el =>
        el.classList.toggle('active', el.dataset.siteId === String(siteId))
    );
    State.siteId = siteId;
    if (State.selectMode) { State.selectMode = false; State.selectedIds.clear(); document.body.classList.remove('select-mode'); document.getElementById('selectModeBtn')?.classList.remove('active'); }

    const url = new URL(location.href);
    url.pathname = `/drawings/project/${siteId}`;
    history.pushState(null, '', url);

    /* 현장 헤더 갱신 */
    let card = document.getElementById('siteHeaderCard');
    if (!card) {
        card = document.createElement('div');
        card.id = 'siteHeaderCard';
        card.className = 'site-header-card';
        const panel = document.getElementById('galleryPanel');
        const noMsg = document.getElementById('noSiteMsg');
        if (noMsg) noMsg.remove();
        const uploadCard = document.getElementById('uploadCard');
        panel.insertBefore(card, uploadCard || document.getElementById('gallerySection'));
    }
    card.innerHTML = `<div style="padding:.25rem .75rem;"><div class="site-title">${esc(siteName)}</div></div>`;

    document.getElementById('uploadCard')?.classList.remove('d-none');
    document.getElementById('gallerySection').classList.remove('d-none');
    loadDrawings(siteId);
}

/* ── 현장 검색 ── */
function filterSites(q) {
    const needle = (q || '').toLowerCase();
    document.querySelectorAll('#siteList .site-item').forEach(el => {
        const name = (el.dataset.siteName || '').toLowerCase();
        const meta = (el.querySelector('.site-item-meta')?.textContent || '').toLowerCase();
        el.style.display = (!needle || name.includes(needle) || meta.includes(needle)) ? '' : 'none';
    });
    const url = new URL(location.href);
    if (q) url.searchParams.set('q', q);
    else url.searchParams.delete('q');
    history.replaceState(null, '', url);
}

/* ── 도면 로드 ── */
async function loadDrawings(siteId) {
    renderSkeletons();
    const sel = document.getElementById('uploadDrawingSelect');
    if (sel) sel.innerHTML = '<option value="">신규 도면으로 등록</option>';

    try {
        const r = await fetch(`/drawings/api/project/${siteId}`);
        const data = await r.json();
        State.drawings = data.drawings || [];

        if (sel) {
            State.drawings.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.id;
                opt.textContent = `${d.title} (${d.drawing_type})`;
                sel.appendChild(opt);
            });
        }
        updateCounts();
        applyFilter();
    } catch {
        document.getElementById('drawingGrid').innerHTML =
            '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:#dc2626;font-size:.82rem;">도면을 불러오지 못했습니다.</div>';
    }
}

function renderSkeletons(n = 8) {
    document.getElementById('drawingGrid').innerHTML =
        Array.from({length: n}, () => `
            <div class="skeleton-card">
                <div class="skeleton skeleton-thumb"></div>
                <div class="skeleton skeleton-line"></div>
                <div class="skeleton skeleton-line-sm"></div>
            </div>`).join('');
}

/* ── 필터 ── */
function updateCounts() {
    const types = ['전체', ...PAGE_DATA.drawingTypeOptions];
    types.forEach(t => {
        const cnt = t === '전체' ? State.drawings.length : State.drawings.filter(d => d.drawing_type === t).length;
        const el = document.getElementById(`cnt-${t}`);
        if (el) el.textContent = cnt;
    });
}
function setFilter(btn, type) {
    document.querySelectorAll('.drawing-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    State.currentFilter = type;
    applyFilter();
}
function applyFilter() {
    State.filtered = State.currentFilter === '전체'
        ? [...State.drawings]
        : State.drawings.filter(d => d.drawing_type === State.currentFilter);
    renderDrawings();
}

/* ── 도면 카드 렌더 ── */
function renderDrawings() {
    const grid = document.getElementById('drawingGrid');
    if (!State.filtered.length) {
        grid.innerHTML = '<div class="empty-gallery" style="grid-column:1/-1;"><span class="empty-icon">📄</span><p>등록된 도면이 없습니다.</p></div>';
        return;
    }
    grid.innerHTML = State.filtered.map((d, i) => {
        const bgCls   = TYPE_BG[d.drawing_type]    || 'badge-bg-기타';
        const icon    = TYPE_ICON[d.drawing_type]   || '📄';
        const badgeCls = TYPE_BADGE[d.drawing_type] || 'badge-type-기타';
        const isSelected = State.selectedIds.has(d.id);
        return `
        <div class="drawing-card${isSelected ? ' selected' : ''}" data-drawing-id="${d.id}"
             onclick="cardClick(event,${i},${d.id})">
            <div class="drawing-thumb-wrap ${bgCls}">
                <span class="drawing-card-check"></span>
                <span class="drawing-thumb-icon">${icon}</span>
                <span class="drawing-version-chip">v${d.version_count}</span>
            </div>
            <div class="drawing-card-body">
                <div class="drawing-card-title">${esc(d.title)}</div>
                <div class="d-flex align-items-center justify-content-between gap-1">
                    <span class="drawing-type-badge ${badgeCls}">${esc(d.drawing_type)}</span>
                    <span class="drawing-card-date">${esc(d.updated_at)}</span>
                </div>
            </div>
        </div>`;
    }).join('');
}

/* ── 카드 클릭 분기 ── */
function cardClick(e, idx, drawingId) {
    if (State.selectMode) { toggleCardSelect(drawingId); return; }
    openLightbox(idx);
}

/* ── 선택 모드 ── */
function toggleSelectMode() {
    State.selectMode = !State.selectMode;
    if (!State.selectMode) { State.selectedIds.clear(); }
    document.body.classList.toggle('select-mode', State.selectMode);
    const btn = document.getElementById('selectModeBtn');
    if (btn) btn.classList.toggle('active', State.selectMode);
    renderDrawings();
    updateBulkDeleteBtn();
}
function toggleCardSelect(drawingId) {
    if (State.selectedIds.has(drawingId)) State.selectedIds.delete(drawingId);
    else State.selectedIds.add(drawingId);
    const card = document.querySelector(`.drawing-card[data-drawing-id="${drawingId}"]`);
    if (card) card.classList.toggle('selected', State.selectedIds.has(drawingId));
    updateBulkDeleteBtn();
}
function selectAll() {
    State.filtered.forEach(d => State.selectedIds.add(d.id));
    renderDrawings();
    updateBulkDeleteBtn();
}
function clearSelection() {
    State.selectedIds.clear();
    renderDrawings();
    updateBulkDeleteBtn();
}
function updateBulkDeleteBtn() {
    const n = State.selectedIds.size;
    const countEl = document.getElementById('selectedCount');
    const btn = document.getElementById('bulkDeleteBtn');
    if (countEl) countEl.textContent = n;
    if (btn) {
        btn.disabled = n === 0;
        btn.textContent = n > 0 ? `선택삭제 (${n})` : '선택삭제';
    }
}
async function deleteSelected() {
    const ids = [...State.selectedIds];
    if (!ids.length) return;
    const titles = ids.map(id => State.drawings.find(d => d.id === id)?.title || id).join(', ');
    if (!confirm(`${ids.length}개 도면을 삭제할까요?\n\n${titles}`)) return;

    const btn = document.getElementById('bulkDeleteBtn');
    btn.disabled = true; btn.textContent = '삭제 중...';

    let deleted = 0, failed = 0;
    for (const id of ids) {
        try {
            const r = await fetch(`/drawings/api/drawing/${id}`, { method: 'DELETE' });
            const data = await r.json();
            if (r.ok && data.ok) {
                State.drawings = State.drawings.filter(d => d.id !== id);
                document.getElementById('uploadDrawingSelect')?.querySelector(`option[value="${id}"]`)?.remove();
                deleted++;
            } else { failed++; }
        } catch { failed++; }
    }
    State.selectedIds.clear();
    updateCounts();
    applyFilter();
    updateBulkDeleteBtn();
    bumpSiteCount(State.siteId, -deleted);
    if (failed === 0) showToast(`${deleted}개 도면이 삭제되었습니다.`, 'success');
    else showToast(`${deleted}개 삭제 완료, ${failed}개 실패`, 'warning');
}

/* ── 사이트 카운트 ── */
function bumpSiteCount(siteId, delta) {
    const el = document.querySelector(`.site-item[data-site-id="${siteId}"] .site-item-count`);
    if (el) el.textContent = Math.max(0, parseInt(el.textContent || '0') + delta);
}

/* ── PDF 라이트박스 ── */
function openLightbox(idx) {
    State.lbIdx = idx;
    showLbDrawing();
    document.getElementById('pdf-lightbox').classList.add('show');
    document.body.style.overflow = 'hidden';
}
function showLbDrawing() {
    const d = State.filtered[State.lbIdx];
    if (!d) return;

    document.getElementById('lb-title').textContent = d.title;
    const badge = document.getElementById('lb-type-badge');
    badge.textContent = d.drawing_type;
    badge.className = `drawing-type-badge ${TYPE_BADGE[d.drawing_type] || 'badge-type-기타'}`;

    const tabsEl = document.getElementById('lb-version-tabs');
    tabsEl.innerHTML = [...d.versions].sort((a, b) => b.version_no - a.version_no).map(v => {
        const extLabel = v.file_ext ? ` <span style="font-size:.58rem;opacity:.7;">${v.file_ext.toUpperCase()}</span>` : '';
        return `<button class="lb-version-tab${v.is_latest ? ' is-latest' : ''}"
                 data-vid="${v.id}" data-has-pdf="${v.has_pdf}" data-file-ext="${v.file_ext||''}"
                 onclick="selectLbVersion(${v.id}, ${v.has_pdf}, '${v.file_ext||''}')">v${v.version_no}${extLabel}</button>`;
    }).join('');

    const latest = d.versions.find(v => v.is_latest) || d.versions[0];
    if (latest) selectLbVersion(latest.id, latest.has_pdf, latest.file_ext || '');

    const total = State.filtered.length;
    document.getElementById('lb-caption-text').textContent = `${State.lbIdx + 1} / ${total}`;
    document.getElementById('lb-prev-btn').disabled = State.lbIdx === 0;
    document.getElementById('lb-next-btn').disabled = State.lbIdx === total - 1;
}
function selectLbVersion(versionId, hasPdf, fileExt) {
    State.lbVersionId = versionId;
    document.querySelectorAll('.lb-version-tab').forEach(tab =>
        tab.classList.toggle('active', parseInt(tab.dataset.vid) === versionId)
    );
    document.getElementById('lb-download-btn').href = `/drawings/version/${versionId}/download`;
    const frame = document.getElementById('pdf-lb-frame');
    if (hasPdf) {
        frame.style.display = '';
        document.getElementById('lb-no-preview')?.remove();
        frame.src = `/drawings/version/${versionId}/view`;
    } else {
        frame.style.display = 'none';
        frame.src = 'about:blank';
        let noPreview = document.getElementById('lb-no-preview');
        if (!noPreview) {
            noPreview = document.createElement('div');
            noPreview.id = 'lb-no-preview';
            noPreview.style.cssText = 'flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#94a3b8;gap:1rem;';
            frame.parentNode.insertBefore(noPreview, frame.nextSibling);
        }
        noPreview.innerHTML = `<span style="font-size:3rem;opacity:.4;">📐</span>
            <p style="font-size:.9rem;margin:0;">DWG 파일은 브라우저에서 미리볼 수 없습니다.</p>
            <a href="/drawings/version/${versionId}/download" class="btn btn-sm btn-outline-light">⬇ DWG 다운로드</a>`;
    }
}
function lbNav(delta) {
    const n = State.filtered.length;
    State.lbIdx = Math.max(0, Math.min(n - 1, State.lbIdx + delta));
    document.getElementById('pdf-lb-frame').src = 'about:blank';
    document.getElementById('lb-no-preview')?.remove();
    showLbDrawing();
}
function closeLightbox() {
    document.getElementById('pdf-lightbox').classList.remove('show');
    document.getElementById('pdf-lb-frame').src = 'about:blank';
    document.body.style.overflow = '';
}

/* ── 버전 삭제 (AJAX) ── */
async function deleteCurrentVersion() {
    if (!State.lbVersionId) return;
    const d = State.filtered[State.lbIdx];
    if (!d) return;
    const v = d.versions.find(v => v.id === State.lbVersionId);
    if (!v) return;

    const msg = d.versions.length === 1
        ? `v${v.version_no}을 삭제하면 "${d.title}" 도면 전체가 삭제됩니다.\n계속하시겠습니까?`
        : `v${v.version_no} 버전을 삭제할까요?`;
    if (!confirm(msg)) return;

    const btn = document.getElementById('lb-delete-btn');
    btn.disabled = true; btn.textContent = '삭제 중...';

    const csrf = document.querySelector('meta[name="csrf-token"]');
    try {
        const r = await fetch(`/drawings/api/version/${State.lbVersionId}`, {
            method: 'DELETE', headers: csrf ? {'X-CSRFToken': csrf.content} : {},
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || '삭제 실패');

        if (data.drawing_deleted) {
            State.drawings = State.drawings.filter(x => x.id !== d.id);
            /* 업로드 select에서도 제거 */
            document.getElementById('uploadDrawingSelect')
                ?.querySelector(`option[value="${d.id}"]`)?.remove();
            applyFilter();
            bumpSiteCount(State.siteId, -1);
            closeLightbox();
            showToast(`"${d.title}" 도면이 삭제되었습니다.`, 'success');
        } else {
            const di = State.drawings.findIndex(x => x.id === d.id);
            if (di >= 0) {
                State.drawings[di].versions = State.drawings[di].versions.filter(x => x.id !== State.lbVersionId);
                State.drawings[di].version_count = State.drawings[di].versions.length;
                State.filtered[State.lbIdx] = State.drawings[di];
                const newLatest = State.drawings[di].versions.find(x => x.is_latest) || State.drawings[di].versions[0];
                if (newLatest) selectLbVersion(newLatest.id);
                showLbDrawing();
            }
            applyFilter();
            showToast(`v${v.version_no} 버전이 삭제되었습니다.`, 'success');
        }
    } catch (e) {
        showToast(e.message, 'danger');
    } finally {
        btn.disabled = false; btn.textContent = '삭제';
    }
}

/* ── 업로드 ── */
function selectDrawingType(btn) {
    document.querySelectorAll('#drawingTypeBtns .drawing-type-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}
function onDrawingSelectChange(sel) {
    const titleInput = document.getElementById('uploadTitle');
    if (!titleInput) return;
    titleInput.disabled = !!sel.value;
    titleInput.placeholder = sel.value ? '기존 도면에 버전 추가' : '도면명 (신규 등록 시 입력)';
    if (sel.value) titleInput.value = '';
}
function handleDragOver(e) { e.preventDefault(); document.getElementById('dropZone').classList.add('drag-over'); }
function handleDragLeave() { document.getElementById('dropZone').classList.remove('drag-over'); }
function handleDrop(e) {
    e.preventDefault();
    document.getElementById('dropZone').classList.remove('drag-over');
    handleFileSelect(e.dataTransfer.files);
}
function handleFileSelect(files) {
    if (!State.siteId) { showToast('먼저 현장을 선택하세요.', 'warning'); return; }
    Array.from(files).forEach(f => {
        const ext = f.name.toLowerCase().split('.').pop();
        if (!['pdf', 'dwg'].includes(ext)) { showToast(`${f.name}: PDF 또는 DWG 파일만 업로드 가능합니다.`, 'danger'); return; }
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
    fd.append('pdf_file', file);
    fd.append('drawing_type', document.querySelector('#drawingTypeBtns .active')?.dataset.type || '제작도면');
    const titleVal = (document.getElementById('uploadTitle')?.value || '').trim();
    if (titleVal) fd.append('title', titleVal);
    const drawingId = document.getElementById('uploadDrawingSelect')?.value;
    if (drawingId) fd.append('drawing_id', drawingId);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/drawings/api/upload/${State.siteId}`);
    // X-CSRFToken은 base.html send() 오버라이드에서 자동 주입됨 (중복 설정 시 400 오류)

    xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
            const pct = Math.round(e.loaded / e.total * 100);
            document.getElementById(`${uid}-bar`).style.width = pct + '%';
            document.getElementById(`${uid}-pct`).textContent = pct + '%';
        }
    };
    xhr.onload = () => {
        item.remove();
        if (xhr.status === 200) {
            try {
                const data = JSON.parse(xhr.responseText);
                const d = data.drawing;
                if (d.is_new) {
                    /* 신규 도면 → 목록 앞에 추가 + select 옵션 추가 */
                    State.drawings.unshift(d);
                    const sel = document.getElementById('uploadDrawingSelect');
                    if (sel) {
                        const opt = document.createElement('option');
                        opt.value = d.id;
                        opt.textContent = `${d.title} (${d.drawing_type})`;
                        sel.appendChild(opt);
                    }
                    bumpSiteCount(State.siteId, 1);
                } else {
                    /* 버전 업데이트 */
                    const idx = State.drawings.findIndex(x => x.id === d.id);
                    if (idx >= 0) State.drawings[idx] = d;
                }
                updateCounts(); applyFilter();
                /* 입력 초기화 */
                document.getElementById('uploadTitle').value = '';
                document.getElementById('uploadDrawingSelect').value = '';
                onDrawingSelectChange(document.getElementById('uploadDrawingSelect'));
                showToast(`업로드 완료 (v${d.version_count})`, 'success');
            } catch { showToast('업로드됐지만 응답 오류', 'warning'); }
        } else {
            try { const e = JSON.parse(xhr.responseText); showToast('업로드 실패: ' + (e.error || xhr.status), 'danger'); }
            catch { showToast('업로드 실패 ' + xhr.status, 'danger'); }
        }
    };
    xhr.onerror = () => { item.remove(); showToast('네트워크 오류', 'danger'); };
    xhr.send(fd);
}

/* ── 유틸 ── */
function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function showToast(msg, type = 'info') {
    const c = {success:'#16a34a', danger:'#dc2626', warning:'#d97706', info:'#2563eb'};
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;background:${c[type]||c.info};color:#fff;padding:.55rem 1rem;border-radius:.5rem;font-size:.82rem;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.2);opacity:0;transition:opacity .25s;`;
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(() => { t.style.opacity = '1'; });
    setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 3000);
}
