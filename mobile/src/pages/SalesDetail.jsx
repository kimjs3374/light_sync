import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const FIELD_LABELS = {
  lens_angle: '렌즈각도',
  spacing_distance: '이격거리',
  body_type: '일체형/분리형',
  has_stabilizer_box: '안정기함 유무',
  stabilizer_vendor_contact: '안정기 업체 연락처',
  stabilizer_address: '안정기함 배송지',
  smps_shipment_schedule: 'SMPS 출하일정',
  is_integrated: '일체형 여부',
  tower_height: '타워 높이(m)',
  lamp_count: '등기구 수량',
  replace_or_new: '교체/신설',
  anchor_spacing: '앵커 간격',
  arm_type: '암 유형',
  is_painted: '도장 여부',
  paint_color: '도장 색상',
  stainless_finish_type: '마감유형',
};

const BODY_TYPE_OPTIONS = ['일체형', '분리형'];
const REPLACE_OPTIONS = ['교체', '신설', '혼합'];
const FINISH_OPTIONS = ['헤어라인', '도장', '무광'];

export default function SalesDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [spec, setSpec] = useState({});
  const [bomRows, setBomRows] = useState([]);
  const [plannedDate, setPlannedDate] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = () => {
    api.get(`/sales/${id}`).then((d) => {
      setData(d);
      const itemSpec = d.item?.spec || {};
      setSpec(itemSpec);
      setBomRows(itemSpec.bom_breakdown || []);
      setPlannedDate(d.item?.desired_delivery_date || '');
    }).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const updateSpec = (key, value) => {
    setSpec(prev => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  const updateBomRow = (idx, key, value) => {
    setBomRows(prev => {
      const next = [...prev];
      next[idx] = { ...next[idx], [key]: value };
      return next;
    });
    setDirty(true);
  };

  const addBomRow = () => {
    const bomOpts = data?.item?.bom_options || {};
    const newRow = {};
    Object.keys(bomOpts).forEach(k => { newRow[k] = ''; });
    newRow.qty = 0;
    setBomRows(prev => [...prev, newRow]);
    setDirty(true);
  };

  const removeBomRow = (idx) => {
    setBomRows(prev => prev.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const saveSpec = { ...spec, bom_breakdown: bomRows };
      await api.post(`/sales/${id}/spec`, { spec: saveSpec, planned_delivery_date: plannedDate });
      setDirty(false);
      load();
    } catch (e) { alert(e.message); }
    setSaving(false);
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">품목을 찾을 수 없습니다</div>;

  const item = data.item || {};
  const history = data.history || [];
  const requiredFields = item.required_fields || [];
  const bomOptions = item.bom_options || {};
  const hasBom = Object.keys(bomOptions).length > 0;
  const totalQty = item.quantity || 0;
  const bomQtySum = bomRows.reduce((s, r) => s + (parseInt(r.qty) || 0), 0);

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontSize: 13 }}>협의관리</h1>
        <span className={`badge badge-${item.status_sales === '협의완료' ? 'green' : item.status_sales === '상세협의중' ? 'blue' : 'orange'}`}>
          {item.status_sales}
        </span>
      </div>

      {/* 품목 요약 */}
      <Section title="품목 정보">
        <Row label="현장명" value={item.project_name} />
        <Row label="계약명" value={item.contract_name} />
        <Row label="품목" value={item.category} />
        <Row label="모델명" value={item.model_name} />
        <Row label="수량" value={item.quantity} />
        <Row label="납품기한" value={item.delivery_due_date} />
      </Section>

      {/* BOM 옵션 배분 */}
      {hasBom && (
        <Section title={`BOM 옵션 배분 (${bomQtySum}/${totalQty}대)`}>
          {bomRows.map((row, idx) => (
            <div key={idx} style={s.bomRow}>
              {Object.entries(bomOptions).map(([optKey, optValues]) => (
                <div key={optKey} style={{ flex: 1 }}>
                  <div style={s.fieldLabel}>{optKey}</div>
                  <select value={row[optKey] || ''} onChange={(e) => updateBomRow(idx, optKey, e.target.value)} style={s.select}>
                    <option value="">선택</option>
                    {(optValues || []).map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
              ))}
              <div style={{ width: 70 }}>
                <div style={s.fieldLabel}>수량</div>
                <input type="number" value={row.qty || ''} onChange={(e) => updateBomRow(idx, 'qty', parseInt(e.target.value) || 0)} style={s.input} />
              </div>
              <button onClick={() => removeBomRow(idx)} style={s.removeBtn}>×</button>
            </div>
          ))}
          <button onClick={addBomRow} style={s.addRowBtn}>+ 추가</button>
        </Section>
      )}

      {/* 협의내용 (스펙 필드) */}
      <Section title="협의내용">
        {requiredFields.filter(f => f !== 'has_stabilizer_box' || spec.has_stabilizer_box !== false).map((field) => (
          <SpecField key={field} field={field} value={spec[field]} onChange={(v) => updateSpec(field, v)} />
        ))}

        {/* 안정기함=true 일 때 추가 필드 */}
        {spec.has_stabilizer_box === true && (
          <>
            <SpecField field="stabilizer_vendor_contact" value={spec.stabilizer_vendor_contact} onChange={(v) => updateSpec('stabilizer_vendor_contact', v)} />
            <SpecField field="stabilizer_address" value={spec.stabilizer_address} onChange={(v) => updateSpec('stabilizer_address', v)} />
            <SpecField field="smps_shipment_schedule" value={spec.smps_shipment_schedule} onChange={(v) => updateSpec('smps_shipment_schedule', v)} />
          </>
        )}

        <div style={{ marginTop: 10 }}>
          <div style={s.fieldLabel}>납품예정일</div>
          <input type="date" value={plannedDate} onChange={(e) => { setPlannedDate(e.target.value); setDirty(true); }} style={s.input} />
        </div>

        {dirty && (
          <button onClick={handleSave} disabled={saving} style={s.saveBtn}>
            {saving ? '저장중...' : '협의내용 저장'}
          </button>
        )}
      </Section>

      {/* 히스토리 */}
      <Section title="히스토리">
        {history.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>기록 없음</div>
        ) : (
          history.slice(0, 20).map((h, i) => (
            <div key={i} style={s.histItem}>
              <div style={s.histAvatar}>{(h.user_name || '?')[0]}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-bright)' }}>{h.user_name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{h.created_at?.slice(0, 16)}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 2, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{h.content}</div>
              </div>
            </div>
          ))
        )}
      </Section>
    </div>
  );
}

function SpecField({ field, value, onChange }) {
  const label = FIELD_LABELS[field] || field;

  if (field === 'has_stabilizer_box' || field === 'is_integrated' || field === 'is_painted') {
    return (
      <div style={s.fieldWrap}>
        <div style={s.fieldLabel}>{label}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {[true, false].map((v) => (
            <button key={String(v)} onClick={() => onChange(v)}
              style={{ ...s.optBtn, background: value === v ? 'var(--accent)' : 'var(--bg)', color: value === v ? '#fff' : 'var(--text-muted)' }}>
              {v ? '예' : '아니오'}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (field === 'body_type') return <SelectField label={label} value={value} options={BODY_TYPE_OPTIONS} onChange={onChange} />;
  if (field === 'replace_or_new') return <SelectField label={label} value={value} options={REPLACE_OPTIONS} onChange={onChange} />;
  if (field === 'stainless_finish_type') return <SelectField label={label} value={value} options={FINISH_OPTIONS} onChange={onChange} />;

  return (
    <div style={s.fieldWrap}>
      <div style={s.fieldLabel}>{label}</div>
      <input type={field === 'lamp_count' ? 'number' : 'text'}
        value={value ?? ''} onChange={(e) => onChange(e.target.value)}
        style={s.input} placeholder={label} />
    </div>
  );
}

function SelectField({ label, value, options, onChange }) {
  return (
    <div style={s.fieldWrap}>
      <div style={s.fieldLabel}>{label}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {options.map((opt) => (
          <button key={opt} onClick={() => onChange(opt)}
            style={{ ...s.optBtn, background: value === opt ? 'var(--accent)' : 'var(--bg)', color: value === opt ? '#fff' : 'var(--text-muted)' }}>
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  if (!value && value !== 0) return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={s.rowV}>{value}</span>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer', padding: '4px 8px 4px 0' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right' },
  fieldWrap: { marginBottom: 10 },
  fieldLabel: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 },
  input: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  select: { width: '100%', padding: '9px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  optBtn: { padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none' },
  saveBtn: { width: '100%', padding: 12, borderRadius: 6, background: 'var(--accent)', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', marginTop: 12 },
  bomRow: { display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 8, padding: '8px 0', borderBottom: '1px solid var(--border)' },
  removeBtn: { background: 'none', border: 'none', color: 'var(--red)', fontSize: 18, cursor: 'pointer', padding: '8px 4px', flexShrink: 0 },
  addRowBtn: { padding: '8px', borderRadius: 6, background: 'var(--surface)', color: 'var(--accent)', fontSize: 12, fontWeight: 600, cursor: 'pointer', border: '1px dashed var(--border)', width: '100%', textAlign: 'center', marginTop: 4 },
  histItem: { display: 'flex', gap: 10, padding: '6px 0' },
  histAvatar: { width: 26, height: 26, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 },
};
