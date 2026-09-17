/**
 * 파일 종류 아이콘 — 윈도우 탐색기처럼 한눈에 갈리게.
 *
 * 이모지를 쓰지 않는다(글꼴 없는 곳에서 네모로 깨진다 — Icons.jsx 와 같은 이유).
 * 색은 **종류를 가리는 데만** 아주 옅게 쓴다. 엑셀이 초록, PDF 가 빨강인 것은
 * 사람들이 20년 동안 봐 온 약속이라, 여기서 회색으로 통일하면 오히려 못 찾는다.
 */

const EXT = {
  xlsx: 'excel', xls: 'excel', xlsm: 'excel', csv: 'excel', ods: 'excel',
  docx: 'word', doc: 'word', odt: 'word', rtf: 'word',
  pptx: 'ppt', ppt: 'ppt', odp: 'ppt',
  pdf: 'pdf',
  hwp: 'hwp', hwpx: 'hwp',
  jpg: 'image', jpeg: 'image', png: 'image', gif: 'image', webp: 'image',
  bmp: 'image', tif: 'image', tiff: 'image', heic: 'image',
  zip: 'zip', '7z': 'zip', rar: 'zip', tar: 'zip', gz: 'zip', alz: 'zip',
  dwg: 'cad', dxf: 'cad', stp: 'cad', step: 'cad', igs: 'cad', iges: 'cad',
  mp4: 'video', avi: 'video', mov: 'video', mkv: 'video', wmv: 'video',
  txt: 'text', log: 'text', md: 'text', json: 'text', xml: 'text',
  eml: 'mail', msg: 'mail',
};

export const fileKind = (name, isDir) => {
  if (isDir) return 'folder';
  const ext = String(name || '').includes('.')
    ? String(name).split('.').pop().toLowerCase() : '';
  return EXT[ext] || 'file';
};

const LABEL = {
  folder: '폴더', excel: '엑셀 문서', word: '워드 문서', ppt: '파워포인트',
  pdf: 'PDF 문서', hwp: '한글 문서', image: '그림', zip: '압축 파일',
  cad: '도면 파일', video: '동영상', text: '텍스트', mail: '메일',
  file: '파일',
};

/** 탐색기의 「유형」 칸에 적을 말 */
export const fileKindLabel = (name, isDir) => {
  const kind = fileKind(name, isDir);
  if (kind === 'file') {
    const ext = String(name || '').includes('.') ? String(name).split('.').pop().toUpperCase() : '';
    return ext ? `${ext} 파일` : '파일';
  }
  return LABEL[kind];
};

const base = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' };

/* 문서 한 장 — 접힌 모서리까지. 종류별 글자는 그 위에 얹는다 */
function Doc({ tag }) {
  return (
    <>
      <path d="M13.5 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V8z" />
      <path d="M13.5 3v4a1 1 0 0 0 1 1h4" />
      {tag && (
        <text x="12" y="17" textAnchor="middle" fontSize="6.5" fontWeight="700"
          fill="currentColor" stroke="none">{tag}</text>
      )}
    </>
  );
}

const SHAPES = {
  folder: () => (
    <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.2l1.8 2h9A1.5 1.5 0 0 1 21 9.5v8A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z" />
  ),
  excel: () => <Doc tag="X" />,
  word: () => <Doc tag="W" />,
  ppt: () => <Doc tag="P" />,
  pdf: () => <Doc tag="PDF" />,
  hwp: () => <Doc tag="한" />,
  text: () => <Doc />,
  mail: () => (
    <>
      <rect x="3" y="6" width="18" height="12" rx="1.6" />
      <path d="M4 7.5l8 5.5 8-5.5" />
    </>
  ),
  image: () => (
    <>
      <rect x="3" y="5" width="18" height="14" rx="1.6" />
      <circle cx="8.5" cy="10" r="1.6" />
      <path d="M21 16l-5-5-6.5 8" />
    </>
  ),
  zip: () => (
    <>
      <path d="M13.5 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V8z" />
      <path d="M13.5 3v4a1 1 0 0 0 1 1h4M10 4v2M11.5 6v2M10 8v2M11.5 10v2M10 12v2" />
    </>
  ),
  /* 도면 — 상자 모양으로. 처음엔 접힌 종이처럼 그렸더니 **메일 아이콘과 똑같이**
     생겨서(렌더해 보고 알았다) 3D 상자로 바꿨다 */
  cad: () => (
    <>
      <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
      <path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" />
    </>
  ),
  video: () => (
    <>
      <rect x="3" y="6" width="18" height="12" rx="1.8" />
      <path d="M10.5 9.5l4.5 2.5-4.5 2.5z" />
    </>
  ),
  file: () => <Doc />,
};

export default function FileIcon({ name, isDir, size = 17 }) {
  const kind = fileKind(name, isDir);
  const Shape = SHAPES[kind] || SHAPES.file;
  return (
    <span className={`fi fi-${kind}`} aria-hidden="true">
      <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
        <Shape />
      </svg>
    </span>
  );
}
