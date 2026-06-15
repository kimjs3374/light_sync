import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function WarrantyCreate() {
  const navigate = useNavigate();
  const [mode, setMode] = useState('warranty'); // warranty | manual
  const [defectTypes, setDefectTypes] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedWarranty, setSelectedWarranty] = useState(null);
  const [form, setForm] = useState({
    defect_type: 'OTHER', symptom: '', customer_name: '', customer_phone: '',
    reported_by: '', assigned_to: '', request_channel: '',
    // 수기 입력
    manual_site_name: '', manual_contract_name: '', manual_model_name: '', manual_delivery_date: '',
  });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.get('/warranty-defect-types').then(d => setDefectTypes(d.defect_types || [])).catch(() => {});
  }, []);

  const searchWarranties = async (q) => {
    setSearchQuery(q);
    if (q.length < 1) { setSearchResults([]); return; }
    try {
      const d = await api.get(`/search/warranties?q=${encodeURIComponent(q)}`);
      setSearchResults(d.results || []);
    } catch {}
  };

  const selectWarranty = (w) => {
    setSelectedWarranty(w);
    setSearchQuery('');
    setSearchResults([]);
  };

  const handleSubmit = async () => {
    if (!form.symptom.trim()) return alert('증상을 입력해주세요');
    if (mode === 'warranty' && !selectedWarranty) return alert('보증 정보를 선택해주세요');
    setSubmitting(true);
    try {
      const body = {
        ...form,
        mode,
        warranty_id: mode === 'warranty' ? selectedWarranty?.id : null,
        project_name: mode === 'warranty' ? selectedWarranty?.contract_name : form.manual_site_name,
        contract_name: mode === 'warranty' ? selectedWarranty?.contract_name : form.manual_contract_name,
        model_name: mode === 'warranty' ? selectedWarranty?.model_name : form.manual_model_name,
      };
      const d = await api.post('/warranty-cases/create', body);
      navigate(`/warranty/${d.case_id}`);
    } catch (e) { alert(e.message); }
    setSubmitting(false);
  };

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>A/S 접수</h1>
      </div>

      {/* 입력 모드 */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={s.secTitle}>입력 방식</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setMode('warranty')}
            style={{ ...s.btn, background: mode === 'warranty' ? 'var(--accent)' : 'var(--surface)', color: mode === 'warranty' ? '#fff' : 'var(--text-muted)' }}>
            보증 검색
          </button>
          <button onClick={() => setMode('manual')}
            style={{ ...s.btn, background: mode === 'manual' ? 'var(--accent)' : 'var(--surface)', color: mode === 'manual' ? '#fff' : 'var(--text-muted)' }}>
            수기 입력
          </button>
        </div>
      </div>

      {/* 1. 보증/계약 정보 */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={s.secTitle}>1. 보증 / 계약 정보</div>

        {mode === 'warranty' ? (
          <>
            {selectedWarranty ? (
              <div style={{ padding: '8px 12px', background: 'var(--surface)', borderRadius: 6, marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>{selectedWarranty.contract_name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{selectedWarranty.item_group} · {selectedWarranty.model_name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>보증: {selectedWarranty.warranty_start} ~ {selectedWarranty.warranty_end}</div>
                  </div>
                  <button onClick={() => setSelectedWarranty(null)} style={{ background: 'none', border: 'none', color: 'var(--red)', fontSize: 14, cursor: 'pointer' }}>×</button>
                </div>
              </div>
            ) : (
              <div style={{ position: 'relative' }}>
                <input placeholder="현장명 / 계약명 / 모델명 검색..." value={searchQuery}
                  onChange={e => searchWarranties(e.target.value)} style={s.inp} />
                {searchResults.length > 0 && (
                  <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, maxHeight: 200, overflow: 'auto', marginTop: 2 }}>
                    {searchResults.map(w => (
                      <div key={w.id} onClick={() => selectWarranty(w)}
                        style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                        <div style={{ fontSize: 13, color: 'var(--text-bright)' }}>{w.contract_name}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{w.item_group} · {w.model_name}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div><div style={s.fl}>현장명</div><input value={form.manual_site_name} onChange={e => setForm(f => ({...f, manual_site_name: e.target.value}))} style={s.inp} placeholder="현장명 입력" /></div>
            <div><div style={s.fl}>계약명</div><input value={form.manual_contract_name} onChange={e => setForm(f => ({...f, manual_contract_name: e.target.value}))} style={s.inp} placeholder="계약명 또는 현장명" /></div>
            <div><div style={s.fl}>모델명</div><input value={form.manual_model_name} onChange={e => setForm(f => ({...f, manual_model_name: e.target.value}))} style={s.inp} placeholder="모델명" /></div>
            <div><div style={s.fl}>납품일</div><input type="date" value={form.manual_delivery_date} onChange={e => setForm(f => ({...f, manual_delivery_date: e.target.value}))} style={s.inp} /></div>
          </div>
        )}
      </div>

      {/* 2. 하자/증상 정보 */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={s.secTitle}>2. 하자 / 증상 정보</div>

        <div style={{ marginBottom: 8 }}>
          <div style={s.fl}>하자유형 *</div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {defectTypes.map(dt => (
              <button key={dt.code} onClick={() => setForm(f => ({...f, defect_type: dt.code}))}
                style={{ padding: '5px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, border: 'none', cursor: 'pointer',
                  background: form.defect_type === dt.code ? 'var(--accent)' : 'var(--bg)', color: form.defect_type === dt.code ? '#fff' : 'var(--text-muted)' }}>
                {dt.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 8 }}>
          <div style={s.fl}>증상 상세 *</div>
          <textarea value={form.symptom} onChange={e => setForm(f => ({...f, symptom: e.target.value}))}
            placeholder="발생 위치, 현상, 수량 등을 구체적으로 입력하세요"
            style={{ ...s.inp, minHeight: 80 }} rows={4} />
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <div style={{ flex: 1 }}><div style={s.fl}>고객명</div><input value={form.customer_name} onChange={e => setForm(f => ({...f, customer_name: e.target.value}))} style={s.inp} /></div>
          <div style={{ flex: 1 }}><div style={s.fl}>고객 연락처</div><input value={form.customer_phone} onChange={e => setForm(f => ({...f, customer_phone: e.target.value}))} style={s.inp} type="tel" /></div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1 }}><div style={s.fl}>접수 경로</div><input value={form.request_channel} onChange={e => setForm(f => ({...f, request_channel: e.target.value}))} style={s.inp} placeholder="전화/카톡/이메일" /></div>
          <div style={{ flex: 1 }}><div style={s.fl}>담당자</div><input value={form.assigned_to} onChange={e => setForm(f => ({...f, assigned_to: e.target.value}))} style={s.inp} /></div>
        </div>
      </div>

      {/* 접수 버튼 */}
      <div style={{ padding: '16px' }}>
        <button onClick={handleSubmit} disabled={submitting}
          style={{ width: '100%', padding: 14, borderRadius: 8, background: 'var(--accent)', color: '#fff', fontSize: 15, fontWeight: 700, cursor: 'pointer', border: 'none' }}>
          {submitting ? '접수중...' : 'A/S 접수 등록'}
        </button>
      </div>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  btn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3, fontWeight: 600 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
};
