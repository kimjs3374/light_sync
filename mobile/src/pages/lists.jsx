import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ListPage from '../components/ListPage';

/* ── 헬퍼 ── */
function Badge({ text, color = 'gray' }) {
  if (!text) return null;
  return <span className={`badge badge-${color}`}>{text}</span>;
}
function Indicator({ color = 'var(--border)' }) {
  return <div className="indicator" style={{ background: color }} />;
}
function dday(dateStr) {
  if (!dateStr) return null;
  const diff = Math.ceil((new Date(dateStr) - new Date()) / 86400000);
  if (diff < 0) return { text: `D+${Math.abs(diff)}`, color: 'red' };
  if (diff <= 7) return { text: `D-${diff}`, color: 'orange' };
  return null;
}
function iColor(dateStr) {
  const d = dday(dateStr);
  return d?.color === 'red' ? 'var(--red)' : d?.color === 'orange' ? 'var(--orange)' : 'var(--border)';
}
function money(v) { return v ? Number(v).toLocaleString() + '원' : ''; }
function payC(s) { return s === '입금완료' ? 'green' : s === '미청구' ? 'orange' : s === '부분입금' ? 'blue' : 'gray'; }
const M = ({ children }) => <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{children}</span>;

/* ═══ 계약관리 ═══ */
// API keys: contract_amount, contract_date, contract_name, contract_no, delivery_due_date, id, is_excluded, ordering_org, payment_status, project_id, project_name, region
export function Contracts() {
  const nav = useNavigate();
  return (
    <ListPage icon="#" title="계약관리" endpoint="/contracts" dataKey="contracts"
      stats={(d) => {
        const cs = d.contracts || [];
        return [
          { label: '전체', value: cs.length },
          { label: '지연', value: cs.filter(c => dday(c.delivery_due_date)?.color === 'red').length, color: 'red' },
          { label: '7일내', value: cs.filter(c => dday(c.delivery_due_date)?.color === 'orange').length, color: 'orange' },
        ];
      }}
      onItemClick={(c) => nav(`/contracts/${c.id}`)}
      renderItem={(c) => {
        const dd = dday(c.delivery_due_date);
        return (<>
          <Indicator color={iColor(c.delivery_due_date)} />
          <div className="msg-body">
            <div className="msg-top">
              <span className="msg-id">{c.contract_no}</span>
              <span className="msg-date">{c.contract_date}</span>
              {dd && <Badge text={dd.text} color={dd.color} />}
            </div>
            <div className="msg-title">{c.contract_name}</div>
            <div className="msg-meta">
              <M>{c.ordering_org}</M>
              <Badge text={c.payment_status} color={payC(c.payment_status)} />
              {c.contract_amount > 0 && <span className="money">{money(c.contract_amount)}</span>}
            </div>
          </div>
        </>);
      }}
    />
  );
}

/* ═══ 납품관리 ═══ */
// API keys: contact_name, contact_phone, contract_id, contract_name, created_at, delivered_total_qty, delivery_due_date, delivery_status, id, inspection_date, inspection_status, planned_total_qty, project_id, project_name
export function Deliveries() {
  const nav = useNavigate();
  const sMap = { waiting: '대기', in_progress: '진행', completed: '완료', done: '완료' };
  const sCol = { waiting: 'orange', in_progress: 'blue', completed: 'green', done: 'green' };
  return (
    <ListPage icon="#" title="납품관리" endpoint="/deliveries" dataKey="deliveries"
      stats={(d) => {
        const ds = d.deliveries || [];
        return [
          { label: '전체', value: ds.length },
          { label: '대기', value: ds.filter(x => x.delivery_status === 'waiting').length, color: 'orange' },
          { label: '진행', value: ds.filter(x => x.delivery_status === 'in_progress').length, color: 'accent' },
          { label: '완료', value: ds.filter(x => ['completed','done'].includes(x.delivery_status)).length, color: 'green' },
        ];
      }}
      onItemClick={(d) => nav(`/delivery-projects/${d.project_id}`)}
      renderItem={(d) => {
        const dd = dday(d.delivery_due_date);
        const pct = d.planned_total_qty > 0 ? Math.round((d.delivered_total_qty / d.planned_total_qty) * 100) : 0;
        return (<>
          <Indicator color={iColor(d.delivery_due_date)} />
          <div className="msg-body">
            <div className="msg-top">
              <span className="msg-date">{d.delivery_due_date}</span>
              {dd && <Badge text={dd.text} color={dd.color} />}
              <Badge text={sMap[d.delivery_status] || d.delivery_status} color={sCol[d.delivery_status] || 'gray'} />
            </div>
            <div className="msg-title">{d.contract_name || d.project_name}</div>
            <div className="msg-meta">
              <M>{d.delivered_total_qty}/{d.planned_total_qty}</M>
              <Badge text={d.inspection_status} color={d.inspection_status === '검수완료' ? 'green' : 'gray'} />
            </div>
            {d.planned_total_qty > 0 && <div className="progress-bar"><div className="fill" style={{ width: `${pct}%` }} /></div>}
          </div>
        </>);
      }}
    />
  );
}

/* ═══ 협의관리(영업) ═══ */
// API keys: category, contract_id, contract_name, delivery_due_date, id, model_name, project_id, project_name, quantity, status_admin, status_prod, status_sales
export function Sales() {
  const nav = useNavigate();
  return (
    <ListPage icon="#" title="협의관리" endpoint="/sales" dataKey="sales"
      stats={(d) => {
        const ss = d.sales || [];
        return [
          { label: '전체', value: ss.length },
          { label: '지연', value: ss.filter(s => dday(s.delivery_due_date)?.color === 'red').length, color: 'red' },
          { label: '7일내', value: ss.filter(s => dday(s.delivery_due_date)?.color === 'orange').length, color: 'orange' },
        ];
      }}
      onItemClick={(p) => nav(`/sales/${p.id}`)}
      renderItem={(p) => {
        const dd = dday(p.delivery_due_date);
        const sc = p.status_sales === '협의완료' ? 'green' : p.status_sales === '상세협의중' ? 'blue' : 'orange';
        return (<>
          <Indicator color={iColor(p.delivery_due_date)} />
          <div className="msg-body">
            <div className="msg-top">
              <span className="msg-date">{p.delivery_due_date}</span>
              {dd && <Badge text={dd.text} color={dd.color} />}
              <Badge text={p.category} color="purple" />
              <Badge text={p.status_sales} color={sc} />
            </div>
            <div className="msg-title">{p.contract_name || p.project_name}</div>
            <div className="msg-meta">
              <M>{p.model_name}</M>
              <M>×{p.quantity}</M>
              {p.status_admin && <Badge text={p.status_admin} color="gray" />}
            </div>
          </div>
        </>);
      }}
    />
  );
}

/* ═══ 발주관리 ═══ */
// API keys: email_sent_at, id, item_count, note, po_date, po_no, project_name, status, tax_amount, total_amount, vendor_name
export function PurchaseOrders() {
  const nav = useNavigate();
  const sColor = { '작성중': 'orange', '발송완료': 'blue', '입고대기': 'purple', '입고완료': 'green', '취소': 'gray' };
  return (
    <ListPage icon="#" title="발주관리" endpoint="/purchase-orders" dataKey="purchase_orders"
      onItemClick={(po) => nav(`/purchase-orders/${po.id}`)}
      onCreate={() => nav('/purchase-orders/create')}
      stats={(d) => {
        const pos = d.purchase_orders || [];
        return [
          { label: '전체', value: pos.length },
          { label: '작성중', value: pos.filter(p => p.status === '작성중').length, color: 'orange' },
          { label: '발송', value: pos.filter(p => p.status === '발송완료').length, color: 'accent' },
          { label: '입고', value: pos.filter(p => ['입고대기', '입고완료'].includes(p.status)).length, color: 'green' },
        ];
      }}
      renderItem={(po) => (<>
        <Indicator color={`var(--${sColor[po.status] || 'gray'})`} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id" style={{ fontFamily: 'monospace' }}>{po.po_no}</span>
            <span className="msg-date">{po.po_date}</span>
            <Badge text={po.status} color={sColor[po.status] || 'gray'} />
          </div>
          <div className="msg-title">{po.vendor_name}{po.project_name ? ` · ${po.project_name}` : ''}</div>
          <div className="msg-meta">
            <M>품목 {po.item_count}</M>
            {po.total_amount > 0 && <span className="money">{money(po.total_amount)}</span>}
            {po.email_sent_at && <Badge text="발송" color="green" />}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 입고관리 ═══ */
// API keys: created_at, id, item_count, note, po_no, rcv_date, rcv_no, status, total_amount, vendor_name
export function Receivings() {
  const nav = useNavigate();
  const sColor = { '검수대기': 'orange', '검수완료': 'green', '반품': 'red' };
  return (
    <ListPage icon="#" title="입고관리" endpoint="/receivings" dataKey="receivings"
      onItemClick={(r) => nav(`/receivings/${r.id}`)}
      onCreate={() => nav('/receivings/create')}
      stats={(d) => {
        const rs = d.receivings || [];
        return [
          { label: '전체', value: rs.length },
          { label: '검수대기', value: rs.filter(r => r.status === '검수대기' || !r.status).length, color: 'orange' },
          { label: '검수완료', value: rs.filter(r => r.status === '검수완료').length, color: 'green' },
          { label: '반품', value: rs.filter(r => r.status === '반품').length, color: 'red' },
        ];
      }}
      renderItem={(r) => (<>
        <Indicator color={`var(--${sColor[r.status] || 'gray'})`} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id" style={{ fontFamily: 'monospace' }}>{r.rcv_no}</span>
            <span className="msg-date">{r.rcv_date}</span>
            <Badge text={r.status || '검수대기'} color={sColor[r.status] || 'orange'} />
          </div>
          <div className="msg-title">{r.vendor_name}</div>
          <div className="msg-meta">
            <M>품목 {r.item_count}</M>
            {r.total_amount > 0 && <span className="money">{money(r.total_amount)}</span>}
            {r.po_no && <M>{r.po_no}</M>}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 견적관리 ═══ */
// API keys: created_at, customer_name, grand_total, id, project_name, quote_date, quote_no, status
export function Quotations() {
  const nav = useNavigate();
  return (
    <ListPage icon="#" title="견적관리" endpoint="/quotations" dataKey="quotations"
      onItemClick={(q) => nav(`/quotations/${q.id}`)}
      onCreate={() => nav('/quotations/create')}
      stats={(d) => {
        const qs = d.quotations || [];
        return [
          { label: '전체', value: qs.length },
          { label: '작성중', value: qs.filter(q => q.status === '작성중').length, color: 'orange' },
          { label: '발송', value: qs.filter(q => q.status === '발송' || q.status === '발송완료').length, color: 'green' },
        ];
      }}
      renderItem={(q) => (<>
        <Indicator color="var(--purple)" />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id">{q.quote_no}</span>
            <span className="msg-date">{q.quote_date}</span>
            <Badge text={q.status} color={q.status === '발송완료' ? 'green' : 'orange'} />
          </div>
          <div className="msg-title">{q.project_name || q.customer_name}</div>
          <div className="msg-meta">
            {q.customer_name && <M>{q.customer_name}</M>}
            {q.grand_total > 0 && <span className="money">{money(q.grand_total)}</span>}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 서류관리 ═══ */
// API keys: req_no, business_name, demand_org, supply_amount, delivery_due, req_date, item_count, status
export function Documents() {
  const nav = useNavigate();
  const statusColor = (s) => s === '완료' ? 'green' : s === '납품계 생성가능' ? 'blue' : s === '착수계 생성가능' ? 'orange' : 'gray';
  return (
    <ListPage icon="#" title="서류관리" endpoint="/documents" dataKey="documents"
      onItemClick={(d) => nav(`/documents/${encodeURIComponent(d.req_no)}`)}
      stats={(d) => {
        const s = d.stats || {};
        return [
          { label: '전체', value: s.total || 0 },
          { label: '미등록', value: s.no_contract || 0, color: 'gray' },
          { label: '착수계', value: s.commencement_ready || 0, color: 'orange' },
          { label: '납품계', value: s.delivery_ready || 0, color: 'accent' },
          { label: '완료', value: s.done || 0, color: 'green' },
        ];
      }}
      renderItem={(d) => (<>
        <Indicator color={`var(--${statusColor(d.status)})`} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id" style={{ fontFamily: 'monospace' }}>{d.req_no}</span>
            <span className="msg-date">{d.req_date}</span>
            <Badge text={d.status} color={statusColor(d.status)} />
          </div>
          <div className="msg-title">{d.business_name}</div>
          <div className="msg-meta">
            <M>{d.demand_org}</M>
            <M>품목 {d.item_count}</M>
            {d.supply_amount > 0 && <span className="money">{money(d.supply_amount)}</span>}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 자재관리 ═══ */
// API keys: contract_id, contract_name, expected_in_date, id, in_confirmed, is_outsourcing, item_category, item_model_name, material_name, order_date, order_status, outsourcing_status, project_id, project_name, quantity
export function Materials() {
  return (
    <ListPage icon="#" title="자재관리" endpoint="/materials" dataKey="materials"
      renderItem={(m) => (<>
        <Indicator color={m.in_confirmed ? 'var(--green)' : m.order_status === '발주완료' ? 'var(--accent)' : 'var(--border)'} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-date">{m.expected_in_date || m.order_date}</span>
            <Badge text={m.order_status} color={m.order_status === '발주완료' ? 'blue' : m.in_confirmed ? 'green' : 'gray'} />
            {m.is_outsourcing && <Badge text="외주" color="purple" />}
          </div>
          <div className="msg-title">{m.material_name || m.item_model_name}</div>
          <div className="msg-meta">
            <M>{m.project_name || m.contract_name}</M>
            <M>×{m.quantity}</M>
            {m.item_category && <Badge text={m.item_category} color="gray" />}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 재고현황 ═══ */
// API keys: available_qty, category, id, is_low_stock, item_code, item_name, item_spec, safety_stock, stock_qty, unit
export function Inventory() {
  return (
    <ListPage icon="#" title="재고현황" endpoint="/inventory" dataKey="inventory"
      renderItem={(item) => (<>
        <Indicator color={item.is_low_stock ? 'var(--red)' : 'var(--green)'} />
        <div className="msg-body">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="msg-title" style={{ flex: 1 }}>{item.item_name}</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: item.is_low_stock ? 'var(--red)' : 'var(--green)', flexShrink: 0 }}>
              {item.stock_qty}
            </span>
          </div>
          <div className="msg-meta">
            {item.item_code && <span className="msg-id">{item.item_code}</span>}
            {item.category && <M>{item.category}</M>}
            <M>{item.unit}</M>
            {item.safety_stock > 0 && <M>안전재고 {item.safety_stock}</M>}
            {item.is_low_stock && <Badge text="부족" color="red" />}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 품목관리 ═══ */
// API keys: category, id, is_active, item_code, item_name, item_spec, manufacturer, stock_qty, unit
export function Items() {
  return (
    <ListPage icon="#" title="품목관리" endpoint="/items" dataKey="items"
      renderItem={(item) => (<>
        <Indicator />
        <div className="msg-body">
          <div className="msg-top">
            {item.item_code && <span className="msg-id">{item.item_code}</span>}
            {item.category && <Badge text={item.category} color="gray" />}
          </div>
          <div className="msg-title">{item.item_name}</div>
          <div className="msg-meta">
            {item.manufacturer && <M>{item.manufacturer}</M>}
            <M>{item.unit}</M>
            <M>재고 {item.stock_qty || 0}</M>
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 거래처 ═══ */
// API keys: address, business, business_no, ceo_name, email, id, name, tel
export function Vendors() {
  const nav = useNavigate();
  return (
    <ListPage icon="#" title="거래처" endpoint="/vendors" dataKey="vendors"
      onItemClick={(v) => nav(`/vendors/${v.id}`)}
      onCreate={() => nav('/vendors/create')}
      stats={(d) => {
        const vs = d.vendors || [];
        const active = vs.filter(v => v.is_active !== false).length;
        return [
          { label: '전체', value: vs.length },
          { label: '사용', value: active, color: 'green' },
          { label: '미사용', value: vs.length - active, color: 'gray' },
        ];
      }}
      renderItem={(v) => (<>
        <Indicator color={v.is_active === false ? 'var(--border)' : 'var(--green)'} />
        <div className="msg-body">
          <div className="msg-top">
            {v.icube_tr_cd && <span className="msg-id" style={{ fontFamily: 'monospace' }}>{v.icube_tr_cd}</span>}
            {v.is_active === false && <Badge text="미사용" color="gray" />}
          </div>
          <div className="msg-title">{v.name}</div>
          <div className="msg-meta">
            {v.ceo_name && <M>대표 {v.ceo_name}</M>}
            {v.tel && <M>{v.tel}</M>}
            {v.business_no && <M>{v.business_no}</M>}
          </div>
          {v.note && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.note}</div>}
        </div>
      </>)}
    />
  );
}

/* ═══ AS관리 ═══ */
// API keys: assigned_to, case_no, completed_date, contract_name, customer_name, customer_phone, defect_type, id, is_chargeable, item_group, model_name, project_id, project_name, reported_by, reported_date, site_visit_date, status, symptom, warranty_id
export function Warranty() {
  const nav = useNavigate();
  return (
    <ListPage icon="#" title="AS관리" endpoint="/warranty-cases" dataKey="warranty_cases"
      stats={(d) => {
        const ws = d.warranty_cases || [];
        return [
          { label: '전체', value: ws.length },
          { label: '처리중', value: ws.filter(x => x.status !== '완료').length, color: 'orange' },
          { label: '완료', value: ws.filter(x => x.status === '완료').length, color: 'green' },
        ];
      }}
      onItemClick={(w) => nav(`/warranty/${w.id}`)}
      renderItem={(w) => (<>
        <Indicator color={w.status === '완료' ? 'var(--green)' : w.status === '접수' ? 'var(--orange)' : 'var(--accent)'} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id">{w.case_no}</span>
            <span className="msg-date">{w.reported_date}</span>
            <Badge text={w.status} color={w.status === '완료' ? 'green' : w.status === '접수' ? 'orange' : 'blue'} />
            {w.is_chargeable && <Badge text="유상" color="red" />}
          </div>
          <div className="msg-title">{w.contract_name || w.project_name}</div>
          <div className="msg-meta">
            <Badge text={w.defect_type} color="purple" />
            <M>{w.model_name}</M>
            {w.symptom && <M>{w.symptom}</M>}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 조달내역 ═══ */
// API keys: cntrct_div_nm, cntrct_dlvr_req_date, cntrct_dlvr_req_nm, cntrct_dlvr_req_no, dlvr_plce_nm, dlvr_tmlmt_date, dminstt_nm, dminstt_rgn_nm, dtil_prdct_clsfc_no_nm, id, prdct_amt, prdct_clsfc_no_nm, prdct_idnt_no_nm, prdct_qty, prdct_uprc
export function Procurements() {
  return (
    <ListPage icon="#" title="조달내역" endpoint="/procurements" dataKey="procurements"
      renderItem={(p) => {
        const dd = dday(p.dlvr_tmlmt_date);
        return (<>
          <Indicator color={iColor(p.dlvr_tmlmt_date)} />
          <div className="msg-body">
            <div className="msg-top">
              <span className="msg-id">{p.cntrct_dlvr_req_no}</span>
              <span className="msg-date">{p.cntrct_dlvr_req_date}</span>
              {dd && <Badge text={dd.text} color={dd.color} />}
            </div>
            <div className="msg-title">{p.cntrct_dlvr_req_nm}</div>
            <div className="msg-meta">
              <M>{p.dminstt_nm}</M>
              <Badge text={p.dtil_prdct_clsfc_no_nm} color="purple" />
              {p.prdct_amt > 0 && <span className="money">{money(p.prdct_amt)}</span>}
              <M>×{p.prdct_qty}</M>
            </div>
          </div>
        </>);
      }}
    />
  );
}

/* ═══ 청구관리 ═══ */
export function Billing() {
  const nav = useNavigate();
  const TABS = [
    { key: 'pending', label: '미청구', color: 'red' },
    { key: 'partial', label: '선금(잔금대기)', color: 'orange' },
    { key: 'billed', label: '청구완료', color: 'blue' },
    { key: 'all', label: '전체', color: 'gray' },
  ];
  const [tab, setTab] = useState('pending');
  return (
    <ListPage icon="#" title="청구관리" endpoint="/billing" dataKey="contracts"
      onItemClick={(r) => nav(`/billing/${r.id}`)}
      defaultParams={{ tab }}
      stats={(d) => {
        const s = d.stats || {};
        return [
          { label: '미청구', value: s['미청구'] || 0, color: 'red' },
          { label: '부분입금', value: s['부분입금'] || 0, color: 'orange' },
          { label: '청구완료', value: s['청구완료'] || 0, color: 'blue' },
        ];
      }}
      filters={[{
        key: 'tab',
        options: TABS.map(t => ({ value: t.key, label: t.label })),
      }]}
      renderItem={(r) => {
        const psColor = r.payment_status === '미청구' ? 'red'
          : r.payment_status === '청구완료' ? 'blue'
          : r.payment_status === '부분입금' ? 'orange' : 'gray';
        return (<>
          <Indicator color={`var(--${psColor})`} />
          <div className="msg-body">
            <div className="msg-top">
              <span className="msg-id">{r.g2b_contract_no || '-'}</span>
              <Badge text={r.is_invoiced ? '발행' : '미발행'} color={r.is_invoiced ? 'green' : 'gray'} />
              <Badge text={r.payment_status} color={psColor} />
            </div>
            <div className="msg-title">{r.contract_name}</div>
            <div className="msg-meta">
              <M>{r.project_name}</M>
              {r.delivery_due_date && <M>납품 {r.delivery_due_date}</M>}
              {r.amount > 0 && <span className="money">{money(r.amount)}</span>}
            </div>
          </div>
        </>);
      }}
    />
  );
}

/* ═══ 인증서관리 ═══ */
export function Certifications() {
  const nav = useNavigate();
  const expColor = (s) => s === 'expired' || s === 'critical' ? 'red'
    : s === 'warning' ? 'orange'
    : s === 'ok' ? 'green' : 'gray';
  const expBadge = (c) => {
    const d = c.days_until_expiry;
    if (d == null) return null;
    if (d < 0) return { text: `${Math.abs(d)}일 경과`, color: 'red' };
    if (d <= 7) return { text: `D-${d}`, color: 'red' };
    if (d <= 30) return { text: `D-${d}`, color: 'orange' };
    return { text: `D-${d}`, color: 'green' };
  };
  return (
    <ListPage icon="#" title="인증서관리" endpoint="/certifications" dataKey="certifications"
      onItemClick={(c) => nav(`/certifications/${c.id}`)}
      onCreate={() => nav('/certifications/create')}
      stats={(d) => {
        const cs = d.certifications || [];
        return [
          { label: '전체', value: cs.length },
          { label: '정상', value: cs.filter(c => c.expiry_status === 'ok').length, color: 'green' },
          { label: '30일내', value: cs.filter(c => c.expiry_status === 'warning').length, color: 'orange' },
          { label: '7일내', value: cs.filter(c => c.expiry_status === 'critical').length, color: 'red' },
          { label: '만료', value: cs.filter(c => c.expiry_status === 'expired').length, color: 'red' },
        ];
      }}
      renderItem={(c) => {
        const dd = expBadge(c);
        return (<>
          <Indicator color={`var(--${expColor(c.expiry_status)})`} />
          <div className="msg-body">
            <div className="msg-top">
              <Badge text={c.cert_type} color="gray" />
              {c.cert_no && <span className="msg-id">{c.cert_no}</span>}
              {dd && <Badge text={dd.text} color={dd.color} />}
              {c.has_file && <Badge text="파일" color="blue" />}
            </div>
            <div className="msg-title">{c.cert_name}</div>
            <div className="msg-meta">
              {c.issued_by && <M>{c.issued_by}</M>}
              {c.product_model && <M>{c.product_model}</M>}
              {c.expiry_date && <M>만료 {c.expiry_date}</M>}
            </div>
          </div>
        </>);
      }}
    />
  );
}

/* ═══ 조도검증 ═══ */
// API keys: id, project_name, customer, location, install_date, facility_type, status, area_count, measured_count, pass_count, fail_count, created_at
export function Illuminance() {
  const nav = useNavigate();
  const sColor = { design: 'orange', measured: 'blue', reported: 'green' };
  const sLabel = { design: '설계', measured: '실측', reported: '리포트' };
  return (
    <ListPage icon="#" title="조도검증" endpoint="/illuminance" dataKey="illuminance_projects"
      onItemClick={(p) => nav(`/illuminance/${p.id}`)}
      stats={(d) => {
        const ps = d.illuminance_projects || [];
        return [
          { label: '전체', value: ps.length },
          { label: '설계', value: ps.filter(p => p.status === 'design').length, color: 'orange' },
          { label: '실측', value: ps.filter(p => p.status === 'measured').length, color: 'accent' },
          { label: 'PASS', value: ps.reduce((s, p) => s + (p.pass_count || 0), 0), color: 'green' },
          { label: 'FAIL', value: ps.reduce((s, p) => s + (p.fail_count || 0), 0), color: 'red' },
        ];
      }}
      renderItem={(p) => (<>
        <Indicator color={`var(--${sColor[p.status] || 'gray'})`} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-date">{p.install_date || p.created_at?.slice(0, 10)}</span>
            <Badge text={sLabel[p.status] || p.status} color={sColor[p.status] || 'gray'} />
            {p.facility_type && <Badge text={p.facility_type} color="purple" />}
          </div>
          <div className="msg-title">{p.project_name}</div>
          <div className="msg-meta">
            <M>구역 {p.area_count}</M>
            <M>실측 {p.measured_count}/{p.area_count}</M>
            {p.pass_count > 0 && <Badge text={`PASS ${p.pass_count}`} color="green" />}
            {p.fail_count > 0 && <Badge text={`FAIL ${p.fail_count}`} color="red" />}
            {p.customer && <M>{p.customer}</M>}
          </div>
        </div>
      </>)}
    />
  );
}

/* ═══ 가공발주 ═══ */
export function ProcessingOrders() {
  const nav = useNavigate();
  const sColor = { '작성중': 'orange', '발주완료': 'blue', '가공중': 'purple', '입고완료': 'green', '취소': 'gray' };
  return (
    <ListPage icon="#" title="가공발주" endpoint="/processing-orders" dataKey="processing_orders"
      onItemClick={(fo) => nav(`/processing-orders/${fo.id}`)}
      onCreate={() => nav('/processing-orders/create')}
      stats={(d) => {
        const fs = d.processing_orders || [];
        return [
          { label: '전체', value: fs.length },
          { label: '작성중', value: fs.filter(f => f.status === '작성중').length, color: 'orange' },
          { label: '발주', value: fs.filter(f => f.status === '발주완료').length, color: 'accent' },
          { label: '가공중', value: fs.filter(f => f.status === '가공중').length, color: 'purple' },
          { label: '입고', value: fs.filter(f => f.status === '입고완료').length, color: 'green' },
        ];
      }}
      renderItem={(fo) => (<>
        <Indicator color={`var(--${sColor[fo.status] || 'gray'})`} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id" style={{ fontFamily: 'monospace' }}>{fo.fo_no}</span>
            <span className="msg-date">{fo.fo_date}</span>
            <Badge text={fo.status} color={sColor[fo.status] || 'gray'} />
            <Badge text={fo.processing_type === '사급가공' ? '사급' : '외주'} color={fo.processing_type === '사급가공' ? 'orange' : 'purple'} />
          </div>
          <div className="msg-title">{fo.vendor_name}{fo.project_name ? ` · ${fo.project_name}` : ''}</div>
          <div className="msg-meta">
            <M>품목 {fo.item_count}</M>
            {fo.total_amount > 0 && <span className="money">{money(fo.total_amount)}</span>}
          </div>
        </div>
      </>)}
    />
  );
}
