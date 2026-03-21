"""계약 상태 기반 공통 필터 — 모든 관리 화면에서 공유

사용법:
    from modules.contract_filters import active_contract_filter

    base_query = db.query(Project).filter(Project.is_contracted == True)
    if not show_done:
        base_query = base_query.filter(active_contract_filter())
"""
from sqlalchemy import and_, or_, exists
from modules.models import Contract, Project


# 완료 상태 목록 (확장 시 여기만 수정)
DONE_STATUSES = ('입금완료', '변경완료', '취소')


def active_contract_filter():
    """입금완료/변경완료/취소가 아닌 계약이 하나라도 있는 프로젝트만 표시.
    계약이 없는 설계 프로젝트도 포함.

    Returns:
        SQLAlchemy filter clause
    """
    return or_(
        ~exists().where(Contract.project_id == Project.id),
        exists().where(and_(
            Contract.project_id == Project.id,
            Contract.payment_status.notin_(DONE_STATUSES)
        ))
    )
