/* ══════════════════════════════════════════════════════════
   조도설계 검증 — 새 현장 등록 (3-Step 마법사)
   PAGE_DATA.apiUploadUrl / PAGE_DATA.apiParsePagesUrl 필요
══════════════════════════════════════════════════════════ */

/* ── ERP 설계현장 연동 자동완성 ─────────────────── */
function onErpProjectChange(sel) {
  const opt = sel.options[sel.selectedIndex];
  if (!opt.value) return;

  // 현장명, 위치: 항상 반영
  document.getElementById('fieldName').value = opt.dataset.name || '';
  document.getElementById('fieldLocation').value = opt.dataset.addr || '';

  // 설계관리에서 조도정보 AJAX
  fetch('/illuminance/api/project-illuminance/' + opt.value)
    .then(r => r.json())
    .then(data => {
      if (data.facility_type) {
        document.getElementById('fieldFacility').value = data.facility_type;
      }
      if (data.fixtures && data.fixtures.length) {
        var info = data.fixtures.map(function(f) { return f.type + ' ' + f.watt + 'W x ' + f.qty; }).join(', ');
        var el = document.getElementById('erpFixtureInfo');
        if (el) el.textContent = '설계관리 기구: ' + info;
      }
    })
    .catch(function() {});
}

/* ── 마법사 스텝 이동 ─────────────────────────────────── */
function wizGoTo(step) {
  // 유효성 검사
  if (step === 2) {
    const name = document.getElementById('fieldName').value.trim();
    if (!name) {
      document.getElementById('fieldName').focus();
      document.getElementById('fieldName').classList.add('is-invalid');
      return;
    }
    document.getElementById('fieldName').classList.remove('is-invalid');
  }

  [1,2,3].forEach(s => {
    document.getElementById('panel-' + s).classList.toggle('active', s === step);
    const ind = document.getElementById('step-ind-' + s);
    ind.classList.remove('active','done');
    if (s < step) ind.classList.add('done');
    else if (s === step) ind.classList.add('active');
  });

  // Step 3 진입 시 parse-pages API 호출 → 파싱 결과 렌더
  if (step === 3) parseAndRenderStep3();
}

/* ── 파일 처리 ──────────────────────────────────────── */
function handleFileSelect(input) {
  const file = input.files[0];
  if (!file) return;

  // 파일 정보 표시
  document.getElementById('fileInfo').classList.remove('d-none');
  document.getElementById('fileName').textContent = file.name;
  document.getElementById('fileSize').textContent =
    (file.size / 1024 / 1024).toFixed(1) + ' MB';

  // PDF 파싱 (서버 업로드)
  simulateParsing(file);
}

function clearFile() {
  document.getElementById('pdfFile').value = '';
  document.getElementById('fileInfo').classList.add('d-none');
  document.getElementById('pageListCard').classList.add('d-none');
  document.getElementById('parseProgress').classList.remove('show');
  document.getElementById('btnToStep3').disabled = true;
  window._parsedPages = [];
}

/* ── 드래그 앤 드롭 ──────────────────────────────── */
(function() {
  const dz = document.getElementById('dropzone');
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
      const dt = new DataTransfer();
      dt.items.add(file);
      document.getElementById('pdfFile').files = dt.files;
      handleFileSelect(document.getElementById('pdfFile'));
    }
  });
})();

/* ── 파싱 시뮬레이션 ─────────────────────────────── */
const TYPE_LABELS = {
  cover: '\ud45c\uc9c0',
  floor_plan: '\ud3c9\uba74\ub3c4',
  summary: '\uc694\uc57d',
  grid_table: '\uaca9\uc790\ud45c',
  '3d_view': '3D\ubdf0'
};
const TYPE_BADGE_CLASS = {
  cover: 'badge-type-cover',
  floor_plan: 'badge-type-floor_plan',
  summary: 'badge-type-summary',
  grid_table: 'badge-type-grid_table',
  '3d_view': 'badge-type-3d_view'
};

window._parsedPages = [];
window._selectedPages = [];
window._uploadToken = null;
window._serverAreas = [];  // parse-pages API 결과

async function simulateParsing(file) {
  const progress = document.getElementById('parseProgress');
  const bar = document.getElementById('parseProgressBar');
  const log = document.getElementById('parseLog');

  progress.classList.add('show');
  log.innerHTML = '';

  function logMsg(pct, msg) {
    bar.style.width = pct + '%';
    const div = document.createElement('div');
    div.innerHTML = msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  logMsg(10, '&#9654; PDF \ud30c\uc77c \uc5c5\ub85c\ub4dc \uc911...');
  await new Promise(r => setTimeout(r, 200));

  try {
    const formData = new FormData();
    formData.append('pdf', file);

    const resp = await fetch(PAGE_DATA.apiUploadUrl, {
      method: 'POST',
      body: formData
    });
    const data = await resp.json();

    if (!data.success) {
      logMsg(100, '&#10007; \uc624\ub958: ' + (data.error || '\uc5c5\ub85c\ub4dc \uc2e4\ud328'));
      return;
    }

    logMsg(55, `&#9654; ${data.total_pages}\ud398\uc774\uc9c0 \uac10\uc9c0 \u2014 \ud14d\uc2a4\ud2b8 \ubd84\uc11d \uc911...`);
    await new Promise(r => setTimeout(r, 200));

    window._uploadToken = data.upload_token;
    document.getElementById('hiddenUploadToken').value = data.upload_token;

    // API 페이지 데이터를 내부 포맷으로 변환
    const pages = data.pages.map(p => ({
      page: p.page_num,
      page_index: p.index,
      type: p.type,
      excerpt: p.preview,
      suggested_name: p.suggested_name,
      auto_select: p.auto_select,
    }));

    logMsg(90, '&#9654; \uaca9\uc790\ud45c \ud328\ud134 \uac10\uc9c0...');
    await new Promise(r => setTimeout(r, 200));
    logMsg(100, '&#10003; \ud30c\uc2f1 \uc644\ub8cc! (' + pages.length + '\ud398\uc774\uc9c0)');

    window._parsedPages = pages;
    renderPageList(pages);
    document.getElementById('pageListCard').classList.remove('d-none');

  } catch (err) {
    logMsg(100, '&#10007; \uc624\ub958: ' + err.message);
  }
}

/* ── 페이지 목록 렌더 ─────────────────────────────── */
function renderPageList(pages) {
  const grid = document.getElementById('pageGrid');
  grid.innerHTML = '';

  // grid_table 타입은 기본 선택
  window._selectedPages = pages
    .filter(p => p.type === 'grid_table')
    .map(p => p.page);

  pages.forEach(p => {
    const isGridTable = p.type === 'grid_table';
    const isSelected = window._selectedPages.includes(p.page);

    const col = document.createElement('div');
    col.className = 'col-sm-6 col-lg-4';

    col.innerHTML = `
      <div class="pdf-page-card ${isSelected ? 'selected' : ''} type-${p.type}"
           id="pageCard-${p.page}"
           onclick="togglePageSelect(${p.page})">
        <div class="d-flex align-items-center gap-2 mb-1">
          <span class="page-num">P.${p.page}</span>
          <span class="badge ${TYPE_BADGE_CLASS[p.type] || 'bg-secondary'}"
                style="font-size:.65rem;white-space:nowrap">
            ${TYPE_LABELS[p.type] || p.type}
          </span>
          ${p.rows > 0 ? `<span class="badge bg-light text-dark ms-auto" style="font-size:.62rem;white-space:nowrap">${p.rows}\u00d7${p.cols}</span>` : ''}
          <input type="checkbox" class="form-check-input ms-auto" id="chk-${p.page}"
                 ${isSelected ? 'checked' : ''}
                 onclick="event.stopPropagation(); togglePageSelect(${p.page})"
                 style="cursor:pointer">
        </div>
        <div class="page-excerpt">${p.excerpt}</div>
        ${isSelected ? `
        <div class="area-name-field" id="areaField-${p.page}">
          <input type="text" class="form-control form-control-sm mt-1"
                 id="areaName-${p.page}"
                 placeholder="\uad6c\uc5ed\uba85"
                 value="${isGridTable ? (p.suggested_name || '') : ''}"
                 onclick="event.stopPropagation()"
                 oninput="updateSelectedCount()">
        </div>` : `<div class="area-name-field d-none" id="areaField-${p.page}">
          <input type="text" class="form-control form-control-sm mt-1"
                 id="areaName-${p.page}"
                 placeholder="\uad6c\uc5ed\uba85"
                 value="${p.suggested_name || ''}"
                 onclick="event.stopPropagation()"
                 oninput="updateSelectedCount()">
        </div>`}
      </div>`;
    grid.appendChild(col);
  });

  updateSelectedCount();
}

function togglePageSelect(pageNum) {
  const card = document.getElementById('pageCard-' + pageNum);
  const chk = document.getElementById('chk-' + pageNum);
  const areaField = document.getElementById('areaField-' + pageNum);

  const idx = window._selectedPages.indexOf(pageNum);
  if (idx >= 0) {
    window._selectedPages.splice(idx, 1);
    card.classList.remove('selected');
    chk.checked = false;
    if (areaField) {
      areaField.classList.add('d-none');
      areaField.classList.remove('');
    }
    card.querySelector('.area-name-field').style.display = 'none';
  } else {
    window._selectedPages.push(pageNum);
    card.classList.add('selected');
    chk.checked = true;
    card.querySelector('.area-name-field').style.display = 'block';
  }
  updateSelectedCount();
}

function selectAllGridTables() {
  (window._parsedPages || []).forEach(p => {
    if (p.type === 'grid_table' && !window._selectedPages.includes(p.page)) {
      window._selectedPages.push(p.page);
      const card = document.getElementById('pageCard-' + p.page);
      if (card) {
        card.classList.add('selected');
        document.getElementById('chk-' + p.page).checked = true;
        card.querySelector('.area-name-field').style.display = 'block';
      }
    }
  });
  updateSelectedCount();
}

function updateSelectedCount() {
  const cnt = window._selectedPages.length;
  document.getElementById('selectedCount').textContent = cnt + '\uac1c \uc120\ud0dd\ub428';
  document.getElementById('btnToStep3').disabled = cnt === 0;
}

/* ── Step 3: 파싱 결과 렌더 ─────────────────────── */
function lxToColor(value, min, max) {
  if (min === max) return { bg: 'hsl(120,60%,55%)', light: false };
  const ratio = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const hue = 240 - ratio * 240;
  const lPeak = 60, lEdge = 45;
  const light = lEdge + (lPeak - lEdge) * Math.sin(ratio * Math.PI);
  const sat = 70 - ratio * 10;
  const isLight = light > 54;
  return { bg: `hsl(${hue.toFixed(0)},${sat.toFixed(0)}%,${light.toFixed(0)}%)`, light: isLight };
}

function calcStats(grid) {
  const flat = grid.flat().filter(v => v !== null && !isNaN(v)).map(Number);
  if (!flat.length) return null;
  const eav = flat.reduce((a,b)=>a+b,0)/flat.length;
  const emin = Math.min(...flat), emax = Math.max(...flat);
  return {
    eav: eav.toFixed(0), emin, emax,
    uo: (emin/eav).toFixed(2), ud: (emin/emax).toFixed(2), count: flat.length
  };
}

function renderMiniHeatmap(design, rows, cols, xLabels, yLabels) {
  if (!design || !design.length) return '';
  const flat = design.flat();
  const gmin = Math.min(...flat), gmax = Math.max(...flat);

  // X/Y 레이블 (서버 값 우선, 없으면 기본값)
  if (!xLabels || !xLabels.length)
    xLabels = Array.from({length: cols}, (_,i) => (cols > 1 ? (i * (35/(cols-1))).toFixed(0) : i) + 'm');
  if (!yLabels || !yLabels.length)
    yLabels = Array.from({length: rows}, (_,i) => (rows > 1 ? (i * (14/(rows-1))).toFixed(0) : i*2) + 'm');

  let html = '<div class="mini-heatmap-wrap"><table class="mini-heatmap-table"><thead><tr><th></th>';
  xLabels.forEach(l => { html += `<th>${l}</th>`; });
  html += '</tr></thead><tbody>';

  // Y축 역순 렌더 (ri=rows-1 먼저)
  for (let ri = rows - 1; ri >= 0; ri--) {
    html += `<tr><th style="text-align:right;padding-right:4px">${yLabels[ri]}</th>`;
    for (let ci = 0; ci < cols; ci++) {
      const val = design[ri][ci];
      const { bg, light } = lxToColor(val, gmin, gmax);
      html += `<td style="background:${bg};color:${light?'#0f172a':'#fff'}">${val}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  return html;
}

async function parseAndRenderStep3() {
  const container = document.getElementById('parseResultAreas');
  container.innerHTML = '<div class="text-muted text-center py-3">&#9654; \uc11c\ubc84\uc5d0\uc11c \uaca9\uc790 \ub370\uc774\ud130 \ud30c\uc2f1 \uc911...</div>';

  if (!window._uploadToken || !window._selectedPages.length) {
    container.innerHTML = '<div class="text-muted text-center py-4" style="font-size:.85rem">\uc120\ud0dd\ub41c \uaca9\uc790\ud45c\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.<br>Step 2\ub85c \ub3cc\uc544\uac00 \ud398\uc774\uc9c0\ub97c \uc120\ud0dd\ud574\uc8fc\uc138\uc694.</div>';
    return;
  }

  // 선택 페이지 → selections 배열 빌드 (page_index는 0-base)
  const selections = window._selectedPages.map(pageNum => {
    const page = (window._parsedPages || []).find(p => p.page === pageNum);
    const areaNameEl = document.getElementById('areaName-' + pageNum);
    return {
      page_index: page ? page.page_index : pageNum - 1,
      area_name: (areaNameEl && areaNameEl.value.trim()) || page?.suggested_name || ('\uad6c\uc5ed' + pageNum),
    };
  });

  try {
    const resp = await fetch(PAGE_DATA.apiParsePagesUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({upload_token: window._uploadToken, selections}),
    });
    const data = await resp.json();

    if (!data.success) {
      container.innerHTML = '<div class="text-danger py-3">\ud30c\uc2f1 \uc624\ub958: ' + (data.error || '\uc54c \uc218 \uc5c6\uc74c') + '</div>';
      return;
    }

    window._serverAreas = data.areas;
    document.getElementById('hiddenAreasJson').value = JSON.stringify(data.areas);

    renderParseResults(data.areas);

  } catch (err) {
    container.innerHTML = '<div class="text-danger py-3">\ud1b5\uc2e0 \uc624\ub958: ' + err.message + '</div>';
  }
}

function renderParseResults(areas) {
  const container = document.getElementById('parseResultAreas');
  container.innerHTML = '';

  if (!areas || !areas.length) {
    container.innerHTML = '<div class="text-muted text-center py-4" style="font-size:.85rem">\ud30c\uc2f1\ub41c \uaca9\uc790 \ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.</div>';
    return;
  }

  areas.forEach((area, idx) => {
    const design = area.design_grid || [];
    const rows = area.grid_rows || design.length;
    const cols = area.grid_cols || (design[0] ? design[0].length : 0);
    const xLabels = area.x_labels || [];
    const yLabels = area.y_labels || [];
    const stats = calcStats(design);
    const heatmapHtml = renderMiniHeatmap(design, rows, cols, xLabels, yLabels);

    const div = document.createElement('div');
    div.className = 'mb-3';
    div.innerHTML = `
      <div class="d-flex align-items-center gap-2 mb-2">
        <span class="badge bg-primary" style="white-space:nowrap">P.${area.page_num}</span>
        <strong style="font-size:.9rem">${area.area_name}</strong>
        <span class="badge bg-light text-dark" style="font-size:.65rem;white-space:nowrap">${rows}\u00d7${cols} \uaca9\uc790</span>
      </div>
      ${heatmapHtml}
      ${stats ? `
      <div class="result-stat-bar">
        <div class="result-stat"><span class="lbl">Eav</span><span class="val">${area.design_eav ? area.design_eav.toFixed(0) : stats.eav}</span><span class="unit">lx</span></div>
        <div class="result-stat"><span class="lbl">Emin</span><span class="val">${area.design_emin || stats.emin}</span><span class="unit">lx</span></div>
        <div class="result-stat"><span class="lbl">Emax</span><span class="val">${area.design_emax || stats.emax}</span><span class="unit">lx</span></div>
        <div class="result-stat"><span class="lbl">Uo</span><span class="val">${area.design_uo ? area.design_uo.toFixed(2) : stats.uo}</span><span class="unit">Emin/Eav</span></div>
        <div class="result-stat"><span class="lbl">Ud</span><span class="val">${area.design_ud ? area.design_ud.toFixed(2) : stats.ud}</span><span class="unit">Emin/Emax</span></div>
      </div>` : ''}`;

    if (idx < areas.length - 1) {
      div.appendChild(Object.assign(document.createElement('hr'), {className: 'mt-3 mb-3'}));
    }
    container.appendChild(div);
  });
}
