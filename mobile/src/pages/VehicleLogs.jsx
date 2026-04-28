import { useState, useEffect } from 'react';
import { api } from '../api/client';

const today = () => new Date().toISOString().slice(0, 10);
const fmt = (n) => (n == null || n === '' ? '-' : Number(n).toLocaleString());

export default function VehicleLogs() {
  // 화면 상태: 'vehicleList' | 'vehicleDetail' | 'create' | 'logDetail'
  const [view, setView] = useState('vehicleList');
  const [vehicles, setVehicles] = useState([]);
  const [selectedVehicle, setSelectedVehicle] = useState(null);   // {name, last_odometer}
  const [vehicleLogs, setVehicleLogs] = useState([]);
  const [logDetail, setLogDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const initialForm = () => ({
    use_date: today(),
    odometer_start: '',
    odometer_end: '',
    fuel_amount: '',
    origin: '',
    destination: '',
    purpose: '',
  });
  const [form, setForm] = useState(initialForm());
  const [receipt, setReceipt] = useState(null);
  const [receiptPreview, setReceiptPreview] = useState(null);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  // ────── 차량 목록 로드 ──────
  const loadVehicles = () => {
    setLoading(true);
    api.get('/vehicle-logs/vehicles')
      .then(d => setVehicles(d.vehicles || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  // ────── 특정 차량 기록 로드 ──────
  const loadVehicleLogs = (vehicle) => {
    setLoading(true);
    api.get(`/vehicle-logs?vehicle=${encodeURIComponent(vehicle)}&limit=50`)
      .then(d => setVehicleLogs(d.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadVehicles(); }, []);

  // ────── 차량 선택 → 바로 등록 폼 ──────
  const openVehicle = (v) => {
    setSelectedVehicle(v);
    const f = initialForm();
    if (v.last_odometer != null) {
      f.odometer_start = String(v.last_odometer);
    }
    setForm(f);
    setReceipt(null);
    setReceiptPreview(null);
    setView('create');
  };

  // ────── 차량 기록 보기 (별도 진입) ──────
  const openVehicleHistory = (v, ev) => {
    ev.stopPropagation();
    setSelectedVehicle(v);
    loadVehicleLogs(v.name);
    setView('vehicleDetail');
  };

  // ────── 영수증 이미지 처리 ──────
  const onPickReceipt = async (file) => {
    if (!file) { setReceipt(null); setReceiptPreview(null); return; }
    if (file.size > 5 * 1024 * 1024) {
      const resized = await resizeImage(file, 1280);
      setReceipt(resized);
      setReceiptPreview(URL.createObjectURL(resized));
    } else {
      setReceipt(file);
      setReceiptPreview(URL.createObjectURL(file));
    }
  };

  const distance = (() => {
    const s = parseInt(form.odometer_start, 10);
    const e = parseInt(form.odometer_end, 10);
    if (!isNaN(s) && !isNaN(e) && e >= s) return e - s;
    return 0;
  })();

  // ────── 등록 제출 ──────
  const submit = async () => {
    if (!selectedVehicle) return alert('차량 정보가 없습니다');
    if (!form.odometer_end) return alert('주행 후 km을 입력해주세요');
    if (!form.origin || !form.destination || !form.purpose) {
      return alert('출발지/도착지/사용목적을 입력해주세요');
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append('vehicle', selectedVehicle.name);
      Object.entries(form).forEach(([k, v]) => fd.append(k, v == null ? '' : String(v)));
      if (receipt) fd.append('receipt', receipt);
      const token = localStorage.getItem('token');
      const res = await fetch('/api/app/vehicle-logs/create', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || '등록 실패');
      // 등록 성공 → 차량 목록으로 복귀 (다른 차량 등록도 쉽게)
      await api.get('/vehicle-logs/vehicles').then(d => {
        setVehicles(d.vehicles || []);
      });
      setView('vehicleList');
    } catch (e) {
      alert(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ────── 기록 상세 보기 ──────
  const openLogDetail = (id) => {
    api.get(`/vehicle-logs/${id}`)
      .then(d => { setLogDetail(d.item); setView('logDetail'); })
      .catch(e => alert(e.message));
  };

  // ────── 삭제 ──────
  const remove = async (id) => {
    if (!confirm('이 운행일지를 삭제하시겠습니까?')) return;
    try {
      await api.post(`/vehicle-logs/${id}/delete`, {});
      setLogDetail(null);
      loadVehicles();
      if (selectedVehicle) loadVehicleLogs(selectedVehicle.name);
      setView('vehicleDetail');
    } catch (e) {
      alert(e.message);
    }
  };

  // ═══════════════════════════════════════════════════════════════
  // 화면 1: 차량 목록 (홈)
  // ═══════════════════════════════════════════════════════════════
  if (view === 'vehicleList') {
    return (
      <div>
        <div className="channel-header">
          <span className="ch-icon">🚗</span>
          <h1>운행일지</h1>
          <span className="ch-count">{vehicles.length}</span>
        </div>
        <div style={{ padding: '8px 16px', fontSize: 12, color: 'var(--text-muted)' }}>
          차량을 선택해서 기록을 등록하거나 조회하세요
        </div>
        {loading ? (
          <div className="page-loader">불러오는 중...</div>
        ) : vehicles.length === 0 ? (
          <div className="page-empty">등록된 회사 차량이 없습니다</div>
        ) : (
          <div style={{ padding: '4px 12px' }}>
            {vehicles.map(v => (
              <div key={v.name} onClick={() => openVehicle(v)}
                   style={s.vehicleCard}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={s.vehicleIcon}>🚗</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-bright)' }}>
                      {v.name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      {v.last_odometer != null
                        ? `직전 주행 후: ${v.last_odometer.toLocaleString()} km`
                        : '운행 기록 없음 (첫 등록)'}
                    </div>
                  </div>
                  <button onClick={(e) => openVehicleHistory(v, e)}
                          style={s.historyBtn}
                          title="기록 보기">
                    이력
                  </button>
                  <div style={{ fontSize: 18, color: 'var(--accent)', fontWeight: 700 }}>+</div>
                </div>
              </div>
            ))}
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center',
                          padding: '8px 0' }}>
              차량을 누르면 바로 등록 화면으로 이동합니다
            </div>
          </div>
        )}
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════
  // 화면 2: 차량 상세 (해당 차량 운행 기록 + 등록 버튼)
  // ═══════════════════════════════════════════════════════════════
  if (view === 'vehicleDetail' && selectedVehicle) {
    return (
      <div>
        <div className="channel-header">
          <button onClick={() => setView('vehicleList')} style={s.back}>←</button>
          <h1 style={{ fontSize: 14 }}>{selectedVehicle.name}</h1>
          <span className="ch-count">{vehicleLogs.length}</span>
        </div>

        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)',
                      background: 'var(--surface)',
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            직전 주행 후: <strong style={{ color: 'var(--text-bright)' }}>
              {selectedVehicle.last_odometer != null
                ? `${selectedVehicle.last_odometer.toLocaleString()} km`
                : '없음'}
            </strong>
          </div>
          <button onClick={() => openVehicle(selectedVehicle)} style={s.headerLink}>+ 등록</button>
        </div>

        <div className="msg-list">
          {loading ? (
            <div className="page-loader">불러오는 중...</div>
          ) : vehicleLogs.length === 0 ? (
            <div className="page-empty">기록 없음 · 첫 운행을 등록해보세요</div>
          ) : (
            vehicleLogs.map(it => (
              <div key={it.id} className="msg-item"
                   onClick={() => openLogDetail(it.id)}
                   style={{ flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', gap: 10 }}>
                  <div className="indicator" style={{ background: 'var(--accent)' }} />
                  <div className="msg-body">
                    <div className="msg-top">
                      <span className="msg-date">{it.use_date}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {it.distance_km.toLocaleString()}km
                      </span>
                    </div>
                    <div className="msg-title">{it.origin} → {it.destination}</div>
                    <div className="msg-meta">
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{it.purpose}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{it.user_name}</span>
                      {it.fuel_amount > 0 && (
                        <span style={{ fontSize: 11, color: 'var(--orange)' }}>
                          ⛽ {fmt(it.fuel_amount)}원
                        </span>
                      )}
                      {it.has_receipt && (
                        <span style={{ fontSize: 11, color: 'var(--accent)' }}>📷</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════
  // 화면 3: 등록 폼
  // ═══════════════════════════════════════════════════════════════
  if (view === 'create' && selectedVehicle) {
    return (
      <div>
        <div className="channel-header">
          <button onClick={() => setView('vehicleList')} style={s.back}>←</button>
          <h1 style={{ fontSize: 14 }}>{selectedVehicle.name} 등록</h1>
          <button onClick={() => { loadVehicleLogs(selectedVehicle.name); setView('vehicleDetail'); }}
                  style={s.headerLink}>이력</button>
        </div>

        {selectedVehicle.last_odometer != null && (
          <div style={{ padding: '8px 16px', fontSize: 12, color: 'var(--text-muted)',
                        background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
            직전 주행 후: <strong style={{ color: 'var(--text-bright)' }}>
              {selectedVehicle.last_odometer.toLocaleString()} km
            </strong> (자동 채움됨)
          </div>
        )}

        <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div style={s.fl}>사용일자</div>
            <input type="date" value={form.use_date}
                   onChange={e => set('use_date', e.target.value)} style={s.inp} />
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1 }}>
              <div style={s.fl}>주행 전 km</div>
              <input type="number" inputMode="numeric" value={form.odometer_start}
                     onChange={e => set('odometer_start', e.target.value)} style={s.inp}
                     placeholder="자동" />
            </div>
            <div style={{ flex: 1 }}>
              <div style={s.fl}>주행 후 km *</div>
              <input type="number" inputMode="numeric" value={form.odometer_end}
                     onChange={e => set('odometer_end', e.target.value)} style={s.inp}
                     placeholder="필수" />
            </div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--accent)', textAlign: 'right',
                        padding: '0 4px' }}>
            주행거리: <strong>{distance.toLocaleString()} km</strong>
          </div>

          <div>
            <div style={s.fl}>주유금액 (원, 선택)</div>
            <input type="number" inputMode="numeric" value={form.fuel_amount}
                   onChange={e => set('fuel_amount', e.target.value)} style={s.inp}
                   placeholder="0" />
          </div>

          <div>
            <div style={s.fl}>출발지 *</div>
            <input value={form.origin} onChange={e => set('origin', e.target.value)}
                   style={s.inp} placeholder="예: 본사" />
          </div>
          <div>
            <div style={s.fl}>도착지 *</div>
            <input value={form.destination} onChange={e => set('destination', e.target.value)}
                   style={s.inp} placeholder="예: 파주현장" />
          </div>
          <div>
            <div style={s.fl}>사용목적 *</div>
            <textarea value={form.purpose} onChange={e => set('purpose', e.target.value)}
                      style={{ ...s.inp, minHeight: 50 }} rows={2}
                      placeholder="예: 납품 / 측정 / 미팅" />
          </div>

          <div>
            <div style={s.fl}>영수증 사진 (선택)</div>
            <input type="file" accept="image/*"
                   onChange={e => onPickReceipt(e.target.files?.[0])}
                   style={{ ...s.inp, padding: 6 }} />
            {receiptPreview && (
              <img src={receiptPreview} alt="미리보기"
                   style={{ width: '100%', maxHeight: 200, objectFit: 'contain',
                            borderRadius: 6, marginTop: 6 }} />
            )}
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button onClick={submit} disabled={submitting}
                    style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>
              {submitting ? '등록 중...' : '등록'}
            </button>
            <button onClick={() => setView('vehicleList')} style={s.btn}>취소</button>
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════
  // 화면 4: 기록 상세
  // ═══════════════════════════════════════════════════════════════
  if (view === 'logDetail' && logDetail) {
    const token = localStorage.getItem('token');
    const receiptUrl = logDetail.receipt_url
      ? `${logDetail.receipt_url}?token=${encodeURIComponent(token)}`
      : null;
    return (
      <div>
        <div className="channel-header">
          <button onClick={() => { setLogDetail(null); setView('vehicleDetail'); }} style={s.back}>←</button>
          <h1 style={{ fontSize: 13 }}>{logDetail.vehicle} · {logDetail.use_date}</h1>
        </div>
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={s.secTitle}>운행 정보</div>
          <Row label="사용일자" value={logDetail.use_date} />
          <Row label="차량" value={logDetail.vehicle} />
          <Row label="부서/성명" value={`${logDetail.user_department || ''} ${logDetail.user_name}`} />
          <Row label="주행 전 km" value={fmt(logDetail.odometer_start)} />
          <Row label="주행 후 km" value={fmt(logDetail.odometer_end)} />
          <Row label="주행거리" value={`${fmt(logDetail.distance_km)} km`} />
          <Row label="주유금액" value={logDetail.fuel_amount ? `${fmt(logDetail.fuel_amount)} 원` : '-'} />
          <Row label="출발지" value={logDetail.origin} />
          <Row label="도착지" value={logDetail.destination} />
          <Row label="사용목적" value={logDetail.purpose} />
        </div>
        {receiptUrl && (
          <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
            <div style={s.secTitle}>영수증</div>
            <img src={receiptUrl} alt="영수증"
                 style={{ width: '100%', borderRadius: 6, marginTop: 6 }} />
          </div>
        )}
        {logDetail.is_mine && (
          <div style={{ padding: '12px 16px' }}>
            <button onClick={() => remove(logDetail.id)} style={s.dangerBtn}>삭제</button>
          </div>
        )}
      </div>
    );
  }

  return <div className="page-loader">로딩...</div>;
}

function Row({ label, value }) {
  if (value == null || value === '') return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between',
                  padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--text-bright)', fontWeight: 500,
                     maxWidth: '65%', textAlign: 'right' }}>{value}</span>
    </div>
  );
}

function resizeImage(file, maxWidth) {
  return new Promise((resolve) => {
    const img = new Image();
    const reader = new FileReader();
    reader.onload = (e) => { img.src = e.target.result; };
    img.onload = () => {
      const ratio = Math.min(1, maxWidth / img.width);
      const w = Math.round(img.width * ratio);
      const h = Math.round(img.height * ratio);
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(img, 0, 0, w, h);
      canvas.toBlob((blob) => {
        const out = new File([blob], file.name, { type: 'image/jpeg' });
        resolve(out);
      }, 'image/jpeg', 0.85);
    };
    reader.readAsDataURL(file);
  });
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  secTitle: { fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
              textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)',
         border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  btn: { flex: 1, padding: '10px', borderRadius: 6, fontSize: 13, fontWeight: 600,
         cursor: 'pointer', border: 'none', background: 'var(--surface)',
         color: 'var(--text-muted)', textAlign: 'center' },
  addBtn: { width: '100%', padding: '12px', borderRadius: 6, background: 'var(--accent)',
            color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer',
            border: 'none', textAlign: 'center' },
  dangerBtn: { width: '100%', padding: 12, borderRadius: 6, border: 'none',
               background: 'rgba(242,63,67,0.15)', color: 'var(--red)',
               fontSize: 14, fontWeight: 600, cursor: 'pointer' },
  vehicleCard: { padding: '14px 16px', borderRadius: 10, background: 'var(--surface)',
                 border: '1px solid var(--border)', marginBottom: 8, cursor: 'pointer' },
  vehicleIcon: { width: 40, height: 40, borderRadius: 8, background: 'var(--bg)',
                 display: 'flex', alignItems: 'center', justifyContent: 'center',
                 fontSize: 20 },
  historyBtn: { background: 'var(--bg)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', fontSize: 11, fontWeight: 600,
                padding: '4px 10px', borderRadius: 14, cursor: 'pointer' },
  headerLink: { background: 'none', border: 'none', color: 'var(--accent)',
                fontSize: 13, fontWeight: 600, cursor: 'pointer', padding: 0 },
};
