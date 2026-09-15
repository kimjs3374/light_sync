import { useState } from 'react';
import { useMail } from '../store/mail';
import { api, mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { formatFullDate, formatSize, senderName, senderEmail } from '../lib/format';
import { isSentFolder } from '../lib/folders';
import { Close, Paperclip, Mail, Expand, Collapse } from './Icons';
import SenderMenu from './SenderMenu';
import RawModal from './RawModal';

function AddressLine({ label, list }) {
  if (!list || !list.length) return null;
  return (
    <div className="addr-line">
      <span className="addr-label">{label}</span>
      <span className="addr-value">
        {list.map((a, i) => (
          <span key={i} className="addr-chip" title={a.email}>
            {a.name ? `${a.name} <${a.email}>` : a.email}
          </span>
        ))}
      </span>
    </div>
  );
}

export default function ReadPane() {
  const s = useMail();
  const d = s.detail;
  // 목록과 같은 메뉴를 쓴다 — 메일을 열어 놓고도 같은 자리에서 같은 일을 한다
  const [senderMenu, setSenderMenu] = useState(null);
  const [rawOpen, setRawOpen] = useState(false);
  // 읽음 여부는 목록 줄이 들고 있다 — 열면 서버가 읽음을 달므로 보통 '읽음' 이다
  const row = s.messages.find((m) => m.uid === s.openUid);
  const isRead = row ? row.is_read : true;

  /**
   * 인쇄 — 서버가 그려 주는 인쇄 화면(mail_print.html, onload 에서 스스로 인쇄)을
   * **Bearer 로 받아서** 새 창에 넣는다. 주소만 새 창에 띄우면 그 창에는
   * 세션 쿠키가 없을 수 있어 로그인 화면이 대신 인쇄된다.
   */
  const printMail = async () => {
    try {
      const html = await api.text(mailApi.printUrl({
        account: s.accountId, folder: s.folder, uid: s.openUid,
      }));
      const w = window.open('', '_blank', 'width=820,height=900');
      if (!w) { alert('팝업이 막혀 있습니다. 이 사이트의 팝업을 허용해 주세요.'); return; }
      w.document.write(html);
      w.document.close();
    } catch (e) {
      alert(e.message || '인쇄 화면을 열지 못했습니다');
    }
  };

  const download = async (att) => {
    const url = mailApi.attachmentUrl({
      account: s.accountId, folder: s.folder, uid: s.openUid, partId: att.part_id,
    });
    try {
      await api.openBinary(url, att.filename);
    } catch (e) {
      alert(e.message || '첨부를 받지 못했습니다');
    }
  };

  if (!s.openUid) {
    return (
      <div className="read-pane">
        <div className="read-empty">
          <span className="read-empty-icon"><Mail size={34} /></span>
          <p className="read-empty-text">읽을 메일을 선택하세요</p>
          <p className="read-empty-hint">↑ ↓ 키로도 옮겨 다닐 수 있습니다</p>
        </div>
      </div>
    );
  }
  if (s.detailLoading) return <div className="read-pane"><div className="list-state">메일을 여는 중…</div></div>;
  if (s.detailError) return <div className="read-pane"><div className="list-state error">{s.detailError}</div></div>;
  if (!d) return null;

  return (
    <div className="read-pane">
      <div className="read-head">
        <div className="read-subject-row">
          <h2 className="read-subject">{d.subject || '(제목 없음)'}</h2>
          {/* 목록을 잠시 접고 읽기창만 남긴다. 긴 메일·표가 든 메일은 반쪽 폭에서
              가로로 스크롤해야 읽힌다 — 그때 한 번 누르면 된다. ESC 로도 돌아온다.
              보기 방식이 '기본(전체보기)' 면 이미 전체라 버튼을 내놓지 않는다. */}
          {s.prefs.layout !== 'full' && (
          <button className="icon-btn" onClick={s.toggleReaderFull}
            title={s.readerFull ? '원래 크기로 (Esc)' : '화면 꽉 채워 보기'}
            aria-pressed={s.readerFull}>
            {s.readerFull ? <Collapse /> : <Expand />}
          </button>
          )}
          <button className="icon-btn" title="닫기" onClick={s.close}><Close /></button>
        </div>

        <div className="read-actions" data-tour="read">
          <button onClick={() => useCompose.getState().open('reply')}>답장</button>
          <button onClick={() => useCompose.getState().open('replyAll')}>전체답장</button>
          <button onClick={() => useCompose.getState().open('forward')}>전달</button>
          {/* 다시 보내기는 보낸편지함에서만. 받은 메일에서 누르면 원본의 받는사람(=나)이
              그대로 실려 나에게 다시 보내는 꼴이 된다 — 뜻이 없는 버튼은 내놓지 않는다. */}
          {isSentFolder(s.folder) && (
            <button className="plain" onClick={() => useCompose.getState().open('resend')}>
              다시 보내기
            </button>
          )}

          {/* 읽음 표시는 한 자리에서 토글한다 — '읽음'·'안읽음' 두 버튼을 나란히 두면
              지금 어느 상태인지는 여전히 안 보인다. 지금 상태의 반대를 내놓는다.
              안읽음으로 돌리면 읽기창이 닫힌다(열어 두면 다시 읽음이 된다). */}
          <button className="plain" onClick={() => s.setReadOne(s.openUid, !isRead)}>
            {isRead ? '안읽음으로 표시' : '읽음으로 표시'}
          </button>
          <button className="plain" onClick={printMail}>인쇄</button>
          <button className="plain" onClick={() => setRawOpen(true)}>원문보기</button>
        </div>

        <div className="read-meta">
          <button
            className="read-from"
            title="누르면 메일 보내기 · 주소록에 추가 · 검색 · 주소 복사"
            onClick={(e) => setSenderMenu({
              rect: e.currentTarget.getBoundingClientRect(),
              name: senderName(d.from),
              email: senderEmail(d.from),
            })}
          >
            <strong>{senderName(d.from)}</strong>
            <span className="read-from-email">{senderEmail(d.from)}</span>
          </button>
          <div className="read-date">{formatFullDate(d.date)}</div>
        </div>

        <AddressLine label="받는사람" list={d.to} />
        <AddressLine label="참조" list={d.cc} />

        {d.attachments?.length > 0 && (
          <div className="attach-box">
            <div className="attach-title">첨부 {d.attachments.length}개</div>
            <div className="attach-list">
              {d.attachments.map((a) => (
                <button key={a.part_id} className="attach-item" onClick={() => download(a)}>
                  <Paperclip size={12} />
                  <span className="attach-name">{a.filename}</span>
                  <span className="attach-size">{formatSize(a.size)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {senderMenu && senderMenu.email && (
        <SenderMenu
          anchor={senderMenu.rect}
          name={senderMenu.name}
          email={senderMenu.email}
          onClose={() => setSenderMenu(null)}
        />
      )}

      {rawOpen && (
        <RawModal account={s.accountId} folder={s.folder} uid={s.openUid}
          onClose={() => setRawOpen(false)} />
      )}

      <div className="read-body">
        {d.html_body
          ? <div className="mail-html" dangerouslySetInnerHTML={{ __html: d.html_body }} />
          : <pre className="mail-text">{d.text_body}</pre>}
      </div>
    </div>
  );
}
