import { useEffect, useState } from 'react';
import { useMail } from '../store/mail';
import { api, mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { formatFullDate, formatSize, senderName, senderEmail } from '../lib/format';
import { isSentFolder } from '../lib/folders';
import { isDraftFolder } from '../lib/compose';
import { Close, Paperclip, Mail, Expand, Collapse } from './Icons';
import SenderMenu from './SenderMenu';
import RawModal from './RawModal';
import AttachPreview, { previewKind } from './AttachPreview';

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

/* ── 수신확인 ────────────────────────────────────────────────────────────
   /mail/api/receipts 는 내가 보낸 것 100건을 통째로 준다. 메일을 열 때마다
   부르면 한 통 보려고 100건을 받는 꼴이라 한 번 받아 들고 쓴다.
   다만 영영 붙들면 방금 보낸 메일이 목록에 없어 "추적 없음"으로 보이고,
   상대가 그 사이 읽어도 숫자가 안 는다 — 1분이 지나면 다시 받는다. */
const RECEIPT_TTL = 60000;
let receiptsAt = 0;
let receiptsPromise = null;

function loadReceipts() {
  if (!receiptsPromise || Date.now() - receiptsAt > RECEIPT_TTL) {
    receiptsAt = Date.now();
    receiptsPromise = mailApi.receipts()
      .then((r) => (Array.isArray(r) ? r : []))
      .catch(() => []);   // 부가 정보다 — 못 받아도 읽기창은 그대로 뜬다
  }
  return receiptsPromise;
}

/** ISO 시각 → `09/16 10:22` (공용계정 읽은사람 목록이 서버에서 오는 모양과 맞춘다) */
function stamp(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * 보낸 메일 한 통에 붙는 수신확인 기록 찾기.
 *
 * 서버가 주는 기록에는 uid 도 메일함도 없다 — **제목과 받는사람 한 명**(보낼 때의
 * 첫 수신자)뿐이다. 그래서 그 둘로 맞춘다. 같은 제목으로 여러 번 보냈으면
 * 가장 최근 것을 쓴다.
 *
 * 계정(mail_account_id)까지 함께 본다 — 같은 제목을 같은 사람에게 개인 계정과
 * 공용 계정 양쪽에서 보냈으면 둘이 섞인다. (이 값은 2026-09-16 에 서버가
 * 내주기 시작했다. 옛 기록에는 없을 수 있으므로 **없으면 계정은 따지지 않는다**)
 *
 * 못 찾으면 null 이고, 화면은 **아무것도 띄우지 않는다.** 추적을 안 심은 옛 메일과
 * 다른 프로그램(휴대폰·아웃룩)으로 보낸 메일이 많아서, 없는 것을 "안 읽음"으로
 * 적으면 그게 거짓말이 된다.
 */
function matchReceipt(list, d, accountId) {
  const subject = String(d.subject || '').trim();
  const tos = (d.to || []).map((a) => String(a.email || '').toLowerCase()).filter(Boolean);
  if (!tos.length) return null;
  const hits = list.filter((r) => String(r.subject || '').trim() === subject
    && tos.includes(String(r.to_email || '').toLowerCase())
    && (!r.mail_account_id || !accountId || r.mail_account_id === accountId));
  if (!hits.length) return null;
  return hits.reduce((best, r) => (
    new Date(r.sent_at || 0) > new Date(best.sent_at || 0) ? r : best));
}

export default function ReadPane() {
  const s = useMail();
  const d = s.detail;
  // 목록과 같은 메뉴를 쓴다 — 메일을 열어 놓고도 같은 자리에서 같은 일을 한다
  const [senderMenu, setSenderMenu] = useState(null);
  const [rawOpen, setRawOpen] = useState(false);
  // 미리보기로 열어 둔 첨부 한 개 (null 이면 안 떠 있다)
  const [preview, setPreview] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [readers, setReaders] = useState([]);
  // 읽음 여부는 목록 줄이 들고 있다 — 열면 서버가 읽음을 달므로 보통 '읽음' 이다
  const row = s.messages.find((m) => m.uid === s.openUid);
  const isRead = row ? row.is_read : true;

  const isSent = isSentFolder(s.folder);
  const isDraft = isDraftFolder(s.folder);
  const isShared = !!s.accounts.find((a) => a.id === s.accountId)?.is_shared;
  // 상세가 다른 메일로 바뀌었는지 가리는 값 — d 를 그대로 의존성에 넣으면
  // 같은 메일인데도 객체가 새로 만들어질 때마다 다시 부른다
  const openedUid = d?.uid;

  /* 다른 메일로 옮기면 열려 있던 첨부 미리보기는 닫는다. 그대로 두면 part 번호는
     그 메일 안에서만 뜻이 있어서, 새 메일의 같은 번호 조각이 대신 열린다. */
  useEffect(() => { setPreview(null); }, [openedUid]);

  /* 보낸 메일이면 상대가 읽었는지 한 줄 적는다. 보낸편지함에서만 뜻이 있다. */
  useEffect(() => {
    setReceipt(null);
    if (!openedUid || !isSent) return undefined;
    let alive = true;
    const detail = d;
    const accountId = s.accountId;
    loadReceipts().then((list) => {
      if (alive) setReceipt(matchReceipt(list, detail, accountId));
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openedUid, isSent, s.accountId]);

  /**
   * 공용계정이면 "이미 본 사람"을 적고, 내가 봤다는 것도 남긴다.
   *
   * **읽는 것이 먼저, 남기는 것이 나중이다.** 순서를 바꾸면 방금 연 내가 늘
   * 목록에 들어가서 "아무도 안 봤으면 안 띄운다"가 영영 안 먹는다 —
   * 공용계정 메일마다 내 이름 한 줄이 붙는다.
   */
  useEffect(() => {
    setReaders([]);
    if (!openedUid || !isShared) return undefined;
    let alive = true;
    const args = { account: s.accountId, folder: s.folder, uid: openedUid };
    mailApi.sharedRead(args)
      .then((list) => {
        if (alive) setReaders(Array.isArray(list) ? list : []);
        return mailApi.markSharedRead(args);
      })
      .catch(() => { /* 읽음 표시는 부가 기능이다 — 실패해도 조용히 넘어간다 */ });
    return () => { alive = false; };
  }, [openedUid, isShared, s.accountId, s.folder]);

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

  /** 첨부 전부를 zip 한 벌로. 서버가 묶어 주고, 이름은 제목을 따른다. */
  const downloadAll = async () => {
    const url = mailApi.attachmentsZipUrl({
      account: s.accountId, folder: s.folder, uid: s.openUid,
    });
    // 파일 이름으로 못 쓰는 글자는 바꾼다 — 메일 제목에 `/` 나 `:` 가 흔하다
    const base = String(d?.subject || `attachments_${s.openUid}`)
      .replace(/[\\/:*?"<>|\r\n\t]/g, '_').trim().slice(0, 120);
    try {
      await api.openBinary(url, `${base || `attachments_${s.openUid}`}.zip`);
    } catch (e) {
      alert(e.message || '첨부를 묶어 받지 못했습니다');
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
          {/* 임시보관함 메일은 읽을 것이 아니라 **마저 쓸 것**이다.
              그래서 버튼줄 맨 앞에 둔다 — 답장·전달보다 먼저 찾는 손이다. */}
          {isDraft && (
            <button onClick={() => useCompose.getState().openDraft()}>이어서 쓰기</button>
          )}
          <button onClick={() => useCompose.getState().open('reply')}>답장</button>
          <button onClick={() => useCompose.getState().open('replyAll')}>전체답장</button>
          <button onClick={() => useCompose.getState().open('forward')}>전달</button>
          {/* 다시 보내기는 보낸편지함에서만. 받은 메일에서 누르면 원본의 받는사람(=나)이
              그대로 실려 나에게 다시 보내는 꼴이 된다 — 뜻이 없는 버튼은 내놓지 않는다. */}
          {isSent && (
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

        {/* 상대가 읽었는가. 추적 기록을 못 찾으면 한 줄도 적지 않는다 —
            모르는 것을 "안 읽음"으로 적으면 그게 거짓말이 된다. */}
        {receipt && (
          <div className="read-note">
            <span className="read-note-label">수신확인</span>
            <span className="read-note-value">
              {receipt.is_read ? (
                <>
                  <b>✓ 읽음</b>
                  {receipt.read_at && ` · ${stamp(receipt.read_at)}`}
                  {receipt.read_count > 1 && ` · ${receipt.read_count}번`}
                </>
              ) : '아직 읽지 않음'}
            </span>
          </div>
        )}

        {/* 공용계정에서 나보다 먼저 이 메일을 본 사람들. 아무도 없으면 안 띄운다. */}
        {readers.length > 0 && (
          <div className="read-note">
            <span className="read-note-label">이미 본 사람</span>
            <span className="read-note-value">
              {readers.map((r, i) => (
                <span key={i} className="read-reader">
                  {r.position ? `${r.name} ${r.position}` : r.name} {r.read_at}
                </span>
              ))}
            </span>
          </div>
        )}

        {d.attachments?.length > 0 && (
          <div className="attach-box">
            <div className="attach-title">
              첨부 {d.attachments.length}개
              {/* 한 개뿐이면 그냥 그 파일을 누르면 된다 — 두 개부터 뜻이 생긴다 */}
              {d.attachments.length >= 2 && (
                <button className="attach-zip" onClick={downloadAll}>전부 받기(zip)</button>
              )}
            </div>
            <div className="attach-list">
              {d.attachments.map((a) => (
                <span key={a.part_id} className="attach-entry">
                  {/* 버튼 안에 버튼을 넣을 수 없어 나란히 둔다 — 겉보기로는 한 덩어리다 */}
                  <button className="attach-item" onClick={() => download(a)}
                    title={`${a.filename} — 누르면 내려받기`}>
                    <Paperclip size={12} />
                    <span className="attach-name">{a.filename}</span>
                    <span className="attach-size">{formatSize(a.size)}</span>
                  </button>
                  {previewKind(a) && (
                    <button className="attach-view" onClick={() => setPreview(a)}
                      title="내려받지 않고 바로 보기">보기</button>
                  )}
                </span>
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

      {preview && (
        <AttachPreview
          account={s.accountId} folder={s.folder} uid={s.openUid} att={preview}
          onClose={() => setPreview(null)}
        />
      )}

      <div className="read-body">
        {d.html_body
          ? <div className="mail-html" dangerouslySetInnerHTML={{ __html: d.html_body }} />
          : <pre className="mail-text">{d.text_body}</pre>}
      </div>
    </div>
  );
}
