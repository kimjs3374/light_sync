from modules.models import Notification, User


def create_notification(db, user_id, title, message='', noti_type='system', link=None):
    """단일 사용자에게 알림 생성"""
    db.add(Notification(
        user_id=user_id, title=title, message=message,
        noti_type=noti_type, link=link
    ))


def create_notification_for_group(db, group_name, title, message='', noti_type='system', link=None):
    """특정 그룹 전체에 알림 생성"""
    users = db.query(User).filter(
        User.user_group == group_name,
        User.is_active.is_(True),
        User.is_approved.is_(True)
    ).all()
    for user in users:
        create_notification(db, user.id, title, message, noti_type, link)


def create_notification_for_all(db, title, message='', noti_type='system', link=None):
    """활성 사용자 전체에 알림 생성"""
    users = db.query(User).filter(
        User.is_active.is_(True),
        User.is_approved.is_(True)
    ).all()
    for user in users:
        create_notification(db, user.id, title, message, noti_type, link)
