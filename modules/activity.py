"""
전사 통합 활동 로그 헬퍼.

사용법:
    from modules.activity import log_activity
    log_activity(db, '가공발주', 'create', 'FO2026-001 가공발주 등록',
                 ref_type='ProcessingOrder', ref_id=1, ref_label='FO2026-001')
"""

from flask import session
from modules.models import ActivityLog


def log_activity(db, module, action, summary,
                 detail=None, ref_type=None, ref_id=None, ref_label=None,
                 project_id=None, user_name=None):
    """활동 로그 1건 기록"""
    db.add(ActivityLog(
        module=module,
        action=action,
        summary=summary,
        detail=detail,
        ref_type=ref_type,
        ref_id=ref_id,
        ref_label=ref_label,
        project_id=project_id,
        user_id=session.get('user_id'),
        user_name=user_name or session.get('full_name', ''),
    ))
