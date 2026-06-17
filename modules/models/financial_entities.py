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
)
from sqlalchemy.orm import relationship

from .base import Base

PAYMENT_STATUS_CHOICES = ['미수금', '부분입금', '입금완료']
MATCH_STATUS_CHOICES = ['자동매칭', '수동매칭', '미매칭']
PAYMENT_METHOD_CHOICES = ['계좌이체', '카드', '어음', '기타']
QUOTE_STATUS_CHOICES = ['작성중', '발송', '만료']


class TaxInvoice(Base):
    """국세청 매출전자세금계산서"""
    __tablename__ = 'tax_invoices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    approval_no = Column(String(50), unique=True, nullable=False)   # 국세청 승인번호
    issue_date = Column(Date, nullable=True)                         # 작성일자
    send_date = Column(Date, nullable=True)                          # 전송일자
    invoice_type = Column(String(20), default='세금계산서')           # 세금계산서/수정세금계산서/계산서
    direction = Column(String(10), default='매출')                    # 매출/매입 (홈택스 수집 시 공급자 사업자번호로 판정)

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


class HometaxCredential(Base):
    """홈택스 공동인증서 무인 수집 설정 (단일 회사 기준 1건).

    인증서 파일은 로컬 비밀 디렉토리(NPKI/, .gitignore)에 저장하고,
    비밀번호는 Fernet 암호화하여 저장한다(메일계정과 동일 패턴).
    """
    __tablename__ = 'hometax_credentials'

    id = Column(Integer, primary_key=True, autoincrement=True)
    biz_no = Column(String(20), nullable=True)                        # 사업자등록번호 (숫자만)
    cert_der_path = Column(String(300), nullable=True)               # signCert.der 절대경로
    cert_key_path = Column(String(300), nullable=True)               # signPri.key 절대경로
    password_encrypted = Column(Text, nullable=True)                 # Fernet 암호화된 인증서 비번
    cert_subject = Column(String(300), nullable=True)               # 표시용 인증서 주체(CN)
    cert_expiry = Column(Date, nullable=True)                         # 표시용 인증서 만료일

    enabled = Column(Boolean, default=False)                         # 무인 수집 활성화 여부
    last_sync_at = Column(DateTime, nullable=True)                   # 마지막 수집 시각
    last_sync_status = Column(String(20), nullable=True)            # 성공/실패/진행중
    last_sync_message = Column(Text, nullable=True)                  # 마지막 결과 메시지

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class Quotation(Base):
    """견적서"""
    __tablename__ = 'quotations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_no = Column(String(20), unique=True, nullable=False)  # MT-YYMMDD-순번
    quote_date = Column(Date, nullable=False)

    # 견적 조건
    validity_period = Column(String(100), default='견적일로부터 1개월')
    delivery_date = Column(String(100), default='협의')
    payment_method = Column(String(100), default='현금')
    bank_account = Column(String(200), nullable=True)

    # 건명
    project_name = Column(String(500), nullable=True)

    # 수급자 정보
    customer_name = Column(String(200), nullable=True)
    customer_contact = Column(String(100), nullable=True)
    customer_address = Column(String(500), nullable=True)
    customer_tel = Column(String(50), nullable=True)
    customer_fax = Column(String(50), nullable=True)
    customer_email = Column(String(200), nullable=True)

    # 금액
    total_amount = Column(Float, default=0)         # 품목 공급가액 합계
    surcharges_json = Column(Text, nullable=True)   # JSON: [{"name":"부가세","rate":10,"amount":...}, ...]
    grand_total = Column(Float, default=0)           # 공급가액 + 부과금 합계
    tax_included = Column(Boolean, default=False)

    # 비고
    note = Column(Text, nullable=True)

    # 상태
    status = Column(String(20), default='작성중')

    # 메타
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    items = relationship("QuotationItem", back_populates="quotation",
                         cascade="all, delete-orphan", order_by="QuotationItem.seq")

    @property
    def surcharges(self):
        try:
            return json.loads(self.surcharges_json or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    @surcharges.setter
    def surcharges(self, value):
        self.surcharges_json = json.dumps(value, ensure_ascii=False)


class QuotationItem(Base):
    """견적 품목"""
    __tablename__ = 'quotation_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    quotation_id = Column(Integer, ForeignKey('quotations.id'), nullable=False)
    seq = Column(Integer, default=0)
    item_id = Column(Integer, nullable=True)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    unit = Column(String(50), default='개')
    quantity = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    note = Column(String(500), nullable=True)

    quotation = relationship("Quotation", back_populates="items")


class QuoteTemplate(Base):
    """견적 세부 템플릿 (품목 세트 재사용)"""
    __tablename__ = 'quote_templates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_name = Column(String(200), nullable=False)  # ex) "15M 조명타워 기초공사"
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    items = relationship("QuoteTemplateItem", back_populates="template",
                         cascade="all, delete-orphan", order_by="QuoteTemplateItem.seq")


class QuoteTemplateItem(Base):
    """세부견적 템플릿 품목"""
    __tablename__ = 'quote_template_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey('quote_templates.id'), nullable=False)
    seq = Column(Integer, default=0)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    unit = Column(String(50), default='개')
    quantity = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    note = Column(String(500), nullable=True)

    template = relationship("QuoteTemplate", back_populates="items")
