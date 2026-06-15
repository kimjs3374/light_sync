import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

/**
 * 거래처 신규 등록 — ERP vendor_list.html 의 신규등록 모달과 동일한 필드
 * - 거래처명(필수), 대표자, 사업자번호, 전화, 팩스, 이메일, 주소, 업체 메모
 * - 등록 성공 시 상세로 이동
 */
export default function VendorCreate() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    name: '', ceo_name: '', business_no: '',
    tel: '', fax: '', email: '', address: '',
    business: '', jongmok: '', note: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    setError('');
    if (!form.name.trim()) { setError('거래처명을 입력해주세요'); return; }
    setSubmitting(true);
    try {
      const data = await api.post('/vendors/create', form);
      const id = data.vendor_id || data.id;
      if (id) navigate(`/vendors/${id}`);
      else navigate('/vendors');
    } catch (e) {
      setError(e.message);
    }
    setSubmitting(false);
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>거래처 신규 등록</h1>
      </div>

      <div style={{ padding: 16 }}>
        {error && (
          <div style={{ padding: '8px 12px', borderRadius: 6, background: 'rgba(242,63,67,0.12)', color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <Field label="거래처명 *" value={form.name} onChange={v => update('name', v)} required />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="대표자" value={form.ceo_name} onChange={v => update('ceo_name', v)} />
          <Field label="사업자번호" value={form.business_no} onChange={v => update('business_no', v)} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="전화" value={form.tel} onChange={v => update('tel', v)} />
          <Field label="팩스" value={form.fax} onChange={v => update('fax', v)} />
        </div>

        <Field label="이메일" value={form.email} onChange={v => update('email', v)} type="email" />
        <Field label="주소" value={form.address} onChange={v => update('address', v)} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="업종" value={form.business} onChange={v => update('business', v)} />
          <Field label="종목" value={form.jongmok} onChange={v => update('jongmok', v)} />
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={s.fl}>업체 메모 <span style={{ color: 'var(--text-muted)' }}>(담당자재, 특이사항 등)</span></div>
          <textarea value={form.note}
            onChange={e => update('note', e.target.value)}
            rows={3}
            placeholder="예: 케이블류 납품, CV/VCTF 전선"
            style={{ ...s.inp, resize: 'vertical', minHeight: 60 }} />
        </div>

        <button onClick={submit} disabled={submitting} style={s.submitBtn}>
          {submitting ? '처리중...' : '등록'}
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={s.fl}>{label}</div>
      <input type={type || 'text'} value={value}
        onChange={e => onChange(e.target.value)}
        style={s.inp} />
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  fl: { fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 },
  inp: { width: '100%', padding: '10px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  submitBtn: { width: '100%', padding: 12, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', marginTop: 8 },
};
