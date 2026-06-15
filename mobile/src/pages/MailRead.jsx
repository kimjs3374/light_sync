import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';

function buildSrcDoc(mail, dark) {
  // 모바일에서 표가 페이지를 뚫지 않도록 viewport 강제 + 본문 폭 제한.
  // 서버에서 nh3 로 이미 sanitize 됨. iframe sandbox 로 한 번 더 격리.
  const body = mail.html_body
    ? mail.html_body
    : `<pre style="white-space:pre-wrap;font:13px/1.5 -apple-system,system-ui,sans-serif;">${(mail.text_body || '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))}</pre>`;
  // 다크 모드: 텍스트/배경만 반전, 이미지/비디오는 원본 색 유지.
  // filter invert+hue-rotate 트릭은 일부 인라인 색이 어색해질 수 있지만
  // 전체 일관성 위해 채택. 사용자가 토글로 끌 수 있음.
  const darkCss = dark ? `
      html { filter: invert(0.92) hue-rotate(180deg); background:#fff; }
      img, video, picture, svg, [style*="background-image"] {
        filter: invert(1) hue-rotate(180deg);
      }
  ` : '';
  return `<!doctype html><html><head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=3">
    <base target="_blank">
    <style>
      html,body { margin:0; padding:10px 12px; background:#fff; color:#222;
        font:13px/1.6 -apple-system,system-ui,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
        word-break:break-word; overflow-wrap:anywhere; }
      img { max-width:100%; height:auto; }
      table { max-width:100%; }
      a { color:#1a73e8; }
      pre { white-space:pre-wrap; }
      blockquote { border-left:3px solid #ddd; margin:6px 0; padding-left:8px; color:#555; }
      ${darkCss}
    </style>
  </head><body>${body}</body></html>`;
}

function formatAddr(a) {
  if (!a) return '';
  if (typeof a === 'string') return a;
  if (a.name && a.email) return `${a.name} <${a.email}>`;
  return a.email || a.name || '';
}

function formatAddrList(list) {
  if (!list || !list.length) return '';
  return list.map(formatAddr).join(', ');
}

export default function MailRead() {
  const { uid } = useParams();
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const accountId = sp.get('account');
  const folder = sp.get('folder') || 'INBOX';

  const [mail, setMail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showMeta, setShowMeta] = useState(false);
  const [darkBody, setDarkBody] = useState(
    () => localStorage.getItem('mail_body_dark') === '1',
  );
  const toggleDark = () => {
    setDarkBody((v) => {
      const nv = !v;
      localStorage.setItem('mail_body_dark', nv ? '1' : '0');
      return nv;
    });
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.get(
      `/mail/api/messages/${uid}?folder=${encodeURIComponent(folder)}&account=${accountId}`,
      { absolute: true },
    )
      .then((r) => { if (alive) setMail(r); })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [uid, accountId, folder]);

  const srcDoc = useMemo(() => (mail ? buildSrcDoc(mail, darkBody) : ''), [mail, darkBody]);

  const markUnread = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post('/mail/api/flags', {
        uids: [Number(uid)], flag: '\\Seen', action: 'remove',
        folder, account_id: Number(accountId),
      }, { absolute: true });
      navigate(-1);
    } catch (e) {
      alert('실패: ' + e.message);
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (busy) return;
    if (!confirm('이 메일을 휴지통으로 옮길까요?')) return;
    setBusy(true);
    try {
      await api.del('/mail/api/messages', {
        uids: [Number(uid)], folder, account_id: Number(accountId),
      }, { absolute: true });
      navigate(-1);
    } catch (e) {
      alert('삭제 실패: ' + e.message);
    } finally { setBusy(false); }
  };

  const downloadAttachment = async (att) => {
    try {
      const url = `/mail/api/attachment/${uid}/${att.part_id}?folder=${encodeURIComponent(folder)}&account=${accountId}`;
      const blob = await api.fetchBlob(url);
      const obj = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = obj;
      a.download = att.filename || 'attachment';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(obj), 1000);
    } catch (e) {
      alert('다운로드 실패: ' + e.message);
    }
  };

  const downloadAllAttachments = async () => {
    try {
      const subject = (mail.subject || '').replace(/[\\/:*?"<>|\r\n\t]/g, '_').trim().slice(0, 120);
      const url = `/mail/api/attachments-zip/${uid}?folder=${encodeURIComponent(folder)}&account=${accountId}&subject=${encodeURIComponent(mail.subject || '')}`;
      const blob = await api.fetchBlob(url);
      const obj = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = obj;
      a.download = `${subject || `attachments_${uid}`}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(obj), 1000);
    } catch (e) {
      alert('다운로드 실패: ' + e.message);
    }
  };

  const compose = (mode) => {
    const params = new URLSearchParams({ account: String(accountId), folder });
    if (mode === 'reply') params.set('reply_uid', String(uid));
    else if (mode === 'reply_all') {
      params.set('reply_uid', String(uid));
      params.set('reply_all', '1');
    } else if (mode === 'forward') {
      params.set('forward_uid', String(uid));
    }
    navigate(`/mail/compose?${params.toString()}`);
  };

  if (loading) return <div className="page-loader">불러오는 중…</div>;
  if (error) return (
    <div style={{ padding: 16 }}>
      <button onClick={() => navigate(-1)} style={s.iconBtn}>← 뒤로</button>
      <div style={{ marginTop: 16, color: '#e74c3c', fontSize: 13 }}>오류: {error}</div>
    </div>
  );
  if (!mail) return null;

  return (
    <div style={{ paddingBottom: 90 }}>
      {/* 헤더 */}
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.iconBtn} aria-label="뒤로">←</button>
        <h1 style={s.subjectHead}>{mail.subject || '(제목 없음)'}</h1>
        <button
          onClick={toggleDark}
          style={{ ...s.iconBtn, color: darkBody ? 'var(--accent)' : 'var(--text-muted)' }}
          aria-label="본문 다크 토글"
          title={darkBody ? '본문 다크모드 끄기' : '본문 다크모드 켜기'}
        >{darkBody ? '☾' : '☼'}</button>
      </div>

      {/* 메타 (from + 펼치기) */}
      <div style={s.metaBox}>
        <div style={s.metaRow}>
          <span style={s.metaFrom}>{formatAddr(mail.from)}</span>
          <span style={s.metaDate}>{mail.date}</span>
        </div>
        <button onClick={() => setShowMeta(!showMeta)} style={s.metaToggle}>
          {showMeta ? '받는사람 숨기기' : `받는사람 보기 (${(mail.to || []).length + (mail.cc || []).length})`}
        </button>
        {showMeta && (
          <div style={{ marginTop: 6 }}>
            {mail.to?.length > 0 && (
              <div style={s.metaSubLine}><b>받는사람:</b> {formatAddrList(mail.to)}</div>
            )}
            {mail.cc?.length > 0 && (
              <div style={s.metaSubLine}><b>참조:</b> {formatAddrList(mail.cc)}</div>
            )}
          </div>
        )}
      </div>

      {/* 첨부 */}
      {(mail.attachments || []).length > 0 && (
        <div style={s.attachBox}>
          <div style={s.attachTitle}>📎 첨부 ({mail.attachments.length})</div>
          {mail.attachments.length > 1 && (
            <button onClick={downloadAllAttachments} style={s.attachZip}>
              ⬇ 전체 다운로드 (ZIP)
            </button>
          )}
          {mail.attachments.map((a) => (
            <button key={a.part_id} onClick={() => downloadAttachment(a)} style={s.attachItem}>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {a.filename}
              </span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                {a.size ? `${(a.size / 1024).toFixed(1)}KB` : ''}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* 본문 — 다크 페이지 위 카드처럼 분리 */}
      <div style={s.bodyWrap}>
        <iframe
          title="mail-body"
          srcDoc={srcDoc}
          sandbox="allow-same-origin allow-popups"
          style={s.iframe}
        />
      </div>

      {/* 하단 액션바 */}
      <div style={s.actionBar}>
        <button onClick={() => compose('reply')} style={s.actBtn}>↩ 답장</button>
        <button onClick={() => compose('reply_all')} style={s.actBtn}>↩↩ 전체</button>
        <button onClick={() => compose('forward')} style={s.actBtn}>↪ 전달</button>
        <button onClick={markUnread} disabled={busy} style={s.actBtn}>안 읽음</button>
        <button onClick={remove} disabled={busy} style={{ ...s.actBtn, color: '#e74c3c' }}>🗑 삭제</button>
      </div>
    </div>
  );
}

const s = {
  iconBtn: {
    width: 32, height: 32, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: 'transparent', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text)', fontSize: 16, cursor: 'pointer',
  },
  subjectHead: {
    flex: 1, fontSize: 14, fontWeight: 600,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  metaBox: {
    padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface)', fontSize: 12,
  },
  metaRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  metaFrom: {
    fontWeight: 600, color: 'var(--text-bright, var(--text))', fontSize: 13,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  metaDate: { color: 'var(--text-muted)', fontSize: 11, flexShrink: 0 },
  metaToggle: {
    marginTop: 6, padding: 0, background: 'transparent', border: 'none',
    color: 'var(--accent)', fontSize: 11, cursor: 'pointer',
  },
  metaSubLine: { color: 'var(--text-muted)', fontSize: 11, marginTop: 2, wordBreak: 'break-all' },
  attachBox: {
    padding: '8px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface)',
  },
  attachTitle: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 },
  attachItem: {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
    padding: '6px 10px', marginBottom: 4,
    background: 'var(--bg, #1c1e21)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text)', fontSize: 12, cursor: 'pointer', textAlign: 'left',
  },
  attachZip: {
    display: 'block', width: '100%', padding: '7px 10px', marginBottom: 6,
    background: 'var(--accent)', border: 'none', borderRadius: 6,
    color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer', textAlign: 'center',
  },
  bodyWrap: {
    margin: '8px',
    borderRadius: 10,
    background: 'var(--surface)',
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
  },
  iframe: {
    display: 'block',
    width: '100%', height: 'calc(100vh - 310px)', minHeight: 320,
    background: 'transparent', border: 'none',
  },
  actionBar: {
    position: 'fixed', left: 0, right: 0, bottom: 56,
    display: 'flex', gap: 4, padding: '6px 6px',
    background: 'var(--surface)', borderTop: '1px solid var(--border)',
    zIndex: 99,
  },
  actBtn: {
    flex: 1, padding: '8px 0', fontSize: 11, fontWeight: 600,
    background: 'transparent', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text)', cursor: 'pointer',
  },
};
