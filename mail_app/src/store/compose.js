import { create } from 'zustand';
import { api, mailApi } from '../api/client';
import {
  buildComposer, draftSignature, isTouched, attachBytes, AUTOSAVE_MAX_ATTACH,
} from '../lib/compose';
import { useMail } from './mail';

let seq = 0;

// ── 자동 임시저장 ─────────────────────────────────────────────────────────
// 손으로 누르지 않아도 손을 멈추면 한 번 저장한다. 임시저장 버튼과 같은 곳
// (임시보관함)에 같은 방식으로 들어간다 — 따로 보관하지 않는다.
const AUTOSAVE_IDLE_MS = 5000;   // 이만큼 조용하면 저장
let autosaveTimer = null;
const cancelAutosave = () => { clearTimeout(autosaveTimer); autosaveTimer = null; };

/**
 * 대용량 첨부 기준. 서버가 알려주는 값으로 덮어쓴다.
 * 이보다 크면 메일에 싣지 않고 Storage 에 올려 링크로 보낸다.
 */
let LARGE_THRESHOLD = 25 * 1024 * 1024;
export const getThreshold = () => LARGE_THRESHOLD;

// 여기서 부팅 즉시 부르지 않는다 — 아래 loadUploadConfig() 주석 참고.
// (첨부를 붙일 때 한 번 받는다)

let largeSeq = 0;

let CHUNK_SIZE = 8 * 1024 * 1024;

/**
 * 업로드 설정은 첫 파일을 붙일 때 한 번만 받는다.
 *
 * 앱이 뜨자마자 부르면 아직 로그인 토큰을 교환하기 전이라 401 이 떨어지고,
 * 그 401 이 "세션 만료"로 해석돼 로그인 화면으로 튕겨버린다. 실제로 로그에
 * upload-config 401 이 두 번 찍혔다.
 */
let configLoaded = false;
async function loadUploadConfig() {
  if (configLoaded) return;
  configLoaded = true;
  try {
    const c = await api.json('/mail/api/upload-config', { optional: true });
    if (c?.threshold) LARGE_THRESHOLD = c.threshold;
    if (c?.chunk_size) CHUNK_SIZE = c.chunk_size;
  } catch { /* 기본값으로 간다 */ }
}

const hex = () => Math.random().toString(16).slice(2).padEnd(13, '0')
  + Date.now().toString(16);

/**
 * 올라간 바이트 수로 진행률·속도·남은시간을 계산한다.
 *
 * 속도를 순간값 그대로 쓰면 숫자가 심하게 튀어서 읽을 수가 없다.
 * 직전 값에 가중치를 둬 완만하게 만든다.
 */
function makeProgress(total, onUpdate) {
  const t0 = performance.now();
  let lastT = t0;
  let lastBytes = 0;
  let speed = 0;          // bytes/sec

  return (loaded) => {
    const now = performance.now();
    const dt = (now - lastT) / 1000;
    if (dt >= 0.3) {
      const inst = (loaded - lastBytes) / dt;
      speed = speed ? speed * 0.65 + inst * 0.35 : inst;
      lastT = now;
      lastBytes = loaded;
    } else if (!speed) {
      const el = (now - t0) / 1000;
      if (el > 0.2) speed = loaded / el;
    }
    onUpdate({
      progress: total ? Math.min(100, Math.floor((loaded / total) * 100)) : 0,
      speed,
      remain: speed > 0 ? Math.max(0, (total - loaded) / speed) : null,
    });
  };
}

/** XHR 로 보내면서 바이트 단위 진행률을 받는다 (fetch 는 업로드 진행률을 안 준다) */
function xhrSend(method, url, body, headers, { onLoaded, onDone, onFail }) {
  const xhr = new XMLHttpRequest();
  xhr.open(method, url);
  Object.entries(headers || {}).forEach(([k, v]) => xhr.setRequestHeader(k, v));
  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) onLoaded(e.loaded);
  });
  xhr.addEventListener('load', () => onDone(xhr));
  xhr.addEventListener('error', () => onFail(new Error('연결이 끊겼습니다.')));
  xhr.addEventListener('abort', () => onFail(new Error('취소됨')));
  xhr.send(body);
  return xhr;
}

/** 단일 PUT 으로 보낼 수 있는 한계. 이 위로는 TUS 로 나눠 보낸다. */
const DIRECT_PUT_MAX = 90 * 1024 * 1024;
/**
 * TUS 조각 크기.
 *
 * 실측: 48MB 를 올릴 때 6MB×8 = 23.6초, 24MB×2 = 11.3초, 48MB×1 = 10.8초.
 * 요청 1회당 왕복 비용이 약 1.8초라 잘게 쪼갤수록 그 비용만 쌓인다.
 * Cloudflare 가 요청 하나를 100MB 에서 끊으므로 그 아래로 넉넉히 잡는다.
 */
const TUS_CHUNK = 48 * 1024 * 1024;
const b64 = (v) => btoa(String.fromCharCode(...new TextEncoder().encode(v)));

/**
 * TUS 재개 업로드 — 브라우저에서 Storage 로 바로, 크기 제한 없이.
 *
 * 단일 PUT 은 Cloudflare 가 100MB 에서 끊는다. TUS 는 6MB 씩 PATCH 로
 * 이어 붙이므로 그 한도에 걸리지 않으면서도 우리 서버를 거치지 않는다.
 * (서버는 30분짜리 토큰만 발급한다 — service 키는 브라우저에 주지 않는다)
 */
function uploadTus(file, { onProgress, onDone, onError }) {
  const state = { canceled: false, xhr: null };

  (async () => {
    let t;
    try {
      t = await api.post('/mail/api/upload-token', { filename: file.name });
      if (t.error) throw new Error(t.error);
    } catch (e) {
      if (!state.canceled) onError(e.message || '업로드 준비 실패');
      return;
    }
    if (state.canceled) return;

    const H = {
      apikey: t.token,
      Authorization: `Bearer ${t.token}`,
      'Tus-Resumable': '1.0.0',
    };

    // ① 업로드 자리 만들기
    let location;
    try {
      const res = await fetch(t.endpoint, {
        method: 'POST',
        headers: {
          ...H,
          'Upload-Length': String(file.size),
          'Upload-Metadata': [
            `bucketName ${b64(t.bucket)}`,
            `objectName ${b64(t.temp_path)}`,
            `contentType ${b64(file.type || 'application/octet-stream')}`,
          ].join(','),
        },
      });
      if (!res.ok) throw new Error(`자리 만들기 실패 (${res.status})`);
      const raw = res.headers.get('Location') || '';
      // Location 은 스토리지 내부 주소를 가리킨다 — 경로만 떼어 공개 주소에 붙인다
      const path = raw.includes('://') ? new URL(raw).pathname : raw;
      location = new URL(t.endpoint).origin + path;
    } catch (e) {
      if (!state.canceled) onError(e.message || '업로드를 시작하지 못했습니다.');
      return;
    }

    // ② 조각을 이어 붙인다 — 조각 안에서도 바이트 단위로 진행률을 낸다
    const report = makeProgress(file.size, onProgress);
    let offset = 0;
    while (offset < file.size) {
      if (state.canceled) return;
      const end = Math.min(offset + TUS_CHUNK, file.size);
      const base = offset;
      try {
        const res = await new Promise((resolve, reject) => {
          state.xhr = xhrSend(
            'PATCH', location, file.slice(offset, end),
            { ...H, 'Upload-Offset': String(offset), 'Content-Type': 'application/offset+octet-stream' },
            {
              onLoaded: (n) => report(base + n),
              onDone: (x) => (x.status >= 200 && x.status < 300
                ? resolve(x)
                : reject(new Error(`조각 전송 실패 (${x.status})`))),
              onFail: reject,
            },
          );
        });
        const next = parseInt(res.getResponseHeader('Upload-Offset') || String(end), 10);
        offset = Number.isFinite(next) ? next : end;
        report(offset);
      } catch (e) {
        if (!state.canceled) onError(e.message || '전송이 끊겼습니다.');
        return;
      }
    }

    if (!state.canceled) onDone({ file_id: t.file_id, temp_path: t.temp_path, size: file.size });
  })();

  return {
    abort() { state.canceled = true; },
  };
}

/**
 * 파일을 Storage 로 바로 올린다 (우리 서버를 거치지 않는다).
 *
 * 서명 URL 을 서버에서 받아 브라우저가 Storage 에 직접 PUT 한다.
 * 조각 방식은 같은 데이터를 두 번(브라우저→우리서버, 우리서버→Storage)
 * 실어 나르는데, 이 방식은 한 번만 간다.
 * 중간 경로가 큰 요청을 막으면(413) 조각 방식으로 되돌아간다.
 */
function uploadDirect(file, { onProgress, onDone, onError, onFallback }) {
  const state = { canceled: false, xhr: null };

  (async () => {
    let sign;
    try {
      sign = await api.post('/mail/api/upload-sign', { filename: file.name });
      if (sign.error || !sign.upload_url) throw new Error(sign.error || '업로드 준비 실패');
    } catch (e) {
      // 준비 단계에서 막히면 조각 방식으로
      if (!state.canceled) onFallback(e.message);
      return;
    }
    if (state.canceled) return;

    const report = makeProgress(file.size, onProgress);
    const xhr = new XMLHttpRequest();
    state.xhr = xhr;
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) report(e.loaded);
    });
    xhr.addEventListener('load', () => {
      if (state.canceled) return;
      if (xhr.status >= 200 && xhr.status < 300) {
        onDone({ file_id: sign.file_id, temp_path: sign.temp_path, size: file.size });
      } else if (xhr.status === 413 || xhr.status === 0) {
        // 중간 경로가 크기를 막았다 → 조각 방식으로 다시
        onFallback(`직접 업로드 거부됨 (${xhr.status})`);
      } else {
        onError(`업로드 실패 (${xhr.status})`);
      }
    });
    xhr.addEventListener('error', () => { if (!state.canceled) onFallback('직접 업로드 연결 실패'); });
    xhr.open('PUT', sign.upload_url);
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.setRequestHeader('x-upsert', 'true');
    xhr.send(file);
  })();

  return {
    abort() {
      state.canceled = true;
      try { state.xhr?.abort(); } catch { /* 이미 끝남 */ }
    },
  };
}

/**
 * 파일을 조각내어 올린다.
 *
 * 한 번에 통째로 보내면 Cloudflare 가 막아 서버까지 가지도 못한다
 * (로그에 흔적조차 남지 않는다). 조각 하나는 8MB 라 그냥 통과한다.
 * 진행률이 필요해서 fetch 대신 조각 수로 계산한다.
 */
function uploadChunked(file, { onProgress, onDone, onError }) {
  const uploadId = hex();
  const total = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
  const state = { canceled: false, uploadId };

  (async () => {
    const report = makeProgress(file.size, onProgress);
    let sent = 0;
    try {
      for (let i = 0; i < total; i++) {
        if (state.canceled) return;
        const from = i * CHUNK_SIZE;
        const blob = file.slice(from, Math.min(from + CHUNK_SIZE, file.size));
        const fd = new FormData();
        fd.append('upload_id', uploadId);
        fd.append('index', String(i));
        fd.append('chunk', blob, 'chunk');

        const base = sent;
        await new Promise((resolve, reject) => {
          xhrSend('POST', '/mail/api/upload-chunk', fd,
            api.token ? { Authorization: `Bearer ${api.token}` } : {},
            {
              onLoaded: (n) => report(base + n),
              onDone: (x) => (x.status >= 200 && x.status < 300
                ? resolve(x) : reject(new Error(`조각 전송 실패 (${x.status})`))),
              onFail: reject,
            });
        });
        sent += blob.size;
        report(sent);
      }
      if (state.canceled) return;

      onProgress(100);
      const fin = await api.post('/mail/api/upload-finish', {
        upload_id: uploadId, filename: file.name, total,
      });
      if (fin.error) throw new Error(fin.error);
      if (!state.canceled) onDone(fin);
    } catch (e) {
      if (state.canceled) return;
      const msg = /413|too large/i.test(e.message || '')
        ? '중간 경로에서 막혔습니다. 관리자에게 문의해주세요.'
        : (e.message || '업로드에 실패했습니다.');
      onError(msg);
    }
  })();

  return {
    abort() {
      state.canceled = true;
      api.del(`/mail/api/upload-chunk/${uploadId}`).catch(() => {});
    },
  };
}

/**
 * 서명 — **계정마다 다르다.** 계정별로 따로 받아 두고 재사용한다.
 *
 * 한 벌만 캐시하면 공용계정(purchase@ 등)으로 바꿔 메일을 써도 먼저 받아 둔
 * 내 개인 서명이 계속 따라붙는다. 계정을 갈아 가며 쓰는 화면이라 반드시 밟는다.
 *
 * 값이 아니라 **약속(Promise)** 을 담는다 — 작성 화면을 연달아 열어도 같은 계정을
 * 두 번 묻지 않는다.
 */
const signatureCache = new Map();

/**
 * 이 계정의 서명. 계정에 직접 적어 둔 것이 있으면 그것을, 없으면 서버가
 * ERP 정보로 만든 자동 서명을 준다(응답: `{ html, custom }`).
 */
async function getSignature(accountId) {
  const key = String(accountId ?? '');
  if (!signatureCache.has(key)) {
    signatureCache.set(key, mailApi.signature(accountId)
      .then((res) => res?.html || '')
      .catch(() => {
        // 실패는 **캐시하지 않는다.** 잠깐 끊겼다고 빈 서명을 박아 두면
        // 탭을 새로 열 때까지 서명 없는 메일만 나간다.
        signatureCache.delete(key);
        return '';
      }));
  }
  return signatureCache.get(key);
}

/**
 * 서명 캐시 비우기 — **설정에서 서명을 고친 직후에 부른다.**
 * 안 부르면 방금 고친 서명이 이 탭에서는 다음 새로고침까지 안 보인다.
 * 계정 id 를 주면 그 계정만, 안 주면 전부 비운다.
 */
export function clearSignatureCache(accountId) {
  if (accountId === undefined || accountId === null) signatureCache.clear();
  else signatureCache.delete(String(accountId));
}

export const useCompose = create((set, get) => ({
  /** 작성 중인 메일 한 건. null 이면 목록 화면. */
  active: null,

  /** 방금 끝낸 일의 결과 화면 (예약 완료 등). null 이면 안 띄운다. */
  done: null,

  /**
   * 작성 화면 열기 — 가운데 영역을 통째로 차지한다.
   * @param mode new | self | reply | replyAll | forward | resend
   * @param ctx  { detail, folder, accountId }  — 없으면 현재 메일 상태에서 가져온다
   */
  async open(mode, ctx = {}) {
    if (!get().canLeave()) return null;
    const m = useMail.getState();
    const accountId = ctx.accountId ?? m.accountId;
    const myEmail = m.accounts.find((a) => a.id === accountId)?.email || '';
    const signature = await getSignature(accountId);

    const active = {
      id: ++seq,
      ...buildComposer(mode, {
        detail: ctx.detail ?? (mode === 'new' || mode === 'self' ? null : m.detail),
        folder: ctx.folder ?? m.folder,
        accountId, myEmail, signature,
      }),
    };
    set({ active });
    return active.id;
  },

  /**
   * 임시보관함 이어쓰기 — 읽고 있던 임시본을 작성 화면으로 되살린다.
   *
   * 저장하면 **그 임시본을 갈아끼운다**(buildComposer 가 draftUid/draftFolder 를
   * 채워 두므로 saveDraft 가 replace_uid 를 싣는다). 임시보관함에 두 통이 되면
   * 무엇이 최신인지 사람이 가릴 방법이 없다.
   *
   * 읽기창은 닫는다. 저장하는 순간 이 uid 는 지워지고 새 uid 로 다시 쌓이므로,
   * 열어 둔 채로 두면 읽기창이 없는 메일을 가리키게 된다.
   */
  async openDraft(ctx = {}) {
    const m = useMail.getState();
    // detail 은 닫기 전에 붙들어 둔다 — close() 가 detail 을 비운다
    const detail = ctx.detail ?? m.detail;
    const folder = ctx.folder ?? m.folder;
    const accountId = ctx.accountId ?? m.accountId;
    if (!detail) return null;
    if (!get().canLeave()) return null;

    const active = {
      id: ++seq,
      ...buildComposer('draft', {
        detail, folder, accountId,
        myEmail: m.accounts.find((a) => a.id === accountId)?.email || '',
        // 서명은 일부러 비운다 — 저장된 본문에 이미 들어 있다
        signature: '',
      }),
    };
    m.close();
    set({ active, done: null });
    return active.id;
  },

  /**
   * 예약해 둔 메일을 작성 화면으로 불러와 고친다.
   * 편집기·주소칸·첨부를 새로 만들지 않고 작성 화면을 그대로 쓴다.
   */
  async openScheduled(id) {
    if (!get().canLeave()) return false;
    const m = useMail.getState();
    try {
      const d = await api.get(`/mail/api/schedule/${id}`);
      if (d.error) { window.alert(d.error); return false; }
      const split = (v) => String(v || '').split(',').map((x) => x.trim()).filter(Boolean);
      const when = new Date(String(d.scheduled_at).replace(' ', 'T'));
      const active = {
        id: ++seq,
        mode: 'editScheduled',
        scheduleId: d.id,
        scheduledAt: when,
        accountId: m.accountId,
        to: split(d.to), cc: split(d.cc), bcc: split(d.bcc),
        showBcc: split(d.bcc).length > 0,
        subject: d.subject || '',
        bodyHtml: d.body || '',
        files: [],
        largeFiles: [],
        // 이미 올려둔 첨부 — 지울 수 있고, 남긴 것만 저장 때 서버로 번호를 넘긴다
        kept: d.attachments || [],
        forward: null,
        sending: false, saving: false, error: '',
        draftUid: null, draftFolder: '', savedAt: null,
        draftVersion: 0, savedSig: '',
        initial: {
          to: split(d.to), cc: split(d.cc), bcc: split(d.bcc),
          subject: d.subject || '', bodyHtml: d.body || '',
        },
      };
      set({ active, done: null });
      return true;
    } catch (e) {
      window.alert(e.message || '예약 메일을 불러오지 못했습니다.');
      return false;
    }
  },

  /** 예약 수정 화면에서 이미 올려둔 첨부 하나 빼기 */
  removeKept(index) {
    set((s) => (s.active
      ? { active: { ...s.active, kept: s.active.kept.filter((a) => a.index !== index) } }
      : {}));
  },

  /** 예약 수정 저장 */
  async saveScheduled() {
    const w = get().active;
    if (!w?.scheduleId || w.sending) return;
    if (!w.to.length) { get().update({ error: '받는 사람을 입력하세요.' }); return; }
    const when = w.scheduledAt;
    if (!(when instanceof Date) || Number.isNaN(when.getTime())) {
      get().update({ error: '예약 시각을 확인해주세요.' });
      return;
    }
    if (when.getTime() <= Date.now()) {
      get().update({ error: '지난 시각으로는 예약할 수 없습니다.' });
      return;
    }
    get().update({ sending: true, error: '' });
    try {
      const pad = (n) => String(n).padStart(2, '0');
      const at = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())} `
        + `${pad(when.getHours())}:${pad(when.getMinutes())}:00`;
      const fd = get()._formData(w);
      fd.append('scheduled_at', at);
      fd.append('keep_attachments', JSON.stringify(w.kept.map((a) => a.index)));

      const res = await api.json(`/mail/api/schedule/${w.scheduleId}`, { method: 'PUT', body: fd });
      if (res.error) { get().update({ sending: false, error: res.error }); return; }
      set({
        active: null,
        done: {
          kind: 'scheduled', scheduleId: w.scheduleId,
          at, when,
          to: [...w.to], cc: [...w.cc], bcc: [...w.bcc],
          subject: w.subject,
          attachments: res.attachment_count || 0,
          accountId: w.accountId,
          canceled: false,
          edited: true,
        },
      });
      return true;
    } catch (e) {
      get().update({ sending: false, error: e.message || '저장하지 못했습니다.' });
    }
  },

  update(patch) {
    set((s) => (s.active ? { active: { ...s.active, ...patch } } : {}));
    get()._scheduleAutosave();
  },

  /**
   * 자동저장 시계 다시 맞추기 — 글자를 칠 때마다 뒤로 민다.
   * 치는 도중에 저장이 끼어들면 커서가 튀고 서버도 쓸데없이 두드린다.
   */
  _scheduleAutosave() {
    cancelAutosave();
    autosaveTimer = setTimeout(() => get()._autosave(), AUTOSAVE_IDLE_MS);
  },

  /**
   * 자동 임시저장.
   *
   * 건너뛰는 경우를 분명히 해둔다 — 조용히 저장 안 되는 게 제일 나쁘다:
   *  - 예약 메일 수정: 임시저장이 아니라 예약본 고치기다
   *  - 아직 아무것도 안 썼다: 빈 껍데기를 임시보관함에 쌓지 않는다
   *  - 고친 게 없다: 같은 걸 다시 올리지 않는다
   *  - 저장/발송 중: 겹쳐 쏘지 않는다
   *  - 첨부가 크다: 첨부는 저장할 때마다 **다시 올라간다.** 40MB 를 5초마다
   *    올릴 수는 없다. 이때는 쉬고, 화면이 "첨부가 커서 자동저장 안 함"을 적는다
   */
  async _autosave() {
    const w = get().active;
    if (!w || w.mode === 'editScheduled') return;
    if (w.saving || w.sending) return;
    if (!isTouched(w)) return;
    if (draftSignature(w) === w.savedSig) return;
    if (attachBytes(w) > AUTOSAVE_MAX_ATTACH) return;
    await get().saveDraft({ auto: true });
  },

  /**
   * 쓰던 내용이 있으면 한 번 물어본다.
   * 작성 화면이 페이지라 폴더를 누르면 그냥 사라지는데, 그때 조용히
   * 날아가면 안 된다.
   */
  canLeave() {
    const a = get().active;
    if (!a) return true;
    // 연 직후와 달라진 게 없으면 묻지 않는다
    if (!isTouched(a)) return true;
    // 임시저장해 둔 그대로면 사라지는 게 아니다 — 임시보관함에 남아 있다
    if (a.savedAt && draftSignature(a) === a.savedSig) return true;

    /**
     * 쓰던 게 있어도 **묻지 않고 임시보관함에 넣고 보낸다.**
     * 메일함을 누른 사람은 그 메일함을 보려는 것이지 "예/아니오" 를 고르려는 게 아니다.
     * 확인창이 뜨면 한 번 눌러서는 안 옮겨진다 — 자동저장이 이미 있는 화면에서
     * 굳이 물을 이유가 없다. 저장은 뒤에서 마저 끝내고, 됐는지는 띠로 알린다.
     *
     * 못 넣는 경우에만 예전처럼 묻는다:
     *  - 예약 메일 수정: 임시저장이 아니라 예약본 고치기다
     *  - 저장·발송 중: 겹쳐 쏘지 않는다
     *  - 대용량 첨부: 나가면서 temp 를 지우므로(_cleanupLarge) 저장본이 깨진다
     *  - 첨부가 큼: 첨부는 저장할 때마다 다시 올라간다. 나가는 길에 붙들 수 없다
     */
    const stashable = a.mode !== 'editScheduled'
      && !a.saving && !a.sending
      && !(a.largeFiles || []).length
      && attachBytes(a) <= AUTOSAVE_MAX_ATTACH;
    if (stashable) {
      get()._stashDraft(a);
      return true;
    }
    return window.confirm('쓰던 메일이 사라집니다. 그래도 나갈까요?');
  },

  /**
   * 나가면서 임시보관함에 넣기.
   *
   * 작성창(active)은 곧 비워지므로 **지금 내용을 인자로 들고 간다** —
   * saveDraft() 처럼 get().active 를 보면 저장할 대상이 이미 없다.
   */
  async _stashDraft(w) {
    cancelAutosave();
    try {
      const fd = get()._formData(w);
      if (w.draftUid) fd.append('replace_uid', String(w.draftUid));
      const res = await api.json('/mail/api/draft', { method: 'POST', body: fd });
      if (res.error) throw new Error(res.error);
      set({ notice: '쓰던 메일을 임시보관함에 넣었습니다.' });
      const m = useMail.getState();
      if (/draft/i.test(m.folder)) m.loadMessages();   // 임시보관함을 보고 있었다면 바로 보인다
    } catch (e) {
      // 조용히 날아가는 것이 제일 나쁘다 — 실패는 반드시 알린다
      set({ notice: `임시보관함에 넣지 못했습니다: ${e.message || '알 수 없는 오류'}` });
    }
  },

  close({ force = false } = {}) {
    if (!force && !get().canLeave()) return false;
    cancelAutosave();
    get()._cleanupLarge();   // 올려둔 임시 파일은 두고 가지 않는다
    set({ active: null, done: null });
    return true;
  },

  /** 큰 첨부 발송이 끝났다 — 이제야 작성 화면을 치운다 */
  sendJobDone() {
    const w = get().active;
    set({ active: null, sendJob: null, done: null });
    const m = useMail.getState();
    if (/sent/i.test(m.folder)) m.loadMessages();
    m.loadFolders(true);
    set({ notice: w ? '큰 첨부를 다 올리고 메일을 보냈습니다.' : '메일을 보냈습니다.' });
  },

  /** 실패 — 작성 화면을 그대로 돌려준다. 여기서 닫으면 쓴 것이 사라진다 */
  sendJobFailed(message) {
    set({ sendJob: null });
    get().update({ sending: false, error: message || '보내지 못했습니다.' });
  },

  /** 결과 화면 닫기 */
  clearDone() { set({ done: null }); },

  /** 큰 첨부를 올리며 보내는 중인 일감 (null 이면 없음) */
  sendJob: null,

  /** 화면 아래 띠로 잠깐 알리는 말 (나가면서 임시저장 등) */
  notice: '',
  clearNotice() { set({ notice: '' }); },

  /** 예약 시각 변경 — 본문·첨부는 그대로 두고 시각만 바꾼다 */
  async reschedule(whenLocal) {
    const d = get().done;
    if (!d?.scheduleId) return null;
    const when = new Date(whenLocal);
    if (Number.isNaN(when.getTime()) || when.getTime() <= Date.now()) return null;
    const pad = (n) => String(n).padStart(2, '0');
    const at = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())} `
      + `${pad(when.getHours())}:${pad(when.getMinutes())}:00`;
    try {
      const res = await api.json(`/mail/api/schedule/${d.scheduleId}`, {
        method: 'PATCH', body: { scheduled_at: at },
      });
      if (res.error) return { error: res.error };
      set({ done: { ...d, at, when } });
      return { ok: true };
    } catch (e) {
      return { error: e.message || '예약을 바꾸지 못했습니다.' };
    }
  },

  /** 결과 화면에서 바로 예약 취소 */
  async cancelScheduled() {
    const d = get().done;
    if (!d?.scheduleId) return false;
    try {
      const res = await api.del(`/mail/api/schedule/${d.scheduleId}`);
      if (res.error) return false;
      set({ done: { ...d, canceled: true } });
      return true;
    } catch {
      return false;
    }
  },

  addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    loadUploadConfig();
    const key = (f) => `${f.name}:${f.size}:${f.lastModified}`;

    const small = [];
    const big = [];
    const cur = get().active;
    if (!cur) return;
    const have = new Set([
      ...cur.files.map(key),
      ...cur.largeFiles.map((l) => `${l.name}:${l.size}:${l.lastModified}`),
    ]);
    for (const f of incoming) {
      if (have.has(key(f))) continue;
      have.add(key(f));
      (f.size > LARGE_THRESHOLD ? big : small).push(f);
    }

    if (small.length) {
      set((s) => (s.active ? { active: { ...s.active, files: [...s.active.files, ...small] } } : {}));
    }
    // 큰 파일은 붙이는 즉시 올린다 — 보내기를 누른 뒤 몇 분씩 멈춰 있으면 고장으로 보인다
    for (const f of big) get()._startLargeUpload(f);
  },

  _startLargeUpload(file) {
    const id = ++largeSeq;
    const entry = {
      id, name: file.name, size: file.size, lastModified: file.lastModified,
      status: 'uploading', progress: 0, speed: 0, remain: null,
      fileId: null, tempPath: null, error: '', xhr: null,
    };
    set((s) => (s.active ? { active: { ...s.active, largeFiles: [...s.active.largeFiles, entry] } } : {}));

    const patch = (p) => set((s) => (s.active
      ? { active: { ...s.active, largeFiles: s.active.largeFiles.map((l) => (l.id === id ? { ...l, ...p } : l)) } }
      : {}));

    const done = (r) => patch({
      status: 'done', progress: 100, fileId: r.file_id, tempPath: r.temp_path, xhr: null,
    });
    const fail = (msg) => patch({ status: 'error', error: msg, xhr: null });

    const startChunked = (why) => {
      console.info('조각 업로드로 전환:', why);
      patch({ progress: 0, note: '조각 전송' });
      const t = uploadChunked(file, {
        onProgress: (p) => patch(p),
        onDone: done,
        onError: fail,
      });
      patch({ xhr: t });
    };

    if (file.size > DIRECT_PUT_MAX) {
      // 단일 PUT 으로는 중간 경로를 못 지난다 → 나눠 보내되 목적지는 Storage 직접
      const t = uploadTus(file, {
        onProgress: (p) => patch(p),
        onDone: done,
        onError: (msg) => startChunked(msg),   // 그래도 안 되면 서버 경유
      });
      patch({ xhr: t });
      return;
    }

    // 우선 Storage 로 직접 — 막히면 조각 방식으로 되돌아간다
    const task = uploadDirect(file, {
      onProgress: (p) => patch(p),
      onDone: done,
      onError: fail,
      onFallback: startChunked,
    });
    patch({ xhr: task });
  },

  /** 대용량 첨부 하나 제거 — 올라간 것은 Storage 에서도 지운다 */
  removeLarge(id) {
    const w = get().active;
    const item = w?.largeFiles.find((l) => l.id === id);
    if (!item) return;
    if (item.xhr) { try { item.xhr.abort(); } catch { /* 이미 끝남 */ } }
    if (item.fileId) get()._deleteTemp(item);
    set((s) => (s.active
      ? { active: { ...s.active, largeFiles: s.active.largeFiles.filter((l) => l.id !== id) } }
      : {}));
  },

  _deleteTemp(item) {
    if (!item?.fileId) return;
    const ext = (item.tempPath || '').includes('.')
      ? item.tempPath.slice(item.tempPath.lastIndexOf('.')) : '';
    api.del(`/mail/api/upload-temp/${item.fileId}?ext=${encodeURIComponent(ext)}`)
      .catch(() => { /* 정리 실패는 만료 정리에 맡긴다 */ });
  },

  /** 작성을 접을 때 올려둔 임시 파일 치우기 */
  _cleanupLarge() {
    const w = get().active;
    if (!w) return;
    for (const l of w.largeFiles) {
      if (l.xhr) { try { l.xhr.abort(); } catch { /* 무시 */ } }
      if (l.fileId) get()._deleteTemp(l);
    }
  },

  removeFile(idx) {
    set((s) => (s.active
      ? { active: { ...s.active, files: s.active.files.filter((_, i) => i !== idx) } }
      : {}));
  },

  /** 발송·임시저장이 공유하는 본문 꾸러미 */
  /** 파일서버에서 고른 파일 담기 (NasPicker 가 부른다) */
  addNasFiles(list) {
    set((st) => {
      if (!st.active) return {};
      const have = new Set((st.active.nasFiles || []).map((f) => f.path));
      const add = (list || []).filter((f) => f.path && !have.has(f.path));
      if (!add.length) return {};
      return { active: { ...st.active, nasFiles: [...(st.active.nasFiles || []), ...add] } };
    });
    get()._scheduleAutosave();
  },

  removeNasFile(path) {
    set((st) => (st.active
      ? { active: { ...st.active, nasFiles: (st.active.nasFiles || []).filter((f) => f.path !== path) } }
      : {}));
    get()._scheduleAutosave();
  },

  _formData(w) {
    const fd = new FormData();
    fd.append('account_id', String(w.accountId));
    fd.append('to', w.to.join(','));
    fd.append('cc', w.cc.join(','));
    fd.append('bcc', w.bcc.join(','));
    fd.append('subject', w.subject);
    fd.append('body', w.bodyHtml);
    w.files.forEach((f) => fd.append('attachments', f, f.name));
    // 이미 올려둔 대용량 첨부 — 서버가 첨부 보관함으로 옮기고 본문에 링크를 넣는다
    const ready = w.largeFiles.filter((l) => l.status === 'done');
    if (ready.length) {
      fd.append('large_files', JSON.stringify(ready.map((l) => ({
        file_id: l.fileId, temp_path: l.tempPath, filename: l.name, size: l.size,
      }))));
    }
    // 파일서버에서 고른 첨부 — **경로만** 보낸다.
    // 파일 내용은 서버가 사내망에서 직접 읽는다(브라우저는 바이트를 만지지 않는다).
    if (w.nasFiles?.length) {
      fd.append('nas_files', JSON.stringify(w.nasFiles.map((f) => f.path)));
    }
    if (w.forward) {
      // 원본 첨부는 브라우저를 거치지 않고 서버가 IMAP 에서 바로 가져다 붙인다
      fd.append('forward_source_uid', String(w.forward.uid));
      fd.append('forward_account_id', String(w.forward.accountId));
      fd.append('forward_folder', w.forward.folder);
      fd.append('forward_parts', JSON.stringify(w.forward.parts));
    }
    return fd;
  },

  /**
   * 내게쓰기 — 받는사람에 내 주소를 넣고 빼는 토글.
   *
   * 켜짐/꺼짐을 따로 기억하지 않는다. "받는사람에 내 주소가 있는가"가 곧
   * 상태다. 그래야 주소를 손으로 지우거나 붙여 넣어도 버튼 표시가 어긋나지 않는다.
   */
  toggleSelf() {
    const w = get().active;
    if (!w) return;
    const me = useMail.getState().accounts.find((a) => a.id === w.accountId)?.email;
    if (!me) return;
    const eq = (x) => x.toLowerCase() === me.toLowerCase();
    get().update({ to: w.to.some(eq) ? w.to.filter((t) => !eq(t)) : [...w.to, me] });
  },

  /**
   * 교체 저장 뒤, 원본 첨부가 가리키는 자리를 새 임시본으로 옮긴다.
   *
   * 옮길 대상은 **방금 지워진 임시본을 가리키던 forward 뿐**이다.
   * 전달·다시보내기의 forward 는 받은편지함·보낸편지함의 살아 있는 메일을
   * 가리키므로 손대지 않는다.
   *
   * 새 part 번호는 서버가 메시지를 다시 조립하면서 정해지므로(= 우리가 계산할 수
   * 없다) 새 임시본을 한 번 읽어 확인한다. 이어쓰기 중인 임시본에만, 저장할
   * 때만 한 번 도는 길이다.
   */
  async _repointForward(w, res) {
    const fwd = w.forward;
    if (!fwd) return null;
    const wasThisDraft = w.draftUid
      && String(fwd.uid) === String(w.draftUid)
      && fwd.folder === w.draftFolder;
    if (!wasThisDraft || !res.uid) return fwd;
    try {
      const d = await mailApi.message({
        account: w.accountId, folder: res.folder, uid: res.uid,
      });
      const atts = d?.attachments || [];
      if (!atts.length) return null;   // 첨부가 없으면 겨눌 자리도 없다
      return {
        uid: res.uid, folder: res.folder, accountId: w.accountId,
        parts: atts.map((a) => a.part_id),
        names: atts.map((a) => a.filename),
      };
    } catch {
      // 못 읽었으면 있던 것을 그대로 둔다 — 여기서 null 로 지우면
      // 첨부가 '확실히' 사라진다. 틀릴 수 있는 쪽보다 나쁘다.
      return fwd;
    }
  },

  /**
   * 임시저장 — 다시 누르면(또는 자동저장이 돌면) 앞서 저장한 임시본을 갈아끼운다.
   * 자동·수동이 같은 길을 쓴다. 임시보관함에 남는 건 늘 한 통이다.
   */
  async saveDraft({ auto = false } = {}) {
    const w = get().active;
    if (!w || w.saving) return;
    cancelAutosave();   // 지금 저장하니 예약된 자동저장은 취소
    get().update({ saving: true, error: '' });
    try {
      const fd = get()._formData(w);
      // 지문은 **보내기 직전의 내용**으로 뜬다 — 저장이 오가는 동안 손을 대면
      // 그건 아직 저장 안 된 변경이다. 응답 시점에 뜨면 그걸 놓친다.
      const sig = draftSignature(w);
      if (w.draftUid) fd.append('replace_uid', String(w.draftUid));
      const res = await api.json('/mail/api/draft', { method: 'POST', body: fd });
      if (res.error) {
        get().update({ saving: false, error: res.error });
        return;
      }
      // ⚠ 교체 저장은 옛 임시본을 **지우고** 새로 쌓는다. forward 가 방금 지워진
      //   그 uid 를 가리킨 채로 남으면(=임시보관함 이어쓰기) 다음 저장 때 서버가
      //   없는 메일에서 첨부를 찾다가 조용히 빈손으로 돌아온다 — 두 번째 저장부터
      //   첨부만 사라진 임시본이 남는다. 새로 쌓인 임시본으로 다시 겨눈다.
      const forward = await get()._repointForward(w, res);
      get().update({
        saving: false,
        draftUid: res.uid || null,
        draftFolder: res.folder || '',
        savedAt: new Date(),
        draftVersion: (w.draftVersion || 0) + 1,
        savedSig: sig,
        savedAuto: auto,
        forward,
      });
      // 임시보관함을 보고 있었다면 방금 저장분이 바로 보여야 한다
      const m = useMail.getState();
      if (/draft/i.test(m.folder)) m.loadMessages();
      return true;
    } catch (e) {
      get().update({ saving: false, error: e.message || '임시저장에 실패했습니다.' });
    }
  },

  /**
   * 예약발송.
   *
   * 첨부는 예약 시점에 서버가 Storage 로 옮겨 두고, 보낼 시각이 되면
   * 스케줄러가 꺼내 붙인다. 그래서 발송과 똑같이 multipart 로 보낸다.
   */
  async schedule(whenLocal) {
    cancelAutosave();
    const w = get().active;
    if (!w) return;
    if (!w.to.length) { get().update({ error: '받는 사람을 입력하세요.' }); return; }
    const when = new Date(whenLocal);
    if (Number.isNaN(when.getTime())) { get().update({ error: '예약 시각을 확인해주세요.' }); return; }
    if (when.getTime() <= Date.now()) { get().update({ error: '지난 시각으로는 예약할 수 없습니다.' }); return; }

    get().update({ sending: true, error: '' });
    try {
      const pad = (n) => String(n).padStart(2, '0');
      const at = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())} `
        + `${pad(when.getHours())}:${pad(when.getMinutes())}:00`;
      const fd = get()._formData(w);
      fd.append('scheduled_at', at);
      const res = await api.json('/mail/api/schedule', { method: 'POST', body: fd });
      if (res.error) { get().update({ sending: false, error: res.error }); return; }
      // 알림창으로 알리고 끝내면 무엇을 언제 보내기로 했는지 남는 게 없다.
      // 예약 내용을 그대로 보여주는 화면으로 넘긴다.
      set({
        active: null,
        done: {
          kind: 'scheduled',
          scheduleId: res.id,
          at, when,
          to: [...w.to], cc: [...w.cc], bcc: [...w.bcc],
          subject: w.subject,
          attachments: res.attachment_count || 0,
          accountId: w.accountId,
          canceled: false,
        },
      });
      return true;
    } catch (e) {
      get().update({ sending: false, error: e.message || '예약에 실패했습니다.' });
    }
  },

  /** 템플릿 적용 — 비어 있는 칸만 채우고 본문은 앞에 끼워 넣는다 */
  applyTemplate(t) {
    const w = get().active;
    if (!w) return;
    const split = (v) => String(v || '').split(',').map((x) => x.trim()).filter(Boolean);
    get().update({
      subject: w.subject || t.subject || '',
      to: w.to.length ? w.to : split(t.to_addresses),
      cc: w.cc.length ? w.cc : split(t.cc_addresses),
      bodyHtml: (t.body || '') + w.bodyHtml,
    });
  },

  async saveAsTemplate(name) {
    const w = get().active;
    if (!w || !name) return;
    const res = await api.post('/mail/api/templates', {
      name,
      subject: w.subject,
      body: w.bodyHtml,
      to_addresses: w.to.join(','),
      cc_addresses: w.cc.join(','),
      is_shared: false,
    });
    return !res.error;
  },

  async send() {
    cancelAutosave();
    const w = get().active;
    if (!w || w.sending) return;
    if (!w.to.length) {
      get().update({ error: '받는 사람을 입력하세요.' });
      return;
    }
    if (w.largeFiles.some((l) => l.status === 'uploading')) {
      get().update({ error: '대용량 첨부를 올리는 중입니다. 끝나면 보낼 수 있습니다.' });
      return;
    }
    get().update({ sending: true, error: '' });

    const fd = get()._formData(w);
    // 임시저장해 둔 게 있으면 발송 후 그 임시본을 지우게 한다
    if (w.draftUid && w.draftFolder) {
      fd.append('draft_replace_uid', String(w.draftUid));
      fd.append('draft_folder', w.draftFolder);
    }

    try {
      const res = await api.json('/mail/api/send', { method: 'POST', body: fd });
      if (res.error) {
        get().update({ sending: false, error: res.error });
        return;
      }

      /* 큰 첨부가 있으면 서버가 **뒤에서** 옮기며 보낸다. 여기서는 일감 번호만 받는다.
         작성 화면은 **닫지 않는다** — 실패하면 쓴 것을 그대로 돌려줘야 한다. */
      if (res.job_id) {
        set({
          sendJob: { job_id: res.job_id, total_bytes: res.total_bytes, file_count: res.file_count },
        });
        get().update({ sending: true });   // 보내는 중이라 버튼은 잠가 둔다
        return true;
      }

      set({ active: null, done: null });   // 옮겨간 임시파일을 지우면 안 되므로 close() 를 안 쓴다
      // 보낸편지함을 보고 있었다면 방금 보낸 메일이 바로 보여야 한다
      const m = useMail.getState();
      if (/sent/i.test(m.folder)) m.loadMessages();
      m.loadFolders(true);
      return true;
    } catch (e) {
      get().update({ sending: false, error: e.message || '발송에 실패했습니다.' });
    }
  },
}));
