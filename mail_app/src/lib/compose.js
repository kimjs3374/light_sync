/**
 * 작성창 초기 상태 만들기.
 *
 * 인용 형식은 기존 ERP 작성 화면(templates/mail_compose.html)과 똑같이 맞춘다.
 * 같은 사람이 두 화면을 오가며 쓰는데 답장 모양이 다르면 받는 쪽이 헷갈린다.
 */

const esc = (s) => String(s || '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const addr = (a) => (a && a.email ? a.email : '');
const addrList = (list) => (list || []).map(addr).filter(Boolean);

/** 원본 본문 — HTML 이 있으면 그대로(서버에서 이미 세정됨), 없으면 평문을 감싼다 */
const sourceBody = (d) =>
  d.html_body || `<pre style="font-family:inherit;white-space:pre-wrap;">${esc(d.text_body)}</pre>`;

const quoteReply = (d) => `<br><br>
<div style="border-left:2px solid #cbd5e1;padding-left:10px;color:#64748b;">
<p style="font-size:.78rem;">${esc(d.date)} ${esc(d.from?.name)} &lt;${esc(d.from?.email)}&gt;</p>
${sourceBody(d)}
</div>`;

const quoteForward = (d) => `<br><br>
<div style="border-top:1px solid #e2e8f0;padding-top:10px;color:#64748b;">
<p style="font-size:.78rem;">---------- 전달된 메일 ----------<br>From: ${esc(d.from?.name)} &lt;${esc(d.from?.email)}&gt;<br>Date: ${esc(d.date)}<br>Subject: ${esc(d.subject)}</p>
${sourceBody(d)}
</div>`;

const stripPrefix = (s, re) => (re.test(s || '') ? s : '');

/**
 * 임시보관함인가.
 *
 * 폴더 이름이 서버마다 `Drafts` · `INBOX.Drafts` · `Draft` 로 갈려서 이름에
 * draft 가 들었는지로만 본다 — 이미 compose 스토어가 같은 잣대(`/draft/i`)로
 * "저장 뒤 목록을 다시 읽을지"를 정하고 있어, 두 곳이 갈리면 저장은 됐는데
 * 목록에 안 뜨는 일이 생긴다.
 * (lib/folders.js 의 folderLabel 과도 같은 잣대다)
 */
export const isDraftFolder = (name) => /draft/i.test(String(name || ''));

/**
 * @param mode  new | self | reply | replyAll | forward | resend | draft
 * @param ctx   { detail, folder, accountId, myEmail, signature }
 */
export function buildComposer(mode, ctx = {}) {
  const { detail: d, folder, accountId, myEmail, signature } = ctx;
  const sig = signature ? `<br><br>${signature}` : '';
  /**
   * 연 직후 상태를 그대로 복사해 둔다.
   * "쓴 게 있나"는 '비었나'가 아니라 '처음과 달라졌나'로 판단해야 한다 —
   * 서명은 새 메일에도 들어 있고, 답장은 받는사람·제목이 이미 채워져 있다.
   */
  const withInitial = (o) => ({
    ...o,
    initial: {
      to: [...o.to], cc: [...o.cc], bcc: [...o.bcc],
      subject: o.subject, bodyHtml: o.bodyHtml,
    },
  });

  const base = {
    mode, accountId,
    to: [], cc: [], bcc: [],
    showBcc: false,     // 참조는 늘 펼쳐 둔다 — 숨은참조만 필요할 때 연다
    subject: '',
    bodyHtml: sig,
    files: [],
    // 대용량 첨부 — 붙이는 즉시 올라가고, 발송 때 링크로 바뀐다
    largeFiles: [],
    // 전달할 때 원본 첨부를 서버가 IMAP 에서 직접 붙이도록 넘기는 정보
    forward: null,
    sending: false,
    saving: false,
    error: '',
    // 임시저장 흔적 — 다시 저장하면 갈아끼우고, 발송하면 지운다
    draftUid: null,
    draftFolder: '',
    savedAt: null,
    draftVersion: 0,    // 몇 번째 임시저장인지 (화면에 v3 처럼 보인다)
    savedSig: '',       // 저장한 순간의 내용 지문 — 지금과 다르면 "변경됨"
    savedAuto: false,   // 마지막 저장이 자동이었나
  };

  if (mode === 'self' && myEmail) return withInitial({ ...base, to: [myEmail] });
  if (!d) return withInitial(base);

  const subj = d.subject || '';

  if (mode === 'reply' || mode === 'replyAll') {
    const me = (myEmail || '').toLowerCase();
    const to = addrList([d.from]);
    // 전체답장은 원본 수신자·참조를 모두 데려오되 내 주소와 중복은 뺀다
    const cc = mode === 'replyAll'
      ? [...new Set([...addrList(d.to), ...addrList(d.cc)])]
        .filter((e) => e.toLowerCase() !== me && !to.some((t) => t.toLowerCase() === e.toLowerCase()))
      : [];
    return withInitial({
      ...base,
      to, cc,
      subject: stripPrefix(subj, /^re:/i) || `Re: ${subj}`,
      bodyHtml: sig + quoteReply(d),
    });
  }

  if (mode === 'forward') {
    return withInitial({
      ...base,
      subject: stripPrefix(subj, /^fwd:/i) || `Fwd: ${subj}`,
      bodyHtml: sig + quoteForward(d),
      forward: (d.attachments || []).length
        ? {
          uid: d.uid, folder, accountId,
          parts: d.attachments.map((a) => a.part_id),
          names: d.attachments.map((a) => a.filename),
        }
        : null,
    });
  }

  if (mode === 'resend') {
    // 내용만 가져온다 — 제목·본문·첨부는 그대로, 받는사람·참조는 비운다.
    // 썼던 메일을 다른 사람에게 다시 쓰는 쓰임이라, 주소가 남아 있으면
    // 지우는 것을 잊고 엉뚱한 사람에게 나간다.
    return withInitial({
      ...base,
      to: [], cc: [],
      subject: subj,
      bodyHtml: sourceBody(d),
      // 다시 보내기도 원본 첨부를 그대로 달고 간다 (전달과 같은 방식).
      // 없으면 첨부만 빠진 메일이 조용히 나간다.
      forward: (d.attachments || []).length
        ? {
          uid: d.uid, folder, accountId,
          parts: d.attachments.map((a) => a.part_id),
          names: d.attachments.map((a) => a.filename),
        }
        : null,
    });
  }

  if (mode === 'draft') {
    /**
     * 임시보관함 이어쓰기 — 저장해 둔 그대로 되살린다.
     *
     * 서명을 다시 붙이지 않는다(ctx.signature 를 안 쓴다). 저장된 본문에 이미
     * 들어 있어서, 붙이면 이어 쓸 때마다 서명이 한 벌씩 늘어난다.
     *
     * draftUid/draftFolder 를 여기서 채우는 것이 핵심이다. 이 둘이 있어야
     *  - 저장할 때 `replace_uid` 로 옛 임시본을 지우고 갈아끼우고(두 통이 안 되고),
     *  - 발송할 때 `draft_replace_uid` 로 임시본이 치워진다.
     *
     * 원본 첨부는 전달과 같은 방식으로 들고 간다 — 브라우저로 내려받았다가
     * 다시 올리지 않고, 서버가 IMAP 에서 바로 집어 붙인다.
     */
    const bcc = addrList(d.bcc);
    return withInitial({
      ...base,
      to: addrList(d.to),
      cc: addrList(d.cc),
      bcc,
      showBcc: bcc.length > 0,
      subject: subj,
      bodyHtml: sourceBody(d),
      forward: (d.attachments || []).length
        ? {
          uid: d.uid, folder, accountId,
          parts: d.attachments.map((a) => a.part_id),
          names: d.attachments.map((a) => a.filename),
        }
        : null,
      draftUid: d.uid ?? null,
      draftFolder: folder || '',
    });
  }

  return withInitial(base);
}

export const composerTitle = (c) => {
  if (c.subject) return c.subject;
  return { reply: '답장', replyAll: '전체답장', forward: '전달', resend: '다시 보내기', self: '내게 쓰기', draft: '이어서 쓰기' }[c.mode]
    || '새 메일';
};


/**
 * 작성 중인 내용의 지문.
 *
 * 임시저장한 뒤로 손을 댔는지 가리는 데 쓴다. 저장한 순간의 지문을 들고 있다가
 * 지금 것과 다르면 "변경됨"이다.
 *
 * 첨부는 파일 자체가 아니라 이름·크기만 본다 — 같은 파일을 두 번 붙이는 일은
 * 드물고, 파일을 통째로 읽으면 글자 한 자 고칠 때마다 디스크를 긁는다.
 */
export function draftSignature(w) {
  if (!w) return '';
  return JSON.stringify([
    w.to, w.cc, w.bcc, w.subject, w.bodyHtml,
    w.files.map((f) => [f.name, f.size]),
    w.largeFiles.filter((l) => l.status === 'done').map((l) => l.fileId),
    (w.kept || []).map((a) => a.index),
  ]);
}


/** 첨부를 뺀 자동저장 한도 — 이보다 크면 자동저장을 쉰다 */
export const AUTOSAVE_MAX_ATTACH = 2 * 1024 * 1024;

/** 지금 붙어 있는 (새로 올릴) 첨부의 총 바이트 */
export const attachBytes = (w) =>
  (w?.files || []).reduce((n, f) => n + (f.size || 0), 0);

/**
 * 화면을 연 뒤로 손을 댔는가.
 *
 * "나가면 사라진다" 경고와 자동저장이 같은 잣대를 써야 한다 — 한쪽만 손댔다고
 * 보면 빈 껍데기가 임시보관함에 쌓이거나, 쓴 게 소리 없이 날아간다.
 */
export function isTouched(w) {
  if (!w) return false;
  const i = w.initial || {};
  const text = (h) => String(h || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  const same = (x = [], y = []) => x.length === y.length && x.every((v, n) => v === y[n]);
  return !same(w.to, i.to) || !same(w.cc, i.cc) || !same(w.bcc, i.bcc)
    || w.subject.trim() !== String(i.subject || '').trim()
    || w.files.length > 0
    || (w.largeFiles || []).length > 0
    || text(w.bodyHtml) !== text(i.bodyHtml);
}
