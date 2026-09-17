"""메일 관련 DB 모델: 계정 설정, 공유 접근, 외부 주소록"""

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .base import Base


class MailAccount(Base):
    """사용자별 메일 계정 (개인 + 공용)"""
    __tablename__ = 'mail_accounts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # NULL이면 공용계정
    email = Column(String(255), nullable=False)
    display_name = Column(String(100))
    imap_host = Column(String(255), nullable=False, default='192.168.0.101')
    imap_port = Column(Integer, nullable=False, default=993)
    smtp_host = Column(String(255), nullable=False, default='192.168.0.101')
    smtp_port = Column(Integer, nullable=False, default=587)
    username = Column(String(255), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    use_ssl = Column(Boolean, default=True)
    is_shared = Column(Boolean, default=False)
    account_type = Column(String(20), default='internal')  # internal / external
    signature = Column(Text)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailSharedAccess(Base):
    """공용 메일계정 접근 권한"""
    __tablename__ = 'mail_shared_access'
    __table_args__ = (
        UniqueConstraint('mail_account_id', 'user_id', name='uq_shared_access'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    mail_account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    can_send = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)


class MailReadReceipt(Base):
    """메일 수신확인 트래킹"""
    __tablename__ = 'mail_read_receipts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(String(64), unique=True, nullable=False, index=True)
    sender_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    mail_account_id = Column(Integer, ForeignKey('mail_accounts.id'))
    to_email = Column(String(255), nullable=False)
    subject = Column(String(500))
    sent_at = Column(DateTime, default=datetime.datetime.now)
    read_at = Column(DateTime, nullable=True)
    read_ip = Column(String(45), nullable=True)
    read_ua = Column(String(500), nullable=True)
    read_count = Column(Integer, default=0)


class MailLargeFile(Base):
    """대용량 첨부파일 (Supabase Storage, 30일 후 자동 삭제)"""
    __tablename__ = 'mail_large_files'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(64), unique=True, nullable=False, index=True)
    sender_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    storage_path = Column(String(500), nullable=False)
    download_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)
    is_deleted = Column(Boolean, default=False)


class MailRule(Base):
    """메일 자동분류 규칙"""
    __tablename__ = 'mail_rules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=True)
    is_shared = Column(Boolean, default=False)  # True면 모든 공용메일에 적용
    name = Column(String(200), nullable=False)
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    # 조건: JSON array [{"field":"from_email","op":"contains","value":"naver.com"}, ...]
    # field: from_email, from_domain, to_email, subject, body, has_attachment
    # op: equals, contains, starts_with, ends_with, regex
    conditions_json = Column(Text, nullable=False, default='[]')
    condition_logic = Column(String(10), default='AND')  # AND / OR
    # 동작
    action_type = Column(String(50), nullable=False)  # move_folder, add_label, mark_read, delete
    action_value = Column(String(500))  # 폴더명 or 라벨ID
    stop_processing = Column(Boolean, default=True)  # 이 규칙 매칭되면 이후 규칙 스킵
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailLabel(Base):
    """메일 라벨 (계정별 색상 태그)"""
    __tablename__ = 'mail_labels'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), nullable=False)
    color = Column(String(20), default='#64748b')
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)


class MailAutoReply(Base):
    """자동회신 (부재중)"""
    __tablename__ = 'mail_auto_reply'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    is_active = Column(Boolean, default=False)
    subject = Column(String(500), default='부재중 자동회신')
    body = Column(Text, default='')
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    reply_once = Column(Boolean, default=True)
    replied_addresses = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailAutoForward(Base):
    """자동전달"""
    __tablename__ = 'mail_auto_forward'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    is_active = Column(Boolean, default=False)
    forward_to = Column(String(500), nullable=False)
    keep_copy = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


class MailScheduled(Base):
    """예약발송"""
    __tablename__ = 'mail_scheduled'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    to_addresses = Column(Text, nullable=False)
    cc_addresses = Column(Text, default='')
    bcc_addresses = Column(Text, default='')
    subject = Column(String(500))
    body = Column(Text)
    attachments_json = Column(Text, default='[]')
    scheduled_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime)
    status = Column(String(20), default='pending')
    created_at = Column(DateTime, default=datetime.datetime.now)


class MailPin(Base):
    """메일 고정 (핀)"""
    __tablename__ = 'mail_pins'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    mail_uid = Column(Integer, nullable=False)
    folder = Column(String(200), default='INBOX')
    created_at = Column(DateTime, default=datetime.datetime.now)


class MailTemplate(Base):
    """메일 템플릿"""
    __tablename__ = 'mail_templates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='SET NULL'))
    name = Column(String(200), nullable=False)
    subject = Column(String(500))
    body = Column(Text)
    to_addresses = Column(Text, default='')
    cc_addresses = Column(Text, default='')
    is_shared = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailSharedRead(Base):
    """공유 편지함 읽음 표시"""
    __tablename__ = 'mail_shared_read'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    mail_uid = Column(Integer, nullable=False)
    folder = Column(String(200), default='INBOX')
    read_at = Column(DateTime, default=datetime.datetime.now)


class MailNotifyState(Base):
    """메일 신착 알림 워터마크 (mail_notifier 데몬용).

    account_id PK. last_seen_uid 까지는 이미 알림 처리됨.
    데몬은 5분 폴링으로 (last_seen_uid, *] 구간 신규 메일을 요약→MM DM 전송.
    """
    __tablename__ = 'mail_notify_state'

    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), primary_key=True)
    last_seen_uid = Column(BigInteger, nullable=False, default=0)
    uid_validity = Column(BigInteger)
    is_enabled = Column(Boolean, nullable=False, default=True)
    last_polled_at = Column(DateTime)
    last_error = Column(Text)
    notify_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailSendJob(Base):
    """큰 첨부를 올리며 보내는 중인 메일 한 건의 진행 상황.

    진행률을 메모리에만 두면 gunicorn 워커가 8개라 **조회 요청이 다른 워커로 가면
    그 작업을 모른다.** 그래서 DB 에 둔다.
    """
    __tablename__ = 'mail_send_jobs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False, unique=True)
    user_id = Column(Integer, nullable=False)
    account_id = Column(Integer)
    status = Column(String(20), nullable=False, default='uploading')
    phase = Column(String(200))
    total_bytes = Column(BigInteger, nullable=False, default=0)
    done_bytes = Column(BigInteger, nullable=False, default=0)
    file_count = Column(Integer, nullable=False, default=0)
    done_files = Column(Integer, nullable=False, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class NasConfig(Base):
    """사내 파일서버(시놀로지) 접속 정보 — 한 줄만 쓴다.

    비밀번호는 메일 계정과 같은 방식으로 암호화해 둔다(MAIL_ENCRYPT_KEY).
    allowed_shares 가 비어 있으면 그 계정이 보는 공유폴더 전부를 쓴다.
    """
    __tablename__ = 'nas_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(120), nullable=False)
    port = Column(Integer, nullable=False, default=5001)
    use_ssl = Column(Boolean, nullable=False, default=True)
    username = Column(String(100), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    allowed_shares = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    updated_by = Column(Integer)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailFolderPref(Base):
    """메일함 순서 · 그룹.

    IMAP 에는 순서가 없다(LIST 는 서버 마음대로 준다). 사람이 정한 순서와
    묶음은 우리가 든다. 계정마다 따로다 — 브라우저에 두면 자리를 옮길 때마다
    다시 정리해야 한다.
    """
    __tablename__ = 'mail_folder_prefs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    folder = Column(String(255), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    group_name = Column(String(60))
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class MailBlocklist(Base):
    """수신차단 / 수신허용 목록 (스팸).

    kind='block' 이면 이 주소에서 온 메일을 스팸함으로 옮긴다.
    kind='allow' 는 그 판정을 **먼저 이긴다** — 거래처가 도메인 단위 차단에
    걸려 스팸함으로 들어가는 사고를 막는 유일한 수단이다.
    value 는 주소(kim@x.co.kr) 또는 도메인(@x.co.kr).
    """
    __tablename__ = 'mail_blocklist'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('mail_accounts.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String(10), nullable=False, default='block')
    value = Column(String(255), nullable=False)
    memo = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.now)


class MailContact(Base):
    """외부 주소록.

    user_id 가 비어 있고 is_shared 면 회사 공용 주소록이다(가져온 것·공유한 것).
    """
    __tablename__ = 'mail_contacts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False)
    company = Column(String(200))
    phone = Column(String(60))
    memo = Column(Text)
    is_shared = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
