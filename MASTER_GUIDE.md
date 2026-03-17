# Light-Sync ERP 프로젝트 마스터 가이드

본 문서는 Light-Sync 통합 관리 시스템의 설계 원칙, 기능 명세, 데이터베이스 구조를 정의한 최종 지침서이다.
모든 개발은 본 가이드의 설계를 절대적으로 준수한다.

---

## 1. 프로젝트 개요

- **명칭**: Light-Sync ERP
- **핵심 목표**: 설계(Project) > 계약(Contract) > 영업(Sales) > 자재(Material) > 생산(Production) > 납품(Delivery)의 End-to-End 데이터 통합
- **대상 도메인**: LED 조명기구 제조 및 납품 (투광등, 가로등, 보안등, 조명타워, 등주 등)

### 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | Python / Flask |
| Database | PostgreSQL (Supabase) / SQLAlchemy ORM |
| Frontend | HTML5 / CSS3 (Bootstrap 5) / Vanilla JS |
| Storage | Supabase Storage (도면, 납품사진 등) |
| 알림 | KakaoWork Workboard API |
| 보안 | Flask-WTF CSRF, Flask-Limiter, bcrypt |
| 인프라 | 운영 도메인 work.mgnt.kr |

---

## 2. 핵심 데이터 흐름

```
설계 등록 (Project)
  └─> 계약 전환 (Contract + ContractItem)
        ├─> 영업관리 (Sales: 스펙 협의)
        ├─> 자재관리 (MaterialOrder: 발주/입고)
        ├─> 생산관리 (ProductionProcess: 공정 추적)
        ├─> 바코드 (ContractBarcode: 제품 이력)
        └─> 납품관리 (Delivery + DeliverySplit: 분할 납품)
```

---

## 3. 기능 명세

### 3.1 인증 및 보안

- **계정 체계**: 아이디, bcrypt 암호화 비밀번호, 이름, 휴대폰 번호, 소속 그룹
- **승인 프로세스**: 회원가입 시 `is_approved=False` 대기 > 관리자 승인 후 접속 가능
- **권한 제어**: GroupPermission 테이블의 `allowed_menus`에 따라 사이드바 메뉴 동적 생성
- **계정 비활성화**: 관리자가 사유와 함께 계정 비활성화/활성화 가능
- **Rate Limiting**: 인증 10회/분, 회원가입 3회/분, 기본 200회/시간
- **CSRF 보호**: Flask-WTF CSRFProtect 전역 적용

### 3.2 메인 현황판 (Dashboard)

- 전체 현장 KPI 요약 (설계/계약/생산/납품 건수)
- 워크플로우 칸반 (영업설계 > 자재확인 > 생산중 > 출고대기 > 납품진행)
- 납품 일정 미니 캘린더
- 우선순위 긴급 항목 목록
- 자동 알림: 납기 임박, 자재 미확인, 생산 지연 등
- 관리자 공지사항 전광판 (DashboardNotice)

### 3.3 설계관리 (Project)

- **신규 등록**: 현장명, 현장주소, 배송주소, 설계기준, 품목(1:N Material) 동시 입력
- **현장 리스트**: 긴급 여부 및 자재별 상태 요약 출력
- **상세 2단 뷰**: 좌측(데이터 편집) / 우측(업무 히스토리 타임라인)
- **계약 전환**: 설계 현장을 계약으로 전환 시 ContractItem 자동 분할 생성
- **삭제 워크플로우**: 삭제 요청 > 관리자 승인/반려 (ProjectDeleteRequest)
- **우선순위 오버라이드**: 권한 있는 사용자가 수동 우선순위 설정 가능

### 3.4 계약관리 (Contract)

- **계약 리스트**: 납기일, 전문기관검수, 긴급, 검색 필터링
- **계약 상세**: Contract > ContractItem 구조, 품목별 JSON 스펙 관리
- **직접 계약 생성**: 설계 단계 없이 바로 계약 등록 가능
- **카카오워크 알림**: 신규 계약 등록 시 Workboard 자동 포스팅
- **3단계 상태 추적** (ContractItem):
  - 영업: 계약확인 > 상세협의중 > 협의완료
  - 자재: 자재확인중 > 발주진행중 > 발주완료 > 입고진행중 > 입고완료
  - 생산: 자재대기중 > 생산대기중 > 생산중 > 생산완료

### 3.5 영업관리 (Sales)

- 계약 품목별 스펙 협의 상태 추적
- 품목 카테고리별 필수 스펙 완성도 검증
- 스펙 JSON 동적 폼 (카테고리별 필수/조건부 필드)

### 3.6 자재관리 (Material)

- 계약 품목으로부터 자재 발주 내역 자동 동기화
- 발주 상태: 자재확인중 > 발주진행중 > 발주완료 > 입고진행중 > 입고완료
- 외주 관리: 외주입고대기 > 외주입고 > 가공중 > 본사입고완료
- 일괄 업데이트 지원

### 3.7 생산관리 (Production)

- 품목 카테고리별 공정 템플릿 자동 생성
  - 투광등기구 (STA, ARENA, BATOO 등): 8~11공정
  - 가로등/보안등: 모듈 조립 > 검사 > 포장
  - 조명타워: 패널 조립 > 전기 > 포장
  - 등주류: 지지대 조립 > 앵커 > 도장
- 공정별 진행률(%) 및 일일 작업 기록 (ProductionDailyLog)
- 선택적 공정 활성화/스킵

### 3.8 납품관리 (Delivery)

- 계약으로부터 납품 내역 자동 생성
- 분할 납품 (DeliverySplit): 일정별 수량 분할
- 납품 상태: 납품대기 > 납품협의중 > 납품진행중 > 납품완료
- 담당자 배정 (역할 기반)
- 현장 사진 업로드: 생산완료, 상차, 납품완료 등 (Supabase Storage)

### 3.9 도면관리 (Drawing)

- 도면 유형: 제작도면 / 발주도면
- 버전 관리 (DrawingVersion): DWG 업로드 > PDF 변환
- 공유 링크: 만료일, 비밀번호, 다운로드 허용 설정
- 접근 로그 기록 (DrawingAccessLog)
- 권한: 영업부 업로드, 영업부+생산부 열람

### 3.10 스포츠 조도 계산기 (Lux Calculator)

- 그리드 설정 > 설계/실측 조도 입력
- 평균조도(E_avg) 및 균제도(U1) 자동 계산
- SportsModule 테이블에 현장 귀속 저장

### 3.11 바코드 관리 (Barcode)

- 조명기구별 바코드 발행 및 추적
- PCB 스펙 (CCT, 칩 사양, 제조일), SMPS 스펙 (모델, 전압, 전류) 기록
- 교체 이력 관리 (replaced_from_barcode, replaced_reason)
- 엑셀 템플릿 일괄 업로드

---

## 4. 정보 아키텍처 (메뉴 구조)

```
Light-Sync ERP
├── 메인 현황판 (Dashboard)       : KPI, 칸반, 캘린더, 긴급항목
├── 설계관리 (Project List)       : 설계 현장 목록 및 상세
├── 계약관리 (Contract List)      : 계약 현장 목록 및 상세
├── 영업관리 (Sales)              : 스펙 협의 및 완성도 추적
├── 자재관리 (Material)           : 발주/입고 추적
├── 생산관리 (Production)         : 공정별 진행률 관리
├── 납품관리 (Delivery)           : 분할 납품 및 현장 사진
├── 도면관리 (Drawing)            : 도면 버전 및 공유
└── [관리자] 시스템관리 (Admin)    : 계정 승인, 권한, 삭제 요청
```

---

## 5. 데이터베이스 명세

### 5.1 프로젝트/계약 계층

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| Project | 현장(설계/계약) | project_no, temp_name, site_address, is_contracted, is_urgent |
| Contract | 계약 (Project 1:N) | contract_name, item_group, delivery_due_date, is_prof_inspection |
| ContractItem | 계약 품목 (Contract 1:N) | category, model_name, quantity, item_spec_json, status_sales/admin/prod |
| Material | 설계 단계 품목 (레거시) | category, model_name, quantity, material_status |

### 5.2 업무 프로세스

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| MaterialOrder | 자재 발주 | order_status, order_date, expected_in_date, is_outsourcing |
| ProductionProcess | 생산 공정 | process_code, process_name, step_order, status, progress_percent |
| ProductionDailyLog | 일일 작업 기록 | work_date, daily_qty, memo, created_by |
| Delivery | 납품 | delivery_status, planned_total_qty, delivered_total_qty |
| DeliverySplit | 분할 납품 | split_no, quantity, scheduled_date, status |
| DeliveryPhoto | 납품 사진 | photo_type, file_name, storage_path |

### 5.3 바코드/도면

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| ContractBarcode | 조명기구 바코드 | barcode, pcb_spec, pcb_cct, smps_model, replaced_from_barcode |
| Drawing | 도면 | title, drawing_type, contract_item_id |
| DrawingVersion | 도면 버전 | version_no, dwg_path, pdf_path, convert_status |
| DrawingShareLink | 도면 공유 | token, expires_at, allow_download, password_hash |
| DrawingAccessLog | 접근 로그 | access_type, ip_address, user_agent |

### 5.4 사용자/시스템

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| User | 사용자 | username, password_hash, full_name, phone_number, user_group, is_approved, is_active |
| GroupPermission | 부서별 권한 | group_name, allowed_menus |
| UserPriorityPermission | 우선순위 지정 권한 | user_id, granted_by_user_id |
| ProjectPriorityOverride | 수동 우선순위 | project_id, priority_value |
| ProjectDeleteRequest | 삭제 요청 | status (PENDING/APPROVED/REJECTED) |
| HistoryLog | 업무 타임라인 | content, log_scope, log_kind, parent_log_id |
| Contact | 담당자 | name, phone, email, category |
| SportsModule | 조도 계산 | grid_layout, design_lux, measured_lux_data, avg_lux, u1_uniformity |
| DashboardNotice | 공지사항 | title, message, level, is_active |
| DashboardSetting | 설정값 | setting_key, setting_value |

### 5.5 품목 카테고리

```
투광등기구, 가로등기구, 보안등기구, 터널등기구,
조명타워, 철제가로등주, 스텐가로등주,
LED경관조명, 태양광가로등, 도로표지병
```

---

## 6. 외부 연동

| 서비스 | 용도 | 환경변수 |
|--------|------|----------|
| Supabase PostgreSQL | 메인 DB | DATABASE_URL, DB_SCHEMA |
| Supabase Storage | 도면/사진 저장 | SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY |
| KakaoWork API | 신규 계약 알림 | KAKAOWORK_BOT_TOKEN, KAKAOWORK_WORKBOARD_ID |

---

## 7. 프로젝트 구조

```
light_sync/
├── app.py                    # Flask 앱 엔트리포인트
├── config.py                 # 환경별 설정 (Development/Production)
├── .env                      # 환경변수
├── routes/                   # Blueprint 라우트
│   ├── auth.py               # 인증, 회원관리
│   ├── dashboard.py          # 메인 현황판
│   ├── project.py            # 설계/계약 관리
│   ├── contract.py           # 직접 계약 생성
│   ├── sales.py              # 영업관리
│   ├── material.py           # 자재관리
│   ├── production.py         # 생산관리
│   ├── delivery.py           # 납품관리
│   ├── drawing.py            # 도면관리
│   ├── technical.py          # 조도 계산기
│   └── barcode.py            # 바코드 관리
├── modules/
│   ├── models/               # SQLAlchemy ORM 모델
│   │   ├── db.py             # DB 엔진 및 세션
│   │   ├── entities.py       # 전체 테이블 정의
│   │   └── constants.py      # 품목 옵션, 스펙 스키마, 상태값
│   ├── services/             # 비즈니스 로직 (Action Handler)
│   ├── utils.py              # 공통 유틸리티
│   ├── priority_utils.py     # 우선순위 계산
│   ├── dashboard_utils.py    # 대시보드 칸반/캘린더
│   ├── production_logic.py   # 공정 템플릿 생성
│   ├── spec_utils.py         # 스펙 JSON 포맷팅
│   ├── history_board.py      # 히스토리 로그
│   ├── storage_adapter.py    # Supabase Storage 연동
│   ├── kakaowork_notifier.py # KakaoWork 알림
│   ├── auth_decorators.py    # @login_required, @admin_required
│   └── db_context.py         # DB 세션 컨텍스트 매니저
└── templates/                # Jinja2 HTML 템플릿
```

---

## 8. 개발 준수 사항

1. **DB 무결성**: 모든 수정사항은 반드시 `modules/models/entities.py`의 스키마와 일치해야 한다.
2. **UI 일관성**: 상세 페이지는 좌측(데이터 편집) / 우측(히스토리 타임라인) 2단 구성을 유지한다.
3. **보안 우선**: 모든 라우트에 `@login_required` 데코레이터를 적용한다. 세션 체크 누락 금지.
4. **데이터 연속성**: 기존 DB 필드를 임의로 변경하거나 삭제하지 않는다. 마이그레이션 필수.
5. **환경변수 통일**: 모든 설정값은 루트 `.env` 파일에서 `load_dotenv()`를 통해 로드한다. 별도 `.env` 파일 파싱 금지.
6. **서비스 레이어 패턴**: 라우트에 비즈니스 로직을 직접 작성하지 않는다. `modules/services/`의 핸들러를 통해 처리한다.
7. **히스토리 기록**: 데이터 변경 시 `HistoryLog`에 scope별 로그를 남긴다.
8. **CSRF 보호**: 모든 POST 요청에 CSRF 토큰을 포함한다.
