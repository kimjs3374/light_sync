import datetime
from collections import defaultdict
from flask import Blueprint, render_template, request, session, abort
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.models import (
    Project, Contract, ContractItem, Material, MaterialOrder,
    ProductionProcess, Delivery, DeliverySplit,
    WarrantyCase, PurchaseOrder, Receiving, Vendor,
)
from modules.services.g2b_catalog_sync import get_catalog_price_map, match_from_price_map

report_bp = Blueprint('report', __name__)

# 부서 그룹 매핑
DEPT_MAP = {
    '영업부': 'sales',
    '생산부': 'production',
    '관리부': 'management',
    '경영관리부': 'management',
}

DEPT_LABELS = {
    'sales': '영업부',
    'production': '생산부',
    'management': '관리부',
}


def _resolve_dept():
    """부서 판별 + 접근 제어. (dept_key, error_code) 반환."""
    is_admin = session.get('role') == 'admin'
    requested = request.args.get('dept', '').strip()

    if requested:
        # dept 파라미터 직접 지정
        dept_key = DEPT_MAP.get(requested) or (requested if requested in DEPT_LABELS else None)
        if not dept_key:
            return None, 404
        if not is_admin:
            # 비admin은 자기 부서만
            user_dept = DEPT_MAP.get(session.get('user_group', ''))
            if dept_key != user_dept:
                return None, 403
        return dept_key, None

    # dept 파라미터 없음 → user_group 기준
    if is_admin:
        return 'sales', None  # admin 기본: 영업부
    user_group = session.get('user_group', '')
    dept_key = DEPT_MAP.get(user_group)
    if not dept_key:
        return None, 403
    return dept_key, None


def _parse_week_range():
    """이번 주 월~금 기본값 + 사용자 지정 날짜 파싱."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end = week_start + datetime.timedelta(days=4)

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if start_str:
        try:
            week_start = datetime.date.fromisoformat(start_str)
        except ValueError:
            pass
    if end_str:
        try:
            week_end = datetime.date.fromisoformat(end_str)
        except ValueError:
            pass
    return today, week_start, week_end


@report_bp.route('/report/weekly')
@login_required
def weekly_report():
    """부서별 주간보고서 - 부서 자동 판별 후 분기."""
    dept_key, err = _resolve_dept()
    if err:
        abort(err)

    if dept_key == 'sales':
        return _weekly_sales()
    elif dept_key == 'production':
        return _weekly_production()
    elif dept_key == 'management':
        return _weekly_management()
    else:
        abort(403)


# ──────────────────────────────────────────────
# 영업부 보고서 (기존 로직 그대로)
# ──────────────────────────────────────────────
def _weekly_sales():
    """영업부 설계 업무보고서 생성"""
    today, week_start, week_end = _parse_week_range()

    with get_db() as db:
        # 1. 진행중인 설계관리 프로젝트 (미계약)
        active_projects = db.query(Project).filter(
            Project.is_contracted.is_(False)
        ).options(
            joinedload(Project.materials),
            joinedload(Project.contacts),
        ).order_by(Project.expected_contract_date.asc().nullslast(), Project.id.desc()).all()

        # 2. 해당 기간 내 신규 등록된 프로젝트
        new_projects = db.query(Project).filter(
            Project.created_at >= datetime.datetime.combine(week_start, datetime.time.min),
            Project.created_at <= datetime.datetime.combine(week_end, datetime.time.max),
        ).options(
            joinedload(Project.materials),
        ).order_by(Project.created_at.desc()).all()

        # 3. 해당 기간 내 계약 전환된 프로젝트
        converted_projects = db.query(Project).filter(
            Project.is_contracted.is_(True),
            Project.contract_date >= week_start,
            Project.contract_date <= week_end,
        ).options(
            joinedload(Project.contracts),
        ).order_by(Project.contract_date.desc()).all()

        # 4. 긴급/지연 프로젝트
        urgent_projects = [p for p in active_projects if p.is_urgent]
        overdue_projects = [p for p in active_projects
                           if p.expected_contract_date and p.expected_contract_date < today]

        # 6. 통계
        stats = {
            'total_active': len(active_projects),
            'new_count': len(new_projects),
            'converted_count': len(converted_projects),
            'urgent_count': len(urgent_projects),
            'overdue_count': len(overdue_projects),
        }

        # 카탈로그 가격맵
        price_map = get_catalog_price_map(db)

        # 진행중/신규 프로젝트 예상금액 계산 (설계 단계 materials 기반)
        all_need_estimate = set(p.id for p in active_projects) | set(p.id for p in new_projects)
        for p in active_projects + new_projects:
            if p.id not in all_need_estimate:
                continue
            all_need_estimate.discard(p.id)
            total_amount = 0
            for m in (p.materials or []):
                match = match_from_price_map(price_map, m.model_name)
                qty = 0
                if m.quantity:
                    try:
                        qty = int(m.quantity)
                    except (ValueError, TypeError):
                        pass
                if match['matched'] and match['unit_price'] and qty:
                    total_amount += qty * match['unit_price']
            p._estimated_amount = total_amount if total_amount > 0 else None

        # 계약 전환 프로젝트 계약금액 계산
        for p in converted_projects:
            total_amount = 0
            for c in (p.contracts or []):
                for item in (c.items or []):
                    match = match_from_price_map(price_map, item.model_name)
                    if match['matched'] and match['unit_price']:
                        total_amount += item.quantity * match['unit_price']
            p._estimated_amount = total_amount if total_amount > 0 else None

        # D-Day 계산 helper
        def calc_dday(p):
            if p.expected_contract_date:
                return (p.expected_contract_date - today).days
            return None

    return render_template(
        'report_weekly.html',
        week_start=week_start,
        week_end=week_end,
        today=today,
        active_projects=active_projects,
        new_projects=new_projects,
        converted_projects=converted_projects,
        urgent_projects=urgent_projects,
        overdue_projects=overdue_projects,
        stats=stats,
        calc_dday=calc_dday,
        report_date=today,
        reporter=request.args.get('reporter', ''),
        is_admin=session.get('role') == 'admin',
        current_dept='sales',
    )


# ──────────────────────────────────────────────
# 생산부 보고서
# ──────────────────────────────────────────────
def _weekly_production():
    """생산부 주간보고서"""
    today, week_start, week_end = _parse_week_range()
    start_dt = datetime.datetime.combine(week_start, datetime.time.min)
    end_dt = datetime.datetime.combine(week_end, datetime.time.max)

    with get_db() as db:
        # ── 주간 요약 ──
        # 생산중 품목 수
        producing_count = db.query(func.count(ContractItem.id)).filter(
            ContractItem.status_prod.in_(['생산중', '조립중', '자재입고완료'])
        ).scalar() or 0

        # 납품준비 건수
        delivery_ready_count = db.query(func.count(Delivery.id)).filter(
            Delivery.delivery_status == '납품준비'
        ).scalar() or 0

        # 납품완료 (기간 내)
        delivery_done_count = db.query(func.count(DeliverySplit.id)).filter(
            DeliverySplit.delivered_done_at >= start_dt,
            DeliverySplit.delivered_done_at <= end_dt,
        ).scalar() or 0

        # AS접수 (기간 내)
        as_count = db.query(func.count(WarrantyCase.id)).filter(
            WarrantyCase.reported_date >= week_start,
            WarrantyCase.reported_date <= week_end,
        ).scalar() or 0

        stats = {
            'producing': producing_count,
            'delivery_ready': delivery_ready_count,
            'delivery_done': delivery_done_count,
            'as_received': as_count,
        }

        # ── 생산 공정 현황 (현장별 전체 공정 대비 완료율) ──
        all_processes = db.query(ProductionProcess).all()

        # project 이름 조회
        all_proc_pids = list(set(pp.project_id for pp in all_processes))
        project_map = {}
        if all_proc_pids:
            for p in db.query(Project).filter(Project.id.in_(all_proc_pids)).all():
                project_map[p.id] = p.temp_name or p.short_name or '-'

        # 현장별 집계: 전체 공정 수 / 완료 공정 수
        proc_agg = defaultdict(lambda: {'total': 0, 'done': 0})
        for pp in all_processes:
            proc_agg[pp.project_id]['total'] += 1
            if pp.status in ('완료', '스킵'):
                proc_agg[pp.project_id]['done'] += 1

        process_rows = []
        for pid, agg in proc_agg.items():
            if agg['total'] == agg['done']:
                continue  # 모든 공정 완료된 현장은 제외
            pct = round(agg['done'] / agg['total'] * 100) if agg['total'] > 0 else 0
            process_rows.append({
                'site_name': project_map.get(pid, '-'),
                'total': agg['total'],
                'done': agg['done'],
                'progress_percent': pct,
            })
        process_rows.sort(key=lambda r: r['progress_percent'], reverse=True)

        # ── 납품 진행 현황 ──
        deliveries = db.query(Delivery).filter(
            Delivery.delivery_status != '납품완료'
        ).options(
            joinedload(Delivery.splits),
        ).order_by(Delivery.project_id).all()

        dlv_project_ids = list(set(d.project_id for d in deliveries))
        dlv_project_map = {}
        if dlv_project_ids:
            for p in db.query(Project).filter(Project.id.in_(dlv_project_ids)).all():
                dlv_project_map[p.id] = p.temp_name or p.short_name or '-'

        delivery_rows = []
        for d in deliveries:
            site = dlv_project_map.get(d.project_id, '-')
            for s in (d.splits or []):
                if s.status == '완료':
                    continue
                delivery_rows.append({
                    'site_name': site,
                    'split_no': s.split_no,
                    'quantity': s.quantity,
                    'scheduled_date': s.scheduled_date,
                    'status': s.status,
                })
        delivery_rows.sort(key=lambda r: r['scheduled_date'] or datetime.date.max)

        # ── AS/하자보증 현황 ──
        warranty_cases = db.query(WarrantyCase).filter(
            WarrantyCase.status != '완료'
        ).order_by(WarrantyCase.reported_date.desc().nullslast()).all()

        wc_project_ids = list(set(wc.project_id for wc in warranty_cases if wc.project_id))
        wc_project_map = {}
        if wc_project_ids:
            for p in db.query(Project).filter(Project.id.in_(wc_project_ids)).all():
                wc_project_map[p.id] = p.temp_name or p.short_name or '-'

        warranty_rows = []
        for wc in warranty_cases:
            site = wc_project_map.get(wc.project_id, wc.manual_site_name or '-')
            warranty_rows.append({
                'case_no': wc.case_no,
                'site_name': site,
                'defect_type': wc.defect_type,
                'status': wc.status,
                'reported_date': wc.reported_date,
            })

    return render_template(
        'report_weekly_production.html',
        week_start=week_start,
        week_end=week_end,
        today=today,
        stats=stats,
        process_rows=process_rows,
        delivery_rows=delivery_rows,
        warranty_rows=warranty_rows,
        reporter=request.args.get('reporter', ''),
        is_admin=session.get('role') == 'admin',
        current_dept='production',
    )


# ──────────────────────────────────────────────
# 관리부 보고서
# ──────────────────────────────────────────────
def _weekly_management():
    """관리부 주간보고서"""
    today, week_start, week_end = _parse_week_range()

    with get_db() as db:
        # ── 주간 요약 ──
        # 발주건수 (기간 내)
        order_count = db.query(func.count(MaterialOrder.id)).filter(
            MaterialOrder.order_date >= week_start,
            MaterialOrder.order_date <= week_end,
        ).scalar() or 0

        # 입고건수 (기간 내)
        receiving_count = db.query(func.count(Receiving.id)).filter(
            Receiving.rcv_date >= week_start,
            Receiving.rcv_date <= week_end,
        ).scalar() or 0

        # 검수대기 건수
        inspect_pending = db.query(func.count(Receiving.id)).filter(
            Receiving.status == '검수대기'
        ).scalar() or 0

        # 발주총액 (기간 내 PO)
        po_total = db.query(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).filter(
            PurchaseOrder.po_date >= week_start,
            PurchaseOrder.po_date <= week_end,
            PurchaseOrder.status != '취소',
        ).scalar() or 0

        stats = {
            'order_count': order_count,
            'receiving_count': receiving_count,
            'inspect_pending': inspect_pending,
            'po_total': int(po_total),
        }

        # ── 자재 발주 현황 (현장별 전체 품목 대비 발주율) ──
        all_mat_orders = db.query(MaterialOrder).all()

        mo_project_ids = list(set(mo.project_id for mo in all_mat_orders))
        mo_project_map = {}
        if mo_project_ids:
            for p in db.query(Project).filter(Project.id.in_(mo_project_ids)).all():
                mo_project_map[p.id] = p.temp_name or p.short_name or '-'

        mat_agg = defaultdict(lambda: {'total': 0, 'ordered': 0})
        for mo in all_mat_orders:
            mat_agg[mo.project_id]['total'] += 1
            if mo.order_status in ('발주완료', '입고완료'):
                mat_agg[mo.project_id]['ordered'] += 1

        material_rows = []
        for pid, agg in mat_agg.items():
            if agg['total'] == agg['ordered']:
                continue  # 전부 발주 완료된 현장 제외
            pct = round(agg['ordered'] / agg['total'] * 100) if agg['total'] > 0 else 0
            material_rows.append({
                'site_name': mo_project_map.get(pid, '-'),
                'total': agg['total'],
                'ordered': agg['ordered'],
                'order_percent': pct,
            })
        material_rows.sort(key=lambda r: r['order_percent'])

        # ── 발주서 현황 ──
        purchase_orders = db.query(PurchaseOrder).filter(
            PurchaseOrder.status != '취소',
            PurchaseOrder.po_date >= week_start,
            PurchaseOrder.po_date <= week_end,
        ).options(
            joinedload(PurchaseOrder.vendor),
        ).order_by(PurchaseOrder.po_date.desc()).all()

        po_rows = []
        po_sum = 0
        for po in purchase_orders:
            amt = int(po.total_amount or 0)
            po_sum += amt
            po_rows.append({
                'po_no': po.po_no,
                'vendor_name': po.vendor.name if po.vendor else '-',
                'total_amount': amt,
                'status': po.status,
                'email_sent': '발송' if po.email_sent_at else '미발송',
                'po_date': po.po_date,
            })

        # ── 입고 검수 현황 ──
        receivings = db.query(Receiving).filter(
            Receiving.rcv_date >= week_start,
            Receiving.rcv_date <= week_end,
        ).options(
            joinedload(Receiving.vendor),
            joinedload(Receiving.items),
        ).order_by(Receiving.rcv_date.desc()).all()

        receiving_rows = []
        for r in receivings:
            # 첫 번째 품목명 표시
            first_item = r.items[0] if r.items else None
            item_count = len(r.items) if r.items else 0
            item_label = (first_item.item_name if first_item else '-')
            if item_count > 1:
                item_label += f' 외 {item_count - 1}건'
            total_qty = sum(i.received_qty or 0 for i in (r.items or []))
            receiving_rows.append({
                'rcv_no': r.rcv_no,
                'vendor_name': r.vendor.name if r.vendor else '-',
                'item_label': item_label,
                'total_qty': int(total_qty),
                'status': r.status,
                'rcv_date': r.rcv_date,
            })

    return render_template(
        'report_weekly_management.html',
        week_start=week_start,
        week_end=week_end,
        today=today,
        stats=stats,
        material_rows=material_rows,
        po_rows=po_rows,
        po_sum=po_sum,
        receiving_rows=receiving_rows,
        reporter=request.args.get('reporter', ''),
        is_admin=session.get('role') == 'admin',
        current_dept='management',
    )
