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
    g2b_contract_no = Column(String(30), nullable=True)  # G2B 계약납품요구번호 (매칭 연동)

    # 대금 관련 필드 (매그나텍 PHASE 8)
    payment_status = Column(String(20), default='미청구')       # 미청구/청구완료/입금완료
    invoice_date = Column(Date, nullable=True)                   # 세금계산서 발행일
    payment_date = Column(Date, nullable=True)                   # 대금 입금확인일

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

    # 검수 관련 필드 (매그나텍 PHASE 7)
    inspection_status = Column(String(20), default='미검수')    # 미검수/합격/불합격/보완
    inspection_date = Column(Date, nullable=True)                # 검수일
    inspection_note = Column(Text, nullable=True)                # 검수 비고

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

    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=True)      # 발주서 연결
    po_item_id = Column(Integer, ForeignKey('purchase_order_items.id'), nullable=True)
    bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)

    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    contract_item = relationship("ContractItem", back_populates="material_orders")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])
    bom_item = relationship("BomItem", foreign_keys=[bom_item_id])


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
# 🔔 알림 (Notification)
# -------------------------------------------------------------------
class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    noti_type = Column(String(30), nullable=False, default='system')
    link = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship("User")

# -------------------------------------------------------------------
# 🔧 하자보증/AS (Warranty)
# -------------------------------------------------------------------
DEFECT_TYPES = [
    ('LED_MODULE', 'LED 모듈 불량'),
    ('SMPS', 'SMPS 고장'),
    ('HEAT', '방열 이상'),
    ('LENS', '렌즈/리플렉터 손상'),
    ('MOISTURE', '결로/침수'),
    ('CONTROL', '제어 불량'),
    ('OTHER', '기타'),
]

CASE_STATUS_STEPS = ['접수', '현장확인', '수리중', '완료', '보류']


class Warranty(Base):
    __tablename__ = 'warranties'
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    warranty_start = Column(Date, nullable=True)
    warranty_end = Column(Date, nullable=True)
    warranty_amount = Column(Integer, default=0)
    insurance_no = Column(String(100), nullable=True)
    insurance_returned = Column(Boolean, default=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    contract = relationship("Contract", backref="warranty")
    project = relationship("Project")
    cases = relationship("WarrantyCase", back_populates="warranty", cascade="all, delete-orphan")


class WarrantyCase(Base):
    __tablename__ = 'warranty_cases'
    id = Column(Integer, primary_key=True, autoincrement=True)
    warranty_id = Column(Integer, ForeignKey('warranties.id'), nullable=True)   # nullable: 수기입력 시 보증 없이 접수
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)      # nullable: 수기입력 시 프로젝트 없을 수 있음
    case_no = Column(String(50), nullable=False)
    defect_type = Column(String(30), nullable=False)
    symptom = Column(Text, nullable=True)
    status = Column(String(20), default='접수')
    reported_by = Column(String(100), nullable=True)
    reported_date = Column(Date, nullable=True)
    site_visit_date = Column(Date, nullable=True)
    completed_date = Column(Date, nullable=True)
    cause_analysis = Column(Text, nullable=True)
    action_taken = Column(Text, nullable=True)
    replaced_parts = Column(String(500), nullable=True)
    assigned_to = Column(String(100), nullable=True)
    created_by = Column(String(50), default='사용자')
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    # 수기입력 전용 필드 (보증 연결 없이 접수할 때 사용)
    manual_site_name = Column(String(200), nullable=True)      # 현장명 수기
    manual_contract_name = Column(String(200), nullable=True)   # 계약명 수기
    manual_model_name = Column(String(200), nullable=True)      # 모델명 수기
    manual_delivery_date = Column(Date, nullable=True)          # 납품일 수기

    warranty = relationship("Warranty", back_populates="cases")
    project = relationship("Project")
    logs = relationship("WarrantyCaseLog", back_populates="case", cascade="all, delete-orphan")


class WarrantyCaseLog(Base):
    __tablename__ = 'warranty_case_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('warranty_cases.id'), nullable=False)
    log_type = Column(String(20), default='status_change')
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    content = Column(Text, nullable=True)
    created_by = Column(String(50), default='사용자')
    created_at = Column(DateTime, default=datetime.datetime.now)

    case = relationship("WarrantyCase", back_populates="logs")


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
    position = Column(String(50), nullable=True)          # 직급 (부장, 과장 등)
    email = Column(String(200), nullable=True)            # 이메일
    office_tel = Column(String(30), nullable=True)        # 사무실 전화
    office_fax = Column(String(30), nullable=True)        # 팩스
    user_group = Column(String(50), ForeignKey('group_permissions.group_name'))
    role = Column(String(20), default="user")
    extra_menus = Column(Text, nullable=True)           # 개인 추가 메뉴 권한 (CSV: "item,vendor")
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


# -------------------------------------------------------------------
# 10. 제품 카탈로그 (나라장터 G2B 연동)
# -------------------------------------------------------------------
class ProductCatalog(Base):
    __tablename__ = 'product_catalog'

    id = Column(Integer, primary_key=True, autoincrement=True)
    prdct_idnt_no = Column(String(30), unique=True, nullable=False)   # 물품식별번호
    krn_prdct_nm = Column(String(300), nullable=False)                # 원본 품명 (API 전체 문자열)
    item_name = Column(String(200), nullable=True)                    # 품목명 (LED투광등기구)
    manufacturer = Column(String(100), nullable=True)                 # 제조사 (매그나텍)
    model_name = Column(String(200), nullable=True)                   # 모델명 (ARENA-200S)
    spec = Column(String(300), nullable=True)                         # 규격 (200W, 5m 등)
    prdct_clsfc_no = Column(String(30), nullable=True)                # 물품분류번호
    dtl_prdct_nm = Column(String(500), nullable=True)                 # 상세품명
    unit = Column(String(20), nullable=True)                          # 단위
    unit_price = Column(Integer, nullable=True)                       # 계약단가 (원)
    price_source = Column(String(10), nullable=False, default='api')  # api / manual / quote
    g2b_contract_method = Column(String(20), nullable=True)           # MAS / 제3자단가 / 수기등록 / 견적
    g2b_cntrct_no = Column(String(50), nullable=True)                 # 계약번호
    cntrct_bgn_date = Column(Date, nullable=True)                     # 계약시작일
    cntrct_end_date = Column(Date, nullable=True)                     # 계약종료일
    last_synced_at = Column(DateTime, nullable=True)                  # 마지막 동기화 시각
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


# -------------------------------------------------------------------
# 10-1. 조달내역 (나라장터 특정물품조달내역 API 연동)
# -------------------------------------------------------------------
class G2bProcurement(Base):
    __tablename__ = 'g2b_procurements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 계약납품요구번호 + 품목순번 = 유니크키
    cntrct_dlvr_req_no = Column(String(30), nullable=False)       # 계약납품요구번호
    prdct_sno = Column(String(10), nullable=False, default='1')   # 품목순번
    cntrct_dlvr_req_chg_ord = Column(String(5), nullable=True)    # 변경차수

    # 계약 기본정보
    prcrmnt_div_nm = Column(String(50), nullable=True)            # 조달구분명 (중앙조달/자체조달)
    cntrct_div_nm = Column(String(50), nullable=True)             # 계약구분명 (총액계약/제3자단가 등)
    cntrct_dlvr_div_nm = Column(String(50), nullable=True)        # 계약납품구분명
    cntrct_dlvr_req_date = Column(Date, nullable=True)            # 계약납품요구일자
    cntrct_dlvr_req_nm = Column(String(200), nullable=True)       # 계약명 (공사명)
    cntrct_mthd_nm = Column(String(100), nullable=True)           # 계약체결방법명

    # 수요기관
    dminstt_nm = Column(String(200), nullable=True)               # 수요기관명
    dminstt_cd = Column(String(20), nullable=True)                # 수요기관코드
    dminstt_rgn_nm = Column(String(100), nullable=True)           # 수요기관지역명
    dmnd_instt_div_nm = Column(String(100), nullable=True)        # 수요기관구분명

    # 물품정보
    prdct_clsfc_no = Column(String(20), nullable=True)            # 물품분류번호 (8자리)
    prdct_clsfc_no_nm = Column(String(200), nullable=True)        # 품명
    dtil_prdct_clsfc_no = Column(String(20), nullable=True)       # 세부물품분류번호 (10자리)
    dtil_prdct_clsfc_no_nm = Column(String(200), nullable=True)   # 세부품명
    prdct_idnt_no = Column(String(20), nullable=True)             # 물품식별번호
    prdct_idnt_no_nm = Column(String(300), nullable=True)         # 물품규격명

    # 금액/수량
    prdct_uprc = Column(Integer, nullable=True)                   # 단가
    prdct_qty = Column(Integer, nullable=True)                    # 수량
    prdct_unit = Column(String(20), nullable=True)                # 단위
    prdct_amt = Column(Integer, nullable=True)                    # 금액

    # 업체정보
    corp_nm = Column(String(100), nullable=True)                  # 업체명
    bizno = Column(String(20), nullable=True)                     # 사업자등록번호

    # 납품정보
    dlvr_plce_nm = Column(String(300), nullable=True)             # 납품장소
    dlvr_tmlmt_date = Column(Date, nullable=True)                 # 납품기한일자
    dlvry_cndtn_nm = Column(String(200), nullable=True)           # 인도조건명

    # 기타
    fnl_cntrct_dlvr_req_chg_ord_yn = Column(String(5), nullable=True)  # 최종변경차수여부
    mas_yn = Column(String(5), nullable=True)                     # 다수공급자계약여부
    uprc_cntrct_no = Column(String(30), nullable=True)            # 단가계약번호
    intl_cntrct_dlvr_req_date = Column(Date, nullable=True)       # 최초계약납품요구일자
    exclc_prodct_yn = Column(String(5), nullable=True)            # 우수제품여부

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (
        UniqueConstraint('cntrct_dlvr_req_no', 'prdct_sno', 'cntrct_dlvr_req_chg_ord',
                         name='uq_g2b_proc_req_sno_chg'),
    )


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


# -------------------------------------------------------------------
# 12. 일일업무보고
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# 11. 구매관리 - 거래처/품목/발주서/이력 (iCUBE 마이그레이션 + 자체 관리)
# -------------------------------------------------------------------
PO_STATUS_CHOICES = ['작성중', '발송완료', '입고대기', '입고완료', '취소']


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


class EmailSignature(Base):
    """사용자별 이메일 서명"""
    __tablename__ = 'email_signatures'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    department = Column(String(50), nullable=True)     # 경영관리부
    position = Column(String(50), nullable=True)       # 부장
    display_name = Column(String(50), nullable=True)   # 이지훈
    email = Column(String(200), nullable=True)         # purchase@mgnt.kr
    mobile = Column(String(30), nullable=True)         # 010-5465-5621
    office_tel = Column(String(30), nullable=True)     # 061-392-5508
    fax = Column(String(30), nullable=True)            # 061-392-5518
    is_default = Column(Boolean, default=False)        # 기본 서명 여부
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    user = relationship("User")

    def to_text(self):
        """서명 텍스트 생성"""
        lines = ['=' * 65]
        title = '(주)매그나텍'
        if self.department:
            title += f' {self.department}'
        if self.display_name:
            title += f' {self.display_name}'
        if self.position:
            title += f' {self.position}'
        lines.append(title)
        if self.email:
            lines.append(f'E-mail : {self.email}')
        if self.mobile:
            lines.append(f'Mobile : {self.mobile}')
        if self.office_tel:
            lines.append(f'Office : {self.office_tel}')
        if self.fax:
            lines.append(f'Fax    : {self.fax}')
        lines.append('홈페이지 : https://www.magnatech.co.kr')
        lines.append('=' * 65)
        return '\n'.join(lines)


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


class DailyReport(Base):
    __tablename__ = 'daily_reports'
    __table_args__ = (
        UniqueConstraint('report_date', 'department', name='uq_daily_report_date_dept'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(Date, nullable=False)                    # 보고 날짜
    department = Column(String(50), nullable=False)               # 부서명 (user_group)
    reporter_name = Column(String(50), nullable=False)            # 보고자 이름
    reporter_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # 기본사항
    headcount_total = Column(Integer, default=0)                  # 총 인원
    headcount_present = Column(Integer, default=0)                # 재실 인원
    headcount_absence_info = Column(String(200), nullable=True)   # 부재 사유 (예: "반차 1명", "연차 1명")

    # 업무 항목 (JSON 배열: ["항목1", "항목2", ...])
    items_json = Column(Text, nullable=False, default='[]')

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def items(self):
        try:
            return json.loads(self.items_json or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    @items.setter
    def items(self, value):
        self.items_json = json.dumps(value, ensure_ascii=False)


# -------------------------------------------------------------------
# 13. 입고관리 (Phase 3)
# -------------------------------------------------------------------
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

    vendor = relationship("Vendor")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])
    contract = relationship("Contract", foreign_keys=[contract_id])
    creator = relationship("User", foreign_keys=[created_by])
    items = relationship("ReceivingItem", back_populates="receiving", cascade="all, delete-orphan", order_by="ReceivingItem.id")


class ReceivingItem(Base):
    """입고 품목 상세"""
    __tablename__ = 'receiving_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiving_id = Column(Integer, ForeignKey('receivings.id'), nullable=False)
    po_item_id = Column(Integer, ForeignKey('purchase_order_items.id'), nullable=True)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    received_qty = Column(Float, default=0)
    unit = Column(String(50), nullable=True)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    note = Column(Text, nullable=True)

    receiving = relationship("Receiving", back_populates="items")
    po_item = relationship("PurchaseOrderItem", foreign_keys=[po_item_id])


# -------------------------------------------------------------------
# 14. BOM 관리 (Phase 4)
# -------------------------------------------------------------------
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
    note = Column(Text, nullable=True)

    bom_header = relationship("BomHeader", back_populates="bom_items")
    item = relationship("Item", foreign_keys=[item_id])


# -------------------------------------------------------------------
# 15. 매출 세금계산서 + 수금관리
# -------------------------------------------------------------------
PAYMENT_STATUS_CHOICES = ['미수금', '부분입금', '입금완료']
MATCH_STATUS_CHOICES = ['자동매칭', '수동매칭', '미매칭']
PAYMENT_METHOD_CHOICES = ['계좌이체', '카드', '어음', '기타']


class TaxInvoice(Base):
    """국세청 매출전자세금계산서"""
    __tablename__ = 'tax_invoices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    approval_no = Column(String(50), unique=True, nullable=False)   # 국세청 승인번호
    issue_date = Column(Date, nullable=True)                         # 작성일자
    send_date = Column(Date, nullable=True)                          # 전송일자
    invoice_type = Column(String(20), default='세금계산서')           # 세금계산서/수정세금계산서

    # 공급자
    supplier_business_no = Column(String(20), nullable=True)         # 공급자 사업자번호
    supplier_name = Column(String(200), nullable=True)               # 공급자 상호

    # 공급받는자
    buyer_business_no = Column(String(20), nullable=True)            # 공급받는자 사업자번호
    buyer_name = Column(String(200), nullable=True)                  # 공급받는자 상호
    buyer_ceo = Column(String(100), nullable=True)                   # 공급받는자 대표자명

    # 금액
    total_amount = Column(Integer, default=0)                         # 합계금액
    supply_amount = Column(Integer, default=0)                        # 공급가액
    tax_amount = Column(Integer, default=0)                           # 세액

    # 품목 정보
    item_date = Column(Date, nullable=True)                           # 품목 작성일
    item_name = Column(String(200), nullable=True)                    # 품목명
    item_spec = Column(String(200), nullable=True)                    # 품목규격
    item_qty = Column(Integer, default=0)                             # 품목수량
    item_unit_price = Column(Integer, default=0)                      # 품목단가

    # 비고 + G2B 파싱
    remark = Column(Text, nullable=True)                              # 비고 원문
    g2b_contract_no = Column(String(30), nullable=True)               # R##TB
    g2b_contract_name = Column(String(300), nullable=True)            # 비고에서 파싱한 계약명
    g2b_delivery_req_no = Column(String(30), nullable=True)           # R##JG
    g2b_delivery_no = Column(String(30), nullable=True)               # R##NS

    # 매칭
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    match_status = Column(String(20), default='미매칭')               # 자동매칭/수동매칭/미매칭

    # 수금
    payment_status = Column(String(20), default='미수금')             # 미수금/부분입금/입금완료
    paid_amount = Column(Integer, default=0)                          # 입금 누계액

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    contract = relationship("Contract", foreign_keys=[contract_id])
    project = relationship("Project", foreign_keys=[project_id])
    payment_records = relationship("PaymentRecord", back_populates="tax_invoice", cascade="all, delete-orphan", order_by="PaymentRecord.payment_date.desc()")


# -------------------------------------------------------------------
# 16. 재고관리 (Inventory Management)
# -------------------------------------------------------------------
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


class StockAudit(Base):
    """재고실사 회차"""
    __tablename__ = 'stock_audits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_no = Column(String(20), unique=True, nullable=False)       # SA2026-001
    audit_date = Column(Date, nullable=False)
    auditor_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    auditor_name = Column(String(50), nullable=False)
    status = Column(String(20), default='진행중')  # 진행중/완료/취소
    note = Column(Text, nullable=True)
    total_items = Column(Integer, default=0)
    diff_items = Column(Integer, default=0)
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


class PaymentRecord(Base):
    """수금 기록"""
    __tablename__ = 'payment_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tax_invoice_id = Column(Integer, ForeignKey('tax_invoices.id'), nullable=False)
    payment_date = Column(Date, nullable=False)                       # 입금일
    amount = Column(Integer, default=0)                               # 입금액
    payment_method = Column(String(30), default='계좌이체')           # 계좌이체/카드/어음/기타
    note = Column(Text, nullable=True)                                # 비고
    created_by = Column(String(50), default='사용자')                 # 등록자
    created_at = Column(DateTime, default=datetime.datetime.now)

    tax_invoice = relationship("TaxInvoice", back_populates="payment_records")
