# Design: vehicle-log

## Context Anchor (from Plan)

| Key | Value |
|-----|-------|
| WHY | 세법상 「업무용승용차 운행기록부」 의무 작성 + 종이 작성·집계 부담 제거 |
| WHO | 운전자(전직원, 모바일 등록) / 회계(PC 다운로드) / 임원진(현황) |
| RISK | 직전 odometer 자동채움 정확도, 영수증 용량, 차량 프리셋 화이트리스트 |
| SUCCESS | 모바일 30초 등록, PC 엑셀 1클릭 회계제출용 양식 다운로드 |
| SCOPE | 등록·조회·수정·삭제·엑셀 / 차량은 출장관리 프리셋 공유 / GPS·OCR 제외 |

## 1. Architecture (Selected: Option A — 단일 모듈 표준 구조)

기존 `business_trip` / `incoming_overview` 패턴 그대로:
- 신규 라우트 모듈 1개 (`routes/vehicle_log.py`) — PC HTML + 엑셀 다운로드
- 모바일 API는 `routes/app_api.py`에 엔드포인트 추가
- 모델은 `modules/models/misc_entities.py`에 `VehicleLog` 추가 (이력관리류 모델 모음 위치)
- PC 템플릿 1개 (`templates/vehicle_log_list.html`)
- 모바일 페이지 1개 (`mobile/src/pages/VehicleLogs.jsx`)

**대안 비교**:
- Option B: 출장관리 모듈에 통합 → 출장 ≠ 운행기록부(법적 별도 기록), 결합 비용 큼
- Option C: 신규 blueprint + 별도 admin 폴더 → 단일 메뉴 1기능에 과한 분리

## 2. Data Model

### 2.1 신규 테이블 `vehicle_logs`

```python
# modules/models/misc_entities.py 에 추가
class VehicleLog(Base):
    """업무용차량 운행기록부 (세법 별지서식 호환)"""
    __tablename__ = 'vehicle_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    use_date = Column(Date, nullable=False, index=True)              # 사용일자
    vehicle = Column(String(100), nullable=False, index=True)        # 차종(번호) — business_trip_vehicles 프리셋

    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    user_name = Column(String(50), nullable=False)                   # 성명 (스냅샷)
    user_department = Column(String(50), nullable=True)              # 부서 (스냅샷)
    user_position = Column(String(50), nullable=True)                # 직급 (스냅샷)

    odometer_start = Column(Integer, nullable=True)                  # 주행 전 km (자동채움, 수정 가능)
    odometer_end = Column(Integer, nullable=False)                   # 주행 후 km (필수)
    distance_km = Column(Integer, nullable=False)                    # 주행거리 = end - start (자동 계산, 저장)

    fuel_amount = Column(Integer, nullable=True)                     # 주유금액(원)
    origin = Column(String(200), nullable=False)                     # 출발지
    destination = Column(String(200), nullable=False)                # 도착지
    purpose = Column(Text, nullable=False)                           # 사용목적

    receipt_url = Column(Text, nullable=True)                        # 영수증 사진 URL (Supabase)

    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now,
                        onupdate=datetime.datetime.now)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index('ix_vehicle_logs_vehicle_date', 'vehicle', 'use_date'),
    )
```

### 2.2 ALTER TABLE (sql_editer.sql 추가)

```sql
CREATE TABLE light_sync.vehicle_logs (
  id SERIAL PRIMARY KEY,
  use_date DATE NOT NULL,
  vehicle VARCHAR(100) NOT NULL,
  user_id INTEGER REFERENCES light_sync.users(id),
  user_name VARCHAR(50) NOT NULL,
  user_department VARCHAR(50),
  user_position VARCHAR(50),
  odometer_start INTEGER,
  odometer_end INTEGER NOT NULL,
  distance_km INTEGER NOT NULL,
  fuel_amount INTEGER,
  origin VARCHAR(200) NOT NULL,
  destination VARCHAR(200) NOT NULL,
  purpose TEXT NOT NULL,
  receipt_url TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX ix_vehicle_logs_vehicle_date
  ON light_sync.vehicle_logs(vehicle, use_date DESC);
CREATE INDEX ix_vehicle_logs_user
  ON light_sync.vehicle_logs(user_id);
CREATE INDEX ix_vehicle_logs_use_date
  ON light_sync.vehicle_logs(use_date DESC);
```

### 2.3 차량 프리셋 공유 정책

- 출장관리 `business_trip_vehicles` 그대로 읽기
- "회사차량 화이트리스트" 헬퍼 (`_get_company_vehicles`):
  ```python
  EXCLUDED = {'개인차량', '대중교통', '기타', ''}
  def _get_company_vehicles(db):
      from routes.business_trip import _get_vehicle_choices
      return [v for v in _get_vehicle_choices(db) if v not in EXCLUDED]
  ```
- 운행일지 폼/엑셀 헤더는 회사차량만 노출

### 2.4 직전 odometer 조회

```python
def get_last_odometer(db, vehicle, before_date=None):
    q = db.query(VehicleLog).filter(VehicleLog.vehicle == vehicle)
    if before_date:
        q = q.filter(VehicleLog.use_date <= before_date)
    last = q.order_by(VehicleLog.use_date.desc(), VehicleLog.id.desc()).first()
    return last.odometer_end if last else None
```

## 3. API Contract

### 3.1 PC HTML
- `GET /vehicle-logs` → `templates/vehicle_log_list.html`
  - Query: `?vehicle=`, `?user_id=`, `?from=YYYY-MM-DD`, `?to=YYYY-MM-DD`
- `GET /vehicle-logs/<id>` → 상세 (모달 또는 별도 페이지)
- `POST /vehicle-logs/<id>/edit` → 수정
- `POST /vehicle-logs/<id>/delete` → 삭제
- `GET /vehicle-logs/export.xlsx` → 엑셀 다운로드 (양식 별지서식)
  - Query: `?vehicle=차량&year=2026` 필수, 기본 현재년도

### 3.2 Mobile JSON (`routes/app_api.py`)
- `GET /api/vehicle-logs?mine=1&limit=30` → 내 기록 목록
  ```json
  {"ok": true, "items": [{"id":1, "use_date":"2026-04-28", "vehicle":"쏘렌토 9539",
   "origin":"본사", "destination":"파주현장", "distance_km":45, "fuel_amount":50000}]}
  ```
- `GET /api/vehicle-logs/vehicles` → 회사차량 화이트리스트 + 직전 odometer
  ```json
  {"ok": true, "vehicles": [{"name":"쏘렌토 9539", "last_odometer":12345}]}
  ```
- `POST /api/vehicle-logs` → 신규 등록 (multipart/form-data, receipt 파일 포함 가능)
  - 요청: `use_date, vehicle, odometer_start, odometer_end, fuel_amount, origin, destination, purpose, receipt(file)`
  - 응답: `{"ok": true, "id": 123, "distance_km": 45}`
- `POST /api/vehicle-logs/<id>` → 수정 (본인만)
- `DELETE /api/vehicle-logs/<id>` → 삭제 (본인 or admin)

### 3.3 검증 규칙
- `odometer_end > odometer_start` (start 있는 경우)
- `distance_km` 서버에서 재계산 (클라이언트 값 신뢰 X)
- `fuel_amount >= 0`
- `vehicle` 화이트리스트 검증
- 영수증: `image/jpeg|png|webp`, ≤5MB

## 4. UI

### 4.1 PC (`templates/vehicle_log_list.html`)
- `page-hero` 헤더 (eyebrow: "Vehicle Log", title: "운행일지", sub: "업무용승용차 운행기록부")
- 상단 액션바: 차량 select / 사용자 select / 기간 from~to / 검색 / **[엑셀 다운로드]**
- 메인 테이블 (po-table 스타일):
  - 사용일자 | 차량 | 부서 | 성명 | 출발지 | 도착지 | 주행거리 | 주유금액 | 사용목적 | 영수증
  - white-space:nowrap, ellipsis, 정수 표시(`|int`)
  - 행 클릭 → 상세 모달
- 상세 모달: 운행기록 + 영수증 사진 큰 미리보기 + 수정/삭제 버튼

### 4.2 Mobile (`mobile/src/pages/VehicleLogs.jsx`)
- 헤더: "운행일지" + 우측 [+ 등록] 버튼
- 리스트: 카드(사용일자 · 차량 · 출발→도착 · {거리}km · {주유금액}원)
- + 클릭 → 등록 폼 시트:
  ```
  사용일자  [오늘 ▼ 자동]
  차량      [쏘렌토 9539 ▼]   ← 회사차량 화이트리스트
            └ 직전 기록: 2026-04-25 12,345km
  주행 전 km  [12,345]         ← 자동 채움, 수정 가능
  주행 후 km  [____] *필수
  주행거리    {auto: 0 km}     ← 실시간 계산
  주유금액   [____] (원, 선택)
  출발지     [____] *필수
  도착지     [____] *필수
  사용목적   [____] *필수
  영수증     [📷 사진 첨부] (선택)
  [취소] [등록]
  ```
- 카드 탭 → 상세 시트 (영수증 사진 포함, 본인이면 [수정][삭제] 노출)
- More 메뉴 → "운행일지" 항목 추가

### 4.3 엑셀 양식 (`modules/services/vehicle_log_excel.py`)
운행기록부.png 별지 양식 그대로 openpyxl 생성:
- 1행: 「【업무용승용차 운행기록부에 관한 별지 서식】<2016.4.1. 제정>」
- 2~3행: 사업연도(YYYY.01.01 ~ YYYY.12.31) | **업무용차량 운행기록부** | 법인명: ㈜매그나텍 | 사업자등록번호: 408-81-68519
- 4행: 1. 기본정보
- 5~6행: 차 종(번호) — 선택 차량명
- 7행: 2. 업무용 사용비율 계산
- 8~9행 (병합 헤더):
  - 사용일자 | 사용자(부서, 성명) | 운행 내역(주행 전 km, 주행 후 km, 주행거리, 주유금액, 목적지(출발지, 도착지), 사용목적)
- 10행~: 데이터 행 (use_date 오름차순)
- 합계행: 주행거리 합계, 주유금액 합계
- 컬럼 너비/병합/테두리/중앙정렬은 기존 `commencement_pdf.py` 스타일 참조

## 5. File Plan

| File | Action | Note |
|------|--------|------|
| `sql_editer.sql` | 추가 | CREATE TABLE vehicle_logs + 인덱스 3개 |
| `modules/models/misc_entities.py` | 추가 | VehicleLog 클래스 |
| `modules/models/__init__.py` | 수정 | VehicleLog export |
| `routes/vehicle_log.py` | 신규 | PC 라우트 (목록/상세/수정/삭제/엑셀) |
| `routes/app_api.py` | 추가 | 모바일 API 4개 |
| `templates/vehicle_log_list.html` | 신규 | PC 목록 + 상세 모달 |
| `modules/services/vehicle_log_excel.py` | 신규 | 별지서식 엑셀 생성 |
| `app.py` | 수정 | blueprint import + register |
| `config.py` | 수정 | MENU_REGISTRY `vehicle_log` 추가 + DEFAULT_GROUP_MENUS 4개 부서 권한 |
| `mobile/src/pages/VehicleLogs.jsx` | 신규 | 모바일 등록/목록 페이지 |
| `mobile/src/App.jsx` | 수정 | `/m/vehicle-logs` 라우트 등록 |
| `mobile/src/pages/More.jsx` | 수정 | 공통메뉴에 "운행일지" 추가 |
| `mobile/src/pages/lists.jsx` | (조건부) | 메뉴 매핑 필요 시 |

## 6. Implementation Order

1. **DB**: sql_editer.sql 작성 → Supabase에 ALTER TABLE 직접 실행
2. **Model**: VehicleLog 추가 + __init__.py export
3. **권한/메뉴**: config.py MENU_REGISTRY + DEFAULT_GROUP_MENUS 수정
4. **PC 라우트**: routes/vehicle_log.py (목록/CRUD/엑셀 stub)
5. **엑셀 서비스**: modules/services/vehicle_log_excel.py (별지서식)
6. **PC 템플릿**: templates/vehicle_log_list.html
7. **모바일 API**: routes/app_api.py 4개 엔드포인트 (직전 odometer 조회 포함)
8. **모바일 UI**: mobile/src/pages/VehicleLogs.jsx (frontend-architect 협업 가능)
9. **모바일 라우팅**: App.jsx + More.jsx
10. `systemctl restart light_sync` + `cd mobile && npm run build`
11. QA: 등록(자동채움 동작) → 목록 → 엑셀 다운로드(양식 일치) → 영수증 업로드/조회

## 7. Decisions (Open Questions 확정)

- **D1. 영수증 사진**: 엑셀 미임베드. PC 상세에서만 미리보기. (v2에서 ZIP 묶음 다운로드 옵션 검토)
- **D2. 업무사용비율**: 시스템 내 별도 계산 안 함 — 운행일지에 등록되는 모든 기록은 정의상 업무용. 엑셀 양식 하단 / 헤더에 **"업무사용비율: 100%"** 고정 표기. 사적사용 분리는 회계가 시스템 외부에서 처리.
- **D3. 주행 전 km 처리**: 직전 동일 차량 기록의 `odometer_end`를 `odometer_start`로 자동 채움. **직전 기록이 없는 첫 등록**은 사용자가 폼에서 직접 입력 (별도 fallback 토글 없음, 동일 입력란 사용). `distance_km`는 항상 `odometer_end - odometer_start`로 서버 계산.
