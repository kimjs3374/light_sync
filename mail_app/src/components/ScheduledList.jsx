import { useCallback, useEffect, useState } from 'react';
import { useMail } from '../store/mail';
import { useCompose } from '../store/compose';
import { api } from '../api/client';
import { Paperclip, Refresh } from './Icons';
import TimePicker, { toServerTime } from './TimePicker';
import ScheduledDetail from './ScheduledDetail';

const DAYS = ['일', '월', '화', '수', '목', '금', '토'];
const pad = (n) => String(n).padStart(2, '0');

function whenParts(str) {
  // 서버가 'YYYY-MM-DD HH:MM' 로 준다 — 로컬 시각으로 그대로 읽는다
  const d = new Date(String(str).replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return { text: str, until: '', past: false };
  const ms = d.getTime() - Date.now();
  const min = Math.round(ms / 60000);
  let until;
  if (ms <= 0) until = '곧 발송';
  else if (min < 60) until = `${min}분 뒤`;
  else if (min < 1440) until = `${Math.round(min / 60)}시간 뒤`;
  else until = `${Math.round(min / 1440)}일 뒤`;
  return {
    text: `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}. (${DAYS[d.getDay()]}) ${pad(d.getHours())}:${pad(d.getMinutes())}`,
    until,
    past: ms <= 0,
  };
}

export default function ScheduledList() {
  const accountId = useMail((s) => s.accountId);
  const compose = useCompose();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [pickId, setPickId] = useState(null);   // 시각을 고치는 중인 행
  const [openId, setOpenId] = useState(null);   // 내용을 펼쳐 본 행

  const load = useCallback(async () => {
    if (!accountId) return;
    setError('');
    try {
      const res = await api.get(`/mail/api/schedule?account=${accountId}`);
      setRows(Array.isArray(res) ? res : []);
    } catch (e) {
      setError(e.message || '예약 목록을 불러오지 못했습니다.');
      setRows([]);
    }
  }, [accountId]);

  useEffect(() => { load(); }, [load]);

  const cancel = async (row) => {
    if (!window.confirm(`'${row.subject || '(제목 없음)'}' 예약을 취소할까요?\n이 메일은 보내지 않습니다.`)) return;
    setBusyId(row.id);
    try {
      await api.del(`/mail/api/schedule/${row.id}`);
      setRows((rs) => rs.filter((r) => r.id !== row.id));
    } catch (e) {
      window.alert(e.message || '예약을 취소하지 못했습니다.');
    } finally {
      setBusyId(null);
    }
  };

  const change = async (row, value) => {
    setPickId(null);
    const at = toServerTime(value);
    if (!at) return;
    setBusyId(row.id);
    try {
      const res = await api.json(`/mail/api/schedule/${row.id}`, {
        method: 'PATCH', body: { scheduled_at: at },
      });
      if (res.error) { window.alert(res.error); return; }
      // 시각이 바뀌면 순서도 바뀐다 — 서버 기준으로 다시 받는다
      await load();
    } catch (e) {
      window.alert(e.message || '예약을 바꾸지 못했습니다.');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="sched-wrap">
      <header className="toolbar">
        <div className="toolbar-row">
          <div className="title-area">
            <strong className="folder-title">예약 발송</strong>
            <span className="count">{rows ? `${rows.length}통` : ''}</span>
          </div>
          <div className="toolbar-right">
            <button className="icon-btn" title="새로고침" onClick={load}><Refresh /></button>
          </div>
        </div>
      </header>

      <div className="sched-body">
        {rows === null && <div className="list-state">불러오는 중…</div>}
        {error && <div className="list-state error">{error}</div>}

        {rows?.length === 0 && !error && (
          <div className="list-state">
            <p>예약해 둔 메일이 없습니다.</p>
            <button className="retry" onClick={() => compose.open('new')}>메일 쓰기</button>
          </div>
        )}

        {rows?.map((r) => {
          const w = whenParts(r.scheduled_at);
          return (
            <div
              key={r.id}
              className={`sched-row${w.past ? ' due' : ''}`}
              onClick={() => setOpenId(r.id)}
              title="내용 보기"
            >
              <div className="sched-when">
                <b>{w.text}</b>
                <em>{w.until}</em>
              </div>
              <div className="sched-main">
                <div className="sched-subject">{r.subject || '(제목 없음)'}</div>
                <div className="sched-to">
                  {r.to}
                  {r.cc && <span className="sched-cc"> · 참조 {r.cc}</span>}
                </div>
              </div>
              {r.attachment_count > 0 && (
                <span className="sched-attach" title={`첨부 ${r.attachment_count}개`}>
                  <Paperclip size={12} />{r.attachment_count}
                </span>
              )}
              <div className="sched-actions" onClick={(e) => e.stopPropagation()}>
                <div className="sched-pick-wrap">
                  <button
                    className="sched-change"
                    disabled={busyId === r.id}
                    onClick={() => setPickId((v) => (v === r.id ? null : r.id))}
                  >
                    시각 변경
                  </button>
                  <button className="sched-change" onClick={() => compose.openScheduled(r.id)}>
                    수정
                  </button>
                  {pickId === r.id && (
                    <TimePicker
                      title="예약 시각 변경"
                      confirm="이 시각으로 변경"
                      initial={new Date(String(r.scheduled_at).replace(' ', 'T'))}
                      onPick={(v) => change(r, v)}
                      onClose={() => setPickId(null)}
                    />
                  )}
                </div>
                <button
                  className="sched-cancel"
                  disabled={busyId === r.id}
                  onClick={() => cancel(r)}
                >
                  {busyId === r.id ? '처리 중…' : '예약 취소'}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {openId !== null && (
        <ScheduledDetail
          id={openId}
          onClose={() => setOpenId(null)}
          onCancel={() => {
            const row = rows?.find((r) => r.id === openId);
            if (row) cancel(row);
          }}
          onEdit={() => compose.openScheduled(openId)}
        />
      )}
    </div>
  );
}
