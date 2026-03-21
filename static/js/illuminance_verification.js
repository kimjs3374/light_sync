/* ══════════════════════════════════════════════════════════
   조도설계 검증 시스템 — 4개 컴포넌트
   IlluminanceHeatmap / IlluminanceInputGrid /
   SequentialInputModal / DiffMap
══════════════════════════════════════════════════════════ */

/* ── 0. 데이터 (PAGE_DATA에서 주입) ─────────────────────── */
const ILV_DATA = {
  rows: 8,
  cols: 16,
  xLabels: ['0','2.3','4.7','7.0','9.3','11.6','14.0','16.3','18.6','21.0','23.3','25.6','28.0','30.3','32.6','35'].map(v => v+'m'),
  yLabels: ['0m','2m','4m','6m','8m','10m','12m','14m'],
  design: [
    [423,538,665,723,781,710,540,518,529,585,736,786,716,660,530,417],
    [443,539,666,696,738,696,628,632,647,661,728,741,690,665,534,438],
    [455,519,617,673,636,608,654,691,702,676,629,641,671,611,516,453],
    [453,509,564,597,593,600,638,705,709,652,608,591,597,560,508,453],
    [452,508,559,595,593,611,655,710,705,638,601,593,597,564,510,454],
    [453,516,612,670,643,630,678,705,693,655,606,638,674,618,521,456],
    [441,534,666,691,741,729,664,651,634,630,698,738,699,669,540,445],
    [419,533,663,716,789,739,588,533,521,544,713,785,724,669,541,425]
  ],
  // 실측값: null = 미입력
  measured: Array.from({length:8}, () => Array(16).fill(null))
};

/* ── 1. 색상 유틸 ─────────────────────────────────────── */
/**
 * lxToColor(value, min, max)
 * 저조도→파랑, 중간→연두, 고조도→빨강
 * HSL 기반 선형 보간: 240(파)→120(초)→0(빨)
 */
function lxToColor(value, min, max) {
  if (min === max) return { bg: 'hsl(120,60%,55%)', light: false };
  const ratio = Math.max(0, Math.min(1, (value - min) / (max - min)));
  // 0→240(파랑), 0.5→120(초록), 1→0(빨강)
  const hue = 240 - ratio * 240;
  // 밝기: 중간이 가장 밝게 (45~65%)
  const lPeak = 60;
  const lEdge = 45;
  const light = lEdge + (lPeak - lEdge) * Math.sin(ratio * Math.PI);
  const sat = 70 - ratio * 10;
  // 배경 대비 텍스트 색 결정
  const isLight = light > 54;
  return {
    bg: `hsl(${hue.toFixed(0)},${sat.toFixed(0)}%,${light.toFixed(0)}%)`,
    light: isLight   // true→검정 텍스트, false→흰색 텍스트
  };
}

/**
 * diffToColor(pct)
 * +10↑=파랑, ±10=중립, -10~-20=주황, -20↓=빨강
 */
function diffToColor(pct) {
  if (pct === null) return { bg: '#f1f5f9', txt: '#94a3b8' };
  if (pct > 10)  return { bg: '#dbeafe', txt: '#1d4ed8' };
  if (pct >= -10) return { bg: '#f0fdf4', txt: '#15803d' };
  if (pct >= -20) return { bg: '#fff7ed', txt: '#c2410c' };
  return { bg: '#fef2f2', txt: '#b91c1c' };
}

/* ── 2. 통계 계산 ─────────────────────────────────────── */
function calcStats(grid) {
  const flat = grid.flat().filter(v => v !== null && v !== '' && !isNaN(v)).map(Number);
  if (!flat.length) return null;
  const eav = flat.reduce((a,b)=>a+b,0)/flat.length;
  const emin = Math.min(...flat);
  const emax = Math.max(...flat);
  const uo = emin / eav;
  const ud = emin / emax;
  return { eav: eav.toFixed(0), emin, emax, uo: uo.toFixed(2), ud: ud.toFixed(2), count: flat.length };
}

function renderStats(containerId, stats, label='') {
  const el = document.getElementById(containerId);
  if (!stats) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="ilv-stat"><span class="ilv-stat-label">Eav${label}</span><span class="ilv-stat-value">${stats.eav}</span><span class="ilv-stat-unit">lx</span></div>
    <div class="ilv-stat"><span class="ilv-stat-label">Emin</span><span class="ilv-stat-value">${stats.emin}</span><span class="ilv-stat-unit">lx</span></div>
    <div class="ilv-stat"><span class="ilv-stat-label">Emax</span><span class="ilv-stat-value">${stats.emax}</span><span class="ilv-stat-unit">lx</span></div>
    <div class="ilv-stat"><span class="ilv-stat-label">Uo (균일도)</span><span class="ilv-stat-value">${stats.uo}</span><span class="ilv-stat-unit">Emin/Eav</span></div>
    <div class="ilv-stat"><span class="ilv-stat-label">Ud</span><span class="ilv-stat-value">${stats.ud}</span><span class="ilv-stat-unit">Emin/Emax</span></div>
    <div class="ilv-stat"><span class="ilv-stat-label">입력</span><span class="ilv-stat-value">${stats.count}</span><span class="ilv-stat-unit">/ ${ILV_DATA.rows*ILV_DATA.cols}</span></div>
  `;
}

/* ══════════════════════════════════════════════════════════
   컴포넌트 A: IlluminanceHeatmap
══════════════════════════════════════════════════════════ */
class IlluminanceHeatmap {
  constructor(tableId, data) {
    this.tableId = tableId;
    this.data = data;
    this.render();
  }

  render() {
    const { rows, cols, xLabels, yLabels, design } = this.data;
    const flat = design.flat();
    const gmin = Math.min(...flat);
    const gmax = Math.max(...flat);

    const tbl = document.getElementById(this.tableId);
    tbl.innerHTML = '';

    // X축 헤더
    const thead = tbl.createTHead();
    const hrow = thead.insertRow();
    // Y축 공백
    const thCorner = document.createElement('th');
    thCorner.className = 'ilv-yaxis';
    hrow.appendChild(thCorner);
    xLabels.forEach(lbl => {
      const th = document.createElement('th');
      th.className = 'ilv-xaxis';
      th.textContent = lbl;
      hrow.appendChild(th);
    });

    // tbody — Y축 반전: 높은 Y값(14m)이 상단, 0m이 하단
    const tbody = tbl.createTBody();
    for (let ri = rows - 1; ri >= 0; ri--) {
      const rowData = design[ri];
      const tr = tbody.insertRow();
      const yth = document.createElement('th');
      yth.className = 'ilv-yaxis';
      yth.scope = 'row';
      yth.textContent = yLabels[ri];
      tr.appendChild(yth);

      rowData.forEach((val, ci) => {
        const td = tr.insertCell();
        const { bg, light } = lxToColor(val, gmin, gmax);
        td.className = 'ilv-cell';
        td.style.background = bg;
        td.style.color = light ? '#0f172a' : '#ffffff';
        td.textContent = val;
        td.setAttribute('title', `Y=${yLabels[ri]}, X=${xLabels[ci]} : ${val} lx`);
        td.setAttribute('aria-label', `${yLabels[ri]} ${xLabels[ci]} ${val}룩스`);
        if (val === gmin) td.classList.add('is-min');
        if (val === gmax) td.classList.add('is-max');
      });
    }

    // 통계
    const stats = calcStats(design);
    renderStats('heatmapStats', stats);
  }
}

/* ══════════════════════════════════════════════════════════
   컴포넌트 B: IlluminanceInputGrid
══════════════════════════════════════════════════════════ */
class IlluminanceInputGrid {
  constructor(tableId, data) {
    this.tableId = tableId;
    this.data = data;
    this.inputs = [];   // [r][c] → <input>
    this.render();
    this._setupKeyNav();
  }

  render() {
    const { rows, cols, xLabels, yLabels, design, measured } = this.data;
    const flat = design.flat();
    const gmin = Math.min(...flat);
    const gmax = Math.max(...flat);

    const tbl = document.getElementById(this.tableId);
    tbl.innerHTML = '';
    this.inputs = [];

    // X축 헤더
    const thead = tbl.createTHead();
    const hrow = thead.insertRow();
    const thCorner = document.createElement('th');
    thCorner.className = 'ilv-yaxis';
    hrow.appendChild(thCorner);
    xLabels.forEach(lbl => {
      const th = document.createElement('th');
      th.className = 'ilv-xaxis';
      th.textContent = lbl;
      hrow.appendChild(th);
    });

    // tbody — Y축 반전: 높은 Y값(14m)이 상단, 0m이 하단
    const tbody = tbl.createTBody();
    for (let ri = rows - 1; ri >= 0; ri--) {
      this.inputs[ri] = this.inputs[ri] || [];
      const tr = tbody.insertRow();
      const yth = document.createElement('th');
      yth.className = 'ilv-yaxis';
      yth.scope = 'row';
      yth.textContent = yLabels[ri];
      tr.appendChild(yth);

      for (let ci = 0; ci < cols; ci++) {
        const td = tr.insertCell();
        td.className = 'ilv-input-cell';

        const inp = document.createElement('input');
        inp.type = 'number';
        inp.min = 0;
        inp.max = 99999;
        inp.inputMode = 'numeric';
        inp.placeholder = String(design[ri][ci]);
        inp.setAttribute('data-r', ri);
        inp.setAttribute('data-c', ci);
        inp.setAttribute('aria-label', `Y=${yLabels[ri]} X=${xLabels[ci]} 실측값`);

        if (measured[ri][ci] !== null) {
          inp.value = measured[ri][ci];
        }

        inp.addEventListener('input', () => this._onInput(inp, td, ri, ci, gmin, gmax));
        inp.addEventListener('focus', () => inp.select());

        td.appendChild(inp);
        this.inputs[ri][ci] = inp;

        if (measured[ri][ci] !== null) {
          this._applyColor(inp, td, measured[ri][ci], design[ri][ci], gmin, gmax);
        }
      }
    }
    this._updateStats();
  }

  _onInput(inp, td, ri, ci, gmin, gmax) {
    const val = inp.value === '' ? null : parseFloat(inp.value);
    ILV_DATA.measured[ri][ci] = val;
    this._applyColor(inp, td, val, ILV_DATA.design[ri][ci], gmin, gmax);
    this._updateStats();
    updateDiffBadge();
  }

  _applyColor(inp, td, val, designVal, gmin, gmax) {
    // 배경색 (히트맵)
    if (val !== null && !isNaN(val)) {
      const { bg, light } = lxToColor(val, gmin, gmax);
      inp.style.background = bg;
      inp.style.color = light ? '#0f172a' : '#fff';
    } else {
      inp.style.background = '';
      inp.style.color = '';
    }
    // 달성률 테두리
    td.classList.remove('status-ok','status-warn','status-err');
    if (val !== null && !isNaN(val) && designVal > 0) {
      const ratio = val / designVal;
      if (ratio >= 0.9)      td.classList.add('status-ok');
      else if (ratio >= 0.7) td.classList.add('status-warn');
      else                   td.classList.add('status-err');
    }
  }

  _setupKeyNav() {
    const tbl = document.getElementById(this.tableId);
    tbl.addEventListener('keydown', (e) => {
      const inp = e.target;
      if (!inp.matches('input[type="number"]')) return;
      const r = parseInt(inp.dataset.r);
      const c = parseInt(inp.dataset.c);
      let nr = r, nc = c;

      if (e.key === 'Tab' && !e.shiftKey) {
        e.preventDefault();
        nc = c + 1;
        if (nc >= ILV_DATA.cols) { nc = 0; nr = r + 1; }
        if (nr >= ILV_DATA.rows) { nr = 0; }
      } else if (e.key === 'Tab' && e.shiftKey) {
        e.preventDefault();
        nc = c - 1;
        if (nc < 0) { nc = ILV_DATA.cols - 1; nr = r - 1; }
        if (nr < 0) { nr = ILV_DATA.rows - 1; }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        nc = c + 1;
        if (nc >= ILV_DATA.cols) { nc = 0; nr = r + 1; }
        if (nr >= ILV_DATA.rows) { nr = 0; }
      } else if (e.key === 'ArrowRight') {
        nc = Math.min(c + 1, ILV_DATA.cols - 1);
      } else if (e.key === 'ArrowLeft') {
        nc = Math.max(c - 1, 0);
      } else if (e.key === 'ArrowDown') {
        nr = Math.min(r + 1, ILV_DATA.rows - 1);
      } else if (e.key === 'ArrowUp') {
        nr = Math.max(r - 1, 0);
      } else return;

      const target = this.inputs[nr]?.[nc];
      if (target) { target.focus(); target.select(); }
    });
  }

  _updateStats() {
    const stats = calcStats(ILV_DATA.measured);
    renderStats('inputStats', stats, ' (실측)');
  }

  // 외부에서 셀 값 갱신 (SequentialInputModal → grid 동기화)
  setValue(r, c, val) {
    ILV_DATA.measured[r][c] = val;
    const inp = this.inputs[r]?.[c];
    const td = inp?.parentElement;
    if (!inp) return;
    inp.value = val !== null ? val : '';
    const flat = ILV_DATA.design.flat();
    this._applyColor(inp, td, val, ILV_DATA.design[r][c], Math.min(...flat), Math.max(...flat));
    this._updateStats();
    updateDiffBadge();
  }
}

/* ══════════════════════════════════════════════════════════
   컴포넌트 C: SequentialInputModal
══════════════════════════════════════════════════════════ */
class SequentialInputModal {
  constructor(data, gridRef) {
    this.data = data;
    this.grid = gridRef;
    this.cursor = 0;   // 0..rows*cols-1
    this.total = data.rows * data.cols;
    this._initMinimap();
    this._bindEvents();
  }

  get curR() { return Math.floor(this.cursor / this.data.cols); }
  get curC() { return this.cursor % this.data.cols; }

  _initMinimap() {
    const mm = document.getElementById('seqMinimap');
    mm.style.gridTemplateColumns = `repeat(${this.data.cols}, 1fr)`;
    mm.innerHTML = '';
    for (let i = 0; i < this.total; i++) {
      const cell = document.createElement('div');
      cell.className = 'seq-minimap-cell pending';
      cell.style.background = '#e2e8f0';
      cell.id = `smcell-${i}`;
      mm.appendChild(cell);
    }
  }

  _updateUI() {
    const r = this.curR, c = this.curC;
    const designVal = this.data.design[r][c];
    const existing = this.data.measured[r][c];

    document.getElementById('seqCoordLabel').textContent =
      `Row ${r+1}, Col ${c+1} — Y=${this.data.yLabels[r]}, X=${this.data.xLabels[c]}`;
    document.getElementById('seqDesignVal').textContent = designVal;
    document.getElementById('seqCellLabel').textContent =
      `${this.cursor+1} / ${this.total}`;

    const inp = document.getElementById('seqInput');
    inp.value = existing !== null ? existing : '';
    inp.focus();

    // 진행바
    const done = this.data.measured.flat().filter(v=>v!==null).length;
    const pct = Math.round(done/this.total*100);
    document.getElementById('seqProgress').style.width = pct+'%';
    document.getElementById('seqProgressLabel').textContent = `${done} / ${this.total} 완료`;

    // 미니맵 갱신
    this._refreshMinimap();
  }

  _refreshMinimap() {
    const flat = this.data.design.flat();
    const gmin = Math.min(...flat), gmax = Math.max(...flat);
    for (let i = 0; i < this.total; i++) {
      const ri = Math.floor(i / this.data.cols);
      const ci = i % this.data.cols;
      const cell = document.getElementById(`smcell-${i}`);
      const mval = this.data.measured[ri][ci];
      cell.classList.remove('done','current','pending');
      if (i === this.cursor) {
        cell.classList.add('current');
        cell.style.background = '#2563eb';
      } else if (mval !== null) {
        cell.classList.add('done');
        const { bg } = lxToColor(mval, gmin, gmax);
        cell.style.background = bg;
      } else {
        cell.classList.add('pending');
        cell.style.background = '#e2e8f0';
      }
    }
  }

  _commit() {
    const val = document.getElementById('seqInput').value;
    const parsed = val === '' ? null : parseFloat(val);
    this.grid.setValue(this.curR, this.curC, parsed);
    this._refreshMinimap();
  }

  _bindEvents() {
    document.getElementById('seqNext').addEventListener('click', () => {
      this._commit();
      if (this.cursor < this.total - 1) this.cursor++;
      this._updateUI();
    });

    document.getElementById('seqPrev').addEventListener('click', () => {
      this._commit();
      if (this.cursor > 0) this.cursor--;
      this._updateUI();
    });

    // 엔터 → 다음
    document.getElementById('seqInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        document.getElementById('seqNext').click();
      }
    });

    // 모달 열릴 때
    document.getElementById('seqModal').addEventListener('show.bs.modal', () => {
      this._updateUI();
    });
  }
}

/* ══════════════════════════════════════════════════════════
   컴포넌트 D: DiffMap
══════════════════════════════════════════════════════════ */
class DiffMap {
  constructor(tableId, data) {
    this.tableId = tableId;
    this.data = data;
  }

  render() {
    const { rows, cols, xLabels, yLabels, design, measured } = this.data;
    const filledCount = measured.flat().filter(v=>v!==null).length;

    if (filledCount === 0) {
      document.getElementById('diffEmpty').style.display = 'block';
      document.getElementById('diffContent').style.display = 'none';
      return;
    }
    document.getElementById('diffEmpty').style.display = 'none';
    document.getElementById('diffContent').style.display = 'block';

    const tbl = document.getElementById(this.tableId);
    tbl.innerHTML = '';

    // X축 헤더
    const thead = tbl.createTHead();
    const hrow = thead.insertRow();
    const thCorner = document.createElement('th');
    thCorner.className = 'ilv-yaxis';
    hrow.appendChild(thCorner);
    xLabels.forEach(lbl => {
      const th = document.createElement('th');
      th.className = 'ilv-xaxis';
      th.textContent = lbl;
      hrow.appendChild(th);
    });

    // Y축 반전: 높은 Y값(14m)이 상단, 0m이 하단
    const tbody = tbl.createTBody();
    const diffGrid = [];
    for (let ri = rows - 1; ri >= 0; ri--) {
      diffGrid[ri] = [];
      const tr = tbody.insertRow();
      const yth = document.createElement('th');
      yth.className = 'ilv-yaxis';
      yth.scope = 'row';
      yth.textContent = yLabels[ri];
      tr.appendChild(yth);

      for (let ci = 0; ci < cols; ci++) {
        const td = tr.insertCell();
        const dval = design[ri][ci];
        const mval = measured[ri][ci];
        let pct = null;
        if (mval !== null && dval > 0) {
          pct = ((mval - dval) / dval) * 100;
        }
        diffGrid[ri][ci] = pct;

        const { bg, txt } = diffToColor(pct);
        td.className = 'ilv-diff-cell';
        td.style.background = bg;
        td.style.color = txt;
        td.textContent = pct !== null
          ? (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%'
          : '\u2014';
        td.setAttribute('title', pct !== null
          ? `설계 ${dval}lx / 실측 ${mval}lx / 차이 ${pct.toFixed(1)}%`
          : '미입력');
      }
    }

    // DiffMap 통계
    this._renderDiffStats(diffGrid, filledCount);
  }

  _renderDiffStats(diffGrid, filledCount) {
    const flat = diffGrid.flat().filter(v=>v!==null);
    if (!flat.length) { document.getElementById('diffStats').innerHTML=''; return; }
    const avg = flat.reduce((a,b)=>a+b,0)/flat.length;
    const underCount = flat.filter(v=>v<-10).length;
    const severeCount = flat.filter(v=>v<-20).length;
    document.getElementById('diffStats').innerHTML = `
      <div class="ilv-stat"><span class="ilv-stat-label">평균 편차</span><span class="ilv-stat-value" style="color:${avg>=0?'#1d4ed8':'#b91c1c'}">${avg>=0?'+':''}${avg.toFixed(1)}</span><span class="ilv-stat-unit">%</span></div>
      <div class="ilv-stat"><span class="ilv-stat-label">-10% 미만</span><span class="ilv-stat-value" style="color:#c2410c">${underCount}</span><span class="ilv-stat-unit">셀</span></div>
      <div class="ilv-stat"><span class="ilv-stat-label">-20% 미만</span><span class="ilv-stat-value" style="color:#b91c1c">${severeCount}</span><span class="ilv-stat-unit">셀</span></div>
      <div class="ilv-stat"><span class="ilv-stat-label">입력 완료</span><span class="ilv-stat-value">${filledCount}</span><span class="ilv-stat-unit">/ ${ILV_DATA.rows*ILV_DATA.cols}</span></div>
    `;
  }
}

/* ── 진행 배지 업데이트 ─────────────────────────────────── */
function updateDiffBadge() {
  const done = ILV_DATA.measured.flat().filter(v=>v!==null).length;
  const total = ILV_DATA.rows * ILV_DATA.cols;
  document.getElementById('diffBadge').textContent = `${done}/${total}`;
  document.getElementById('diffBadge').className = done > 0
    ? 'badge bg-primary ms-1' : 'badge bg-secondary ms-1';
}

/* ── 초기화 버튼 ─────────────────────────────────────────── */
document.getElementById('btnClearInput').addEventListener('click', () => {
  if (!confirm('모든 실측 입력값을 지우겠습니까?')) return;
  ILV_DATA.measured = Array.from({length: ILV_DATA.rows}, () => Array(ILV_DATA.cols).fill(null));
  inputGrid.render();
  updateDiffBadge();
});

/* ── JSON 내보내기 ───────────────────────────────────────── */
document.getElementById('btnExportJSON').addEventListener('click', () => {
  const stats = calcStats(ILV_DATA.measured);
  const payload = {
    generated: new Date().toISOString(),
    rows: ILV_DATA.rows,
    cols: ILV_DATA.cols,
    design: ILV_DATA.design,
    measured: ILV_DATA.measured,
    measured_stats: stats
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'illuminance_verification.json';
  a.click();
  URL.revokeObjectURL(a.href);
});

/* ── DiffMap 탭 활성화 시 렌더 ─────────────────────────── */
document.querySelector('[data-bs-target="#tabDiff"]').addEventListener('show.bs.tab', () => {
  diffMap.render();
});

/* ── 인스턴스 생성 ──────────────────────────────────────── */
const heatmap   = new IlluminanceHeatmap('heatmapTable', ILV_DATA);
const inputGrid = new IlluminanceInputGrid('inputTable', ILV_DATA);
const diffMap   = new DiffMap('diffTable', ILV_DATA);
const seqModal  = new SequentialInputModal(ILV_DATA, inputGrid);
