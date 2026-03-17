🏟️ Light-Sync ERP 프로젝트 마스터 가이드
본 문서는 Light-Sync 통합 관리 시스템의 설계 원칙, 기능 명세, 데이터베이스 구조를 정의한 최종 지침서이다. 모든 개발은 본 가이드의 설계를 절대적으로 준수한다.

1. 프로젝트 개요 (Project Overview)
명칭: Light-Sync ERP

핵심 목표: 현장 영업(Project) ➡️ 자재 분할(Material) ➡️ 공정 추적(Logistics) ➡️ 조도 계산(Technical)의 데이터 통합.

기술 스택: - Backend: Python / Flask

Database: SQLite (SQLAlchemy ORM)

Frontend: HTML5 / CSS3 (Bootstrap 5) / JavaScript (Vanilla JS)

Infrastructure: Synology NAS (Reverse Proxy), 외부 도메인 (work.mgnt.kr)

2. 기능 명세 (Functional Specifications)
🔒 2.1 인증 및 보안 (Auth & Security)
계정 체계: 아이디, 암호화된 비번(bcrypt), 이름, 휴대폰 번호(필수), 소속 그룹.

승인 프로세스: 회원가입 시 is_approved=False 상태로 대기 ➡️ 최고관리자 승인 후 접속 가능.

권한 제어: GroupPermission 테이블의 allowed_menus에 따라 사이드바 메뉴 동적 생성.

📊 2.2 현장 및 자재 관리 (Sales & Projects)
신규 등록: 한 번의 입력으로 '마스터 현장'과 'N개의 자재'를 분리하여 DB에 동시 저장 (1:N 분할 저장).

현장 리스트: 전체 현장의 긴급 여부 및 자재별 공정 상태(🔴🟡🟢)를 요약 출력.

상세 2단 뷰 (핵심 UI):

좌측 (Action Pane): 자재별 계약명, 모델명, 수량, 바코드, 입고 예정일 수정 및 저장.

우측 (Feed Pane): 현장별 독립 채팅창. 사용자 메시지 및 시스템 자동 로그(자재 수정 이력 등)를 타임라인으로 출력.

🏟️ 2.3 스포츠 조도 계산 (Sports Lux Calc)
데이터 연동: 특정 현장에 귀속된 조도 계산 데이터를 SportsModule 테이블에 저장.

자동 연산: 그리드 설정 ➡️ 설계/실측값 입력 ➡️ 평균조도(E_avg) 및 균제도(U1) 자동 계산.

3. 정보 아키텍처 (Menu Tree)
Plaintext
Light-Sync ERP
├── 🏠 메인 현황판 (Dashboard) : 전체 현황 요약
├── ☰ 전체 현장 리스트 (Project List) : 현장 상세 진입점
├── 🆕 신규 현장 등록 (Project Create) : 1:N 자재 입력 폼
├── 🏟️ 스포츠 조도 계산기 (Sports Calc) : 기술 데이터 연산/저장
├── 👤 내 정보 관리 (Profile) : 개인정보 및 비번 변경
└── 👑 시스템 관리 (Admin) : 계정 승인 및 부서별 메뉴 권한 설정
4. 데이터베이스 명세 (Database Specs)
🗄️ 핵심 테이블 구조
Project (현장): project_no (연도-일련번호), temp_name, site_address 등.

Material (자재): category (조명/타워), model_name, quantity, material_status 등.

HistoryLog (로그): user_name, content, created_at.

User (사용자): username, password_hash, phone_number, user_group, is_approved.

GroupPermission (권한): group_name, allowed_menus.

⚠️ 인공지능(Gemini) 준수 사항 (Wake-up Rules)
절대 금지: Streamlit 코드를 Flask 프로젝트에 섞지 말 것.

DB 무결성: 모든 수정사항은 반드시 models.py의 스키마와 일치해야 함.

UI 일관성: 상세 페이지는 반드시 좌측(데이터)/우측(채팅) 2단 구성을 유지할 것.

보안 우선: 로그인 세션 체크(session['user_id'])가 누락된 라우팅을 만들지 말 것.

데이터 연속성: 새 기능을 추가할 때 기존 DB 필드를 무시하거나 임의로 변경하지 말 것.