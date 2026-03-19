"""바코드 CRUD action 핸들러."""
from modules.utils import safe_int
from modules.models import (
    Contract, ContractItem, ContractBarcode,
    LIGHTING_DETAIL_ITEMS,
)
from modules.history_board import append_history_log
from routes.barcode import parse_barcode_xlsx_rows


def handle_update_barcodes_manual(db, project, form, current_user, **ctx):
    item_id = safe_int(form.get('item_id'))
    item = db.query(ContractItem).get(item_id)
    if not item:
        return {}
    con = db.query(Contract).get(item.contract_id)
    if not con or con.project_id != project.id:
        return {}
    if item.category not in LIGHTING_DETAIL_ITEMS:
        return {'flash': ('해당 품목은 바코드 관리 대상이 아닙니다.', 'warning')}

    rows = []
    raw_lines = form.get('barcode_lines', '') or ''
    for line in raw_lines.splitlines():
        code = line.strip()
        if not code:
            continue
        rows.append({
            'barcode': code,
            'site_name': form.get('site_name') or project.temp_name,
            'model_name': form.get('model_name') or item.model_name,
            'producer': form.get('producer') or '',
            'lens_angle': form.get('lens_angle') or '',
            'pcb_spec': form.get('pcb_spec') or '',
            'pcb_cct': form.get('pcb_cct') or '',
            'pcb_chip_spec': form.get('pcb_chip_spec') or '',
            'pcb_mfg_date': form.get('pcb_mfg_date') or '',
            'smps_model': form.get('smps_model') or '',
            'smps_qty': form.get('smps_qty') or '0',
            'smps_setting': form.get('smps_setting') or '',
            'smps_vdc': form.get('smps_vdc') or '',
            'smps_adc': form.get('smps_adc') or '',
            'spacing_distance': form.get('spacing_distance') or '',
            'replaced_from_barcode': form.get('replaced_from_barcode') or '',
            'replaced_reason': form.get('replaced_reason') or '',
        })

    parsed = []
    seen = set()
    for row in rows:
        code = (row.get('barcode') or '').strip()
        if not code or code in seen:
            continue
        seen.add(code)
        parsed.append(row)

    old_count = len(item.barcodes)
    db.query(ContractBarcode).filter_by(contract_item_id=item.id).delete()
    for idx, row in enumerate(parsed, start=1):
        old_code = (row.get('replaced_from_barcode') or '').strip()
        new_code = (row.get('barcode') or '').strip()
        replace_reason = (row.get('replaced_reason') or '').strip()
        db.add(ContractBarcode(
            contract_item_id=item.id,
            barcode=new_code,
            seq=idx,
            site_name=row.get('site_name') or project.temp_name,
            model_name=row.get('model_name') or item.model_name,
            producer=row.get('producer') or '',
            lens_angle=row.get('lens_angle') or '',
            pcb_spec=row.get('pcb_spec') or '',
            pcb_cct=row.get('pcb_cct') or '',
            pcb_chip_spec=row.get('pcb_chip_spec') or '',
            pcb_mfg_date=row.get('pcb_mfg_date') or '',
            smps_model=row.get('smps_model') or '',
            smps_qty=safe_int(row.get('smps_qty'), 0),
            smps_setting=row.get('smps_setting') or '',
            smps_vdc=row.get('smps_vdc') or '',
            smps_adc=row.get('smps_adc') or '',
            spacing_distance=row.get('spacing_distance') or '',
            replaced_from_barcode=old_code or None,
            replaced_reason=replace_reason or None,
            created_by=current_user or '사용자'
        ))
        if old_code and old_code != new_code:
            append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                content=(
                    f"{current_user}님이 바코드 교체: {item.model_name or '-'} "
                    f"{old_code} ➡️ {new_code}" +
                    (f" (사유: {replace_reason})" if replace_reason else "")
                ),
                scope='contract', kind='system')

    item.barcode_id = (parsed[0].get('barcode') if parsed else None)
    append_history_log(db, project_id=project.id, user_name="시스템 🤖",
        content=(
            f"{current_user}님이 바코드 수기 저장: {item.model_name or '-'} "
            f"({old_count}건 ➡️ {len(parsed)}건)"
        ),
        scope='contract', kind='system')
    return {}


def handle_upload_barcodes(db, project, form, current_user, **ctx):
    files = ctx.get('files', {})
    item_id = safe_int(form.get('item_id'))
    item = db.query(ContractItem).get(item_id)
    file = files.get('barcode_file')
    if not item or not file:
        return {}
    con = db.query(Contract).get(item.contract_id)
    if not con or con.project_id != project.id:
        return {}
    if item.category not in LIGHTING_DETAIL_ITEMS:
        return {'flash': ('해당 품목은 바코드 관리 대상이 아닙니다.', 'warning')}

    file_name = (file.filename or '').lower()
    parsed = []
    seen = set()
    if not file_name.endswith('.xlsx'):
        return {'flash': ('업로드는 XLSX 파일만 지원합니다.', 'warning')}

    file.stream.seek(0)
    rows = parse_barcode_xlsx_rows(file)
    for row in rows:
        code = (row.get('barcode') or row.get('바코드번호') or '').strip()
        if not code or code in seen:
            continue
        seen.add(code)
        parsed.append(row)

    old_count = len(item.barcodes)
    db.query(ContractBarcode).filter_by(contract_item_id=item.id).delete()
    for idx, row in enumerate(parsed, start=1):
        new_code = (row.get('barcode') or row.get('바코드번호') or '').strip()
        old_code = (row.get('replaced_from_barcode') or row.get('교체전바코드') or '').strip()
        replace_reason = (row.get('replaced_reason') or row.get('교체사유') or '').strip()
        db.add(ContractBarcode(
            contract_item_id=item.id,
            barcode=new_code,
            seq=idx,
            site_name=(row.get('site_name') or row.get('현장명') or project.temp_name),
            model_name=(row.get('model_name') or row.get('모델명') or item.model_name),
            producer=(row.get('producer') or row.get('생산자') or ''),
            lens_angle=(row.get('lens_angle') or row.get('렌즈각도') or ''),
            pcb_spec=(row.get('pcb_spec') or row.get('PCB사양') or ''),
            pcb_cct=(row.get('pcb_cct') or row.get('색온도') or ''),
            pcb_chip_spec=(row.get('pcb_chip_spec') or row.get('칩사양') or ''),
            pcb_mfg_date=(row.get('pcb_mfg_date') or row.get('제조일자') or ''),
            smps_model=(row.get('smps_model') or row.get('SMPS 모델명') or ''),
            smps_qty=safe_int((row.get('smps_qty') or row.get('SMPS 수량') or '0'), 0),
            smps_setting=(row.get('smps_setting') or row.get('SMPS세팅값') or ''),
            smps_vdc=(row.get('smps_vdc') or row.get('세팅전압(VDC)') or ''),
            smps_adc=(row.get('smps_adc') or row.get('세팅전류(ADC)') or ''),
            spacing_distance=(row.get('spacing_distance') or row.get('이격거리') or ''),
            replaced_from_barcode=old_code or None,
            replaced_reason=replace_reason or None,
            created_by=current_user or '사용자'
        ))
        if old_code and old_code != new_code:
            append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                content=(
                    f"{current_user}님이 바코드 교체: {item.model_name or '-'} "
                    f"{old_code} ➡️ {new_code}" +
                    (f" (사유: {replace_reason})" if replace_reason else "")
                ),
                scope='contract', kind='system')

    item.barcode_id = ((parsed[0].get('barcode') or parsed[0].get('바코드번호')) if parsed else None)
    append_history_log(db, project_id=project.id, user_name="시스템 🤖",
        content=(
            f"{current_user}님이 바코드 파일 업로드: {item.model_name or '-'} "
            f"({old_count}건 ➡️ {len(parsed)}건)"
        ),
        scope='contract', kind='system')
    return {}


def handle_delete_barcode(db, project, form, current_user, **ctx):
    barcode_id = safe_int(form.get('barcode_id'))
    bc = db.query(ContractBarcode).get(barcode_id)
    if bc:
        item = db.query(ContractItem).get(bc.contract_item_id)
        if item:
            con = db.query(Contract).get(item.contract_id)
            if con and con.project_id == project.id:
                del_code = bc.barcode
                db.delete(bc)
                db.flush()
                first_bc = db.query(ContractBarcode).filter_by(contract_item_id=item.id).order_by(ContractBarcode.seq.asc()).first()
                item.barcode_id = first_bc.barcode if first_bc else None
                append_history_log(db, project_id=project.id, user_name="시스템 🤖",
                    content=f"{current_user}님이 바코드 삭제: {item.model_name or '-'} / {del_code}",
                    scope='contract', kind='system')
    return {}


def handle_update_barcode_meta(db, project, form, current_user, **ctx):
    barcode_id = safe_int(form.get('barcode_id'))
    bc = db.query(ContractBarcode).get(barcode_id)
    if not bc:
        return {}
    item = db.query(ContractItem).get(bc.contract_item_id)
    if not item:
        return {}
    con = db.query(Contract).get(item.contract_id)
    if not con or con.project_id != project.id:
        return {}

    old_code = bc.barcode
    new_code = (form.get('barcode') or '').strip()
    replaced_from = (form.get('replaced_from_barcode') or '').strip()
    replaced_reason = (form.get('replaced_reason') or '').strip()

    bc.barcode = new_code or bc.barcode
    bc.site_name = form.get('site_name') or bc.site_name
    bc.model_name = form.get('model_name') or bc.model_name
    bc.producer = form.get('producer') or ''
    bc.lens_angle = form.get('lens_angle') or ''
    bc.pcb_spec = form.get('pcb_spec') or ''
    bc.pcb_cct = form.get('pcb_cct') or ''
    bc.pcb_chip_spec = form.get('pcb_chip_spec') or ''
    bc.pcb_mfg_date = form.get('pcb_mfg_date') or ''
    bc.smps_model = form.get('smps_model') or ''
    bc.smps_qty = safe_int(form.get('smps_qty'), 0)
    bc.smps_setting = form.get('smps_setting') or ''
    bc.smps_vdc = form.get('smps_vdc') or ''
    bc.smps_adc = form.get('smps_adc') or ''
    bc.spacing_distance = form.get('spacing_distance') or ''
    bc.replaced_from_barcode = replaced_from or None
    bc.replaced_reason = replaced_reason or None

    if replaced_from and replaced_from != bc.barcode:
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
            content=(
                f"{current_user}님이 바코드 교체: {item.model_name or '-'} "
                f"{replaced_from} ➡️ {bc.barcode}" +
                (f" (사유: {replaced_reason})" if replaced_reason else "")
            ),
            scope='contract', kind='system')
    elif old_code != bc.barcode:
        append_history_log(db, project_id=project.id, user_name="시스템 🤖",
            content=f"{current_user}님이 바코드 수정: {item.model_name or '-'} {old_code} ➡️ {bc.barcode}",
            scope='contract', kind='system')
    return {}
