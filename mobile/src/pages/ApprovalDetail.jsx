import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const stColor = (st) => ({
  approved: 'var(--success, #16a34a)', rejected: 'var(--danger, #dc2626)',
  current: 'var(--accent)', pending: 'var(--warning, #d97706)',
}[st] || 'var(--text-muted)');

export default function ApprovalDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.get(`/approvals/${id}`).then(d => setDoc(d.doc)).catch(e => alert(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const act = async (kind) => {
    if (kind === 'reject' && !comment.trim()) return alert('반려 사유를 입력하세요');
    if (kind === 'cancel' && !confirm('상신을 회수하시겠습니까?')) return;
    setBusy(true);
    try {
      await api.post(`/approvals/${id}/${kind}`, { comment: comment.trim() });
      load(); setComment('');
    } catch (e) { alert(e.message); } finally { setBusy(false); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!doc) return <div className="page-empty">문서를 찾을 수 없습니다</div>;

  return (
    <div>
      <div className="channel-header">
        <button onClick={() => navigate('/approvals')} style={s.back}>←</button>
        <h1 style={{ fontSize: 16, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.title}</h1>
        <span style={{ ...s.badge, color: stColor(doc.status), border: `1px solid ${stColor(doc.status)}`, marginLeft: 'auto' }}>{doc.status_label}</span>
      </div>

      <div style={{ padding: 14 }}>
        <div style={s.meta}>{doc.doc_no} · {doc.form_name}</div>
        <div style={s.meta}>기안 {doc.drafter_name} {doc.drafter_position} ({doc.drafter_dept}) · {doc.date}</div>

        {/* 결재 도장 */}
        <div style={s.stampRow}>
          <div style={s.stampCell}>
            <div style={s.stampHd}>기안</div>
            <div style={s.stampBody}><b>{doc.drafter_name}</b></div>
          </div>
          {doc.steps.map(st => (
            <div key={st.order} style={s.stampCell}>
              <div style={s.stampHd}>{st.role}</div>
              <div style={s.stampBody}>
                <b style={{ color: stColor(st.status) }}>{st.name}</b>
                <div style={{ fontSize: 9, color: stColor(st.status) }}>{st.status_label}</div>
              </div>
            </div>
          ))}
        </div>

        {/* 내용 */}
        <div style={s.section}>
          {doc.fields.map((f, i) => f.type === 'lineitems' ? (
            <div key={i} style={{ ...s.row, flexDirection: 'column', gap: 6, alignItems: 'stretch' }}>
              <div style={s.rowL}>{f.label}</div>
              <div>
                {(f.rows || []).map((r, ri) => (
                  <div key={ri} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
                    <span>
                      {r.item || '-'}{r.payee ? ` · ${r.payee}` : ''}
                      {(r.bank || r.account_no) && (
                        <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>
                          {[r.bank, r.account_no].filter(Boolean).join(' ')}
                        </div>
                      )}
                    </span>
                    <b>{r.amount ? Number(String(r.amount).replace(/[^0-9-]/g, '')).toLocaleString() : '-'}</b>
                  </div>
                ))}
                {doc.amount != null && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 6, fontWeight: 700, color: 'var(--accent)' }}>
                    <span>합계</span><span>{doc.amount.toLocaleString()} 원</span>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div key={i} style={s.row}>
              <div style={s.rowL}>{f.label}</div>
              <div style={s.rowV}>{f.value || '-'}{f.value && f.suffix ? ` ${f.suffix}` : ''}</div>
            </div>
          ))}
          {doc.content && <div style={{ ...s.row, flexDirection: 'column', gap: 4 }}>
            <div style={s.rowL}>본문/비고</div>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{doc.content}</div>
          </div>}
        </div>

        {doc.attachments && doc.attachments.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 13 }}>
            <div style={{ ...s.rowL, marginBottom: 4 }}>첨부 증빙</div>
            {doc.attachments.map(a => <div key={a.id} style={{ padding: '3px 0' }}>📎 {a.name}</div>)}
          </div>
        )}

        {doc.references.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
            참조/수신: {doc.references.map(r => `${r.type}·${r.name}`).join(', ')}
          </div>
        )}

        {/* 진행 이력 */}
        <div style={{ ...s.secTitle, marginTop: 16 }}>결재 진행</div>
        {doc.steps.map(st => (
          <div key={st.order} style={s.prog}>
            <span>{st.order}. {st.name} {st.position} {st.comment ? `— ${st.comment}` : ''}</span>
            <span style={{ color: stColor(st.status), fontWeight: 600 }}>{st.status_label} {st.acted_at}</span>
          </div>
        ))}

        {/* 액션 */}
        {(doc.my_turn || doc.can_cancel) && (
          <div style={{ marginTop: 16 }}>
            {doc.my_turn && (
              <>
                <textarea style={s.inp} placeholder="의견 (반려 시 필수)" value={comment}
                  onChange={e => setComment(e.target.value)} />
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button onClick={() => act('approve')} disabled={busy}
                    style={{ ...s.actBtn, background: 'var(--success, #16a34a)', color: '#fff' }}>✅ 승인</button>
                  <button onClick={() => act('reject')} disabled={busy}
                    style={{ ...s.actBtn, background: 'var(--danger, #dc2626)', color: '#fff' }}>⛔ 반려</button>
                </div>
              </>
            )}
            {doc.can_cancel && (
              <button onClick={() => act('cancel')} disabled={busy}
                style={{ ...s.actBtn, width: '100%', marginTop: 8, background: 'var(--surface)', color: 'var(--text-muted)' }}>↩️ 회수</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 20, cursor: 'pointer' },
  badge: { fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, whiteSpace: 'nowrap' },
  meta: { fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 },
  stampRow: { display: 'flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', margin: '12px 0' },
  stampCell: { flex: 1, borderRight: '1px solid var(--border)', textAlign: 'center' },
  stampHd: { fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', background: 'var(--surface)', padding: 3, borderBottom: '1px solid var(--border)' },
  stampBody: { padding: '8px 2px', fontSize: 12, color: 'var(--text)' },
  section: { marginTop: 12, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' },
  row: { display: 'flex', borderBottom: '1px solid var(--border)', padding: '8px 10px' },
  rowL: { width: 110, fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 },
  rowV: { fontSize: 13, color: 'var(--text)' },
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  prog: { display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '6px 0', borderBottom: '1px solid var(--border)', gap: 8 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box', minHeight: 54 },
  actBtn: { flex: 1, padding: 12, borderRadius: 6, fontSize: 14, fontWeight: 700, cursor: 'pointer', border: 'none' },
};
