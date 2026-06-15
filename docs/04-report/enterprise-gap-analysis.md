# Light-Sync ERP 전체 시스템 — 대기업 ERP 대비 Gap 분석

- **Date**: 2026-04-06
- **시스템 규모**: 라우트 44개, DB 모델 96개, 서비스 42개, 템플릿 125개, 외부 연동 8개
- **비교 대상**: SAP, Oracle EBS, 더존 iCUBE, 영림원 K-System

---

## 현재 시스템 수준

| 영역 | 현재 수준 | 대기업 기준 |
|------|----------|-----------|
| 기능 범위 | 44개 모듈, 96 테이블 — **기능은 대기업급** | 동급 |
| 보안 | CSRF/bcrypt/세션관리 있으나 **구멍 있음** | 미달 |
| 성능 | 47명 기준 충분, **100명+ 시 병목** | 미달 |
| 운영 | 수동 배포, 백업 미확인, 모니터링 없음 | **심각 미달** |

---

## 즉시 수정 (보안 취약점)

### 1. 이메일 HTML XSS 취약점

**위치**: `templates/mail_print.html:29`

```html
{{ msg.html_body|safe }}  ← 이메일 HTML을 그대로 렌더링
```

**위험**: 악성 이메일 수신 시 JavaScript 실행 가능. 세션 탈취, 관리자 권한 도용 가능.

**수정**: nh3 라이브러리(이미 설치됨)로 HTML 세정 후 렌더링.

---

### 2. 보안 헤더 누락

**현상**: X-Frame-Options, HSTS, Content-Security-Policy 등 미설정.

**위험**: 클릭재킹, MIME 스니핑, 프로토콜 다운그레이드 공격에 노출.

**수정**: `@app.after_request`에 보안 헤더 5줄 추가.

---

### 3. 로그인 무차별 대입 방어 부족

**현상**: 로그인 실패 횟수 제한 없음. rate limiter는 분당 10회지만 계정 잠금은 없음.

**수정**: 5회 실패 시 5분 잠금 + IP 기반 차단.

---

## 단기 보완 (1~2주)

### 4. 페이지네이션 일관성 부재

**현상**: 주요 목록 페이지에서 **전체 데이터를 메모리에 로드** 후 Python에서 필터링.

```python
# routes/project.py:142
all_projects = db.query(Project).filter(...).all()  # ← 전부 로드
for p in all_projects:
    if q and not matches: continue  # Python 필터
```

**위험**: 현장 1,000건 넘으면 대시보드 3~5초 지연. 현재 47명이라 체감 안 되지만 성장 시 병목.

**수정**: SQL WHERE + LIMIT/OFFSET으로 전환.

---

### 5. DB 인덱스 부재

**현상**: notifications, history_logs 등 자주 조회되는 테이블에 인덱스 없음.

**수정**: 
```sql
CREATE INDEX idx_notifications_user_created ON notifications(user_id, created_at DESC);
CREATE INDEX idx_history_logs_project_created ON history_logs(project_id, created_at DESC);
```

---

### 6. DB 커넥션 풀 기본값

**현상**: SQLAlchemy 기본 풀 사이즈 5개. gunicorn 4워커 × 동시 요청 시 부족.

**수정**: `pool_size=20, max_overflow=10, pool_pre_ping=True`

---

### 7. 캐싱 레이어 없음

**현상**: 매 요청마다 DB 직접 조회. 카탈로그, 프로젝트 목록 등 반복 조회에 캐싱 없음.

**수정**: flask-caching + Redis (또는 인메모리). 목록 5분, 정적 데이터 1시간 캐시.

---

## 중기 개선 (1~3개월)

### 8. 모니터링 시스템 없음

**현상**: 
- 헬스체크 엔드포인트 없음
- 에러율/응답시간 메트릭 없음
- 서버 다운되면 알 방법이 없음 (직접 접속해봐야 앎)

**대기업 기준**: Prometheus + Grafana, 또는 Datadog/New Relic APM.

**수정**: 최소 `/health` 엔드포인트 + 외부 uptime 모니터링 (UptimeRobot 등).

---

### 9. 백업/복구 전략 미확인

**현상**:
- DB 백업 crontab 없음
- Supabase 자동 백업 설정 여부 불명
- 복구 테스트 이력 없음
- RTO/RPO 미정의

**대기업 기준**: 일일 풀백업 + 시간별 증분백업. 월 1회 복구 테스트. RTO 4시간 이내.

**수정**: `pg_dump` 일일 crontab + S3 업로드 + 복구 테스트 절차 문서화.

---

### 10. CI/CD 파이프라인 없음

**현상**:
- 자동 테스트 없음
- 스테이징 환경 없음
- 프로덕션 직접 배포
- 롤백 절차 없음

**대기업 기준**: Git push → 자동 테스트 → 스테이징 배포 → 승인 → 프로덕션.

**수정**: GitHub Actions + Docker + 스테이징 서버.

---

### 11. 스키마 마이그레이션 수동

**현상**: `init_db()`에 600줄짜리 ALTER TABLE 하드코딩. Alembic 미사용.

**위험**: 어떤 변경이 언제 적용됐는지 추적 불가. 롤백 불가.

**수정**: Alembic 도입 (`flask db migrate/upgrade`).

---

### 12. Row-Level Security 없음

**현상**: 모든 사용자가 모든 프로젝트/계약 데이터 조회 가능. 부서별 데이터 격리 없음.

**대기업 기준**: PostgreSQL RLS 정책으로 user_group 기반 행 수준 필터링.

**수정**: 현재 47명 규모에서는 신뢰 기반으로 운영 가능. 100명+ 시 RLS 도입.

---

## 분류 요약

| 등급 | 항목 | 난이도 | 영향 |
|------|------|--------|------|
| **즉시** | 이메일 XSS | 낮음 (3줄) | 보안 취약점 제거 |
| **즉시** | 보안 헤더 | 낮음 (5줄) | 기본 방어 확보 |
| **즉시** | 로그인 잠금 | 중간 | 무차별 대입 차단 |
| **단기** | 페이지네이션 | 중간 | 성능 병목 제거 |
| **단기** | DB 인덱스 | 낮음 (SQL 2줄) | 쿼리 속도 보장 |
| **단기** | 커넥션 풀 | 낮음 (설정 1줄) | 동시 접속 안정성 |
| **단기** | 캐싱 | 중간 | 반복 쿼리 절감 |
| **중기** | 모니터링 | 중간 | 장애 감지 |
| **중기** | 백업/복구 | 중간 | 데이터 보호 |
| **중기** | CI/CD | 높음 | 배포 안정성 |
| **중기** | Alembic 마이그레이션 | 중간 | 스키마 추적 |
| **중기** | Row-Level Security | 높음 | 데이터 격리 |

---

## 잘 되어있는 것 (대기업급)

| 영역 | 상태 | 비고 |
|------|------|------|
| **기능 범위** | 44개 모듈 | 영업→자재→생산→납품→재무 풀체인 |
| **외부 연동** | 8개 시스템 | G2B, Mailcow, Supabase, ONLYOFFICE, KakaoWork, iCUBE, Groq AI, Google |
| **AI 챗봇** | Groq 함수 호출 | 20+ 도구, 권한 체크 포함 |
| **RBAC** | 그룹+메뉴 권한 | 부서별 메뉴 접근 제어 |
| **CSRF 보호** | Flask-WTF | 전체 적용 |
| **비밀번호** | bcrypt | 업계 표준 |
| **파일 관리** | Supabase Storage | 클라우드 저장 |
| **PDF 생성** | 5종 | 착수계, 납품서, 견적서, 발주서, 조도보고서 |
| **모바일 API** | 30+ 엔드포인트 | 모바일 앱 지원 |
| **히스토리 추적** | HistoryLog + ActivityLog | 업무 이력 2중 기록 |
| **알림 시스템** | 18개 이벤트 듀얼 채널 | 오늘 구축 완료 |
