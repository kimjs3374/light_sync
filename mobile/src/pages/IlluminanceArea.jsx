import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

/* ────────── 색상 헬퍼 ────────── */
function lxToColor(v, min, max) {
  if (v == null || isNaN(v)) return { bg: 'transparent', light: true };
  const span = Math.max(max - min, 1);
  const t = Math.min(1, Math.max(0, (v - min) / span));
  const stops = [
    [0.00, [37, 99, 235]],
    [0.25, [59, 130, 246]],
    [0.50, [34, 197, 94]],
    [0.75, [234, 179, 8]],
    [1.00, [239, 68, 68]],
  ];
  let rgb = stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [p0, c0] = stops[i - 1];
      const [p1, c1] = stops[i];
      const k = (t - p0) / (p1 - p0);
      rgb = c0.map((v, j) => Math.round(v + (c1[j] - v) * k));
      break;
    }
  }
  const [r, g, b] = rgb;
  const lum = (0.299 * r + 0.587 * g + 0.114 * b);
  return { bg: `rgb(${r},${g},${b})`, light: lum > 160 };
}

function diffToColor(pct) {
  if (pct == null || isNaN(pct)) return { bg: 'var(--bg)', txt: 'var(--text-muted)' };
  if (pct >= -10 && pct <= 10) return { bg: 'rgba(34,197,94,0.2)', txt: 'var(--green)' };
  if (pct > 10) return { bg: 'rgba(59,130,246,0.2)', txt: 'var(--accent)' };
  if (pct >= -20) return { bg: 'rgba(234,179,8,0.2)', txt: 'var(--orange)' };
  return { bg: 'rgba(239,68,68,0.2)', txt: 'var(--red)' };
}

function calcStats(grid) {
  const flat = grid.flat().filter(v => v != null && !isNaN(v));
  if (flat.length === 0) return null;
  const eav = flat.reduce((s, v) => s + v, 0) / flat.length;
  const emin = Math.min(...flat);
  const emax = Math.max(...flat);
  const uo = eav ? emin / eav : 0;
  const ud = emax ? emin / emax : 0;
  return {
    eav: eav.toFixed(1),
    emin: emin.toFixed(1),
    emax: emax.toFixed(1),
    uo: uo.toFixed(3),
    ud: ud.toFixed(3),
    count: flat.length,
  };
}

const ksColor = (s) => s === 'PASS' ? 'green' : s === 'WARNING' ? 'orange' : s === 'FAIL' ? 'red' : 'gray';

export default function IlluminanceArea() {
  const { projectId, areaId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('design');
  const [measured, setMeasured] = useState([]);
  const [meta, setMeta] = useState({
    measure_date: new Date().toISOString().slice(0, 10),
    measured_by: '',
    weather: '맑음',
    instrument: '',
    notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [seqOpen, setSeqOpen] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState('');

  const load = () => {
    setLoading(true);
    api.get(`/illuminance/${projectId}/area/${areaId}`)
      .then((d) => {
        setData(d);
        const a = d.area;
        const rows = a.grid_rows || 0;
        const cols = a.grid_cols || 0;
        const latest = a.latest_grid;
        if (latest && latest.length === rows) {
          setMeasured(latest.map(row => [...row]));
        } else {
          setMeasured(Array.from({ length: rows }, () => Array(cols).fill(null)));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, [projectId, areaId]);

  const design = data?.area?.design_grid || [];
  const rows = data?.area?.grid_rows || 0;
  const cols = data?.area?.grid_cols || 0;
  const xLabels = data?.area?.x_labels || [];
  const yLabels = data?.area?.y_labels || [];
  const ksEav = data?.area?.ks_eav_min;
  const ksUo = data?.area?.ks_uo_min;

  const { gmin, gmax } = useMemo(() => {
    const flat = design.flat().filter(v => v != null && !isNaN(v));
    return { gmin: flat.length ? Math.min(...flat) : 0, gmax: flat.length ? Math.max(...flat) : 1 };
  }, [design]);

  const designStats = useMemo(() => calcStats(design), [design]);
  const measuredStats = useMemo(() => calcStats(measured), [measured]);

  const setCell = (r, c, val) => {
    setMeasured(m => {
      const next = m.map(row => [...row]);
      if (!next[r]) next[r] = Array(cols).fill(null);
      next[r][c] = val;
      return next;
    });
  };

  const clearMeasured = () => {
    if (!confirm('실측값을 모두 초기화하시겠습니까?')) return;
    setMeasured(Array.from({ length: rows }, () => Array(cols).fill(null)));
  };

  const save = async () => {
    const filled = measured.flat().filter(v => v != null).length;
    if (filled === 0) return alert('측정값을 입력해주세요');
    setSaving(true);
    try {
      const res = await api.post(`/illuminance/${projectId}/area/${areaId}/measure`, {
        grid_data: measured,
        ...meta,
      });
      alert(`저장 완료\nKS: ${res.ks_pass}\nEav: ${res.measured_eav} lx\nUo: ${res.measured_uo}`);
      load();
    } catch (e) { alert(e.message); }
    setSaving(false);
  };

  const deleteMeasure = async (mid) => {
    if (!confirm('이 실측 기록을 삭제하시겠습니까?')) return;
    try {
      await api.post(`/illuminance/${projectId}/area/${areaId}/measure/${mid}/delete`, {});
      load();
    } catch (e) { alert(e.message); }
  };

  const saveAreaName = async () => {
    const nm = nameDraft.trim();
    if (!nm) return setEditingName(false);
    try {
      await api.post(`/illuminance/${projectId}/area/${areaId}/edit-name`, { area_name: nm });
      setEditingName(false);
      load();
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data?.area) return <div className="page-loader">구역을 찾을 수 없습니다</div>;

  const a = data.area;

  return (
    <div style={{ paddingBottom: 120 }}>
      <div className="channel-header">
        <button onClick={() => navigate(`/illuminance/${projectId}`)} style={s.back}>←</button>
        {editingName ? (
          <div style={{ display: 'flex', gap: 6, flex: 1 }}>
            <input value={nameDraft} onChange={e => setNameDraft(e.target.value)}
              style={{ ...s.inp, flex: 1 }} autoFocus />
            <button onClick={saveAreaName} style={{ ...s.btnSm, color: 'var(--accent)' }}>저장</button>
            <button onClick={() => setEditingName(false)} style={s.btnSm}>취소</button>
          </div>
        ) : (
          <h1 onClick={() => { setNameDraft(a.area_name); setEditingName(true); }} style={{ cursor: 'pointer' }}>
            {a.area_name} ✎
          </h1>
        )}
      </div>

      {/* 구역 정보 */}
      <div style={s.infoBar}>
        <InfoChip label="시설" value={data.facility_type || '-'} />
        <InfoChip label="격자" value={`${rows}×${cols}`} />
        {a.lamp_type && <InfoChip label="광원" value={a.lamp_type} />}
        {a.lamp_watt > 0 && <InfoChip label="W" value={`${a.lamp_watt} × ${a.lamp_qty || 0}`} />}
        {a.installation_height && <InfoChip label="높이" value={`${a.installation_height}m`} />}
      </div>

      {/* KS 기준 */}
      {(ksEav || ksUo) ? (
        <div style={s.ksBar}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginRight: 8 }}>KS 기준</span>
          {ksEav ? <Pill text={`Eav ≥ ${ksEav} lx`} /> : null}
          {ksUo ? <Pill text={`Uo ≥ ${ksUo}`} /> : null}
        </div>
      ) : null}

      {/* 탭 */}
      <div style={s.tabs}>
        {[
          { k: 'design', l: '설계' },
          { k: 'measured', l: `실측 (${measured.flat().filter(v => v != null).length}/${design.flat().filter(v => v != null).length})` },
          { k: 'diff', l: '달성률' },
          { k: 'history', l: `기록(${data.measurements?.length || 0})` },
        ].map(t => (
          <button key={t.k} onClick={() => setTab(t.k)}
            style={{ ...s.tab, ...(tab === t.k ? s.tabActive : {}) }}>
            {t.l}
          </button>
        ))}
      </div>

      {/* 통계 */}
      {(tab === 'design' || tab === 'measured' || tab === 'diff') && (
        <StatBar
          stats={tab === 'design' ? designStats : measuredStats}
          ksEav={ksEav} ksUo={ksUo}
          showKs={tab === 'measured' || tab === 'diff'}
        />
      )}

      {/* 콘텐츠 */}
      {tab === 'design' && (
        <GridView mode="design" grid={design} xLabels={xLabels} yLabels={yLabels} gmin={gmin} gmax={gmax} />
      )}

      {tab === 'measured' && (
        <>
          <MeasureMeta meta={meta} setMeta={setMeta} />
          <GridView mode="input" grid={measured} design={design} xLabels={xLabels} yLabels={yLabels}
            gmin={gmin} gmax={gmax} onCell={setCell} />
          <div style={{ display: 'flex', gap: 6, padding: '10px 16px', flexWrap: 'wrap' }}>
            <button onClick={() => setSeqOpen(true)} style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)' }}>
              한 칸씩 입력
            </button>
            <button onClick={clearMeasured} style={{ ...s.btn, background: 'var(--surface)', color: 'var(--red)' }}>
              초기화
            </button>
            <button onClick={save} disabled={saving} style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>
              {saving ? '저장중...' : '실측값 저장'}
            </button>
          </div>
        </>
      )}

      {tab === 'diff' && (
        <DiffView design={design} measured={measured} xLabels={xLabels} yLabels={yLabels} />
      )}

      {tab === 'history' && (
        <HistoryView measurements={data.measurements || []} onDelete={deleteMeasure}
          design={design} xLabels={xLabels} yLabels={yLabels} gmin={gmin} gmax={gmax} />
      )}

      {seqOpen && (
        <SequentialModal
          design={design} measured={measured}
          xLabels={xLabels} yLabels={yLabels}
          gmin={gmin} gmax={gmax}
          onCell={setCell}
          onClose={() => setSeqOpen(false)}
        />
      )}
    </div>
  );
}

/* ────────── 구역 정보 칩 ────────── */
function InfoChip({ label, value }) {
  return (
    <div style={s.chip}>
      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function Pill({ text }) {
  return <span style={s.pill}>{text}</span>;
}

/* ────────── 통계 바 ────────── */
function StatBar({ stats, ksEav, ksUo, showKs }) {
  if (!stats) return (
    <div style={{ padding: '8px 16px', fontSize: 11, color: 'var(--text-muted)' }}>
      데이터 없음
    </div>
  );
  const ksPass = showKs && ksEav && parseFloat(stats.eav) >= ksEav
    && (!ksUo || parseFloat(stats.uo) >= ksUo);
  return (
    <div style={s.statBar}>
      <Stat label="Eav" value={stats.eav} unit="lx" highlight={showKs ? (ksPass ? 'green' : 'red') : null} />
      <Stat label="Emin" value={stats.emin} unit="lx" />
      <Stat label="Emax" value={stats.emax} unit="lx" />
      <Stat label="Uo" value={stats.uo} highlight={showKs && ksUo ? (parseFloat(stats.uo) >= ksUo ? 'green' : 'red') : null} />
      <Stat label="Ud" value={stats.ud} />
      <Stat label="측점" value={stats.count} />
    </div>
  );
}

function Stat({ label, value, unit, highlight }) {
  return (
    <div style={s.statItem}>
      <div style={{
        fontSize: 13, fontWeight: 700,
        color: highlight === 'green' ? 'var(--green)'
            : highlight === 'red' ? 'var(--red)'
            : 'var(--text-bright)',
        fontFamily: 'var(--mono, monospace)',
      }}>{value}{unit && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}> {unit}</span>}</div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label}</div>
    </div>
  );
}

/* ────────── 격자 뷰 (heatmap/input) ────────── */
function GridView({ mode, grid, design, xLabels, yLabels, gmin, gmax, onCell }) {
  const rows = grid.length;
  const cols = grid[0]?.length || 0;
  return (
    <div style={{ overflowX: 'auto', padding: '4px 10px 12px', WebkitOverflowScrolling: 'touch' }}>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}></th>
            {xLabels.map((l, i) => <th key={i} style={s.th}>{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, rIdx) => {
            const ri = rows - 1 - rIdx;
            return (
              <tr key={ri}>
                <th style={s.yTh}>{yLabels[ri]}</th>
                {Array.from({ length: cols }).map((_, ci) => {
                  const designVal = design?.[ri]?.[ci];
                  const val = grid[ri]?.[ci];
                  if (mode === 'input') {
                    const disabled = design && designVal == null;
                    const { bg, light } = (val != null && !isNaN(val)) ? lxToColor(val, gmin, gmax) : { bg: '', light: true };
                    const ratio = (val != null && designVal > 0) ? val / designVal : null;
                    const border = ratio == null ? 'var(--border)'
                      : ratio >= 0.9 ? 'var(--green)'
                      : ratio >= 0.7 ? 'var(--orange)'
                      : 'var(--red)';
                    return (
                      <td key={ci} style={s.td}>
                        <input
                          type="number" inputMode="numeric"
                          disabled={disabled}
                          value={val == null ? '' : val}
                          placeholder={disabled ? '—' : String(designVal ?? '')}
                          onChange={e => {
                            const v = e.target.value === '' ? null : parseFloat(e.target.value);
                            onCell(ri, ci, v);
                          }}
                          onFocus={e => e.target.select()}
                          style={{
                            ...s.cellInput,
                            background: disabled ? 'var(--bg)' : (bg || 'var(--surface)'),
                            color: !bg ? 'var(--text-bright)' : (light ? '#0f172a' : '#fff'),
                            border: `2px solid ${border}`,
                            opacity: disabled ? 0.4 : 1,
                          }}
                        />
                      </td>
                    );
                  }
                  const { bg, light } = (val != null) ? lxToColor(val, gmin, gmax) : { bg: 'var(--bg)', light: true };
                  return (
                    <td key={ci} style={{ ...s.cell, background: bg, color: light ? '#0f172a' : '#fff' }}>
                      {val != null ? Math.round(val) : '—'}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ────────── 차이(달성률) 뷰 ────────── */
function DiffView({ design, measured, xLabels, yLabels }) {
  const rows = design.length;
  const cols = design[0]?.length || 0;
  const filled = measured.flat().filter(v => v != null).length;
  if (filled === 0) {
    return <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
      실측값을 입력하면 설계와의 차이가 표시됩니다.
    </div>;
  }
  const pctGrid = design.map((row, ri) => row.map((dv, ci) => {
    const mv = measured[ri]?.[ci];
    if (mv == null || dv == null || dv === 0) return null;
    return (mv - dv) / dv * 100;
  }));
  const flat = pctGrid.flat().filter(v => v != null);
  const ok = flat.filter(v => v >= -10 && v <= 10).length;
  const warn = flat.filter(v => v < -10 && v >= -20).length;
  const bad = flat.filter(v => v < -20).length;
  const excess = flat.filter(v => v > 10).length;
  return (
    <>
      <div style={{ padding: '8px 16px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <Badge2 text={`정상 ${ok}`} color="green" />
        <Badge2 text={`주의 ${warn}`} color="orange" />
        <Badge2 text={`불량 ${bad}`} color="red" />
        <Badge2 text={`초과 ${excess}`} color="accent" />
        <Badge2 text={`달성 ${flat.length ? (ok / flat.length * 100).toFixed(0) : 0}%`}
          color={flat.length && ok / flat.length >= 0.9 ? 'green' : 'red'} />
      </div>
      <div style={{ overflowX: 'auto', padding: '4px 10px 12px' }}>
        <table style={s.table}>
          <thead>
            <tr>
              <th style={s.th}></th>
              {xLabels.map((l, i) => <th key={i} style={s.th}>{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }).map((_, rIdx) => {
              const ri = rows - 1 - rIdx;
              return (
                <tr key={ri}>
                  <th style={s.yTh}>{yLabels[ri]}</th>
                  {Array.from({ length: cols }).map((_, ci) => {
                    const pct = pctGrid[ri][ci];
                    const { bg, txt } = diffToColor(pct);
                    return (
                      <td key={ci} style={{ ...s.cell, background: bg, color: txt, fontWeight: 700 }}>
                        {pct != null ? (pct > 0 ? '+' : '') + pct.toFixed(0) + '%' : '—'}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Badge2({ text, color }) {
  return <span className={`badge badge-${color}`}>{text}</span>;
}

/* ────────── 실측 메타 ────────── */
function MeasureMeta({ meta, setMeta }) {
  return (
    <div style={{ padding: '6px 16px 0', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
      <div><div style={s.fl}>측정일</div>
        <input type="date" value={meta.measure_date}
          onChange={e => setMeta(m => ({ ...m, measure_date: e.target.value }))} style={s.inp} /></div>
      <div><div style={s.fl}>측정자</div>
        <input type="text" value={meta.measured_by} placeholder="이름"
          onChange={e => setMeta(m => ({ ...m, measured_by: e.target.value }))} style={s.inp} /></div>
      <div><div style={s.fl}>날씨</div>
        <select value={meta.weather} onChange={e => setMeta(m => ({ ...m, weather: e.target.value }))} style={s.inp}>
          {['맑음', '흐림', '비', '눈', '야간'].map(w => <option key={w}>{w}</option>)}
        </select></div>
      <div><div style={s.fl}>측정기</div>
        <input type="text" value={meta.instrument} placeholder="조도계 모델명"
          onChange={e => setMeta(m => ({ ...m, instrument: e.target.value }))} style={s.inp} /></div>
      <div style={{ gridColumn: '1 / -1' }}>
        <div style={s.fl}>비고</div>
        <input type="text" value={meta.notes} placeholder="특이사항"
          onChange={e => setMeta(m => ({ ...m, notes: e.target.value }))} style={s.inp} />
      </div>
    </div>
  );
}

/* ────────── 기록 탭 ────────── */
function HistoryView({ measurements, onDelete, design, xLabels, yLabels, gmin, gmax }) {
  const [expanded, setExpanded] = useState({});
  const toggle = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }));

  if (measurements.length === 0) return (
    <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
      실측 기록이 없습니다.
    </div>
  );
  return (
    <div style={{ padding: '8px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      {measurements.slice().reverse().map(m => {
        const grid = m.measured_grid || [];
        const hasGrid = grid.length > 0 && grid[0]?.length > 0;
        const rows = grid.length;
        const cols = grid[0]?.length || 0;
        const flat = grid.flat().filter(v => v != null && !isNaN(v));
        const gridMin = flat.length ? Math.min(...flat) : gmin;
        const gridMax = flat.length ? Math.max(...flat) : gmax;
        return (
          <div key={m.id} style={s.histCard}>
            {/* 헤더 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>
                {m.measure_date}
                {m.measured_by && <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>· {m.measured_by}</span>}
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                {m.ks_pass && <span className={`badge badge-${ksColor(m.ks_pass)}`}>{m.ks_pass}</span>}
                {hasGrid && (
                  <button onClick={() => toggle(m.id)} style={{ ...s.btnSm, color: 'var(--accent)' }}>
                    {expanded[m.id] ? '접기' : '격자보기'}
                  </button>
                )}
                <button onClick={() => onDelete(m.id)} style={{ ...s.btnSm, color: 'var(--red)' }}>삭제</button>
              </div>
            </div>

            {/* 메타 */}
            <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {m.weather && <span>{m.weather}</span>}
              {m.instrument && <span>{m.instrument}</span>}
            </div>

            {/* 통계 */}
            <div style={{ fontSize: 11, marginTop: 4, color: 'var(--text-bright)', fontFamily: 'monospace' }}>
              Eav <b>{m.measured_eav ?? '-'}</b> lx · Emin <b>{m.measured_emin ?? '-'}</b> · Emax <b>{m.measured_emax ?? '-'}</b>
              &nbsp;· Uo <b>{m.measured_uo ?? '-'}</b> · Ud <b>{m.measured_ud ?? '-'}</b>
            </div>
            {m.eav_achievement != null && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                달성률 Eav <b style={{ color: m.eav_achievement >= 90 ? 'var(--green)' : 'var(--red)' }}>{m.eav_achievement}%</b>
                {m.uo_achievement != null && <> · Uo <b style={{ color: m.uo_achievement >= 90 ? 'var(--green)' : 'var(--red)' }}>{m.uo_achievement}%</b></>}
              </div>
            )}
            {m.notes && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{m.notes}</div>}

            {/* 격자 히트맵 (토글) */}
            {expanded[m.id] && hasGrid && (
              <div style={{ marginTop: 8, overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      <th style={s.th}></th>
                      {xLabels.map((l, i) => <th key={i} style={s.th}>{l}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: rows }).map((_, rIdx) => {
                      const ri = rows - 1 - rIdx;
                      return (
                        <tr key={ri}>
                          <th style={s.yTh}>{yLabels[ri]}</th>
                          {Array.from({ length: cols }).map((_, ci) => {
                            const val = grid[ri]?.[ci];
                            const { bg, light } = val != null ? lxToColor(val, gridMin, gridMax) : { bg: 'var(--bg)', light: true };
                            return (
                              <td key={ci} style={{ ...s.cell, background: bg, color: light ? '#0f172a' : '#fff' }}>
                                {val != null ? Math.round(val) : '—'}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ────────── 순차 입력 모달 ────────── */
function SequentialModal({ design, measured, xLabels, yLabels, gmin, gmax, onCell, onClose }) {
  const rows = design.length;
  const cols = design[0]?.length || 0;
  const cells = useMemo(() => {
    const out = [];
    for (let r = rows - 1; r >= 0; r--) {
      for (let c = 0; c < cols; c++) {
        if (design[r][c] != null) out.push({ r, c });
      }
    }
    return out;
  }, [design, rows, cols]);
  const [cursor, setCursor] = useState(() => {
    const firstEmpty = cells.findIndex(({ r, c }) => measured[r]?.[c] == null);
    return firstEmpty >= 0 ? firstEmpty : 0;
  });
  const [val, setVal] = useState(() => {
    const { r, c } = cells[0] || {};
    return measured[r]?.[c] ?? '';
  });
  const inputRef = useRef();

  useEffect(() => {
    const { r, c } = cells[cursor] || {};
    setVal(measured[r]?.[c] ?? '');
    setTimeout(() => inputRef.current?.focus(), 10);
  }, [cursor]);

  if (cells.length === 0) return null;
  const { r: ri, c: ci } = cells[cursor];
  const total = cells.length;
  const filled = cells.filter(({ r, c }) => measured[r]?.[c] != null).length;

  const commit = () => {
    const num = val === '' ? null : parseFloat(val);
    onCell(ri, ci, num);
  };

  const next = () => {
    commit();
    if (cursor < total - 1) setCursor(cursor + 1);
  };
  const prev = () => {
    commit();
    if (cursor > 0) setCursor(cursor - 1);
  };

  return (
    <div style={s.modalOverlay} onClick={onClose}>
      <div style={s.modal} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' }}>
            순차 입력 {cursor + 1} / {total}
          </div>
          <button onClick={onClose} style={{ ...s.btnSm, color: 'var(--text-muted)' }}>닫기</button>
        </div>
        <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, marginBottom: 12, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${filled / total * 100}%`,
            background: 'var(--accent)', transition: 'width .2s',
          }} />
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
          행 {rows - ri} · 열 {ci + 1} &nbsp;·&nbsp; Y={yLabels[ri]}, X={xLabels[ci]}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <div style={{ flex: 1, padding: 10, borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>설계값</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>
              {design[ri]?.[ci] ?? '-'}
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>실측값 (lx)</div>
            <input ref={inputRef} type="number" inputMode="numeric" value={val}
              onChange={e => setVal(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') next(); }}
              style={{ ...s.inp, fontSize: 20, fontWeight: 700, textAlign: 'center', padding: 10 }} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={prev} disabled={cursor === 0} style={s.btn}>이전</button>
          <button onClick={next} disabled={cursor >= total - 1}
            style={{ ...s.btn, background: 'var(--accent)', color: '#fff', flex: 2 }}>
            다음 →
          </button>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 10, textAlign: 'center' }}>
          Enter = 다음 칸으로 이동
        </div>
      </div>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  infoBar: { display: 'flex', gap: 6, padding: '6px 16px', overflowX: 'auto', WebkitOverflowScrolling: 'touch' },
  chip: { display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '4px 10px', borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)', flexShrink: 0, lineHeight: 1.2 },
  ksBar: { padding: '4px 16px 8px', display: 'flex', gap: 6, flexWrap: 'wrap', borderBottom: '1px solid var(--border)' },
  pill: { fontSize: 11, padding: '2px 8px', borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text-bright)' },
  tabs: { display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 5 },
  tab: { flex: 1, padding: '10px 4px', border: 'none', background: 'transparent', color: 'var(--text-muted)', fontSize: 12, fontWeight: 600, cursor: 'pointer', borderBottom: '2px solid transparent' },
  tabActive: { color: 'var(--accent)', borderBottom: '2px solid var(--accent)' },
  statBar: { display: 'flex', padding: '8px 16px', borderBottom: '1px solid var(--border)', overflowX: 'auto' },
  statItem: { flex: 1, minWidth: 50, textAlign: 'center' },
  table: { borderCollapse: 'separate', borderSpacing: 2 },
  th: { fontSize: 9, fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'monospace', padding: 2, minWidth: 38 },
  yTh: { fontSize: 9, fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'monospace', paddingRight: 6, textAlign: 'right', minWidth: 28, position: 'sticky', left: 0, background: 'var(--bg)', zIndex: 2 },
  td: { padding: 0 },
  cell: { width: 38, height: 38, borderRadius: 4, fontSize: 10, fontFamily: 'monospace', fontWeight: 600, textAlign: 'center' },
  cellInput: { width: 42, height: 42, borderRadius: 4, textAlign: 'center', fontFamily: 'monospace', fontSize: 11, fontWeight: 700, outline: 'none', padding: 0, MozAppearance: 'textfield' },
  btn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center', background: 'var(--surface)', color: 'var(--text-muted)' },
  btnSm: { background: 'none', border: 'none', fontSize: 11, cursor: 'pointer', padding: '2px 6px' },
  fl: { fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 },
  inp: { width: '100%', padding: '7px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 12 },
  histCard: { padding: 10, borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--border)' },
  modalOverlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 },
  modal: { width: '100%', maxWidth: 400, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 },
};
