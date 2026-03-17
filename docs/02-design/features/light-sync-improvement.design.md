# Light-Sync Improvement Design Document

> **Summary**: 4단계 보안/안정성/리팩토링/성능 개선의 상세 기술 설계
>
> **Project**: Light-Sync (LED 조명기구 제조/납품 ERP)
> **Version**: 1.0
> **Author**: Claude Code + User
> **Date**: 2026-03-17
> **Status**: Draft
> **Planning Doc**: [light-sync-improvement.plan.md](../01-plan/features/light-sync-improvement.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- 운영 중인 시스템을 중단 없이 단계적으로 개선
- 기존 기능에 영향 없이 보안/안정성/성능 향상
- 코드 유지보수성 향상 (500줄 이내 파일, 중복 제거)
- OWASP Top 10 주요 항목 대응

### 1.2 Design Principles

- **점진적 개선**: 한 번에 전체 변경 대신 Phase별 독립 적용
- **하위 호환성**: 기존 URL, 세션, DB 스키마 유지
- **최소 의존성 추가**: Flask 생태계 표준 라이브러리 우선 사용
- **기존 패턴 존중**: MASTER_GUIDE.md 원칙 유지

---

## 2. Architecture

### 2.1 Current vs Target Architecture

```
[Current]                              [Target]
┌──────────────────────┐    ┌────────────────────────────────┐
│ app.py (하드코딩)     │    │ app.py + config.py (환경변수)    │
├──────────────────────┤    ├────────────────────────────────┤
│ routes/ (9 files)    │    │ routes/ (11 files)              │
│  project.py 2100줄   │    │  project.py ~400줄              │
│  (비즈니스+라우트혼재)  │    │  material.py (NEW) ~300줄       │
│                      │    │  barcode.py (NEW) ~200줄        │
├──────────────────────┤    ├────────────────────────────────┤
│ modules/             │    │ modules/                        │
│  models/ (ORM only)  │    │  models/ (ORM only)             │
│  (유틸 중복 4곳)      │    │  services/ (NEW - 비즈니스 로직) │
│                      │    │  utils.py (NEW - 공통 유틸)      │
│                      │    │  spec_utils.py (NEW - spec 로직) │
└──────────────────────┘    └────────────────────────────────┘
```

### 2.2 Data Flow (개선 후)

```
Request → CSRF Check → Auth Middleware → Route Handler
                                            ↓
                                    Service Layer (Business Logic)
                                            ↓
                                    DB Session (Context Manager)
                                            ↓
                                    Response / Template Render
```

### 2.3 New Dependencies

| Package | Version | Purpose | Phase |
|---------|---------|---------|-------|
| `Flask-WTF` | >=1.2.0 | CSRF Protection | Phase 1 |
| `Flask-Limiter` | >=3.5.0 | Rate Limiting | Phase 2 |
| `python-dotenv` | >=1.0.0 | 환경변수 로딩 | Phase 1 |

---

## 3. Phase 1: 긴급 보안 패치 — 상세 설계

### 3.1 config.py 생성 (FR-01~03)

**새 파일**: `config.py`

```python
import os
import secrets
from dotenv import load_dotenv

load_dotenv()  # .env 파일 자동 로딩

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    # Session security (FR-08, FR-09)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True       # HTTPS only
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 28800  # 8 hours in seconds

    # Server
    HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
    PORT = int(os.environ.get('FLASK_PORT', 8501))
    DOMAIN = os.environ.get('FLASK_DOMAIN', 'work.mgnt.kr')

    # File upload limits (FR-12)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # localhost에서는 HTTP 허용

class ProductionConfig(Config):
    DEBUG = False
```

**app.py 수정사항**:
```python
# Before
app.secret_key = "light_sync_secret"
LOCKED_DEBUG = True

# After
from config import ProductionConfig
app.config.from_object(ProductionConfig)
```

### 3.2 .env 파일 템플릿 (FR-01)

**새 파일**: `.env.example` (Git 추적용)

```env
# Flask
SECRET_KEY=<generate-with-python-c-"import secrets;print(secrets.token_hex(32))">
FLASK_DEBUG=false
FLASK_HOST=0.0.0.0
FLASK_PORT=8501
FLASK_DOMAIN=work.mgnt.kr

# Database (Supabase PostgreSQL)
DATABASE_URL=postgresql://postgres:<NEW_PASSWORD>@<HOST>:5432/postgres
DB_SCHEMA=light_sync

# Supabase Storage
SUPABASE_URL=https://<PROJECT_ID>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<NEW_SERVICE_ROLE_KEY>

# Kakao Work
KAKAOWORK_BOT_TOKEN=<NEW_BOT_TOKEN>

# Admin
ADMIN_DEFAULT_PASSWORD=<STRONG_PASSWORD>
```

**사용자 조치 필요**: Supabase/Kakao Work에서 새 크리덴셜 발급 후 `.env`에 설정

### 3.3 CSRF Protection (FR-04)

**app.py에 추가**:
```python
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)
```

**모든 HTML 폼에 추가** (48개 템플릿):
```html
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- 기존 필드들 -->
</form>
```

**AJAX 요청 처리** (base.html의 공통 JS):
```javascript
// meta 태그에 CSRF 토큰 삽입
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

// fetch 요청 시 자동 포함
const originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
    if (options.method && options.method.toUpperCase() !== 'GET') {
        options.headers = options.headers || {};
        options.headers['X-CSRFToken'] = csrfToken;
    }
    return originalFetch(url, options);
};
```

### 3.4 권한 체크 강화 (FR-05)

**auth.py 수정 — approve_user**:
```python
# Before: GET, 권한 체크 없음
@auth_bp.route('/approve_user/<int:user_id>')
def approve_user(user_id):
    db = SessionLocal()
    user = db.query(User).get(user_id)
    if user: user.is_approved = True; db.commit()
    db.close()
    return redirect(url_for('auth.admin_settings'))

# After: POST, 관리자 권한 체크, try/finally
@auth_bp.route('/approve_user/<int:user_id>', methods=['POST'])
def approve_user(user_id):
    if session.get('role') != 'admin':
        flash("권한이 없습니다.", "danger")
        return redirect(url_for('dashboard.dashboard_view'))
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user:
            user.is_approved = True
            db.commit()
            flash(f"{user.full_name} 계정이 승인되었습니다.", "success")
    finally:
        db.close()
    return redirect(url_for('auth.admin_settings'))
```

**auth.py 수정 — reject_user**:
```python
# Before: GET 메서드
@auth_bp.route('/reject_user/<int:user_id>')

# After: POST 메서드
@auth_bp.route('/reject_user/<int:user_id>', methods=['POST'])
```

**admin_settings.html 수정** — 승인/거절 링크를 POST 폼으로 변경:
```html
<!-- Before -->
<a href="{{ url_for('auth.approve_user', user_id=u.id) }}">승인</a>

<!-- After -->
<form method="POST" action="{{ url_for('auth.approve_user', user_id=u.id) }}" style="display:inline">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <button type="submit" class="btn btn-success btn-sm">승인</button>
</form>
```

### 3.5 회원가입 검증 (FR-07)

**auth.py register() 수정**:
```python
@auth_bp.route('/register', methods=['POST'])
def register():
    username = (request.form.get('new_username') or '').strip()
    password = request.form.get('new_password') or ''
    fullname = (request.form.get('new_fullname') or '').strip()
    phone = (request.form.get('new_phone') or '').strip()
    group = request.form.get('new_group') or ''

    # Validation
    errors = []
    if len(username) < 3:
        errors.append("아이디는 3자 이상 입력해주세요.")
    if len(password) < 6:
        errors.append("비밀번호는 6자 이상 입력해주세요.")
    if not fullname:
        errors.append("이름을 입력해주세요.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for('auth.login'))

    db = SessionLocal()
    try:
        # 중복 체크
        if db.query(User).filter(User.username == username).first():
            flash("이미 존재하는 아이디입니다.", "danger")
            return redirect(url_for('auth.login'))

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db.add(User(
            username=username, password_hash=hashed_pw,
            full_name=fullname, phone_number=phone,
            user_group=group, is_approved=False
        ))
        db.commit()
        flash("가입 신청 완료!", "success")
    except Exception:
        db.rollback()
        flash("가입 처리 중 오류가 발생했습니다.", "danger")
    finally:
        db.close()
    return redirect(url_for('auth.login'))
```

### 3.6 Admin 기본 비밀번호 (FR-06)

**db.py init_db() 수정**:
```python
# Before
hashed_pw = bcrypt.hashpw("admin1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# After
admin_pw = os.environ.get('ADMIN_DEFAULT_PASSWORD', 'admin1234')
hashed_pw = bcrypt.hashpw(admin_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
```

---

## 4. Phase 2: 안정성 확보 — 상세 설계

### 4.1 DB Session Context Manager (FR-10)

**새 파일**: `modules/db_context.py`

```python
from contextlib import contextmanager
from modules.models import SessionLocal

@contextmanager
def get_db():
    """안전한 DB 세션 컨텍스트 매니저"""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

**라우트에서 사용 패턴**:
```python
# Before (모든 라우트에서 반복)
db = SessionLocal()
# ... 로직 ...
db.close()  # 예외 시 누수

# After
from modules.db_context import get_db

@auth_bp.route('/admin_settings')
def admin_settings():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard.dashboard_view'))
    with get_db() as db:
        pending = db.query(User).filter(User.is_approved == False).all()
        users = db.query(User).filter(User.is_approved == True).order_by(User.created_at.desc()).all()
        # ... 나머지 로직 ...
        return render_template('admin_settings.html', pending=pending, users=users)
```

**적용 대상**: 전체 9개 라우트 파일의 모든 엔드포인트 (~50개 함수)

### 4.2 Safe Integer Parsing (FR-11)

**modules/utils.py에 통합**:
```python
def safe_int(value, default=0):
    """안전한 정수 변환"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default
```

**적용 대상**:
- `routes/production.py`: 라인 510, 543, 654, 729
- `routes/sales.py`: 라인 304
- `routes/delivery.py`: 라인 69

### 4.3 파일 업로드 검증 (FR-12)

**modules/utils.py에 추가**:
```python
ALLOWED_EXTENSIONS = {'pdf', 'dwg', 'png', 'jpg', 'jpeg', 'gif', 'xlsx', 'docx'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

def validate_upload(file):
    """업로드 파일 검증"""
    if not file or not file.filename:
        return False, "파일이 선택되지 않았습니다."

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"허용되지 않는 파일 형식입니다: .{ext}"

    # Content-Length 기반 크기 체크 (app.config MAX_CONTENT_LENGTH으로 자동 제한됨)
    return True, "ok"
```

### 4.4 Rate Limiting (FR-13)

**app.py에 추가**:
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour"]
)
```

**auth.py 적용**:
```python
from app import limiter  # 또는 Blueprint에서 limit 데코레이터 사용

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    # ...

@auth_bp.route('/register', methods=['POST'])
@limiter.limit("3 per minute")
def register():
    # ...
```

### 4.5 에러 핸들링 (FR-14)

**app.py에 추가**:
```python
import logging
from logging.handlers import RotatingFileHandler

# 로깅 설정
handler = RotatingFileHandler('logs/light_sync.log', maxBytes=10_000_000, backupCount=5)
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s [%(name)s] %(message)s'
))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="페이지를 찾을 수 없습니다."), 404

@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"Internal error: {e}")
    return render_template('error.html', code=500, message="서버 오류가 발생했습니다."), 500
```

### 4.6 Open Redirect 방지 (FR-15)

**drawing.py 수정**:
```python
from urllib.parse import urlparse

def _safe_next_url(default_endpoint, **default_kwargs):
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    # 상대 경로만 허용, // 시작 차단 (//evil.com 방지)
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        parsed = urlparse(next_url)
        if not parsed.netloc:  # 호스트명이 없는 경우만 허용
            return next_url
    return url_for(default_endpoint, **default_kwargs)
```

---

## 5. Phase 3: 코드 리팩토링 — 상세 설계

### 5.1 공통 유틸리티 추출 (FR-16)

**새 파일**: `modules/utils.py`

```python
import datetime

def parse_date(value):
    """날짜 문자열 → date 객체 변환"""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None

def safe_int(value, default=0):
    """안전한 정수 변환"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default

def is_true_value(value):
    """폼 데이터의 truthy 체크"""
    return str(value).lower() in ('1', 'true', 'on', 'yes') if value else False
```

**제거 대상 (중복)**:
| 함수 | 파일 | 라인 |
|------|------|------|
| `_parse_date()` | `routes/project.py` | ~213 |
| `_parse_date()` | `routes/sales.py` | ~31 |
| `_parse_date()` | `routes/production.py` | ~37 |
| `_parse_date()` | `routes/delivery.py` | ~60 |
| `_to_int()` | `routes/project.py` | ~228 |
| `_to_int()` | `routes/production.py` | ~241 |
| `_to_int()` | `routes/delivery.py` | ~69 |
| `_is_true_value()` | `routes/project.py` | ~41 |
| `_is_true_value()` | `routes/sales.py` | ~27 |

### 5.2 Spec 로직 통합 (FR-17)

**새 파일**: `modules/spec_utils.py`

`routes/sales.py`의 `_extract_item_spec()`과 `routes/project.py`의 `_extract_contract_item_spec()`을 하나로 통합. 검증 로직도 동일하게 통합.

### 5.3 project.py 분할 (FR-18)

**현재 project.py (~2,100줄) → 3개 파일로 분할**:

| 새 파일 | 함수들 | 예상 라인 |
|---------|--------|----------|
| `routes/project.py` | project CRUD, detail, list, delete request | ~500줄 |
| `routes/material.py` (NEW) | material_management, material_detail, material sync | ~400줄 |
| `routes/barcode.py` (NEW) | barcode 관련 엔드포인트, xlsx 빌더 | ~300줄 |

**Blueprint 등록**:
```python
# app.py에 추가
from routes.material import material_bp
from routes.barcode import barcode_bp
app.register_blueprint(material_bp)
app.register_blueprint(barcode_bp)
```

### 5.4 서비스 레이어 분리 (FR-19)

**새 디렉토리**: `modules/services/`

| 파일 | 이전 위치 | 핵심 함수 |
|------|----------|----------|
| `material_service.py` | project.py | `sync_material_orders()`, `compute_admin_status()`, `refresh_admin_statuses()` |
| `production_service.py` | production.py | `sync_production_processes()`, `refresh_production_statuses()` |
| `delivery_service.py` | delivery.py | `sync_deliveries()`, `compute_delivery_status()` |

### 5.5 데드코드 제거 (FR-20)

**db.py에서 제거할 코드**: `_is_sqlite_engine()` 함수(항상 False 반환)와 그 아래의 SQLite ALTER TABLE 블록 전체 (~170줄, 라인 70~246)

### 5.6 부팅 시 정규화 제거 (FR-21)

**db.py init_db()에서 분리**:
- 라인 247~301의 데이터 정규화 로직을 `scripts/normalize_data.py`로 이동
- `init_db()`에서는 스키마 생성 + 초기 데이터 시딩만 수행
- 정규화는 별도 마이그레이션 스크립트로 1회 실행

---

## 6. Phase 4: 성능 최적화 — 상세 설계

### 6.1 GET 동기화 제거 (FR-22)

**현재 문제**: 페이지 조회(GET)마다 DB에 INSERT/UPDATE 실행

| 라우트 | 문제 함수 | 개선 방안 |
|--------|----------|----------|
| `production.py` | `sync_production_processes()` on GET | POST(상태 변경) 시에만 호출 |
| `delivery.py` | `_sync_deliveries()` on GET | POST(계약/납품 변경) 시에만 호출 |
| `project.py` | `_sync_material_orders()` on GET | POST(자재 변경) 시에만 호출 |

**수동 동기화 버튼 추가** (각 관리 페이지):
```html
<form method="POST" action="{{ url_for('production.sync_processes') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <button type="submit" class="btn btn-outline-secondary btn-sm">
        🔄 데이터 동기화
    </button>
</form>
```

### 6.2 DB 인덱스 추가 (FR-23)

**entities.py에 인덱스 정의 추가**:

```python
from sqlalchemy import Index

# Contract 테이블
Index('ix_contracts_project_id', Contract.project_id)
Index('ix_contracts_delivery_due_date', Contract.delivery_due_date)

# ContractItem 테이블
Index('ix_contract_items_contract_id', ContractItem.contract_id)
Index('ix_contract_items_status_prod', ContractItem.status_prod)

# HistoryLog 테이블
Index('ix_history_logs_project_id_created', HistoryLog.project_id, HistoryLog.created_at)

# MaterialOrder 테이블
Index('ix_material_orders_contract_item_id', MaterialOrder.contract_item_id)
Index('ix_material_orders_order_status', MaterialOrder.order_status)

# ProductionProcess 테이블
Index('ix_prod_processes_contract_item_id', ProductionProcess.contract_item_id)

# Delivery 테이블
Index('ix_deliveries_contract_id', Delivery.contract_id)
```

### 6.3 Storage Config 캐싱 (FR-24)

**storage_adapter.py 수정**:
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_storage_config():
    # 기존 로직 동일 — 하지만 1번만 실행
    ...
```

### 6.4 SERVER_NAME 제거 (FR-25)

**app.py에서 제거**:
```python
# Before
app.config["SERVER_NAME"] = LOCKED_DOMAIN

# After — 삭제 (리버스 프록시가 도메인 처리)
# SERVER_NAME 제거, force_locked_domain()은 유지
```

### 6.5 로깅 프레임워크 (FR-26)

Phase 2 (4.5)에서 설계한 로깅 설정 활용. 추가로 각 라우트에서:

```python
import logging
logger = logging.getLogger(__name__)

# print() 대신
logger.info("Drawing uploaded: %s", filename)
logger.error("Upload failed: %s", str(e))
```

---

## 7. Security Considerations

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| CSRF | 없음 | Flask-WTF CSRFProtect 전역 적용 |
| Session | 만료 없음, 쿠키 보안 없음 | 8시간 만료, HttpOnly + Secure + SameSite=Lax |
| Secret Key | 하드코딩 `"light_sync_secret"` | 환경변수 기반 32바이트 랜덤 키 |
| Debug Mode | `True` (Werkzeug 디버거 노출) | `False` (운영), `True` (개발환경만) |
| Rate Limiting | 없음 | 로그인 10/분, 가입 3/분 |
| Input Validation | 없음 | 가입 시 길이/형식/중복 검증 |
| File Upload | 확장자만 체크 | 확장자 + 크기 제한 (50MB) |
| Open Redirect | `//evil.com` 가능 | `urlparse` 검증 추가 |
| Admin Auth | approve_user GET 무인가 | POST + admin 권한 체크 |
| Credentials | Git에 평문 노출 | `.env` + `.gitignore` + 크리덴셜 교체 |

---

## 8. Implementation Order

### Phase 1 구현 순서 (긴급 보안)

| # | Task | 파일 | 의존성 |
|---|------|------|--------|
| 1-1 | `python-dotenv`, `Flask-WTF` 설치 | requirements.txt | 없음 |
| 1-2 | `config.py` 생성 | config.py (NEW) | 없음 |
| 1-3 | `.env.example` 생성 | .env.example (NEW) | 없음 |
| 1-4 | `app.py` 수정 (config 적용, CSRF, SERVER_NAME 제거) | app.py | 1-1, 1-2 |
| 1-5 | `base.html`에 CSRF meta 태그 + 공통 JS 추가 | templates/base.html | 1-4 |
| 1-6 | 전체 HTML 폼에 `csrf_token` 추가 | templates/*.html (48개) | 1-5 |
| 1-7 | `auth.py` 보안 강화 (approve/reject POST, 가입 검증) | routes/auth.py | 1-6 |
| 1-8 | `admin_settings.html` 승인/거절 폼 변경 | templates/admin_settings.html | 1-7 |
| 1-9 | `db.py` admin 비밀번호 환경변수화 | modules/models/db.py | 1-2 |

### Phase 2 구현 순서 (안정성)

| # | Task | 파일 | 의존성 |
|---|------|------|--------|
| 2-1 | `modules/db_context.py` 생성 | modules/db_context.py (NEW) | 없음 |
| 2-2 | `modules/utils.py` 생성 (safe_int, validate_upload) | modules/utils.py (NEW) | 없음 |
| 2-3 | `Flask-Limiter` 설치 + app.py 적용 | requirements.txt, app.py | 없음 |
| 2-4 | 전체 라우트 DB 세션 → `with get_db()` 전환 | routes/*.py (9개) | 2-1 |
| 2-5 | `int()` → `safe_int()` 전환 | routes/production.py, sales.py, delivery.py | 2-2 |
| 2-6 | Rate Limiting 적용 (auth 엔드포인트) | routes/auth.py | 2-3 |
| 2-7 | Open redirect 수정 | routes/drawing.py | 없음 |
| 2-8 | `bare except` → `except Exception` + 로깅 | modules/models/db.py | 없음 |
| 2-9 | 에러 핸들러 + 에러 페이지 템플릿 | app.py, templates/error.html (NEW) | 없음 |

### Phase 3 구현 순서 (리팩토링)

| # | Task | 파일 | 의존성 |
|---|------|------|--------|
| 3-1 | `modules/utils.py` 확장 (parse_date, is_true_value) | modules/utils.py | Phase 2 완료 |
| 3-2 | `modules/spec_utils.py` 생성 | modules/spec_utils.py (NEW) | 없음 |
| 3-3 | 4개 라우트에서 중복 유틸 제거 → import 전환 | routes/*.py | 3-1 |
| 3-4 | spec 중복 제거 → import 전환 | routes/sales.py, project.py | 3-2 |
| 3-5 | `modules/services/` 디렉토리 + 서비스 파일 생성 | modules/services/*.py (NEW) | 없음 |
| 3-6 | project.py에서 material 라우트 분리 | routes/material.py (NEW) | 3-5 |
| 3-7 | project.py에서 barcode 라우트 분리 | routes/barcode.py (NEW) | 3-6 |
| 3-8 | app.py에 새 Blueprint 등록 | app.py | 3-6, 3-7 |
| 3-9 | db.py SQLite 데드코드 제거 | modules/models/db.py | 없음 |
| 3-10 | db.py 부팅 시 정규화 → 별도 스크립트 | scripts/normalize_data.py (NEW) | 없음 |

### Phase 4 구현 순서 (성능 최적화)

| # | Task | 파일 | 의존성 |
|---|------|------|--------|
| 4-1 | GET 동기화 제거 + POST 이벤트 기반 전환 | routes/production.py, delivery.py, project.py | Phase 3 완료 |
| 4-2 | 수동 동기화 버튼 추가 (각 관리 페이지) | templates/*.html | 4-1 |
| 4-3 | DB 인덱스 추가 | modules/models/entities.py | 없음 |
| 4-4 | storage_adapter.py 캐싱 | modules/storage_adapter.py | 없음 |
| 4-5 | 로깅 프레임워크 도입 (print→logging) | 전체 | Phase 2 완료 |
| 4-6 | Query.get() → session.get() 마이그레이션 | routes/*.py | 없음 |

---

## 9. New/Modified Files Summary

| 구분 | 파일 | Phase |
|------|------|-------|
| **NEW** | `config.py` | 1 |
| **NEW** | `.env.example` | 1 |
| **NEW** | `modules/db_context.py` | 2 |
| **NEW** | `modules/utils.py` | 2-3 |
| **NEW** | `modules/spec_utils.py` | 3 |
| **NEW** | `modules/services/__init__.py` | 3 |
| **NEW** | `modules/services/material_service.py` | 3 |
| **NEW** | `modules/services/production_service.py` | 3 |
| **NEW** | `modules/services/delivery_service.py` | 3 |
| **NEW** | `routes/material.py` | 3 |
| **NEW** | `routes/barcode.py` | 3 |
| **NEW** | `templates/error.html` | 2 |
| **NEW** | `scripts/normalize_data.py` | 3 |
| **MODIFY** | `app.py` | 1-2 |
| **MODIFY** | `requirements.txt` | 1-2 |
| **MODIFY** | `routes/auth.py` | 1-2 |
| **MODIFY** | `routes/project.py` | 3 (분할) |
| **MODIFY** | `routes/production.py` | 2-4 |
| **MODIFY** | `routes/delivery.py` | 2-4 |
| **MODIFY** | `routes/sales.py` | 2-3 |
| **MODIFY** | `routes/drawing.py` | 2 |
| **MODIFY** | `modules/models/db.py` | 1, 3 |
| **MODIFY** | `modules/models/entities.py` | 4 (인덱스) |
| **MODIFY** | `modules/storage_adapter.py` | 4 |
| **MODIFY** | `templates/base.html` | 1 (CSRF) |
| **MODIFY** | `templates/*.html` (48개) | 1 (CSRF 토큰) |

---

## 10. Coding Convention Reference

### 10.1 Python Conventions (이 프로젝트용)

| Target | Rule | Example |
|--------|------|---------|
| 함수명 | snake_case | `get_user_by_id()`, `sync_deliveries()` |
| 클래스명 | PascalCase | `User`, `ContractItem` |
| 상수 | UPPER_SNAKE_CASE | `MAX_FILE_SIZE`, `LOCKED_DOMAIN` |
| 파일명 | snake_case | `material_service.py` |
| Blueprint | 모듈명_bp | `material_bp`, `barcode_bp` |

### 10.2 Import Order

```python
# 1. 표준 라이브러리
import os
import datetime
from pathlib import Path

# 2. 서드파티
from flask import Blueprint, request, session
from sqlalchemy.orm import joinedload

# 3. 로컬 모듈
from modules.db_context import get_db
from modules.utils import parse_date, safe_int
from modules.models import User, Contract
```

### 10.3 DB Session Convention

```python
# 반드시 context manager 사용
with get_db() as db:
    result = db.query(Model).filter(...).all()
    # db.commit() 필요 시
    db.commit()
# 자동 close + 예외 시 자동 rollback
```

### 10.4 Error Handling Convention

```python
# 외부 입력 처리 시
value = safe_int(request.form.get('id'))
date = parse_date(request.form.get('date'))

# DB 작업 시
with get_db() as db:
    try:
        # 비즈니스 로직
        db.commit()
        flash("성공 메시지", "success")
    except Exception as e:
        db.rollback()
        app.logger.error(f"Error in {endpoint}: {e}")
        flash("처리 중 오류가 발생했습니다.", "danger")
```

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial design based on Plan document | Claude Code |
