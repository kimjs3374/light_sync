import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_LABELS = { waiting: '납품대기', coordinating: '납품협의중', in_progress: '납품진행중', done: '납품완료' };
const STATUS_COLORS = { waiting: 'gray', coordinating: 'blue', in_progress: 'orange', done: 'green' };
const SPLIT_STATUS_LABELS = { waiting: '예정', coordinating: '진행', done: '완료' };

export default function DeliveryProjectDetail() {
  const { pid } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState('');
  const [modal, setModal] = useState(null);   // { type, delivery, split? }

  const load = () => {
    setLoading(true);
    api.get(`/delivery-projects/${pid}`).then(setData).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [pid]);

  const act = async (action, body = {}) => {
    try {
      await api.post(`/delivery-projects/${pid}/action`, { action, ...body });
      load();
      setModal(null);
    } catch (e) { alert(e.message); }
  };

  const sendComment = async () => {
    if (!comment.trim()) return;
    try {
      await api.post(`/projects/${pid}/comment`, { content: comment.trim(), scope: 'delivery' });
      setComment('');
      load();
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">납품 정보를 찾을 수 없습니다</div>;

  const p = data.project || {};
  const deliveries = data.deliveries || [];
  const contacts = data.contacts || [];
  const history = data.history || [];
  const users = data.users || [];

  const summary = {
    today: deliveries.reduce((s, d) => s + d.today_split_count, 0),
    overdue: deliveries.reduce((s, d) => s + d.overdue_split_count, 0),
    unassigned: deliveries.filter(d => d.is_unassigned).length,
  };

  return (
    <div style={{ paddingBottom: 130 }}>
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1 style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.temp_name}</h1>
      </div>

      {/* 헤더 액션 */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {p.project_no} · 계약 {p.contract_count} · 납품 {p.delivery_count} · 연락처 {p.contact_count}
        </span>
        <div style={{ flex: 1 }} />
        <Btn onClick={() => act('sync_deliveries')} small>🔄 동기화</Btn>
      </div>

      {/* 운영 포인트 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, padding: 12, borderBottom: '1px solid var(--border)' }}>
        <Kpi label="오늘회차" value={summary.today} />
        <Kpi label="지연" value={summary.overdue} color="red" />
        <Kpi label="미배정" value={summary.unassigned} color="orange" />
        <Kpi label="완납" value={deliveries.filter(x => x.delivery_status === 'done').length} color="green" />
      </div>

      {/* 납품카드 */}
      {deliveries.length === 0 ? (
        <div className="page-empty" style={{ padding: 20 }}>연결된 납품 대상이 없습니다</div>
      ) : deliveries.map((d, i) => (
        <DeliveryCard
          key={d.id}
          delivery={d}
          idx={i + 1}
          onAction={act}
          onOpenModal={(type, extra) => setModal({ type, delivery: d, ...extra })}
        />
      ))}

      {/* 연락처 */}
      <Section title="👤 연락처" action={<Btn small onClick={() => setModal({ type: 'contact-add' })}>+ 추가</Btn>}>
        {contacts.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>등록된 연락처가 없습니다</div>
        ) : contacts.map((c) => (
          <div key={c.id} style={{ padding: '6px 0', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, color: 'var(--text-bright)' }}>{c.name} <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({c.category})</span></div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{c.phone}{c.email ? ` · ${c.email}` : ''}</div>
            </div>
            <Btn small onClick={() => setModal({ type: 'contact-edit', contact: c })}>수정</Btn>
            <Btn small danger onClick={() => { if (confirm(`${c.name} 연락처를 삭제할까요?`)) act('delete_contact', { contact_id: c.id }); }}>삭제</Btn>
          </div>
        ))}
      </Section>

      {/* 히스토리 */}
      <div style={{ padding: '12px 0' }}>
        <div style={{ padding: '0 16px', fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase' }}>히스토리 ({history.length})</div>
        {history.length === 0 ? <div className="page-empty">기록 없음</div> :
          history.slice(0, 50).map((h, i) => (
            <div key={i} style={{ padding: '6px 16px', display: 'flex', gap: 10 }}>
              <div style={{ width: 26, height: 26, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 }}>
                {(h.user_name || '?')[0]}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{h.content}</div>
              </div>
            </div>
          ))}
      </div>

      {/* 코멘트 입력 */}
      <div style={{ position: 'fixed', bottom: 56, left: 0, right: 0, padding: '8px 12px', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, zIndex: 10 }}>
        <input type="text" placeholder="코멘트 입력..." value={comment} onChange={e => setComment(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendComment()}
          style={{ flex: 1, padding: '8px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 }} />
        <button onClick={sendComment} style={{ padding: '8px 16px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none' }}>전송</button>
      </div>

      {/* 모달 */}
      {modal?.type === 'split-add' && (
        <Modal title={`${modal.delivery.contract_name} · 회차 추가`} onClose={() => setModal(null)}>
          <SplitForm delivery={modal.delivery} onSubmit={(body) => act('add_split', { delivery_id: modal.delivery.id, ...body })} />
        </Modal>
      )}
      {modal?.type === 'split-edit' && (
        <Modal title={`${modal.split.split_no}차 회차 수정`} onClose={() => setModal(null)}>
          <SplitForm delivery={modal.delivery} split={modal.split}
            onSubmit={(body) => act('update_split', { split_id: modal.split.id, ...body })} />
        </Modal>
      )}
      {modal?.type === 'assign-owner' && (
        <Modal title="담당자 지정" onClose={() => setModal(null)}>
          <AssignOwnerForm users={users} onSubmit={(uid) => act('assign_delivery_owner', { delivery_id: modal.delivery.id, owner_user_id: uid })} />
        </Modal>
      )}
      {modal?.type === 'inspection' && (
        <Modal title="검수 상태 변경" onClose={() => setModal(null)}>
          <InspectionForm delivery={modal.delivery}
            onSubmit={(body) => act('update_inspection', { delivery_id: modal.delivery.id, ...body })} />
        </Modal>
      )}
      {modal?.type === 'contact-add' && (
        <Modal title="+ 연락처 추가" onClose={() => setModal(null)}>
          <ContactForm onSubmit={(body) => act('add_contact', body)} />
        </Modal>
      )}
      {modal?.type === 'contact-edit' && (
        <Modal title="연락처 수정" onClose={() => setModal(null)}>
          <ContactForm contact={modal.contact}
            onSubmit={(body) => act('update_contact', { contact_id: modal.contact.id, ...body })} />
        </Modal>
      )}
    </div>
  );
}

function DeliveryCard({ delivery: d, idx, onAction, onOpenModal }) {
  const remain = (d.planned_total_qty || 0) - (d.delivered_total_qty || 0);
  const sbg = STATUS_COLORS[d.delivery_status] || 'gray';

  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      {/* 헤더 */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>계약 {idx}</div>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-bright)', marginTop: 2 }}>{d.contract_name}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
          <Badge text={`담당 ${d.contact_name || '미지정'}`} />
          {d.contact_phone && <Badge text={d.contact_phone} />}
          <Badge text={`계획 ${d.planned_total_qty}EA`} />
          <Badge text={`완료 ${d.delivered_total_qty}EA`} />
          {remain > 0 ? <Badge text={`잔여 ${remain}EA`} color="red" /> :
            (d.planned_total_qty || 0) > 0 ? <Badge text="완납" color="green" /> : null}
          <Badge text={STATUS_LABELS[d.delivery_status] || d.delivery_status} color={sbg} />
          <Badge text={`검수 ${d.inspection_status}`} color={d.inspection_status === '합격' ? 'green' : d.inspection_status === '불합격' ? 'red' : 'gray'} />
        </div>
      </div>

      {/* 액션 */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
        <Btn small onClick={() => onAction('assign_me', { delivery_id: d.id })}>내가 담당</Btn>
        <Btn small onClick={() => onOpenModal('assign-owner')}>담당자 지정</Btn>
        <Btn small onClick={() => onOpenModal('inspection')}>검수</Btn>
        <Btn small primary onClick={() => onOpenModal('split-add')}>+ 회차</Btn>
      </div>

      {/* 모델별 진행률 */}
      {d.item_stats.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 6, marginBottom: 10 }}>
          {d.item_stats.map((s) => {
            const ip = s.planned > 0 ? Math.round(s.delivered / s.planned * 100) : 0;
            const rem = s.planned - s.delivered;
            return (
              <div key={s.item_id} style={{ padding: 8, background: 'var(--surface)', borderRadius: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.category} {s.model_name}
                  </span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: ip >= 100 ? 'var(--green)' : 'var(--text-muted)', whiteSpace: 'nowrap' }}>{ip}%</span>
                </div>
                <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(ip, 100)}%`, background: ip >= 100 ? 'var(--green)' : 'var(--accent)' }} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>
                  <span>계획 {s.planned}</span><span>완료 {s.delivered}</span>
                  {rem > 0 ? <span style={{ color: 'var(--red)', fontWeight: 700 }}>잔여 {rem}</span> : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 전체 진행률 */}
      {(d.planned_total_qty || 0) > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>
            <span>전체 진행률</span><span>{d.progress_pct}%</span>
          </div>
          <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${Math.min(d.progress_pct, 100)}%`, background: d.delivery_status === 'done' ? 'var(--green)' : 'var(--accent)' }} />
          </div>
        </div>
      )}

      {/* 회차 리스트 */}
      {d.splits.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 10, textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 6 }}>
          등록된 회차가 없습니다
        </div>
      ) : d.splits.map((sp) => (
        <SplitRow key={sp.id} split={sp}
          onEdit={() => onOpenModal('split-edit', { split: sp })}
          onDelete={() => { if (confirm(`${sp.split_no}차를 삭제할까요?`)) onAction('delete_split', { split_id: sp.id }); }}
        />
      ))}

    </div>
  );
}

function SplitRow({ split: sp, onEdit, onDelete }) {
  const isDone = sp.status === 'done' || sp.status === '완료';
  const statusColor = isDone ? 'green' : (sp.status === 'coordinating' || sp.status === '진행') ? 'orange' : 'gray';
  const bg = sp.is_overdue ? 'rgba(242,63,67,0.1)' : sp.is_today ? 'rgba(83,155,245,0.1)' : 'var(--surface)';

  return (
    <div style={{ padding: 10, borderRadius: 6, background: bg, marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, gap: 6 }}>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 13, color: 'var(--text-bright)' }}>{sp.split_no}차</strong>
          <Badge text={SPLIT_STATUS_LABELS[sp.status] || sp.status} color={statusColor} />
          <Badge text={`${sp.quantity}EA`} />
          {sp.is_today && <Badge text="오늘" color="blue" />}
          {sp.is_overdue && <Badge text="지연" color="red" />}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <Btn small onClick={onEdit}>수정</Btn>
          <Btn small danger onClick={onDelete}>삭제</Btn>
        </div>
      </div>
      {sp.split_items.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginBottom: 6 }}>
          {sp.split_items.map((si, i) => (
            <span key={i} className="badge badge-gray" style={{ fontSize: 10 }}>
              {si.category} {si.model_name} <strong>{si.quantity}EA</strong>
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4, fontSize: 10 }}>
        <Mini label="예정일" value={sp.scheduled_date || '-'} />
        <Mini label="확정일" value={sp.confirmed_date || '-'} />
        <Mini label="상차" value={sp.loading_done_at?.replace('T', ' ') || '-'} />
        <Mini label="납품" value={sp.delivered_done_at?.replace('T', ' ') || '-'} />
      </div>
      {sp.note && (
        <div style={{ marginTop: 6, padding: 6, background: 'var(--bg)', borderRadius: 4, fontSize: 11, color: 'var(--text)', whiteSpace: 'pre-wrap' }}>
          📝 {sp.note}
        </div>
      )}
    </div>
  );
}

function SplitForm({ delivery, split, onSubmit }) {
  const [form, setForm] = useState({
    split_no: split?.split_no || (delivery.splits.length + 1),
    scheduled_date: split?.scheduled_date || '',
    confirmed_date: split?.confirmed_date || '',
    loading_done_at: split?.loading_done_at || '',
    delivered_done_at: split?.delivered_done_at || '',
    status: split?.status || 'waiting',
    note: split?.note || '',
  });
  const existingQtys = {};
  (split?.split_items || []).forEach(si => { existingQtys[si.contract_item_id] = si.quantity; });
  const [qtys, setQtys] = useState(existingQtys);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const itemStatsById = {};
  delivery.item_stats.forEach(s => { itemStatsById[s.item_id] = s; });

  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit({ ...form, item_qtys: qtys }); }}>
      {delivery.item_stats.length > 0 && (
        <>
          <label style={labelSt}>모델별 수량</label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 10 }}>
            {delivery.item_stats.map((s) => {
              const rem = (s.planned || 0) - (s.delivered || 0) + (split?.split_items?.find(si => si.contract_item_id === s.item_id)?.quantity || 0);
              return (
                <div key={s.item_id} style={{ background: 'var(--surface)', padding: 6, borderRadius: 4 }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.category} {s.model_name}
                  </div>
                  <input type="number" min="0" placeholder="0"
                    value={qtys[s.item_id] || ''}
                    onChange={e => setQtys({ ...qtys, [s.item_id]: parseInt(e.target.value) || 0 })}
                    style={{ ...inpSt, textAlign: 'right', padding: '5px 8px', fontSize: 12 }} />
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>
                    계획 {s.planned} / 잔여 <span style={{ color: rem > 0 ? 'var(--red)' : 'var(--green)', fontWeight: 700 }}>{rem}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div><label style={labelSt}>회차</label><input type="number" min="1" value={form.split_no} onChange={set('split_no')} style={inpSt} /></div>
        <div><label style={labelSt}>상태</label>
          <select value={form.status} onChange={set('status')} style={inpSt}>
            <option value="waiting">예정</option>
            <option value="coordinating">진행</option>
            <option value="done">완료</option>
          </select>
        </div>
        <div><label style={labelSt}>예정일</label><input type="date" value={form.scheduled_date} onChange={set('scheduled_date')} style={inpSt} /></div>
        <div><label style={labelSt}>확정일</label><input type="date" value={form.confirmed_date} onChange={set('confirmed_date')} style={inpSt} /></div>
        <div><label style={labelSt}>상차완료</label><input type="datetime-local" value={form.loading_done_at} onChange={set('loading_done_at')} style={inpSt} /></div>
        <div><label style={labelSt}>납품완료</label><input type="datetime-local" value={form.delivered_done_at} onChange={set('delivered_done_at')} style={inpSt} /></div>
      </div>
      <label style={labelSt}>메모</label>
      <input value={form.note} onChange={set('note')} placeholder="운송/현장 특이사항" style={inpSt} />
      <button type="submit" style={submitSt}>{split ? '회차 저장' : '회차 추가'}</button>
    </form>
  );
}

function AssignOwnerForm({ users, onSubmit }) {
  const [uid, setUid] = useState('');
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (uid) onSubmit(uid); }}>
      <label style={labelSt}>담당자 선택</label>
      <select value={uid} onChange={e => setUid(e.target.value)} style={inpSt} required>
        <option value="">-- 선택 --</option>
        {users.map(u => <option key={u.id} value={u.id}>{u.name} {u.position}</option>)}
      </select>
      <button type="submit" style={submitSt}>지정</button>
    </form>
  );
}

function InspectionForm({ delivery, onSubmit }) {
  const [form, setForm] = useState({
    inspection_status: delivery.inspection_status || '미검수',
    inspection_date: delivery.inspection_date || '',
    inspector: delivery.inspector || '',
    inspection_note: delivery.inspection_note || '',
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}>
      <label style={labelSt}>상태</label>
      <select value={form.inspection_status} onChange={set('inspection_status')} style={inpSt} required>
        {['미검수', '합격', '불합격', '보완'].map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <label style={labelSt}>검수일</label>
      <input type="date" value={form.inspection_date} onChange={set('inspection_date')} style={inpSt} />
      <label style={labelSt}>검수자</label>
      <input value={form.inspector} onChange={set('inspector')} style={inpSt} />
      <label style={labelSt}>비고</label>
      <textarea rows={3} value={form.inspection_note} onChange={set('inspection_note')} style={inpSt} />
      <button type="submit" style={submitSt}>저장</button>
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
      <label style={labelSt}>구분</label>
      <input value={form.contact_category} onChange={set('contact_category')} placeholder="설계사, 감독관 등" style={inpSt} />
      <label style={labelSt}>이름 *</label>
      <input value={form.name} onChange={set('name')} style={inpSt} required />
      <label style={labelSt}>연락처</label>
      <input value={form.phone} onChange={set('phone')} style={inpSt} />
      <label style={labelSt}>이메일</label>
      <input type="email" value={form.email} onChange={set('email')} style={inpSt} />
      <button type="submit" style={submitSt}>저장</button>
    </form>
  );
}

function Section({ title, action, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{title}</div>
        {action}
      </div>
      {children}
    </div>
  );
}
function Badge({ text, color = 'gray' }) {
  return <span className={`badge badge-${color}`} style={{ fontSize: 10 }}>{text}</span>;
}
function Kpi({ label, value, color }) {
  return (
    <div style={{ padding: 8, background: 'var(--surface)', borderRadius: 6, textAlign: 'center' }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: color ? `var(--${color})` : 'var(--text-bright)' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</div>
    </div>
  );
}
function Mini({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 11, color: 'var(--text-bright)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
    </div>
  );
}
function Btn({ children, onClick, primary, danger, small }) {
  return (
    <button onClick={onClick} type="button" style={{
      padding: small ? '4px 8px' : '6px 10px',
      borderRadius: 4, fontSize: small ? 11 : 12, fontWeight: 600,
      border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
      background: primary ? 'var(--accent)' : danger ? 'rgba(242,63,67,0.15)' : 'var(--surface)',
      color: primary ? '#fff' : danger ? 'var(--red)' : 'var(--text-bright)',
    }}>{children}</button>
  );
}
function Modal({ title, onClose, children }) {
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-secondary)', borderRadius: 8, maxWidth: 600, width: '100%', maxHeight: '90vh', overflow: 'auto', padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' }}>{title}</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: 'pointer' }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

const inpSt = { width: '100%', padding: '8px 10px', borderRadius: 4, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13, marginBottom: 6 };
const labelSt = { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 3, marginTop: 6 };
const submitSt = { width: '100%', padding: '10px', borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer', marginTop: 10 };
