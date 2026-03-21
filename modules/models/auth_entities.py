import datetime

from sqlalchemy import (
    Boolean,
    Column,
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
    extra_menus = Column(Text, nullable=True)           # 개인 추가 메뉴 권한 (CSV: "item,vendor")
    can_approve_delete = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
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


class GroupPermission(Base):
    __tablename__ = 'group_permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(50), unique=True, nullable=False)
    allowed_menus = Column(Text, nullable=False)


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
