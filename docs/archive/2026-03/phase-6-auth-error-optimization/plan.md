# Phase 6: Auth Decorator + Error Handling + DB Index Optimization

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| **Problem** | 30개 라우트에 반복되는 세션 체크, 14개 bare except 블록, DB 인덱스 부재로 인한 성능/보안/유지보수 리스크 |
| **Solution** | `@login_required` / `@role_required` 데코레이터 도입, 구조화된 에러 핸들링 + 로깅, 주요 컬럼 DB 인덱스 추가, 백업파일 정리 |
| **Function UX Effect** | 인증/인가 코드 30개 → 데코레이터 1줄로 대체, 에러 발생 시 로그 추적 가능, 목록 조회 성능 향상 |
| **Core Value** | 보안 일관성 확보 + 운영 가시성 확보 + 쿼리 성능 최적화 + 코드 정리 |

---

## 1. Background & Problem

### 1.1 현재 상태

Phase 1~5를 통해 보안 패치, 안정화, 리팩토링, 서비스 레이어 분리를 완료했으나, 아래 4가지 Cross-Cutting Concern이 남아있음:

1. **인증 체크 반복** (30개소)
   - `if 'user_id' not in session: return redirect(url_for('auth.login'))` 패턴이 모든 라우트에 반복
   - 파일별: project.py(10), drawing.py(7), delivery.py(3), sales.py(2), production.py(2), material.py(2), dashboard.py(1), contract.py(1), barcode.py(1), technical.py(1)

2. **인가(권한) 로직 분산** (12개소)
   - auth.py: `session.get('role') != 'admin'` 6회 반복
   - delivery.py: `_can_assign_owner()` 함수
   - dashboard.py: `_is_admin()` 함수
   - project.py: `_can_approve_delete()`, `_can_manage_priority()` 함수
   - drawing.py: `_can_write_drawings()` 함수
   - sales.py: `can_write_drawings` 인라인 체크

3. **에러 핸들링 부재** (14개소)
   - `except Exception: pass` 또는 `except Exception as e:` 후 flash만 표시
   - app.logger 활용 없음 (500 핸들러에만 존재)
   - 에러 원인 추적 불가

4. **DB 인덱스 미설정**
   - `Project.is_contracted` — 거의 모든 목록 쿼리에서 필터링
   - `Contract.project_id` — FK이지만 인덱스 없음
   - `Contract.delivery_due_date` — 납기일 범위 쿼리
   - `HistoryLog.project_id` — 이력 조회
   - `Delivery.project_id` — 납품 조회
   - 각종 status 컬럼 — 상태 필터링

5. **백업 파일 존재**
   - `modules/models.back` (210 lines) — Phase 3 이전 모델 백업
   - `routes/project.back` (225 lines) — Phase 4 이전 라우트 백업

### 1.2 리스크

| 리스크 | 영향도 | 발생확률 |
|--------|--------|----------|
| 인증 체크 누락 시 비인가 접근 | HIGH | 신규 라우트 추가 시 |
| 에러 무시로 인한 데이터 손실 | HIGH | 운영 중 |
| 느린 목록 조회 (프로젝트 100+ 증가 시) | MEDIUM | 데이터 증가 시 |
| 백업 파일 혼란 | LOW | 개발 시 |

---

## 2. Goal & Scope

### 2.1 목표

1. **인증/인가 데코레이터 도입** — 30개 반복 코드 → `@login_required` 1줄로 대체
2. **구조화된 에러 핸들링** — 14개 bare except를 로깅 + 적절한 사용자 메시지로 교체
3. **DB 인덱스 추가** — 주요 FK/필터 컬럼에 인덱스 설정
4. **백업 파일 제거** — models.back, project.back 삭제

### 2.2 범위

**In-Scope:**
- `modules/auth_decorators.py` 신규 생성
- 10개 라우트 파일 인증 체크 교체
- 14개 에러 핸들링 개선
- models 인덱스 추가 (Alembic 없이 직접 추가)
- 백업 파일 삭제

**Out-of-Scope:**
- RBAC 테이블 기반 권한 관리 (현재 session 기반 유지)
- Alembic 마이그레이션 도입
- CSP 헤더 (P2로 연기)
- Soft delete (P2로 연기)

---

## 3. Implementation Checkpoints

### CP-01: `modules/auth_decorators.py` 생성
- `login_required` 데코레이터: session['user_id'] 체크 → redirect to login
- `admin_required` 데코레이터: login_required + role == 'admin' 체크
- `role_required(*roles)` 데코레이터: 특정 role/group 체크
- `permission_required(perm)` 데코레이터: can_approve_delete 등 권한 체크

### CP-02: 라우트 인증 체크 교체 (project.py)
- 10개 엔드포인트에 `@login_required` 적용
- `_can_approve_delete()`, `_can_manage_priority()` → 데코레이터 또는 ctx로 통합

### CP-03: 라우트 인증 체크 교체 (drawing.py)
- 7개 엔드포인트에 `@login_required` 적용
- `_can_write_drawings()` → 데코레이터로 통합

### CP-04: 라우트 인증 체크 교체 (delivery.py, sales.py, production.py)
- delivery.py 3개, sales.py 2개, production.py 2개 교체

### CP-05: 라우트 인증 체크 교체 (나머지)
- dashboard.py(1), contract.py(1), barcode.py(1), material.py(2), technical.py(1)
- dashboard.py `_is_admin()` → `@admin_required` 교체
- auth.py 6개 admin 체크 → `@admin_required` 교체

### CP-06: 에러 핸들링 개선 (project.py)
- 7개 except 블록에 `app.logger.error()` 추가
- 사용자에게 적절한 flash 메시지 유지
- 가능한 경우 구체적 예외 타입으로 교체

### CP-07: 에러 핸들링 개선 (나머지 라우트)
- auth.py(1), barcode.py(2), contract.py(1), drawing.py(2), technical.py(1)
- bare `except Exception:` → `except Exception as e:` + logging

### CP-08: DB 인덱스 추가
- `Project.is_contracted` — Boolean 인덱스
- `Contract.project_id` — FK 인덱스
- `Contract.delivery_due_date` — 날짜 범위 인덱스
- `HistoryLog.project_id` — FK 인덱스
- `Delivery.project_id` — FK 인덱스
- `ContractItem.contract_id` — FK 인덱스
- status 관련 복합 인덱스 검토

### CP-09: 백업 파일 제거
- `modules/models.back` 삭제
- `routes/project.back` 삭제

### CP-10: 통합 검증
- 전체 import 체크 (Python syntax validation)
- 데코레이터 적용 후 기존 동작 유지 확인

---

## 4. Estimated Impact

| 항목 | Before | After |
|------|--------|-------|
| 세션 체크 코드 | 30개소 반복 | `@login_required` 데코레이터 1줄 |
| Admin 체크 코드 | 12개소 반복 | `@admin_required` 데코레이터 1줄 |
| 에러 핸들링 | 14개 bare except | 구조화된 로깅 + 사용자 메시지 |
| DB 인덱스 | unique 제약만 | FK + 필터 컬럼 인덱스 추가 |
| 백업 파일 | 2개 (435 lines) | 0개 |

---

## 5. Dependencies & Risks

| 리스크 | 대응 |
|--------|------|
| 데코레이터 적용 시 기존 동작 변경 | functools.wraps 사용, 원래 redirect 동작 유지 |
| DB 인덱스 추가 시 테이블 락 | SQLite는 인덱스 추가 시 최소 영향 |
| auth.py의 admin 체크가 데코레이터와 다른 패턴 | login 관련 라우트는 제외 (비인증 상태 접근 필요) |

---

## 6. Success Criteria

- [ ] 모든 라우트에서 인증 체크가 데코레이터로 통일됨
- [ ] 14개 bare except가 모두 구조화된 핸들링으로 교체됨
- [ ] 주요 컬럼에 인덱스가 추가됨
- [ ] 백업 파일이 제거됨
- [ ] 기존 기능이 정상 동작함 (import 에러 없음)
