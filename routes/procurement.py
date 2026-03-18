import datetime

from collections import OrderedDict

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from sqlalchemy import func, extract, or_, distinct

from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.models import G2bProcurement
from modules.services.g2b_procurement_sync import sync_daily, sync_bulk

procurement_bp = Blueprint('procurement', __name__)


# --- ACTION HANDLERS ---

def handle_sync_daily(db, form, user_name):
    """일일 동기화 (전일 데이터)"""
    if session.get('role') != 'admin':
        return {'flash': ('권한이 없습니다.', 'danger')}
    result = sync_daily(db)
    total = result['created'] + result['updated']
    if total == 0:
        return {'flash': ('새로운 조달내역이 없습니다.', 'info')}
    msg = f"일일 동기화 완료: 신규 {result['created']}건, 갱신 {result['updated']}건"
    return {'flash': (msg, 'success')}


def handle_sync_bulk(db, form, user_name):
    """벌크 동기화 (2015~현재)"""
    if session.get('role') != 'admin':
        return {'flash': ('권한이 없습니다.', 'danger')}
    result = sync_bulk(db, start_year=2015)
    msg = f"벌크 동기화 완료: 신규 {result['created']}건, 갱신 {result['updated']}건"
    if result.get('errors'):
        msg += f", 오류 {result['errors']}건"
    return {'flash': (msg, 'success')}


ACTION_HANDLERS = {
    'sync_daily': handle_sync_daily,
    'sync_bulk': handle_sync_bulk,
}


# --- ROUTES ---

@procurement_bp.route('/procurement', methods=['GET'])
@login_required
def procurement_list():
    """나라장터 조달내역 목록 조회"""
    q = (request.args.get('q') or '').strip()
    year = (request.args.get('year') or '').strip()
    product = (request.args.get('product') or '').strip()
    org = (request.args.get('org') or '').strip()
    status_filter = (request.args.get('status') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 30)

    with get_db() as db:
        # --- 필터 조건 빌드 (공통) ---
        filters_list = []
        if q:
            like_q = f'%{q}%'
            filters_list.append(or_(
                G2bProcurement.cntrct_dlvr_req_nm.ilike(like_q),
                G2bProcurement.dminstt_nm.ilike(like_q),
                G2bProcurement.prdct_idnt_no_nm.ilike(like_q),
            ))
        if year:
            filters_list.append(
                extract('year', G2bProcurement.cntrct_dlvr_req_date) == int(year)
            )
        if product:
            filters_list.append(G2bProcurement.dtil_prdct_clsfc_no_nm == product)
        if org:
            filters_list.append(G2bProcurement.dminstt_nm.ilike(f'%{org}%'))

        # 상태 필터: 신규(chg=00, amt>0) / 변경(chg>00, amt>0) / 취소(amt=0, qty=0)
        if status_filter == 'new':
            filters_list.append(G2bProcurement.cntrct_dlvr_req_chg_ord == '00')
            filters_list.append(G2bProcurement.prdct_amt > 0)
        elif status_filter == 'changed':
            filters_list.append(G2bProcurement.cntrct_dlvr_req_chg_ord != '00')
            filters_list.append(G2bProcurement.prdct_amt > 0)
        elif status_filter == 'cancelled':
            filters_list.append(G2bProcurement.prdct_amt == 0)
            filters_list.append(G2bProcurement.prdct_qty == 0)
        elif status_filter == 'spec_price':
            filters_list.append(G2bProcurement.dtil_prdct_clsfc_no_nm == '스포츠조명기구')

        # --- 계약 단위 그룹 쿼리 (페이지네이션용) ---
        contract_q = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.min(G2bProcurement.cntrct_dlvr_req_date).label('req_date'),
            func.min(G2bProcurement.cntrct_dlvr_req_nm).label('req_nm'),
            func.min(G2bProcurement.dminstt_nm).label('dminstt'),
            func.min(G2bProcurement.dminstt_rgn_nm).label('rgn'),
            func.min(G2bProcurement.cntrct_mthd_nm).label('mthd'),
            func.min(G2bProcurement.dlvr_tmlmt_date).label('dlvr_date'),
            func.sum(G2bProcurement.prdct_amt).label('total_amt'),
            func.sum(G2bProcurement.prdct_qty).label('total_qty'),
            func.count().label('item_cnt'),
            func.max(G2bProcurement.cntrct_dlvr_req_chg_ord).label('chg_ord'),
        ).filter(*filters_list).group_by(
            G2bProcurement.cntrct_dlvr_req_no
        ).order_by(func.min(G2bProcurement.cntrct_dlvr_req_date).desc())

        total = contract_q.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page
        contract_rows = contract_q.offset(offset).limit(per_page).all()

        # --- 해당 페이지 계약의 품목 상세 일괄 로드 ---
        req_nos = [r.cntrct_dlvr_req_no for r in contract_rows]
        detail_items = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no.in_(req_nos)
        ).order_by(G2bProcurement.cntrct_dlvr_req_no, G2bProcurement.prdct_sno).all() if req_nos else []

        # 계약번호별 품목 그룹핑
        detail_map = OrderedDict()
        for item in detail_items:
            detail_map.setdefault(item.cntrct_dlvr_req_no, []).append(item)

        # 계약 목록에 품목 상세 매핑
        contracts = []
        for row in contract_rows:
            total_amt = row.total_amt or 0
            total_qty = row.total_qty or 0
            chg_ord = row.chg_ord or '00'

            # 규격가격 여부: 품목 중 스포츠조명기구(수요기관규격)가 있으면
            line_items = detail_map.get(row.cntrct_dlvr_req_no, [])
            is_spec_price = any(
                '스포츠조명기구' in (it.dtil_prdct_clsfc_no_nm or '')
                for it in line_items
            )

            # 상태 판별
            if total_amt == 0 and total_qty == 0 and chg_ord != '00':
                status = 'cancelled'
            elif is_spec_price:
                status = 'spec_price'
            elif chg_ord != '00':
                status = 'changed'
            else:
                status = 'new'

            contracts.append({
                'req_no': row.cntrct_dlvr_req_no,
                'req_date': row.req_date,
                'req_nm': row.req_nm,
                'dminstt': row.dminstt,
                'rgn': row.rgn,
                'dlvr_date': row.dlvr_date,
                'total_amt': total_amt,
                'item_cnt': row.item_cnt,
                'chg_ord': chg_ord,
                'status': status,
                'line_items': detail_map.get(row.cntrct_dlvr_req_no, []),
            })

        # --- 통계 (전체 기준, 필터 무관) ---
        total_contracts = db.query(func.count(distinct(G2bProcurement.cntrct_dlvr_req_no))).scalar() or 0
        total_amt = db.query(func.sum(G2bProcurement.prdct_amt)).scalar() or 0

        current_year = datetime.date.today().year
        year_row = db.query(
            func.count(distinct(G2bProcurement.cntrct_dlvr_req_no)),
            func.sum(G2bProcurement.prdct_amt)
        ).filter(
            extract('year', G2bProcurement.cntrct_dlvr_req_date) == current_year
        ).first()
        year_count = year_row[0] if year_row else 0
        year_amt = year_row[1] or 0 if year_row else 0

        top_row = db.query(
            G2bProcurement.dtil_prdct_clsfc_no_nm,
            func.count(distinct(G2bProcurement.cntrct_dlvr_req_no)).label('cnt')
        ).group_by(
            G2bProcurement.dtil_prdct_clsfc_no_nm
        ).order_by(func.count(distinct(G2bProcurement.cntrct_dlvr_req_no)).desc()).first()

        top_product = top_row[0] if top_row else '-'
        top_product_pct = round(top_row[1] / total_contracts * 100) if top_row and total_contracts else 0

        stats = {
            'total_count': total_contracts,
            'total_amt': total_amt,
            'year': current_year,
            'year_count': year_count,
            'year_amt': year_amt,
            'top_product': top_product,
            'top_product_pct': top_product_pct,
            'filtered': total,
        }

        # --- 필터 옵션 ---
        years = db.query(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).label('yr')
        ).distinct().order_by(extract('year', G2bProcurement.cntrct_dlvr_req_date).desc()).all()

        products = db.query(
            G2bProcurement.dtil_prdct_clsfc_no_nm
        ).distinct().order_by(G2bProcurement.dtil_prdct_clsfc_no_nm).all()

        filter_options = {
            'years': [int(r[0]) for r in years if r[0]],
            'products': [r[0] for r in products if r[0]],
        }

    return render_template(
        'procurement_list.html',
        contracts=contracts,
        pagination=pagination,
        stats=stats,
        filters={'q': q, 'year': year, 'product': product, 'org': org, 'status': status_filter},
        filter_options=filter_options,
        is_admin=(session.get('role') == 'admin'),
    )


@procurement_bp.route('/procurement', methods=['POST'])
@login_required
def procurement_action():
    """POST 액션 처리 (동기화)"""
    action = request.form.get('action')
    user_name = session.get('full_name') or '사용자'

    with get_db() as db:
        handler = ACTION_HANDLERS.get(action)
        if handler:
            result = handler(db, request.form, user_name)
            if result.get('flash'):
                flash(*result['flash'])
            db.commit()

    return redirect(url_for('procurement.procurement_list'))


@procurement_bp.route('/procurement/report')
@login_required
def procurement_report():
    """조달내역 분석 보고서 (차트) - 연도 필터 지원"""
    sel_year = (request.args.get('year') or '').strip()

    with get_db() as db:
        current_year = datetime.date.today().year

        # 공통 필터: 선택 연도가 있으면 해당 연도만
        def year_filter():
            filters = [G2bProcurement.prdct_amt > 0]
            if sel_year:
                filters.append(extract('year', G2bProcurement.cntrct_dlvr_req_date) == int(sel_year))
            return filters

        # 연도 목록 (셀렉트박스용)
        avail_years = db.query(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).label('yr')
        ).distinct().order_by(extract('year', G2bProcurement.cntrct_dlvr_req_date).desc()).all()
        year_options = [int(r[0]) for r in avail_years if r[0]]

        # 1) 품목별 금액 비율 (도넛차트)
        product_data = db.query(
            G2bProcurement.dtil_prdct_clsfc_no_nm,
            func.sum(G2bProcurement.prdct_amt).label('amt'),
            func.count(distinct(G2bProcurement.cntrct_dlvr_req_no)).label('cnt'),
        ).filter(
            *year_filter()
        ).group_by(
            G2bProcurement.dtil_prdct_clsfc_no_nm
        ).order_by(func.sum(G2bProcurement.prdct_amt).desc()).all()

        products = {
            'labels': [r[0] or '기타' for r in product_data],
            'amounts': [int(r[1] or 0) for r in product_data],
            'counts': [int(r[2] or 0) for r in product_data],
        }

        # 2) 연도별 계약금액 (막대차트) - 항상 전체 연도 (연도 선택과 무관)
        yearly_data = db.query(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).label('yr'),
            func.sum(G2bProcurement.prdct_amt).label('amt'),
            func.count(distinct(G2bProcurement.cntrct_dlvr_req_no)).label('cnt'),
        ).filter(
            G2bProcurement.prdct_amt > 0
        ).group_by('yr').order_by('yr').all()

        yearly = {
            'labels': [str(int(r[0])) for r in yearly_data if r[0]],
            'amounts': [int(r[1] or 0) for r in yearly_data if r[0]],
            'counts': [int(r[2] or 0) for r in yearly_data if r[0]],
        }

        # 3) 3년 월별 비교 (선택 연도 기준 ±1년, 미선택 시 최근 3년)
        if sel_year:
            center = int(sel_year)
            compare_years = [center - 1, center, center + 1]
        else:
            compare_years = [current_year - 2, current_year - 1, current_year]

        monthly_data = {}
        for yr in compare_years:
            rows = db.query(
                extract('month', G2bProcurement.cntrct_dlvr_req_date).label('mn'),
                func.sum(G2bProcurement.prdct_amt).label('amt'),
            ).filter(
                extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                G2bProcurement.prdct_amt > 0,
            ).group_by('mn').order_by('mn').all()

            month_map = {int(r[0]): int(r[1] or 0) for r in rows if r[0]}
            monthly_data[yr] = [month_map.get(m, 0) for m in range(1, 13)]

        monthly = {
            'labels': [f'{m}월' for m in range(1, 13)],
            'years': compare_years,
            'datasets': monthly_data,
        }

        # 4) 월별 추이
        if sel_year:
            # 선택 연도: 해당 연도 월별
            trend_q = db.query(
                extract('month', G2bProcurement.cntrct_dlvr_req_date).label('mn'),
                func.sum(G2bProcurement.prdct_amt).label('amt'),
            ).filter(*year_filter()).group_by('mn').order_by('mn').all()
            month_map = {int(r[0]): int(r[1] or 0) for r in trend_q if r[0]}
            trend = {
                'labels': [f'{m}월' for m in range(1, 13)],
                'amounts': [month_map.get(m, 0) for m in range(1, 13)],
            }
        else:
            # 전체: 1~12월 전 연도 합산
            trend_q = db.query(
                extract('month', G2bProcurement.cntrct_dlvr_req_date).label('mn'),
                func.sum(G2bProcurement.prdct_amt).label('amt'),
            ).filter(G2bProcurement.prdct_amt > 0).group_by('mn').order_by('mn').all()
            month_map = {int(r[0]): int(r[1] or 0) for r in trend_q if r[0]}
            trend = {
                'labels': [f'{m}월' for m in range(1, 13)],
                'amounts': [month_map.get(m, 0) for m in range(1, 13)],
            }

        # 5) 수요기관 TOP 10 (금액 기준)
        top_orgs_data = db.query(
            G2bProcurement.dminstt_nm,
            func.sum(G2bProcurement.prdct_amt).label('amt'),
            func.count(distinct(G2bProcurement.cntrct_dlvr_req_no)).label('cnt'),
        ).filter(
            *year_filter()
        ).group_by(
            G2bProcurement.dminstt_nm
        ).order_by(func.sum(G2bProcurement.prdct_amt).desc()).limit(10).all()

        top_orgs = {
            'labels': [r[0] or '기타' for r in top_orgs_data],
            'amounts': [int(r[1] or 0) for r in top_orgs_data],
            'counts': [int(r[2] or 0) for r in top_orgs_data],
        }

    return render_template(
        'procurement_report.html',
        products=products,
        yearly=yearly,
        monthly=monthly,
        trend=trend,
        top_orgs=top_orgs,
        current_year=current_year,
        sel_year=sel_year,
        year_options=year_options,
        current_date=datetime.date.today().strftime('%Y-%m-%d'),
    )
