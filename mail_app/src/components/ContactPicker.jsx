import { useEffect, useState } from 'react';
import { useContacts, BOOK_LABEL } from '../store/contacts';
import { useCompose } from '../store/compose';
import { Close, Search as SearchIcon } from './Icons';

const BOOKS = ['personal', 'shared', 'internal'];

/**
 * 메일쓰기에서 여는 주소록 — 골라서 받는사람·참조·숨은참조에 담는다.
 *
 * 고른 것을 어느 칸에 넣을지는 **담을 때 고른다.** 칸을 먼저 고르게 하면
 * 참조에 넣으려다 받는사람에 들어가는 실수가 잦다.
 * 주소록 화면과 같은 스토어를 쓰므로 탭·검색 동작이 양쪽에서 같다.
 */
export default function ContactPicker({ onClose }) {
  const c = useContacts();
  const [text, setText] = useState('');
  const [picked, setPicked] = useState([]);   // [{name,email}]

  // 주소록 화면과 스토어를 같이 쓴다 — 거기서 걸어 둔 검색어를 들고 열리면
  // 검색칸은 비었는데 목록만 걸러져 있는 꼴이 된다. 열 때 한 번 푼다.
  useEffect(() => {
    const st = useContacts.getState();
    if (st.q) st.setQuery(''); else st.load();
    /* eslint-disable-next-line */
  }, []);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (text === c.q) return;
    const t = setTimeout(() => c.setQuery(text), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const has = (email) => picked.some((p) => p.email.toLowerCase() === email.toLowerCase());
  const toggle = (item) => {
    setPicked((prev) => (has(item.email)
      ? prev.filter((p) => p.email.toLowerCase() !== item.email.toLowerCase())
      : [...prev, { name: item.name, email: item.email }]));
  };

  /** 이미 들어 있는 주소는 다시 넣지 않는다 */
  const put = (field) => {
    if (!picked.length) return;
    const w = useCompose.getState().active;
    if (!w) return;
    const cur = w[field] || [];
    const lower = new Set(cur.map((v) => v.toLowerCase()));
    const add = picked.map((p) => p.email).filter((e) => !lower.has(e.toLowerCase()));
    const patch = { [field]: [...cur, ...add] };
    if (field === 'bcc') patch.showBcc = true;
    useCompose.getState().update(patch);
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="contact-card wide" onClick={(e) => e.stopPropagation()} role="dialog"
        aria-label="주소록에서 고르기">
        <div className="contact-card-head">
          <h3>주소록</h3>
          <button className="icon-btn" title="닫기" onClick={onClose}><Close /></button>
        </div>

        <div className="picker-tools">
          <div className="book-tabs">
            {BOOKS.map((b) => (
              <button key={b} className={`book-tab${c.book === b ? ' on' : ''}`}
                onClick={() => c.setBook(b)}>
                {BOOK_LABEL[b]}
                <span className="book-count">{c.counts[b] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="search contacts-search">
            <input value={text} onChange={(e) => setText(e.target.value)}
              placeholder={`${BOOK_LABEL[c.book]}에서 검색`} autoFocus />
            {text && <button className="search-clear" title="검색 해제" onClick={() => setText('')}>✕</button>}
            <span className="search-icon"><SearchIcon /></span>
          </div>
        </div>

        <div className="picker-list">
          {c.loading ? <div className="list-state">불러오는 중…</div>
            : !c.items.length ? <div className="list-state">연락처가 없습니다</div>
              : (
                <table className="contact-table">
                  <tbody>
                    {c.items.map((item) => (
                      <tr key={`${item.type}-${item.id ?? item.email}`}
                        className={has(item.email) ? 'picked' : ''}
                        onClick={() => toggle(item)}>
                        <td className="col-pick">
                          <input type="checkbox" checked={has(item.email)} readOnly />
                        </td>
                        <td title={item.name}>{item.name}</td>
                        <td title={item.email}>{item.email}</td>
                        <td title={item.company}>{item.company}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          {c.pages > 1 && (
            <div className="pagination">
              <button disabled={c.page <= 1} onClick={() => c.goPage(c.page - 1)}>‹ 이전</button>
              <span className="page-now">{c.page} / {c.pages}</span>
              <button disabled={c.page >= c.pages} onClick={() => c.goPage(c.page + 1)}>다음 ›</button>
            </div>
          )}
        </div>

        {/* 고른 것은 늘 보인다 — 여러 쪽을 넘나들며 골라도 무엇을 담았는지 안 잊는다 */}
        <div className="picker-picked">
          {picked.length === 0
            ? <span className="picked-none">넣을 사람을 고르세요</span>
            : picked.map((p) => (
              <span key={p.email} className="addr-tag">
                {p.name ? `${p.name} <${p.email}>` : p.email}
                <button className="addr-tag-x" aria-label="빼기"
                  onClick={() => setPicked((prev) => prev.filter((x) => x.email !== p.email))}>✕</button>
              </span>
            ))}
        </div>

        <div className="contact-card-foot">
          <button className="btn-send" disabled={!picked.length} onClick={() => put('to')}>
            받는사람에 넣기{picked.length ? ` (${picked.length})` : ''}
          </button>
          <button className="act" disabled={!picked.length} onClick={() => put('cc')}>참조</button>
          <button className="act" disabled={!picked.length} onClick={() => put('bcc')}>숨은참조</button>
          <button className="btn-cancel" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
