import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const PAYMENT_STATUSES = [
  { value: '미청구', color: 'orange' },
  { value: '청구완료', color: 'blue' },
  { value: '부분입금', color: 'purple' },
  { value: '입금완료', color: 'green' },
];

const ADMIN_STATUSES = ['자재확인중', '자재입고완료', '발주완료', '입고완료'];
const PROD_STATUSES = ['자재대기중', '자재입고완료', '생산진행중', '생산완료', '출고완료'];
const SALES_STATUSES = ['계약확인', '상세협의중', '협의완료', '생산의뢰'];

export default function ContractDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState('');
  const [posting, setPosting] = useState(false);
  const [changing, setChanging] = useState(false);

  const load = () => {
    api.get(`/contracts/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const changePayment = async (status) => {
    if (changing) return;
    setChanging(true);
    try {
      await api.post(`/contracts/${id}/payment-status`, { status });
      load();
    } catch (e) { alert(e.message); }
    setChanging(false);
  };

  const changeItemStatus = async (itemId, field, status) => {
    try {
      await api.post(`/contract-items/${itemId}/status`, { field, status });
      load();
    } catch (e) { alert(e.message); }
  };

  const handleComment = async () => {
    if (!comment.trim() || !data?.contract?.project_id) return;
    setPosting(true);
    try {
      await api.post(`/projects/${data.contract.project_id}/comment`, { content: comment.trim() });
      setComment('');
      load();
    } catch {}
    setPosting(false);
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">계약을 찾을 수 없습니다</div>;

  const c = data.contract || {};
  const items = data.items || [];
  const history = data.history || [];

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 14 }}>{c.contract_name}</h1>
      </div>

      {/* 결제상태 변경 */}
      <Section title="결제 상태">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {PAYMENT_STATUSES.map((ps) => (
            <button key={ps.value} onClick={() => changePayment(ps.value)} disabled={changing}
              style={{ ...s.statusBtn, background: c.payment_status === ps.value ? `var(--${ps.color})` : 'var(--surface)', color: c.payment_status === ps.value ? '#fff' : 'var(--text-muted)' }}>
              {ps.value}
            </button>
          ))}
        </div>
      </Section>

      {/* 계약 정보 */}
      <Section title="계약 정보">
        <Row label="계약번호" value={c.contract_no} accent />
        <Row label="계약일" value={c.contract_date} />
        <Row label="납품기한" value={c.delivery_due_date} />
        <Row label="발주기관" value={c.ordering_org} />
        <Row label="계약금액" value={c.contract_amount ? Number(c.contract_amount).toLocaleString() + '원' : ''} />
      </Section>

      {/* 품목 + 상태 변경 */}
      {items.length > 0 && (
        <Section title={`품목 (${items.length})`}>
          {items.map((ci) => (
            <div key={ci.id} style={s.itemCard}>
              <div style={s.itemName}>{ci.model_name || ci.category}</div>
              <div style={s.itemQty}>수량 {ci.quantity}</div>

              <StatusRow label="관리" current={ci.status_admin} options={ADMIN_STATUSES}
                onChange={(v) => changeItemStatus(ci.id, 'status_admin', v)} />
              <StatusRow label="생산" current={ci.status_prod} options={PROD_STATUSES}
                onChange={(v) => changeItemStatus(ci.id, 'status_prod', v)} />
              <StatusRow label="영업" current={ci.status_sales} options={SALES_STATUSES}
                onChange={(v) => changeItemStatus(ci.id, 'status_sales', v)} />
            </div>
          ))}
        </Section>
      )}

      {/* 히스토리 */}
      <Section title="히스토리">
        {history.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>기록 없음</div>
        ) : (
          history.slice(0, 30).map((h, i) => (
            <div key={i} style={s.histItem}>
              <div style={s.histAvatar}>{(h.user_name || '?')[0]}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at?.slice(0, 16)}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5 }}>{h.content}</div>
              </div>
            </div>
          ))
        )}
      </Section>

      {/* 코멘트 */}
      <div style={s.commentBar}>
        <input type="text" placeholder="코멘트 입력..." value={comment}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleComment()}
          style={s.commentInput} />
        <button onClick={handleComment} disabled={posting} style={s.commentBtn}>전송</button>
      </div>
    </div>
  );
}

function StatusRow({ label, current, options, onChange }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {options.map((opt) => (
          <button key={opt} onClick={() => onChange(opt)}
            style={{
              padding: '3px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
              border: 'none', cursor: 'pointer',
              background: current === opt ? 'var(--accent)' : 'var(--bg)',
              color: current === opt ? '#fff' : 'var(--text-muted)',
            }}>
            {opt}
          </button>
        ))}
      </div>
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
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer', padding: '4px 8px 4px 0' },
  statusBtn: { flex: 1, padding: '8px 0', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center', minWidth: 60 },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500 },
  itemCard: { padding: '10px 0', borderBottom: '1px solid var(--border)' },
  itemName: { fontSize: 13, color: 'var(--text-bright)', fontWeight: 600 },
  itemQty: { fontSize: 11, color: 'var(--text-muted)', marginTop: 2 },
  histItem: { display: 'flex', gap: 10, padding: '6px 0' },
  histAvatar: { width: 26, height: 26, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 },
  commentBar: { position: 'fixed', bottom: 48, left: 0, right: 0, padding: '8px 12px', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)', display: 'flex', gap: 8 },
  commentInput: { flex: 1, padding: '8px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  commentBtn: { padding: '8px 16px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none' },
};
