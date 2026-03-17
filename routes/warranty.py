import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from sqlalchemy.orm import joinedload
from modules.auth_decorators import login_required
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.pagination import make_pagination
from modules.models import (
    Project, Contract, Warranty, WarrantyCase, WarrantyCaseLog,
    DEFECT_TYPES, CASE_STATUS_STEPS,
)
from modules.services.warranty_actions import handle_warranty_action

warranty_bp = Blueprint("warranty", __name__)


# -------------------------------------------------------------------
# 1. AS 케이스 목록
# -------------------------------------------------------------------
@warranty_bp.route('/warranty')
@login_required
def warranty_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 20)
    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    defect_filter = request.args.get('defect', '').strip()
    sort = request.args.get('sort', 'created_desc').strip()

    with get_db() as db:
        query = db.query(WarrantyCase).options(
            joinedload(WarrantyCase.warranty),
            joinedload(WarrantyCase.project),
        )

        # 검색
        if q:
            query = query.join(WarrantyCase.project).filter(
                (Project.project_no.ilike(f'%{q}%'))
                | (Project.temp_name.ilike(f'%{q}%'))
                | (WarrantyCase.case_no.ilike(f'%{q}%'))
            )

        # 필터
        if status_filter and status_filter != 'all':
            query = query.filter(WarrantyCase.status == status_filter)
        if defect_filter and defect_filter != 'all':
            query = query.filter(WarrantyCase.defect_type == defect_filter)

        # 정렬
        if sort == 'reported_asc':
            query = query.order_by(WarrantyCase.reported_date.asc())
        elif sort == 'reported_desc':
            query = query.order_by(WarrantyCase.reported_date.desc())
        else:
            query = query.order_by(WarrantyCase.created_at.desc())

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        cases = query.offset((pagination['page'] - 1) * per_page).limit(per_page).all()

        # 통계
        all_cases = db.query(WarrantyCase).all()
        open_count = sum(1 for c in all_cases if c.status not in ('완료', '보류'))
        defect_counts = {}
        for code, label in DEFECT_TYPES:
            defect_counts[code] = sum(1 for c in all_cases if c.defect_type == code)

        stats = {
            'total': len(all_cases),
            'filtered': total,
            'open': open_count,
            'defect_counts': defect_counts,
        }

    return render_template(
        'warranty_list.html',
        cases=cases,
        stats=stats,
        filters={'q': q, 'status': status_filter, 'defect': defect_filter, 'sort': sort},
        pagination=pagination,
        defect_types=DEFECT_TYPES,
        status_steps=CASE_STATUS_STEPS,
    )


# -------------------------------------------------------------------
# 2. AS 케이스 등록 (보증연결 / 수기입력 2가지 모드)
# -------------------------------------------------------------------
def _next_case_no(db):
    """자동 채번: AS-{year}-{seq:03d}"""
    year = datetime.date.today().year
    prefix = f'AS-{year}-'
    last_case = (
        db.query(WarrantyCase)
        .filter(WarrantyCase.case_no.like(f'{prefix}%'))
        .order_by(WarrantyCase.case_no.desc())
        .first()
    )
    if last_case:
        try:
            seq = int(last_case.case_no.replace(prefix, '')) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f'{prefix}{seq:03d}'


@warranty_bp.route('/warranty/create', methods=['GET', 'POST'])
@login_required
def warranty_create():
    with get_db() as db:
        if request.method == 'POST':
            mode = request.form.get('input_mode', 'warranty')  # warranty or manual
            user_name = session.get('full_name', '사용자')
            case_no = _next_case_no(db)

            if mode == 'warranty':
                # 모드1: 보증 연결
                warranty_id = safe_int(request.form.get('warranty_id'))
                warranty = db.query(Warranty).get(warranty_id) if warranty_id else None
                if not warranty:
                    flash('보증 정보를 선택해주세요.', 'danger')
                    return redirect(url_for('warranty.warranty_create'))

                case = WarrantyCase(
                    warranty_id=warranty.id,
                    project_id=warranty.project_id,
                    case_no=case_no,
                    defect_type=request.form.get('defect_type', 'OTHER'),
                    symptom=request.form.get('symptom', '').strip(),
                    status='접수',
                    reported_by=request.form.get('reported_by', '').strip(),
                    reported_date=parse_date(request.form.get('reported_date')) or datetime.date.today(),
                    assigned_to=request.form.get('assigned_to', '').strip(),
                    created_by=user_name,
                )
            else:
                # 모드2: 수기 입력 (보증 없이 접수)
                project_id = safe_int(request.form.get('project_id')) or None
                case = WarrantyCase(
                    warranty_id=None,
                    project_id=project_id,
                    case_no=case_no,
                    defect_type=request.form.get('defect_type', 'OTHER'),
                    symptom=request.form.get('symptom', '').strip(),
                    status='접수',
                    reported_by=request.form.get('reported_by', '').strip(),
                    reported_date=parse_date(request.form.get('reported_date')) or datetime.date.today(),
                    assigned_to=request.form.get('assigned_to', '').strip(),
                    created_by=user_name,
                    manual_site_name=request.form.get('manual_site_name', '').strip(),
                    manual_contract_name=request.form.get('manual_contract_name', '').strip(),
                    manual_model_name=request.form.get('manual_model_name', '').strip(),
                    manual_delivery_date=parse_date(request.form.get('manual_delivery_date')),
                )

            db.add(case)
            db.flush()

            db.add(WarrantyCaseLog(
                case_id=case.id,
                log_type='status_change',
                old_status=None,
                new_status='접수',
                content=f'AS 접수 ({("보증연결" if mode == "warranty" else "수기입력")})',
                created_by=user_name,
            ))
            db.commit()
            flash(f'AS 케이스 {case_no} 가 등록되었습니다.', 'success')
            return redirect(url_for('warranty.warranty_detail', case_id=case.id))

        # GET: 보증 등록된 계약 + 전체 프로젝트 (수기입력용)
        warranties = (
            db.query(Warranty)
            .options(joinedload(Warranty.contract), joinedload(Warranty.project))
            .all()
        )
        projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(True))
            .order_by(Project.id.desc())
            .all()
        )

    return render_template(
        'warranty_create.html',
        warranties=warranties,
        projects=projects,
        defect_types=DEFECT_TYPES,
        today=datetime.date.today().isoformat(),
    )


# -------------------------------------------------------------------
# 3. AS 케이스 상세
# -------------------------------------------------------------------
@warranty_bp.route('/warranty/<int:case_id>', methods=['GET', 'POST'])
@login_required
def warranty_detail(case_id):
    with get_db() as db:
        case = (
            db.query(WarrantyCase)
            .options(
                joinedload(WarrantyCase.warranty).joinedload(Warranty.contract),
                joinedload(WarrantyCase.project),
                joinedload(WarrantyCase.logs),
            )
            .get(case_id)
        )
        if not case:
            flash('AS 케이스를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('warranty.warranty_list'))

        if request.method == 'POST':
            action = request.form.get('action', '')
            session_data = {
                'full_name': session.get('full_name', '사용자'),
            }
            handle_warranty_action(db, case, action, request.form, session_data)
            db.commit()
            flash('처리되었습니다.', 'success')
            return redirect(url_for('warranty.warranty_detail', case_id=case_id))

        logs = sorted(case.logs, key=lambda l: l.created_at, reverse=True)

    return render_template(
        'warranty_detail.html',
        case=case,
        logs=logs,
        defect_types=DEFECT_TYPES,
        status_steps=CASE_STATUS_STEPS,
    )


# -------------------------------------------------------------------
# 4. 보증 등록/수정
# -------------------------------------------------------------------
@warranty_bp.route('/warranty/register/<int:contract_id>', methods=['GET', 'POST'])
@login_required
def warranty_register(contract_id):
    with get_db() as db:
        contract = (
            db.query(Contract)
            .options(joinedload(Contract.project))
            .get(contract_id)
        )
        if not contract:
            flash('계약 정보를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('warranty.warranty_list'))

        warranty = db.query(Warranty).filter_by(contract_id=contract_id).first()

        if request.method == 'POST':
            if not warranty:
                warranty = Warranty(
                    contract_id=contract_id,
                    project_id=contract.project_id,
                )
                db.add(warranty)

            warranty.warranty_start = parse_date(request.form.get('warranty_start'))
            warranty.warranty_end = parse_date(request.form.get('warranty_end'))
            warranty.warranty_amount = safe_int(request.form.get('warranty_amount'))
            warranty.insurance_no = request.form.get('insurance_no', '').strip()
            warranty.insurance_returned = request.form.get('insurance_returned') in ('on', '1')
            warranty.note = request.form.get('note', '').strip()
            db.commit()
            flash('보증 정보가 저장되었습니다.', 'success')
            return redirect(url_for('warranty.warranty_register', contract_id=contract_id))

    return render_template(
        'warranty_register.html',
        contract=contract,
        warranty=warranty,
    )
