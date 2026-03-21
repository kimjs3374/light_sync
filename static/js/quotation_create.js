(function() {
    var rowIndex = 0;
    var scIndex = 0;
    var roundAdjust = 0;
    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    var dd = document.getElementById('itemAcDropdown');
    var pdd = document.getElementById('priceDd');
    var activeInput = null;
    var activePriceInput = null;
    var acTimer = null;
    var container = document.getElementById('itemsContainer');

    var dateInput = document.querySelector('input[name="quote_date"]');
    if (dateInput && !dateInput.value) dateInput.value = new Date().toISOString().split('T')[0];

    // ── 품목 카드 추가 ──
    function addItemCard(data) {
        data = data || {};
        rowIndex++;
        var card = document.createElement('div');
        card.className = 'qi-card';
        card.innerHTML =
            '<input type="hidden" name="item_id[]" value="' + (data.id || '') + '">' +
            '<div class="qi-inline">' +
                '<div class="qi-f-no qi-no">' + rowIndex + '</div>' +
                '<div class="qi-field qi-f-name">' +
                    '<label>품명</label>' +
                    '<input type="text" name="item_name[]" class="form-control form-control-sm item-ac-input" value="' + (data.item_name || '') + '" placeholder="품명 (자동완성)" autocomplete="off" required>' +
                '</div>' +
                '<div class="qi-field qi-f-spec">' +
                    '<label>규격</label>' +
                    '<input type="text" name="item_spec[]" class="form-control form-control-sm" value="' + (data.item_spec || '') + '">' +
                '</div>' +
                '<div class="qi-field qi-f-unit">' +
                    '<label>단위</label>' +
                    '<input type="text" name="unit[]" class="form-control form-control-sm text-center" value="' + (data.unit || 'EA') + '">' +
                '</div>' +
                '<div class="qi-field qi-f-qty">' +
                    '<label>수량</label>' +
                    '<input type="number" name="quantity[]" class="form-control form-control-sm text-end calc-field" value="' + (data.quantity || '') + '" min="0" step="any" inputmode="decimal">' +
                '</div>' +
                '<div class="qi-field qi-f-price">' +
                    '<label>단가</label>' +
                    '<input type="number" name="unit_price[]" class="form-control form-control-sm text-end calc-field" value="' + (data.unit_price || '') + '" min="0" step="any" inputmode="decimal">' +
                '</div>' +
                '<div class="qi-field qi-f-note">' +
                    '<label>비고</label>' +
                    '<input type="text" name="item_note[]" class="form-control form-control-sm" value="' + (data.note || '') + '">' +
                '</div>' +
                '<div class="qi-f-rm"><button type="button" class="qi-rm">&times;</button></div>' +
            '</div>';
        container.appendChild(card);
        recalcAll();
    }
    window._addItemRow = addItemCard;

    document.getElementById('addItemBtn').addEventListener('click', function() { addItemCard(); });

    // 수정 모드: 기존 품목 로드 / 신규: 빈 3개
    // PAGE_DATA에서 초기 데이터 로드
    if (window.PAGE_DATA && window.PAGE_DATA.editMode) {
        (window.PAGE_DATA.items || []).forEach(function(item) { addItemCard(item); });
        (window.PAGE_DATA.surcharges || []).forEach(function(sc) { addScRow(sc); });
    } else {
        addItemCard(); addItemCard(); addItemCard();
    }

    // ── 품목 초기화 ──
    document.getElementById('clearItemsBtn').addEventListener('click', function() {
        if (!confirm('모든 품목을 초기화하시겠습니까?')) return;
        container.innerHTML = '';
        rowIndex = 0;
        addItemCard(); addItemCard(); addItemCard();
        recalcAll();
    });

    // ── 삭제 + 계산 이벤트 ──
    container.addEventListener('click', function(e) {
        if (e.target.classList.contains('qi-rm')) {
            e.target.closest('.qi-card').remove();
            renumberCards();
            recalcAll();
        }
    });
    container.addEventListener('input', function(e) {
        if (e.target.classList.contains('calc-field')) recalcAll();
    });

    // ── 품목 인라인 자동완성 ──
    container.addEventListener('input', function(e) {
        if (!e.target.classList.contains('item-ac-input')) return;
        clearTimeout(acTimer);
        activeInput = e.target;
        var q = e.target.value.trim();
        if (q.length < 1) { dd.classList.remove('show'); return; }
        acTimer = setTimeout(function() {
            fetch('/api/items/search?q=' + encodeURIComponent(q))
                .then(function(r) { return r.json(); })
                .then(function(items) {
                    if (!items.length) { dd.classList.remove('show'); return; }
                    dd.innerHTML = items.map(function(it) {
                        var priceStr = it.last_unit_price ? ' <span class="ac-price">' + Number(it.last_unit_price).toLocaleString() + '원</span>' : '';
                        return '<div class="ac-item" data-id="' + it.id + '" data-name="' + it.item_name + '"'
                            + ' data-spec="' + (it.item_spec || '') + '" data-unit="' + (it.unit || 'EA') + '"'
                            + ' data-price="' + (it.last_unit_price || 0) + '">'
                            + '<strong>' + it.item_name + '</strong>'
                            + (it.item_spec ? ' <span class="ac-sub">(' + it.item_spec + ')</span>' : '')
                            + priceStr + '</div>';
                    }).join('');
                    var rect = activeInput.getBoundingClientRect();
                    dd.style.top = (rect.bottom + window.scrollY + 2) + 'px';
                    dd.style.left = rect.left + 'px';
                    dd.style.width = Math.max(rect.width, 320) + 'px';
                    dd.classList.add('show');
                });
        }, 200);
    });

    dd.addEventListener('mousedown', function(e) {
        e.preventDefault();
        var item = e.target.closest('.ac-item');
        if (!item || !activeInput) return;
        var card = activeInput.closest('.qi-card');
        card.querySelector('input[name="item_id[]"]').value = item.dataset.id;
        card.querySelector('input[name="item_name[]"]').value = item.dataset.name;
        card.querySelector('input[name="item_spec[]"]').value = item.dataset.spec;
        card.querySelector('input[name="unit[]"]').value = item.dataset.unit || 'EA';
        var price = parseFloat(item.dataset.price) || 0;
        if (price > 0) card.querySelector('input[name="unit_price[]"]').value = price;
        dd.classList.remove('show');
        recalcAll();
        card.querySelector('input[name="quantity[]"]').focus();
    });

    document.addEventListener('click', function(e) {
        if (!e.target.classList.contains('item-ac-input') && !dd.contains(e.target)) dd.classList.remove('show');
        if (!e.target.classList.contains('calc-field') && !pdd.contains(e.target)) pdd.classList.remove('show');
    });

    // ── 단가 추천 드롭다운 ──
    container.addEventListener('focus', function(e) {
        if (!e.target.matches('input[name="unit_price[]"]')) return;
        activePriceInput = e.target;
        var card = e.target.closest('.qi-card');
        var itemName = card.querySelector('input[name="item_name[]"]').value.trim();
        if (!itemName) { pdd.classList.remove('show'); return; }
        fetch('/api/quote-price-history?item_name=' + encodeURIComponent(itemName))
            .then(function(r) { return r.json(); })
            .then(function(prices) {
                if (!prices.length) { pdd.classList.remove('show'); return; }
                pdd.innerHTML = '<div class="pd-title">과거 견적 단가</div>' +
                    prices.map(function(p) {
                        return '<div class="pd-item" data-price="' + p.price + '">' +
                            '<span class="pd-price">' + Number(p.price).toLocaleString() + '</span>' +
                            '<span class="pd-meta">' + (p.spec ? p.spec + ' | ' : '') + p.count + '회' + (p.last_date ? ' | ' + p.last_date : '') + '</span>' +
                            '</div>';
                    }).join('');
                var rect = e.target.getBoundingClientRect();
                pdd.style.top = (rect.bottom + window.scrollY + 2) + 'px';
                pdd.style.left = rect.left + 'px';
                pdd.style.width = Math.max(rect.width, 220) + 'px';
                pdd.classList.add('show');
            });
    }, true);

    pdd.addEventListener('mousedown', function(e) {
        e.preventDefault();
        var item = e.target.closest('.pd-item');
        if (!item || !activePriceInput) return;
        activePriceInput.value = item.dataset.price;
        pdd.classList.remove('show');
        recalcAll();
    });

    // ── 부과금 ──
    function addScRow(data) {
        data = data || {};
        scIndex++;
        var row = document.createElement('div');
        row.className = 'qi-card';
        row.style.background = '#fffbeb';
        row.style.borderColor = '#fde68a';
        row.innerHTML =
            '<button type="button" class="qi-rm sc-rm-btn">&times;</button>' +
            '<div class="row g-2 align-items-end">' +
                '<div class="col-5"><label class="form-label small text-muted mb-0">항목명</label><input type="text" name="sc_name[]" class="form-control form-control-sm" value="' + (data.name || '') + '" placeholder="부가세, 이윤 등"></div>' +
                '<div class="col-3"><label class="form-label small text-muted mb-0">비율 (%)</label><input type="number" name="sc_rate[]" class="form-control form-control-sm text-end sc-calc" value="' + (data.rate || '') + '" min="0" step="any" inputmode="decimal"></div>' +
                '<div class="col-4 text-end"><label class="form-label small text-muted mb-0">금액</label><div class="fw-bold sc-amount" style="font-size:1rem;color:#92400e;padding:6px 0;">0원</div></div>' +
            '</div>';
        document.getElementById('scContainer').appendChild(row);
        recalcAll();
    }
    document.getElementById('addScBtn').addEventListener('click', function() { addScRow(); });

    // 부가세 10% 자동 추가
    document.getElementById('addVatBtn').addEventListener('click', function() {
        // 이미 부가세 있는지 확인
        var exists = false;
        document.querySelectorAll('#scContainer input[name="sc_name[]"]').forEach(function(inp) {
            if (inp.value.trim() === '부가세') exists = true;
        });
        if (exists) { alert('부가세가 이미 추가되어 있습니다.'); return; }
        addScRow({name: '부가세', rate: 10});
    });

    document.getElementById('scContainer').addEventListener('click', function(e) {
        if (e.target.classList.contains('sc-rm-btn')) { e.target.closest('.qi-card').remove(); recalcAll(); }
    });
    document.getElementById('scContainer').addEventListener('input', function(e) {
        if (e.target.classList.contains('sc-calc')) recalcAll();
    });

    // ── 절상/절삭 ──
    document.querySelectorAll('.round-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var unit = parseInt(this.dataset.unit);
            var dir = this.dataset.dir;
            var raw = _getRawTotal();
            var rounded;
            if (dir === 'ceil') {
                rounded = Math.ceil(raw / unit) * unit;
            } else {
                rounded = Math.floor(raw / unit) * unit;
            }
            roundAdjust = rounded - raw;
            document.getElementById('roundAdjustInput').value = roundAdjust;
            recalcAll();
        });
    });

    document.getElementById('roundResetBtn').addEventListener('click', function() {
        roundAdjust = 0;
        document.getElementById('roundAdjustInput').value = 0;
        recalcAll();
    });

    function _getRawTotal() {
        var supply = 0;
        container.querySelectorAll('.qi-card').forEach(function(card) {
            var qty = parseFloat(card.querySelector('input[name="quantity[]"]').value) || 0;
            var price = parseFloat(card.querySelector('input[name="unit_price[]"]').value) || 0;
            supply += qty * price;
        });
        var scTotal = 0;
        document.querySelectorAll('#scContainer .qi-card').forEach(function(row) {
            var rate = parseFloat(row.querySelector('input[name="sc_rate[]"]').value) || 0;
            scTotal += Math.round(supply * rate / 100);
        });
        return supply + scTotal;
    }

    // ── 계산 ──
    function recalcAll() {
        var supply = 0;
        container.querySelectorAll('.qi-card').forEach(function(card) {
            var qty = parseFloat(card.querySelector('input[name="quantity[]"]').value) || 0;
            var price = parseFloat(card.querySelector('input[name="unit_price[]"]').value) || 0;
            var amount = qty * price;
            supply += amount;
        });
        document.getElementById('supplyTotal').textContent = supply.toLocaleString();

        var scTotal = 0;
        var scHtml = '';
        document.querySelectorAll('#scContainer .qi-card').forEach(function(row) {
            var name = row.querySelector('input[name="sc_name[]"]').value.trim();
            var rate = parseFloat(row.querySelector('input[name="sc_rate[]"]').value) || 0;
            var amt = Math.round(supply * rate / 100);
            row.querySelector('.sc-amount').textContent = amt.toLocaleString();
            scTotal += amt;
            if (name) scHtml += '<div class="total-row" style="opacity:.7;"><span>' + name + ' (' + rate + '%)</span><span>' + amt.toLocaleString() + '원</span></div>';
        });
        document.getElementById('scTotalRows').innerHTML = scHtml;

        // 절상/절삭 반영
        var rawTotal = supply + scTotal;
        var finalTotal = rawTotal + roundAdjust;
        document.getElementById('beforeRound').textContent = rawTotal.toLocaleString();
        document.getElementById('afterRound').textContent = finalTotal.toLocaleString();
        if (roundAdjust !== 0) {
            document.getElementById('roundRow').style.display = '';
            document.getElementById('roundDisplay').textContent = (roundAdjust > 0 ? '+' : '') + roundAdjust.toLocaleString();
        } else {
            document.getElementById('roundRow').style.display = 'none';
        }
        document.getElementById('grandTotal').textContent = finalTotal.toLocaleString();
    }

    function renumberCards() {
        container.querySelectorAll('.qi-card').forEach(function(card, i) {
            card.querySelector('.qi-no').textContent = (i + 1);
        });
        rowIndex = container.querySelectorAll('.qi-card').length;
    }

    // ── 세부견적 템플릿 ──
    document.getElementById('loadTplBtn').addEventListener('click', function() {
        new bootstrap.Modal(document.getElementById('tplLoadModal')).show();
        loadTemplateList();
    });
    document.querySelectorAll('.tpl-badge').forEach(function(b) {
        b.addEventListener('click', function() { loadTemplateItems(this.dataset.tplId); });
    });

    function loadTemplateList(q) {
        fetch('/api/quote-templates' + (q ? '?q=' + encodeURIComponent(q) : ''))
            .then(function(r) { return r.json(); })
            .then(function(tpls) {
                var el = document.getElementById('tplSearchResults');
                if (!tpls.length) { el.innerHTML = '<div class="text-center text-muted py-3">저장된 템플릿이 없습니다.</div>'; return; }
                el.innerHTML = '<div class="list-group">' + tpls.map(function(t) {
                    return '<a href="#" class="list-group-item list-group-item-action tpl-load-btn py-2" data-id="' + t.id + '">'
                        + '<strong>' + t.name + '</strong> <span class="badge bg-primary ms-1">' + t.item_count + '건</span>'
                        + ' <small class="text-muted">(' + t.total.toLocaleString() + '원)</small>'
                        + (t.creator ? ' <small class="text-muted">| ' + t.creator + '</small>' : '')
                        + (t.updated_at ? ' <small class="text-muted">| ' + t.updated_at + '</small>' : '')
                        + '</a>';
                }).join('') + '</div>';
            });
    }
    var tplTimer = null;
    document.getElementById('tplSearchInput').addEventListener('input', function() {
        clearTimeout(tplTimer);
        var q = this.value.trim();
        tplTimer = setTimeout(function() { loadTemplateList(q); }, 300);
    });
    document.getElementById('tplSearchResults').addEventListener('click', function(e) {
        var btn = e.target.closest('.tpl-load-btn');
        if (!btn) return;
        e.preventDefault();
        loadTemplateItems(btn.dataset.id);
        bootstrap.Modal.getInstance(document.getElementById('tplLoadModal')).hide();
    });
    function loadTemplateItems(tplId) {
        fetch('/api/quote-templates/' + tplId).then(function(r) { return r.json(); }).then(function(tpl) {
            if (tpl.error) { alert(tpl.error); return; }
            tpl.items.forEach(function(item) { addItemCard(item); });
            recalcAll();
        });
    }

    // ── 템플릿 저장 ──
    document.getElementById('saveTplBtn').addEventListener('click', function() {
        var cards = container.querySelectorAll('.qi-card');
        if (!cards.length) { alert('저장할 품목이 없습니다.'); return; }
        document.getElementById('tplSavePreview').textContent = cards.length + '개 품목이 저장됩니다.';
        new bootstrap.Modal(document.getElementById('tplSaveModal')).show();
        document.getElementById('tplSaveName').focus();
    });
    document.getElementById('tplSaveConfirmBtn').addEventListener('click', function() {
        var name = document.getElementById('tplSaveName').value.trim();
        if (!name) { alert('템플릿 이름을 입력하세요.'); return; }
        var items = [];
        container.querySelectorAll('.qi-card').forEach(function(card) {
            var n = card.querySelector('input[name="item_name[]"]').value.trim();
            if (!n) return;
            items.push({
                item_name: n,
                item_spec: card.querySelector('input[name="item_spec[]"]').value.trim(),
                unit: card.querySelector('input[name="unit[]"]').value.trim() || 'EA',
                quantity: parseFloat(card.querySelector('input[name="quantity[]"]').value) || 0,
                unit_price: parseFloat(card.querySelector('input[name="unit_price[]"]').value) || 0,
                note: card.querySelector('input[name="item_note[]"]').value.trim(),
            });
        });

        function doSave(overwrite) {
            fetch('/api/quote-templates', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({ name: name, note: document.getElementById('tplSaveNote').value.trim(), items: items, overwrite: overwrite }),
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.ok) {
                    alert('템플릿 "' + d.name + '" ' + (d.message || '저장') + ' 완료!');
                    bootstrap.Modal.getInstance(document.getElementById('tplSaveModal')).hide();
                } else alert(d.error || '저장 실패');
            });
        }

        // 동일 이름 존재 여부 확인 후 덮어쓰기 물어보기
        fetch('/api/quote-templates?q=' + encodeURIComponent(name))
            .then(function(r) { return r.json(); })
            .then(function(tpls) {
                var dup = tpls.find(function(t) { return t.name === name; });
                if (dup) {
                    if (confirm('"' + name + '" 템플릿이 이미 있습니다 (' + dup.creator + ' 작성, ' + dup.updated_at + ').\n덮어쓰기 하시겠습니까?')) {
                        doSave(true);
                    }
                } else {
                    doSave(false);
                }
            });
    });
    // ── 견적 전용 품목 빠른 등록 ──
    document.getElementById('qiSaveBtn').addEventListener('click', function() {
        var name = document.getElementById('qiName').value.trim();
        if (!name) { alert('품명을 입력하세요.'); return; }
        fetch('/api/items/create-quote-item', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({
                item_name: name,
                item_spec: document.getElementById('qiSpec').value.trim(),
                unit: document.getElementById('qiUnit').value.trim() || 'EA',
                last_unit_price: parseFloat(document.getElementById('qiPrice').value) || 0,
            }),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.ok) {
                alert('"' + name + '" 등록 완료! 자동완성에서 검색됩니다.');
                bootstrap.Modal.getInstance(document.getElementById('quickItemModal')).hide();
                // 바로 품목 행에 추가
                addItemCard({id: d.id, item_name: name, item_spec: d.spec, unit: d.unit, unit_price: d.price});
                recalcAll();
                document.getElementById('qiName').value = '';
                document.getElementById('qiSpec').value = '';
                document.getElementById('qiPrice').value = '';
            } else { alert(d.error || '등록 실패'); }
        });
    });
})();
