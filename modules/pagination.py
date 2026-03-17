import math
from flask import request


def make_pagination(page, per_page, total, window=2):
    """페이지네이션 메타데이터 생성"""
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))

    start = max(1, page - window)
    end = min(total_pages, page + window)

    return {
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_page': page - 1,
        'next_page': page + 1,
        'page_range': list(range(start, end + 1)),
        'show_first': start > 1,
        'show_last': end < total_pages,
    }


def pagination_query(page_num):
    """현재 필터 쿼리스트링을 유지하면서 page 파라미터만 교체"""
    args = request.args.to_dict()
    args['page'] = page_num
    return '&'.join(f'{k}={v}' for k, v in args.items())
