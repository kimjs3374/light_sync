import { useEffect } from 'react';
import { useContacts, BOOK_LABEL } from '../store/contacts';
import { Close } from './Icons';

/**
 * 연락처 추가·수정 창.
 *
 * 주소록 화면이 아니라 App 이 그린다 — 메일을 읽다가 "주소록 저장" 을 눌러도
 * 보던 메일 위에서 열려야 하고, 저장하고 나면 읽던 자리로 그대로 돌아와야 한다.
 *
 * 저장할 곳(내 주소록 / 회사 공용)은 **늘 눈에 보이게 고른다.** 회사 공용은
 * 전 직원이 함께 보는 자리라, 모르고 넣었다는 일이 없어야 한다.
 */
export default function ContactEditModal() {
  const c = useContacts();
  const form = c.editing;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') useContacts.getState().cancelEdit(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  if (!form) return null;

  const field = (key, label, opts = {}) => (
    <label className="cform-row">
      <span className="cform-label">{label}</span>
      {opts.area ? (
        <textarea
          className="cform-input" rows={2} value={form[key]}
          onChange={(e) => c.patchEdit({ [key]: e.target.value })}
        />
      ) : (
        <input
          className="cform-input" value={form[key]} type={opts.type || 'text'}
          placeholder={opts.placeholder || ''} autoFocus={!!opts.autoFocus}
          onChange={(e) => c.patchEdit({ [key]: e.target.value })}
        />
      )}
    </label>
  );

  return (
    <div className="modal-backdrop" onClick={() => c.cancelEdit()}>
      <div className="contact-card" onClick={(e) => e.stopPropagation()} role="dialog"
        aria-label={form.id ? '연락처 수정' : '연락처 추가'}>
        <div className="contact-card-head">
          <h3>{form.id ? '연락처 수정' : '연락처 추가'}</h3>
          <button className="icon-btn" title="닫기" onClick={() => c.cancelEdit()}><Close /></button>
        </div>

        {/* 폼 안에 폼을 넣지 않는다 — 엔터로 저장되게만 해 두면 충분하다 */}
        <div className="contact-form"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') { e.preventDefault(); c.save(); }
          }}
        >
          {field('name', '이름', { autoFocus: !form.name })}
          {field('email', '메일주소', { type: 'email', autoFocus: !!form.name && !form.email })}
          {field('company', '회사')}
          {field('phone', '전화')}
          {field('memo', '메모', { area: true })}

          <div className="cform-row">
            <span className="cform-label">저장할 곳</span>
            <div className="book-choice">
              {['personal', 'shared'].map((b) => (
                <button
                  key={b}
                  type="button"
                  className={`book-pick${form.book === b ? ' on' : ''}`}
                  onClick={() => c.patchEdit({ book: b })}
                >
                  {BOOK_LABEL[b]}
                  <em>{b === 'personal' ? '나만 봅니다' : '전 직원이 함께 씁니다'}</em>
                </button>
              ))}
            </div>
          </div>
        </div>

        {form.error && <div className="contact-error">{form.error}</div>}

        <div className="contact-card-foot">
          <button className="btn-send" disabled={c.saving} onClick={() => c.save()}>
            {c.saving ? '저장 중…' : '저장'}
          </button>
          <button className="btn-cancel" onClick={() => c.cancelEdit()}>취소</button>
        </div>
      </div>
    </div>
  );
}
