import { useEffect, useRef, useState } from 'react';
import { useMail } from '../store/mail';
import { mailApi } from '../api/client';
import { useCompose } from '../store/compose';
import { useContacts } from '../store/contacts';

/**
 * 보낸사람 이름을 누르면 뜨는 메뉴 — 메일보내기 · 주소록에 추가 · 이 사람 메일 검색 · 주소 복사.
 *
 * 자리는 fixed 로 잡는다. 목록 줄 안에 absolute 로 붙이면 목록의 스크롤 영역에
 * 잘려서 메뉴 절반이 안 보인다. 화면 밖으로 나가지 않게 끝에서 되민다.
 */
export default function SenderMenu({ anchor, name, email, onClose }) {
  const ref = useRef(null);
  const [copied, setCopied] = useState(false);
  const [pos, setPos] = useState({ left: anchor.left, top: anchor.bottom + 4 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const left = Math.min(anchor.left, window.innerWidth - box.width - 10);
    const top = anchor.bottom + box.height > window.innerHeight - 10
      ? Math.max(10, anchor.top - box.height - 4)     // 아래가 모자라면 위로 편다
      : anchor.bottom + 4;
    setPos({ left: Math.max(10, left), top });
  }, [anchor]);

  useEffect(() => {
    const onDown = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    const t = setTimeout(() => document.addEventListener('mousedown', onDown), 0);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onClose);
    // 목록이 스크롤되면 메뉴만 제자리에 남아 엉뚱한 줄을 가리킨다 — 그냥 닫는다
    window.addEventListener('scroll', onClose, true);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onClose);
      window.removeEventListener('scroll', onClose, true);
    };
  }, [onClose]);

  const write = async () => {
    const id = await useCompose.getState().open('new');
    if (id) useCompose.getState().update({ to: [email] });
    onClose();
  };

  const addContact = () => {
    // 같은 주소가 이미 있으면 서버가 그 줄을 고친다 — 두 줄로 늘지 않는다
    useContacts.getState().startEdit({ name: name || '', email });
    onClose();
  };

  const searchMail = () => {
    useMail.getState().searchAdvanced({ from: email });
    onClose();
  };

  /** 이 주소에서 오는 메일을 앞으로 스팸함으로 — 목록에 넣기만 한다.
      이미 와 있는 메일까지 옮기는 것은 설정 > 스팸의 [지금 적용]이 한다. */
  const block = async () => {
    if (!window.confirm(`${email} 에서 오는 메일을 앞으로 스팸함으로 보낼까요?`)) return;
    try {
      const account = useMail.getState().accountId;
      const r = await mailApi.spamAdd({ account, kind: 'block', value: email, memo: '' });
      if (r.error) throw new Error(r.error);
      // 목록에 넣는 데서 끝내면 "차단했는데 그대로 있다" 가 된다 —
      // 그 주소 메일은 그 자리에서 스팸함으로 치운다(그 주소만 찾으므로 빠르다)
      const applied = await mailApi.spamApply(account, email).catch(() => null);
      useMail.getState().loadMessages();
      useCompose.setState({
        notice: applied?.moved
          ? `${email} 을 차단하고 ${applied.moved}통을 스팸함으로 옮겼습니다.`
          : `${email} 을 차단했습니다. 앞으로 오는 메일은 스팸함으로 갑니다.`,
      });
    } catch (e) {
      useCompose.setState({ notice: e.message || '차단하지 못했습니다' });
    }
    onClose();
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(email);
    } catch {
      // https 가 아니거나 권한이 없을 때 — 옛 방식으로 되돌린다
      const ta = document.createElement('textarea');
      ta.value = email;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch { /* 여기까지 막히면 포기한다 */ }
      ta.remove();
    }
    setCopied(true);
    setTimeout(onClose, 700);
  };

  return (
    <div className="sender-menu" ref={ref} style={{ left: pos.left, top: pos.top }} role="menu">
      <div className="sm-head">
        {name && <b title={name}>{name}</b>}
        <span title={email}>{email}</span>
      </div>
      <button className="sm-item" onClick={write}>메일 보내기</button>
      <button className="sm-item" onClick={addContact}>주소록에 추가</button>
      <button className="sm-item" onClick={searchMail}>이 사람 메일 검색</button>
      <button className="sm-item danger" onClick={block}>이 주소 수신차단</button>
      <button className="sm-item" onClick={copy}>{copied ? '복사했습니다' : '주소 복사'}</button>
    </div>
  );
}
