import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const FOLDERS = [
  { key: 'INBOX', label: '받은' },
  { key: 'Sent', label: '보낸' },
  { key: 'Drafts', label: '임시' },
  { key: 'Trash', label: '휴지통' },
];

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  const y = d.getFullYear() === now.getFullYear();
  if (y) return `${d.getMonth() + 1}/${d.getDate()}`;
  return `${d.getFullYear() % 100}/${d.getMonth() + 1}/${d.getDate()}`;
}

export default function MailInbox() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState(null);
  const [folder, setFolder] = useState('INBOX');
  const [messages, setMessages] = useState([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const seenKey = useRef('');

  // 계정 목록
  useEffect(() => {
    api.get('/mail/api/accounts', { absolute: true })
      .then((r) => {
        const list = r.accounts || [];
        setAccounts(list);
        const saved = Number(localStorage.getItem('mail_account_id') || 0);
        const initial = list.find((a) => a.id === saved)?.id ?? list[0]?.id ?? null;
        if (initial) setAccountId(initial);
      })
      .catch((e) => setError(e.message));
  }, []);

  // 메시지 로드
  const fetchPage = useCallback(async (p, append) => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.get(
        `/mail/api/messages?folder=${encodeURIComponent(folder)}&account=${accountId}&page=${p}&per_page=30`,
        { absolute: true },
      );
      const list = r.messages || [];
      setMessages((prev) => (append ? [...prev, ...list] : list));
      setPage(r.page || p);
      setPages(r.pages || 1);
      setTotal(r.total || 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [accountId, folder]);

  // accountId / folder 가 바뀌면 1페이지부터 다시
  useEffect(() => {
    if (!accountId) return;
    const key = `${accountId}|${folder}`;
    if (seenKey.current === key) return;
    seenKey.current = key;
    setMessages([]);
    setPage(1);
    setPages(1);
    setTotal(0);
    fetchPage(1, false);
  }, [accountId, folder, fetchPage]);

  const onChangeAccount = (id) => {
    localStorage.setItem('mail_account_id', String(id));
    setAccountId(id);
  };

  const openMessage = (uid) => {
    navigate(`/mail/read/${uid}?account=${accountId}&folder=${encodeURIComponent(folder)}`);
  };

  const refresh = () => {
    seenKey.current = '';   // useEffect 재실행 유도
    fetchPage(1, false);
  };

  return (
    <div style={{ paddingBottom: 100 }}>
      <div className="channel-header">
        <button onClick={() => navigate(-1)} style={s.iconBtn} aria-label="뒤로">←</button>
        <span className="ch-icon">📧</span>
        <h1 style={{ flex: 1 }}>메일</h1>
        <button onClick={refresh} style={s.iconBtn} disabled={loading} aria-label="새로고침">⟳</button>
        <button
          onClick={() => navigate(`/mail/compose?account=${accountId ?? ''}`)}
          style={{ ...s.iconBtn, color: 'var(--accent)' }}
          disabled={!accountId}
          aria-label="새 메일"
        >✎</button>
      </div>

      {/* 계정 드롭다운 */}
      <div style={s.accountBar}>
        <select
          value={accountId ?? ''}
          onChange={(e) => onChangeAccount(Number(e.target.value))}
          style={s.accountSelect}
          disabled={!accounts.length}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.is_shared ? '📮 ' : ''}{a.display_name ? `${a.display_name} <${a.email}>` : a.email}
            </option>
          ))}
          {!accounts.length && <option value="">계정이 없습니다</option>}
        </select>
      </div>

      {/* 폴더 탭 */}
      <div style={s.tabBar}>
        {FOLDERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFolder(f.key)}
            style={{ ...s.tab, ...(folder === f.key ? s.tabActive : null) }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 상태 */}
      {error && <div style={s.errorBox}>{error}</div>}
      {loading && messages.length === 0 && (
        <div style={s.empty}>불러오는 중…</div>
      )}
      {!loading && !error && messages.length === 0 && (
        <div style={s.empty}>메일이 없습니다</div>
      )}

      {/* 메시지 목록 */}
      <div>
        {messages.map((m) => {
          const unread = !m.is_read;
          const from = m.from?.name || m.from?.email || '(보낸이 없음)';
          return (
            <div key={m.uid} onClick={() => openMessage(m.uid)} style={s.msgRow}>
              <div style={{ ...s.unreadBar, background: unread ? 'var(--accent)' : 'transparent' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={s.msgLine1}>
                  <span style={{ ...s.from, fontWeight: unread ? 700 : 500 }}>{from}</span>
                  <span style={s.date}>{formatDate(m.date)}</span>
                </div>
                <div style={s.msgLine2}>
                  <span style={{ ...s.subject, fontWeight: unread ? 600 : 400 }}>
                    {m.subject || '(제목 없음)'}
                  </span>
                  {m.has_attachment && <span style={s.attach}>📎</span>}
                  {m.is_flagged && <span style={s.flag}>★</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 더 보기 */}
      {messages.length > 0 && page < pages && (
        <div style={{ padding: 12 }}>
          <button
            onClick={() => fetchPage(page + 1, true)}
            disabled={loading}
            style={s.moreBtn}
          >
            {loading ? '불러오는 중…' : `더 보기 (${messages.length}/${total})`}
          </button>
        </div>
      )}
      {messages.length > 0 && page >= pages && (
        <div style={s.endMark}>— 끝 ({total}건) —</div>
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
  accountBar: {
    padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--surface)',
  },
  accountSelect: {
    width: '100%', padding: '8px 10px', fontSize: 13,
    background: 'var(--bg)', color: 'var(--text)',
    border: '1px solid var(--border)', borderRadius: 6,
  },
  tabBar: {
    display: 'flex', gap: 4, padding: '6px 8px', overflowX: 'auto',
    borderBottom: '1px solid var(--border)', background: 'var(--surface)',
  },
  tab: {
    padding: '6px 12px', fontSize: 12, fontWeight: 600,
    background: 'transparent', color: 'var(--text-muted)',
    border: '1px solid var(--border)', borderRadius: 16, cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  tabActive: { color: 'var(--accent)', borderColor: 'var(--accent)' },
  errorBox: { padding: '10px 16px', color: 'var(--red, #e74c3c)', fontSize: 12 },
  empty: { padding: '40px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 },
  msgRow: {
    display: 'flex', alignItems: 'stretch', gap: 8,
    padding: '10px 12px 10px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer',
  },
  unreadBar: { width: 3, alignSelf: 'stretch', borderRadius: 1, marginRight: 8 },
  msgLine1: { display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' },
  from: {
    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    color: 'var(--text-bright, var(--text))', fontSize: 13,
  },
  date: { fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', flexShrink: 0 },
  msgLine2: {
    display: 'flex', alignItems: 'center', gap: 6, marginTop: 2,
  },
  subject: {
    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    color: 'var(--text)', fontSize: 12,
  },
  attach: { fontSize: 11, color: 'var(--text-muted)' },
  flag: { fontSize: 11, color: '#f1c40f' },
  moreBtn: {
    width: '100%', padding: 12, fontSize: 13,
    background: 'var(--surface)', color: 'var(--accent)',
    border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer',
  },
  endMark: { padding: '14px 16px 24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11 },
};
