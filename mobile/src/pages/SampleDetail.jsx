import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const STATUS_COLOR = {
  '제작중': 'gray', '보관중': 'green', '시험중': 'blue',
  '반출': 'orange', '반납완료': 'blue', '폐기': 'red',
};
const RESULT_COLOR = { '합격': 'green', '불합격': 'red', '판정보류': 'orange' };

export default function SampleDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [sm, setSm] = useState(null);
  const [opts, setOpts] = useState({});
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('info');
  const [busy, setBusy] = useState(false);
  const [statusNote, setStatusNote] = useState('');
  const [showTest, setShowTest] = useState(false);

  const token = localStorage.getItem('token');

  const load = useCallback(() => {
    api.get(`/samples/${id}`)
      .then(d => setSm(d.sample || null))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get('/samples/options').then(setOpts).catch(() => {}); }, []);

  const changeStatus = async (next) => {
    if (busy || !sm || next === sm.status) return;
    setBusy(true);
    try {
      await api.post(`/samples/${id}/status`, { status: next, note: statusNote });
      setStatusNote('');
      load();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const deleteTest = async (testId) => {
    if (!confirm('이 시험 기록을 삭제하시겠습니까?')) return;
    try { await api.post(`/samples/tests/${testId}/delete`, {}); load(); }
    catch (e) { alert(e.message); }
  };

  const discard = async () => {
    if (!confirm(`${sm.sample_no} 시료를 폐기 처리하시겠습니까?\n목록에서 제외되고 QR 스캔도 막힙니다.`)) return;
    try { await api.post(`/samples/${id}/delete`, {}); navigate('/samples', { replace: true }); }
    catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!sm) return <div className="page-loader">시료를 찾을 수 없습니다</div>;

  const sc = STATUS_COLOR[sm.status] || 'gray';

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1 style={{ fontFamily: 'monospace' }}>{sm.sample_no}</h1>
      </div>

      {/* 요약 */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
          <span className={`badge badge-${sc}`}>{sm.status}</span>
          <span className="badge badge-gray">{sm.purpose}</span>
          {sm.expiry_status === 'expired' && <span className="badge badge-red">성적서 만료</span>}
          {sm.expiry_status === 'warning' && <span className="badge badge-orange">성적서 30일</span>}
        </div>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-bright)' }}>{sm.model_name}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
          {[sm.location, sm.mfg_date && `제작 ${sm.mfg_date}`, `시험 ${sm.test_count}건`,
            sm.scan_count ? `스캔 ${sm.scan_count}회` : null].filter(Boolean).join(' · ')}
        </div>
        <a href={`/api/app/samples/${id}/label.pdf?token=${token}`} target="_blank" rel="noopener noreferrer"
           style={s.labelBtn}>QR 라벨 PDF 열기</a>
      </div>

      {/* 탭 */}
      <div style={s.tabRow}>
        {[['info', '정보'], ['tests', `시험 ${sm.test_count}`], ['logs', '이력']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            ...s.tab,
            color: tab === k ? 'var(--accent)' : 'var(--text-muted)',
            borderBottom: tab === k ? '2px solid var(--accent)' : '2px solid transparent',
          }}>{l}</button>
        ))}
      </div>

      {tab === 'info' && (
        <>
          <Sec title="스펙">
            {(sm.spec_pairs || []).map(p => <Row key={p.label} label={p.label} value={p.value} />)}
            {!sm.spec_pairs?.length && <div style={s.empty}>등록된 스펙이 없습니다</div>}
          </Sec>

          <Sec title="보관 정보">
            <Row label="제작일" value={sm.mfg_date} />
            <Row label="제작자" value={sm.made_by} />
            <Row label="보관위치" value={sm.location} />
            <Row label="연결 현장" value={sm.project} />
            <Row label="등록자" value={sm.created_by} />
            <Row label="마지막 스캔" value={sm.last_scanned_at} />
          </Sec>

          {(sm.public_note || sm.internal_note) && (
            <Sec title="메모">
              {sm.public_note && (
                <div style={{ marginBottom: 8 }}>
                  <span className="badge badge-blue">공개</span>
                  <div style={s.note}>{sm.public_note}</div>
                </div>
              )}
              {sm.internal_note && (
                <div>
                  <span className="badge badge-gray">사내 전용</span>
                  <div style={s.note}>{sm.internal_note}</div>
                </div>
              )}
            </Sec>
          )}

          {sm.has_photo && (
            <Sec title="시료 사진">
              <a href={`/api/app/samples/${id}/photo?token=${token}`} target="_blank" rel="noopener noreferrer">
                <img src={`/api/app/samples/${id}/photo?token=${token}`} alt="시료"
                     style={{ width: '100%', maxHeight: 360, objectFit: 'contain',
                              borderRadius: 6, background: 'var(--bg)' }} />
              </a>
            </Sec>
          )}

          <Sec title="상태 변경">
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 8 }}>
              {(opts.status_choices || []).map(st => (
                <button key={st} onClick={() => changeStatus(st)} disabled={busy} style={{
                  padding: '7px 11px', borderRadius: 5, border: 'none', cursor: 'pointer',
                  fontSize: 12, fontWeight: 600,
                  background: sm.status === st ? `var(--${STATUS_COLOR[st] === 'gray' ? 'surface' : STATUS_COLOR[st]})` : 'var(--surface)',
                  color: sm.status === st ? '#fff' : 'var(--text-muted)',
                }}>{st}</button>
              ))}
            </div>
            <input value={statusNote} onChange={e => setStatusNote(e.target.value)}
                   placeholder="사유·비고 (선택) — 반출 시 인수자 등" style={s.inp} />
          </Sec>

          <div style={{ display: 'flex', gap: 8, padding: '14px 16px' }}>
            <button onClick={() => navigate(`/samples/${id}/edit`)}
                    style={{ ...s.btn, color: 'var(--accent)' }}>수정</button>
            <button onClick={discard}
                    style={{ ...s.btn, background: 'rgba(242,63,67,0.15)', color: 'var(--red)' }}>폐기</button>
          </div>
        </>
      )}

      {tab === 'tests' && (
        <div>
          <div style={{ padding: '10px 16px' }}>
            <button onClick={() => setShowTest(true)} style={s.addBtn}>+ 시험 기록 등록</button>
          </div>
          {(sm.tests || []).length === 0 ? (
            <div className="page-empty">시험 기록 없음</div>
          ) : (
            sm.tests.map(t => (
              <div key={t.id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 5 }}>
                  <span className="badge badge-blue">{t.test_category}</span>
                  {t.result && <span className={`badge badge-${RESULT_COLOR[t.result] || 'gray'}`}>{t.result}</span>}
                  {!t.is_public && <span className="badge badge-gray">QR 비공개</span>}
                  {t.expiry_status === 'expired' && <span className="badge badge-red">만료</span>}
                  {t.expiry_status === 'warning' && <span className="badge badge-orange">30일</span>}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>
                  {t.test_type || '시험'}
                </div>
                {t.agency && <div style={{ fontSize: 12, color: 'var(--text)' }}>{t.agency}</div>}
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
                  {[t.report_no && `성적서 ${t.report_no}`,
                    t.issued_date && `발급 ${t.issued_date}`,
                    t.valid_until && `유효 ${t.valid_until}`].filter(Boolean).join(' · ')}
                </div>
                {t.measured?.length > 0 && (
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6 }}>
                    {t.measured.map(m => (
                      <span key={m.label} style={s.chip}>{m.label} <b>{m.value}</b></span>
                    ))}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  {t.has_file && (
                    <a href={`/api/app/samples/tests/${t.id}/file?token=${token}`}
                       target="_blank" rel="noopener noreferrer"
                       style={{ ...s.smallBtn, color: 'var(--accent)', textDecoration: 'none' }}>성적서 보기</a>
                  )}
                  <button onClick={() => deleteTest(t.id)}
                          style={{ ...s.smallBtn, color: 'var(--red)' }}>삭제</button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {tab === 'logs' && (
        <div>
          {(sm.logs || []).length === 0 ? (
            <div className="page-empty">이력 없음</div>
          ) : (
            sm.logs.map((lg, i) => (
              <div key={i} style={{ padding: '9px 16px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className={`badge badge-${lg.origin === 'qr' ? 'blue' : 'gray'}`}>{lg.action}</span>
                  <span style={{ fontSize: 12, color: 'var(--text)' }}>{lg.content}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>
                  {lg.user_name} · {lg.created_at}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {showTest && (
        <TestSheet
          sampleId={id}
          opts={opts}
          onClose={() => setShowTest(false)}
          onSaved={() => { setShowTest(false); setTab('tests'); load(); }}
        />
      )}
    </div>
  );
}

/** 시험 기록 등록 시트 — 성적서 촬영 첨부 지원 */
function TestSheet({ sampleId, opts, onClose, onSaved }) {
  const [form, setForm] = useState({
    test_category: '공인시험', test_type: '', agency: '', request_date: '',
    report_no: '', issued_date: '', valid_until: '', result: '',
    tester: '', note: '', certification_id: '',
  });
  const [measures, setMeasures] = useState({});
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    setSaving(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => fd.append(k, v == null ? '' : v));
      Object.entries(measures).forEach(([k, v]) => { if (v) fd.append(`measure_${k}`, v); });
      if (file) fd.append('report_file', file);
      await api.postForm(`/samples/${sampleId}/tests`, fd);
      onSaved();
    } catch (e) {
      alert(e.message);
      setSaving(false);
    }
  };

  const hidden = form.test_category === 'A/S분석'
    || ['불합격', '판정보류'].includes(form.result);

  return (
    <div style={s.backdrop}>
      <div style={s.sheet}>
        <div style={s.sheetHead}>
          <span style={{ fontSize: 14, fontWeight: 700 }}>시험 기록 등록</span>
          <button onClick={onClose} style={s.close}>✕</button>
        </div>

        <div style={{ padding: '10px 14px', overflowY: 'auto', flex: 1 }}>
          <F label="시험 구분">
            <select value={form.test_category} onChange={e => set('test_category', e.target.value)} style={s.inp}>
              {(opts.category_choices || []).map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </F>
          <F label="시험 종류">
            <select value={form.test_type} onChange={e => set('test_type', e.target.value)} style={s.inp}>
              <option value="">-- 선택 --</option>
              {(opts.type_choices || []).map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </F>
          <F label="시험기관">
            <input value={form.agency} onChange={e => set('agency', e.target.value)}
                   list="agencies" placeholder="한국산업기술시험원(KTL)" style={s.inp} />
            <datalist id="agencies">
              {(opts.agencies || []).map(a => <option key={a} value={a} />)}
            </datalist>
          </F>

          <div style={{ display: 'flex', gap: 8 }}>
            <F label="성적서 번호" flex>
              <input value={form.report_no} onChange={e => set('report_no', e.target.value)} style={s.inp} />
            </F>
            <F label="판정" flex>
              <select value={form.result} onChange={e => set('result', e.target.value)} style={s.inp}>
                <option value="">-- 선택 --</option>
                {(opts.result_choices || []).map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </F>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <F label="발급일" flex>
              <input type="date" value={form.issued_date} onChange={e => set('issued_date', e.target.value)} style={s.inp} />
            </F>
            <F label="유효기간" flex>
              <input type="date" value={form.valid_until} onChange={e => set('valid_until', e.target.value)} style={s.inp} />
            </F>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <F label="의뢰·접수일" flex>
              <input type="date" value={form.request_date} onChange={e => set('request_date', e.target.value)} style={s.inp} />
            </F>
            <F label="담당·측정자" flex>
              <input value={form.tester} onChange={e => set('tester', e.target.value)} style={s.inp} />
            </F>
          </div>

          <F label="연결 인증서 (선택)">
            <select value={form.certification_id} onChange={e => set('certification_id', e.target.value)} style={s.inp}>
              <option value="">-- 없음 --</option>
              {(opts.certifications || []).map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </F>

          <div style={{ ...s.fl, marginTop: 10, marginBottom: 5 }}>측정값</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {(opts.measure_fields || []).map(m => (
              <div key={m.key}>
                <div style={s.fl}>{m.label}{m.unit ? ` (${m.unit})` : ''}</div>
                <input value={measures[m.key] || ''} inputMode="decimal"
                       onChange={e => setMeasures(v => ({ ...v, [m.key]: e.target.value }))}
                       style={s.inp} />
              </div>
            ))}
          </div>

          <F label="성적서 첨부 — 촬영 또는 파일 선택">
            <input type="file" accept=".pdf,image/*" capture="environment"
                   onChange={e => setFile(e.target.files[0] || null)} style={{ ...s.inp, padding: 6 }} />
            {file && <div style={s.help}>{file.name}</div>}
          </F>

          <F label="비고">
            <textarea value={form.note} onChange={e => set('note', e.target.value)}
                      rows={2} style={{ ...s.inp, minHeight: 48, resize: 'vertical' }} />
          </F>

          {hidden && (
            <div style={s.warn}>
              이 기록은 <b>QR 공개 페이지에 노출되지 않습니다</b> (사내 열람 전용).
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, padding: '10px 14px', borderTop: '1px solid var(--border)' }}>
          <button onClick={onClose} style={s.btn}>취소</button>
          <button onClick={submit} disabled={saving}
                  style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>
            {saving ? '등록중...' : '등록'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Sec({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={s.secTitle}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  if (value == null || value === '') return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={s.rowV}>{value}</span>
    </div>
  );
}

function F({ label, children, flex }) {
  return (
    <div style={{ marginBottom: 8, ...(flex ? { flex: 1, minWidth: 0 } : {}) }}>
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
  row: {
    display: 'flex', justifyContent: 'space-between', padding: '4px 0',
    borderBottom: '1px solid var(--border)', gap: 8,
  },
  rowL: { fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 },
  rowV: {
    fontSize: 12, color: 'var(--text-bright)', fontWeight: 500,
    maxWidth: '65%', textAlign: 'right', wordBreak: 'break-all',
  },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  help: { fontSize: 10, color: 'var(--text-muted)', marginTop: 3 },
  empty: { fontSize: 12, color: 'var(--text-muted)', padding: '4px 0' },
  note: { fontSize: 12, color: 'var(--text)', whiteSpace: 'pre-wrap', marginTop: 4 },
  inp: {
    width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)',
    border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13,
  },
  btn: {
    flex: 1, padding: '12px 0', borderRadius: 6, fontSize: 13, fontWeight: 600,
    cursor: 'pointer', border: 'none', textAlign: 'center',
    background: 'var(--surface)', color: 'var(--text-muted)',
  },
  smallBtn: {
    padding: '6px 12px', borderRadius: 5, fontSize: 11, fontWeight: 600,
    cursor: 'pointer', border: 'none', background: 'var(--surface)',
  },
  addBtn: {
    width: '100%', padding: '10px', borderRadius: 6, cursor: 'pointer',
    background: 'var(--surface)', color: 'var(--accent)', fontSize: 13,
    fontWeight: 600, border: '1px dashed var(--border)',
  },
  labelBtn: {
    display: 'inline-block', marginTop: 8, padding: '7px 13px', borderRadius: 5,
    background: 'var(--surface)', color: 'var(--accent)', fontSize: 12,
    fontWeight: 600, textDecoration: 'none',
  },
  tabRow: { display: 'flex', borderBottom: '1px solid var(--border)' },
  tab: {
    flex: 1, padding: '11px 0', background: 'none', border: 'none',
    fontSize: 13, fontWeight: 600, cursor: 'pointer',
  },
  chip: {
    fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)',
    borderRadius: 5, padding: '2px 7px', color: 'var(--text)',
  },
  backdrop: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 3000,
    display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
  },
  sheet: {
    width: '100%', maxWidth: 520, maxHeight: '92vh', background: 'var(--surface)',
    borderRadius: '12px 12px 0 0', display: 'flex', flexDirection: 'column',
  },
  sheetHead: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 14px', borderBottom: '1px solid var(--border)', flexShrink: 0,
  },
  close: { background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 16, cursor: 'pointer' },
  warn: {
    marginTop: 6, padding: '9px 11px', borderRadius: 6, fontSize: 11,
    background: 'rgba(242,63,67,0.12)', color: 'var(--text)', lineHeight: 1.6,
  },
};
