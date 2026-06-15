import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

/**
 * 거래처 상세 — ERP vendor_detail.html 과 1:1 동일
 * - 기본정보 (업체명/대표자/사업자번호/업종/종목/전화/팩스/이메일/주소/상태)
 * - 거래 통계 (발주 건수/총액, 입고 건수/총액, 최근거래)
 * - 탭: 발주이력 / 입고이력 / 업체 메모
 * - 편집 모달: 전체 필드 수정
 */

function money(v) {
  if (!v) return '0';
  try { return Number(v).toLocaleString(); } catch { return String(v); }
}

export default function VendorDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('po'); // 'po' | 'rcv' | 'note'
  const [expanded, setExpanded] = useState({}); // {key: true}
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [note, setNote] = useState('');
  const [noteSaved, setNoteSaved] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/vendors/${id}`)
      .then((d) => {
        if (d.vendor) {
          setData(d);
          setNote(d.vendor.note || '');
        } else {
          setData(null);
        }
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const saveEdit = async () => {
    try {
      await api.post(`/vendors/${id}/edit`, form);
      setEditing(false);
      load();
    } catch (e) { alert(e.message); }
  };

  const saveNote = async () => {
    try {
      await api.post(`/vendors/${id}/note`, { note });
      setNoteSaved(true);
      setTimeout(() => setNoteSaved(false), 2000);
      setData(prev => prev ? { ...prev, vendor: { ...prev.vendor, note } } : prev);
    } catch (e) { alert(e.message); }
  };

  const deleteVendor = async () => {
    if (!confirm('정말 이 거래처를 삭제하시겠습니까?')) return;
    try {
      await api.post(`/vendors/${id}/delete`, {});
      navigate('/vendors');
    } catch (e) { alert(e.message); }
  };

  const toggleActive = async () => {
    try {
      await api.post(`/vendors/${id}/edit`, { is_active: !data.vendor.is_active });
      load();
    } catch (e) { alert(e.message); }
  };

  if (loading) return <div className="page-loader">불러오는 중...</div>;
  if (!data) return <div className="page-loader">거래처를 찾을 수 없습니다</div>;

  const v = data.vendor;
  const pos = data.purchase_orders || [];
  const rcvs = data.receivings || [];
  const stats = data.trade_stats || {};

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.back}>←</button>
        <h1>{v.name}</h1>
      </div>

      {/* 헤더 정보 */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-bright)' }}>{v.name}</span>
          <span className={`badge badge-${v.is_active ? 'green' : 'gray'}`}>
            {v.is_active ? '사용' : '미사용'}
          </span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          코드: {v.icube_tr_cd || v.id}
        </div>
      </div>

      {/* 거래 통계 */}
      <Sec title="거래 통계">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <StatBox label="발주 건수" value={stats.po_count || 0} color="blue" />
          <StatBox label="발주 총액" value={`${money(stats.po_total)}원`} color="blue" big />
          <StatBox label="입고 건수" value={stats.rcv_count || 0} color="green" />
          <StatBox label="입고 총액" value={`${money(stats.rcv_total)}원`} color="green" big />
        </div>
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
          최근 발주: {stats.last_po_date || '-'} · 최근 입고: {stats.last_rcv_date || '-'}
        </div>
      </Sec>

      {/* 기본정보 */}
      <Sec title="기본정보">
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              ['name', '거래처명 *'],
              ['ceo_name', '대표자'],
              ['business_no', '사업자번호'],
              ['business', '업종'],
              ['jongmok', '종목'],
              ['tel', '전화'],
              ['fax', '팩스'],
              ['email', '이메일'],
              ['address', '주소'],
            ].map(([k, l]) => (
              <div key={k}>
                <div style={s.fl}>{l}</div>
                <input value={form[k] || ''}
                  onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))}
                  style={s.inp} />
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button onClick={saveEdit} style={{ ...s.btn, background: 'var(--accent)', color: '#fff' }}>저장</button>
              <button onClick={() => setEditing(false)} style={s.btn}>취소</button>
            </div>
          </div>
        ) : (
          <>
            <Row label="대표자" value={v.ceo_name} />
            <Row label="사업자번호" value={v.business_no} mono />
            <Row label="업종" value={v.business} />
            <Row label="종목" value={v.jongmok} />
            <Row label="전화" value={v.tel} />
            <Row label="팩스" value={v.fax} />
            <Row label="이메일" value={v.email} />
            <Row label="주소" value={v.address} />
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button onClick={() => { setForm({
                name: v.name || '',
                ceo_name: v.ceo_name || '',
                business_no: v.business_no || '',
                business: v.business || '',
                jongmok: v.jongmok || '',
                tel: v.tel || '',
                fax: v.fax || '',
                email: v.email || '',
                address: v.address || '',
              }); setEditing(true); }}
                style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)' }}>수정</button>
              <button onClick={toggleActive} style={s.btn}>
                {v.is_active ? '미사용 전환' : '사용 전환'}
              </button>
              <button onClick={deleteVendor} style={{ ...s.btn, color: 'var(--red)' }}>삭제</button>
            </div>
          </>
        )}
      </Sec>

      {/* 탭 */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
        {[
          { key: 'po', label: `발주이력 ${stats.po_count || 0}` },
          { key: 'rcv', label: `입고이력 ${stats.rcv_count || 0}` },
          { key: 'note', label: '업체 메모' },
        ].map(t => (
          <button key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              flex: 1, padding: '10px 0', border: 'none',
              background: 'transparent',
              color: tab === t.key ? 'var(--text-bright)' : 'var(--text-muted)',
              fontWeight: tab === t.key ? 700 : 500,
              borderBottom: tab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              fontSize: 13, cursor: 'pointer',
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* 탭 내용 */}
      <div style={{ padding: '8px 0' }}>
        {tab === 'po' && (
          pos.length === 0 ? (
            <div className="page-empty">발주 이력이 없습니다.</div>
          ) : pos.map((po, i) => {
            const key = `po-${i}`;
            const open = expanded[key];
            return (
              <div key={key} style={{ borderBottom: '1px solid var(--border)' }}>
                <div onClick={() => setExpanded(e => ({ ...e, [key]: !e[key] }))}
                  style={{ padding: '10px 16px', cursor: 'pointer' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                    <span style={{
                      fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
                      color: po.po_id ? 'var(--accent)' : po.fo_id ? '#0891b2' : 'var(--text-muted)',
                    }}>{po.CLS_NB}</span>
                    {po.fo_id && <span className="badge badge-purple">가공</span>}
                    {po.source === 'icube' && <span className="badge badge-gray">iCUBE</span>}
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{po.CLS_DT}</span>
                    <span style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>
                      {money(po.total)}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {po.detail_rows?.[0] ? (po.detail_rows[0].ITEM_NM || po.detail_rows[0].ITEM_CD) : ''}
                    {po.detail_rows?.length > 1 && <span style={{ color: 'var(--text-muted)' }}> 외 {po.detail_rows.length - 1}건</span>}
                  </div>
                </div>
                {open && (
                  <div style={{ padding: '6px 16px 12px', background: 'var(--bg)' }}>
                    {po.detail_rows.map((it, j) => (
                      <div key={j} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '3px 0', borderBottom: '1px dashed var(--border)' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {it.ITEM_NM || it.ITEM_CD}
                          </div>
                          {it.ITEM_DC && <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{it.ITEM_DC}</div>}
                        </div>
                        <div style={{ textAlign: 'right', marginLeft: 8, fontFamily: 'monospace', flexShrink: 0 }}>
                          <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{money(it.CLS_QT)} × {money(it.CLS_UM)}</div>
                          <div style={{ color: 'var(--text-bright)', fontWeight: 700 }}>{money(it.CLSH_AM)}</div>
                        </div>
                      </div>
                    ))}
                    {po.REMARK_DC && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>비고: {po.REMARK_DC}</div>}
                    {po.po_id && (
                      <button onClick={(e) => { e.stopPropagation(); navigate(`/purchase-orders/${po.po_id}`); }}
                        style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)', marginTop: 6, width: '100%' }}>
                        발주서 열기 →
                      </button>
                    )}
                    {po.fo_id && (
                      <button onClick={(e) => { e.stopPropagation(); navigate(`/processing-orders/${po.fo_id}`); }}
                        style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)', marginTop: 6, width: '100%' }}>
                        가공발주 열기 →
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}

        {tab === 'rcv' && (
          rcvs.length === 0 ? (
            <div className="page-empty">입고 이력이 없습니다.</div>
          ) : rcvs.map((rcv, i) => {
            const key = `rcv-${i}`;
            const open = expanded[key];
            return (
              <div key={key} style={{ borderBottom: '1px solid var(--border)' }}>
                <div onClick={() => setExpanded(e => ({ ...e, [key]: !e[key] }))}
                  style={{ padding: '10px 16px', cursor: 'pointer' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                    <span style={{
                      fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
                      color: rcv.rcv_id ? 'var(--green)' : 'var(--text-muted)',
                    }}>{rcv.RCV_NB}</span>
                    {rcv.source === 'icube' && <span className="badge badge-gray">iCUBE</span>}
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{rcv.RCV_DT}</span>
                    <span style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>
                      {money(rcv.total)}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {rcv.detail_rows?.[0] ? (rcv.detail_rows[0].ITEM_NM || rcv.detail_rows[0].ITEM_CD) : ''}
                    {rcv.detail_rows?.length > 1 && <span> 외 {rcv.detail_rows.length - 1}건</span>}
                  </div>
                </div>
                {open && (
                  <div style={{ padding: '6px 16px 12px', background: 'var(--bg)' }}>
                    {rcv.detail_rows.map((it, j) => (
                      <div key={j} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '3px 0', borderBottom: '1px dashed var(--border)' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {it.ITEM_NM || it.ITEM_CD}
                          </div>
                          {it.ITEM_DC && <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{it.ITEM_DC}</div>}
                        </div>
                        <div style={{ textAlign: 'right', marginLeft: 8, fontFamily: 'monospace', flexShrink: 0 }}>
                          <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{money(it.RCV_QT)} × {money(it.RCV_UM)}</div>
                          <div style={{ color: 'var(--text-bright)', fontWeight: 700 }}>{money(it.RCVH_AM)}</div>
                        </div>
                      </div>
                    ))}
                    {rcv.rcv_id && (
                      <button onClick={(e) => { e.stopPropagation(); navigate(`/receivings/${rcv.rcv_id}`); }}
                        style={{ ...s.btn, background: 'var(--surface)', color: 'var(--accent)', marginTop: 6, width: '100%' }}>
                        입고 열기 →
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}

        {tab === 'note' && (
          <div style={{ padding: '10px 16px' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              업체 메모 (담당자재, 특이사항 등)
            </div>
            <textarea value={note} onChange={e => setNote(e.target.value)}
              rows={5}
              placeholder="예: 케이블류 납품, CV/VCTF 전선. 담당자 김과장 010-1234-5678"
              style={{ ...s.inp, resize: 'vertical', minHeight: 100 }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              <button onClick={saveNote} style={{ ...s.btn, background: 'var(--accent)', color: '#fff', width: 100 }}>저장</button>
              {noteSaved && <span style={{ fontSize: 11, color: 'var(--green)' }}>저장됨</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Sec({ title, children }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value, mono }) {
  if (!value) return null;
  return (
    <div style={s.row}>
      <span style={s.rowL}>{label}</span>
      <span style={{ ...s.rowV, ...(mono ? { fontFamily: 'monospace' } : {}) }}>{value}</span>
    </div>
  );
}

function StatBox({ label, value, color, big }) {
  return (
    <div style={{
      background: 'var(--surface)', borderRadius: 6, padding: 10,
      borderLeft: `3px solid var(--${color})`,
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      <div style={{
        fontSize: big ? 14 : 18,
        fontWeight: 700,
        color: `var(--${color})`,
        fontFamily: big ? 'monospace' : 'inherit',
      }}>{value}</div>
    </div>
  );
}

const s = {
  back: { background: 'none', border: 'none', color: 'var(--accent)', fontSize: 16, cursor: 'pointer' },
  btn: { flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', border: 'none', textAlign: 'center', background: 'var(--surface)', color: 'var(--text-muted)' },
  row: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  rowL: { fontSize: 12, color: 'var(--text-muted)' },
  rowV: { fontSize: 12, color: 'var(--text-bright)', fontWeight: 500, maxWidth: '65%', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  fl: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 },
  inp: { width: '100%', padding: '9px 12px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 },
};
