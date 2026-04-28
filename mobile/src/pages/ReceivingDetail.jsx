import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function ReceivingDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    api.get('/receivings').then((d) => {
      const rcv = (d.receivings || []).find(r => r.id === Number(id));
      setData(rcv || null);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  const confirmReceiving = async () => {
    if (confirming) return;
    if (!confirm('검수완료 처리하시겠습니까?')) return;
    setConfirming(true);
    try {
      await api.post(`/receivings/${id}/confirm`, {});
      setData(prev => prev ? { ...prev, status: '검수완료' } : prev);
    } catch (e) { alert(e.message); }
    setConfirming(false);
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">입고 정보를 찾을 수 없습니다</div>;

  const isDone = data.status === '검수완료';

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>{data.rcv_no}</h1>
        <span className={`badge badge-${isDone ? 'green' : 'orange'}`}>{data.status}</span>
      </div>

      {/* 검수 버튼 */}
      {!isDone && (
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <button onClick={confirmReceiving} disabled={confirming} style={s.confirmBtn}>
            {confirming ? '처리중...' : '검수완료 처리'}
          </button>
        </div>
      )}

      <div style={{ padding: '12px 16px' }}>
        <Row label="입고번호" value={data.rcv_no} accent />
        <Row label="입고일" value={data.rcv_date} />
        <Row label="거래처" value={data.vendor_name} />
        <Row label="품목수" value={`${data.item_count}건`} />
        {data.total_amount > 0 && <Row label="금액" value={Number(data.total_amount).toLocaleString() + '원'} />}
        {data.po_no && <Row label="발주번호" value={data.po_no} />}
        {data.note && <Row label="비고" value={data.note} />}
      </div>
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
  confirmBtn: { width: '100%', padding: 12, borderRadius: 6, border: 'none', background: 'var(--green)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500 },
};
