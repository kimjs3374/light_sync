import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Time,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base


class Delivery(Base):
    __tablename__ = 'deliveries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)

    delivery_status = Column(String(30), default='납품대기')

    # 검수 관련 필드 (매그나텍 PHASE 7)
    inspection_status = Column(String(20), default='미검수')    # 미검수/합격/불합격/보완
    inspection_date = Column(Date, nullable=True)                # 검수일
    inspection_note = Column(Text, nullable=True)                # 검수 비고
    inspector = Column(String(100), nullable=True)               # 검수자

    planned_total_qty = Column(Integer, default=0)
    delivered_total_qty = Column(Integer, default=0)

    contact_name = Column(String(100), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    note = Column(Text, nullable=True)

    entity_version = Column(Integer, nullable=False, default=1)  # 동시수정 충돌 방지 (optimistic locking)

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    project = relationship("Project", back_populates="deliveries")
    contract = relationship("Contract", back_populates="deliveries")
    splits = relationship("DeliverySplit", back_populates="delivery", cascade="all, delete-orphan", order_by="DeliverySplit.split_no")
    photos = relationship("DeliveryPhoto", back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryPhoto.created_at.desc()")


class DeliverySplit(Base):
    __tablename__ = 'delivery_splits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(Integer, ForeignKey('deliveries.id'), nullable=False)
    contract_item_id = Column(Integer, ForeignKey('contract_items.id'), nullable=True)

    split_no = Column(Integer, default=1)
    quantity = Column(Integer, default=0)
    scheduled_date = Column(Date, nullable=True)
    # 납품예정 시각. NULL 이면 마감시각(DELIVERY_DUE_HOUR, 기본 18시)으로 간주.
    # 이 시각이 지나면 담당자에게 카카오워크 확인 DM 이 나간다.
    scheduled_time = Column(Time, nullable=True)
    confirmed_date = Column(Date, nullable=True)
    loading_done_at = Column(DateTime, nullable=True)
    delivered_done_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='예정')  # 대기/예정/진행중/완료 (한글 통일, 영문 deprecated)
    note = Column(Text, nullable=True)

    entity_version = Column(Integer, nullable=False, default=1)  # 동시수정 충돌 방지 (optimistic locking)

    delivery = relationship("Delivery", back_populates="splits")
    contract_item = relationship("ContractItem")
    split_items = relationship("DeliverySplitItem", back_populates="split", cascade="all, delete-orphan")


class DeliverySplitItem(Base):
    """회차별 모델(품목)별 수량 — 1회차에 여러 모델 동시 납품"""
    __tablename__ = 'delivery_split_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    split_id = Column(Integer, ForeignKey('delivery_splits.id', ondelete='CASCADE'), nullable=False)
    contract_item_id = Column(Integer, ForeignKey('contract_items.id', ondelete='CASCADE'), nullable=False)
    quantity = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('split_id', 'contract_item_id', name='uq_split_item'),
    )

    split = relationship("DeliverySplit", back_populates="split_items")
    contract_item = relationship("ContractItem")


class DeliveryPhoto(Base):
    __tablename__ = 'delivery_photos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(Integer, ForeignKey('deliveries.id'), nullable=False)
    split_id = Column(Integer, ForeignKey('delivery_splits.id'), nullable=True)

    photo_type = Column(String(30), default='etc')
    file_name = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    uploaded_by = Column(String(50), default='사용자')
    created_at = Column(DateTime, default=datetime.datetime.now)

    delivery = relationship("Delivery", back_populates="photos")
