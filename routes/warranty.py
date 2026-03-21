import datetime
import json

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from sqlalchemy import func
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


# ───────────────────────────────────────────────────────────
# 헬퍼: 케이스 번호 자동 채번 AS-{year}-{seq:03d}
# ───────────────────────────────────────────────────────────
def _next_case_no(db):
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


# ===================================================================
# 1. GET /warranty → 대시보드
# ===================================================================
@warranty_bp.route('/warranty')
@login_required
def dashboard():
    with get_db() as db:
        today = datetime.date.today()
        d30 = today + datetime.timedelta(days=30)

        # 보증 통계
        total = db.query(Warranty).count()
        active = db.query(Warranty).filter(Warranty.warranty_end >= today).count()
        expiring = db.query(Warranty).filter(
            Warranty.warranty_end >= today,
            Warranty.warranty_end <= d30,
        ).count()

        # 케이스 통계
        case_total = db.query(WarrantyCase).count()
        case_active = db.query(WarrantyCase).filter(
            WarrantyCase.status.notin_(['완료', '보류'])
        ).count()

        # 만료 임박 보증 (30일 이내, 10건)
        expiring_list = (
            db.query(Warranty)
            .filter(
                Warranty.warranty_end >= today,
                Warranty.warranty_end <= d30,
            )
            .order_by(Warranty.warranty_end.asc())
            .limit(10)
            .all()
        )

        # 진행중 A/S 케이스 (최근 10건)
        active_cases = (
            db.query(WarrantyCase)
            .filter(WarrantyCase.status.notin_(['완료', '보류']))
            .order_by(WarrantyCase.reported_date.desc())
            .limit(10)
            .all()
        )

        # 품목별 불량 통계 (WarrantyCase.item_group 기준)
        defect_stats = (
            db.query(
                WarrantyCase.item_group,
                WarrantyCase.defect_type,
                func.count(WarrantyCase.id),
            )
            .group_by(WarrantyCase.item_group, WarrantyCase.defect_type)
            .all()
        )

        # 만료임박 보증의 케이스 건수 (lazy load 방지)
        exp_ids = [w.id for w in expiring_list]
        exp_case_counts = {}
        if exp_ids:
            for wid, cnt in db.query(WarrantyCase.warranty_id, func.count(WarrantyCase.id)).filter(
                WarrantyCase.warranty_id.in_(exp_ids)
            ).group_by(WarrantyCase.warranty_id).all():
                exp_case_counts[wid] = cnt

        return render_template(
            'warranty.html',
            total=total,
            active=active,
            expiring_count=expiring,
            case_total=case_total,
            case_active=case_active,
            expiring_list=expiring_list,
            active_cases=active_cases,
            defect_stats=defect_stats,
            defect_types=DEFECT_TYPES,
            today=today,
            exp_case_counts=exp_case_counts,
        )


# ===================================================================
# 2. GET /warranty/list → 보증 목록
# ===================================================================
@warranty_bp.route('/warranty/list')
@login_required
def warranty_list():
    with get_db() as db:
        today = datetime.date.today()

        # 필터 파라미터
        status_filter = request.args.get('status', 'all')   # all / active / expired
        type_filter = request.args.get('type', '')           # 일반 / 우수제품 / 혁신제품
        item_filter = request.args.get('item', '')           # 품목유형
        search = request.args.get('q', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 50

        query = db.query(Warranty)

        if status_filter == 'active':
            query = query.filter(Warranty.warranty_end >= today)
        elif status_filter == 'expired':
            query = query.filter(Warranty.warranty_end < today)

        if type_filter:
            query = query.filter(Warranty.warranty_type == type_filter)
        if item_filter:
            query = query.filter(Warranty.item_group == item_filter)
        if search:
            like = f'%{search}%'
            query = query.filter(
                (Warranty.contract_name.ilike(like))
                | (Warranty.model_name.ilike(like))
            )

        total_count = query.count()
        warranties = (
            query.order_by(Warranty.warranty_end.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # 전체 통계
        total_all = db.query(Warranty).count()
        active_all = db.query(Warranty).filter(Warranty.warranty_end >= today).count()
        open_cases = db.query(WarrantyCase).filter(
            WarrantyCase.status.notin_(['완료', '보류'])
        ).count()

        # 하자유형별 건수
        defect_counts = {}
        for code, label in DEFECT_TYPES:
            cnt = db.query(WarrantyCase).filter(WarrantyCase.defect_type == code).count()
            if cnt > 0:
                defect_counts[label] = cnt

        stats = {
            'total': total_all,
            'open': open_cases,
            'filtered': total_count,
            'defect_counts': defect_counts,
        }

        # 품목유형 목록 (필터 드롭다운용)
        item_groups = [
            r[0]
            for r in db.query(Warranty.item_group)
            .distinct()
            .filter(Warranty.item_group.isnot(None))
            .all()
        ]

        # 템플릿 호환 변수
        filters = {
            'q': search,
            'status': status_filter,
            'defect': request.args.get('defect', 'all'),
            'sort': request.args.get('sort', 'created_desc'),
            'type': type_filter,
            'item': item_filter,
        }

        # 비정규화이므로 cases 건수도 미리 가져옴 (lazy load 방지)
        warranty_case_counts = {}
        case_rows = (
            db.query(WarrantyCase.warranty_id, func.count(WarrantyCase.id))
            .group_by(WarrantyCase.warranty_id)
            .all()
        )
        for wid, cnt in case_rows:
            warranty_case_counts[wid] = cnt

        return render_template(
            'warranty_list.html',
            warranties=warranties,
            cases=warranties,
            today=today,
            total_count=total_count,
            page=page,
            per_page=per_page,
            total_all=total_all,
            active_all=active_all,
            stats=stats,
            filters=filters,
            defect_types=DEFECT_TYPES,
            status_filter=status_filter,
            type_filter=type_filter,
            item_filter=item_filter,
            search=search,
            item_groups=sorted(item_groups),
            warranty_case_counts=warranty_case_counts,
        )


# ===================================================================
# 3. GET/POST /warranty/case/create → A/S 접수
# ===================================================================
@warranty_bp.route('/warranty/case/create', methods=['GET', 'POST'])
@login_required
def case_create():
    if request.method == 'POST':
        with get_db() as db:
            mode = request.form.get('input_mode', 'warranty')  # warranty / manual
            user_name = session.get('full_name', '사용자')
            case_no = _next_case_no(db)
            today = datetime.date.today()

            if mode == 'warranty':
                # 보증 연결 모드
                warranty_id = safe_int(request.form.get('warranty_id'))
                warranty = db.query(Warranty).get(warranty_id) if warranty_id else None
                if not warranty:
                    flash('보증 정보를 선택해주세요.', 'danger')
                    return redirect(url_for('warranty.case_create'))

                # 유상/무상 자동판별
                is_chargeable = (
                    warranty.warranty_end < today if warranty.warranty_end else True
                )

                case = WarrantyCase(
                    warranty_id=warranty.id,
                    project_id=warranty.project_id,
                    case_no=case_no,
                    defect_type=request.form.get('defect_type', 'OTHER'),
                    symptom=request.form.get('symptom', '').strip(),
                    status='접수',
                    reported_by=request.form.get('reported_by', '').strip(),
                    reported_date=parse_date(request.form.get('reported_date')) or today,
                    assigned_to=request.form.get('assigned_to', '').strip(),
                    request_channel=request.form.get('request_channel', '').strip() or None,
                    customer_name=request.form.get('customer_name', '').strip() or None,
                    customer_phone=request.form.get('customer_phone', '').strip() or None,
                    is_chargeable=is_chargeable,
                    created_by=user_name,
                    # 비정규화 필드
                    contract_name=warranty.contract_name,
                    item_group=warranty.item_group,
                    model_name=warranty.model_name,
                )
            else:
                # 수기 입력 모드 (보증 없이 접수)
                project_id = safe_int(request.form.get('project_id')) or None
                case = WarrantyCase(
                    warranty_id=None,
                    project_id=project_id,
                    case_no=case_no,
                    defect_type=request.form.get('defect_type', 'OTHER'),
                    symptom=request.form.get('symptom', '').strip(),
                    status='접수',
                    reported_by=request.form.get('reported_by', '').strip(),
                    reported_date=parse_date(request.form.get('reported_date')) or today,
                    assigned_to=request.form.get('assigned_to', '').strip(),
                    request_channel=request.form.get('request_channel', '').strip() or None,
                    customer_name=request.form.get('customer_name', '').strip() or None,
                    customer_phone=request.form.get('customer_phone', '').strip() or None,
                    is_chargeable=True,  # 보증 없으면 기본 유상
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
                content=f'AS 접수 ({"보증연결" if mode == "warranty" else "수기입력"})'
                        + (f' — {"유상" if case.is_chargeable else "무상"}' ),
                created_by=user_name,
            ))
            db.commit()
            flash(f'AS 케이스 {case_no} 가 등록되었습니다.', 'success')
            return redirect(url_for('warranty.case_detail', case_id=case.id))

    # GET
    with get_db() as db:
        defect_types = DEFECT_TYPES

        # warranty_id 가 쿼리스트링으로 전달될 수 있음 (보증 목록에서 바로 접수)
        preselect_warranty_id = request.args.get('warranty_id', type=int)
        preselect = None
        if preselect_warranty_id:
            preselect = db.query(Warranty).get(preselect_warranty_id)

        # 수기입력용 프로젝트 목록
        projects = (
            db.query(Project)
            .filter(Project.is_contracted.is_(True))
            .order_by(Project.id.desc())
            .all()
        )

        preselect_expired = False
        if preselect and preselect.warranty_end:
            preselect_expired = preselect.warranty_end < datetime.date.today()

        return render_template(
            'warranty_case_create.html',
            defect_types=defect_types,
            preselect=preselect,
            preselect_expired=preselect_expired,
            projects=projects,
            today=datetime.date.today().isoformat(),
        )


# ===================================================================
# 4. GET/POST /warranty/case/<id> → A/S 케이스 상세
# ===================================================================
@warranty_bp.route('/warranty/case/<int:case_id>', methods=['GET', 'POST'])
@login_required
def case_detail(case_id):
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
            return redirect(url_for('warranty.dashboard'))

        if request.method == 'POST':
            action = request.form.get('action', '')
            user_name = session.get('full_name', '사용자')
            session_data = {'full_name': user_name}

            if action == 'update_status':
                # 상태 변경 + WarrantyCaseLog 기록
                handle_warranty_action(db, case, action, request.form, session_data)

            elif action == 'update_detail':
                # 처리 내역 업데이트
                handle_warranty_action(db, case, action, request.form, session_data)

            elif action == 'add_note':
                # 메모 추가
                handle_warranty_action(db, case, action, request.form, session_data)

            elif action == 'update_parts':
                # 부품 정보 업데이트
                parts_data = request.form.get('parts_json', '[]').strip()
                try:
                    parts = json.loads(parts_data)
                except (json.JSONDecodeError, TypeError):
                    parts = []
                case.parts_json = json.dumps(parts, ensure_ascii=False)
                case.replaced_parts = ', '.join(
                    p.get('name', '') for p in parts if p.get('name')
                )
                db.add(WarrantyCaseLog(
                    case_id=case.id,
                    log_type='note',
                    content='교체 부품 정보 업데이트',
                    created_by=user_name,
                ))

            elif action == 'update_shipping':
                # 물류 정보 업데이트
                case.shipping_method = request.form.get('shipping_method', '').strip() or None
                case.shipping_tracking = request.form.get('shipping_tracking', '').strip() or None
                case.shipping_date = parse_date(request.form.get('shipping_date'))
                db.add(WarrantyCaseLog(
                    case_id=case.id,
                    log_type='note',
                    content=f'물류 정보 업데이트 ({case.shipping_method or "-"})',
                    created_by=user_name,
                ))

            elif action == 'update_charge':
                # 비용 정보 업데이트
                case.is_chargeable = request.form.get('is_chargeable') in ('on', '1', 'true')
                case.charge_amount = safe_int(request.form.get('charge_amount'))
                case.charge_status = request.form.get('charge_status', '').strip() or None
                db.add(WarrantyCaseLog(
                    case_id=case.id,
                    log_type='note',
                    content=f'비용 정보 업데이트 ({"유상" if case.is_chargeable else "무상"}'
                            f'{f" {case.charge_amount:,}원" if case.charge_amount else ""})',
                    created_by=user_name,
                ))

            else:
                # 기타 action 은 warranty_actions 에 위임
                handle_warranty_action(db, case, action, request.form, session_data)

            db.commit()
            flash('처리되었습니다.', 'success')
            return redirect(url_for('warranty.case_detail', case_id=case_id))

        # GET: 로그 최신순 정렬
        logs = sorted(case.logs, key=lambda l: l.created_at, reverse=True)

        # 부품 JSON 파싱
        parts = []
        if case.parts_json:
            try:
                parts = json.loads(case.parts_json)
            except (json.JSONDecodeError, TypeError):
                parts = []

        return render_template(
            'warranty_case_detail.html',
            case=case,
            logs=logs,
            parts=parts,
            defect_types=DEFECT_TYPES,
            status_steps=CASE_STATUS_STEPS,
            today=datetime.date.today(),
        )


# ===================================================================
# 5. GET /warranty/api/contract-search → 계약 검색 AJAX
# ===================================================================
@warranty_bp.route('/warranty/api/contract-search')
@login_required
def api_contract_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    with get_db() as db:
        like = f'%{q}%'
        results = (
            db.query(Warranty)
            .filter(
                (Warranty.contract_name.ilike(like))
                | (Warranty.model_name.ilike(like))
            )
            .order_by(Warranty.warranty_end.desc())
            .limit(20)
            .all()
        )

        today = datetime.date.today()
        return jsonify([
            {
                'warranty_id': w.id,
                'contract_name': w.contract_name or '',
                'item_group': w.item_group or '',
                'model_name': w.model_name or '',
                'warranty_type': w.warranty_type or '',
                'warranty_start': w.warranty_start.isoformat() if w.warranty_start else '',
                'warranty_end': w.warranty_end.isoformat() if w.warranty_end else '',
                'is_expired': w.warranty_end < today if w.warranty_end else True,
                'site_address': w.site_address or '',
            }
            for w in results
        ])


# ===================================================================
# 6. GET/POST /warranty/register/<contract_id> → 보증 등록/수정
# ===================================================================
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
            warranty.warranty_type = request.form.get('warranty_type', '일반').strip() or '일반'
            warranty.insurance_no = request.form.get('insurance_no', '').strip()
            warranty.insurance_returned = request.form.get('insurance_returned') in ('on', '1')
            warranty.note = request.form.get('note', '').strip()

            # 비정규화 필드 동기화
            warranty.contract_name = contract.contract_name
            warranty.site_address = request.form.get('site_address', '').strip() or warranty.site_address
            warranty.customer_contact = request.form.get('customer_contact', '').strip() or warranty.customer_contact
            warranty.customer_phone = request.form.get('customer_phone', '').strip() or warranty.customer_phone
            warranty.item_group = request.form.get('item_group', '').strip() or warranty.item_group
            warranty.model_name = request.form.get('model_name', '').strip() or warranty.model_name
            warranty.quantity = safe_int(request.form.get('quantity')) or warranty.quantity

            db.commit()
            flash('보증 정보가 저장되었습니다.', 'success')
            return redirect(url_for('warranty.warranty_register', contract_id=contract_id))

        return render_template(
            'warranty_register.html',
            contract=contract,
            warranty=warranty,
        )


# ===================================================================
# 레거시 URL 호환 리다이렉트
# ===================================================================
@warranty_bp.route('/warranty/create')
@login_required
def legacy_create():
    """기존 /warranty/create → /warranty/case/create 리다이렉트"""
    return redirect(url_for('warranty.case_create', **request.args), code=301)


@warranty_bp.route('/warranty/<int:case_id>')
@login_required
def legacy_detail(case_id):
    """기존 /warranty/<id> → /warranty/case/<id> 리다이렉트"""
    return redirect(url_for('warranty.case_detail', case_id=case_id), code=301)
