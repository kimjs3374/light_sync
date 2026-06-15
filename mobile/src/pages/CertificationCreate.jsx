import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const CERT_TYPES = [
  'KS인증', '고효율인증', '성능인증', '녹색기술인증', '환경표지',
  '조달우수제품', '혁신제품', 'ISO', 'MAS계약', '직접생산증명',
  'G-PASS', '중소기업확인서', '단체표준', '기타',
];

export default function CertificationCreate() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    cert_type: '기타',
    cert_name: '',
    cert_no: '',
    issued_by: '',
    issued_date: '',
    expiry_date: '',
    product_model: '',
    alert_days: 30,
    note: '',
  });
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.cert_name.trim()) { setError('인증서명을 입력해주세요'); return; }
    setError('');
    setSaving(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => fd.append(k, v == null ? '' : v));
      if (file) fd.append('cert_file', file);
      const token = localStorage.getItem('token');
      const res = await fetch('/api/app/certifications/create', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || '등록 실패');
      navigate(data.cert_id ? `/certifications/${data.cert_id}` : '/certifications');
    } catch (e) {
      setError(e.message);
    }
    setSaving(false);
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>인증서 등록</h1>
      </div>

      <div style={{ padding: 16 }}>
        {error && (
          <div style={{ padding: '8px 12px', borderRadius: 6,
                        background: 'rgba(242,63,67,0.12)', color: 'var(--red)',
                        fontSize: 13, marginBottom: 12 }}>{error}</div>
        )}

        <Field label="인증 유형 *">
          <select value={form.cert_type} onChange={(e) => set('cert_type', e.target.value)} style={s.inp}>
            {CERT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>

        <Field label="인증서명 *">
          <input value={form.cert_name} onChange={(e) => set('cert_name', e.target.value)}
            placeholder="예: KS C 7653" style={s.inp} />
        </Field>

        <Field label="인증번호">
          <input value={form.cert_no} onChange={(e) => set('cert_no', e.target.value)}
            placeholder="예: 제16-0239호" style={s.inp} />
        </Field>

        <Field label="발급기관">
          <input value={form.issued_by} onChange={(e) => set('issued_by', e.target.value)}
            placeholder="예: 한국표준협회" style={s.inp} />
        </Field>

        <Field label="발급일">
          <input type="date" value={form.issued_date}
            onChange={(e) => set('issued_date', e.target.value)} style={s.inp} />
        </Field>

        <Field label="만료일">
          <input type="date" value={form.expiry_date}
            onChange={(e) => set('expiry_date', e.target.value)} style={s.inp} />
        </Field>

        <Field label="대상 제품/모델">
          <input value={form.product_model} onChange={(e) => set('product_model', e.target.value)}
            placeholder="예: ARENA-200(S)" style={s.inp} />
        </Field>

        <Field label="만료 전 알림 (일)">
          <input type="number" min="1" max="365" value={form.alert_days}
            onChange={(e) => set('alert_days', e.target.value)} style={s.inp} />
        </Field>

        <Field label="인증서 파일">
          <input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp"
            onChange={(e) => setFile(e.target.files[0] || null)}
            style={{ ...s.inp, padding: 6 }} />
        </Field>

        <Field label="비고">
          <textarea value={form.note} onChange={(e) => set('note', e.target.value)}
            rows={3} style={{ ...s.inp, resize: 'vertical', minHeight: 60 }} />
        </Field>

        <button onClick={submit} disabled={saving} style={s.submit}>
          {saving ? '등록중...' : '등록'}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  inp: { width: '100%', padding: '10px 12px', borderRadius: 6,
         background: 'var(--bg)', border: '1px solid var(--border)',
         color: 'var(--text)', fontSize: 13 },
  submit: { width: '100%', padding: 12, borderRadius: 6,
            background: 'var(--accent)', color: '#fff',
            fontSize: 14, fontWeight: 600, cursor: 'pointer',
            border: 'none', marginTop: 8 },
};
