import { Fragment } from 'react';
import { useMail } from '../store/mail';
import { folderLabel, splitFolders, showsUnread, arrangeUserFolders } from '../lib/folders';
import { Mail } from './Icons';
import AccountCard from './AccountCard';
import ThemeToggle from './ThemeToggle';
import { useCompose } from '../store/compose';
import { erpUrl, MAIL_ORIGIN } from '../lib/erp';

export default function Sidebar() {
  const { folders, labels, folder, selectFolder, specialView, openSpecial, selfUnread } = useMail();
  /* 메일을 쓰는 동안에는 어떤 메일함도 활성이 아니다.
     가운데는 작성 화면인데 왼쪽만 받은편지함이 켜져 있으면, 지금 무엇을 보고 있는지가
     화면 두 곳에서 다르게 읽힌다. 눌러서 옮겨 간 메일함이 그때 켜진다. */
  const composing = useCompose((st) => !!st.active);
  const { sys, user } = splitFolders(folders);
  // 순서·그룹은 설정 > 메일함 관리에서 정한다 (서버에 저장 — 자리를 옮겨도 따라온다)
  const folderPrefs = useMail((st) => st.folderPrefs);
  const { groups, plain } = arrangeUserFolders(user, folderPrefs);

  /**
   * 메일함 한 줄.
   *
   * 뱃지는 따로 누를 수 있는 버튼이다 — 누르면 그 메일함으로 옮기면서
   * 안읽은 메일만 걸어 바로 보여준다. 버튼 안에 버튼을 넣을 수 없으므로
   * 줄 전체를 div 로 감싸고 이름과 뱃지를 형제 버튼으로 둔다.
   */
  /**
   * 이름이 겹치는 메일함은 실제 이름을 덧붙인다.
   * 서버에 Archive 와 Archived 가 같이 있으면 둘 다 '보관함' 으로 보여서,
   * 화면에 똑같은 줄이 두 개 서고 어느 쪽이 무엇인지 알 수 없었다.
   * (그 둘은 2026-09-15 에 정리했지만, 같은 일이 또 생겨도 화면에서는 갈려 보여야 한다)
   */
  const labelCount = {};
  folders.forEach((f) => {
    const l = folderLabel(f.name);
    labelCount[l] = (labelCount[l] || 0) + 1;
  });

  const Item = ({ f }) => {
    const active = f.name === folder && !specialView && !composing;
    const base = folderLabel(f.name);
    const label = labelCount[base] > 1 ? `${base} (${f.name})` : base;
    const unread = showsUnread(f.name) ? (f.unread || 0) : 0;
    return (
      <div className={`folder-row${active ? ' active' : ''}`}>
        <button className="folder-item" title={label}
          onClick={() => { if (useCompose.getState().close()) selectFolder(f.name); }}>
          <span className="folder-name">{label}</span>
        </button>
        {unread > 0 && (
          <button
            className="folder-badge"
            onClick={() => { if (useCompose.getState().close()) selectFolder(f.name, { unreadOnly: true }); }}
            title={`안읽은 메일 ${unread}통만 보기`}
          >
            {unread}
          </button>
        )}
      </div>
    );
  };

  /** 실제 IMAP 폴더가 아닌 메일함 한 줄 (내게쓴메일함·예약 발송) */
  const VirtualItem = ({ item }) => (
    <div className={`folder-row${specialView === item.key && !composing ? ' active' : ''}`}>
      <button
        className="folder-item"
        title={item.label}
        onClick={() => { if (useCompose.getState().close()) openSpecial(item.key); }}
      >
        <span className="folder-name">{item.label}</span>
      </button>
      {item.unread > 0 && (
        <button
          className="folder-badge"
          title={`안읽은 메일 ${item.unread}통만 보기`}
          onClick={() => {
            if (!useCompose.getState().close()) return;
            openSpecial(item.key);
            useMail.getState().setQuickFilter('unread');
          }}
        >
          {item.unread}
        </button>
      )}
    </div>
  );

  return (
    <nav className="sidebar">
      {/* 고정 영역 — 폴더가 길어져도 신원·필터·메일쓰기는 늘 보인다 */}
      <div className="sidebar-fixed">
        <div className="brand">
          {/* 로고를 누르면 메일 첫 화면. 주소를 박아둔다 —
              옛 주소(work.mgnt.kr/webmail/)에서 열려도 새 주소로 간다 */}
          <a className="brand-home" href={MAIL_ORIGIN} title="매그나텍 메일 (mail.mgnt.kr)">
            <span className="brand-mark"><Mail /></span>
            <span className="brand-name">매그나텍 메일</span>
          </a>
          <ThemeToggle />
          <a className="erp-link" href={erpUrl('/')} title="ERP로 돌아가기" data-tour="erp">ERP ↗</a>
        </div>
        <AccountCard />
      </div>

      {/* 스크롤 영역 — 메일함 목록 */}
      <div className="sidebar-scroll">
        <div className="folder-section">메일함</div>
        <div className="folder-group" data-tour="folders">
          {/* 내게쓴메일함은 받은편지함과 **같은 INBOX** 를 보낸사람으로 가른 것이다.
              그래서 받은편지함 **바로 앞**에 붙여 둔다 — 목록 맨 끝에 있으면
              둘이 한 메일함이라는 게 화면에서 읽히지 않는다. */}
          {sys.map((f) => (
            <Fragment key={f.name}>
              {f.name.toUpperCase() === 'INBOX' && (
                <VirtualItem item={{ key: 'selfbox', label: '내게쓴메일함', unread: selfUnread }} />
              )}
              <Item f={f} />
            </Fragment>
          ))}

          {/* 예약 발송도 실제 IMAP 폴더가 아니다 — 메일함 목록 끝에 둔다 */}
          <VirtualItem item={{ key: 'scheduled', label: '예약 발송', unread: 0 }} />
        </div>

        {/* 주소록은 메일함이 아니다 — 칸을 갈라 둔다.
            들어가는 문은 하나다. 내 주소록·회사 공용·사내 직원을 가르는 일은
            들어가서 탭으로 한다 — 왼쪽에 세 줄을 늘어놓으면 메일함과 섞여 읽힌다. */}
        <div className="folder-section">주소록</div>
        <div className="folder-group" data-tour="contacts">
          <div className={`folder-row${specialView === 'contacts' && !composing ? ' active' : ''}`}>
            <button className="folder-item" title="주소록"
              onClick={() => {
                if (!useCompose.getState().close()) return;
                openSpecial('contacts');
              }}>
              <span className="folder-name">주소록</span>
            </button>
          </div>
        </div>

        {/* 묶어 둔 메일함은 묶음 이름을 달고 따로 선다 */}
        {groups.map((g) => (
          <div key={g.name}>
            <div className="folder-section">{g.name}</div>
            <div className="folder-group">
              {g.folders.map((f) => <Item key={f.name} f={f} />)}
            </div>
          </div>
        ))}

        {plain.length > 0 && (
          <>
            <div className="folder-section">내 폴더</div>
            <div className="folder-group">
              {plain.map((f) => <Item key={f.name} f={f} />)}
            </div>
          </>
        )}

        {labels.length > 0 && (
          <>
            <div className="folder-section">라벨</div>
            <div className="folder-group">
              {labels.map((l) => (
                <div key={l.id} className="folder-row">
                  <div className="folder-item label-item">
                    <span className="folder-name">
                      <span className="label-dot" style={{ background: l.color }} />
                      {l.name}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </nav>
  );
}
