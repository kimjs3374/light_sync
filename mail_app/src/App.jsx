import { useEffect, useRef, useState } from 'react';
import { useMail, visibleMessages } from './store/mail';
import Sidebar from './components/Sidebar';
import Toolbar from './components/Toolbar';
import MessageList from './components/MessageList';
import ReadPane from './components/ReadPane';
import Splitter from './components/Splitter';
import ComposePage from './components/ComposePage';
import ComposeDone from './components/ComposeDone';
import ScheduledList from './components/ScheduledList';
import StaleBanner from './components/StaleBanner';
import { useCompose } from './store/compose';

/**
 * 키보드 이동 — 목록에 커서를 두고 ↑↓/jk 로 옮긴다.
 * 스토어를 직접 읽어 쓰므로 리스너를 한 번만 걸면 된다
 * (스토어 객체를 의존성에 넣으면 상태가 바뀔 때마다 리스너가 다시 붙는다).
 */
function useKeyboard() {
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) {
        if (e.key === 'Escape') e.target.blur();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const st = useMail.getState();
      const list = visibleMessages(st);
      const current = list[st.cursor];

      switch (e.key) {
        case 'ArrowDown': case 'j': e.preventDefault(); st.moveCursor(1); break;
        case 'ArrowUp': case 'k': e.preventDefault(); st.moveCursor(-1); break;
        case 'Enter': if (current) { e.preventDefault(); st.open(current.uid); } break;
        case 'x': if (current) { e.preventDefault(); st.toggleCheck(current.uid); } break;
        case '/': e.preventDefault(); document.querySelector('.search input')?.focus(); break;
        case 'c': e.preventDefault(); useCompose.getState().open('new'); break;
        case 'r': if (st.openUid) { e.preventDefault(); useCompose.getState().open('reply'); } break;
        case 'f': if (st.openUid) { e.preventDefault(); useCompose.getState().open('forward'); } break;
        case 'Escape': if (st.openUid) st.close(); break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

export default function App() {
  const s = useMail();
  const [ready, setReady] = useState(false);
  const [fatal, setFatal] = useState('');
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;   // StrictMode 이중 실행 방지
    started.current = true;
    (async () => {
      try {
        await useMail.getState().init();
      } catch (e) {
        setFatal(e.message || '메일을 불러오지 못했습니다');
      } finally {
        setReady(true);
      }
    })();
  }, []);

  useKeyboard();
  const composing = useCompose((st) => st.active);
  const composeDone = useCompose((st) => st.done);

  // 새 메일이 오면 뱃지가 따라오도록 주기적으로 안읽음만 확인한다 (IMAP 왕복 1회)
  useEffect(() => {
    const id = setInterval(() => useMail.getState().refreshInboxUnread(), 60000);
    const onFocus = () => useMail.getState().refreshInboxUnread();
    window.addEventListener('focus', onFocus);
    return () => { clearInterval(id); window.removeEventListener('focus', onFocus); };
  }, []);

  if (!ready) return <div className="boot">메일함을 여는 중…</div>;
  if (fatal) return <div className="boot error">{fatal}</div>;

  if (s.listError === 'no-account' || (!s.accounts.length)) {
    return (
      <div className="boot">
        <p>메일 계정이 설정되지 않았습니다.</p>
        <a className="btn-compose" href="/mail/settings">ERP에서 메일 설정하기</a>
      </div>
    );
  }

  return (
    <div className="app">
      <StaleBanner />
      <div className="main">
        <Sidebar />
        <section className="content">
          {composing ? (
            /* 메일 쓰기는 페이지다 — 폴더는 그대로 두고 가운데를 통째로 쓴다 */
            <ComposePage win={composing} />
          ) : composeDone ? (
            <ComposeDone done={composeDone} />
          ) : s.specialView === 'scheduled' ? (
            <ScheduledList />
          ) : (
            <>
              <Toolbar />
              {/* 읽기창은 늘 오른쪽에 있다 — 메일을 열고 닫아도 목록 너비가
                  흔들리지 않아야 경계선을 맞춰 둔 의미가 있다. */}
              <div
                className={`content-body${s.openUid ? ' has-mail' : ''}`}
                style={{ '--split': `${s.prefs.splitPct}%` }}
              >
                <MessageList />
                <Splitter />
                <ReadPane />
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}


