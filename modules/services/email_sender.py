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
        with smtplib.SMTP(config['host'], config['port'], timeout=30) as server:
            # 인증이 필요한 경우
            if config['password']:
                try:
                    server.starttls()
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


def send_email_with_attachments(to_email, subject, body_text, attachments=None, from_email=None, from_name=None):
    """
    다중 첨부파일 이메일 발송 (가공발주 등).

    Args:
        to_email: 수신자 이메일
        subject: 메일 제목
        body_text: 메일 본문
        attachments: list of (filename, content_bytes) tuples
        from_email: 발신자 이메일 (None이면 SMTP 기본값)
        from_name: 발신자 표시 이름 (None이면 이메일만 표시)

    Returns:
        dict: {'success': bool, 'message': str}
    """
    config = _get_smtp_config()
    attachments = attachments or []
    envelope_from = from_email or config['user']

    # From 헤더: 한글 이름이 있으면 RFC2047 인코딩
    if from_name:
        from email.utils import formataddr
        from email.header import Header
        display_from = formataddr((str(Header(from_name, 'utf-8')), envelope_from))
    else:
        display_from = envelope_from

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
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        for fname, fbytes in attachments:
            att = MIMEApplication(fbytes)
            att.add_header('Content-Disposition', 'attachment', filename=fname)
            msg.attach(att)

        with smtplib.SMTP(config['host'], config['port'], timeout=30) as server:
            if config['password']:
                try:
                    server.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass
                server.login(config['user'], config['password'])
            server.sendmail(envelope_from, [to_email], msg.as_string())

        logger.info("이메일 발송 성공: From=%s, To=%s, Subject=%s, 첨부=%d건", envelope_from, to_email, subject, len(attachments))
        return {'success': True, 'message': '이메일 발송 완료'}

    except smtplib.SMTPException as e:
        logger.error("SMTP 오류: %s", e)
        return {'success': False, 'message': f'SMTP 오류: {e}'}
    except Exception as e:
        logger.error("이메일 발송 실패: %s", e)
        return {'success': False, 'message': f'발송 실패: {e}'}
