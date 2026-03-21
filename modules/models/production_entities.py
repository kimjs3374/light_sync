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


class ProductionProcess(Base):
    __tablename__ = 'production_processes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=False)
    contract_item_id = Column(Integer, ForeignKey('contract_items.id'), nullable=False)

    process_code = Column(String(40), nullable=False)
    process_name = Column(String(200), nullable=False)
    step_order = Column(Integer, default=1)
    parent_process_id = Column(Integer, ForeignKey('production_processes.id'), nullable=True)

    status = Column(String(30), default='대기')  # 대기/진행중/완료/스킵
    progress_qty = Column(Integer, default=0)
    progress_percent = Column(Float, default=0.0)
    is_optional = Column(Boolean, default=False)
    is_forced = Column(Boolean, default=False)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    contract_item = relationship("ContractItem", back_populates="production_processes")
    parent_process = relationship("ProductionProcess", remote_side=[id], foreign_keys=[parent_process_id], backref="child_processes")
    daily_logs = relationship("ProductionDailyLog", back_populates="production_process", cascade="all, delete-orphan", order_by="ProductionDailyLog.work_date.desc()")

    __table_args__ = (
        UniqueConstraint('contract_item_id', 'process_code', name='uq_prod_item_process_code'),
    )


class ProductionDailyLog(Base):
    __tablename__ = 'production_daily_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    production_process_id = Column(Integer, ForeignKey('production_processes.id'), nullable=False)
    work_date = Column(Date, nullable=False)
    daily_qty = Column(Integer, default=0)
    memo = Column(Text, nullable=True)
    created_by = Column(String(50), default='사용자')
    created_at = Column(DateTime, default=datetime.datetime.now)

    production_process = relationship("ProductionProcess", back_populates="daily_logs")


class Material(Base):
    __tablename__ = 'materials'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)

    category = Column(String(50), nullable=False)
    contract_name = Column(String(200))
    model_name = Column(String(200))
    quantity = Column(String(50))

    barcode_id = Column(String(100), unique=True, nullable=True)
    expected_arrival_date = Column(Date, nullable=True)

    status_sales = Column(String(50), default="계약확인")
    status_admin = Column(String(50), default="자재확인중")
    status_prod = Column(String(50), default="자재입고대기")

    project = relationship("Project", back_populates="materials")


class MaterialOrder(Base):
    __tablename__ = 'material_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=False)
    contract_item_id = Column(Integer, ForeignKey('contract_items.id'), nullable=False)

    item_category = Column(String(50), nullable=False)
    item_model_name = Column(String(200), nullable=True)
    material_name = Column(String(100), nullable=False)
    quantity = Column(Integer, default=0)

    order_status = Column(String(30), default='발주대기')  # 발주대기/발주완료/입고완료
    order_date = Column(Date, nullable=True)
    expected_in_date = Column(Date, nullable=True)
    in_confirmed = Column(Boolean, default=False)
    in_confirmed_at = Column(DateTime, nullable=True)

    is_outsourcing = Column(Boolean, default=False)
    outsourcing_status = Column(String(30), nullable=True)  # 외주입고대기/외주입고/가공중/본사입고완료

    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=True)      # 발주서 연결
    po_item_id = Column(Integer, ForeignKey('purchase_order_items.id'), nullable=True)
    bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)

    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    project = relationship("Project", foreign_keys=[project_id])
    contract = relationship("Contract", foreign_keys=[contract_id])
    contract_item = relationship("ContractItem", back_populates="material_orders")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])
    bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
