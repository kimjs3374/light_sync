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
      onItemClick={(d) => nav(`/deliveries/${d.id}`)}
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
  return (
    <ListPage icon="#" title="발주관리" endpoint="/purchase-orders" dataKey="purchase_orders"
      onItemClick={(po) => nav(`/purchase-orders/${po.id}`)}
      renderItem={(po) => (<>
        <Indicator color={po.status === '작성중' ? 'var(--orange)' : 'var(--green)'} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id">{po.po_no}</span>
            <span className="msg-date">{po.po_date}</span>
            <Badge text={po.status} color={po.status === '작성중' ? 'orange' : 'green'} />
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
  return (
    <ListPage icon="#" title="입고관리" endpoint="/receivings" dataKey="receivings"
      onItemClick={(r) => nav(`/receivings/${r.id}`)}
      renderItem={(r) => (<>
        <Indicator color={r.status === '검수완료' ? 'var(--green)' : 'var(--orange)'} />
        <div className="msg-body">
          <div className="msg-top">
            <span className="msg-id">{r.rcv_no}</span>
            <span className="msg-date">{r.rcv_date}</span>
            <Badge text={r.status} color={r.status === '검수완료' ? 'green' : 'orange'} />
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
  return (
    <ListPage icon="#" title="거래처" endpoint="/vendors" dataKey="vendors"
      renderItem={(v) => (<>
        <Indicator />
        <div className="msg-body">
          <div className="msg-title">{v.name}</div>
          <div className="msg-meta">
            {v.ceo_name && <M>대표 {v.ceo_name}</M>}
            {v.tel && <M>{v.tel}</M>}
            {v.business && <M>{v.business}</M>}
            {v.business_no && <M>{v.business_no}</M>}
          </div>
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
