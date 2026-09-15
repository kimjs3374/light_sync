/**
 * 폴더 아이콘·한글명·정렬 — 기존 ERP 메일 화면(static/js/mail.js)과 같은 규칙.
 * 두 화면이 나란히 쓰이므로 사용자가 보는 이름이 갈리면 안 된다.
 */

export const folderIcon = (name) => {
  const n = name.toLowerCase();
  if (n === 'inbox') return '📥';
  if (n.includes('sent')) return '📤';
  if (n.includes('draft')) return '📝';
  if (n.includes('trash') || n.includes('delete')) return '🗑️';
  if (n.includes('junk') || n.includes('spam')) return '⚠️';
  if (n.includes('archive')) return '🗄️';
  return '📁';
};

export const folderLabel = (name) => {
  const n = name.toLowerCase();
  if (n === 'inbox') return '받은편지함';
  if (n.includes('sent')) return '보낸편지함';
  if (n.includes('draft')) return '임시보관함';
  if (n.includes('trash') || n.includes('delete')) return '휴지통';
  if (n.includes('junk') || n.includes('spam')) return '스팸';
  if (n.includes('archive')) return '보관함';
  return name.split('.').pop().split('/').pop();
};

const SYS_EXACT = ['inbox', 'sent', 'drafts', 'draft', 'trash', 'junk', 'spam', 'archive', 'archived'];
const SYS_ORDER = ['inbox', 'sent', 'draft', 'archive', 'junk', 'spam', 'trash'];

const baseName = (n) => n.split('.').pop().split('/').pop();

/** 시스템 폴더와 사용자 폴더를 갈라 정렬해 돌려준다. */
export function splitFolders(folders) {
  const sys = [];
  const user = [];
  for (const f of folders) {
    const n = f.name.toLowerCase();
    if (SYS_EXACT.includes(n) || SYS_EXACT.includes(baseName(n))) sys.push(f);
    else user.push(f);
  }
  sys.sort((a, b) => {
    const ai = SYS_ORDER.findIndex((s) => baseName(a.name.toLowerCase()).startsWith(s));
    const bi = SYS_ORDER.findIndex((s) => baseName(b.name.toLowerCase()).startsWith(s));
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });
  return { sys, user };
}

/** 보낸편지함·임시보관함은 안읽음 뱃지를 달지 않는다 (기존 화면과 동일) */
export const showsUnread = (name) => {
  const n = name.toLowerCase();
  return !n.includes('sent') && !n.includes('draft');
};

/** 휴지통 폴더 실제 이름 찾기 — 서버마다 Trash / INBOX.Trash 로 다르다 */
export const findTrash = (folders) =>
  folders.find((f) => {
    const n = f.name.toLowerCase();
    return n.includes('trash') || n.includes('delete');
  })?.name || null;

export const findJunk = (folders) =>
  folders.find((f) => {
    const n = f.name.toLowerCase();
    return n.includes('junk') || n.includes('spam');
  })?.name || null;
