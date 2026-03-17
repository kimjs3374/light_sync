import datetime
import json
import secrets

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
from .constants import DETAIL_ITEM_OPTIONS

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

# -------------------------------------------------------------------
# 💡 2. [신규] 계약 정보 (Contracts) - 한 현장당 1~9건
# -------------------------------------------------------------------
class Contract(Base):
    __tablename__ = 'contracts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    
    contract_name = Column(String(200), nullable=False) # 계약명
    item_group = Column(String(50), default=DETAIL_ITEM_OPTIONS[0])     # 계약 상세품목(단일 규칙)
    contract_date = Column(Date)                       # 계약일
    delivery_due_date = Column(Date)                   # 납품기일 (D-Day 계산용)
    desired_delivery_date = Column(Date)               # 납품희망일
    
    is_prof_inspection = Column(Boolean, default=False) # 전문기관검수여부 (💡 체크 시 파란 음영)
    is_urgent_prod = Column(Boolean, default=False)     # 긴급제작건 여부 (💡 체크 시 빨간 음영)
    
    project = relationship("Project", back_populates="contracts")
    # 💡 계약별 품목 (1계약 : N품목)
    items = relationship("ContractItem", back_populates="contract", cascade="all, delete-orphan")
    deliveries = relationship("Delivery", back_populates="contract")


class Delivery(Base):
    __tablename__ = 'deliveries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)

    delivery_status = Column(String(30), default='납품대기')

    planned_total_qty = Column(Integer, default=0)
    delivered_total_qty = Column(Integer, default=0)

    contact_name = Column(String(100), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    note = Column(Text, nullable=True)

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

    split_no = Column(Integer, default=1)
    quantity = Column(Integer, default=0)
    scheduled_date = Column(Date, nullable=True)
    confirmed_date = Column(Date, nullable=True)
    loading_done_at = Column(DateTime, nullable=True)
    delivered_done_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='예정')
    note = Column(Text, nullable=True)

    delivery = relationship("Delivery", back_populates="splits")


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

# -------------------------------------------------------------------
# 💡 3. [신규] 계약별 상세 품목 (ContractItems)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# 💡 4. 담당자 연락처 (Contacts)
# -------------------------------------------------------------------
class Contact(Base):
    __tablename__ = 'contacts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    
    name = Column(String(50), nullable=False)    # 이름
    phone = Column(String(50))                   # 연락처
    email = Column(String(100))                  # 이메일
    category = Column(String(50))                # 구분 (감독관, 업체, 감리, 배송 등)
    
    project = relationship("Project", back_populates="contacts")

# -------------------------------------------------------------------
# 5. 설계 단계 자재/품목 (Materials) - 영업관리에서 사용
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# 5-1. 자재관리 (계약 품목 하위 자재)
# -------------------------------------------------------------------
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

    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    contract_item = relationship("ContractItem", back_populates="material_orders")


# -------------------------------------------------------------------
# 5-2. 생산관리 (계약 품목 하위 공정)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# 6. 스포츠 조도 계산 모듈 (Sports Lux)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# 7. 업무 히스토리 로그 (Feed)
# -------------------------------------------------------------------
class HistoryLog(Base):
    __tablename__ = 'history_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    
    user_name = Column(String(50), default="사용자")
    content = Column(Text, nullable=False)
    log_scope = Column(String(20), default='common')      # design/contract/sales/drawing/technical/common
    log_kind = Column(String(20), default='system')       # system/comment/reply
    parent_log_id = Column(Integer, ForeignKey('history_logs.id'), nullable=True)
    root_log_id = Column(Integer, ForeignKey('history_logs.id'), nullable=True)
    origin_snapshot = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now) 
    
    project = relationship("Project", back_populates="history_logs")
    parent = relationship("HistoryLog", remote_side=[id], foreign_keys=[parent_log_id], backref="replies")


# -------------------------------------------------------------------
# 7-1. 대시보드 전광판 공지 (관리자 직접 관리)
# -------------------------------------------------------------------
class DashboardNotice(Base):
    __tablename__ = 'dashboard_notices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False, default='공지')
    message = Column(Text, nullable=False)
    level = Column(String(20), nullable=False, default='info')  # info / warning / danger
    sort_order = Column(Integer, default=100)
    display_seconds = Column(Integer, default=6)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class DashboardSetting(Base):
    __tablename__ = 'dashboard_settings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    setting_key = Column(String(100), unique=True, nullable=False)
    setting_value = Column(String(200), nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

# -------------------------------------------------------------------
# 8. 도면 관리 (DWG/PDF)
# -------------------------------------------------------------------
DRAWING_TYPE_OPTIONS = ["제작도면", "발주도면"]
DRAWING_CONVERT_STATUS = ["UPLOADED", "PROCESSING", "SUCCESS", "FAILED"]


class Drawing(Base):
    __tablename__ = 'drawings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_item_id = Column(Integer, ForeignKey('contract_items.id'), nullable=True)
    title = Column(String(200), nullable=False)
    drawing_type = Column(String(20), nullable=False, default='제작도면')
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    project = relationship("Project", back_populates="drawings")
    contract_item = relationship("ContractItem", back_populates="drawings")
    versions = relationship("DrawingVersion", back_populates="drawing", cascade="all, delete-orphan", order_by="DrawingVersion.version_no.desc()")


class DrawingVersion(Base):
    __tablename__ = 'drawing_versions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    drawing_id = Column(Integer, ForeignKey('drawings.id'), nullable=False)
    version_no = Column(Integer, nullable=False, default=1)
    dwg_path = Column(String(500), nullable=False)
    pdf_path = Column(String(500), nullable=True)
    convert_status = Column(String(20), nullable=False, default='UPLOADED')
    convert_message = Column(Text, nullable=True)
    converted_at = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    is_latest = Column(Boolean, default=True)

    drawing = relationship("Drawing", back_populates="versions")
    share_links = relationship("DrawingShareLink", back_populates="drawing_version", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('drawing_id', 'version_no', name='uq_drawing_version_no'),
    )


class DrawingShareLink(Base):
    __tablename__ = 'drawing_share_links'
    id = Column(Integer, primary_key=True, autoincrement=True)
    drawing_version_id = Column(Integer, ForeignKey('drawing_versions.id'), nullable=False)
    token = Column(String(120), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    expires_at = Column(DateTime, nullable=False)
    allow_download = Column(Boolean, default=True)
    password_hash = Column(String(200), nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    drawing_version = relationship("DrawingVersion", back_populates="share_links")
    access_logs = relationship("DrawingAccessLog", back_populates="share_link", cascade="all, delete-orphan")


class DrawingAccessLog(Base):
    __tablename__ = 'drawing_access_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    share_link_id = Column(Integer, ForeignKey('drawing_share_links.id'), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    access_type = Column(String(20), nullable=False, default='VIEW')
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    share_link = relationship("DrawingShareLink", back_populates="access_logs")

# -------------------------------------------------------------------
# 👑 9. 시스템 권한 및 계정 (Auth)
# -------------------------------------------------------------------
class GroupPermission(Base):
    __tablename__ = 'group_permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(50), unique=True, nullable=False)
    allowed_menus = Column(Text, nullable=False)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(50), nullable=False)
    phone_number = Column(String(20), nullable=False)
    user_group = Column(String(50), ForeignKey('group_permissions.group_name'))
    role = Column(String(20), default="user") 
    can_approve_delete = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    priority_permission = relationship(
        "UserPriorityPermission",
        foreign_keys="UserPriorityPermission.user_id",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )


class UserPriorityPermission(Base):
    __tablename__ = 'user_priority_permissions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    granted_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    granted_by_name = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    user = relationship("User", foreign_keys=[user_id], back_populates="priority_permission")


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
