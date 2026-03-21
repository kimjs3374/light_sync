"""
매출관리 Blueprint — 세금계산서 기준 + G2B 매칭 보강.

주 데이터: tax_invoices (국세청 엑셀 임포트)
보강: g2b_procurements 매칭으로 계약명/수요기관 등 연결
"""

import datetime
import logging

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort,
)
from sqlalchemy import desc, func, extract
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

logger = logging.getLogger(__name__)

financial_bp = Blueprint('financial', __name__)


def _fmt_money(val):
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


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

        # G2B 매칭된 정상 세금계산서만
        matched_filter = TaxInvoice.match_status.in_(['자동매칭', '수동매칭'])
        normal_filter = TaxInvoice.invoice_type == '세금계산서'

        # KPI (G2B 매칭된 것만)
        monthly_supply = db.query(
            func.coalesce(func.sum(TaxInvoice.supply_amount), 0)
        ).filter(normal_filter, matched_filter,
                 TaxInvoice.issue_date >= current_month_start,
                 TaxInvoice.issue_date < next_month).scalar() or 0

        total_supply = db.query(
            func.coalesce(func.sum(TaxInvoice.supply_amount), 0)
        ).filter(normal_filter, matched_filter).scalar() or 0

        total_cnt = db.query(func.count(TaxInvoice.id)).filter(
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
                func.coalesce(func.sum(TaxInvoice.supply_amount), 0)
            ).filter(normal_filter, matched_filter,
                     TaxInvoice.issue_date >= m,
                     TaxInvoice.issue_date < m_end).scalar() or 0
            monthly_labels.append(f"{m.month}월")
            monthly_amounts.append(int(amt))

        # Chart 2: 월별 발행 건수 (G2B 매칭분만)
        count_labels = []
        count_values = []
        for m in months:
            m_end = (m + datetime.timedelta(days=32)).replace(day=1)
            cnt = db.query(func.count(TaxInvoice.id)).filter(
                normal_filter, matched_filter,
                TaxInvoice.issue_date >= m,
                TaxInvoice.issue_date < m_end).scalar() or 0
            count_labels.append(f"{m.month}월")
            count_values.append(cnt)

        # Chart 3: 수요기관별 매출 TOP 10 (G2B 매칭분, buyer_name = 수요기관)
        top_buyers = db.query(
            TaxInvoice.buyer_name,
            func.sum(TaxInvoice.supply_amount).label('total')
        ).filter(normal_filter, matched_filter,
                 TaxInvoice.buyer_name.isnot(None)
        ).group_by(TaxInvoice.buyer_name).order_by(
            func.sum(TaxInvoice.supply_amount).desc()
        ).limit(10).all()

        buyer_labels = [r[0] or '(미상)' for r in top_buyers]
        buyer_amounts = [int(r[1] or 0) for r in top_buyers]

        # ===== 년도별 계약 대비 매출 + 이월 =====
        # 매칭된 세금계산서 G2B 번호 set
        invoiced_nos = set(
            r[0] for r in db.query(TaxInvoice.g2b_contract_no).filter(
                normal_filter, matched_filter,
                TaxInvoice.g2b_contract_no.isnot(None),
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
        per_page = 30

        # G2B 매칭된 세금계산서만 표시
        q = db.query(TaxInvoice).options(
            joinedload(TaxInvoice.contract),
            joinedload(TaxInvoice.project),
        ).filter(
            TaxInvoice.match_status.in_(['자동매칭', '수동매칭'])
        )

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
            q = q.filter(
                (TaxInvoice.buyer_name.ilike(f'%{search}%')) |
                (TaxInvoice.approval_no.ilike(f'%{search}%')) |
                (TaxInvoice.item_name.ilike(f'%{search}%'))
            )

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

        # 합계 (G2B 매칭된 정상 세금계산서만)
        sum_supply = db.query(func.coalesce(func.sum(TaxInvoice.supply_amount), 0)).filter(
            TaxInvoice.invoice_type == '세금계산서',
            TaxInvoice.match_status.in_(['자동매칭', '수동매칭']),
        ).scalar() or 0

        return render_template('tax_invoice_list.html',
            invoices=invoices,
            g2b_map=g2b_map,
            pagination=pagination,
            match_status_list=MATCH_STATUS_CHOICES,
            sum_supply=sum_supply,
            fmt_money=_fmt_money,
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
        records = parse_tax_invoice_excel(file_stream=file)
        if not records:
            flash('데이터를 읽을 수 없습니다. 국세청 양식인지 확인해주세요.', 'warning')
            return redirect(url_for('financial.tax_invoice_list'))

        with get_db() as db:
            result = import_and_match(db, records)
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

        # G2B 보강: 같은 계약번호의 전체 품목
        g2b_procs = []
        g2b_total_amt = 0
        g2b_total_qty = 0
        if inv.g2b_contract_no:
            g2b_procs = db.query(G2bProcurement).filter(
                G2bProcurement.cntrct_dlvr_req_no == inv.g2b_contract_no
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
                contract.payment_status = '입금완료'
                contract.invoice_date = inv.issue_date
                contract.payment_date = inv.issue_date
                # 하자보증 자동 생성
                auto_create_warranty(db, contract.id, inv.issue_date)
                db.commit()
                flash('계약 매칭 완료.', 'success')
            else:
                flash('계약을 찾을 수 없습니다.', 'danger')
        else:
            flash('계약을 선택해주세요.', 'warning')

    return redirect(url_for('financial.tax_invoice_detail', invoice_id=invoice_id))


# ===================================================================
# 6. 세금계산서 삭제
# ===================================================================
@financial_bp.route('/financial/tax-invoice/<int:invoice_id>/delete', methods=['POST'])
@login_required
@menu_required('financial')
def tax_invoice_delete(invoice_id):
    with get_db() as db:
        inv = db.query(TaxInvoice).get(invoice_id)
        if not inv:
            abort(404)
        db.delete(inv)
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
