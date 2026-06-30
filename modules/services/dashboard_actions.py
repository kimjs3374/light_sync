from modules.utils import safe_int
from modules.models import DashboardNotice, DashboardSetting


# --- Setting helpers (kept simple, used by both actions and route) ---

def get_dashboard_setting_int(db, key, default_value):
    row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == key).first()
    if not row:
        return default_value
    return safe_int(row.setting_value, default_value)


def set_dashboard_setting_int(db, key, value):
    row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == key).first()
    if not row:
        row = DashboardSetting(setting_key=key, setting_value=str(value))
        db.add(row)
    else:
        row.setting_value = str(value)


# --- 메뉴 활성/비활성 (관리자 전역 제어) ---
# 'menu_disabled' 키에 비활성 메뉴키 목록을 JSON 배열로 저장한다.

def get_disabled_menus(db):
    """비활성화된 메뉴키 집합 반환 (없으면 빈 set)."""
    import json
    row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_disabled').first()
    if not row or not row.setting_value:
        return set()
    try:
        return set(json.loads(row.setting_value))
    except Exception:
        return set()


def set_disabled_menus(db, keys):
    """비활성 메뉴키 목록 저장."""
    import json
    value = json.dumps(sorted(set(keys)), ensure_ascii=False)
    row = db.query(DashboardSetting).filter(DashboardSetting.setting_key == 'menu_disabled').first()
    if not row:
        db.add(DashboardSetting(setting_key='menu_disabled', setting_value=value))
    else:
        row.setting_value = value


# --- Action Handlers ---

def handle_update_global_seconds(db, form, **ctx):
    global_seconds = max(2, safe_int(form.get('global_display_seconds'), 6))
    set_dashboard_setting_int(db, 'billboard_global_seconds', global_seconds)
    return {'flash': ('전광판 전역 노출시간이 저장되었습니다.', 'success')}


def handle_create_notice(db, form, **ctx):
    title = (form.get('title') or '공지').strip()
    message = (form.get('message') or '').strip()
    level = (form.get('level') or 'info').strip()
    sort_order = safe_int(form.get('sort_order'), 100)
    display_seconds = max(2, safe_int(form.get('display_seconds'), 6))
    is_active = form.get('is_active') == '1'

    if not message:
        return {'flash': ('공지 메시지를 입력해 주세요.', 'warning')}

    db.add(DashboardNotice(
        title=title or '공지',
        message=message,
        level=level if level in {'info', 'warning', 'danger'} else 'info',
        sort_order=sort_order,
        display_seconds=display_seconds,
        is_active=is_active,
    ))
    return {'flash': ('전광판 공지가 등록되었습니다.', 'success')}


def handle_update_notice(db, form, **ctx):
    notice_id = safe_int(form.get('notice_id'))
    notice = db.query(DashboardNotice).get(notice_id)
    if not notice:
        return {}

    notice.title = (form.get('title') or '공지').strip() or '공지'
    notice.message = (form.get('message') or '').strip()
    notice.level = (form.get('level') or 'info').strip()
    if notice.level not in {'info', 'warning', 'danger'}:
        notice.level = 'info'
    notice.sort_order = safe_int(form.get('sort_order'), 100)
    notice.display_seconds = max(2, safe_int(form.get('display_seconds'), 6))
    notice.is_active = form.get('is_active') == '1'

    if not notice.message:
        return {'flash': ('공지 메시지는 비워둘 수 없습니다.', 'warning')}

    return {'flash': ('전광판 공지가 수정되었습니다.', 'success')}


def handle_delete_notice(db, form, **ctx):
    notice_id = safe_int(form.get('notice_id'))
    notice = db.query(DashboardNotice).get(notice_id)
    if not notice:
        return {}
    db.delete(notice)
    return {'flash': ('전광판 공지가 삭제되었습니다.', 'warning')}
