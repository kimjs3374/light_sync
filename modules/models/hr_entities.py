"""인사관리(HR) 모델

연차는 입사일 기준 자동 산정(근로기준법) + 전자결재 휴가 승인분 자동 차감.
LeaveAdjustment는 이월/수동 보정용 가감 기록.
"""
import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import Base


class LeaveAdjustment(Base):
    """연차 수동 가감 (이월/보정/특별부여 등)."""
    __tablename__ = 'leave_adjustments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    days = Column(Numeric(4, 1), nullable=False)          # +이월/특별부여, -차감
    reason = Column(Text, nullable=True)
    leave_year = Column(Integer, nullable=True)           # 적용 연차연도(입사기념 연도 시작연도)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship('User')


class LeavePromotion(Base):
    """연차사용촉진제 (근로기준법 제61조) 촉구/지정 이력 = 법적 증빙.

    입사일 기준 연차연도, 1년 이상/미만 모두 대상.
    1차 촉구(사용시기 지정 요청) → 직원 셀프 지정 → 미지정 시 2차(회사 지정 통보).
    메일/ERP 알림 + 서면 통보서 출력 이력을 한 행에 누적 기록.
    """
    __tablename__ = 'leave_promotions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    leave_year = Column(Integer, nullable=False)          # 입사기념 연도 시작연도
    emp_type = Column(String(10), nullable=False, default='over1y')  # over1y/under1y
    stage = Column(String(10), nullable=False)            # first/extra/second

    # 촉구 시점 연차 스냅샷 (서면 서류용)
    year_start = Column(Date, nullable=True)
    year_end = Column(Date, nullable=True)                # 연차연도 마지막 사용일
    granted_days = Column(Numeric(4, 1), nullable=True)
    used_days = Column(Numeric(4, 1), nullable=True)
    remaining_days = Column(Numeric(4, 1), nullable=True) # 촉구 시점 미사용 잔여

    # 발송(촉구/통보)
    notified_at = Column(DateTime, default=datetime.datetime.now)
    notified_by = Column(String(50), nullable=True, default='system')  # system/관리자명
    channel = Column(String(20), nullable=True, default='email')       # email/erp/both
    email_to = Column(String(255), nullable=True)
    email_sent = Column(Boolean, default=False)

    # 직원 셀프 지정
    designate_due = Column(Date, nullable=True)           # 지정 기한(10일)
    employee_dates = Column(JSONB, nullable=True)         # 직원 지정 사용예정일
    designated_at = Column(DateTime, nullable=True)

    # 2차: 회사 지정
    admin_dates = Column(JSONB, nullable=True)            # 회사 지정 사용일
    admin_by = Column(String(50), nullable=True)
    admin_at = Column(DateTime, nullable=True)

    status = Column(String(20), default='sent')           # sent/designated/admin_designated/completed/expired
    printed_at = Column(DateTime, nullable=True)          # 서면 통보서 출력 시각
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship('User')


class LeaveUsage(Base):
    """연차 수동 사용 기록 (전자결재 미경유, 도입 전 사용분 소급 입력용).

    전자결재 휴가 승인분 자동 차감과 별개로, 관리자가 실제 사용한 연차를
    날짜 단위로 직접 등록한다. used_leave_days 계산 시 사용일 기준으로 합산.
    """
    __tablename__ = 'leave_usages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    used_date = Column(Date, nullable=False)              # 사용일(시작일)
    days = Column(Numeric(3, 1), nullable=False, default=1)  # 사용일수 (반차=0.5)
    leave_type = Column(String(20), nullable=True, default='연차')
    reason = Column(Text, nullable=True)
    leave_year = Column(Integer, nullable=True)           # 적용 연차연도(입사기념 연도 시작연도)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship('User')
