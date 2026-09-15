import { useEffect, useRef, useState } from 'react';
import { useContacts, BOOK_LABEL } from '../store/contacts';
import { Close } from './Icons';

const STATE_LABEL = { add: '새로 추가', update: '빈 칸 채움', skip: '이미 있음' };

/**
 * 쓰던 주소록 가져오기 — 다음·네이버·구글·아웃룩이 내주는 .vcf / .csv 파일.
 *
 * 고르자마자 **저장하지 않고 먼저 세어서 보여준다**(dry-run). 남의 주소록 수백 건이
 * 말없이 쏟아진 뒤에 되돌리는 것보다, 들어올 것을 먼저 보고 누르는 편이 낫다.
 * 저장할 곳을 바꾸면 숫자가 달라지므로(내 주소록엔 없고 공용엔 있을 수 있다)
 * 그때마다 다시 센다.
 */
export default function ContactImportModal({ onClose }) {
  const c = useContacts();
  const [book, setBook] = useState(c.book === 'internal' ? 'personal' : c.book);
  const [file, setFile] = useState(null);
  const [dry, setDry] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);
  const [dragging, setDragging] = useState(0);
  const fileRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // 파일이나 저장할 곳이 바뀌면 다시 센다
  useEffect(() => {
    if (!file) return;
    let alive = true;
    setBusy(true); setError(''); setDone(null);
    c.importFile(file, { book, dryRun: true })
      .then((res) => { if (alive) setDry(res); })
      .catch((e) => { if (alive) { setError(e.message || '파일을 읽지 못했습니다'); setDry(null); } })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, book]);

  const pick = (files) => {
    const f = files?.[0];
    if (f) { setFile(f); setDry(null); }
  };

  const run = async () => {
    setBusy(true); setError('');
    try {
      setDone(await c.importFile(file, { book, dryRun: false }));
    } catch (e) {
      setError(e.message || '가져오지 못했습니다');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="contact-card wide" onClick={(e) => e.stopPropagation()} role="dialog"
        aria-label="주소록 가져오기">
        <div className="contact-card-head">
          <h3>주소록 가져오기</h3>
          <button className="icon-btn" title="닫기" onClick={onClose}><Close /></button>
        </div>

        <div className="import-body">
          <div className="cform-row">
            <span className="cform-label">가져올 곳</span>
            <div className="book-choice">
              {['personal', 'shared'].map((b) => (
                <button key={b} type="button" className={`book-pick${book === b ? ' on' : ''}`}
                  onClick={() => setBook(b)} disabled={busy}>
                  {BOOK_LABEL[b]}
                  <em>{b === 'personal' ? '나만 봅니다' : '전 직원이 함께 씁니다'}</em>
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            className={`import-drop${dragging > 0 ? ' active' : ''}`}
            onClick={() => fileRef.current?.click()}
            onDragEnter={(e) => { e.preventDefault(); setDragging((d) => d + 1); }}
            onDragLeave={() => setDragging((d) => Math.max(0, d - 1))}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); setDragging(0); pick(e.dataTransfer?.files); }}
          >
            {file
              ? <><b>{file.name}</b><span>다른 파일로 바꾸려면 다시 누르세요</span></>
              : <><b>주소록 파일을 끌어다 놓거나 눌러서 선택</b>
                <span>다음·네이버·구글·아웃룩에서 내보낸 .vcf 또는 .csv</span></>}
          </button>
          <input ref={fileRef} type="file" accept=".vcf,.csv,text/vcard,text/csv" hidden
            onChange={(e) => { pick(e.target.files); e.target.value = ''; }} />

          {busy && <div className="import-note">읽는 중…</div>}
          {error && <div className="contact-error">{error}</div>}

          {done ? (
            <div className="import-result">
              <b>{BOOK_LABEL[done.book]}에 가져왔습니다.</b>
              <span>새로 추가 {done.added}건 · 빈 칸 채움 {done.updated}건 · 이미 있어 그대로 둠 {done.skipped}건</span>
            </div>
          ) : dry && (
            <>
              <div className="import-result">
                <b>{dry.stats.format === 'csv' ? 'CSV' : 'vCard'} {dry.stats.cards}건에서 주소 {dry.stats.contacts}개를 읽었습니다.</b>
                <span>
                  새로 추가 {dry.added}건 · 빈 칸 채움 {dry.updated}건 · 이미 있음 {dry.skipped}건
                  {dry.stats.no_email > 0 && ` · 메일주소 없어 건너뜀 ${dry.stats.no_email}건`}
                  {dry.stats.bad_email > 0 && ` · 주소 형식이 아니라 건너뜀 ${dry.stats.bad_email}건`}
                </span>
              </div>

              {/* 표는 줄바꿈하지 않는다 — 길면 … 로 자른다 */}
              <div className="import-preview">
                <table className="contact-table">
                  <thead>
                    <tr><th>이름</th><th>메일주소</th><th>회사</th><th>전화</th><th className="col-state">어떻게</th></tr>
                  </thead>
                  <tbody>
                    {dry.preview.map((p, i) => (
                      <tr key={i}>
                        <td title={p.name}>{p.name}</td>
                        <td title={p.email}>{p.email}</td>
                        <td title={p.company}>{p.company}</td>
                        <td title={p.phone}>{p.phone}</td>
                        <td className="col-state"><span className={`state-tag ${p.state}`}>{STATE_LABEL[p.state]}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {dry.stats.contacts > dry.preview.length && (
                  <div className="import-note">앞 {dry.preview.length}건만 보여 줍니다.</div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="contact-card-foot">
          {done ? (
            <button className="btn-send" onClick={onClose}>닫기</button>
          ) : (
            <>
              <button className="btn-send" disabled={!dry || busy || (dry.added + dry.updated === 0)}
                onClick={run}>
                {busy ? '가져오는 중…'
                  : dry ? `${dry.added + dry.updated}건 가져오기` : '가져오기'}
              </button>
              <button className="btn-cancel" onClick={onClose}>취소</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
