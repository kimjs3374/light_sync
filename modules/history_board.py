import datetime

from modules.models import HistoryLog


VALID_SCOPES = {'common', 'design', 'contract', 'sales', 'material', 'production', 'delivery', 'drawing', 'technical'}


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
):
    resolved_kind = (kind or ('system' if '시스템' in (user_name or '') else 'comment')).strip().lower()
    if resolved_kind not in {'system', 'comment', 'reply'}:
        resolved_kind = 'comment'

    resolved_scope = (scope or '').strip().lower()
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
        'drawing': 0,
        'technical': 0,
        'comments': 0,
    }

    for log in history_rows:
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
        counts['all'] += 1
        if log.log_kind == 'comment':
            counts['comments'] += 1
        else:
            scope = log.log_scope if log.log_scope in ('design', 'contract', 'sales', 'material', 'production', 'delivery', 'drawing', 'technical') else default_scope
            if scope not in counts:
                scope = 'all'
            counts[scope] += 1

    return top_logs, counts


def get_project_history_context(db, project_id, default_scope='common', limit=500):
    """프로젝트 기준 히스토리 조회 + 보드 렌더링용 집계 공통 유틸"""
    history_rows = db.query(HistoryLog).filter(
        HistoryLog.project_id == project_id
    ).order_by(HistoryLog.created_at.desc(), HistoryLog.id.desc()).limit(limit).all()
    history, history_counts = build_history_view(history_rows, default_scope=default_scope)
    return history, history_counts
