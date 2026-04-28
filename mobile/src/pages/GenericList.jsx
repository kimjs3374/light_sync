import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const M = ({ children }) => <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{children}</span>;
function Badge({ text, color = 'gray' }) {
  if (!text) return null;
  return <span className={`badge badge-${color}`}>{text}</span>;
}
function money(v) { return v ? Number(v).toLocaleString() + '원' : ''; }

const CONFIGS = {
  '/design': {
    title: '설계관리', endpoint: '/projects/design', dataKey: 'projects',
    render: (p) => (<>
      <div className="msg-top"><span className="msg-id">{p.project_no}</span><Badge text={p.status} color={p.status === '계약' ? 'green' : 'blue'} /></div>
      <div className="msg-title">{p.name}</div>
      <div className="msg-meta"><M>{p.short_name}</M><M>{p.site_address}</M></div>
    </>),
  },
  '/processing-orders': {
    title: '가공발주', endpoint: '/processing-orders', dataKey: 'processing_orders',
    actions: (item, reload) => [
      { label: '작성중', action: () => api.post(`/processing-orders/${item.id}/status`, { status: '작성중' }).then(reload) },
      { label: '발주완료', action: () => api.post(`/processing-orders/${item.id}/status`, { status: '발주완료' }).then(reload) },
      { label: '입고완료', action: () => api.post(`/processing-orders/${item.id}/status`, { status: '입고완료' }).then(reload) },
    ],
    render: (p) => (<>
      <div className="msg-top"><span className="msg-id">{p.fo_no}</span><span className="msg-date">{p.fo_date}</span><Badge text={p.status} color={p.status === '작성중' ? 'orange' : p.status === '발주완료' ? 'blue' : 'green'} /></div>
      <div className="msg-title">{p.vendor_name}{p.project_name ? ` · ${p.project_name}` : ''}</div>
      <div className="msg-meta"><M>{p.processing_type}</M><M>품목 {p.item_count}</M>{p.total_amount > 0 && <span className="money">{money(p.total_amount)}</span>}</div>
    </>),
  },
  '/financial': {
    title: '매출/수금', endpoint: '/financial', dataKey: '_summary', isSummary: true,
    summaryFields: [
      { key: 'total_contracts', label: '전체 계약' },
      { key: 'total_amount', label: '총 계약금액', format: 'money' },
      { key: 'paid_count', label: '입금완료', color: 'green' },
      { key: 'unpaid_count', label: '미입금', color: 'orange' },
    ],
  },
  '/billing': {
    title: '청구관리', endpoint: '/billing', dataKey: 'invoices',
    actions: (item, reload) => [
      { label: '입금', action: () => api.post(`/billing/${item.id}/payment-status`, { status: '입금' }).then(reload) },
      { label: '미입금', action: () => api.post(`/billing/${item.id}/payment-status`, { status: '미입금' }).then(reload) },
    ],
    render: (p) => (<>
      <div className="msg-top"><span className="msg-id">{p.approval_no}</span><span className="msg-date">{p.issue_date}</span><Badge text={p.payment_status} color={p.payment_status === '입금' ? 'green' : 'orange'} /></div>
      <div className="msg-title">{p.item_name || p.buyer_name}</div>
      <div className="msg-meta"><M>{p.buyer_name}</M><M>{p.invoice_type}</M>{p.total_amount > 0 && <span className="money">{money(p.total_amount)}</span>}</div>
    </>),
  },
  '/certifications': {
    title: '인증서관리', endpoint: '/certifications', dataKey: 'certifications',
    actions: (item, reload) => [
      { label: '삭제', action: () => confirm('삭제하시겠습니까?') && api.post(`/certifications/${item.id}/delete`, {}).then(reload), danger: true },
    ],
    render: (p) => {
      const ec = p.expiry_status === '만료' ? 'red' : p.expiry_status === '만료임박' ? 'orange' : 'green';
      return (<>
        <div className="msg-top"><span className="msg-id">{p.cert_no}</span><Badge text={p.expiry_status} color={ec} /></div>
        <div className="msg-title">{p.cert_name}</div>
        <div className="msg-meta"><M>{p.cert_type}</M><M>{p.issuer}</M><M>만료 {p.expiry_date}</M>{p.product_model && <M>{p.product_model}</M>}</div>
      </>);
    },
  },
  '/bom': {
    title: 'BOM관리', endpoint: '/bom', dataKey: 'bom_list',
    render: (p) => (<>
      <div className="msg-top"><span className="msg-id">{p.product_code}</span><Badge text={p.is_active ? '활성' : '비활성'} color={p.is_active ? 'green' : 'gray'} /></div>
      <div className="msg-title">{p.product_name}</div>
      <div className="msg-meta"><M>{p.category}</M><M>v{p.version}</M><M>품목 {p.item_count}</M></div>
    </>),
  },
  '/photos': {
    title: '사진관리', endpoint: '/photos', dataKey: 'photos',
    render: (p) => (<>
      <div className="msg-top"><span className="msg-date">{p.created_at}</span><Badge text={p.photo_type} color="gray" /></div>
      <div className="msg-title">{p.project_name || p.file_name}</div>
      <div className="msg-meta"><M>{p.uploaded_by}</M></div>
    </>),
  },
  '/drawings': {
    title: '도면관리', endpoint: '/drawings', dataKey: 'drawings',
    render: (p) => (<>
      <div className="msg-top"><span className="msg-date">{p.created_at}</span><Badge text={p.drawing_type} color="gray" /><Badge text={p.convert_status} color={p.convert_status === 'done' ? 'green' : 'orange'} /></div>
      <div className="msg-title">{p.title}</div>
      <div className="msg-meta"><M>{p.project_name}</M><M>Rev.{p.revision_count}</M><M>{p.created_by}</M></div>
    </>),
  },
  '/receiving-photos': {
    title: '입고사진', endpoint: '/receiving-photos', dataKey: 'receiving_photos',
    render: (p) => (<>
      <div className="msg-top"><span className="msg-date">{p.created_at}</span>{p.po_no && <span className="msg-id">{p.po_no}</span>}</div>
      <div className="msg-title">{p.vendor_name || '입고사진'}</div>
      <div className="msg-meta"><M>{p.author_name}</M>{p.photos?.length > 0 && <M>{p.photos.length}장</M>}<M>{p.content}</M></div>
    </>),
  },
  '/business-trips': {
    title: '출장관리', endpoint: '/business-trips', dataKey: 'business_trips',
    actions: (item, reload) => [
      { label: '출장중', action: () => api.post(`/business-trips/${item.id}/status`, { status: '출장중' }).then(reload) },
      { label: '완료', action: () => api.post(`/business-trips/${item.id}/status`, { status: '완료' }).then(reload) },
    ],
    render: (p) => (<>
      <div className="msg-top"><span className="msg-date">{p.departure_date} ~ {p.return_date}</span><Badge text={p.status} color={p.status === '완료' ? 'green' : p.status === '출장중' ? 'blue' : 'orange'} /></div>
      <div className="msg-title">{p.title || p.destination}</div>
      <div className="msg-meta"><M>{p.destination}</M><M>{p.members_count}명</M>{p.member_names && <M>{p.member_names}</M>}{p.vehicle && <M>{p.vehicle}</M>}</div>
    </>),
  },
  '/tools': {
    title: '공구관리', endpoint: '/tools', dataKey: 'tools',
    actions: (item, reload) => [
      { label: '사용가능', action: () => api.post(`/tools/${item.id}/status`, { status: '사용가능' }).then(reload) },
      { label: '사용중', action: () => api.post(`/tools/${item.id}/status`, { status: '사용중' }).then(reload) },
      { label: '수리중', action: () => api.post(`/tools/${item.id}/status`, { status: '수리중' }).then(reload) },
    ],
    render: (p) => (<>
      <div className="msg-top"><Badge text={p.status} color={p.status === '사용가능' ? 'green' : p.status === '사용중' ? 'blue' : 'orange'} /><Badge text={p.category} color="gray" /></div>
      <div className="msg-title">{p.tool_name}</div>
      <div className="msg-meta"><M>{p.current_location}</M><M>{p.team}</M><M>보유 {p.total_qty} / 가용 {p.available_qty}</M></div>
    </>),
  },
  '/documents': {
    title: '서류관리', endpoint: '/documents', dataKey: 'documents',
    actions: (item, reload) => [
      ...(!item.commencement_generated ? [{ label: '착수계 생성', action: () => api.post(`/documents/${item.id}/generate-commencement`, {}).then(reload) }] : []),
      ...(!item.delivery_generated ? [{ label: '납품계 생성', action: () => api.post(`/documents/${item.id}/generate-delivery`, {}).then(reload) }] : []),
    ],
    render: (p) => (<>
      <div className="msg-top"><span className="msg-id">{p.procurement_req_no}</span><Badge text={p.status} color={p.status === '완료' ? 'green' : 'orange'} /></div>
      <div className="msg-title">{p.title || p.project_name}</div>
      <div className="msg-meta"><M>{p.demand_org}</M>{p.commencement_generated && <Badge text="착수계" color="green" />}{p.delivery_generated && <Badge text="납품계" color="green" />}</div>
    </>),
  },
};

export default function GenericList() {
  const location = window.location.pathname.replace('/m', '');
  const config = CONFIGS[location];

  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const fetchData = () => {
    if (!config) return;
    setLoading(true);
    const qs = search ? `?search=${encodeURIComponent(search)}` : '';
    api.get(`${config.endpoint}${qs}`).then((d) => {
      if (config.isSummary) { setSummary(d); } else { setItems(d[config.dataKey] || []); }
    }).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(fetchData, [search, location]);

  if (!config) return <div className="page-loader">페이지를 찾을 수 없습니다</div>;

  if (config.isSummary && summary) {
    return (
      <div>
        <div className="channel-header"><span className="ch-icon">#</span><h1>{config.title}</h1></div>
        <div className="stat-bar" style={{ padding: '8px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          {(config.summaryFields || []).map((f) => {
            const raw = summary.financial?.[f.key] ?? summary[f.key];
            const display = f.format === 'money' ? (raw ? Number(raw).toLocaleString() + '원' : '0') : raw;
            return (
              <div key={f.key} className="stat-item">
                <div className="stat-num" style={{ color: f.color ? `var(--${f.color})` : 'var(--text-bright)', fontSize: f.format === 'money' ? 14 : 18 }}>{display}</div>
                <div className="stat-label">{f.label}</div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="channel-header"><span className="ch-icon">#</span><h1>{config.title}</h1><span className="ch-count">{items.length}</span></div>
      <div className="search-bar"><input type="text" placeholder="검색..." value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div> : items.length === 0 ? <div className="page-empty">데이터 없음</div> : (
          items.map((item, i) => (
            <div key={item.id || i} className="msg-item" style={{ flexDirection: 'column', gap: 0 }}>
              <div style={{ display: 'flex', gap: 10 }}>
                <div className="indicator" style={{ background: 'var(--border)' }} />
                <div className="msg-body">{config.render(item)}</div>
              </div>
              {config.actions && (
                <div style={{ display: 'flex', gap: 4, marginTop: 6, marginLeft: 14, flexWrap: 'wrap' }}>
                  {config.actions(item, () => { setSearch(s => s); fetchData(); }).map((act, j) => (
                    <button key={j} onClick={(e) => { e.stopPropagation(); act.action().catch(err => alert(err.message)); }}
                      style={{
                        padding: '4px 10px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                        border: 'none', cursor: 'pointer',
                        background: act.danger ? 'rgba(242,63,67,0.15)' : 'var(--surface)',
                        color: act.danger ? 'var(--red)' : 'var(--text-muted)',
                      }}>
                      {act.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
