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
)
from sqlalchemy.orm import relationship

from .base import Base


class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_no = Column(String(50), unique=True, nullable=False) # 관리번호

    temp_name = Column(String(100), nullable=False) # 현장 가칭
    short_name = Column(String(50))                 # 약칭

    # 💡 주소 관리 강화 (현장 vs 납품주소)
    site_address = Column(String(500))      # 현장 주소
    shipping_address = Column(String(500))  # 실제 납품 주소
    is_shipping_same = Column(Boolean, default=True) # 현장주소와 동일 체크박스용

    site_memo = Column(Text) # 현장 특이사항 및 메모

    # 💡 [추가] 작업 경로 및 설계기준 저장용
    work_path = Column(String(500))
    design_basis = Column(Text)

    status = Column(String(50), default="설계/영업")
    is_urgent = Column(Boolean, default=False) # 긴급 현장 여부

    # 설계 시방서 반영 확인 (매그나텍 PHASE 2-3)
    spec_confirmed = Column(Boolean, default=False)              # 시방서 반영 확인 여부
    spec_confirmed_date = Column(Date, nullable=True)            # 시방서 반영 확인일

    is_contracted = Column(Boolean, default=False) # 계약 체결 여부
    contract_date = Column(Date, nullable=True) # 설계에서 넘어올 때의 기준일
    expected_contract_date = Column(Date, nullable=True) # 계약 예정일
    created_at = Column(DateTime, default=datetime.datetime.now) # 생성일

    # 관계 설정
    # 설계 단계 자재
    materials = relationship("Material", back_populates="project", cascade="all, delete-orphan")
    # 💡 [신규] 계약 정보 (1현장 : N계약)
    contracts = relationship("Contract", back_populates="project", cascade="all, delete-orphan")

    sports_modules = relationship("SportsModule", back_populates="project", cascade="all, delete-orphan")
    history_logs = relationship("HistoryLog", back_populates="project", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="project", cascade="all, delete-orphan")
    drawings = relationship("Drawing", back_populates="project", cascade="all, delete-orphan")
    deliveries = relationship("Delivery", back_populates="project", cascade="all, delete-orphan")
    priority_override = relationship("ProjectPriorityOverride", back_populates="project", uselist=False, cascade="all, delete-orphan")
    project_photos = relationship("ProjectPhoto", back_populates="project", cascade="all, delete-orphan")


class ProjectPriorityOverride(Base):
    __tablename__ = 'project_priority_overrides'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    note = Column(Text, nullable=True)
    set_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    set_by_name = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    project = relationship("Project", back_populates="priority_override")


class ProjectDeleteRequest(Base):
    __tablename__ = 'project_delete_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, nullable=False)
    project_no_snapshot = Column(String(50), nullable=True)
    project_name_snapshot = Column(String(200), nullable=True)

    requester_id = Column(Integer, nullable=False)
    requester_name = Column(String(50), nullable=False)
    requester_group = Column(String(50), nullable=True)
    request_reason = Column(Text, nullable=False)

    status = Column(String(20), default='PENDING')  # PENDING/APPROVED/REJECTED/CANCELED
    approved_by_user_id = Column(Integer, nullable=True)
    approved_by_name = Column(String(50), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    reject_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class ProjectPhoto(Base):
    __tablename__ = 'project_photos'

    id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id  = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    photo_type  = Column(String(30), default='설계')   # 설계/명함/생산/상차/하차/설치
    file_name   = Column(String(255), nullable=False)
    storage_path= Column(String(500), nullable=False)
    uploaded_by = Column(String(50),  default='사용자')
    created_at  = Column(DateTime,    default=datetime.datetime.now)

    project  = relationship("Project",  back_populates="project_photos")
    contract = relationship("Contract", back_populates="project_photos")


class Contact(Base):
    __tablename__ = 'contacts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)

    name = Column(String(50), nullable=False)    # 이름
    phone = Column(String(50))                   # 연락처
    email = Column(String(100))                  # 이메일
    category = Column(String(50))                # 구분 (감독관, 업체, 감리, 배송 등)

    project = relationship("Project", back_populates="contacts")


class SportsModule(Base):
    __tablename__ = 'sports_modules'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)

    grid_layout = Column(String(50))
    design_lux = Column(Float, default=0.0)
    measured_lux_data = Column(Text)

    avg_lux = Column(Float, default=0.0)
    u1_uniformity = Column(Float, default=0.0)

    project = relationship("Project", back_populates="sports_modules")
