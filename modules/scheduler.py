"""백그라운드 스케줄러 — 출장 상태 자동 업데이트, G2B 일일 동기화 등"""
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
_scheduler = None


def _sync_g2b_daily():
    """G2B 조달내역 일일 동기화 + 자동 계약 생성 (매일 06:00)"""
    from modules.db_context import get_db
    from modules.services.g2b_procurement_sync import sync_daily, auto_create_contracts

    try:
        with get_db() as db:
            result = sync_daily(db)
            db.commit()
            auto_result = auto_create_contracts(db)
            db.commit()
        logger.info(
            f"[scheduler] G2B 일일동기화 완료 — 신규 {result['created']}건, "
            f"갱신 {result['updated']}건 / 자동계약 {auto_result.get('created', 0)}건"
        )
    except Exception as e:
        logger.error(f"[scheduler] G2B 일일동기화 오류: {e}")


# 출장 상태 자동 전환은 crontab(flask update-trip-status)으로 이관됨.
#   기존 in-process 버전은 gunicorn 멀티워커에서 미동작 이력 + '출장중' 값을
#   완료 전환에서 누락하는 버그가 있었다. 로직은 services/business_trip_status.py 단일화.


def _cleanup_expired_mail_files():
    """만료된 대용량 메일 첨부파일 삭제 (매일 03:00)"""
    from modules.db_context import get_db
    from modules.models.mail_entities import MailLargeFile
    from modules import storage_adapter
    import datetime as _dt

    try:
        now = _dt.datetime.now()
        deleted = 0
        with get_db() as db:
            expired = db.query(MailLargeFile).filter(
                MailLargeFile.expires_at < now,
                MailLargeFile.is_deleted == False,
            ).all()
            import os as _os
            for record in expired:
                storage_adapter.delete_object(record.storage_path)
                # 로컬 캐시도 삭제
                ext = _os.path.splitext(record.storage_path)[1] or ''
                cache_file = f'/tmp/mail_dl_cache/{record.file_id}{ext}'
                if _os.path.exists(cache_file):
                    _os.remove(cache_file)
                record.is_deleted = True
                deleted += 1
            db.commit()
        if deleted:
            logger.info(f"[scheduler] 만료 메일 첨부파일 {deleted}건 삭제")
    except Exception as e:
        logger.error(f"[scheduler] 메일 파일 정리 오류: {e}")


def _process_auto_reply_forward(app):
    """자동회신 + 자동전달 처리 — 5분마다 새 메일 체크."""
    import datetime
    try:
        with app.app_context():
            from modules.db_context import get_db
            from modules.models.mail_entities import MailAccount, MailAutoReply, MailAutoForward
            from modules.services.mail_client import MailClient, decrypt_password
            with get_db() as db:
                # 자동회신 활성 계정
                auto_replies = db.query(MailAutoReply).filter_by(is_active=True).all()
                # 자동전달 활성 계정
                auto_forwards = db.query(MailAutoForward).filter_by(is_active=True).all()

                # 처리할 계정 ID 수집
                account_ids = set()
                ar_map = {}  # account_id -> MailAutoReply
                af_map = {}  # account_id -> [MailAutoForward]
                today = datetime.date.today()

                for ar in auto_replies:
                    if ar.start_date and today < ar.start_date.date():
                        continue
                    if ar.end_date and today > ar.end_date.date():
                        continue
                    account_ids.add(ar.account_id)
                    ar_map[ar.account_id] = ar

                for af in auto_forwards:
                    account_ids.add(af.account_id)
                    af_map.setdefault(af.account_id, []).append(af)

                if not account_ids:
                    return

                for aid in account_ids:
                    account = db.query(MailAccount).filter_by(id=aid).first()
                    if not account:
                        continue
                    try:
                        pw = decrypt_password(account.password_encrypted)
                        client = MailClient(
                            account.imap_host, account.imap_port,
                            account.smtp_host, account.smtp_port,
                            account.username, pw, account.use_ssl,
                        )
                        with client:
                            # 최근 5분 내 새 메일 (UNSEEN)
                            client._imap.select_folder('INBOX', readonly=False)
                            unseen = client._imap.search('UNSEEN')
                            if not unseen:
                                continue

                            # 최근 10건만 처리 (과부하 방지)
                            for uid in unseen[:10]:
                                raw = client._imap.fetch([uid], ['ENVELOPE'])
                                if uid not in raw:
                                    continue
                                env = raw[uid].get(b'ENVELOPE')
                                if not env:
                                    continue
                                from_addr = ''
                                if env.from_ and env.from_[0]:
                                    f = env.from_[0]
                                    mbox = f.mailbox.decode() if f.mailbox else ''
                                    host = f.host.decode() if f.host else ''
                                    from_addr = f"{mbox}@{host}" if mbox and host else ''

                                if not from_addr:
                                    continue

                                # 자동회신
                                ar = ar_map.get(aid)
                                if ar and from_addr:
                                    replied = set((ar.replied_addresses or '').split(','))
                                    if not ar.reply_once or from_addr not in replied:
                                        try:
                                            client.send_message(
                                                from_addr=account.email,
                                                from_name=account.display_name or '',
                                                to=from_addr,
                                                subject=ar.subject or '부재중 자동회신',
                                                html_body=ar.body or '',
                                            )
                                            replied.add(from_addr)
                                            ar.replied_addresses = ','.join(replied)
                                            logger.info(f"[scheduler] 자동회신: {account.email} → {from_addr}")
                                        except Exception as e:
                                            logger.error(f"[scheduler] 자동회신 실패: {e}")

                                # 자동전달
                                for af in af_map.get(aid, []):
                                    try:
                                        # 원본 가져와서 전달
                                        full = client._imap.fetch([uid], ['RFC822'])
                                        if uid in full:
                                            import email as _email
                                            from email.mime.text import MIMEText
                                            orig = _email.message_from_bytes(full[uid][b'RFC822'])
                                            subj = orig.get('Subject', '')
                                            body_text = ''
                                            for part in orig.walk():
                                                ct = part.get_content_type()
                                                if ct == 'text/html':
                                                    body_text = part.get_payload(decode=True).decode(errors='replace')
                                                    break
                                                elif ct == 'text/plain' and not body_text:
                                                    body_text = part.get_payload(decode=True).decode(errors='replace')

                                            client.send_message(
                                                from_addr=account.email,
                                                from_name=f"[전달] {account.display_name or account.email}",
                                                to=af.forward_to,
                                                subject=f"Fwd: {subj}",
                                                html_body=body_text,
                                            )
                                            logger.info(f"[scheduler] 자동전달: {account.email} → {af.forward_to}")

                                            if not af.keep_copy:
                                                client.move_messages([uid], 'Trash', src_folder='INBOX')
                                    except Exception as e:
                                        logger.error(f"[scheduler] 자동전달 실패: {e}")

                    except Exception as e:
                        logger.error(f"[scheduler] 자동회신/전달 오류 (account={aid}): {e}")

                db.commit()
    except Exception as e:
        logger.error(f"[scheduler] 자동회신/전달 처리 오류: {e}")


def _load_scheduled_attachments(sched):
    """예약 메일의 첨부를 Storage 에서 읽어 [(filename, bytes), ...] 로 돌려준다.

    한 건이라도 못 읽으면 발송을 멈춘다 — 첨부가 빠진 채 나가는 것이
    안 나가는 것보다 나쁘다. (받는 쪽은 첨부가 원래 없었다고 생각한다)
    """
    import json as _json
    from modules import storage_adapter

    meta = []
    try:
        meta = _json.loads(sched.attachments_json or '[]')
    except Exception:
        logger.error("[scheduler] 첨부 정보 해석 실패: id=%s", sched.id)
        raise

    out = []
    for a in meta:
        path = a.get('path')
        data = storage_adapter.download_bytes(path) if path else None
        if not data:
            raise RuntimeError(f"첨부를 읽지 못했습니다: {a.get('filename')} ({path})")
        out.append((a.get('filename') or 'attachment', data))
    return out


def _cleanup_scheduled_attachments(sched):
    """발송이 끝난 예약의 첨부 보관본 삭제."""
    import json as _json
    from modules import storage_adapter
    try:
        for a in _json.loads(sched.attachments_json or '[]'):
            if a.get('path'):
                storage_adapter.delete_object(a['path'])
    except Exception as e:
        logger.warning("[scheduler] 예약 첨부 정리 실패: id=%s %s", sched.id, e)


def process_scheduled_mails_once(app):
    """예약발송 1회 처리. (성공건수, 실패건수) 를 돌려준다.

    crontab 에서 1분마다 부른다 — in-process 스케줄러는 쓰지 않는다.
    워커가 8개라 각자 돌면 같은 메일이 8번 나간다.
    """
    return _process_scheduled_mails(app)


def _process_scheduled_mails(app):
    """예약발송 처리 본체."""
    sent = failed = 0
    from datetime import datetime
    try:
        with app.app_context():
            from modules.db_context import get_db
            from modules.models.mail_entities import MailScheduled, MailAccount
            from modules.services.mail_client import MailClient, decrypt_password
            with get_db() as db:
                pending = db.query(MailScheduled).filter(
                    MailScheduled.status == 'pending',
                    MailScheduled.scheduled_at <= datetime.now(),
                ).all()
                for sched in pending:
                    try:
                        account = db.query(MailAccount).filter_by(id=sched.account_id).first()
                        if not account:
                            sched.status = 'failed'
                            failed += 1
                            continue
                        pw = decrypt_password(account.password_encrypted)
                        client = MailClient(
                            account.imap_host, account.imap_port,
                            account.smtp_host, account.smtp_port,
                            account.username, pw, account.use_ssl,
                        )
                        # 예약 시점에 Storage 로 옮겨둔 첨부를 도로 꺼내 붙인다.
                        # (예약은 몇 시간 뒤에 실행되므로 파일을 DB 본문에 들고 있을 수 없다)
                        attachments = _load_scheduled_attachments(sched)

                        with client:
                            client.send_message(
                                from_addr=account.email,
                                from_name=account.display_name or '',
                                to=sched.to_addresses,
                                cc=sched.cc_addresses or None,
                                bcc=sched.bcc_addresses or None,
                                subject=sched.subject or '',
                                html_body=sched.body or '',
                                attachments=attachments or None,
                            )
                        sched.status = 'sent'
                        sched.sent_at = datetime.now()
                        sent += 1
                        # 보냈으면 보관본은 지운다. 실패한 건은 남겨 둬야
                        # 사람이 무엇이 안 나갔는지 확인할 수 있다.
                        _cleanup_scheduled_attachments(sched)
                        logger.info(
                            "[scheduler] 예약발송 완료: id=%s to=%s 첨부=%d건",
                            sched.id, sched.to_addresses, len(attachments),
                        )
                    except Exception as e:
                        sched.status = 'failed'
                        failed += 1
                        logger.error(f"[scheduler] 예약발송 실패: id={sched.id} {e}")
                db.commit()
    except Exception as e:
        logger.error(f"[scheduler] 예약발송 처리 오류: {e}")
    return sent, failed


def init_scheduler(app):
    """앱 컨텍스트 안에서 스케줄러 시작"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    # 출장 상태 보정은 crontab(flask update-trip-status)으로 이관.
    #   APScheduler in-process 방식은 gunicorn 멀티워커에서 신뢰불가(실제로 미동작 이력).
    #   표시 로직은 이미 날짜기준 유효상태를 계산하므로 이 job 없이도 정상.
    # 예약발송은 crontab(flask send-scheduled-mails)으로 이관.
    #   워커 8개가 각자 1분마다 돌면 같은 메일이 8번 나간다.
    #   다른 주기작업들이 이미 같은 이유로 옮겨져 있다.
    _scheduler.add_job(
        lambda: _process_auto_reply_forward(app),
        trigger='interval',
        minutes=5,
        id='mail_auto_reply_forward',
        replace_existing=True,
    )
    # 일일 알림, 알림 정리는 crontab으로 이관 (gunicorn 멀티워커 중복 실행 방지)
    # → app.py의 Flask CLI: check-notifications, cleanup-notifications
    # G2B 동기화, 메일파일 정리도 동일하게 crontab으로 이관됨
    _scheduler.start()
    logger.info("[scheduler] 백그라운드 스케줄러 시작 (자동회신/전달 5분)")
