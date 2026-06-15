"""전자결재(電子決裁) 모델

순차 결재 + 직급/부서 기반 기본 결재선(수정 가능) + 참조/수신.
양식(ApprovalFormTemplate)은 관리자가 추가/수정 가능하도록 DB에 저장.

상태 흐름:
    draft(작성중) → pending(진행중) → approved(완료) / rejected(반려)
    pending 상태에서 기안자가 회수 → canceled(회수)
"""
import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import Base

# 상태 상수
DOC_STATUS = {
    'draft': '작성중',
    'pending': '진행중',
    'approved': '완료',
    'rejected': '반려',
    'canceled': '회수',
}
STEP_STATUS = {
    'waiting': '대기',
    'current': '결재중',
    'approved': '승인',
    'rejected': '반려',
}
STEP_ROLE = {
    'approval': '결재',
    'agreement': '합의',
}
REF_TYPE = {
    'reference': '참조',
    'receiver': '수신',
}


class ApprovalFormTemplate(Base):
    """전자결재 양식 템플릿 (관리자가 추가/수정 가능).

    field_schema 예시 (JSONB):
        [
          {"key": "leave_type", "label": "휴가종류", "type": "select",
           "options": ["연차", "반차(오전)", "반차(오후)", "병가", "경조사"], "required": true},
          {"key": "start_date", "label": "시작일", "type": "date", "required": true},
          {"key": "days", "label": "일수", "type": "number", "required": true}
        ]
    default_line 예시: ["drafter", "dept_head", "executive"]
        (상신 시 토큰을 실제 사용자로 해석 → ApprovalStep 생성)
    """
    __tablename__ = 'approval_form_templates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    form_key = Column(String(50), unique=True, nullable=False)   # leave, expense, proposal, trip
    name = Column(String(100), nullable=False)                   # 휴가신청서
    description = Column(Text, nullable=True)
    icon = Column(String(20), nullable=True)                     # 이모지
    field_schema = Column(JSONB, nullable=False, default=list)   # 양식 필드 정의
    default_line = Column(JSONB, nullable=True)                  # 기본 결재선 토큰 리스트
    has_amount = Column(Boolean, default=False)                  # 금액 집계 대상 여부
    amount_field = Column(String(50), nullable=True)             # 금액으로 집계할 field key
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class ApprovalDocument(Base):
    """전자결재 문서(기안)"""
    __tablename__ = 'approval_documents'

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_no = Column(String(30), unique=True, nullable=True)      # EA-2026-0001 (상신 시 부여)
    form_key = Column(String(50), nullable=False)
    form_name = Column(String(100), nullable=False)              # 양식명 스냅샷

    title = Column(String(200), nullable=False)
    drafter_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    drafter_name = Column(String(50), nullable=False)
    drafter_dept = Column(String(50), nullable=True)
    drafter_position = Column(String(50), nullable=True)

    form_data = Column(JSONB, nullable=True)                     # 양식 필드 입력값
    content = Column(Text, nullable=True)                        # 본문/사유(공통)
    amount = Column(Numeric(15, 0), nullable=True)               # 금액(지출/품의)

    status = Column(String(20), default='draft', nullable=False)
    current_step = Column(Integer, default=0)                    # 현재 진행 중인 step_order

    created_at = Column(DateTime, default=datetime.datetime.now)
    submitted_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    steps = relationship(
        'ApprovalStep',
        back_populates='document',
        order_by='ApprovalStep.step_order',
        cascade='all, delete-orphan',
    )
    references = relationship(
        'ApprovalReference',
        back_populates='document',
        cascade='all, delete-orphan',
    )
    attachments = relationship(
        'ApprovalAttachment',
        back_populates='document',
        cascade='all, delete-orphan',
    )
    comments = relationship(
        'ApprovalComment',
        back_populates='document',
        order_by='ApprovalComment.created_at',
        cascade='all, delete-orphan',
    )

    @property
    def status_label(self):
        return DOC_STATUS.get(self.status, self.status)

    def current_approver_step(self):
        """현재 결재 차례 step 반환 (없으면 None)"""
        for s in self.steps:
            if s.status == 'current':
                return s
        return None


class ApprovalStep(Base):
    """결재선 단계 (순차 결재)"""
    __tablename__ = 'approval_steps'

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('approval_documents.id'), nullable=False)
    step_order = Column(Integer, nullable=False)                 # 1, 2, 3 ...
    approver_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    approver_name = Column(String(50), nullable=False)
    approver_position = Column(String(50), nullable=True)
    approver_dept = Column(String(50), nullable=True)
    role = Column(String(20), default='approval')               # approval/agreement
    status = Column(String(20), default='waiting')              # waiting/current/approved/rejected
    comment = Column(Text, nullable=True)
    acted_at = Column(DateTime, nullable=True)

    document = relationship('ApprovalDocument', back_populates='steps')

    @property
    def status_label(self):
        return STEP_STATUS.get(self.status, self.status)

    @property
    def role_label(self):
        return STEP_ROLE.get(self.role, self.role)


class ApprovalReference(Base):
    """참조/수신자"""
    __tablename__ = 'approval_references'

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('approval_documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    user_name = Column(String(50), nullable=False)
    ref_type = Column(String(20), default='reference')          # reference/receiver
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)

    document = relationship('ApprovalDocument', back_populates='references')

    @property
    def ref_label(self):
        return REF_TYPE.get(self.ref_type, self.ref_type)


class ApprovalAttachment(Base):
    """결재 첨부파일 (Supabase Storage)"""
    __tablename__ = 'approval_attachments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('approval_documents.id'), nullable=False)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=True)
    size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.datetime.now)

    document = relationship('ApprovalDocument', back_populates='attachments')


class ApprovalComment(Base):
    """결재 문서 의견/댓글"""
    __tablename__ = 'approval_comments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('approval_documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    user_name = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)

    document = relationship('ApprovalDocument', back_populates='comments')
