import { useState } from 'react';
import { useMail, visibleMessages } from '../store/mail';
import { folderLabel, findTrash, findJunk, splitFolders } from '../lib/folders';
import { Refresh, Search as SearchIcon } from './Icons';


const FILTER_LABEL = { unread: '안읽은 메일', flagged: '중요 메일', attach: '첨부 있는 메일' };

export default function Toolbar() {
  const s = useMail();
  const [q, setQ] = useState('');
  const [moveOpen, setMoveOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const n = s.checked.size;
  const visible = visibleMessages(s);
  const trash = findTrash(s.folders);
  const junk = findJunk(s.folders);

  const run = async (fn) => {
    setBusy(true);
    try { await fn(); }
    catch (e) { alert(e.message || '처리하지 못했습니다'); }
    finally { setBusy(false); setMoveOpen(false); }
  };

  const onDelete = () => {
    if (!n) return;
    const inTrash = s.folder === trash;
    const msg = inTrash
      ? `선택한 ${n}통을 완전히 삭제할까요? 되돌릴 수 없습니다.`
      : `선택한 ${n}통을 휴지통으로 옮길까요?`;
    if (!confirm(msg)) return;
    run(s.deleteChecked);
  };

  const { sys, user } = splitFolders(s.folders);
  const moveTargets = [...sys, ...user].filter((f) => f.name !== s.folder);

  return (
    <header className="toolbar">
      <div className="toolbar-row">
        <label className="check-all">
          <input
            type="checkbox"
            checked={visible.length > 0 && visible.every((m) => s.checked.has(m.uid))}
            onChange={s.toggleCheckAll}
          />
        </label>

        {n > 0 ? (
          <div className="bulk-actions">
            <span className="bulk-count">{n}통 선택</span>
            <button disabled={busy} onClick={() => run(() => s.markRead(true))}>읽음</button>
            <button disabled={busy} onClick={() => run(() => s.markRead(false))}>안읽음</button>
            <div className="move-wrap">
              <button disabled={busy} onClick={() => setMoveOpen((v) => !v)}>이동 ▾</button>
              {moveOpen && (
                <div className="move-menu" onMouseLeave={() => setMoveOpen(false)}>
                  {moveTargets.map((f) => (
                    <button key={f.name} onClick={() => run(() => s.moveChecked(f.name))}>
                      {folderLabel(f.name)}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {junk && s.folder !== junk && (
              <button disabled={busy} onClick={() => run(() => s.moveChecked(junk))}>스팸신고</button>
            )}
            <button className="danger" disabled={busy} onClick={onDelete}>삭제</button>
            <button className="plain" onClick={s.clearChecked}>선택해제</button>
          </div>
        ) : (
          <div className="title-area">
            <strong className="folder-title">
              {s.specialView === 'selfbox' ? '내게쓴메일함' : folderLabel(s.folder)}
            </strong>
            <span className="count">
              {s.searchQuery ? `검색 ${s.total}건` : `${s.total}통`}
            </span>
            {/* 필터는 왼쪽 카드에 있다 — 켜져 있다는 사실은 여기서도 보여야 한다 */}
            {s.quickFilter !== 'all' && (
              <button className="active-filter" onClick={() => s.setQuickFilter('all')}
                title="필터 해제">
                {FILTER_LABEL[s.quickFilter]}
                {s.quickFilter === 'attach' && <em> · 현재 쪽에서만</em>}
                <span className="af-x">✕</span>
              </button>
            )}
          </div>
        )}

        <div className="toolbar-right">
          <form
            className="search"
            onSubmit={(e) => { e.preventDefault(); s.search(q); }}
          >
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`${s.specialView === 'selfbox' ? '내게쓴메일함' : folderLabel(s.folder)}에서 검색`}
            />
            {s.searchQuery && (
              <button type="button" className="search-clear" title="검색 해제"
                onClick={() => { setQ(''); s.search(''); }}>✕</button>
            )}
            <button type="submit" title="검색"><SearchIcon /></button>
          </form>

          <button className="icon-btn" title="새로고침" disabled={s.listLoading}
            onClick={() => { s.loadFolders(true); s.loadMessages(); }}><Refresh /></button>

          <select
            className="pane-select"
            value={s.prefs.density}
            onChange={(e) => s.setPref('density', e.target.value)}
            title="목록 밀도"
          >
            <option value="cozy">보통</option>
            <option value="compact">좁게</option>
          </select>
        </div>
      </div>

    </header>
  );
}
