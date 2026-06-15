import datetime
import json

from flask import session
from sqlalchemy import func
from modules.models import HistoryLog, HistoryReadMark


def get_user_display_name(fallback='사용자'):
    """세션에서 이름+직급 형식 반환 (예: 김정수 차장)"""
    name = session.get('full_name', fallback)
    pos = session.get('position', '')
    return f"{name} {pos}" if pos else name


# drawing → design으로 통합, technical → 미사용 (하자AS 별도 PDCA 예정)
VALID_SCOPES = {'common', 'design', 'contract', 'sales', 'material', 'production', 'delivery'}
# 기존 drawing/technical 데이터 호환: 입력 시 design으로 매핑
_SCOPE_ALIAS = {'drawing': 'design', 'technical': 'design'}


def append_history_log(
    db,
    project_id,
    user_name,
    content,
    scope='common',
    kind=None,
    parent_log_id=None,
    root_log_id=None,
    origin_snapshot=None,
    origin='system',
):
    resolved_kind = (kind or ('system' if '시스템' in (user_name or '') else 'comment')).strip().lower()
    if resolved_kind not in {'system', 'comment', 'reply'}:
        resolved_kind = 'comment'

    resolved_scope = (scope or '').strip().lower()
    resolved_scope = _SCOPE_ALIAS.get(resolved_scope, resolved_scope)
    if resolved_scope not in VALID_SCOPES:
        resolved_scope = 'common' if resolved_kind == 'comment' else 'design'

    log = HistoryLog(
        project_id=project_id,
        user_name=user_name,
        content=content,
        log_scope=resolved_scope,
        log_kind=resolved_kind,
        parent_log_id=parent_log_id,
        root_log_id=root_log_id,
        origin_snapshot=origin_snapshot,
        origin=origin,
    )
    db.add(log)
    return log


def build_history_view(history_rows, default_scope='common'):
    top_logs = []
    reply_map = {}
    counts = {
        'all': 0,
        'design': 0,
        'contract': 0,
        'sales': 0,
        'material': 0,
        'production': 0,
        'delivery': 0,
        'comments': 0,
    }

    for log in history_rows:
        # attachments_json → list 변환
        raw = getattr(log, 'attachments_json', None)
        if raw and isinstance(raw, str):
            try:
                log.attachments_json = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                log.attachments_json = []
        elif not raw:
            log.attachments_json = []

        if not log.log_kind:
            log.log_kind = 'system' if '시스템' in (log.user_name or '') else 'comment'
        if not log.log_scope:
            log.log_scope = 'common' if log.log_kind == 'comment' else default_scope

        if log.parent_log_id:
            reply_map.setdefault(log.parent_log_id, []).append(log)
        else:
            top_logs.append(log)

    for log in top_logs:
        log.thread_replies = sorted(
            reply_map.get(log.id, []),
            key=lambda x: (x.created_at or datetime.datetime.min, x.id or 0)
        )

    # reply 포함 전체 로그 대상 카운트 (기존 drawing/technical → design으로 매핑)
    for log in history_rows:
        counts['all'] += 1
        if log.log_kind in ('comment', 'reply'):
            counts['comments'] += 1
        else:
            scope = _SCOPE_ALIAS.get(log.log_scope, log.log_scope)
            if scope not in counts:
                scope = default_scope if default_scope in counts else 'design'
            counts[scope] += 1

    return top_logs, counts


def get_project_history_context(db, project_id, default_scope='common', limit=500, user_id=None):
    """프로젝트 기준 히스토리 조회 + 보드 렌더링용 집계 공통 유틸"""
    history_rows = db.query(HistoryLog).filter(
        HistoryLog.project_id == project_id
    ).order_by(HistoryLog.created_at.desc(), HistoryLog.id.desc()).limit(limit).all()
    history, history_counts = build_history_view(history_rows, default_scope=default_scope)

    # 안 읽은 건수 계산
    unread = 0
    if user_id and history_rows:
        mark = db.query(HistoryReadMark).filter_by(
            user_id=user_id, project_id=project_id
        ).first()
        last_read = mark.last_read_at if mark else None
        if last_read:
            unread = sum(1 for log in history_rows if log.created_at and log.created_at > last_read)
        else:
            unread = len(history_rows)
    history_counts['unread'] = unread

    # 읽은 사람 목록 (최근 읽음 기준)
    readers = db.query(HistoryReadMark).filter_by(project_id=project_id).all()
    read_users = []
    for r in readers:
        if r.full_name:
            read_users.append({'name': r.full_name, 'read_at': r.last_read_at.strftime('%m/%d %H:%M') if r.last_read_at else ''})
    history_counts['readers'] = read_users

    return history, history_counts


def mark_history_read(db, user_id, project_id, full_name=None):
    """히스토리 읽음 처리 — last_read_at을 현재 시각으로 갱신"""
    mark = db.query(HistoryReadMark).filter_by(
        user_id=user_id, project_id=project_id
    ).first()
    now = datetime.datetime.now()
    if mark:
        mark.last_read_at = now
        if full_name:
            mark.full_name = full_name
    else:
        db.add(HistoryReadMark(user_id=user_id, project_id=project_id,
                               last_read_at=now, full_name=full_name))
    db.commit()
