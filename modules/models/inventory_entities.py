import datetime

from sqlalchemy import (
    Boolean,
    Column,
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

MOVEMENT_TYPES = [
    'IN_RECEIVING',         # 입고
    'IN_ADJUST',            # 수동 조정 (증가)
    'OUT_ADJUST',           # 수동 조정 (감소)
    'OUT_RESERVE',          # 예약 (출고 예정)
    'IN_CANCEL_RESERVE',    # 예약 취소 (복원)
    'AUDIT_ADJUST',         # 실사 조정
]

MOVEMENT_TYPE_LABELS = {
    'IN_RECEIVING': '입고',
    'IN_ADJUST': '수동조정(+)',
    'OUT_ADJUST': '수동조정(-)',
    'OUT_RESERVE': '예약',
    'IN_CANCEL_RESERVE': '예약취소',
    'AUDIT_ADJUST': '실사조정',
}


class Item(Base):
    """품목 마스터 (iCUBE SITEM 마이그레이션)"""
    __tablename__ = 'items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    icube_item_cd = Column(String(30), unique=True, nullable=True)  # iCUBE 품목코드 (품번)
    item_name = Column(String(300), nullable=False)                 # 품명
    item_spec = Column(String(500), nullable=True)                  # 규격
    unit = Column(String(50), nullable=True)                        # 단위
    category = Column(String(50), nullable=True)                    # 분류 (드라이버, 하우징, LED모듈 등)
    manufacturer = Column(String(100), nullable=True)               # 제조사/납품업체
    note = Column(Text, nullable=True)                              # 비고
    is_active = Column(Boolean, default=True)
    stock_qty = Column(Float, default=0)                              # 실재고 수량
    reserved_qty = Column(Float, default=0)                           # 예약수량 (현장별)
    safety_stock = Column(Float, default=0)                            # 안전재고 기준
    last_unit_price = Column(Float, default=0)                         # 최근 입고단가 (캐시)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class BomHeader(Base):
    """BOM 마스터 (완제품별)"""
    __tablename__ = 'bom_headers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String(50), unique=True, nullable=False)
    product_name = Column(String(200), nullable=False)
    product_category = Column(String(50), nullable=True)     # 제품군 (실내등, 투광등 등)
    certification_no = Column(String(50), nullable=True)     # 인증번호
    version = Column(String(20), default='1.0')
    is_active = Column(Boolean, default=True)
    option_schema = Column(Text, nullable=True)            # JSON: 옵션 종류/값 정의 (슈퍼BOM)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    bom_items = relationship("BomItem", back_populates="bom_header", cascade="all, delete-orphan", order_by="BomItem.id")


class BomItem(Base):
    """BOM 소요 부품"""
    __tablename__ = 'bom_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    bom_id = Column(Integer, ForeignKey('bom_headers.id'), nullable=False)
    item_code = Column(String(100), nullable=True)            # 품번 (items.icube_item_cd 매칭)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=True)  # items FK
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    quantity = Column(Float, default=1)       # 1개 완제품당 소요량
    unit_price = Column(Float, nullable=True)                 # 현재 단가
    prev_unit_price = Column(Float, nullable=True)            # 직전 단가
    amount = Column(Float, nullable=True)                     # 금액
    supplier = Column(String(200), nullable=True)             # 납품업체
    unit = Column(String(50), nullable=True)
    option_filter = Column(Text, nullable=True)             # JSON: 옵션조건 (null=공통, {"lens_angle":"20도"}=옵션부품)
    note = Column(Text, nullable=True)

    bom_header = relationship("BomHeader", back_populates="bom_items")
    item = relationship("Item", foreign_keys=[item_id])


class StockAudit(Base):
    """재고실사 회차"""
    __tablename__ = 'stock_audits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_no = Column(String(20), unique=True, nullable=False)       # SA2026-001
    audit_date = Column(DateTime, nullable=False)
    auditor_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    auditor_name = Column(String(50), nullable=False)
    status = Column(String(20), default='진행중')  # 진행중/완료/취소
    note = Column(Text, nullable=True)
    total_items = Column(Integer, default=0)
    diff_items = Column(Integer, default=0)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    audit_items = relationship("StockAuditItem", back_populates="audit", cascade="all, delete-orphan")


class StockAuditItem(Base):
    """실사 품목 상세"""
    __tablename__ = 'stock_audit_items'
    __table_args__ = (
        UniqueConstraint('audit_id', 'item_id', name='uq_audit_item'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(Integer, ForeignKey('stock_audits.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=False)
    system_qty = Column(Float, default=0)
    actual_qty = Column(Float, nullable=True)
    diff_qty = Column(Float, default=0)
    diff_reason = Column(Text, nullable=True)
    is_adjusted = Column(Boolean, default=False)
    adjusted_at = Column(DateTime, nullable=True)

    audit = relationship("StockAudit", back_populates="audit_items")
    item = relationship("Item")


class StockMovement(Base):
    """재고 변동 이력"""
    __tablename__ = 'stock_movements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=False)
    movement_type = Column(String(20), nullable=False)
    quantity = Column(Float, nullable=False)
    before_qty = Column(Float, default=0)
    after_qty = Column(Float, default=0)
    unit_price = Column(Float, nullable=True)
    reference_type = Column(String(30), nullable=True)
    reference_id = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String(50), default='시스템')
    created_at = Column(DateTime, default=datetime.datetime.now)

    item = relationship("Item")
