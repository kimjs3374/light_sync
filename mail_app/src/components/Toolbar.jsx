import { useState } from 'react';
import { useMail, visibleMessages, SORT_KEYS, SORT_LABEL, isDefaultSort } from '../store/mail';
import { folderLabel, findTrash, findJunk, splitFolders } from '../lib/folders';
import { Refresh, Search as SearchIcon, Gear } from './Icons';
import { useSettings } from '../store/settings';
import AdvancedSearch from './AdvancedSearch';


const FILTER_LABEL = { unread: '안읽은 메일', flagged: '중요 메일', attach: '첨부 있는 메일' };

export default function Toolbar() {
  const s = useMail();
  const [q, setQ] = useState('');
  const [advOpen, setAdvOpen] = useState(false);
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

  /**
   * 휴지통·스팸함 비우기 — 되돌릴 수 없으니 몇 통인지 세어 보여주고 한 번 묻는다.
   * 서버가 이 두 곳 외에는 거절하므로 화면에서도 그 두 곳에서만 버튼을 낸다.
   */
  const emptiable = !s.specialView && (s.folder === trash || s.folder === junk);
  const onEmpty = () => {
    const where = folderLabel(s.folder);
    if (!confirm(`${where}에 있는 메일 ${s.total}통이 모두 지워집니다. 되돌릴 수 없습니다.`)) return;
    run(s.emptyCurrentFolder);
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
              {s.searchQuery || s.searchDetail ? `검색 ${s.total}건` : `${s.total}통`}
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
            {/* 라벨도 마찬가지다 — 누른 곳은 왼쪽 라벨 목록이지만,
                지금 목록이 왜 이것만인지는 목록 위에 적혀 있어야 한다 */}
            {s.labelFilter && (
              <button className="active-filter" onClick={s.clearLabelFilter}
                title="라벨 해제">
                라벨 · {s.labelFilter.name}
                <span className="af-x">✕</span>
              </button>
            )}
            {/* 비우기는 휴지통·스팸함에서만. 지울 것이 없으면 내놓지 않는다 */}
            {emptiable && s.total > 0 && (
              <button className="empty-folder" disabled={busy} onClick={onEmpty}>
                비우기
              </button>
            )}
          </div>
        )}

        {/* 검색·새로고침은 자기가 다루는 목록 위에 있어야 한다 —
            읽기창 쪽 끝으로 밀어두면 무엇에 대한 검색인지 읽히지 않는다 */}
        <div className="list-tools">
          <div className="search-wrap" data-tour="search">
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
            <button
              type="button"
              className={`adv-toggle${advOpen || s.searchDetail ? ' on' : ''}`}
              title="상세검색"
              aria-expanded={advOpen}
              onClick={() => setAdvOpen((v) => !v)}
            >상세</button>
            {advOpen && <AdvancedSearch onClose={() => setAdvOpen(false)} />}
          </div>

          {/* 정렬 고르기. 무엇이 걸렸는지와 "이 쪽에서만"이라는 사실은
              아래 한 줄(sort-criteria)이 맡는다 — 여기 적으면 화면이 좁아질 때
              제일 먼저 밀려나 사라진다. */}
          <select
            className="pane-select sort-select"
            value={`${s.sortBy}:${s.sortDir}`}
            onChange={(e) => {
              const [by, dir] = e.target.value.split(':');
              s.setSort(by, dir);
            }}
            title="정렬 — 지금 보고 있는 쪽 안에서만 순서를 바꿉니다"
          >
            {SORT_KEYS.map((k) => (
              <optgroup key={k} label={SORT_LABEL[k]}>
                <option value={`${k}:desc`}>
                  {SORT_LABEL[k]} 내림차순{k === 'date' ? ' (최신순)' : ''}
                </option>
                <option value={`${k}:asc`}>
                  {SORT_LABEL[k]} 오름차순{k === 'date' ? ' (오래된순)' : ''}
                </option>
              </optgroup>
            ))}
          </select>

          <button className="icon-btn" title="새로고침" disabled={s.listLoading}
            onClick={() => { s.loadFolders(true); s.loadMessages(); }}><Refresh /></button>
        </div>

        {/* 밀도만 오른쪽 끝 — 검색·새로고침과 달리 목록을 다루는 게 아니라
            화면 보기 설정이라 자리를 따로 둔다 */}
        <select
          className="pane-select density-select" data-tour="density"
          value={s.prefs.density}
          onChange={(e) => s.setPref('density', e.target.value)}
          title="목록 밀도"
        >
          <option value="roomy">크게</option>
          <option value="cozy">보통</option>
          <option value="compact">좁게</option>
        </select>

        {/* 설정은 보기 설정(밀도) 바로 옆에 둔다 — 화면을 손보러 온 손이
            거기까지 와 있다. 깊은 설정(계정·템플릿)은 그 안에서 ERP 로 보낸다. */}
        <button className="icon-btn gear-btn" title="화면 안내 — 버튼이 무엇을 하는지 짚어 줍니다"
          onClick={() => useSettings.getState().startTour()}>?</button>

        <button className="icon-btn gear-btn" title="환경설정" data-tour="settings"
          onClick={() => useSettings.getState().openSettings()}>
          <Gear />
        </button>
      </div>

      {/* 상세검색이 걸려 있으면 무엇으로 걸렀는지 적어둔다 —
          안 적으면 "왜 이것만 나오는지" 를 화면 어디서도 읽을 수 없다 */}
      {/* 정렬은 **지금 보고 있는 쪽 안에서만** 돈다 — 서버가 날짜순으로 한 쪽씩
          떼어 주기 때문이다. 이 줄을 빼면 "2쪽에 더 오래된 메일이 있는데 왜
          안 올라오냐"를 화면 어디에서도 읽을 수 없다.
          툴바 안(검색칸 옆)이 아니라 아래 한 줄로 두는 까닭: 저 안에 두면
          화면이 좁아질 때 제일 먼저 밀려나 사라진다. */}
      {!isDefaultSort(s) && (
        <div className="toolbar-row sort-criteria">
          <span className="sc-tag">정렬</span>
          <span className="sc-chip">
            {SORT_LABEL[s.sortBy]} {s.sortDir === 'asc' ? '오름차순' : '내림차순'}
          </span>
          <span className="dc-more">지금 보고 있는 쪽 안에서만 순서가 바뀝니다</span>
          <button className="dc-clear" onClick={() => s.setSort('date', 'desc')}>
            기본 순서로 ✕
          </button>
        </div>
      )}

      {s.searchDetail && (
        <div className="toolbar-row detail-criteria">
          <span className="dc-tag">상세검색</span>
          {s.searchDetail.criteria.map((c) => (
            <span className="dc-chip" key={c}>{c}</span>
          ))}
          {s.searchDetail.truncated && (
            <span className="dc-more">최근 {s.searchDetail.shown}건만 표시</span>
          )}
          <button className="dc-clear" onClick={s.clearSearchDetail}>해제 ✕</button>
        </div>
      )}
    </header>
  );
}
