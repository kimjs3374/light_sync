import datetime

from flask import Blueprint, render_template, request, session, jsonify, flash, redirect, url_for
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required, menu_required
from modules.db_context import get_db
from modules.models import (
    DailyReport, User, Contract, ContractItem,
    Delivery, Drawing, ProductionProcess, ProductionDailyLog,
    WarrantyCase, PurchaseOrder, Receiving, ProcessingOrder,
    TaxInvoice, PaymentRecord,
)

daily_report_bp = Blueprint('daily_report', __name__)

WEEKDAY_KR = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']


def _site_name(project):
    """프로젝트 → 현장명. 없으면 None."""
    if not project:
        return None
    return project.temp_name or None


def _collect_sales_items(db, target_date, day_start, day_end):
    """영업부: 계약 등록 / 납품 / 도면 / 세금계산서 발행"""
    items = []

    # 계약 등록 (contract_date 기준)
    for c in db.query(Contract).filter(
        Contract.contract_date == target_date,
    ).options(joinedload(Contract.project)).all():
        site = _site_name(c.project)
        if not site:
            continue
        cname = c.contract_name or ''
        if cname and site not in cname:
            items.append(f"{site} {cname} 계약 등록")
        else:
            items.append(f"{cname or site} 계약 등록")

    # 납품 (created_at 기준, 현장 있는 것만)
    deliv_by_site = {}
    for d in db.query(Delivery).filter(
        Delivery.created_at >= day_start, Delivery.created_at <= day_end,
    ).options(joinedload(Delivery.project)).all():
        site = _site_name(d.project)
        if not site:
            continue
        deliv_by_site.setdefault(site, set()).add(d.delivery_status or '등록')
    for site, statuses in deliv_by_site.items():
        items.append(f"{site} 납품 {'/'.join(sorted(statuses))}")

    # 도면 등록/수정 (현장별 합산)
    drawing_by_site = {}
    for dw in db.query(Drawing).filter(
        ((Drawing.created_at >= day_start) & (Drawing.created_at <= day_end))
        | ((Drawing.updated_at >= day_start) & (Drawing.updated_at <= day_end)),
    ).options(joinedload(Drawing.project)).all():
        site = _site_name(dw.project)
        if not site:
            continue
        is_new = dw.created_at and day_start <= dw.created_at <= day_end
        drawing_by_site.setdefault(site, []).append(('등록' if is_new else '수정', dw.title))
    for site, dws in drawing_by_site.items():
        if len(dws) == 1:
            action, title = dws[0]
            items.append(f"{site} {title} 도면 {action}")
        else:
            actions = sorted({a for a, _ in dws})
            items.append(f"{site} 도면 {'/'.join(actions)} {len(dws)}건")

    # 세금계산서 발행 (issue_date 기준)
    tax_by_site = {}
    for ti in db.query(TaxInvoice).filter(
        TaxInvoice.issue_date == target_date,
    ).options(joinedload(TaxInvoice.project)).all():
        site = _site_name(ti.project) or ti.g2b_contract_name or '(현장미상)'
        tax_by_site.setdefault(site, []).append(int(ti.total_amount or 0))
    for site, amounts in tax_by_site.items():
        total = sum(amounts)
        cnt = len(amounts)
        amt_str = f" ({total:,}원)" if total else ''
        suffix = f" {cnt}건" if cnt > 1 else ''
        items.append(f"{site} 세금계산서 발행{suffix}{amt_str}")

    return items


def _collect_admin_items(db, target_date, day_start, day_end):
    """경영관리부: 발주서 / 입고 / 입금확인"""
    items = []

    # 발주서 (현장별 그룹핑, 3건 이상 압축)
    po_by_site = {}
    for po in db.query(PurchaseOrder).filter(
        PurchaseOrder.created_at >= day_start, PurchaseOrder.created_at <= day_end,
    ).options(joinedload(PurchaseOrder.project), joinedload(PurchaseOrder.vendor)).all():
        site = _site_name(po.project) or '(현장미지정)'
        po_by_site.setdefault(site, []).append(po)
    for site, pos in po_by_site.items():
        if len(pos) <= 2:
            for po in pos:
                vendor_name = po.vendor.name if po.vendor else '(거래처미상)'
                items.append(f"{site} 발주 ({vendor_name})")
        else:
            vendors = sorted({po.vendor.name for po in pos if po.vendor})
            vendor_str = (
                f" ({vendors[0]} 외 {len(vendors)-1})" if len(vendors) > 1
                else f" ({vendors[0]})" if vendors else ''
            )
            items.append(f"{site} 발주 {len(pos)}건{vendor_str}")

    # 입고 (현장별 그룹핑, 거래처 위주)
    rcv_by_site = {}
    for rcv in db.query(Receiving).filter(
        Receiving.created_at >= day_start, Receiving.created_at <= day_end,
    ).options(
        joinedload(Receiving.vendor),
        joinedload(Receiving.purchase_order).joinedload(PurchaseOrder.project),
    ).all():
        site = None
        if rcv.purchase_order and rcv.purchase_order.project:
            site = _site_name(rcv.purchase_order.project)
        site = site or '(직접입고)'
        rcv_by_site.setdefault(site, []).append(rcv)
    for site, rcvs in rcv_by_site.items():
        vendors = sorted({r.vendor.name for r in rcvs if r.vendor})
        if site == '(직접입고)':
            vendor_str = ', '.join(vendors) if vendors else '거래처미상'
            items.append(f"자재 수령 ({vendor_str})")
        else:
            vendor_str = (
                f" ({vendors[0]} 외 {len(vendors)-1})" if len(vendors) > 1
                else f" ({vendors[0]})" if vendors else ''
            )
            cnt_str = f" {len(rcvs)}건" if len(rcvs) > 1 else ''
            items.append(f"{site} 입고{cnt_str}{vendor_str}")

    # 입금 확인 (payment_date 기준)
    pay_by_site = {}
    for pr in db.query(PaymentRecord).filter(
        PaymentRecord.payment_date == target_date,
    ).options(
        joinedload(PaymentRecord.tax_invoice).joinedload(TaxInvoice.project),
    ).all():
        ti = pr.tax_invoice
        if not ti:
            continue
        site = _site_name(ti.project) or ti.g2b_contract_name or '(현장미상)'
        pay_by_site.setdefault(site, []).append(int(pr.amount or 0))
    for site, amounts in pay_by_site.items():
        total = sum(amounts)
        amt_str = f" ({total:,}원)" if total else ''
        items.append(f"{site} 입금 확인{amt_str}")

    return items


def _collect_production_items(db, target_date, day_start, day_end):
    """생산부: 생산 실적 / 가공발주 / 하자·AS"""
    items = []

    # 생산 실적 (현장+공정별 합산)
    prod_summary = {}
    for log in db.query(ProductionDailyLog).filter(
        ProductionDailyLog.work_date == target_date,
    ).options(
        joinedload(ProductionDailyLog.production_process)
        .joinedload(ProductionProcess.contract_item)
        .joinedload(ContractItem.contract)
        .joinedload(Contract.project)
    ).all():
        try:
            site = _site_name(log.production_process.contract_item.contract.project)
        except AttributeError:
            site = None
        if not site:
            continue
        pname = log.production_process.process_name if log.production_process else '생산'
        key = (site, pname)
        prod_summary.setdefault(key, 0)
        prod_summary[key] += int(log.daily_qty or 0)
    for (site, pname), qty in prod_summary.items():
        if qty:
            items.append(f"{site} {pname} {qty}개")
        else:
            items.append(f"{site} {pname}")

    # 가공발주 (외주)
    fo_by_site = {}
    for fo in db.query(ProcessingOrder).filter(
        ProcessingOrder.fo_date == target_date,
    ).options(joinedload(ProcessingOrder.project), joinedload(ProcessingOrder.vendor)).all():
        site = _site_name(fo.project) or '(현장미지정)'
        fo_by_site.setdefault(site, []).append(fo)
    for site, fos in fo_by_site.items():
        vendors = sorted({f.vendor.name for f in fos if f.vendor})
        vendor_str = (
            f" ({vendors[0]} 외 {len(vendors)-1})" if len(vendors) > 1
            else f" ({vendors[0]})" if vendors else ''
        )
        cnt_str = f" {len(fos)}건" if len(fos) > 1 else ''
        items.append(f"{site} 가공발주{cnt_str}{vendor_str}")

    # 하자/AS 접수 (현장별 그룹핑)
    case_by_site = {}
    for c in db.query(WarrantyCase).filter(
        WarrantyCase.created_at >= day_start, WarrantyCase.created_at <= day_end,
    ).options(joinedload(WarrantyCase.warranty)).all():
        w = c.warranty
        site = None
        if w:
            site = _site_name(getattr(w, 'project', None)) or w.contract_name
        site = site or '(현장미상)'
        case_by_site.setdefault(site, []).append(c.defect_type or '기타')
    for site, defects in case_by_site.items():
        if len(defects) == 1:
            items.append(f"{site} 하자/AS 접수 ({defects[0]})")
        else:
            items.append(f"{site} 하자/AS 접수 {len(defects)}건")

    return items


def _collect_auto_items(db, target_date):
    """ERP 데이터에서 당일 활동을 부서별로 자동 수집"""
    day_start = datetime.datetime.combine(target_date, datetime.time.min)
    day_end = datetime.datetime.combine(target_date, datetime.time.max)

    dept_items = {}
    sales = _collect_sales_items(db, target_date, day_start, day_end)
    if sales:
        dept_items['영업부'] = sales
    admin = _collect_admin_items(db, target_date, day_start, day_end)
    if admin:
        dept_items['경영관리부'] = admin
    prod = _collect_production_items(db, target_date, day_start, day_end)
    if prod:
        dept_items['생산부'] = prod

    return dept_items


@daily_report_bp.route('/daily-report')
@login_required
def daily_report_view():
    """일일업무보고 - 자동수집 + 수동추가"""
    target_date_str = request.args.get('date')
    if target_date_str:
        try:
            target_date = datetime.date.fromisoformat(target_date_str)
        except ValueError:
            target_date = datetime.date.today()
    else:
        target_date = datetime.date.today()

    user_group = session.get('user_group', '')

    with get_db() as db:
        auto_items = _collect_auto_items(db, target_date)

        saved_reports = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
        ).order_by(DailyReport.department).all()

        saved_map = {}
        for r in saved_reports:
            saved_map[r.department] = {
                'id': r.id,
                'reporter_name': r.reporter_name,
                'headcount_total': r.headcount_total,
                'headcount_present': r.headcount_present,
                'headcount_absence_info': r.headcount_absence_info or '',
                'manual_items': r.items,
                'auto_items': r.auto_items,  # None이면 실시간, 리스트면 수정된 버전
            }

        all_depts = sorted(set(list(auto_items.keys()) + list(saved_map.keys())))

        # 부서별 인원 수 (한번에 조회)
        from sqlalchemy import func
        dept_headcounts = dict(
            db.query(User.user_group, func.count(User.id))
            .filter(User.is_active.is_(True), User.is_approved.is_(True))
            .group_by(User.user_group).all()
        )

        dept_reports = []
        for dept in all_depts:
            live_auto = auto_items.get(dept, [])
            saved = saved_map.get(dept, {})
            hc = dept_headcounts.get(dept, 0)
            # 저장된 auto_items가 있으면 그걸 사용 (수정된 버전), 없으면 실시간 수집
            saved_auto = saved.get('auto_items')
            auto = saved_auto if saved_auto is not None else live_auto
            dept_reports.append({
                'department': dept,
                'auto_items': auto,
                'live_auto_items': live_auto,  # 실시간 수집 원본 (새로고침용)
                'manual_items': saved.get('manual_items', []),
                'headcount_total': saved.get('headcount_total', hc),
                'headcount_present': saved.get('headcount_present', hc),
                'headcount_absence_info': saved.get('headcount_absence_info', ''),
                'is_my_dept': dept == user_group,
                'is_saved': dept in saved_map,
                'auto_modified': saved_auto is not None,
            })

        if user_group and not any(d['department'] == user_group for d in dept_reports):
            hc = dept_headcounts.get(user_group, 0)
            dept_reports.insert(0, {
                'department': user_group,
                'auto_items': [],
                'manual_items': [],
                'headcount_total': hc,
                'headcount_present': hc,
                'headcount_absence_info': '',
                'is_my_dept': True,
                'is_saved': False,
            })

    prev_date = (target_date - datetime.timedelta(days=1)).isoformat()
    next_date = (target_date + datetime.timedelta(days=1)).isoformat()

    return render_template(
        'daily_report.html',
        target_date=target_date,
        weekday_kr=WEEKDAY_KR[target_date.weekday()],
        user_group=user_group,
        user_name=session.get('full_name', ''),
        dept_reports=dept_reports,
        prev_date=prev_date,
        next_date=next_date,
    )


@daily_report_bp.route('/daily-report/save', methods=['POST'])
@login_required
@menu_required('daily_report')
def daily_report_save():
    """수동 추가 항목 + 기본사항 저장"""
    target_date_str = request.form.get('report_date', '')
    department = request.form.get('department', session.get('user_group', ''))
    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except ValueError:
        target_date = datetime.date.today()

    user_id = session.get('user_id')
    user_name = session.get('full_name', '')

    try:
        headcount_total = int(request.form.get('headcount_total', 0) or 0)
        headcount_present = int(request.form.get('headcount_present', 0) or 0)
    except (ValueError, TypeError):
        headcount_total = 0
        headcount_present = 0
    headcount_absence_info = request.form.get('headcount_absence_info', '').strip()

    # 본인 부서만 수정 가능
    user_group = session.get('user_group', '')
    if department != user_group:
        flash('본인 부서만 수정할 수 있습니다.', 'danger')
        return redirect(url_for('daily_report.daily_report_view', date=target_date_str))

    manual_raw = request.form.get('manual_items', '').strip()
    manual_items = [line.strip() for line in manual_raw.splitlines() if line.strip()]

    auto_raw = request.form.get('auto_items', '').strip()
    auto_items_edited = [line.strip() for line in auto_raw.splitlines() if line.strip()] if auto_raw else None

    with get_db() as db:
        existing = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
            DailyReport.department == department,
        ).first()

        if existing:
            existing.reporter_name = user_name
            existing.reporter_id = user_id
            existing.headcount_total = headcount_total
            existing.headcount_present = headcount_present
            existing.headcount_absence_info = headcount_absence_info
            existing.items = manual_items
            if auto_items_edited is not None:
                existing.auto_items = auto_items_edited
        else:
            report = DailyReport(
                report_date=target_date,
                department=department,
                reporter_name=user_name,
                reporter_id=user_id,
                headcount_total=headcount_total,
                headcount_present=headcount_present,
                headcount_absence_info=headcount_absence_info,
            )
            report.items = manual_items
            if auto_items_edited is not None:
                report.auto_items = auto_items_edited
            db.add(report)

        db.commit()

    flash(f'{department} 업무보고가 저장되었습니다.', 'success')
    return redirect(url_for('daily_report.daily_report_view', date=target_date_str))


@daily_report_bp.route('/daily-report/generate-text')
@login_required
def generate_kakao_text():
    """단일 부서 카카오톡 포맷"""
    target_date_str = request.args.get('date')
    department = request.args.get('department', session.get('user_group', ''))
    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except (ValueError, TypeError):
        target_date = datetime.date.today()

    with get_db() as db:
        auto = _collect_auto_items(db, target_date).get(department, [])
        saved = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
            DailyReport.department == department,
        ).first()
        manual = saved.items if saved else []
        hc_total = saved.headcount_total if saved else 0
        hc_present = saved.headcount_present if saved else 0
        absence = saved.headcount_absence_info if saved else ''

    all_items = auto + manual
    if not all_items:
        return jsonify({'ok': False, 'error': '해당 부서의 업무 내역이 없습니다.'}), 404

    text = _format_kakao_text(department, target_date, hc_total, hc_present, absence, all_items)
    return jsonify({'ok': True, 'text': text})


@daily_report_bp.route('/daily-report/generate-all-text')
@login_required
def generate_all_kakao_text():
    """전체 부서 카카오톡 포맷"""
    target_date_str = request.args.get('date')
    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except (ValueError, TypeError):
        target_date = datetime.date.today()

    with get_db() as db:
        auto_items = _collect_auto_items(db, target_date)
        saved_reports = db.query(DailyReport).filter(
            DailyReport.report_date == target_date,
        ).order_by(DailyReport.department).all()
        saved_map = {r.department: r for r in saved_reports}

        all_depts = sorted(set(list(auto_items.keys()) + list(saved_map.keys())))
        texts = []
        for dept in all_depts:
            auto = auto_items.get(dept, [])
            saved = saved_map.get(dept)
            manual = saved.items if saved else []
            all_items = auto + manual
            if not all_items:
                continue
            hc_total = saved.headcount_total if saved else 0
            hc_present = saved.headcount_present if saved else 0
            absence = saved.headcount_absence_info if saved else ''
            texts.append(_format_kakao_text(dept, target_date, hc_total, hc_present, absence, all_items))

    if not texts:
        return jsonify({'ok': False, 'error': '해당 날짜의 보고가 없습니다.'}), 404
    return jsonify({'ok': True, 'text': '\n\n'.join(texts)})


def _format_kakao_text(department, target_date, hc_total, hc_present, absence_info, items):
    """카카오톡 업무보고 포맷"""
    weekday = WEEKDAY_KR[target_date.weekday()]
    date_str = target_date.strftime('%Y. %m. %d.')
    lines = [
        f"{date_str} {weekday}",
        f"{department} 업무보고",
        "",
        "- 기본사항",
        f"인원 {hc_total}명중 재실 {hc_present}명{' ' + absence_info if absence_info else ''}",
        "",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item}")
    lines.append("")
    lines.append("이상입니다.")
    return '\n'.join(lines)
