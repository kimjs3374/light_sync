import datetime

from collections import OrderedDict

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from sqlalchemy import func, extract, or_, distinct
from urllib.parse import quote

from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.models import G2bProcurement, Contract, ContractItem, Project
from modules.services.g2b_procurement_sync import sync_daily, sync_bulk
from modules.services.procurement_summary import (
    get_filter_options, get_summary_pivot, build_chart_data, generate_excel,
)

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

        # G2B 연동 맵: g2b_contract_no -> (contract_id, project_id)
        linked_contracts = db.query(
            Contract.g2b_contract_no, Contract.id, Contract.project_id
        ).filter(
            Contract.g2b_contract_no.isnot(None),
            Contract.g2b_contract_no.in_(req_nos) if req_nos else False,
        ).all() if req_nos else []
        linked_map = {r[0]: {'contract_id': r[1], 'project_id': r[2]} for r in linked_contracts}

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

            linked = linked_map.get(row.cntrct_dlvr_req_no)
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
                'linked': linked,
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


# ===================================================================
# G2B <-> ERP Contract Matching
# ===================================================================

def _can_match():
    """매칭 권한 확인: 영업부 또는 admin"""
    return session.get('role') == 'admin' or session.get('user_group') == '영업부'


def _score_date(contract_date, g2b_date):
    """날짜 매칭 점수 (최대 40)"""
    if not contract_date or not g2b_date:
        return 0
    delta = abs((contract_date - g2b_date).days)
    if delta == 0:
        return 40
    elif delta <= 7:
        return 20
    elif delta <= 30:
        return 10
    return 0


def _score_name(contract_name, g2b_name):
    """이름 유사도 점수 (최대 30) - 순수 부분문자열 매칭"""
    if not contract_name or not g2b_name:
        return 0
    cn = contract_name.strip().replace(' ', '')
    gn = g2b_name.strip().replace(' ', '')
    if not cn or not gn:
        return 0
    # 정확 일치
    if cn == gn:
        return 30
    # 한쪽이 다른쪽에 포함
    if cn in gn or gn in cn:
        return 25
    # 공통 부분문자열 (길이 3 이상)
    max_common = 0
    shorter, longer = (cn, gn) if len(cn) <= len(gn) else (gn, cn)
    for length in range(min(len(shorter), 20), 2, -1):
        found = False
        for start in range(len(shorter) - length + 1):
            sub = shorter[start:start + length]
            if sub in longer:
                max_common = length
                found = True
                break
        if found:
            break
    if max_common >= 6:
        return 20
    elif max_common >= 4:
        return 15
    elif max_common >= 3:
        return 10
    return 0


def _score_amount(contract_total, g2b_amt):
    """금액 근사 점수 (최대 20)"""
    if not contract_total or not g2b_amt or contract_total == 0 or g2b_amt == 0:
        return 0
    ratio = abs(contract_total - g2b_amt) / max(contract_total, g2b_amt)
    if ratio <= 0.05:
        return 20
    elif ratio <= 0.15:
        return 15
    elif ratio <= 0.30:
        return 10
    return 0


def _score_org(project_temp_name, g2b_dminstt):
    """수요기관-현장명 부분일치 점수 (최대 10)"""
    if not project_temp_name or not g2b_dminstt:
        return 0
    pn = project_temp_name.strip().replace(' ', '')
    gn = g2b_dminstt.strip().replace(' ', '')
    if not pn or not gn:
        return 0
    if pn in gn or gn in pn:
        return 10
    # 공통 부분문자열 (길이 2 이상)
    shorter, longer = (pn, gn) if len(pn) <= len(gn) else (gn, pn)
    for length in range(min(len(shorter), 10), 1, -1):
        for start in range(len(shorter) - length + 1):
            sub = shorter[start:start + length]
            if sub in longer:
                if length >= 4:
                    return 8
                elif length >= 3:
                    return 5
                elif length >= 2:
                    return 3
    return 0


@procurement_bp.route('/api/g2b-search', methods=['GET'])
@login_required
def g2b_search():
    """G2B 미연동 계약 검색 API (계약 등록 시 불러오기용)"""
    q = request.args.get('q', '').strip()

    with get_db() as db:
        # 이미 연동된 계약번호 목록
        linked_nos = [r[0] for r in db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None)
        ).all()]

        filters = [G2bProcurement.prdct_amt > 0]
        if q:
            like_q = f'%{q}%'
            filters.append(
                (G2bProcurement.cntrct_dlvr_req_nm.ilike(like_q)) |
                (G2bProcurement.dminstt_nm.ilike(like_q))
            )
        else:
            # 검색어 없으면 최근 30일 이내
            d_min = datetime.date.today() - datetime.timedelta(days=30)
            filters.append(G2bProcurement.cntrct_dlvr_req_date >= d_min)

        g2b_q = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.min(G2bProcurement.cntrct_dlvr_req_date).label('req_date'),
            func.min(G2bProcurement.cntrct_dlvr_req_nm).label('req_nm'),
            func.min(G2bProcurement.dminstt_nm).label('dminstt'),
            func.min(G2bProcurement.dlvr_tmlmt_date).label('dlvr_date'),
            func.sum(G2bProcurement.prdct_amt).label('total_amt'),
            func.count().label('item_cnt'),
        ).filter(*filters)

        if linked_nos:
            g2b_q = g2b_q.filter(~G2bProcurement.cntrct_dlvr_req_no.in_(linked_nos))

        g2b_q = g2b_q.group_by(
            G2bProcurement.cntrct_dlvr_req_no
        ).order_by(func.min(G2bProcurement.cntrct_dlvr_req_date).desc()).limit(30)

        results = []
        for g in g2b_q.all():
            # 해당 계약의 품목 상세
            items = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_no == g.cntrct_dlvr_req_no
            ).order_by(G2bProcurement.prdct_sno).all()

            item_list = []
            for it in items:
                item_list.append({
                    'detail_name': it.dtil_prdct_clsfc_no_nm or '',
                    'spec_name': it.prdct_idnt_no_nm or '',
                    'qty': it.prdct_qty or 0,
                    'amt': int(it.prdct_amt or 0),
                })

            results.append({
                'req_no': g.cntrct_dlvr_req_no,
                'req_nm': g.req_nm or '',
                'req_date': g.req_date.strftime('%Y-%m-%d') if g.req_date else '',
                'dminstt': g.dminstt or '',
                'dlvr_date': g.dlvr_date.strftime('%Y-%m-%d') if g.dlvr_date else '',
                'total_amt': int(g.total_amt or 0),
                'item_cnt': g.item_cnt,
                'items': item_list,
            })

    return jsonify({'results': results})


@procurement_bp.route('/api/g2b-match/<int:contract_id>', methods=['GET'])
@login_required
def g2b_match_candidates(contract_id):
    """G2B 매칭 후보 목록 API"""
    if not _can_match():
        return jsonify({'error': '권한이 없습니다.'}), 403

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'error': '계약을 찾을 수 없습니다.'}), 404

        project = db.query(Project).get(contract.project_id)

        # 계약 품목 합계 금액 계산
        contract_total = db.query(func.sum(ContractItem.quantity)).filter(
            ContractItem.contract_id == contract_id
        ).scalar() or 0
        # ContractItem에 금액 컬럼이 없으므로 수량 기반 비교는 skip,
        # 대신 contract에 연결된 항목 수량합을 사용

        # G2B 후보: 계약 단위 그룹 (취소 건 제외)
        # 이미 다른 Contract에 연동된 건 제외
        linked_nos = [r[0] for r in db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None),
            Contract.id != contract_id,
        ).all()]

        # 날짜 범위 필터: contract_date +/- 180일
        date_filters = []
        if contract.contract_date:
            d_min = contract.contract_date - datetime.timedelta(days=180)
            d_max = contract.contract_date + datetime.timedelta(days=180)
            date_filters.append(G2bProcurement.cntrct_dlvr_req_date >= d_min)
            date_filters.append(G2bProcurement.cntrct_dlvr_req_date <= d_max)

        g2b_groups = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.min(G2bProcurement.cntrct_dlvr_req_date).label('req_date'),
            func.min(G2bProcurement.cntrct_dlvr_req_nm).label('req_nm'),
            func.min(G2bProcurement.dminstt_nm).label('dminstt'),
            func.sum(G2bProcurement.prdct_amt).label('total_amt'),
            func.sum(G2bProcurement.prdct_qty).label('total_qty'),
            func.count().label('item_cnt'),
        ).filter(
            G2bProcurement.prdct_amt > 0,
            *date_filters,
        )

        if linked_nos:
            g2b_groups = g2b_groups.filter(
                ~G2bProcurement.cntrct_dlvr_req_no.in_(linked_nos)
            )

        g2b_groups = g2b_groups.group_by(
            G2bProcurement.cntrct_dlvr_req_no
        ).all()

        # 점수 계산
        candidates = []
        for g in g2b_groups:
            s_date = _score_date(contract.contract_date, g.req_date)
            s_name = _score_name(contract.contract_name, g.req_nm)
            s_amt = _score_amount(g.total_amt, g.total_amt)  # G2B 금액 vs G2B 금액 (self) - 아래 수정
            s_org = _score_org(project.temp_name if project else '', g.dminstt)

            # 금액 비교: ContractItem에 단가가 없으므로, G2B 금액끼리 비교 대신 skip
            # 실제로는 contract에 총액 정보가 없어 금액 점수는 G2B 총액 크기만 참고
            # -> 여기서는 0으로 처리하되, 다른 점수로 보완
            total_score = s_date + s_name + s_org
            # 금액 점수는 추후 ContractItem에 금액 컬럼이 추가되면 활성화
            # 현재는 최대 80점 만점 체계

            if total_score < 5:
                continue

            candidates.append({
                'req_no': g.cntrct_dlvr_req_no,
                'req_nm': g.req_nm or '',
                'req_date': g.req_date.strftime('%Y-%m-%d') if g.req_date else '',
                'dminstt': g.dminstt or '',
                'total_amt': int(g.total_amt or 0),
                'item_cnt': g.item_cnt,
                'score': total_score,
                'score_detail': {
                    'date': s_date,
                    'name': s_name,
                    'org': s_org,
                },
            })

        # 정렬: 점수 내림차순
        candidates.sort(key=lambda x: (-x['score'], x['req_date']))
        candidates = candidates[:10]

    return jsonify({'candidates': candidates})


@procurement_bp.route('/api/g2b-match/<int:contract_id>/link', methods=['POST'])
@login_required
def g2b_match_link(contract_id):
    """G2B 매칭 연동 저장"""
    if not _can_match():
        return jsonify({'error': '권한이 없습니다.'}), 403

    data = request.get_json() or {}
    g2b_no = (data.get('g2b_contract_no') or '').strip()
    if not g2b_no:
        return jsonify({'error': 'g2b_contract_no is required'}), 400

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'error': '계약을 찾을 수 없습니다.'}), 404

        # 중복 확인: 다른 Contract에 이미 연동된 G2B 번호인지
        existing = db.query(Contract).filter(
            Contract.g2b_contract_no == g2b_no,
            Contract.id != contract_id,
        ).first()
        if existing:
            return jsonify({'error': f'이미 다른 계약(ID:{existing.id})에 연동된 G2B 번호입니다.'}), 409

        contract.g2b_contract_no = g2b_no
        db.commit()

    return jsonify({'ok': True, 'g2b_contract_no': g2b_no})


@procurement_bp.route('/api/g2b-match/<int:contract_id>/unlink', methods=['POST'])
@login_required
def g2b_match_unlink(contract_id):
    """G2B 매칭 연동 해제"""
    if not _can_match():
        return jsonify({'error': '권한이 없습니다.'}), 403

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'error': '계약을 찾을 수 없습니다.'}), 404

        contract.g2b_contract_no = None
        db.commit()

    return jsonify({'ok': True})


# ===================================================================
# 납품집계 (Delivery Summary)
# ===================================================================

def _parse_years():
    """년도 파라미터 파싱 (multi-select + comma-sep)"""
    current_year = datetime.date.today().year
    years = []
    for v in request.args.getlist('years'):
        for part in v.split(','):
            part = part.strip()
            if part:
                try:
                    years.append(int(part))
                except ValueError:
                    pass
    return years or [current_year]


@procurement_bp.route('/procurement/summary')
@login_required
def procurement_summary():
    """납품집계 — 대분류 선택 필수, 모델 검색 시 모델별 전환"""
    years = _parse_years()
    category = (request.args.get('category') or '').strip()
    q = (request.args.get('q') or '').strip()

    # 모델 검색어 있으면 모델별, 없으면 대분류별
    view = 'model' if q else 'category'

    with get_db() as db:
        filter_options = get_filter_options(db)
        pivot = get_summary_pivot(
            db, years=years, category=category or None,
            q=q or None, group_by=view,
        )
        chart_data = build_chart_data(pivot)

    import json
    return render_template(
        'procurement_summary.html',
        pivot=pivot,
        chart_data_json=json.dumps(chart_data, ensure_ascii=False),
        filters={'years': ','.join(str(y) for y in years), 'category': category, 'q': q, 'view': view},
        filter_options=filter_options,
        selected_years=years,
        current_date=datetime.date.today().strftime('%Y-%m-%d'),
    )


@procurement_bp.route('/procurement/summary/excel')
@login_required
def procurement_summary_excel():
    """납품집계 엑셀 다운로드"""
    years = _parse_years()
    category = (request.args.get('category') or '').strip()
    q = (request.args.get('q') or '').strip()
    view = 'model' if q else 'category'

    with get_db() as db:
        pivot = get_summary_pivot(
            db, years=years, category=category or None,
            q=q or None, group_by=view,
        )

    title = f'납품집계_{category}' if category else '납품집계'
    try:
        buf = generate_excel(pivot, years, title=title)
    except ImportError:
        flash('openpyxl 모듈이 설치되지 않았습니다.', 'danger')
        return redirect(url_for('procurement.procurement_summary'))

    year_str = '_'.join(str(y) for y in years)
    filename = f'{title}_{year_str}.xlsx'
    encoded = quote(filename)

    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded}"
    return resp


@procurement_bp.route('/api/procurement-models')
@login_required
def procurement_model_suggest():
    """모델(규격명) 자동완성 API"""
    category = (request.args.get('category') or '').strip()
    q = (request.args.get('q') or '').strip()

    with get_db() as db:
        filters = [
            G2bProcurement.prdct_amt > 0,
            G2bProcurement.prdct_idnt_no_nm.isnot(None),
        ]
        if category:
            filters.append(G2bProcurement.dtil_prdct_clsfc_no_nm == category)
        if q:
            filters.append(G2bProcurement.prdct_idnt_no_nm.ilike(f'%{q}%'))

        rows = db.query(
            G2bProcurement.prdct_idnt_no_nm,
            func.count().label('cnt'),
        ).filter(*filters).group_by(
            G2bProcurement.prdct_idnt_no_nm,
        ).order_by(func.count().desc()).limit(20).all()

    return jsonify([{'name': r[0], 'count': r[1]} for r in rows])
