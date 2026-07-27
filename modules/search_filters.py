"""목록 화면 검색어를 DB로 내리는 사전필터.

배경:
  6개 관리 화면은 계약된 현장 전체를 하위 데이터까지 joinedload 로 끌어온 뒤
  파이썬에서 검색어를 매칭한다. 완료 포함 조회 시 현장 1,302건 + 하위 26,745행을
  매번 로드하므로, 현장 하나를 검색해도 전량이 DB에서 나온다.

설계:
  각 화면의 파이썬 매칭 로직은 **손대지 않는다.** 이 모듈은 그 앞단에서
  "파이썬 필터가 통과시킬 수 있는 행을 반드시 포함하는" superset SQL 조건만 만든다.
  사전필터로 후보를 줄이고 최종 판정은 기존 파이썬 코드가 그대로 하므로
  화면에 나오는 결과는 달라지지 않는다.

  superset 을 보장할 수 없는 검색어(파생 문자열에만 존재하는 라벨 등)는 None 을
  돌려주고, 호출부는 사전필터 없이 기존 경로를 탄다 — 느리지만 정확하다.

사용법:
    pre = delivery_search_filter(q)
    if pre is not None:
        base_query = base_query.filter(pre)
"""
from sqlalchemy import or_, select, exists, and_

from modules.models import (
    Project, Contract, ContractItem, MaterialOrder,
)

# format_spec_summary(spec_utils.py:80) 가 만들어내는 라벨/값.
# item_spec_json 원문에는 없으므로 이 토큰이 걸리는 검색어는 사전필터를 포기한다.
_SPEC_SUMMARY_TOKENS = (
    '렌즈', '이격', '일체형', '높이', '등수', '앙카', '암대', '예', '아니오', '-',
)

# deliveries.delivery_status 저장값 (delivery.py DELIVERY_STATUS_OPTIONS)
_DELIVERY_STATUS_VALUES = ('waiting', 'coordinating', 'in_progress', 'done')


def _like(q):
    """ILIKE 패턴 — %, _ 는 리터럴로 취급"""
    escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _cols(pattern, *columns):
    return [c.ilike(pattern, escape='\\') for c in columns]


def _project_cols(pattern, include_short_name=True):
    cols = [Project.project_no, Project.temp_name]
    if include_short_name:
        cols.append(Project.short_name)
    return _cols(pattern, *cols)


def _contract_exists(*conditions):
    return exists(
        select(Contract.id).where(and_(Contract.project_id == Project.id, or_(*conditions)))
    ).correlate(Project)


def _contract_item_exists(*conditions):
    return exists(
        select(ContractItem.id)
        .join(Contract, Contract.id == ContractItem.contract_id)
        .where(and_(Contract.project_id == Project.id, or_(*conditions)))
    ).correlate(Project)


def _touches_spec_summary(q):
    """검색어가 파생 스펙요약 문자열에만 존재할 수 있는지.

    요약은 "이격:12m, 일체형:예" 처럼 라벨 + 값의 조합이다.
      - 라벨 안에서만 걸리는 검색어      → q 가 라벨의 부분문자열 (아래 판정)
      - 값 안에서만 걸리는 검색어        → item_spec_json ILIKE 로 이미 커버됨
      - 라벨↔값을 걸쳐서 걸리는 검색어   → 반드시 ':' 또는 ',' 를 포함
    셋 다 아니면 SQL 사전필터가 superset 임이 보장된다.
    """
    if ':' in q or ',' in q:
        return True
    return any(q in token for token in _SPEC_SUMMARY_TOKENS)


def delivery_search_filter(q):
    """납품관리 — delivery.py 의 hay: project_no, temp_name, contract_name, delivery_status

    delivery_status 는 사전필터에 넣지 않는다. 사전필터로 후보를 고른 **뒤**
    sync_deliveries() 가 그 값을 다시 계산하므로, 동기화 전 값으로 후보를 좁히면
    상태어 검색이 어긋난다. 상태값에 걸릴 수 있는 검색어는 사전필터를 포기한다.
    """
    if not q or any(q in status for status in _DELIVERY_STATUS_VALUES):
        return None
    p = _like(q)
    return or_(
        *_project_cols(p, include_short_name=False),
        _contract_exists(Contract.contract_name.ilike(p, escape='\\')),
    )


def project_list_search_filter(q):
    """영업관리 project_list — search_pool: project_no, temp_name, short_name"""
    if not q:
        return None
    return or_(*_project_cols(_like(q)))


def contract_list_search_filter(q):
    """계약관리 contract_list — search_pool 에 format_spec_summary() 파생문자열 포함.

    스펙요약 라벨('이격', '일체형', '예' 등)에 걸리는 검색어는 SQL 로 재현할 수 없으므로
    None 을 돌려 기존 전량조회 경로를 태운다.
    """
    if not q or _touches_spec_summary(q):
        return None
    p = _like(q)
    return or_(
        *_project_cols(p),
        _contract_exists(
            Contract.contract_name.ilike(p, escape='\\'),
            Contract.item_group.ilike(p, escape='\\'),
        ),
        _contract_item_exists(
            ContractItem.model_name.ilike(p, escape='\\'),
            ContractItem.item_spec_json.ilike(p, escape='\\'),
        ),
    )


def material_search_filter(q):
    """자재관리 — _match_order: project_no, temp_name, contract_name +
    material_orders(item_category, item_model_name, material_name, order_status, outsourcing_status)
    """
    if not q:
        return None
    p = _like(q)
    return or_(
        *_project_cols(p, include_short_name=False),
        _contract_exists(Contract.contract_name.ilike(p, escape='\\')),
        # 파이썬은 p.contracts → c.items → item.material_orders 로 순회하므로
        # 동일 경로로 조인한다 (order.project_id 직접 비교 시 경로 불일치분을 놓칠 수 있음)
        exists(
            select(MaterialOrder.id)
            .join(ContractItem, ContractItem.id == MaterialOrder.contract_item_id)
            .join(Contract, Contract.id == ContractItem.contract_id)
            .where(and_(
                Contract.project_id == Project.id,
                or_(*_cols(
                    p,
                    MaterialOrder.item_category,
                    MaterialOrder.item_model_name,
                    MaterialOrder.material_name,
                    MaterialOrder.order_status,
                    MaterialOrder.outsourcing_status,
                )),
            ))
        ).correlate(Project),
    )


def sales_search_filter(q):
    """영업(sales_list) — _match_project: project_no, temp_name, short_name,
    contract_name, item_group, item.model_name, item.category
    """
    if not q:
        return None
    p = _like(q)
    return or_(
        *_project_cols(p),
        _contract_exists(
            Contract.contract_name.ilike(p, escape='\\'),
            Contract.item_group.ilike(p, escape='\\'),
        ),
        _contract_item_exists(
            ContractItem.model_name.ilike(p, escape='\\'),
            ContractItem.category.ilike(p, escape='\\'),
        ),
    )
