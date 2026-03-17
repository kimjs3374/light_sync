import datetime

from flask import Blueprint, render_template, request, session, jsonify
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models import Notification
from modules.pagination import make_pagination
from modules.utils import safe_int

notification_bp = Blueprint('notification', __name__)


@notification_bp.route('/notifications')
@login_required
def notification_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        base_q = db.query(Notification).filter(
            Notification.user_id == session['user_id']
        ).order_by(Notification.created_at.desc())

        total = base_q.count()
        pagination = make_pagination(page, per_page, total)
        items = base_q.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

    return render_template('notification_center.html', items=items, pagination=pagination)


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
