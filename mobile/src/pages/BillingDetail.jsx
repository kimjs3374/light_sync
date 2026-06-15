import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

// 청구관리 상세 — ERP /billing 100% 매칭
// 데이터 소스: Contract (payment_status 기준) + 매칭된 TaxInvoice 목록 + G2B 계약금액
// 액션:
//   - 미청구  → "청구완료" (invoice_date 자동 today)
//   - 부분입금 → "잔금청구" (동일 엔드포인트)
//   - 청구완료 → "미청구로 복원"

function money(v) {
  if (v === null || v === undefined || v === '') return '-';
  const n = Number(v);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString() + '원';
}

function statusColor(s) {
  if (s === '미청구') return 'red';
  if (s === '청구완료') return 'blue';
  if (s === '부분입금') return 'orange';
  if (s === '입금완료') return 'green';
  return 'gray';
}

export default function BillingDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [invoiceDate, setInvoiceDate] = useState('');
  const [paymentDate, setPaymentDate] = useState('');
  const [dirty, setDirty] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/billing/${id}`).then((d) => {
      setData(d);
      setInvoiceDate(d.contract?.invoice_date || '');
      setPaymentDate(d.contract?.payment_date || '');
      setDirty(false);
    }).catch((e) => alert(e.message || '조회 실패'))
      .finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data || !data.contract) return <div className="page-loader">계약을 찾을 수 없습니다</div>;

  const c = data.contract;
  const p = data.project || {};
  const invoices = data.tax_invoices || [];
  const deliveries = data.deliveries || [];
  const history = data.history || [];
  const amount = data.amount || 0;

  const today = new Date().toISOString().slice(0, 10);
  const dday = c.delivery_due_date
    ? Math.floor((new Date(c.delivery_due_date) - new Date(today)) / 86400000)
    : null;

  const markBilled = async () => {
    const label = c.payment_status === '부분입금' ? '잔금청구' : '청구완료';
    if (!confirm(`"${c.contract_name}" ${label} 처리하시겠습니까?`)) return;
    setSaving(true);
    try {
      await api.post('/billing/mark-billed', { contract_id: c.id });
      load();
    } catch (e) { alert(e.message || '오류'); }
    setSaving(false);
  };

  const revertBilled = async () => {
    if (!confirm(`"${c.contract_name}" 미청구로 복원하시겠습니까?`)) return;
    setSaving(true);
    try {
      await api.post('/billing/revert-billed', { contract_id: c.id });
      load();
    } catch (e) { alert(e.message || '오류'); }
    setSaving(false);
  };

  const saveDates = async () => {
    setSaving(true);
    try {
      await api.post(`/billing/${c.id}/edit`, {
        invoice_date: invoiceDate || null,
        payment_date: paymentDate || null,
      });
      setDirty(false);
      load();
    } catch (e) { alert(e.message || '오류'); }
    setSaving(false);
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 13 }}>청구관리</h1>
        <span className={`badge badge-${statusColor(c.payment_status)}`}>{c.payment_status || '-'}</span>
      </div>

      {/* 요약 */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{c.g2b_contract_no || '-'}</div>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-bright)', marginBottom: 6 }}>{c.contract_name || '-'}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {data.is_invoiced
            ? <span className="badge badge-green">세금계산서 발행</span>
            : <span className="badge badge-gray">세금계산서 미발행</span>}
          {c.is_excluded && <span className="badge badge-gray">예외처리</span>}
        </div>
      </div>

      {/* 계약/현장 정보 */}
      <Section title="계약 정보">
        <Row label="현장명" value={p.name || p.temp_name} />
        <Row label="설계번호" value={p.project_no} />
        <Row label="계약일" value={c.contract_date} />
        <Row label="납품기일" value={c.delivery_due_date
          ? `${c.delivery_due_date}${dday !== null ? ` (D${dday >= 0 ? '-' : '+'}${Math.abs(dday)})` : ''}`
          : null} />
        <Row label="계약금액" value={money(amount)} />
        <Row label="변경차수" value={c.g2b_change_ord} />
      </Section>

      {/* 납품 현황 */}
      <Section title={`납품 현황 (${deliveries.length})`}>
        {deliveries.length === 0 ? (
          <div style={s.empty}>납품 정보 없음</div>
        ) : deliveries.map((d) => (
          <div key={d.id} style={s.listRow} onClick={() => nav(`/deliveries/${d.id}`)}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 600 }}>{d.delivery_no || '-'}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                납품일 {d.delivery_date || '-'}
              </div>
            </div>
            <span className={`badge badge-${d.delivery_status === 'done' ? 'green' : 'orange'}`}>
              {d.delivery_status === 'done' ? '납품완료' : d.delivery_status || '-'}
            </span>
          </div>
        ))}
      </Section>

      {/* 청구/입금 일자 편집 */}
      <Section title="청구/입금 일자">
        <div style={s.fieldWrap}>
          <div style={s.fieldLabel}>세금계산서 발행일</div>
          <input type="date" value={invoiceDate || ''}
            onChange={(e) => { setInvoiceDate(e.target.value); setDirty(true); }}
            style={s.input} />
        </div>
        <div style={s.fieldWrap}>
          <div style={s.fieldLabel}>입금확인일</div>
          <input type="date" value={paymentDate || ''}
            onChange={(e) => { setPaymentDate(e.target.value); setDirty(true); }}
            style={s.input} />
        </div>
        {dirty && (
          <button onClick={saveDates} disabled={saving} style={s.saveBtn}>
            {saving ? '저장중...' : '일자 저장'}
          </button>
        )}
      </Section>

      {/* 세금계산서 매칭 내역 */}
      <Section title={`세금계산서 매칭 (${invoices.length})`}>
        {invoices.length === 0 ? (
          <div style={s.empty}>매칭된 세금계산서 없음</div>
        ) : invoices.map((inv) => (
          <div key={inv.id} style={s.invoiceCard}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{inv.approval_no || '승인번호 없음'}</span>
              <span className={`badge badge-${inv.payment_status === '입금완료' ? 'green' : inv.payment_status === '부분입금' ? 'orange' : 'red'}`}>
                {inv.payment_status || '-'}
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 600 }}>
              {inv.buyer_name || '-'}
            </div>
            <div style={s.invoiceMeta}>
              <span>발행일 {inv.issue_date || '-'}</span>
              <span>{inv.invoice_type || '세금계산서'}</span>
              <span className="money">{money(inv.total_amount)}</span>
            </div>
            <div style={{ ...s.invoiceMeta, marginTop: 2 }}>
              <span>공급가액 {money(inv.supply_amount)}</span>
              <span>세액 {money(inv.tax_amount)}</span>
              {inv.paid_amount > 0 && <span>입금 {money(inv.paid_amount)}</span>}
            </div>
            {inv.match_status && (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>매칭: {inv.match_status}</div>
            )}
          </div>
        ))}
      </Section>

      {/* 액션 */}
      <Section title="상태 변경">
        {c.payment_status === '미청구' && (
          <button onClick={markBilled} disabled={saving} style={{ ...s.saveBtn, background: 'var(--accent)' }}>
            {saving ? '처리중...' : '청구완료 처리'}
          </button>
        )}
        {c.payment_status === '부분입금' && (
          <button onClick={markBilled} disabled={saving} style={{ ...s.saveBtn, background: '#f59e0b' }}>
            {saving ? '처리중...' : '잔금청구 처리'}
          </button>
        )}
        {c.payment_status === '청구완료' && (
          <button onClick={revertBilled} disabled={saving} style={{ ...s.saveBtn, background: 'var(--surface)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
            {saving ? '처리중...' : '미청구로 복원'}
          </button>
        )}
        {c.payment_status === '입금완료' && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', padding: 12 }}>
            입금완료 건은 매출/수금 화면에서 관리합니다.
          </div>
        )}
      </Section>

      {/* 히스토리 */}
      <Section title="히스토리">
        {history.length === 0 ? (
          <div style={s.empty}>기록 없음</div>
        ) : history.slice(0, 20).map((h, i) => (
          <div key={i} style={s.histItem}>
            <div style={s.histAvatar}>{(h.user_name || '?')[0]}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at?.slice(0, 16)}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{h.content}</div>
            </div>
          </div>
        ))}
      </Section>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={s.rowV}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer', padding: '4px 8px 4px 0' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right' },
  fieldWrap: { marginBottom: 10 },
  fieldLabel: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 },
  input: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  saveBtn: { width: '100%', padding: 12, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', marginTop: 8 },
  empty: { padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 },
  listRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer', gap: 8 },
  invoiceCard: { padding: '8px 10px', background: 'var(--surface)', borderRadius: 6, marginBottom: 6, border: '1px solid var(--border)' },
  invoiceMeta: { display: 'flex', gap: 10, fontSize: 11, color: 'var(--text-muted)', marginTop: 4, flexWrap: 'wrap' },
  histItem: { display: 'flex', gap: 10, padding: '6px 0' },
  histAvatar: { width: 26, height: 26, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 },
};
