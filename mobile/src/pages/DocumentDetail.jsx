import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const money = (v) => v ? Number(v).toLocaleString() : '0';

export default function DocumentDetail() {
  const { reqNo } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [cForm, setCForm] = useState({ commencement_date: '', agent_id: '' });
  const [dForm, setDForm] = useState({ delivery_date: '' });
  const [attType, setAttType] = useState('biz_registration');
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/documents/${encodeURIComponent(reqNo)}/detail`)
      .then((d) => {
        setData(d);
        setCForm({
          commencement_date: d.package.commencement_date || '',
          agent_id: d.package.commencement_agent_id || '',
        });
        setDForm({ delivery_date: d.package.delivery_date || '' });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [reqNo]);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">서류 정보를 찾을 수 없습니다</div>;

  const p = data.package;
  const procurements = data.procurements || [];
  const attachments = data.attachments || [];
  const agents = data.agents || [];
  const attachTypes = data.doc_attach_types || {};

  const token = () => localStorage.getItem('token');
  const pdfUrl = (which) => `/api/app/documents/${encodeURIComponent(reqNo)}/${which}-pdf?token=${encodeURIComponent(token())}`;
  const fileUrl = (path) => `/api/app/document-file?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token())}`;

  const step = {
    contract: !!p.req_pdf_path,
    commencement: !!p.commencement_generated,
    delivery: !!p.delivery_generated,
  };

  const uploadContract = async (file) => {
    const fd = new FormData();
    fd.append('contract_pdf', file);
    setBusy(true);
    try {
      const res = await fetch(`/api/app/documents/${encodeURIComponent(reqNo)}/upload-contract`, {
        method: 'POST', headers: { Authorization: `Bearer ${token()}` }, body: fd,
      });
      const j = await res.json();
      if (!j.ok) throw new Error(j.error || '업로드 실패');
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const saveCommencement = async () => {
    try {
      await api.post(`/documents/${encodeURIComponent(reqNo)}/save-commencement`, {
        commencement_date: cForm.commencement_date,
        agent_id: cForm.agent_id || null,
      });
      load();
    } catch (e) { alert(e.message); }
  };
  const saveDelivery = async () => {
    try {
      await api.post(`/documents/${encodeURIComponent(reqNo)}/save-delivery`, {
        delivery_date: dForm.delivery_date,
      });
      load();
    } catch (e) { alert(e.message); }
  };

  const uploadAttachment = async (file) => {
    const fd = new FormData();
    fd.append('file_type', attType);
    fd.append('attachment_file', file);
    setBusy(true);
    try {
      const res = await fetch(`/api/app/documents/${encodeURIComponent(reqNo)}/upload-attachment`, {
        method: 'POST', headers: { Authorization: `Bearer ${token()}` }, body: fd,
      });
      const j = await res.json();
      if (!j.ok) throw new Error(j.error || '업로드 실패');
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const deleteAttachment = async (id) => {
    if (!confirm('삭제하시겠습니까?')) return;
    try {
      await api.post(`/documents/${encodeURIComponent(reqNo)}/attachments/${id}/delete`, {});
      load();
    } catch (e) { alert(e.message); }
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1 style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 14 }}>
          {p.business_name || '서류관리'}
        </h1>
      </div>

      {/* 기본 헤더 */}
      <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{p.procurement_req_no}</div>
        <div style={{ fontSize: 12, color: 'var(--text)' }}>{p.demand_org}</div>
      </div>

      {/* 스텝 인디케이터 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, padding: 12, borderBottom: '1px solid var(--border)' }}>
        <Step n="1" label="계약서" done={step.contract} />
        <Step n="2" label="착수계" done={step.commencement} ready={step.contract} />
        <Step n="3" label="납품계" done={step.delivery} ready={step.contract} />
      </div>

      {/* 1. 계약서 (납품요구서) */}
      <Section title="1. 계약서 (납품요구서)" right={p.req_pdf_path ? <Badge text="등록완료" color="green" /> : null}>
        {p.req_pdf_path && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: 8, background: 'var(--surface)', borderRadius: 6, marginBottom: 8 }}>
            <Info label="계약체결번호" value={p.contract_no} mono />
            <Info label="계약체결일" value={p.contract_date} />
            <Info label="하자담보기간" value={p.warranty_period} />
            <Info label="검사기관" value={p.inspection_org} />
            <Info label="검수기관" value={p.acceptance_org} />
            <Info label="관청구분" value={p.org_type} />
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={btnStyle('var(--accent)', '#fff')}>
            {busy ? '업로드중...' : (p.req_pdf_path ? '재업로드' : '📄 PDF 업로드')}
            <input type="file" accept=".pdf" style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files[0]; if (f) uploadContract(f); e.target.value = ''; }} />
          </label>
          {p.req_pdf_path && (
            <a href={fileUrl(p.req_pdf_path)} target="_blank" rel="noreferrer" style={btnStyle('var(--surface)', 'var(--text-bright)')}>PDF 보기</a>
          )}
        </div>
      </Section>

      {/* 2. 착수계 */}
      <Section title="2. 착수계" right={
        p.commencement_generated ? <Badge text="생성완료" color="green" /> :
        p.commencement_doc_no ? <Badge text="정보저장됨" color="orange" /> : null
      }>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 8 }}>
          <div>
            <label style={labelSt}>착수일</label>
            <input type="date" value={cForm.commencement_date} onChange={(e) => setCForm({ ...cForm, commencement_date: e.target.value })} style={inpSt} />
          </div>
          <div>
            <label style={labelSt}>현장대리인</label>
            <select value={cForm.agent_id || ''} onChange={(e) => setCForm({ ...cForm, agent_id: e.target.value })} style={inpSt}>
              <option value="">선택</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name} {a.position}</option>)}
            </select>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={labelSt}>공문번호</label>
            <input value={p.commencement_doc_no || '자동채번'} readOnly style={{ ...inpSt, fontFamily: 'monospace', background: 'var(--surface)' }} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={saveCommencement} style={btnStyle('var(--accent)', '#fff')}>정보 저장</button>
          {p.commencement_doc_no && (
            <a href={pdfUrl('commencement')} target="_blank" rel="noreferrer" style={btnStyle('var(--orange)', '#fff')}>📥 착수계 PDF</a>
          )}
        </div>
      </Section>

      {/* 3. 납품계 */}
      <Section title="3. 납품계" right={
        p.delivery_generated ? <Badge text="생성완료" color="green" /> :
        p.delivery_doc_no ? <Badge text="정보저장됨" color="orange" /> : null
      }>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 8 }}>
          <div>
            <label style={labelSt}>납품일 (제출일자)</label>
            <input type="date" value={dForm.delivery_date} onChange={(e) => setDForm({ ...dForm, delivery_date: e.target.value })} style={inpSt} />
          </div>
          <div>
            <label style={labelSt}>공문번호</label>
            <input value={p.delivery_doc_no || '자동채번'} readOnly style={{ ...inpSt, fontFamily: 'monospace', background: 'var(--surface)' }} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={saveDelivery} style={btnStyle('var(--accent)', '#fff')}>정보 저장</button>
          {p.delivery_doc_no && (
            <a href={pdfUrl('delivery')} target="_blank" rel="noreferrer" style={btnStyle('var(--orange)', '#fff')}>📥 납품계 PDF</a>
          )}
        </div>
      </Section>

      {/* 4. 첨부파일 */}
      <Section title={`첨부파일 (${attachments.length})`}>
        {attachments.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>등록된 첨부파일이 없습니다</div>
        ) : attachments.map((a) => (
          <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderTop: '1px solid var(--border)' }}>
            <span className="badge badge-gray" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{a.file_type_label}</span>
            <a href={fileUrl(a.storage_path)} target="_blank" rel="noreferrer"
              style={{ flex: 1, minWidth: 0, fontSize: 12, color: 'var(--accent)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {a.file_name}
            </a>
            <button onClick={() => deleteAttachment(a.id)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 6, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={attType} onChange={(e) => setAttType(e.target.value)} style={{ ...inpSt, width: 'auto', flex: '0 0 auto' }}>
            {Object.entries(attachTypes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label style={btnStyle('var(--accent)', '#fff')}>
            {busy ? '업로드중...' : '📎 업로드'}
            <input type="file" style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files[0]; if (f) uploadAttachment(f); e.target.value = ''; }} />
          </label>
        </div>
      </Section>

      {/* 금액 정보 */}
      <Section title="💰 금액 정보">
        <AmountRow label="품대계" value={money(p.supply_amount)} />
        <AmountRow label="수수료" value={money(p.fee)} />
        <AmountRow label="합계금액" value={money(p.total_amount)} total />
      </Section>

      {/* 기본 정보 */}
      <Section title="기본 정보">
        <Info label="사업명" value={p.business_name} full />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <Info label="수요기관" value={p.demand_org} />
          <Info label="수요기관번호" value={p.demand_org_no} mono />
          <Info label="납품기한" value={procurements[0]?.dlvr_tmlmt_date} />
          <Info label="납품요구일자" value={procurements[0]?.cntrct_dlvr_req_date} />
        </div>
      </Section>

      {/* 품목 내역 */}
      <Section title={`품목 내역 (${procurements.length})`}>
        {procurements.map((pr) => (
          <div key={pr.id} style={{ padding: '8px 0', borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>
              {pr.dtil_prdct_clsfc_no_nm || pr.prdct_clsfc_no_nm || '-'}
            </div>
            {pr.prdct_idnt_no_nm && (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{pr.prdct_idnt_no_nm}</div>
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 11 }}>
              <span style={{ color: 'var(--text-muted)' }}>단가 {money(pr.prdct_uprc)}</span>
              <span style={{ color: 'var(--text-muted)' }}>수량 {pr.prdct_qty || '-'}</span>
              <span style={{ color: 'var(--text-bright)', fontWeight: 700 }}>{money(pr.prdct_amt)}원</span>
            </div>
          </div>
        ))}
      </Section>
    </div>
  );
}

function Section({ title, right, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-bright)' }}>{title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}
function Step({ n, label, done, ready }) {
  const cls = done ? 'green' : ready ? 'orange' : 'gray';
  const colors = { green: 'var(--green)', orange: 'var(--orange)', gray: 'var(--border)' };
  return (
    <div style={{ padding: 8, borderRadius: 6, textAlign: 'center', background: `${colors[cls]}25`, border: `1px solid ${colors[cls]}` }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: colors[cls] }}>{done ? '✓' : n}</div>
      <div style={{ fontSize: 10, color: 'var(--text)', marginTop: 2 }}>{label}</div>
    </div>
  );
}
function Badge({ text, color = 'gray' }) {
  return <span className={`badge badge-${color}`} style={{ fontSize: 10 }}>{text}</span>;
}
function Info({ label, value, mono, full }) {
  return (
    <div style={full ? { gridColumn: '1 / -1' } : undefined}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 12, color: 'var(--text-bright)', fontFamily: mono ? 'monospace' : undefined, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {value || '-'}
      </div>
    </div>
  );
}
function AmountRow({ label, value, total }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderTop: total ? '2px solid var(--text-bright)' : '1px solid var(--border)', marginTop: total ? 4 : 0 }}>
      <span style={{ fontSize: total ? 13 : 12, color: 'var(--text-muted)', fontWeight: total ? 700 : 400 }}>{label}</span>
      <span style={{ fontSize: total ? 14 : 12, color: total ? 'var(--accent)' : 'var(--text-bright)', fontFamily: 'monospace', fontWeight: total ? 700 : 500 }}>
        {value}원
      </span>
    </div>
  );
}

const inpSt = { width: '100%', padding: '7px 10px', borderRadius: 4, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 12 };
const labelSt = { fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 3 };
const btnStyle = (bg, color) => ({
  padding: '7px 12px', borderRadius: 4, fontSize: 12, fontWeight: 600,
  border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
  background: bg, color, textDecoration: 'none', display: 'inline-flex', alignItems: 'center',
});
