import { useEffect, useRef, useState } from 'react';
import { useMail, visibleMessages } from '../store/mail';
import { showsUnread } from '../lib/folders';
import { formatListDate, senderName, senderEmail, splitSubject } from '../lib/format';
import { Paperclip, Star } from './Icons';
import SenderMenu from './SenderMenu';

function Pagination() {
  const { page, pages, goPage, searchQuery } = useMail();
  if (searchQuery || pages <= 1) return null;

  const window = 5;
  let start = Math.max(1, page - Math.floor(window / 2));
  const end = Math.min(pages, start + window - 1);
  start = Math.max(1, end - window + 1);
  const nums = [];
  for (let i = start; i <= end; i++) nums.push(i);

  return (
    <div className="pagination">
      <button disabled={page <= 1} onClick={() => goPage(1)}>«</button>
      <button disabled={page <= 1} onClick={() => goPage(page - 1)}>‹</button>
      {nums.map((i) => (
        <button key={i} className={i === page ? 'on' : ''} onClick={() => goPage(i)}>{i}</button>
      ))}
      <button disabled={page >= pages} onClick={() => goPage(page + 1)}>›</button>
      <button disabled={page >= pages} onClick={() => goPage(pages)}>»</button>
    </div>
  );
}

export default function MessageList() {
  const s = useMail();
  const messages = visibleMessages(s);
  const cursorRef = useRef(null);
  // 보낸사람 이름을 누르면 뜨는 메뉴 — 한 번에 하나만 뜬다
  const [senderMenu, setSenderMenu] = useState(null);

  /**
   * 보낸편지함·임시보관함에서는 안읽음을 표시하지 않는다.
   *
   * 목록의 점은 IMAP \Seen 플래그 하나를 그대로 그린 것이다. 받은 메일에서는
   * "내가 안 열어봤다"는 뜻이지만, 내가 보낸 사본에는 읽고말고가 없다.
   * 우리가 보낸 것은 \Seen 을 붙여 저장하지만(mail_client.append_to_sent) 휴대폰·
   * 아웃룩 등 다른 클라이언트가 넣은 사본에는 그 플래그가 없어, 같은 목록에서
   * 어떤 줄만 점이 찍혀 "왜 표기가 다르냐"로 읽혔다.
   * 사이드바 뱃지가 쓰는 잣대(showsUnread)를 목록도 똑같이 쓴다.
   */
  const marksUnread = showsUnread(s.folder);

  // 키보드로 커서를 옮기면 그 줄이 보이도록 따라 스크롤한다
  useEffect(() => {
    cursorRef.current?.scrollIntoView({ block: 'nearest' });
  }, [s.cursor]);

  if (s.listLoading) {
    return <div className="msg-list"><div className="list-state">불러오는 중…</div></div>;
  }
  if (s.listError && s.listError !== 'no-account') {
    return (
      <div className="msg-list">
        <div className="list-state error">
          {s.listError}
          <button className="retry" onClick={() => s.loadMessages()}>다시 시도</button>
        </div>
      </div>
    );
  }
  if (!messages.length) {
    return (
      <div className="msg-list">
        <div className="list-state">
          {s.searchQuery
            ? `'${s.searchQuery}' 검색 결과가 없습니다`
            : s.searchDetail
              ? '조건에 맞는 메일이 없습니다'
              : '메일이 없습니다'}
        </div>
      </div>
    );
  }

  return (
    <div className={`msg-list density-${s.prefs.density}`} data-tour="list">
      {messages.map((m, i) => {
        const checked = s.checked.has(m.uid);
        const open = s.openUid === m.uid;
        const atCursor = i === s.cursor;
        const { tag, text } = splitSubject(m.subject);
        return (
          <div
            key={m.uid}
            ref={atCursor ? cursorRef : null}
            className={`msg-row${m.is_read || !marksUnread ? '' : ' unread'}${open ? ' open' : ''}`
              + `${checked ? ' checked' : ''}${atCursor ? ' cursor' : ''}`}
            onClick={() => s.open(m.uid)}
          >
            <label className="col-check" onClick={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={checked} onChange={() => s.toggleCheck(m.uid)} />
            </label>

            <button
              className={`col-star${m.is_flagged ? ' on' : ''}`}
              title={m.is_flagged ? '중요 해제' : '중요 표시'}
              onClick={(e) => { e.stopPropagation(); s.toggleStar(m.uid, !m.is_flagged); }}
            >
              <Star filled={m.is_flagged} />
            </button>

            {/* 안읽음은 굵기 대신 점으로 — 줄 전체를 굵히면 목록이 무거워진다 */}
            <span className="col-dot" aria-hidden="true" />

            {/* 이름을 누르면 그 사람에 대해 할 수 있는 일이 열린다.
                줄을 누르는 것(메일 열기)과 겹치지 않게 전파를 끊는다 */}
            <button
              className="col-from"
              title={`${senderEmail(m.from)} — 누르면 메뉴`}
              onClick={(e) => {
                e.stopPropagation();
                setSenderMenu({
                  rect: e.currentTarget.getBoundingClientRect(),
                  name: senderName(m.from),
                  email: senderEmail(m.from),
                });
              }}
            >
              {senderName(m.from)}
            </button>

            <div className="col-subject">
              {tag && <span className="subject-tag" title={tag}>{tag}</span>}
              <span className="subject-text">{text}</span>
            </div>

            <div className="col-attach">{m.has_attachment && <Paperclip />}</div>
            <div className="col-date">{formatListDate(m.date)}</div>
          </div>
        );
      })}
      <Pagination />

      {senderMenu && senderMenu.email && (
        <SenderMenu
          anchor={senderMenu.rect}
          name={senderMenu.name}
          email={senderMenu.email}
          onClose={() => setSenderMenu(null)}
        />
      )}
    </div>
  );
}
