import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const money = (v) => v ? Number(v).toLocaleString() + '원' : '';

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState('');
  const [posting, setPosting] = useState(false);
  const [modal, setModal] = useState(null); // 'project' | 'basis' | 'workpath' | 'material' | 'contact' | null
  const [editTarget, setEditTarget] = useState(null); // 수정 대상

  const load = () => {
    setLoading(true);
    api.get(`/projects/${id}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [id]);

  const act = async (action, body = {}) => {
    try {
      await api.post(`/projects/${id}/action`, { action, ...body });
      load();
      setModal(null);
      setEditTarget(null);
    } catch (e) {
      alert(e.message);
    }
  };

  const handleComment = async (e) => {
    e?.preventDefault?.();
    if (!comment.trim()) return;
    setPosting(true);
    try {
      await api.post(`/projects/${id}/comment`, { content: comment.trim() });
      setComment('');
      load();
    } catch (e) { alert(e.message); }
    setPosting(false);
  };

  const convertToContract = async () => {
    if (!confirm('실제 계약 리스트로 전환하시겠습니까?')) return;
    try {
      await api.post(`/projects/${id}/convert-to-contract`, {});
      load();
    } catch (e) { alert(e.message); }
  };

  const deleteRequest = async () => {
    const reason = prompt('삭제요청 사유를 입력해 주세요.');
    if (!reason || !reason.trim()) return;
    try {
      await api.post(`/projects/${id}/delete-request`, { reason: reason.trim() });
      alert('삭제요청이 접수되었습니다.');
      navigate('/design');
    } catch (e) { alert(e.message); }
  };

  const copyWorkPath = () => {
    if (data?.project?.work_path) {
      navigator.clipboard.writeText(data.project.work_path).then(() => alert('복사 완료'));
    }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">현장 정보를 찾을 수 없습니다</div>;

  const p = data.project || {};
  const contracts = data.contracts || [];
  const history = data.history || [];
  const materials = data.materials || [];
  const contacts = data.contacts || [];
  const drawings = data.drawings || [];
  const fixtures = data.illuminance_fixtures || [];
  const opts = data.detail_item_options || [];

  return (
    <div style={{ paddingBottom: 140 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 14, cursor: 'pointer', padding: '4px 0' }}>←</button>
        <h1 style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.temp_name || p.name}</h1>
      </div>

      {/* 헤더 액션 */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {!p.is_contracted && <Btn onClick={convertToContract}>계약 전환</Btn>}
        <Btn onClick={() => setModal('project')}>정보 수정</Btn>
        <Btn onClick={deleteRequest} danger>삭제요청</Btn>
      </div>

      {/* 기본 정보 */}
      <Section title="기본 정보">
        <Row label="설계번호" value={p.project_no} />
        <Row label="상태" value={p.status} />
        <Row label="현장주소" value={p.site_address} />
        <Row label="납품지주소" value={p.shipping_address} />
        <Row label="계약예정일" value={p.expected_contract_date} />
      </Section>

      {/* 현장 메모 */}
      <Section title="📝 현장 특이사항 및 메모">
        <div style={{ fontSize: 12, color: 'var(--text)', whiteSpace: 'pre-wrap' }}>
          {p.site_memo || <span style={{ color: 'var(--text-muted)' }}>등록된 메모가 없습니다</span>}
        </div>
      </Section>

      {/* 설계 기준 */}
      <Section title="📋 설계 기준 및 주요 요청사항" action={<Btn small onClick={() => setModal('basis')}>수정</Btn>}>
        <div style={{ fontSize: 12, color: 'var(--text)', whiteSpace: 'pre-wrap' }}>
          {p.design_basis || <span style={{ color: 'var(--text-muted)' }}>기준 미입력</span>}
        </div>
      </Section>

      {/* 작업 경로 */}
      <Section title="📂 작업 경로" action={
        <div style={{ display: 'flex', gap: 4 }}>
          {p.work_path && <Btn small onClick={copyWorkPath}>복사</Btn>}
          <Btn small onClick={() => setModal('workpath')}>수정</Btn>
        </div>
      }>
        <code style={{ fontSize: 11, color: 'var(--text)', wordBreak: 'break-all' }}>
          {p.work_path || <span style={{ color: 'var(--text-muted)' }}>경로 미설정</span>}
        </code>
      </Section>

      {/* 조도 설계정보 */}
      <Section title="💡 조도 설계정보">
        <Row label="시설종류" value={p.illuminance_facility_type || '-'} />
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>기구 목록</div>
          {fixtures.length === 0 ? <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>-</span> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {fixtures.map((f, i) => (
                <span key={i} className="badge badge-gray" style={{ fontSize: 10 }}>
                  {f.type}{f.model ? ` ${f.model}` : ''}{f.watt ? ` ${f.watt}W` : ''} x{f.qty}
                </span>
              ))}
            </div>
          )}
        </div>
      </Section>

      {/* 자재 목록 */}
      <Section title="📦 설계 반영 자재 목록" action={
        <Btn small onClick={() => { setEditTarget({ new: true }); setModal('material'); }}>+ 추가</Btn>
      }>
        {materials.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>등록된 자재가 없습니다</div>
        ) : (
          materials.map((m) => (
            <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: 'var(--text-bright)' }}>{m.model_name}</div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{m.category} · 수량 {m.quantity}</div>
              </div>
              <Btn small onClick={() => { setEditTarget(m); setModal('material'); }}>수정</Btn>
              <Btn small danger onClick={() => {
                if (confirm('해당 품목을 삭제할까요?')) act('delete_material', { material_id: m.id });
              }}>삭제</Btn>
            </div>
          ))
        )}
      </Section>

      {/* 담당자 */}
      <Section title="👤 담당자" action={
        <Btn small onClick={() => { setEditTarget({ new: true }); setModal('contact'); }}>+ 추가</Btn>
      }>
        {contacts.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>등록된 담당자가 없습니다</div>
        ) : (
          contacts.map((c) => (
            <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: 'var(--text-bright)' }}>{c.name} <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({c.category})</span></div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{c.phone}{c.email ? ` · ${c.email}` : ''}</div>
              </div>
              <Btn small onClick={() => { setEditTarget(c); setModal('contact'); }}>수정</Btn>
              <Btn small danger onClick={() => {
                const reason = prompt(`[${c.name}] 담당자를 삭제하시겠습니까? 사유:`);
                if (reason) act('delete_contact', { contact_id: c.id, delete_reason: reason });
              }}>삭제</Btn>
            </div>
          ))
        )}
      </Section>

      {/* 도면 */}
      {drawings.length > 0 && (
        <Section title="📐 도면">
          {drawings.map((d) => (
            <div key={d.id} style={{ padding: '6px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, color: 'var(--text-bright)' }}>{d.title}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                {d.drawing_type} · v{d.latest_version_no} ({d.version_count}개) · {d.convert_status}
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* 계약 */}
      {contracts.length > 0 && (
        <Section title="📑 계약 정보">
          {contracts.map((c) => (
            <div key={c.id} style={{ padding: '6px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, color: 'var(--text-bright)' }}>{c.contract_name}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                {c.g2b_contract_no} · {c.ordering_org}
                {c.contract_amount ? ` · ${money(c.contract_amount)}` : ''}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                납품기한 {c.delivery_due_date || '-'} · {c.payment_status}
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* 히스토리 */}
      <div style={{ padding: '12px 0' }}>
        <div style={{ padding: '0 16px', fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          히스토리 ({history.length})
        </div>
        {history.length === 0 ? (
          <div className="page-empty">기록이 없습니다</div>
        ) : history.slice(0, 30).map((h, i) => (
          <div key={i} style={{ padding: '6px 16px', display: 'flex', gap: 10 }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', flexShrink: 0, background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)' }}>
              {(h.user_name || '?')[0]}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {h.content}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 코멘트 입력 */}
      <div style={{ position: 'fixed', bottom: 56, left: 0, right: 0, padding: '8px 12px', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)', display: 'flex', gap: 8 }}>
        <input type="text" placeholder="코멘트 입력..." value={comment} onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleComment()}
          style={{ flex: 1, padding: '8px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 }} />
        <button onClick={handleComment} disabled={posting}
          style={{ padding: '8px 16px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none' }}>전송</button>
      </div>

      {/* 모달들 */}
      {modal === 'project' && (
        <Modal title="⚙️ 현장 기본정보 수정" onClose={() => setModal(null)}>
          <ProjectForm project={p} onSubmit={(body) => act('update_project', body)} />
        </Modal>
      )}
      {modal === 'basis' && (
        <Modal title="📝 설계 기준 수정" onClose={() => setModal(null)}>
          <BasisForm basis={p.design_basis} onSubmit={(body) => act('update_design_basis', body)} />
        </Modal>
      )}
      {modal === 'workpath' && (
        <Modal title="📂 작업 경로 수정" onClose={() => setModal(null)}>
          <WorkPathForm workPath={p.work_path} onSubmit={(body) => act('update_work_path', body)} />
        </Modal>
      )}
      {modal === 'material' && (
        <Modal title={editTarget?.new ? '+ 자재 추가' : '자재 수정'} onClose={() => { setModal(null); setEditTarget(null); }}>
          <MaterialForm item={editTarget?.new ? null : editTarget} opts={opts}
            onSubmit={(body) => {
              if (editTarget?.new) act('add_material', body);
              else act('update_material', { ...body, material_id: editTarget.id });
            }} />
        </Modal>
      )}
      {modal === 'contact' && (
        <Modal title={editTarget?.new ? '+ 담당자 추가' : '담당자 수정'} onClose={() => { setModal(null); setEditTarget(null); }}>
          <ContactForm contact={editTarget?.new ? null : editTarget}
            onSubmit={(body) => {
              if (editTarget?.new) act('add_contact', body);
              else act('update_contact', { ...body, contact_id: editTarget.id });
            }} />
        </Modal>
      )}
    </div>
  );
}

function Section({ title, action, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{title}</div>
        {action}
      </div>
      {children}
    </div>
  );
}
function Row({ label, value }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0' }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)', textAlign: 'right', maxWidth: '65%', wordBreak: 'break-all' }}>{value}</span>
    </div>
  );
}
function Btn({ children, onClick, small, danger }) {
  return (
    <button onClick={onClick} style={{
      padding: small ? '3px 8px' : '5px 10px',
      borderRadius: 4, fontSize: small ? 10 : 11, fontWeight: 600,
      border: 'none', cursor: 'pointer',
      background: danger ? 'rgba(242,63,67,0.15)' : 'var(--surface)',
      color: danger ? 'var(--red)' : 'var(--text-bright)',
      whiteSpace: 'nowrap',
    }}>{children}</button>
  );
}
function Modal({ title, children, onClose }) {
  return (
    <div onClick={onClose} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-secondary)', borderRadius: 8, maxWidth: 500, width: '100%', maxHeight: '85vh', overflow: 'auto', padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' }}>{title}</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: 'pointer' }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
const fieldStyle = { width: '100%', padding: '8px 10px', borderRadius: 4, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13, marginBottom: 8 };
const labelStyle = { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 4 };
const submitStyle = { width: '100%', padding: '10px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer', marginTop: 8 };

function ProjectForm({ project, onSubmit }) {
  const [form, setForm] = useState({
    temp_name: project.temp_name || '',
    expected_contract_date: project.expected_contract_date || '',
    site_address: project.site_address || '',
    shipping_address: project.shipping_address || '',
    site_memo: project.site_memo || '',
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}>
      <label style={labelStyle}>현장 가칭 *</label>
      <input style={fieldStyle} value={form.temp_name} onChange={set('temp_name')} required />
      <label style={labelStyle}>계약 예정일</label>
      <input type="date" style={fieldStyle} value={form.expected_contract_date} onChange={set('expected_contract_date')} />
      <label style={labelStyle}>📍 현장 주소</label>
      <input style={fieldStyle} value={form.site_address} onChange={set('site_address')} />
      <label style={labelStyle}>🚛 납품지 주소</label>
      <input style={fieldStyle} value={form.shipping_address} onChange={set('shipping_address')} />
      <label style={labelStyle}>📝 현장 메모</label>
      <textarea rows={4} style={fieldStyle} value={form.site_memo} onChange={set('site_memo')} />
      <button type="submit" style={submitStyle}>저장</button>
    </form>
  );
}
function BasisForm({ basis, onSubmit }) {
  const [form, setForm] = useState({ design_basis: basis || '', edit_reason: '' });
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (!form.edit_reason.trim()) { alert('수정 사유는 필수입니다'); return; } onSubmit(form); }}>
      <label style={labelStyle}>설계 기준</label>
      <textarea rows={8} style={fieldStyle} value={form.design_basis} onChange={(e) => setForm({ ...form, design_basis: e.target.value })} required />
      <label style={{ ...labelStyle, color: 'var(--red)' }}>⚠️ 수정 사유 (필수)</label>
      <input style={fieldStyle} value={form.edit_reason} onChange={(e) => setForm({ ...form, edit_reason: e.target.value })} required />
      <button type="submit" style={submitStyle}>저장</button>
    </form>
  );
}
function WorkPathForm({ workPath, onSubmit }) {
  const [v, setV] = useState(workPath || '');
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit({ work_path: v }); }}>
      <label style={labelStyle}>폴더 경로</label>
      <input style={fieldStyle} value={v} onChange={(e) => setV(e.target.value)} />
      <button type="submit" style={submitStyle}>저장</button>
    </form>
  );
}
function MaterialForm({ item, opts, onSubmit }) {
  const [form, setForm] = useState({
    category: item?.category || opts[0] || '',
    model_name: item?.model_name || '',
    quantity: item?.quantity || '1',
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}>
      <label style={labelStyle}>상세품목 *</label>
      <select style={fieldStyle} value={form.category} onChange={set('category')} required>
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      <label style={labelStyle}>모델명 *</label>
      <input style={fieldStyle} value={form.model_name} onChange={set('model_name')} required />
      <label style={labelStyle}>수량</label>
      <input type="number" min="0" style={fieldStyle} value={form.quantity} onChange={set('quantity')} />
      <button type="submit" style={submitStyle}>저장</button>
    </form>
  );
}
function ContactForm({ contact, onSubmit }) {
  const [form, setForm] = useState({
    contact_category: contact?.category || '',
    name: contact?.name || '',
    phone: contact?.phone || '',
    email: contact?.email || '',
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}>
      <label style={labelStyle}>구분 *</label>
      <input style={fieldStyle} placeholder="설계사, 감독관 등" value={form.contact_category} onChange={set('contact_category')} required />
      <label style={labelStyle}>이름 *</label>
      <input style={fieldStyle} value={form.name} onChange={set('name')} required />
      <label style={labelStyle}>연락처</label>
      <input style={fieldStyle} value={form.phone} onChange={set('phone')} />
      <label style={labelStyle}>이메일</label>
      <input type="email" style={fieldStyle} value={form.email} onChange={set('email')} />
      <button type="submit" style={submitStyle}>저장</button>
    </form>
  );
}
