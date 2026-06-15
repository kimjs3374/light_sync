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


def _auto_update_trip_status():
    """출장 상태 자동 전환 (10분마다)
    예정  → 진행중 : departure_date <= 지금
    진행중 → 완료   : return_date   <= 지금
    """
    from modules.db_context import get_db
    from modules.models import BusinessTrip

    now = datetime.datetime.now()
    updated = 0
    try:
        with get_db() as db:
            # 예정 → 진행중
            to_ongoing = db.query(BusinessTrip).filter(
                BusinessTrip.status == '예정',
                BusinessTrip.departure_date <= now,
            ).all()
            for trip in to_ongoing:
                trip.status = '진행중'
                updated += 1

            # 예정/진행중 → 완료
            to_done = db.query(BusinessTrip).filter(
                BusinessTrip.status.in_(['예정', '진행중']),
                BusinessTrip.return_date <= now,
            ).all()
            for trip in to_done:
                trip.status = '완료'
                updated += 1

            if updated:
                db.commit()
                logger.info(f"[scheduler] 출장 상태 자동 업데이트 {updated}건")
    except Exception as e:
        logger.error(f"[scheduler] 출장 상태 업데이트 오류: {e}")


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


def _process_scheduled_mails(app):
    """예약발송 처리 — 매 1분마다 실행."""
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
                            continue
                        pw = decrypt_password(account.password_encrypted)
                        client = MailClient(
                            account.imap_host, account.imap_port,
                            account.smtp_host, account.smtp_port,
                            account.username, pw, account.use_ssl,
                        )
                        with client:
                            client.send_message(
                                from_addr=account.email,
                                from_name=account.display_name or '',
                                to=sched.to_addresses,
                                cc=sched.cc_addresses or None,
                                bcc=sched.bcc_addresses or None,
                                subject=sched.subject or '',
                                html_body=sched.body or '',
                            )
                        sched.status = 'sent'
                        sched.sent_at = datetime.now()
                        logger.info(f"[scheduler] 예약발송 완료: id={sched.id} to={sched.to_addresses}")
                    except Exception as e:
                        sched.status = 'failed'
                        logger.error(f"[scheduler] 예약발송 실패: id={sched.id} {e}")
                db.commit()
    except Exception as e:
        logger.error(f"[scheduler] 예약발송 처리 오류: {e}")


def init_scheduler(app):
    """앱 컨텍스트 안에서 스케줄러 시작"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _auto_update_trip_status,
        trigger='interval',
        minutes=10,
        id='trip_status_update',
        replace_existing=True,
    )
    _scheduler.add_job(
        lambda: _process_scheduled_mails(app),
        trigger='interval',
        minutes=1,
        id='mail_scheduled_send',
        replace_existing=True,
    )
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
    logger.info("[scheduler] 백그라운드 스케줄러 시작 (출장상태 10분, 예약발송 1분, 자동회신/전달 5분)")
