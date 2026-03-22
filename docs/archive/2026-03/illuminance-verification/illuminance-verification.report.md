# PDCA Completion Report: illuminance-verification

**Feature**: illuminance-verification
**Date**: 2026-03-20
**Duration**: 1일 (단일 세션)
**Final Match Rate**: 95%

---

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| Problem | Relux 시뮬레이션 설계조도(PDF)와 현장 실측값을 별도 관리하거나 비교할 수단이 없어, 납품 후 성능 검증 및 하자 분쟁 시 근거 자료 확보가 불가능했음 |
| Solution | PDF 자동 파싱으로 설계 격자를 등록하고 현장 실측값 입력 UI(히트맵·순차입력), KS 기준 자동 판정, 설계-실측 비교 리포트를 제공하는 조도검증 모듈을 구현 |
| Function UX Effect | PDF 1회 업로드로 구역별 설계값 자동 등록. 격자 히트맵으로 조도 분포 직관적 파악. 모바일 순차입력 모드로 현장 실측 즉시 입력. 구역별 KS 판정 리포트 인쇄 출력 |
| Core Value | 납품현장 조명 성능 데이터의 체계적 아카이빙 → 납품 품질 증빙 문서화 → 하자 분쟁 대응 근거 자료 확보 |

---

## 1. Project Overview

| 항목 | 내용 |
|------|------|
| Feature Name | illuminance-verification |
| Plan 작성일 | 2026-03-20 |
| 구현 완료일 | 2026-03-20 |
| 최종 Match Rate | 95% (초기 82% → iterate 후 95%) |
| 구현 파일 수 | 11개 (신규 6 + 수정 5) |
| 총 코드 라인 | 약 2,800줄 |

---

## 2. Implementation Summary

### 2.1 신규 생성 파일

| 파일 | 내용 | 상태 |
|------|------|:----:|
| `routes/illuminance.py` | Blueprint: 14개 route (CRUD + API + 리포트) | ✅ |
| `modules/services/illuminance_pdf_parser.py` | Relux PDF 파싱 엔진 (layout mode 격자 추출) | ✅ |
| `templates/illuminance_list.html` | 프로젝트 목록 (카드 그리드, 상태 필터) | ✅ |
| `templates/illuminance_new.html` | 등록 마법사 (3-step: 기본정보 → PDF → 확인) | ✅ |
| `templates/illuminance_detail.html` | 프로젝트 상세 (구역 카드 목록 + 수정/삭제) | ✅ |
| `templates/illuminance_area.html` | 구역 상세 (히트맵 + 실측입력 + 차이분석 + 이력) | ✅ |
| `templates/illuminance_report.html` | 비교 분석 리포트 (인쇄용) | ✅ |

### 2.2 수정 파일

| 파일 | 변경 내용 | 상태 |
|------|-----------|:----:|
| `modules/models/entities.py` | 3개 모델 클래스 추가 (Project, Area, Measured) | ✅ |
| `modules/models/db.py` | 3개 테이블 create_tables() 등록 | ✅ |
| `app.py` | illuminance Blueprint 등록 | ✅ |
| `config.py` | MENU_REGISTRY 영업부 추가, DEFAULT_GROUP_MENUS 반영 | ✅ |
| `sql_editer.sql` | 3개 테이블 DDL 기록 | ✅ |

---

## 3. Gap Analysis Result

### 3.1 초기 분석 (82%)

| 항목 | 점수 |
|------|:----:|
| API Endpoints | 85% |
| Data Model | 95% |
| PDF Parser | 100% |
| UI Templates | 75% |
| **Overall** | **82%** |

### 3.2 Iterate 후 (95%)

| 항목 | 해결 내용 |
|------|-----------|
| `illuminance_report.html` | 리포트 템플릿 + route 구현 완료 (+10%) |
| 사이드바 메뉴 | `config.py` MENU_REGISTRY 영업부 그룹 등록 (+3%) |
| 탭 디자인 | vendor_detail.html 패턴 동일 밑줄 탭으로 수정 |
| 다크 테마 제거 | 외부 폰트 제거, `--mg-*` 라이트 테마 통일 |

---

## 4. Technical Highlights

### 4.1 PDF 파싱 엔진 (핵심 구현)

Relux PDF는 `pypdf` `extraction_mode='layout'` 으로 문자 수평 위치를 보존해서 추출한다.

**주요 버그 수정 이력**:

| 버그 | 원인 | 수정 |
|------|------|------|
| `[m]` 치환 오류 | 3자 `[m]`을 4공백으로 치환 → 이후 숫자 위치 +1 밀림 | 3공백으로 수정 |
| all-None 컬럼 잔존 | 비직사각형 격자의 빈 컬럼 미제거 | 후처리 제거 로직 추가 |
| Y축 방향 반전 | PDF는 위→아래 읽기, 격자는 아래가 0m | `list(reversed())` 처리 |

### 4.2 격자 UI

- 히트맵: HSL 색상 계산 (외부 라이브러리 없음)
- 입력 셀: Tab/Enter 자동이동, 실시간 Eav/Uo 계산, KS 달성률 색상 테두리
- 차이맵: ±% 4단계 색상 (초과 파랑 / 정상 연초록 / 주의 주황 / 불량 빨강)
- 모바일 순차입력: 풀스크린 모달, 진행률 바, 미니맵

### 4.3 추가 구현 (Design 외)

| 항목 | 내용 |
|------|------|
| 프로젝트 수정/삭제 | AJAX PUT/DELETE + confirm |
| 구역명 수정/삭제 | 인라인 prompt + AJAX |
| 실측 기록 삭제 | 이력 탭 개별 삭제 |
| ERP 프로젝트 연결 | `erp_project_id` FK 연결 옵션 |
| KS 기준 확장 | 6종 → 14종 (경기용 추가) |

---

## 5. 설계 준수 체크리스트

| 항목 | 결과 |
|------|:----:|
| DB 스키마 3테이블 (illuminance_projects, areas, measured) | ✅ |
| PDF 파싱 엔진 (ReluxPdfParser) | ✅ |
| 14개 route (CRUD + API + 리포트) | ✅ |
| 격자 히트맵 (Y축 반전, min/max 표식) | ✅ |
| 실측 입력 (Tab/Enter 이동, 실시간 stat) | ✅ |
| 모바일 순차입력 모드 | ✅ |
| 차이맵 (4단계 색상) | ✅ |
| 비교 분석 리포트 (인쇄용) | ✅ |
| ERP 디자인 시스템 통일 (`--mg-*`, 라이트 테마) | ✅ |
| 사이드바 메뉴 영업부 등록 | ✅ |

---

## 6. Lessons Learned

1. **PDF 파싱은 실측 데이터로 검증 필수**: layout mode 사용 시 특수 마커(`[m]`, `(min)`, `[max]`)의 자릿수가 이후 숫자 위치에 영향을 미침. 실제 PDF로 추출 결과를 검증해야 버그 발견 가능.

2. **디자인 시스템 통일**: 초기 구현에서 다크 테마/외부 폰트 혼입. 신규 페이지 작성 시 `base.html`의 `--mg-*` 변수와 `page-hero` 패턴을 먼저 확인 후 작성할 것.

3. **탭 스타일 표준화**: 프로젝트 내 `nav-tabs` 커스텀 스타일이 `vendor_detail.html`에 존재. 신규 탭 페이지는 해당 스타일 참조.

---

## 7. Next Steps

- 실제 Relux PDF 추가 샘플 테스트 (다양한 시설 종류)
- 리포트 WeasyPrint PDF 다운로드 기능 (현재는 브라우저 인쇄)
- ERP 설계현장과의 연동 강화 (`erp_project_id` 기반 양방향)
