import datetime
import json

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

# 하자보증/AS 관련 상수
DEFECT_TYPES = [
    ('LED_MODULE', 'LED 모듈 불량'),
    ('SMPS', 'SMPS 고장'),
    ('HEAT', '방열 이상'),
    ('LENS', '렌즈/리플렉터 손상'),
    ('MOISTURE', '결로/침수'),
    ('CONTROL', '제어 불량'),
    ('WIRING', '배선/커넥터 불량'),
    ('BODY', '등기구 외함 손상'),
    ('POLE', '등주/타워 손상'),
    ('PAINT', '도장 박리/부식'),
    ('ANCHOR', '앵커/기초 문제'),
    ('SENSOR', '센서 오동작'),
    ('OTHER', '기타'),
]

CASE_STATUS_STEPS = ['접수', '현장확인', '부품준비', '수리/교체', '완료', '보류']


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


class HistoryReadMark(Base):
    """사용자별 프로젝트 히스토리 마지막 읽은 시점"""
    __tablename__ = 'history_read_marks'
    __table_args__ = (UniqueConstraint('user_id', 'project_id', name='uq_history_read_user_project'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    last_read_at = Column(DateTime, nullable=False, default=datetime.datetime.now)


class ActivityLog(Base):
    """전사 통합 활동 로그 (실시간 타임라인용)"""
    __tablename__ = 'activity_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    module = Column(String(30), nullable=False)         # processing_order, purchase_order, material, production, inventory, etc.
    action = Column(String(30), nullable=False)         # create, update, delete, status_change, upload, email, confirm
    summary = Column(String(500), nullable=False)       # 한 줄 요약
    detail = Column(Text, nullable=True)                # 상세 내용 (JSON 등)
    ref_type = Column(String(30), nullable=True)        # 참조 엔티티 타입 (ProcessingOrder, PurchaseOrder, etc.)
    ref_id = Column(Integer, nullable=True)             # 참조 엔티티 ID
    ref_label = Column(String(100), nullable=True)      # 참조 라벨 (FO2026-001, PO2026-001 등)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    user_name = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


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
    setting_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


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
    # 자동수집 항목 (수정 가능, NULL이면 실시간 수집 사용)
    auto_items_json = Column(Text, nullable=True)

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

    @property
    def auto_items(self):
        if self.auto_items_json is None:
            return None  # None = 아직 저장 안 됨, 실시간 수집 사용
        try:
            return json.loads(self.auto_items_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @auto_items.setter
    def auto_items(self, value):
        self.auto_items_json = json.dumps(value, ensure_ascii=False) if value is not None else None


class Warranty(Base):
    __tablename__ = 'warranties'
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), unique=True, nullable=True)  # G2B 동기화 시 계약 없을 수 있음
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)  # G2B 동기화 시 프로젝트 미연결 가능
    warranty_start = Column(Date, nullable=True)
    warranty_end = Column(Date, nullable=True)
    warranty_amount = Column(Integer, default=0)
    warranty_type = Column(String(20), default='일반')          # 혁신제품/우수제품/일반
    auto_generated = Column(Boolean, default=False)
    insurance_no = Column(String(100), nullable=True)
    insurance_returned = Column(Boolean, default=False)
    note = Column(Text, nullable=True)
    contract_name = Column(String(200), nullable=True)
    item_group = Column(String(50), nullable=True)
    model_name = Column(String(200), nullable=True)
    quantity = Column(Integer, nullable=True)
    site_address = Column(String(500), nullable=True)
    customer_contact = Column(String(200), nullable=True)
    customer_phone = Column(String(50), nullable=True)
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

    # 유상/무상
    is_chargeable = Column(Boolean, default=False)
    charge_amount = Column(Integer, default=0)
    charge_status = Column(String(20), nullable=True)

    # 고객 정보
    request_channel = Column(String(30), nullable=True)
    customer_name = Column(String(100), nullable=True)
    customer_phone = Column(String(50), nullable=True)

    # 교체 부품
    parts_json = Column(Text, nullable=True)

    # 물류
    shipping_method = Column(String(30), nullable=True)
    shipping_tracking = Column(String(100), nullable=True)
    shipping_date = Column(Date, nullable=True)

    # 비정규화
    contract_name = Column(String(200), nullable=True)
    item_group = Column(String(50), nullable=True)
    model_name = Column(String(200), nullable=True)

    # 수기입력 전용 필드 (보증 연결 없이 접수할 때 사용)
    manual_site_name = Column(String(200), nullable=True)      # 현장명 수기
    manual_contract_name = Column(String(200), nullable=True)   # 계약명 수기
    manual_model_name = Column(String(200), nullable=True)      # 모델명 수기
    manual_delivery_date = Column(Date, nullable=True)          # 납품일 수기

    warranty = relationship("Warranty", back_populates="cases")
    project = relationship("Project")
    logs = relationship("WarrantyCaseLog", back_populates="case", cascade="all, delete-orphan")

    @property
    def parts(self):
        try:
            return json.loads(self.parts_json or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    @parts.setter
    def parts(self, value):
        self.parts_json = json.dumps(value, ensure_ascii=False)


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


class IlluminanceProject(Base):
    """조도설계 검증 — 현장/프로젝트 마스터"""
    __tablename__ = 'illuminance_projects'
    id             = Column(Integer, primary_key=True, autoincrement=True)
    project_name   = Column(String(200), nullable=False)
    erp_project_id = Column(Integer, ForeignKey('projects.id', ondelete='SET NULL'), nullable=True)
    customer       = Column(String(200))
    location       = Column(String(500))
    install_date   = Column(Date)
    pdf_filename   = Column(String(300))
    facility_type  = Column(String(100))  # 풋살장/축구장/테니스장/주차장/보행로
    status         = Column(String(20), default='design')  # design/measured/reported
    notes          = Column(Text)
    created_by     = Column(String(50))
    created_at     = Column(DateTime, default=datetime.datetime.now)
    areas          = relationship('IlluminanceArea', back_populates='project',
                                  cascade='all, delete-orphan', order_by='IlluminanceArea.area_index')
    erp_project    = relationship('Project', foreign_keys=[erp_project_id], lazy='select')


class IlluminanceArea(Base):
    """조도설계 검증 — 구역 (1 프로젝트 = N 구역)"""
    __tablename__ = 'illuminance_areas'
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    project_id          = Column(Integer, ForeignKey('illuminance_projects.id'), nullable=False)
    area_name           = Column(String(200), nullable=False)
    area_index          = Column(Integer, default=1)
    installation_height = Column(Float)
    lamp_type           = Column(String(100))
    lamp_watt           = Column(Integer)
    lamp_qty            = Column(Integer)
    tower_qty           = Column(Integer)
    simulation_date     = Column(Date)
    design_eav          = Column(Float)
    design_emin         = Column(Float)
    design_emax         = Column(Float)
    design_uo           = Column(Float)
    design_ud           = Column(Float)
    maintenance_factor  = Column(Float)
    total_flux          = Column(Float)
    total_power         = Column(Float)
    power_per_area      = Column(Float)
    grid_rows           = Column(Integer)
    grid_cols           = Column(Integer)
    grid_x_labels       = Column(Text)   # JSON
    grid_y_labels       = Column(Text)   # JSON
    design_grid         = Column(Text)   # JSON 2D array
    ks_eav_min          = Column(Float)
    ks_uo_min           = Column(Float)
    ks_ud_min           = Column(Float)
    fixtures            = Column(Text)   # JSON: [{"type":"LED투광등","watt":400,"qty":4}]
    created_at          = Column(DateTime, default=datetime.datetime.now)
    project             = relationship('IlluminanceProject', back_populates='areas')
    measurements        = relationship('IlluminanceMeasured', back_populates='area',
                                       cascade='all, delete-orphan',
                                       order_by='IlluminanceMeasured.created_at')

    @property
    def design_grid_parsed(self):
        return json.loads(self.design_grid) if self.design_grid else []

    @property
    def x_labels_parsed(self):
        return json.loads(self.grid_x_labels) if self.grid_x_labels else []

    @property
    def y_labels_parsed(self):
        return json.loads(self.grid_y_labels) if self.grid_y_labels else []

    @property
    def latest_measurement(self):
        return self.measurements[-1] if self.measurements else None


class IlluminanceMeasured(Base):
    """조도설계 검증 — 현장 실측값"""
    __tablename__ = 'illuminance_measured'
    id              = Column(Integer, primary_key=True, autoincrement=True)
    area_id         = Column(Integer, ForeignKey('illuminance_areas.id'), nullable=False)
    measure_date    = Column(Date, nullable=False)
    measured_by     = Column(String(100))
    weather         = Column(String(50))
    instrument      = Column(String(200))
    measured_eav    = Column(Float)
    measured_emin   = Column(Float)
    measured_emax   = Column(Float)
    measured_uo     = Column(Float)
    measured_ud     = Column(Float)
    measured_grid   = Column(Text)   # JSON 2D array
    ks_pass         = Column(String(10))   # PASS/WARNING/FAIL
    eav_achievement = Column(Float)
    uo_achievement  = Column(Float)
    notes           = Column(Text)
    created_at      = Column(DateTime, default=datetime.datetime.now)
    area            = relationship('IlluminanceArea', back_populates='measurements')

    @property
    def measured_grid_parsed(self):
        return json.loads(self.measured_grid) if self.measured_grid else []


# ── 인증서 만료 관리 ──
CERT_TYPE_CHOICES = [
    ('KS인증', 'KS인증'),
    ('성능인증', '성능인증'),
    ('녹색기술인증', '녹색기술인증'),
    ('환경표지', '환경표지'),
    ('조달우수제품', '조달우수제품'),
    ('G-PASS', 'G-PASS'),
    ('기타', '기타'),
]


class Certification(Base):
    """인증서 만료 관리"""
    __tablename__ = 'certifications'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cert_type = Column(String(50), nullable=False)
    cert_name = Column(String(200), nullable=False)
    cert_no = Column(String(100), nullable=True)
    issued_by = Column(String(200), nullable=True)
    issued_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    product_model = Column(String(200), nullable=True)
    alert_days = Column(Integer, default=30)
    file_path = Column(String(500), nullable=True)
    note = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - datetime.date.today()).days

    @property
    def expiry_status(self):
        days = self.days_until_expiry
        if days is None:
            return 'unknown'
        if days < 0:
            return 'expired'
        if days <= 7:
            return 'critical'
        if days <= 30:
            return 'warning'
        return 'ok'


# ── 시방서/규격서 추적 (PHASE 3) ──
SPEC_DOC_STATUS = ['미제출', '검토중', '반영완료', '미반영']
SPEC_DOC_TYPES = ['시방서', '규격서', '설계도서']


class SpecDocument(Base):
    """현장별 시방서/규격서 추적"""
    __tablename__ = 'spec_documents'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    doc_type = Column(String(30), nullable=False, default='시방서')
    doc_status = Column(String(20), nullable=False, default='미제출')
    title = Column(String(300), nullable=True)
    file_path = Column(String(500), nullable=True)
    submitted_date = Column(Date, nullable=True)
    confirmed_date = Column(Date, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    project = relationship('Project')


# ── 조도 시뮬레이션 설계 보고서 (PHASE 2) ──
SIMULATION_DOC_TYPES = ['DIALux', '조명배치도', '에너지절감분석', '기타']


class DesignSimulationDoc(Base):
    """설계 단계 조도 시뮬레이션 보고서"""
    __tablename__ = 'design_simulation_docs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    doc_type = Column(String(30), nullable=False, default='DIALux')
    title = Column(String(300), nullable=True)
    file_path = Column(String(500), nullable=True)
    simulation_date = Column(Date, nullable=True)
    target_lux = Column(Float, nullable=True)
    achieved_lux = Column(Float, nullable=True)
    uniformity = Column(Float, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    project = relationship('Project')


# ── 조명배치도 (타워별 투광등 넘버링 + 렌즈각도) ──

class TowerLayout(Base):
    """현장 타워별 조명배치도 마스터"""
    __tablename__ = 'tower_layouts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    tower_name = Column(String(100), nullable=False)       # 타워 이름 (예: T1, T2)
    rows = Column(Integer, nullable=False, default=2)       # 행 수
    cols = Column(Integer, nullable=False, default=3)       # 열 수
    model_name = Column(String(200), nullable=True)         # 투광등 모델명
    watt = Column(Integer, nullable=True)                   # 와트수
    note = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    project = relationship('Project')
    positions = relationship('TowerLayoutPosition', back_populates='tower_layout',
                             cascade='all, delete-orphan',
                             order_by='TowerLayoutPosition.position_no')


class TowerLayoutPosition(Base):
    """타워 내 개별 투광등 위치 (번호 + 렌즈각도)"""
    __tablename__ = 'tower_layout_positions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tower_layout_id = Column(Integer, ForeignKey('tower_layouts.id', ondelete='CASCADE'), nullable=False)
    position_no = Column(Integer, nullable=False)           # 좌상단→우측 순번 (1~rows*cols)
    row_idx = Column(Integer, nullable=False)               # 행 인덱스 (0-based)
    col_idx = Column(Integer, nullable=False)               # 열 인덱스 (0-based)
    lens_angle = Column(String(50), nullable=True)          # 렌즈각도 (예: 20°, 30°)
    note = Column(String(200), nullable=True)               # 비고

    tower_layout = relationship('TowerLayout', back_populates='positions')


class LensAngleConfig(Base):
    """모델별 렌즈각도 설정"""
    __tablename__ = 'lens_angle_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(100), unique=True, nullable=False)   # 모델 키워드 (예: STA, BATOO, ARENA)
    angles = Column(String(500), nullable=False)                     # 파이프 구분 (예: 20|35|55)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def angle_list(self):
        return [a.strip() for a in self.angles.split('|') if a.strip()]
