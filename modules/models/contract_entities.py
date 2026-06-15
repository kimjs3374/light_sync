import datetime
import json

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base
from .constants import DETAIL_ITEM_OPTIONS


class Contract(Base):
    __tablename__ = 'contracts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)  # G2B 동기화 시 프로젝트 미연결 가능

    contract_name = Column(String(200), nullable=False) # 계약명
    item_group = Column(String(50), default=DETAIL_ITEM_OPTIONS[0])     # 계약 상세품목(단일 규칙)
    contract_date = Column(Date)                       # 계약일
    delivery_due_date = Column(Date)                   # 납품기일 (D-Day 계산용)
    desired_delivery_date = Column(Date)               # 납품희망일

    is_prof_inspection = Column(Boolean, default=False) # 전문기관검수여부 (💡 체크 시 파란 음영)
    is_urgent_prod = Column(Boolean, default=False)     # 긴급제작건 여부 (💡 체크 시 빨간 음영)
    g2b_contract_no = Column(String(30), nullable=True)  # G2B 계약납품요구번호 (매칭 연동)
    g2b_change_ord = Column(String(5), default='00')     # G2B 변경차수 (00=원계약, 01~=변경)

    # 대금 관련 필드 (매그나텍 PHASE 8)
    payment_status = Column(String(20), default='미청구')       # 미청구/부분입금/입금완료/변경완료/취소
    invoice_date = Column(Date, nullable=True)                   # 세금계산서 발행일
    payment_date = Column(Date, nullable=True)                   # 대금 입금확인일
    is_excluded = Column(Boolean, default=False)                 # 예외처리 여부 (관리화면 숨김)
    exclude_reason = Column(String(50), nullable=True)           # 예외 사유
    exclude_note = Column(String(200), nullable=True)            # 예외 메모

    # 미청구 사유 분류 (회수불가/탕감/분쟁/단순지연/기타 — 알림 라우팅 기준)
    unpaid_reason = Column(String(50), nullable=True)
    unpaid_reason_note = Column(Text, nullable=True)

    project = relationship("Project", back_populates="contracts")
    # 💡 계약별 품목 (1계약 : N품목)
    items = relationship("ContractItem", back_populates="contract", cascade="all, delete-orphan")
    deliveries = relationship("Delivery", back_populates="contract")
    project_photos = relationship("ProjectPhoto", back_populates="contract")


class ContractItem(Base):
    __tablename__ = 'contract_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=False)

    category = Column(String(50), nullable=False) # 품목구분 (조명기구, 타워 등)
    model_name = Column(String(200))             # 모델명
    quantity = Column(Integer, default=0)         # 수량

    barcode_id = Column(String(100), nullable=True) # 바코드 (💡 조명기구만 입력)
    item_spec_json = Column(Text, nullable=True)     # 품목별 동적 스펙(JSON)

    # 부서별 진행 단계
    status_sales = Column(String(50), default="계약확인")
    status_admin = Column(String(50), default="자재확인중")
    status_prod = Column(String(50), default="자재대기중")

    contract = relationship("Contract", back_populates="items")
    barcodes = relationship("ContractBarcode", back_populates="contract_item", cascade="all, delete-orphan", order_by="ContractBarcode.seq")
    drawings = relationship("Drawing", back_populates="contract_item", cascade="all, delete-orphan")
    material_orders = relationship("MaterialOrder", back_populates="contract_item", cascade="all, delete-orphan")
    production_processes = relationship("ProductionProcess", back_populates="contract_item", cascade="all, delete-orphan", order_by="ProductionProcess.step_order")

    @property
    def item_spec(self):
        if not self.item_spec_json:
            return {}
        try:
            parsed = json.loads(self.item_spec_json)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @item_spec.setter
    def item_spec(self, value):
        value = value or {}
        self.item_spec_json = json.dumps(value, ensure_ascii=False)


class ContractBarcode(Base):
    __tablename__ = 'contract_barcodes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_item_id = Column(Integer, ForeignKey('contract_items.id'), nullable=False)
    barcode = Column(String(100), nullable=False)
    seq = Column(Integer, default=1)
    site_name = Column(String(200))
    model_name = Column(String(200))
    producer = Column(String(100))
    lens_angle = Column(String(100))
    pcb_spec = Column(String(200))
    pcb_cct = Column(String(100))
    pcb_chip_spec = Column(String(200))
    pcb_mfg_date = Column(String(100))
    smps_model = Column(String(200))
    smps_qty = Column(Integer, default=0)
    smps_setting = Column(String(200))
    smps_vdc = Column(String(100))
    smps_adc = Column(String(100))
    spacing_distance = Column(String(100))
    replaced_from_barcode = Column(String(100))
    replaced_reason = Column(String(200))
    created_at = Column(DateTime, default=datetime.datetime.now)
    created_by = Column(String(50), default='시스템')

    __table_args__ = (
        UniqueConstraint('contract_item_id', 'barcode', name='uq_contract_item_barcode'),
    )

    contract_item = relationship("ContractItem", back_populates="barcodes")
