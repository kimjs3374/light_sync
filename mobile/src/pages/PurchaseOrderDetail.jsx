import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_COLORS = {
  '작성중': 'orange',
  '발송완료': 'blue',
  '입고대기': 'purple',
  '입고완료': 'green',
  '취소': 'gray',
};
const money = (v) => v ? Number(v).toLocaleString() : '0';

export default function PurchaseOrderDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/purchase-orders/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [id]);

  const changeStatus = async (s) => {
    if (busy) return;
    setBusy(true);
    try { await api.post(`/purchase-orders/${id}/status`, { status: s }); load(); }
    catch (e) { alert(e.message); }
    setBusy(false);
  };

  const sendEmail = async () => {
    const sentAt = data.purchase_order.email_sent_at;
    const msg = sentAt
      ? `[주의] 이미 ${sentAt}에 발송된 발주서입니다.\n거래처가 같은 발주서를 중복으로 받게 됩니다.\n\n그래도 ${data.purchase_order.vendor_name}에 다시 발송할까요?`
      : `거래처 ${data.purchase_order.vendor_name}에 이메일을 발송할까요?`;
    if (!confirm(msg)) return;
    setBusy(true);
    try {
      const r = await api.post(`/purchase-orders/${id}/send-email`, {});
      alert(`이메일 발송 완료: ${r.email_to}`);
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const deletePo = async () => {
    if (!confirm('발주서를 삭제하시겠습니까?')) return;
    try {
      await api.post(`/purchase-orders/${id}/delete`, {});
      nav('/purchase-orders');
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">발주서를 찾을 수 없습니다</div>;

  const po = data.purchase_order;
  const items = data.items || [];
  const statusChoices = data.status_choices || ['작성중', '발송완료', '입고대기', '입고완료', '취소'];
  const token = localStorage.getItem('token');
  const pdfUrl = `/api/app/purchase-orders/${id}/pdf?token=${encodeURIComponent(token)}`;
  const isDraft = po.status === '작성중';

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1 style={{ fontSize: 14, fontFamily: 'monospace' }}>{po.po_no}</h1>
        <span className={`badge badge-${STATUS_COLORS[po.status] || 'gray'}`}>{po.status}</span>
      </div>

      {/* 상태 변경 */}
      <Section title="발주 상태">
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {statusChoices.map((s) => (
            <button key={s} onClick={() => changeStatus(s)} disabled={busy}
              style={{
                flex: '1 1 auto', minWidth: 60, padding: '7px 10px', borderRadius: 4,
                fontSize: 11, fontWeight: 600, cursor: 'pointer', border: 'none',
                background: po.status === s ? `var(--${STATUS_COLORS[s] || 'gray'})` : 'var(--surface)',
                color: po.status === s ? '#fff' : 'var(--text-muted)',
              }}>
              {s}
            </button>
          ))}
        </div>
      </Section>

      {/* 액션 버튼 */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <a href={pdfUrl} target="_blank" rel="noreferrer" style={btnStyle('var(--accent)', '#fff')}>📄 PDF</a>
        {po.vendor_email && (
          <button onClick={sendEmail} disabled={busy} style={btnStyle('var(--orange)', '#fff')}>
            {busy ? '전송중...' : (po.email_sent_at ? '📧 이메일 재발송' : '📧 이메일 발송')}
          </button>
        )}
        {isDraft && (
          <button onClick={() => nav(`/purchase-orders/${id}/edit`)} style={btnStyle('var(--surface)', 'var(--text-bright)')}>✏️ 수정</button>
        )}
        {isDraft && (
          <button onClick={deletePo} style={btnStyle('rgba(242,63,67,0.15)', 'var(--red)')}>🗑 삭제</button>
        )}
      </div>

      {/* 발주 정보 */}
      <Section title="발주 정보">
        <Row label="발주번호" value={po.po_no} mono />
        <Row label="발주일" value={po.po_date} />
        <Row label="담당자" value={po.assignee_name} />
        <Row label="현장" value={po.project_name} />
        {po.contract_name && <Row label="계약" value={po.contract_name} />}
        {po.email_sent_at && <Row label="메일발송" value={`${po.email_to} (${po.email_sent_at})`} />}
        {po.note && <Row label="비고" value={po.note} />}
      </Section>

      {/* 거래처 정보 */}
      <Section title="거래처 정보">
        <Row label="거래처명" value={po.vendor_name} />
        <Row label="대표자" value={po.vendor_ceo} />
        <Row label="사업자번호" value={po.vendor_business_no} mono />
        <Row label="전화" value={po.vendor_tel} />
        <Row label="이메일" value={po.vendor_email} />
      </Section>

      {/* 품목 테이블 */}
      <Section title={`품목 (${items.length})`}>
        {items.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>등록된 품목이 없습니다</div>
        ) : items.map((it) => (
          <div key={it.id} style={{ padding: '8px 0', borderTop: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{it.item_name}</div>
                {it.item_spec && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{it.item_spec}</div>}
                {it.item_code && <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: 2 }}>{it.item_code}</div>}
                {it.note && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>📝 {it.note}</div>}
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>{money(it.amount)}원</div>
                {it.in_confirmed && <span className="badge badge-green" style={{ fontSize: 9, marginTop: 2 }}>입고확인</span>}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
              <span>{it.quantity} {it.unit}</span>
              <span>@{Number(it.unit_price).toLocaleString()}</span>
              {it.delivery_date && <span>📅 {it.delivery_date}</span>}
              {it.expected_in_date && <span>입고예정 {it.expected_in_date}</span>}
            </div>
          </div>
        ))}
      </Section>

      {/* 금액 */}
      <Section title="💰 금액">
        <AmountRow label="공급가액" value={money(po.total_amount)} />
        <AmountRow label="부가세 10%" value={money(po.tax_amount)} />
        <AmountRow label="합계" value={money(po.grand_total)} total />
      </Section>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}
function Row({ label, value, mono }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', gap: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)', fontFamily: mono ? 'monospace' : undefined, textAlign: 'right', maxWidth: '65%', wordBreak: 'break-all' }}>{value}</span>
    </div>
  );
}
function AmountRow({ label, value, total }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderTop: total ? '2px solid var(--text-bright)' : '1px solid var(--border)', marginTop: total ? 4 : 0 }}>
      <span style={{ fontSize: total ? 13 : 12, color: 'var(--text-muted)', fontWeight: total ? 700 : 400 }}>{label}</span>
      <span style={{ fontSize: total ? 15 : 12, color: total ? 'var(--accent)' : 'var(--text-bright)', fontFamily: 'monospace', fontWeight: total ? 700 : 500 }}>
        {value}원
      </span>
    </div>
  );
}
const btnStyle = (bg, color) => ({
  padding: '7px 12px', borderRadius: 4, fontSize: 12, fontWeight: 600,
  border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
  background: bg, color, textDecoration: 'none', display: 'inline-flex', alignItems: 'center',
});
