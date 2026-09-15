import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, AlignLeft, AlignCenter, ListBullet, ListNumber, Divider } from './Icons';

/**
 * 본문 편집기.
 *
 * 라이브러리를 붙이지 않는다 — 메일 본문에 필요한 서식은 굵게·색·크기·목록·링크
 * 정도이고, 그건 브라우저의 execCommand 로 충분하다. 에디터 하나 얹자고 300KB를
 * 더 받는 건 이 화면에 과하다.
 *
 * execCommand 는 명세상 폐기 예정이지만 모든 브라우저가 여전히 지원하고,
 * 대체 표준이 아직 없다. 나중에 갈아탈 때를 위해 실행 지점을 exec() 한 곳으로 모았다.
 */

const FONT_SIZES = [
  { label: '작게', value: '2' },
  { label: '보통', value: '3' },
  { label: '조금 크게', value: '4' },
  { label: '크게', value: '5' },
  { label: '아주 크게', value: '6' },
];

/**
 * 탭 한 번의 폭.
 *
 * 처음엔 `&nbsp;` 4개를 넣었는데 실측 14.4px — 한글 한 글자(12.7px)보다 겨우 컸다.
 * `&nbsp;` 는 보통 공백 폭이라 4개를 넣어도 한 글자밖에 안 된다.
 * em space(`&emsp;`)는 글자 한 칸 폭이라 4개면 54px, 한글 4자(50.8px)와 맞는다.
 * 워드프로세서 탭 간격이 대략 4글자라 그 기준을 따랐다.
 *
 * 일반 공백을 쓰지 않는 이유: 메일 HTML 에서 연속된 공백은 받는 쪽에서
 * 한 칸으로 줄어들어 들여쓰기가 통째로 사라진다.
 */
const TAB_WIDTH = 4;
const TAB_HTML = '&emsp;'.repeat(TAB_WIDTH);
const EM_SPACE = '\u2003';
const NB_SPACE = '\u00a0';

const COLORS = [
  '#0f172a', '#dc2626', '#ea580c', '#ca8a04',
  '#16a34a', '#2563eb', '#7c3aed', '#64748b',
];

/** 툴바 아이콘 — 글자 자체가 아이콘 역할을 한다 */
const Btn = ({ cmd, title, children, onExec, active, className = '' }) => (
  <button
    type="button"
    className={`ed-btn ${className}${active ? ' on' : ''}`}
    title={title}
    aria-label={title}
    aria-pressed={!!active}
    // 눌렀을 때 본문 선택이 풀리면 서식이 엉뚱한 곳에 먹는다
    onMouseDown={(e) => e.preventDefault()}
    onClick={() => onExec(cmd)}
  >
    {children}
  </button>
);

export default function Editor({ initialHtml, onChange, editorRef }) {
  const innerRef = useRef(null);
  const ref = editorRef || innerRef;
  const [state, setState] = useState({});
  const [palette, setPalette] = useState(false);

  // 처음 한 번만 넣는다 — 매 입력마다 React 가 다시 그리면 커서가 맨 앞으로 튄다
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = initialHtml || '';
    el.focus();
    const sel = window.getSelection();
    const r = document.createRange();
    r.setStart(el, 0);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sync = useCallback(() => onChange(ref.current?.innerHTML || ''), [onChange, ref]);

  /** 서식 적용 — 여기 한 곳만 거친다 */
  const exec = useCallback((cmd, value = null) => {
    ref.current?.focus();
    try {
      document.execCommand(cmd, false, value);
    } catch { /* 지원하지 않는 명령은 조용히 넘어간다 */ }
    sync();
    refreshState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sync]);

  const refreshState = useCallback(() => {
    const el = ref.current;
    if (!el || !el.contains(document.getSelection()?.anchorNode)) return;
    const q = (c) => { try { return document.queryCommandState(c); } catch { return false; } };
    setState({
      bold: q('bold'), italic: q('italic'), underline: q('underline'),
      strike: q('strikeThrough'),
      ul: q('insertUnorderedList'), ol: q('insertOrderedList'),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    document.addEventListener('selectionchange', refreshState);
    return () => document.removeEventListener('selectionchange', refreshState);
  }, [refreshState]);

  /**
   * Tab 키.
   *
   * 기본 동작은 포커스를 다음 요소로 넘기는 것이라, 본문을 쓰다가 Tab 을 누르면
   * 편집기 밖으로 튕겨 나간다. 메일 본문에서 Tab 은 들여쓰기로 쓰는 게 맞다.
   *
   *  - 목록 안       : Tab 들여쓰기 / Shift+Tab 내어쓰기 (단계가 바뀐다)
   *  - 그 밖의 곳    : Tab 한 칸(글자 4개 폭) / Shift+Tab 그만큼 되돌리기
   *
   * 다만 Tab 을 완전히 가로채면 키보드만 쓰는 사람이 편집기에 갇힌다.
   * 빠져나가는 길은 Esc 다 (App 의 전역 키 처리에서 blur 시킨다).
   */
  const onKeyDown = (e) => {
    if (e.key !== 'Tab') return;
    e.preventDefault();

    const inList = (() => {
      try {
        return document.queryCommandState('insertUnorderedList')
          || document.queryCommandState('insertOrderedList');
      } catch { return false; }
    })();

    if (e.shiftKey) {
      if (inList) { exec('outdent'); return; }
      // 목록이 아니면 앞서 넣은 공백을 하나씩 거둔다
      const sel = window.getSelection();
      if (sel && sel.isCollapsed && sel.anchorNode?.nodeType === 3) {
        const text = sel.anchorNode.nodeValue || '';
        const at = sel.anchorOffset;
        const before = text.slice(0, at);
        const m = before.match(
          new RegExp(`(?:${EM_SPACE}|${NB_SPACE}| ){1,${TAB_WIDTH}}$`),
        );
        if (m) {
          const range = document.createRange();
          range.setStart(sel.anchorNode, at - m[0].length);
          range.setEnd(sel.anchorNode, at);
          sel.removeAllRanges();
          sel.addRange(range);
          exec('delete');
          return;
        }
      }
      exec('outdent');
      return;
    }

    if (inList) { exec('indent'); return; }
    exec('insertHTML', TAB_HTML);
  };

  const addLink = () => {
    const url = window.prompt('연결할 주소를 입력하세요', 'https://');
    if (url && url !== 'https://') exec('createLink', url);
  };

  return (
    <div className="editor">
      <div className="editor-toolbar" role="toolbar" aria-label="본문 서식">
        <select
          className="ed-select"
          defaultValue="3"
          title="글자 크기"
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => exec('fontSize', e.target.value)}
        >
          {FONT_SIZES.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>

        <span className="ed-sep" />

        <Btn cmd="bold" title="굵게" onExec={exec} active={state.bold} className="ed-bold">가</Btn>
        <Btn cmd="italic" title="기울임" onExec={exec} active={state.italic} className="ed-italic">가</Btn>
        <Btn cmd="underline" title="밑줄" onExec={exec} active={state.underline} className="ed-underline">가</Btn>
        <Btn cmd="strikeThrough" title="취소선" onExec={exec} active={state.strike} className="ed-strike">가</Btn>

        <div className="ed-color-wrap">
          <button type="button" className="ed-btn" title="글자색"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setPalette((v) => !v)}>
            <span className="ed-color-mark">가</span>
          </button>
          {palette && (
            <div className="ed-palette" onMouseLeave={() => setPalette(false)}>
              {COLORS.map((col) => (
                <button key={col} type="button" className="ed-swatch" style={{ background: col }}
                  title={col}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => { exec('foreColor', col); setPalette(false); }} />
              ))}
            </div>
          )}
        </div>

        <span className="ed-sep" />

        <Btn cmd="insertUnorderedList" title="글머리 기호" onExec={exec} active={state.ul}><ListBullet /></Btn>
        <Btn cmd="insertOrderedList" title="번호 매기기" onExec={exec} active={state.ol}><ListNumber /></Btn>

        <span className="ed-sep" />

        <Btn cmd="justifyLeft" title="왼쪽 정렬" onExec={exec}><AlignLeft /></Btn>
        <Btn cmd="justifyCenter" title="가운데 정렬" onExec={exec}><AlignCenter /></Btn>

        <span className="ed-sep" />

        <button type="button" className="ed-btn" title="링크 넣기"
          onMouseDown={(e) => e.preventDefault()} onClick={addLink}><Link /></button>
        <Btn cmd="insertHorizontalRule" title="구분선" onExec={exec}><Divider /></Btn>
        <Btn cmd="removeFormat" title="서식 지우기" onExec={exec}>✕가</Btn>
      </div>

      <div
        ref={ref}
        className="compose-body"
        contentEditable
        suppressContentEditableWarning
        onInput={sync}
        onBlur={sync}
        onKeyDown={onKeyDown}
        onKeyUp={refreshState}
        onMouseUp={refreshState}
      />
    </div>
  );
}
