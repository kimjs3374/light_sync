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
import ReceiptsPage from './components/ReceiptsPage';
import ContactsPage from './components/ContactsPage';
import ContactEditModal from './components/ContactEditModal';
import SettingsModal from './components/SettingsModal';
import TourGuide from './components/TourGuide';
import StaleBanner from './components/StaleBanner';
import { useCompose } from './store/compose';
import { useContacts } from './store/contacts';
import { useSettings } from './store/settings';
import { erpUrl } from './lib/erp';
import { tourSeen } from './lib/tour';
import { startRouting } from './lib/route';

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
        // 전체화면이면 먼저 그것부터 푼다 — 한 번에 메일까지 닫히면
        // "넓게 보려다 읽던 메일을 잃는" 꼴이 된다
        case 'Escape':
          if (st.readerFull) st.toggleReaderFull();
          else if (st.openUid) st.close();
          break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

/**
 * 화면 아래 잠깐 뜨는 띠.
 * 확인창과 달리 손을 붙들지 않는다 — 한 일을 알리되 가던 길을 막지 않는다.
 */
function Notice({ text }) {
  useEffect(() => {
    if (!text) return undefined;
    const t = setTimeout(() => useCompose.getState().clearNotice(), 4000);
    return () => clearTimeout(t);
  }, [text]);
  if (!text) return null;
  return (
    <div className="notice-toast" role="status">
      <span>{text}</span>
      <button onClick={() => useCompose.getState().clearNotice()} aria-label="닫기">✕</button>
    </div>
  );
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
        // 뒤로/앞으로가기는 메일함이 올라온 뒤에 연결한다 —
        // 주소에 적힌 메일함으로 맞추려면 폴더 목록이 먼저 있어야 한다
        startRouting();
      } catch (e) {
        setFatal(e.message || '메일을 불러오지 못했습니다');
      } finally {
        setReady(true);
      }
    })();
  }, []);

  useKeyboard();

  /* 처음 온 사람에게는 화면 안내를 한 번 띄운다.
     예전 ERP 메일과 생김새가 많이 달라, 아무 말 없이 띄워 두면
     "되던 게 안 된다" 가 된다. 본 사람에게는 다시 뜨지 않는다. */
  useEffect(() => {
    if (!ready || fatal) return;
    if (!tourSeen()) useSettings.getState().startTour();
  }, [ready, fatal]);
  const composing = useCompose((st) => st.active);
  const composeDone = useCompose((st) => st.done);
  // 연락처 편집창은 화면 위에 뜬다 — 메일을 읽다가 보낸사람을 저장해도
  // 읽던 자리를 잃지 않아야 한다
  const editingContact = useContacts((st) => !!st.editing);
  // 나가면서 임시보관함에 넣었을 때처럼, 묻지 않고 한 일은 띠로 알린다
  const notice = useCompose((st) => st.notice);
  const settingsOpen = useSettings((st) => st.open);
  const tourOpen = useSettings((st) => st.tour);
  // 읽기창이 목록 자리까지 넓어지는 경우 두 가지:
  //  ① 최대화 버튼을 눌렀을 때
  //  ② 보기 방식이 '기본(전체보기)' 일 때 — 그때는 누르면 늘 전체다
  const fullRead = (s.readerFull || s.prefs.layout === 'full') && !!s.openUid;

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
        <a className="btn-compose" href={erpUrl('/mail/settings')}>ERP에서 메일 설정하기</a>
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
          ) : s.specialView === 'receipts' ? (
            /* 수신확인도 메일함이 아니다 — 목록·읽기창 대신 가운데를 통째로 쓴다 */
            <ReceiptsPage />
          ) : s.specialView === 'contacts' ? (
            <ContactsPage />
          ) : (
            <>
              {/* 최대화해도 툴바(메일함 이름·검색)는 그대로 둔다 —
                  읽기창이 화면 맨 위까지 올라오면 지금 어느 메일함을 보고 있는지가
                  화면에서 사라진다. 넓어지는 방향은 옆(목록 자리)뿐이다. */}
              <Toolbar />
              {/* 읽기창은 늘 오른쪽에 있다 — 메일을 열고 닫아도 목록 너비가
                  흔들리지 않아야 경계선을 맞춰 둔 의미가 있다. */}
              <div
                className={`content-body layout-${s.prefs.layout}`
                  + `${s.openUid ? ' has-mail' : ''}${fullRead ? ' full-read' : ''}`}
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
      {editingContact && <ContactEditModal />}
      {settingsOpen && <SettingsModal />}
      {tourOpen && <TourGuide onClose={() => useSettings.getState().endTour()} />}
      <Notice text={notice} />
    </div>
  );
}


