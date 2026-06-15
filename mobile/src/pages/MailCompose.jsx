import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../hooks/useAuth';

function escapeHtml(s) {
  return (s || '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

function plainToHtml(text) {
  return escapeHtml(text).replace(/\n/g, '<br>');
}

// 원본 메일을 인용문으로 변환 (plain text quote)
function buildQuote(orig) {
  if (!orig) return '';
  const from = orig.from?.name ? `${orig.from.name} <${orig.from.email || ''}>` : (orig.from?.email || '');
  const head = `\n\n---------- 원본 메일 ----------\nFrom: ${from}\nDate: ${orig.date || ''}\nSubject: ${orig.subject || ''}\n\n`;
  const text = orig.text_body || (orig.html_body || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '');
  return head + text;
}

export default function MailCompose() {
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const accountIdParam = Number(sp.get('account')) || null;
  const folder = sp.get('folder') || 'INBOX';
  const replyUid = sp.get('reply_uid');
  const replyAll = sp.get('reply_all') === '1';
  const forwardUid = sp.get('forward_uid');
  const sourceUid = replyUid || forwardUid;
  const user = useAuth((s) => s.user);

  const [accounts, setAccounts] = useState([]);
  const [fromAccount, setFromAccount] = useState(null);
  const [to, setTo] = useState('');
  const [cc, setCc] = useState('');
  const [bcc, setBcc] = useState('');
  const [showCcBcc, setShowCcBcc] = useState(false);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [signature, setSignature] = useState('');
  const [files, setFiles] = useState([]);
  const [forwardSrc, setForwardSrc] = useState(null);
  const [sending, setSending] = useState(false);
  const [loadingOrig, setLoadingOrig] = useState(!!sourceUid);

  // 계정 + 서명 로드
  useEffect(() => {
    Promise.all([
      api.get('/mail/api/accounts', { absolute: true }).catch(() => ({ accounts: [] })),
      api.get('/mail/api/user-signature', { absolute: true }).catch(() => ({ html: '' })),
    ]).then(([accRes, sigRes]) => {
      const list = accRes.accounts || [];
      setAccounts(list);
      const saved = Number(localStorage.getItem('mail_account_id') || 0);
      const initial = list.find((a) => a.id === accountIdParam)
        || list.find((a) => a.id === saved)
        || list[0];
      if (initial) setFromAccount(initial.id);
      setSignature(sigRes.html || '');
    });
  }, [accountIdParam]);

  // 답장/전달 원본 로드
  useEffect(() => {
    if (!sourceUid || !accountIdParam) return;
    setLoadingOrig(true);
    api.get(
      `/mail/api/messages/${sourceUid}?folder=${encodeURIComponent(folder)}&account=${accountIdParam}`,
      { absolute: true },
    )
      .then((r) => {
        if (replyUid) {
          setTo(r.from?.email || '');
          if (replyAll) {
            const myEmail = (user?.username && '@') ? `${user.username}@mgnt.kr`.toLowerCase() : '';
            const others = [...(r.to || []), ...(r.cc || [])]
              .map((a) => a.email)
              .filter((e) => e && e.toLowerCase() !== myEmail && e.toLowerCase() !== (r.from?.email || '').toLowerCase());
            setCc(others.join(', '));
            setShowCcBcc(others.length > 0);
          }
          const sub = r.subject || '';
          setSubject(/^re:/i.test(sub) ? sub : `Re: ${sub}`);
        } else if (forwardUid) {
          const sub = r.subject || '';
          setSubject(/^fwd?:/i.test(sub) ? sub : `Fwd: ${sub}`);
          if (r.attachments?.length) {
            setForwardSrc({
              uid: Number(forwardUid),
              account_id: accountIdParam,
              folder,
              parts: r.attachments.map((a) => a.part_id),
              filenames: r.attachments.map((a) => a.filename),
            });
          }
        }
        setBody(buildQuote(r));
      })
      .catch((e) => alert('원본 로드 실패: ' + e.message))
      .finally(() => setLoadingOrig(false));
  }, [sourceUid, replyAll, forwardUid, replyUid, accountIdParam, folder, user?.username]);

  const onPickFiles = (e) => {
    const picked = Array.from(e.target.files || []);
    setFiles((prev) => [...prev, ...picked]);
    e.target.value = '';
  };

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));
  const removeForwardAttachment = (idx) => {
    if (!forwardSrc) return;
    setForwardSrc({
      ...forwardSrc,
      parts: forwardSrc.parts.filter((_, i) => i !== idx),
      filenames: forwardSrc.filenames.filter((_, i) => i !== idx),
    });
  };

  const totalSize = useMemo(
    () => files.reduce((s, f) => s + (f.size || 0), 0),
    [files],
  );

  const submit = async () => {
    if (sending) return;
    if (!fromAccount) { alert('보낸사람 계정을 선택하세요.'); return; }
    if (!to.trim()) { alert('받는 사람을 입력하세요.'); return; }
    if (totalSize > 24 * 1024 * 1024) {
      if (!confirm('첨부 합계가 24MB를 초과합니다. 그래도 전송할까요? (메일 서버가 거절할 수 있습니다)')) return;
    }
    setSending(true);
    try {
      const fd = new FormData();
      fd.append('account_id', String(fromAccount));
      fd.append('to', to);
      fd.append('cc', cc);
      fd.append('bcc', bcc);
      fd.append('subject', subject);
      const bodyHtml = plainToHtml(body) + (signature ? `<br><br>${signature}` : '');
      fd.append('body', bodyHtml);
      for (const f of files) fd.append('attachments', f);
      if (forwardSrc && forwardSrc.parts.length) {
        fd.append('forward_source_uid', String(forwardSrc.uid));
        fd.append('forward_account_id', String(forwardSrc.account_id));
        fd.append('forward_folder', forwardSrc.folder);
        fd.append('forward_parts', JSON.stringify(forwardSrc.parts));
      }
      await api.postForm('/mail/api/send', fd, { absolute: true });
      alert('메일을 발송했습니다.');
      navigate('/mail');
    } catch (e) {
      alert('발송 실패: ' + e.message);
    } finally {
      setSending(false);
    }
  };

  if (loadingOrig) return <div className="page-loader">원본 메일 불러오는 중…</div>;

  return (
    <div style={{ paddingBottom: 80 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.iconBtn} aria-label="뒤로">←</button>
        <h1 style={{ flex: 1 }}>
          {replyUid ? (replyAll ? '전체답장' : '답장') : forwardUid ? '전달' : '새 메일'}
        </h1>
        <button onClick={submit} disabled={sending} style={s.sendBtn}>
          {sending ? '발송 중…' : '보내기'}
        </button>
      </div>

      {/* 보낸사람 */}
      <div style={s.row}>
        <label style={s.label}>보낸사람</label>
        <select
          value={fromAccount ?? ''}
          onChange={(e) => setFromAccount(Number(e.target.value))}
          style={s.input}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.is_shared ? '📮 ' : ''}{a.display_name ? `${a.display_name} <${a.email}>` : a.email}
            </option>
          ))}
        </select>
      </div>

      {/* 받는사람 */}
      <div style={s.row}>
        <label style={s.label}>받는사람</label>
        <input
          type="text"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="콤마(,)로 구분"
          style={s.input}
        />
      </div>

      {!showCcBcc && (
        <div style={{ padding: '0 14px 6px' }}>
          <button onClick={() => setShowCcBcc(true)} style={s.linkBtn}>+ 참조 / 숨은참조</button>
        </div>
      )}
      {showCcBcc && (
        <>
          <div style={s.row}>
            <label style={s.label}>참조</label>
            <input type="text" value={cc} onChange={(e) => setCc(e.target.value)} placeholder="CC" style={s.input} />
          </div>
          <div style={s.row}>
            <label style={s.label}>숨은참조</label>
            <input type="text" value={bcc} onChange={(e) => setBcc(e.target.value)} placeholder="BCC" style={s.input} />
          </div>
        </>
      )}

      {/* 제목 */}
      <div style={s.row}>
        <label style={s.label}>제목</label>
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="제목"
          style={{ ...s.input, fontWeight: 600 }}
        />
      </div>

      {/* 첨부 */}
      <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <label style={s.fileBtn}>
            📎 파일
            <input type="file" multiple onChange={onPickFiles} style={{ display: 'none' }} />
          </label>
          <label style={s.fileBtn}>
            📷 사진
            <input type="file" accept="image/*" capture="environment" multiple onChange={onPickFiles} style={{ display: 'none' }} />
          </label>
          {files.length > 0 && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {files.length}개 · {(totalSize / 1024 / 1024).toFixed(1)}MB
            </span>
          )}
        </div>
        {files.map((f, i) => (
          <div key={i} style={s.fileItem}>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {f.name}
            </span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{(f.size / 1024).toFixed(1)}KB</span>
            <button onClick={() => removeFile(i)} style={s.removeX}>×</button>
          </div>
        ))}
        {forwardSrc?.parts?.length > 0 && forwardSrc.filenames.map((fn, i) => (
          <div key={`fwd-${i}`} style={{ ...s.fileItem, opacity: 0.85 }}>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              📨 {fn} <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>(원본)</span>
            </span>
            <button onClick={() => removeForwardAttachment(i)} style={s.removeX}>×</button>
          </div>
        ))}
      </div>

      {/* 본문 */}
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="내용"
        style={s.textarea}
      />

      {signature && (
        <div style={s.sigPreview}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>— 자동 서명 미리보기 —</div>
          <div dangerouslySetInnerHTML={{ __html: signature }} />
        </div>
      )}
    </div>
  );
}

const s = {
  iconBtn: {
    width: 32, height: 32, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: 'transparent', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text)', fontSize: 16, cursor: 'pointer',
  },
  sendBtn: {
    padding: '6px 14px', background: 'var(--accent)', color: '#fff',
    border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 700, cursor: 'pointer',
  },
  row: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '6px 14px', borderBottom: '1px solid var(--border)',
  },
  label: { width: 64, fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 },
  input: {
    flex: 1, padding: '8px 10px', fontSize: 13,
    background: 'var(--bg, #1c1e21)', color: 'var(--text)',
    border: '1px solid var(--border)', borderRadius: 6,
  },
  linkBtn: {
    padding: '6px 0', background: 'transparent', border: 'none',
    color: 'var(--accent)', fontSize: 11, cursor: 'pointer',
  },
  fileBtn: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '6px 10px', fontSize: 12, fontWeight: 600,
    background: 'var(--surface)', color: 'var(--accent)',
    border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer',
  },
  fileItem: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '6px 8px', marginTop: 6,
    background: 'var(--bg, #1c1e21)', border: '1px solid var(--border)', borderRadius: 6,
    fontSize: 12, color: 'var(--text)',
  },
  removeX: {
    width: 20, height: 20, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: 'transparent', border: 'none', color: 'var(--text-muted)',
    fontSize: 16, cursor: 'pointer', lineHeight: 1,
  },
  textarea: {
    width: '100%', minHeight: 240, padding: 14,
    background: 'transparent', color: 'var(--text)', border: 'none',
    fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit', resize: 'vertical',
    outline: 'none', boxSizing: 'border-box',
  },
  sigPreview: {
    padding: '10px 14px', margin: '10px 14px', borderTop: '1px dashed var(--border)',
    fontSize: 12, color: 'var(--text-muted)',
  },
};
