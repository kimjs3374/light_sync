# Light-Sync ERP TODO

> **정렬 규칙: 최신 날짜 순 (위→아래 = 최근→과거)**

## 2026-03-30
- [x] 전체 리스트 UI 조달내역 스타일 통일 — 20+개 페이지 일괄 변환
  - 조달내역 기준: procurement-tree-table, 0.82rem, colgroup, table-light thead
  - 계약/협의/납품/서류/자재관리 전면 재작성 (플랫 테이블 + collapse 상세행)
  - 설계/발주/가공발주/입고/BOM/출장/인증서/견적/거래처/공구/보증 스타일 통일
  - per_page 전체 50건 통일 (19개 라우트)
  - 계약일/납품기한/D-Day 3컬럼 모든 리스트에 추가
  - 검색 필터 펼치기/접기 버튼 전체 삭제 (11개 파일)
- [x] 우선순위 리스트 개편 — 테이블+트리 → 리스트형 카드 (모든 페이지 공통 컴포넌트)
- [x] 납품관리 모델별 분할납품 — delivery_split_items 테이블
  - 1회차에 여러 모델 동시 수량 입력 (item_qty_{id})
  - 모델별 진행률 카드 + 잔여수량 빨간색 표시
  - 회차 추가/수정 폼에 모델별 수량 + 잔여수량 가이드
  - 히스토리 로그 전체 한국어화
  - 카카오워크 알림에 모델명 포함
- [x] 종합현황 카드형 재설계 — 자재입고 제거, 영업/생산/납품 3단계
  - 카드 클릭 시 품목별 상세 (영업단계/생산단계/납품상태/잔여수량)
  - 인쇄 버튼 + 표시건수 50/100/전체 선택
- [x] 자재관리 BOM 매칭 수정 — 역방향 매칭 (model_name에 product_code 포함)
  - _material_specs_from_contract_item 정규 카테고리명 전부 매칭
- [x] 사진관리 모바일 검색 — 드롭다운 위 검색 입력란 추가
- [x] 진영공설운동장 유령 데이터 제거 (is_contracted=false)
- [x] 카카오워크 생산완료 알림 — 품목 단위 + 현장 전체 완료 시 그룹채팅 자동 발송
  - refresh_production_statuses에서 status_prod 변경 감지 → notify_production_complete / notify_site_complete
- [x] 카카오워크 알림 포맷 통일 — 제목 줄바꿈 + 상세 페이지 URL 포함
  - 신규계약: [신규 계약 현장 등록] ↵ 계약명 + /contract_detail/{id}
  - 납품일정: [납품일정등록] ↵ 현장명 + /delivery_management/{id}
  - 협의변경: [협의변경] ↵ 현장명 + /sales_management/{id}

## 미완료 기능
- [ ] 협의내용 최적화 (품목별 스펙 스키마 고도화)
- [ ] 조달내역 미발행 조달건 상세 뷰 (품목 필터 + 경과일 표시)
- [ ] bkit 플러그인 롤백 — CC 2.1.81 서드파티 마켓플레이스 미지원으로 code-review 플러그인에 임시 합침
- [ ] 재고관리: BOM 부품별 `track_inventory` 플래그 — 자재담당자 연동여부 체크 파일 회신 후 매칭
- [ ] 재고관리: 소진 이력 조회/수정/삭제 화면
- [ ] 재고관리: 레거시 예약 핸들러 완전 삭제 (handle_reserve_stock, handle_cancel_reservation 등 dead code 정리)

## 2026-03-28
- [x] 자재/재고관리 전면 재설계 (PDCA 95%)
  - BOM 풀체인 해제: are_materials_ready 항상 True, 자재대기중 분기 제거
  - 부족자재 현황 (/inventory/shortage): BOM 소요 vs 현재고, 가공발주 제외 옵션
  - 소진 등록 (/inventory/consume): 계약 검색 → 품목 선택 → BOM 분해 → 수량 수정 → 등록
  - 재고 조정 (/inventory/adjust): 다건 일괄, 품목 자동완성, 시료/실사/반품/파손/기타
  - 재고원장: stock_consumptions + stock_consumption_items + stock_movements 확장
  - reserved_qty 전면 폐기 (20+ 파일, 템플릿/서비스/MCP)
  - DB 마이그레이션: status_prod 자재대기중→생산대기중 58건
  - API 4개: bom-breakdown, item-search, contract-search, contract-items
- [x] 사이드바 메뉴 그룹 분리: 관리부(10개) → 관리부(7) + 자재/재고(4)

## 2026-03-27
- [x] 서류관리 시스템 — 납품요구서 PDF 파싱 + 착수계/납품계 PDF 자동 생성
  - KONEPS 납품요구서 자동 파싱 (계약번호/수수료/보증기간/검사검수 추출)
  - 착수계 PDF: openpyxl 엑셀 템플릿 → LibreOffice headless 변환
  - 납품계 7페이지 PDF: reportlab 직접 생성 (한글 폰트 자동 탐색)
  - 공문번호 연도별 자동 채번 (document_serials)
  - 계약서/공통서류 첨부파일 관리 (Supabase Storage)
- [x] 출장관리 — 출장 등록/수정/삭제 + 차량 프리셋 + 인원 관리
  - 예정/진행/완료 상태 추적, 차량 프리셋, 인원 동적 추가
  - 목록/상세/등록수정 3화면
- [x] 공구관리 (전동공구 관리대장) — 불출/반납 이력 추적
  - 팀별/상태별 필터링 (보관/불출/점검/폐기)
  - 불출/반납 기록 + 반납예정일 관리
- [x] 입고사진 피드 — 워크보드 스타일 글+사진 피드 (Supabase Storage, 거래처/발주 연결)
- [x] 모바일 앱 API — HMAC 토큰 인증 + CORS (routes/app_api.py)
- [x] 인증서 관리 강화 — 상태별 필터(만료/위험/경고/안전) + 검색 + 엑셀 템플릿 다운로드
- [x] 제품카탈로그 엑셀 다운로드 기능
- [x] 전체 모바일 반응형 최적화 — 카드형 테이블 + 트리형 변환 + 글로벌 CSS
- [x] CSS 대규모 정리/간소화 (magnatech.css 리팩토링)
- [x] 품목 상세 페이지 개편
- [x] 발주서 첨부파일 기능 (purchase_order_files)

## 2026-03-25
- [x] 히스토리보드 이름+직급 표시 — get_user_display_name() 헬퍼, 전 라우트 적용 ("김정수 차장")
- [x] 대시보드 타임라인 scope 바로가기 — log_scope별 해당 관리 페이지 직접 이동 + scope 뱃지
  - history_detail_link() 함수 추가 (design→설계, contract→계약, sales→영업, material→자재, production→생산, delivery→납품)
- [x] 코멘트 작성 시 scope 정확 저장 — 기존 AJAX 코멘트 전부 common → 각 페이지별 write_scope 전달
  - history_write_scope 변수 + data-write-scope 폼 속성 + API write_scope 파라미터
- [x] 기존 common 코멘트 scope 보정 SQL 실행 (sql_editer.sql, 직전 시스템 로그 scope 유추)

## 2026-03-24
- [x] 견적서 PDF 출력 리디자인 — 원본 PDF 1:1 대응
  - 좌우 여백 축소 (15mm→10mm), 회사명/대표이사 순서 변경
  - 도장 오버레이 (이름 위 absolute, 우측 하단 고정)
  - 인쇄 시 직인 하단 고정 (qt-paper height:257mm 유지)
  - `\` 줄바꿈 통일 (품명/규격/비고, cell-wrap div 2줄 클램프)
  - 테이블 9행 고정 (빈 행 포함), 행 높이 45px 통일, 9pt 가운데정렬
  - 부가세포함 시 합계 옆 "(부가세포함)" 표시
  - 메타 라벨 정렬 (납기일↔수급자 값 시작점 min-width:72px 통일)
- [x] 입고관리 수정 기능 + 품번 저장 + 합계 스타일 통일
  - 입고 수정 라우트/템플릿 추가 (발주서 기반/직접 입고 모두 지원)
  - ReceivingItem.item_cd 컬럼 추가 + 등록/수정 시 품번 저장 (발주 연결 시 자동)
  - 기존 25건 품명 기준 item_cd 마이그레이션 (100% 매칭)
  - 상세 페이지 품번 컬럼 추가
  - 합계 영역: tfoot → 가공발주 스타일 summary 블록 (공급가액/부가세/합계, 3페이지 통일)
- [x] 계약명 우선 표시 전환 — 전사현황판 카드/일정 + 대시보드 캘린더/오늘최우선
  - 칸반 카드: contract_name 메인 타이틀 + project_name 서브 텍스트
  - 전사현황판 일정(다가오는 납품): 계약명 메인, 현장명·날짜 서브
  - 대시보드 납품 캘린더: 계약명 메인, 현장명·설계번호 서브
  - 대시보드 오늘최우선: 계약명 타이틀, 현장명 서브타이틀
  - JS AJAX 갱신 + 모달 타이틀 동기화
- [x] 채널 챗봇 안정성 대폭 강화
  - REPLY_TIMEOUT 180초→600초(10분), cleanup 300초→900초(15분), 프론트 maxPolls 20→60
  - partial reply 지원 — 오래 걸리는 작업 시 중간 안내 메시지 선발송 후 최종 답변 (channel_reply partial=true)
  - 페이지 이동 시 응답 유실 방지 — channel_reply 수신 즉시 DB 히스토리 저장 (_save_reply_to_history)
  - 늦은 응답 구제 — pending 만료 후 도착한 응답을 _late_replies에 보관, 다음 poll에서 전달
  - 프론트 not_found 시 즉시 에러 대신 2초 후 재시도 (continue)
- [x] 사용자 그룹(부서) 변경 기능 추가
  - 관리자 설정 > 사용자 선택 시 부서 드롭다운 추가 (즉시 저장)
  - 부서 변경 시 개인 추가 메뉴 권한(extra_menus) 초기화 → 새 부서 그룹 권한 자동 적용
  - 좌측 트리 사용자 이동 + 인원수 뱃지 실시간 갱신
- [x] 워크보드 이미지 썸네일 최적화
  - Pillow 기반 on-the-fly 썸네일 생성 (300x300, EXIF 회전 보정)
  - 디스크 캐싱 (storage/archive/.thumbs/) — 최초 1회 생성 후 즉시 서빙
  - 목록/상세 썸네일 로드 + 라이트박스 원본 로드 분리 (data-full)
  - lazy loading 적용

## 2026-03-23 (워크보드 카카오워크 스타일 + 히스토리보드 업그레이드)
- [x] 워크보드 아카이브 카카오워크 스타일 리디자인
  - ProseMirror→HTML 렌더러 (bold, link, mention)
  - 피드형 UI (본문+댓글+첨부파일 인라인, "이전 댓글 N개 더보기")
  - 첨부파일 2,401개 카카오워크→Supabase Storage 완전 이전 (8.89GB)
  - 이미지 라이트박스 (좌우 넘기기, 키보드 ←→/ESC, 카운터)
  - content_json + attachments_json 컬럼 추가 + SQLite→Supabase 마이그레이션
  - 댓글 작성자 원본 교정 (SQLite raw_json 기준 845건 검증)
- [x] 히스토리보드 업그레이드
  - @멘션 자동완성 (전체/영업부/관리부/생산부 + 개인)
  - 파일/이미지 첨부 (Supabase Storage 업로드)
  - 읽음 표시 (아바타 + 읽은 시각, 8명+N명)
  - 답글 [대댓글] 포맷 독립 코멘트 저장 (답글 먼저 + 원글인용 아래)

## 2026-03-23 (가공발주 + 활동로그)
- [x] 가공발주 메뉴 — 외주가공업체 발주 관리
  - ProcessingOrder/Item/File 모델 + FO번호 자동채번
  - DWG 파일 첨부 (Supabase Storage) + 도면관리 자동등록
  - 이메일 발송 (미리보기 모달, 제목/본문 수정, 담당자 발신, 다중 첨부)
  - 품목별 입고확인 → MaterialOrder 자동 갱신 + 생산관리 연동
  - 목록: 현장 우선 + 현장별/업체별/날짜순 그룹핑 + 납기 yyyy-mm-dd
  - 등록: 단가 회계서식(콤마) + 파일 동시 첨부 + 금액요약 우측정렬
- [x] 전사 활동 로그 시스템 (activity_logs)
  - 통합 활동 로그 테이블 + log_activity() 헬퍼
  - 11개 모듈 35개 포인트 적용 (발주/자재/생산/납품/수금/재고/도면/입고/협의/AS)
  - 실시간 타임라인 패널 (히스토리보드 없는 페이지용, 15초 자동갱신)
- [x] 발주관리 단가 회계서식 + 금액요약 스타일 통일
- [x] 거래처 자동완성 선택 후 커서 다음 필드 이동
- [x] 계약 자동완성 item_group 뱃지 (등기구/등주 구분)

## 2026-03-23
- [x] MCP 서버 대규모 보강 — 53→65개 Tool, instructions 5,800자, 업무용어→Tool 매핑
  - G2B 조달(2), 인증서(1), 시방서(1), 조명배치도(2), 조도검증(2), 직원/근무(2), 가공발주(2)
  - MCP 사용 가이드 (.claude/mcp_guide.md) + MCP_ERROR.md 업데이트
- [x] 3단계 Tool 라우터 구축 — 키워드 하드코딩 → DB 패턴 매칭 → LLM 폴백
  - 27,253건 시드 패턴 자동 생성 (scripts/seed_query_patterns.py)
  - mcp_query_patterns 테이블, 사용할수록 자동 학습 (hit_count)
  - LLM 호출 1회로 단축 (기존 4~5회, 45초 → 3~5초)
- [x] 챗봇 라우터 직접 포맷 — _direct_format()으로 LLM 스킵 즉시 응답
- [x] 챗봇 히스토리 정책 변경 — 기록용으로만 저장, Groq에 안 보냄 (토큰 절약)
  - "아까 그거" 등 맥락 참조 시에만 최근 4개 로드
- [x] 챗봇 UI 개선 — 시간 표시(HH:MM:SS) + 날짜 그룹핑(오늘/어제/날짜)
  - chatbot.html, channel_chat.html, chatbot-panel.js 3곳 동시 적용
  - /chatbot 페이지 스크롤 방지 (main-content 패딩 제거)
- [x] 챗봇 권한 프리셋 — 일반직원(27)/생산부(42)/영업부(36)/관리부(66)
  - 금액 관련 10개 Tool 관리부 외 전면 차단
  - 신규 사용자 승인 시 일반직원 프리셋 자동 적용 (auth.py)
  - erp_tools.py ALL_TOOLS에 신규 12개 Tool 등록
- [x] 사용자 인증 시스템 대규모 개편
  - 이메일 필수, 비밀번호 규칙(8자+3종), 비밀번호 보기 토글
  - 내 정보 관리 페이지 (/my_profile), 관리자 사용자 정보 수정
  - 아이디 찾기 / 비밀번호 찾기 (이메일 임시비번 발송)
  - 강제 비밀번호 변경 (must_change_password)
- [x] 조도검증-설계관리 시뮬레이션 연동 — 구역별 Eav/Emin/Emax/Uo/Ud + 설계기준 + 적합판정 인라인 테이블
  - 설계기준 입력 필드 3개 (Eav/Uo/Ud), KS기준→설계기준 명칭 변경
  - 조도검증 현장선택 설계현장만 표시 (G2B 조달내역 제외)
  - Uo(Emin/Eav), Ud(Emin/Emax) 수식 표시 + 역수값 표시
  - Emin 파란색, Emax 빨간색 컬러 구분
- [x] 사이드바 메뉴 하이라이트 전면 개선 — prefix 매핑 제거, g.active_menu_key + data-menu-key 매칭
  - menu_required 데코레이터에서 g.active_menu_key 자동 세팅
  - 상세 페이지(/project_detail, /processing-order 등)에서도 정확한 메뉴 하이라이트

## 2026-03-22
- [x] 조명배치도 신규 기능 — 현장별 타워 투광등 넘버링 + 렌즈각도 관리
  - 타워 CRUD (열×행 가변), 그리드 시각화, 인라인 팝오버 즉시 각도 적용
  - 모델별 렌즈관리 (lens_angle_configs, 키워드 매칭)
  - 엑셀 템플릿 다운로드 + 임포트 (현장번호 매칭 → 타워 자동생성)
  - 현장 전체 삭제, MENU_REGISTRY 영업부 등록
- [x] 협의관리 개편 — 영업관리→협의관리 이름 변경 + 협의항목 관리 페이지 (JSON 오버라이드)
- [x] 대시보드 5탭 할일 — 영업/가공/자재/생산/납품, 부서별 기본탭, 협의완료 우선정렬
- [x] 워크보드 스펙 자동 파싱 — 아카이브 본문+댓글에서 SMPS/케이블/렌즈/암대/도장 추출 (활성 18건 반영)
- [x] 엑셀 현장별정보 ↔ DB 매칭 스크립트 — 유사도 기반 자동매칭 + 수동매칭 엑셀 출력
- [x] 워크보드/AS 아카이브 SQLite → Supabase 전환 (557건 동일, workboard.db/as.db 미사용)
- [x] 조달내역 수금 컬럼 금액숨김 연동 (hide_financial 시 수금도 함께 숨김)
- [x] 권한 변경 즉시 반영 — before_request 30초 간격 DB 갱신 (재로그인 불필요)
- [x] 사이드바 종합현황 직접 링크 (하위메뉴 제거)
- [x] 우선순위 리스트 기본 닫힘 + 🔥 뱃지 강조
- [x] G2B 자동계약 채번 G-YYYY-NNNN (설계번호 YYYY-NNN과 분리)
- [x] DRAWING_REQUIRED_ITEMS 상수 추가 (도면 필요 품목 5종)
- [x] status-chip CSS 클래스 통일 (is- 접두사 + secondary 추가)
- [x] 상단 고정바 KPI 요약 API (/api/kpi-summary)
- [x] A/S 관리 전면 재설계 — 134케이스+285로그, 보증 자동화 (PDCA 95%)
- [x] 대시보드 KPI 세분화 — 대기/지연 → 생산대기/자재대기/납기지연 3개 분리
- [x] 세금계산서 G2B 계약명 검색 + 미청구 목록 검색
- [x] 수금상태 일괄정정 기능
- [x] 사이드바 브랜드 MAGNATECH 로고 개편
- [x] 티커 롤링 overflow 기반 자연스러운 스크롤

## 2026-03-21
- [x] 전체 코드 간소화 — 4Phase 리팩토링 (CSS/JS 추출, MCP registry 2170→43줄, entities 11개 분할, Route 서비스 분리) Match Rate 100%
- [x] 조도검증-설계관리 통합 연동 — 양방향 연동, PDF 원스톱 업로드, 기구 다중화, PDF 파서 격자 개선 (PDCA 95%)
- [x] PDF 파서 격자 인식 개선 — 비정형/정형 자동 판별, sparse row 병합 (null 204셀→0건)
- [x] MCP 매출조회 — 세금계산서→조달계약(G2B) 기준 변경
- [x] 그룹 메뉴 권한 UI 재설계 — 챗봇 관리 스타일 (조직트리 2단 + 메뉴 카드)
- [x] 메뉴 권한 관리 별도 페이지 분리 (/auth/admin/menu_perms)
- [x] 도면관리 고도화 — SPA 갤러리, PDF/DWG, 드래그앤드롭+프로그레스바, 버전 라이트박스, bulk delete
- [x] 히스토리보드 openHistoryFab() 복구 — Jinja2 블록 스코프 querySelector 패턴
- [x] 발주서 삭제 모달 버그 수정
- [x] admin_settings CSS/JS 정적 파일 분리

## 2026-03-20
- [x] 슈퍼BOM — 옵션별 BOM 필터링 (option_schema + option_filter, 8FR 100%) PDCA 95%
- [x] 발주 UX 개선 — 선택발주+계약그룹핑+재고표시 PDCA 90%
- [x] MCP 서버 — FastMCP 28Tool+4Resource, Claude Web+LM Studio 연동 PDCA 92%
- [x] 현장 사진 독립 갤러리 — 모바일 카메라+드래그앤드롭+ZIP+라이트박스 PDCA 91%
- [x] 카카오워크 ICS 연차 캘린더 동기화
- [x] 입고관리 통합검색 (토큰 AND 검색)
- [x] 일일보고 자동수집 수정 가능 + 발주서 현장별 압축
- [x] 거래처 상세 거래내역 통합 테이블
- [x] NAS 동기화 v3 (Python 올인원, .plan.txt, .lnk 파싱, rename 감지)
- [x] 입고예정 v2 — PurchaseOrderItem 전환, 대시보드/전사현황판 통계 동기화
- [x] 조도검증 시스템 — Relux PDF 파싱 + 히트맵 + KS 판정

## 2026-03-19
- [x] 전사 현황판 디스플레이 (MAGNATECH /production/display) — 6컬럼 칸반+전광판+날씨
- [x] 통합 히스토리보드 UX 개선 + 연락처 재배치
- [x] 납품집계 (G2B 대분류/모델별 피벗+차트+엑셀) PDCA 95%
- [x] 세금계산서 매출관리 (국세청 임포트 + G2B 매칭 + 매출 대시보드)
- [x] 히스토리보드 UX 대개편 — offcanvas+FAB+AJAX댓글+매그나텍 연동 PDCA 97%
- [x] 재고관리 시스템 — 대시보드+실사+회전율+BOM재고+변동이력 PDCA 95%
- [x] 생산관리 전면 재설계 — 작업자 중심 카드형 (현장→품목→공정, AJAX 인라인)
- [x] 접이식 사이드바 (250px↔60px 토글+플라이아웃+즐겨찾기+FOUC 방지) PDCA 95%
- [x] 견적관리 (견적서 CRUD + PDF + 품목 연동)
- [x] 전 템플릿 MAGNATECH Design System 통합

## 2026-03-18
- [x] 품목관리 페이지 (품번/품명/규격 + CRUD + 카테고리 + 거래처 자동완성)
- [x] G2B 계약매칭 + 자동계약생성 + 설계현장 병합 + 계약삭제
- [x] 자재관리 발주서 연동 (BOM→1클릭 발주서)
- [x] 자재관리 BOM list 마이그레이션 (223 완성품, 3,762 부품)
- [x] 부서별 주간보고서 (영업/생산/관리 자동 집계)
- [x] 거래처관리/입고관리 분리 + 발주서 입고확인

## 완료된 전체 기능
- [x] 전체 히스토리 보드 연동
- [x] 하자보증/AS 관리 (PHASE 9)
- [x] 임원진 별도 그룹 관리 → 조직도 기반 부서별 권한
- [x] ~~월별 수금관리~~ → 세금계산서 매출관리로 대체
- [x] MCP 서버 연동 (Light-Sync MCP)
- [x] 접이식 사이드바 + 즐겨찾기
- [x] 견적관리
- [x] Super BOM (옵션별 BOM 필터링)
- [x] 사진관리 (모바일 카메라 + 갤러리)
- [x] 납품서류 자동화 (착수계/납품계 PDF + 납품요구서 파싱)
- [x] 출장관리 (출장/차량/인원)
- [x] 공구관리 (전동공구 불출/반납)
- [x] 모바일 반응형 최적화
- [x] 자재/재고관리 전면 재설계 (BOM 풀체인 해제 + 재고원장 + 소진등록 + 부족자재)
