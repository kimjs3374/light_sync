import datetime

from sqlalchemy.orm import joinedload

from modules.models import (
    Contract,
    ContractItem,
    MaterialOrder,
    ProductionDailyLog,
    ProductionProcess,
)


PROD_PROCESS_STATUS = ('대기', '진행중', '완료', '스킵')
READY_MATERIAL_STATUS = '입고완료'


def _is_integrated(item):
    spec = item.item_spec or {}
    body_type = str(spec.get('body_type') or '').strip()
    return bool(spec.get('is_integrated') is True or body_type == '일체형')


def _base_process_template(item):
    category = (item.category or '').strip()
    model_name = (item.model_name or '').strip().upper()
    spec = item.item_spec or {}
    processes = []

    if category in ('투광등기구', 'LED투광등기구'):
        if 'STA' in model_name:
            processes = [
                {'name': '외함제작'},
                {'name': '하우징 히트파이프 조립', 'parent_ref': '외함제작'},
                {'name': '조립부 실리콘작업', 'parent_ref': '외함제작'},
                {'name': '방열핀 적층 프레스작업', 'parent_ref': '외함제작'},
                {'name': '후면 커버 조립', 'parent_ref': '외함제작'},
                {'name': 'PCB 조립'},
                {'name': '렌즈부 조립'},
                {'name': '전면유리커버 조립'},
                {'name': '전면 바이저 조립'},
                {'name': '브라켓 조립'},
                {'name': '포장 및 출고 대기'},
            ]
        elif 'ARENA' in model_name:
            processes = [
                {'name': '히트파이프 조립'},
                {'name': 'PCB 조립'},
                {'name': '렌즈부 조립'},
                {'name': '반사판 조립'},
                {'name': '전면유리 조립'},
                {'name': '브라켓 조립'},
                {'name': '포장 및 출고 대기'},
            ]
        else:  # BATOO 및 기타 모델 fallback
            processes = [
                {'name': 'PCB 조립'},
                {'name': '렌즈 조립'},
                {'name': '전면 유리조립'},
                {'name': '브라켓 조립'},
                {'name': '포장 및 출고 대기'},
            ]
        if _is_integrated(item):
            insert_before_name(processes, '브라켓 조립', {'name': 'SMPS 일체형 조립'})

    elif category in ('가로등기구', '보안등기구', 'LED가로등기구', 'LED보안등기구'):
        processes = [
            {'name': '모듈 조립'},
            {'name': '모듈과 분배기 결선'},
            {'name': '전선 연결'},
            {'name': '포장 및 출고 대기'},
        ]
        if _is_integrated(item):
            insert_before_name(processes, '전선 연결', {'name': 'SMPS 일체형 조립'})

    elif category in ('스텐가로등주', '스테인리스가로등주'):
        skip_models = {
            'MTPS-202-4', 'MTPS-202-5', 'MTPS-202-6',
            'MTPS-203-4', 'MTPS-203-5', 'MTPS-203-6',
        }
        processes = [
            {'name': '파이프 재단 및 가공'},
            {'name': '베이스 및 점검구 용접'},
        ]
        if model_name not in skip_models:
            processes.append({'name': '2단폴 용접'})
        processes.extend([
            {'name': '암대 용접'},
        ])
        finish_type = str(spec.get('stainless_finish_type') or '').strip()
        if finish_type == '광택':
            processes.append({'name': '광택작업'})
        else:
            processes.append({'name': '도장입고'})
        processes.append({'name': '출고대기'})

    elif category == '철제가로등주':
        processes = [
            {'name': '파이프 재단 및 가공'},
            {'name': '베이스 및 점검구 용접'},
            {'name': '2단폴 용접'},
            {'name': '암대 용접'},
            {'name': '도금 입고'},
        ]
        is_painted = bool(spec.get('is_painted'))
        if is_painted:
            processes.extend([
                {'name': '샌딩 작업'},
                {'name': '도장 입고'},
                {'name': '출고 대기'},
            ])
        else:
            processes.append({'name': '출고 대기'})

    elif category == '조명타워':
        if '기초앙카' in (item.model_name or ''):
            processes = [
                {'name': 'L앙카 용접'},
                {'name': '베이스 용접'},
                {'name': '도금 입고'},
                {'name': '출고대기'},
            ]
        else:
            processes = [
                {'name': '플랜지 가접'},
                {'name': '플랜지 및 보강대 용접'},
                {'name': '상부구조물 제작'},
                {'name': '도금 입고'},
                {'name': '출고 대기'},
            ]

    else:
        processes = [
            {'name': '기본 생산 준비'},
            {'name': '본조립'},
            {'name': '포장 및 출고 대기'},
        ]

    normalized = []
    for idx, p in enumerate(processes, start=1):
        normalized.append({
            'process_code': f'P{idx:03d}',
            'process_name': p['name'],
            'step_order': idx,
            'parent_ref': p.get('parent_ref'),
            'is_optional': bool(p.get('is_optional', False)),
        })
    return normalized


def insert_before_name(processes, target_name, new_process):
    for idx, proc in enumerate(processes):
        if proc.get('name') == target_name:
            processes.insert(idx, new_process)
            return
    processes.append(new_process)


def sync_production_processes_for_contract_item(db, contract, item):
    template = _base_process_template(item)
    existing = db.query(ProductionProcess).filter(
        ProductionProcess.contract_item_id == item.id
    ).all()
    existing_map = {p.process_code: p for p in existing}

    target_codes = {p['process_code'] for p in template}
    parent_name_to_code = {p['process_name']: p['process_code'] for p in template}

    for t in template:
        parent_code = parent_name_to_code.get(t.get('parent_ref')) if t.get('parent_ref') else None
        parent = existing_map.get(parent_code) if parent_code else None
        obj = existing_map.get(t['process_code'])
        if obj:
            obj.project_id = contract.project_id
            obj.contract_id = contract.id
            obj.process_name = t['process_name']
            obj.step_order = t['step_order']
            obj.parent_process_id = parent.id if parent else None
            obj.is_optional = t['is_optional']
        else:
            obj = ProductionProcess(
                project_id=contract.project_id,
                contract_id=contract.id,
                contract_item_id=item.id,
                process_code=t['process_code'],
                process_name=t['process_name'],
                step_order=t['step_order'],
                parent_process_id=parent.id if parent else None,
                status='대기',
                progress_qty=0,
                progress_percent=0,
                is_optional=t['is_optional'],
            )
            db.add(obj)
            db.flush()
            existing_map[t['process_code']] = obj

    for old in existing:
        if old.process_code not in target_codes:
            db.query(ProductionDailyLog).filter(
                ProductionDailyLog.production_process_id == old.id
            ).delete()
            db.delete(old)


def sync_production_processes(db, project_id=None):
    q = db.query(Contract).options(joinedload(Contract.items))
    if project_id:
        q = q.filter(Contract.project_id == project_id)

    for contract in q.all():
        for item in contract.items:
            sync_production_processes_for_contract_item(db, contract, item)


def are_materials_ready(item):
    orders = list(item.material_orders or [])
    if not orders:
        return False
    return all((o.order_status or '') == READY_MATERIAL_STATUS for o in orders)


def recompute_process_progress(db, process_obj, item_qty):
    total_qty = db.query(ProductionDailyLog).filter(
        ProductionDailyLog.production_process_id == process_obj.id
    ).with_entities(ProductionDailyLog.daily_qty).all()
    done = sum(int(row[0] or 0) for row in total_qty)
    process_obj.progress_qty = done
    qty = int(item_qty or 0)
    if qty > 0:
        process_obj.progress_percent = round(min(100.0, (done / qty) * 100.0), 2)
    else:
        process_obj.progress_percent = 0.0


def compute_item_production_status(item):
    if not are_materials_ready(item):
        return '자재대기중'

    processes = sorted(item.production_processes or [], key=lambda x: (x.step_order, x.id))
    if not processes:
        return '생산대기중'

    statuses = [(p.status or '대기') for p in processes]
    if all(s in ('완료', '스킵') for s in statuses):
        return '생산완료'
    if any(s in ('진행중', '완료') for s in statuses):
        return '생산중'
    return '생산대기중'


def refresh_production_statuses(db, project_id=None):
    q = db.query(ContractItem).options(
        joinedload(ContractItem.material_orders),
        joinedload(ContractItem.production_processes)
    )
    if project_id:
        q = q.join(Contract).filter(Contract.project_id == project_id)

    for item in q.all():
        target = compute_item_production_status(item)
        if (item.status_prod or '').strip() != target:
            item.status_prod = target


def can_start_process(item, process_obj):
    processes = sorted(item.production_processes or [], key=lambda x: (x.step_order, x.id))
    current_order = process_obj.step_order or 0
    prev = [p for p in processes if (p.step_order or 0) < current_order]
    return all((p.status or '대기') in ('진행중', '완료', '스킵') for p in prev)


def set_process_status(process_obj, new_status):
    new_status = (new_status or '').strip()
    if new_status not in PROD_PROCESS_STATUS:
        return False

    process_obj.status = new_status
    now = datetime.datetime.now()
    if new_status == '진행중' and not process_obj.started_at:
        process_obj.started_at = now
    if new_status in ('완료', '스킵'):
        if not process_obj.started_at:
            process_obj.started_at = now
        if not process_obj.completed_at:
            process_obj.completed_at = now
    if new_status in ('대기', '진행중'):
        process_obj.completed_at = None
    return True
