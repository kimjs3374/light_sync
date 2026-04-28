import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';

const FORMS = {
  'purchase-order': {
    title: '발주서 생성',
    endpoint: '/purchase-orders/create',
    fields: [
      { key: 'vendor_name', label: '거래처 *', required: true },
      { key: 'project_name', label: '현장명' },
      { key: 'note', label: '비고', multiline: true },
    ],
    onSuccess: (data, nav) => nav(`/purchase-orders/${data.po_id}`),
  },
  'receiving': {
    title: '입고 등록',
    endpoint: '/receivings/create',
    fields: [
      { key: 'vendor_name', label: '거래처 *', required: true },
      { key: 'note', label: '비고', multiline: true },
    ],
    onSuccess: (data, nav) => nav(`/receivings/${data.rcv_id}`),
  },
  'quotation': {
    title: '견적서 생성',
    endpoint: '/quotations/create',
    fields: [
      { key: 'title', label: '제목 *', required: true },
      { key: 'project_name', label: '현장명' },
    ],
    onSuccess: (data, nav) => nav('/quotations'),
  },
  'warranty': {
    title: 'AS 접수',
    endpoint: '/warranty-cases/create',
    fields: [
      { key: 'project_name', label: '현장명' },
      { key: 'contract_name', label: '계약명' },
      { key: 'model_name', label: '모델명' },
      { key: 'defect_type', label: '결함유형' },
      { key: 'symptom', label: '증상 *', required: true, multiline: true },
      { key: 'customer_phone', label: '고객연락처' },
    ],
    onSuccess: (data, nav) => nav(`/warranty/${data.case_id}`),
  },
  'processing-order': {
    title: '가공발주 생성',
    endpoint: '/processing-orders/create',
    fields: [
      { key: 'vendor_name', label: '거래처 *', required: true },
      { key: 'project_name', label: '현장명' },
      { key: 'processing_type', label: '유형 (외주가공/사급가공)' },
      { key: 'note', label: '비고', multiline: true },
    ],
    onSuccess: (data, nav) => nav('/processing-orders'),
  },
  'business-trip': {
    title: '출장 등록',
    endpoint: '/business-trips/create',
    fields: [
      { key: 'title', label: '제목 *', required: true },
      { key: 'destination', label: '목적지 *', required: true },
      { key: 'departure_date', label: '출발일 *', required: true, type: 'date' },
      { key: 'return_date', label: '복귀일 *', required: true, type: 'date' },
      { key: 'vehicle', label: '차량' },
      { key: 'note', label: '비고', multiline: true },
    ],
    onSuccess: (data, nav) => nav('/business-trips'),
  },
  'vendor': {
    title: '거래처 등록',
    endpoint: '/vendors/create',
    fields: [
      { key: 'name', label: '업체명 *', required: true },
      { key: 'ceo_name', label: '대표자명' },
      { key: 'business_no', label: '사업자번호' },
      { key: 'tel', label: '전화번호' },
      { key: 'email', label: '이메일' },
      { key: 'address', label: '주소' },
    ],
    onSuccess: (data, nav) => nav('/vendors'),
  },
  'item': {
    title: '품목 등록',
    endpoint: '/items/create',
    fields: [
      { key: 'item_name', label: '품목명 *', required: true },
      { key: 'item_code', label: '품목코드' },
      { key: 'category', label: '분류' },
      { key: 'unit', label: '단위 (EA, SET 등)' },
      { key: 'manufacturer', label: '제조사' },
    ],
    onSuccess: (data, nav) => nav('/items'),
  },
  'tool': {
    title: '공구 등록',
    endpoint: '/tools/create',
    fields: [
      { key: 'tool_name', label: '공구명 *', required: true },
      { key: 'category', label: '분류' },
      { key: 'total_qty', label: '수량', type: 'number' },
      { key: 'current_location', label: '보관위치' },
    ],
    onSuccess: (data, nav) => nav('/tools'),
  },
  'certification': {
    title: '인증서 등록',
    endpoint: '/certifications/create',
    fields: [
      { key: 'cert_name', label: '인증서명 *', required: true },
      { key: 'cert_type', label: '유형' },
      { key: 'cert_no', label: '인증번호' },
      { key: 'issuer', label: '발급기관' },
      { key: 'issue_date', label: '발급일', type: 'date' },
      { key: 'expiry_date', label: '만료일', type: 'date' },
    ],
    onSuccess: (data, nav) => nav('/certifications'),
  },
};

export default function CreateForm() {
  const [searchParams] = useSearchParams();
  const type = searchParams.get('type') || '';
  const navigate = useNavigate();
  const [values, setValues] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const form = FORMS[type];
  if (!form) return <div className="page-loader">알 수 없는 양식</div>;

  const handleSubmit = async () => {
    setError('');
    for (const f of form.fields) {
      if (f.required && !values[f.key]?.trim()) {
        setError(`${f.label.replace(' *', '')}을(를) 입력해주세요`);
        return;
      }
    }
    setSubmitting(true);
    try {
      const data = await api.post(form.endpoint, values);
      form.onSuccess(data, navigate);
    } catch (e) {
      setError(e.message);
    }
    setSubmitting(false);
  };

  return (
    <div>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' }}>←</button>
        <h1>{form.title}</h1>
      </div>

      <div style={{ padding: '16px' }}>
        {error && (
          <div style={{ padding: '8px 12px', borderRadius: 6, background: 'rgba(242,63,67,0.12)', color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>
            {error}
          </div>
        )}

        {form.fields.map((f) => (
          <div key={f.key} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{f.label}</div>
            {f.multiline ? (
              <textarea
                value={values[f.key] || ''}
                onChange={(e) => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                rows={3}
                style={{ ...s.input, resize: 'vertical', minHeight: 60 }}
              />
            ) : (
              <input
                type={f.type || 'text'}
                value={values[f.key] || ''}
                onChange={(e) => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                style={s.input}
              />
            )}
          </div>
        ))}

        <button onClick={handleSubmit} disabled={submitting} style={s.submitBtn}>
          {submitting ? '처리중...' : '생성'}
        </button>
      </div>
    </div>
  );
}

const s = {
  input: { width: '100%', padding: '10px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  submitBtn: { width: '100%', padding: 12, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', marginTop: 8 },
};
