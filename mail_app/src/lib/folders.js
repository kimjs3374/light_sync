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

/* 기본 메일함 — 이름을 바꾸거나 지울 수 없는 것들.
   한글 이름도 함께 본다: 서버에 따라 '임시보관함' 같은 한글 폴더가 실제로 있고,
   우리가 만들어 내는 '내게쓴메일함' 과 이름이 겹치는 폴더도 손대면 안 된다. */
const SYS_EXACT = [
  'inbox', 'sent', 'drafts', 'draft', 'trash', 'junk', 'spam', 'archive', 'archived',
  '받은편지함', '보낸편지함', '임시보관함', '휴지통', '스팸', '보관함', '내게쓴메일함', '내게쓴편지함',
];
const SYS_ORDER = ['inbox', 'sent', 'draft', 'archive', 'junk', 'spam', 'trash'];

/* 띄어쓰기는 지우고 본다 — 실제로 '임시 보관함'(공백 포함) 폴더가 있었다.
   공백 하나로 기본 메일함 판정이 새면 그 폴더만 고칠 수 있게 남는다. */
const norm = (n) => String(n || '').toLowerCase().replace(/\s+/g, '');
const baseName = (n) => norm(n).split('.').pop().split('/').pop();

/** 시스템 폴더와 사용자 폴더를 갈라 정렬해 돌려준다. */
export function splitFolders(folders) {
  const sys = [];
  const user = [];
  for (const f of folders) {
    const n = norm(f.name);
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

/** 보낸편지함인가 — '다시 보내기' 처럼 내가 보낸 메일에서만 뜻이 있는 기능의 잣대 */
export const isSentFolder = (name) => String(name || '').toLowerCase().includes('sent');

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

/**
 * 사람이 정한 순서·그룹으로 내 폴더를 정리한다.
 *
 * IMAP LIST 는 서버 마음대로 준 순서라, 정해 둔 것이 없으면 이름순으로 둔다.
 * 순서를 아직 정하지 않은 폴더(새로 만든 것)는 **뒤로** 보낸다 — 앞에 끼어들면
 * 정리해 둔 차례가 흐트러진다.
 */
export function arrangeUserFolders(user, prefs = []) {
  const map = new Map(prefs.map((p) => [p.folder, p]));
  const sorted = [...user].sort((a, b) => {
    const ao = map.has(a.name) ? map.get(a.name).sort_order : 9999;
    const bo = map.has(b.name) ? map.get(b.name).sort_order : 9999;
    return ao - bo || a.name.localeCompare(b.name, 'ko');
  });

  const groups = [];
  const plain = [];
  for (const f of sorted) {
    const g = (map.get(f.name)?.group_name || '').trim();
    if (!g) { plain.push(f); continue; }
    let grp = groups.find((x) => x.name === g);
    if (!grp) { grp = { name: g, folders: [] }; groups.push(grp); }
    grp.folders.push(f);
  }
  return { groups, plain, ordered: sorted };
}
