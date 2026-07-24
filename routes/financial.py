"""
매출관리 Blueprint — 세금계산서 기준 + G2B 매칭 보강.

주 데이터: tax_invoices (국세청 엑셀 임포트)
보강: g2b_procurements 매칭으로 계약명/수요기관 등 연결
"""

import datetime
import logging
import re

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort,
)
from sqlalchemy import desc, func, extract, text, or_
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int, parse_date
from modules.db_context import get_db
from modules.models import (
    TaxInvoice, Contract, G2bProcurement, Project,
    MATCH_STATUS_CHOICES,
)
from modules.services.warranty_auto import auto_create_warranty
from modules.services.tax_invoice_agg import deduped_invoice_subq
from difflib import SequenceMatcher
from modules.activity import log_activity

logger = logging.getLogger(__name__)

financial_bp = Blueprint('financial', __name__)


def _fmt_money(val):
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_bizno(raw):
    """사업자등록번호 → XXX-XX-XXXXX (10자리 아니면 원본 반환)."""
    d = re.sub(r'\D', '', str(raw or ''))
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if len(d) == 10 else (raw or '')


# 자사(공급자/공급받는자 중 매그나텍 측) 정보 — 전자세금계산서 양식 보강용
from modules.services.delivery_doc_pdf import (
    COMPANY_NAME, COMPANY_BIZ_NO, COMPANY_ADDR, COMPANY_CEO,
    COMPANY_TEL, COMPANY_FAX, number_to_korean,
)

_COMPANY_INFO = {
    'name': COMPANY_NAME,
    'biz_no': COMPANY_BIZ_NO,
    'biz_no_digits': re.sub(r'\D', '', COMPANY_BIZ_NO),
    'addr': COMPANY_ADDR,
    'ceo': COMPANY_CEO,
    'tel': COMPANY_TEL,
    'fax': COMPANY_FAX,
}


def _korean_money(val):
    """정수 금액 → '일금 …원정' (음수/0 안전)."""
    try:
        n = int(val or 0)
    except (ValueError, TypeError):
        return ''
    if n == 0:
        return '일금 영원정'
    sign = '(-) ' if n < 0 else ''
    return f"일금 {sign}{number_to_korean(abs(n))}원정"


# ===================================================================
# 1. 매출 대시보드 (경영진용)
# ===================================================================
@financial_bp.route('/financial/dashboard')
@login_required
@menu_required('financial')
def financial_dashboard():
    with get_db() as db:
        today = datetime.date.today()
        current_month_start = today.replace(day=1)
        next_month = (current_month_start + datetime.timedelta(days=32)).replace(day=1)

        # 승인번호 정규화 중복제거 서브쿼리 (이중저장 과대계상 방지)
        inv = deduped_invoice_subq(db)
        # G2B 매칭된 정상 세금계산서만
        matched_filter = inv.c.match_status.in_(['자동매칭', '수동매칭'])
        normal_filter = inv.c.invoice_type == '세금계산서'

        # KPI (G2B 매칭된 것만)
        monthly_supply = db.query(
            func.coalesce(func.sum(inv.c.supply_amount), 0)
        ).filter(normal_filter, matched_filter,
                 inv.c.issue_date >= current_month_start,
                 inv.c.issue_date < next_month).scalar() or 0

        total_supply = db.query(
            func.coalesce(func.sum(inv.c.supply_amount), 0)
        ).filter(normal_filter, matched_filter).scalar() or 0

        total_cnt = db.query(func.count(inv.c.id)).filter(
            normal_filter, matched_filter).scalar() or 0

        kpi = {
            'monthly_supply': monthly_supply,
            'total_supply': total_supply,
            'total_cnt': total_cnt,
        }

        # Chart 1: 월별 매출 추이 (최근 12개월, G2B 매칭분만)
        months = []
        for i in range(11, -1, -1):
            d = today - datetime.timedelta(days=i * 30)
            months.append(d.replace(day=1))

        monthly_labels = []
        monthly_amounts = []
        for m in months:
            m_end = (m + datetime.timedelta(days=32)).replace(day=1)
            amt = db.query(
                func.coalesce(func.sum(inv.c.supply_amount), 0)
            ).filter(normal_filter, matched_filter,
                     inv.c.issue_date >= m,
                     inv.c.issue_date < m_end).scalar() or 0
            monthly_labels.append(f"{m.month}월")
            monthly_amounts.append(int(amt))

        # Chart 2: 월별 발행 건수 (G2B 매칭분만)
        count_labels = []
        count_values = []
        for m in months:
            m_end = (m + datetime.timedelta(days=32)).replace(day=1)
            cnt = db.query(func.count(inv.c.id)).filter(
                normal_filter, matched_filter,
                inv.c.issue_date >= m,
                inv.c.issue_date < m_end).scalar() or 0
            count_labels.append(f"{m.month}월")
            count_values.append(cnt)

        # Chart 3: 수요기관별 매출 TOP 10 (G2B 매칭분, buyer_name = 수요기관)
        top_buyers = db.query(
            inv.c.buyer_name,
            func.sum(inv.c.supply_amount).label('total')
        ).filter(normal_filter, matched_filter,
                 inv.c.buyer_name.isnot(None)
        ).group_by(inv.c.buyer_name).order_by(
            func.sum(inv.c.supply_amount).desc()
        ).limit(10).all()

        buyer_labels = [r[0] or '(미상)' for r in top_buyers]
        buyer_amounts = [int(r[1] or 0) for r in top_buyers]

        # ===== 년도별 계약 대비 매출 + 이월 =====
        # 매칭된 세금계산서 G2B 번호 set
        invoiced_nos = set(
            r[0] for r in db.query(inv.c.g2b_contract_no).filter(
                normal_filter, matched_filter,
                inv.c.g2b_contract_no.isnot(None),
            ).all()
        )

        # 년도별 집계
        yearly_rows = db.query(
            extract('year', G2bProcurement.cntrct_dlvr_req_date).label('yr'),
            func.count(G2bProcurement.id),
            func.sum(G2bProcurement.prdct_amt),
        ).filter(
            G2bProcurement.cntrct_dlvr_req_date.isnot(None),
        ).group_by('yr').order_by(desc('yr')).all()

        yearly_data = []
        for yr_val, cnt, contract_amt in yearly_rows:
            yr = int(yr_val) if yr_val else 0
            if yr < 2013:
                continue
            contract_amt = int(contract_amt or 0)

            # 해당 년도 계약 중 세금계산서 발행된 금액
            invoiced_amt = db.query(
                func.coalesce(func.sum(G2bProcurement.prdct_amt), 0)
            ).filter(
                extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                G2bProcurement.cntrct_dlvr_req_no.in_(invoiced_nos) if invoiced_nos else False,
            ).scalar() or 0

            # 해당 년도 계약 중 미발행 건
            yr_all_nos = set(
                r[0] for r in db.query(G2bProcurement.cntrct_dlvr_req_no).filter(
                    extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                ).distinct().all()
            )
            yr_uninvoiced_nos = yr_all_nos - invoiced_nos
            uninvoiced_amt = 0
            uninvoiced_cnt = 0
            if yr_uninvoiced_nos:
                row = db.query(
                    func.count(G2bProcurement.id),
                    func.coalesce(func.sum(G2bProcurement.prdct_amt), 0),
                ).filter(
                    G2bProcurement.cntrct_dlvr_req_no.in_(yr_uninvoiced_nos),
                    extract('year', G2bProcurement.cntrct_dlvr_req_date) == yr,
                ).first()
                if row:
                    uninvoiced_cnt = row[0] or 0
                    uninvoiced_amt = int(row[1] or 0)

            sales_rate = round(int(invoiced_amt) / contract_amt * 100, 1) if contract_amt > 0 else 0

            yearly_data.append({
                'year': yr,
                'contract_cnt': cnt,
                'contract_amt': contract_amt,
                'invoiced_amt': int(invoiced_amt),
                'sales_rate': sales_rate,
                'carryover_cnt': uninvoiced_cnt,
                'carryover_amt': uninvoiced_amt,
            })

        # 년도별 차트 데이터 (최근 5년)
        recent_yearly = list(reversed(yearly_data[:5]))
        yearly_chart = {
            'labels': [str(d['year']) for d in recent_yearly],
            'contract': [d['contract_amt'] for d in recent_yearly],
            'invoiced': [d['invoiced_amt'] for d in recent_yearly],
            'carryover': [d['carryover_amt'] for d in recent_yearly],
        }

        # 년도별 조달 세금계산서 발행금액 추이 (전체 연도)
        yearly_invoice_rows = db.query(
            extract('year', inv.c.issue_date).label('yr'),
            func.sum(inv.c.total_amount),
            func.count(inv.c.id),
        ).filter(
            matched_filter,
            inv.c.issue_date.isnot(None),
        ).group_by('yr').order_by('yr').all()

        yearly_invoice_chart = {
            'labels': [str(int(r[0])) for r in yearly_invoice_rows if r[0] and int(r[0]) >= 2013],
            'amounts': [int(r[1] or 0) for r in yearly_invoice_rows if r[0] and int(r[0]) >= 2013],
            'counts': [int(r[2] or 0) for r in yearly_invoice_rows if r[0] and int(r[0]) >= 2013],
        }

        return render_template('financial_dashboard.html',
            kpi=kpi,
            monthly_labels=monthly_labels,
            monthly_amounts=monthly_amounts,
            count_labels=count_labels,
            count_values=count_values,
            buyer_labels=buyer_labels,
            buyer_amounts=buyer_amounts,
            yearly_data=yearly_data,
            yearly_chart=yearly_chart,
            yearly_invoice_chart=yearly_invoice_chart,
            fmt_money=_fmt_money,
        )


# ===================================================================
# 2. 세금계산서 목록 (세금계산서가 주인공)
# ===================================================================
@financial_bp.route('/financial/tax-invoices')
@login_required
@menu_required('financial')
def tax_invoice_list():
    with get_db() as db:
        page = safe_int(request.args.get('page'), 1)
        per_page = 50

        match_filter = request.args.get('match', 'matched')  # matched / unmatched / all

        q = db.query(TaxInvoice).options(
            joinedload(TaxInvoice.contract),
            joinedload(TaxInvoice.project),
        )

        if match_filter == 'matched':
            q = q.filter(TaxInvoice.match_status.in_(['자동매칭', '수동매칭']))
        elif match_filter == 'unmatched':
            q = q.filter(TaxInvoice.match_status == '미매칭')
        # 'all' → 필터 없음

        # 필터
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        search = request.args.get('search', '').strip()

        if date_from:
            d = parse_date(date_from)
            if d:
                q = q.filter(TaxInvoice.issue_date >= d)
        if date_to:
            d = parse_date(date_to)
            if d:
                q = q.filter(TaxInvoice.issue_date <= d)
        if search:
            # G2B 계약명으로도 검색: g2b_contract_no → g2b_procurements.cntrct_dlvr_req_nm
            g2b_match_nos = set()
            if len(search) >= 2:
                g2b_hits = db.query(G2bProcurement.cntrct_dlvr_req_no).filter(
                    G2bProcurement.cntrct_dlvr_req_nm.ilike(f'%{search}%')
                ).distinct().all()
                g2b_match_nos = {r[0] for r in g2b_hits}

            search_filters = [
                TaxInvoice.buyer_name.ilike(f'%{search}%'),
                TaxInvoice.approval_no.ilike(f'%{search}%'),
                TaxInvoice.item_name.ilike(f'%{search}%'),
                TaxInvoice.g2b_contract_no.ilike(f'%{search}%'),
            ]
            if g2b_match_nos:
                search_filters.append(TaxInvoice.g2b_contract_no.in_(g2b_match_nos))
            q = q.filter(or_(*search_filters))

        total = q.count()
        invoices = q.order_by(desc(TaxInvoice.issue_date), desc(TaxInvoice.id))\
            .offset((page - 1) * per_page).limit(per_page).all()

        pagination = make_pagination(page, per_page, total)

        # G2B 매칭 보강: 세금계산서의 g2b_contract_no → g2b_procurements에서 계약명/수요기관 가져오기
        g2b_nos = [inv.g2b_contract_no for inv in invoices if inv.g2b_contract_no]
        g2b_map = {}
        if g2b_nos:
            procs = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_no.in_(g2b_nos)
            ).all()
            for p in procs:
                if p.cntrct_dlvr_req_no not in g2b_map:
                    g2b_map[p.cntrct_dlvr_req_no] = p

        # 합계 (G2B 매칭된 정상 세금계산서만) — 정규화 중복제거
        _inv = deduped_invoice_subq(db)
        sum_supply = db.query(func.coalesce(func.sum(_inv.c.supply_amount), 0)).filter(
            _inv.c.invoice_type == '세금계산서',
            _inv.c.match_status.in_(['자동매칭', '수동매칭']),
        ).scalar() or 0

        # 탭 뱃지용 건수
        unpaid_contract_count = db.query(func.count(Contract.id)).filter(
            Contract.payment_status == '미청구'
        ).scalar() or 0
        partial_contract_count = db.query(func.count(Contract.id)).filter(
            Contract.payment_status == '부분입금'
        ).scalar() or 0
        exception_contract_count = db.query(func.count(Contract.id)).filter(
            Contract.payment_status == '예외'
        ).scalar() or 0

        # 미청구/부분입금/예외 계약 목록
        unpaid_contracts = []
        unpaid_sort = request.args.get('sort', 'due_asc')
        unpaid_due = request.args.get('due', 'all')
        if match_filter in ('unmatched', 'partial', 'exception'):
            if match_filter == 'partial':
                target_statuses = ['부분입금']
            elif match_filter == 'exception':
                target_statuses = ['예외']
            else:
                target_statuses = ['미청구']
            unpaid_q = db.query(Contract).options(
                joinedload(Contract.project),
            ).filter(
                Contract.payment_status.in_(target_statuses),
            )
            unpaid_search = (request.args.get('q') or '').strip()
            if unpaid_search:
                like_q = f'%{unpaid_search}%'
                unpaid_q = unpaid_q.filter(
                    (Contract.contract_name.ilike(like_q)) |
                    (Contract.g2b_contract_no.ilike(like_q)) |
                    (Contract.project.has(Project.short_name.ilike(like_q)))
                )
            _today = datetime.date.today()
            if unpaid_due == 'overdue':
                unpaid_q = unpaid_q.filter(Contract.delivery_due_date < _today)
            elif unpaid_due == 'month':
                unpaid_q = unpaid_q.filter(
                    Contract.delivery_due_date >= _today,
                    Contract.delivery_due_date <= _today + datetime.timedelta(days=30),
                )
            elif unpaid_due == 'future':
                unpaid_q = unpaid_q.filter(Contract.delivery_due_date >= _today)
            if unpaid_sort == 'due_desc':
                unpaid_q = unpaid_q.order_by(desc(Contract.delivery_due_date))
            elif unpaid_sort == 'date_desc':
                unpaid_q = unpaid_q.order_by(desc(Contract.contract_date))
            elif unpaid_sort == 'date_asc':
                unpaid_q = unpaid_q.order_by(Contract.contract_date.asc())
            else:  # due_asc (납기 오래된 순 = 기본)
                unpaid_q = unpaid_q.order_by(Contract.delivery_due_date.asc().nullslast())
            unpaid_contracts = unpaid_q.all()

        return render_template('tax_invoice_list.html',
            invoices=invoices,
            g2b_map=g2b_map,
            pagination=pagination,
            match_status_list=MATCH_STATUS_CHOICES,
            sum_supply=sum_supply,
            fmt_money=_fmt_money,
            match_filter=match_filter,
            unpaid_contract_count=unpaid_contract_count,
            partial_contract_count=partial_contract_count,
            exception_contract_count=exception_contract_count,
            unpaid_contracts=unpaid_contracts,
            unpaid_sort=unpaid_sort,
            unpaid_due=unpaid_due,
            today=datetime.date.today(),
        )


# ===================================================================
# 3. 엑셀 임포트
# ===================================================================
@financial_bp.route('/financial/tax-invoice/import', methods=['POST'])
@login_required
@menu_required('financial')
def tax_invoice_import():
    from modules.services.tax_invoice_import import parse_tax_invoice_excel, import_and_match

    file = request.files.get('excel_file')
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return redirect(url_for('financial.tax_invoice_list'))

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ('xls', 'xlsx'):
        flash('엑셀 파일(.xls, .xlsx)만 업로드 가능합니다.', 'danger')
        return redirect(url_for('financial.tax_invoice_list'))

    try:
        # G2B 번호 세트 로딩 (비고 파싱용)
        with get_db() as db:
            g2b_set = set(
                r[0] for r in db.execute(text(
                    'SELECT DISTINCT cntrct_dlvr_req_no FROM light_sync.g2b_procurements'
                )).fetchall()
            )

        records = parse_tax_invoice_excel(file_stream=file, g2b_numbers_set=g2b_set)
        if not records:
            flash('데이터를 읽을 수 없습니다. 국세청 양식인지 확인해주세요.', 'warning')
            return redirect(url_for('financial.tax_invoice_list'))

        with get_db() as db:
            result = import_and_match(db, records)
            log_activity(db, '매출수금', 'import', f'세금계산서 임포트 {result["imported"]}건', ref_type='TaxInvoice')
            db.commit()

        flash(
            f"임포트 완료: {result['imported']}건 신규 "
            f"(G2B매칭 {result['matched']}건, 미매칭 {result['unmatched']}건, "
            f"중복스킵 {result['skipped']}건)",
            'success'
        )
    except Exception as e:
        logger.error(f"세금계산서 임포트 오류: {e}", exc_info=True)
        flash(f'임포트 중 오류: {str(e)}', 'danger')

    return redirect(url_for('financial.tax_invoice_list'))


# ===================================================================
# 4. 세금계산서 상세
# ===================================================================
@financial_bp.route('/financial/tax-invoice/<int:invoice_id>')
@login_required
@menu_required('financial')
def tax_invoice_detail(invoice_id):
    with get_db() as db:
        inv = db.query(TaxInvoice).options(
            joinedload(TaxInvoice.contract),
            joinedload(TaxInvoice.project),
        ).get(invoice_id)
        if not inv:
            abort(404)

        # G2B 보강: 세금계산서 또는 연결된 계약의 G2B번호로 조달내역 조회
        g2b_procs = []
        g2b_total_amt = 0
        g2b_total_qty = 0
        g2b_no = inv.g2b_contract_no
        if not g2b_no and inv.contract and inv.contract.g2b_contract_no:
            g2b_no = inv.contract.g2b_contract_no
        if g2b_no:
            g2b_procs = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_no == g2b_no
            ).all()
            g2b_total_amt = sum(p.prdct_amt or 0 for p in g2b_procs)
            g2b_total_qty = sum(p.prdct_qty or 0 for p in g2b_procs)

        # 수동 매칭용 계약 목록
        contracts = []
        if inv.match_status == '미매칭':
            contracts = db.query(Contract).options(
                joinedload(Contract.project)
            ).order_by(desc(Contract.contract_date)).limit(50).all()

        return render_template('tax_invoice_detail.html',
            inv=inv,
            g2b_procs=g2b_procs,
            g2b_total_amt=g2b_total_amt,
            g2b_total_qty=g2b_total_qty,
            contracts=contracts,
            fmt_money=_fmt_money,
            fmt_bizno=_fmt_bizno,
            company=_COMPANY_INFO,
            total_korean=_korean_money(inv.total_amount),
        )


# ===================================================================
# 5. 수동 매칭
# ===================================================================
@financial_bp.route('/financial/tax-invoice/<int:invoice_id>/match', methods=['POST'])
@login_required
@menu_required('financial')
def tax_invoice_match(invoice_id):
    with get_db() as db:
        inv = db.query(TaxInvoice).get(invoice_id)
        if not inv:
            abort(404)

        contract_id = safe_int(request.form.get('contract_id'))
        if contract_id:
            contract = db.query(Contract).get(contract_id)
            if contract:
                inv.contract_id = contract.id
                inv.project_id = contract.project_id
                inv.match_status = '수동매칭'
                # 금액 비교 후 수금상태 재계산
                from modules.services.warranty_auto import recalc_contract_payment_status
                status = recalc_contract_payment_status(db, contract, inv.issue_date)
                log_activity(db, '매출수금', 'match', f'세금계산서 수동매칭 ({contract.contract_name or ""})',
                             ref_type='TaxInvoice', ref_id=inv.id)
                db.commit()
                flash(f'계약 매칭 완료. ({status})', 'success')
            else:
                flash('계약을 찾을 수 없습니다.', 'danger')
        else:
            flash('계약을 선택해주세요.', 'warning')

    return redirect(url_for('financial.tax_invoice_detail', invoice_id=invoice_id))


# ===================================================================
# 6. 계약 기준 세금계산서 매칭 API (AJAX)
# ===================================================================

# 공공기관 거래처 판별 키워드
_PUBLIC_KEYWORDS = (
    '군', '시', '도', '구', '청', '공사', '공단', '대학', '교육',
    '조달', '국립', '한국', '센터', '연구', '재단', '공원', '체육',
    '시설', '환경', '항만', '산림', '보건', '복지',
)


def _is_public_buyer(name):
    """공공기관(조달대금) 거래처 여부 추정"""
    if not name:
        return False
    return any(kw in name for kw in _PUBLIC_KEYWORDS)


@financial_bp.route('/financial/api/invoice-candidates/<int:contract_id>')
@login_required
@menu_required('financial')
def invoice_candidates(contract_id):
    """미청구 계약에 대해:
    - 유사도 상위 5건 자동 추천
    - 검색어 있으면 조달 추정 미매칭 세금계산서 전체 검색
    """
    search = (request.args.get('q') or '').strip().lower()

    with get_db() as db:
        contract = db.query(Contract).options(
            joinedload(Contract.project),
        ).get(contract_id)
        if not contract:
            return jsonify({'recommend': [], 'search_results': []})

        contract_name = contract.contract_name or ''
        project_name = (contract.project.temp_name if contract.project else '') or ''
        buyer_name = (contract.project.short_name if contract.project else '') or ''
        g2b_no = contract.g2b_contract_no or ''

        # 미매칭 + 조달 추정 세금계산서
        all_unmatched = db.query(TaxInvoice).filter(
            TaxInvoice.match_status == '미매칭',
        ).order_by(desc(TaxInvoice.issue_date)).all()

        public_invoices = [inv for inv in all_unmatched if _is_public_buyer(inv.buyer_name)]

        def _to_dict(inv, score=0):
            return {
                'invoice_id': inv.id,
                'issue_date': inv.issue_date.strftime('%Y-%m-%d') if inv.issue_date else '-',
                'buyer_name': (inv.buyer_name or '')[:40],
                'item_name': (inv.item_name or '')[:60],
                'total_amount': inv.total_amount or 0,
                'g2b_no': (inv.g2b_contract_no or '')[:15],
                'score': score,
            }

        # ── 추천: 유사도 상위 5건 ──
        # 품목명(item_name)이 핵심 — 비고 공란인 세금계산서는 품목명에 계약명이 들어있음
        scored = []
        for inv in public_invoices:
            inv_buyer = inv.buyer_name or ''
            inv_item = inv.item_name or ''
            inv_g2b = inv.g2b_contract_no or ''

            # 품목명 ↔ 계약명 (핵심: 비고 공란인 건의 매칭 단서)
            score_item_contract = SequenceMatcher(None, inv_item, contract_name).ratio()
            # 품목명 ↔ 현장명
            score_item_project = SequenceMatcher(None, inv_item, project_name).ratio()
            # 거래처 ↔ 발주처
            score_buyer = SequenceMatcher(None, inv_buyer, buyer_name).ratio()
            # 거래처명에 계약명 키워드 포함 여부
            score_buyer_contract = SequenceMatcher(None, inv_buyer, contract_name).ratio()

            score = max(score_item_contract, score_item_project) * 0.5 + max(score_buyer, score_buyer_contract) * 0.3

            if g2b_no and inv_g2b:
                if g2b_no == inv_g2b:
                    score = 1.0
                elif len(g2b_no) >= 10 and len(inv_g2b) >= 10 and g2b_no[:10] == inv_g2b[:10]:
                    score += 0.3

            if score >= 0.1:
                scored.append((inv, round(score * 100)))

        scored.sort(key=lambda x: x[1], reverse=True)
        recommend = [_to_dict(inv, sc) for inv, sc in scored[:5]]

        # ── 검색: 미매칭 세금계산서 전체에서 검색 (조달 추정 필터 없음) ──
        search_results = []
        if search:
            for inv in all_unmatched:
                hay = ' '.join([
                    inv.buyer_name or '',
                    inv.item_name or '',
                    inv.g2b_contract_no or '',
                    inv.approval_no or '',
                    inv.issue_date.strftime('%Y-%m-%d') if inv.issue_date else '',
                ]).lower()
                if search in hay:
                    search_results.append(_to_dict(inv))
            search_results = search_results[:50]

        return jsonify({
            'recommend': recommend,
            'search_results': search_results,
            'public_total': len(public_invoices),
        })


# ===================================================================
# 6-2. 계약 상세 정보 API (매칭 모달용)
# ===================================================================
@financial_bp.route('/financial/api/contract-info/<int:contract_id>')
@login_required
@menu_required('financial')
def contract_info(contract_id):
    """매칭 모달에 표시할 계약 상세 정보"""
    with get_db() as db:
        c = db.query(Contract).options(
            joinedload(Contract.project),
            joinedload(Contract.items),
        ).get(contract_id)
        if not c:
            return jsonify({})

        items = [{
            'category': item.category,
            'model_name': item.model_name,
            'quantity': item.quantity or 0,
        } for item in (c.items or [])]

        total_amt = sum(item.quantity or 0 for item in (c.items or []))

        # G2B 조달내역에서 금액 조회
        g2b_amt = 0
        if c.g2b_contract_no:
            row = db.execute(text(
                'SELECT SUM(prdct_amt) FROM light_sync.g2b_procurements WHERE cntrct_dlvr_req_no = :no'
            ), {'no': c.g2b_contract_no}).scalar()
            g2b_amt = row or 0

        # 이미 매칭된 세금계산서
        matched_invs = db.query(TaxInvoice).filter(
            TaxInvoice.contract_id == c.id,
        ).order_by(TaxInvoice.issue_date).all()
        invoiced_total = sum(i.total_amount or 0 for i in matched_invs)
        matched_list = [{
            'approval_no': i.approval_no,
            'issue_date': i.issue_date.strftime('%Y-%m-%d') if i.issue_date else '-',
            'buyer_name': (i.buyer_name or '')[:30],
            'total_amount': i.total_amount or 0,
            'invoice_type': i.invoice_type or '',
        } for i in matched_invs]

        return jsonify({
            'contract_name': c.contract_name or '',
            'g2b_no': c.g2b_contract_no or '',
            'buyer': c.project.short_name if c.project else '',
            'project_name': c.project.temp_name if c.project else '',
            'contract_date': c.contract_date.strftime('%Y-%m-%d') if c.contract_date else '-',
            'delivery_due': c.delivery_due_date.strftime('%Y-%m-%d') if c.delivery_due_date else '-',
            'payment_status': c.payment_status or '',
            'item_group': c.item_group or '',
            'g2b_amount': g2b_amt,
            'invoiced_total': invoiced_total,
            'matched_invoices': matched_list,
            'items': items,
        })


# ===================================================================
# 7. 매칭 공통 로직 + API
# ===================================================================
def _do_match_invoice(db, inv, contract):
    """세금계산서를 계약에 매칭 + 수금상태 자동 판별

    Returns: str (결과 메시지)
    """
    inv.contract_id = contract.id
    inv.project_id = contract.project_id
    inv.match_status = '수동매칭'
    if contract.g2b_contract_no and not inv.g2b_contract_no:
        inv.g2b_contract_no = contract.g2b_contract_no

    # 최신 발행일 갱신
    if not contract.invoice_date or (inv.issue_date and inv.issue_date > contract.invoice_date):
        contract.invoice_date = inv.issue_date

    # 수금상태 재계산 (공통 함수)
    from modules.services.warranty_auto import recalc_contract_payment_status
    recalc_contract_payment_status(db, contract, inv.issue_date)

    return f'{(contract.contract_name or "")[:40]} ← {inv.buyer_name or ""}'


@financial_bp.route('/financial/api/quick-match', methods=['POST'])
@login_required
@menu_required('financial')
def quick_match():
    """계약 기준으로 세금계산서 수동매칭"""
    data = request.get_json() or {}
    invoice_id = safe_int(data.get('invoice_id'))
    contract_id = safe_int(data.get('contract_id'))

    if not invoice_id or not contract_id:
        return jsonify({'ok': False, 'error': '파라미터 부족'}), 400

    with get_db() as db:
        inv = db.query(TaxInvoice).get(invoice_id)
        contract = db.query(Contract).options(joinedload(Contract.project)).get(contract_id)
        if not inv or not contract:
            return jsonify({'ok': False, 'error': '데이터 없음'}), 404

        msg = _do_match_invoice(db, inv, contract)
        status = contract.payment_status
        log_activity(db, '매출수금', 'match', f'세금계산서 매칭 ({msg})', ref_type='TaxInvoice', ref_id=inv.id)
        db.commit()

    return jsonify({'ok': True, 'message': f'{msg} 매칭 완료 ({status})'})


# ===================================================================
# 8. 예외 처리 (미청구/부분입금 → 완료 처리)
# ===================================================================
@financial_bp.route('/financial/api/exclude-contract', methods=['POST'])
@login_required
@menu_required('financial')
def exclude_contract():
    """미청구/부분입금 계약을 예외 처리 (완료)"""
    data = request.get_json() or {}
    contract_id = safe_int(data.get('contract_id'))
    reason = data.get('reason', '기타')
    note = data.get('note', '')

    if not contract_id:
        return jsonify({'ok': False, 'error': '계약 ID 없음'}), 400

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'ok': False, 'error': '계약 없음'}), 404

        msg_name = (contract.contract_name or '')[:40]
        old_status = contract.payment_status

        # payment_status를 '예외'로 변경 → 관리 화면에서 숨김
        # 세금계산서 탭에서는 '예외' 상태로 별도 표시
        contract.payment_status = '예외'

        # 메모 기록
        if contract.project_id:
            proj = db.query(Project).get(contract.project_id)
            if proj:
                proj.site_memo = (proj.site_memo or '') + f'\n[예외처리] {reason}: {old_status}→예외' + (f' — {note}' if note else '')

        log_activity(db, '매출수금', 'exclude', f'{msg_name} 예외처리 ({reason})', ref_type='Contract', ref_id=contract.id)
        db.commit()

    return jsonify({'ok': True, 'message': f'{msg_name} → {reason} 예외처리 완료'})


@financial_bp.route('/financial/api/restore-exception', methods=['POST'])
@login_required
@menu_required('financial')
def restore_exception():
    """예외 계약을 해제하고 수금상태를 재계산"""
    from modules.services.warranty_auto import recalc_contract_payment_status

    data = request.get_json() or {}
    contract_id = safe_int(data.get('contract_id'))
    if not contract_id:
        return jsonify({'ok': False, 'error': '계약 ID 없음'}), 400

    with get_db() as db:
        contract = db.query(Contract).get(contract_id)
        if not contract:
            return jsonify({'ok': False, 'error': '계약 없음'}), 404

        if contract.payment_status != '예외':
            return jsonify({'ok': False, 'error': '예외 상태가 아닙니다'}), 400

        # 임시로 미청구로 변경 후 재계산 (recalc가 예외 상태는 건드리지 않으므로)
        contract.payment_status = '미청구'
        new_status = recalc_contract_payment_status(db, contract)

        msg_name = (contract.contract_name or '')[:40]

        if contract.project_id:
            proj = db.query(Project).get(contract.project_id)
            if proj:
                proj.site_memo = (proj.site_memo or '') + f'\n[예외해제] 예외→{new_status}'

        log_activity(db, '매출수금', 'restore', f'{msg_name} 예외 해제 ({new_status})', ref_type='Contract', ref_id=contract.id)
        db.commit()

    return jsonify({'ok': True, 'message': f'{msg_name} → 예외 해제 ({new_status})'})


# ===================================================================
# 9. 승인번호로 세금계산서 조회 (AJAX)
# ===================================================================
@financial_bp.route('/financial/api/find-invoice')
@login_required
@menu_required('financial')
def find_invoice():
    """승인번호 또는 부분 검색으로 세금계산서 조회 + 매칭 상태 확인"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify([])

    with get_db() as db:
        invoices = db.query(TaxInvoice).filter(
            (TaxInvoice.approval_no.ilike(f'%{q}%')) |
            (TaxInvoice.buyer_name.ilike(f'%{q}%')) |
            (TaxInvoice.item_name.ilike(f'%{q}%'))
        ).order_by(desc(TaxInvoice.issue_date)).limit(30).all()

        results = []
        for inv in invoices:
            matched_contract_name = ''
            if inv.contract_id:
                c = db.query(Contract).get(inv.contract_id)
                if c:
                    matched_contract_name = c.contract_name or ''

            results.append({
                'invoice_id': inv.id,
                'approval_no': inv.approval_no,
                'issue_date': inv.issue_date.strftime('%Y-%m-%d') if inv.issue_date else '-',
                'buyer_name': (inv.buyer_name or '')[:40],
                'item_name': (inv.item_name or '')[:60],
                'total_amount': inv.total_amount or 0,
                'match_status': inv.match_status or '미매칭',
                'matched_contract': matched_contract_name[:50],
                'g2b_no': (inv.g2b_contract_no or '')[:15],
            })

        return jsonify(results)


# ===================================================================
# 9. 승인번호로 강제매칭 (AJAX)
# ===================================================================
@financial_bp.route('/financial/api/match-by-approval', methods=['POST'])
@login_required
@menu_required('financial')
def match_by_approval():
    """승인번호로 세금계산서를 찾아서 계약에 강제매칭"""
    data = request.get_json() or {}
    approval_no = (data.get('approval_no') or '').strip()
    contract_id = safe_int(data.get('contract_id'))

    if not approval_no or not contract_id:
        return jsonify({'ok': False, 'error': '승인번호와 계약을 모두 입력해주세요'}), 400

    with get_db() as db:
        inv = db.query(TaxInvoice).filter_by(approval_no=approval_no).first()
        if not inv:
            return jsonify({'ok': False, 'error': f'승인번호 {approval_no}에 해당하는 세금계산서가 없습니다'}), 404

        contract = db.query(Contract).options(joinedload(Contract.project)).get(contract_id)
        if not contract:
            return jsonify({'ok': False, 'error': '계약을 찾을 수 없습니다'}), 404

        # 이미 다른 계약에 매칭된 경우 경고
        if inv.contract_id and inv.contract_id != contract_id:
            old_c = db.query(Contract).get(inv.contract_id)
            old_name = old_c.contract_name[:30] if old_c else '?'
            return jsonify({
                'ok': False,
                'error': f'이미 다른 계약에 매칭되어 있습니다: {old_name}',
                'current_match': old_name,
            }), 409

        msg = _do_match_invoice(db, inv, contract)
        status = contract.payment_status
        log_activity(db, '매출수금', 'match', f'승인번호 매칭 ({approval_no})', ref_type='TaxInvoice', ref_id=inv.id)
        db.commit()

    return jsonify({
        'ok': True,
        'message': f'매칭 완료: {msg} ({approval_no}) — {status}',
    })


# ===================================================================
# 10. 세금계산서 삭제
# ===================================================================
@financial_bp.route('/financial/tax-invoice/<int:invoice_id>/delete', methods=['POST'])
@login_required
@menu_required('financial')
def tax_invoice_delete(invoice_id):
    with get_db() as db:
        inv = db.query(TaxInvoice).get(invoice_id)
        if not inv:
            abort(404)
        contract_id = inv.contract_id
        log_activity(db, '매출수금', 'delete', '세금계산서 삭제', ref_type='TaxInvoice', ref_id=inv.id)
        db.delete(inv)
        db.flush()
        # 연관 계약 수금상태 재계산
        if contract_id:
            contract = db.query(Contract).get(contract_id)
            if contract:
                from modules.services.warranty_auto import recalc_contract_payment_status
                recalc_contract_payment_status(db, contract)
        db.commit()
        flash('삭제되었습니다.', 'info')
    return redirect(url_for('financial.tax_invoice_list'))


# ===================================================================
# 7. API: 계약별 세금계산서 (계약 상세 AJAX)
# ===================================================================
@financial_bp.route('/financial/api/contract/<int:contract_id>/invoices')
@login_required
def api_contract_invoices(contract_id):
    with get_db() as db:
        invoices = db.query(TaxInvoice).filter(
            TaxInvoice.contract_id == contract_id
        ).order_by(desc(TaxInvoice.issue_date)).all()

        return jsonify({
            'invoices': [{
                'id': i.id,
                'issue_date': i.issue_date.isoformat() if i.issue_date else '',
                'total_amount': i.total_amount or 0,
                'supply_amount': i.supply_amount or 0,
                'approval_no': i.approval_no,
            } for i in invoices],
            'summary': {
                'count': len(invoices),
                'total_amount': sum(i.total_amount or 0 for i in invoices),
            }
        })
