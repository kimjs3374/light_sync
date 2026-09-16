import { useCallback, useEffect, useState } from 'react';
import { mailApi } from '../api/client';
import { formatFullDate } from '../lib/format';
import { Refresh } from './Icons';

/**
 * 수신확인 — 내가 보낸 메일을 상대가 열었는지.
 *
 * 어떻게 아는가: 보낼 때 메일 안에 **눈에 안 보이는 작은 그림**을 하나 넣어 두고,
 * 상대 메일 프로그램이 그 그림을 불러 가면 그때 읽은 것으로 본다.
 *
 * 그래서 **그림을 막아 둔 메일 프로그램에서는 읽어도 「안 읽음」으로 남는다.**
 * 이 한 줄을 화면에 적지 않으면 "분명 읽었다는데 왜 안 읽음이냐" 는 문의가 반드시 온다.
 * 아웃룩·회사 메일은 기본으로 그림을 막아 두는 곳이 많다.
 *
 * 목록은 계정이 아니라 **보낸 사람(나)** 기준이다 — 서버가 로그인한 사람이 보낸 것을
 * 모두 준다. 그래서 왼쪽에서 계정을 바꿔도 이 목록은 그대로다.
 */
export default function ReceiptsPage() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [unreadOnly, setUnreadOnly] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      const res = await mailApi.receipts();
      setRows(Array.isArray(res) ? res : []);
    } catch (e) {
      setError(e.message || '수신확인 목록을 불러오지 못했습니다.');
      setRows([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const all = rows || [];
  const unreadCount = all.filter((r) => !r.is_read).length;
  const shown = unreadOnly ? all.filter((r) => !r.is_read) : all;

  return (
    <div className="sched-wrap">
      <header className="toolbar">
        <div className="toolbar-row">
          <div className="title-area">
            <strong className="folder-title">수신확인</strong>
            <span className="count">
              {rows ? `${all.length}통 · 안읽음 ${unreadCount}통` : ''}
            </span>
          </div>
          <div className="toolbar-right">
            <button className="icon-btn" title="새로고침" onClick={load}><Refresh /></button>
          </div>
        </div>
      </header>

      <div className="sched-body rcpt-body">
        {/* 길게 적으면 안 읽는다. 꼭 알아야 할 한 가지(안 읽음이 곧 안 봤다는 뜻은
            아니다)만 굵게 남기고 나머지는 덜어냈다. */}
        <p className="rcpt-note">
          보낸 메일을 상대가 열면 「읽음」으로 표시됩니다. 최근 100통까지 보여 드립니다.
          <br />
          <b>「안 읽음」이 곧 안 봤다는 뜻은 아닙니다</b> — 아웃룩·회사 메일처럼
          그림을 막아 둔 곳에서는 읽어도 「안 읽음」으로 남습니다.
        </p>

        <div className="rcpt-filter">
          <label className="set-toggle">
            <input type="checkbox" checked={unreadOnly}
              onChange={(e) => setUnreadOnly(e.target.checked)} />
            <span>안 읽은 것만 보기</span>
          </label>
        </div>

        {rows === null && <div className="list-state">불러오는 중…</div>}
        {error && <div className="list-state error">{error}</div>}

        {rows !== null && !error && shown.length === 0 && (
          <div className="list-state">
            {unreadOnly && all.length > 0
              ? '보내신 메일을 모두 읽으셨습니다.'
              : '수신확인을 켜고 보내신 메일이 아직 없습니다.'}
          </div>
        )}

        {shown.length > 0 && (
          <table className="contact-table rcpt-table">
            <thead>
              <tr>
                <th className="col-to">받는 사람</th>
                <th>제목</th>
                <th className="col-when">보낸 시각</th>
                <th className="col-read">읽음</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id}>
                  <td title={r.to_email}>{r.to_email}</td>
                  <td title={r.subject}>{r.subject || '(제목 없음)'}</td>
                  <td className="col-when" title={formatFullDate(r.sent_at)}>
                    {formatFullDate(r.sent_at)}
                  </td>
                  {/* 강조는 ✓ 와 굵기로만 — 읽음/안읽음을 색으로 가르면 표가 시끄러워진다 */}
                  <td className="col-read" title={r.is_read ? formatFullDate(r.read_at) : '아직 열어 보지 않았습니다'}>
                    {r.is_read ? (
                      <span className="rcpt-read">
                        <b>✓ 읽음</b>
                        <em>{formatFullDate(r.read_at)}{r.read_count > 1 ? ` · ${r.read_count}번` : ''}</em>
                      </span>
                    ) : <span className="rcpt-unread">안 읽음</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
