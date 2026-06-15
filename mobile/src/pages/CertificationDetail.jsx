import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const CERT_TYPES = [
  'KS인증', '고효율인증', '성능인증', '녹색기술인증', '환경표지',
  '조달우수제품', '혁신제품', 'ISO', 'MAS계약', '직접생산증명',
  'G-PASS', '중소기업확인서', '단체표준', '기타',
];

function dday(dateStr) {
  if (!dateStr) return null;
  const d = Math.ceil((new Date(dateStr) - new Date()) / 86400000);
  if (d < 0) return { text: `${Math.abs(d)}일 경과`, color: 'red' };
  if (d <= 7) return { text: `D-${d}`, color: 'red' };
  if (d <= 30) return { text: `D-${d}`, color: 'orange' };
  return { text: `D-${d}`, color: 'green' };
}

export default function CertificationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = () => {
    api.get(`/certifications/${id}`)
      .then((d) => setData(d.cert || null))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const startEdit = () => {
    setForm({
      cert_type: data.cert_type || '기타',
      cert_name: data.cert_name || '',
      cert_no: data.cert_no || '',
      issued_by: data.issued_by || data.issuer || '',
      issued_date: data.issued_date || data.issue_date || '',
      expiry_date: data.expiry_date || '',
      product_model: data.product_model || '',
      alert_days: data.alert_days || 30,
      note: data.note || '',
    });
    setFile(null);
    setEditing(true);
  };

  const save = async () => {
    if (!form.cert_name?.trim()) return alert('인증서명을 입력해주세요');
    setSaving(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => fd.append(k, v == null ? '' : v));
      if (file) fd.append('cert_file', file);
      const token = localStorage.getItem('token');
      const res = await fetch(`/api/app/certifications/${id}/edit`, {
        method: 'POST', headers: { 'Authorization': `Bearer ${token}` }, body: fd,
      });
      const out = await res.json();
      if (!out.ok) throw new Error(out.error || '저장 실패');
      setEditing(false);
      load();
    } catch (e) { alert(e.message); }
    setSaving(false);
  };

  const remove = async () => {
    if (!confirm('이 인증서를 비활성화하시겠습니까?')) return;
    try {
      await api.post(`/certifications/${id}/delete`, {});
      navigate('/certifications');
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">인증서를 찾을 수 없습니다</div>;

  const dd = dday(data.expiry_date);
  const token = localStorage.getItem('token');
  const fileUrl = data.file_path
    ? (data.file_path.startsWith('http')
        ? data.file_path
        : `/api/app/certifications/${id}/file?token=${token}`)
    : null;
  const ext = data.file_path ? data.file_path.split('.').pop().toLowerCase() : '';
  const isImage = ['jpg', 'jpeg', 'png', 'webp', 'gif'].includes(ext);
  const isPdf = ext === 'pdf';

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>{data.cert_name}</h1>
      </div>

      <Sec title="인증서 정보">
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div>
              <div style={s.fl}>인증 유형 *</div>
              <select value={form.cert_type || '기타'}
                onChange={(e) => setForm(f => ({ ...f, cert_type: e.target.value }))}
                style={s.inp}>
                {CERT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            {[
              ['cert_name', '인증서명 *'],
              ['cert_no', '인증번호'],
              ['issued_by', '발급기관'],
              ['issued_date', '발급일', 'date'],
              ['expiry_date', '만료일', 'date'],
              ['product_model', '대상 제품/모델'],
              ['alert_days', '만료 전 알림 (일)', 'number'],
            ].map(([k, l, t]) => (
              <div key={k}>
                <div style={s.fl}>{l}</div>
                <input type={t || 'text'} value={form[k] || ''}
                  onChange={(e) => setForm(f => ({ ...f, [k]: e.target.value }))}
                  style={s.inp} />
              </div>
            ))}
            <div>
              <div style={s.fl}>비고</div>
              <textarea value={form.note || ''}
                onChange={(e) => setForm(f => ({ ...f, note: e.target.value }))}
                rows={2} style={{ ...s.inp, minHeight: 50, resize: 'vertical' }} />
            </div>
            <div>
              <div style={s.fl}>인증서 파일 교체</div>
              <input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp"
                onChange={(e) => setFile(e.target.files[0] || null)}
                style={{ ...s.inp, padding: 6 }} />
              {data.file_path && !file && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                  현재: {data.file_path.split('/').pop()}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button onClick={save} disabled={saving}
                style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>
                {saving ? '저장중...' : '저장'}
              </button>
              <button onClick={() => setEditing(false)} style={s.btn}>취소</button>
            </div>
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
              <span className="badge badge-gray">{data.cert_type || '-'}</span>
              {dd && <span className={`badge badge-${dd.color}`}>{dd.text}</span>}
            </div>
            <Row label="인증서명" value={data.cert_name} accent />
            <Row label="인증유형" value={data.cert_type} />
            <Row label="인증번호" value={data.cert_no} />
            <Row label="발급기관" value={data.issued_by || data.issuer} />
            <Row label="발급일" value={data.issued_date || data.issue_date} />
            <Row label="만료일" value={data.expiry_date} />
            <Row label="대상 제품/모델" value={data.product_model} />
            <Row label="알림일수" value={data.alert_days ? `${data.alert_days}일 전` : null} />
            <Row label="비고" value={data.note} />
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button onClick={startEdit}
                style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)' }}>수정</button>
              <button onClick={remove}
                style={{ ...s.btn, background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>삭제</button>
            </div>
          </>
        )}
      </Sec>

      {fileUrl && !editing && (
        <Sec title="인증서 파일">
          {isImage ? (
            <a href={fileUrl} target="_blank" rel="noopener noreferrer">
              <img src={fileUrl} alt="인증서"
                style={{ width: '100%', maxHeight: 400, objectFit: 'contain',
                         borderRadius: 6, background: 'var(--bg)' }} />
            </a>
          ) : isPdf ? (
            <div>
              <embed src={fileUrl} type="application/pdf"
                style={{ width: '100%', height: 500, borderRadius: 6, background: 'var(--bg)' }} />
              <a href={fileUrl} target="_blank" rel="noopener noreferrer"
                style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)',
                         display: 'block', marginTop: 8, textAlign: 'center', textDecoration: 'none' }}>
                새 창에서 열기
              </a>
            </div>
          ) : (
            <a href={fileUrl} target="_blank" rel="noopener noreferrer"
              style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)',
                       display: 'block', textAlign: 'center', textDecoration: 'none' }}>
              파일 다운로드 ({data.file_path.split('/').pop()})
            </a>
          )}
        </Sec>
      )}
    </div>
  );
}

function Sec({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value, accent }) {
  if (value == null || value === '') return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={{ ...s.rowV, ...(accent ? { color: 'var(--accent)' } : {}) }}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  btn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600,
         cursor: 'pointer', border: 'none', textAlign: 'center',
         background: 'var(--surface)', color: 'var(--text-muted)' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0',
         borderBottom: '1px solid var(--border)', gap: 8 },
  rowL: { fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500,
          maxWidth: '65%', textAlign: 'right', wordBreak: 'break-all' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6,
         background: 'var(--bg)', border: '1px solid var(--border)',
         color: 'var(--text)', fontSize: 13 },
};
