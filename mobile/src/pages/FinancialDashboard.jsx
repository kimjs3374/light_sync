import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

// ERP routes/financial.py financial_dashboard 100% 이식
// KPI + 월별매출/건수 + 수요기관 TOP10 + 년도별 계약대비매출

function fmtMoney(v) {
  if (v == null) return '0';
  try { return Number(v).toLocaleString(); } catch { return String(v); }
}
function fmtAmt(v) {
  if (v == null) return '0';
  const n = Number(v) || 0;
  if (n >= 1e8) return (n / 1e8).toFixed(1) + '억';
  if (n >= 1e4) return (n / 1e4).toFixed(0) + '만';
  return n.toLocaleString();
}

export default function FinancialDashboard() {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('trend'); // trend | detail

  useEffect(() => {
    api.get('/financial/dashboard')
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">데이터를 불러올 수 없습니다</div>;

  const kpi = data.kpi || {};
  const monthly = data.monthly || { labels: [], amounts: [], counts: [] };
  const topBuyers = data.top_buyers || { labels: [], amounts: [] };
  const yearlyData = data.yearly_data || [];
  const yearlyInvoice = data.yearly_invoice_chart || { labels: [], amounts: [], counts: [] };
  const yearlyChart = data.yearly_chart || { labels: [], contract: [], invoiced: [], carryover: [] };

  return (
    <div style={{ paddingBottom: 80 }}>
      {/* 헤더 */}
      <div className="channel-header">
        <span className="ch-icon">#</span>
        <h1>매출현황 대시보드</h1>
        <button onClick={() => nav('/billing')} style={s.linkBtn}>세금계산서</button>
      </div>

      {/* KPI */}
      <div style={s.kpiGrid}>
        <div style={s.kpiCard}>
          <div style={s.kpiLabel}>당월매출(공급가액)</div>
          <div style={{ ...s.kpiValue, color: 'var(--accent)' }}>
            {fmtAmt(kpi.monthly_supply)}<span style={s.kpiUnit}>원</span>
          </div>
        </div>
        <div style={s.kpiCard}>
          <div style={s.kpiLabel}>누적매출(공급가액)</div>
          <div style={{ ...s.kpiValue, color: 'var(--green)' }}>
            {fmtAmt(kpi.total_supply)}<span style={s.kpiUnit}>원</span>
          </div>
        </div>
        <div style={s.kpiCard}>
          <div style={s.kpiLabel}>세금계산서</div>
          <div style={{ ...s.kpiValue, color: 'var(--text-bright)' }}>
            {fmtMoney(kpi.total_cnt)}<span style={s.kpiUnit}>건</span>
          </div>
        </div>
      </div>

      {/* 탭 */}
      <div style={s.tabBar}>
        <button
          onClick={() => setTab('trend')}
          style={{ ...s.tabBtn, ...(tab === 'trend' ? s.tabActive : {}) }}
        >매출 추이</button>
        <button
          onClick={() => setTab('detail')}
          style={{ ...s.tabBtn, ...(tab === 'detail' ? s.tabActive : {}) }}
        >상세 분석</button>
      </div>

      {tab === 'trend' && (
        <div>
          {/* 월별 매출 (최근 12개월) */}
          <Section title="월별 매출 추이 (공급가액, 최근 12개월)">
            <BarChart labels={monthly.labels} values={monthly.amounts} color="#3b82f6" valueFmt={fmtAmt} unit="원" />
          </Section>

          {/* 월별 세금계산서 발행 건수 */}
          <Section title="월별 세금계산서 발행 건수">
            <BarChart labels={monthly.labels} values={monthly.counts} color="#8b5cf6" valueFmt={v => fmtMoney(v)} unit="건" />
          </Section>

          {/* 년도별 발행금액 */}
          <Section title="년도별 조달매출 추이 (부가세 포함)">
            <BarChart
              labels={yearlyInvoice.labels}
              values={yearlyInvoice.amounts}
              secondValues={yearlyInvoice.counts}
              secondLabel="건수"
              color="#3b82f6"
              valueFmt={fmtAmt}
              unit="원"
            />
          </Section>
        </div>
      )}

      {tab === 'detail' && (
        <div>
          {/* 년도별 계약 vs 매출 vs 이월 */}
          <Section title="년도별 계약금액 vs 매출 vs 이월">
            <MultiBarChart
              labels={yearlyChart.labels}
              series={[
                { label: '계약금액', data: yearlyChart.contract, color: '#94a3b8' },
                { label: '매출(발행)', data: yearlyChart.invoiced, color: '#3b82f6' },
                { label: '이월금액', data: yearlyChart.carryover, color: '#ef4444' },
              ]}
            />
          </Section>

          {/* 년도별 테이블 */}
          <div style={s.tableCard}>
            <div style={s.tableHdr}>년도별 계약 대비 매출 / 이월 현황</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={s.table}>
                <thead>
                  <tr>
                    <th style={s.th}>년도</th>
                    <th style={{ ...s.th, textAlign: 'right' }}>계약</th>
                    <th style={{ ...s.th, textAlign: 'right' }}>계약금액</th>
                    <th style={{ ...s.th, textAlign: 'right' }}>매출(발행)</th>
                    <th style={s.th}>매출율</th>
                    <th style={{ ...s.th, textAlign: 'right' }}>이월</th>
                    <th style={{ ...s.th, textAlign: 'right' }}>이월금액</th>
                  </tr>
                </thead>
                <tbody>
                  {yearlyData.map(d => {
                    const rateColor = d.sales_rate >= 80 ? 'var(--green)'
                      : d.sales_rate >= 50 ? 'var(--orange)'
                      : d.sales_rate > 0 ? 'var(--red)' : 'var(--text-muted)';
                    return (
                      <tr key={d.year}>
                        <td style={{ ...s.td, textAlign: 'center', fontWeight: 700 }}>{d.year}</td>
                        <td style={{ ...s.td, textAlign: 'right' }}>{d.contract_cnt}건</td>
                        <td style={{ ...s.td, textAlign: 'right' }}>{fmtAmt(d.contract_amt)}</td>
                        <td style={{ ...s.td, textAlign: 'right', color: 'var(--accent)', fontWeight: 700 }}>
                          {fmtAmt(d.invoiced_amt)}
                        </td>
                        <td style={{ ...s.td, textAlign: 'center' }}>
                          <span style={{ ...s.rateBadge, background: rateColor }}>{d.sales_rate}%</span>
                        </td>
                        <td style={{ ...s.td, textAlign: 'right', color: d.carryover_cnt > 0 ? 'var(--red)' : 'var(--text)', fontWeight: d.carryover_cnt > 0 ? 700 : 400 }}>
                          {d.carryover_cnt}건
                        </td>
                        <td style={{ ...s.td, textAlign: 'right', color: d.carryover_amt > 0 ? 'var(--red)' : 'var(--text)', fontWeight: d.carryover_amt > 0 ? 700 : 400 }}>
                          {fmtAmt(d.carryover_amt)}
                        </td>
                      </tr>
                    );
                  })}
                  {yearlyData.length === 0 && (
                    <tr><td colSpan={7} style={{ ...s.td, textAlign: 'center', color: 'var(--text-muted)' }}>데이터 없음</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 수요기관 TOP 10 */}
          <Section title="수요기관별 매출 TOP 10 (공급가액)">
            <HBarChart labels={topBuyers.labels} values={topBuyers.amounts} color="#10b981" valueFmt={fmtAmt} unit="원" />
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={s.section}>
      <div style={s.sectionTitle}>{title}</div>
      <div style={s.sectionBody}>{children}</div>
    </div>
  );
}

// 세로 막대 차트 (div 기반)
function BarChart({ labels, values, color, valueFmt, unit, secondValues, secondLabel }) {
  const max = Math.max(...values, 1);
  const secondMax = secondValues ? Math.max(...secondValues, 1) : null;
  if (!labels || labels.length === 0) {
    return <div style={s.emptyChart}>데이터 없음</div>;
  }
  return (
    <div>
      <div style={s.barRow}>
        {labels.map((label, i) => {
          const v = values[i] || 0;
          const h = (v / max) * 100;
          const sv = secondValues ? (secondValues[i] || 0) : null;
          const sh = secondMax ? (sv / secondMax) * 100 : null;
          return (
            <div key={i} style={s.barItem}>
              <div style={s.barValue}>{v > 0 ? valueFmt(v) : ''}</div>
              <div style={s.barTrack}>
                <div style={{ ...s.barFill, height: `${h}%`, background: color }} />
                {sh != null && sv > 0 && (
                  <div style={{ ...s.barDot, bottom: `${sh}%` }} title={`${secondLabel}: ${sv}`} />
                )}
              </div>
              <div style={s.barLabel}>{label}</div>
            </div>
          );
        })}
      </div>
      <div style={s.legend}>
        <span style={{ ...s.legendDot, background: color }} />
        <span>{unit}</span>
        {secondLabel && (
          <>
            <span style={{ ...s.legendDot, background: '#f59e0b', marginLeft: 10 }} />
            <span>{secondLabel}</span>
          </>
        )}
      </div>
    </div>
  );
}

// 다중 시리즈 세로 막대 (년도별 계약 vs 매출 vs 이월)
function MultiBarChart({ labels, series }) {
  const allVals = series.flatMap(s => s.data);
  const max = Math.max(...allVals, 1);
  if (!labels || labels.length === 0) {
    return <div style={s.emptyChart}>데이터 없음</div>;
  }
  return (
    <div>
      <div style={s.barRow}>
        {labels.map((label, i) => (
          <div key={i} style={{ ...s.barItem, flex: 'none', width: 60 }}>
            <div style={{ display: 'flex', gap: 2, height: 120, alignItems: 'flex-end', justifyContent: 'center' }}>
              {series.map((ser, j) => {
                const v = ser.data[i] || 0;
                const h = (v / max) * 100;
                return (
                  <div key={j} style={{ width: 12, height: '100%', display: 'flex', alignItems: 'flex-end' }}>
                    <div style={{ width: '100%', height: `${h}%`, background: ser.color, borderRadius: '2px 2px 0 0' }} />
                  </div>
                );
              })}
            </div>
            <div style={s.barLabel}>{label}</div>
          </div>
        ))}
      </div>
      <div style={s.legend}>
        {series.map((ser, j) => (
          <span key={j} style={{ marginRight: 10, display: 'inline-flex', alignItems: 'center' }}>
            <span style={{ ...s.legendDot, background: ser.color }} />
            {ser.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// 가로 막대 차트 (수요기관 TOP 10)
function HBarChart({ labels, values, color, valueFmt, unit }) {
  const max = Math.max(...values, 1);
  if (!labels || labels.length === 0) {
    return <div style={s.emptyChart}>데이터 없음</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {labels.map((label, i) => {
        const v = values[i] || 0;
        const w = (v / max) * 100;
        return (
          <div key={i} style={s.hbarRow}>
            <div style={s.hbarLabel} title={label}>{label}</div>
            <div style={s.hbarTrack}>
              <div style={{ ...s.hbarFill, width: `${w}%`, background: color }} />
              <span style={s.hbarValue}>{valueFmt(v)}{unit}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const s = {
  linkBtn: {
    background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)',
    padding: '4px 10px', borderRadius: 6, fontSize: 12,
  },
  kpiGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6,
    padding: '10px 16px 4px',
  },
  kpiCard: {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 8, padding: '10px 6px', textAlign: 'center',
  },
  kpiLabel: { fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 4, whiteSpace: 'nowrap' },
  kpiValue: { fontSize: 15, fontWeight: 800, lineHeight: 1.2 },
  kpiUnit: { fontSize: 10, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 2 },

  tabBar: {
    display: 'flex', borderBottom: '1px solid var(--border)',
    padding: '0 16px', marginTop: 6,
  },
  tabBtn: {
    background: 'none', color: 'var(--text-muted)', padding: '10px 14px',
    fontSize: 13, fontWeight: 600, borderBottom: '2px solid transparent',
  },
  tabActive: { color: 'var(--text-bright)', borderBottom: '2px solid var(--accent)' },

  section: {
    margin: '10px 12px',
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 8,
  },
  sectionTitle: {
    padding: '10px 14px 6px', fontSize: 12, fontWeight: 700,
    color: 'var(--text-bright)',
  },
  sectionBody: { padding: '4px 12px 14px' },

  barRow: {
    display: 'flex', gap: 2, alignItems: 'flex-end',
    height: 160, overflowX: 'auto', paddingBottom: 4,
  },
  barItem: {
    flex: '1 0 28px', minWidth: 28, display: 'flex',
    flexDirection: 'column', alignItems: 'center',
  },
  barValue: {
    fontSize: 9, color: 'var(--text-muted)', marginBottom: 2,
    height: 12, whiteSpace: 'nowrap',
  },
  barTrack: {
    width: '100%', height: 120, display: 'flex',
    alignItems: 'flex-end', justifyContent: 'center',
    position: 'relative',
  },
  barFill: {
    width: '70%', borderRadius: '3px 3px 0 0',
  },
  barDot: {
    position: 'absolute', left: '50%', transform: 'translateX(-50%) translateY(50%)',
    width: 6, height: 6, borderRadius: '50%', background: '#f59e0b',
  },
  barLabel: {
    fontSize: 10, color: 'var(--text-muted)', marginTop: 4,
    whiteSpace: 'nowrap',
  },

  legend: {
    marginTop: 6, fontSize: 10, color: 'var(--text-muted)',
    display: 'flex', alignItems: 'center', flexWrap: 'wrap',
  },
  legendDot: {
    display: 'inline-block', width: 8, height: 8, borderRadius: 2,
    marginRight: 4,
  },

  hbarRow: { display: 'flex', alignItems: 'center', gap: 6 },
  hbarLabel: {
    width: 100, fontSize: 11, color: 'var(--text)',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  hbarTrack: {
    flex: 1, height: 18, background: 'var(--bg)',
    borderRadius: 3, position: 'relative', overflow: 'hidden',
  },
  hbarFill: { height: '100%', borderRadius: 3 },
  hbarValue: {
    position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
    fontSize: 10, color: 'var(--text-bright)', fontWeight: 600,
  },

  emptyChart: {
    padding: '24px 0', textAlign: 'center',
    color: 'var(--text-muted)', fontSize: 12,
  },

  tableCard: {
    margin: '10px 12px',
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 8, overflow: 'hidden',
  },
  tableHdr: {
    background: 'var(--bg-active)', color: 'var(--text-bright)',
    padding: '8px 12px', fontSize: 12, fontWeight: 700,
  },
  table: {
    width: '100%', borderCollapse: 'collapse', fontSize: 11,
    whiteSpace: 'nowrap',
  },
  th: {
    padding: '6px 8px', background: 'var(--bg)',
    color: 'var(--text-muted)', fontWeight: 600, textAlign: 'left',
    borderBottom: '1px solid var(--border)',
  },
  td: {
    padding: '6px 8px', borderBottom: '1px solid var(--border)',
    color: 'var(--text)',
  },
  rateBadge: {
    display: 'inline-block', padding: '2px 6px', borderRadius: 3,
    color: '#fff', fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap',
  },
};
