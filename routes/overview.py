import datetime

from flask import Blueprint, render_template, request
from sqlalchemy.orm import joinedload

from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models import Project, Contract, ContractItem, Delivery
from modules.pagination import make_pagination
from modules.utils import safe_int

overview_bp = Blueprint('overview', __name__)


def _calc_entry(proj):
    """프로젝트의 단계별 진행률 계산"""
    total_items = 0
    sales_done = 0
    material_done = 0
    production_done = 0
    total_deliveries = 0
    delivery_done = 0

    for contract in proj.contracts:
        for item in contract.items:
            total_items += 1
            if item.status_sales == '협의완료':
                sales_done += 1
            if item.status_admin == '입고완료':
                material_done += 1
            if item.status_prod == '생산완료':
                production_done += 1

        for delivery in contract.deliveries:
            total_deliveries += 1
            if delivery.delivery_status == '납품완료':
                delivery_done += 1

    sales_pct = round(sales_done / total_items * 100) if total_items else 0
    material_pct = round(material_done / total_items * 100) if total_items else 0
    production_pct = round(production_done / total_items * 100) if total_items else 0
    delivery_pct = round(delivery_done / total_deliveries * 100) if total_deliveries else 0

    phases = [sales_pct, material_pct, production_pct, delivery_pct]
    overall_pct = round(sum(phases) / len(phases)) if phases else 0

    return {
        'project': proj,
        'total_items': total_items,
        'total_deliveries': total_deliveries,
        'sales_pct': sales_pct,
        'material_pct': material_pct,
        'production_pct': production_pct,
        'delivery_pct': delivery_pct,
        'overall_pct': overall_pct,
    }


@overview_bp.route('/project_overview')
@login_required
def project_overview():
    search = (request.args.get('search') or '').strip()
    progress_filter = request.args.get('progress', 'all')   # all/not_started/in_progress/completed
    sort_by = request.args.get('sort', 'id_desc')           # id_desc/pct_asc/pct_desc
    page = safe_int(request.args.get('page'), 1)
    per_page = 20

    with get_db() as db:
        projects = db.query(Project).filter(Project.is_contracted.is_(True)).options(
            joinedload(Project.contracts).joinedload(Contract.items),
            joinedload(Project.contracts).joinedload(Contract.deliveries),
        ).order_by(Project.id.desc()).all()

        # 전체 계산
        all_entries = [_calc_entry(p) for p in projects]

        # 검색
        if search:
            q = search.lower()
            all_entries = [e for e in all_entries
                          if q in (e['project'].temp_name or '').lower()
                          or q in (e['project'].project_no or '').lower()
                          or q in (e['project'].short_name or '').lower()]

        # 진행상태 필터
        if progress_filter == 'not_started':
            all_entries = [e for e in all_entries if e['overall_pct'] == 0]
        elif progress_filter == 'in_progress':
            all_entries = [e for e in all_entries if 0 < e['overall_pct'] < 100]
        elif progress_filter == 'completed':
            all_entries = [e for e in all_entries if e['overall_pct'] == 100]

        # 통계 (필터 전 전체 기준)
        total_all = len([_calc_entry(p) for p in projects])  # 이미 계산되므로 len(projects)
        total_all = len(projects)
        completed_count = sum(1 for e in [_calc_entry(p) for p in projects] if e['overall_pct'] == 100)
        in_progress_count = sum(1 for e in [_calc_entry(p) for p in projects] if 0 < e['overall_pct'] < 100)

        # 정렬
        if sort_by == 'pct_asc':
            all_entries.sort(key=lambda e: e['overall_pct'])
        elif sort_by == 'pct_desc':
            all_entries.sort(key=lambda e: e['overall_pct'], reverse=True)
        # id_desc는 이미 기본 정렬

        # 페이지네이션
        total = len(all_entries)
        pagination = make_pagination(page, per_page, total)
        start = (pagination['page'] - 1) * per_page
        entries = all_entries[start:start + per_page]

        stats = {
            'total_projects': total_all,
            'filtered': total,
            'completed': completed_count,
            'in_progress': in_progress_count,
        }

    return render_template(
        'project_overview.html',
        entries=entries,
        filters={'search': search, 'progress': progress_filter, 'sort': sort_by},
        pagination=pagination,
        stats=stats,
    )
