# Light-Sync ERP

## 프로젝트 개요
(주)매그나텍 LED 조명 사업부 사내 ERP 시스템. Flask + PostgreSQL(Supabase) + Jinja2.

## 핵심 문서 (반드시 참조)
- `.claude/magnatech_memory.md` — 제품 라인업 + 관급자재 9단계 업무 프로세스
- `.claude/magnatech_workflow.md` — 업무 워크플로우 (G2B 기준 생명주기 + 댓글 패턴 분석)
- `.claude/chatbot_mcp_design.md` — 챗봇 MCP 응답 설계 (시나리오 + 호출체인 + 응답템플릿)
- `.claude/archive_matching_spec.md` — 워크보드 아카이브 ↔ 조달계약 매칭 명세서 (4단계 로직 + 수동 6건)
- `MCP_ERROR.md` — MCP API 주의사항 + 추가 이력 (호출 시 반드시 참고)
- `.claude/mcp_guide.md` — MCP 서버 사용 가이드 (61개 Tool + 4개 Resource + 실행방법)

## 아키텍처 핵심

### G2B 조달내역이 뿌리
모든 업무 데이터의 출발점은 `g2b_procurements` 테이블.
- G2B 동기화 → contracts 생성 → 6개 관리 화면 노출
- 세금계산서 매칭 → 입금확인 → 하자보증 자동 생성
- 예외처리/상태변경 등 관리 기능은 조달내역(/procurement)에서 시작

### 완료건 필터링: contract.payment_status 단일 기준
- `modules/contract_filters.py`의 `active_contract_filter()` 하나로 6개 관리 화면 통일
- `payment_status`는 실제 수금 상태만 반영 (미청구/부분입금/입금완료/변경완료/취소)
- 예외처리는 `is_excluded` 플래그로만 처리, payment_status 절대 수동 변경 금지
- `project.status`로 완료 판단하지 않음

### 번호 체계
- 설계번호: `YYYY-NNN` (설계/영업 프로젝트)
- G2B 계약번호: `G-YYYY-NNNN` (조달내역 자동 생성)
- 설계관리에서 G2B 프로젝트(`G-` 접두사) 제외

## DB
- PostgreSQL (Supabase), 스키마: `light_sync`
- sql_editer.sql에 마이그레이션 SQL 기록 (스키마 접두사 `light_sync.` 필수)
- DB 컬럼 추가 시 ORM만으로 부족, ALTER TABLE 직접 실행 필요

## 파일 저장 규칙
- **static/ 디렉토리에 사용자 파일 저장 금지** — 모든 업로드 파일은 Supabase Storage에 저장
- 계약서/납품요구서: `documents/contracts/{req_no}.pdf`
- 착수계 편집 결과: `documents/commencement/{req_no}.xlsx`
- 공통서류: `documents/common/{key}.pdf`
- 제작도면: `documents/drawings/{model_code}.pdf`
- 템플릿: `documents/templates/{type}_template.xlsx`
- static/은 코드에 포함된 정적 자산(JS, CSS, 이미지, 엑셀 템플릿 원본)만 허용

## 코딩 규칙
- 응답은 존댓말
- 테이블: 줄바꿈 금지, ellipsis 필수, 뱃지/버튼 white-space:nowrap
- 폼 중첩 절대 금지
- 모든 업무행위 히스토리 로그 필수 (append_history_log)
- 이름+직급 한국식 표기 (부서 이름 직급)
