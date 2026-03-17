import datetime
from modules.utils import parse_date
from modules.models import WarrantyCaseLog


def handle_warranty_action(db, case, action, form, session_data):
    user_name = session_data.get('full_name', '사용자')

    if action == 'update_status':
        new_status = form.get('new_status')
        if new_status and new_status != case.status:
            old = case.status
            case.status = new_status
            if new_status == '현장확인':
                case.site_visit_date = parse_date(form.get('site_visit_date')) or datetime.date.today()
            elif new_status == '완료':
                case.completed_date = parse_date(form.get('completed_date')) or datetime.date.today()
            db.add(WarrantyCaseLog(
                case_id=case.id, log_type='status_change',
                old_status=old, new_status=new_status,
                content=form.get('status_memo', '').strip() or f'{old} → {new_status}',
                created_by=user_name,
            ))

    elif action == 'update_detail':
        case.cause_analysis = form.get('cause_analysis', '').strip()
        case.action_taken = form.get('action_taken', '').strip()
        case.replaced_parts = form.get('replaced_parts', '').strip()
        case.assigned_to = form.get('assigned_to', '').strip()
        db.add(WarrantyCaseLog(
            case_id=case.id, log_type='note',
            content='처리 내역 업데이트',
            created_by=user_name,
        ))

    elif action == 'add_note':
        content = form.get('note_content', '').strip()
        if content:
            db.add(WarrantyCaseLog(
                case_id=case.id, log_type='note',
                content=content,
                created_by=user_name,
            ))
