import { useEffect, useState } from 'react';
import { useMail, PER_PAGE_CHOICES, LAYOUTS, LAYOUT_LABEL } from '../store/mail';
import { useSettings, SETTING_SECTIONS } from '../store/settings';
import { useContacts } from '../store/contacts';
import { api, mailApi } from '../api/client';
import { erpUrl } from '../lib/erp';
import { folderLabel, splitFolders, arrangeUserFolders } from '../lib/folders';
import { loadTheme, saveTheme, THEME_LABEL, THEMES } from '../lib/theme';
import { Close } from './Icons';

/**
 * 환경설정 — 네이버·다음 메일의 설정 구성을 따랐다.
 * 왼쪽에 칸 이름, 오른쪽에 그 칸의 내용.
 *
 * **여기서 바꾸는 것이 곧 저장이다.** 화면 설정은 누르는 즉시 브라우저에 남고,
 * 서버 설정(자동응답·전달·분류)은 [저장]을 눌러야 서버로 간다 — 그 차이를
 * 칸마다 글로 적어 둔다. 어디까지 저장됐는지 모르는 설정창이 제일 나쁘다.
 *
 * 계정마다 따로인 설정(자동응답·전달·분류)은 **지금 보고 있는 계정** 것이다.
 * 계정을 바꾸면 내용도 바뀌므로 어느 계정인지 늘 위에 적는다.
 */

function Row({ label, hint, children }) {
  return (
    <div className="set-row">
      <div className="set-label">
        <span>{label}</span>
        {hint && <em>{hint}</em>}
      </div>
      <div className="set-control">{children}</div>
    </div>
  );
}

/** 보기 방식 예시 — 말보다 그림이 빠르다. 색은 테마 토큰을 그대로 쓴다. */
function LayoutThumb({ kind }) {
  return (
    <span className={`lay-thumb lay-${kind}`} aria-hidden="true">
      {kind === 'full' ? (
        <i className="lay-read" />
      ) : (
        <>
          <i className="lay-list" />
          <i className="lay-read" />
        </>
      )}
    </span>
  );
}

function LayoutChoice({ value, onPick }) {
  const NOTE = {
    full: '누르면 메일이 화면을 다 씁니다',
    'split-v': '왼쪽 목록 · 오른쪽 메일',
    'split-h': '위 목록 · 아래 메일',
  };
  return (
    <div className="lay-choice">
      {LAYOUTS.map((k) => (
        <button key={k} type="button" className={`lay-pick${value === k ? ' on' : ''}`}
          onClick={() => onPick(k)}>
          <LayoutThumb kind={k} />
          <b>{LAYOUT_LABEL[k]}</b>
          <em>{NOTE[k]}</em>
        </button>
      ))}
    </div>
  );
}

function Choice({ value, options, onPick }) {
  return (
    <div className="set-choice">
      {options.map((o) => (
        <button key={o.value} type="button"
          className={`set-pick${String(value) === String(o.value) ? ' on' : ''}`}
          onClick={() => onPick(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ on, onChange, label }) {
  return (
    <label className="set-toggle">
      <input type="checkbox" checked={!!on} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

/* ── 화면 — 브라우저에만 남는다(계정과 무관) ────────────────────────────── */
function DisplayPanel() {
  const s = useMail();
  const [theme, setTheme] = useState(loadTheme);

  return (
    <>
      <p className="set-note">이 칸의 설정은 <b>이 브라우저에만</b> 남습니다. 누르면 바로 적용됩니다.</p>

      <Row label="화면 테마" hint="자동은 컴퓨터 설정을 따릅니다">
        <Choice
          value={theme}
          options={THEMES.map((t) => ({ value: t, label: THEME_LABEL[t] }))}
          onPick={(v) => { saveTheme(v); setTheme(v); }}
        />
      </Row>

      <Row label="메일 여는 방식" hint="목록에서 메일을 눌렀을 때">
        <LayoutChoice value={s.prefs.layout} onPick={(v) => s.setPref('layout', v)} />
      </Row>

      <Row label="목록 줄 높이">
        <Choice
          value={s.prefs.density}
          options={[
            { value: 'roomy', label: '크게' },
            { value: 'cozy', label: '보통' },
            { value: 'compact', label: '좁게' },
          ]}
          onPick={(v) => s.setPref('density', v)}
        />
      </Row>

      <Row label="한 쪽에 보여줄 메일" hint="많이 볼수록 메일함을 여는 데 오래 걸립니다">
        <Choice
          value={s.prefs.perPage}
          options={PER_PAGE_CHOICES.map((n) => ({ value: n, label: `${n}통` }))}
          onPick={(v) => { s.setPref('perPage', v); s.goPage(1); }}
        />
      </Row>

      {s.prefs.layout !== 'full' && (
        <Row
          label={s.prefs.layout === 'split-h' ? '목록과 읽기창 높이' : '목록과 읽기창 너비'}
          hint={`지금 목록이 ${Math.round(s.prefs.splitPct)}% — 경계선을 끌어서도 바꿉니다`}
        >
          <button className="set-btn" onClick={() => s.setPref('splitPct', 44)}>처음으로</button>
        </Row>
      )}

      <Row label="주소록" hint="내 주소록 · 회사 공용 · 사내 직원">
        <button className="set-btn" onClick={() => {
          useSettings.getState().close();
          useContacts.getState().setBook('personal');
          useMail.getState().openSpecial('contacts');
        }}>주소록 열기</button>
      </Row>
    </>
  );
}

/* ── 자동 처리가 실제로 도는지 알리는 띠 ───────────────────────────────
   설정은 저장됐는데 아무 일도 안 일어나는 상태가 제일 나쁘다.
   crontab 이 `flask process-mail-automation` 을 돌릴 때마다 시각이 남고,
   그게 한참 없으면 여기서 그대로 말해 준다. */
function AutomationBanner({ what }) {
  const [st, setSt] = useState(null);
  useEffect(() => { mailApi.automationStatus().then(setSt).catch(() => setSt(null)); }, []);
  if (!st) return null;
  if (!st.stale) {
    return <p className="set-note ok">자동 처리가 돌고 있습니다 (마지막 {st.last_run?.replace('T', ' ')}).</p>;
  }
  return (
    <p className="set-note bad">
      ⚠ 지금은 자동 처리가 돌지 않습니다 — <b>{what}은 저장만 되고 실행되지 않습니다.</b>
      {st.last_run ? ` (마지막 실행 ${st.last_run.replace('T', ' ')})` : ' (실행된 적 없음)'}
      <br />서버에서 <code>flask process-mail-automation</code> 을 주기적으로 돌리도록 켜야 합니다.
    </p>
  );
}

/* ── 메일함 관리 ────────────────────────────────────────────────────────
   IMAP 폴더를 직접 고친다 — 아웃룩·휴대폰에서도 그대로 바뀐다.
   기본 메일함(받은편지함·보낸편지함·임시보관함·휴지통·스팸)은 손대지 못하게 막는다:
   이름이 바뀌는 순간 우리 화면도, 보낸 사본 저장도 그 폴더를 못 찾는다. */
function FoldersPanel({ account }) {
  const folders = useMail((st) => st.folders);
  const folderPrefs = useMail((st) => st.folderPrefs);
  const { sys, user } = splitFolders(folders);

  const [name, setName] = useState('');
  const [parent, setParent] = useState('');
  const [renaming, setRenaming] = useState(null);   // {name, value}
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState('');

  /* 화면에서 끌어 옮기는 동안의 차례와 묶음.
     서버 값을 그대로 쓰지 않고 한 번 복사해 두는 이유: 끌 때마다 서버에 쏘면
     화면이 덜컹거리고, 놓기 전에 취소해도 이미 저장돼 버린다. */
  const [order, setOrder] = useState([]);
  const [groupMap, setGroupMap] = useState({});
  const [dragIdx, setDragIdx] = useState(null);

  useEffect(() => {
    const arranged = arrangeUserFolders(user, folderPrefs);
    setOrder(arranged.ordered.map((f) => f.name));
    const gm = {};
    folderPrefs.forEach((p) => { if (p.group_name) gm[p.folder] = p.group_name; });
    setGroupMap(gm);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folders, folderPrefs]);

  const reload = () => useMail.getState().loadFolders(true);
  const byName = (n) => user.find((f) => f.name === n) || { name: n };
  const knownGroups = [...new Set(Object.values(groupMap).filter(Boolean))];

  /** 차례·묶음을 통째로 저장한다 — 한 줄씩 보내면 중간에 끊겼을 때 순서가 엉킨다 */
  const savePrefs = async (nextOrder = order, nextGroups = groupMap) => {
    try {
      const r = await mailApi.saveFolderPrefs({
        account: account.id,
        items: nextOrder.map((n) => ({ folder: n, group_name: nextGroups[n] || '' })),
      });
      if (r.error) throw new Error(r.error);
      await reload();
    } catch (e) { setState(e.message || '순서를 저장하지 못했습니다'); }
  };

  const onDragOver = (i) => {
    if (dragIdx === null || dragIdx === i) return;
    setOrder((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragIdx, 1);
      next.splice(i, 0, moved);
      return next;
    });
    setDragIdx(i);
  };

  const setGroup = (folder, value) => {
    const next = { ...groupMap, [folder]: value };
    setGroupMap(next);
    return next;
  };

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true); setState('');
    try {
      const r = await mailApi.createFolder({ account: account.id, name: name.trim(), parent });
      if (r.error) throw new Error(r.error);
      setName(''); setState(`'${r.name}' 메일함을 만들었습니다.`);
      await reload();
    } catch (e) { setState(e.message || '만들지 못했습니다'); }
    finally { setBusy(false); }
  };

  const rename = async () => {
    const { name: old, value } = renaming;
    if (!value.trim()) return;
    setBusy(true); setState('');
    try {
      const r = await mailApi.renameFolder({ account: account.id, name: old, newName: value.trim() });
      if (r.error) throw new Error(r.error);
      setRenaming(null); setState('이름을 바꿨습니다.');
      await reload();
      if (useMail.getState().folder === old) useMail.getState().selectFolder(r.name);
    } catch (e) { setState(e.message || '바꾸지 못했습니다'); }
    finally { setBusy(false); }
  };

  const remove = async (f) => {
    if (!window.confirm(`'${folderLabel(f.name)}' 메일함을 지울까요?`)) return;
    setBusy(true); setState('');
    try {
      let r = await mailApi.deleteFolder({ account: account.id, name: f.name });
      if (r.error === 'not_empty') {
        const ok = window.confirm(
          `이 메일함에 ${r.count}통이 들어 있습니다`
          + (r.children ? ` (하위 메일함 ${r.children}개 포함)` : '') + '.\n'
          + '지우면 안에 든 메일도 함께 사라집니다 — 휴지통으로 가지 않습니다.\n그래도 지울까요?');
        if (!ok) { setBusy(false); return; }
        r = await mailApi.deleteFolder({ account: account.id, name: f.name, force: true });
      }
      if (r.error) throw new Error(r.error);
      setState('메일함을 지웠습니다.');
      await reload();
      if (useMail.getState().folder === f.name) useMail.getState().selectFolder('INBOX');
    } catch (e) { setState(e.message || '지우지 못했습니다'); }
    finally { setBusy(false); }
  };

  return (
    <>
      <p className="set-note">
        여기서 만든 메일함은 <b>아웃룩·휴대폰 메일앱에도 그대로 보입니다</b>(IMAP 폴더입니다).
        받은편지함·보낸편지함처럼 기본으로 있는 메일함은 고치거나 지울 수 없습니다.
      </p>

      <Row label="새 메일함">
        <div className="set-inline">
          <input className="set-input" value={name} onChange={(e) => setName(e.target.value)}
            placeholder="메일함 이름" onKeyDown={(e) => { if (e.key === 'Enter') create(); }} />
          <select className="set-input" value={parent} onChange={(e) => setParent(e.target.value)}>
            <option value="">맨 위에 만들기</option>
            {[...sys, ...user].map((f) => (
              <option key={f.name} value={f.name}>{folderLabel(f.name)} 아래</option>
            ))}
          </select>
          <button className="set-btn primary" onClick={create} disabled={busy}>만들기</button>
        </div>
      </Row>

      <Row label="기본 메일함" hint="고치거나 지울 수 없습니다">
        <table className="contact-table set-table">
          <tbody>
            {sys.map((f) => (
              <tr key={f.name}>
                <td title={f.name}>{folderLabel(f.name)}</td>
                <td className="col-count">{f.unread ? `안읽음 ${f.unread}` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Row>

      <Row label="내 메일함" hint="⠿ 를 끌어 차례를 바꿉니다. 묶음 이름을 적으면 그 이름으로 묶여 보입니다">
        {order.length === 0 ? <span className="set-empty">직접 만든 메일함이 없습니다.</span> : (
          <table className="contact-table set-table fold-table">
            <thead>
              <tr><th className="col-grip"></th><th>메일함</th><th className="col-group">묶음</th>
                <th className="col-act"></th></tr>
            </thead>
            <tbody>
              {order.map((n, i) => {
                const f = byName(n);
                return (
                  <tr key={n}
                    className={dragIdx === i ? 'dragging' : ''}
                    draggable={!renaming}
                    onDragStart={() => setDragIdx(i)}
                    onDragOver={(e) => { e.preventDefault(); onDragOver(i); }}
                    onDragEnd={() => { setDragIdx(null); savePrefs(); }}
                  >
                    <td className="col-grip" title="끌어서 차례 바꾸기">⠿</td>
                    <td title={n}>
                      {renaming?.name === n ? (
                        <input className="set-input" value={renaming.value} autoFocus
                          onChange={(e) => setRenaming({ ...renaming, value: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') rename();
                            if (e.key === 'Escape') setRenaming(null);
                          }} />
                      ) : folderLabel(n)}
                    </td>
                    <td className="col-group">
                      <input className="set-input" list="fold-group-list" placeholder="(없음)"
                        value={groupMap[n] || ''}
                        onChange={(e) => setGroup(n, e.target.value)}
                        onBlur={(e) => savePrefs(order, setGroup(n, e.target.value))} />
                    </td>
                    <td className="col-act">
                      {renaming?.name === n ? (
                        <>
                          <button className="row-act" onClick={rename} disabled={busy}>저장</button>
                          <button className="row-act" onClick={() => setRenaming(null)}>취소</button>
                        </>
                      ) : (
                        <>
                          <button className="row-act" disabled={busy}
                            onClick={() => setRenaming({ name: n, value: folderLabel(n) })}>이름</button>
                          <button className="row-act danger" disabled={busy}
                            onClick={() => remove(f)}>삭제</button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <datalist id="fold-group-list">
          {knownGroups.map((g) => <option key={g} value={g} />)}
        </datalist>
      </Row>

      {state && <p className="set-note">{state}</p>}
    </>
  );
}

/* ── 보내기 — 내가 누구로 보이는가 ──────────────────────────────────────── */
function SendingPanel({ account }) {
  const [name, setName] = useState(account?.display_name || '');
  const [sig, setSig] = useState('');
  const [state, setState] = useState('');

  useEffect(() => { setName(account?.display_name || ''); }, [account?.id, account?.display_name]);
  useEffect(() => {
    api.get('/mail/api/user-signature').then((r) => setSig(r.html || '')).catch(() => setSig(''));
  }, []);

  const save = async () => {
    setState('saving');
    try {
      const r = await api.post('/mail/api/account', { id: account.id, display_name: name.trim() });
      if (r.error) throw new Error(r.error);
      // 목록·작성화면이 쓰는 계정 정보도 같이 고쳐야 새로 고치지 않아도 바뀐다
      useMail.setState({
        accounts: useMail.getState().accounts.map((a) => (
          a.id === account.id ? { ...a, display_name: name.trim() } : a)),
      });
      setState('saved');
    } catch (e) {
      setState(e.message || '저장하지 못했습니다');
    }
  };

  return (
    <>
      <Row label="보내는 사람 이름" hint="받는 쪽에 이 이름으로 보입니다">
        <div className="set-inline">
          <input className="set-input" value={name} onChange={(e) => setName(e.target.value)}
            placeholder={account?.email || ''} />
          <button className="set-btn primary" disabled={state === 'saving'} onClick={save}>
            {state === 'saving' ? '저장 중…' : '저장'}
          </button>
        </div>
      </Row>
      {state && state !== 'saving' && (
        <p className={`set-note${state === 'saved' ? ' ok' : ' bad'}`}>
          {state === 'saved' ? '저장했습니다.' : state}
        </p>
      )}

      <Row label="서명" hint="ERP 계정 정보(부서·이름·직급·연락처)로 만들어집니다">
        <div className="set-sig">
          {sig
            ? <div className="mail-html" dangerouslySetInnerHTML={{ __html: sig }} />
            : <span className="set-empty">서명이 없습니다</span>}
        </div>
      </Row>
      <p className="set-note">
        서명 내용을 바꾸려면 ERP 의 내 정보(부서·직급·연락처)를 고쳐야 합니다.
      </p>
    </>
  );
}

/* ── 부재중 자동응답 ────────────────────────────────────────────────────── */
function AutoReplyPanel({ account }) {
  const [v, setV] = useState(null);
  const [state, setState] = useState('');

  useEffect(() => {
    setV(null); setState('');
    api.get(`/mail/api/auto-reply?account=${account.id}`)
      .then(setV)
      .catch((e) => setState(e.message || '불러오지 못했습니다'));
  }, [account.id]);

  if (!v) return <p className="set-note">{state || '불러오는 중…'}</p>;
  const patch = (o) => setV({ ...v, ...o });

  const save = async () => {
    setState('saving');
    try {
      const r = await api.post('/mail/api/auto-reply', { account_id: account.id, ...v });
      if (r.error) throw new Error(r.error);
      setState('saved');
    } catch (e) { setState(e.message || '저장하지 못했습니다'); }
  };

  return (
    <>
      <p className="set-note">
        휴가·출장처럼 자리를 비울 때, 받은 메일에 자동으로 한 통 답장합니다.
      </p>
      <AutomationBanner what="자동응답" />

      <Row label="사용">
        <Toggle on={v.is_active} onChange={(b) => patch({ is_active: b })}
          label={v.is_active ? '자동응답을 보냅니다' : '보내지 않습니다'} />
      </Row>
      <Row label="기간" hint="비워 두면 사용하는 동안 계속">
        <div className="set-inline">
          <input className="set-input" type="date" value={v.start_date || ''}
            onChange={(e) => patch({ start_date: e.target.value })} />
          <span className="set-tilde">~</span>
          <input className="set-input" type="date" value={v.end_date || ''}
            onChange={(e) => patch({ end_date: e.target.value })} />
        </div>
      </Row>
      <Row label="제목">
        <input className="set-input wide" value={v.subject || ''}
          onChange={(e) => patch({ subject: e.target.value })} />
      </Row>
      <Row label="내용">
        <textarea className="set-input wide" rows={5} value={v.body || ''}
          onChange={(e) => patch({ body: e.target.value })}
          placeholder={'예) 9/20까지 휴가입니다. 급한 건은 010-0000-0000 으로 연락 주세요.'} />
      </Row>
      <Row label="같은 사람에게" hint="한 번만 보내야 자동응답끼리 주고받지 않습니다">
        <Toggle on={v.reply_once} onChange={(b) => patch({ reply_once: b })} label="한 번만 보내기" />
      </Row>

      <div className="set-foot">
        <button className="set-btn primary" disabled={state === 'saving'} onClick={save}>
          {state === 'saving' ? '저장 중…' : '저장'}
        </button>
        {state && state !== 'saving' && (
          <span className={state === 'saved' ? 'set-ok' : 'set-bad'}>
            {state === 'saved' ? '저장했습니다.' : state}
          </span>
        )}
      </div>
    </>
  );
}

/* ── 자동 전달 ──────────────────────────────────────────────────────────── */
function ForwardPanel({ account }) {
  const [rows, setRows] = useState(null);
  const [addr, setAddr] = useState('');
  const [keep, setKeep] = useState(true);
  const [state, setState] = useState('');

  const load = () => api.get(`/mail/api/auto-forward?account=${account.id}`)
    .then((r) => setRows(Array.isArray(r) ? r : []))
    .catch((e) => setState(e.message || '불러오지 못했습니다'));

  useEffect(() => { setRows(null); load(); /* eslint-disable-next-line */ }, [account.id]);

  const add = async () => {
    const to = addr.trim();
    if (!to) return;
    setState('saving');
    try {
      const r = await api.post('/mail/api/auto-forward', {
        account_id: account.id, forward_to: to, is_active: true, keep_copy: keep,
      });
      if (r.error) throw new Error(r.error);
      setAddr(''); setState(''); await load();
    } catch (e) { setState(e.message || '추가하지 못했습니다'); }
  };

  const toggle = async (row, field, value) => {
    await api.post('/mail/api/auto-forward', { account_id: account.id, ...row, [field]: value });
    load();
  };

  const remove = async (row) => {
    if (!window.confirm(`${row.forward_to} 로 보내는 자동전달을 지울까요?`)) return;
    await api.del(`/mail/api/auto-forward/${row.id}`);
    load();
  };

  return (
    <>
      <p className="set-note">
        받은 메일을 다른 주소로 자동으로 보냅니다. <b>원본 보관</b>을 끄면 이 메일함에는 남지 않습니다.
      </p>
      <AutomationBanner what="자동전달" />

      <Row label="주소 추가">
        <div className="set-inline">
          <input className="set-input" value={addr} onChange={(e) => setAddr(e.target.value)}
            placeholder="forward@example.com"
            onKeyDown={(e) => { if (e.key === 'Enter') add(); }} />
          <Toggle on={keep} onChange={setKeep} label="원본 보관" />
          <button className="set-btn primary" onClick={add} disabled={state === 'saving'}>추가</button>
        </div>
      </Row>
      {state && state !== 'saving' && <p className="set-note bad">{state}</p>}

      {rows === null ? <p className="set-note">불러오는 중…</p>
        : rows.length === 0 ? <p className="set-note">설정된 자동전달이 없습니다.</p>
          : (
            <table className="contact-table set-table">
              <thead><tr><th>전달 주소</th><th>사용</th><th>원본 보관</th><th className="col-act"></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td title={r.forward_to}>{r.forward_to}</td>
                    <td><Toggle on={r.is_active} onChange={(b) => toggle(r, 'is_active', b)} label={r.is_active ? '사용' : '중지'} /></td>
                    <td><Toggle on={r.keep_copy} onChange={(b) => toggle(r, 'keep_copy', b)} label={r.keep_copy ? '보관' : '안 함'} /></td>
                    <td className="col-act">
                      <button className="row-act danger" onClick={() => remove(r)}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
    </>
  );
}

/* ── 자동 분류 ──────────────────────────────────────────────────────────
   규칙을 **여기서 다 만든다**. 예전엔 목록만 보여주고 만들기는 ERP 설정으로
   보냈는데, 설정이 두 화면에 나뉘면 어디서 고쳤는지를 사람이 기억해야 한다.

   조건 모양은 서버(modules/services/mail_classifier.py)가 실제로 읽는 것과
   **똑같이** 맞춘다 — {field, op, value}. 화면에만 있는 조건을 만들면
   저장은 되고 분류는 안 되는, 제일 찾기 어려운 고장이 난다. */
const COND_FIELDS = [
  ['from_email', '보낸사람 메일주소'],
  ['from_domain', '보낸사람 도메인'],
  ['from_name', '보낸사람 이름'],
  ['to_email', '받는사람 메일주소'],
  ['subject', '제목'],
  ['has_attachment', '첨부파일'],
];
const COND_OPS = [
  ['contains', '포함'], ['equals', '일치'], ['starts_with', '(으)로 시작'],
  ['ends_with', '(으)로 끝남'], ['not_contains', '포함하지 않음'], ['regex', '정규식'],
];
/* 서버가 실제로 할 수 있는 동작만 내놓는다 (apply_actions 가 아는 것) */
const ACTIONS = [
  ['move_folder', '메일함으로 이동'],
  ['add_label', '라벨 달기'],
  ['mark_read', '읽음으로 표시'],
  ['delete', '휴지통으로'],
];
const ACTION_LABEL = Object.fromEntries(ACTIONS);
const FIELD_LABEL = Object.fromEntries(COND_FIELDS);
const OP_LABEL = Object.fromEntries(COND_OPS);

const emptyRule = () => ({
  id: null, name: '', priority: 0, is_active: true,
  condition_logic: 'AND',
  conditions: [{ field: 'from_domain', op: 'contains', value: '' }],
  action_type: 'move_folder', action_value: '',
  stop_processing: true,
});

const parseConds = (json) => {
  try {
    const arr = JSON.parse(json || '[]');
    return Array.isArray(arr) && arr.length ? arr : emptyRule().conditions;
  } catch { return emptyRule().conditions; }
};

const condText = (c) => (c.field === 'has_attachment'
  ? `첨부파일 ${c.value === 'true' ? '있음' : '없음'}`
  : `${FIELD_LABEL[c.field] || c.field} ${OP_LABEL[c.op] || c.op} "${c.value}"`);

function RuleEditor({ account, rule, onDone, onCancel }) {
  const folders = useMail((s) => s.folders);
  const labels = useMail((s) => s.labels);
  const [v, setV] = useState(rule);
  const [state, setState] = useState('');

  const patch = (o) => setV({ ...v, ...o });
  const patchCond = (i, o) => patch({
    conditions: v.conditions.map((c, idx) => (idx === i ? { ...c, ...o } : c)),
  });

  const save = async () => {
    const name = v.name.trim();
    if (!name) { setState('규칙 이름을 지어 주세요.'); return; }
    const conds = v.conditions
      .map((c) => ({ ...c, value: String(c.value ?? '').trim() }))
      .filter((c) => c.value !== '');
    if (!conds.length) { setState('조건을 한 줄 이상 채워 주세요.'); return; }
    if (v.action_type === 'move_folder' && !v.action_value) { setState('옮길 메일함을 고르세요.'); return; }
    if (v.action_type === 'add_label' && !v.action_value.trim()) { setState('라벨 이름을 적어 주세요.'); return; }

    setState('saving');
    try {
      const r = await api.post('/mail/api/rules', {
        id: v.id || undefined,
        account_id: account.id,
        name,
        priority: Number(v.priority) || 0,
        is_active: v.is_active,
        condition_logic: v.condition_logic,
        conditions: conds,
        action_type: v.action_type,
        action_value: (v.action_value || '').trim(),
        stop_processing: v.stop_processing,
      });
      if (r.error) throw new Error(r.error);
      // 규칙은 새로 오는 메일에 걸린다. 방금 만든 사람은 **지금 받은편지함**에도
      // 걸리길 기대하므로 그 자리에서 물어본다 — 설정을 닫고 다시 찾아 들어오게
      // 하면 대부분 그냥 안 한다.
      if (window.confirm('규칙을 저장했습니다.\n지금 받은편지함에도 이 규칙들을 적용할까요?')) {
        try {
          const ap = await api.post('/mail/api/rules/apply', { account_id: account.id, folder: 'INBOX' });
          if (!ap.error) useMail.getState().loadMessages();
        } catch { /* 적용 실패는 저장을 되돌리지 않는다 */ }
      }
      onDone();
    } catch (e) {
      setState(e.message || '저장하지 못했습니다');
    }
  };

  return (
    <div className="rule-editor">
      <div className="rule-editor-head">{v.id ? '규칙 고치기' : '새 규칙'}</div>

      <Row label="규칙 이름" hint="목록에서 이 이름으로 보입니다">
        <input className="set-input wide" value={v.name} autoFocus
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="예) 조달청 공고는 업무함으로" />
      </Row>

      <Row label="조건" hint={v.condition_logic === 'AND' ? '모두 맞아야 합니다' : '하나만 맞으면 됩니다'}>
        <div className="set-choice">
          <button type="button" className={`set-pick${v.condition_logic === 'AND' ? ' on' : ''}`}
            onClick={() => patch({ condition_logic: 'AND' })}>모두 만족</button>
          <button type="button" className={`set-pick${v.condition_logic === 'OR' ? ' on' : ''}`}
            onClick={() => patch({ condition_logic: 'OR' })}>하나라도 만족</button>
        </div>

        {v.conditions.map((c, i) => (
          <div className="cond-row" key={i}>
            <select className="set-input cond-field" value={c.field}
              onChange={(e) => patchCond(i, {
                field: e.target.value,
                // 첨부 유무는 있음/없음 두 값뿐이라 연산자가 없다
                op: e.target.value === 'has_attachment' ? 'equals' : (c.op === 'equals' ? 'contains' : c.op),
                value: e.target.value === 'has_attachment' ? 'true' : '',
              })}>
              {COND_FIELDS.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
            </select>

            {c.field === 'has_attachment' ? (
              <select className="set-input" value={c.value || 'true'}
                onChange={(e) => patchCond(i, { value: e.target.value })}>
                <option value="true">있음</option>
                <option value="false">없음</option>
              </select>
            ) : (
              <>
                <select className="set-input cond-op" value={c.op}
                  onChange={(e) => patchCond(i, { op: e.target.value })}>
                  {COND_OPS.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
                </select>
                <input className="set-input cond-value" value={c.value || ''}
                  onChange={(e) => patchCond(i, { value: e.target.value })}
                  placeholder={c.field === 'from_domain' ? 'korea.kr' : '값'} />
              </>
            )}

            <button type="button" className="row-act danger" aria-label="조건 지우기"
              disabled={v.conditions.length <= 1}
              onClick={() => patch({ conditions: v.conditions.filter((_, idx) => idx !== i) })}>✕</button>
          </div>
        ))}
        <button type="button" className="set-btn"
          onClick={() => patch({ conditions: [...v.conditions, { field: 'subject', op: 'contains', value: '' }] })}>
          + 조건 추가
        </button>
      </Row>

      <Row label="하는 일">
        <div className="set-inline">
          <select className="set-input" value={v.action_type}
            onChange={(e) => patch({ action_type: e.target.value, action_value: '' })}>
            {ACTIONS.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
          </select>

          {v.action_type === 'move_folder' && (
            <select className="set-input" value={v.action_value}
              onChange={(e) => patch({ action_value: e.target.value })}>
              <option value="">메일함 고르기</option>
              {folders.map((f) => (
                <option key={f.name} value={f.name}>{folderLabel(f.name)}</option>
              ))}
            </select>
          )}

          {v.action_type === 'add_label' && (
            <>
              <input className="set-input" value={v.action_value} list="rule-label-list"
                onChange={(e) => patch({ action_value: e.target.value })} placeholder="라벨 이름" />
              <datalist id="rule-label-list">
                {labels.map((l) => <option key={l.id} value={l.name} />)}
              </datalist>
            </>
          )}
        </div>
        {v.action_type === 'delete' && (
          <span className="set-note bad">받자마자 휴지통으로 갑니다. 조건을 넓게 걸지 마세요.</span>
        )}
      </Row>

      <Row label="순서" hint="숫자가 작을수록 먼저 봅니다">
        <div className="set-inline">
          <input className="set-input cond-num" type="number" value={v.priority}
            onChange={(e) => patch({ priority: e.target.value })} />
          <Toggle on={v.stop_processing} onChange={(b) => patch({ stop_processing: b })}
            label="맞으면 여기서 멈추기(뒤 규칙은 안 봄)" />
          <Toggle on={v.is_active} onChange={(b) => patch({ is_active: b })} label="사용" />
        </div>
      </Row>

      <div className="set-foot">
        <button className="set-btn primary" disabled={state === 'saving'} onClick={save}>
          {state === 'saving' ? '저장 중…' : '저장'}
        </button>
        <button className="set-btn" onClick={onCancel}>취소</button>
        {state && state !== 'saving' && <span className="set-bad">{state}</span>}
      </div>
    </div>
  );
}

function RulesPanel({ account }) {
  const [rows, setRows] = useState(null);
  const [edit, setEdit] = useState(null);
  const [state, setState] = useState('');

  const load = () => api.get(`/mail/api/rules?account=${account.id}`)
    .then((r) => setRows(Array.isArray(r) ? r : []))
    .catch((e) => setState(e.message || '불러오지 못했습니다'));

  useEffect(() => { setRows(null); setEdit(null); load(); /* eslint-disable-next-line */ }, [account.id]);

  const startEdit = (r) => setEdit(r
    ? {
      id: r.id, name: r.name || '', priority: r.priority || 0, is_active: !!r.is_active,
      condition_logic: r.condition_logic || 'AND', conditions: parseConds(r.conditions_json),
      action_type: r.action_type || 'move_folder', action_value: r.action_value || '',
      stop_processing: !!r.stop_processing,
    }
    : emptyRule());

  const toggleActive = async (row, on) => {
    const r = await api.post('/mail/api/rules', {
      id: row.id, account_id: account.id, name: row.name, priority: row.priority,
      is_active: on, condition_logic: row.condition_logic,
      conditions: parseConds(row.conditions_json),
      action_type: row.action_type, action_value: row.action_value,
      stop_processing: row.stop_processing,
    });
    if (r.error) { window.alert(r.error); return; }
    load();
  };

  const remove = async (row) => {
    if (!window.confirm(`규칙 '${row.name}' 을 지울까요?`)) return;
    const r = await api.del(`/mail/api/rules/${row.id}`);
    if (r.error) { window.alert(r.error); return; }
    load();
  };

  const applyNow = async () => {
    setState('applying');
    try {
      const r = await api.post('/mail/api/rules/apply', { account_id: account.id, folder: 'INBOX' });
      if (r.error) throw new Error(r.error);
      setState(`받은편지함 ${r.processed || 0}통을 훑어 ${r.actions || 0}건을 옮겼습니다.`);
      useMail.getState().loadMessages();
    } catch (e) { setState(e.message || '적용하지 못했습니다'); }
  };

  if (edit) {
    return (
      <RuleEditor
        account={account}
        rule={edit}
        onDone={() => { setEdit(null); setState(''); load(); }}
        onCancel={() => setEdit(null)}
      />
    );
  }

  return (
    <>
      <p className="set-note">
        조건에 맞는 메일을 자동으로 옮기거나 표시합니다. 위에서부터 차례로 보고,
        <b> 맞으면 거기서 멈춥니다</b>(규칙마다 끌 수 있습니다).
        규칙은 <b>새로 오는 메일</b>에 걸립니다 — 이미 받은편지함에 있는 메일에도 걸려면
        아래 [받은편지함에 지금 적용]을 누르세요.
      </p>
      <AutomationBanner what="자동분류" />

      {rows === null ? <p className="set-note">불러오는 중…</p>
        : rows.length === 0 ? <p className="set-note">만들어 둔 규칙이 없습니다.</p>
          : (
            <table className="contact-table set-table">
              <thead>
                <tr><th className="col-order">순서</th><th>규칙</th><th>조건</th><th>하는 일</th>
                  <th className="col-use">사용</th><th className="col-act"></th></tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const conds = parseConds(r.conditions_json);
                  const summary = conds.map(condText)
                    .join(r.condition_logic === 'OR' ? ' 또는 ' : ' 그리고 ');
                  return (
                    <tr key={r.id}>
                      <td className="col-order">{r.priority}</td>
                      <td title={r.name}>{r.name}</td>
                      <td title={summary}>{summary}</td>
                      <td title={r.action_value}>
                        {ACTION_LABEL[r.action_type] || r.action_type}
                        {r.action_value ? ` · ${r.action_value}` : ''}
                      </td>
                      <td className="col-use">
                        <Toggle on={r.is_active} onChange={(b) => toggleActive(r, b)}
                          label={r.is_active ? '사용' : '중지'} />
                      </td>
                      <td className="col-act">
                        <button className="row-act" onClick={() => startEdit(r)}>수정</button>
                        <button className="row-act danger" onClick={() => remove(r)}>삭제</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

      <div className="set-foot">
        <button className="set-btn primary" onClick={() => startEdit(null)}>+ 새 규칙</button>
        <button className="set-btn" onClick={applyNow} disabled={state === 'applying'}>
          {state === 'applying' ? '적용 중…' : '받은편지함에 지금 적용'}
        </button>
      </div>
      {state && state !== 'applying' && <p className="set-note">{state}</p>}
    </>
  );
}

/* ── 스팸 · 수신차단 ────────────────────────────────────────────────────
   메일서버(mailcow)의 스팸 필터와는 **별개**다. 여기 있는 것은 "이 주소는
   스팸함으로" 라는 우리 쪽 목록이고, 판정은 서버·화면이 같은 함수를 쓴다.
   허용이 차단을 이긴다 — 도메인을 통째로 막아 두고 그 안의 거래처 한 곳만
   받는 것이 제일 흔한 쓰임이다. */
function SpamPanel({ account }) {
  const [items, setItems] = useState(null);
  const [value, setValue] = useState('');
  const [kind, setKind] = useState('block');
  const [memo, setMemo] = useState('');
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState('');

  const load = () => mailApi.spamList(account.id)
    .then((r) => setItems(r.items || []))
    .catch((e) => setState(e.message || '불러오지 못했습니다'));

  useEffect(() => { setItems(null); load(); /* eslint-disable-next-line */ }, [account.id]);

  const add = async () => {
    if (!value.trim()) return;
    setBusy(true); setState('');
    try {
      const r = await mailApi.spamAdd({ account: account.id, kind, value, memo });
      if (r.error) throw new Error(r.error);
      setValue(''); setMemo('');
      await load();
    } catch (e) { setState(e.message || '추가하지 못했습니다'); }
    finally { setBusy(false); }
  };

  const remove = async (row) => {
    if (!window.confirm(`'${row.value}' 을 목록에서 뺄까요?`)) return;
    const r = await mailApi.spamDelete(row.id);
    if (r.error) { window.alert(r.error); return; }
    load();
  };

  const applyNow = async () => {
    setBusy(true); setState('');
    try {
      const r = await mailApi.spamApply(account.id);
      if (r.error) throw new Error(r.error);
      setState(r.message || `최근 ${r.checked}통을 훑어 ${r.moved}통을 스팸함으로 옮겼습니다.`);
      useMail.getState().loadMessages();
      useMail.getState().loadFolders(true);
    } catch (e) { setState(e.message || '적용하지 못했습니다'); }
    finally { setBusy(false); }
  };

  const empty = async () => {
    if (!window.confirm('스팸함을 비울까요?\n안에 든 메일이 모두 지워집니다 — 휴지통으로 가지 않습니다.')) return;
    setBusy(true); setState('');
    try {
      const r = await mailApi.spamEmpty(account.id);
      if (r.error) throw new Error(r.error);
      setState(`스팸함에서 ${r.deleted}통을 지웠습니다.`);
      useMail.getState().loadFolders(true);
    } catch (e) { setState(e.message || '비우지 못했습니다'); }
    finally { setBusy(false); }
  };

  const blocks = (items || []).filter((i) => i.kind === 'block');
  const allows = (items || []).filter((i) => i.kind === 'allow');

  return (
    <>
      <p className="set-note">
        여기 적은 주소에서 온 메일을 <b>스팸함으로</b> 옮깁니다. 메일주소(kim@x.co.kr) 도,
        도메인(@x.co.kr) 도 됩니다. <b>수신허용이 차단을 이깁니다</b> —
        도메인을 통째로 막아 두고 그 안의 거래처 한 곳만 받을 때 씁니다.
      </p>
      <AutomationBanner what="수신차단" />

      <Row label="주소 추가">
        <div className="set-inline">
          <select className="set-input" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="block">수신차단</option>
            <option value="allow">수신허용</option>
          </select>
          <input className="set-input" value={value} onChange={(e) => setValue(e.target.value)}
            placeholder="kim@x.co.kr 또는 @x.co.kr"
            onKeyDown={(e) => { if (e.key === 'Enter') add(); }} />
          <input className="set-input" value={memo} onChange={(e) => setMemo(e.target.value)}
            placeholder="메모(왜 막았는지)" />
          <button className="set-btn primary" onClick={add} disabled={busy}>추가</button>
        </div>
      </Row>
      {state && <p className="set-note">{state}</p>}

      {items === null ? <p className="set-note">불러오는 중…</p> : (
        <>
          <Row label={`수신차단 ${blocks.length}건`}>
            {blocks.length === 0 ? <span className="set-empty">차단한 주소가 없습니다.</span> : (
              <table className="contact-table set-table">
                <tbody>
                  {blocks.map((r) => (
                    <tr key={r.id}>
                      <td title={r.value}>{r.value}</td>
                      <td title={r.memo}>{r.memo}</td>
                      <td className="col-count">{r.created_at}</td>
                      <td className="col-act"><button className="row-act danger" onClick={() => remove(r)}>빼기</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Row>

          <Row label={`수신허용 ${allows.length}건`} hint="차단보다 먼저 봅니다">
            {allows.length === 0 ? <span className="set-empty">허용 목록이 비어 있습니다.</span> : (
              <table className="contact-table set-table">
                <tbody>
                  {allows.map((r) => (
                    <tr key={r.id}>
                      <td title={r.value}>{r.value}</td>
                      <td title={r.memo}>{r.memo}</td>
                      <td className="col-count">{r.created_at}</td>
                      <td className="col-act"><button className="row-act danger" onClick={() => remove(r)}>빼기</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Row>
        </>
      )}

      <div className="set-foot">
        <button className="set-btn" onClick={applyNow} disabled={busy}>받은편지함에 지금 적용</button>
        <button className="set-btn" onClick={empty} disabled={busy}>스팸함 비우기</button>
      </div>
    </>
  );
}

/* ── 단축키 · 도움말 ────────────────────────────────────────────────────── */
const KEYS = [
  ['↑ ↓ / j k', '목록에서 위아래로'],
  ['Enter', '고른 메일 열기'],
  ['x', '고른 메일 선택(체크)'],
  ['c', '메일 쓰기'],
  ['r / f', '답장 / 전달'],
  ['/', '검색칸으로'],
  ['Esc', '최대화 풀기 → 메일 닫기'],
];

function HelpPanel() {
  return (
    <>
      <Row label="화면 안내" hint="버튼이 무엇을 하는지 순서대로 짚어 줍니다">
        <button className="set-btn primary" onClick={() => useSettings.getState().startTour()}>
          화면 안내 다시 보기
        </button>
      </Row>

      <Row label="단축키">
        <table className="contact-table set-table">
          <tbody>
            {KEYS.map(([k, v]) => (
              <tr key={k}><td className="set-key">{k}</td><td>{v}</td></tr>
            ))}
          </tbody>
        </table>
      </Row>
      <Row label="계정 · 템플릿 · 공용계정" hint="메일 서버 주소·비밀번호처럼 여기 없는 설정은 ERP 설정 화면에 있습니다">
        <a className="set-btn" href={erpUrl('/mail/settings')} target="_blank" rel="noreferrer">
          ERP 메일 설정 열기 ↗
        </a>
      </Row>
      <Row label="화면이 옛날 것 같을 때" hint="새로고침해야 새 기능이 붙습니다">
        <button className="set-btn" onClick={() => window.location.reload(true)}>새로고침</button>
      </Row>
    </>
  );
}

export default function SettingsModal() {
  const { section, goSection, close } = useSettings();
  const accounts = useMail((s) => s.accounts);
  const accountId = useMail((s) => s.accountId);
  const account = accounts.find((a) => a.id === accountId);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [close]);

  const perAccount = section !== 'display' && section !== 'help';

  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="settings-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="환경설정">
        <div className="contact-card-head">
          <h3>환경설정</h3>
          <button className="icon-btn" title="닫기" onClick={close}><Close /></button>
        </div>

        <div className="settings-body">
          <nav className="settings-nav">
            {SETTING_SECTIONS.map((s) => (
              <button key={s.key} className={`set-nav-item${section === s.key ? ' on' : ''}`}
                onClick={() => goSection(s.key)}>{s.label}</button>
            ))}
          </nav>

          <div className="settings-panel">
            {/* 계정마다 따로인 설정은 어느 계정 것인지 늘 적는다 */}
            {perAccount && (
              <div className="set-account">
                <span>설정할 계정</span>
                <b>{account?.email || '계정 없음'}</b>
                {accounts.length > 1 && <em>계정을 바꾸려면 왼쪽 위 주소를 누르세요</em>}
              </div>
            )}

            {!account && perAccount ? (
              <p className="set-note bad">메일 계정이 없어 이 설정을 쓸 수 없습니다.</p>
            ) : section === 'display' ? <DisplayPanel />
              : section === 'folders' ? <FoldersPanel account={account} />
                : section === 'sending' ? <SendingPanel account={account} />
                  : section === 'autoreply' ? <AutoReplyPanel account={account} />
                    : section === 'forward' ? <ForwardPanel account={account} />
                      : section === 'rules' ? <RulesPanel account={account} />
                        : section === 'spam' ? <SpamPanel account={account} />
                          : <HelpPanel />}
          </div>
        </div>
      </div>
    </div>
  );
}
