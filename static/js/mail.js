/**
 * ERP 웹메일 JS — 리스트 + 페이지 이동 방식
 */

function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
}

function fetchJson(url, opts = {}) {
    const defaults = {
        headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
    };
    if (opts.body && !(opts.body instanceof FormData)) {
        defaults.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(opts.body);
    }
    return fetch(url, { ...defaults, ...opts }).then(r => r.json());
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function formatDate(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        const now = new Date();
        if (d.toDateString() === now.toDateString()) {
            return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
        }
        if (d.getFullYear() === now.getFullYear()) {
            return d.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
        }
        return d.toLocaleDateString('ko-KR', { year: '2-digit', month: 'short', day: 'numeric' });
    } catch { return iso; }
}

function formatSize(bytes) {
    if (!bytes) return '0B';
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + 'KB';
    return (bytes / 1048576).toFixed(1) + 'MB';
}


// =========================================================================
// Mail — 메일함 목록
// =========================================================================
const Mail = {
    accountId: null,
    currentFolder: 'INBOX',
    currentPage: 1,

    init(accountId) {
        const params = new URLSearchParams(window.location.search);
        const urlAccount = params.get('account');
        const urlFolder = params.get('folder');
        this.accountId = urlAccount ? parseInt(urlAccount) : accountId;
        this.mode = document.getElementById('mailMode')?.value || 'personal';
        if (urlFolder) this.currentFolder = urlFolder;
        this.bindEvents();
        this._highlightTab();
        this.initTabDrag();
        window.scrollTo(0, 0);
        // 폴더(캐시 우선) + 메시지 병렬 로드
        Promise.all([this.loadFolders(false), this.loadMessages()]).then(() => {
            this._initFolderDrop();
            // 백그라운드로 폴더 갱신 (깜빡임 없이)
            this.loadFolders(true);
        });
        this.startNotification();
    },

    switchAccount(id) {
        this.accountId = id;
        this.currentFolder = 'INBOX';
        this.currentPage = 1;
        this._unreadOnly = false;
        const ufBtn = document.getElementById('unreadFilterBtn');
        if (ufBtn) { ufBtn.classList.remove('btn-primary', 'text-white'); ufBtn.classList.add('btn-outline-secondary'); }
        const sel = document.getElementById('accountSelect');
        if (sel) sel.value = id;
        this._highlightTab();
        const ft = document.getElementById('folderTitle');
        if (ft) ft.textContent = '받은편지함';
        // URL에 account 파라미터 저장 (새로고침 시 유지)
        const url = new URL(window.location);
        url.searchParams.set('account', id);
        history.replaceState(null, '', url);
        this.loadFolders(true);
        this.loadMessages();
    },

    _highlightTab() {
        document.querySelectorAll('.mail-account-tab').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.accountId) === this.accountId);
        });
    },

    bindEvents() {
        // 계정 전환
        document.getElementById('accountSelect')?.addEventListener('change', (e) => {
            this.accountId = parseInt(e.target.value);
            this.currentFolder = 'INBOX';
            this.currentPage = 1;
            this.loadFolders(true);
            this.loadMessages();
        });

        // 새로고침 (폴더도 강제 리로드)
        document.getElementById('refreshBtn')?.addEventListener('click', () => {
            this.loadFolders(true);
            this.loadMessages();
        });

        // 보낸사람 클릭 (이벤트 위임)
        document.addEventListener('click', (e) => {
            const from = e.target.closest('.mail-col-from[data-email]');
            if (from) {
                e.stopPropagation();
                e.preventDefault();
                this._showFromMenu(e, from.dataset.email, from.dataset.name);
            }
        });

        // 전체 선택
        document.getElementById('selectAll')?.addEventListener('change', (e) => {
            document.querySelectorAll('.mail-check').forEach(c => c.checked = e.target.checked);
            this._updateBulk();
        });

        // 검색
        document.getElementById('searchBtn')?.addEventListener('click', () => this.search());
        document.getElementById('searchInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.search();
        });
    },

    selectFolder(name) {
        if (!document.getElementById('mailListBody')) {
            const mode = new URLSearchParams(window.location.search).get('mode') || 'personal';
            const base = mode === 'shared' ? '/mail/shared' : '/mail/personal';
            location.href = `${base}?folder=${encodeURIComponent(name)}&account=${this.accountId}`;
            return;
        }
        this._activeLabel = null;
        this.currentFolder = name;
        this.currentPage = 1;
        // 안읽은 메일 필터 해제
        if (this._unreadOnly) {
            this._unreadOnly = false;
            const btn = document.getElementById('unreadFilterBtn');
            if (btn) { btn.classList.remove('btn-primary', 'text-white'); btn.classList.add('btn-outline-secondary'); }
        }
        this.loadMessages();
        this._renderFolderSidebar(this._lastFolders || [], this._labels);
        const el = document.getElementById('folderTitle');
        const item = document.querySelector(`.mail-folder-item[data-folder="${name}"]`);
        if (el && item) el.textContent = item.textContent.trim().replace(/\d+$/, '').trim();
    },

    // --- 폴더 사이드바 ---
    _unreadOnly: false,

    toggleUnreadFilter() {
        this._unreadOnly = !this._unreadOnly;
        const btn = document.getElementById('unreadFilterBtn');
        if (btn) {
            btn.classList.toggle('btn-primary', this._unreadOnly);
            btn.classList.toggle('btn-outline-secondary', !this._unreadOnly);
            btn.classList.toggle('text-white', this._unreadOnly);
        }
        this.currentPage = 1;
        this.loadMessages();
    },

    _lastFolders: [],

    async loadFolders(force) {
        const cacheKey = `mail_folders_${this.accountId}`;

        if (!force) {
            try {
                const cached = sessionStorage.getItem(cacheKey);
                if (cached) {
                    const data = JSON.parse(cached);
                    this._lastFolders = data.folders || data;
                    this._renderFolderSidebar(this._lastFolders, data.labels || []);
                    // 캐시 표시 후 백그라운드로 정확한 unread 갱신
                    this._fetchAllUnreadBackground(false);
                    return;
                }
            } catch {}
        }

        const res = await fetchJson(`/mail/api/folders?account=${this.accountId}${force ? '&refresh=1' : ''}`);
        if (res.error) return;
        const folders = res.folders || [];
        const labels = res.labels || [];
        this._lastFolders = folders;

        try { sessionStorage.setItem(cacheKey, JSON.stringify({folders, labels})); } catch {}

        this._renderFolderSidebar(folders, labels);

        // 빠른 INBOX-only 응답 그린 뒤, 전체 폴더 unread 를 백그라운드 fetch
        // → 사이드바 뱃지가 1~2초 안에 정확한 값으로 채워짐
        this._fetchAllUnreadBackground(force);
    },

    async _fetchAllUnreadBackground(force) {
        if (!this.accountId) return;
        try {
            const url = `/mail/api/folders?account=${this.accountId}&all_unread=1${force ? '&refresh=1' : ''}`;
            const res = await fetchJson(url);
            if (res.error) return;
            const folders = res.folders || [];
            const labels = res.labels || [];
            this._lastFolders = folders;
            try {
                const cacheKey = `mail_folders_${this.accountId}`;
                sessionStorage.setItem(cacheKey, JSON.stringify({folders, labels}));
            } catch {}
            this._renderFolderSidebar(folders, labels);
        } catch {}
    },

    _labels: [],

    _renderFolderSidebar(folders, labels) {
        const sidebar = document.getElementById('folderSidebar');
        if (!sidebar) return;
        this._labels = labels || [];

        const icon = (name) => {
            const n = name.toLowerCase();
            if (n === 'inbox') return '📥';
            if (n.includes('sent')) return '📤';
            if (n.includes('draft')) return '📝';
            if (n.includes('trash') || n.includes('delete')) return '🗑️';
            if (n.includes('junk') || n.includes('spam')) return '⚠️';
            if (n.includes('archive')) return '🗄️';
            return '📁';
        };
        const folderLabel = (name) => {
            const n = name.toLowerCase();
            if (n === 'inbox') return '받은편지함';
            if (n.includes('sent')) return '보낸편지함';
            if (n.includes('draft')) return '임시보관함';
            if (n.includes('trash') || n.includes('delete')) return '휴지통';
            if (n.includes('junk') || n.includes('spam')) return '스팸';
            if (n.includes('archive')) return '보관함';
            return name.split('.').pop().split('/').pop();
        };

        // 분류: 시스템 폴더 vs 사용자 폴더
        const sysExact = ['inbox', 'sent', 'drafts', 'draft', 'trash', 'junk', 'spam', 'archive', 'archived'];
        const sysFolders = [];
        const userFolders = [];
        folders.forEach(f => {
            const n = f.name.toLowerCase();
            // 정확히 시스템 폴더명이거나 구분자 없는 단일 이름만 매칭
            // INBOX.관리 같은 하위 폴더는 사용자 폴더로 분류
            const baseName = n.split('.').pop().split('/').pop();
            if (sysExact.includes(n) || sysExact.includes(baseName)) sysFolders.push(f);
            else userFolders.push(f);
        });
        const sysOrder = ['inbox', 'sent', 'draft', 'archive', 'junk', 'spam', 'trash'];
        sysFolders.sort((a, b) => {
            const an = a.name.toLowerCase().split('.').pop().split('/').pop();
            const bn = b.name.toLowerCase().split('.').pop().split('/').pop();
            const ai = sysOrder.findIndex(s => an.startsWith(s));
            const bi = sysOrder.findIndex(s => bn.startsWith(s));
            return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
        });

        let html = '';

        // 시스템 폴더
        sysFolders.forEach(f => {
            const active = f.name === this.currentFolder ? 'active' : '';
            const n = f.name.toLowerCase();
            const isSent = n.includes('sent');
            const isDraft = n.includes('draft');
            const badge = (f.unread > 0 && !isSent && !isDraft) ? `<span class="badge bg-danger rounded-pill">${f.unread}</span>` : '';
            html += `<div class="mail-folder-item ${active}" data-folder="${f.name}" onclick="Mail.selectFolder('${f.name.replace(/'/g,"\\'")}')">
                <span>${icon(f.name)} ${folderLabel(f.name)}</span> ${badge}
            </div>`;
        });

        // 사용자 폴더
        if (userFolders.length) {
            html += '<div class="mail-folder-section">📁 폴더</div>';
            userFolders.forEach(f => {
                const active = f.name === this.currentFolder ? 'active' : '';
                const badge = f.unread > 0 ? `<span class="badge bg-danger rounded-pill">${f.unread}</span>` : '';
                html += `<div class="mail-folder-item ${active}" data-folder="${f.name}" onclick="Mail.selectFolder('${f.name.replace(/'/g,"\\'")}')">
                    <span>📁 ${folderLabel(f.name)}</span> ${badge}
                </div>`;
            });
        }

        // 라벨
        if (this._labels.length) {
            html += '<div class="mail-folder-section">🏷️ 라벨</div>';
            this._labels.forEach(l => {
                const active = this._activeLabel === l.id ? 'active' : '';
                html += `<div class="mail-folder-item mail-label-item ${active}" data-label-id="${l.id}" onclick="Mail.selectLabel(${l.id},'${esc(l.name)}')">
                    <span><span class="mail-label-dot" style="background:${l.color};"></span> ${esc(l.name)}</span>
                </div>`;
            });
        }

        // 라벨 추가 버튼
        html += `<div class="mail-folder-item" style="color:#94a3b8;font-size:.75rem;" onclick="Mail.addLabel()">
            <span>+ 라벨 추가</span>
        </div>`;

        // 주소록 (외부메일 모드에서는 표시 안 함)
        const mailMode = document.getElementById('mailMode')?.value || 'personal';
        if (mailMode !== 'external') {
            const settingsUrl = sidebar.dataset.settingsUrl || '/mail/settings?mode=personal';
            html += '<div class="mail-folder-section">📒 주소록</div>';
            html += `<div class="mail-folder-item" onclick="location.href='${settingsUrl}#tabContacts'">
                <span>📒 주소록 관리</span>
            </div>`;
        }

        const sidebarHtml = `<div class="mail-sidebar-inner">${html}</div>`;
        sidebar.innerHTML = sidebarHtml;
        // 캐시에 HTML 저장 (다음 페이지에서 즉시 복원)
        try { sessionStorage.setItem('mail_sidebar_html_' + this.accountId, sidebarHtml); } catch {}
        this._initFolderDrop();
    },

    _activeLabel: null,

    selectLabel(id, name) {
        this._activeLabel = id;
        this.currentFolder = 'INBOX';
        this._renderFolderSidebar(this._lastFolders || [], this._labels);
        const el = document.getElementById('folderTitle');
        if (el) el.textContent = '🏷️ ' + name;
        // 라벨 필터링: IMAP KEYWORD 검색
        this._loadLabelMessages(id, name);
    },

    _labelSearchCriteria: null,

    async _loadLabelMessages(labelId, labelName) {
        this._labelSearchCriteria = `KEYWORD label_${labelId}`;
        this.currentFolder = 'INBOX';
        this.currentPage = 1;
        await this.loadMessages();
        this._labelSearchCriteria = null;
    },

    async addLabel() {
        const name = prompt('라벨 이름:');
        if (!name) return;
        const colors = ['#ef4444','#f97316','#eab308','#22c55e','#3b82f6','#8b5cf6','#ec4899','#64748b'];
        const color = colors[Math.floor(Math.random() * colors.length)];
        await fetch('/mail/api/labels', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()},
            body: JSON.stringify({ account_id: this.accountId, name, color })
        });
        this.loadFolders(true);
    },

    // --- 메일 목록 ---
    async loadMessages() {
        const body = document.getElementById('mailListBody');
        body.innerHTML = '<div class="text-center py-4 text-muted" style="font-size:.82rem;"><span class="spinner-border spinner-border-sm"></span> 로딩 중...</div>';

        // 핀 로드는 메시지 로드와 병렬
        const unreadParam = this._unreadOnly ? '&unread_only=1' : '';
        const labelParam = this._labelSearchCriteria ? `&search_criteria=${encodeURIComponent(this._labelSearchCriteria)}` : '';
        const [, res] = await Promise.all([
            this._loadPins(),
            fetchJson(`/mail/api/messages?folder=${encodeURIComponent(this.currentFolder)}&page=${this.currentPage}&per_page=30&account=${this.accountId}${unreadParam}${labelParam}`),
        ]);
        if (res.error) {
            body.innerHTML = `<div class="text-center py-4 text-danger" style="font-size:.82rem;">${esc(res.error)}</div>`;
            return;
        }

        // 보낸편지함 판별 (먼저 선언)
        const isSentFolder = this.currentFolder.toLowerCase().includes('sent');

        const countEl = document.getElementById('mailCount');
        if (countEl) countEl.textContent = `${res.total}건`;

        if (!res.messages?.length) {
            body.innerHTML = '<div class="text-center py-4 text-muted" style="font-size:.82rem;">메일이 없습니다</div>';
            document.getElementById('paginationBar').innerHTML = '';
            return;
        }

        // 보낸편지함이면 수신확인 데이터 로드
        let receiptsMap = {};
        if (isSentFolder) {
            try {
                const rr = await fetchJson('/mail/api/receipts');
                if (Array.isArray(rr)) rr.forEach(r => { receiptsMap[r.subject] = r; });
            } catch {}
        }

        body.innerHTML = res.messages.map(m => {
            const from = isSentFolder
                ? (m.to?.[0]?.name || m.to?.[0]?.email || '(수신자)')
                : (m.from?.name || m.from?.email || '(알수없음)');
            const isUnread = !isSentFolder && !m.is_read;
            const unread = isUnread ? 'fw-bold' : '';
            const dot = isUnread ? '<span style="color:var(--mg-primary);font-size:.5rem;vertical-align:middle;">●</span> ' : '';
            const attach = m.has_attachment ? '📎' : '';

            // 수신확인 표시
            let receiptBadge = '';
            if (isSentFolder) {
                const subj = (m.subject || '').replace(/^(Re:|Fwd:)\s*/i, '');
                const receipt = receiptsMap[subj] || receiptsMap[m.subject];
                if (receipt) {
                    if (receipt.is_read) {
                        const readDate = new Date(receipt.read_at).toLocaleString('ko-KR', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
                        receiptBadge = `<span class="badge bg-success" title="읽음: ${readDate} (${receipt.read_count}회)" style="font-size:.6rem;cursor:help;">✓읽음</span>`;
                    } else {
                        receiptBadge = '<span class="badge bg-secondary" title="아직 읽지 않음" style="font-size:.6rem;cursor:help;">미확인</span>';
                    }
                }
            }

            const mode = document.getElementById('mailMode')?.value || new URLSearchParams(window.location.search).get('mode') || 'personal';
            const url = `/mail/read/${m.uid}?folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}&mode=${mode}`;
            const starred = m.is_flagged ? '★' : '☆';
            const starClass = m.is_flagged ? 'color:#eab308;' : 'color:#cbd5e1;';
            const pinned = (this._pinnedUids || []).includes(m.uid);
            const pinIcon = pinned ? '📌' : '';

            return `<div class="mail-row ${isUnread ? 'mail-unread' : ''} ${pinned ? 'mail-pinned' : ''}" draggable="true" data-uid="${m.uid}" onclick="Mail._clickRow(event,this,${m.uid},'${url}',${isUnread||false})" ondragstart="Mail._dragStart(event,${m.uid})">
                <label class="mail-col-check" onclick="event.stopPropagation()"><input type="checkbox" class="mail-check" value="${m.uid}" onchange="Mail._updateBulk()"></label>
                <div style="width:20px;flex-shrink:0;text-align:center;cursor:pointer;font-size:.8rem;${starClass}" onclick="event.stopPropagation();Mail.toggleStar(${m.uid},${!m.is_flagged})">${starred}</div>
                <div class="mail-col-from" data-email="${esc(m.from?.email||'')}" data-name="${esc(m.from?.name||'')}">${pinIcon}${esc(from)}</div>
                <div class="mail-col-subject">${esc(m.subject || '(제목 없음)')} ${receiptBadge}</div>
                <div class="mail-col-attach">${attach}</div>
                <div class="mail-col-date">${formatDate(m.date)}</div>
            </div>`;
        }).join('');

        this._renderPagination(res);
    },

    _renderPagination(data) {
        const bar = document.getElementById('paginationBar');
        if (!bar || data.pages <= 1) { if (bar) bar.innerHTML = ''; return; }
        let html = '<nav><ul class="pagination pagination-sm mb-0 justify-content-center">';
        if (data.page > 1) html += `<li class="page-item"><a class="page-link" href="#" onclick="Mail.goPage(${data.page-1});return false">‹</a></li>`;
        const start = Math.max(1, data.page - 3);
        const end = Math.min(data.pages, data.page + 3);
        for (let i = start; i <= end; i++) {
            html += `<li class="page-item ${i===data.page?'active':''}"><a class="page-link" href="#" onclick="Mail.goPage(${i});return false">${i}</a></li>`;
        }
        if (data.page < data.pages) html += `<li class="page-item"><a class="page-link" href="#" onclick="Mail.goPage(${data.page+1});return false">›</a></li>`;
        html += '</ul></nav>';
        bar.innerHTML = html;
    },

    goPage(p) { this.currentPage = p; this.loadMessages(); },

    // --- 검색 ---
    async search() {
        const q = document.getElementById('searchInput')?.value.trim();
        if (!q) { this.loadMessages(); return; }
        const body = document.getElementById('mailListBody');
        body.innerHTML = '<div class="text-center py-4 text-muted" style="font-size:.82rem;"><span class="spinner-border spinner-border-sm"></span> 검색 중...</div>';

        const res = await fetchJson(`/mail/api/search?q=${encodeURIComponent(q)}&folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}`);
        if (res.error) { body.innerHTML = `<div class="text-center py-4 text-danger" style="font-size:.82rem;">${res.error}</div>`; return; }

        const countEl = document.getElementById('mailCount');
        if (countEl) countEl.textContent = `검색결과 ${res.total}건`;

        if (!res.messages?.length) {
            body.innerHTML = '<div class="text-center py-4 text-muted" style="font-size:.82rem;">검색 결과 없음</div>';
            return;
        }
        const isSentFolder = ['Sent', 'SENT', 'Sent Messages', '보낸편지함'].includes(this.currentFolder);
        const highlight = (text, kw) => {
            if (!kw || !text) return esc(text || '');
            const escaped = esc(text);
            const escapedKw = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            return escaped.replace(new RegExp(`(${escapedKw})`, 'gi'), '<mark style="background:#fff59d;padding:0 2px;border-radius:2px;">$1</mark>');
        };
        body.innerHTML = res.messages.map(m => {
            const from = isSentFolder
                ? (m.to?.[0]?.name || m.to?.[0]?.email || '(수신자)')
                : (m.from?.name || m.from?.email || '(알수없음)');
            const isUnread = !isSentFolder && !m.is_read;
            const mode = document.getElementById('mailMode')?.value || new URLSearchParams(window.location.search).get('mode') || 'personal';
            const url = `/mail/read/${m.uid}?folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}&mode=${mode}`;
            return `<div class="mail-row ${isUnread ? 'mail-unread' : ''}" data-uid="${m.uid}" onclick="Mail._clickRow(event,this,${m.uid},'${url}',${isUnread})">
                <label class="mail-col-check" onclick="event.stopPropagation()"><input type="checkbox" class="mail-check" value="${m.uid}" onchange="Mail._updateBulk()"></label>
                <div class="mail-col-from">${highlight(from, q)}</div>
                <div class="mail-col-subject">${highlight(m.subject || '(제목 없음)', q)}</div>
                <div class="mail-col-attach">${m.has_attachment ? '📎' : ''}</div>
                <div class="mail-col-date">${formatDate(m.date)}</div>
            </div>`;
        }).join('');
        document.getElementById('paginationBar').innerHTML = '';
    },

    // --- 일괄 액션 ---
    _getSelectedUids() { return Array.from(document.querySelectorAll('.mail-check:checked')).map(c => parseInt(c.value)); },
    _updateBulk() {
        const n = this._getSelectedUids().length;
        const el = document.getElementById('bulkActions');
        if (el) el.style.display = n > 0 ? 'flex' : 'none';
    },
    markRead() { this._setFlags('\\Seen', 'add'); },
    markUnread() { this._setFlags('\\Seen', 'remove'); },
    _setFlags(flag, action) {
        const uids = this._getSelectedUids();
        if (!uids.length) return;
        fetchJson('/mail/api/flags', { method: 'POST', body: { uids, flag, action, folder: this.currentFolder, account_id: this.accountId } })
            .then(r => { if (r.success) { this._resetChecks(); this.loadMessages(); setTimeout(() => this.loadFolders(true), 500); } });
    },
    deleteSelected() {
        const uids = this._getSelectedUids();
        if (!uids.length || !confirm(`${uids.length}건을 삭제하시겠습니까?`)) return;
        fetchJson('/mail/api/messages', { method: 'DELETE', body: { uids, folder: this.currentFolder, account_id: this.accountId } })
            .then(r => { if (r.success) { this._resetChecks(); this.loadMessages(); this.loadFolders(true); } else alert(r.error); });
    },
    _resetChecks() {
        document.querySelectorAll('.mail-check').forEach(c => c.checked = false);
        const sa = document.getElementById('selectAll');
        if (sa) sa.checked = false;
        this._updateBulk();
    },

    // --- 보낸사람 컨텍스트 메뉴 ---
    _showFromMenu(event, email, name) {
        document.getElementById('fromContextMenu')?.remove();
        if (!email) return;
        const mode = document.getElementById('mailMode')?.value || 'personal';
        const dd = document.createElement('div');
        dd.id = 'fromContextMenu';
        dd.style.cssText = 'position:fixed;z-index:9999;background:#fff;border:1px solid #dee2e6;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.15);font-size:.8rem;min-width:160px;';
        dd.innerHTML = `
            <div style="padding:8px 12px;border-bottom:1px solid #f1f5f9;font-weight:600;color:#64748b;font-size:.72rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:240px;" title="${email}">${name || email}</div>
            <div class="from-menu-item" onclick="Mail._fromAction('compose','${email}')">✏️ 메일 쓰기</div>
            <div class="from-menu-item" onclick="Mail._fromAction('search','${email}')">🔍 이 사람 메일 검색</div>
            <div class="from-menu-item" onclick="Mail._fromAction('contact','${email}','${name}')">📒 주소록 추가</div>
            <div class="from-menu-item" onclick="Mail._fromAction('copy','${email}')">📋 주소 복사</div>
        `;
        dd.style.left = Math.min(event.clientX, window.innerWidth - 200) + 'px';
        dd.style.top = event.clientY + 'px';
        document.body.appendChild(dd);
        setTimeout(() => {
            const close = (e) => { if (!dd.contains(e.target)) { dd.remove(); document.removeEventListener('click', close); } };
            document.addEventListener('click', close);
        }, 10);
    },

    _fromAction(action, email, name) {
        document.getElementById('fromContextMenu')?.remove();
        const mode = document.getElementById('mailMode')?.value || new URLSearchParams(window.location.search).get('mode') || 'personal';
        if (action === 'compose') {
            location.href = `/mail/compose?mode=${mode}&account=${this.accountId}&to=${encodeURIComponent(email)}`;
        } else if (action === 'search') {
            const input = document.getElementById('searchInput');
            if (input) { input.value = email; this.search(); }
        } else if (action === 'contact') {
            this._openAddContactModal(name || email.split('@')[0], email);
        } else if (action === 'copy') {
            navigator.clipboard.writeText(email).then(() => alert('복사되었습니다.'));
        }
    },

    // 주소록 추가 모달 (메일 리스트/읽기 화면 공용, 동적 생성)
    _openAddContactModal(name, email) {
        let modalEl = document.getElementById('mailAddContactModal');
        if (!modalEl) {
            modalEl = document.createElement('div');
            modalEl.id = 'mailAddContactModal';
            modalEl.className = 'modal fade';
            modalEl.tabIndex = -1;
            modalEl.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">📒 주소록 추가</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <form id="mailAddContactForm" onsubmit="event.preventDefault(); Mail._submitAddContact();">
                                <div class="mb-3">
                                    <label class="form-label small mb-1">이름 <span class="text-danger">*</span></label>
                                    <input type="text" id="mailAddContactName" class="form-control form-control-sm" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label small mb-1">이메일 <span class="text-danger">*</span></label>
                                    <input type="email" id="mailAddContactEmail" class="form-control form-control-sm" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label small mb-1">회사</label>
                                    <input type="text" id="mailAddContactCompany" class="form-control form-control-sm">
                                </div>
                                <div class="mb-0">
                                    <label class="form-label small mb-1">메모</label>
                                    <textarea id="mailAddContactMemo" class="form-control form-control-sm" rows="2"></textarea>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-sm btn-secondary" data-bs-dismiss="modal">취소</button>
                            <button type="button" class="btn btn-sm btn-primary" onclick="Mail._submitAddContact()">저장</button>
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(modalEl);
        }
        document.getElementById('mailAddContactName').value = name || '';
        document.getElementById('mailAddContactEmail').value = email || '';
        document.getElementById('mailAddContactCompany').value = '';
        document.getElementById('mailAddContactMemo').value = '';
        const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        modal.show();
        setTimeout(() => document.getElementById('mailAddContactName')?.focus(), 200);
    },

    async _submitAddContact() {
        const name = document.getElementById('mailAddContactName').value.trim();
        const email = document.getElementById('mailAddContactEmail').value.trim();
        const company = document.getElementById('mailAddContactCompany').value.trim();
        const memo = document.getElementById('mailAddContactMemo').value.trim();
        if (!name) { alert('이름을 입력하세요.'); return; }
        if (!email) { alert('이메일을 입력하세요.'); return; }
        const r = await fetchJson('/mail/api/contacts', { method: 'POST', body: { name, email, company, memo } });
        if (r && (r.success || r.id)) {
            bootstrap.Modal.getInstance(document.getElementById('mailAddContactModal'))?.hide();
            alert('주소록에 추가되었습니다.');
        } else {
            alert(r?.error || '추가 실패');
        }
    },

    // --- 메일 클릭 → 즉시 읽음 처리 후 이동 ---
    _clickRow(event, el, uid, url, isUnread) {
        if (!event.target.closest('.mail-col-subject')) return;
        if (isUnread) {
            el.classList.remove('mail-unread');
            const folderItem = document.querySelector(`.mail-folder-item[data-folder="${this.currentFolder}"] .badge`);
            if (folderItem) {
                const n = parseInt(folderItem.textContent) - 1;
                if (n <= 0) folderItem.remove();
                else folderItem.textContent = n;
            }
            try {
                const cacheKey = `mail_folders_${this.accountId}`;
                const cached = JSON.parse(sessionStorage.getItem(cacheKey) || '{}');
                const folders = cached.folders || [];
                const f = folders.find(x => x.name === this.currentFolder);
                if (f && f.unread > 0) f.unread--;
                sessionStorage.setItem(cacheKey, JSON.stringify(cached));
            } catch {}
            fetchJson('/mail/api/flags', { method: 'POST', body: { uids: [uid], flag: '\\Seen', action: 'add', folder: this.currentFolder, account_id: this.accountId } });
        }
        location.href = url;
    },

    async openReadPane(uid) {
        const listBody = document.getElementById('mailListBody');
        const pagination = document.getElementById('paginationBar');
        const readPane = document.getElementById('mailReadPane');
        const content = document.getElementById('mailReadContent');
        if (!readPane || !content) return;

        // 목록 숨기고 읽기 패널 표시
        listBody.style.display = 'none';
        pagination.style.display = 'none';
        readPane.style.display = '';
        content.innerHTML = '<div class="text-center py-4 text-muted"><span class="spinner-border spinner-border-sm"></span> 로딩 중...</div>';

        this._readUid = uid;
        const mode = document.getElementById('mailMode')?.value || 'personal';
        const res = await fetchJson(`/mail/api/messages/${uid}?folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}`);

        if (res.error) {
            content.innerHTML = `<div class="text-center py-4 text-danger">${esc(res.error)}</div>`;
            return;
        }

        const from = `<strong>${esc(res.from?.name || '')}</strong> &lt;${esc(res.from?.email || '')}&gt;`;
        const to = (res.to || []).map(a => a.name ? `${esc(a.name)} &lt;${esc(a.email)}&gt;` : esc(a.email)).join(', ');
        const cc = (res.cc || []).map(a => esc(a.email)).join(', ');
        let dateStr = res.date || '';
        try { dateStr = new Date(dateStr).toLocaleString('ko-KR'); } catch {}

        let attachHtml = '';
        if (res.attachments?.length) {
            const zipBtn = res.attachments.length > 1
                ? `<a href="/mail/api/attachments-zip/${uid}?folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}&subject=${encodeURIComponent(res.subject || '')}" class="mail-att-link mail-att-zip" style="font-weight:600;">⬇ 전체 다운로드 (${res.attachments.length})</a><div style="flex-basis:100%;height:0;"></div>`
                : '';
            attachHtml = '<div class="mail-read-attachments">' + zipBtn + res.attachments.map(a =>
                `<a href="/mail/api/attachment/${uid}/${a.part_id}?folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}" class="mail-att-link" target="_blank">📎 ${esc(a.filename)} <span style="color:#94a3b8;font-size:.72rem;">${formatSize(a.size)}</span></a>`
            ).join('') + '</div>';
        }

        const body = res.html_body || `<pre style="font-family:inherit;white-space:pre-wrap;">${esc(res.text_body || '')}</pre>`;

        content.innerHTML = `
            <div class="mail-read-header">
                <h5>${esc(res.subject || '(제목 없음)')}</h5>
                <div class="d-flex justify-content-between align-items-start">
                    <div class="mail-read-meta">
                        <div>${from}</div>
                        <div>받는 사람: ${to}</div>
                        ${cc ? `<div>참조: ${cc}</div>` : ''}
                    </div>
                    <div style="font-size:.78rem;color:#94a3b8;white-space:nowrap;">${dateStr}</div>
                </div>
            </div>
            ${attachHtml}
            <div class="mail-read-body">${body}</div>
        `;

        // 액션 버튼
        const actions = document.getElementById('readPaneActions');
        actions.innerHTML = `
            <a href="/mail/compose?reply=${uid}&folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}&mode=${mode}" class="btn btn-sm btn-outline-primary">↩ 답장</a>
            <a href="/mail/compose?reply_all=${uid}&folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}&mode=${mode}" class="btn btn-sm btn-outline-primary">↩ 전체답장</a>
            <a href="/mail/compose?forward=${uid}&folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}&mode=${mode}" class="btn btn-sm btn-outline-secondary">→ 전달</a>
            <button class="btn btn-sm btn-outline-secondary" onclick="Mail.printMail(${uid})">🖨</button>
            <button class="btn btn-sm btn-outline-danger" onclick="Mail._deleteFromPane(${uid})">삭제</button>
        `;

        // 공유 읽음 표시
        fetchJson('/mail/api/shared-read', { method: 'POST', body: { account_id: this.accountId, uid, folder: this.currentFolder } });
        fetchJson(`/mail/api/shared-read?account=${this.accountId}&uid=${uid}&folder=${encodeURIComponent(this.currentFolder)}`)
            .then(readers => {
                if (readers?.length) {
                    const badge = readers.map(r => `<span class="badge bg-light text-dark border" style="font-size:.68rem;">${r.name} ${r.position} ${r.read_at}</span>`).join(' ');
                    content.querySelector('.mail-read-header')?.insertAdjacentHTML('beforeend',
                        `<div class="mt-2" style="font-size:.72rem;color:#94a3b8;">👁 읽은 사람: ${badge}</div>`
                    );
                }
            });
    },

    closeReadPane() {
        const listBody = document.getElementById('mailListBody');
        const pagination = document.getElementById('paginationBar');
        const readPane = document.getElementById('mailReadPane');
        if (listBody) listBody.style.display = '';
        if (pagination) pagination.style.display = '';
        if (readPane) readPane.style.display = 'none';
    },

    async _deleteFromPane(uid) {
        if (!confirm('이 메일을 삭제하시겠습니까?')) return;
        const res = await fetchJson('/mail/api/messages', {
            method: 'DELETE',
            body: { uids: [uid], folder: this.currentFolder, account_id: this.accountId }
        });
        if (res.success) {
            this.closeReadPane();
            this.loadMessages();
            setTimeout(() => this.loadFolders(true), 500);
        } else alert(res.error);
    },

    // --- 별표 토글 ---
    async toggleStar(uid, starred) {
        await fetchJson('/mail/api/star', { method: 'POST', body: { account_id: this.accountId, uid, folder: this.currentFolder, starred } });
        this.loadMessages();
    },

    // --- 핀 토글 ---
    async togglePin(uid) {
        await fetchJson('/mail/api/pin', { method: 'POST', body: { account_id: this.accountId, uid, folder: this.currentFolder } });
        this.loadMessages();
    },

    // --- 핀 목록 로드 ---
    _pinnedUids: [],
    async _loadPins() {
        const res = await fetchJson(`/mail/api/pins?account=${this.accountId}&folder=${this.currentFolder}`);
        this._pinnedUids = res || [];
    },

    // --- 일괄 폴더 이동 ---
    moveSelected() {
        const uids = this._getSelectedUids();
        if (!uids.length) return;
        // 기존 드롭다운 제거
        document.getElementById('moveFolderDropdown')?.remove();
        const btn = document.querySelector('[onclick="Mail.moveSelected()"]');
        if (!btn) return;
        const folders = this._lastFolders || [];
        const items = folders.map(f => f.name).filter(n => n !== this.currentFolder);
        const dd = document.createElement('div');
        dd.id = 'moveFolderDropdown';
        dd.style.cssText = 'position:absolute;z-index:9999;background:#fff;border:1px solid #dee2e6;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.15);max-height:300px;overflow-y:auto;min-width:200px;font-size:.8rem;';
        dd.innerHTML = items.map(n => {
            const label = n.split('.').pop().split('/').pop();
            return `<div style="padding:6px 12px;cursor:pointer;white-space:nowrap;" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background=''" onclick="Mail._doMove('${n.replace(/'/g,"\\'")}')">📁 ${label}</div>`;
        }).join('');
        // 위치
        const rect = btn.getBoundingClientRect();
        dd.style.top = (rect.bottom + window.scrollY + 2) + 'px';
        dd.style.left = rect.left + 'px';
        document.body.appendChild(dd);
        // 외부 클릭 시 닫기
        setTimeout(() => {
            const close = (e) => { if (!dd.contains(e.target)) { dd.remove(); document.removeEventListener('click', close); } };
            document.addEventListener('click', close);
        }, 10);
    },

    async _doMove(dest) {
        document.getElementById('moveFolderDropdown')?.remove();
        const uids = this._getSelectedUids();
        if (!uids.length) return;
        const res = await fetchJson('/mail/api/move-bulk', {
            method: 'POST',
            body: { account_id: this.accountId, uids, src_folder: this.currentFolder, dest_folder: dest }
        });
        if (res.success) { this._resetChecks(); this.loadMessages(); this.loadFolders(true); }
        else alert(res.error || '이동 실패');
    },

    // --- 드래그앤드롭 폴더 이동 ---
    _dragStart(e, uid) {
        e.dataTransfer.setData('text/plain', JSON.stringify({ uids: [uid], src_folder: this.currentFolder }));
        e.dataTransfer.effectAllowed = 'move';
    },

    _initFolderDrop() {
        document.querySelectorAll('.mail-folder-item[data-folder]').forEach(el => {
            el.addEventListener('dragover', e => { e.preventDefault(); el.style.background = '#c7d2fe'; });
            el.addEventListener('dragleave', () => { el.style.background = ''; });
            el.addEventListener('drop', async e => {
                e.preventDefault(); el.style.background = '';
                const data = JSON.parse(e.dataTransfer.getData('text/plain'));
                const dest = el.dataset.folder;
                if (dest === data.src_folder) return;
                // 선택된 메일도 포함
                const selected = this._getSelectedUids();
                const uids = [...new Set([...data.uids, ...selected])];
                const res = await fetchJson('/mail/api/move-bulk', {
                    method: 'POST',
                    body: { account_id: this.accountId, uids, src_folder: data.src_folder, dest_folder: dest }
                });
                if (res.success) { this.loadMessages(); this.loadFolders(true); }
            });
        });
    },

    // --- 인쇄 ---
    printMail(uid) {
        window.open(`/mail/print/${uid}?folder=${encodeURIComponent(this.currentFolder)}&account=${this.accountId}`, '_blank', 'width=800,height=600');
    },

    // --- 새 메일 폴링 + 자동 새로고침 ---
    _lastUnread: null,
    async checkNewMail() {
        if (!this.accountId) return;
        // 가벼운 엔드포인트: INBOX UNSEEN 만 RTT 1번
        const res = await fetchJson(`/mail/api/inbox-unread?account=${this.accountId}`);
        if (res.error || typeof res.unread !== 'number') return;
        const unread = res.unread;
        if (this._lastUnread !== null && unread > this._lastUnread) {
            const diff = unread - this._lastUnread;
            if ('Notification' in window && Notification.permission === 'granted') {
                try { new Notification('새 메일', { body: `${diff}건의 새 메일이 도착했습니다.`, icon: '/static/img/logo.png' }); } catch {}
            }
            // INBOX + 1페이지 + 체크된 메일 없을 때만 리스트 자동 갱신 (사용자 컨텍스트 보호)
            const onInbox = (this.currentFolder || '').toLowerCase() === 'inbox';
            const onFirstPage = !this.currentPage || this.currentPage === 1;
            const anyChecked = document.querySelectorAll('#mailListBody input[type="checkbox"]:checked').length > 0;
            if (onInbox && onFirstPage && !anyChecked) {
                this.loadMessages();
            }
            // 사이드바 unread 카운트도 갱신 (refresh=1 로 캐시 우회)
            this.loadFolders(true);
        }
        this._lastUnread = unread;
    },

    // --- 계정 탭 드래그 순서 변경 ---
    initTabDrag() {
        const tabs = document.querySelector('.mail-account-tabs');
        if (!tabs) return;
        let dragEl = null;
        tabs.querySelectorAll('.mail-account-tab').forEach(tab => {
            tab.draggable = true;
            tab.addEventListener('dragstart', (e) => { dragEl = tab; tab.style.opacity = '.5'; });
            tab.addEventListener('dragend', () => { if (dragEl) dragEl.style.opacity = ''; dragEl = null; });
            tab.addEventListener('dragover', (e) => { e.preventDefault(); tab.classList.add('drag-over'); });
            tab.addEventListener('dragleave', () => { tab.classList.remove('drag-over'); });
            tab.addEventListener('drop', (e) => {
                e.preventDefault();
                tab.classList.remove('drag-over');
                if (!dragEl || dragEl === tab) return;
                const allTabs = [...tabs.querySelectorAll('.mail-account-tab')];
                const fromIdx = allTabs.indexOf(dragEl);
                const toIdx = allTabs.indexOf(tab);
                if (fromIdx < toIdx) tab.after(dragEl);
                else tab.before(dragEl);
                // 서버에 순서 저장 (외부메일은 별도 API)
                const order = [...tabs.querySelectorAll('.mail-account-tab')].map(t => parseInt(t.dataset.accountId));
                const orderUrl = this.mode === 'external' ? '/mail/api/external-order' : '/mail/api/shared-order';
                fetchJson(orderUrl, { method: 'POST', body: { order } });
            });
        });
    },

    startNotification() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
        // 30초 폴링 — INBOX UNSEEN 만 가볍게 확인
        setInterval(() => this.checkNewMail(), 30000);
    },
};


// =========================================================================
// MailRead — 메일 본문 페이지
// =========================================================================
const MailRead = {
    uid: null,
    folder: null,
    accountId: null,

    async init(uid, folder, accountId) {
        this.uid = uid;
        this.folder = folder;
        this.accountId = accountId;

        const res = await fetchJson(`/mail/api/messages/${uid}?folder=${encodeURIComponent(folder)}&account=${accountId}`);
        const el = document.getElementById('mailContent');

        if (res.error) {
            el.innerHTML = `<div class="text-center py-5 text-danger">${esc(res.error)}</div>`;
            return;
        }

        const from = `<strong>${esc(res.from?.name || '')}</strong> &lt;${esc(res.from?.email || '')}&gt;`;
        const to = (res.to || []).map(a => a.name ? `${esc(a.name)} &lt;${esc(a.email)}&gt;` : esc(a.email)).join(', ');
        const cc = (res.cc || []).map(a => a.name ? `${esc(a.name)} &lt;${esc(a.email)}&gt;` : esc(a.email)).join(', ');

        let dateStr = res.date || '';
        try { dateStr = new Date(dateStr).toLocaleString('ko-KR'); } catch {}

        let attachHtml = '';
        if (res.attachments?.length) {
            const zipBtn = res.attachments.length > 1
                ? `<a href="/mail/api/attachments-zip/${uid}?folder=${encodeURIComponent(folder)}&account=${accountId}&subject=${encodeURIComponent(res.subject || '')}" class="mail-att-link mail-att-zip" style="font-weight:600;">⬇ 전체 다운로드 (${res.attachments.length})</a><div style="flex-basis:100%;height:0;"></div>`
                : '';
            attachHtml = '<div class="mail-read-attachments">' + zipBtn + res.attachments.map(a =>
                `<a href="/mail/api/attachment/${uid}/${a.part_id}?folder=${encodeURIComponent(folder)}&account=${accountId}" class="mail-att-link" target="_blank">
                    📎 ${esc(a.filename)} <span style="color:var(--mg-subtle);font-size:.72rem;">${formatSize(a.size)}</span>
                </a>`
            ).join('') + '</div>';
        }

        const body = res.html_body || `<pre style="font-family:inherit;white-space:pre-wrap;">${esc(res.text_body || '')}</pre>`;

        el.innerHTML = `
            <div class="mail-read-header">
                <h5>${esc(res.subject || '(제목 없음)')}</h5>
                <div class="d-flex justify-content-between align-items-start">
                    <div class="mail-read-meta">
                        <div>보낸 사람: ${res.from?.name ? `<strong>${esc(res.from.name)}</strong> &lt;${esc(res.from.email || '')}&gt;` : esc(res.from?.email || '')}</div>
                        <div>받는 사람: ${to}</div>
                        ${cc ? `<div>참조: ${cc}</div>` : ''}
                    </div>
                    <div style="font-size:.78rem;color:var(--mg-subtle);white-space:nowrap;">${dateStr}</div>
                </div>
            </div>
            ${attachHtml}
            <div class="mail-read-body">${body}</div>
        `;

        // 본문 링크 보정: 스킴 없는 도메인 링크(www.x.com)는 현재 페이지(/mail/read/..) 기준
        // 상대경로로 잘못 풀리므로 https:// 를 붙이고, 모든 링크는 새 탭으로 연다.
        el.querySelectorAll('.mail-read-body a').forEach(a => {
            const href = a.getAttribute('href') || '';
            if (href && !/^([a-z][a-z0-9+.-]*:|#|\/)/i.test(href)) {
                a.setAttribute('href', 'https://' + href);
            }
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noopener noreferrer');
        });

        // 본문 이미지 보정: http:// 이미지는 HTTPS 페이지에서 mixed-content로 차단되므로
        // https 로 승격 시도. 스킴 없는 상대경로도 https:// 로 보정.
        el.querySelectorAll('.mail-read-body img').forEach(img => {
            const src = img.getAttribute('src') || '';
            if (src.startsWith('http://')) {
                img.setAttribute('src', 'https://' + src.slice('http://'.length));
            } else if (src && !/^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(src)) {
                img.setAttribute('src', 'https://' + src);
            }
        });

        // Web Bug / 트래킹 픽셀 숨김 (로드는 하되 화면에서 안 보이게)
        el.querySelectorAll('.mail-read-body img').forEach(img => {
            const w = parseInt(img.getAttribute('width')) || img.naturalWidth;
            const h = parseInt(img.getAttribute('height')) || img.naturalHeight;
            if ((w <= 3 && h <= 3) || img.src.includes('open') || img.src.includes('track') || img.src.includes('beacon') || img.src.includes('stibee') || img.src.includes('pixel')) {
                img.style.cssText = 'width:0!important;height:0!important;overflow:hidden!important;position:absolute!important;display:block!important;';
            }
        });

        // 공유 읽음 표시 기록
        fetchJson('/mail/api/shared-read', {
            method: 'POST',
            body: { account_id: this.accountId, uid: this.uid, folder: this.folder }
        });

        // 공유 읽음 사용자 표시
        fetchJson(`/mail/api/shared-read?account=${this.accountId}&uid=${this.uid}&folder=${encodeURIComponent(this.folder)}`)
            .then(readers => {
                if (readers?.length) {
                    const badge = readers.map(r => `<span class="badge bg-light text-dark border" style="font-size:.68rem;">${r.name} ${r.position} ${r.read_at}</span>`).join(' ');
                    el.querySelector('.mail-read-header')?.insertAdjacentHTML('beforeend',
                        `<div class="mt-2" style="font-size:.72rem;color:#94a3b8;">👁 읽은 사람: ${badge}</div>`
                    );
                }
            });

        // 삭제 버튼
        document.getElementById('deleteBtn')?.addEventListener('click', () => {
            if (!confirm('이 메일을 삭제하시겠습니까?')) return;
            const mode = new URLSearchParams(window.location.search).get('mode') || 'personal';
            fetchJson('/mail/api/messages', {
                method: 'DELETE',
                body: { uids: [this.uid], folder: this.folder, account_id: this.accountId }
            }).then(r => {
                if (r.success) history.back();
                else alert(r.error);
            });
        });
    },
};


// =========================================================================
// MailCompose — 메일 작성
// =========================================================================
const MailCompose = {
    _files: [],
    _forwardAttachments: [],   // 전달 시 원본 첨부파일 메타 [{part_id, filename, size, content_type}]
    _forwardSourceUid: null,
    _forwardAccountId: null,
    _forwardFolder: 'INBOX',

    init() {
        this.bindEvents();
        this.initTagInput('toTagWrap', 'toTagInput', 'toInput', 'toSuggest');
        this.initTagInput('ccTagWrap', 'ccTagInput', 'ccInput', 'ccSuggest');
        this._insertSignature();
        this.initTagInput('bccTagWrap', 'bccTagInput', 'bccInput', null);
        this.initDropZone();
    },

    // --- 태그 입력 (#7, #8) ---
    initTagInput(wrapId, inputId, hiddenId, suggestId) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const separators = [',', ';', ' '];
        let suggestTimer = null;

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const v = input.value.trim().replace(/[,;]/g, '');
                if (v && v.includes('@')) { this.addTag(wrapId, v); input.value = ''; this._syncHidden(wrapId, hiddenId); }
            }
            if (e.key === 'Tab') {
                const v = input.value.trim().replace(/[,;]/g, '');
                if (v && v.includes('@')) {
                    e.preventDefault();
                    this.addTag(wrapId, v); input.value = ''; this._syncHidden(wrapId, hiddenId);
                }
                // 입력값 없으면 기본 Tab 동작 (다음 필드 이동) — preventDefault 안 함
            }
            if (e.key === 'Backspace' && !input.value) {
                const tags = document.getElementById(wrapId).querySelectorAll('.mail-tag');
                if (tags.length) { tags[tags.length - 1].remove(); this._syncHidden(wrapId, hiddenId); }
            }
        });

        input.addEventListener('input', () => {
            const v = input.value;
            const last = v.slice(-1);
            if (separators.includes(last)) {
                const email = v.slice(0, -1).trim().replace(/[,;]/g, '');
                if (email && email.includes('@')) { this.addTag(wrapId, email); input.value = ''; this._syncHidden(wrapId, hiddenId); }
                else input.value = email;
            }
            // suggest
            if (suggestId) {
                clearTimeout(suggestTimer);
                suggestTimer = setTimeout(() => this._suggest(input, document.getElementById(suggestId), wrapId, hiddenId), 300);
            }
        });

        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = (e.clipboardData || window.clipboardData).getData('text');
            const emails = text.split(/[,;\s\n]+/).map(s => s.trim()).filter(s => s.includes('@'));
            emails.forEach(em => this.addTag(wrapId, em));
            this._syncHidden(wrapId, hiddenId);
        });

        input.addEventListener('blur', () => {
            const v = input.value.trim().replace(/[,;]/g, '');
            if (v && v.includes('@')) { this.addTag(wrapId, v); input.value = ''; this._syncHidden(wrapId, hiddenId); }
            if (suggestId) setTimeout(() => { const d = document.getElementById(suggestId); if (d) { d.innerHTML = ''; d.style.display = 'none'; } }, 200);
        });
    },

    addTag(wrapId, email) {
        email = email.trim();
        if (!email) return;
        const wrap = document.getElementById(wrapId);
        // 중복 방지
        const existing = wrap.querySelectorAll('.mail-tag .tag-email');
        for (const el of existing) { if (el.textContent === email) return; }
        const tag = document.createElement('span');
        tag.className = 'mail-tag';
        tag.innerHTML = `<span class="tag-email">${esc(email)}</span><span class="tag-remove" onclick="this.parentElement.remove();MailCompose._syncFromWrap('${wrapId}')">×</span>`;
        wrap.insertBefore(tag, wrap.querySelector('.mail-tag-input'));
    },

    _syncHidden(wrapId, hiddenId) {
        const wrap = document.getElementById(wrapId);
        const hidden = document.getElementById(hiddenId);
        if (!wrap || !hidden) return;
        const emails = [...wrap.querySelectorAll('.mail-tag .tag-email')].map(el => el.textContent);
        hidden.value = emails.join(', ');
    },

    _syncFromWrap(wrapId) {
        const map = { toTagWrap: 'toInput', ccTagWrap: 'ccInput', bccTagWrap: 'bccInput' };
        this._syncHidden(wrapId, map[wrapId]);
    },

    _insertSignature() {
        const sig = this._userSignatureHtml;
        if (!sig) return;
        // 다시보내기는 원본 본문 그대로 — 서명 중복 방지
        if (this._isResend) return;
        // 외부메일은 서명 자동적용 안 함
        const mode = document.getElementById('mailMode')?.value;
        if (mode === 'external') return;
        const body = document.getElementById('mailBody');
        if (!body) return;
        const sigHtml = `<div id="mail-signature" style="margin-top:16px;padding-top:8px;font-size:13px;">${sig}</div>`;
        // 답장/전달 인용문 앞에 서명 삽입
        const quoted = body.querySelector('div[style*="border-left"]') || body.querySelector('div[style*="border-top"]');
        if (quoted) {
            quoted.insertAdjacentHTML('beforebegin', '<br>' + sigHtml);
        } else {
            body.innerHTML = body.innerHTML + '<br>' + sigHtml;
        }
    },

    bindEvents() {
        document.getElementById('sendBtn')?.addEventListener('click', () => this.send());
        document.getElementById('draftBtn')?.addEventListener('click', () => alert('임시저장은 준비 중입니다.'));
        document.getElementById('fromAccount')?.addEventListener('change', (e) => {
            document.getElementById('accountId').value = e.target.value;
        });

        // Tab 순서: 받는사람 → 참조 → 제목 → 본문
        const tabOrder = ['toTagInput', 'ccTagInput', 'subjectInput', 'mailBody'];
        tabOrder.forEach((id, i) => {
            document.getElementById(id)?.addEventListener('keydown', (e) => {
                if (e.key === 'Tab' && !e.shiftKey && id !== 'mailBody') {
                    e.preventDefault();
                    const next = document.getElementById(tabOrder[i + 1]);
                    if (next) next.focus();
                }
                if (e.key === 'Tab' && e.shiftKey && id !== 'toTagInput' && id !== 'mailBody') {
                    e.preventDefault();
                    const prev = document.getElementById(tabOrder[i - 1]);
                    if (prev) prev.focus();
                }
            });
        });

        // 본문에서 Tab → 들여쓰기, Shift+Tab → 내어쓰기
        document.getElementById('mailBody')?.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                if (e.shiftKey) {
                    document.execCommand('outdent');
                } else {
                    document.execCommand('indent');
                }
            }
        });
    },

    // --- 드래그앤드롭 ---
    initDropZone() {
        const zone = document.getElementById('dropZone');
        const input = document.getElementById('fileInput');
        if (!zone || !input) return;

        ['dragenter', 'dragover'].forEach(e => zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.add('dragover'); }));
        ['dragleave', 'drop'].forEach(e => zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.remove('dragover'); }));

        zone.addEventListener('drop', (ev) => {
            const files = ev.dataTransfer?.files;
            if (files) this.addFiles(files);
        });

        zone.addEventListener('click', (ev) => {
            if (ev.target.tagName !== 'LABEL') input.click();
        });

        input.addEventListener('change', () => {
            if (input.files) this.addFiles(input.files);
            input.value = '';
        });

        // 페이지 전체 드래그도 지원
        document.addEventListener('dragover', (ev) => ev.preventDefault());
        document.addEventListener('drop', (ev) => {
            ev.preventDefault();
            if (ev.dataTransfer?.files?.length) this.addFiles(ev.dataTransfer.files);
        });
    },

    addFiles(fileList) {
        for (let i = 0; i < fileList.length; i++) {
            const f = fileList[i];
            // 중복 체크
            if (this._files.some(ex => ex.name === f.name && ex.size === f.size)) continue;
            this._files.push(f);
        }
        this.renderFileList();
    },

    removeFile(idx) {
        this._files.splice(idx, 1);
        this.renderFileList();
    },

    removeForwardAttachment(btn) {
        const item = btn.closest('.mail-file-item');
        const idx = parseInt(item.dataset.idx);
        this._forwardAttachments = this._forwardAttachments.filter((_, i) => i !== idx);
        item.remove();
        // 남은 항목의 data-idx 재정렬
        document.querySelectorAll('#forwardAttachments .mail-file-item').forEach((el, i) => {
            el.dataset.idx = i;
        });
    },

    renderFileList() {
        const el = document.getElementById('fileList');
        if (!el) return;
        if (!this._files.length) { el.innerHTML = ''; return; }

        el.innerHTML = this._files.map((f, i) => {
            const isLarge = f.size > 25 * 1024 * 1024;
            const badge = isLarge ? '<span class="file-badge-large">📦 대용량 (링크 전환)</span>' : '';
            return `<div class="mail-file-item">
                <div>📄 ${esc(f.name)} <span class="file-size">${formatSize(f.size)}</span> ${badge}</div>
                <button class="file-remove" onclick="MailCompose.removeFile(${i})" title="제거">×</button>
            </div>`;
        }).join('');
    },

    send() {
        // hidden 필드 동기화
        this._syncHidden('toTagWrap', 'toInput');
        this._syncHidden('ccTagWrap', 'ccInput');
        this._syncHidden('bccTagWrap', 'bccInput');

        const to = document.getElementById('toInput')?.value?.trim();
        if (!to) { alert('받는사람을 입력하세요.'); return; }

        const mode = document.getElementById('mailMode')?.value;
        const fromSelect = document.getElementById('fromAccount');
        const accountCount = fromSelect ? fromSelect.options.length : 0;

        // 공용메일이고 계정 2개 이상이면 확인 모달
        if (mode === 'shared' && accountCount >= 2) {
            this._showConfirmModal();
            return;
        }

        // 그 외 바로 발송
        this._doSend();
    },

    _showConfirmModal() {
        const fromSelect = document.getElementById('fromAccount');
        const confirmFrom = document.getElementById('confirmFromAccount');
        if (confirmFrom && fromSelect) confirmFrom.value = fromSelect.value;

        document.getElementById('confirmTo').textContent = document.getElementById('toInput')?.value || '';
        const cc = document.getElementById('ccInput')?.value?.trim();
        const ccRow = document.getElementById('confirmCcRow');
        if (cc) { document.getElementById('confirmCc').textContent = cc; ccRow.style.display = ''; }
        else { ccRow.style.display = 'none'; }
        document.getElementById('confirmSubject').textContent = document.getElementById('subjectInput')?.value || '(제목 없음)';

        new bootstrap.Modal(document.getElementById('sendConfirmModal')).show();
    },

    confirmedSend() {
        // 모달에서 변경한 보내는 사람 반영
        const confirmFrom = document.getElementById('confirmFromAccount');
        const fromSelect = document.getElementById('fromAccount');
        if (confirmFrom && fromSelect) {
            fromSelect.value = confirmFrom.value;
            document.getElementById('accountId').value = confirmFrom.value;
        }
        bootstrap.Modal.getInstance(document.getElementById('sendConfirmModal'))?.hide();
        this._doSend();
    },

    async _doSend() {
        const form = document.getElementById('composeForm');
        const fd = new FormData(form);
        let bodyHtml = document.getElementById('mailBody')?.innerHTML || '';
        const accountId = document.getElementById('accountId')?.value || document.getElementById('fromAccount')?.value || '';
        fd.set('account_id', accountId);
        const mode = document.getElementById('mailMode')?.value;

        const MAX_ATTACH = 25 * 1024 * 1024;  // 25MB
        const normalFiles = [];
        const largeFiles = [];

        for (const f of this._files) {
            if (f.size > MAX_ATTACH) largeFiles.push(f);
            else normalFiles.push(f);
        }

        // 일반 첨부 합계 체크
        let normalTotal = normalFiles.reduce((s, f) => s + f.size, 0);
        if (normalTotal > MAX_ATTACH) {
            alert(`일반 첨부파일 합계 ${(normalTotal/1048576).toFixed(1)}MB — 25MB 초과.\n큰 파일은 자동으로 다운로드 링크로 전환됩니다.`);
            return;
        }

        const btn = document.getElementById('sendBtn');
        btn.disabled = true;

        // 대용량 파일 → Storage 업로드 → 본문에 링크 삽입
        if (largeFiles.length) {
            let linkHtml = '<br><hr style="border-color:#e2e8f0;"><p style="color:#64748b;font-size:13px;">📎 <strong>대용량 첨부파일</strong></p><table style="border-collapse:collapse;font-size:13px;">';
            const internalHost = 'http://192.168.0.110:8501';

            for (let i = 0; i < largeFiles.length; i++) {
                const lf = largeFiles[i];
                try {
                    const r = await new Promise((resolve, reject) => {
                        const xhr = new XMLHttpRequest();
                        const startTime = Date.now();

                        xhr.upload.addEventListener('progress', (e) => {
                            if (!e.lengthComputable) return;
                            const pct = Math.round((e.loaded / e.total) * 100);
                            const elapsed = (Date.now() - startTime) / 1000;
                            const speed = e.loaded / elapsed;
                            const remain = elapsed > 0 ? ((e.total - e.loaded) / speed) : 0;
                            const speedStr = speed > 1048576 ? (speed / 1048576).toFixed(1) + 'MB/s' : (speed / 1024).toFixed(0) + 'KB/s';
                            const remainStr = remain > 60 ? Math.round(remain / 60) + '분' : Math.round(remain) + '초';
                            btn.textContent = `${esc(lf.name)} ${pct}% · ${speedStr} · 남은시간 ${remainStr}`;
                        });

                        xhr.upload.addEventListener('loadend', () => {
                            btn.textContent = `${esc(lf.name)} — 서버 처리 중...`;
                        });
                        xhr.addEventListener('load', () => {
                            if (xhr.status >= 200 && xhr.status < 300) {
                                try { resolve(JSON.parse(xhr.responseText)); }
                                catch { reject(new Error('응답 파싱 실패')); }
                            } else {
                                try { const j = JSON.parse(xhr.responseText); reject(new Error(j.error || `HTTP ${xhr.status}`)); }
                                catch { reject(new Error(`업로드 실패 (${xhr.status})`)); }
                            }
                        });
                        xhr.addEventListener('error', () => reject(new Error('네트워크 오류')));
                        xhr.addEventListener('abort', () => reject(new Error('업로드 취소됨')));

                        const lfFd = new FormData();
                        lfFd.append('file', lf);
                        xhr.open('POST', internalHost + '/mail/api/upload-large');
                        xhr.withCredentials = true;
                        xhr.send(lfFd);
                    });

                    if (!r.success) { alert(`업로드 실패: ${r.error}`); btn.disabled = false; btn.textContent = '보내기'; return; }

                    linkHtml += `<tr style="border-bottom:1px solid #f1f5f9;">
                        <td style="padding:6px 12px;">📄 <a href="${r.download_url}" style="color:#2563eb;">${esc(r.filename)}</a></td>
                        <td style="padding:6px 12px;color:#94a3b8;">${formatSize(r.size)}</td>
                        <td style="padding:6px 12px;color:#dc2626;font-size:12px;">⏰ ${r.expires_at}까지 다운로드 가능</td>
                    </tr>`;
                } catch (e) {
                    alert(`업로드 오류: ${e.message}`);
                    btn.disabled = false; btn.textContent = '보내기'; return;
                }
            }
            linkHtml += '</table>';
            bodyHtml += linkHtml;
        }

        fd.set('body', bodyHtml);
        // 일반 첨부만 FormData에 추가
        normalFiles.forEach(f => fd.append('attachments', f));

        // 전달 시 원본 첨부파일 정보 포함
        if (this._forwardAttachments.length && this._forwardSourceUid) {
            fd.set('forward_source_uid', this._forwardSourceUid);
            fd.set('forward_account_id', this._forwardAccountId);
            fd.set('forward_folder', this._forwardFolder);
            fd.set('forward_parts', JSON.stringify(this._forwardAttachments.map(a => a.part_id)));
        }

        btn.textContent = '발송 중...';
        try {
            const resp = await fetch('/mail/api/send', { method: 'POST', headers: { 'X-CSRFToken': csrfToken() }, body: fd });
            if (!resp.ok) {
                alert('발송 실패 (서버 오류 ' + resp.status + ')');
                return;
            }
            const res = await resp.json();
            if (res.success) { alert('메일이 발송되었습니다.'); location.href = mode === 'external' ? '/mail/external' : (mode === 'shared' ? '/mail/shared' : '/mail/personal'); }
            else alert(res.error || '발송 실패');
        } catch (e) { alert('발송 오류: ' + e.message); }
        finally { btn.disabled = false; btn.textContent = '보내기'; }
    },

    async _suggest(input, dropdown, wrapId, hiddenId) {
        const q = input.value.trim();
        if (q.length < 1) { dropdown.style.display = 'none'; return; }
        const res = await fetchJson(`/mail/api/contacts/suggest?q=${encodeURIComponent(q)}`);
        if (!res?.length) { dropdown.style.display = 'none'; return; }
        dropdown.style.display = 'block';
        dropdown.innerHTML = res.map(c =>
            `<div class="suggest-item" onmousedown="MailCompose.addTag('${wrapId}','${c.email}');MailCompose._syncHidden('${wrapId}','${hiddenId}');document.getElementById('${input.id}').value='';document.getElementById('${dropdown.id}').style.display='none';">
                <strong>${esc(c.name)}</strong> &lt;${esc(c.email)}&gt;
                ${c.type === 'internal' ? '<span class="badge bg-info">사내</span>' : ''}
            </div>`
        ).join('');
    },

    // --- 주소록 모달 (#9) ---
    async showContacts() {
        const modal = new bootstrap.Modal(document.getElementById('contactsModal'));
        modal.show();
        const res = await fetchJson('/mail/api/contacts/suggest?q=&limit=200');
        const body = document.getElementById('contactModalBody');
        if (!res?.length) { body.innerHTML = '<tr><td colspan="4" class="text-center text-muted">주소록이 비어있습니다.</td></tr>'; return; }
        body.innerHTML = res.map(c =>
            `<tr><td><input type="checkbox" class="contact-pick" value="${esc(c.email)}"></td><td>${esc(c.name)} ${c.type === 'internal' ? '<span class="badge bg-info" style="font-size:.65rem;">사내</span>' : ''}</td><td>${esc(c.email)}</td><td>${esc(c.company || '')}</td></tr>`
        ).join('');
        document.getElementById('contactModalSearch')?.addEventListener('input', function() {
            const q = this.value.toLowerCase();
            body.querySelectorAll('tr').forEach(tr => {
                tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
        });
    },

    // --- 예약발송 ---
    async scheduleSend() {
        this._syncHidden('toTagWrap', 'toInput');
        this._syncHidden('ccTagWrap', 'ccInput');
        this._syncHidden('bccTagWrap', 'bccInput');
        const to = document.getElementById('toInput')?.value?.trim();
        if (!to) { alert('받는사람을 입력하세요.'); return; }
        const dt = prompt('예약 발송 시간을 입력하세요.\n형식: 2026-04-02 14:00');
        if (!dt) return;
        const accountId = document.getElementById('accountId')?.value || document.getElementById('fromAccount')?.value;
        const body = document.getElementById('mailBody')?.innerHTML || '';
        const r = await fetchJson('/mail/api/schedule', {
            method: 'POST',
            body: {
                account_id: parseInt(accountId),
                to, cc: document.getElementById('ccInput')?.value || '',
                bcc: document.getElementById('bccInput')?.value || '',
                subject: document.getElementById('subjectInput')?.value || '',
                body, scheduled_at: dt,
            }
        });
        if (r.success) alert(`예약 완료! ${dt}에 발송됩니다.`);
        else alert(r.error || '예약 실패');
    },

    // --- 템플릿 불러오기 ---
    async loadTemplate() {
        const r = await fetchJson('/mail/api/templates');
        if (!r?.length) { alert('저장된 템플릿이 없습니다.\n메일 설정 → 템플릿에서 추가하세요.'); return; }
        const list = document.getElementById('templateList');
        list.innerHTML = r.map(t =>
            `<div class="px-3 py-2 border-bottom" style="cursor:pointer;font-size:.85rem;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background=''" onclick="MailCompose._applyTemplate(${t.id})">
                <div class="fw-bold">${esc(t.name)}</div>
                <div class="text-muted small">${esc(t.subject || '제목 없음')}${t.is_shared ? ' <span class=badge bg-info>공유</span>' : ''}</div>
            </div>`
        ).join('');
        this._templateCache = r;
        new bootstrap.Modal(document.getElementById('templateModal')).show();
    },

    _templateCache: [],
    _applyTemplate(id) {
        const t = this._templateCache.find(x => x.id === id);
        if (!t) return;
        if (t.subject) document.getElementById('subjectInput').value = t.subject;
        if (t.body) {
            const body = document.getElementById('mailBody');
            // 서명 블록 보존: 서명 앞에 템플릿 본문 삽입
            const sig = body.querySelector('#mail-signature');
            const html = t.body.replace(/\n/g, '<br>');
            if (sig) { sig.insertAdjacentHTML('beforebegin', html); }
            else { body.innerHTML = html; }
        }
        if (t.to_addresses) {
            t.to_addresses.split(',').map(e => e.trim()).filter(Boolean).forEach(e => this.addTag('toTagWrap', e));
            this._syncHidden('toTagWrap', 'toInput');
        }
        bootstrap.Modal.getInstance(document.getElementById('templateModal'))?.hide();
    },

    insertContacts() {
        const checked = document.querySelectorAll('.contact-pick:checked');
        checked.forEach(c => { this.addTag('toTagWrap', c.value); c.checked = false; });
        this._syncHidden('toTagWrap', 'toInput');
        bootstrap.Modal.getInstance(document.getElementById('contactsModal'))?.hide();
    },
};


// =========================================================================
// MailSettings — 설정
// =========================================================================
const MailSettings = {
    init() {
        document.getElementById('accountForm')?.addEventListener('submit', (e) => { e.preventDefault(); this.saveAccount(); });
        document.getElementById('testConnBtn')?.addEventListener('click', () => this.testConnection());
        // 서명 탭 클릭 시 로드
        document.querySelector('a[href="#tabSignature"]')?.addEventListener('shown.bs.tab', () => this.loadSignature());
        // 주소록 탭 클릭 시 로드
        document.querySelector('a[href="#tabContacts"]')?.addEventListener('shown.bs.tab', () => this.loadContacts());
        // 검색 (debounce + 페이지 리셋)
        document.getElementById('contactSearch')?.addEventListener('input', () => {
            clearTimeout(this._contactDebounce);
            this._contactDebounce = setTimeout(() => this.loadContacts(1), 300);
        });
    },

    // --- 주소록 ---
    _contactPage: 1,
    _contactDebounce: null,

    async loadContacts(page) {
        if (page !== undefined) this._contactPage = page;
        const q = (document.getElementById('contactSearch')?.value || '').trim();
        const res = await fetchJson(`/mail/api/contacts?page=${this._contactPage}&per_page=50&q=${encodeURIComponent(q)}`);
        const tbody = document.getElementById('contactsTableBody');
        if (!tbody) return;

        const items = res.items || [];
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-muted">연락처가 없습니다</td></tr>';
            this._renderContactPager(res);
            return;
        }
        tbody.innerHTML = items.map(c => `<tr>
            <td>${esc(c.name)} ${c.type === 'internal' ? '<span class="badge bg-info" style="font-size:.65rem;">사내</span>' : c.type === 'shared' ? '<span class="badge bg-success" style="font-size:.65rem;">공유</span>' : ''}</td>
            <td>${esc(c.email)}</td>
            <td>${esc(c.company || '')}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(c.memo || '')}</td>
            <td>${c.type === 'external' ? `
                <button class="btn btn-sm btn-outline-primary" onclick="MailSettings.editContact(${c.id},'${esc(c.name)}','${esc(c.email)}','${esc(c.company||'')}','${esc(c.memo||'')}')">수정</button>
                <button class="btn btn-sm btn-outline-danger" onclick="MailSettings.deleteContact(${c.id})">삭제</button>
            ` : ''}</td>
        </tr>`).join('');
        this._renderContactPager(res);
    },

    _renderContactPager(res) {
        let el = document.getElementById('contactsPager');
        if (!el) {
            el = document.createElement('div');
            el.id = 'contactsPager';
            el.className = 'd-flex justify-content-between align-items-center mt-2';
            el.style.fontSize = '.82rem';
            document.getElementById('contactsTableBody')?.closest('table')?.after(el);
        }
        const { total, page, total_pages } = res;
        if (total_pages <= 1) { el.innerHTML = `<span class="text-muted">총 ${total}건</span><span></span>`; return; }

        let pages = '';
        const start = Math.max(1, page - 2);
        const end = Math.min(total_pages, page + 2);
        if (start > 1) pages += `<button class="btn btn-sm btn-outline-secondary" onclick="MailSettings.loadContacts(1)">1</button> `;
        if (start > 2) pages += '<span class="mx-1">...</span>';
        for (let i = start; i <= end; i++) {
            pages += `<button class="btn btn-sm ${i === page ? 'btn-primary' : 'btn-outline-secondary'}" onclick="MailSettings.loadContacts(${i})">${i}</button> `;
        }
        if (end < total_pages - 1) pages += '<span class="mx-1">...</span>';
        if (end < total_pages) pages += `<button class="btn btn-sm btn-outline-secondary" onclick="MailSettings.loadContacts(${total_pages})">${total_pages}</button>`;

        el.innerHTML = `<span class="text-muted">총 ${total}건</span><div class="d-flex gap-1 align-items-center">${pages}</div>`;
    },

    _openContactModal({ id = '', name = '', email = '', company = '', memo = '', title = '연락처 추가' } = {}) {
        const modalEl = document.getElementById('contactEditModal');
        if (!modalEl) { alert('모달을 찾을 수 없습니다.'); return; }
        document.getElementById('contactEditModalTitle').textContent = title;
        document.getElementById('contactEditId').value = id || '';
        document.getElementById('contactEditName').value = name || '';
        document.getElementById('contactEditEmail').value = email || '';
        document.getElementById('contactEditCompany').value = company || '';
        document.getElementById('contactEditMemo').value = memo || '';
        const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        modal.show();
        setTimeout(() => document.getElementById('contactEditName')?.focus(), 200);
    },

    addContact() {
        this._openContactModal({ title: '연락처 추가' });
    },

    editContact(id, name, email, company, memo) {
        this._openContactModal({ id, name, email, company, memo, title: '연락처 수정' });
    },

    async saveContactFromModal() {
        const id = document.getElementById('contactEditId').value;
        const name = document.getElementById('contactEditName').value.trim();
        const email = document.getElementById('contactEditEmail').value.trim();
        const company = document.getElementById('contactEditCompany').value.trim();
        const memo = document.getElementById('contactEditMemo').value.trim();
        if (!name) { alert('이름을 입력하세요.'); return; }
        if (!email) { alert('이메일을 입력하세요.'); return; }

        const body = { name, email, company, memo };
        if (id) body.id = parseInt(id);
        const r = await fetchJson('/mail/api/contacts', { method: 'POST', body });
        if (r && (r.success || r.id)) {
            bootstrap.Modal.getInstance(document.getElementById('contactEditModal'))?.hide();
            this.loadContacts();
        } else {
            alert(r?.error || '저장 실패');
        }
    },

    deleteContact(id) {
        if (!confirm('이 연락처를 삭제하시겠습니까?')) return;
        fetchJson(`/mail/api/contacts/${id}`, { method: 'DELETE' })
            .then(r => { if (r.success) this.loadContacts(); });
    },

    async saveAccount() {
        const data = {
            id: document.getElementById('accountId')?.value || null,
            email: document.getElementById('acctEmail').value,
            display_name: document.getElementById('acctDisplayName').value,
            imap_host: document.getElementById('acctImapHost').value,
            imap_port: parseInt(document.getElementById('acctImapPort').value),
            smtp_host: document.getElementById('acctSmtpHost').value,
            smtp_port: parseInt(document.getElementById('acctSmtpPort').value),
            username: document.getElementById('acctUsername').value,
        };
        const pw = document.getElementById('acctPassword').value;
        if (pw) data.password = pw;
        const res = await fetchJson('/mail/api/account', { method: 'POST', body: data });
        if (res.success) { alert('저장되었습니다.'); if (!data.id) document.getElementById('accountId').value = res.id; }
        else alert(res.error || '저장 실패');
    },

    async testConnection() {
        const id = document.getElementById('accountId')?.value;
        if (!id) { alert('먼저 계정을 저장해주세요.'); return; }
        const el = document.getElementById('testResult');
        el.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 연결 테스트 중...';
        const res = await fetchJson(`/mail/api/account/${id}/test`, { method: 'POST' });
        el.innerHTML = res.success
            ? `<div class="alert alert-success py-1 small">${res.message}</div>`
            : `<div class="alert alert-danger py-1 small">${res.error}</div>`;
    },

    async loadSignature() {
        const res = await fetchJson('/mail/api/user-signature');
        const el = document.getElementById('signaturePreview');
        if (el) el.innerHTML = res.html || '<span class="text-muted">서명 정보가 없습니다. 관리자에게 계정 정보 등록을 요청하세요.</span>';
    },

    addSharedAccount() {
        const email = prompt('공용 메일 주소:');
        if (!email) return;
        const username = prompt('IMAP 로그인 계정:');
        if (!username) return;
        const password = prompt('비밀번호:');
        if (!password) return;
        fetchJson('/mail/api/admin/shared', { method: 'POST', body: { email, username, password, display_name: email.split('@')[0] } })
            .then(r => { if (r.success) { alert('생성 완료'); location.reload(); } else alert(r.error); });
    },
    editSharedAccount(id) { alert('공용계정 수정 — 준비 중 (ID: ' + id + ')'); },
    editSharedAccess(id) { alert('권한 설정 — 준비 중 (ID: ' + id + ')'); },
};
