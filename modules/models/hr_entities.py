"""인사관리(HR) 모델

연차는 입사일 기준 자동 산정(근로기준법) + 전자결재 휴가 승인분 자동 차감.
LeaveAdjustment는 이월/수동 보정용 가감 기록.
"""
import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
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
