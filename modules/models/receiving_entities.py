import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .base import Base

RCV_STATUS_CHOICES = ['검수대기', '검수완료', '반품']


class Receiving(Base):
    """입고 (발주서 기반 또는 직접 입고)"""
    __tablename__ = 'receivings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    rcv_no = Column(String(20), unique=True, nullable=False)      # RCV2026-001
    rcv_date = Column(Date, nullable=False)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    status = Column(String(20), default='검수대기')     # 검수대기/검수완료/반품
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    fo_id = Column(Integer, ForeignKey('processing_orders.id'), nullable=True)   # 가공발주 연결

    vendor = relationship("Vendor")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])
    processing_order = relationship("ProcessingOrder", foreign_keys=[fo_id])
    contract = relationship("Contract", foreign_keys=[contract_id])
    creator = relationship("User", foreign_keys=[created_by])
    items = relationship("ReceivingItem", back_populates="receiving", cascade="all, delete-orphan", order_by="ReceivingItem.id")


class ReceivingItem(Base):
    """입고 품목 상세"""
    __tablename__ = 'receiving_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiving_id = Column(Integer, ForeignKey('receivings.id'), nullable=False)
    po_item_id = Column(Integer, ForeignKey('purchase_order_items.id'), nullable=True)
    fo_item_id = Column(Integer, ForeignKey('processing_order_items.id'), nullable=True)
    item_cd = Column(String(50), nullable=True)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    received_qty = Column(Float, default=0)
    unit = Column(String(50), nullable=True)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    note = Column(Text, nullable=True)

    receiving = relationship("Receiving", back_populates="items")
    po_item = relationship("PurchaseOrderItem", foreign_keys=[po_item_id])


class ReceivingHistory(Base):
    """iCUBE 입고이력 (마이그레이션용, 읽기 전용)"""
    __tablename__ = 'receiving_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    icube_rcv_nb = Column(String(30), unique=True, nullable=False)
    receive_date = Column(Date, nullable=True)
    vendor_name = Column(String(200), nullable=True)
    vendor_tr_cd = Column(String(20), nullable=True)
    warehouse = Column(String(50), nullable=True)
    items_json = Column(Text, nullable=True)    # JSON: [{item_cd, item_name, spec, qty, unit_price, amount, unit, remark}]
    total_amount = Column(Float, default=0)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


class ReceivingPhotoPost(Base):
    """입고사진 피드 게시물"""
    __tablename__ = 'receiving_photo_posts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    vendor_name = Column(String(200), nullable=True)
    po_no = Column(String(20), nullable=True)
    photos_json = Column(Text, nullable=True)  # JSON: [{file_name, file_path, file_size}]
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    author = relationship("User", foreign_keys=[created_by])
