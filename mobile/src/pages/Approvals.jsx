import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const TABS = [
  { key: 'inbox', label: '결재대기' },
  { key: 'drafted', label: '내가 올린' },
  { key: 'referenced', label: '참조' },
  { key: 'done', label: '완료' },
];

const statusColor = (st) => ({
  draft: 'var(--text-muted)', pending: 'var(--warning, #d97706)',
  approved: 'var(--success, #16a34a)', rejected: 'var(--danger, #dc2626)',
  canceled: 'var(--text-muted)',
}[st] || 'var(--text-muted)');

export default function Approvals() {
  const navigate = useNavigate();
  const [tab, setTab] = useState('inbox');
  const [items, setItems] = useState([]);
  const [inbox, setInbox] = useState(0);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/approvals?tab=${tab}`)
      .then(d => { setItems(d.approvals || []); setInbox(d.inbox_count || 0); })
      .catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [tab]);

  return (
    <div>
      <div className="channel-header">
        <span className="ch-icon">📋</span>
        <h1>전자결재</h1>
        <button onClick={() => setShowForm(true)} style={s.newBtn}>✏️ 새 기안</button>
      </div>

      {/* 탭 */}
      <div style={s.tabBar}>
        {TABS.map(t => (
          <div key={t.key} onClick={() => setTab(t.key)}
               style={{ ...s.tab, ...(tab === t.key ? s.tabOn : {}) }}>
            {t.label}{t.key === 'inbox' && inbox > 0 ? ` (${inbox})` : ''}
          </div>
        ))}
      </div>

      <div className="msg-list">
        {loading ? <div className="page-loader">불러오는 중...</div>
          : items.length === 0 ? <div className="page-empty">문서가 없습니다</div>
          : items.map(d => (
            <div key={d.id} className="msg-item" onClick={() => navigate(`/approvals/${d.id}`)}
                 style={{ flexDirection: 'column', gap: 6, alignItems: 'stretch' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="indicator" style={{ background: statusColor(d.status) }} />
                <div className="msg-body" style={{ flex: 1 }}>
                  <div className="msg-top">
                    <span className="msg-date">{d.doc_no || '임시저장'} · {d.form_name}</span>
                    <span style={{ ...s.badge, color: statusColor(d.status),
                      border: `1px solid ${statusColor(d.status)}` }}>{d.status_label}</span>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-bright)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                    {d.drafter_name} {d.drafter_position} · {d.date}
                    {d.status === 'pending' && ` · ${d.approved_steps}/${d.step_count} 결재`}
                    {d.my_turn && <span style={s.turnTag}>내 차례</span>}
                  </div>
                </div>
              </div>
            </div>
          ))}
      </div>

      {showForm && <CreateModal onClose={() => setShowForm(false)} onDone={() => { setShowForm(false); setTab('drafted'); load(); }} />}
    </div>
  );
}

const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const isHoliday = (dateStr, hol) => {
  const w = new Date(dateStr + 'T00:00:00').getDay();
  return w === 0 || w === 6 || (hol && hol.has(dateStr));
};
// 시작~종료일 근무일수 (주말·공휴일 제외, 양끝 포함)
function workingDays(s, e, holidays) {
  const sd = new Date(s + 'T00:00:00'), ed = new Date((e || s) + 'T00:00:00');
  if (isNaN(sd) || isNaN(ed) || ed < sd) return 0;
  let n = 0;
  for (const d = new Date(sd); d <= ed; d.setDate(d.getDate() + 1)) {
    if (!isHoliday(iso(d), holidays)) n++;
  }
  return n;
}

function CreateModal({ onClose, onDone }) {
  const [forms, setForms] = useState([]);
  const [users, setUsers] = useState([]);
  const [balance, setBalance] = useState(null);
  const [holidays, setHolidays] = useState(null);
  const [picked, setPicked] = useState(null);   // selected form object
  const [title, setTitle] = useState('');
  const [fields, setFields] = useState({});
  const [content, setContent] = useState('');
  const [line, setLine] = useState([]);          // [{approver_id, approver_name, approver_position}]
  const [attachFiles, setAttachFiles] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get('/approvals/forms').then(d => {
      setForms(d.forms || []); setUsers(d.users || []); setBalance(d.leave_balance || null);
      setHolidays(new Set(d.holidays || []));
    }).catch(() => {});
  }, []);

  const choose = (f) => {
    setPicked(f); setTitle(''); setContent('');
    const fd = {}; (f.fields || []).forEach(x => { fd[x.key] = ''; });
    if (f.form_key === 'leave') { fd.period = '종일'; fd.leave_type = '연차'; }
    if (f.form_key === 'expense') { fd.items = [{ item: '', amount: '', payee: '' }]; }
    setFields(fd); setAttachFiles([]);
    setLine(f.default_line || []);
  };

  const isLeave = picked && picked.form_key === 'leave';
  const ff = (k) => (picked && picked.fields || []).find(f => f.key === k) || { label: k, options: [] };
  const period = fields.period || '종일';
  const isHalf = period.indexOf('반차') >= 0;
  const updateField = (key, value) => setFields({ ...fields, [key]: value });
  const setPeriod = (p) => {
    const nf = { ...fields, period: p };
    if (p.indexOf('반차') >= 0) {
      if (!nf.start_date) nf.start_date = iso(new Date());
      nf.end_date = nf.start_date;
      if (p === '오전반차') { nf.start_time = '09:00'; nf.end_time = '14:00'; }
      else { nf.start_time = '14:00'; nf.end_time = '18:00'; }
      nf.days = '0.5';
    } else {
      nf.days = nf.start_date ? String(workingDays(nf.start_date, nf.end_date || nf.start_date, holidays)) : '';
    }
    setFields(nf);
  };
  const updateLeave = (key, value) => {
    const nf = { ...fields, [key]: value };
    if (isHalf) {
      if (key === 'start_date') nf.end_date = value;
      nf.days = '0.5';
    } else {
      if (key === 'start_date' && !nf.end_date) nf.end_date = value;
      nf.days = nf.start_date ? String(workingDays(nf.start_date, nf.end_date || nf.start_date, holidays)) : '';
    }
    setFields(nf);
  };
  const returnHint = isHalf
    ? (period === '오전반차' ? `🔔 ${fields.end_time || '14:00'} 출근(복귀)` : `🔔 ${fields.start_time || '14:00'} 조퇴`)
    : '';
  const afterLeave = (isLeave && balance && parseFloat(fields.days) > 0)
    ? Math.round((balance.remaining - parseFloat(fields.days)) * 100) / 100 : null;

  // ── 지출결의서 명세 ──
  const isExpense = picked && picked.form_key === 'expense';
  const exItems = (fields.items && fields.items.length) ? fields.items : [{ item: '', amount: '', payee: '' }];
  const setExItems = (arr) => setFields({ ...fields, items: arr.length ? arr : [{ item: '', amount: '', payee: '' }] });
  const updItem = (i, k, v) => setExItems(exItems.map((r, idx) => idx === i ? { ...r, [k]: v } : r));
  const addItem = () => setExItems([...exItems, { item: '', amount: '', payee: '' }]);
  const delItem = (i) => setExItems(exItems.filter((_, idx) => idx !== i));
  const exTotal = exItems.reduce((sum, r) => sum + (parseInt((r.amount || '').toString().replace(/[^0-9-]/g, '')) || 0), 0);

  const submit = async () => {
    if (!title.trim()) return alert('제목을 입력하세요');
    for (const fl of (picked.fields || [])) {
      if (fl.type === 'lineitems') continue;
      if (fl.required && !String(fields[fl.key] || '').trim()) return alert(`${fl.label}을(를) 입력하세요`);
    }
    if (isExpense) {
      const valid = exItems.filter(r => (r.item || '').trim() || (r.amount || '').toString().trim());
      if (!valid.length) return alert('지출명세를 1건 이상 입력하세요');
    }
    if (!line.length) return alert('결재자를 1명 이상 지정하세요');
    setSaving(true);
    try {
      const res = await api.post('/approvals', {
        form_key: picked.form_key, title: title.trim(), form_data: fields, content: content.trim(),
        approver_ids: line.map(l => l.approver_id),
      });
      // 증빙 첨부 업로드 (지출결의서)
      if (attachFiles.length && res.doc_id) {
        for (const f of attachFiles) {
          const fd = new FormData(); fd.append('file', f);
          try { await api.postForm(`/approvals/${res.doc_id}/attachment`, fd); } catch (e) { /* 개별 실패 무시 */ }
        }
      }
      onDone();
    } catch (e) { alert(e.message); setSaving(false); }
  };

  const addApprover = (e) => {
    const id = parseInt(e.target.value); if (!id) return;
    const u = users.find(x => x.id === id);
    if (u && !line.find(l => l.approver_id === id))
      setLine([...line, { approver_id: u.id, approver_name: u.name, approver_position: u.position }]);
    e.target.value = '';
  };

  return (
    <div style={s.overlay}>
      <div style={s.sheet}>
        <div className="channel-header">
          <button onClick={onClose} style={s.back}>✕</button>
          <h1>{picked ? picked.name : '새 기안'}</h1>
        </div>
        <div style={{ padding: 12, overflowY: 'auto', flex: 1 }}>
          {!picked ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {forms.map(f => (
                <button key={f.form_key} onClick={() => choose(f)} style={s.formCard}>
                  <div style={{ fontSize: 26 }}>{f.icon}</div>
                  <div style={{ fontWeight: 700, marginTop: 4 }}>{f.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{f.description}</div>
                </button>
              ))}
            </div>
          ) : (
            <>
              {isLeave && balance && (
                <div style={s.balanceBox}>
                  <span>부여 <b>{balance.granted}{balance.adjust ? (balance.adjust > 0 ? `+${balance.adjust}` : balance.adjust) : ''}</b></span>
                  <span>사용 <b>{balance.used}</b></span>
                  <span>잔여 <b style={{ color: '#0284c7', fontSize: 16 }}>{balance.remaining}</b>일</span>
                  {afterLeave !== null && <span style={{ marginLeft: 'auto' }}>신청후 <b style={{ color: afterLeave < 0 ? '#dc2626' : '#0284c7' }}>{afterLeave}</b>일</span>}
                </div>
              )}
              <div style={s.fl}>제목 *</div>
              <input style={s.inp} value={title} onChange={e => setTitle(e.target.value)} placeholder="문서 제목" />

              {isLeave ? (
                <>
                  {/* 휴가종류 */}
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>{ff('leave_type').label} *</div>
                    <select style={s.inp} value={fields.leave_type || ''} onChange={e => updateField('leave_type', e.target.value)}>
                      <option value="">선택</option>
                      {(ff('leave_type').options || []).map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                  {/* 기간 세그먼트 */}
                  <div style={{ ...s.fl, marginTop: 12 }}>기간</div>
                  <div style={{ display: 'flex', gap: 0, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                    {['종일', '오전반차', '오후반차'].map(p => (
                      <button key={p} type="button" onClick={() => setPeriod(p)}
                        style={{ flex: 1, padding: '10px 0', fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none',
                          background: period === p ? 'var(--accent)' : 'transparent', color: period === p ? '#fff' : 'var(--text-muted)' }}>{p}</button>
                    ))}
                  </div>
                  {/* 날짜 */}
                  {isHalf ? (
                    <>
                      <div style={{ ...s.fl, marginTop: 10 }}>날짜 *</div>
                      <input style={s.inp} type="date" value={fields.start_date || ''} onChange={e => updateLeave('start_date', e.target.value)} />
                      <div style={{ ...s.fl, marginTop: 10 }}>휴가 시간</div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <input style={{ ...s.inp, flex: 1 }} type="time" step="600" value={fields.start_time || ''} onChange={e => updateLeave('start_time', e.target.value)} />
                        <span>~</span>
                        <input style={{ ...s.inp, flex: 1 }} type="time" step="600" value={fields.end_time || ''} onChange={e => updateLeave('end_time', e.target.value)} />
                      </div>
                      {returnHint && <div style={{ marginTop: 6, fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{returnHint}</div>}
                    </>
                  ) : (
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <div style={{ flex: 1 }}><div style={s.fl}>시작일 *</div>
                        <input style={s.inp} type="date" value={fields.start_date || ''} onChange={e => updateLeave('start_date', e.target.value)} /></div>
                      <div style={{ flex: 1 }}><div style={s.fl}>종료일</div>
                        <input style={s.inp} type="date" value={fields.end_date || ''} onChange={e => updateLeave('end_date', e.target.value)} /></div>
                    </div>
                  )}
                  {/* 사용일수 */}
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
                    <span style={s.fl}>사용일수</span>
                    <b style={{ fontSize: 18, color: 'var(--accent)' }}>{fields.days || 0}</b><span>일</span>
                    <small style={{ color: 'var(--text-muted)', marginLeft: 4 }}>자동</small>
                  </div>
                  {/* 비상연락처 / 사유 */}
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>{ff('emergency_contact').label}</div>
                    <input style={s.inp} value={fields.emergency_contact || ''} onChange={e => updateField('emergency_contact', e.target.value)} />
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>{ff('reason').label}</div>
                    <textarea style={{ ...s.inp, minHeight: 50 }} value={fields.reason || ''} onChange={e => updateField('reason', e.target.value)} />
                  </div>
                </>
              ) : isExpense ? (
                <>
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>지출일 *</div>
                    <input style={s.inp} type="date" value={fields.expense_date || ''} onChange={e => updateField('expense_date', e.target.value)} />
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>결제수단</div>
                    <select style={s.inp} value={fields.payment_method || ''} onChange={e => updateField('payment_method', e.target.value)}>
                      <option value="">선택</option>
                      {['법인카드', '계좌이체', '현금', '개인카드(환급)'].map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', marginTop: 12 }}>
                    <span style={s.fl}>지출명세 *</span>
                    <button type="button" onClick={addItem} style={{ ...s.qbtn, marginLeft: 'auto' }}>+ 항목</button>
                  </div>
                  {exItems.map((r, i) => (
                    <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, marginTop: 6 }}>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input style={{ ...s.inp, flex: 1 }} placeholder="지출항목" value={r.item || ''} onChange={e => updItem(i, 'item', e.target.value)} />
                        <button type="button" onClick={() => delItem(i)} style={{ background: 'none', border: 'none', color: 'var(--danger,#dc2626)', fontSize: 16 }}>✕</button>
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                        <input style={{ ...s.inp, flex: 1 }} type="number" placeholder="금액" value={r.amount || ''} onChange={e => updItem(i, 'amount', e.target.value)} />
                        <input style={{ ...s.inp, flex: 1 }} placeholder="사용처/거래처" value={r.payee || ''} onChange={e => updItem(i, 'payee', e.target.value)} />
                      </div>
                    </div>
                  ))}
                  <div style={{ textAlign: 'right', marginTop: 6, fontSize: 14 }}>합계 <b style={{ color: 'var(--accent)' }}>{exTotal.toLocaleString()}</b> 원</div>
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>지출사유 *</div>
                    <textarea style={{ ...s.inp, minHeight: 50 }} value={fields.reason || ''} onChange={e => updateField('reason', e.target.value)} />
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <div style={s.fl}>증빙서류 첨부</div>
                    <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.xlsx,.xls"
                      onChange={e => setAttachFiles([...e.target.files])} style={{ ...s.inp, padding: 6 }} />
                    {attachFiles.length > 0 && <small style={{ color: 'var(--text-muted)' }}>{attachFiles.length}개 선택됨</small>}
                  </div>
                </>
              ) : (picked.fields || []).map(fl => (
                <div key={fl.key} style={{ marginTop: 10 }}>
                  <div style={s.fl}>{fl.label}{fl.required ? ' *' : ''}</div>
                  {fl.type === 'textarea' ? (
                    <textarea style={{ ...s.inp, minHeight: 60 }} value={fields[fl.key] || ''}
                      onChange={e => updateField(fl.key, e.target.value)} />
                  ) : fl.type === 'select' ? (
                    <select style={s.inp} value={fields[fl.key] || ''}
                      onChange={e => updateField(fl.key, e.target.value)}>
                      <option value="">선택</option>
                      {(fl.options || []).map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input style={s.inp} type={fl.type === 'number' ? 'number' : fl.type === 'date' ? 'date' : fl.type === 'time' ? 'time' : fl.type === 'datetime' ? 'datetime-local' : 'text'}
                      value={fields[fl.key] || ''} onChange={e => updateField(fl.key, e.target.value)}
                      placeholder={fl.suffix ? `단위: ${fl.suffix}` : ''} />
                  )}
                </div>
              ))}
              <div style={{ ...s.fl, marginTop: 10 }}>본문/비고</div>
              <textarea style={{ ...s.inp, minHeight: 50 }} value={content} onChange={e => setContent(e.target.value)} />

              <div style={{ ...s.fl, marginTop: 12 }}>결재선 (순차)</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                {line.map((l, i) => (
                  <span key={l.approver_id} style={s.chip}>
                    {i + 1}. {l.approver_name} {l.approver_position}
                    <span onClick={() => setLine(line.filter(x => x.approver_id !== l.approver_id))}
                      style={{ marginLeft: 4, cursor: 'pointer' }}>✕</span>
                  </span>
                ))}
              </div>
              <select style={s.inp} onChange={addApprover} defaultValue="">
                <option value="">+ 결재자 추가</option>
                {users.map(u => <option key={u.id} value={u.id}>{u.name} {u.position} ({u.dept})</option>)}
              </select>

              <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                <button onClick={() => setPicked(null)} style={s.btn}>← 양식</button>
                <button onClick={submit} disabled={saving}
                  style={{ ...s.btn, background: 'var(--accent)', color: '#fff', flex: 2 }}>
                  {saving ? '상신 중...' : '📤 상신'}</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const s = {
  newBtn: { marginLeft: 'auto', background: 'var(--accent)', color: '#fff', border: 'none',
    borderRadius: 6, padding: '6px 10px', fontSize: 13, fontWeight: 600, cursor: 'pointer' },
  tabBar: { display: 'flex', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 1 },
  tab: { flex: 1, textAlign: 'center', padding: '10px 0', fontSize: 13, color: 'var(--text-muted)', cursor: 'pointer', borderBottom: '2px solid transparent' },
  tabOn: { color: 'var(--accent)', borderBottomColor: 'var(--accent)', fontWeight: 700 },
  badge: { fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' },
  turnTag: { marginLeft: 6, background: 'var(--danger, #dc2626)', color: '#fff', fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4 },
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 100, display: 'flex', alignItems: 'flex-end' },
  sheet: { background: 'var(--bg)', width: '100%', maxHeight: '92vh', borderRadius: '14px 14px 0 0', display: 'flex', flexDirection: 'column' },
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 18, cursor: 'pointer' },
  formCard: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, textAlign: 'center', color: 'var(--text)', cursor: 'pointer' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  balanceBox: { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', marginBottom: 12, fontSize: 13, color: 'var(--text)' },
  qbtn: { padding: '6px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: '1px solid var(--accent)', background: 'transparent', color: 'var(--accent)' },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box' },
  chip: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '4px 10px', fontSize: 12, color: 'var(--text)' },
  btn: { flex: 1, padding: 11, borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', background: 'var(--surface)', color: 'var(--text-muted)' },
};
