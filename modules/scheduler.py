"""백그라운드 스케줄러 — 출장 상태 자동 업데이트, G2B 일일 동기화 등"""
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
_scheduler = None


def _sync_g2b_daily():
    """G2B 조달내역 일일 동기화 + 자동 계약 생성 (매일 06:00)"""
    from modules.db_context import get_db
    from modules.services.g2b_procurement_sync import sync_daily, auto_create_contracts

    try:
        with get_db() as db:
            result = sync_daily(db)
            db.commit()
            auto_result = auto_create_contracts(db)
            db.commit()
        logger.info(
            f"[scheduler] G2B 일일동기화 완료 — 신규 {result['created']}건, "
            f"갱신 {result['updated']}건 / 자동계약 {auto_result.get('created', 0)}건"
        )
    except Exception as e:
        logger.error(f"[scheduler] G2B 일일동기화 오류: {e}")


def _auto_update_trip_status():
    """출장 상태 자동 전환 (10분마다)
    예정  → 진행중 : departure_date <= 지금
    진행중 → 완료   : return_date   <= 지금
    """
    from modules.db_context import get_db
    from modules.models import BusinessTrip

    now = datetime.datetime.now()
    updated = 0
    try:
        with get_db() as db:
            # 예정 → 진행중
            to_ongoing = db.query(BusinessTrip).filter(
                BusinessTrip.status == '예정',
                BusinessTrip.departure_date <= now,
            ).all()
            for trip in to_ongoing:
                trip.status = '진행중'
                updated += 1

            # 예정/진행중 → 완료
            to_done = db.query(BusinessTrip).filter(
                BusinessTrip.status.in_(['예정', '진행중']),
                BusinessTrip.return_date <= now,
            ).all()
            for trip in to_done:
                trip.status = '완료'
                updated += 1

            if updated:
                db.commit()
                logger.info(f"[scheduler] 출장 상태 자동 업데이트 {updated}건")
    except Exception as e:
        logger.error(f"[scheduler] 출장 상태 업데이트 오류: {e}")


def init_scheduler(app):
    """앱 컨텍스트 안에서 스케줄러 시작"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _auto_update_trip_status,
        trigger='interval',
        minutes=10,
        id='trip_status_update',
        replace_existing=True,
    )
    _scheduler.add_job(
        _sync_g2b_daily,
        trigger='cron',
        hour=6,
        minute=0,
        id='g2b_daily_sync',
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("[scheduler] 백그라운드 스케줄러 시작 (출장상태 10분, G2B동기화 매일 06:00)")
