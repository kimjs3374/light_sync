---
name: project_illuminance_verification
description: 조도설계 검증 3페이지 UI — 목록/등록마법사/구역상세 구현 위치 및 설계 결정사항
type: project
---

Flask + Jinja2 + Bootstrap 5 기반 조도검증 시스템 구현 (2026-03-20).

**파일 구조 (3페이지 분리)**
- `templates/illuminance_list.html` — 프로젝트 목록, 카드 그리드, 상태 필터 탭
- `templates/illuminance_new.html` — 3단계 마법사 등록 폼 (기본정보 → PDF 업로드 → 파싱 확인)
- `templates/illuminance_area.html` — 구역 상세 (탭 3개: 설계히트맵 / 실측입력 / 차이분석)
- `templates/illuminance_verification.html` — 구버전 단일 파일 (참고용 유지)

**핵심 설계 결정**

Y축 반전: PDF와 동일하게 높은 Y값이 테이블 최상단. 렌더 루프를 `for (ri = rows-1; ri >= 0; ri--)` 역순으로 돌림.
키보드 Tab 방향도 Y역순 보정 (화면상 다음 행 = 데이터상 ri-1).

- `lxToColor(value, min, max)`: HSL(240→0) 선형 보간, 밝기 sin 곡선
- 달성률 테두리: 90%+ ok / 70–90% warn / <70% err
- DiffMap: +10↑ 파랑 / ±10 중립(초록) / -10~-20 주황 / -20↓ 빨강
- `ILV_DATA` 전역 객체에 design + measured 배열 보관, 컴포넌트 간 공유
- Jinja2에서 `{{ design_grid | tojson }}`, `{{ measured_grid | default('null') | tojson }}` 으로 주입
- 반응형: 48px(데스크톱) / 36px(태블릿) / 28px(모바일) + 가로스크롤
- Y축 th에 `position:sticky; left:0` + `background:var(--mg-surface)` 적용

**등록 마법사 (illuminance_new.html)**
- Step 2 PDF 파싱은 실제 서버 API 연동 필요 (현재는 simulateParsing() 샘플 데이터)
- `hidden` 필드 `selected_pages`, `area_names` JSON으로 서버 전달
- 타입 뱃지: cover=회색 / floor_plan=연보라 / summary=파랑 / grid_table=초록 / 3d_view=주황
- grid_table 타입 페이지는 기본 선택, 구역명 자동 제안 (Zone A, B, ...)

**목록 (illuminance_list.html)**
- Jinja2 변수: `projects` 리스트, 각 항목에 status/name/client/install_date/areas/eav/uo 포함
- JS 클라이언트 사이드 필터 (data-status + data-name 속성 기반)

**Why:** 현장 조도 실측값을 Relux 설계값과 비교하여 조명 설계 검증 자동화
**How to apply:** 라우트에서 design_grid를 JSON으로 주입하면 즉시 동작. measured는 null 허용
