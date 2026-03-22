"""입고 지연 알림 자동 생성 서비스"""
import datetime

from modules.models.entities import MaterialOrder, Notification, User


def create_receiving_delay_notifications(db):
    """지연 입고 알림 자동 생성 (하루 1회 중복 방지)"""
    today = datetime.date.today()
    today_start = datetime.datetime.combine(today, datetime.time.min)

    overdue_list = db.query(MaterialOrder).filter(
        MaterialOrder.order_status == '발주완료',
        MaterialOrder.in_confirmed.is_(False),
        MaterialOrder.expected_in_date.isnot(None),
        MaterialOrder.expected_in_date < today,
    ).all()

    if not overdue_list:
        return

    # 관리부 사용자 (입고 담당)
    admin_users = db.query(User).filter(
        User.user_group == '관리부',
        User.is_active.is_(True),
        User.is_approved.is_(True),
    ).all()

    if not admin_users:
        return

    for mo in overdue_list:
        dday_abs = (today - mo.expected_in_date).days
        link = f'/receiving?tab=expected'

        for user in admin_users:
            # 오늘 동일 MO 알림 중복 체크
            already = db.query(Notification).filter(
                Notification.user_id == user.id,
                Notification.link == link,
                Notification.title.contains(str(mo.id)),
                Notification.created_at >= today_start,
            ).first()
            if already:
                continue

            project_name = mo.project.temp_name if mo.project else '미지정'
            notif = Notification(
                user_id=user.id,
                title=f'[MO{mo.id}] 입고지연: {mo.material_name}',
                message=f'{project_name} — {mo.material_name} D+{dday_abs}일 지연 (예정: {mo.expected_in_date})',
                noti_type='system',
                link=link,
                is_read=False,
            )
            db.add(notif)

    db.commit()
