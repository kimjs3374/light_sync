"""납품예정시각 경과 회차 → 담당자 카카오워크 확인 DM

흐름:
  예정시각 경과 + 미완료 회차 탐색
    → 담당자(deliveries.contact_name)를 ERP User 로 매칭
    → 카카오워크 1:1 DM (✅ 납품완료 / 🕐 아직)
    → 버튼 클릭은 routes/kakaowork_action.py 에서 처리

주의:
  - `deliveries.contact_name` 은 User FK 가 아니라 자유 문자열이고, 저장 형식이 둘로 섞여 있다.
    '최한진'(담당자 지정 버튼) / '최한진 대리'(본인지정 버튼, 이름+직급).
    직급을 떼고 재시도하지 않으면 절반이 매칭에 실패한다.
  - 담당자 미배정·매칭 실패 건은 DM 대상이 없으므로 그룹방 알림으로 돌린다.
  - 같은 회차에 하루 두 번 묻지 않는다 (notify dedupe_key + 이력 확인).
"""
import datetime
import logging
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)

# scheduled_time 이 없는 회차의 기본 마감시각 — 이 시각이 지나야 '예정 경과'로 본다
DUE_HOUR = int(os.environ.get('DELIVERY_DUE_HOUR', '18'))

# 회차 완료로 보는 status 값 (delivery_actions.SPLIT_STATUS_DONE_VALUES 와 동일)
DONE_VALUES = ('done', '완료')


def _strip_position(name):
    """'최한진 대리' → '최한진'. 이름만 남긴다."""
    parts = (name or '').strip().split()
    return parts[0] if parts else ''


def resolve_owner(db, contact_name):
    """담당자 문자열 → User. 정확 일치 우선, 실패 시 직급 제거 후 재시도."""
    from modules.models import User

    name = (contact_name or '').strip()
    if not name:
        return None
    user = db.query(User).filter(User.full_name == name, User.is_active.is_(True)).first()
    if user:
        return user
    bare = _strip_position(name)
    if bare and bare != name:
        matches = db.query(User).filter(User.full_name == bare, User.is_active.is_(True)).all()
        # 동명이인이면 누구에게 보낼지 알 수 없다 — 그룹 알림으로 넘긴다
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning("[납품확인] 동명이인 %d명 — DM 스킵: %s", len(matches), name)
    return None


def find_due_splits(db, now=None):
    """예정시각이 지났는데 아직 완료되지 않은 회차 목록."""
    now = now or datetime.datetime.now()
    rows = db.execute(text('''
        SELECT s.id AS split_id, s.split_no, s.quantity, s.status,
               s.scheduled_date, s.scheduled_time, s.confirmed_date,
               d.id AS delivery_id, d.contact_name,
               p.id AS project_id, p.temp_name AS project_name, p.project_no,
               c.contract_name
        FROM light_sync.delivery_splits s
        JOIN light_sync.deliveries d ON d.id = s.delivery_id
        JOIN light_sync.projects p   ON p.id = d.project_id
        LEFT JOIN light_sync.contracts c ON c.id = d.contract_id
        WHERE COALESCE(s.status, '') NOT IN ('done', '완료')
          AND COALESCE(s.confirmed_date, s.scheduled_date) IS NOT NULL
          AND (COALESCE(s.confirmed_date, s.scheduled_date)
               + COALESCE(s.scheduled_time, make_time(:due_hour, 0, 0))) <= :now
        ORDER BY COALESCE(s.confirmed_date, s.scheduled_date), s.id
    '''), {'due_hour': DUE_HOUR, 'now': now}).fetchall()
    return rows


def _asked_today(db, split_id, today):
    """오늘 이미 물어봤는지 — 중복 발송 방지"""
    return db.execute(text('''
        SELECT 1 FROM light_sync.history_logs
        WHERE content LIKE :pat AND created_at >= :start LIMIT 1
    '''), {'pat': f'%[납품확인#{split_id}]%', 'start': datetime.datetime.combine(today, datetime.time.min)}
    ).first() is not None


def run_delivery_checks(db, dry_run=False, now=None):
    """예정 경과 회차에 대해 담당자 DM 발송 (담당자 없으면 그룹 알림).

    Returns:
        dict: {sent, unassigned, skipped, items[]}
    """
    from modules.history_board import append_history_log
    from modules.kakaowork_notifier import send_delivery_check_dm
    from modules.notification_engine import notify

    now = now or datetime.datetime.now()
    today = now.date()
    rows = find_due_splits(db, now)

    sent, unassigned, skipped, items = 0, [], 0, []
    for r in rows:
        due = r.confirmed_date or r.scheduled_date
        elapsed = (today - due).days
        label = f"{(r.project_name or r.project_no or '')[:32]} {r.split_no}차 {r.quantity or 0}EA"

        if _asked_today(db, r.split_id, today):
            skipped += 1
            continue

        owner = resolve_owner(db, r.contact_name)
        if not owner:
            unassigned.append({'split_id': r.split_id, 'label': label,
                               'contact_name': r.contact_name, 'elapsed': elapsed,
                               'project_id': r.project_id})
            continue

        items.append({'split_id': r.split_id, 'label': label,
                      'owner': owner.full_name, 'elapsed': elapsed})
        if dry_run:
            continue

        ok = send_delivery_check_dm(
            owner_name=owner.full_name,
            owner_dept=(owner.user_group or ''),
            owner_email=(owner.email or ''),
            split_id=r.split_id,
            project_name=(r.project_name or r.project_no or ''),
            contract_name=(r.contract_name or ''),
            split_no=r.split_no or 1,
            quantity=r.quantity or 0,
            due_date=due,
            elapsed_days=elapsed,
        )
        # 성공/실패 무관하게 물어본 사실을 남긴다 — 실패건이 매분 재시도되지 않도록
        append_history_log(
            db,
            project_id=r.project_id,
            user_name='시스템',
            content=(f'[납품확인#{r.split_id}] {owner.full_name}님에게 납품완료 확인 요청'
                     f' — {r.split_no}차 {r.quantity or 0}EA, 예정 {due} ({elapsed}일 경과)'
                     + ('' if ok else ' · 카카오 발송 실패')),
            scope='delivery',
            kind='system',
        )
        if ok:
            sent += 1

    # 담당자 없는 건은 그룹방으로 — 아무도 모르는 채로 묻히지 않게
    if unassigned and not dry_run:
        detail = ', '.join(f"{u['label']}({u['elapsed']}일 경과)" for u in unassigned[:5])
        if len(unassigned) > 5:
            detail += f" 외 {len(unassigned) - 5}건"
        notify(db, 'delivery.check_unassigned', {
            'count': len(unassigned),
            'detail': detail,
            'project_id': unassigned[0]['project_id'],
        }, dedupe_key=f"dlv_check_unassigned:{today}")
        for u in unassigned:
            append_history_log(
                db,
                project_id=u['project_id'],
                user_name='시스템',
                content=(f"[납품확인#{u['split_id']}] 담당자 미배정/매칭실패"
                         f"(contact_name={u['contact_name']!r}) — 그룹방 알림으로 대체"),
                scope='delivery',
                kind='system',
            )

    logger.info('[납품확인] 대상 %d건 — DM %d건, 담당자없음 %d건, 오늘이미발송 %d건',
                len(rows), sent, len(unassigned), skipped)
    return {'total': len(rows), 'sent': sent, 'unassigned': len(unassigned),
            'skipped': skipped, 'items': items, 'unassigned_items': unassigned}


def complete_split(db, split_id, user_name):
    """회차를 납품완료 처리하고 납품 계획/실적을 재계산한다.

    웹 화면(handle_update_split)과 같은 필드를 건드린다.
    Returns: (ok, message)
    """
    from modules.models import DeliverySplit, Delivery
    from modules.history_board import append_history_log
    from modules.services.delivery_actions import sync_deliveries, mark_split_delivered

    split = db.query(DeliverySplit).get(split_id)
    if not split:
        return False, '회차를 찾을 수 없습니다.'
    if (split.status or '') in DONE_VALUES:
        return True, '이미 납품완료 처리된 회차입니다.'

    delivery = db.query(Delivery).get(split.delivery_id)
    now = datetime.datetime.now()
    # 버튼 클릭 시점을 납품일시로 확정 (status/납품일시/확정일 한 세트)
    mark_split_delivered(split, delivered_at=now, now=now)

    project_id = delivery.project_id if delivery else None
    if project_id:
        append_history_log(
            db,
            project_id=project_id,
            user_name=user_name or '시스템',
            content=f"{split.split_no}차 {split.quantity or 0}EA 납품완료 처리 ({split.delivered_done_at.strftime('%Y-%m-%d %H:%M')}, 카카오워크 확인)",
            scope='delivery',
            kind='system',
        )
        db.flush()
        sync_deliveries(db, project_id=project_id)
    return True, f'{split.split_no}차 납품완료로 처리했습니다.'
