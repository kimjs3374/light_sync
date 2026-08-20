"""시료관리 엔티티 — 생산부 시료 마스터 + 시험이력 + QR 추적.

시료 1개체 = samples 1행. 시료번호는 모델별 채번(ARENA-200S-001).
QR 라벨을 실물에 부착하고, 스캔하면 /s/<qr_token> 공개 페이지로 연결된다.
"""

import datetime
import re
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import Base


SAMPLE_PURPOSE_CHOICES = [
    '인증취득', '입찰제출', '수요기관승인', '사내시험', 'A/S분석', '전시/홍보', '기타',
]

SAMPLE_STATUS_CHOICES = [
    '제작중', '보관중', '시험중', '반출', '반납완료', '폐기',
]

# 시험 구분 4종 — 공인기관/사내/발주처검사/AS분석
TEST_CATEGORY_CHOICES = [
    '공인시험', '사내검사', '조달·수요기관검사', 'A/S분석',
]

TEST_TYPE_CHOICES = [
    '광학(광속·배광)', '전기(소비전력·역률)', '내구/수명', '방수·방진(IP)',
    'EMC/전자파', 'KS인증시험', '고효율기자재', '내후성/염수분무',
    '외관/치수', '원인분석', '기타',
]

TEST_RESULT_CHOICES = ['합격', '불합격', '판정보류', '참고(수치만)']

TEST_AGENCY_SUGGESTIONS = [
    '한국산업기술시험원(KTL)',
    '한국기계전기전자시험연구원(KTC)',
    '한국조명ICT연구원',
    '한국건설생활환경시험연구원(KCL)',
    'FITI시험연구원',
    '한국화학융합시험연구원(KTR)',
    '사내 시험실',
]

# 측정값 입력 필드 (measured_json 키 → 라벨/단위)
MEASURE_FIELDS = [
    ('lumen',   '광속',     'lm'),
    ('efficacy', '효율',    'lm/W'),
    ('watt',    '소비전력', 'W'),
    ('cct',     '색온도',   'K'),
    ('cri',     '연색성',   'Ra'),
    ('pf',      '역률',     ''),
    ('thd',     'THD',      '%'),
    ('lifetime', '수명',    'h'),
]

# ── 공개(QR) 페이지 비노출 규칙 ─────────────────────────────
# A/S 회수품 원인분석과 불합격·보류 이력은 외부에 노출하지 않는다.
# 토큰 URL이 외부로 유출돼도 합격한 유효 성적서만 보이게 하기 위함.
PUBLIC_HIDDEN_CATEGORIES = {'A/S분석'}
PUBLIC_HIDDEN_RESULTS = {'불합격', '판정보류'}


def normalize_model_code(model_name):
    """모델명 → 채번용 모델코드. 'ARENA-200S 5m' → 'ARENA-200S'."""
    if not model_name:
        return 'ETC'
    code = str(model_name).strip().upper()
    code = code.split()[0] if code.split() else code
    code = re.sub(r'[^A-Z0-9\-_]', '', code)
    return code[:40] or 'ETC'


def generate_sample_no(db, model_name):
    """모델별 시료번호 채번 — ARENA-200S-001.

    같은 모델코드의 마지막 seq + 1. UniqueConstraint(model_code, seq)로
    동시 등록 충돌은 DB가 막고, 라우트에서 재시도한다.
    """
    model_code = normalize_model_code(model_name)
    last_seq = (
        db.query(Sample.seq)
        .filter(Sample.model_code == model_code)
        .order_by(Sample.seq.desc())
        .limit(1)
        .scalar()
    )
    seq = (last_seq or 0) + 1
    return model_code, seq, f'{model_code}-{seq:03d}'


class Sample(Base):
    """시료 마스터 — 시료 1개체"""
    __tablename__ = 'samples'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── 식별 ──
    sample_no = Column(String(60), unique=True, nullable=False)   # ARENA-200S-001
    model_code = Column(String(40), nullable=False)               # 채번 접두 (ARENA-200S)
    seq = Column(Integer, nullable=False, default=1)              # 모델별 순번
    qr_token = Column(String(64), unique=True, nullable=False,
                      default=lambda: secrets.token_urlsafe(16))

    # ── 제품 ──
    model_name = Column(String(200), nullable=False)
    catalog_id = Column(Integer, ForeignKey('product_catalog.id'), nullable=True)
    item_cd = Column(String(50), nullable=True)                   # 아이큐브 품번

    # ── 구분/상태 ──
    purpose = Column(String(30), nullable=False, default='사내시험')
    status = Column(String(20), nullable=False, default='보관중')

    # ── 제작/보관 ──
    mfg_date = Column(Date, nullable=True)
    made_by = Column(String(50), nullable=True)
    location = Column(String(200), nullable=True)                 # 보관위치 (시료보관실 A-3)

    # ── 연결 ──
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    warranty_case_id = Column(Integer, ForeignKey('warranty_cases.id'), nullable=True)

    # ── 스펙 (고정) ──
    led_chip = Column(String(200), nullable=True)
    pcb_spec = Column(String(200), nullable=True)
    cct = Column(String(50), nullable=True)                       # 색온도 (5700K)
    lens_angle = Column(String(100), nullable=True)
    smps_model = Column(String(200), nullable=True)
    watt = Column(Float, nullable=True)                           # 소비전력(W)
    lumen = Column(Float, nullable=True)                          # 광속(lm)
    input_voltage = Column(String(50), nullable=True)             # AC220V 60Hz
    ip_grade = Column(String(30), nullable=True)                  # IP66
    body_material = Column(String(100), nullable=True)
    weight = Column(Float, nullable=True)                         # kg
    # ── 스펙 (가변) ──
    spec_json = Column(JSONB, nullable=True)                      # {"항목명": "값"}

    photo_path = Column(String(500), nullable=True)               # Supabase Storage 경로
    public_note = Column(Text, nullable=True)                     # QR 공개 페이지 노출
    internal_note = Column(Text, nullable=True)                   # 사내 전용 (공개 금지)

    # ── QR 스캔 추적 ──
    scan_count = Column(Integer, nullable=False, default=0)
    last_scanned_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (
        UniqueConstraint('model_code', 'seq', name='uq_sample_model_seq'),
    )

    tests = relationship(
        'SampleTest', back_populates='sample',
        cascade='all, delete-orphan',
        order_by='desc(SampleTest.issued_date), desc(SampleTest.id)',
    )
    logs = relationship(
        'SampleLog', back_populates='sample',
        cascade='all, delete-orphan',
        order_by='desc(SampleLog.created_at), desc(SampleLog.id)',
    )
    project = relationship('Project')
    catalog = relationship('ProductCatalog')
    warranty_case = relationship('WarrantyCase')

    # ── 파생 속성 ──
    @property
    def public_tests(self):
        """QR 공개 페이지에 노출 가능한 시험만 — 불합격/보류/AS분석 제외."""
        return [t for t in self.tests if t.is_public]

    @property
    def test_count(self):
        return len(self.tests)

    @property
    def expiry_status(self):
        """보유 성적서 중 가장 급한 만료 상태. Certification과 같은 등급 체계."""
        order = {'expired': 0, 'critical': 1, 'warning': 2, 'ok': 3}
        worst = None
        for t in self.tests:
            st = t.expiry_status
            if st == 'unknown':
                continue
            if worst is None or order[st] < order[worst]:
                worst = st
        return worst or 'unknown'

    @property
    def spec_pairs(self):
        """상세/공개 화면용 스펙 (라벨, 값) 목록 — 값 있는 항목만."""
        fixed = [
            ('모델명', self.model_name),
            ('LED 칩', self.led_chip),
            ('PCB 사양', self.pcb_spec),
            ('색온도', self.cct),
            ('렌즈 각도', self.lens_angle),
            ('SMPS', self.smps_model),
            ('소비전력', f'{self.watt:g}W' if self.watt else None),
            ('광속', f'{self.lumen:g}lm' if self.lumen else None),
            ('입력전원', self.input_voltage),
            ('IP 등급', self.ip_grade),
            ('본체 재질', self.body_material),
            ('중량', f'{self.weight:g}kg' if self.weight else None),
        ]
        pairs = [(k, v) for k, v in fixed if v not in (None, '')]
        for k, v in (self.spec_json or {}).items():
            if v not in (None, ''):
                pairs.append((str(k), str(v)))
        return pairs


class SampleTest(Base):
    """시료 시험 이력 — 공인시험/사내검사/발주처검사/AS분석"""
    __tablename__ = 'sample_tests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_id = Column(Integer, ForeignKey('samples.id'), nullable=False)

    test_category = Column(String(30), nullable=False, default='공인시험')
    test_type = Column(String(50), nullable=True)
    agency = Column(String(200), nullable=True)                   # 시험기관

    request_date = Column(Date, nullable=True)                    # 접수/의뢰일
    report_no = Column(String(100), nullable=True)                # 성적서 번호
    issued_date = Column(Date, nullable=True)                     # 발급일
    valid_until = Column(Date, nullable=True)                     # 유효기간

    result = Column(String(20), nullable=True)                    # 합격/불합격/판정보류/참고
    measured_json = Column(JSONB, nullable=True)                  # {"lumen": 21500, ...}

    file_path = Column(String(500), nullable=True)                # Supabase Storage 성적서
    file_name = Column(String(300), nullable=True)                # 원본 파일명
    certification_id = Column(Integer, ForeignKey('certifications.id'), nullable=True)

    tester = Column(String(50), nullable=True)                    # 담당/측정자
    note = Column(Text, nullable=True)

    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    sample = relationship('Sample', back_populates='tests')
    certification = relationship('Certification')

    @property
    def days_until_expiry(self):
        if not self.valid_until:
            return None
        return (self.valid_until - datetime.date.today()).days

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

    @property
    def is_public(self):
        """QR 공개 페이지 노출 여부 — 합격 성적서만, AS분석 제외, 만료 제외."""
        if self.test_category in PUBLIC_HIDDEN_CATEGORIES:
            return False
        if (self.result or '') in PUBLIC_HIDDEN_RESULTS:
            return False
        if self.expiry_status == 'expired':
            return False
        return True

    @property
    def measured_pairs(self):
        """(라벨, 값+단위) 목록 — 입력된 항목만."""
        data = self.measured_json or {}
        pairs = []
        for key, label, unit in MEASURE_FIELDS:
            val = data.get(key)
            if val in (None, ''):
                continue
            pairs.append((label, f'{val}{unit}' if unit else str(val)))
        known = {k for k, _, _ in MEASURE_FIELDS}
        for k, v in data.items():
            if k not in known and v not in (None, ''):
                pairs.append((str(k), str(v)))
        return pairs


class SampleLog(Base):
    """시료 이력 로그 — 등록/수정/시험등록/반출/반납/폐기/QR스캔"""
    __tablename__ = 'sample_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_id = Column(Integer, ForeignKey('samples.id'), nullable=False)

    action = Column(String(30), nullable=False)                   # 등록/수정/상태변경/시험등록/QR스캔/폐기
    content = Column(Text, nullable=True)
    user_name = Column(String(50), nullable=True)
    origin = Column(String(20), nullable=False, default='web')    # web / qr / mobile
    ip_address = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    sample = relationship('Sample', back_populates='logs')


def append_sample_log(db, sample_id, action, content=None,
                      user_name=None, origin='web', ip_address=None):
    """시료 이력 1건 기록 — 모든 업무행위 로그 필수 규칙."""
    log = SampleLog(
        sample_id=sample_id,
        action=action,
        content=content,
        user_name=user_name or '시스템',
        origin=origin,
        ip_address=ip_address,
    )
    db.add(log)
    return log
