import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';

/** 시료 등록/수정 — 모바일 1탭 직행. 모델명만 필수, 스펙은 접어둔다.
 *  경로에 :id 가 있으면 수정 모드로 동작한다. */
export default function SampleCreate() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = Boolean(id);
  const [opts, setOpts] = useState({ purpose_choices: [], status_choices: [] });
  const [loading, setLoading] = useState(Boolean(id));
  const [form, setForm] = useState({
    model_name: '', item_cd: '', purpose: '사내시험', status: '보관중',
    mfg_date: new Date().toISOString().slice(0, 10),
    made_by: '', location: '',
    led_chip: '', pcb_spec: '', cct: '', lens_angle: '', smps_model: '',
    input_voltage: '', ip_grade: '', body_material: '',
    watt: '', lumen: '', weight: '',
    public_note: '', internal_note: '',
  });
  const [photo, setPhoto] = useState(null);
  const [showSpec, setShowSpec] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get('/samples/options').then(setOpts).catch(() => {});
  }, []);

  // 수정 모드 — 기존 값 채우기
  useEffect(() => {
    if (!id) return;
    api.get(`/samples/${id}`)
      .then(d => {
        const f = d.sample?.fields;
        if (f) setForm(prev => ({ ...prev, ...f }));
        if (f && Object.values(f).some(v => v !== '' && v != null)) setShowSpec(true);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.model_name.trim()) return alert('모델명을 입력해주세요');
    setSaving(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => fd.append(k, v == null ? '' : v));
      if (photo) fd.append('photo', photo);
      const path = isEdit ? `/samples/${id}/edit` : '/samples/create';
      const d = await api.postForm(path, fd);
      navigate(`/samples/${isEdit ? id : d.sample_id}`, { replace: true });
    } catch (e) {
      alert(e.message);
      setSaving(false);
    }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>{isEdit ? '시료 수정' : '시료 등록'}</h1>
      </div>

      <Sec title="기본 정보">
        <Field label="모델명 *">
          <input value={form.model_name} onChange={e => set('model_name', e.target.value)}
                 placeholder="ARENA-200S" style={s.inp} autoFocus />
          <div style={s.help}>
            {isEdit ? '모델명을 바꿔도 시료번호는 유지됩니다'
                    : '시료번호는 모델별로 자동 채번됩니다 (예: ARENA-200S-001)'}
          </div>
        </Field>

        <div style={{ display: 'flex', gap: 8 }}>
          <Field label="용도" flex>
            <select value={form.purpose} onChange={e => set('purpose', e.target.value)} style={s.inp}>
              {(opts.purpose_choices || []).map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="상태" flex>
            <select value={form.status} onChange={e => set('status', e.target.value)} style={s.inp}>
              {(opts.status_choices || []).map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <Field label="제작일" flex>
            <input type="date" value={form.mfg_date} onChange={e => set('mfg_date', e.target.value)} style={s.inp} />
          </Field>
          <Field label="제작자" flex>
            <input value={form.made_by} onChange={e => set('made_by', e.target.value)} style={s.inp} />
          </Field>
        </div>

        <Field label="보관위치">
          <input value={form.location} onChange={e => set('location', e.target.value)}
                 placeholder="시료보관실 A-3" style={s.inp} />
        </Field>

        <Field label="품번 (선택)">
          <input value={form.item_cd} onChange={e => set('item_cd', e.target.value)} style={s.inp} />
        </Field>

        <Field label="시료 사진">
          <input type="file" accept="image/*" capture="environment"
                 onChange={e => setPhoto(e.target.files[0] || null)}
                 style={{ ...s.inp, padding: 6 }} />
          {photo && <div style={s.help}>{photo.name}</div>}
        </Field>
      </Sec>

      <div style={{ padding: '10px 16px' }}>
        <button onClick={() => setShowSpec(v => !v)} style={s.toggle}>
          {showSpec ? '▲ 스펙 접기' : '▼ 스펙 입력 (선택)'}
        </button>
      </div>

      {showSpec && (
        <Sec title="시료 스펙">
          {[
            ['led_chip', 'LED 칩'],
            ['pcb_spec', 'PCB 사양'],
            ['cct', '색온도 (5700K)'],
            ['lens_angle', '렌즈 각도'],
            ['smps_model', 'SMPS 모델'],
            ['input_voltage', '입력전원 (AC220V 60Hz)'],
            ['ip_grade', 'IP 등급 (IP66)'],
            ['body_material', '본체 재질'],
          ].map(([k, l]) => (
            <Field key={k} label={l}>
              <input value={form[k]} onChange={e => set(k, e.target.value)} style={s.inp} />
            </Field>
          ))}
          <div style={{ display: 'flex', gap: 8 }}>
            <Field label="소비전력 (W)" flex>
              <input type="number" step="0.1" inputMode="decimal" value={form.watt}
                     onChange={e => set('watt', e.target.value)} style={s.inp} />
            </Field>
            <Field label="광속 (lm)" flex>
              <input type="number" step="1" inputMode="numeric" value={form.lumen}
                     onChange={e => set('lumen', e.target.value)} style={s.inp} />
            </Field>
            <Field label="중량 (kg)" flex>
              <input type="number" step="0.1" inputMode="decimal" value={form.weight}
                     onChange={e => set('weight', e.target.value)} style={s.inp} />
            </Field>
          </div>
        </Sec>
      )}

      <Sec title="메모">
        <Field label="공개 메모 — QR 스캔 시 외부에 보입니다">
          <textarea value={form.public_note} onChange={e => set('public_note', e.target.value)}
                    rows={2} style={{ ...s.inp, minHeight: 50, resize: 'vertical' }} />
        </Field>
        <Field label="내부 메모 — 사내 전용, 외부 비공개">
          <textarea value={form.internal_note} onChange={e => set('internal_note', e.target.value)}
                    rows={2} style={{ ...s.inp, minHeight: 50, resize: 'vertical' }} />
        </Field>
      </Sec>

      <div style={{ display: 'flex', gap: 8, padding: '14px 16px' }}>
        <button onClick={() => navigate(-1)} style={s.btn}>취소</button>
        <button onClick={submit} disabled={saving}
                style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>
          {saving ? '저장중...' : (isEdit ? '저장' : '등록')}
        </button>
      </div>
    </div>
  );
}

function Sec({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={s.secTitle}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{children}</div>
    </div>
  );
}

function Field({ label, children, flex }) {
  return (
    <div style={flex ? { flex: 1, minWidth: 0 } : undefined}>
      <div style={s.fl}>{label}</div>
      {children}
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  secTitle: {
    fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8,
  },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  help: { fontSize: 10, color: 'var(--text-muted)', marginTop: 3 },
  inp: {
    width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)',
    border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13,
  },
  btn: {
    flex: 1, padding: '12px 0', borderRadius: 6, fontSize: 13, fontWeight: 600,
    cursor: 'pointer', border: 'none', textAlign: 'center',
    background: 'var(--surface)', color: 'var(--text-muted)',
  },
  toggle: {
    width: '100%', padding: '9px', borderRadius: 6, cursor: 'pointer',
    background: 'var(--surface)', color: 'var(--text-muted)', fontSize: 12,
    fontWeight: 600, border: '1px solid var(--border)',
  },
};
