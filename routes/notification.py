import datetime

from flask import Blueprint, render_template, request, session, jsonify
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models import Notification, HistoryLog, Project
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.dashboard_utils import history_detail_link, project_detail_link

notification_bp = Blueprint('notification', __name__)

# 알림 유형별 한글 라벨
NOTI_TYPE_LABELS = {
    'contract': '계약', 'delivery': '납품', 'delivery_urgent': '납품긴급',
    'delivery_overdue': '납기초과', 'production': '생산', 'material': '자재',
    'inventory': '재고', 'processing': '가공', 'document': '서류',
    'tax_invoice': '세금계산서', 'warranty': '하자보증', 'cert': '인증서',
    'trip': '출장', 'issue': '이슈', 'system': '시스템',
    'daily_digest': '일일점검',
}

# 필터 탭 그룹
FILTER_GROUPS = {
    'delivery': ['delivery', 'delivery_urgent', 'delivery_overdue'],
    'production': ['production'],
    'material': ['material', 'inventory', 'processing'],
    'document': ['document', 'tax_invoice', 'warranty', 'cert'],
}


@notification_bp.route('/notifications')
@login_required
def notification_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 20
    filter_type = request.args.get('type', '')

    with get_db() as db:
        # 코멘트 탭: HistoryLog에서 comment/reply 조회
        if filter_type == 'comment':
            base_q = db.query(HistoryLog).join(
                Project, Project.id == HistoryLog.project_id
            ).filter(
                HistoryLog.log_kind.in_(['comment', 'reply']),
                Project.is_contracted.is_(True),
            ).order_by(HistoryLog.created_at.desc())

            total = base_q.count()
            pagination = make_pagination(page, per_page, total)
            logs = base_q.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

            # Notification과 동일한 형태로 변환
            comment_items = []
            for log in logs:
                project = db.query(Project).get(log.project_id)
                project_name = (project.short_name or project.temp_name) if project else '?'
                comment_items.append({
                    'id': log.id,
                    'is_read': True,
                    'noti_type': 'comment',
                    'title': f'{log.user_name} · {project_name}',
                    'message': log.content,
                    'link': project_detail_link(project) + '#history-board' if project else '#',
                    'created_at': log.created_at,
                    'is_comment': True,
                    'log_scope': log.log_scope,
                })

            return render_template('notification_center.html',
                                   items=comment_items, pagination=pagination,
                                   filter_type=filter_type,
                                   noti_type_labels=NOTI_TYPE_LABELS)

        base_q = db.query(Notification).filter(
            Notification.user_id == session['user_id']
        )

        if filter_type == 'unread':
            base_q = base_q.filter(Notification.is_read == False)
        elif filter_type in FILTER_GROUPS:
            base_q = base_q.filter(Notification.noti_type.in_(FILTER_GROUPS[filter_type]))
        elif filter_type and filter_type != 'all':
            base_q = base_q.filter(Notification.noti_type == filter_type)

        base_q = base_q.order_by(Notification.created_at.desc())
        total = base_q.count()
        pagination = make_pagination(page, per_page, total)
        items = base_q.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

    return render_template('notification_center.html',
                           items=items, pagination=pagination,
                           filter_type=filter_type,
                           noti_type_labels=NOTI_TYPE_LABELS)


@notification_bp.route('/api/notifications/unread-count')
@login_required
def unread_count():
    with get_db() as db:
        count = db.query(Notification).filter(
            Notification.user_id == session['user_id'],
            Notification.is_read == False
        ).count()
    return jsonify({'count': count})


@notification_bp.route('/api/notifications/recent')
@login_required
def recent_notifications():
    with get_db() as db:
        items = db.query(Notification).filter(
            Notification.user_id == session['user_id']
        ).order_by(Notification.created_at.desc()).limit(20).all()

        result = []
        for n in items:
            result.append({
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'noti_type': n.noti_type,
                'link': n.link,
                'is_read': n.is_read,
                'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else None,
            })
    return jsonify({'items': result})


@notification_bp.route('/api/notifications/<int:noti_id>/read', methods=['POST'])
@login_required
def mark_read(noti_id):
    with get_db() as db:
        noti = db.query(Notification).filter(
            Notification.id == noti_id,
            Notification.user_id == session['user_id']
        ).first()
        if noti:
            noti.is_read = True
            db.commit()
    return jsonify({'ok': True})


@notification_bp.route('/api/notifications/read-all', methods=['POST'])
@login_required
def mark_all_read():
    with get_db() as db:
        db.query(Notification).filter(
            Notification.user_id == session['user_id'],
            Notification.is_read == False
        ).update({'is_read': True})
        db.commit()
    return jsonify({'ok': True})


@notification_bp.route('/api/dashboard/feed')
@login_required
def dashboard_feed():
    """대시보드 통합 피드 — 알림 + 히스토리 로그 시간순 통합"""
    page = safe_int(request.args.get('page'), 1)
    per_page = 20
    filter_type = request.args.get('type', '')  # '', 'notification', 'history', 또는 noti_type 그룹

    with get_db() as db:
        user_id = session['user_id']
        items = []

        # 알림 항목
        if filter_type in ('', 'notification') or filter_type in FILTER_GROUPS:
            noti_q = db.query(Notification).filter(
                Notification.user_id == user_id
            )
            if filter_type in FILTER_GROUPS:
                noti_q = noti_q.filter(Notification.noti_type.in_(FILTER_GROUPS[filter_type]))
            notifications = noti_q.order_by(
                Notification.created_at.desc()
            ).limit(per_page * 2).all()

            for n in notifications:
                items.append({
                    'id': f'n-{n.id}',
                    'source': 'notification',
                    'noti_type': n.noti_type,
                    'noti_type_label': NOTI_TYPE_LABELS.get(n.noti_type, n.noti_type),
                    'title': n.title,
                    'message': n.message,
                    'link': n.link,
                    'is_read': n.is_read,
                    'is_urgent': n.noti_type in ('delivery_urgent', 'delivery_overdue', 'issue'),
                    'created_at': n.created_at.isoformat() if n.created_at else None,
                    'created_at_display': n.created_at.strftime('%m/%d %H:%M') if n.created_at else '',
                    '_ts': n.created_at,
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

            scope_labels = {
                'design': '설계', 'contract': '계약', 'sales': '영업',
                'material': '자재', 'production': '생산', 'delivery': '납품', 'common': '코멘트',
            }
            for log in logs:
                project = log.project
                content = log.content or ''
                is_issue = ('이슈' in content) or ('긴급' in content)
                items.append({
                    'id': f'h-{log.id}',
                    'source': 'history',
                    'noti_type': log.log_scope or 'common',
                    'noti_type_label': scope_labels.get(log.log_scope, '로그'),
                    'title': f'{log.user_name} · {project.short_name or project.temp_name}' if project else log.user_name,
                    'message': content,
                    'link': history_detail_link(project, log.log_scope) if project else '#',
                    'is_read': True,
                    'is_urgent': is_issue,
                    'created_at': log.created_at.isoformat() if log.created_at else None,
                    'created_at_display': log.created_at.strftime('%m/%d %H:%M') if log.created_at else '',
                    '_ts': log.created_at,
                })

        # 긴급 상단 고정 + 시간순 정렬
        items.sort(key=lambda x: (
            not x.get('is_urgent', False),
            -(x['_ts'].timestamp() if x.get('_ts') else 0),
        ))

        start = (page - 1) * per_page
        paged = items[start:start + per_page]
        for item in paged:
            item.pop('_ts', None)

        return jsonify({
            'items': paged,
            'has_more': len(items) > start + per_page,
            'page': page,
        })
