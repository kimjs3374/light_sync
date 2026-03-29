# 가공발주 Design Document

> **Plan Reference**: `docs/01-plan/features/processing-order.plan.md`
> **Date**: 2026-03-22
> **Status**: Draft

---

## 1. Design Principles

기존 발주관리(PO) UI 패턴을 **그대로 계승**하여 사용자가 별도 학습 없이 사용 가능하게 설계.

| 원칙 | 적용 |
|------|------|
| **일관성** | page-hero, stat-card, filter-bar, info-card, section-num 등 기존 PO 패턴 동일 적용 |
| **차별성** | 가공 특화 요소만 추가 — DWG 첨부 영역, 가공유형 선택, 납기 하이라이트 |
| **디자인 토큰** | `magnatech.css` 변수 사용 (--mg-primary, --mg-ink, --mg-border 등) |

---

## 2. DB Schema

### 2.1 processing_orders

```sql
CREATE TABLE light_sync.processing_orders (
    id SERIAL PRIMARY KEY,
    fo_no VARCHAR(20) UNIQUE NOT NULL,           -- FO2026-001
    fo_date DATE NOT NULL,
    vendor_id INTEGER NOT NULL REFERENCES light_sync.vendors(id),
    processing_type VARCHAR(20) DEFAULT '외주가공', -- 사급가공 / 외주가공
    project_id INTEGER REFERENCES light_sync.projects(id),
    contract_id INTEGER REFERENCES light_sync.contracts(id),
    assigned_to INTEGER REFERENCES light_sync.users(id),
    status VARCHAR(20) DEFAULT '작성중',           -- 작성중/발주완료/가공중/입고완료/취소
    total_amount FLOAT DEFAULT 0,
    tax_amount FLOAT DEFAULT 0,
    note TEXT,
    created_by INTEGER REFERENCES light_sync.users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    history_log TEXT                               -- JSON 히스토리
);
```

### 2.2 processing_order_items

```sql
CREATE TABLE light_sync.processing_order_items (
    id SERIAL PRIMARY KEY,
    fo_id INTEGER NOT NULL REFERENCES light_sync.processing_orders(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES light_sync.items(id),
    item_name VARCHAR(300) NOT NULL,
    item_spec VARCHAR(500),
    quantity FLOAT DEFAULT 0,
    unit_price FLOAT DEFAULT 0,
    amount FLOAT DEFAULT 0,
    unit VARCHAR(50),
    delivery_date DATE,                            -- 납기일
    in_confirmed BOOLEAN DEFAULT FALSE,
    in_confirmed_at TIMESTAMP,
    bom_item_id INTEGER REFERENCES light_sync.bom_items(id),
    material_order_id INTEGER REFERENCES light_sync.material_orders(id),
    processing_note TEXT,                          -- 가공 사양 메모
    note TEXT
);
```

### 2.3 processing_order_files

```sql
CREATE TABLE light_sync.processing_order_files (
    id SERIAL PRIMARY KEY,
    fo_id INTEGER NOT NULL REFERENCES light_sync.processing_orders(id) ON DELETE CASCADE,
    file_name VARCHAR(500) NOT NULL,               -- 원본 파일명
    file_path VARCHAR(1000) NOT NULL,              -- Supabase Storage 경로
    file_size INTEGER DEFAULT 0,
    file_type VARCHAR(20),                         -- dwg/dxf/pdf/jpg/png/zip
    uploaded_by INTEGER REFERENCES light_sync.users(id),
    uploaded_at TIMESTAMP DEFAULT NOW()
);
```

### 2.4 ORM Models

```python
# modules/models/procurement_entities.py에 추가

FO_STATUS_CHOICES = ['작성중', '발주완료', '가공중', '입고완료', '취소']
FO_TYPE_CHOICES = ['사급가공', '외주가공']

class ProcessingOrder(Base):
    __tablename__ = 'processing_orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    fo_no = Column(String(20), unique=True, nullable=False)
    fo_date = Column(Date, nullable=False)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    processing_type = Column(String(20), default='외주가공')
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    assigned_to = Column(Integer, ForeignKey('users.id'), nullable=True)
    status = Column(String(20), default='작성중')
    total_amount = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    history_log = Column(Text, nullable=True)

    vendor = relationship("Vendor")
    project = relationship("Project", foreign_keys=[project_id])
    contract = relationship("Contract", foreign_keys=[contract_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    items = relationship("ProcessingOrderItem", back_populates="processing_order",
                         cascade="all, delete-orphan", order_by="ProcessingOrderItem.id")
    files = relationship("ProcessingOrderFile", back_populates="processing_order",
                         cascade="all, delete-orphan", order_by="ProcessingOrderFile.uploaded_at.desc()")

class ProcessingOrderItem(Base):
    __tablename__ = 'processing_order_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    fo_id = Column(Integer, ForeignKey('processing_orders.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=True)
    item_name = Column(String(300), nullable=False)
    item_spec = Column(String(500), nullable=True)
    quantity = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    unit = Column(String(50), nullable=True)
    delivery_date = Column(Date, nullable=True)
    in_confirmed = Column(Boolean, default=False)
    in_confirmed_at = Column(DateTime, nullable=True)
    bom_item_id = Column(Integer, ForeignKey('bom_items.id'), nullable=True)
    material_order_id = Column(Integer, ForeignKey('material_orders.id'), nullable=True)
    processing_note = Column(Text, nullable=True)
    note = Column(Text, nullable=True)

    processing_order = relationship("ProcessingOrder", back_populates="items")
    bom_item = relationship("BomItem", foreign_keys=[bom_item_id])
    material_order = relationship("MaterialOrder", foreign_keys=[material_order_id])

class ProcessingOrderFile(Base):
    __tablename__ = 'processing_order_files'
    id = Column(Integer, primary_key=True, autoincrement=True)
    fo_id = Column(Integer, ForeignKey('processing_orders.id'), nullable=False)
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_size = Column(Integer, default=0)
    file_type = Column(String(20), nullable=True)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.datetime.now)

    processing_order = relationship("ProcessingOrder", back_populates="files")
```

---

## 3. Route Design

### 3.1 Blueprint 등록

```python
# routes/processing_order.py
processing_order_bp = Blueprint('processing_order', __name__)

# app.py에 등록
app.register_blueprint(processing_order_bp)
```

### 3.2 Route 명세

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/processing-orders` | `fo_list()` | 목록 (통계+필터+테이블) |
| GET | `/processing-order/create` | `fo_create()` | 등록 폼 |
| POST | `/processing-order/create` | `fo_create()` | 등록 처리 |
| GET | `/processing-order/<fo_id>` | `fo_detail()` | 상세 조회 |
| POST | `/processing-order/<fo_id>/edit` | `fo_edit()` | 수정 처리 |
| POST | `/processing-order/<fo_id>/delete` | `fo_delete()` | 삭제 |
| POST | `/processing-order/<fo_id>/status` | `fo_change_status()` | 상태 변경 |
| POST | `/processing-order/<fo_id>/upload` | `fo_upload_file()` | 파일 업로드 |
| POST | `/processing-order/<fo_id>/file/<fid>/delete` | `fo_delete_file()` | 파일 삭제 |
| GET | `/processing-order/<fo_id>/file/<fid>/download` | `fo_download_file()` | 파일 다운로드 |
| POST | `/processing-order/<fo_id>/confirm-item/<item_id>` | `fo_confirm_item()` | 품목 입고확인 |
| POST | `/processing-order/<fo_id>/sync-production` | `fo_sync_production()` | 생산연동 |

### 3.3 번호 채번 규칙

```python
def _generate_fo_no():
    """FO{YYYY}-{NNN} 형식 자동 채번"""
    year = datetime.date.today().strftime('%Y')
    prefix = f'FO{year}-'
    last = db.session.query(ProcessingOrder)\
        .filter(ProcessingOrder.fo_no.like(f'{prefix}%'))\
        .order_by(ProcessingOrder.fo_no.desc()).first()
    if last:
        seq = int(last.fo_no.replace(prefix, '')) + 1
    else:
        seq = 1
    return f'{prefix}{seq:03d}'
```

---

## 4. UI Design — 기존 PO 패턴 계승

### 4.1 Design Token Reference (magnatech.css)

```
Colors:    --mg-ink:#0f172a  --mg-muted:#64748b  --mg-primary:#2563eb
           --mg-success:#16a34a  --mg-warning:#d97706  --mg-danger:#dc2626
Surface:   --mg-bg:#f8fafc  --mg-border:#e2e8f0
Font:      --mg-font:'DM Sans'  --mg-mono:'JetBrains Mono'
Radius:    --mg-radius:.65rem (cards)  .45rem (buttons/inputs)
Shadow:    --mg-shadow: 0 2px 12px rgba(15,23,42,.06)
```

### 4.2 목록 화면 (`fo_list.html`)

PO `po_list.html`과 **동일한 레이아웃 구조**를 사용합니다.

#### Page Hero
```
┌─────────────────────────────────────────────────────────────────┐
│  hero-eyebrow: "Fabrication Orders"                             │
│  h2: "가공발주 관리"                                              │
│  hero-sub: "외주 가공업체 발주, 도면 관리, 납품 추적을 관리합니다"     │
│                                          [+ 신규 가공발주]  btn  │
└─────────────────────────────────────────────────────────────────┘
```

#### 통계 카드 (stat-card-po 패턴 재사용)
```
┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐
│  12  │  │  2   │  │  3   │  │  5   │  │  2   │
│ 전체 │  │작성중│  │발주완료│ │가공중│  │입고완료│
│      │  │ 노랑 │  │ 파랑  │  │ 보라 │  │ 초록 │
└──────┘  └──────┘  └──────┘  └──────┘  └──────┘
col-4 col-md-2 (모바일 3열, 데스크탑 5열)
```

상태별 색상:
| 상태 | 배경 | 글자 | border-left |
|------|------|------|-------------|
| 작성중 | `#fef3c7` | `#92400e` | `#f59e0b` |
| 발주완료 | `#dbeafe` | `#1e40af` | `#3b82f6` |
| 가공중 | `#f3e8ff` | `#6b21a8` | `#a855f7` |
| 입고완료 | `#dcfce7` | `#166534` | `#22c55e` |
| 취소 | `#f1f5f9` | `#64748b` | `#94a3b8` |

#### 필터 바 (filter-bar 패턴)
```
┌─────────────────────────────────────────────────────────────────┐
│ [발주번호/업체명/품목명 검색___]  [상태 ▼]  [유형 ▼]  [검색][초기화] │
│                                         [업체별│날짜순] 토글     │
└─────────────────────────────────────────────────────────────────┘
```
- 유형 필터: 전체 / 사급가공 / 외주가공 (PO에 없는 추가 요소)

#### 목록 테이블 (po-table 패턴)

```
┌────────┬────────┬────────┬──────┬──────┬──────┬──────┬────────┬──┐
│ 발주번호│ 발주일 │ 업체   │ 유형 │ 현장 │ 상태 │ 합계 │ 납기   │📎│
├────────┼────────┼────────┼──────┼──────┼──────┼──────┼────────┼──┤
│FO2026- │03-22   │(주)OO │사급  │XX현장│가공중│1,200 │D-3 ⚠  │3 │
│001     │        │가공    │가공  │      │  🟣  │,000  │03-25   │  │
├────────┼────────┼────────┼──────┼──────┼──────┼──────┼────────┼──┤
│FO2026- │03-20   │△△산업 │외주  │YY현장│발주  │  800 │D+2 🔴 │1 │
│002     │        │        │가공  │      │완료  │,000  │지연!   │  │
└────────┴────────┴────────┴──────┴──────┴──────┴──────┴────────┴──┘
```

**납기 컬럼 특화 표시:**
- D-3 이하: `color: --mg-warning` + `⚠` 아이콘
- 지연(D+n): `color: --mg-danger` + `fw-bold` + `🔴`
- 여유(D-4+): `color: --mg-muted` (회색)

**📎 파일 컬럼**: 첨부파일 개수 표시 (0이면 `-`)

**행 클릭 → 상세** (기존 PO 패턴: `onclick="location.href=..."`)

#### 그룹핑 토글 (PO 패턴 재사용)
- **업체별**: vendor.name 기준 그룹 헤더 + 접기/펼치기
- **날짜순**: 그룹 헤더 없이 fo_date 내림차순 플랫 리스트

---

### 4.3 등록 화면 (`fo_create.html`)

PO `po_create.html` 섹션 패턴을 계승하되, **섹션 3개 구성** (기존 2개에서 +1).

#### 섹션 1: 가공발주 기본정보 (po-section, section-num 패턴)

```
┌─── ① 가공발주 기본정보 ───────────────────────────────────────────┐
│                                                                   │
│  가공업체 *             발주일 *           가공유형 *              │
│  [업체명 검색 자동완성][+]  [2026-03-22]   (●) 외주가공  (○) 사급가공│
│  ↳ TEL: 031-000-0000                                             │
│                                                                   │
│  담당자                연결 현장 (선택)      비고                   │
│  [김OO 대리 (본인) ▼]  [현장명 검색___]     [메모 입력___]         │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

- 가공업체: PO의 거래처 자동완성 + 신규등록 모달 **동일** (Vendor 테이블 공유)
- **가공유형**: 라디오 버튼 — `외주가공`(기본) / `사급가공`
- 연결 현장: PO의 계약검색 자동완성 **동일** 패턴

#### 섹션 2: 가공 품목 (itemsTable 패턴)

```
┌─── ② 가공 품목 ──────────────────────────────── [+ 품목 추가] ──┐
│                                                                  │
│  No │ 품명 *        │ 규격    │ 수량 │ 단위 │ 단가   │ 금액    │ 납기일   │ 가공메모 │ ✕ │
│  1  │ [폴 3단___][Q]│ [Φ165] │ [20] │ [EA] │ [150k] │ 3,000k │ [03-30] │ [SUS304]│ ✕ │
│  2  │ [브라켓__][Q] │ [200mm]│ [40] │ [EA] │ [25k]  │ 1,000k │ [04-02] │ [도면참조]│ ✕ │
│                                                                  │
│  ─────────────────────────────── 공급가액  4,000,000             │
│  ─────────────────────────────── 부가세      400,000             │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 합계      4,400,000             │
└──────────────────────────────────────────────────────────────────┘
```

PO 대비 **추가 컬럼**:
- **납기일**: `type="date"` — 품목별 개별 납기 관리
- **가공메모**: 가공 사양 특이사항 (SUS재질, 도금 등)

`colgroup` 비율:
```html
<col style="width:38px">  <!-- No -->
<col>                      <!-- 품명 (flex) -->
<col style="width:110px">  <!-- 규격 -->
<col style="width:68px">   <!-- 수량 -->
<col style="width:50px">   <!-- 단위 -->
<col style="width:95px">   <!-- 단가 -->
<col style="width:95px">   <!-- 금액 -->
<col style="width:105px">  <!-- 납기일 -->
<col style="width:110px">  <!-- 가공메모 -->
<col style="width:38px">   <!-- 삭제 -->
```

#### 섹션 3: 도면 첨부 (신규 섹션)

```
┌─── ③ 도면/파일 첨부 ─────────────────────────────────────────────┐
│                                                                   │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   │
│  │  📎 파일을 드래그하거나 클릭하여 업로드                        │   │
│  │     DWG, DXF, PDF, JPG, PNG, ZIP (최대 50MB)               │   │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘   │
│                                                                   │
│  (저장 후 파일 첨부 가능)                                          │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

파일 업로드 영역 스타일:
```css
.file-drop-zone {
    border: 2px dashed var(--mg-border);
    border-radius: var(--mg-radius);
    padding: 24px;
    text-align: center;
    color: var(--mg-muted);
    transition: all .2s;
    cursor: pointer;
}
.file-drop-zone:hover,
.file-drop-zone.drag-over {
    border-color: var(--mg-primary);
    background: #eff6ff;
    color: var(--mg-primary);
}
```

**등록 시에는 파일 업로드 비활성** (fo_id 필요) → 저장 후 상세에서 업로드.

#### 하단 버튼 (PO 동일)
```
                                         [취소]  [가공발주 저장]
```

---

### 4.4 상세 화면 (`fo_detail.html`)

PO `po_detail.html` 레이아웃을 **그대로 계승**하되, 가공 특화 영역 추가.

#### 상단 Hero (PO 동일 패턴)
```
┌─────────────────────────────────────────────────────────────────┐
│  hero-eyebrow: "Fabrication Order Detail"                       │
│  h2: "FO2026-001"  [가공중 🟣]                                   │
│  hero-sub: FO2026-001 | (주)OO가공 | 2026-03-22 | 사급가공        │
│                                      [목록] [삭제]              │
└─────────────────────────────────────────────────────────────────┘
```

#### 본문 레이아웃 (8:4 그리드)

```
┌──── col-md-8 ─────────────────────┬──── col-md-4 ─────────────┐
│                                    │                           │
│  ┌─ 가공발주 정보 (info-card) ──┐ │  ┌─ 금액 요약 ──────────┐ │
│  │ 발주번호  발주일  가공업체    │ │  │ 공급가액   4,000,000 │ │
│  │ 가공유형  담당자  이메일발송  │ │  │ 부가세       400,000 │ │
│  │ 현장      비고              │ │  │ ━━━━━━━━━━━━━━━━━━━ │ │
│  └─────────────────────────────┘ │  │ 합계       4,400,000 │ │
│                                    │  └───────────────────────┘ │
│                                    │                           │
│                                    │  ┌─ 상태 변경 ──────────┐ │
│                                    │  │ [발주완료 ▼] [변경]   │ │
│                                    │  └───────────────────────┘ │
│                                    │                           │
│                                    │  ┌─ 액션 버튼 ──────────┐ │
│                                    │  │ [생산관리 연동]       │ │
│                                    │  └───────────────────────┘ │
└────────────────────────────────────┴───────────────────────────┘

┌──── 가공 품목 (전폭) ─────────────────────────────────────────┐
│  No│ 품명/규격      │ 수량│ 단위│ 단가  │ 금액   │ 납기  │ 입고 │ 메모  │
│  1 │ 폴 3단 (Φ165) │  20│  EA│ 150k │ 3,000k│ 03-30│ [확인]│SUS304│
│  2 │ 브라켓 (200mm) │  40│  EA│  25k │ 1,000k│ 04-02│  ✅  │도면참조│
└───────────────────────────────────────────────────────────────┘

┌──── 첨부 파일 (전폭) ─────────────────────────────────────────┐
│                                                                │
│  ┌─ 도면/파일 ────────────────────────── [+ 파일 업로드] ────┐ │
│  │                                                            │ │
│  │  📐 tower_pole_v3.dwg       2.4 MB  03/22 14:30  [다운][삭제]│ │
│  │  📐 bracket_detail.dwg      850 KB  03/22 14:31  [다운][삭제]│ │
│  │  📄 가공사양서.pdf           120 KB  03/22 14:32  [다운][삭제]│ │
│  │                                                            │ │
│  │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   │ │
│  │  │  📎 파일을 드래그하거나 클릭하여 업로드              │   │ │
│  │  │     DWG, DXF, PDF, JPG, PNG, ZIP (최대 50MB)     │   │ │
│  │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

#### 품목 입고 확인 버튼
- 미입고 품목: `<button class="btn btn-success btn-xs">입고확인</button>`
- 입고완료 품목: `<span class="text-success fw-bold">✓ 03/25</span>`
- AJAX POST → 개별 품목 입고 확인 → MaterialOrder 자동 동기화

#### 납기일 표시 규칙
```
오늘 기준:
  D-3 이하  → badge bg-warning text-dark   "D-3 ⚠"
  지연(D+n) → badge bg-danger text-white   "D+2 지연"
  여유      → text-muted                    "03-30"
  입고완료  → text-success line-through     "03-30 ✓"
```

#### 파일 목록 아이콘
```
.dwg, .dxf → 📐
.pdf       → 📄
.jpg, .png → 🖼️
.zip       → 📦
```

#### 파일 업로드 로직
```javascript
// Supabase Storage 직접 업로드 (AJAX)
// 1. 서버에서 signed URL 발급
// 2. 클라이언트에서 직접 업로드
// 3. 완료 후 processing_order_files에 메타데이터 저장
// 4. 파일 목록 AJAX 갱신 (페이지 리로드 없음)
```

#### 수정 모달 (PO editModal 동일 패턴)
- `작성중` 상태에서만 수정 가능
- 모달 내부에 품목 테이블 + 행 추가/삭제

---

## 5. 상태 머신

```
                     ┌──────────┐
                     │  작성중   │
                     └────┬─────┘
                          │ [발주]
                     ┌────▼─────┐
        ┌────────────│ 발주완료  │────────────┐
        │            └────┬─────┘            │
        │                 │ [가공시작]         │
        │            ┌────▼─────┐            │
        │            │  가공중   │            │
        │            └────┬─────┘            │
        │                 │ [전체입고]         │
        │            ┌────▼─────┐            │
        │            │ 입고완료  │            │
        │            └──────────┘            │
        │                                     │
        │  [취소] (어디서든 가능)               │
        └──────────┐                ┌────────┘
                   ▼                ▼
              ┌──────────┐
              │   취소    │
              └──────────┘
```

### 상태 변경 시 자동 동작

| 전환 | 자동 동작 |
|------|----------|
| 작성중 → 발주완료 | `append_history_log("발주 확정")` |
| 발주완료 → 가공중 | `append_history_log("가공 시작")` |
| 품목 입고확인 (전체) | status → `입고완료`, MaterialOrder.outsourcing_status → `본사입고완료` |
| → 취소 | `append_history_log("취소")`, 연결된 MaterialOrder 해제 |

---

## 6. 생산 연동 로직

### 6.1 가공발주 → MaterialOrder 연결

```python
def _sync_fo_to_material_orders(db, fo):
    """가공발주 품목 → MaterialOrder 연결"""
    for item in fo.items:
        if item.material_order_id:
            continue  # 이미 연결됨
        # contract_item 기준으로 MaterialOrder 매칭
        if fo.contract_id:
            mat = MaterialOrder.query.filter_by(
                contract_id=fo.contract_id,
                material_name=item.item_name,
                is_outsourcing=True
            ).first()
            if mat:
                item.material_order_id = mat.id
                mat.outsourcing_status = '가공중'
                mat.order_date = fo.fo_date
    db.session.commit()
```

### 6.2 입고 확인 → MaterialOrder 갱신

```python
def _confirm_fo_item(db, fo, item):
    """품목 입고 확인 → MaterialOrder 자동 갱신"""
    item.in_confirmed = True
    item.in_confirmed_at = datetime.datetime.now()

    if item.material_order_id:
        mat = MaterialOrder.query.get(item.material_order_id)
        if mat:
            mat.outsourcing_status = '본사입고완료'
            mat.in_confirmed = True
            mat.in_confirmed_at = datetime.datetime.now()

    # 전체 품목 입고 완료 시 FO 상태 변경
    all_confirmed = all(i.in_confirmed for i in fo.items)
    if all_confirmed:
        fo.status = '입고완료'
        append_history_log(fo, '전체 입고 완료 → 상태변경')

    db.session.commit()
```

---

## 7. 파일 관리 (Supabase Storage)

### 7.1 Storage 구조
```
Bucket: processing-orders
Path:   processing-orders/{fo_no}/{filename}
예시:   processing-orders/FO2026-001/tower_pole_v3.dwg
```

### 7.2 업로드 Flow
```
클라이언트                      서버                    Supabase
   │                            │                        │
   │ POST /fo/{id}/upload       │                        │
   │  (multipart/form-data)     │                        │
   │ ──────────────────────────>│                        │
   │                            │ upload to storage      │
   │                            │ ──────────────────────>│
   │                            │        public URL      │
   │                            │ <──────────────────────│
   │                            │                        │
   │                            │ INSERT file record     │
   │     JSON { file_id, name } │                        │
   │ <──────────────────────────│                        │
   │                            │                        │
   │  (AJAX로 파일목록 갱신)      │                        │
```

### 7.3 허용 확장자 / 크기
```python
ALLOWED_EXTENSIONS = {'dwg', 'dxf', 'pdf', 'jpg', 'jpeg', 'png', 'zip'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
```

---

## 8. 메뉴 등록

### 8.1 config.py MENU_REGISTRY

```python
# 관리부 섹션, purchase_order 바로 뒤에 추가
("processing_order", {"label": "가공발주", "group": "관리부", "endpoint": "processing_order.fo_list"}),
```

### 8.2 기본 권한 설정
```python
# 관리부: processing_order:rw (읽기+쓰기)
# 영업부: processing_order:r (읽기만)
# 생산부: processing_order:r (입고 확인만 → 추후 rw 확장 가능)
```

---

## 9. Implementation Order

| # | 작업 | 파일 | 의존 |
|---|------|------|------|
| 1 | DB 모델 3개 추가 | `modules/models/procurement_entities.py` | - |
| 2 | 마이그레이션 SQL | `sql_editer.sql` | #1 |
| 3 | 라우트 기본 CRUD | `routes/processing_order.py` | #1 |
| 4 | 목록 템플릿 | `templates/fo_list.html` | #3 |
| 5 | 등록 템플릿 | `templates/fo_create.html` | #3 |
| 6 | 상세 템플릿 | `templates/fo_detail.html` | #3 |
| 7 | 파일 업로드/다운로드 | `routes/processing_order.py` | #3 |
| 8 | 상태 관리 + 히스토리 | `routes/processing_order.py` | #3 |
| 9 | 생산 연동 (MaterialOrder) | `routes/processing_order.py` | #3 |
| 10 | 메뉴 등록 + 권한 | `config.py` | #3 |

---

## 10. UI Consistency Checklist

기존 PO 화면과 1:1 대응하여 **일관성 보장**:

| UI 요소 | PO 원본 | 가공발주 적용 |
|---------|--------|-------------|
| page-hero | `hero-eyebrow` + `h2` + `hero-sub` | 동일 구조, 텍스트만 변경 |
| stat-card | `stat-card-po` + `stat-num` + `stat-label` | 동일 클래스명, 상태 색상만 추가 (가공중=보라) |
| filter-bar | `filter-bar` + 검색 + 상태 select | 동일 + 가공유형 select 추가 |
| 테이블 | `po-table` + `badge-status` | 동일 패턴 + 납기/파일 컬럼 추가 |
| 그룹핑 | `groupToggle` + `buildGroupHeader()` | 동일 JS 재사용 |
| 섹션 카드 | `po-section` + `section-num` | 동일 클래스, 섹션 3개 |
| 상세 레이아웃 | `info-card` 8:4 + `amount-card` | 동일 그리드 |
| 품목 테이블 | `items-table` + `colgroup` | 동일 + 납기/메모 컬럼 |
| 금액 요약 | `amount-card` + `amount-row` | 동일 |
| 수정 모달 | `editModal` 내 테이블 | 동일 패턴 |
| 삭제 모달 | `deleteModal` 빨강 헤더 | 동일 |
| 버튼 스타일 | `action-btn` + `btn-add-item` | 동일 |
| 자동완성 | `vendor-ac-dropdown` | 동일 JS 재사용 |
