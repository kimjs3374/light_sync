from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from modules.auth_decorators import login_required
import datetime
import shutil
from pathlib import Path
from collections import defaultdict
from sqlalchemy.orm import joinedload
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.spec_utils import format_spec_summary
from modules.models import (
    Project, Material, HistoryLog, Contract, ContractItem,
    ProjectDeleteRequest, UserPriorityPermission,
    Drawing, DrawingVersion,
    DETAIL_ITEM_OPTIONS, LIGHTING_DETAIL_ITEMS, normalize_detail_item, DRAWING_TYPE_OPTIONS,
    CONTRACT_ITEM_SPEC_SCHEMA,
)
from modules.history_board import append_history_log, get_project_history_context
from modules.priority_utils import (
    append_due_priority_reason,
    append_manual_priority_reason,
    append_priority_reason,
    get_active_priority_override,
    make_priority_entry,
    sort_priority_entries,
)
from modules.storage_adapter import is_storage_enabled, delete_prefix
from routes.material import compute_admin_status_from_orders
from modules.services.project_actions import (
    handle_update_design_basis, handle_update_project,
    handle_update_priority_override, handle_update_work_path, handle_update_material,
)
from modules.services.contract_actions import (
    handle_update_contract, handle_add_contract, handle_update_contract_item,
    handle_add_contract_item, handle_delete_contract_item, handle_delete_material,
)
from modules.services.barcode_actions import (
    handle_update_barcodes_manual, handle_upload_barcodes,
    handle_delete_barcode, handle_update_barcode_meta,
)
from modules.services.contact_actions import (
    handle_add_contact, handle_update_contact, handle_delete_contact,
    handle_add_material, handle_add_chat, handle_add_history_reply,
)

project_bp = Blueprint('project', __name__)

BASE_DIR = Path(__file__).resolve().parents[1]

ACTION_HANDLERS = {
    'update_design_basis': handle_update_design_basis,
    'update_project': handle_update_project,
    'update_priority_override': handle_update_priority_override,
    'update_work_path': handle_update_work_path,
    'update_material': handle_update_material,
    'update_contract': handle_update_contract,
    'add_contract': handle_add_contract,
    'update_contract_item': handle_update_contract_item,
    'add_contract_item': handle_add_contract_item,
    'delete_contract_item': handle_delete_contract_item,
    'delete_material': handle_delete_material,
    'update_contract_item_barcodes_manual': handle_update_barcodes_manual,
    'upload_contract_item_barcodes': handle_upload_barcodes,
    'delete_contract_item_barcode': handle_delete_barcode,
    'update_contract_item_barcode_meta': handle_update_barcode_meta,
    'add_contact': handle_add_contact,
    'update_contact': handle_update_contact,
    'delete_contact': handle_delete_contact,
    'add_material': handle_add_material,
    'add_chat': handle_add_chat,
    'add_history_reply': handle_add_history_reply,
}


def _remove_project_drawing_storage(project_id):
    if is_storage_enabled():
        try:
            delete_prefix(f"storage/drawings/project_{project_id}")
        except Exception:
            current_app.logger.warning('Failed to delete storage prefix for project_%s', project_id, exc_info=True)

    project_dir = BASE_DIR / 'storage' / 'drawings' / f'project_{project_id}'
    if project_dir.is_dir():
        shutil.rmtree(project_dir, ignore_errors=True)


def _is_prod_group():
    return session.get('user_group') == '생산부'


def _can_approve_delete():
    return bool(session.get('role') == 'admin' or session.get('can_approve_delete'))


def _can_manage_priority(db):
    if session.get('role') == 'admin' or session.get('can_manage_priority'):
        return True
    user_id = session.get('user_id')
    if not user_id:
        return False
    return bool(
        db.query(UserPriorityPermission).filter(
            UserPriorityPermission.user_id == user_id,
            UserPriorityPermission.is_active.is_(True)
        ).first()
    )


def _execute_project_delete(db, project_obj):
    contract_count = len(project_obj.contracts or [])
    item_count = sum(len(c.items or []) for c in (project_obj.contracts or []))
    material_count = len(project_obj.materials or [])
    project_label = f"{project_obj.project_no} / {project_obj.temp_name}"

    _remove_project_drawing_storage(project_obj.id)
    db.delete(project_obj)
    return project_label, contract_count, item_count, material_count


# -------------------------------------------------------------------
# 1. 영업관리 리스트
# -------------------------------------------------------------------
@project_bp.route('/project_list')
@login_required
def project_list():
    with get_db() as db:
        today = datetime.date.today()
        # 관계 데이터를 미리 로드하여 세션 종료 후에도 템플릿에서 에러가 나지 않게 함
        projects = db.query(Project).options(
            joinedload(Project.materials),
            joinedload(Project.contacts),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        priority_projects = []
        for p in projects:
            reasons = []
            dday = (p.expected_contract_date - today).days if p.expected_contract_date else None
            override = append_manual_priority_reason(reasons, p)

            if not p.is_contracted:
                if p.is_urgent:
                    append_priority_reason(reasons, 'urgent')
                append_due_priority_reason(reasons, dday, 'project')

            if reasons:
                meta_lines = [
                    f"계약예정일: {p.expected_contract_date.strftime('%Y-%m-%d') if p.expected_contract_date else '-'}",
                    f"등록 품목: {len(p.materials or [])}건",
                    f"담당자: {len(p.contacts or [])}명",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=p.id,
                    project_no=p.project_no,
                    title=p.temp_name or '-',
                    subtitle=(f"약칭: {p.short_name}" if p.short_name else ''),
                    detail_url=url_for('project.project_detail', project_id=p.id),
                    reasons=reasons,
                    dday=dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)
        return render_template('project_list.html', projects=projects, today=today, priority_projects=priority_projects)

# -------------------------------------------------------------------
# 2. 📋 계약관리 리스트 (실무형 필터/검색 강화)
# -------------------------------------------------------------------
@project_bp.route('/contract_list')
@login_required
def contract_list():

    q = (request.args.get('q') or '').strip().lower()
    due_filter = request.args.get('due', 'all')
    inspection_filter = request.args.get('inspection', 'all')
    urgent_filter = request.args.get('urgent', 'all')
    sort_by = request.args.get('sort', 'due_asc')

    with get_db() as db:
        # 하위 계약/품목/원본자재까지 선로드
        projects = db.query(Project).filter(Project.is_contracted == True).options(
            joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.material_orders),
            joinedload(Project.materials),
            joinedload(Project.priority_override),
        ).order_by(Project.id.desc()).all()

        enriched = []
        today = datetime.date.today()
        total_contracted = len(projects)
        overdue_count = 0
        due_7_count = 0
        urgent_count = 0
        for p in projects:
            contracts_sorted = sorted(
                p.contracts,
                key=lambda c: c.delivery_due_date or datetime.date.max
            )
            primary_contract = contracts_sorted[0] if contracts_sorted else None
            due_date = primary_contract.delivery_due_date if primary_contract else None
            dday = (due_date - today).days if due_date else None

            search_pool = [p.project_no or '', p.temp_name or '', p.short_name or '']
            for c in p.contracts:
                search_pool.append(c.contract_name or '')
                search_pool.append(c.item_group or '')
                for item in c.items:
                    item.status_admin = compute_admin_status_from_orders(item.material_orders)
                    search_pool.append(item.model_name or '')
                    search_pool.append(format_spec_summary(item.category, item.item_spec))

            has_inspection = any(c.is_prof_inspection for c in p.contracts)
            is_urgent_project = p.is_urgent or any(c.is_urgent_prod for c in p.contracts)

            if dday is not None and dday < 0:
                overdue_count += 1
            if dday is not None and 0 <= dday <= 7:
                due_7_count += 1
            if is_urgent_project:
                urgent_count += 1

            if q and not any(q in s.lower() for s in search_pool):
                continue
            if due_filter == 'overdue' and (dday is None or dday >= 0):
                continue
            if due_filter == 'week' and (dday is None or dday < 0 or dday > 7):
                continue
            if due_filter == 'twoweek' and (dday is None or dday < 0 or dday > 14):
                continue
            if inspection_filter == 'yes' and not has_inspection:
                continue
            if inspection_filter == 'no' and has_inspection:
                continue
            if urgent_filter == 'yes' and not is_urgent_project:
                continue

            p.primary_contract = primary_contract
            p.due_date = due_date
            p.dday = dday
            p.has_inspection = has_inspection
            p.is_urgent_project = is_urgent_project
            p.item_groups = sorted(list({(c.item_group or DETAIL_ITEM_OPTIONS[0]) for c in p.contracts}))
            enriched.append(p)

        if sort_by == 'due_desc':
            enriched.sort(key=lambda p: (p.dday is None, -(p.dday if p.dday is not None else -99999)))
        elif sort_by == 'created_desc':
            enriched.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
        else:  # due_asc
            enriched.sort(key=lambda p: (p.dday is None, p.dday if p.dday is not None else 99999))

        priority_projects = []
        for p in enriched:
            reasons = []
            override = append_manual_priority_reason(reasons, p)
            if p.is_urgent_project:
                append_priority_reason(reasons, 'urgent')
            if p.has_inspection:
                append_priority_reason(reasons, 'inspection')
            append_due_priority_reason(reasons, p.dday, 'contract')

            if reasons:
                meta_lines = [
                    f"대표 계약: {p.primary_contract.contract_name if p.primary_contract else '-'}",
                    f"계약건 수: {len(p.contracts or [])}건",
                    f"품목군: {', '.join(p.item_groups) if p.item_groups else '-'}",
                ]
                if override and override.note:
                    meta_lines.insert(0, f"수동 사유: {override.note}")
                priority_projects.append(make_priority_entry(
                    project_id=p.id,
                    project_no=p.project_no,
                    title=p.temp_name or '-',
                    subtitle=(f"약칭: {p.short_name}" if p.short_name else ''),
                    detail_url=url_for('project.contract_detail', project_id=p.id),
                    reasons=reasons,
                    dday=p.dday,
                    override_note=(override.note if override and override.note else ''),
                    meta_lines=meta_lines,
                ))

        priority_projects = sort_priority_entries(priority_projects)

        return render_template(
            'contract_list.html',
            projects=enriched,
            priority_projects=priority_projects,
            today=today,
            lighting_detail_items=LIGHTING_DETAIL_ITEMS,
            filters={
                'q': request.args.get('q', ''),
                'due': due_filter,
                'inspection': inspection_filter,
                'urgent': urgent_filter,
                'sort': sort_by,
            },
            stats={
                'total': total_contracted,
                'filtered': len(enriched),
                'overdue': overdue_count,
                'due_7': due_7_count,
                'urgent': urgent_count,
            },
            format_spec_summary=format_spec_summary
        )

# -------------------------------------------------------------------
# 3. 영업 현장 등록 (원본 로직 유지)
# -------------------------------------------------------------------
@project_bp.route('/project_create', methods=['GET', 'POST'])
@login_required
def project_create():
    if _is_prod_group():
        flash('생산부는 설계 현장 등록 권한이 없습니다.', 'danger')
        return redirect(url_for('project.project_list'))
    with get_db() as db:
        if request.method == 'POST':
            try:
                year = str(datetime.date.today().year)
                count = db.query(Project).filter(Project.project_no.like(f"{year}-%")).count()
                new_p = Project(
                    project_no=f"{year}-{(count + 1):03d}",
                    temp_name=request.form.get('temp_name'),
                    site_address=request.form.get('site_address'),
                    shipping_address=request.form.get('shipping_address') or request.form.get('site_address'),
                    site_memo=request.form.get('site_memo'),
                    expected_contract_date=parse_date(request.form.get('expected_contract_date'))
                )
                db.add(new_p); db.flush()
                # 화면에서 선택한 카테고리(light_category[])를 그대로 반영
                categories = request.form.getlist('light_category[]')
                models = request.form.getlist('light_model[]')
                qtys = request.form.getlist('light_qty[]')
                for cat, m, q in zip(categories, models, qtys):
                    normalized_cat = normalize_detail_item(cat, default=DETAIL_ITEM_OPTIONS[0])
                    if (m or '').strip():
                        db.add(Material(project_id=new_p.id, category=normalized_cat, model_name=m, quantity=str(q)))

                # 구버전 폼 호환 (tower_* 필드가 들어오는 경우)
                tower_models = request.form.getlist('tower_model[]')
                tower_qtys = request.form.getlist('tower_qty[]')
                for m, q in zip(tower_models, tower_qtys):
                    if (m or '').strip():
                        db.add(Material(
                            project_id=new_p.id,
                            category=normalize_detail_item("조명타워", default=DETAIL_ITEM_OPTIONS[0]),
                            model_name=m,
                            quantity=str(q)
                        ))
                db.commit()
                return redirect(url_for('project.project_list'))
            except Exception as e:
                db.rollback()
                current_app.logger.exception('project_create failed')
                flash('등록 처리 중 오류가 발생했습니다.', 'danger')
        return render_template('project_create.html', detail_item_options=DETAIL_ITEM_OPTIONS)

# -------------------------------------------------------------------
# 4. 상세 페이지 통합 처리 (로그 기능 및 수정 로직 완벽 복구)
# -------------------------------------------------------------------
@project_bp.route('/project_detail/<int:project_id>', methods=['GET', 'POST'])
@login_required
def project_detail(project_id):
    return handle_detail_common(project_id, 'project_detail.html')

@project_bp.route('/contract_detail/<int:project_id>', methods=['GET', 'POST'])
@login_required
def contract_detail(project_id):
    return handle_detail_common(project_id, 'contract_detail.html')

def handle_detail_common(project_id, template_name):
    with get_db() as db:
        current_user = session.get('full_name')
        user_group = session.get('user_group')
        page_scope = 'contract' if 'contract' in template_name else 'design'

        p = db.query(Project).options(
            joinedload(Project.materials),
            joinedload(Project.contacts),
            joinedload(Project.priority_override),
            joinedload(Project.history_logs),
            joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.barcodes),
            joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.drawings).joinedload(Drawing.versions)
        ).get(project_id)

        can_manage_priority = _can_manage_priority(db)

        if request.method == 'POST':
            action = request.form.get('action')
            ajax_log_entry = None

            handler = ACTION_HANDLERS.get(action)
            if handler:
                ctx = {
                    'page_scope': page_scope,
                    'can_manage_priority': can_manage_priority,
                    'user_id': session.get('user_id'),
                    'user_group': user_group,
                    'role': session.get('role'),
                    'files': request.files,
                }
                result = handler(db, p, request.form, current_user, **ctx)
                if result.get('flash'):
                    flash(*result['flash'])
                for f in result.get('flashes', []):
                    flash(*f)
                if result.get('ajax_log'):
                    ajax_log_entry = result['ajax_log']

            # 신규/레거시 HistoryLog 객체 공통 기본값 보정
            for obj in list(db.new):
                if isinstance(obj, HistoryLog):
                    if not obj.log_kind:
                        obj.log_kind = 'system' if '시스템' in (obj.user_name or '') else 'comment'
                    if not obj.log_scope:
                        obj.log_scope = 'common' if obj.log_kind == 'comment' else page_scope

            db.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'ok': True, 'action': action, 'log': ajax_log_entry})
            redirect_to = "project.contract_detail" if "contract" in template_name else "project.project_detail"
            return redirect(url_for(redirect_to, project_id=project_id))

        history, history_counts = get_project_history_context(
            db,
            project_id=project_id,
            default_scope=page_scope,
            limit=500
        )
        return render_template(
            template_name,
            project=p,
            priority_override=get_active_priority_override(p),
            can_manage_priority=can_manage_priority,
            history=history,
            history_counts=history_counts,
            detail_item_options=DETAIL_ITEM_OPTIONS,
            lighting_detail_items=LIGHTING_DETAIL_ITEMS,
            contract_item_spec_schema=CONTRACT_ITEM_SPEC_SCHEMA,
            drawing_type_options=DRAWING_TYPE_OPTIONS,
            can_write_drawings=(session.get('role') == 'admin' or session.get('user_group') == '영업부')
        )

# -------------------------------------------------------------------
# 5. 계약 전환 (백업코드 승계)
# -------------------------------------------------------------------
@project_bp.route('/convert_to_contract/<int:project_id>', methods=['POST'])
@login_required
def convert_to_contract(project_id):
    if _is_prod_group():
        flash('생산부는 계약 전환 권한이 없습니다.', 'danger')
        return redirect(url_for('project.project_list'))
    with get_db() as db:
        p = db.query(Project).get(project_id)
        if p:
            if p.is_contracted:
                flash('이미 계약 현장으로 전환된 건입니다.', 'warning')
            else:
                try:
                    p.is_contracted = True
                    p.contract_date = datetime.date.today()
                    # 품목군별 자동 분리 계약 생성 (계약건 단일 품목군 원칙)
                    if not p.contracts:
                        grouped = defaultdict(list)
                        for mat in p.materials:
                            group_key = normalize_detail_item(mat.category, default=DETAIL_ITEM_OPTIONS[0])
                            grouped[group_key].append(mat)

                        if grouped:
                            for group_name, mats in grouped.items():
                                new_c = Contract(
                                    project_id=project_id,
                                    contract_name=f"{p.temp_name} - {group_name}",
                                    item_group=group_name,
                                    contract_date=datetime.date.today(),
                                    delivery_due_date=datetime.date.today() + datetime.timedelta(days=30)
                                )
                                db.add(new_c)
                                db.flush()

                                for mat in mats:
                                    db.add(ContractItem(
                                        contract_id=new_c.id,
                                        category=group_name,
                                        model_name=mat.model_name,
                                        quantity=safe_int(mat.quantity, 0)
                                    ))
                        else:
                            # 품목 미입력 현장도 최소 1개 계약 껍데기 생성
                            db.add(Contract(
                                project_id=project_id,
                                contract_name=f"{p.temp_name} 기본 계약",
                                item_group=DETAIL_ITEM_OPTIONS[0],
                                contract_date=datetime.date.today(),
                                delivery_due_date=datetime.date.today() + datetime.timedelta(days=30)
                            ))

                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name="시스템 🤖",
                        content=f"{session.get('full_name')}님이 계약 현장으로 전환하였습니다. (품목군별 자동 분리 적용)",
                        scope='contract',
                        kind='system'
                    )
                    db.commit()
                    flash('계약 현장으로 전환되었습니다.', 'success')
                except Exception as e:
                    db.rollback()
                    current_app.logger.exception('convert_to_contract failed project=%s', project_id)
                    flash('계약 전환 처리 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('project.contract_list'))


# -------------------------------------------------------------------
# 6. 현장 삭제요청/승인 (설계/계약 공통)
# -------------------------------------------------------------------
@project_bp.route('/project_delete_request/<int:project_id>', methods=['POST'])
@login_required
def project_delete_request(project_id):
    if _is_prod_group():
        flash('생산부는 삭제요청 권한이 없습니다.', 'danger')
        return redirect(url_for('project.project_list'))

    reason = (request.form.get('delete_reason') or '').strip()
    if not reason:
        flash('삭제 사유는 필수입니다.', 'warning')
        return redirect(request.referrer or url_for('project.project_list'))

    with get_db() as db:
        try:
            p = db.query(Project).get(project_id)

            if not p:
                flash('삭제요청 대상 현장을 찾을 수 없습니다.', 'warning')
                return redirect(request.referrer or url_for('project.project_list'))

            exists_pending = db.query(ProjectDeleteRequest).filter(
                ProjectDeleteRequest.project_id == project_id,
                ProjectDeleteRequest.status == 'PENDING'
            ).first()
            if exists_pending:
                flash('이미 대기중인 삭제요청이 있습니다.', 'warning')
                return redirect(request.referrer or url_for('project.project_list'))

            db.add(ProjectDeleteRequest(
                project_id=project_id,
                project_no_snapshot=p.project_no,
                project_name_snapshot=p.temp_name,
                requester_id=session.get('user_id'),
                requester_name=session.get('full_name') or '사용자',
                requester_group=session.get('user_group') or '-',
                request_reason=reason,
                status='PENDING'
            ))
            db.commit()
            flash('삭제요청이 접수되었습니다. 승인 후 삭제가 진행됩니다.', 'success')
            return redirect(request.referrer or url_for('project.project_list'))
        except Exception as e:
            db.rollback()
            current_app.logger.exception('project_delete_request failed project=%s', project_id)
            flash('삭제요청 처리 중 오류가 발생했습니다.', 'danger')
            return redirect(request.referrer or url_for('project.project_list'))


@project_bp.route('/project_delete_requests/<int:req_id>/approve', methods=['POST'])
@login_required
def approve_project_delete_request(req_id):
    if not _can_approve_delete():
        flash('삭제 승인 권한이 없습니다.', 'danger')
        return redirect(url_for('auth.admin_settings'))

    with get_db() as db:
        try:
            req_obj = db.query(ProjectDeleteRequest).get(req_id)
            if not req_obj or req_obj.status != 'PENDING':
                flash('승인 가능한 삭제요청이 아닙니다.', 'warning')
                return redirect(url_for('auth.admin_settings'))

            p = db.query(Project).options(
                joinedload(Project.contracts).joinedload(Contract.items),
                joinedload(Project.materials),
                joinedload(Project.drawings)
            ).get(req_obj.project_id)

            req_obj.status = 'APPROVED'
            req_obj.approved_by_user_id = session.get('user_id')
            req_obj.approved_by_name = session.get('full_name') or '승인자'
            req_obj.approved_at = datetime.datetime.now()

            if p:
                project_label, contract_count, item_count, material_count = _execute_project_delete(db, p)
                flash(
                    f"삭제 승인/완료: {project_label} (계약 {contract_count}건, 계약품목 {item_count}건, 설계품목 {material_count}건)",
                    'success'
                )
            else:
                flash('요청은 승인 처리되었고, 대상 현장은 이미 삭제되어 있습니다.', 'info')

            db.commit()
        except Exception as e:
            db.rollback()
            current_app.logger.exception('approve_project_delete failed req=%s', req_id)
            flash('삭제 승인 처리 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('auth.admin_settings'))


@project_bp.route('/project_delete_requests/<int:req_id>/reject', methods=['POST'])
@login_required
def reject_project_delete_request(req_id):
    if not _can_approve_delete():
        flash('삭제 반려 권한이 없습니다.', 'danger')
        return redirect(url_for('auth.admin_settings'))

    reject_reason = (request.form.get('reject_reason') or '').strip()

    with get_db() as db:
        try:
            req_obj = db.query(ProjectDeleteRequest).get(req_id)
            if not req_obj or req_obj.status != 'PENDING':
                flash('반려 가능한 삭제요청이 아닙니다.', 'warning')
                return redirect(url_for('auth.admin_settings'))

            req_obj.status = 'REJECTED'
            req_obj.reject_reason = reject_reason or None
            req_obj.approved_by_user_id = session.get('user_id')
            req_obj.approved_by_name = session.get('full_name') or '승인자'
            req_obj.approved_at = datetime.datetime.now()
            db.commit()
            flash('삭제요청이 반려되었습니다.', 'warning')
        except Exception as e:
            db.rollback()
            current_app.logger.exception('reject_project_delete failed req=%s', req_id)
            flash('삭제 반려 처리 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('auth.admin_settings'))


@project_bp.route('/project_delete/<int:project_id>', methods=['POST'])
@login_required
def project_delete(project_id):
    """기존 라우트 호환: 승인권자만 즉시삭제 가능(일반 사용자는 삭제요청 사용)."""
    if not _can_approve_delete():
        flash('직접 삭제 권한이 없습니다. 삭제요청을 이용해 주세요.', 'danger')
        return redirect(request.referrer or url_for('project.project_list'))

    with get_db() as db:
        try:
            p = db.query(Project).options(
                joinedload(Project.contracts).joinedload(Contract.items),
                joinedload(Project.materials),
                joinedload(Project.drawings)
            ).get(project_id)

            if not p:
                flash('삭제 대상 현장을 찾을 수 없습니다.', 'warning')
                return redirect(url_for('project.project_list'))

            next_url = (request.form.get('next') or '').strip()
            if not next_url.startswith('/'):
                next_url = url_for('project.contract_list' if p.is_contracted else 'project.project_list')

            project_label, contract_count, item_count, material_count = _execute_project_delete(db, p)
            db.commit()

            flash(
                f"현장 삭제 완료: {project_label} (계약 {contract_count}건, 계약품목 {item_count}건, 설계품목 {material_count}건)",
                'success'
            )
            return redirect(next_url)
        except Exception as e:
            db.rollback()
            current_app.logger.exception('project_delete failed project=%s', project_id)
            flash('현장 삭제 처리 중 오류가 발생했습니다.', 'danger')
            return redirect(url_for('project.project_list'))