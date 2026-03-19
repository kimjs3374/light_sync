"""프로젝트 기본 정보 관련 action 핸들러."""
import datetime
from modules.utils import safe_int, parse_date
from modules.models import (
    Material, ProjectPriorityOverride,
    DETAIL_ITEM_OPTIONS, normalize_detail_item,
)
from modules.history_board import append_history_log
from modules.priority_utils import get_active_priority_override


def handle_update_design_basis(db, project, form, current_user, **ctx):
    old_basis = project.design_basis or '미입력'
    new_basis = form.get('design_basis')
    reason = form.get('edit_reason')
    if old_basis != new_basis:
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                           content=f"{current_user}님이 설계기준 수정 (사유: {reason})\n변경 전: {old_basis}",
                           scope='design', kind='system')
        project.design_basis = new_basis
    return {}


def handle_update_project(db, project, form, current_user, **ctx):
    old_info = f"현장명:{project.temp_name}, 주소:{project.site_address or '-'}, 납품:{project.shipping_address or '-'}, 계약예정일:{project.expected_contract_date or '-'}"
    project.temp_name = form.get('temp_name')
    project.short_name = form.get('short_name', project.short_name)
    project.site_address = form.get('site_address')
    project.shipping_address = form.get('shipping_address')
    project.site_memo = form.get('site_memo')
    project.expected_contract_date = parse_date(form.get('expected_contract_date'))
    if 'is_urgent' in form:
        project.is_urgent = form.get('is_urgent') == '1'
    new_info = f"현장명:{project.temp_name}, 주소:{project.site_address or '-'}, 납품:{project.shipping_address or '-'}, 계약예정일:{project.expected_contract_date or '-'}"
    if old_info != new_info:
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                           content=f"{current_user}님이 전체 정보 수정\n변경 전: {old_info}\n변경 후: {new_info}",
                           scope='design', kind='system')
    return {}


def handle_update_priority_override(db, project, form, current_user, **ctx):
    can_manage_priority = ctx.get('can_manage_priority', False)
    if not can_manage_priority:
        return {'flash': ('우선순위 지정 권한이 없습니다.', 'danger')}

    priority_mode = (form.get('priority_mode') or 'set').strip()
    note = (form.get('priority_note') or '').strip()
    override = db.query(ProjectPriorityOverride).filter(
        ProjectPriorityOverride.project_id == project.id
    ).first()

    if priority_mode == 'clear':
        if override and override.is_active:
            old_note = override.note or ''
            override.is_active = False
            override.note = None
            override.set_by_user_id = ctx.get('user_id')
            override.set_by_name = current_user or '사용자'
            append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                               content=f"{current_user}님이 수동 우선순위 해제" + (f"\n이전 사유: {old_note}" if old_note else ""),
                               scope='design', kind='system')
            return {'flash': ('수동 우선순위가 해제되었습니다.', 'success')}
        else:
            return {'flash': ('설정된 수동 우선순위가 없습니다.', 'info')}
    else:
        is_new = override is None
        if is_new:
            override = ProjectPriorityOverride(project_id=project.id)
            db.add(override)
        override.is_active = True
        override.note = note or None
        override.set_by_user_id = ctx.get('user_id')
        override.set_by_name = current_user or '사용자'
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
            content=(
                f"{current_user}님이 수동 우선순위 {'지정' if is_new or not get_active_priority_override(project) else '수정'}"
                + (f"\n사유: {note}" if note else "")
            ),
            scope='design', kind='system')
        return {'flash': ('수동 우선순위가 저장되었습니다.', 'success')}


def handle_update_work_path(db, project, form, current_user, **ctx):
    new_path = form.get('work_path')
    if project.work_path != new_path:
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                           content=f"{current_user}님이 작업경로 업데이트: {new_path}",
                           scope='design', kind='system')
        project.work_path = new_path
    return {}


def handle_confirm_spec(db, project, form, current_user, **ctx):
    """시방서 반영 확인 체크 + 히스토리 자동 기록 (매그나텍 PHASE 2-3)"""
    confirmed = form.get("spec_confirmed") == "on"
    project.spec_confirmed = confirmed
    project.spec_confirmed_date = datetime.date.today() if confirmed else None

    if confirmed:
        content = "시방서 반영 확인됨"
    else:
        content = "시방서 반영 확인 해제"

    append_history_log(
        db,
        project_id=project.id,
        user_name="System",
        content=f"{current_user} [설계] {content}",
        scope="design",
        kind="system",
    )
    return {'flash': (content, 'success')}


def handle_update_material(db, project, form, current_user, **ctx):
    template_name = ctx.get('page_scope', '')
    user_group = ctx.get('user_group')
    role = ctx.get('role')
    mat = db.query(Material).get(safe_int(form.get('material_id')))
    if mat:
        old_info = f"{mat.category}/{mat.model_name}({mat.quantity})"
        new_cat = normalize_detail_item(form.get('category'), default=mat.category or DETAIL_ITEM_OPTIONS[0])
        new_m, new_q = form.get('model_name'), form.get('quantity')
        new_barcode = form.get('barcode_id')
        if mat.category != new_cat or mat.model_name != new_m or mat.quantity != new_q:
            append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                               content=f"{current_user}님이 품목 수정\n변경 전: {old_info} ➡️ 변경 후: {new_cat}/{new_m}({new_q})",
                               scope='material', kind='system')
            mat.category, mat.model_name, mat.quantity = new_cat, new_m, new_q
        if new_barcode is not None and mat.barcode_id != new_barcode:
            mat.barcode_id = new_barcode

        # 계약관리 상태 업데이트
        if ctx.get('page_scope') == 'contract':
            for dept, col in [('영업', 'status_sales'), ('관리', 'status_admin'), ('생산', 'status_prod')]:
                if user_group == f"{dept}부" or role == 'admin':
                    setattr(mat, col, form.get(col))
    return {}
