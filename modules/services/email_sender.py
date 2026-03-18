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
