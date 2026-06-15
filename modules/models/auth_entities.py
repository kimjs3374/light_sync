import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .base import Base


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(50), nullable=False)
    phone_number = Column(String(20), nullable=False)
    position = Column(String(50), nullable=True)          # 직급 (부장, 과장 등)
    email = Column(String(200), nullable=True)            # 이메일
    office_tel = Column(String(30), nullable=True)        # 사무실 전화
    office_fax = Column(String(30), nullable=True)        # 팩스
    user_group = Column(String(50), ForeignKey('group_permissions.group_name'))
    role = Column(String(20), default="user")
    extra_menus = Column(Text, nullable=True)           # 개인 추가 메뉴 권한 (CSV: "item:rw,vendor:r")
    hide_financial_override = Column(Boolean, nullable=True)  # 개인 금액 숨김 (None=그룹따름, True=숨김, False=표시)
    can_approve_delete = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)  # 비밀번호 초기화 후 강제 변경
    address = Column(String(300), nullable=True)          # 자택 주소 (현장대리인계용)
    birth_date = Column(Date, nullable=True)               # 생년월일
    hire_date = Column(Date, nullable=True)                # 입사일
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    priority_permission = relationship(
        "UserPriorityPermission",
        foreign_keys="UserPriorityPermission.user_id",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    _MAIL_DISCLAIMER = (
        '위 메일 및 첨부자료는 지정된 수신인만을 위한 것이며 관련법령에 의해 보호대상이 되는 기밀사항을 포함할 수 있습니다.<br>'
        '본 메일, 혹은 첨부자료에 포함된 내용을 무단으로 조사, 사용, 복사, 공개 혹은 배포하는 행위는 엄격히 금지되어 있습니다.<br>'
        '이 메일이 잘못 전송된 경우에는 본 메일 및 첨부자료를 복사하거나 공개하지 마시고<br>'
        '발신인에게 알려주시고 메일 및 첨부자료는 즉시 삭제해주시기 바랍니다.'
    )

    def to_signature_html(self):
        """User 정보 기반 메일 서명 HTML 생성"""
        parts = []
        title = '<strong>(주)매그나텍</strong>'
        if self.user_group:
            title += f' {self.user_group}'
        if self.full_name:
            title += f' {self.full_name}'
        if self.position:
            title += f' {self.position}'
        parts.append(title)
        if self.phone_number:
            parts.append(f'Mobile : {self.phone_number}')
        parts.append('Office : 061-392-5508')
        parts.append('Fax : 061-392-5518')
        parts.append('홈페이지 : <a href="https://www.magnatech.co.kr">www.magnatech.co.kr</a>')
        sep = '═' * 40
        disclaimer = f'<div style="font-size:11px;color:#333;margin-bottom:8px;">{self._MAIL_DISCLAIMER}</div>'
        return f'{disclaimer}{sep}<br>{"<br>".join(parts)}<br>{sep}'


class GroupPermission(Base):
    __tablename__ = 'group_permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(50), unique=True, nullable=False)
    allowed_menus = Column(Text, nullable=False)
    hide_financial = Column(Boolean, default=False)  # True면 금액 컬럼 미표시


class UserPriorityPermission(Base):
    __tablename__ = 'user_priority_permissions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    granted_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    granted_by_name = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    user = relationship("User", foreign_keys=[user_id], back_populates="priority_permission")


class EmailSignature(Base):
    """사용자별 이메일 서명"""
    __tablename__ = 'email_signatures'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    department = Column(String(50), nullable=True)     # 경영관리부
    position = Column(String(50), nullable=True)       # 부장
    display_name = Column(String(50), nullable=True)   # 이지훈
    email = Column(String(200), nullable=True)         # purchase@mgnt.kr
    mobile = Column(String(30), nullable=True)         # 010-5465-5621
    office_tel = Column(String(30), nullable=True)     # 061-392-5508
    fax = Column(String(30), nullable=True)            # 061-392-5518
    is_default = Column(Boolean, default=False)        # 기본 서명 여부
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    user = relationship("User")

    def to_text(self):
        """서명 텍스트 생성"""
        lines = ['=' * 65]
        title = '(주)매그나텍'
        if self.department:
            title += f' {self.department}'
        if self.display_name:
            title += f' {self.display_name}'
        if self.position:
            title += f' {self.position}'
        lines.append(title)
        if self.email:
            lines.append(f'E-mail : {self.email}')
        if self.mobile:
            lines.append(f'Mobile : {self.mobile}')
        if self.office_tel:
            lines.append(f'Office : {self.office_tel}')
        if self.fax:
            lines.append(f'Fax    : {self.fax}')
        lines.append('홈페이지 : https://www.magnatech.co.kr')
        lines.append('=' * 65)
        return '\n'.join(lines)

    DISCLAIMER = (
        '위 메일 및 첨부자료는 지정된 수신인만을 위한 것이며 관련법령에 의해 보호대상이 되는 기밀사항을 포함할 수 있습니다.<br>'
        '본 메일, 혹은 첨부자료에 포함된 내용을 무단으로 조사, 사용, 복사, 공개 혹은 배포하는 행위는 엄격히 금지되어 있습니다.<br>'
        '이 메일이 잘못 전송된 경우에는 본 메일 및 첨부자료를 복사하거나 공개하지 마시고<br>'
        '발신인에게 알려주시고 메일 및 첨부자료는 즉시 삭제해주시기 바랍니다.'
    )

    def to_html(self):
        """서명 HTML 생성"""
        parts = []
        title = '<strong>(주)매그나텍</strong>'
        if self.department:
            title += f' {self.department}'
        if self.display_name:
            title += f' {self.display_name}'
        if self.position:
            title += f' {self.position}'
        parts.append(title)
        if self.mobile:
            parts.append(f'Mobile : {self.mobile}')
        if self.office_tel:
            parts.append(f'Office : {self.office_tel}')
        if self.fax:
            parts.append(f'Fax : {self.fax}')
        parts.append('홈페이지 : <a href="https://www.magnatech.co.kr">www.magnatech.co.kr</a>')
        sep = '<span style="color:#cbd5e1;">═' * 40 + '</span>'
        disclaimer = f'<div style="font-size:11px;color:#94a3b8;margin-bottom:8px;">{self.DISCLAIMER}</div>'
        return f'{disclaimer}{sep}<br>{"<br>".join(parts)}<br>{sep}'


# ==============================================================
# OIDC Provider (사내 SSO) — Mattermost 등 외부 도구 인증용
# ==============================================================
class OAuthClient(Base):
    __tablename__ = 'oauth_clients'
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(80), unique=True, nullable=False, index=True)
    client_secret_hash = Column(String(200), nullable=False)
    name = Column(String(100), nullable=False)
    redirect_uris = Column(Text, nullable=False)              # 줄바꿈 구분 다중 URI
    allowed_scopes = Column(String(200), default='openid profile email')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    notes = Column(Text, nullable=True)


class OAuthCode(Base):
    __tablename__ = 'oauth_codes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(120), unique=True, nullable=False, index=True)
    client_id = Column(String(80), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    redirect_uri = Column(String(500), nullable=False)
    scope = Column(String(200), nullable=False)
    nonce = Column(String(200), nullable=True)
    code_challenge = Column(String(200), nullable=True)
    code_challenge_method = Column(String(20), nullable=True)
    used = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)


class OAuthToken(Base):
    __tablename__ = 'oauth_tokens'
    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String(200), unique=True, nullable=False, index=True)
    client_id = Column(String(80), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    scope = Column(String(200), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.now)
