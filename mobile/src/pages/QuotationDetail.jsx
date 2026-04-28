import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function QuotationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/quotations/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">견적서를 찾을 수 없습니다</div>;

  const q = data.quotation || {};
  const items = data.items || [];
  const surcharges = data.surcharges || [];
  const money = (v) => v ? Number(v).toLocaleString() + '원' : '';

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 13 }}>{q.quote_no}</h1>
        <span className={`badge badge-${q.status === '발송' || q.status === '발송완료' ? 'green' : 'orange'}`}>{q.status}</span>
      </div>

      {/* 견적 정보 */}
      <Section title="견적 정보">
        <Row label="견적번호" value={q.quote_no} accent />
        <Row label="견적일" value={q.quote_date} />
        <Row label="건명" value={q.project_name} />
        <Row label="유효기간" value={q.validity_period} />
        <Row label="납기" value={q.delivery_date} />
        <Row label="결제조건" value={q.payment_method} />
      </Section>

      {/* 수급자 정보 */}
      <Section title="수급자">
        <Row label="업체명" value={q.customer_name} />
        <Row label="담당자" value={q.customer_contact} />
        <Row label="전화" value={q.customer_tel} />
        <Row label="이메일" value={q.customer_email} />
        <Row label="주소" value={q.customer_address} />
      </Section>

      {/* 품목 목록 */}
      <Section title={`품목 (${items.length})`}>
        {items.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>품목 없음</div>
        ) : (
          items.map((item, i) => (
            <div key={item.id} style={s.itemRow}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={s.itemName}>{item.item_name}</div>
                  {item.item_spec && <div style={s.itemSpec}>{item.item_spec}</div>}
                </div>
                <div style={s.itemAmount}>{money(item.amount)}</div>
              </div>
              <div style={s.itemMeta}>
                <span>{item.quantity} {item.unit}</span>
                <span>@{Number(item.unit_price).toLocaleString()}</span>
                {item.note && <span>{item.note}</span>}
              </div>
            </div>
          ))
        )}
      </Section>

      {/* 금액 합계 */}
      <Section title="금액">
        <Row label="공급가액" value={money(q.total_amount)} />
        {surcharges.map((sc, i) => (
          <Row key={i} label={`${sc.name} (${sc.rate}%)`} value={money(sc.amount)} />
        ))}
        <div style={s.totalRow}>
          <span style={s.totalLabel}>합계</span>
          <span style={s.totalValue}>{money(q.grand_total)}</span>
        </div>
        {q.tax_included && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>* 부가세 포함</div>}
      </Section>

      {/* 비고 */}
      {q.note && (
        <Section title="비고">
          <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{q.note}</div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={s.secTitle}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value, accent }) {
  if (!value) return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={{ ...s.rowV, ...(accent ? { color: 'var(--accent)', fontFamily: "'SF Mono','Consolas',monospace" } : {}) }}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right' },
  itemRow: { padding: '8px 0', borderBottom: '1px solid var(--border)' },
  itemName: { fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' },
  itemSpec: { fontSize: 11, color: 'var(--text-muted)', marginTop: 2 },
  itemAmount: { fontSize: 13, fontWeight: 600, color: 'var(--accent)', flexShrink: 0, fontFamily: "'SF Mono','Consolas',monospace" },
  itemMeta: { display: 'flex', gap: 10, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' },
  totalRow: { display: 'flex', justifyContent: 'space-between', padding: '8px 0', marginTop: 4 },
  totalLabel: { fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' },
  totalValue: { fontSize: 16, fontWeight: 700, color: 'var(--accent)', fontFamily: "'SF Mono','Consolas',monospace" },
};
