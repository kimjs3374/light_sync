import { useEffect, useRef, useState } from 'react';
import { useMail } from '../store/mail';
import { api } from '../api/client';
import { useCompose } from '../store/compose';
import { Star, Paperclip, External, Users, Mail } from './Icons';

/** 안읽음 뱃지는 지금 보고 있는 폴더 기준 — 필터도 그 폴더 안에서 걸린다 */
function useFolderUnread() {
  const { folders, folder } = useMail();
  return folders.find((f) => f.name === folder)?.unread || 0;
}

function AccountPicker({ open, onClose }) {
  const { accounts, accountId, switchAccount } = useMail();
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    // 클릭이 열자마자 닫히지 않도록 다음 틱부터 듣는다
    const t = setTimeout(() => document.addEventListener('mousedown', onDown), 0);
    document.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="account-picker" ref={ref} role="listbox">
      {accounts.map((a) => (
        <button
          key={a.id}
          className={`picker-item${a.id === accountId ? ' active' : ''}`}
          role="option"
          aria-selected={a.id === accountId}
          onClick={() => {
            if (!useCompose.getState().close()) return;
            switchAccount(a.id);
            onClose();
          }}
        >
          <span className="picker-icon">
            {a.account_type === 'external' ? <External size={13} />
              : a.is_shared ? <Users size={13} /> : <Mail size={13} />}
          </span>
          <span className="picker-text">
            <span className="picker-email">{a.email}</span>
            {(a.display_name || a.is_shared) && (
              <span className="picker-sub">
                {a.display_name || (a.is_shared ? '공용계정' : '')}
              </span>
            )}
          </span>
          {a.id === accountId && <span className="picker-check">✓</span>}
        </button>
      ))}
    </div>
  );
}

export default function AccountCard() {
  const s = useMail();
  const [pickerOpen, setPickerOpen] = useState(false);
  const unread = useFolderUnread();

  const account = s.accounts.find((a) => a.id === s.accountId);
  const user = api.user || {};
  // 실제로 메일 헤더(From)에 실려 나가는 이름을 보여준다 — ERP 계정 이름이 아니라
  // 이 메일 계정의 발송자 이름이라야 "내가 누구로 보이는가"와 화면이 일치한다.
  const senderName = account?.display_name
    || user.full_name
    || (account?.email || '').split('@')[0];

  /** 같은 필터를 다시 누르면 전체로 돌아온다 */
  const toggle = (key) => {
    if (!useCompose.getState().close()) return;   // 쓰던 메일이 있으면 먼저 물어본다
    s.setQuickFilter(s.quickFilter === key ? 'all' : key);
  };

  const FILTERS = [
    { key: 'unread', label: '안읽음', icon: <span className="fi-dot" />, badge: unread || null },
    { key: 'flagged', label: '중요', icon: <Star size={12} /> },
    { key: 'attach', label: '첨부', icon: <Paperclip size={12} /> },
  ];

  return (
    <div className="account-card">
      <div className="card-identity">
        <div className="identity-name" title="이 계정으로 보낼 때 표시되는 이름">
          {senderName || '사용자'}
        </div>
        <div className="picker-wrap">
          <button
            className={`identity-email${pickerOpen ? ' open' : ''}`}
            onClick={() => setPickerOpen((v) => !v)}
            title="메일 계정 전환"
            aria-haspopup="listbox"
            aria-expanded={pickerOpen}
          >
            <span className="email-text">{account?.email || '계정 없음'}</span>
            {s.accounts.length > 1 && <span className="email-caret" aria-hidden="true">▾</span>}
          </button>
          <AccountPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
        </div>
      </div>

      <div className="card-filters">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`filter-item${s.quickFilter === f.key ? ' on' : ''}`}
            onClick={() => toggle(f.key)}
          >
            <span className="filter-icon">{f.icon}</span>
            <span className="filter-label">{f.label}</span>
            {f.badge ? <span className="filter-badge">{f.badge}</span> : null}
          </button>
        ))}
      </div>

      <div className="compose-actions">
        <button className="btn-compose" onClick={() => useCompose.getState().open('new')}>
          메일 쓰기
        </button>
        <button className="btn-self" onClick={() => useCompose.getState().open('self')}
          title="내 주소로 보내기">
          내게 쓰기
        </button>
      </div>
    </div>
  );
}
