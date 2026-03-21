## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 조도검증-설계관리 통합 연동 |
| 기간 | 2026-03-21 (1일) |
| Match Rate | 95% |

### 1.3 Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 조도검증↔설계관리 단절, 현장명 미반영, KS 하드코딩, 시설종류 5개 고정, 기구 1종만, PDF 파서 격자 NULL 33% |
| **Solution** | Project 조도필드 통합, 양방향 연동 API, 자유입력, 다중기구, PDF 파서 격자 매핑 전면 개선 |
| **Function UX Effect** | 설계관리에서 PDF 1클릭 업로드→조도검증 자동 생성, 기구목록 자재에서 자동 파싱, 90개 격자 전부 정확 |
| **Core Value** | 중복입력 제거, 설계-검증 데이터 일관성, 비정형 격자(야구장) 완벽 대응 |

---

# Completion Report: 조도검증-설계관리 통합 연동

## 1. PDCA 이력

| Phase | 일시 | 결과 |
|-------|------|------|
| Plan | 2026-03-21 | 7건 문제점 분석, 7 Step 구현 전략 |
| Design | 2026-03-21 | DB 스키마, API, UI, 양방향 연동 설계 |
| Do | 2026-03-21 | 4개 에이전트 병렬 구현 + 파서 개선 |
| Check | 2026-03-21 | Match Rate 95%, Missing 0건 |

## 2. 구현 결과

### 2.1 DB 스키마
- Project: `illuminance_facility_type`(String 100), `illuminance_fixtures`(Text) 추가
- IlluminanceArea: `fixtures`(Text) 추가
- 불필요 필드 제거: `illuminance_design_lux`, `illuminance_design_uo`, `spec_confirmed`, `spec_confirmed_date`

### 2.2 API
- `GET /illuminance/api/project-illuminance/<id>` — 설계현장 조도정보 반환
- `POST /illuminance/api/quick-create` — PDF 업로드→파싱→조도검증 자동 생성 (원스톱)
- 기구목록: `illuminance_fixtures` JSON 우선, 없으면 `project.materials`에서 조명기구 자동 파싱

### 2.3 설계관리 UI
- contract_detail.html + project_detail.html 양쪽에 조도 설계정보 카드
- 시설종류 + 기구목록(badge) + 연결된 조도검증 프로젝트 목록
- [PDF 업로드] 원스톱 버튼 + [직접등록] + [수정] 모달
- 수정 모달: 시설종류(자유입력 datalist) + 기구 동적 행 추가/삭제

### 2.4 조도검증 신규등록
- 시설종류: select 5개 → input+datalist 무제한 자유입력
- 설계현장 연결 시 AJAX 자동채움 (현장명, 주소, 시설종류, 기구)
- URL 파라미터 `?erp_project_id=` 지원 (설계관리에서 원클릭 이동)
- KS 기준: facility_type 기반 `get_ks_standard()` 단일 로직

### 2.5 기구 다중화
- Area 저장 시 `fixtures` JSON 자동 생성
- Area 상세에서 다중 기구 badge 표시

### 2.6 양방향 연동
- 설계관리 → 연결된 조도검증 프로젝트 목록 (상태 badge)
- 조도검증 → 설계관리 바로가기 링크

### 2.7 PDF 파서 개선
- 컬럼 매핑 충돌 해결: 값 수 == 컬럼 수면 위치 순서 1:1 배정
- 비정형/정형 격자 자동 판별 (`is_irregular`)
- sparse row 병합: 1~2개 값 행을 인접 행 None에 병합, 실패 시 행 유지
- 결과: **90개 격자 전부 Eav PASS, 값 누락 0건**

## 3. 설계변경 사항

| 변경 | 사유 |
|------|------|
| `illuminance_design_lux/uo` 제거 | PDF 파싱으로 design_eav/uo 자동 추출, 수동 입력 불필요 |
| `spec_confirmed/date` 제거 | 시방서 반영 확인은 업무 범위 밖 |
| KS 우선순위 3단계 → 1단계 | design_lux 제거로 facility KS만 사용 |

## 4. 산출물

### 신규/수정 파일
| 파일 | 변경 |
|------|------|
| modules/models/project_entities.py | illuminance 필드 2개 추가, 불필요 4개 제거 |
| modules/models/misc_entities.py | IlluminanceArea.fixtures, facility_type 확장 |
| modules/services/illuminance_pdf_parser.py | 격자 파서 전면 개선 |
| modules/services/project_actions.py | handle_confirm_spec 제거 |
| routes/illuminance.py | API 2개 추가, new/new_save/area 수정 |
| routes/project.py | update_illuminance action, 데이터 전달 |
| templates/contract_detail.html | 조도카드+수정모달+PDF업로드+시방서 제거 |
| templates/project_detail.html | 조도카드+수정모달+PDF업로드+시방서 제거 |
| templates/illuminance_new.html | 자유입력+preselect+design_lux 제거 |
| templates/illuminance_detail.html | 설계관리 링크 |
| templates/illuminance_area.html | 기구 다중 표시 |
| static/js/illuminance_new.js | AJAX 자동채움 강화 |
| sql_editer.sql | ALTER TABLE 추가 |
