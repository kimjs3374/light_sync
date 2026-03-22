from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from modules.auth_decorators import login_required, menu_required
import datetime
from modules.db_context import get_db
from modules.utils import safe_int
from modules.models import (
    Project, Contract, ContractItem,
    DETAIL_ITEM_OPTIONS, normalize_detail_item
)
from modules.history_board import append_history_log
from modules.kakaowork_notifier import post_contract_summary

contract_bp = Blueprint('contract', __name__)

@contract_bp.route('/contract_create', methods=['GET', 'POST'])
@login_required
@menu_required('contract')
def contract_create():
    if session.get('user_group') == '생산부':
        flash('생산부는 계약 현장 등록 권한이 없습니다.', 'danger')
        return redirect(url_for('project.contract_list'))
    with get_db() as db:
        if request.method == 'POST':
            try:
                year = str(datetime.date.today().year)
                count = db.query(Project).filter(Project.project_no.like(f"{year}-%")).count()
                site_addr = request.form.get('site_address')
                is_same = request.form.get('is_shipping_same') == '1'
                new_p = Project(
                    project_no=f"{year}-{(count + 1):03d}",
                    temp_name=request.form.get('temp_name'),
                    short_name=request.form.get('short_name'),
                    site_address=site_addr,
                    shipping_address=site_addr if is_same else request.form.get('shipping_address'),
                    is_shipping_same=is_same,
                    is_contracted=True,
                    design_basis=request.form.get('design_basis'),
                    work_path=request.form.get('work_path')
                )
                db.add(new_p); db.flush()

                created_contract_count = 0
                for i in range(1, 10):
                    c_name = request.form.get(f'contract_name_{i}')
                    if not c_name: continue

                    item_group = normalize_detail_item(
                        request.form.get(f'item_group_{i}'),
                        default=DETAIL_ITEM_OPTIONS[0]
                    )

                    c_date_raw = request.form.get(f'contract_date_{i}')
                    d_due_raw = request.form.get(f'delivery_due_{i}')
                    if not c_date_raw or not d_due_raw:
                        raise ValueError(f"{i}번 계약의 계약일/납품기일을 입력해 주세요.")

                    g2b_no = request.form.get(f'g2b_contract_no_{i}', '').strip() or None

                    new_c = Contract(
                        project_id=new_p.id, contract_name=c_name,
                        item_group=item_group,
                        contract_date=datetime.datetime.strptime(c_date_raw, '%Y-%m-%d').date(),
                        delivery_due_date=datetime.datetime.strptime(d_due_raw, '%Y-%m-%d').date(),
                        desired_delivery_date=(
                            datetime.datetime.strptime(request.form.get(f'desired_delivery_{i}'), '%Y-%m-%d').date()
                            if request.form.get(f'desired_delivery_{i}') else None
                        ),
                        is_prof_inspection=request.form.get(f'is_prof_{i}') == '1',
                        is_urgent_prod=request.form.get(f'is_urgent_{i}') == '1',
                        g2b_contract_no=g2b_no,
                    )
                    db.add(new_c); db.flush()
                    cats = request.form.getlist(f'item_category_{i}[]')
                    mods = request.form.getlist(f'item_model_{i}[]')
                    qtys = request.form.getlist(f'item_qty_{i}[]')

                    has_item = False
                    for cat, mod, qty in zip(cats, mods, qtys):
                        if mod.strip():
                            normalized_cat = normalize_detail_item(cat, default=DETAIL_ITEM_OPTIONS[0])
                            if normalized_cat != item_group:
                                raise ValueError(f"{i}번 계약은 품목군[{item_group}]만 등록할 수 있습니다. 입력[{normalized_cat}]")
                            db.add(ContractItem(contract_id=new_c.id, category=item_group, model_name=mod, quantity=safe_int(qty)))
                            has_item = True

                    if not has_item:
                        raise ValueError(f"{i}번 계약에 최소 1개 품목을 입력해 주세요.")

                    created_contract_count += 1

                if created_contract_count == 0:
                    raise ValueError("최소 1개 계약을 입력해 주세요.")

                append_history_log(
                    db,
                    project_id=new_p.id,
                    user_name="시스템 🤖",
                    content=f"{session.get('full_name')}님이 계약현장을 직접 등록하였습니다. (품목군 단일 규칙 적용)",
                    scope='contract',
                    kind='system'
                )

                created_contracts = list(new_p.contracts)
                db.commit()

                notify_ok, notify_msg, _ = post_contract_summary(new_p, created_contracts)
                if not notify_ok:
                    flash(f"계약은 등록되었지만 카카오워크 알림은 실패했습니다: {notify_msg}", "warning")

                return redirect(url_for('project.contract_list'))
            except Exception as e:
                db.rollback()
                current_app.logger.exception('contract_create failed')
                flash('등록 처리 중 오류가 발생했습니다.', 'danger')
        return render_template('contract_create.html', detail_item_options=DETAIL_ITEM_OPTIONS)

# 계약 리스트/상세는 project_bp에서 단일 처리 (중복 라우팅 방지)