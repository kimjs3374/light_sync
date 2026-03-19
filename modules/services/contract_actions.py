"""계약/품목 CRUD action 핸들러."""
import datetime
from modules.utils import safe_int, parse_date
from modules.spec_utils import extract_contract_item_spec, validate_contract_item_spec, format_spec_summary
from modules.models import (
    Contract, ContractItem, Material, MaterialOrder, HistoryLog,
    DETAIL_ITEM_OPTIONS, LIGHTING_DETAIL_ITEMS, normalize_detail_item,
    SALES_STATUS_STEPS, ADMIN_STATUS_STEPS, PROD_STATUS_STEPS,
)
from routes.material import sync_material_orders_for_contract_item


def handle_update_contract(db, project, form, current_user, **ctx):
    contract_id = safe_int(form.get('contract_id'))
    con = db.query(Contract).filter_by(id=contract_id, project_id=project.id).first()
    if not con:
        return {}
    old_info = (
        f"계약명:{con.contract_name}, 품목군:{con.item_group}, 계약일:{con.contract_date}, "
        f"납품기일:{con.delivery_due_date}, 납품희망일:{con.desired_delivery_date}, "
        f"전문검수:{con.is_prof_inspection}, 긴급제작:{con.is_urgent_prod}"
    )
    con.contract_name = form.get('contract_name') or con.contract_name
    con.item_group = normalize_detail_item(
        form.get('item_group'),
        default=con.item_group or DETAIL_ITEM_OPTIONS[0]
    )
    con.contract_date = parse_date(form.get('contract_date')) or con.contract_date
    con.delivery_due_date = parse_date(form.get('delivery_due_date')) or con.delivery_due_date
    con.desired_delivery_date = parse_date(form.get('desired_delivery_date'))
    con.is_prof_inspection = form.get('is_prof_inspection') == '1'
    con.is_urgent_prod = form.get('is_urgent_prod') == '1'
    for item in con.items:
        item.category = con.item_group
    new_info = (
        f"계약명:{con.contract_name}, 품목군:{con.item_group}, 계약일:{con.contract_date}, "
        f"납품기일:{con.delivery_due_date}, 납품희망일:{con.desired_delivery_date}, "
        f"전문검수:{con.is_prof_inspection}, 긴급제작:{con.is_urgent_prod}"
    )
    ajax_log = None
    if old_info != new_info:
        log_content = f"{current_user}님이 계약정보 수정\n변경 전: {old_info}\n변경 후: {new_info}"
        db.add(HistoryLog(project_id=project.id, user_name="시스템 🤖", content=log_content))
        ajax_log = {
            'user_name': '시스템 🤖',
            'content': log_content,
            'created_at': datetime.datetime.now().strftime('%y/%m/%d %H:%M:%S')
        }
    return {'ajax_log': ajax_log}


def handle_add_contract(db, project, form, current_user, **ctx):
    import json as _json
    contract_name = (form.get('contract_name') or '').strip()
    item_group = normalize_detail_item(form.get('item_group'), default=DETAIL_ITEM_OPTIONS[0])
    contract_date = parse_date(form.get('contract_date')) or datetime.date.today()
    delivery_due_date = parse_date(form.get('delivery_due_date')) or (datetime.date.today() + datetime.timedelta(days=30))

    if not contract_name:
        return {'flash': ('계약명을 입력해 주세요.', 'warning')}

    g2b_no = (form.get('g2b_contract_no') or '').strip() or None

    new_contract = Contract(
        project_id=project.id,
        contract_name=contract_name,
        item_group=item_group,
        contract_date=contract_date,
        delivery_due_date=delivery_due_date,
        desired_delivery_date=parse_date(form.get('desired_delivery_date')),
        is_prof_inspection=form.get('is_prof_inspection') == '1',
        is_urgent_prod=form.get('is_urgent_prod') == '1',
        g2b_contract_no=g2b_no,
    )
    db.add(new_contract)
    db.flush()

    # G2B 품목 자동 생성
    g2b_items_json = form.get('g2b_items_json', '').strip()
    if g2b_items_json:
        try:
            g2b_items = _json.loads(g2b_items_json)
            for gi in g2b_items:
                model = gi.get('spec_name') or gi.get('detail_name') or '-'
                qty = safe_int(gi.get('qty'), 1)
                db.add(ContractItem(
                    contract_id=new_contract.id,
                    category=item_group,
                    model_name=model,
                    quantity=qty,
                ))
        except (ValueError, TypeError):
            pass

    db.add(HistoryLog(
        project_id=project.id,
        user_name="시스템 🤖",
        content=f"{current_user}님이 계약 추가: {new_contract.contract_name} / 품목군:{new_contract.item_group}"
        + (f" (G2B 연동: {g2b_no})" if g2b_no else "")
    ))
    return {}


def handle_delete_contract(db, project, form, current_user, **ctx):
    contract_id = safe_int(form.get('contract_id'))
    con = db.query(Contract).filter_by(id=contract_id, project_id=project.id).first()
    if not con:
        return {'flash': ('계약을 찾을 수 없습니다.', 'warning')}

    contract_name = con.contract_name
    # 하위 품목의 자재발주 삭제 → 품목 삭제 → 계약 삭제
    for item in con.items:
        db.query(MaterialOrder).filter(MaterialOrder.contract_item_id == item.id).delete()
        db.delete(item)
    db.delete(con)
    db.add(HistoryLog(
        project_id=project.id,
        user_name="시스템 🤖",
        content=f"{current_user}님이 계약 삭제: {contract_name}"
    ))
    return {'flash': (f'계약 [{contract_name}]이 삭제되었습니다.', 'success')}


def handle_update_contract_item(db, project, form, current_user, **ctx):
    item_id = safe_int(form.get('item_id'))
    item = db.query(ContractItem).get(item_id)
    if not item:
        return {}
    con = db.query(Contract).get(item.contract_id)
    if not con or con.project_id != project.id:
        return {}

    old_info = f"{item.category}/{item.model_name}({item.quantity})"
    old_spec_summary = format_spec_summary(item.category, item.item_spec)
    old_sales_status = item.status_sales or '계약확인'
    old_admin_status = item.status_admin or '자재확인중'
    old_prod_status = item.status_prod or '자재대기중'

    new_category = normalize_detail_item(
        form.get('category'),
        default=con.item_group or DETAIL_ITEM_OPTIONS[0]
    )
    if new_category != (con.item_group or DETAIL_ITEM_OPTIONS[0]):
        return {'flash': (f"계약[{con.contract_name}]은 품목군 [{con.item_group}]만 입력할 수 있습니다.", 'warning')}

    flashes = []
    item.category = new_category
    item.model_name = form.get('model_name')
    item.quantity = safe_int(form.get('quantity'), 0)
    item.barcode_id = form.get('barcode_id') if item.category in LIGHTING_DETAIL_ITEMS else None
    new_spec = extract_contract_item_spec(form, item.category)
    missing_spec = validate_contract_item_spec(item.category, new_spec)
    if missing_spec:
        flashes.append((f"필수 스펙 누락: {', '.join(missing_spec)}", 'warning'))
    else:
        item.item_spec = new_spec

    sales_status = form.get('status_sales')
    if sales_status:
        if sales_status in SALES_STATUS_STEPS:
            item.status_sales = sales_status
        else:
            flashes.append(('영업현황 값이 올바르지 않아 기존 값을 유지했습니다.', 'warning'))

    admin_status = form.get('status_admin')
    if admin_status:
        if admin_status in ADMIN_STATUS_STEPS:
            item.status_admin = admin_status
        else:
            flashes.append(('구매현황 값이 올바르지 않아 기존 값을 유지했습니다.', 'warning'))

    prod_status = form.get('status_prod')
    if prod_status:
        if prod_status in PROD_STATUS_STEPS:
            item.status_prod = prod_status
        else:
            flashes.append(('생산현황 값이 올바르지 않아 기존 값을 유지했습니다.', 'warning'))

    new_info = f"{item.category}/{item.model_name}({item.quantity})"
    changed_logs = []
    if old_info != new_info:
        changed_logs.append(f"품목정보: {old_info} ➡️ {new_info}")
    new_spec_summary = format_spec_summary(item.category, new_spec)
    if old_spec_summary != new_spec_summary:
        changed_logs.append(f"품목스펙: {old_spec_summary} ➡️ {new_spec_summary}")
    if old_sales_status != (item.status_sales or old_sales_status):
        changed_logs.append(f"영업현황: {old_sales_status} ➡️ {item.status_sales}")
    if old_admin_status != (item.status_admin or old_admin_status):
        changed_logs.append(f"구매현황: {old_admin_status} ➡️ {item.status_admin}")
    if old_prod_status != (item.status_prod or old_prod_status):
        changed_logs.append(f"생산현황: {old_prod_status} ➡️ {item.status_prod}")

    ajax_log = None
    if changed_logs:
        log_content = (
            f"{current_user}님이 계약품목 수정: {item.model_name or '-'}\n" +
            "\n".join(changed_logs)
        )
        db.add(HistoryLog(project_id=project.id, user_name="시스템 🤖", content=log_content))
        ajax_log = {
            'user_name': '시스템 🤖',
            'content': log_content,
            'created_at': datetime.datetime.now().strftime('%y/%m/%d %H:%M:%S')
        }
    sync_material_orders_for_contract_item(db, con, item)

    result = {'ajax_log': ajax_log}
    if flashes:
        result['flashes'] = flashes
    return result


def handle_add_contract_item(db, project, form, current_user, **ctx):
    contract_id = safe_int(form.get('contract_id'))
    con = db.query(Contract).filter_by(id=contract_id, project_id=project.id).first()
    if not con:
        return {}
    category = normalize_detail_item(
        form.get('category'),
        default=con.item_group or DETAIL_ITEM_OPTIONS[0]
    )
    model_name = (form.get('model_name') or '').strip()
    if not model_name:
        return {'flash': ('모델명을 입력해 주세요.', 'warning')}
    if category != (con.item_group or DETAIL_ITEM_OPTIONS[0]):
        return {'flash': (f"계약[{con.contract_name}]은 품목군 [{con.item_group}]만 추가 가능합니다.", 'warning')}

    new_item = ContractItem(
        contract_id=con.id,
        category=category,
        model_name=model_name,
        quantity=safe_int(form.get('quantity'), 0),
        barcode_id=form.get('barcode_id') if category in LIGHTING_DETAIL_ITEMS else None
    )
    spec = extract_contract_item_spec(form, category)
    missing_spec = validate_contract_item_spec(category, spec)
    if missing_spec:
        return {'flash': (f"필수 스펙 누락: {', '.join(missing_spec)}", 'warning')}
    new_item.item_spec = spec
    db.add(new_item)
    db.add(HistoryLog(
        project_id=project.id,
        user_name="시스템 🤖",
        content=f"{current_user}님이 계약품목 추가: {new_item.category}/{new_item.model_name}({new_item.quantity})"
    ))
    db.flush()
    sync_material_orders_for_contract_item(db, con, new_item)
    return {}


def handle_delete_contract_item(db, project, form, current_user, **ctx):
    item_id = safe_int(form.get('item_id'))
    item = db.query(ContractItem).get(item_id)
    if item:
        con = db.query(Contract).get(item.contract_id)
        if con and con.project_id == project.id:
            db.add(HistoryLog(
                project_id=project.id,
                user_name="시스템 🤖",
                content=f"{current_user}님이 계약품목 삭제: {item.category}/{item.model_name}({item.quantity})"
            ))
            db.query(MaterialOrder).filter(MaterialOrder.contract_item_id == item.id).delete()
            db.delete(item)
    return {}


def handle_delete_material(db, project, form, current_user, **ctx):
    mat = db.query(Material).get(safe_int(form.get('material_id')))
    if mat:
        db.add(HistoryLog(project_id=project.id, user_name="시스템 🤖",
                          content=f"{current_user}님이 품목 삭제: {mat.category}({mat.model_name})"))
        db.delete(mat)
    return {}
