# Light-Sync ERP TODO

## 전체 기능계획
- [x] 전체 히스토리 보드 연동 → offcanvas 패널 + FAB + AJAX 댓글 + 20개 핸들러 로그 통일 + scope 통합
- [x] 하자보증/AS 관리 (매그나텍 PHASE 9) — 하자접수→현장확인→수리/교체→완료보고, technical scope 히스토리 연동
- [ ] 납품서류 자동화
- [ ] 협의내용 최적화
- [ ] 영업부 가공발주 연동
- [x] 임원진 별도 그룹 관리 → 조직도 기반 부서별 권한 + 개인 추가 메뉴 + 임원진 전체 열람
- [x] ~~월별 수금관리~~ → 세금계산서 매출관리로 대체 (조달청=발행즉시입금, 수금관리 불필요)
- [ ] 조달내역 미발행 조달건 상세 뷰 (품목 필터 + 경과일 표시)
- [x] MCP 제작해서 로컬LLM과 연동 → Light-Sync MCP 서버 (FastMCP 28Tool+4Resource, Claude Web+LM Studio)
- [ ] 모바일환경 최적화
- [x] 접이식 사이드바 + 즐겨찾기 (250px↔60px 토글, 아이콘 플라이아웃, ⭐즐겨찾기 최대8개, FOUC 방지)
- [x] 견적관리 (견적서 CRUD + PDF + 품목 연동) → quotation blueprint
- [x] Super BOM → 슈퍼BOM (옵션별 BOM 필터링, option_schema/option_filter)
- [x] 사진등록 및 모바일환경 카메라 연동 → 현장 사진 독립 갤러리 (/photos, 카메라+드래그앤드롭+ZIP+계약별필터)

## 2026-03-19
- [x] 전사 현황판 디스플레이 (MAGNATECH /production/display) — 6컬럼 칸반+전광판+날씨
- [x] 통합 히스토리보드 UX 개선 + 연락처 재배치
- [x] 납품집계 (G2B 조달내역 대분류/모델별 월별 피벗 + stacked bar 차트 + 엑셀 + 모델 자동완성 + 금액토글 + 년도별 sub_rows)
- [x] 세금계산서 매출관리 (국세청 엑셀 임포트 + G2B 2단계 매칭 + 매출 대시보드 + 년도별 계약대비매출/이월 + 조달내역 발행필터)
- [x] 투광등기구 → LED투광등기구 데이터 병합 (3건)
- [x] 히스토리보드 UX 대개편 — offcanvas+FAB+AJAX댓글+연락처 접히는 바+매그나텍 검수/대금/설계 연동 (PDCA 97%)
- [x] 재고관리 시스템 — 대시보드+실사(엑셀 템플릿/업로드/차이보고서)+회전율+BOM 가용재고+변동이력 (PDCA 95%)
- [x] 발주서 삭제 전체 상태 허용 (입고 연결 시만 차단)
- [x] 직접입고 품번/품명/규격 3칸 자동완성 + 미등록 품목 자동생성 + 재고 반영
- [x] 발주서 기반 입고 모달 — 열자마자 발주서 목록 즉시 표시
- [x] 일일업무보고 댓글/답글 제외 (system 이벤트만 수집)
- [x] FAB(📜) 전역 배치 (/production/display 제외)
- [x] 생산관리 전면 재설계 — 작업자 중심 카드형 UI (현장목록→품목별→공정 카드, AJAX 인라인 수량입력, 모바일 반응형, 히스토리보드 연동)
- [x] 일일업무보고 발주서/입고/재고실사 이벤트 자동수집 추가
- [x] 접이식 사이드바 (250px↔60px 토글 + 그룹 아이콘 플라이아웃 + 즐겨찾기 ⭐ + FOUC 방지) — PDCA 95%
- [x] 견적관리 기능 추가 (견적서 CRUD + PDF 생성 + quotation blueprint)
- [x] 전 템플릿 MAGNATECH Design System 통합 (page-hero, 인쇄 스타일, 테이블 overflow:visible)

## 2026-03-21
- [x] 전체 코드 간소화 및 스플릿 — 4Phase 리팩토링 (CSS/JS 추출 14+16파일, MCP registry 2170→43줄, entities 11개 분할, Route 서비스 분리) Match Rate 100%, PDCA 완료
- [x] 발주서 삭제 모달 버그 수정 — deleteModal이 `{% if status=='작성중' %}` 조건 안에 있어 다른 상태에서 미렌더링, 조건 밖으로 이동
- [ ] bkit 플러그인 롤백 — CC 2.1.81 서드파티 마켓플레이스 미지원으로 code-review 플러그인에 임시 합침. 롤백: `bash ~/.claude/plugins/cache/bkit-marketplace/bkit/rollback-bkit.sh` 후 `/reload-plugins`
- [x] MCP 매출조회 — 세금계산서 기준 → 조달계약(G2B) 기준으로 변경 (get_revenue_summary, get_financial_overview)
- [x] 그룹 메뉴 권한 UI 재설계 — 챗봇 관리 페이지 스타일 (좌측 조직트리 2단, 우측 메뉴 카드, 그룹/개인 통합 관리)
- [x] 메뉴 권한 관리 별도 페이지 분리 (/auth/admin/menu_perms + menu_perms.html)
- [x] 코드 분리 — admin_settings.html CSS/JS 정적 파일 분리 (static/css/admin_settings.css, static/js/admin_settings.js), base.html block head 추가
- [x] 도면관리 고도화 — SPA 갤러리 (사진관리 동일 구조), PDF iframe 미리보기, DWG 업로드/다운로드, XHR 인라인 업로드(드래그앤드롭+프로그레스바), 버전 탭 라이트박스, 전체선택/선택삭제 bulk delete, 사이드바 공유 그룹 등록
- [x] 히스토리보드 openHistoryFab() 복구 — Jinja2 블록 스코프 문제로 querySelector('[id$="HistoryOffcanvas"]') 패턴으로 교체
- [x] 고사양 매그니 미표시 버그 진단 — 세션 만료 문제, channel_allowed 라우트 debug 로깅 추가

## 2026-03-20
- [x] 슈퍼BOM — 옵션별 BOM 필터링 (option_schema JSON + option_filter, 8FR 100%) — PDCA 95%
- [x] 발주 UX 개선 — 선택발주+계약그룹핑+재고표시 — PDCA 90%
- [x] MCP 서버 — FastMCP 28Tool+4Resource, Claude Web+LM Studio 연동 — PDCA 92%
- [x] 현장 사진 독립 갤러리 — 모바일 카메라+드래그앤드롭+ZIP다운로드+계약별필터+라이트박스 — PDCA 91%
- [x] 카카오워크 ICS 연차 캘린더 동기화 (대시보드+전사현황판 연동, 오전/오후반차 자동 구분)
- [x] 입고관리 통합검색 (거래처+품명+규격 토큰 AND 검색, 매칭 품목만 필터)
- [x] 일일보고 자동수집 내용 수정 가능 (auto_items_json)
- [x] 일일보고 발주서 현장별 압축 (3건 이상 → "외 N건")
- [x] 거래처 상세 거래내역 통합 테이블 (건별 카드 → 클릭 펼침 행)
- [x] 직접입고 첫 행 자동 생성 + 자동완성 overflow 수정
- [x] NAS 동기화 v3 (Python 올인원, .plan.txt, .lnk 파싱, rename 감지)
- [x] 입고예정 v2 — MaterialOrder→PurchaseOrderItem 전환 (계약 없는 발주서도 표시), 검수 프로세스 전면 제거, 입고관리 디자인 po_list 기준 통일, 대시보드/전사현황판 입고예정 통계 동기화
- [x] 조도검증 시스템 — Relux PDF 파싱 + 조도 격자 히트맵 + KS 판정 + 설계-실측 비교 리포트


## 2026-03-18
- [x] 품목관리 페이지 (품번/품명/규격 분류 + CRUD + 카테고리 체계 + 거래처 자동완성)
- [x] iCUBE USE_YN 매핑 버그 수정 (전 품목 is_active=False 문제)
- [x] G2B 계약매칭 추천 (점수 기반 자동 추천 + 수동 연동/해제)
- [x] G2B 불러오기 (계약등록 시 G2B 선택→계약명/날짜/품목/모델/수량 자동 채움)
- [x] G2B 자동 계약생성 (sync-g2b CLI → 신규 수집건 자동 Project+Contract 생성, status='G2B자동')
- [x] 계약관리에서 설계현장 병합 (설계현장 연결 → 6종 엔티티 이관)
- [x] 계약 삭제 기능 (하위 품목+자재발주 함께 삭제)
- [x] 자재관리 발주서 연동 (BOM 소요자재→1클릭 발주서 생성, bom_item_id FK 연결)
- [x] 자재관리 BOM list 마이그레이션 및 연동 (223 완성품, 3,762 부품, 42% items 매칭)
- [x] 부서별 주간보고서 (영업/생산/관리 자동 집계 + 접근 제어 + admin 드롭다운)
- [x] 영업부 주간보고서 품목 상세 펼침 (품목|모델|수량 + rowspan + 합계행)
- [x] 사이드바 업무보고 트리 메뉴 (일일보고/주간보고)
- [x] 계약상세 현황 컬럼 통합 (영업/구매/생산 → 1컬럼 한 줄)
- [x] 거래처관리/입고관리 분리
- [x] 입고관리에 발주서 불러와서 입고확인 하는 기능 제작
