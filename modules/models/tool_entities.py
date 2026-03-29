import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .base import Base

TOOL_STATUS_CHOICES = ['보관중', '사용중', '점검중', '폐기']
CHECKOUT_STATUS_CHOICES = ['불출', '반납']


class Tool(Base):
    """공구 마스터"""
    __tablename__ = 'tools'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_name = Column(String(200), nullable=False)
    category = Column(String(50), default='전동공구')
    team = Column(String(50), nullable=True)
    total_qty = Column(Integer, default=1)
    available_qty = Column(Integer, default=1)
    current_location = Column(String(200), default='사무실')
    status = Column(String(20), default='보관중')
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    checkouts = relationship("ToolCheckout", back_populates="tool",
                             cascade="all, delete-orphan",
                             order_by="desc(ToolCheckout.checkout_at)")


class ToolCheckout(Base):
    """공구 불출/반납 이력"""
    __tablename__ = 'tool_checkouts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_id = Column(Integer, ForeignKey('tools.id'), nullable=False)
    checkout_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    checkout_user_name = Column(String(50), nullable=False)
    purpose = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    checkout_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    expected_return_at = Column(DateTime, nullable=True)
    return_at = Column(DateTime, nullable=True)
    return_note = Column(Text, nullable=True)
    status = Column(String(20), default='불출')
    created_at = Column(DateTime, default=datetime.datetime.now)

    tool = relationship("Tool", back_populates="checkouts")
    user = relationship("User", foreign_keys=[checkout_user_id])
