import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_CHOICES = ['작성중', '발주완료', '가공중', '입고완료', '취소'];
const STATUS_COLORS = {
  '작성중': 'orange',
  '발주완료': 'blue',
  '가공중': 'purple',
  '입고완료': 'green',
  '취소': 'gray',
};
const TYPE_CHOICES = ['사급가공', '외주가공'];
const money = (v) => Math.round(Number(v) || 0).toLocaleString();

const API_BASE = '/api/app';

export default function ProcessingOrderDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [viewFile, setViewFile] = useState(null);
  const [showEdit, setShowEdit] = useState(false);
  const [showEmail, setShowEmail] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/processing-orders/${id}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data || !data.fo) return <div className="page-loader">가공발주를 찾을 수 없습니다</div>;

  const fo = data.fo;
  const items = data.items || [];
  const files = data.files || [];
  const history = data.history || [];

  const token = localStorage.getItem('token');
  const fileUrl = (fid, thumb) =>
    `${API_BASE}/processing-orders/files/${fid}/view?_t=${encodeURIComponent(token)}${thumb ? '&thumb=1' : ''}`;

  const isDraft = fo.status === '작성중';
  const refImages = files.filter(f => f.is_reference && ['jpg', 'jpeg', 'png', 'pdf'].includes((f.file_type || '').toLowerCase()));
  const imgFiles = files.filter(f => f.is_image);
  const nonImageFiles = files.filter(f => !f.is_image);

  const grandTotal = (Number(fo.total_amount) || 0) + (Number(fo.tax_amount) || 0);

  const changeStatus = async (status) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post(`/processing-orders/${id}/status`, { status });
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const confirmItem = async (itemId) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post(`/processing-orders/${id}/confirm-item/${itemId}`, {});
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const toggleReference = async (fid) => {
    try {
      await api.post(`/processing-orders/${id}/file/${fid}/toggle-reference`, {});
      load();
    } catch (e) { alert(e.message); }
  };

  const deleteFile = async (fid) => {
    if (!confirm('이 파일을 삭제하시겠습니까?')) return;
    try {
      await api.post(`/processing-orders/${id}/file/${fid}/delete`, {});
      load();
    } catch (e) { alert(e.message); }
  };

  const uploadFiles = async (fileList) => {
    if (!fileList || !fileList.length) return;
    setBusy(true);
    try {
      const fd = new FormData();
      for (let i = 0; i < fileList.length; i++) fd.append('files', fileList[i]);
      const res = await fetch(`${API_BASE}/processing-orders/${id}/upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: fd,
      });
      const j = await res.json();
      if (!res.ok || j.ok === false) throw new Error(j.error || '업로드 실패');
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const syncProduction = async () => {
    setBusy(true);
    try {
      await api.post(`/processing-orders/${id}/sync-production`, {});
      alert('생산관리 연동 완료');
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const deleteFo = async () => {
    if (!confirm(`가공발주 ${fo.fo_no}를 삭제하시겠습니까?\n첨부파일도 함께 삭제됩니다.`)) return;
    try {
      await api.post(`/processing-orders/${id}/delete`, {});
      nav('/processing-orders');
    } catch (e) { alert(e.message); }
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      {/* ── 이미지 뷰어 ── */}
      {viewFile && (
        <div onClick={() => setViewFile(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.9)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 16,
          }}>
          {['jpg', 'jpeg', 'png'].includes((viewFile.file_type || '').toLowerCase()) ? (
            <img src={fileUrl(viewFile.id, false)} alt={viewFile.file_name}
              onClick={e => e.stopPropagation()}
              style={{ maxWidth: '95vw', maxHeight: '80vh', objectFit: 'contain', borderRadius: 8 }} />
          ) : (
            <iframe src={fileUrl(viewFile.id, false)} title={viewFile.file_name}
              onClick={e => e.stopPropagation()}
              style={{ width: '95vw', height: '80vh', border: 'none', background: '#fff', borderRadius: 8 }} />
          )}
          <div style={{ color: '#fff', marginTop: 12, fontSize: 13 }}>{viewFile.file_name}</div>
        </div>
      )}

      {/* ── 수정 모달 ── */}
      {showEdit && (
        <EditModal fo={fo} items={items} onClose={() => setShowEdit(false)} onSaved={() => { setShowEdit(false); load(); }} />
      )}

      {/* ── 이메일 모달 ── */}
      {showEmail && (
        <EmailModal foId={id} onClose={() => setShowEmail(false)} onSent={() => { setShowEmail(false); load(); }} />
      )}

      {/* ── 헤더 ── */}
      <div className="channel-header">
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1 style={{ fontSize: 14, fontFamily: 'monospace' }}>{fo.fo_no}</h1>
        <span className={`badge badge-${STATUS_COLORS[fo.status] || 'gray'}`}>{fo.status}</span>
      </div>

      {/* ── 상태 변경 ── */}
      <Section title="발주 상태">
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {STATUS_CHOICES.map(s => (
            <button key={s} onClick={() => changeStatus(s)} disabled={busy}
              style={{
                flex: '1 1 auto', minWidth: 60, padding: '7px 10px', borderRadius: 4,
                fontSize: 11, fontWeight: 600, cursor: 'pointer', border: 'none',
                background: fo.status === s ? `var(--${STATUS_COLORS[s] || 'gray'})` : 'var(--surface)',
                color: fo.status === s ? '#fff' : 'var(--text-muted)',
              }}>
              {s}
            </button>
          ))}
        </div>
      </Section>

      {/* ── 액션 버튼 ── */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {fo.vendor_email && (
          <button onClick={() => setShowEmail(true)} disabled={busy} style={btnStyle('var(--green)', '#fff')}>
            이메일 발송
          </button>
        )}
        {fo.contract_id && (
          <button onClick={syncProduction} disabled={busy} style={btnStyle('var(--accent)', '#fff')}>
            생산관리 연동
          </button>
        )}
        {isDraft && (
          <button onClick={() => setShowEdit(true)} style={btnStyle('var(--surface)', 'var(--text-bright)')}>수정</button>
        )}
        <button onClick={deleteFo} style={btnStyle('rgba(242,63,67,0.15)', 'var(--red)')}>삭제</button>
      </div>

      {/* ── 발주 정보 ── */}
      <Section title="가공발주 정보">
        <Row label="발주번호" value={fo.fo_no} mono />
        <Row label="발주일" value={fo.fo_date} />
        <Row label="가공업체" value={fo.vendor_name} />
        <Row label="가공유형" value={fo.processing_type}
          badge={fo.processing_type === '사급가공' ? 'orange' : 'purple'} />
        <Row label="담당자" value={fo.assignee_name} />
        <Row label="현장/계약" value={fo.contract_name || fo.project_name} />
        {fo.vendor_email && <Row label="업체이메일" value={fo.vendor_email} />}
        {fo.note && <Row label="비고" value={fo.note} />}
      </Section>

      {/* ── 금액 ── */}
      <Section title="금액 요약">
        <AmountRow label="공급가액" value={money(fo.total_amount)} />
        <AmountRow label="부가세 10%" value={money(fo.tax_amount)} />
        <AmountRow label="합계" value={money(grandTotal)} total />
      </Section>

      {/* ── 품목 ── */}
      <Section title={`가공 품목 (${items.length})`}>
        {items.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>품목이 없습니다</div>
        ) : items.map((it, idx) => (
          <div key={it.id} style={{ padding: '8px 0', borderTop: idx === 0 ? 'none' : '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>
                  <span style={{ color: 'var(--text-muted)', marginRight: 6 }}>#{idx + 1}</span>
                  {it.item_name}
                </div>
                {it.item_spec && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{it.item_spec}</div>}
                {it.processing_note && <div style={{ fontSize: 10, color: 'var(--orange)', marginTop: 2 }}>메모: {it.processing_note}</div>}
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>{money(it.amount)}원</div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 4, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
              <span>{it.quantity || 0} {it.unit || ''}</span>
              <span>@{Number(it.unit_price || 0).toLocaleString()}</span>
              {it.delivery_date && (
                it.in_confirmed
                  ? <span style={{ color: 'var(--green)', textDecoration: 'line-through' }}>납기 {it.delivery_date} ✓</span>
                  : <span>납기 {it.delivery_date}</span>
              )}
            </div>
            <div style={{ marginTop: 6 }}>
              {it.in_confirmed ? (
                <button onClick={() => confirmItem(it.id)} disabled={busy}
                  style={{ ...actionBtn, background: 'rgba(45,199,112,0.15)', color: 'var(--green)' }}>
                  ✓ 입고확인됨 {it.in_confirmed_at ? `(${it.in_confirmed_at})` : ''} · 취소
                </button>
              ) : (
                <button onClick={() => confirmItem(it.id)} disabled={busy}
                  style={{ ...actionBtn, background: 'var(--green)', color: '#fff' }}>
                  입고확인
                </button>
              )}
            </div>
          </div>
        ))}
      </Section>

      {/* ── 도면 참고 갤러리 ── */}
      {refImages.length > 0 && (
        <Section title={`도면 참고 (${refImages.length})`}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
            {refImages.map(f => (
              <div key={f.id} onClick={() => setViewFile(f)}
                style={{
                  aspectRatio: '1', borderRadius: 6, overflow: 'hidden', cursor: 'pointer',
                  background: 'var(--surface)', position: 'relative',
                }}>
                {['jpg', 'jpeg', 'png'].includes((f.file_type || '').toLowerCase()) ? (
                  <img src={fileUrl(f.id, true)} alt={f.file_name} loading="lazy"
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                ) : (
                  <div style={{
                    width: '100%', height: '100%', display: 'flex', alignItems: 'center',
                    justifyContent: 'center', fontSize: 10, color: 'var(--text-muted)', padding: 4, textAlign: 'center',
                  }}>PDF<br />{(f.file_name || '').slice(0, 12)}</div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── 첨부 파일 ── */}
      <Section
        title={`도면/파일 (${files.length})`}
        action={
          <label style={{ ...btnStyle('var(--accent)', '#fff'), fontSize: 11, cursor: 'pointer' }}>
            + 업로드
            <input type="file" multiple accept=".dwg,.dxf,.pdf,.jpg,.jpeg,.png,.zip"
              onChange={(e) => { uploadFiles(e.target.files); e.target.value = ''; }}
              style={{ display: 'none' }} />
          </label>
        }
      >
        {files.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>첨부된 파일이 없습니다</div>
        ) : files.map(f => {
          const icon = ['dwg', 'dxf'].includes((f.file_type || '').toLowerCase()) ? '📐'
            : (f.file_type || '').toLowerCase() === 'pdf' ? '📄'
            : ['jpg', 'jpeg', 'png'].includes((f.file_type || '').toLowerCase()) ? '🖼️'
            : '📦';
          const previewable = ['pdf', 'jpg', 'jpeg', 'png'].includes((f.file_type || '').toLowerCase());
          return (
            <div key={f.id} style={{
              padding: '8px 6px', borderTop: '1px solid var(--border)',
              background: f.is_reference ? 'rgba(240,160,32,0.06)' : 'transparent',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 16 }}>{icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {f.file_name}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    {(f.file_size / 1024 / 1024).toFixed(1)}MB
                    {f.uploaded_at ? ` · ${f.uploaded_at.slice(5, 16)}` : ''}
                    {f.is_reference && <span className="badge badge-orange" style={{ marginLeft: 6 }}>참고용</span>}
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {previewable && (
                  <button onClick={() => setViewFile(f)} style={{ ...actionBtn, background: 'var(--surface)', color: 'var(--text-bright)' }}>
                    보기
                  </button>
                )}
                <a href={fileUrl(f.id, false)} download={f.file_name}
                  style={{ ...actionBtn, background: 'var(--surface)', color: 'var(--accent)', textDecoration: 'none' }}>
                  다운로드
                </a>
                <button onClick={() => toggleReference(f.id)}
                  style={{ ...actionBtn, background: f.is_reference ? 'var(--orange)' : 'var(--surface)', color: f.is_reference ? '#fff' : 'var(--orange)' }}>
                  {f.is_reference ? '참고용 해제' : '참고용'}
                </button>
                <button onClick={() => deleteFile(f.id)}
                  style={{ ...actionBtn, background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>
                  삭제
                </button>
              </div>
            </div>
          );
        })}
      </Section>

      {/* ── 변경 이력 ── */}
      {history.length > 0 && (
        <Section title={`변경 이력 (${history.length})`}>
          {[...history].reverse().map((log, i) => (
            <div key={i} style={{ padding: '6px 0', borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {log.time} · {log.user || '-'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-bright)', marginTop: 2 }}>{log.text}</div>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

/* ── Edit Modal ── */
function EditModal({ fo, items, onClose, onSaved }) {
  const [foDate, setFoDate] = useState(fo.fo_date || '');
  const [processingType, setProcessingType] = useState(fo.processing_type || '외주가공');
  const [note, setNote] = useState(fo.note || '');
  const [list, setList] = useState(items.map(it => ({
    item_id: it.item_id || null,
    item_name: it.item_name || '',
    item_spec: it.item_spec || '',
    quantity: it.quantity || '',
    unit: it.unit || 'EA',
    unit_price: it.unit_price || '',
    delivery_date: it.delivery_date || '',
    processing_note: it.processing_note || '',
    note: it.note || '',
  })));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const add = () => setList([...list, { item_name: '', item_spec: '', quantity: '', unit: 'EA', unit_price: '', delivery_date: '', processing_note: '', note: '', item_id: null }]);
  const upd = (i, k, v) => setList(list.map((it, idx) => idx === i ? { ...it, [k]: v } : it));
  const del = (i) => setList(list.filter((_, idx) => idx !== i));

  const total = useMemo(() =>
    list.reduce((s, it) => s + (parseFloat(it.quantity) || 0) * (parseFloat(it.unit_price) || 0), 0),
    [list]);

  const submit = async () => {
    setErr('');
    const real = list.filter(it => (it.item_name || '').trim());
    if (real.length === 0) { setErr('품목을 1개 이상 입력해주세요'); return; }
    setSaving(true);
    try {
      await api.post(`/processing-orders/${fo.id}/edit`, {
        fo_date: foDate,
        processing_type: processingType,
        note,
        items: real.map(it => ({
          ...it,
          quantity: parseFloat(it.quantity) || 0,
          unit_price: parseFloat(it.unit_price) || 0,
        })),
      });
      onSaved();
    } catch (e) { setErr(e.message); setSaving(false); }
  };

  return (
    <div style={modalBack} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={modalHeader}>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-bright)' }}>가공발주 수정</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 18, color: 'var(--text-muted)', cursor: 'pointer' }}>×</button>
        </div>
        <div style={modalBody}>
          {err && <div style={errorBox}>{err}</div>}
          <label style={lbl}>발주일</label>
          <input type="date" value={foDate} onChange={e => setFoDate(e.target.value)} style={inp} />
          <label style={lbl}>가공유형</label>
          <div style={{ display: 'flex', gap: 8 }}>
            {TYPE_CHOICES.map(t => (
              <label key={t} style={{ flex: 1, padding: '8px', borderRadius: 6, background: processingType === t ? 'var(--accent)' : 'var(--surface)', color: processingType === t ? '#fff' : 'var(--text)', fontSize: 12, textAlign: 'center', cursor: 'pointer', fontWeight: 600 }}>
                <input type="radio" checked={processingType === t} onChange={() => setProcessingType(t)} style={{ display: 'none' }} />
                {t}
              </label>
            ))}
          </div>
          <label style={lbl}>비고</label>
          <input value={note} onChange={e => setNote(e.target.value)} style={inp} />

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '14px 0 6px' }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-bright)' }}>가공 품목</span>
            <button onClick={add} style={{ ...actionBtn, background: 'var(--accent)', color: '#fff' }}>+ 추가</button>
          </div>
          {list.map((it, i) => (
            <div key={i} style={{ padding: 8, borderRadius: 6, background: 'var(--surface)', marginBottom: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>#{i + 1}</span>
                {list.length > 1 && (
                  <button onClick={() => del(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 11, cursor: 'pointer' }}>삭제</button>
                )}
              </div>
              <input placeholder="품명 *" value={it.item_name} onChange={e => upd(i, 'item_name', e.target.value)} style={{ ...inp, marginBottom: 4 }} />
              <input placeholder="규격" value={it.item_spec} onChange={e => upd(i, 'item_spec', e.target.value)} style={{ ...inp, marginBottom: 4 }} />
              <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                <input placeholder="수량" type="number" step="any" value={it.quantity} onChange={e => upd(i, 'quantity', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
                <input placeholder="단위" value={it.unit} onChange={e => upd(i, 'unit', e.target.value)} style={{ ...inp, width: 60, textAlign: 'center' }} />
                <input placeholder="단가" type="number" step="any" value={it.unit_price} onChange={e => upd(i, 'unit_price', e.target.value)} style={{ ...inp, flex: 1, textAlign: 'right' }} />
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                <input type="date" value={it.delivery_date} onChange={e => upd(i, 'delivery_date', e.target.value)} style={{ ...inp, flex: 1 }} />
                <input placeholder="가공메모" value={it.processing_note} onChange={e => upd(i, 'processing_note', e.target.value)} style={{ ...inp, flex: 1 }} />
              </div>
            </div>
          ))}
          <div style={{ marginTop: 10, padding: '8px 10px', background: 'var(--surface)', borderRadius: 6, display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>합계(공급가)</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>{money(total)}원</span>
          </div>
        </div>
        <div style={modalFooter}>
          <button onClick={onClose} style={btnStyle('var(--surface)', 'var(--text-muted)')}>취소</button>
          <button onClick={submit} disabled={saving} style={btnStyle('var(--accent)', '#fff')}>
            {saving ? '저장중...' : '저장'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Email Modal ── */
function EmailModal({ foId, onClose, onSent }) {
  const [preview, setPreview] = useState(null);
  const [to, setTo] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    api.get(`/processing-orders/${foId}/email-preview`)
      .then(d => {
        setPreview(d);
        setTo(d.to || '');
        setSubject(d.subject || '');
        setBody(d.body || '');
      })
      .catch(e => setErr(e.message));
  }, [foId]);

  const submit = async () => {
    if (!confirm('이메일을 발송하시겠습니까?')) return;
    setErr('');
    setSending(true);
    try {
      await api.post(`/processing-orders/${foId}/send-email`, {
        email_to: to, email_subject: subject, email_body: body,
      });
      alert('이메일 발송 완료');
      onSent();
    } catch (e) { setErr(e.message); setSending(false); }
  };

  return (
    <div style={modalBack} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ ...modalHeader, background: 'rgba(45,199,112,0.1)' }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--green)' }}>이메일 미리보기</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 18, color: 'var(--text-muted)', cursor: 'pointer' }}>×</button>
        </div>
        <div style={modalBody}>
          {err && <div style={errorBox}>{err}</div>}
          {!preview ? <div className="page-loader">불러오는 중...</div> : (
            <>
              <label style={lbl}>수신자</label>
              <input type="email" value={to} onChange={e => setTo(e.target.value)} style={inp} />
              <label style={lbl}>업체명</label>
              <input value={preview.vendor_name || ''} disabled style={{ ...inp, opacity: 0.6 }} />
              <label style={lbl}>제목</label>
              <input value={subject} onChange={e => setSubject(e.target.value)} style={inp} />
              <label style={lbl}>본문 (수정 가능)</label>
              <textarea value={body} onChange={e => setBody(e.target.value)} rows={14}
                style={{ ...inp, resize: 'vertical', fontFamily: 'monospace', fontSize: 12, lineHeight: 1.5 }} />
              {preview.files && preview.files.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)' }}>
                  첨부파일 ({preview.files.length}):
                  <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {preview.files.map((fn, i) => (
                      <span key={i} className="badge badge-gray" style={{ fontSize: 10 }}>{fn}</span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
        <div style={modalFooter}>
          <button onClick={onClose} style={btnStyle('var(--surface)', 'var(--text-muted)')}>취소</button>
          <button onClick={submit} disabled={sending || !preview} style={btnStyle('var(--green)', '#fff')}>
            {sending ? '발송중...' : '발송'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── helpers ── */
function Section({ title, action, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{title}</div>
        {action}
      </div>
      {children}
    </div>
  );
}
function Row({ label, value, mono, badge }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', gap: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      {badge ? (
        <span className={`badge badge-${badge}`}>{value}</span>
      ) : (
        <span style={{ fontSize: 12, color: 'var(--text-bright)', fontFamily: mono ? 'monospace' : undefined, textAlign: 'right', maxWidth: '65%', wordBreak: 'break-all' }}>{value}</span>
      )}
    </div>
  );
}
function AmountRow({ label, value, total }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', padding: '6px 0',
      borderTop: total ? '2px solid var(--text-bright)' : '1px solid var(--border)',
      marginTop: total ? 4 : 0,
    }}>
      <span style={{ fontSize: total ? 13 : 12, color: 'var(--text-muted)', fontWeight: total ? 700 : 400 }}>{label}</span>
      <span style={{ fontSize: total ? 15 : 12, color: total ? 'var(--accent)' : 'var(--text-bright)', fontFamily: 'monospace', fontWeight: total ? 700 : 500 }}>
        {value}원
      </span>
    </div>
  );
}
const btnStyle = (bg, color) => ({
  padding: '7px 12px', borderRadius: 4, fontSize: 12, fontWeight: 600,
  border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
  background: bg, color, display: 'inline-flex', alignItems: 'center',
});
const actionBtn = {
  padding: '4px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
  border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
};
const inp = {
  width: '100%', padding: '8px 10px', borderRadius: 6,
  background: 'var(--bg)', border: '1px solid var(--border)',
  color: 'var(--text)', fontSize: 13, marginBottom: 6,
};
const lbl = { display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 3, marginTop: 4 };
const modalBack = {
  position: 'fixed', inset: 0, zIndex: 300, background: 'rgba(0,0,0,0.7)',
  display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
};
const modalBox = {
  width: '100%', maxWidth: 520, maxHeight: '95vh',
  background: 'var(--bg-secondary)', borderRadius: '12px 12px 0 0',
  display: 'flex', flexDirection: 'column', overflow: 'hidden',
};
const modalHeader = {
  padding: '12px 16px', borderBottom: '1px solid var(--border)',
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  background: 'var(--surface)',
};
const modalBody = { padding: 16, overflowY: 'auto', flex: 1 };
const modalFooter = {
  padding: 12, borderTop: '1px solid var(--border)',
  display: 'flex', justifyContent: 'flex-end', gap: 8, background: 'var(--surface)',
};
const errorBox = {
  padding: '8px 12px', borderRadius: 6,
  background: 'rgba(242,63,67,0.12)', color: 'var(--red)',
  fontSize: 12, marginBottom: 8,
};
