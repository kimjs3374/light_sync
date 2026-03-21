import datetime
import secrets

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base

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
