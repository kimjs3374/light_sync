# A/S 관리 시스템 전면 재설계 Design Document

> **Feature**: A/S 관리 시스템 전면 재설계
> **Version**: 1.0
> **Date**: 2026-03-21
> **Status**: Draft
> **Planning Doc**: [warranty-redesign.plan.md](../../01-plan/features/warranty-redesign.plan.md)

---

## Executive Summary

현재 A/S 관리는 카카오워크 게시판(140건)으로 운영되며, ERP WarrantyCase는 0건이다.
1,206건 보증/258건 진행중 보증에 대한 만료 추적, 유상/무상 판별, 반복 불량 분석이 전무하다.

본 설계는 다음을 구현한다:

1. **Warranty/WarrantyCase 모델 보강** -- 비정규화 필드 추가로 JOIN 0개 목록 조회 달성
2. **A/S 대시보드** -- 보증현황 요약 + 만료임박 + 진행중 케이스 + 품목별 통계
3. **A/S 접수 UX 전면 재설계** -- 계약검색 -> 자동채움 -> 유상/무상 자동판별
4. **제품 이력카드** -- 계약 -> 납품 -> 대금 -> 보증 -> A/S 전 주기 통합 뷰
5. **기존 1,206건 보증 비정규화 백필** -- 1회성 스크립트

| 지표 | Before | After |
|------|--------|-------|
| A/S 케이스 등록 | 0건 (카톡) | ERP 통합 |
| 목록 조회 성능 | JOIN 3개 | JOIN 0개 |
| 유상/무상 판별 | 수동 | 자동 |
| 보증 만료 추적 | 없음 | 대시보드 + D-day |
| 반복 불량 분석 | 불가 | 품목/모델별 통계 |

---

## 1. DB 스키마 변경

### 1.1 Warranty 모델 보강

기존 `misc_entities.py` Warranty 클래스에 비정규화 필드 8개를 추가한다.

```python
class Warranty(Base):
    __tablename__ = 'warranties'

    # ── 기존 필드 (유지) ──
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), unique=True, nullable=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    warranty_start = Column(Date, nullable=True)
    warranty_end = Column(Date, nullable=True)
    warranty_amount = Column(Integer, default=0)
    warranty_type = Column(String(20), default='일반')          # 혁신제품/우수제품/일반
    auto_generated = Column(Boolean, default=False)
    insurance_no = Column(String(100), nullable=True)
    insurance_returned = Column(Boolean, default=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    # ── 신규 추가: 비정규화 필드 (목록 조회 시 JOIN 제거) ──
    contract_name = Column(String(200), nullable=True)      # Contract.contract_name
    project_name = Column(String(200), nullable=True)       # Project.temp_name
    item_group = Column(String(50), nullable=True)          # Contract.item_group
    model_name = Column(String(200), nullable=True)         # ContractItem[0].model_name
    quantity = Column(Integer, nullable=True)                # sum(ContractItem.quantity)
    site_address = Column(String(500), nullable=True)       # Project.site_address
    customer_contact = Column(String(200), nullable=True)   # 발주처 담당자
    customer_phone = Column(String(50), nullable=True)      # 발주처 전화번호

    # ── 관계 (유지) ──
    contract = relationship("Contract", backref="warranty")
    project = relationship("Project")
    cases = relationship("WarrantyCase", back_populates="warranty", cascade="all, delete-orphan")
```

> **비정규화 근거**: 1,206건 보증 목록을 조회할 때 Warranty -> Contract -> Project -> ContractItem 3단 JOIN 제거.
> 보증은 과거 시점 snapshot이므로 원본 변경 시 동기화 불필요.

### 1.2 WarrantyCase 모델 보강

기존 WarrantyCase에 유상/무상 3필드, 고객정보 3필드, 교체부품 JSON, 물류 3필드, 비정규화 3필드를 추가한다.

```python
class WarrantyCase(Base):
    __tablename__ = 'warranty_cases'

    # ── 기존 필드 (유지) ──
    id = Column(Integer, primary_key=True, autoincrement=True)
    warranty_id = Column(Integer, ForeignKey('warranties.id'), nullable=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
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
    manual_site_name = Column(String(200), nullable=True)
    manual_contract_name = Column(String(200), nullable=True)
    manual_model_name = Column(String(200), nullable=True)
    manual_delivery_date = Column(Date, nullable=True)

    # ── 신규: 유상/무상 판별 ──
    is_chargeable = Column(Boolean, default=False)          # True=유상 (보증 만료)
    charge_amount = Column(Integer, default=0)              # 유상 금액 (원)
    charge_status = Column(String(20), nullable=True)       # 미청구/청구완료/입금완료

    # ── 신규: 고객 정보 ──
    request_channel = Column(String(30), nullable=True)     # 접수경로: 전화/카톡/이메일/방문
    customer_name = Column(String(100), nullable=True)      # 고객 담당자명
    customer_phone = Column(String(50), nullable=True)      # 고객 전화번호

    # ── 신규: 교체 부품 상세 (JSON) ──
    parts_json = Column(Text, nullable=True)
    # 구조: [{"name":"SMPS 150W","model":"MT-SLC-150","qty":1,"unit_price":0}]

    # ── 신규: 물류 ──
    shipping_method = Column(String(30), nullable=True)     # 택배/방문/직접수령
    shipping_tracking = Column(String(100), nullable=True)  # 송장번호
    shipping_date = Column(Date, nullable=True)             # 발송일

    # ── 신규: 비정규화 (목록 조회용) ──
    contract_name = Column(String(200), nullable=True)      # Contract.contract_name
    item_group = Column(String(50), nullable=True)          # Contract.item_group
    model_name = Column(String(200), nullable=True)         # ContractItem[0].model_name

    # ── 관계 (유지) ──
    warranty = relationship("Warranty", back_populates="cases")
    project = relationship("Project")
    logs = relationship("WarrantyCaseLog", back_populates="case", cascade="all, delete-orphan")
```

#### parts_json 구조

```json
[
    {"name": "SMPS 150W", "model": "MT-SLC-150", "qty": 2, "unit_price": 15000},
    {"name": "LED 모듈 50W", "model": "MT-M50", "qty": 4, "unit_price": 8000}
]
```

`@property parts` / `@parts.setter` 패턴으로 Python list 접근 (DailyReport.items 패턴 동일).

```python
@property
def parts(self):
    try:
        return json.loads(self.parts_json or '[]')
    except (json.JSONDecodeError, TypeError):
        return []

@parts.setter
def parts(self, value):
    self.parts_json = json.dumps(value, ensure_ascii=False)
```

### 1.3 DEFECT_TYPES 확장 (7 -> 13개)

기존 `misc_entities.py`의 `DEFECT_TYPES` 교체:

```python
DEFECT_TYPES = [
    ('LED_MODULE', 'LED 모듈 불량'),
    ('SMPS', 'SMPS 고장'),
    ('HEAT', '방열 이상'),
    ('LENS', '렌즈/리플렉터 손상'),
    ('MOISTURE', '결로/침수'),
    ('CONTROL', '제어 불량'),
    ('WIRING', '배선/커넥터 불량'),     # 신규
    ('BODY', '등기구 외함 손상'),       # 신규
    ('POLE', '등주/타워 손상'),         # 신규
    ('PAINT', '도장 박리/부식'),        # 신규
    ('ANCHOR', '앵커/기초 문제'),       # 신규
    ('SENSOR', '센서 오동작'),          # 신규
    ('OTHER', '기타'),
]
```

### 1.4 CASE_STATUS_STEPS 확장 (5 -> 6단계)

```python
# 기존: ['접수', '현장확인', '수리중', '완료', '보류']
CASE_STATUS_STEPS = ['접수', '현장확인', '부품준비', '수리/교체', '완료', '보류']
```

변경 사항:
- `수리중` -> `부품준비` + `수리/교체` (2단계 분리)
- 부품 택배/물류 추적이 필요하므로 `부품준비` 단계 분리

### 1.5 인덱스 4개

```sql
-- 보증 만료일 (만료 임박 조회 + 정렬)
CREATE INDEX IF NOT EXISTS idx_warranty_end ON warranties(warranty_end);

-- 보증 유형별 필터
CREATE INDEX IF NOT EXISTS idx_warranty_type ON warranties(warranty_type);

-- A/S 케이스 상태별 조회
CREATE INDEX IF NOT EXISTS idx_case_status ON warranty_cases(status);

-- A/S 케이스 접수일 역순 정렬
CREATE INDEX IF NOT EXISTS idx_case_reported ON warranty_cases(reported_date DESC);
```

### 1.6 sql_editer.sql ALTER TABLE 구문

```sql
-- ══════════════════════════════════════════════
-- A/S 관리 재설계 (2026-03-21)
-- ══════════════════════════════════════════════

-- Warranty 비정규화 필드 8개
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS contract_name VARCHAR(200);
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS project_name VARCHAR(200);
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS item_group VARCHAR(50);
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS model_name VARCHAR(200);
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS quantity INTEGER;
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS site_address VARCHAR(500);
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS customer_contact VARCHAR(200);
ALTER TABLE warranties ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);

-- WarrantyCase 유상/무상 3필드
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS is_chargeable BOOLEAN DEFAULT FALSE;
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS charge_amount INTEGER DEFAULT 0;
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS charge_status VARCHAR(20);

-- WarrantyCase 고객정보 3필드
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS request_channel VARCHAR(30);
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS customer_name VARCHAR(100);
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);

-- WarrantyCase 교체부품 JSON
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS parts_json TEXT;

-- WarrantyCase 물류 3필드
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS shipping_method VARCHAR(30);
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS shipping_tracking VARCHAR(100);
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS shipping_date DATE;

-- WarrantyCase 비정규화 3필드
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS contract_name VARCHAR(200);
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS item_group VARCHAR(50);
ALTER TABLE warranty_cases ADD COLUMN IF NOT EXISTS model_name VARCHAR(200);

-- 인덱스 4개
CREATE INDEX IF NOT EXISTS idx_warranty_end ON warranties(warranty_end);
CREATE INDEX IF NOT EXISTS idx_warranty_type ON warranties(warranty_type);
CREATE INDEX IF NOT EXISTS idx_case_status ON warranty_cases(status);
CREATE INDEX IF NOT EXISTS idx_case_reported ON warranty_cases(reported_date DESC);
```

---

## 2. 보증 자동생성 강화

### 2.1 warranty_auto.py 수정

**파일**: `modules/services/warranty_auto.py`

기존 `auto_create_warranty(db, contract_id, issue_date)` 함수에 비정규화 데이터 수집을 추가한다.

```python
def auto_create_warranty(db, contract_id, issue_date):
    """세금계산서 매칭 시 하자보증 자동생성 (비정규화 포함)"""
    existing = db.query(Warranty).filter_by(contract_id=contract_id).first()
    if existing:
        return existing

    contract = db.query(Contract).options(
        joinedload(Contract.project),
        joinedload(Contract.items),
    ).get(contract_id)
    if not contract:
        return None

    warranty_type = _determine_warranty_type(db, contract)

    years = 3 if warranty_type in ('혁신제품', '우수제품') else 1
    start_date = issue_date if isinstance(issue_date, datetime.date) else datetime.date.today()
    end_date = start_date.replace(year=start_date.year + years)

    # 비정규화 데이터 수집
    project = contract.project
    first_item = contract.items[0] if contract.items else None

    warranty = Warranty(
        contract_id=contract_id,
        project_id=contract.project_id,
        warranty_start=start_date,
        warranty_end=end_date,
        warranty_type=warranty_type,
        auto_generated=True,
        # 비정규화 필드
        contract_name=contract.contract_name,
        project_name=project.temp_name if project else None,
        item_group=contract.item_group,
        model_name=first_item.model_name if first_item else None,
        quantity=sum(i.quantity or 0 for i in contract.items),
        site_address=project.site_address if project else None,
        # customer_contact, customer_phone: 발주처 정보 (Project에 있으면 수집)
    )
    db.add(warranty)

    logger.info(
        'Auto warranty created: contract=%d, type=%s, %s~%s',
        contract_id, warranty_type, start_date, end_date,
    )
    return warranty
```

#### 혁신제품 판별 보강

기존 `_determine_warranty_type`의 혁신 판별 조건을 확장한다:

```python
def _determine_warranty_type(db, contract):
    """G2B 조달 데이터로 보증유형 판별"""
    if not contract.g2b_contract_no:
        return '일반'

    proc = db.query(G2bProcurement).filter(
        G2bProcurement.cntrct_dlvr_req_no == contract.g2b_contract_no
    ).first()
    if not proc:
        return '일반'

    # 우수제품 여부
    if proc.exclc_prodct_yn and proc.exclc_prodct_yn.upper() in ('Y', 'YES', '1'):
        return '우수제품'

    # 혁신제품 판별 (복수 조건)
    cntrct_mthd = proc.cntrct_mthd_nm or ''
    cntrct_div = proc.cntrct_div_nm or ''
    if '혁신' in cntrct_mthd or '혁신' in cntrct_div:
        return '혁신제품'

    return '일반'
```

### 2.2 기존 1,206건 백필 스크립트

1회성 스크립트로 기존 보증 데이터에 비정규화 필드를 채운다.
`warranty_auto.py` 하단 또는 별도 함수로 작성한다.

```python
def backfill_warranty_denorm(db):
    """기존 보증 1,206건에 비정규화 데이터 백필 (1회성)"""
    warranties = db.query(Warranty).filter(
        Warranty.contract_name.is_(None)
    ).all()

    count = 0
    for w in warranties:
        if not w.contract_id:
            continue
        contract = db.query(Contract).options(
            joinedload(Contract.project),
            joinedload(Contract.items),
        ).get(w.contract_id)
        if not contract:
            continue

        project = contract.project
        first_item = contract.items[0] if contract.items else None

        w.contract_name = contract.contract_name
        w.project_name = project.temp_name if project else None
        w.item_group = contract.item_group
        w.model_name = first_item.model_name if first_item else None
        w.quantity = sum(i.quantity or 0 for i in contract.items)
        w.site_address = project.site_address if project else None
        count += 1

    db.commit()
    logger.info('Backfilled %d warranties with denormalized data', count)
    return count
```

실행 방법: Flask shell 또는 1회성 스크립트에서 호출.

```python
# flask shell
from modules.services.warranty_auto import backfill_warranty_denorm
from modules.db_context import get_db
with get_db() as db:
    backfill_warranty_denorm(db)
```

---

## 3. Route 설계

### 3.1 라우트 구조

| Method | Path | Description | 비고 |
|--------|------|-------------|------|
| GET | `/warranty` | A/S 대시보드 | **재설계** (기존: 케이스 목록) |
| GET | `/warranty/list` | 보증 목록 | **신규** (필터/검색/정렬/50건) |
| GET | `/warranty/case/create` | A/S 접수 | **재설계** (계약검색 -> 자동채움) |
| GET/POST | `/warranty/case/<id>` | A/S 상세 | **재설계** (상태+부품+물류+비용) |
| POST | `/warranty/api/search-contract` | 계약검색 AJAX | **신규** |
| GET | `/warranty/<id>/product-history` | 제품 이력카드 | **신규** |
| GET/POST | `/warranty/register/<contract_id>` | 보증 등록/수정 | 유지 |

> 기존 `/warranty` (케이스 목록)을 대시보드로 변경하고, 보증 목록은 `/warranty/list`로 분리한다.

### 3.2 GET /warranty -- A/S 대시보드

**템플릿**: `templates/warranty_dashboard.html`

#### 데이터 구조

```python
@warranty_bp.route('/warranty')
@login_required
def warranty_dashboard():
    today = datetime.date.today()
    threshold_30d = today + datetime.timedelta(days=30)

    with get_db() as db:
        # 보증현황 요약 (Warranty 테이블만, JOIN 없음)
        total_count = db.query(Warranty).count()
        active_count = db.query(Warranty).filter(Warranty.warranty_end >= today).count()
        expired_count = total_count - active_count
        case_count = db.query(WarrantyCase).count()

        # 만료임박 (30일 이내, 진행중인 것만)
        expiring = (
            db.query(Warranty)
            .filter(
                Warranty.warranty_end >= today,
                Warranty.warranty_end <= threshold_30d,
            )
            .order_by(Warranty.warranty_end.asc())
            .limit(20)
            .all()
        )

        # 진행중 A/S 케이스
        open_cases = (
            db.query(WarrantyCase)
            .filter(WarrantyCase.status.notin_(['완료', '보류']))
            .order_by(WarrantyCase.reported_date.desc())
            .limit(20)
            .all()
        )

        # 품목별 불량 통계 (item_group x defect_type 피벗)
        all_cases = db.query(
            WarrantyCase.item_group,
            WarrantyCase.defect_type,
            func.count(WarrantyCase.id),
        ).group_by(WarrantyCase.item_group, WarrantyCase.defect_type).all()

    return render_template('warranty_dashboard.html',
        summary={'total': total_count, 'active': active_count,
                 'expired': expired_count, 'cases': case_count},
        expiring=expiring,
        open_cases=open_cases,
        defect_stats=all_cases,
        today=today,
        defect_types=DEFECT_TYPES,
    )
```

#### 화면 레이아웃

```
┌─── 보증 현황 요약 ──────────────────────────────────────────┐
│  [card shadow-sm]   [card shadow-sm]   [card shadow-sm]      │
│  전체 1,206건       진행중 258건       만료 948건              │
│                                                              │
│  [card shadow-sm]                                            │
│  A/S 접수 0건                                                │
└──────────────────────────────────────────────────────────────┘

┌─── 만료 임박 (30일 이내) ────────────────────────────────────┐
│  테이블: 현장명 | 품목 | 모델 | 만료일 | D-day | [A/S접수]    │
│  white-space:nowrap, text-truncate, btn-xs                   │
└──────────────────────────────────────────────────────────────┘

┌─── 진행중 A/S 케이스 ────────────────────────────────────────┐
│  테이블: 번호 | 현장 | 증상 | 상태badge | 담당자 | 경과일     │
│  상태: badge-status 인라인                                   │
└──────────────────────────────────────────────────────────────┘

┌─── 품목별 불량 통계 ─────────────────────────────────────────┐
│  item_group x defect_type 피벗 테이블                        │
│  LED투광등 | SMPS 12 | LED모듈 8 | 결로 3                    │
└──────────────────────────────────────────────────────────────┘
```

#### UI 규칙 (MAGNATECH Design System)

- 요약 카드: `card shadow-sm`, 숫자는 `h3` bold, 라벨은 `text-muted small`
- 테이블: `table table-sm`, `white-space: nowrap`, 줄바꿈 금지
- D-day 뱃지: 7일 이내 `badge bg-danger`, 14일 이내 `badge bg-warning`, 30일 이내 `badge bg-info`
- 상태 뱃지: 접수=`bg-primary`, 현장확인=`bg-info`, 부품준비=`bg-warning`, 수리/교체=`bg-orange`, 완료=`bg-success`, 보류=`bg-secondary`
- 버튼: `btn btn-xs btn-outline-primary`
- 텍스트 말줄임: `text-truncate`, max-width 지정

### 3.3 GET /warranty/list -- 보증 목록

**템플릿**: `templates/warranty_list.html` (기존 파일 재설계)

```python
@warranty_bp.route('/warranty/list')
@login_required
def warranty_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 50
    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()      # active/expired/all
    type_filter = request.args.get('type', '').strip()           # 일반/우수제품/혁신제품
    item_filter = request.args.get('item_group', '').strip()     # 품목유형
    sort = request.args.get('sort', 'end_asc').strip()

    with get_db() as db:
        query = db.query(Warranty)  # JOIN 없음 (비정규화)

        # 검색 (contract_name, project_name, model_name 통합)
        if q:
            like = f'%{q}%'
            query = query.filter(
                (Warranty.contract_name.ilike(like))
                | (Warranty.project_name.ilike(like))
                | (Warranty.model_name.ilike(like))
            )

        # 필터: 상태
        today = datetime.date.today()
        if status_filter == 'active':
            query = query.filter(Warranty.warranty_end >= today)
        elif status_filter == 'expired':
            query = query.filter(Warranty.warranty_end < today)

        # 필터: 보증유형
        if type_filter:
            query = query.filter(Warranty.warranty_type == type_filter)

        # 필터: 품목유형
        if item_filter:
            query = query.filter(Warranty.item_group == item_filter)

        # 정렬
        sort_map = {
            'end_asc': Warranty.warranty_end.asc(),
            'end_desc': Warranty.warranty_end.desc(),
            'start_desc': Warranty.warranty_start.desc(),
            'name_asc': Warranty.project_name.asc(),
        }
        query = query.order_by(sort_map.get(sort, Warranty.warranty_end.asc()))

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        warranties = query.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

    return render_template('warranty_list.html',
        warranties=warranties,
        pagination=pagination,
        filters={'q': q, 'status': status_filter, 'type': type_filter,
                 'item_group': item_filter, 'sort': sort},
        today=datetime.date.today(),
    )
```

#### 테이블 컬럼

| # | 컬럼 | 원본 | 비고 |
|---|------|------|------|
| 1 | 현장명 | `project_name` | text-truncate, max-width: 200px |
| 2 | 계약명 | `contract_name` | text-truncate, max-width: 180px |
| 3 | 품목 | `item_group` | badge |
| 4 | 모델명 | `model_name` | text-truncate |
| 5 | 수량 | `quantity` | 우측정렬 |
| 6 | 보증유형 | `warranty_type` | badge (우수=blue, 혁신=purple, 일반=gray) |
| 7 | 시작일 | `warranty_start` | |
| 8 | 만료일 | `warranty_end` | D-day 뱃지 |
| 9 | 상태 | computed | 진행중/만료 |
| 10 | A/S | case count | 링크 |

### 3.4 GET /warranty/case/create -- A/S 접수

**템플릿**: `templates/warranty_case_create.html` (신규, 기존 `warranty_create.html` 대체)

#### 접수 흐름

```
Step 1: 계약 검색 (AJAX)
  ┌──────────────────────────────────────────────────────┐
  │  [검색 input] 현장명/관리번호/모델명 입력             │
  │  → POST /warranty/api/search-contract                │
  │  → 검색 결과 드롭다운 (card shadow-sm)                │
  │  → 선택 시 자동 채움:                                 │
  │    - 현장명, 계약명, 품목, 모델, 수량                  │
  │    - 보증기간, 남은일수                                │
  │    - 유상/무상 자동판별 + badge 표시                    │
  └──────────────────────────────────────────────────────┘

Step 2: A/S 정보 입력
  ┌──────────────────────────────────────────────────────┐
  │  하자유형: [select - 13개 옵션]                       │
  │  증상: [textarea]                                     │
  │  접수경로: [radio: 전화/카톡/이메일/방문]              │
  │                                                       │
  │  고객 정보:                                           │
  │    담당자명: [input]  전화번호: [input]                │
  │                                                       │
  │  교체 부품 (동적 행 추가):                             │
  │    [부품명] [모델명] [수량] [단가] [+추가] [-삭제]     │
  │                                                       │
  │  발송 방법: [select: 택배/방문/직접수령]               │
  │  담당자 배정: [select - 사용자 목록]                   │
  └──────────────────────────────────────────────────────┘

Step 3: 확인 및 저장
  ┌──────────────────────────────────────────────────────┐
  │  유상/무상: [badge 자동 표시, 수동 변경 가능]          │
  │  [저장 btn-primary] [취소 btn-secondary]              │
  └──────────────────────────────────────────────────────┘
```

#### POST 처리

```python
@warranty_bp.route('/warranty/case/create', methods=['GET', 'POST'])
@login_required
def warranty_case_create():
    with get_db() as db:
        if request.method == 'POST':
            warranty_id = safe_int(request.form.get('warranty_id'))
            warranty = db.query(Warranty).get(warranty_id) if warranty_id else None

            # 유상/무상 자동판별
            today = datetime.date.today()
            is_chargeable = False
            if warranty and warranty.warranty_end:
                is_chargeable = warranty.warranty_end < today

            # 수동 오버라이드 허용
            manual_chargeable = request.form.get('is_chargeable')
            if manual_chargeable is not None:
                is_chargeable = manual_chargeable == '1'

            case_no = _next_case_no(db)
            user_name = session.get('full_name', '사용자')

            # 비정규화 데이터
            contract_name = None
            item_group = None
            model_name = None
            if warranty:
                contract_name = warranty.contract_name
                item_group = warranty.item_group
                model_name = warranty.model_name

            case = WarrantyCase(
                warranty_id=warranty.id if warranty else None,
                project_id=warranty.project_id if warranty else None,
                case_no=case_no,
                defect_type=request.form.get('defect_type', 'OTHER'),
                symptom=request.form.get('symptom', '').strip(),
                status='접수',
                reported_by=request.form.get('reported_by', '').strip(),
                reported_date=parse_date(request.form.get('reported_date')) or today,
                assigned_to=request.form.get('assigned_to', '').strip(),
                created_by=user_name,
                # 유상/무상
                is_chargeable=is_chargeable,
                charge_amount=safe_int(request.form.get('charge_amount')),
                charge_status='미청구' if is_chargeable else None,
                # 고객 정보
                request_channel=request.form.get('request_channel'),
                customer_name=request.form.get('customer_name', '').strip(),
                customer_phone=request.form.get('customer_phone_input', '').strip(),
                # 부품 JSON
                parts_json=request.form.get('parts_json', '[]'),
                # 물류
                shipping_method=request.form.get('shipping_method'),
                # 비정규화
                contract_name=contract_name,
                item_group=item_group,
                model_name=model_name,
            )
            # ... 이하 기존 로직 (flush, log, commit)
```

### 3.5 POST /warranty/api/search-contract -- 계약검색 AJAX

```python
@warranty_bp.route('/warranty/api/search-contract', methods=['POST'])
@login_required
def api_search_contract():
    q = request.json.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    with get_db() as db:
        like = f'%{q}%'
        # Warranty 테이블만 검색 (비정규화 필드 활용)
        results = (
            db.query(Warranty)
            .filter(
                (Warranty.contract_name.ilike(like))
                | (Warranty.project_name.ilike(like))
                | (Warranty.model_name.ilike(like))
            )
            .order_by(Warranty.warranty_end.desc())
            .limit(20)
            .all()
        )

        today = datetime.date.today()
        data = []
        for w in results:
            days_left = (w.warranty_end - today).days if w.warranty_end else None
            data.append({
                'warranty_id': w.id,
                'contract_name': w.contract_name,
                'project_name': w.project_name,
                'item_group': w.item_group,
                'model_name': w.model_name,
                'quantity': w.quantity,
                'warranty_type': w.warranty_type,
                'warranty_start': w.warranty_start.isoformat() if w.warranty_start else None,
                'warranty_end': w.warranty_end.isoformat() if w.warranty_end else None,
                'days_left': days_left,
                'is_expired': days_left is not None and days_left < 0,
                'is_chargeable': days_left is not None and days_left < 0,
            })

    return jsonify(data)
```

### 3.6 GET/POST /warranty/case/<id> -- A/S 상세

**템플릿**: `templates/warranty_case_detail.html` (신규, 기존 `warranty_detail.html` 대체)

#### 화면 구성

```
┌─── 케이스 헤더 ──────────────────────────────────────────────┐
│  AS-2026-001 | [badge 상태] | [badge 유상/무상]              │
│  현장: OO공원 LED 투광등 | 접수일: 2026-03-21 | 담당: 홍길동  │
└──────────────────────────────────────────────────────────────┘

┌─── 상태 프로세스 바 ─────────────────────────────────────────┐
│  [접수] → [현장확인] → [부품준비] → [수리/교체] → [완료]      │
│  현재 단계 active 표시, form="status-form" 외부 폼            │
└──────────────────────────────────────────────────────────────┘

┌─── 2컬럼 레이아웃 ───────────────────────────────────────────┐
│  좌측 (col-md-8):                                            │
│  ┌─ 기본 정보 (card) ──────────────────────────┐             │
│  │  하자유형, 증상, 원인분석, 조치내용           │             │
│  └──────────────────────────────────────────────┘             │
│  ┌─ 교체 부품 (card) ──────────────────────────┐             │
│  │  테이블: 부품명 | 모델 | 수량 | 단가 | 소계  │             │
│  │  합계: XXX원                                 │             │
│  └──────────────────────────────────────────────┘             │
│  ┌─ 물류 정보 (card) ──────────────────────────┐             │
│  │  발송방법 | 송장번호 | 발송일                │             │
│  └──────────────────────────────────────────────┘             │
│  ┌─ 비용 (card) ───────────────────────────────┐             │
│  │  유상/무상 | 금액 | 청구상태                  │             │
│  └──────────────────────────────────────────────┘             │
│                                                               │
│  우측 (col-md-4):                                            │
│  ┌─ 타임라인 (card) ───────────────────────────┐             │
│  │  WarrantyCaseLog 역순 표시                   │             │
│  │  상태변경 / 메모 / 부품발송 이력              │             │
│  └──────────────────────────────────────────────┘             │
│  ┌─ 고객 정보 (card) ──────────────────────────┐             │
│  │  담당자 | 전화번호 | 접수경로                 │             │
│  └──────────────────────────────────────────────┘             │
│  ┌─ 보증 정보 (card) ──────────────────────────┐             │
│  │  보증기간 | 남은일수 | 유형                   │             │
│  │  [제품 이력카드 링크]                         │             │
│  └──────────────────────────────────────────────┘             │
└──────────────────────────────────────────────────────────────┘
```

#### warranty_actions.py 확장

기존 `handle_warranty_action` 함수에 다음 액션을 추가한다:

```python
elif action == 'update_parts':
    parts_json = form.get('parts_json', '[]')
    case.parts_json = parts_json
    db.add(WarrantyCaseLog(
        case_id=case.id, log_type='note',
        content='교체 부품 업데이트',
        created_by=user_name,
    ))

elif action == 'update_shipping':
    case.shipping_method = form.get('shipping_method', '').strip()
    case.shipping_tracking = form.get('shipping_tracking', '').strip()
    case.shipping_date = parse_date(form.get('shipping_date'))
    db.add(WarrantyCaseLog(
        case_id=case.id, log_type='note',
        content=f'물류 업데이트: {case.shipping_method} / {case.shipping_tracking}',
        created_by=user_name,
    ))

elif action == 'update_charge':
    case.is_chargeable = form.get('is_chargeable') == '1'
    case.charge_amount = safe_int(form.get('charge_amount'))
    case.charge_status = form.get('charge_status', '').strip()
    db.add(WarrantyCaseLog(
        case_id=case.id, log_type='note',
        content=f'비용 업데이트: {"유상" if case.is_chargeable else "무상"} {case.charge_amount:,}원',
        created_by=user_name,
    ))
```

> 폼 중첩 금지 원칙: 각 액션 폼은 `form="action-form-id"` 속성으로 외부 참조.

### 3.7 GET /warranty/<id>/product-history -- 제품 이력카드

```python
@warranty_bp.route('/warranty/<int:warranty_id>/product-history')
@login_required
def product_history(warranty_id):
    with get_db() as db:
        warranty = db.query(Warranty).options(
            joinedload(Warranty.contract).joinedload(Contract.items),
            joinedload(Warranty.contract).joinedload(Contract.deliveries),
            joinedload(Warranty.cases).joinedload(WarrantyCase.logs),
            joinedload(Warranty.project),
        ).get(warranty_id)

        if not warranty:
            flash('보증 정보를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('warranty.warranty_dashboard'))

        # BOM 정보 (있으면)
        bom_data = None
        if warranty.contract and warranty.contract.items:
            first_item = warranty.contract.items[0]
            bom = db.query(Bom).filter_by(
                finished_item_id=first_item.id
            ).first()
            if bom:
                bom_data = bom

    return render_template('warranty_product_history.html',
        warranty=warranty,
        bom_data=bom_data,
        today=datetime.date.today(),
    )
```

#### 이력카드 레이아웃

```
┌─── 제품 이력카드 ────────────────────────────────────────────┐
│  [현장명] | [계약명] | [보증유형 badge]                       │
│                                                              │
│  ┌─ 계약 정보 ─────────────────────────────────┐             │
│  │  계약일 | 납품기한 | 세금계산서일 | 입금일    │             │
│  │  품목: [item_group] | 모델: [model_name]     │             │
│  │  수량: [quantity]                            │             │
│  └──────────────────────────────────────────────┘             │
│                                                              │
│  ┌─ 제품 사양 (BOM) ──────────────────────────┐              │
│  │  BOM 부품 테이블 (있으면 표시)               │              │
│  └──────────────────────────────────────────────┘             │
│                                                              │
│  ┌─ 보증 상태 ─────────────────────────────────┐             │
│  │  시작: YYYY-MM-DD | 만료: YYYY-MM-DD        │             │
│  │  남은 기간: D-day badge | 유상/무상 badge     │             │
│  └──────────────────────────────────────────────┘             │
│                                                              │
│  ┌─ A/S 이력 타임라인 ────────────────────────┐              │
│  │  AS-2026-001 | 접수 | SMPS 교체 | 완료      │              │
│  │  AS-2026-003 | 접수 | 결로 점검 | 진행중     │              │
│  └──────────────────────────────────────────────┘             │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. 성능 최적화

### 4.1 목록 조회 -- Warranty 테이블만 (JOIN 0개)

비정규화 필드를 활용하여 `/warranty/list` 목록 조회 시 JOIN을 완전히 제거한다.

| 기존 쿼리 | 재설계 쿼리 |
|----------|-----------|
| `Warranty` + `joinedload(Contract)` + `joinedload(Project)` + `joinedload(Contract.items)` | `db.query(Warranty).filter(...).limit(50)` |
| JOIN 3개, N+1 위험 | JOIN 0개, 단일 테이블 스캔 |

### 4.2 상세 조회 -- joinedload 사용

상세 페이지(`/warranty/case/<id>`, `/warranty/<id>/product-history`)에서만 필요한 관계를 eager loading:

```python
# A/S 상세
case = db.query(WarrantyCase).options(
    joinedload(WarrantyCase.warranty).joinedload(Warranty.contract),
    joinedload(WarrantyCase.project),
    joinedload(WarrantyCase.logs),
).get(case_id)

# 제품 이력카드
warranty = db.query(Warranty).options(
    joinedload(Warranty.contract).joinedload(Contract.items),
    joinedload(Warranty.contract).joinedload(Contract.deliveries),
    joinedload(Warranty.cases),
    joinedload(Warranty.project),
).get(warranty_id)
```

### 4.3 인덱스 전략

| 인덱스 | 대상 쿼리 | 효과 |
|--------|----------|------|
| `idx_warranty_end` | 만료임박 조회, 정렬 | 1,206건 range scan |
| `idx_warranty_type` | 보증유형 필터 | 선택도 3 (일반/우수/혁신) |
| `idx_case_status` | 진행중 케이스 필터 | 선택도 6 |
| `idx_case_reported` | 접수일 역순 정렬 | covering index |

### 4.4 대시보드 쿼리 최적화

통계 쿼리를 `.count()` + `func.count`로 처리하여 전체 레코드 로딩을 방지한다.

```python
# 기존 (비효율): all_cases = db.query(WarrantyCase).all() 후 Python 순회
# 재설계 (효율): SQL 집계
active_count = db.query(Warranty).filter(Warranty.warranty_end >= today).count()
```

---

## 5. 유상/무상 자동판별 로직

### 5.1 핵심 로직

```python
def determine_chargeable(warranty, today=None):
    """보증기간 기준 유상/무상 자동판별

    Args:
        warranty: Warranty 객체
        today: 기준일 (None이면 오늘)

    Returns:
        bool: True=유상 (보증 만료), False=무상 (보증 내)
    """
    if today is None:
        today = datetime.date.today()

    if not warranty or not warranty.warranty_end:
        return True  # 보증 정보 없음 -> 유상 처리

    if warranty.warranty_end < today:
        return True   # 보증 만료 -> 유상
    else:
        return False  # 보증 내 -> 무상
```

### 5.2 적용 시점

1. **A/S 접수 시** (`/warranty/case/create` POST): 자동 판별 후 `is_chargeable` 세팅
2. **계약 검색 AJAX** (`/warranty/api/search-contract`): 검색 결과에 `is_chargeable` 포함
3. **수동 오버라이드 가능**: 담당자가 판단하여 유상<->무상 변경 (변경 시 로그 기록)

### 5.3 UI 표시

```html
<!-- 유상 -->
<span class="badge bg-danger">유상</span>
<!-- 무상 -->
<span class="badge bg-success">무상</span>
<!-- 보증 없음 -->
<span class="badge bg-secondary">보증 미등록</span>
```

---

## 6. 구현 순서 (의존성 기반)

```
Phase 1 (Day 1): DB 모델 + 마이그레이션
  ├─ 1-1. misc_entities.py: Warranty 비정규화 필드 8개 추가
  ├─ 1-2. misc_entities.py: WarrantyCase 신규 필드 12개 추가
  ├─ 1-3. misc_entities.py: DEFECT_TYPES 13개, CASE_STATUS_STEPS 6단계
  ├─ 1-4. misc_entities.py: WarrantyCase.parts property 추가
  ├─ 1-5. sql_editer.sql: ALTER TABLE + CREATE INDEX 구문 추가
  ├─ 1-6. DB 마이그레이션 실행 (PostgreSQL)
  ├─ 1-7. warranty_auto.py: 비정규화 데이터 수집 추가
  ├─ 1-8. warranty_auto.py: 혁신제품 판별 보강
  └─ 1-9. backfill_warranty_denorm() 실행 (1,206건)

Phase 2 (Day 2): 대시보드 + 보증 목록
  ├─ 2-1. routes/warranty.py: warranty_dashboard() 라우트
  ├─ 2-2. templates/warranty_dashboard.html: 대시보드 UI
  ├─ 2-3. routes/warranty.py: warranty_list() 라우트 재설계
  ├─ 2-4. templates/warranty_list.html: 보증 목록 UI 재설계
  └─ 의존: Phase 1 (비정규화 필드 존재해야 목록 조회 가능)

Phase 3 (Day 3): A/S 접수 + 상세 + 제품 이력
  ├─ 3-1. routes/warranty.py: warranty_case_create() 재설계
  ├─ 3-2. routes/warranty.py: api_search_contract() AJAX
  ├─ 3-3. templates/warranty_case_create.html: 접수 UI
  ├─ 3-4. routes/warranty.py: warranty_detail() 재설계
  ├─ 3-5. templates/warranty_case_detail.html: 상세 UI
  ├─ 3-6. warranty_actions.py: update_parts/shipping/charge 액션
  ├─ 3-7. routes/warranty.py: product_history() 라우트
  ├─ 3-8. templates/warranty_product_history.html: 이력카드 UI
  └─ 의존: Phase 2 (대시보드에서 접수 페이지로 진입)

Phase 4 (Day 4): MCP + 검증
  ├─ 4-1. light_sync_mcp/tools/warranty.py: MCP 도구 업데이트
  ├─ 4-2. 전체 기능 검증
  └─ 의존: Phase 3 (모든 라우트 완성 후)
```

---

## 7. 검증 계획

### 7.1 DB 검증

| 항목 | 검증 방법 | 기대 결과 |
|------|----------|----------|
| ALTER TABLE 실행 | sql_editer.sql 실행 후 `\d warranties`, `\d warranty_cases` | 신규 컬럼 존재 |
| 인덱스 생성 | `\di` | 4개 인덱스 존재 |
| 백필 스크립트 | `SELECT count(*) FROM warranties WHERE contract_name IS NOT NULL` | 1,206건 (contract_id 있는 것 전부) |

### 7.2 기능 검증

| 항목 | 검증 방법 | 기대 결과 |
|------|----------|----------|
| 대시보드 로딩 | `/warranty` 접속 | 보증현황 4개 카드 + 만료임박 + 진행중 케이스 |
| 보증 목록 필터 | 상태=진행중 필터 적용 | 258건 표시 |
| 보증 목록 검색 | 현장명 검색 | 해당 보증만 필터링 |
| 페이지네이션 | 2페이지 이동 | 51~100번째 보증 표시 |
| 계약 검색 AJAX | "LED" 입력 | 관련 보증 목록 반환 (JSON) |
| A/S 접수 (무상) | 진행중 보증 선택 -> 접수 | is_chargeable=False, 케이스 생성 |
| A/S 접수 (유상) | 만료 보증 선택 -> 접수 | is_chargeable=True, charge_status='미청구' |
| 상태 변경 | 접수 -> 현장확인 | 로그 기록, site_visit_date 자동 세팅 |
| 부품 등록 | parts_json 저장 | JSON 파싱 후 테이블 표시 |
| 물류 업데이트 | 송장번호 입력 | 로그 기록 |
| 제품 이력카드 | `/warranty/1/product-history` | 계약+보증+A/S 통합 표시 |

### 7.3 성능 검증

| 항목 | 검증 방법 | 기대 결과 |
|------|----------|----------|
| 목록 조회 쿼리 | SQLAlchemy echo=True | Warranty 테이블 단일 SELECT (JOIN 없음) |
| 대시보드 로딩 | 브라우저 DevTools Network | 500ms 이내 |
| 인덱스 활용 | `EXPLAIN ANALYZE` | idx_warranty_end 사용 |

### 7.4 엣지 케이스

| 항목 | 시나리오 | 기대 결과 |
|------|---------|----------|
| 보증 없는 접수 | warranty_id=None (수기입력) | manual_ 필드 사용, is_chargeable=True |
| 보증 날짜 없음 | warranty_end=None | is_chargeable=True (보증 정보 없음) |
| 동일 보증 복수 A/S | 같은 warranty_id로 2건 접수 | 각각 별도 case_no 채번 |
| 비정규화 누락 백필 | contract_id 없는 보증 | skip (contract_name=None 유지) |

---

## 8. 파일 변경 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `modules/models/misc_entities.py` | 수정 | Warranty/WarrantyCase 필드 추가, 상수 확장 |
| `modules/services/warranty_auto.py` | 수정 | 비정규화 수집, 혁신판별 보강, 백필 함수 |
| `modules/services/warranty_actions.py` | 수정 | 부품/물류/비용 액션 추가 |
| `routes/warranty.py` | 재설계 | 대시보드/목록/접수/상세/이력/AJAX |
| `sql_editer.sql` | 추가 | ALTER TABLE + CREATE INDEX |
| `templates/warranty_dashboard.html` | 신규 | A/S 대시보드 |
| `templates/warranty_list.html` | 재설계 | 보증 목록 |
| `templates/warranty_case_create.html` | 신규 | A/S 접수 |
| `templates/warranty_case_detail.html` | 신규 | A/S 상세 |
| `templates/warranty_product_history.html` | 신규 | 제품 이력카드 |
| `light_sync_mcp/tools/warranty.py` | 수정 | MCP 도구 업데이트 |
