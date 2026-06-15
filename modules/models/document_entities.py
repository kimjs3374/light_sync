"""서류관리 엔티티 — 착수계/납품계 PDF 생성 + 공문번호 채번."""

import datetime
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Text, ForeignKey, Boolean, JSON,
)
from sqlalchemy.orm import relationship
from .base import Base


# 공문번호 채번용
class DocumentSerial(Base):
    """공문번호 연도별 순번 관리 (관리 제 YY-NNNNNN호)."""
    __tablename__ = 'document_serials'

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False, unique=True)       # 연도 (2026)
    last_number = Column(Integer, nullable=False, default=0)  # 마지막 발급번호

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class DocumentPackage(Base):
    """서류 패키지 — 하나의 납품요구건에 대한 서류 묶음."""
    __tablename__ = 'document_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    procurement_req_no = Column(String(30), nullable=False, unique=True, index=True)  # 납품요구번호 (g2b 매칭키)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)

    # 사업 기본정보 (PDF 파싱 또는 API에서)
    business_name = Column(String(300), nullable=True)        # 사업명
    demand_org = Column(String(200), nullable=True)           # 수요기관 (발주처)
    demand_org_no = Column(String(20), nullable=True)         # 수요기관번호
    org_type = Column(String(10), nullable=True)              # 관청구분 (청/기관) — 자동판별

    # PDF 파싱 보완 데이터
    contract_no = Column(String(50), nullable=True)           # 계약체결번호
    contract_date = Column(Date, nullable=True)               # 계약체결일자
    fee = Column(Integer, nullable=True)                      # 수수료
    total_amount = Column(Integer, nullable=True)             # 합계금액 (품대계+수수료)
    supply_amount = Column(Integer, nullable=True)            # 품대계
    warranty_period = Column(String(20), nullable=True)       # 하자담보책임기간
    inspection_org = Column(String(200), nullable=True)       # 검사기관
    acceptance_org = Column(String(200), nullable=True)       # 검수기관

    # 납품요구서 원본 PDF
    req_pdf_path = Column(String(500), nullable=True)         # 업로드된 납품요구서 PDF 경로

    # 착수계
    commencement_doc_no = Column(String(30), nullable=True)   # 착수계 공문번호
    commencement_date = Column(Date, nullable=True)           # 착수일
    commencement_agent_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # 현장대리인
    commencement_generated = Column(Boolean, default=False)   # 착수계 생성 여부

    # 납품계
    delivery_doc_no = Column(String(30), nullable=True)       # 납품계 공문번호
    delivery_date = Column(Date, nullable=True)               # 납품일 (제출일자)
    delivery_generated = Column(Boolean, default=False)       # 납품계 생성 여부

    # 서류 패키지 조립 순서 (현장별 개별 설정, null이면 전체 기본순서 사용)
    assembly_order = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    created_by = Column(String(50), nullable=True)

    # 관계
    project = relationship('Project', foreign_keys=[project_id])
    contract = relationship('Contract', foreign_keys=[contract_id])
    commencement_agent = relationship('User', foreign_keys=[commencement_agent_id])
    attachments = relationship('DocumentAttachment', back_populates='package',
                               cascade='all, delete-orphan', order_by='DocumentAttachment.sort_order')


class DocumentAttachment(Base):
    """서류 패키지 첨부파일 — 납세증명서, 사업자등록증 등."""
    __tablename__ = 'document_attachments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    package_id = Column(Integer, ForeignKey('document_packages.id'), nullable=False)
    file_type = Column(String(50), nullable=False)            # 파일 유형 (아래 상수)
    file_name = Column(String(300), nullable=True)            # 원본 파일명
    storage_path = Column(String(500), nullable=True)         # 저장 경로
    sort_order = Column(Integer, default=0)                   # 정렬순서

    created_at = Column(DateTime, default=datetime.datetime.now)

    package = relationship('DocumentPackage', back_populates='attachments')


class CommonDrawing(Base):
    """공통 제작도면 — 모델코드별 도면 PDF 등록 관리."""
    __tablename__ = 'common_drawings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(100), nullable=False, unique=True, index=True)
    storage_path = Column(String(500), nullable=False)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


# 첨부파일 유형 상수
DOC_ATTACH_TYPES = {
    'biz_registration': '사업자등록증',
    'tax_cert_national': '국세 납세증명서',
    'tax_cert_local': '지방세 납세증명서',
    'factory_cert': '공장등록증명서',
    'direct_production': '직접생산확인증명서',
    'contract_pdf': '물품계약서(납품요구서)',
    'drawing': '제작도면',
    'stamp_official': '공문도장',
    'stamp_corporate': '법인인감',
    'other': '기타',
}

# 고정 첨부파일 (한번 올리면 재사용)
REUSABLE_ATTACH_TYPES = ['biz_registration', 'factory_cert', 'direct_production',
                          'stamp_official', 'stamp_corporate']


def determine_org_type(org_name):
    """발주처명에서 관청구분 자동 판별 (청/기관)."""
    if not org_name:
        return '청'
    org_name = org_name.strip()
    # 기관 키워드
    institution_keywords = ['공사', '공단', '재단', '원', '대학교', '학교', '센터', '연구']
    for kw in institution_keywords:
        if org_name.endswith(kw) or kw in org_name:
            return '기관'
    return '청'


def generate_doc_number(db_session, doc_date=None):
    """
    공문번호를 자동채번한다.
    형식: 관리 제 YY-MMDDNN호 (연도2자리-월일+순번2자리)
    예: 관리 제 26-032601호
    """
    if doc_date is None:
        doc_date = datetime.date.today()

    year = doc_date.year
    year_short = year % 100  # 26

    serial = db_session.query(DocumentSerial).filter(
        DocumentSerial.year == year
    ).first()

    if not serial:
        serial = DocumentSerial(year=year, last_number=0)
        db_session.add(serial)
        db_session.flush()

    serial.last_number += 1
    next_num = serial.last_number

    # 형식: YY-MMDDNN (월일 + 순번2자리, 하루에 99건까지)
    mmdd = doc_date.strftime('%m%d')
    doc_no = f"관리 제 {year_short:02d}-{mmdd}{next_num:02d}호"

    db_session.flush()
    return doc_no
