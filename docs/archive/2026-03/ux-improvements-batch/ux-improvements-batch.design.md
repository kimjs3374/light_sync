# UX 개선 5종 일괄 Design Document

> **Summary**: 설계관리 검색/필터, 비밀번호 변경, 페이지네이션, 알림센터, 프로젝트 종합현황 뷰 상세 설계
>
> **Project**: Light-Sync ERP
> **Author**: ENG
> **Date**: 2026-03-17
> **Status**: Draft
> **Planning Doc**: [ux-improvements-batch.plan.md](../../01-plan/features/ux-improvements-batch.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- 기존 코드 패턴(contract_list 검색/필터)을 최대한 재활용하여 일관성 확보
- 공통 유틸리티(페이지네이션)를 한 번 만들고 전체 리스트에 적용
- 신규 모델(Notification) 추가를 최소화하면서 알림 기능 구현
- 모바일 반응형 기존 패턴(`mobile-stack-table`) 유지

### 1.2 Design Principles

- 기존 코드 패턴 준수 (Blueprint, get_db(), flash, Jinja2 템플릿)
- 최소 변경 원칙 — 기존 동작을 깨뜨리지 않음
- 공통 컴포넌트 추출 (pagination, notification dropdown)

---

## 2. Architecture

### 2.1 Component Diagram

```
기존 구조 유지:
Browser ──→ Flask (Blueprint routes) ──→ SQLAlchemy ──→ PostgreSQL

신규 추가:
├── modules/pagination.py          (공통 유틸)
├── routes/notification.py         (알림 Blueprint)
├── routes/overview.py             (종합현황 Blueprint)
├── templates/components/          (공통 컴포넌트)
│   ├── pagination.html
│   ├── notification_dropdown.html
│   └── change_password_modal.html
├── templates/notification_center.html
└── templates/project_overview.html
```

### 2.2 신규 Blueprint 등록 (app.py)

```python
from routes.notification import notification_bp
from routes.overview import overview_bp
app.register_blueprint(notification_bp)
app.register_blueprint(overview_bp)
```

---

## 3. Data Model

### 3.1 Notification 모델 (신규)

```python
class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    noti_type = Column(String(30), nullable=False, default='system')
        # delivery_due, material_pending, production_delay, contract_new, system
    link = Column(String(500), nullable=True)       # 클릭 시 이동 URL
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship("User")
```

### 3.2 기존 모델 변경: 없음

---

## 4. Feature 1: 설계관리 검색/필터

### 4.1 Route 변경: `routes/project.py` → `project_list()`

```python
@project_bp.route('/project_list')
@login_required
def project_list():
    q = (request.args.get('q') or '').strip().lower()
    status_filter = request.args.get('status', 'all')   # all/진행중/계약완료/긴급
    due_filter = request.args.get('due', 'all')          # all/overdue/week/twoweek
    sort_by = request.args.get('sort', 'created_desc')   # created_desc/due_asc/due_desc
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 20)

    with get_db() as db:
        today = datetime.date.today()
        projects = db.query(Project).options(
            joinedload(Project.materials),
            joinedload(Project.contacts),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        # 검색
        filtered = []
        for p in projects:
            search_pool = ' '.join([
                p.project_no or '', p.temp_name or '', p.short_name or ''
            ]).lower()
            if q and q not in search_pool:
                continue

            # 상태 필터
            if status_filter == '진행중' and p.is_contracted:
                continue
            if status_filter == '계약완료' and not p.is_contracted:
                continue
            if status_filter == '긴급' and not p.is_urgent:
                continue

            # D-Day 필터
            dday = (p.expected_contract_date - today).days if p.expected_contract_date else None
            if due_filter == 'overdue' and (dday is None or dday >= 0):
                continue
            if due_filter == 'week' and (dday is None or dday > 7 or dday < 0):
                continue
            if due_filter == 'twoweek' and (dday is None or dday > 14 or dday < 0):
                continue

            filtered.append(p)

        # 정렬
        if sort_by == 'due_asc':
            filtered.sort(key=lambda p: p.expected_contract_date or datetime.date.max)
        elif sort_by == 'due_desc':
            filtered.sort(key=lambda p: p.expected_contract_date or datetime.date.min, reverse=True)
        # created_desc는 이미 id desc

        # 통계
        stats = {
            'total': len(projects),
            'filtered': len(filtered),
            'overdue': sum(1 for p in projects if p.expected_contract_date and (p.expected_contract_date - today).days < 0 and not p.is_contracted),
            'urgent': sum(1 for p in projects if p.is_urgent and not p.is_contracted),
        }

        # 페이지네이션
        total = len(filtered)
        paginated = filtered[(page-1)*per_page : page*per_page]

        # 필터 상태 유지
        filters = {'q': q, 'status': status_filter, 'due': due_filter, 'sort': sort_by}
        pagination = make_pagination(page, per_page, total)

        # ... priority_projects 로직 유지 ...

        return render_template('project_list.html',
            projects=paginated, today=today,
            priority_projects=priority_projects,
            stats=stats, filters=filters, pagination=pagination)
```

### 4.2 Template: `project_list.html` 변경

제목 아래, 테이블 위에 contract_list.html과 동일한 패턴의 검색 폼 추가:

```html
<!-- 통계 카드 -->
<div class="row g-3 mb-3">
    <div class="col-md-2 col-6"><div class="card ..."><small>전체</small><div>{{ stats.total }}</div></div></div>
    <div class="col-md-2 col-6"><div class="card ..."><small>조회 결과</small><div>{{ stats.filtered }}</div></div></div>
    <div class="col-md-2 col-6"><div class="card ... border-danger"><small>지연(D+)</small><div>{{ stats.overdue }}</div></div></div>
    <div class="col-md-2 col-6"><div class="card ... border-dark"><small>긴급건</small><div>{{ stats.urgent }}</div></div></div>
</div>

<!-- 검색 폼 -->
<form class="card border-0 shadow-sm mb-4" method="GET">
    <div class="card-body row g-2 align-items-end">
        <div class="col-md-3">
            <label>검색</label>
            <input name="q" value="{{ filters.q }}" placeholder="관리번호/현장명/약칭">
        </div>
        <div class="col-md-2">
            <label>상태</label>
            <select name="status">
                <option value="all">전체</option>
                <option value="진행중">진행중</option>
                <option value="계약완료">계약완료</option>
                <option value="긴급">긴급</option>
            </select>
        </div>
        <div class="col-md-2">
            <label>계약예정일</label>
            <select name="due">
                <option value="all">전체</option>
                <option value="overdue">지연(D+)</option>
                <option value="week">7일 이내</option>
                <option value="twoweek">14일 이내</option>
            </select>
        </div>
        <div class="col-md-2">
            <label>정렬</label>
            <select name="sort">
                <option value="created_desc">최신등록순</option>
                <option value="due_asc">계약예정일 임박순</option>
                <option value="due_desc">계약예정일 여유순</option>
            </select>
        </div>
        <div class="col-md-3 text-md-end">
            <a href="{{ url_for('project.project_list') }}" class="btn btn-outline-secondary btn-sm">초기화</a>
            <button class="btn btn-primary btn-sm fw-bold">검색</button>
        </div>
    </div>
</form>
```

---

## 5. Feature 2: 비밀번호 변경

### 5.1 Route: `routes/auth.py` 추가

```python
@auth_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    if new_pw != confirm_pw:
        flash('새 비밀번호가 일치하지 않습니다.', 'danger')
        return redirect(request.referrer or url_for('dashboard.dashboard_view'))

    if len(new_pw) < 6:
        flash('새 비밀번호는 6자 이상이어야 합니다.', 'danger')
        return redirect(request.referrer or url_for('dashboard.dashboard_view'))

    with get_db() as db:
        user = db.get(User, session['user_id'])
        if not user or not bcrypt.checkpw(current_pw.encode('utf-8'), user.password_hash.encode('utf-8')):
            flash('현재 비밀번호가 올바르지 않습니다.', 'danger')
            return redirect(request.referrer or url_for('dashboard.dashboard_view'))

        user.password_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db.commit()
        flash('비밀번호가 변경되었습니다.', 'success')
    return redirect(request.referrer or url_for('dashboard.dashboard_view'))
```

### 5.2 Route: 관리자 비밀번호 초기화 (admin_settings)

```python
@auth_bp.route('/reset_password/<int:user_id>', methods=['POST'])
@admin_required
def reset_password(user_id):
    new_pw = request.form.get('reset_password', '')
    if len(new_pw) < 6:
        flash('비밀번호는 6자 이상이어야 합니다.', 'danger')
        return redirect(url_for('auth.admin_settings'))

    with get_db() as db:
        user = db.get(User, user_id)
        if user:
            user.password_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.commit()
            flash(f'{user.full_name} 비밀번호가 초기화되었습니다.', 'success')
    return redirect(url_for('auth.admin_settings'))
```

### 5.3 Template: `components/change_password_modal.html`

```html
<!-- base.html 사이드바 하단에 버튼 추가 -->
<button class="btn btn-sm btn-outline-light mt-2" data-bs-toggle="modal" data-bs-target="#changePasswordModal">
    🔒 비밀번호 변경
</button>

<!-- 모달 -->
<div class="modal fade" id="changePasswordModal">
    <form method="POST" action="{{ url_for('auth.change_password') }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="password" name="current_password" required placeholder="현재 비밀번호">
        <input type="password" name="new_password" required minlength="6" placeholder="새 비밀번호 (6자 이상)">
        <input type="password" name="confirm_password" required placeholder="새 비밀번호 확인">
        <button type="submit">변경</button>
    </form>
</div>
```

---

## 6. Feature 3: 페이지네이션

### 6.1 공통 유틸: `modules/pagination.py`

```python
import math

def make_pagination(page, per_page, total, window=2):
    """페이지네이션 메타데이터 생성"""
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))

    start = max(1, page - window)
    end = min(total_pages, page + window)

    return {
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_page': page - 1,
        'next_page': page + 1,
        'page_range': list(range(start, end + 1)),
        'show_first': start > 1,
        'show_last': end < total_pages,
    }
```

### 6.2 공통 템플릿: `templates/components/pagination.html`

```html
{% if pagination and pagination.total_pages > 1 %}
<nav class="d-flex justify-content-between align-items-center mt-3 flex-wrap gap-2">
    <small class="text-muted">
        전체 {{ pagination.total }}건 / {{ pagination.page }} of {{ pagination.total_pages }} 페이지
    </small>
    <ul class="pagination pagination-sm mb-0">
        {% if pagination.has_prev %}
        <li class="page-item"><a class="page-link" href="?{{ pagination_query(pagination.prev_page) }}">‹</a></li>
        {% endif %}
        {% if pagination.show_first %}
        <li class="page-item"><a class="page-link" href="?{{ pagination_query(1) }}">1</a></li>
        <li class="page-item disabled"><span class="page-link">…</span></li>
        {% endif %}
        {% for p in pagination.page_range %}
        <li class="page-item {% if p == pagination.page %}active{% endif %}">
            <a class="page-link" href="?{{ pagination_query(p) }}">{{ p }}</a>
        </li>
        {% endfor %}
        {% if pagination.show_last %}
        <li class="page-item disabled"><span class="page-link">…</span></li>
        <li class="page-item"><a class="page-link" href="?{{ pagination_query(pagination.total_pages) }}">{{ pagination.total_pages }}</a></li>
        {% endif %}
        {% if pagination.has_next %}
        <li class="page-item"><a class="page-link" href="?{{ pagination_query(pagination.next_page) }}">›</a></li>
        {% endif %}
    </ul>
</nav>
{% endif %}
```

### 6.3 쿼리스트링 보존 헬퍼: `modules/pagination.py`

```python
from flask import request

def pagination_query_helper(page_num):
    """현재 필터 쿼리스트링을 유지하면서 page 파라미터만 교체"""
    args = request.args.to_dict()
    args['page'] = page_num
    return '&'.join(f'{k}={v}' for k, v in args.items())
```

app.py의 Jinja2 global에 등록:

```python
app.jinja_env.globals['pagination_query'] = pagination_query_helper
```

### 6.4 적용 대상 라우트 (6개)

| 라우트 | 파일 | 함수명 |
|--------|------|--------|
| /project_list | routes/project.py | project_list() |
| /contract_list | routes/project.py | contract_list() |
| /sales_management | routes/sales.py | sales_list() |
| /material_management | routes/material.py | material_management() |
| /production_management | routes/production.py | production_management() |
| /delivery_management | routes/delivery.py | delivery_management() |

각 라우트에 동일 패턴 적용:
1. `page`, `per_page` 파라미터 수신
2. 필터링 후 `make_pagination()` 호출
3. 슬라이싱: `filtered[(page-1)*per_page : page*per_page]`
4. 템플릿에 `pagination` 전달
5. 테이블 아래 `{% include 'components/pagination.html' %}` 추가

---

## 7. Feature 4: 알림센터

### 7.1 Route: `routes/notification.py`

```python
notification_bp = Blueprint('notification', __name__)

@notification_bp.route('/notifications')
@login_required
def notification_list():
    """알림 전체 목록 페이지"""
    page = safe_int(request.args.get('page'), 1)
    per_page = 30
    with get_db() as db:
        user_id = session['user_id']
        total = db.query(Notification).filter(Notification.user_id == user_id).count()
        items = db.query(Notification).filter(
            Notification.user_id == user_id
        ).order_by(Notification.created_at.desc()).offset((page-1)*per_page).limit(per_page).all()
        pagination = make_pagination(page, per_page, total)
        return render_template('notification_center.html', notifications=items, pagination=pagination)

@notification_bp.route('/api/notifications/unread-count')
@login_required
def unread_count():
    """AJAX: 미확인 알림 수"""
    with get_db() as db:
        count = db.query(Notification).filter(
            Notification.user_id == session['user_id'],
            Notification.is_read == False
        ).count()
        return jsonify({'count': count})

@notification_bp.route('/api/notifications/recent')
@login_required
def recent_notifications():
    """AJAX: 최근 20건 (드롭다운용)"""
    with get_db() as db:
        items = db.query(Notification).filter(
            Notification.user_id == session['user_id']
        ).order_by(Notification.created_at.desc()).limit(20).all()
        return jsonify({'items': [{
            'id': n.id, 'title': n.title, 'message': n.message,
            'noti_type': n.noti_type, 'link': n.link,
            'is_read': n.is_read, 'created_at': str(n.created_at)[:16]
        } for n in items]})

@notification_bp.route('/api/notifications/<int:noti_id>/read', methods=['POST'])
@login_required
def mark_read(noti_id):
    """알림 읽음 처리"""
    with get_db() as db:
        noti = db.get(Notification, noti_id)
        if noti and noti.user_id == session['user_id']:
            noti.is_read = True
            db.commit()
        return jsonify({'ok': True})

@notification_bp.route('/api/notifications/read-all', methods=['POST'])
@login_required
def mark_all_read():
    """전체 읽음 처리"""
    with get_db() as db:
        db.query(Notification).filter(
            Notification.user_id == session['user_id'],
            Notification.is_read == False
        ).update({'is_read': True})
        db.commit()
        return jsonify({'ok': True})
```

### 7.2 알림 생성 유틸: `modules/notification_utils.py`

```python
def create_notification(db, user_id, title, message, noti_type='system', link=None):
    """알림 생성 헬퍼"""
    db.add(Notification(
        user_id=user_id, title=title, message=message,
        noti_type=noti_type, link=link
    ))

def create_notification_for_group(db, group_name, title, message, noti_type='system', link=None):
    """특정 그룹 전체에 알림"""
    users = db.query(User).filter(User.user_group == group_name, User.is_active == True).all()
    for user in users:
        create_notification(db, user.id, title, message, noti_type, link)

def create_notification_for_all(db, title, message, noti_type='system', link=None):
    """활성 사용자 전체에 알림"""
    users = db.query(User).filter(User.is_active == True, User.is_approved == True).all()
    for user in users:
        create_notification(db, user.id, title, message, noti_type, link)
```

### 7.3 자동 알림 트리거 (기존 코드에 추가)

| 트리거 위치 | 조건 | 알림 유형 | 대상 |
|-------------|------|-----------|------|
| 대시보드 로드 시 | 납기 7일 이내 계약건 | delivery_due | 영업부, 관리부 |
| 자재 상태변경 시 | 발주완료 → 입고완료 | material_pending | 생산부 |
| 계약 생성 시 | 신규 계약 | contract_new | 전체 |

### 7.4 UI: base.html 헤더 알림 아이콘

사이드바 상단에 알림 아이콘 추가:

```html
<div class="text-center mb-2">
    <a href="{{ url_for('notification.notification_list') }}" class="text-white position-relative" id="notiBtn">
        🔔 <span class="badge bg-danger rounded-pill position-absolute" id="notiBadge" style="display:none; top:-5px; right:-10px; font-size:.65rem;">0</span>
    </a>
</div>
```

30초 주기 AJAX 폴링:

```javascript
setInterval(function() {
    fetch('/api/notifications/unread-count')
        .then(r => r.json())
        .then(d => {
            const badge = document.getElementById('notiBadge');
            if (d.count > 0) {
                badge.textContent = d.count > 99 ? '99+' : d.count;
                badge.style.display = '';
            } else {
                badge.style.display = 'none';
            }
        });
}, 30000);
```

---

## 8. Feature 5: 프로젝트 종합현황 뷰

### 8.1 Route: `routes/overview.py`

```python
overview_bp = Blueprint('overview', __name__)

@overview_bp.route('/project_overview')
@login_required
def project_overview():
    q = (request.args.get('q') or '').strip().lower()
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        today = datetime.date.today()
        projects = db.query(Project).filter(Project.is_contracted == True).options(
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.deliveries),
        ).order_by(Project.id.desc()).all()

        result = []
        for p in projects:
            if q and q not in (p.project_no + p.temp_name + (p.short_name or '')).lower():
                continue

            # 각 단계별 진행률 계산
            all_items = [item for c in p.contracts for item in c.items]
            total_items = len(all_items)

            sales_done = sum(1 for it in all_items if it.status_sales == '협의완료')
            admin_done = sum(1 for it in all_items if it.status_admin == '입고완료')
            prod_done = sum(1 for it in all_items if it.status_prod == '생산완료')

            delivery_count = len(p.deliveries)
            delivery_done = sum(1 for d in p.deliveries if d.delivery_status == '납품완료')

            phases = {
                'contract': {'label': '계약', 'status': 'done', 'pct': 100},
                'sales': {
                    'label': '영업협의',
                    'status': 'done' if total_items and sales_done == total_items else 'progress' if sales_done > 0 else 'wait',
                    'pct': round(sales_done / total_items * 100) if total_items else 0,
                },
                'material': {
                    'label': '자재',
                    'status': 'done' if total_items and admin_done == total_items else 'progress' if admin_done > 0 else 'wait',
                    'pct': round(admin_done / total_items * 100) if total_items else 0,
                },
                'production': {
                    'label': '생산',
                    'status': 'done' if total_items and prod_done == total_items else 'progress' if prod_done > 0 else 'wait',
                    'pct': round(prod_done / total_items * 100) if total_items else 0,
                },
                'delivery': {
                    'label': '납품',
                    'status': 'done' if delivery_count and delivery_done == delivery_count else 'progress' if delivery_done > 0 else 'wait',
                    'pct': round(delivery_done / delivery_count * 100) if delivery_count else 0,
                },
            }

            # 전체 진행률
            phase_values = [v['pct'] for v in phases.values()]
            overall_pct = round(sum(phase_values) / len(phase_values)) if phase_values else 0

            result.append({
                'project': p,
                'phases': phases,
                'overall_pct': overall_pct,
                'total_items': total_items,
            })

        total = len(result)
        paginated = result[(page-1)*per_page : page*per_page]
        pagination = make_pagination(page, per_page, total)
        filters = {'q': q}

        return render_template('project_overview.html',
            entries=paginated, filters=filters, pagination=pagination, stats={'total': total})
```

### 8.2 Template: `project_overview.html`

```html
{% extends 'base.html' %}
{% block content %}
<h2 class="text-primary fw-bold mb-4">📊 프로젝트 종합현황</h2>

<!-- 검색 -->
<form class="card border-0 shadow-sm mb-4" method="GET">
    <div class="card-body row g-2 align-items-end">
        <div class="col-md-6">
            <input name="q" value="{{ filters.q }}" placeholder="관리번호/현장명/약칭" class="form-control">
        </div>
        <div class="col-md-6 text-md-end">
            <a href="{{ url_for('overview.project_overview') }}" class="btn btn-outline-secondary btn-sm">초기화</a>
            <button class="btn btn-primary btn-sm fw-bold">검색</button>
        </div>
    </div>
</form>

<!-- 프로젝트 카드 -->
{% for entry in entries %}
<div class="card shadow-sm border-0 mb-3">
    <div class="card-body">
        <div class="d-flex justify-content-between mb-2">
            <div>
                <b>{{ entry.project.project_no }}</b>
                <span class="fw-bold ms-2">{{ entry.project.temp_name }}</span>
                <small class="text-muted ms-1">(품목 {{ entry.total_items }}건)</small>
            </div>
            <span class="badge bg-primary">전체 {{ entry.overall_pct }}%</span>
        </div>
        <!-- 전체 프로그레스바 -->
        <div class="progress mb-3" style="height: 8px;">
            <div class="progress-bar" style="width: {{ entry.overall_pct }}%"></div>
        </div>
        <!-- 단계별 -->
        <div class="row g-2 text-center">
            {% for key, phase in entry.phases.items() %}
            <div class="col">
                <small class="text-muted d-block">{{ phase.label }}</small>
                <span class="badge {% if phase.status == 'done' %}bg-success{% elif phase.status == 'progress' %}bg-warning text-dark{% else %}bg-secondary{% endif %}">
                    {{ phase.pct }}%
                </span>
            </div>
            {% endfor %}
        </div>
    </div>
</div>
{% endfor %}

{% include 'components/pagination.html' %}
{% endblock %}
```

### 8.3 사이드바 메뉴 추가: `base.html`

```html
<a href="{{ url_for('overview.project_overview') }}">📊 종합현황</a>
```

납품관리와 도면관리 사이에 배치.

---

## 9. Security Considerations

- [x] 비밀번호 변경: bcrypt 해싱, 현재 PW 검증 필수
- [x] 알림 API: `session['user_id']` 검증으로 타인 알림 접근 방지
- [x] CSRF: 기존 Flask-WTF CSRF 보호 적용 (POST 요청)
- [x] 검색 입력: SQL injection 없음 (Python 레벨 필터링)
- [x] XSS: Jinja2 자동 이스케이프

---

## 10. Implementation Order

1. [ ] `modules/pagination.py` — 공통 페이지네이션 유틸 생성
2. [ ] `app.py` — Jinja2 global 등록 (`pagination_query`)
3. [ ] `templates/components/pagination.html` — 공통 페이지네이션 템플릿
4. [ ] `routes/project.py` → `project_list()` 검색/필터/페이지네이션 적용
5. [ ] `templates/project_list.html` — 검색 폼 + 통계 카드 + 페이지네이션 추가
6. [ ] `routes/project.py` → `contract_list()` 페이지네이션 적용
7. [ ] `routes/sales.py`, `routes/material.py`, `routes/production.py`, `routes/delivery.py` 페이지네이션 적용
8. [ ] 각 리스트 템플릿에 `{% include 'components/pagination.html' %}` 추가
9. [ ] `routes/auth.py` — `change_password()`, `reset_password()` 추가
10. [ ] `templates/components/change_password_modal.html` 생성
11. [ ] `templates/base.html` — 비밀번호 변경 버튼 + 모달 include
12. [ ] `modules/models/entities.py` — Notification 모델 추가
13. [ ] `modules/notification_utils.py` — 알림 생성 헬퍼
14. [ ] `routes/notification.py` — 알림 API + 목록 페이지
15. [ ] `templates/notification_center.html` — 알림 전체 목록
16. [ ] `templates/base.html` — 알림 아이콘 + AJAX 폴링
17. [ ] `app.py` — notification_bp 등록
18. [ ] `routes/overview.py` — 종합현황 라우트
19. [ ] `templates/project_overview.html` — 종합현황 페이지
20. [ ] `templates/base.html` — 사이드바 "종합현황" 메뉴 추가
21. [ ] `app.py` — overview_bp 등록

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-17 | Initial draft | ENG |
