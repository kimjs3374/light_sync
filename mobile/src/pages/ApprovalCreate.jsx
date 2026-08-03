import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

// 반차 기본 시간대: 오전 09:00~12:00 / 오후 13:00~18:00 (12~13 점심시간 제외)
const HALF_AM = ['09:00', '12:00'];
const HALF_PM = ['13:00', '18:00'];

const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const isHoliday = (dateStr, hol) => {
  const w = new Date(dateStr + 'T00:00:00').getDay();
  return w === 0 || w === 6 || (hol && hol.has(dateStr));
};
// 특근 구분 (PC 양식과 동일)
const OT_TYPES = ['연장', '야간', '휴일'];
const OT_BLANK = { work_date: '', ot_type: '', start_time: '', end_time: '', break_hours: '', hours: '', work_content: '' };
// 시작~종료 시각 + 휴게 → 특근시간(h). 자정 넘김 처리 (PC otHours와 동일)
function otHours(start, end, brk) {
  if (!start || !end) return '';
  const [sh, sm] = start.split(':').map(Number);
  const [eh, em] = end.split(':').map(Number);
  if ([sh, sm, eh, em].some(isNaN)) return '';
  let mins = (eh * 60 + em) - (sh * 60 + sm);
  if (mins < 0) mins += 24 * 60;
  let h = mins / 60 - (parseFloat(brk) || 0);
  if (h < 0) h = 0;
  return (Math.round(h * 100) / 100).toString();
}

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

export default function ApprovalCreate() {
  const navigate = useNavigate();
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

  const goBack = () => { if (picked) setPicked(null); else navigate('/approvals'); };

  const choose = (f) => {
    setPicked(f); setTitle(''); setContent('');
    const fd = {}; (f.fields || []).forEach(x => { fd[x.key] = x.type === 'lineitems' ? [] : ''; });
    if (f.form_key === 'leave') { fd.period = '종일'; fd.leave_type = '연차'; }
    if (f.form_key === 'expense') { fd.items = [{ item: '', amount: '', payee: '' }]; }
    if (f.form_key === 'overtime') {
      const now = new Date();
      fd.work_month = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
      fd.entries = [{ ...OT_BLANK }];
    }
    setFields(fd); setAttachFiles([]);
    setLine(f.default_line || []);
  };

  // 본인 전결: 양식의 자동 결재선이 비어 있으면(= 기안자가 조직 최상위) 전결 대상
  const selfApproval = !!(picked && !(picked.default_line || []).length);
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
      if (p === '오전반차') { nf.start_time = HALF_AM[0]; nf.end_time = HALF_AM[1]; }
      else { nf.start_time = HALF_PM[0]; nf.end_time = HALF_PM[1]; }
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
    ? (period === '오전반차' ? `🔔 ${HALF_PM[0]} 출근(복귀)` : `🔔 ${fields.start_time || HALF_PM[0]} 조퇴`)
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

  // ── 특근대장 내역 (PC 특근대장 양식과 동일 항목) ──
  const isOvertime = picked && picked.form_key === 'overtime';
  const otRows = (Array.isArray(fields.entries) && fields.entries.length) ? fields.entries : [{ ...OT_BLANK }];
  const setOtRows = (arr) => setFields({ ...fields, entries: arr.length ? arr : [{ ...OT_BLANK }] });
  const updOt = (i, k, v) => setOtRows(otRows.map((r, idx) => {
    if (idx !== i) return r;
    const nr = { ...r, [k]: v };
    // 시작·종료·휴게 변경 시 특근시간 자동 계산 (직접 수정도 가능)
    if (k === 'start_time' || k === 'end_time' || k === 'break_hours') {
      const h = otHours(nr.start_time, nr.end_time, nr.break_hours);
      if (h !== '') nr.hours = h;
    }
    return nr;
  }));
  const addOt = () => setOtRows([...otRows, { ...OT_BLANK }]);
  const delOt = (i) => setOtRows(otRows.filter((_, idx) => idx !== i));
  const otTotal = otRows.reduce((sum, r) => sum + (parseFloat(r.hours) || 0), 0);
  // 값이 하나라도 들어간 행 = 사용자가 쓴 행. 그 중 근무일자·특근시간이 빠진 행은 상신 차단
  const otFilled = otRows.filter(r => Object.values(r).some(v => String(v || '').trim()));
  const otBad = otFilled.filter(r => !(r.work_date || '').trim() || !((parseFloat(r.hours) || 0) > 0));

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
    if (isOvertime) {
      if (!(fields.work_month || '').trim()) return alert('대상월을 선택하세요');
      if (!otFilled.length) return alert('특근내역을 1건 이상 입력하세요');
      if (otBad.length) return alert('특근내역에 근무일자와 특근시간을 입력하세요');
    }
    if (!line.length) {
      if (!selfApproval) return alert('결재자를 1명 이상 지정하세요');
      if (!confirm('상위 결재자가 없어 본인 전결로 즉시 완료됩니다. 상신할까요?')) return;
    }
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
      navigate('/approvals');
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
    <div>
      <div className="channel-header">
        <button onClick={goBack} style={s.back}>‹</button>
        <h1>{picked ? picked.name : '새 기안'}</h1>
      </div>
      {/* 하단 고정 네비에 상신 버튼이 가려지지 않도록 여백 확보 (다른 작성화면과 동일) */}
      <div style={{ padding: 12, paddingBottom: 80 }}>
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
            ) : isOvertime ? (
              <>
                <div style={{ marginTop: 10 }}>
                  <div style={s.fl}>대상월 *</div>
                  <input style={s.inp} type="month" value={fields.work_month || ''}
                    onChange={e => updateField('work_month', e.target.value)} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginTop: 12 }}>
                  <span style={s.fl}>특근내역 *</span>
                  <button type="button" onClick={addOt} style={{ ...s.qbtn, marginLeft: 'auto' }}>+ 날짜</button>
                </div>
                {otRows.map((r, i) => (
                  <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, marginTop: 6 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <input style={{ ...s.inp, flex: 1 }} type="date" value={r.work_date || ''}
                        onChange={e => updOt(i, 'work_date', e.target.value)} />
                      <select style={{ ...s.inp, width: 90 }} value={r.ot_type || ''}
                        onChange={e => updOt(i, 'ot_type', e.target.value)}>
                        <option value="">구분</option>
                        {OT_TYPES.map(o => <option key={o} value={o}>{o}</option>)}
                      </select>
                      <button type="button" onClick={() => delOt(i)}
                        style={{ background: 'none', border: 'none', color: 'var(--danger,#dc2626)', fontSize: 16 }}>✕</button>
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
                      <input style={{ ...s.inp, flex: 1 }} type="time" value={r.start_time || ''}
                        onChange={e => updOt(i, 'start_time', e.target.value)} />
                      <span style={{ color: 'var(--text-muted)' }}>~</span>
                      <input style={{ ...s.inp, flex: 1 }} type="time" value={r.end_time || ''}
                        onChange={e => updOt(i, 'end_time', e.target.value)} />
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
                      <input style={{ ...s.inp, flex: 1 }} type="number" step="0.5" min="0" placeholder="휴게(h)"
                        value={r.break_hours || ''} onChange={e => updOt(i, 'break_hours', e.target.value)} />
                      <input style={{ ...s.inp, flex: 1 }} type="number" step="0.5" min="0" placeholder="특근시간(h)"
                        value={r.hours || ''} onChange={e => updOt(i, 'hours', e.target.value)} />
                    </div>
                    <input style={{ ...s.inp, marginTop: 6 }} placeholder="업무내용"
                      value={r.work_content || ''} onChange={e => updOt(i, 'work_content', e.target.value)} />
                  </div>
                ))}
                <div style={{ textAlign: 'right', marginTop: 6, fontSize: 14 }}>
                  월 합계 <b style={{ color: 'var(--accent)' }}>{Math.round(otTotal * 100) / 100}</b> h
                </div>
                <small style={{ color: 'var(--text-muted)' }}>시작·종료·휴게를 입력하면 특근시간이 자동 계산됩니다.</small>
                <div style={{ marginTop: 10 }}>
                  <div style={s.fl}>비고</div>
                  <textarea style={{ ...s.inp, minHeight: 50 }} value={fields.reason || ''}
                    onChange={e => updateField('reason', e.target.value)} />
                </div>
              </>
            ) : (picked.fields || []).map(fl => (
              <div key={fl.key} style={{ marginTop: 10 }}>
                <div style={s.fl}>{fl.label}{fl.required ? ' *' : ''}</div>
                {fl.type === 'lineitems' ? (
                  // 다건 입력 전용 UI가 없는 양식 — 텍스트로 받으면 데이터가 깨지므로 입력 자체를 막는다
                  <div style={{ ...s.inp, color: 'var(--text-muted)', fontSize: 12 }}>
                    이 항목은 PC ERP에서 입력하세요
                  </div>
                ) : fl.type === 'textarea' ? (
                  <textarea style={{ ...s.inp, minHeight: 60 }} value={fields[fl.key] || ''}
                    onChange={e => updateField(fl.key, e.target.value)} />
                ) : fl.type === 'select' ? (
                  <select style={s.inp} value={fields[fl.key] || ''}
                    onChange={e => updateField(fl.key, e.target.value)}>
                    <option value="">선택</option>
                    {(fl.options || []).map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input style={s.inp} type={fl.type === 'number' ? 'number' : fl.type === 'date' ? 'date' : fl.type === 'time' ? 'time' : fl.type === 'month' ? 'month' : fl.type === 'datetime' ? 'datetime-local' : 'text'}
                    value={fields[fl.key] || ''} onChange={e => updateField(fl.key, e.target.value)}
                    placeholder={fl.suffix ? `단위: ${fl.suffix}` : ''} />
                )}
              </div>
            ))}
            <div style={{ ...s.fl, marginTop: 10 }}>본문/비고</div>
            <textarea style={{ ...s.inp, minHeight: 50 }} value={content} onChange={e => setContent(e.target.value)} />

            <div style={{ ...s.fl, marginTop: 12 }}>결재선 (순차)</div>
            {selfApproval && !line.length && (
              <div style={{ background: 'var(--surface)', border: '1px solid var(--accent)', borderRadius: 8,
                padding: '8px 12px', marginBottom: 6, fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
                🟢 본인 전결 — 상위 결재자가 없어 상신 시 즉시 완료됩니다
              </div>
            )}
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

            {(picked.default_refs || []).length > 0 && (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                참조 (자동): {(picked.default_refs || []).map(r => `${r.name} ${r.position}`).join(', ')}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button onClick={() => setPicked(null)} style={s.btn}>← 양식</button>
              <button onClick={submit} disabled={saving}
                style={{ ...s.btn, background: 'var(--accent)', color: '#fff', flex: 2 }}>
                {saving ? '상신 중...' : (selfApproval && !line.length ? '🟢 전결 상신' : '📤 상신')}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 26, lineHeight: 1, cursor: 'pointer', marginRight: 4 },
  formCard: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, textAlign: 'center', color: 'var(--text)', cursor: 'pointer' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  balanceBox: { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', marginBottom: 12, fontSize: 13, color: 'var(--text)' },
  qbtn: { padding: '6px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: '1px solid var(--accent)', background: 'transparent', color: 'var(--accent)' },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box' },
  chip: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '4px 10px', fontSize: 12, color: 'var(--text)' },
  btn: { flex: 1, padding: 11, borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', background: 'var(--surface)', color: 'var(--text-muted)' },
};
