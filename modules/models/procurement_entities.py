import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base

PO_STATUS_CHOICES = ['작성중', '발송완료', '입고대기', '입고완료', '취소']
FO_STATUS_CHOICES = ['작성중', '발주완료', '가공중', '입고완료', '취소']
FO_TYPE_CHOICES = ['사급가공', '외주가공']


class Vendor(Base):
    """거래처 마스터 (iCUBE STRADE 마이그레이션)"""
    __tablename__ = 'vendors'

    id = Column(Integer, primary_key=True, autoincrement=True)
    icube_tr_cd = Column(String(20), unique=True, nullable=True)  # iCUBE 거래처코드
    name = Column(String(200), nullable=False)
    ceo_name = Column(String(100), nullable=True)
    business_no = Column(String(50), nullable=True)    # 사업자번호
    email = Column(String(200), nullable=True)
    tel = Column(String(100), nullable=True)
    fax = Column(String(100), nullable=True)
    address = Column(String(500), nullable=True)
    business = Column(String(200), nullable=True)      # 업종
    jongmok = Column(String(200), nullable=True)       # 종목
    is_active = Column(Boolean, default=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    purchase_orders = relationship("PurchaseOrder", back_populates="vendor")
    vendor_items = relationship("VendorItem", back_populates="vendor", cascade="all, delete-orphan")


class VendorItem(Base):
    """거래처별 담당자재 매핑"""
    __tablename__ = 'vendor_items'
    __table_args__ = (
        UniqueConstraint('vendor_id', 'item_id', name='uq_vendor_item'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=True)  # 마스터 품목 연결 (nullable: 직접입력도 가능)
    item_name = Column(String(300), nullable=False)       # 품명
    item_spec = Column(String(500), nullable=True)        # 규격
    unit = Column(String(50), nullable=True)              # 단위
    last_price = Column(Float, nullable=True)             # 최근 단가
    note = Column(Text, nullable=True)                    # 메모
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    vendor = relationship("Vendor", back_populates="vendor_items")
    item = relationship("Item")


class PurchaseOrder(Base):
    """발주서 (신규 작성용)"""
    __tablename__ = 'purchase_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    po_no = Column(String(20), unique=True, nullable=False)   # PO2026-001
    po_date = Column(Date, nullable=False)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)  # 계약 연결
    assigned_to = Column(Integer, ForeignKey('users.id'), nullable=True)      # 담당자
    status = Column(String(20), default='작성중')  # 작성중/발송완료/입고대기/입고완료/취소
    total_amount = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    email_sent_at = Column(DateTime, nullable=True)
    email_to = Column(String(200), nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    vendor = relationship("Vendor", back_populates="purchase_orders")
    project = relationship("Project", foreign_keys=[project_id])
    contract = relationship("Contract", foreign_keys=[contract_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan", order_by="PurchaseOrderItem.id")
    files = relationship("PurchaseOrderFile", back_populates="purchase_order",
                         cascade="all, delete-orphan", order_by="PurchaseOrderFile.id")


class PurchaseOrderItem(Base):
    """발주 품목 상세"""
    __tablename__ = 'purchase_order_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=True)
    item_code = Column(String(30), nullable=True)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    quantity = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    unit = Column(String(50), nullable=True)
    delivery_date = Column(Date, nullable=True)
    expected_in_date = Column(Date, nullable=True)
    in_confirmed = Column(Boolean, default=False)
    in_confirmed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)

    bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="items")
    bom_item = relationship("BomItem", foreign_keys=[bom_item_id])


class PurchaseOrderHistory(Base):
    """iCUBE 발주이력 (마이그레이션용, 읽기 전용)"""
    __tablename__ = 'purchase_order_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    icube_cls_nb = Column(String(30), unique=True, nullable=False)
    order_date = Column(Date, nullable=True)
    vendor_name = Column(String(200), nullable=True)
    vendor_tr_cd = Column(String(20), nullable=True)
    items_json = Column(Text, nullable=True)    # JSON: [{item_cd, item_name, spec, qty, unit_price, amount, unit, remark}]
    total_amount = Column(Float, default=0)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


class EmailHistory(Base):
    """이메일 발송이력"""
    __tablename__ = 'email_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    send_date = Column(DateTime, default=datetime.datetime.now)
    sender = Column(String(200), nullable=True)
    receiver = Column(String(200), nullable=True)
    subject = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)
    attachment = Column(String(500), nullable=True)
    is_success = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=True)
    po_ref = Column(String(50), nullable=True)    # iCUBE 발주번호 참조 (PO2603000015 등)
    created_at = Column(DateTime, default=datetime.datetime.now)


# ── 가공발주 ──────────────────────────────────────────────────

class ProcessingOrder(Base):
    """가공발주서 (외주 가공업체 발주)"""
    __tablename__ = 'processing_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fo_no = Column(String(20), unique=True, nullable=False)       # FO2026-001
    fo_date = Column(Date, nullable=False)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    processing_type = Column(String(20), default='외주가공')       # 사급가공 / 외주가공
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    assigned_to = Column(Integer, ForeignKey('users.id'), nullable=True)
    status = Column(String(20), default='작성중')
    total_amount = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    history_log = Column(Text, nullable=True)

    vendor = relationship("Vendor")
    project = relationship("Project", foreign_keys=[project_id])
    contract = relationship("Contract", foreign_keys=[contract_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    items = relationship("ProcessingOrderItem", back_populates="processing_order",
                         cascade="all, delete-orphan", order_by="ProcessingOrderItem.id")
    files = relationship("ProcessingOrderFile", back_populates="processing_order",
                         cascade="all, delete-orphan")


class ProcessingOrderItem(Base):
    """가공발주 품목"""
    __tablename__ = 'processing_order_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fo_id = Column(Integer, ForeignKey('processing_orders.id', ondelete='CASCADE'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=True)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    quantity = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    unit = Column(String(50), nullable=True)
    delivery_date = Column(Date, nullable=True)
    in_confirmed = Column(Boolean, default=False)
    in_confirmed_at = Column(DateTime, nullable=True)
    bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)
    material_order_id = Column(Integer, ForeignKey('material_orders.id'), nullable=True)
    processing_note = Column(Text, nullable=True)
    note = Column(Text, nullable=True)

    processing_order = relationship("ProcessingOrder", back_populates="items")
    bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
    material_order = relationship("MaterialOrder", foreign_keys=[material_order_id])


class ProcessingOrderFile(Base):
    """가공발주 첨부파일 (DWG 등)"""
    __tablename__ = 'processing_order_files'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fo_id = Column(Integer, ForeignKey('processing_orders.id', ondelete='CASCADE'), nullable=False)
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_size = Column(Integer, default=0)
    file_type = Column(String(20), nullable=True)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.datetime.now)

    processing_order = relationship("ProcessingOrder", back_populates="files")


class PurchaseOrderFile(Base):
    """자재발주 검수 사진/파일"""
    __tablename__ = 'purchase_order_files'

    id = Column(Integer, primary_key=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False)
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_size = Column(Integer, default=0)
    file_type = Column(String(20), nullable=True)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.datetime.now)
    # 검수 확인
    is_confirmed = Column(Integer, default=0)          # 0=대기, 1=확인
    confirmed_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="files")
    uploader = relationship("User", foreign_keys=[uploaded_by])
    confirmer = relationship("User", foreign_keys=[confirmed_by])
