import { useMail } from '../store/mail';
import { folderLabel, splitFolders, showsUnread } from '../lib/folders';
import { Mail } from './Icons';
import AccountCard from './AccountCard';
import { useCompose } from '../store/compose';

export default function Sidebar() {
  const { folders, labels, folder, selectFolder, specialView, openSpecial, selfUnread } = useMail();
  const { sys, user } = splitFolders(folders);

  /**
   * 메일함 한 줄.
   *
   * 뱃지는 따로 누를 수 있는 버튼이다 — 누르면 그 메일함으로 옮기면서
   * 안읽은 메일만 걸어 바로 보여준다. 버튼 안에 버튼을 넣을 수 없으므로
   * 줄 전체를 div 로 감싸고 이름과 뱃지를 형제 버튼으로 둔다.
   */
  const Item = ({ f }) => {
    const active = f.name === folder && !specialView;
    const label = folderLabel(f.name);
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

  return (
    <nav className="sidebar">
      {/* 고정 영역 — 폴더가 길어져도 신원·필터·메일쓰기는 늘 보인다 */}
      <div className="sidebar-fixed">
        <div className="brand">
          <span className="brand-mark"><Mail /></span>
          <span className="brand-name">매그나텍 메일</span>
          <a className="erp-link" href="/" title="ERP로 돌아가기">ERP ↗</a>
        </div>
        <AccountCard />
      </div>

      {/* 스크롤 영역 — 메일함 목록 */}
      <div className="sidebar-scroll">
        <div className="folder-section">메일함</div>
        <div className="folder-group">
          {sys.map((f) => <Item key={f.name} f={f} />)}

          {/* 실제 IMAP 폴더가 아니라 우리가 만들어 주는 메일함 두 개 */}
          {[
            { key: 'selfbox', label: '내게쓴메일함', unread: selfUnread },
            { key: 'scheduled', label: '예약 발송', unread: 0 },
          ].map((v) => (
            <div key={v.key} className={`folder-row${specialView === v.key ? ' active' : ''}`}>
              <button
                className="folder-item"
                title={v.label}
                onClick={() => { if (useCompose.getState().close()) openSpecial(v.key); }}
              >
                <span className="folder-name">{v.label}</span>
              </button>
              {v.unread > 0 && (
                <button
                  className="folder-badge"
                  title={`안읽은 메일 ${v.unread}통만 보기`}
                  onClick={() => {
                    if (!useCompose.getState().close()) return;
                    openSpecial(v.key);
                    useMail.getState().setQuickFilter('unread');
                  }}
                >
                  {v.unread}
                </button>
              )}
            </div>
          ))}
        </div>

        {user.length > 0 && (
          <>
            <div className="folder-section">내 폴더</div>
            <div className="folder-group">
              {user.map((f) => <Item key={f.name} f={f} />)}
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
