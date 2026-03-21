/* contract_detail.js
 * PAGE_DATA (set in template) provides:
 *   .contractIds   - array of contract IDs
 *   .projectId     - project ID
 *   .designSearchUrl - url_for('project.api_design_projects_search')
 */

// ── 세금계산서/수금 현황 로드 ──
(function(){
    const contracts = PAGE_DATA.contractIds || [];
    const section = document.getElementById('contractInvoiceSection');
    if (!section) return;
    if (!contracts.length) {
        section.innerHTML = '<div class="text-center py-2 text-muted small">등록된 계약이 없습니다.</div>';
        return;
    }
    let allHtml = '';
    let loaded = 0;
    contracts.forEach(cid => {
        fetch('/financial/api/contract/' + cid + '/invoices')
        .then(r => r.json())
        .then(data => {
            loaded++;
            if (data.invoices && data.invoices.length > 0) {
                let rows = data.invoices.map(i => {
                    const payBadge = i.payment_status === '입금완료'
                        ? '<span class="badge bg-success" style="font-size:0.68rem;white-space:nowrap;">완료</span>'
                        : i.payment_status === '부분입금'
                        ? '<span class="badge bg-warning text-dark" style="font-size:0.68rem;white-space:nowrap;">부분</span>'
                        : '<span class="badge bg-danger" style="font-size:0.68rem;white-space:nowrap;">미수금</span>';
                    return `<tr style="cursor:pointer;" onclick="location.href='/financial/tax-invoice/${i.id}'">
                        <td>${i.issue_date||'-'}</td>
                        <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${i.buyer_name||'-'}</td>
                        <td class="text-end">${(i.total_amount||0).toLocaleString()}</td>
                        <td class="text-end">${(i.paid_amount||0).toLocaleString()}</td>
                        <td>${payBadge}</td>
                    </tr>`;
                }).join('');
                const summ = data.summary;
                const pct = summ.total_amount > 0 ? Math.round(summ.total_paid / summ.total_amount * 100) : 0;
                allHtml += `<div class="mb-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <small class="fw-bold">세금계산서 ${summ.count}건</small>
                        <small class="text-muted">합계 ${summ.total_amount.toLocaleString()}원 | 수금 ${summ.total_paid.toLocaleString()}원 (${pct}%)</small>
                    </div>
                    <div class="progress" style="height:6px;border-radius:3px;">
                        <div class="progress-bar ${pct>=100?'bg-success':pct>0?'bg-warning':'bg-danger'}" style="width:${pct}%;"></div>
                    </div>
                    <table class="table table-sm mb-0 mt-1" style="font-size:0.78rem;">
                        <thead><tr><th style="white-space:nowrap;">발행일</th><th style="white-space:nowrap;">거래처</th><th class="text-end" style="white-space:nowrap;">합계</th><th class="text-end" style="white-space:nowrap;">입금</th><th style="white-space:nowrap;">상태</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`;
            }
            if (loaded === contracts.length) {
                section.innerHTML = allHtml || '<div class="text-center py-2 text-muted small">매칭된 세금계산서가 없습니다.</div>';
            }
        })
        .catch(() => {
            loaded++;
            if (loaded === contracts.length && !allHtml) {
                section.innerHTML = '<div class="text-center py-2 text-muted small">매칭된 세금계산서가 없습니다.</div>';
            }
        });
    });
})();

// ── 유틸리티 함수 ──
function copyPath() {
    navigator.clipboard.writeText(document.getElementById('workPathText').innerText).then(() => alert('복사 완료!'));
}

function submitDeleteRequest(form) {
    const name = form.getAttribute('data-project-name') || '현장';
    const reason = prompt(`[${name}] 삭제요청 사유를 입력해 주세요.\n(사유 없이는 요청할 수 없습니다)`);
    if (!reason || !reason.trim()) {
        alert('삭제 사유는 필수입니다.');
        return false;
    }
    form.querySelector('input[name="delete_reason"]').value = reason.trim();
    return confirm('삭제요청을 등록할까요?\n최고관리자/승인권자 승인 후 실제 삭제됩니다.');
}

// ── 계약 자동저장 ──
function setupContractAutoSave() {
    document.querySelectorAll('form.auto-contract-form').forEach((form) => {
        const statusEl = form.querySelector('.save-status');
        let timer = null;
        let submitting = false;

        const setStatus = (text, cls) => {
            if (!statusEl) return;
            statusEl.className = `save-status ${cls}`;
            statusEl.textContent = text;
        };

        const submitAjax = () => {
            if (submitting) return;
            submitting = true;
            setStatus('저장 중...', 'text-warning');
            const actionUrl = form.getAttribute('action');

            fetch(actionUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                body: new FormData(form)
            })
            .then(async (res) => {
                if (!res.ok) throw new Error('http error');
                const contentType = res.headers.get('content-type') || '';
                if (!contentType.includes('application/json')) {
                    throw new Error('non-json response');
                }
                return res.json();
            })
            .then(data => {
                if (!data.ok) throw new Error('save failed');
                setStatus('자동 저장 완료', 'text-success');
                appendSystemLog(data.log);
            })
            .catch(() => {
                setStatus('자동 저장 실패 (다시 시도해 주세요)', 'text-danger');
            })
            .finally(() => {
                submitting = false;
            });
        };

        const scheduleSave = () => {
            clearTimeout(timer);
            timer = setTimeout(submitAjax, 350);
        };

        form.querySelectorAll('input, select, textarea').forEach((el) => {
            if (el.type === 'hidden') return;
            el.addEventListener('change', scheduleSave);
            if (el.tagName === 'INPUT' && ['text', 'date', 'number'].includes(el.type)) {
                el.addEventListener('blur', scheduleSave);
            }
        });

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            submitAjax();
        });
    });
}

function appendSystemLog(log) {
    if (!log) return;
    const board = document.getElementById('systemLogBoard');
    if (!board) return;

    const wrap = document.createElement('div');
    wrap.className = 'mb-2 p-2 rounded shadow-sm bg-white border-start border-4 border-primary small log-entry-system';
    wrap.innerHTML = `<b>${log.user_name}</b> <span class="text-muted float-end">${log.created_at}</span><br><div style="white-space: pre-wrap;">${(log.content || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>`;
    board.prepend(wrap);
}

// ── 담당자 편집 ──
function openContactEdit(id, category, name, phone, email) {
    const idEl = document.getElementById('edit_contact_id');
    const catEl = document.getElementById('edit_contact_category');
    const nameEl = document.getElementById('edit_contact_name');
    const phoneEl = document.getElementById('edit_contact_phone');
    const emailEl = document.getElementById('edit_contact_email');

    if (!idEl || !catEl || !nameEl || !phoneEl || !emailEl) return;

    idEl.value = id || '';
    catEl.value = category || '';
    nameEl.value = name || '';
    phoneEl.value = phone || '';
    emailEl.value = email || '';

    new bootstrap.Modal(document.getElementById('editContactModal')).show();
}

function openContactEditFromBtn(btn) {
    openContactEdit(
        btn.dataset.id,
        btn.dataset.category,
        btn.dataset.name,
        btn.dataset.phone,
        btn.dataset.email
    );
}

// ── 바코드 편집 ──
function openBarcodeEditFromBtn(btn) {
    const map = [
        ['edit_barcode_id', 'barcodeId'],
        ['edit_barcode', 'barcode'],
        ['edit_site_name', 'siteName'],
        ['edit_model_name', 'modelName'],
        ['edit_producer', 'producer'],
        ['edit_lens_angle', 'lensAngle'],
        ['edit_pcb_spec', 'pcbSpec'],
        ['edit_pcb_cct', 'pcbCct'],
        ['edit_pcb_chip_spec', 'pcbChipSpec'],
        ['edit_pcb_mfg_date', 'pcbMfgDate'],
        ['edit_smps_model', 'smpsModel'],
        ['edit_smps_qty', 'smpsQty'],
        ['edit_smps_setting', 'smpsSetting'],
        ['edit_smps_vdc', 'smpsVdc'],
        ['edit_smps_adc', 'smpsAdc'],
        ['edit_spacing_distance', 'spacingDistance'],
        ['edit_replaced_from_barcode', 'replacedFromBarcode'],
        ['edit_replaced_reason', 'replacedReason'],
    ];

    map.forEach(([id, key]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.value = btn.dataset[key] ?? '';
    });

    new bootstrap.Modal(document.getElementById('barcodeEditModal')).show();
}

// ── 영업현황 (Sales Status) ──
function statusToSteps(status) {
    if (status === '협의완료') return [true, true, true];
    if (status === '상세협의중') return [true, true, false];
    return [true, false, false];
}

function stepsToStatus() {
    const s1 = document.getElementById('sales_step_1')?.checked;
    const s2 = document.getElementById('sales_step_2')?.checked;
    const s3 = document.getElementById('sales_step_3')?.checked;
    if (s1 && s2 && s3) return '협의완료';
    if (s1 && s2) return '상세협의중';
    return '계약확인';
}

function enforceSalesStepRule() {
    const s1 = document.getElementById('sales_step_1');
    const s2 = document.getElementById('sales_step_2');
    const s3 = document.getElementById('sales_step_3');
    if (!s1 || !s2 || !s3) return;

    if (!s1.checked) {
        s2.checked = false;
        s3.checked = false;
    }
    if (!s2.checked) {
        s3.checked = false;
    }

    s2.disabled = !s1.checked;
    s3.disabled = !(s1.checked && s2.checked);
}

function openSalesStatusModalFromBtn(btn) {
    const itemId = btn.dataset.itemId;
    const current = btn.dataset.currentStatus || '계약확인';
    const [s1, s2, s3] = statusToSteps(current);

    const itemIdEl = document.getElementById('sales_modal_item_id');
    const step1 = document.getElementById('sales_step_1');
    const step2 = document.getElementById('sales_step_2');
    const step3 = document.getElementById('sales_step_3');
    if (!itemIdEl || !step1 || !step2 || !step3) return;

    itemIdEl.value = itemId;
    step1.checked = s1;
    step2.checked = s2;
    step3.checked = s3;
    enforceSalesStepRule();

    new bootstrap.Modal(document.getElementById('salesStatusModal')).show();
}

function applySalesStatusFromModal() {
    const itemId = document.getElementById('sales_modal_item_id')?.value;
    if (!itemId) return false;

    const status = stepsToStatus();
    const hidden = document.getElementById(`sales_status_${itemId}`);
    const btn = document.querySelector(`button[data-item-id="${itemId}"]`);
    const badge = document.getElementById(`sales_status_badge_${itemId}`);
    if (hidden) hidden.value = status;
    if (btn) {
        btn.dataset.currentStatus = status;
    }
    if (badge) {
        badge.textContent = status;
    }

    bootstrap.Modal.getInstance(document.getElementById('salesStatusModal'))?.hide();
    return false;
}

// ── 구매현황 (Admin Status) ──
function adminStatusToSteps(status) {
    if (status === '입고완료') return [true, true, true];
    if (status === '자재발주') return [true, true, false];
    return [true, false, false];
}

function adminStepsToStatus() {
    const s1 = document.getElementById('admin_step_1')?.checked;
    const s2 = document.getElementById('admin_step_2')?.checked;
    const s3 = document.getElementById('admin_step_3')?.checked;
    if (s1 && s2 && s3) return '입고완료';
    if (s1 && s2) return '자재발주';
    return '자재확인중';
}

function enforceAdminStepRule() {
    const s1 = document.getElementById('admin_step_1');
    const s2 = document.getElementById('admin_step_2');
    const s3 = document.getElementById('admin_step_3');
    if (!s1 || !s2 || !s3) return;

    if (!s1.checked) {
        s2.checked = false;
        s3.checked = false;
    }
    if (!s2.checked) {
        s3.checked = false;
    }

    s2.disabled = !s1.checked;
    s3.disabled = !(s1.checked && s2.checked);
}

function openAdminStatusModalFromBtn(btn) {
    const itemId = btn.dataset.itemId;
    const current = btn.dataset.currentStatus || '자재확인중';
    const itemIdEl = document.getElementById('admin_modal_item_id');
    const [s1, s2, s3] = adminStatusToSteps(current);
    if (!itemIdEl) return;
    itemIdEl.value = itemId;

    const step1 = document.getElementById('admin_step_1');
    const step2 = document.getElementById('admin_step_2');
    const step3 = document.getElementById('admin_step_3');
    if (!step1 || !step2 || !step3) return;

    step1.checked = s1;
    step2.checked = s2;
    step3.checked = s3;
    enforceAdminStepRule();

    new bootstrap.Modal(document.getElementById('adminStatusModal')).show();
}

function applyAdminStatusFromModal() {
    const itemId = document.getElementById('admin_modal_item_id')?.value;
    if (!itemId) return false;

    const selected = adminStepsToStatus();

    const hidden = document.getElementById(`admin_status_${itemId}`);
    const btn = document.querySelector(`button[onclick="openAdminStatusModalFromBtn(this)"][data-item-id="${itemId}"]`);
    const badge = document.getElementById(`admin_status_badge_${itemId}`);
    if (hidden) hidden.value = selected;
    if (btn) btn.dataset.currentStatus = selected;
    if (badge) badge.textContent = selected;

    bootstrap.Modal.getInstance(document.getElementById('adminStatusModal'))?.hide();
    return false;
}

// ── 생산현황 (Prod Status) ──
function prodStatusToSteps(status) {
    if (status === '생산완료') return [true, true, true, true];
    if (status === '생산중') return [true, true, true, false];
    if (status === '생산대기중') return [true, true, false, false];
    return [true, false, false, false];
}

function prodStepsToStatus() {
    const s1 = document.getElementById('prod_step_1')?.checked;
    const s2 = document.getElementById('prod_step_2')?.checked;
    const s3 = document.getElementById('prod_step_3')?.checked;
    const s4 = document.getElementById('prod_step_4')?.checked;
    if (s1 && s2 && s3 && s4) return '생산완료';
    if (s1 && s2 && s3) return '생산중';
    if (s1 && s2) return '생산대기중';
    return '자재대기중';
}

function enforceProdStepRule() {
    const s1 = document.getElementById('prod_step_1');
    const s2 = document.getElementById('prod_step_2');
    const s3 = document.getElementById('prod_step_3');
    const s4 = document.getElementById('prod_step_4');
    if (!s1 || !s2 || !s3 || !s4) return;

    if (!s1.checked) {
        s2.checked = false;
        s3.checked = false;
        s4.checked = false;
    }
    if (!s2.checked) {
        s3.checked = false;
        s4.checked = false;
    }
    if (!s3.checked) {
        s4.checked = false;
    }

    s2.disabled = !s1.checked;
    s3.disabled = !(s1.checked && s2.checked);
    s4.disabled = !(s1.checked && s2.checked && s3.checked);
}

function openProdStatusModalFromBtn(btn) {
    const itemId = btn.dataset.itemId;
    const current = btn.dataset.currentStatus || '자재대기중';
    const itemIdEl = document.getElementById('prod_modal_item_id');
    const [s1, s2, s3, s4] = prodStatusToSteps(current);
    if (!itemIdEl) return;
    itemIdEl.value = itemId;

    const step1 = document.getElementById('prod_step_1');
    const step2 = document.getElementById('prod_step_2');
    const step3 = document.getElementById('prod_step_3');
    const step4 = document.getElementById('prod_step_4');
    if (!step1 || !step2 || !step3 || !step4) return;

    step1.checked = s1;
    step2.checked = s2;
    step3.checked = s3;
    step4.checked = s4;
    enforceProdStepRule();

    new bootstrap.Modal(document.getElementById('prodStatusModal')).show();
}

function applyProdStatusFromModal() {
    const itemId = document.getElementById('prod_modal_item_id')?.value;
    if (!itemId) return false;

    const selected = prodStepsToStatus();

    const hidden = document.getElementById(`prod_status_${itemId}`);
    const btn = document.querySelector(`button[onclick="openProdStatusModalFromBtn(this)"][data-item-id="${itemId}"]`);
    const badge = document.getElementById(`prod_status_badge_${itemId}`);
    if (hidden) hidden.value = selected;
    if (btn) btn.dataset.currentStatus = selected;
    if (badge) badge.textContent = selected;

    bootstrap.Modal.getInstance(document.getElementById('prodStatusModal'))?.hide();
    return false;
}

// ── G2B 매칭 ──
let _g2bContractId = null;

function g2bOpenMatch(contractId) {
    _g2bContractId = contractId;
    const modal = new bootstrap.Modal(document.getElementById('g2bMatchModal'));
    modal.show();
    document.getElementById('g2bMatchBody').innerHTML = '<div class="text-center py-4 text-muted">로딩 중...</div>';

    fetch('/api/g2b-match/' + contractId)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('g2bMatchBody').innerHTML = '<div class="alert alert-danger">' + data.error + '</div>';
                return;
            }
            const candidates = data.candidates || [];
            if (candidates.length === 0) {
                document.getElementById('g2bMatchBody').innerHTML = '<div class="text-center py-4 text-muted">매칭 후보가 없습니다.</div>';
                return;
            }
            let html = '<table class="table table-sm table-hover align-middle" style="font-size:0.82rem;">';
            html += '<thead class="table-light"><tr><th style="width:60px;">점수</th><th>계약명</th><th>수요기관</th><th class="text-end" style="width:110px;">금액</th><th style="width:90px;">계약일</th><th style="width:60px;"></th></tr></thead><tbody>';
            candidates.forEach(function(c) {
                const maxScore = 80;
                const pct = Math.round(c.score / maxScore * 100);
                const barColor = pct >= 70 ? '#198754' : pct >= 40 ? '#ffc107' : '#dc3545';
                html += '<tr>';
                html += '<td><div style="background:#e9ecef;border-radius:4px;height:18px;width:100%;position:relative;">';
                html += '<div style="background:' + barColor + ';height:100%;width:' + pct + '%;border-radius:4px;"></div>';
                html += '<span style="position:absolute;top:0;left:50%;transform:translateX(-50%);font-size:0.72rem;font-weight:bold;line-height:18px;">' + c.score + '</span>';
                html += '</div></td>';
                html += '<td title="' + (c.req_nm || '') + '">' + ((c.req_nm || '').substring(0, 40)) + (c.req_nm && c.req_nm.length > 40 ? '...' : '') + '</td>';
                html += '<td><small>' + (c.dminstt || '-') + '</small></td>';
                html += '<td class="text-end fw-bold">' + Number(c.total_amt).toLocaleString() + '</td>';
                html += '<td>' + (c.req_date || '-') + '</td>';
                html += '<td><button class="btn btn-sm btn-primary py-0 px-2" style="font-size:0.75rem;" onclick="g2bLink(\'' + c.req_no + '\')">연동</button></td>';
                html += '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById('g2bMatchBody').innerHTML = html;
        })
        .catch(err => {
            document.getElementById('g2bMatchBody').innerHTML = '<div class="alert alert-danger">오류: ' + err.message + '</div>';
        });
}

function g2bLink(reqNo) {
    if (!_g2bContractId) return;
    if (!confirm('이 G2B 계약(' + reqNo + ')을 연동하시겠습니까?')) return;

    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    fetch('/api/g2b-match/' + _g2bContractId + '/link', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
        body: JSON.stringify({g2b_contract_no: reqNo})
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        bootstrap.Modal.getInstance(document.getElementById('g2bMatchModal')).hide();
        location.reload();
    })
    .catch(err => alert('오류: ' + err.message));
}

function g2bUnlink(contractId, btn) {
    if (!confirm('G2B 연동을 해제하시겠습니까?')) return;

    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    fetch('/api/g2b-match/' + contractId + '/unlink', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        location.reload();
    })
    .catch(err => alert('오류: ' + err.message));
}

// ── G2B 불러오기 (계약 추가 폼 자동 채움) ──
(function() {
    const btn = document.getElementById('g2bImportBtnDetail');
    if (!btn) return;

    // 모달 HTML 삽입
    document.body.insertAdjacentHTML('beforeend', `
    <div class="modal fade" id="g2bImportDetailModal" tabindex="-1">
        <div class="modal-dialog modal-lg modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header py-2">
                    <h6 class="modal-title fw-bold">G2B 조달내역 불러오기</h6>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body p-3">
                    <div class="input-group input-group-sm mb-3">
                        <input type="text" class="form-control" id="g2bDetailSearchInput" placeholder="계약명 또는 수요기관명 검색...">
                        <button class="btn btn-outline-primary" type="button" id="g2bDetailSearchBtn">검색</button>
                    </div>
                    <div id="g2bDetailResults" style="max-height:400px; overflow-y:auto;">
                        <div class="text-center text-muted py-4">로딩 중...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>`);

    let _modal = null;
    function getModal() {
        if (!_modal) _modal = new bootstrap.Modal(document.getElementById('g2bImportDetailModal'));
        return _modal;
    }
    const results = document.getElementById('g2bDetailResults');

    btn.addEventListener('click', () => {
        document.getElementById('g2bDetailSearchInput').value = '';
        getModal().show();
        doSearch('');
    });

    function doSearch(q) {
        results.innerHTML = '<div class="text-center py-4 text-muted">검색 중...</div>';
        const url = '/api/g2b-search' + (q ? '?q=' + encodeURIComponent(q) : '');
        fetch(url).then(r => r.json()).then(data => {
            if (!data.results || !data.results.length) {
                results.innerHTML = '<div class="text-center py-4 text-muted">결과 없음</div>';
                return;
            }
            let html = '<div class="list-group list-group-flush">';
            data.results.forEach(g => {
                html += `<a href="#" class="list-group-item list-group-item-action g2b-detail-item"
                   data-g2b='${JSON.stringify(g).replace(/'/g, "&#39;")}'>
                    <div class="fw-bold" style="font-size:.9rem;">${g.req_nm}</div>
                    <small class="text-muted">${g.dminstt} &middot; ${g.req_date} &middot; ${g.item_cnt}품목${g.dlvr_date ? ' &middot; 납품기한: ' + g.dlvr_date : ''}</small>
                </a>`;
            });
            html += '</div>';
            results.innerHTML = html;
            results.querySelectorAll('.g2b-detail-item').forEach(el => {
                el.addEventListener('click', e => {
                    e.preventDefault();
                    const g = JSON.parse(el.dataset.g2b);
                    fillAddContractForm(g);
                    getModal().hide();
                });
            });
        }).catch(err => {
            results.innerHTML = '<div class="alert alert-danger">오류: ' + err.message + '</div>';
        });
    }

    document.getElementById('g2bDetailSearchBtn').addEventListener('click', () => {
        doSearch(document.getElementById('g2bDetailSearchInput').value.trim());
    });
    document.getElementById('g2bDetailSearchInput').addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); doSearch(e.target.value.trim()); }
    });

    function fillAddContractForm(g) {
        const form = document.querySelector('input[name="action"][value="add_contract"]').closest('form');
        if (!form) return;
        const nameInput = form.querySelector('input[name="contract_name"]');
        if (nameInput) nameInput.value = g.req_nm || '';
        const dateInput = form.querySelector('input[name="contract_date"]');
        if (dateInput && g.req_date) dateInput.value = g.req_date;
        const dueInput = form.querySelector('input[name="delivery_due_date"]');
        if (dueInput && g.dlvr_date) dueInput.value = g.dlvr_date;
        // G2B 연동 번호 + 품목 JSON
        document.getElementById('addContractG2bNo').value = g.req_no || '';
        document.getElementById('addContractG2bItems').value = g.items ? JSON.stringify(g.items) : '';
    }
})();

// ── 설계현장 연결 (병합) ──
(function() {
    const projectId = PAGE_DATA.projectId;
    const designSearchUrl = PAGE_DATA.designSearchUrl;
    let _modal = null;
    function getModal() {
        if (!_modal) _modal = new bootstrap.Modal(document.getElementById('mergeDesignModal'));
        return _modal;
    }

    const results = document.getElementById('mergeDesignResults');
    const searchInput = document.getElementById('mergeDesignSearchInput');
    const searchBtn = document.getElementById('mergeDesignSearchBtn');

    if (!searchBtn) return;

    function doSearch(q) {
        results.innerHTML = '<div class="text-center py-4 text-muted">검색 중...</div>';
        const url = designSearchUrl + (q ? '?q=' + encodeURIComponent(q) : '');
        fetch(url).then(r => r.json()).then(data => {
            if (!data.results || !data.results.length) {
                results.innerHTML = '<div class="text-center py-4 text-muted">결과 없음</div>';
                return;
            }
            let html = '<div class="list-group list-group-flush">';
            data.results.forEach(p => {
                const info = [
                    p.material_count ? '자재 ' + p.material_count + '건' : '',
                    p.contact_count ? '담당자 ' + p.contact_count + '명' : '',
                    p.drawing_count ? '도면 ' + p.drawing_count + '건' : '',
                ].filter(Boolean).join(', ') || '데이터 없음';
                html += `<a href="#" class="list-group-item list-group-item-action merge-design-item" data-design-id="${p.id}">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <span class="fw-bold" style="font-size:.9rem;">${p.temp_name}</span>
                            <span class="text-muted ms-2" style="font-size:.82rem;">(${p.project_no})</span>
                        </div>
                        <span class="badge bg-secondary">${p.status}</span>
                    </div>
                    <small class="text-muted">${info} | 등록: ${p.created_at}</small>
                </a>`;
            });
            html += '</div>';
            results.innerHTML = html;

            results.querySelectorAll('.merge-design-item').forEach(el => {
                el.addEventListener('click', e => {
                    e.preventDefault();
                    const designId = el.dataset.designId;
                    const designName = el.querySelector('.fw-bold').textContent;
                    if (!confirm('설계현장 "' + designName + '"의 모든 데이터를 현재 계약현장으로 이관합니다.\n\n이 작업은 되돌릴 수 없습니다. 진행하시겠습니까?')) return;

                    fetch('/api/project/' + projectId + '/merge-design/' + designId, {
                        method: 'POST',
                        headers: {'X-Requested-With': 'XMLHttpRequest'},
                    }).then(r => r.json()).then(resp => {
                        if (resp.ok) {
                            const merged = resp.merged || {};
                            const detail = Object.entries(merged).filter(([k,v]) => v > 0).map(([k,v]) => k + ' ' + v + '건').join(', ');
                            alert('병합 완료: ' + (detail || '데이터 없음') + '\n\n페이지를 새로고침합니다.');
                            location.reload();
                        } else {
                            alert('병합 실패: ' + (resp.error || '알 수 없는 오류'));
                        }
                    }).catch(err => {
                        alert('병합 오류: ' + err.message);
                    });
                });
            });
        }).catch(err => {
            results.innerHTML = '<div class="alert alert-danger">오류: ' + err.message + '</div>';
        });
    }

    // 모달 열릴 때 자동 검색 (빈 검색어)
    document.getElementById('mergeDesignModal').addEventListener('shown.bs.modal', () => {
        searchInput.value = '';
        doSearch('');
        searchInput.focus();
    });

    searchBtn.addEventListener('click', () => doSearch(searchInput.value.trim()));
    searchInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); doSearch(e.target.value.trim()); }
    });
})();

// ── DOMContentLoaded 초기화 ──
document.addEventListener('DOMContentLoaded', function () {
    setupContractAutoSave();

    ['sales_step_1', 'sales_step_2', 'sales_step_3'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', enforceSalesStepRule);
    });

    ['admin_step_1', 'admin_step_2', 'admin_step_3'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', enforceAdminStepRule);
    });

    ['prod_step_1', 'prod_step_2', 'prod_step_3', 'prod_step_4'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', enforceProdStepRule);
    });

    const hash = window.location.hash;
    if (!hash) return;
    const target = document.querySelector(hash);
    if (!target) return;
    target.classList.add('border', 'border-warning', 'border-3');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
});
