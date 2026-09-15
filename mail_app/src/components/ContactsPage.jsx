import { useEffect, useState } from 'react';
import { useContacts, BOOK_LABEL } from '../store/contacts';
import { useCompose } from '../store/compose';
import { api } from '../api/client';
import ContactImportModal from './ContactImportModal';
import { Search as SearchIcon } from './Icons';

const BOOK_NOTE = {
  personal: '나만 보는 주소록입니다. 메일을 보내면 받는사람이 여기에 저절로 쌓입니다.',
  shared: '전 직원이 함께 보고 고치는 주소록입니다. 예전에 쓰던 주소록에서 가져온 것도 여기 있습니다.',
  internal: '직원 계정에서 만들어지는 목록입니다. 사람이 들어오고 나가면 저절로 따라오므로 여기서 고치지 않습니다.',
};

const BOOKS = ['personal', 'shared', 'internal'];

function Pagination() {
  const { page, pages, goPage } = useContacts();
  if (pages <= 1) return null;
  const span = 5;
  let start = Math.max(1, page - Math.floor(span / 2));
  const end = Math.min(pages, start + span - 1);
  start = Math.max(1, end - span + 1);
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

/** 주소록 화면 — 내 주소록 · 회사 공용 · 사내 직원을 탭으로 가른다. */
export default function ContactsPage() {
  const c = useContacts();
  const [text, setText] = useState(c.q);
  const [importing, setImporting] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [busy, setBusy] = useState('');

  useEffect(() => { c.load(); /* eslint-disable-next-line */ }, []);

  // 글자마다 쏘지 않는다 — 250ms 조용해지면 한 번
  useEffect(() => {
    if (text === c.q) return;
    const t = setTimeout(() => c.setQuery(text), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const write = async (email) => {
    const id = await useCompose.getState().open('new');
    if (id) useCompose.getState().update({ to: [email] });
  };

  const remove = async (item) => {
    const where = BOOK_LABEL[item.type];
    if (!window.confirm(`${where}에서 ${item.name} <${item.email}> 을 지울까요?`
      + (item.type === 'shared' ? '\n회사 공용 주소록이라 전 직원의 화면에서 사라집니다.' : ''))) return;
    setBusy(item.id);
    try { await c.remove(item); }
    catch (e) { window.alert(e.message || '삭제하지 못했습니다'); }
    finally { setBusy(''); }
  };

  const download = async (format) => {
    setExportOpen(false);
    const name = `${BOOK_LABEL[c.book].replace(/\s/g, '')}_${new Date().toISOString().slice(0, 10)}.${format}`;
    try { await api.openBinary(c.exportUrl(c.book, format), name); }
    catch (e) { window.alert(e.message || '내보내지 못했습니다'); }
  };

  return (
    <div className="contacts-page">
      <div className="contacts-head">
        <div className="contacts-title-row">
          <h2 className="contacts-heading">주소록</h2>
          <div className="contacts-tools">
            <div className="search contacts-search">
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={`${BOOK_LABEL[c.book]}에서 검색`}
              />
              {text && (
                <button className="search-clear" title="검색 해제" onClick={() => setText('')}>✕</button>
              )}
              <span className="search-icon"><SearchIcon /></span>
            </div>
            <button className="act" onClick={() => c.startEdit()}>+ 연락처 추가</button>
            <button className="act" onClick={() => setImporting(true)}>가져오기</button>
            <div className="act-wrap">
              <button className={`act${exportOpen ? ' on' : ''}`}
                onClick={() => setExportOpen((v) => !v)}>내보내기 ▾</button>
              {exportOpen && (
                <div className="move-menu" onMouseLeave={() => setExportOpen(false)}>
                  <button onClick={() => download('vcf')}>vCard (.vcf)</button>
                  <button onClick={() => download('csv')}>엑셀용 CSV (.csv)</button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 주소록이 셋으로 갈라져 있다는 것이 화면에서 바로 읽혀야 한다 */}
        <div className="book-tabs">
          {BOOKS.map((b) => (
            <button key={b} className={`book-tab${c.book === b ? ' on' : ''}`}
              onClick={() => c.setBook(b)}>
              {BOOK_LABEL[b]}
              <span className="book-count">{c.counts[b] ?? 0}</span>
            </button>
          ))}
        </div>
        <p className="book-note">{BOOK_NOTE[c.book]}</p>
      </div>

      <div className="contacts-body">
        {c.loading ? <div className="list-state">불러오는 중…</div>
          : c.error ? <div className="list-state error">{c.error}</div>
            : !c.items.length ? (
              <div className="list-state">
                {c.q ? `'${c.q}' 에 맞는 연락처가 없습니다`
                  : c.book === 'personal' ? '아직 저장한 연락처가 없습니다. 메일을 보내면 받는사람이 여기 쌓입니다.'
                    : '연락처가 없습니다'}
              </div>
            ) : (
              <table className="contact-table">
                <thead>
                  <tr>
                    <th>이름</th><th>메일주소</th><th>회사</th><th>전화</th><th>메모</th>
                    <th className="col-act"></th>
                  </tr>
                </thead>
                <tbody>
                  {c.items.map((item) => (
                    <tr key={`${item.type}-${item.id ?? item.email}`}>
                      <td title={item.name}>
                        {item.name}
                        {c.book === 'all' && <span className={`book-tag ${item.type}`}>{BOOK_LABEL[item.type]}</span>}
                      </td>
                      <td title={item.email}>{item.email}</td>
                      <td title={item.company}>{item.company}</td>
                      <td title={item.phone}>{item.phone}</td>
                      <td title={item.memo}>{item.memo}</td>
                      <td className="col-act">
                        <button className="row-act" onClick={() => write(item.email)}>메일쓰기</button>
                        {item.editable && (
                          <>
                            <button className="row-act" onClick={() => c.startEdit({ ...item, book: item.type })}>
                              수정
                            </button>
                            <button className="row-act danger" disabled={busy === item.id}
                              onClick={() => remove(item)}>삭제</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        <Pagination />
      </div>

      {importing && <ContactImportModal onClose={() => setImporting(false)} />}
    </div>
  );
}
