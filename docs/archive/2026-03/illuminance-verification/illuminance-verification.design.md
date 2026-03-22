# Illuminance Verification Design

> Plan 참조: `docs/01-plan/features/illuminance-verification.plan.md`

---

## 1. Architecture Overview

```
routes/illuminance.py         ← Blueprint (ilv)
  │
  ├── GET  /illuminance                    → illuminance_list.html
  ├── GET  /illuminance/new                → illuminance_new.html
  ├── POST /illuminance/api/upload-pdf     → JSON {pages:[]}
  ├── POST /illuminance/api/parse-pages    → JSON {areas:[]}
  ├── POST /illuminance/new                → redirect /illuminance/<id>
  ├── GET  /illuminance/<id>               → illuminance_detail.html
  ├── GET  /illuminance/<id>/area/<aid>    → illuminance_area.html
  ├── POST /illuminance/<id>/area/<aid>/measure → redirect same
  ├── GET  /illuminance/<id>/report        → illuminance_report.html
  └── GET  /illuminance/api/area/<aid>/grid → JSON grid data

modules/services/illuminance_pdf_parser.py ← PDF 파싱 엔진
modules/models/entities.py                 ← 3개 모델 클래스 추가
modules/models/db.py                       ← 3개 테이블 생성
```

---

## 2. DB 모델 상세

### 2.1 엔티티 클래스 (`entities.py` 추가)

```python
class IlluminanceProject(Base):
    __tablename__ = 'illuminance_projects'
    id              = Column(Integer, primary_key=True)
    project_name    = Column(String, nullable=False)
    customer        = Column(String)
    location        = Column(String)
    install_date    = Column(Date)
    pdf_filename    = Column(String)          # 업로드 파일명 (UUID 포함)
    facility_type   = Column(String)          # 풋살장/축구장/테니스장/주차장/보행로
    status          = Column(String, default='design')  # design/measured/reported
    notes           = Column(Text)
    created_by      = Column(String)
    created_at      = Column(DateTime, default=func.now())
    areas           = relationship('IlluminanceArea', back_populates='project',
                                   cascade='all, delete-orphan')


class IlluminanceArea(Base):
    __tablename__ = 'illuminance_areas'
    id                  = Column(Integer, primary_key=True)
    project_id          = Column(Integer, ForeignKey('illuminance_projects.id'), nullable=False)
    area_name           = Column(String, nullable=False)
    area_index          = Column(Integer, default=1)
    # 설치조건
    installation_height = Column(Float)
    lamp_type           = Column(String)
    lamp_watt           = Column(Integer)
    lamp_qty            = Column(Integer)
    tower_qty           = Column(Integer)
    simulation_date     = Column(Date)
    # 설계 요약값
    design_eav          = Column(Float)
    design_emin         = Column(Float)
    design_emax         = Column(Float)
    design_uo           = Column(Float)
    design_ud           = Column(Float)
    maintenance_factor  = Column(Float)
    total_flux          = Column(Float)
    total_power         = Column(Float)
    power_per_area      = Column(Float)
    # 격자 메타
    grid_rows           = Column(Integer)
    grid_cols           = Column(Integer)
    grid_x_labels       = Column(Text)       # JSON: ["0m","2.3m",...]
    grid_y_labels       = Column(Text)       # JSON: ["0m","2m",...]
    design_grid         = Column(Text)       # JSON: [[423,538,...],...]
    # KS 기준
    ks_eav_min          = Column(Float)
    ks_uo_min           = Column(Float)
    created_at          = Column(DateTime, default=func.now())
    project             = relationship('IlluminanceProject', back_populates='areas')
    measurements        = relationship('IlluminanceMeasured', back_populates='area',
                                       cascade='all, delete-orphan')

    @property
    def design_grid_parsed(self):
        return json.loads(self.design_grid) if self.design_grid else []

    @property
    def grid_x_labels_parsed(self):
        return json.loads(self.grid_x_labels) if self.grid_x_labels else []

    @property
    def grid_y_labels_parsed(self):
        return json.loads(self.grid_y_labels) if self.grid_y_labels else []

    @property
    def latest_measurement(self):
        return self.measurements[-1] if self.measurements else None


class IlluminanceMeasured(Base):
    __tablename__ = 'illuminance_measured'
    id              = Column(Integer, primary_key=True)
    area_id         = Column(Integer, ForeignKey('illuminance_areas.id'), nullable=False)
    measure_date    = Column(Date, nullable=False)
    measured_by     = Column(String)
    weather         = Column(String)
    instrument      = Column(String)
    # 실측 요약 (격자에서 자동계산 후 저장)
    measured_eav    = Column(Float)
    measured_emin   = Column(Float)
    measured_emax   = Column(Float)
    measured_uo     = Column(Float)
    measured_ud     = Column(Float)
    # 격자
    measured_grid   = Column(Text)           # JSON: [[512,...],...] (null 허용)
    # 판정
    ks_pass         = Column(String)         # PASS/WARNING/FAIL
    eav_achievement = Column(Float)          # measured_eav / design_eav * 100
    uo_achievement  = Column(Float)
    notes           = Column(Text)
    created_at      = Column(DateTime, default=func.now())
    area            = relationship('IlluminanceArea', back_populates='measurements')
```

### 2.2 `db.py` 추가 (테이블 생성)

```python
# create_tables() 함수 내 추가
IlluminanceProject.__table__.create(bind=engine, checkfirst=True)
IlluminanceArea.__table__.create(bind=engine, checkfirst=True)
IlluminanceMeasured.__table__.create(bind=engine, checkfirst=True)
```

### 2.3 `sql_editer.sql` 기록

```sql
-- illuminance-verification 스키마 (2026-03-20)
CREATE TABLE IF NOT EXISTS illuminance_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    customer TEXT, location TEXT, install_date DATE,
    pdf_filename TEXT, facility_type TEXT,
    status TEXT DEFAULT 'design',
    notes TEXT, created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS illuminance_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES illuminance_projects(id) ON DELETE CASCADE,
    area_name TEXT NOT NULL, area_index INTEGER DEFAULT 1,
    installation_height REAL, lamp_type TEXT, lamp_watt INTEGER,
    lamp_qty INTEGER, tower_qty INTEGER, simulation_date DATE,
    design_eav REAL, design_emin REAL, design_emax REAL,
    design_uo REAL, design_ud REAL,
    maintenance_factor REAL, total_flux REAL, total_power REAL, power_per_area REAL,
    grid_rows INTEGER, grid_cols INTEGER,
    grid_x_labels TEXT, grid_y_labels TEXT, design_grid TEXT,
    ks_eav_min REAL, ks_uo_min REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS illuminance_measured (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER NOT NULL REFERENCES illuminance_areas(id) ON DELETE CASCADE,
    measure_date DATE NOT NULL, measured_by TEXT,
    weather TEXT, instrument TEXT,
    measured_eav REAL, measured_emin REAL, measured_emax REAL,
    measured_uo REAL, measured_ud REAL,
    measured_grid TEXT,
    ks_pass TEXT, eav_achievement REAL, uo_achievement REAL,
    notes TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. PDF 파싱 엔진 (`illuminance_pdf_parser.py`)

### 3.1 모듈 구조

```python
class ReluxPdfParser:
    def __init__(self, pdf_path: str):
        self.reader = PdfReader(pdf_path)
        self.pages = []  # [{index, type, text, preview, parsed}]

    def analyze_pages(self) -> list[dict]:
        """모든 페이지 타입 분류 + 텍스트 발췌 반환 (Step 2용)"""

    def parse_page(self, page_index: int) -> dict:
        """단일 페이지 파싱 — 격자 + 요약값 + 설치조건"""

    def _classify_page(self, text: str) -> str:
        """cover / floor_plan / summary / grid_table / 3d_view"""

    def _extract_summary(self, text: str) -> dict:
        """Eav, Emin, Emax, Uo, Ud 추출"""

    def _extract_grid(self, text: str) -> dict:
        """격자 숫자 배열 + X/Y 레이블 추출"""

    def _extract_conditions(self, text: str) -> dict:
        """높이, 기구, 와트, 수량, 타워수 추출 (cover 페이지)"""
```

### 3.2 페이지 분류 로직

```python
PATTERNS = {
    'grid_table': ['Table', '(E)', 'Calculation results', 'Eav', 'Emin', 'Emax'],
    'summary':    ['Result overview', 'Eav', 'Emin', 'Emax', 'Uniformity'],
    'cover':      ['조명높이', '조명기구', '조명수량', 'Installation', 'Date'],
    'floor_plan': ['Floor plan', '1 :', '[m]', 'N'],
    '3d_view':    ['3D view', '3D luminance', 'Luminance'],
}

def _classify_page(self, text):
    # grid_table 우선 판별 (숫자 격자 존재 여부)
    if re.search(r'Eav.*?:\s*\d+\s*lx', text) and re.search(r'(\d{3}\s+){5,}', text):
        return 'grid_table'
    # 나머지 패턴 매칭
    ...
```

### 3.3 격자 추출 로직

```python
def _extract_grid(self, text):
    lines = text.split('\n')
    grid_rows = []
    for line in lines:
        # (417) → 417, [789] → 789 마커 제거
        clean = re.sub(r'[\(\[\)\]]', '', line)
        nums = re.findall(r'\b\d{3,4}\b', clean)
        if len(nums) >= 6:  # 최소 6개 이상 숫자 = 격자 행으로 간주
            grid_rows.append([int(n) for n in nums])

    # X/Y 레이블 추출
    x_labels = self._extract_axis_labels(text, axis='x')  # "0 5 10 15..." 패턴
    y_labels = self._extract_axis_labels(text, axis='y')  # "0\n2\n4\n..." 패턴

    return {
        'grid': grid_rows,
        'rows': len(grid_rows),
        'cols': max(len(r) for r in grid_rows) if grid_rows else 0,
        'x_labels': x_labels,
        'y_labels': y_labels,
    }
```

---

## 4. 화면별 설계

### 4.1 `illuminance_list.html` — 목록

```
[다크 히어로 헤더]
  조도설계 검증    [+ 신규 등록]
  총 N건 | 설계등록 N | 실측완료 N | 분석완료 N

[상태 필터 탭] 전체 / 설계등록 / 실측대기 / 분석완료

[카드 그리드 col-md-6 col-lg-4]
  ┌──────────────────────────────┐
  │ 창원 가음정공원 풋살장  [설계등록] │
  │ 발주처: 창원시 / 설치: 2026-02-19│
  │ 구역 1개                         │
  │ 높이 12m · LED 800W · 12EA · 타워 2│
  │ ──────────────────────────────   │
  │ Eav 612 lx   Emin 417   Uo 0.68  │
  └──────────────────────────────┘
```

### 4.2 `illuminance_new.html` — 등록 마법사

**Step 1: 기본정보** (현장명*, 발주처, 설치위치, 설치일, 시설종류)

**Step 2: PDF 업로드 & 페이지 선택**
```
드래그 업로드 영역 → 업로드 완료 → 페이지 카드 표시

[페이지 1]  cover         창원 가음정공원...   □
[페이지 2]  floor_plan    Floor plan...        □
[페이지 3]  3d_view       3D view...           □
[페이지 4]  summary       Eav=612, Emin=417... □
[페이지 5]  summary       Evaluation area 1... □
[페이지 6]  grid_table ★  풋살장 Table (E)...  ☑ [구역명: 풋살장]
[페이지 7]  3d_view       3D luminance...      □
```
- `grid_table` 타입은 자동 체크 + 파란 강조 테두리
- 체크 시 구역명 입력 필드 노출

**Step 3: 파싱 확인**
- 선택 구역별 카드: 구역명 + 미니 히트맵(8×16 축소) + Eav/Emin/Emax/Uo
- 수정 필요 시 값 편집 가능
- [저장] 클릭 → POST

### 4.3 `illuminance_area.html` — 구역 상세 (핵심 화면)

```
breadcrumb: 조도검증 > 창원 풋살장 > 풋살장 구역
설치조건 인라인: 높이 12m · LED 800W · 12EA · 타워 2개 · 유지보수 0.90

[탭: 설계 히트맵] [탭: 실측 입력] [탭: 차이 분석]
```

**탭 1: 설계 히트맵**
- 범례 바 (파→초→빨) + min/max 표식
- 격자 히트맵 (Y축 반전: 14m=상단, 0m=하단)
- 우측 stat bar: Eav 612 / Emin 417 / Emax 789 / Uo 0.68 / Ud 0.53
- KS 기준: 풋살장 훈련 Eav≥300 ✅ / Uo≥0.50 ✅

**탭 2: 실측 입력**
- 한 줄 폼: 측정일 / 측정자 / 날씨[맑음/흐림/야간] / 기기명
- 격자 입력 (Y축 반전 동일, placeholder=설계값)
- 실시간 stat bar + KS 달성 뱃지
- 모바일: "순차입력 모드" 버튼 (풀스크린 모달)
- [저장] 버튼

**탭 3: 차이 분석** (실측 완료 후 활성화)
- 차이맵 (±% 색상)
- 요약 카드: Eav 달성률 94.4% / Uo 달성률 98.5% / KS PASS

### 4.4 `illuminance_report.html` — 리포트 (인쇄용)

A4 기준 레이아웃:
- 표지: 현장명, 발주처, 설치일, 측정일
- 구역별 페이지:
  - 설치조건 테이블
  - 설계 히트맵 (이미지 or 테이블)
  - 실측 테이블
  - 비교 요약 (달성률, KS 판정)
- 인쇄 CSS: `@media print { .no-print { display:none } }`

---

## 5. API 응답 형식

### POST `/illuminance/api/upload-pdf`
```json
{
  "success": true,
  "total_pages": 7,
  "pages": [
    {
      "index": 0,
      "page_num": 1,
      "type": "cover",
      "preview": "창원 가음정공원 못안마을 풋살장...",
      "auto_select": false
    },
    {
      "index": 5,
      "page_num": 6,
      "type": "grid_table",
      "preview": "풋살장 Table (E) — Eav: 612 lx, Emin: 417 lx",
      "auto_select": true,
      "suggested_name": "풋살장"
    }
  ],
  "upload_token": "abc123"   // 임시 파일 식별자
}
```

### POST `/illuminance/api/parse-pages`
```json
Request:
{
  "upload_token": "abc123",
  "selections": [
    { "page_index": 5, "area_name": "풋살장" }
  ]
}

Response:
{
  "success": true,
  "areas": [
    {
      "area_name": "풋살장",
      "page_index": 5,
      "design_eav": 612, "design_emin": 417, "design_emax": 789,
      "design_uo": 0.68, "design_ud": 0.53,
      "grid_rows": 8, "grid_cols": 16,
      "x_labels": ["0m","2.3m",...],
      "y_labels": ["0m","2m",...],
      "design_grid": [[423,538,...],...]
    }
  ]
}
```

### POST `/illuminance/<id>/area/<aid>/measure`
```
Form fields:
  measure_date, measured_by, weather, instrument, notes
  grid_data  (JSON string — 2D array, null for empty cells)
```

---

## 6. KS 기준 상수

```python
# modules/services/illuminance_pdf_parser.py 또는 constants.py
KS_STANDARDS = {
    '풋살장_훈련':    {'eav': 300, 'uo': 0.50},
    '풋살장_경기':    {'eav': 500, 'uo': 0.60},
    '축구장_훈련':    {'eav': 200, 'uo': 0.50},
    '테니스장_훈련':  {'eav': 300, 'uo': 0.60},
    '주차장_실외':    {'eav': 30,  'uo': 0.25},
    '보행로_일반':    {'eav': 15,  'uo': 0.40},
}

def get_ks_standard(facility_type: str) -> dict:
    return KS_STANDARDS.get(facility_type, {'eav': 0, 'uo': 0})

def judge_ks(measured_eav, measured_uo, ks_eav, ks_uo) -> str:
    eav_ok = measured_eav >= ks_eav
    uo_ok  = measured_uo  >= ks_uo
    if eav_ok and uo_ok:   return 'PASS'
    if eav_ok or uo_ok:    return 'WARNING'
    return 'FAIL'
```

---

## 7. 파일 업로드 처리

```python
UPLOAD_FOLDER = 'static/uploads/illuminance_pdf/'
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

def save_pdf(file) -> str:
    """UUID 기반 파일명으로 저장, 원본 파일명 반환"""
    ext = secure_filename(file.filename).rsplit('.', 1)[-1]
    saved_name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, saved_name))
    return saved_name
```

---

## 8. 구현 순서 (Do 단계)

| 단계 | 작업 | 파일 |
|------|------|------|
| 1 | DB 스키마 + 엔티티 클래스 | db.py, entities.py, sql_editer.sql |
| 2 | PDF 파싱 엔진 기본 | illuminance_pdf_parser.py |
| 3 | Blueprint + 목록/등록 routes | illuminance.py |
| 4 | 목록 템플릿 | illuminance_list.html |
| 5 | PDF 업로드 API + 페이지 선택 UI | illuminance_new.html |
| 6 | 파싱 API + 확인 UI | illuminance_new.html (Step 3) |
| 7 | 구역 상세 + 히트맵 탭 | illuminance_area.html |
| 8 | 실측 입력 + 저장 API | illuminance_area.html (탭 2) |
| 9 | 차이 분석 탭 | illuminance_area.html (탭 3) |
| 10 | 리포트 + app.py 등록 + 사이드바 | illuminance_report.html, base.html |

---

## 9. 디자인 통일성 체크리스트

- [x] `{% extends 'base.html' %}` — 모든 템플릿
- [x] `--mg-*` CSS 변수 사용 (새 커스텀 변수는 `--ilv-` 접두어)
- [x] 다크 히어로 헤더 (dashboard.html 패턴)
- [x] 카드 `shadow-sm` + `--mg-radius`
- [x] `white-space:nowrap` — 모든 뱃지/버튼
- [x] 숫자: `font-family: var(--mg-mono)`
- [x] 버튼 최대 `btn-sm`
- [x] Y축 반전 (높은 Y값 = 상단)
