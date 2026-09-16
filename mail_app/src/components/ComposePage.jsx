import { useRef, useState } from 'react';
import { useCompose } from '../store/compose';
import { useMail } from '../store/mail';
import { useContacts } from '../store/contacts';
import { formatSize, formatSpeed, formatRemain } from '../lib/format';
import { Paperclip, Close } from './Icons';
import AddressInput from './AddressInput';
import Editor from './Editor';
import ComposeToolbar from './ComposeToolbar';
import PreviewModal from './PreviewModal';
import ContactPicker from './ContactPicker';

const MODE_TITLE = {
  new: '메일 쓰기', self: '내게 쓰기', reply: '답장',
  replyAll: '전체답장', forward: '전달', resend: '다시 보내기',
  editScheduled: '예약 메일 수정',
  draft: '이어서 쓰기',
};

export default function ComposePage({ win }) {
  const c = useCompose();
  const accounts = useMail((s) => s.accounts);
  const picking = useContacts((st) => st.picking);
  const bodyRef = useRef(null);
  const fileRef = useRef(null);
  const [dragDepth, setDragDepth] = useState(0);

  const account = accounts.find((a) => a.id === win.accountId);
  const onDrop = (e) => {
    e.preventDefault();
    setDragDepth(0);
    if (e.dataTransfer?.files?.length) c.addFiles(e.dataTransfer.files);
  };

  return (
    <div
      className={`compose-page${dragDepth > 0 ? ' dropping' : ''}`}
      onDragEnter={(e) => { e.preventDefault(); setDragDepth((d) => d + 1); }}
      onDragLeave={() => setDragDepth((d) => Math.max(0, d - 1))}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      {/* 제목줄 / 버튼줄 두 단. 버튼이 제목 바로 아래 왼쪽에 모여 있어야
          손이 가는 거리가 짧다. */}
      <div className="compose-head">
        <div className="compose-head-title">
          <h2 className="compose-heading">{MODE_TITLE[win.mode] || '메일 쓰기'}</h2>
          {/* 화면을 닫는 건 동작이 아니라 이탈이라 버튼줄이 아니라 여기에 둔다 */}
          <button className="compose-close" title="작성 취소" aria-label="작성 취소"
            onClick={() => c.close()}>
            <Close size={16} />
          </button>
        </div>
        <ComposeToolbar account={account} />
      </div>

      <div className="compose-fields">
        <AddressInput label="받는사람" value={win.to} autoFocus={!win.to.length}
          onChange={(v) => c.update({ to: v })} />

        <AddressInput
          label="참조"
          value={win.cc}
          onChange={(v) => c.update({ cc: v })}
          trailing={!win.showBcc && (
            <button className="bcc-toggle" onClick={() => c.update({ showBcc: true })}>
              + 숨은참조
            </button>
          )}
        />

        {win.showBcc && (
          <AddressInput label="숨은참조" value={win.bcc}
            onChange={(v) => c.update({ bcc: v })} />
        )}

        <div className="subject-field">
          <span className="addr-field-label">제목</span>
          <input
            className="compose-subject"
            value={win.subject}
            onChange={(e) => c.update({ subject: e.target.value })}
            placeholder="제목을 입력하세요"
          />
        </div>

        <div className="compose-files">
          <span className="addr-field-label">첨부</span>
          <div className="compose-file-area">
            <button
              type="button"
              className={`attach-drop${dragDepth > 0 ? ' active' : ''}`}
              onClick={() => fileRef.current?.click()}
            >
              <Paperclip size={13} />
              <span>파일을 끌어다 놓거나 눌러서 선택</span>
            </button>
            <input ref={fileRef} type="file" multiple hidden
              onChange={(e) => { c.addFiles(e.target.files); e.target.value = ''; }} />

            <div className="compose-file-list">
              {/* 예약에 이미 올려둔 첨부 — 여기서 빼면 저장할 때 서버에서도 지워진다 */}
              {win.kept?.map((a) => (
                <span key={`k${a.index}`} className="compose-file">
                  <Paperclip size={11} />
                  <span className="cf-name">{a.filename}</span>
                  <span className="cf-size">{formatSize(a.size)}</span>
                  <button className="cf-x" onClick={() => c.removeKept(a.index)} aria-label="첨부 삭제">✕</button>
                </span>
              ))}
              {win.forward?.names.map((n, i) => (
                <span key={`f${i}`} className="compose-file original" title="원본에서 함께 전달됩니다">
                  <Paperclip size={11} />{n}
                </span>
              ))}
              {/* 대용량 — 메일에 싣지 않고 링크로 보낸다. 올라가는 동안 진행률을 보여준다 */}
              {win.largeFiles?.map((l) => (
                <span key={`L${l.id}`} className={`compose-file large ${l.status}`}
                  title={l.status === 'error' ? l.error : '대용량 — 링크로 보냅니다'}>
                  <Paperclip size={11} />
                  <span className="cf-name">{l.name}</span>
                  <span className="cf-size">{formatSize(l.size)}</span>
                  {l.status === 'uploading' && (
                    <>
                      <span className="cf-prog"><i style={{ width: `${l.progress}%` }} />{l.progress}%</span>
                      {l.speed > 0 && <span className="cf-rate">{formatSpeed(l.speed)}</span>}
                      {l.remain !== null && <span className="cf-eta">{formatRemain(l.remain)}</span>}
                    </>
                  )}
                  {l.status === 'done' && <span className="cf-tag">링크</span>}
                  {l.status === 'error' && <span className="cf-err">실패</span>}
                  <button className="cf-x" onClick={() => c.removeLarge(l.id)} aria-label="첨부 삭제">✕</button>
                </span>
              ))}
              {win.files.map((f, i) => (
                <span key={`u${i}`} className="compose-file">
                  <Paperclip size={11} />
                  <span className="cf-name">{f.name}</span>
                  <span className="cf-size">{formatSize(f.size)}</span>
                  <button className="cf-x" onClick={() => c.removeFile(i)} aria-label="첨부 삭제">✕</button>
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {win.error && <div className="compose-error">{win.error}</div>}

      <Editor
        key={win.id}
        editorRef={bodyRef}
        initialHtml={win.bodyHtml}
        onChange={(html) => c.update({ bodyHtml: html })}
      />

      {dragDepth > 0 && <div className="compose-dropzone">여기에 놓으면 첨부됩니다</div>}
      {win.previewing && <PreviewModal account={account} />}
      {picking && <ContactPicker onClose={() => useContacts.setState({ picking: false })} />}
    </div>
  );
}
