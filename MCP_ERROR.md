# MCP API 사용 주의사항

## 1. 조달 계약금액 조회

### ❌ 잘못된 방법
```
get_revenue_summary(year=2025)  // 세금계산서 기준
get_tax_invoices(year=2025)     // 청구 기준
```

### ✅ 올바른 방법
```
get_g2b_contract_detail(search="키워드")  // G2B 조달내역 기반
// 계약 시점 기준 데이터 사용
```

### 차이점
| 구분 | 세금계산서 | 조달 계약 |
|------|---------|---------|
| 기준 | 청구 시점 | 계약 시점 |
| 금액 | 청구액 | 계약금액 |
| 예시 | 2025년 12억2천만원 | 2025년 44억원 |

### 교훈
- **계약금액** 조회 → `get_g2b_contract_detail()` 사용
- **매출액(청구기준)** 조회 → `get_revenue_summary()` / `get_tax_invoices()` 사용

---

## 2. contracts 테이블 — 이제 사용 중 (2026-07-09 재확인)

### 현황 (2026-07-09 실측)
- `contracts` 테이블: **1,300건** — G2B 동기화로 자동 생성됨
- `g2b_procurements` 테이블: **1,673건** (실제 조달 이력)
- `tax_invoices` 테이블: **15,477건** (매출 2,671 / 매입 12,806)
- `warranties` 테이블: **1,253건**

> ⚠️ 2026-03-21 시점의 "contracts 0건, get_contracts() 항상 빈 배열" 기록은
> **더 이상 사실이 아닙니다.** 이 잘못된 안내가 server.py INSTRUCTIONS 에도
> 들어 있어서 LLM 이 계약 조회를 일부러 우회하고 있었습니다. (2026-07-09 수정)

### 용도 구분
- 조달 원문(품목·금액·납기) → `get_g2b_contract_detail()`
- 수금상태(payment_status)·현장연결 → `get_contracts()` / `get_contract_detail()`
- 하자보증 → `get_warranty_by_g2b()`
- 계약금액은 `g2b_procurements.prdct_amt` 합산으로 산출

---

## 2-1. tax_invoices 는 매출·매입 혼재 ⚠️ (2026-07-09 발견)

`direction` 컬럼으로 매출/매입을 구분합니다. **매입이 매출의 약 5배**입니다.

| direction | 건수 |
|-----------|------|
| 매출 | 2,671 |
| 매입 | 12,806 |

direction 필터 없이 합산하면 매출이 2배 가까이 부풀려집니다.
실제로 `get_revenue_summary(2025)` 가 65.4억 대신 **121.1억**을 반환하고 있었습니다.

- 매출 집계: `get_revenue_summary(year, direction='매출')` — 기본값이 '매출'
- 매입/지출: `get_purchase_summary(year, month, vendor)` — 2026-07-09 신설
- 목록: `get_tax_invoices(direction='매출'|'매입'|'all')`
- `tax_invoices` 에 `g2b_procurement_id` 컬럼은 **없습니다**. 매칭 판정은
  `contract_id` 또는 `match_status`(자동매칭/수동매칭/미매칭) 로 하세요.

---

## 2-2. production_processes 에 없는 컬럼 ⚠️ (2026-07-09 발견)

실제 컬럼: `process_code`, `process_name`, `step_order`, `status`,
`progress_qty`, `progress_percent`, `started_at`, `completed_at`

**존재하지 않는 컬럼**: `stage`, `worker_name`, `item_name`, `quantity`, `note`

기존 Tool 들이 `hasattr()` 가드로 이 컬럼들을 참조해 조용히 빈 값을 반환했습니다.
그 결과 `get_fab_status()` 는 FAB 필터가 걸리지 않아 전체 공정 5,327건을 "FAB"로,
`get_worker_assignments()` 는 전원을 "미배정" 한 덩어리로 반환했습니다.
→ 두 Tool 을 `get_process_summary()` / `get_work_logs()` 로 재설계 (2026-07-09).

작업자 정보의 유일한 근거는 `production_daily_logs.created_by`(기록자)입니다.

---

## 3. MCP Tool 추가 이력

### 2026-07-13 — 카카오봇 업무쓰기 전면 개방 + 범용 확정 도구 `confirm_write` (113 → 114 Tool)

봇이 "MCP 통한 출장 신규등록 미지원"이라 거절 → **도구 부재 아님, WRITE_ALLOW 프로필 문제**(line 124 원인과 동일 계열).

| 구분 | 내용 |
|------|------|
| 근본원인 | 카카오봇(`scripts/kakao_brain.py` 단발 + `mcp-erp-only.json`)의 `WRITE_ALLOW`가 `write_preview_vehicle_log,confirm_vehicle_log`만 → 출장 등 나머지 write 도구 **미등록**. confirm 게이트 편차: vehicle_log/leave만 전용 MCP confirm 도구, 나머지 9종은 `routes/mattermost_action._action_write_confirm` **버튼 전용**(카카오 콜백 `/kakaowork/action`은 결재 승인/반려만 처리) → 카카오 대화형 확정 불가 |
| 신규 도구 | `confirm_write(session_token)` — write_preview_* 전 유형 범용 확정. `PendingWriteSession` 조회 후 `routes.mattermost_action._write_*` 실행기 재사용(MCP 프로세스에서 import OK). 신원은 `KAKAO_ERP_USER` 강제, `mm_user_name` 자리에 ERP username 전달(`_resolve_erp_user`가 username 우선매칭 → 본인명의 검증 정상) |
| config | `mcp-erp-only.json` WRITE_ALLOW = 업무쓰기 11 preview + `confirm_write,confirm_vehicle_log,confirm_leave_request` (출장·납품·AS·청구·발주·생산·업무일지·휴가·메일) |
| 프롬프트 | `kakao_brain.py` SYSTEM_PROMPT에 쓰기 매핑 + "동의 시 confirm_write(session_token)" 흐름 추가 |
| 검증 | ① READONLY+새 WRITE_ALLOW 환경서 등록 114 Tool·confirm_write 포함 확인 ② 출장 preview→confirm_write 실등록(id=140)→정리 ③ **라이브 단발 경로**(`ask_claude`, KAKAO_ERP_USER=mgn0615) 실행: "출장 등록해줘"→정상 preview 반환(거절 소멸) |
| 버그 | "나 문정훈하고 출장" 인데 출장자에 **요청자 본인 누락**. `write_preview_business_trip`이 travelers 비었을 때만 발신자 채우고, 값 있으면 본인 미포함 |
| 수정 | `include_requester` 파라미터 신설 — 1인칭(나/저/나도/우리/같이) 시 요청자(서버 강제 `KAKAO_ERP_USER`로 신원확정)를 출장자 앞에 합침(중복제거). 프롬프트에 "1인칭이면 include_requester=true" 지시. 라이브 검증: 요청자=김대중 "나 문정훈하고…" → 출장자 "김대중, 문정훈" |
| 배포 | 단발경로는 메시지마다 파일 fresh read → 즉시 반영, 재시작 불필요. ⚠️ `kakao_brain_daemon.py`(pid, Jul9 기동, `.bak.20260709d` 버전)는 **레거시 orphan** — 현재 단발 코드에 소켓 없음. 현 on-disk `kakao_brain.py`엔 `_build_mcp_config`/`FAST_ENV` 없어 데몬 재시작 시 ImportError. 데몬은 방치(단발이 우회) |

★ ERP 웹 채널챗(`channel_chat.py`→`mcp-channel.json`, 비-READONLY)도 write 전부 등록되어 confirm_write 사용 가능. 단 게이트는 `chatbot_permissions.allowed_tools`(soft) — 2026-07-13 전 사용자에 write 13종 추가.

### 2026-07-13 — 출장 ↔ 운행일지 연동 (프리필) + 계기판 거리도출 버그 수정

출장 데이터가 운행일지와 거의 겹침(차량·목적지·목적·날짜·인원). 계기판/거리만 빼고 프리필.

| 구분 | 내용 |
|------|------|
| 신규 | `modules/services/vehicle_log_trip_link.py` — `trip_to_log_defaults(session, trip)` 단일 소스.<br>회사차량 출장만(대중교통 등 제외), 출발지 기본 '본사'(수정가능) |
| MCP | `write_preview_vehicle_log(from_trip_id=...)` — 출장에서 차량·목적지·목적·날짜·출발지 자동 프리필.<br>카카오 AX: "OO 출장 운행일지 써줘" → `get_business_trips(search)` → `write_preview_vehicle_log(from_trip_id, 계기판)` → `confirm_vehicle_log` |
| 웹 | 운행일지 작성 모달에 '출장 불러오기' 드롭다운(`/vehicle-logs/trip-prefill/<id>`).<br>출장 상세에 '운행일지 작성' 버튼 → `/vehicle-logs?trip_id=N` 자동 오픈+프리필 |
| 버그 | `odometer_end`(계기판)만 주면 거리를 못 물어 진행 불가였음 → 계기판에서 거리 도출.<br>**카카오 주력 흐름(계기판 사진→odometer_end)이 이 버그로 막혀 있었음** |
| 봇 | 카카오 AX 프롬프트(`scripts/kakao_brain.py` SYSTEM_PROMPT)에 출장연동 흐름 추가.<br>카카오봇 config=`mcp-erp-only.json`(READONLY+WRITE_ALLOW), mmbot 아님 |

★ 카카오봇 도구 게이트: `chatbot_permissions.allowed_tools`는 읽기전용만(kakao_brain.py:126).<br>쓰기 도구는 MCP config `WRITE_ALLOW` + `--dangerously-skip-permissions`로 도달(권한테이블 무관).

### 2026-07-13 — 출장 상태 판정 버그 수정 (저장값 → 날짜기준 유효상태)

봇이 "진행중 출장"을 물으면 4~6월 방치건을 오늘 출장중처럼 답하고, 정작 오늘 실제 출장자는 누락.

| 구분 | 내용 |
|------|------|
| 원인 | `get_business_trips`/`get_business_trip_detail` 가 저장 `status` 컬럼을 그대로 필터.<br>ERP 웹은 출발/복귀일로 **계산한** 유효상태를 씀(`eff_status_expr`). 둘이 불일치 |
| 증상1 | 저장 status=진행중 7건(전부 복귀일 지남) → 웹기준 완료인데 MCP는 진행중으로 반환 |
| 증상2 | 오늘 실제 출장 #139(저장 status=예정)를 `status='진행중'` 필터가 누락 |
| 증상3 | 문서에 없는 유령 값 `출장중`(#46) 혼재. 스케줄러 완료전환이 이 값을 누락 |
| 수정 | 상태 판정을 `modules/services/business_trip_status.py` 단일 소스로 추출.<br>MCP·웹 목록(`_build_trip_query`)이 같은 로직 공유. status 는 날짜 기준 계산 |
| 데이터 | 저장 status 88건 일괄 보정(예정→완료 79, 진행중→완료 7, 출장중→완료 1, 예정→진행중 1) |
| 스케줄러 | 죽어있던 APScheduler `_auto_update_trip_status`(10분) 제거 → **crontab `flask update-trip-status`(10분)** 로 이관.<br>[[feedback_scheduler_crontab]] 원칙(gunicorn 멀티워커는 crontab 필수) 준수 |

★ 저장 status 컬럼은 이제 표시에 무관(모든 경로가 날짜 계산). crontab 보정은 DB 직접열람·저장값 의존 화면용.

### 2026-07-10 — 운행일지 쓰기 정상화 + 쓰기도구 허용목록 게이트 (112 → 113 Tool)

`write_preview_vehicle_log` 는 원래 있었으나 봇이 "등록 도구 없다"고 답한 원인 규명 및 결함 수정.

| 구분 | 내용 |
|------|------|
| 원인 | 카카오워크 봇은 `LIGHT_SYNC_MCP_READONLY=1` 프로필 → write 도구 미등록. 도구 부재가 아니라 프로필 문제 |
| 버그 | `write_ops.VEHICLE_CHOICES` 가 하드코딩 낡은 값. 실제 차량은 `쏘렌토 9539/트럭 1467/자차이용`.<br>최다 사용 `트럭 1467` 등록 불가, 유령 차량(`포터 8804`) 통과 |
| 버그 | `odometer_end=0` 하드코딩 + `odometer_start` 미기록 → 계기판 컬럼 공란 |
| 버그 | `origin` 을 상수 `"출발지 미기재"` 로 고정 |
| 개선 | 차량 목록을 `DashboardSetting['business_trip_vehicles']` 프리셋에서 로드 (ERP 폼과 동일 소스).<br>운행일지는 `EXCLUDED_VEHICLES` 제외한 회사차량만 |
| 개선 | `origin` 필수 승격, `odometer_end` 선택 입력. 주행 전 계기판은 직전 기록에서 **confirm 시점에** 재조회해 자동 채움 |
| 개선 | 거리 ↔ 계기판 불일치 시 조용히 덮어쓰지 않고 되물음. 역주행 계기판은 preview/confirm 양쪽에서 거부 |
| 신규 | `confirm_vehicle_log(session_token)` — 버튼 없는 봇(카카오워크)용 확정 도구.<br>`confirm_leave_request` 와 동일하게 `KAKAO_ERP_USER` 신원 대조로 명의 위조 차단 |
| 신규 | `LIGHT_SYNC_MCP_WRITE_ALLOW=<도구명 CSV>` — 쓰기 도구를 **개별 허용**.<br>기존 `LIGHT_SYNC_MCP_WRITE_LEAVE_ONLY=1` 은 하위호환 유지 |
| 리팩터 | 기록 로직을 `modules/services/vehicle_log_write.py` 로 추출.<br>Flask 버튼 경로(`routes/mattermost_action.py`)와 MCP confirm 경로가 같은 코드 사용 |

⚠️ **채널봇/ERP 웹챗봇은 운행일지 등록 불가 (미해결)**
- 채널봇: MCP 서버 프로세스를 다수 사용자가 공유 → `KAKAO_ERP_USER` env 주입 불가.
  preview 는 되지만 `confirm_vehicle_log` 가 "신원 미주입"으로 거부. 요청단위 신원 전달 배관 필요.
- ERP 웹챗봇: `chatbot_permissions.allowed_tools` 에 vehicle 도구가 14명 전원 0개 → 조회조차 차단.

### 2026-07-09 — 전체 점검 + 전자결재·인사 도메인 추가 (100 → 111 Tool)

전 Tool 실호출 점검 후 결함 수정 및 미커버 도메인 보강.

| 구분 | 내용 |
|------|------|
| 버그 | `get_revenue_summary`/`get_tax_invoices`/`get_financial_overview` direction 미필터 → 매출 2배 과대계상 |
| 버그 | `get_contracts` "항상 빈 배열" 안내가 거짓 (실제 1,300건) |
| 버그 | `get_fab_status`·`get_worker_assignments` 가 없는 컬럼 참조 → 재설계 |
| 버그 | `get_tax_invoices.g2b_matched` 가 없는 컬럼 참조 → 항상 False |
| 성능 | limit 없던 `get_fab_status`(5,327) `get_vendor_list`(3,738) `get_production_by_site`(1,268) `get_worker_assignments`(625KB) 에 limit + total/truncated 추가 |
| 신설 | 전자결재 4종: `get_approval_documents`, `get_approval_detail`, `get_my_pending_approvals`, `get_my_approval_drafts` |
| 신설 | 인사/연차 4종: `get_leave_balance`, `get_leave_calendar`, `get_leave_promotion_status`, `get_employee_card` |
| 신설 | 재무 1종: `get_purchase_summary` (매입 거래처별 지출) |
| 신설 | 생산 2종: `get_process_summary`, `get_work_logs` (fab/worker 대체) |
| 신설 | 쓰기 1종: `write_preview_leave_request` (휴가 상신 → confirm_leave_request) |
| 변경 | `get_today_attendance` 가 카카오워크 ICS → 전자결재 휴가신청서 기준으로 전환 |

**연차/휴가 로직은 직접 계산 금지.** `hr_service.leave_summary()` 와
`approval_service.get_approved_leaves_for_date/_for_month()` 를 재사용해야
ERP 화면과 숫자가 일치합니다.

### 2026-06-19 — 미등록 모듈 일괄 등록 (+17 Tool → 100개)

`tools/` 폴더에 구현돼 있으나 `tools_registry.py`에 **import/register 누락**돼 있던
6개 모듈을 등록. (그동안 INSTRUCTIONS에는 일부 문서화돼 있었으나 실제 호출 불가 상태였음)

| 모듈 | Tool | 용도 |
|------|------|------|
| material_order.py | `get_material_orders`, `get_material_orders_by_project` | 현장 계약품목 발주 진행상태 |
| incoming_overview.py | `get_incoming_overview` | 발주품목 입고 추적 통합 |
| billing.py | `get_billing_status` | 청구관리(미청구/청구완료/부분입금) |
| vehicle_log.py | `get_vehicle_logs`, `get_vehicle_log_summary` | 차량 운행기록부 |
| dept_report.py | `get_dept_weekly_report` | 부서별 주간 KPI |
| write_ops.py | `write_preview_*` 10종 | 쓰기작업(확인 후 DB 반영) |

**⚠️ 함께 수정한 버그**: `routes/mattermost_action.py`의 `WRITE_CONFIRM_ACTIONS`
게이트에 `confirm_production_complete_all`, `confirm_email_send`가 빠져 있어
해당 preview의 **확인 버튼이 "알 수 없는 action_type"으로 실패**하던 문제를 수정.

**write_preview_* 패턴 주의**: 이 도구들은 즉시 DB를 바꾸지 않고 preview/토큰만 반환.
실제 반영은 사용자가 채팅 확인 버튼 클릭 → `/mattermost/action`에서 처리.
한 작업당 1회만 호출하고, `status=needs_info`면 `question`으로 추가 질문할 것.

### 2026-03-22 추가 (8개 Tool)

| Tool | 파일 | 용도 | 상태 |
|------|------|------|------|
| `get_g2b_contract_detail` | g2b.py | G2B 계약 상세 (contracts 대체) | ✅ 완료 |
| `get_warranty_by_g2b` | g2b.py | G2B 계약번호 기준 하자보증 조회 | ✅ 완료 |
| `get_cert_expiry_alerts` | certification.py | 만료 임박 인증서 알림 | ✅ 완료 |
| `get_spec_doc_status` | spec_doc.py | 현장별 시방서 반영 현황 | ✅ 완료 |
| `get_lighting_layouts` | lighting_layout.py | 조명배치도 목록 조회 | ✅ 완료 |
| `get_lighting_layout_detail` | lighting_layout.py | 타워별 투광등 배치 상세 | ✅ 완료 |
| `get_illuminance_projects` | illuminance.py | 조도설계 검증 프로젝트 목록 | ✅ 완료 |
| `get_illuminance_detail` | illuminance.py | 조도설계 상세 + KS 기준 판정 | ✅ 완료 |

### 미구현 (개발 대기)

(없음 — 2026-06-19 기준 구현된 모든 Tool 모듈이 registry에 등록됨)
