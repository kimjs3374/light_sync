import ListPage from '../components/ListPage';

function Badge({ text, color = 'gray' }) {
  if (!text) return null;
  return <span className={`badge badge-${color}`}>{text}</span>;
}

function Indicator({ color = 'var(--border)' }) {
  return <div className="indicator" style={{ background: color }} />;
}

const sColor = { pending: 'orange', partial: 'blue', done: 'green', overdue: 'red', direct: 'purple' };

export default function IncomingOverview() {
  return (
    <ListPage
      icon="#"
      title="발주/입고현황"
      endpoint="/incoming-overview"
      dataKey="items"
      stats={(d) => {
        const s = d.stats || {};
        return [
          { label: '미입고', value: s.pending ?? 0, color: 'orange' },
          { label: '지연', value: s.overdue ?? 0, color: 'red' },
          { label: '7일내', value: s.this_week ?? 0, color: 'accent' },
          { label: '오늘입고', value: s.today_in ?? 0, color: 'green' },
        ];
      }}
      filters={[{
        key: 'status',
        options: [
          { value: '', label: '전체' },
          { value: 'pending', label: '미입고' },
          { value: 'partial', label: '부분입고' },
          { value: 'overdue', label: '지연' },
          { value: 'done', label: '완료' },
          { value: 'direct', label: '직접입고' },
        ],
      }]}
      /* 클릭 시 이동 없음 — 리스트 조회 전용 */
      renderItem={(it) => (
        <>
          <Indicator color={`var(--${sColor[it.status] || 'gray'})`} />
          <div className="msg-body">
            <div className="msg-top">
              <span className="msg-id" style={{ fontFamily: 'monospace' }}>
                {it.status === 'direct' ? it.rcv_no : it.po_no}
              </span>
              <span className="msg-date">
                {it.status === 'direct' ? it.rcv_date : (it.delivery_date || '-')}
              </span>
              <Badge text={it.status_label} color={sColor[it.status] || 'gray'} />
            </div>
            <div className="msg-title">
              {it.item_name}{it.item_spec ? ` · ${it.item_spec}` : ''}
            </div>
            <div className="msg-meta">
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{it.vendor_name}</span>
              {it.site_name && (
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>· {it.site_name}</span>
              )}
              <span className="money">
                {it.status === 'direct'
                  ? `${Math.round(it.received_qty)}${it.unit ? ` ${it.unit}` : ''}`
                  : `${Math.round(it.received_qty)}/${Math.round(it.quantity)}${it.unit ? ` ${it.unit}` : ''}`}
              </span>
              {it.remain > 0 && (
                <Badge
                  text={`잔 ${Math.round(it.remain)}`}
                  color={it.status === 'overdue' ? 'red' : 'orange'}
                />
              )}
            </div>
          </div>
        </>
      )}
    />
  );
}
