# Illuminance Verification Plan

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | Relux 시뮬레이션 설계값과 현장 실측조도를 별도로 관리하거나 비교할 수단이 없음. 납품 후 성능 검증이 불가능하고, 시공 품질 이슈 발생 시 근거 자료 부재 |
| Solution | PDF에서 설계조도 격자를 자동 파싱하여 저장하고, 현장 실측값 입력 UI를 제공한 뒤 설계 대비 달성률·KS 기준 판정·비교 리포트를 자동 생성 |
| Function UX Effect | PDF 업로드 1회로 설계값 자동 등록. 격자 히트맵으로 조도 분포 직관적 파악. 모바일 순차입력 모드로 현장에서 바로 실측값 입력. 구역별 비교 분석 리포트 PDF 즉시 출력 |
| Core Value | 조명 성능 데이터의 체계적 아카이빙 → 납품 품질 증빙 → 하자 분쟁 시 근거 자료 확보 → 고객 신뢰도 향상 |

---

## 1. Background

### 현재 문제

| # | 문제 | 영향 |
|---|------|------|
| 1 | 시뮬레이션 결과가 PDF로만 존재, 검색·비교 불가 | 납품현장 사후 관리 불가 |
| 2 | 현장 실측 기록이 없음 | 하자 시 근거 자료 없음 |
| 3 | 설계 vs 실측 비교 수단 없음 | 시공 품질 검증 불가 |
| 4 | 구역별 조도 편차 파악 불가 | 불균일 시공 미발견 |

### 샘플 PDF 분석 (창원 가음정공원 풋살장)

- **소프트웨어**: Relux (표준 조명 시뮬레이션 툴)
- **구조**: 7페이지 — 커버, 평면도, 3D뷰, 전체요약, 구역요약, 격자테이블, 3D휘도
- **핵심 데이터** (페이지 6):
  - 격자: **8행 × 16열** (Y: 0~14m @ 2m 간격 / X: 0~35m)
  - Eav=612 lx, Emin=417 lx, Emax=789 lx, Uo=0.68, Ud=0.53

### 중요 발견: 한 현장에 복수 구역

한 PDF 내에 여러 평가 구역이 존재 가능:
- 예: 테니스장 → 코트1, 코트2, 워밍업존, 복도 등 6~8구역
- 예: 이번 샘플 → 풋살장 전체(p4) + Evaluation area 1(p5) — 구역별 격자 각각 존재
- **설계 원칙**: 1 프로젝트 = N 구역 (1:N), 구역별 독립 격자 관리

---

## 2. Goal

1. Relux PDF 자동 파싱 → 설계조도 격자(구역별) 저장
2. 설계 격자 히트맵 UI + 현장 실측값 격자 입력 UI (병렬 표시)
3. 구역별 설계 vs 실측 비교: 달성률, KS 기준 판정, 차이맵
4. 비교 분석 리포트 PDF 출력 (납품처 제출용)
5. 모바일 현장 입력 완전 지원 (순차입력 모드)

---

## 3. Scope

### 3.1 In Scope

#### A. 프로젝트 관리 (`/illuminance`)
- 현장 목록: 상태별 (설계등록 / 실측대기 / 분석완료)
- 신규 등록: PDF 업로드 → 자동 파싱 → 구역별 설계값 확인/수정 → 저장
- 프로젝트 상세: 구역 탭 + 설계/실측/비교 탭

#### B. PDF 업로드 & 페이지 선택 워크플로우

Relux PDF는 커버/평면도/3D뷰/요약/격자테이블/휘도 등 다양한 페이지를 포함하며,
격자 데이터가 있는 페이지는 일부임. **사용자가 직접 페이지를 선택**해서 임포트.

**Step 1 — PDF 업로드**
- PDF 드래그 업로드 → 서버에서 페이지별 텍스트 추출

**Step 2 — 페이지 미리보기 & 선택**
- 전체 페이지 목록 표시 (페이지 번호 + 감지된 타입 + 텍스트 발췌)
- 페이지 타입 자동 분류:
  - `cover` — 프로젝트 정보, 설치조건
  - `floor_plan` — 평면도 이미지
  - `summary` — Eav/Emin/Emax/Uo 요약 (격자 없음)
  - **`grid_table`** — 격자 숫자 테이블 ← **선택 대상**
  - `3d_view` — 3D 이미지
- 사용자가 격자 데이터를 가져올 페이지 **체크박스 선택**
- 선택한 페이지마다 "구역명" 입력 (기본값: 페이지에서 감지된 이름)

**Step 3 — 선택 페이지 파싱 & 확인**
- 선택된 페이지에서 추출:
  - 요약값: Eav, Emin, Emax, Uo, Ud
  - 격자 숫자 배열 + X/Y축 레이블 (m 단위)
- 파싱 결과 미리보기 (히트맵 미니 + 요약값)
- 사용자 확인 → 저장

**파싱 엔진 (내부)**:
- 페이지 타입 감지: 키워드 패턴 (`Table, (E)`, `Calculation results`, `lx`, 숫자격자)
- 격자 추출: 연속 숫자 행 파싱 + `(min)` `[max]` 마커 처리
- X/Y 레이블: 축 레이블 라인 (`0 5 10 15...`) 파싱
- 파싱 실패 시 수동 입력 fallback

#### C. 조도 테이블 UI (핵심)

**설계 히트맵 뷰** (read-only):
- X/Y축 레이블 (m 단위)
- 셀 = 설계 lx 값 + 배경색 (히트맵 스케일)
- 최소값(파랑 테두리), 최대값(빨강 테두리) 강조
- 데스크톱: 셀 48px / 태블릿: 36px / 모바일: 28px + 가로스크롤

**실측 입력 그리드** (editable):
- 동일 격자 구조, placeholder에 설계값 연하게 표시
- 탭/엔터 → 좌→우→다음행 자동이동
- 입력 완료 셀 → 히트맵 색상 즉시 반영
- 달성률 색상 테두리: ≥90%=초록 / 70~90%=주황 / <70%=빨강
- 입력할수록 Eav/Emin/Emax/Uo 실시간 자동계산

**모바일 순차입력 모드**:
- "순차입력" 버튼 → 풀스크린 모달
- 현재 위치 표시 (Row 3, Col 5 → Y=6m, X=11.5m)
- 설계값 크게 표시 → 큰 숫자 입력 → 이전/다음 버튼
- 진행률 바 (35/128, 27%)

**차이맵 뷰** (실측 완료 후):
- 각 셀: (실측-설계)/설계 × 100%
- 색상: +10% 이상=파랑 / ±10%=흰색 / -10~-20%=주황 / -20% 이하=빨강

#### D. 비교 분석 & 리포트
- 구역별 KS 기준 자동 판정 (시설 종류 선택 → 기준 자동 적용)
- 전체/구역별 달성률 요약
- 미달 구역 하이라이트
- 리포트 PDF 출력 (WeasyPrint 또는 기존 pdf 모듈)

### 3.2 Out of Scope
- DIALux PDF 파싱 (Relux만 우선)
- 자동 측정기기 연동
- 3D 조도 분포 시각화

---

## 4. DB Schema

### 4.1 테이블 구조

```sql
-- 현장/프로젝트 마스터
CREATE TABLE illuminance_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,        -- 현장명
    customer TEXT,                     -- 발주처
    location TEXT,                     -- 설치위치
    install_date DATE,                 -- 실제 설치일
    pdf_filename TEXT,                 -- 업로드된 원본 PDF
    facility_type TEXT,                -- 시설종류 (풋살장/축구장/테니스장/주차장/보행로)
    status TEXT DEFAULT 'design',      -- design / measured / reported
    notes TEXT,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 구역 (1 프로젝트 = N 구역)
CREATE TABLE illuminance_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES illuminance_projects(id) ON DELETE CASCADE,
    area_name TEXT NOT NULL,           -- 구역명 (풋살장, Evaluation area 1, 코트1...)
    area_index INTEGER DEFAULT 1,      -- PDF 내 순서
    -- 설치조건 (PDF 파싱)
    installation_height REAL,          -- 설치높이 (m)
    lamp_type TEXT,                    -- 조명기구
    lamp_watt INTEGER,                 -- 와트
    lamp_qty INTEGER,                  -- 수량
    tower_qty INTEGER,                 -- 타워 수
    simulation_date DATE,
    -- 요약 설계값 (PDF 파싱)
    design_eav REAL,
    design_emin REAL,
    design_emax REAL,
    design_uo REAL,
    design_ud REAL,
    maintenance_factor REAL,
    total_flux REAL,
    total_power REAL,
    power_per_area REAL,
    -- 격자 메타
    grid_rows INTEGER,
    grid_cols INTEGER,
    grid_x_labels TEXT,                -- JSON array (m 값)
    grid_y_labels TEXT,                -- JSON array (m 값)
    design_grid TEXT,                  -- JSON 2D array (설계 lx 값)
    -- KS 기준 (시설별 자동 적용)
    ks_eav_min REAL,                   -- KS 기준 최소 평균조도
    ks_uo_min REAL,                    -- KS 기준 최소 균제도
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 실측값 (1 구역 = N 회 측정 가능)
CREATE TABLE illuminance_measured (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER NOT NULL REFERENCES illuminance_areas(id) ON DELETE CASCADE,
    measure_date DATE NOT NULL,
    measured_by TEXT,
    weather TEXT,                      -- 측정환경 (맑음/흐림/야간)
    instrument TEXT,                   -- 측정기기
    -- 실측 요약값 (격자에서 자동계산)
    measured_eav REAL,
    measured_emin REAL,
    measured_emax REAL,
    measured_uo REAL,
    measured_ud REAL,
    -- 격자 데이터
    measured_grid TEXT,                -- JSON 2D array (실측 lx 값)
    -- 판정
    ks_pass TEXT,                      -- PASS / WARNING / FAIL
    eav_achievement REAL,              -- Eav 달성률 % (measured/design)
    uo_achievement REAL,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 4.2 KS 기준 테이블

| 시설 종류 | 용도 | Eav 기준 (lx) | Uo 기준 |
|----------|------|--------------|---------|
| 풋살장 | 훈련 | 300 | 0.50 |
| 풋살장 | 경기 | 500 | 0.60 |
| 축구장 | 훈련 | 200 | 0.50 |
| 테니스장 | 훈련 | 300 | 0.60 |
| 주차장 | 실외 | 30 | 0.25 |
| 보행로 | 일반 | 15 | 0.40 |

---

## 5. Routes & Pages

| Method | URL | 기능 |
|--------|-----|------|
| GET | `/illuminance` | 프로젝트 목록 |
| GET | `/illuminance/new` | 신규 등록 폼 (Step 1: 기본정보 + PDF 업로드) |
| POST | `/illuminance/api/upload-pdf` | PDF 업로드 → 페이지 목록 반환 (AJAX) |
| POST | `/illuminance/api/parse-pages` | 선택 페이지 파싱 → 격자 데이터 반환 (AJAX) |
| POST | `/illuminance/new` | 프로젝트 + 구역들 최종 저장 |
| GET | `/illuminance/<id>` | 프로젝트 상세 (구역 목록 탭) |
| GET | `/illuminance/<id>/area/<area_id>` | 구역 상세 (설계/실측/비교 탭) |
| POST | `/illuminance/<id>/area/<area_id>/measure` | 실측값 저장 |
| GET | `/illuminance/<id>/report` | 비교 분석 리포트 |
| GET | `/illuminance/api/area/<area_id>/grid` | 격자 JSON 반환 |

---

## 6. Files

### 신규 생성
```
routes/illuminance.py
modules/services/illuminance_pdf_parser.py   ← Relux PDF 파싱 엔진
templates/illuminance_list.html
templates/illuminance_new.html
templates/illuminance_detail.html            ← 구역 탭 포함
templates/illuminance_area.html              ← 히트맵 + 입력 그리드 + 차이맵
templates/illuminance_report.html            ← 리포트 (인쇄용)
static/js/illuminance_grid.js                ← 히트맵/입력/차이맵 컴포넌트
static/css/illuminance.css                   ← 히트맵 스타일
```

### 수정
```
app.py                        ← Blueprint 등록
modules/models/db.py          ← 테이블 생성 (3개)
modules/models/entities.py    ← 모델 클래스
templates/base.html           ← 사이드바 메뉴 추가
sql_editer.sql                ← ALTER/CREATE 문 기록
```

---

## 7. Implementation Order

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 1 | DB 스키마 + 모델 | db.py, entities.py, sql_editer.sql |
| 2 | PDF 파싱 엔진 | illuminance_pdf_parser.py |
| 3 | 프로젝트/구역 CRUD routes | illuminance.py |
| 4 | 히트맵 JS 컴포넌트 | illuminance_grid.js, illuminance.css |
| 5 | 설계 히트맵 뷰 | illuminance_area.html (설계 탭) |
| 6 | 실측 입력 그리드 + 저장 | illuminance_area.html (실측 탭) + API |
| 7 | 차이맵 + 달성률 | illuminance_area.html (비교 탭) |
| 8 | 리포트 PDF 출력 | illuminance_report.html |
| 9 | 사이드바 메뉴 + 목록 | base.html, illuminance_list.html |

---

## 8. Key Constraints

- 기존 PDF 모듈: `pypdf` (venv에 설치됨) → Relux 텍스트 추출 가능 확인
- 히트맵 컬러: CSS `hsl()` 계산 (외부 라이브러리 없이)
- 격자 크기: 최대 20행 × 30열 허용 설계 (현장에 따라 격자 다름)
- 모바일 입력: 가로스크롤 허용 (강제 축소 금지)
- 복수 구역: 구역별 독립 격자, 독립 실측 세션 관리
