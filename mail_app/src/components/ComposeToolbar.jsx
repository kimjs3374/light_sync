import { useEffect, useState } from 'react';
import { useCompose } from '../store/compose';
import { api } from '../api/client';
import TimePicker, { Popover } from './TimePicker';

const pad = (n) => String(n).padStart(2, '0');

function ScheduleMenu({ onClose }) {
  const c = useCompose();
  const w = c.active;
  const attachCount = (w?.files.length || 0) + (w?.forward?.parts.length || 0);

  // 예약이 되면 스토어가 완료 화면으로 넘긴다 — 여기서 알림창을 띄우지 않는다
  const go = async (value) => {
    await c.schedule(value);
    onClose();
  };

  return (
    <TimePicker
      title="예약 발송"
      note={attachCount > 0 ? `첨부 ${attachCount}건도 함께 예약됩니다.` : ''}
      confirm="이 시각에 예약"
      onPick={go}
      onClose={onClose}
    />
  );
}

function TemplateMenu({ onClose }) {
  const c = useCompose();
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.get('/mail/api/templates')
      .then((r) => setItems(Array.isArray(r) ? r : []))
      .catch(() => setItems([]));
  }, []);

  const saveCurrent = async () => {
    const name = window.prompt('템플릿 이름을 입력하세요');
    if (!name) return;
    const ok = await c.saveAsTemplate(name.trim());
    window.alert(ok ? '템플릿으로 저장했습니다.' : '템플릿 저장에 실패했습니다.');
    onClose();
  };

  return (
    <Popover onClose={onClose} className="pop-template">
      <div className="pop-title">템플릿</div>
      {items === null && <div className="pop-empty">불러오는 중…</div>}
      {items?.length === 0 && <div className="pop-empty">저장된 템플릿이 없습니다</div>}
      {items?.map((t) => (
        <button key={t.id} className="pop-item"
          onClick={() => { c.applyTemplate(t); onClose(); }}>
          <span>{t.name}</span>
          {t.is_shared && <em>공용</em>}
        </button>
      ))}
      <div className="pop-sep" />
      <button className="pop-item pop-add" onClick={saveCurrent}>+ 지금 내용을 템플릿으로</button>
    </Popover>
  );
}

const DAYS = ['일', '월', '화', '수', '목', '금', '토'];
const whenLabel = (d) => (d instanceof Date && !Number.isNaN(d.getTime())
  ? `${d.getMonth() + 1}/${d.getDate()}(${DAYS[d.getDay()]}) ${pad(d.getHours())}:${pad(d.getMinutes())}`
  : '');

export default function ComposeToolbar({ account }) {
  const c = useCompose();
  const w = c.active;
  const editing = w.mode === 'editScheduled';
  const [menu, setMenu] = useState('');   // '' | 'schedule' | 'template'
  const toggle = (name) => setMenu((m) => (m === name ? '' : name));

  // 버튼이 켜져 보이는 근거는 받는사람 목록 그 자체다 (별도 플래그 없음)
  const me = (account?.email || '').toLowerCase();
  const selfOn = !!me && w.to.some((t) => t.toLowerCase() === me);

  return (
    <div className="compose-head-actions">
      {editing ? (
        <>
          <button className="btn-send" disabled={w.sending} onClick={() => c.saveScheduled()}>
            {w.sending ? '저장 중…' : '예약 저장'}
          </button>
          <div className="act-wrap">
            <button className={`act${menu === 'schedule' ? ' on' : ''}`} onClick={() => toggle('schedule')}>
              시각 변경 · {whenLabel(w.scheduledAt)}
            </button>
            {menu === 'schedule' && (
              <TimePicker
                title="예약 시각 변경"
                confirm="이 시각으로"
                initial={w.scheduledAt}
                onPick={(v) => { c.update({ scheduledAt: new Date(v) }); setMenu(''); }}
                onClose={() => setMenu('')}
              />
            )}
          </div>
        </>
      ) : (
        <>
          <button className="btn-send" disabled={w.sending} onClick={() => c.send()}>
            {w.sending ? '보내는 중…' : '보내기'}
          </button>

          <div className="act-wrap">
            <button className={`act${menu === 'schedule' ? ' on' : ''}`} onClick={() => toggle('schedule')}>
              예약
            </button>
            {menu === 'schedule' && <ScheduleMenu onClose={() => setMenu('')} />}
          </div>

          <button className="act" disabled={w.saving} onClick={() => c.saveDraft()}>
            {w.saving ? '저장 중…' : '임시저장'}
          </button>
        </>
      )}

      <button className="act" onClick={() => c.update({ previewing: true })}>미리보기</button>

      <div className="act-wrap">
        <button className={`act${menu === 'template' ? ' on' : ''}`} onClick={() => toggle('template')}>
          템플릿
        </button>
        {menu === 'template' && <TemplateMenu onClose={() => setMenu('')} />}
      </div>

      <button
        className={`act${selfOn ? ' on' : ''}`}
        onClick={() => c.toggleSelf()}
        aria-pressed={selfOn}
        title={selfOn ? `받는사람에서 ${account?.email} 빼기` : `받는사람에 ${account?.email} 넣기`}
      >
        내게쓰기
      </button>

    </div>
  );
}
