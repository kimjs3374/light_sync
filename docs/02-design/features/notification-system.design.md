# notification-system Design

- **Feature**: 알림 시스템 전면 재설계
- **Architecture**: Option B — 클린 아키텍처 (이벤트 기반 알림 엔진)
- **Created**: 2026-04-06

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | 부서 간 정보 단절로 납품·생산 일정 누락 빈번. 기존 알림은 입고지연 1건만 작동 |
| **WHO** | 영업팀, 생산팀, 관리부, 전 직원 (47명) |
| **RISK** | 알림 과다 피로감, 카카오워크 API rate limit |
| **SUCCESS** | 납품 알림 100% 도달, 대시보드 3초 내 업무 파악, 카카오워크 동시 발송 |
| **SCOPE** | ERP 내부 + 카카오워크. 이메일·SMS 제외. 개인 설정 제외 |

---

## 1. Overview

### 1.1 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                     이벤트 발생 지점                              │
│  contract.py │ delivery_actions │ production_logic │ scheduler  │
└──────┬───────┴────────┬─────────┴────────┬─────────┴─────┬─────┘
       │                │                  │               │
       ▼                ▼                  ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    notify(event_type, data)                      │
│              modules/notification_engine.py                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ Event Config │→│ Target Resolver│→│ Channel Dispatcher │     │
│  │ (REGISTRY)   │  │ (부서/전체)   │  │ (ERP + KakaoWork) │     │
│  └──────────────┘  └──────────────┘  └────────────────────┘     │
└──────────────────────────┬──────────────────────┬───────────────┘
                           │                      │
                    ┌──────▼──────┐         ┌─────▼──────┐
                    │ ERP 내부     │         │ 카카오워크   │
                    │ notifications│         │ 그룹챗/워크보드│
                    │ DB 테이블    │         │ API 전송     │
                    └─────────────┘         └────────────┘
                           │
                    ┌──────▼──────┐
                    │ 대시보드 피드 │
                    │ + 벨 드롭다운 │
                    │ + 토스트      │
                    └─────────────┘
```

### 1.2 핵심 설계 원칙

1. **단일 진입점**: 모든 알림은 `notify()` 함수 하나를 통해 발생
2. **선언적 설정**: 이벤트별 대상·채널·메시지 포맷을 `EVENT_REGISTRY` dict로 관리
3. **기존 호출 교체**: 현재 5곳의 카카오워크 직접 호출을 `notify()` 호출로 교체
4. **Non-blocking**: 알림 실패가 원래 업무 흐름을 중단하지 않음

---

## 2. Event Registry (이벤트 등록부)

### 2.1 Registry 구조

```python
# modules/notification_engine.py

EVENT_REGISTRY = {
    # ── 계약/납품 ──
    'contract.created': {
        'title': '[신규 계약] {project_name}',
        'message': '{contract_name} — 납품기한: {delivery_due_date}',
        'target': 'all',           # 'all' | 'group:관리부' | 'group:생산부' | ['group:관리부', 'group:생산부']
        'noti_type': 'contract',
        'link': '/contract_detail/{project_id}',
        'kakao': True,             # 카카오워크 동시 발송 여부
        'kakao_format': 'workboard',  # 'text' | 'workboard'
    },
    'delivery.scheduled': {
        'title': '[납품일정] {project_name}',
        'message': '{delivery_date} 납품 예정 — 담당: {manager_name}',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/delivery_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.due_d7': {
        'title': '[납품 D-7] {project_name}',
        'message': '{delivery_due_date} 납품기한 7일 전',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.due_d1': {
        'title': '[내일 납품] {project_name}',
        'message': '{delivery_due_date} 납품기한 — 준비 확인 필요',
        'target': 'all',
        'noti_type': 'delivery_urgent',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.overdue': {
        'title': '[납기 초과] {project_name}',
        'message': '{delivery_due_date} 기한 D+{overdue_days}일 경과',
        'target': 'all',
        'noti_type': 'delivery_overdue',
        'link': '/contract_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'delivery.completed': {
        'title': '[납품 완료] {project_name}',
        'message': '{delivery_date} 납품 완료',
        'target': 'all',
        'noti_type': 'delivery',
        'link': '/delivery_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 생산/자재 ──
    'production.item_complete': {
        'title': '[생산완료] {project_name}',
        'message': '{model_name} {quantity}EA 생산완료',
        'target': 'all',
        'noti_type': 'production',
        'link': '/production_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'production.site_complete': {
        'title': '[현장 전체 생산완료] {project_name}',
        'message': '전 품목 생산완료 — 출고 준비 필요',
        'target': 'all',
        'noti_type': 'production',
        'link': '/production_detail/{project_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'material.received': {
        'title': '[자재 입고] {material_name}',
        'message': '{project_name} — {material_name} 입고 완료',
        'target': 'group:생산부',
        'noti_type': 'material',
        'link': '/receiving?tab=expected',
        'kakao': False,
    },
    'material.overdue': {
        'title': '[입고 지연] {material_name}',
        'message': '{project_name} — D+{overdue_days}일 지연',
        'target': 'group:관리부',
        'noti_type': 'material',
        'link': '/receiving?tab=expected',
        'kakao': False,
    },
    'inventory.low_stock': {
        'title': '[재고 부족] {item_name}',
        'message': '현재고 {current_qty} / 안전재고 {safe_qty}',
        'target': 'group:관리부',
        'noti_type': 'inventory',
        'link': '/inventory',
        'kakao': True,
        'kakao_format': 'text',
    },
    'processing.completed': {
        'title': '[가공 완료] {order_name}',
        'message': '{vendor_name} — 가공 완료',
        'target': 'group:생산부',
        'noti_type': 'processing',
        'link': '/processing_order/{order_id}',
        'kakao': False,
    },

    # ── 서류/행정 ──
    'document.deadline_d7': {
        'title': '[서류 마감 D-7] {document_name}',
        'message': '{project_name} — {deadline} 마감',
        'target': 'group:관리부',
        'noti_type': 'document',
        'link': '/document_detail/{document_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'tax_invoice.issued': {
        'title': '[세금계산서] {project_name}',
        'message': '{amount}원 발행',
        'target': 'group:관리부',
        'noti_type': 'tax_invoice',
        'link': '/procurement',
        'kakao': False,
    },
    'warranty.expiring': {
        'title': '[하자보증 만료 D-30] {project_name}',
        'message': '{expiry_date} 만료 예정',
        'target': 'group:관리부',
        'noti_type': 'warranty',
        'link': '/warranty/{warranty_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'cert.expiring': {
        'title': '[인증서 만료 임박] {cert_name}',
        'message': '{expiry_date} 만료 — 갱신 필요',
        'target': 'group:관리부',
        'noti_type': 'cert',
        'link': '/admin/settings#cert',
        'kakao': True,
        'kakao_format': 'text',
    },

    # ── 일반 ──
    'trip.created': {
        'title': '[출장 등록] {destination}',
        'message': '{departure_date}~{return_date} · {members}',
        'target': 'all',
        'noti_type': 'trip',
        'link': '/trip_detail/{trip_id}',
        'kakao': True,
        'kakao_format': 'text',
    },
    'issue.flagged': {
        'title': '[이슈] {project_name}',
        'message': '{content}',
        'target': 'all',
        'noti_type': 'issue',
        'link': '{detail_url}',
        'kakao': True,
        'kakao_format': 'text',
    },
}
```

### 2.2 이벤트 목록 요약

| # | event_type | 대상 | 카카오 | 발생 시점 |
|---|-----------|------|--------|----------|
| 1 | `contract.created` | 전체 | ✅ 워크보드 | G2B 동기화 / 수동 등록 |
| 2 | `delivery.scheduled` | 전체 | ✅ | 납품일정 등록/변경 |
| 3 | `delivery.due_d7` | 전체 | ✅ | 스케줄러 (매일 07:00) |
| 4 | `delivery.due_d1` | 전체 | ✅ | 스케줄러 (매일 07:00) |
| 5 | `delivery.overdue` | 전체 | ✅ | 스케줄러 (매일 07:00) |
| 6 | `delivery.completed` | 전체 | ✅ | 납품 완료 처리 |
| 7 | `production.item_complete` | 전체 | ✅ | 생산 상태 변경 |
| 8 | `production.site_complete` | 전체 | ✅ | 전 품목 생산완료 |
| 9 | `material.received` | 생산부 | ❌ | 입고 확인 처리 |
| 10 | `material.overdue` | 관리부 | ❌ | 스케줄러 (매일 07:00) |
| 11 | `inventory.low_stock` | 관리부 | ✅ | 스케줄러 (매일 07:00) |
| 12 | `processing.completed` | 생산부 | ❌ | 가공발주 상태 변경 |
| 13 | `document.deadline_d7` | 관리부 | ✅ | 스케줄러 (매일 07:00) |
| 14 | `tax_invoice.issued` | 관리부 | ❌ | 세금계산서 등록 |
| 15 | `warranty.expiring` | 관리부 | ✅ | 스케줄러 (매일 07:00) |
| 16 | `cert.expiring` | 관리부 | ✅ | 스케줄러 (매일 07:00) |
| 17 | `trip.created` | 전체 | ✅ | 출장 등록 |
| 18 | `issue.flagged` | 전체 | ✅ | 이슈 히스토리 로그 |

---

## 3. 모듈 설계

### 3.1 notification_engine.py (신규)

알림 시스템의 핵심 모듈. 단일 진입점 `notify()` 함수를 제공.

```python
# modules/notification_engine.py

import logging
import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

EVENT_REGISTRY = { ... }  # §2.1 참조

def notify(db, event_type: str, data: Dict[str, Any], 
           dedupe_key: Optional[str] = None) -> bool:
    """
    알림 엔진 단일 진입점.
    
    Args:
        db: SQLAlchemy session
        event_type: 이벤트 유형 (EVENT_REGISTRY 키)
        data: 이벤트 데이터 (title/message 포맷용 + 라우팅용)
        dedupe_key: 중복 방지 키 (같은 날 동일 키 알림 스킵)
    
    Returns:
        bool: 성공 여부
    """
    config = EVENT_REGISTRY.get(event_type)
    if not config:
        logger.warning(f"[notify] 등록되지 않은 이벤트: {event_type}")
        return False
    
    try:
        # 1. 메시지 빌드
        title = config['title'].format(**data)
        message = config['message'].format(**data)
        link = config['link'].format(**data)
        noti_type = config['noti_type']
        
        # 2. 대상 사용자 결정
        users = _resolve_targets(db, config['target'])
        
        # 3. ERP 내부 알림 생성
        _create_erp_notifications(db, users, title, message, noti_type, link, dedupe_key)
        
        # 4. 카카오워크 발송 (해당되는 경우)
        if config.get('kakao'):
            _send_kakao(config, title, message, data)
        
        return True
    except Exception as e:
        logger.error(f"[notify] {event_type} 처리 오류: {e}")
        return False


def _resolve_targets(db, target_spec):
    """대상 사양에 따라 사용자 목록 반환"""
    from modules.models import User
    base = db.query(User).filter(User.is_active.is_(True), User.is_approved.is_(True))
    
    if target_spec == 'all':
        return base.all()
    
    if isinstance(target_spec, str) and target_spec.startswith('group:'):
        group_name = target_spec.split(':', 1)[1]
        return base.filter(User.user_group == group_name).all()
    
    if isinstance(target_spec, list):
        users = []
        seen = set()
        for spec in target_spec:
            for user in _resolve_targets(db, spec):
                if user.id not in seen:
                    seen.add(user.id)
                    users.append(user)
        return users
    
    return []


def _create_erp_notifications(db, users, title, message, noti_type, link, dedupe_key=None):
    """ERP 내부 알림 생성 (중복 방지 포함)"""
    from modules.models import Notification
    today_start = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    
    for user in users:
        if dedupe_key:
            already = db.query(Notification).filter(
                Notification.user_id == user.id,
                Notification.noti_type == noti_type,
                Notification.title == title,
                Notification.created_at >= today_start,
            ).first()
            if already:
                continue
        
        db.add(Notification(
            user_id=user.id,
            title=title,
            message=message,
            noti_type=noti_type,
            link=link,
            is_read=False,
        ))


def _send_kakao(config, title, message, data):
    """카카오워크 채널 발송"""
    from modules.kakaowork_notifier import send_group_notification, post_contract_summary
    
    kakao_format = config.get('kakao_format', 'text')
    
    if kakao_format == 'workboard' and 'project' in data and 'contracts' in data:
        post_contract_summary(data['project'], data['contracts'])
    else:
        text = f"{title}\n\n{message}"
        if data.get('timestamp'):
            text += f"\n\n(발행시각: {data['timestamp']})"
        send_group_notification(text)
```

### 3.2 notification_scheduler.py (신규)

시간 기반 알림을 처리하는 스케줄러 작업.

```python
# modules/services/notification_scheduler.py

"""시간 기반 알림 스케줄러 작업 — 매일 07:00 실행"""

import datetime
import logging
from modules.notification_engine import notify

logger = logging.getLogger(__name__)

def run_daily_notification_checks():
    """매일 07:00 실행 — 납품기한, 서류마감, 만료 등 시간 기반 알림 일괄 처리"""
    from modules.db_context import get_db
    
    with get_db() as db:
        today = datetime.date.today()
        
        _check_delivery_deadlines(db, today)
        _check_material_overdue(db, today)
        _check_low_stock(db)
        _check_document_deadlines(db, today)
        _check_warranty_expiry(db, today)
        _check_cert_expiry(db, today)
        
        db.commit()
    
    logger.info("[notification_scheduler] 일일 알림 점검 완료")


def _check_delivery_deadlines(db, today):
    """납품기한 D-7, D-1, 초과 알림"""
    from modules.models import Contract, Project
    from modules.contract_filters import active_contract_filter
    
    contracts = db.query(Contract).join(
        Project, Project.id == Contract.project_id
    ).filter(
        Project.is_contracted.is_(True),
        active_contract_filter(),
        Contract.delivery_due_date.isnot(None),
    ).all()
    
    for c in contracts:
        if not c.project:
            continue
        
        delta = (c.delivery_due_date - today).days
        project_name = c.project.short_name or c.project.temp_name
        data = {
            'project_name': project_name,
            'project_id': c.project_id,
            'delivery_due_date': c.delivery_due_date.strftime('%Y-%m-%d'),
            'contract_name': c.contract_name or project_name,
        }
        
        if delta == 7:
            notify(db, 'delivery.due_d7', data, dedupe_key=f'd7-{c.id}')
        elif delta == 1:
            notify(db, 'delivery.due_d1', data, dedupe_key=f'd1-{c.id}')
        elif delta < 0:
            data['overdue_days'] = abs(delta)
            notify(db, 'delivery.overdue', data, dedupe_key=f'overdue-{c.id}')


def _check_material_overdue(db, today):
    """입고 지연 알림 (기존 notification_service.py 대체)"""
    from modules.models.entities import MaterialOrder
    
    overdue_list = db.query(MaterialOrder).filter(
        MaterialOrder.order_status == '발주완료',
        MaterialOrder.in_confirmed.is_(False),
        MaterialOrder.expected_in_date.isnot(None),
        MaterialOrder.expected_in_date < today,
    ).all()
    
    for mo in overdue_list:
        project_name = mo.project.temp_name if mo.project else '미지정'
        overdue_days = (today - mo.expected_in_date).days
        notify(db, 'material.overdue', {
            'material_name': mo.material_name,
            'project_name': project_name,
            'overdue_days': overdue_days,
        }, dedupe_key=f'mo-overdue-{mo.id}')


def _check_low_stock(db):
    """안전재고 미달 알림"""
    from modules.models import Item
    
    low_items = db.query(Item).filter(
        Item.safe_stock.isnot(None),
        Item.safe_stock > 0,
        Item.current_stock < Item.safe_stock,
    ).all()
    
    for item in low_items:
        notify(db, 'inventory.low_stock', {
            'item_name': item.name or item.model_code,
            'current_qty': item.current_stock or 0,
            'safe_qty': item.safe_stock,
        }, dedupe_key=f'lowstock-{item.id}')


def _check_document_deadlines(db, today):
    """서류 제출 마감 D-7 알림"""
    from modules.models import Document
    
    d7_date = today + datetime.timedelta(days=7)
    docs = db.query(Document).filter(
        Document.deadline.isnot(None),
        Document.deadline == d7_date,
        Document.status != '완료',
    ).all()
    
    for doc in docs:
        project_name = doc.project.temp_name if doc.project else '미지정'
        notify(db, 'document.deadline_d7', {
            'document_name': doc.doc_type or '서류',
            'project_name': project_name,
            'deadline': doc.deadline.strftime('%Y-%m-%d'),
            'document_id': doc.id,
        }, dedupe_key=f'doc-d7-{doc.id}')


def _check_warranty_expiry(db, today):
    """하자보증 만료 D-30 알림"""
    from modules.models import WarrantyCase
    
    d30_date = today + datetime.timedelta(days=30)
    cases = db.query(WarrantyCase).filter(
        WarrantyCase.warranty_end_date.isnot(None),
        WarrantyCase.warranty_end_date == d30_date,
    ).all()
    
    for wc in cases:
        notify(db, 'warranty.expiring', {
            'project_name': wc.project_name or '미지정',
            'expiry_date': wc.warranty_end_date.strftime('%Y-%m-%d'),
            'warranty_id': wc.id,
        }, dedupe_key=f'warranty-{wc.id}')


def _check_cert_expiry(db, today):
    """인증서 만료 D-60 알림"""
    from modules.models import CertDocument
    
    d60_date = today + datetime.timedelta(days=60)
    certs = db.query(CertDocument).filter(
        CertDocument.expiry_date.isnot(None),
        CertDocument.expiry_date == d60_date,
    ).all()
    
    for cert in certs:
        notify(db, 'cert.expiring', {
            'cert_name': cert.cert_name or '인증서',
            'expiry_date': cert.expiry_date.strftime('%Y-%m-%d'),
        }, dedupe_key=f'cert-{cert.id}')
```

### 3.3 기존 코드 교체 지점

현재 5곳에서 카카오워크를 직접 호출하는 코드를 `notify()` 호출로 교체:

| # | 파일 | 현재 코드 | 교체 후 |
|---|------|----------|---------|
| 1 | `routes/contract.py:106` | `post_contract_summary(new_p, created_contracts)` | `notify(db, 'contract.created', {..., 'project': new_p, 'contracts': created_contracts})` |
| 2 | `modules/production_logic.py:276` | `notify_production_complete(...)` | `notify(db, 'production.item_complete', {...})` |
| 3 | `modules/production_logic.py:276` | `notify_site_complete(...)` | `notify(db, 'production.site_complete', {...})` |
| 4 | `routes/business_trip.py:185` | `send_group_notification(notify_text)` | `notify(db, 'trip.created', {...})` |
| 5 | `modules/services/delivery_actions.py:196` | `send_group_notification(notify_text)` | `notify(db, 'delivery.scheduled', {...})` |
| 6 | `modules/services/sales_actions.py:178` | `send_group_notification(notify_text)` | `notify(db, 'issue.flagged', {...})` |

### 3.4 스케줄러 등록

`modules/scheduler.py`에 일일 알림 job 추가:

```python
# scheduler.py init_scheduler()에 추가
_scheduler.add_job(
    run_daily_notification_checks,
    trigger='cron',
    hour=7, minute=0,
    id='daily_notification_checks',
    replace_existing=True,
)
```

**주의**: gunicorn 멀티워커 중복 실행 방지를 위해 crontab으로 이관하는 것이 안전. 
기존 G2B 동기화와 동일 패턴 (`scripts/run_daily_notifications.py` + crontab).

---

## 4. API 설계

### 4.1 기존 API (변경 없음)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/notifications/unread-count` | 미읽은 알림 수 |
| GET | `/api/notifications/recent` | 최근 알림 20건 |
| POST | `/api/notifications/<id>/read` | 단건 읽음 처리 |
| POST | `/api/notifications/read-all` | 전체 읽음 처리 |

### 4.2 신규 API

| Method | Path | 설명 | 응답 |
|--------|------|------|------|
| GET | `/api/dashboard/feed` | 대시보드 통합 피드 | `{items: [...], has_more: bool}` |

#### 통합 피드 API 상세

```python
# routes/notification.py에 추가

@notification_bp.route('/api/dashboard/feed')
@login_required
def dashboard_feed():
    """대시보드 통합 피드 — 알림 + 히스토리 로그 시간순 통합"""
    page = safe_int(request.args.get('page'), 1)
    per_page = 20
    filter_type = request.args.get('type', '')  # 'notification', 'history', '' (전체)
    
    with get_db() as db:
        user_id = session['user_id']
        user_group = session.get('user_group', '')
        items = []
        
        # 알림 항목
        if filter_type in ('', 'notification'):
            notifications = db.query(Notification).filter(
                Notification.user_id == user_id
            ).order_by(Notification.created_at.desc()).limit(per_page * 2).all()
            
            for n in notifications:
                items.append({
                    'id': f'n-{n.id}',
                    'type': 'notification',
                    'noti_type': n.noti_type,
                    'title': n.title,
                    'message': n.message,
                    'link': n.link,
                    'is_read': n.is_read,
                    'created_at': n.created_at.isoformat() if n.created_at else None,
                    'timestamp': n.created_at,
                })
        
        # 히스토리 로그 항목
        if filter_type in ('', 'history'):
            logs = db.query(HistoryLog).join(
                Project, Project.id == HistoryLog.project_id
            ).filter(
                Project.is_contracted.is_(True)
            ).options(
                joinedload(HistoryLog.project)
            ).order_by(HistoryLog.created_at.desc()).limit(per_page * 2).all()
            
            for log in logs:
                project = log.project
                items.append({
                    'id': f'h-{log.id}',
                    'type': 'history',
                    'noti_type': log.log_scope or 'common',
                    'title': f'{log.user_name} · {project.short_name or project.temp_name}',
                    'message': log.content,
                    'link': history_detail_link(project, log.log_scope),
                    'is_read': True,
                    'created_at': log.created_at.isoformat() if log.created_at else None,
                    'timestamp': log.created_at,
                })
        
        # 시간순 정렬 + 페이지네이션
        items.sort(key=lambda x: x.get('timestamp') or datetime.datetime.min, reverse=True)
        start = (page - 1) * per_page
        paged = items[start:start + per_page]
        
        for item in paged:
            item.pop('timestamp', None)
        
        return jsonify({
            'items': paged,
            'has_more': len(items) > start + per_page,
            'page': page,
        })
```

---

## 5. 프론트엔드 설계

### 5.1 알림 드롭다운 패널

**위치**: `templates/base.html` — 벨 아이콘 클릭 시 드롭다운

```
┌──────────────────────────────┐
│ 알림                    전체보기 →│
├──────────────────────────────┤
│ 🔴 [내일 납품] 여수 체육관        │
│    2026-04-07 납품기한     1분 전│
├──────────────────────────────┤
│ 🟢 [생산완료] 강릉 도서관         │
│    MG-600W 50EA          5분 전│
├──────────────────────────────┤
│    [자재 입고] LED 드라이버       │
│    여수 체육관              30분 전│
├──────────────────────────────┤
│ ... 최대 10건               │
├──────────────────────────────┤
│        전체 읽음 처리           │
└──────────────────────────────┘
```

**구현**: `static/js/notification-panel.js` (신규)
- 벨 아이콘 클릭 → `/api/notifications/recent` fetch → 드롭다운 렌더링
- 항목 클릭 → 읽음 처리 + 해당 페이지 이동
- noti_type별 좌측 색상 표시:
  - `delivery_urgent`, `delivery_overdue`: 빨간색
  - `production`: 초록색
  - `material`, `inventory`: 주황색
  - `contract`: 파란색
  - 기타: 회색

### 5.2 토스트 알림

**위치**: `templates/base.html` 하단 — 새 알림 수신 시 자동 표시

```
                              ┌────────────────────────┐
                              │ [내일 납품] 여수 체육관    │
                              │ 2026-04-07 납품기한      │
                              │              바로가기 → │
                              └────────────────────────┘
```

**구현**: `static/js/notification-badge.js` 확장
- 기존 30초 폴링 시 이전 count와 비교
- count 증가 시 → 최근 알림 1건 fetch → 토스트 표시
- 5초 후 자동 닫힘, 클릭 시 즉시 이동

### 5.3 알림센터 개선

**위치**: `templates/notification_center.html` 리뉴얼

변경사항:
- noti_type별 필터 탭 추가 (전체 | 납품 | 생산 | 자재 | 서류 | 기타)
- 읽음/안읽음 필터
- page-hero 제거 (기존 피드백: 카드/hero 금지)
- 각 항목에 noti_type 아이콘 + 색상 라벨 추가

### 5.4 대시보드 피드 전환

**기존 구조** → **신규 구조**:

```
기존:                           신규:
┌─────────┬──────┐             ┌─────────┬──────┐
│ Priority│Cal   │             │ KPI칩   │Cal   │
│ Workflow│      │             │ Workflow │      │
│ 입고예정 │연차  │             │──────── │연차  │
│ Action  │출장  │             │ 통합피드  │출장  │
│ Tabs    │──────│             │ (알림+   │      │
│         │타임  │             │  히스토리)│      │
│         │라인  │             │         │      │
└─────────┴──────┘             └─────────┴──────┘
```

**변경 사항**:
1. **KPI 칩**: 현행 유지 (상단 고정)
2. **파이프라인 워크플로우**: 현행 유지 (축소)
3. **전광판(Ticker)**: 제거 — 피드로 통합
4. **Priority Brief**: 제거 — 피드로 통합
5. **입고예정 카드**: 현행 유지 (간결하므로)
6. **Action Tabs**: 제거 — 피드 + 필터로 대체
7. **우측 타임라인**: 제거 — 피드로 통합
8. **신규: 통합 피드**: 좌측 메인 영역에 배치
   - 알림(notification) + 히스토리 로그(history) 시간순 통합
   - 필터: 전체 | 내 부서 | 납품 | 생산 | 자재
   - 이슈/긴급 항목 상단 고정 (is_issue)
   - 무한 스크롤 (페이지네이션)
   - 각 항목 클릭 시 해당 화면으로 이동

**통합 피드 항목 UI**:

```
┌─ noti_type 색상바 ──────────────────────────────────┐
│ 🔴 [내일 납품] 여수 체육관                         1분 전│
│    2026-04-07 납품기한 — 준비 확인 필요                  │
│    시스템 알림                          바로가기 →   │
├─────────────────────────────────────────────────────┤
│ 🟢 [생산완료] 강릉 도서관                         5분 전│
│    MG-600W 50EA 생산완료                            │
│    시스템 알림                          바로가기 →   │
├─────────────────────────────────────────────────────┤
│    김대리 · 강릉 도서관                          10분 전│
│    납품일정 확정: 4/10 현장 도착                      │
│    히스토리 로그 · 납품관리                바로가기 →   │
└─────────────────────────────────────────────────────┘
```

---

## 6. 데이터 모델

### 6.1 기존 테이블 (변경 없음)

```sql
-- notifications 테이블 (이미 존재)
-- noti_type 값만 다양화: system → contract, delivery, delivery_urgent, 
-- delivery_overdue, production, material, inventory, processing,
-- document, tax_invoice, warranty, cert, trip, issue
```

스키마 변경 없이 `noti_type` 컬럼의 값만 다양하게 사용.

### 6.2 알림 보존 정책

```python
# notification_scheduler.py에 추가
def cleanup_old_notifications():
    """90일 이상 된 읽은 알림 삭제 (매주 일요일 03:00)"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=90)
    db.query(Notification).filter(
        Notification.is_read.is_(True),
        Notification.created_at < cutoff,
    ).delete()
```

---

## 7. 파일 구조

### 7.1 신규 파일

| 파일 | 설명 |
|------|------|
| `modules/notification_engine.py` | 알림 엔진 (EVENT_REGISTRY + notify() + 디스패처) |
| `modules/services/notification_scheduler.py` | 시간 기반 알림 스케줄러 작업 |
| `static/js/notification-panel.js` | 알림 드롭다운 패널 JS |

### 7.2 수정 파일

| 파일 | 변경 내용 |
|------|----------|
| `modules/scheduler.py` | 일일 알림 job 추가 |
| `routes/contract.py` | `post_contract_summary` → `notify()` 교체 |
| `modules/production_logic.py` | `notify_production_complete/site_complete` → `notify()` 교체 |
| `routes/business_trip.py` | `send_group_notification` → `notify()` 교체 |
| `modules/services/delivery_actions.py` | `send_group_notification` → `notify()` 교체 |
| `modules/services/sales_actions.py` | `send_group_notification` → `notify()` 교체 |
| `routes/notification.py` | 피드 API 추가 + 알림센터 필터 |
| `templates/base.html` | 드롭다운 패널 마크업 + 토스트 컨테이너 |
| `templates/notification_center.html` | 필터 탭 + UI 개선 |
| `templates/dashboard.html` | 전광판/액션탭/타임라인 → 통합 피드 교체 |
| `static/js/notification-badge.js` | 토스트 알림 + 드롭다운 연동 |
| `routes/dashboard.py` | 피드 데이터 전달, 불필요 쿼리 정리 |
| `modules/services/notification_service.py` | 기존 입고지연 로직 → `notification_scheduler.py`로 이관 (파일 삭제 또는 비움) |

### 7.3 삭제/비움 파일

| 파일 | 사유 |
|------|------|
| `modules/services/notification_service.py` | 입고지연 로직이 `notification_scheduler.py`로 이관 |
| `modules/notification_utils.py` | `notification_engine.py`의 `notify()`로 대체 |

---

## 8. 테스트 계획

| # | 테스트 항목 | 검증 방법 |
|---|-----------|----------|
| T1 | 계약 등록 시 전체 알림 + 워크보드 발송 | 계약 생성 후 notifications 테이블 확인 |
| T2 | 납품 D-7, D-1 스케줄러 알림 | `run_daily_notification_checks()` 수동 실행 |
| T3 | 생산완료 시 ERP + 카카오워크 동시 발송 | 생산 상태 변경 후 확인 |
| T4 | 부서별 타겟팅 (관리부만 입고지연) | user_group 다른 사용자로 확인 |
| T5 | 중복 방지 (dedupe_key) | 동일 이벤트 2회 발생 시 알림 1건만 |
| T6 | 드롭다운 패널 표시 | 벨 아이콘 클릭 후 최근 알림 확인 |
| T7 | 토스트 알림 | 새 알림 발생 시 우하단 토스트 확인 |
| T8 | 대시보드 피드 렌더링 | 알림 + 히스토리 통합 피드 시간순 확인 |
| T9 | 대시보드 피드 필터 | 유형별 필터 전환 동작 확인 |
| T10 | 알림 보존 정책 | 90일 이상 읽은 알림 삭제 확인 |

---

## 9. 의존성

- 추가 패키지 없음 (기존 Flask + SQLAlchemy + APScheduler + requests)
- 카카오워크 API: 기존 `kakaowork_notifier.py` 그대로 활용
- DB 스키마 변경 없음

---

## 10. 리스크 대응

| 리스크 | 대응 |
|--------|------|
| 알림 폭풍 (납기초과 현장 다수) | dedupe_key로 동일 이벤트 하루 1회 제한 |
| 카카오워크 rate limit | 스케줄러 알림은 1건씩 순차 발송, sleep 불필요 (일일 1회) |
| 대시보드 피드 성능 | 페이지네이션 + LIMIT으로 제한, 무한스크롤 |
| 기존 카카오워크 메시지 포맷 변경 | workboard 포맷은 기존 함수 그대로 사용, text는 title+message 조합 |

---

## 11. Implementation Guide

### 11.1 구현 순서

| 순서 | 모듈 | 설명 | 의존성 |
|------|------|------|--------|
| 1 | notification_engine.py | 알림 엔진 + EVENT_REGISTRY | 없음 |
| 2 | 기존 코드 교체 (6개 파일) | 카카오워크 직접 호출 → notify() | 모듈 1 |
| 3 | notification_scheduler.py | 시간 기반 알림 + 스케줄러 등록 | 모듈 1 |
| 4 | 알림 드롭다운 + 토스트 | base.html + notification-panel.js | 모듈 1 |
| 5 | 대시보드 피드 API | /api/dashboard/feed | 모듈 1 |
| 6 | 대시보드 UI 전환 | dashboard.html 재설계 | 모듈 5 |
| 7 | 알림센터 개선 | notification_center.html | 모듈 1 |
| 8 | 정리 | 구 파일 삭제/비움, 알림 보존 정책 | 전체 |

### 11.2 Module Map

| Module ID | 파일 | 예상 변경량 |
|-----------|------|-----------|
| M1-engine | `modules/notification_engine.py` | ~150줄 신규 |
| M2-replace | 6개 기존 파일 | 각 ~5줄 수정 |
| M3-scheduler | `modules/services/notification_scheduler.py` + `modules/scheduler.py` | ~180줄 신규 + ~10줄 수정 |
| M4-dropdown | `templates/base.html` + `static/js/notification-panel.js` | ~30줄 수정 + ~80줄 신규 |
| M5-feed-api | `routes/notification.py` | ~60줄 추가 |
| M6-dashboard | `templates/dashboard.html` + `routes/dashboard.py` | ~200줄 수정 |
| M7-center | `templates/notification_center.html` | ~40줄 수정 |
| M8-cleanup | 구 파일 정리 | 삭제/비움 |

### 11.3 Session Guide

**추천 세션 분할**:

| 세션 | 범위 | 목표 |
|------|------|------|
| Session 1 | M1 + M2 + M3 | 알림 엔진 + 기존 교체 + 스케줄러 (백엔드 완성) |
| Session 2 | M4 + M5 + M7 | 드롭다운 + 토스트 + 피드 API + 알림센터 |
| Session 3 | M6 + M8 | 대시보드 UI 전환 + 정리 |
