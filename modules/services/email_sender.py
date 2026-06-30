"""
SMTP 이메일 발송 모듈.

- SMTP: mail.mgnt.kr:25 (환경변수로 설정 가능)
- 발신: purchase@mgnt.kr
- DRY_RUN 모드 지원 (SMTP_DRY_RUN=true)
"""

import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

logger = logging.getLogger(__name__)


def _get_smtp_config():
    """환경변수에서 SMTP 설정을 읽는다."""
    return {
        'host': os.environ.get('SMTP_HOST', 'mail.mgnt.kr'),
        'port': int(os.environ.get('SMTP_PORT', '25')),
        'user': os.environ.get('SMTP_USER', 'purchase@mgnt.kr'),
        'password': os.environ.get('SMTP_PASS', ''),
        'dry_run': os.environ.get('SMTP_DRY_RUN', 'true').lower() in ('true', '1', 'yes'),
    }


def send_purchase_order_email(to_email, subject, body_text, pdf_bytes=None, pdf_filename=None):
    """
    발주서 이메일을 발송한다.

    Args:
        to_email: 수신자 이메일 주소
        subject: 메일 제목
        body_text: 메일 본문 (plain text)
        pdf_bytes: 첨부할 PDF 파일 바이트 (optional)
        pdf_filename: 첨부 파일명 (optional)

    Returns:
        dict: {'success': bool, 'message': str}
    """
    config = _get_smtp_config()

    if config['dry_run']:
        logger.info("[DRY_RUN] 이메일 발송 시뮬레이션")
        logger.info("  To: %s", to_email)
        logger.info("  Subject: %s", subject)
        logger.info("  Body: %s", body_text[:100])
        logger.info("  PDF 첨부: %s (%d bytes)", pdf_filename, len(pdf_bytes) if pdf_bytes else 0)
        return {
            'success': True,
            'message': f'[DRY_RUN] 테스트 모드 - 실제 발송하지 않음 (To: {to_email})',
        }

    try:
        msg = MIMEMultipart()
        msg['From'] = config['user']
        msg['To'] = to_email
        msg['Subject'] = subject

        # 본문
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        # PDF 첨부
        if pdf_bytes and pdf_filename:
            attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
            attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
            msg.attach(attachment)

        # SMTP 발송
        import ssl as _ssl
        smtp_ctx = _ssl.create_default_context()
        smtp_ctx.check_hostname = False
        smtp_ctx.verify_mode = _ssl.CERT_NONE

        with smtplib.SMTP(config['host'], config['port'], timeout=30) as server:
            # 인증이 필요한 경우
            if config['password']:
                try:
                    server.starttls(context=smtp_ctx)
                except smtplib.SMTPNotSupportedError:
                    pass  # TLS 미지원 서버
                server.login(config['user'], config['password'])

            server.sendmail(config['user'], [to_email], msg.as_string())

        logger.info("이메일 발송 성공: To=%s, Subject=%s", to_email, subject)
        return {'success': True, 'message': '이메일 발송 완료'}

    except smtplib.SMTPException as e:
        logger.error("SMTP 오류: %s", e)
        return {'success': False, 'message': f'SMTP 오류: {e}'}
    except Exception as e:
        logger.error("이메일 발송 실패: %s", e)
        return {'success': False, 'message': f'발송 실패: {e}'}


def _get_user_mail_account(user_id):
    """로그인 사용자의 mail_accounts SMTP 설정을 가져온다."""
    if not user_id:
        return None
    try:
        from modules.db_context import get_db
        from modules.services.mail_client import decrypt_password
        from sqlalchemy import text
        with get_db() as db:
            row = db.execute(text(
                "SELECT email, smtp_host, smtp_port, username, password_encrypted "
                "FROM light_sync.mail_accounts WHERE user_id = :uid AND is_active = true "
                "ORDER BY is_default DESC LIMIT 1"
            ), {"uid": user_id}).fetchone()
            if row:
                return {
                    'email': row[0],
                    'smtp_host': row[1],
                    'smtp_port': row[2],
                    'username': row[3],
                    'password': decrypt_password(row[4]),
                }
    except Exception as e:
        logger.warning("사용자 메일계정 조회 실패 (user_id=%s): %s", user_id, e)
    return None


def _get_shared_mail_account(email):
    """공용(부서) 메일 계정의 SMTP 설정을 이메일 주소로 가져온다."""
    if not email:
        return None
    try:
        from modules.db_context import get_db
        from modules.services.mail_client import decrypt_password
        from sqlalchemy import text
        with get_db() as db:
            row = db.execute(text(
                "SELECT email, smtp_host, smtp_port, username, password_encrypted, display_name "
                "FROM light_sync.mail_accounts "
                "WHERE email = :email AND is_active = true "
                "ORDER BY is_shared DESC LIMIT 1"
            ), {"email": email}).fetchone()
            if row:
                return {
                    'email': row[0],
                    'smtp_host': row[1],
                    'smtp_port': row[2],
                    'username': row[3],
                    'password': decrypt_password(row[4]),
                    'display_name': row[5],
                }
    except Exception as e:
        logger.warning("공용 메일계정 조회 실패 (email=%s): %s", email, e)
    return None


def send_email_with_attachments(to_email, subject, body_text, attachments=None,
                                from_email=None, from_name=None, user_id=None,
                                from_account_email=None, body_html=None):
    """
    다중 첨부파일 이메일 발송 (가공발주 등).
    - from_account_email이 주어지면 해당 부서 공용 계정(purchase/sales/eng 등)으로 발송.
    - 없으면 user_id에 해당하는 사용자의 메일 계정(mail_accounts)으로 발송.
    - 둘 다 없으면 환경변수 SMTP 설정(purchase@mgnt.kr) fallback.
    """
    attachments = attachments or []

    # 1) 발신 계정 결정: 부서 공용계정 우선 → 사용자 개인계정 → 환경변수
    acct = _get_shared_mail_account(from_account_email) if from_account_email else None
    if acct:
        # 부서 메일로 발송 시 From 표시도 해당 부서로 (별도 지정 없을 때)
        if not from_email:
            from_email = acct['email']
        if not from_name:
            from_name = acct.get('display_name')
    else:
        acct = _get_user_mail_account(user_id) if user_id else None
    if acct:
        smtp_host = acct['smtp_host']
        smtp_port = acct['smtp_port']
        smtp_user = acct['username']
        smtp_pass = acct['password']
        envelope_from = acct['email']
    else:
        config = _get_smtp_config()
        smtp_host = config['host']
        smtp_port = config['port']
        smtp_user = config['user']
        smtp_pass = config['password']
        envelope_from = config['user']

    display_email = from_email or envelope_from

    # From 헤더: 한글 이름이 있으면 RFC2047 인코딩
    if from_name:
        from email.utils import formataddr
        from email.header import Header
        display_from = formataddr((str(Header(from_name, 'utf-8')), display_email))
    else:
        display_from = display_email

    config = _get_smtp_config()
    if config['dry_run']:
        logger.info("[DRY_RUN] 이메일 발송 시뮬레이션")
        logger.info("  From: %s, To: %s, Subject: %s", display_from, to_email, subject)
        logger.info("  첨부: %d건", len(attachments))
        return {
            'success': True,
            'message': f'[DRY_RUN] 테스트 모드 (From: {display_from}, To: {to_email}, 첨부 {len(attachments)}건)',
        }

    try:
        msg = MIMEMultipart()
        msg['From'] = display_from
        msg['To'] = to_email
        msg['Subject'] = subject
        if display_email != envelope_from:
            msg['Reply-To'] = display_email
        if body_html:
            alt = MIMEMultipart('alternative')
            alt.attach(MIMEText(body_text, 'plain', 'utf-8'))
            alt.attach(MIMEText(body_html, 'html', 'utf-8'))
            msg.attach(alt)
        else:
            msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        for fname, fbytes in attachments:
            att = MIMEApplication(fbytes)
            att.add_header('Content-Disposition', 'attachment', filename=fname)
            msg.attach(att)

        import ssl as _ssl
        smtp_ctx = _ssl.create_default_context()
        smtp_ctx.check_hostname = False
        smtp_ctx.verify_mode = _ssl.CERT_NONE

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=smtp_ctx) as server:
                if smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(envelope_from, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                if smtp_pass:
                    try:
                        server.starttls(context=smtp_ctx)
                    except smtplib.SMTPNotSupportedError:
                        pass
                    server.login(smtp_user, smtp_pass)
                server.sendmail(envelope_from, [to_email], msg.as_string())

        logger.info("이메일 발송 성공: From=%s(%s), To=%s, Subject=%s, 첨부=%d건",
                     envelope_from, smtp_user, to_email, subject, len(attachments))
        return {'success': True, 'message': f'이메일 발송 완료 ({envelope_from})'}

    except smtplib.SMTPException as e:
        logger.error("SMTP 오류: %s", e)
        return {'success': False, 'message': f'SMTP 오류: {e}'}
    except Exception as e:
        logger.error("이메일 발송 실패: %s", e)
        return {'success': False, 'message': f'발송 실패: {e}'}
