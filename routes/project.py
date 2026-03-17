from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, Response
import datetime
import csv
import io
import re
import zipfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from sqlalchemy.orm import joinedload
from modules.models import (
    SessionLocal, Project, Material, MaterialOrder, HistoryLog, SportsModule, Contact, Contract, ContractItem, ContractBarcode,
    ProjectDeleteRequest, ProjectPriorityOverride, UserPriorityPermission,
    Drawing, DrawingVersion,
    DETAIL_ITEM_OPTIONS, LIGHTING_DETAIL_ITEMS, normalize_detail_item, DRAWING_TYPE_OPTIONS,
    CONTRACT_ITEM_SPEC_SCHEMA
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
from modules.production_logic import refresh_production_statuses
from modules.storage_adapter import is_storage_enabled, delete_prefix

SALES_STATUS_STEPS = ['계약확인', '상세협의중', '협의완료']
ADMIN_STATUS_STEPS = ['자재확인중', '발주진행중', '발주완료', '입고진행중', '입고완료']
PROD_STATUS_STEPS = ['자재대기중', '생산대기중', '생산중', '생산완료']
TRUE_VALUES = {'1', 'true', 'True', 'on', 'yes', 'Y'}

project_bp = Blueprint('project', __name__)

BASE_DIR = Path(__file__).resolve().parents[1]


def _is_true_value(value):
    return str(value).strip() in TRUE_VALUES


def _extract_contract_item_spec(form, category):
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    req = schema.get('required', [])
    cond_req = schema.get('conditional_required', {})

    spec = {}

    for field in req:
        raw = form.get(f'spec_{field}')
        if isinstance(raw, str):
            raw = raw.strip()
        spec[field] = raw

    for trigger, rule in cond_req.items():
        current = spec.get(trigger)
        expected = rule.get('equals')
        if isinstance(expected, bool):
            current_cmp = _is_true_value(current)
        else:
            current_cmp = current
        if current_cmp == expected:
            for field in rule.get('fields', []):
                raw = form.get(f'spec_{field}')
                if isinstance(raw, str):
                    raw = raw.strip()
                spec[field] = raw

    for key, val in list(spec.items()):
        if key in ('has_stabilizer_box', 'is_integrated', 'is_painted'):
            spec[key] = _is_true_value(val)
        elif key == 'lamp_count':
            spec[key] = _to_int(val, 0)
        elif val is None:
            spec[key] = ''

    return spec


def _validate_contract_item_spec(category, spec):
    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    schema = CONTRACT_ITEM_SPEC_SCHEMA.get(category, {})
    req = schema.get('required', [])
    cond_req = schema.get('conditional_required', {})

    missing = []
    for field in req:
        value = spec.get(field)
        if value in (None, '', []):
            missing.append(field)

    for trigger, rule in cond_req.items():
        current = spec.get(trigger)
        expected = rule.get('equals')
        if current == expected:
            for field in rule.get('fields', []):
                value = spec.get(field)
                if value in (None, '', []):
                    missing.append(field)

    return missing


def _format_spec_summary(category, spec):
    if not isinstance(spec, dict) or not spec:
        return '-'

    category = normalize_detail_item(category, default=DETAIL_ITEM_OPTIONS[0])
    if category == '투광등기구':
        return f"렌즈:{spec.get('lens_angle') or '-'}, 이격:{spec.get('spacing_distance') or '-'}"
    if category in ('가로등기구', '보안등기구', '터널등기구'):
        return f"이격:{spec.get('spacing_distance') or '-'}, 일체형:{'예' if spec.get('is_integrated') else '아니오'}"
    if category == '조명타워':
        return f"높이:{spec.get('tower_height') or '-'}, 등수:{spec.get('lamp_count') or 0}"
    if category in ('철제가로등주', '스텐가로등주'):
        return f"앙카:{spec.get('anchor_spacing') or '-'}, 암대:{spec.get('arm_type') or '-'}"
    return '-'


def _is_pristine_material_order(order):
    out_status = (order.outsourcing_status or '').strip()
    out_default = out_status in ('', '외주입고대기')
    note_empty = not (order.note or '').strip()
    return (
        (order.order_status or '발주대기') == '발주대기'
        and order.order_date is None
        and order.expected_in_date is None
        and not bool(order.in_confirmed)
        and note_empty
        and out_default
    )


def _compute_admin_status_from_orders(orders):
    orders = list(orders or [])
    if not orders:
        return '자재확인중'

    statuses = [(o.order_status or '발주대기') for o in orders]
    outsourced = [o for o in orders if o.is_outsourcing]

    all_pristine = all(_is_pristine_material_order(o) for o in orders)
    if all_pristine:
        return '자재확인중'

    all_in_done = all(s == '입고완료' for s in statuses)
    all_out_done = all((o.outsourcing_status or '') == '본사입고완료' for o in outsourced) if outsourced else True
    if all_in_done and all_out_done:
        return '입고완료'

    all_order_done_only = all(s == '발주완료' for s in statuses)
    if all_order_done_only:
        if (not outsourced) or any((o.outsourcing_status or '') != '본사입고완료' for o in outsourced):
            return '입고진행중'
        return '발주완료'

    if all(s in ('발주완료', '입고완료') for s in statuses):
        return '입고진행중'

    return '발주진행중'


def _refresh_admin_statuses_from_material_orders(db, project_id=None):
    q = db.query(ContractItem).options(
        joinedload(ContractItem.material_orders),
        joinedload(ContractItem.contract)
    )
    if project_id:
        q = q.join(Contract).filter(Contract.project_id == project_id)

    items = q.all()
    for item in items:
        computed = _compute_admin_status_from_orders(item.material_orders)
        if item.status_admin != computed:
            item.status_admin = computed
    refresh_production_statuses(db, project_id=project_id)


@project_bp.route('/barcode_template')
def download_barcode_template():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    headers = [
        'barcode', '현장명', '모델명', '생산자', '렌즈각도',
        'PCB사양', '색온도', '칩사양', '제조일자',
        'SMPS 모델명', 'SMPS 수량', 'SMPS세팅값',
        '세팅전압(VDC)', '세팅전류(ADC)', '이격거리',
        '교체전바코드', '교체사유'
    ]
    sample_row = [
        'BC-2026-0001', '샘플현장', 'LGT-500W-A', '홍길동', '90도',
        'PCB-X1', '5700K', 'Chip-3030', '26/03/03',
        'SMPS-600W', '1', '기본세팅',
        '48', '10.5', '2.5m',
        '', ''
    ]

    xlsx_data = _build_simple_xlsx([headers, sample_row])

    return Response(
        xlsx_data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': 'attachment; filename=barcode_upload_template.xlsx'
        }
    )

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_to_dt_start(d):
    if not d:
        return None
    return datetime.datetime.combine(d, datetime.time.min)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _remove_project_drawing_storage(project_id):
    if is_storage_enabled():
        try:
            delete_prefix(f"storage/drawings/project_{project_id}")
        except Exception:
            pass

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


def _parse_barcode_csv_rows(file_storage):
    data = file_storage.read()
    text_data = ''
    for enc in ('utf-8-sig', 'cp949', 'euc-kr', 'utf-8'):
        try:
            text_data = data.decode(enc)
            break
        except Exception:
            continue
    if not text_data:
        return []

    reader = csv.DictReader(io.StringIO(text_data))
    rows = []
    for r in reader:
        if not r:
            continue
        rows.append({(k or '').strip(): (v or '').strip() for k, v in r.items()})
    return rows


def _col_to_letters(n):
    letters = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xml_escape(v):
    s = '' if v is None else str(v)
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;'))


def _build_simple_xlsx(rows):
    content_types = """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>
  <Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
  <Override PartName='/xl/styles.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'/>
</Types>"""

    rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>
</Relationships>"""

    workbook = """<?xml version='1.0' encoding='UTF-8'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <sheets>
    <sheet name='barcode_template' sheetId='1' r:id='rId1'/>
  </sheets>
</workbook>"""

    workbook_rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>
  <Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles' Target='styles.xml'/>
</Relationships>"""

    styles = """<?xml version='1.0' encoding='UTF-8'?>
<styleSheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <fonts count='1'><font><sz val='11'/><name val='Calibri'/></font></fonts>
  <fills count='1'><fill><patternFill patternType='none'/></fill></fills>
  <borders count='1'><border/></borders>
  <cellStyleXfs count='1'><xf numFmtId='0' fontId='0' fillId='0' borderId='0'/></cellStyleXfs>
  <cellXfs count='1'><xf numFmtId='0' fontId='0' fillId='0' borderId='0' xfId='0'/></cellXfs>
</styleSheet>"""

    row_xml = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{_col_to_letters(c_idx)}{r_idx}"
            v = _xml_escape(value)
            cells.append(f"<c r='{ref}' t='inlineStr'><is><t>{v}</t></is></c>")
        row_xml.append(f"<row r='{r_idx}'>{''.join(cells)}</row>")

    sheet = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        "</worksheet>"
    )

    buff = io.BytesIO()
    with zipfile.ZipFile(buff, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('xl/workbook.xml', workbook)
        zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        zf.writestr('xl/styles.xml', styles)
        zf.writestr('xl/worksheets/sheet1.xml', sheet)
    return buff.getvalue()


def _parse_barcode_xlsx_rows(file_storage):
    raw = file_storage.read()
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rows = []

    def _cell_text(cell, shared):
        c_type = cell.attrib.get('t')
        if c_type == 'inlineStr':
            t = cell.find('x:is/x:t', ns)
            return (t.text or '') if t is not None else ''
        v = cell.find('x:v', ns)
        if v is None or v.text is None:
            return ''
        if c_type == 's':
            try:
                return shared[int(v.text)]
            except Exception:
                return ''
        return v.text

    with zipfile.ZipFile(io.BytesIO(raw), 'r') as zf:
        shared = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            sroot = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in sroot.findall('x:si', ns):
                t = si.find('x:t', ns)
                if t is not None and t.text is not None:
                    shared.append(t.text)
                else:
                    parts = [n.text or '' for n in si.findall('.//x:t', ns)]
                    shared.append(''.join(parts))

        sheet_candidates = [n for n in zf.namelist() if n.startswith('xl/worksheets/') and n.endswith('.xml')]
        if not sheet_candidates:
            return []
        sroot = ET.fromstring(zf.read(sheet_candidates[0]))
        for row in sroot.findall('.//x:sheetData/x:row', ns):
            values = {}
            max_col = 0
            for cell in row.findall('x:c', ns):
                ref = cell.attrib.get('r', '')
                m = re.match(r'([A-Z]+)', ref)
                if not m:
                    continue
                col_letters = m.group(1)
                col_idx = 0
                for ch in col_letters:
                    col_idx = col_idx * 26 + (ord(ch) - ord('A') + 1)
                max_col = max(max_col, col_idx)
                values[col_idx] = _cell_text(cell, shared).strip()

            if max_col == 0:
                continue
            row_list = [values.get(i, '') for i in range(1, max_col + 1)]
            rows.append(row_list)

    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        d = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            d[h] = (row[i] if i < len(row) else '').strip()
        if d:
            result.append(d)
    return result

# -------------------------------------------------------------------
# 1. 영업관리 리스트
# -------------------------------------------------------------------
@project_bp.route('/project_list')
def project_list():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    db = SessionLocal()
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
    db.close()
    return render_template('project_list.html', projects=projects, today=today, priority_projects=priority_projects)

# -------------------------------------------------------------------
# 2. 📋 계약관리 리스트 (실무형 필터/검색 강화)
# -------------------------------------------------------------------
@project_bp.route('/contract_list')
def contract_list():
    if 'user_id' not in session: return redirect(url_for('auth.login'))

    q = (request.args.get('q') or '').strip().lower()
    due_filter = request.args.get('due', 'all')
    inspection_filter = request.args.get('inspection', 'all')
    urgent_filter = request.args.get('urgent', 'all')
    sort_by = request.args.get('sort', 'due_asc')

    db = SessionLocal()
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
                item.status_admin = _compute_admin_status_from_orders(item.material_orders)
                search_pool.append(item.model_name or '')
                search_pool.append(_format_spec_summary(item.category, item.item_spec))

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

    db.close()
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
        format_spec_summary=_format_spec_summary
    )

# -------------------------------------------------------------------
# 2-1. 자재관리 진입 라우트 (사이드바 연동용)
# -------------------------------------------------------------------
def _material_specs_from_contract_item(item):
    category = normalize_detail_item(item.category, default=DETAIL_ITEM_OPTIONS[0])
    model_name = (item.model_name or '').upper()

    if category == '투광등기구':
        if 'STA' in model_name:
            return [
                ('LED', True, '외주입고대기'),
                ('RP', True, '외주입고대기'),
                ('PCB', False, None),
                ('SMPS', False, None),
                ('렌즈', False, None),
                ('외함프레임', False, None),
                ('외함브라켓', False, None),
                ('외함체결부속', False, None),
            ]
        return [
            ('LED', True, '외주입고대기'),
            ('RP', True, '외주입고대기'),
            ('PCB', False, None),
            ('외함', False, None),
            ('SMPS', False, None),
            ('렌즈', False, None),
        ]

    if category in ('가로등기구', '보안등기구', '터널등기구'):
        return [
            ('모듈', False, None),
            ('분배기', False, None),
            ('외함', False, None),
            ('SMPS', False, None),
        ]

    if category == '조명타워':
        specs = [('강관파이프', False, None), ('베이스판', False, None)]
        if '기초앙카' in (item.model_name or ''):
            specs.append(('L앙카', False, None))
        return specs

    if category in ('철제가로등주', '스텐가로등주'):
        return [
            ('파이프', False, None),
            ('베이스판', False, None),
            ('밴딩(암대)', False, None),
            ('부속자재', False, None),
        ]

    return []


def _sync_material_orders_for_contract_item(db, contract, item):
    target_specs = _material_specs_from_contract_item(item)
    target_names = {name for name, _, _ in target_specs}
    existing_orders = db.query(MaterialOrder).filter(MaterialOrder.contract_item_id == item.id).all()
    existing_map = {o.material_name: o for o in existing_orders}

    qty = _to_int(item.quantity, 0)
    for material_name, is_outsourcing, outsourcing_status in target_specs:
        order = existing_map.get(material_name)
        if order:
            order.item_category = item.category
            order.item_model_name = item.model_name
            order.quantity = qty
            order.is_outsourcing = bool(is_outsourcing)
            if not is_outsourcing:
                order.outsourcing_status = None
            elif not order.outsourcing_status:
                order.outsourcing_status = outsourcing_status
            continue

        db.add(MaterialOrder(
            project_id=contract.project_id,
            contract_id=contract.id,
            contract_item_id=item.id,
            item_category=item.category,
            item_model_name=item.model_name,
            material_name=material_name,
            quantity=qty,
            order_status='발주대기',
            is_outsourcing=bool(is_outsourcing),
            outsourcing_status=outsourcing_status if is_outsourcing else None,
        ))

    for old in existing_orders:
        if old.material_name not in target_names:
            db.delete(old)


def _sync_material_orders(db, project_id=None):
    q = db.query(Contract).options(joinedload(Contract.items))
    if project_id:
        q = q.filter(Contract.project_id == project_id)
    contracts = q.all()
    for contract in contracts:
        for item in contract.items:
            _sync_material_orders_for_contract_item(db, contract, item)


@project_bp.route('/material_management', methods=['GET', 'POST'])
def material_management():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    db = SessionLocal()
    current_user = session.get('full_name') or '사용자'

    if request.method == 'POST' and request.form.get('action') == 'sync_material_orders':
        _sync_material_orders(db)
        _refresh_admin_statuses_from_material_orders(db)
        first_order = db.query(MaterialOrder).order_by(MaterialOrder.id.asc()).first()
        if first_order:
            append_history_log(
                db,
                project_id=first_order.project_id,
                user_name='시스템 🤖',
                content=f"{current_user}님이 자재 자동생성/동기화를 실행했습니다.",
                scope='material',
                kind='system'
            )
        db.commit()
        flash('자재 자동생성/동기화가 완료되었습니다.', 'success')
        return redirect(url_for('project.material_management'))

    _sync_material_orders(db)
    _refresh_admin_statuses_from_material_orders(db)
    db.commit()

    q = (request.args.get('q') or '').strip().lower()
    status = request.args.get('status', 'all')
    outsource = request.args.get('outsource', 'all')
    sort_by = request.args.get('sort', 'due_asc')

    projects = db.query(Project).filter(Project.is_contracted.is_(True)).options(
        joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.material_orders),
        joinedload(Project.priority_override),
    ).order_by(Project.id.desc()).all()

    def _match_order(order, project_obj, contract_obj):
        search_pool = ' '.join([
            project_obj.project_no or '',
            project_obj.temp_name or '',
            contract_obj.contract_name or '',
            order.item_category or '',
            order.item_model_name or '',
            order.material_name or '',
            order.order_status or '',
            order.outsourcing_status or ''
        ]).lower()

        if q and q not in search_pool:
            return False
        if status != 'all' and (order.order_status or '') != status:
            return False
        if outsource == 'yes' and not order.is_outsourcing:
            return False
        if outsource == 'no' and order.is_outsourcing:
            return False
        return True

    filtered_projects = []
    total_orders = 0
    filtered_orders = 0
    for p in projects:
        has_any = False
        all_orders_for_project = []
        for c in p.contracts:
            c._matched_items = []
            for item in c.items:
                item.status_admin = _compute_admin_status_from_orders(item.material_orders)
                all_orders_for_project.extend(item.material_orders)
                total_orders += len(item.material_orders)
                item._matched_orders = [o for o in item.material_orders if _match_order(o, p, c)]
                if item._matched_orders:
                    filtered_orders += len(item._matched_orders)
                    c._matched_items.append(item)
                    has_any = True
        if has_any:
            p._purchase_status = _compute_admin_status_from_orders(all_orders_for_project)
            filtered_projects.append(p)

    today = datetime.date.today()
    for p in filtered_projects:
        contracts_sorted = sorted(
            p.contracts,
            key=lambda c: c.delivery_due_date or datetime.date.max
        )
        primary_contract = contracts_sorted[0] if contracts_sorted else None
        p._mat_due_date = primary_contract.delivery_due_date if primary_contract else None
        p._mat_dday = (p._mat_due_date - today).days if p._mat_due_date else None

    if sort_by == 'due_desc':
        filtered_projects.sort(
            key=lambda p: (p._mat_dday is None, -(p._mat_dday if p._mat_dday is not None else -99999))
        )
    elif sort_by == 'created_desc':
        filtered_projects.sort(key=lambda p: p.created_at or datetime.datetime.min, reverse=True)
    else:  # due_asc
        filtered_projects.sort(
            key=lambda p: (p._mat_dday is None, p._mat_dday if p._mat_dday is not None else 99999)
        )

    stats = {
        'total_projects': len(projects),
        'filtered_projects': len(filtered_projects),
        'total_orders': total_orders,
        'filtered_orders': filtered_orders,
    }

    priority_projects = []
    for p in filtered_projects:
        reasons = []
        override = append_manual_priority_reason(reasons, p)
        is_urgent_project = bool(p.is_urgent or any(c.is_urgent_prod for c in (p.contracts or [])))
        matched_item_count = 0
        matched_order_count = 0
        active_order_count = 0

        for c in p.contracts:
            for item in getattr(c, '_matched_items', []):
                orders = list(getattr(item, '_matched_orders', []) or [])
                matched_item_count += 1
                matched_order_count += len(orders)
                active_order_count += sum(1 for order in orders if (order.order_status or '') != '입고완료')

        if is_urgent_project:
            append_priority_reason(reasons, 'urgent')
        append_due_priority_reason(reasons, p._mat_dday, 'material')
        if (p._purchase_status or '') in ('자재확인중', '발주진행중', '입고진행중'):
            append_priority_reason(reasons, 'material_pending', p._purchase_status or '자재확인중')

        if reasons:
            meta_lines = [
                f"조회 품목: {matched_item_count}건 / 조회 자재건: {matched_order_count}건",
                f"미완료 자재건: {active_order_count}건",
                f"계약건 수: {len(p.contracts or [])}건",
            ]
            if override and override.note:
                meta_lines.insert(0, f"수동 사유: {override.note}")
            priority_projects.append(make_priority_entry(
                project_id=p.id,
                project_no=p.project_no,
                title=p.temp_name or '-',
                subtitle=f"현재 자재상태: {p._purchase_status or '-'}",
                detail_url=url_for('project.material_detail', project_id=p.id),
                reasons=reasons,
                dday=p._mat_dday,
                override_note=(override.note if override and override.note else ''),
                meta_lines=meta_lines,
            ))

    priority_projects = sort_priority_entries(priority_projects)

    response = render_template(
        'material_management.html',
        projects=filtered_projects,
        priority_projects=priority_projects,
        stats=stats,
        filters={'q': request.args.get('q', ''), 'status': status, 'outsource': outsource, 'sort': sort_by}
    )
    db.close()
    return response


@project_bp.route('/material_management/<int:project_id>', methods=['GET', 'POST'])
def material_detail(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    db = SessionLocal()
    current_user = session.get('full_name') or '사용자'

    p = db.query(Project).options(
        joinedload(Project.contracts).joinedload(Contract.items).joinedload(ContractItem.material_orders)
    ).get(project_id)

    if not p:
        db.close()
        flash('대상을 찾을 수 없습니다.', 'warning')
        return redirect(url_for('project.material_management'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'sync_material_orders':
            _sync_material_orders(db, project_id)
            _refresh_admin_statuses_from_material_orders(db, project_id)
            append_history_log(
                db,
                project_id=project_id,
                user_name='시스템 🤖',
                content=f"{current_user}님이 자재 자동생성/동기화를 실행했습니다.",
                scope='material',
                kind='system'
            )
            db.commit()
            flash('자재 자동생성/동기화가 완료되었습니다.', 'success')

        elif action == 'update_material_order':
            order_id = int(request.form.get('material_order_id'))
            order = db.query(MaterialOrder).get(order_id)
            if order and order.project_id == project_id:
                old_status = order.order_status or '발주대기'
                old_out = order.outsourcing_status or '-'

                order.order_date = _parse_date(request.form.get('order_date'))
                order.expected_in_date = _parse_date(request.form.get('expected_in_date'))
                in_confirmed_date = _parse_date(request.form.get('in_confirmed_date'))
                order.note = request.form.get('note')

                new_status = request.form.get('order_status') or old_status
                if new_status in ('발주대기', '발주완료', '입고완료'):
                    order.order_status = new_status

                if order.is_outsourcing:
                    new_out = request.form.get('outsourcing_status')
                    if new_out in ('외주입고대기', '외주입고', '가공중', '본사입고완료'):
                        order.outsourcing_status = new_out
                        if new_out == '본사입고완료':
                            order.order_status = '입고완료'
                            order.in_confirmed = True
                            order.in_confirmed_at = datetime.datetime.now()

                in_confirmed = request.form.get('in_confirmed') == 'on'
                order.in_confirmed = in_confirmed
                if in_confirmed:
                    order.order_status = '입고완료'
                    if in_confirmed_date:
                        order.in_confirmed_at = _date_to_dt_start(in_confirmed_date)
                    elif not order.in_confirmed_at:
                        order.in_confirmed_at = datetime.datetime.now()
                else:
                    order.in_confirmed_at = None

                if order.order_status == '발주완료' and not order.order_date:
                    order.order_date = datetime.date.today()

                append_history_log(
                    db,
                    project_id=order.project_id,
                    user_name='시스템 🤖',
                    content=(
                        f"{current_user}님이 자재상태 수정: {order.item_model_name or '-'} / {order.material_name}"
                        f"\n상태: {old_status} ➡️ {order.order_status}"
                        f"\n외주: {old_out} ➡️ {order.outsourcing_status or '-'}"
                    ),
                    scope='material',
                    kind='system'
                )
                _refresh_admin_statuses_from_material_orders(db, project_id)
                db.commit()
                flash('자재 정보가 저장되었습니다.', 'success')

        elif action == 'bulk_update_material_orders':
            raw_ids = request.form.getlist('selected_order_ids')
            selected_ids = []
            for v in raw_ids:
                if (v or '').isdigit():
                    selected_ids.append(int(v))
            selected_ids = sorted(set(selected_ids))

            if not selected_ids:
                flash('일괄적용할 자재를 선택해 주세요.', 'warning')
            else:
                orders = db.query(MaterialOrder).filter(
                    MaterialOrder.project_id == project_id,
                    MaterialOrder.id.in_(selected_ids)
                ).all()

                bulk_status = request.form.get('bulk_order_status') or ''
                bulk_order_date = _parse_date(request.form.get('bulk_order_date'))
                bulk_expected_in_date = _parse_date(request.form.get('bulk_expected_in_date'))
                bulk_in_confirmed = request.form.get('bulk_in_confirmed') or ''  # '', 'yes', 'no'
                bulk_in_confirmed_date = _parse_date(request.form.get('bulk_in_confirmed_date'))
                bulk_outsourcing_status = request.form.get('bulk_outsourcing_status') or ''
                bulk_note_mode = request.form.get('bulk_note_mode') or 'append'  # append|replace
                bulk_note_text = (request.form.get('bulk_note_text') or '').strip()

                valid_statuses = {'발주대기', '발주완료', '입고완료'}
                valid_out_statuses = {'외주입고대기', '외주입고', '가공중', '본사입고완료'}

                updated_count = 0
                skip_outsource_count = 0
                for order in orders:
                    changed = False

                    if bulk_status in valid_statuses and order.order_status != bulk_status:
                        order.order_status = bulk_status
                        changed = True

                    if bulk_order_date and order.order_date != bulk_order_date:
                        order.order_date = bulk_order_date
                        changed = True

                    if bulk_expected_in_date and order.expected_in_date != bulk_expected_in_date:
                        order.expected_in_date = bulk_expected_in_date
                        changed = True

                    if bulk_outsourcing_status in valid_out_statuses:
                        if order.is_outsourcing:
                            if order.outsourcing_status != bulk_outsourcing_status:
                                order.outsourcing_status = bulk_outsourcing_status
                                changed = True
                            if bulk_outsourcing_status == '본사입고완료':
                                if order.order_status != '입고완료':
                                    order.order_status = '입고완료'
                                    changed = True
                                if not order.in_confirmed:
                                    order.in_confirmed = True
                                    changed = True
                                if not order.in_confirmed_at:
                                    order.in_confirmed_at = datetime.datetime.now()
                                    changed = True
                        else:
                            skip_outsource_count += 1

                    if bulk_in_confirmed == 'yes':
                        if not order.in_confirmed:
                            order.in_confirmed = True
                            changed = True
                        if order.order_status != '입고완료':
                            order.order_status = '입고완료'
                            changed = True
                        target_confirm_dt = _date_to_dt_start(bulk_in_confirmed_date) if bulk_in_confirmed_date else datetime.datetime.now()
                        if order.in_confirmed_at != target_confirm_dt:
                            order.in_confirmed_at = target_confirm_dt
                            changed = True
                    elif bulk_in_confirmed == 'no':
                        if order.in_confirmed:
                            order.in_confirmed = False
                            changed = True
                        if order.in_confirmed_at is not None:
                            order.in_confirmed_at = None
                            changed = True

                    if bulk_note_text:
                        if bulk_note_mode == 'replace':
                            if (order.note or '') != bulk_note_text:
                                order.note = bulk_note_text
                                changed = True
                        else:
                            merged = f"{order.note}\n{bulk_note_text}".strip() if order.note else bulk_note_text
                            if (order.note or '') != merged:
                                order.note = merged
                                changed = True

                    if order.order_status == '발주완료' and not order.order_date:
                        order.order_date = datetime.date.today()
                        changed = True

                    if changed:
                        updated_count += 1

                if updated_count:
                    _refresh_admin_statuses_from_material_orders(db, project_id)
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name='시스템 🤖',
                        content=(
                            f"{current_user}님이 자재 {updated_count}건 일괄적용"
                            f" (선택 {len(selected_ids)}건"
                            f"{', 외주미대상 ' + str(skip_outsource_count) + '건 스킵' if skip_outsource_count else ''})"
                        ),
                        scope='material',
                        kind='system'
                    )
                    db.commit()
                    flash(f'일괄적용 완료: {updated_count}건 반영', 'success')
                else:
                    flash('변경된 내용이 없습니다. 적용값을 확인해 주세요.', 'info')

        elif action == 'add_chat':
            msg = (request.form.get('chat_message') or '').strip()
            if msg:
                append_history_log(
                    db,
                    project_id=project_id,
                    user_name=current_user,
                    content=msg,
                    scope='material',
                    kind='comment'
                )
                db.commit()

        elif action == 'add_history_reply':
            parent_id_raw = request.form.get('parent_log_id')
            reply_message = (request.form.get('reply_message') or '').strip()
            if parent_id_raw and reply_message:
                parent = db.query(HistoryLog).get(int(parent_id_raw))
                if parent and parent.project_id == project_id:
                    origin_full = (parent.content or '').strip()
                    origin_snapshot = origin_full[:220] + '...' if len(origin_full) > 220 else origin_full
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name=current_user,
                        content=reply_message,
                        scope='material',
                        kind='reply',
                        parent_log_id=parent.id,
                        root_log_id=parent.root_log_id or parent.id,
                        origin_snapshot=origin_snapshot
                    )
                    db.commit()

        return redirect(url_for('project.material_detail', project_id=project_id))

    _sync_material_orders(db, project_id)
    _refresh_admin_statuses_from_material_orders(db, project_id)
    db.commit()

    history, history_counts = get_project_history_context(
        db,
        project_id=project_id,
        default_scope='material',
        limit=300
    )

    response = render_template(
        'material_detail.html',
        project=p,
        history=history,
        history_counts=history_counts,
        today=datetime.date.today(),
    )
    db.close()
    return response

# -------------------------------------------------------------------
# 3. 영업 현장 등록 (원본 로직 유지)
# -------------------------------------------------------------------
@project_bp.route('/project_create', methods=['GET', 'POST'])
def project_create():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if _is_prod_group():
        flash('생산부는 설계 현장 등록 권한이 없습니다.', 'danger')
        return redirect(url_for('project.project_list'))
    db = SessionLocal()
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
                expected_contract_date=_parse_date(request.form.get('expected_contract_date'))
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
            db.rollback(); flash(f"등록 실패: {e}", "danger")
    db.close()
    return render_template('project_create.html', detail_item_options=DETAIL_ITEM_OPTIONS)

# -------------------------------------------------------------------
# 4. 상세 페이지 통합 처리 (로그 기능 및 수정 로직 완벽 복구)
# -------------------------------------------------------------------
@project_bp.route('/project_detail/<int:project_id>', methods=['GET', 'POST'])
def project_detail(project_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    return handle_detail_common(project_id, 'project_detail.html')

@project_bp.route('/contract_detail/<int:project_id>', methods=['GET', 'POST'])
def contract_detail(project_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    return handle_detail_common(project_id, 'contract_detail.html')

def handle_detail_common(project_id, template_name):
    db = SessionLocal()
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
        
        # 💡 사장님 요청 기능 1: 설계 기준 수정 로그 (A -> B)
        if action == 'update_design_basis':
            old_basis = p.design_basis or '미입력'
            new_basis = request.form.get('design_basis')
            reason = request.form.get('edit_reason')
            if old_basis != new_basis:
                db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖", 
                                  content=f"{current_user}님이 설계기준 수정 (사유: {reason})\n변경 전: {old_basis}"))
                p.design_basis = new_basis

        # 💡 현장 기본 정보 수정
        elif action == 'update_project':
            old_info = f"현장명:{p.temp_name}, 주소:{p.site_address or '-'}, 납품:{p.shipping_address or '-'}, 계약예정일:{p.expected_contract_date or '-'}"
            p.temp_name = request.form.get('temp_name')
            p.short_name = request.form.get('short_name', p.short_name)
            p.site_address = request.form.get('site_address')
            p.shipping_address = request.form.get('shipping_address')
            p.site_memo = request.form.get('site_memo')
            p.expected_contract_date = _parse_date(request.form.get('expected_contract_date'))
            if 'is_urgent' in request.form:
                p.is_urgent = request.form.get('is_urgent') == '1'
            new_info = f"현장명:{p.temp_name}, 주소:{p.site_address or '-'}, 납품:{p.shipping_address or '-'}, 계약예정일:{p.expected_contract_date or '-'}"
            if old_info != new_info:
                db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖",
                                  content=f"{current_user}님이 전체 정보 수정\n변경 전: {old_info}\n변경 후: {new_info}"))

        elif action == 'update_priority_override':
            if not can_manage_priority:
                flash('우선순위 지정 권한이 없습니다.', 'danger')
            else:
                priority_mode = (request.form.get('priority_mode') or 'set').strip()
                note = (request.form.get('priority_note') or '').strip()
                override = db.query(ProjectPriorityOverride).filter(ProjectPriorityOverride.project_id == project_id).first()

                if priority_mode == 'clear':
                    if override and override.is_active:
                        old_note = override.note or ''
                        override.is_active = False
                        override.note = None
                        override.set_by_user_id = session.get('user_id')
                        override.set_by_name = current_user or '사용자'
                        db.add(HistoryLog(
                            project_id=project_id,
                            user_name="시스템 🤖",
                            content=f"{current_user}님이 수동 우선순위 해제" + (f"\n이전 사유: {old_note}" if old_note else "")
                        ))
                        flash('수동 우선순위가 해제되었습니다.', 'success')
                    else:
                        flash('설정된 수동 우선순위가 없습니다.', 'info')
                else:
                    is_new = override is None
                    if is_new:
                        override = ProjectPriorityOverride(project_id=project_id)
                        db.add(override)
                    override.is_active = True
                    override.note = note or None
                    override.set_by_user_id = session.get('user_id')
                    override.set_by_name = current_user or '사용자'
                    db.add(HistoryLog(
                        project_id=project_id,
                        user_name="시스템 🤖",
                        content=(
                            f"{current_user}님이 수동 우선순위 {'지정' if is_new or not get_active_priority_override(p) else '수정'}"
                            + (f"\n사유: {note}" if note else "")
                        )
                    ))
                    flash('수동 우선순위가 저장되었습니다.', 'success')

        # 💡 작업 경로 업데이트 로그
        elif action == 'update_work_path':
            new_path = request.form.get('work_path')
            if p.work_path != new_path:
                db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖", 
                                  content=f"{current_user}님이 작업경로 업데이트: {new_path}"))
                p.work_path = new_path

        # 💡 품목 수정 로그 (기존 ➡️ 변경)
        elif action == 'update_material':
            mat = db.query(Material).get(int(request.form.get('material_id')))
            if mat:
                old_info = f"{mat.category}/{mat.model_name}({mat.quantity})"
                new_cat = normalize_detail_item(request.form.get('category'), default=mat.category or DETAIL_ITEM_OPTIONS[0])
                new_m, new_q = request.form.get('model_name'), request.form.get('quantity')
                new_barcode = request.form.get('barcode_id')
                if mat.category != new_cat or mat.model_name != new_m or mat.quantity != new_q:
                    db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖", 
                                      content=f"{current_user}님이 품목 수정\n변경 전: {old_info} ➡️ 변경 후: {new_cat}/{new_m}({new_q})"))
                    mat.category, mat.model_name, mat.quantity = new_cat, new_m, new_q
                # 계약 상세에서 전달되는 바코드 반영
                if new_barcode is not None and mat.barcode_id != new_barcode:
                    mat.barcode_id = new_barcode
                
                # 계약관리 상태 업데이트
                if "contract" in template_name:
                    for dept, col in [('영업', 'status_sales'), ('관리', 'status_admin'), ('생산', 'status_prod')]:
                        if user_group == f"{dept}부" or session.get('role') == 'admin':
                            setattr(mat, col, request.form.get(col))

        # 💡 계약 정보 수정
        elif action == 'update_contract':
            contract_id = int(request.form.get('contract_id'))
            con = db.query(Contract).filter_by(id=contract_id, project_id=project_id).first()
            if con:
                old_info = (
                    f"계약명:{con.contract_name}, 품목군:{con.item_group}, 계약일:{con.contract_date}, "
                    f"납품기일:{con.delivery_due_date}, 납품희망일:{con.desired_delivery_date}, "
                    f"전문검수:{con.is_prof_inspection}, 긴급제작:{con.is_urgent_prod}"
                )
                con.contract_name = request.form.get('contract_name') or con.contract_name
                con.item_group = normalize_detail_item(
                    request.form.get('item_group'),
                    default=con.item_group or DETAIL_ITEM_OPTIONS[0]
                )
                con.contract_date = _parse_date(request.form.get('contract_date')) or con.contract_date
                con.delivery_due_date = _parse_date(request.form.get('delivery_due_date')) or con.delivery_due_date
                con.desired_delivery_date = _parse_date(request.form.get('desired_delivery_date'))
                con.is_prof_inspection = request.form.get('is_prof_inspection') == '1'
                con.is_urgent_prod = request.form.get('is_urgent_prod') == '1'
                # 계약 단일 상세품목 규칙: 계약 품목군이 바뀌면 하위 품목군도 일괄 정합
                for item in con.items:
                    item.category = con.item_group
                new_info = (
                    f"계약명:{con.contract_name}, 품목군:{con.item_group}, 계약일:{con.contract_date}, "
                    f"납품기일:{con.delivery_due_date}, 납품희망일:{con.desired_delivery_date}, "
                    f"전문검수:{con.is_prof_inspection}, 긴급제작:{con.is_urgent_prod}"
                )
                if old_info != new_info:
                    log_content = f"{current_user}님이 계약정보 수정\n변경 전: {old_info}\n변경 후: {new_info}"
                    db.add(HistoryLog(
                        project_id=project_id,
                        user_name="시스템 🤖",
                        content=log_content
                    ))
                    ajax_log_entry = {
                        'user_name': '시스템 🤖',
                        'content': log_content,
                        'created_at': datetime.datetime.now().strftime('%y/%m/%d %H:%M:%S')
                    }

        # 💡 계약 추가
        elif action == 'add_contract':
            contract_name = (request.form.get('contract_name') or '').strip()
            item_group = normalize_detail_item(request.form.get('item_group'), default=DETAIL_ITEM_OPTIONS[0])
            contract_date = _parse_date(request.form.get('contract_date')) or datetime.date.today()
            delivery_due_date = _parse_date(request.form.get('delivery_due_date')) or (datetime.date.today() + datetime.timedelta(days=30))

            if not contract_name:
                flash('계약명을 입력해 주세요.', 'warning')
            else:
                new_contract = Contract(
                    project_id=project_id,
                    contract_name=contract_name,
                    item_group=item_group,
                    contract_date=contract_date,
                    delivery_due_date=delivery_due_date,
                    desired_delivery_date=_parse_date(request.form.get('desired_delivery_date')),
                    is_prof_inspection=request.form.get('is_prof_inspection') == '1',
                    is_urgent_prod=request.form.get('is_urgent_prod') == '1'
                )
                db.add(new_contract)
                db.flush()
                db.add(HistoryLog(
                    project_id=project_id,
                    user_name="시스템 🤖",
                    content=f"{current_user}님이 계약 추가: {new_contract.contract_name} / 품목군:{new_contract.item_group}"
                ))

        # 💡 계약 품목 수정
        elif action == 'update_contract_item':
            item_id = int(request.form.get('item_id'))
            item = db.query(ContractItem).get(item_id)
            if item:
                con = db.query(Contract).get(item.contract_id)
                if con and con.project_id == project_id:
                    old_info = f"{item.category}/{item.model_name}({item.quantity})"
                    old_spec_summary = _format_spec_summary(item.category, item.item_spec)
                    old_sales_status = item.status_sales or '계약확인'
                    old_admin_status = item.status_admin or '자재확인중'
                    old_prod_status = item.status_prod or '자재대기중'

                    new_category = normalize_detail_item(
                        request.form.get('category'),
                        default=con.item_group or DETAIL_ITEM_OPTIONS[0]
                    )
                    # 계약 단일 품목군 규칙 강제
                    if new_category != (con.item_group or DETAIL_ITEM_OPTIONS[0]):
                        flash(f"계약[{con.contract_name}]은 품목군 [{con.item_group}]만 입력할 수 있습니다.", "warning")
                    else:
                        item.category = new_category
                        item.model_name = request.form.get('model_name')
                        item.quantity = _to_int(request.form.get('quantity'), 0)
                        item.barcode_id = request.form.get('barcode_id') if item.category in LIGHTING_DETAIL_ITEMS else None
                        new_spec = _extract_contract_item_spec(request.form, item.category)
                        missing_spec = _validate_contract_item_spec(item.category, new_spec)
                        if missing_spec:
                            flash(f"필수 스펙 누락: {', '.join(missing_spec)}", 'warning')
                        else:
                            item.item_spec = new_spec
                        sales_status = request.form.get('status_sales')
                        if sales_status:
                            if sales_status in SALES_STATUS_STEPS:
                                item.status_sales = sales_status
                            else:
                                flash('영업현황 값이 올바르지 않아 기존 값을 유지했습니다.', 'warning')

                        admin_status = request.form.get('status_admin')
                        if admin_status:
                            if admin_status in ADMIN_STATUS_STEPS:
                                item.status_admin = admin_status
                            else:
                                flash('구매현황 값이 올바르지 않아 기존 값을 유지했습니다.', 'warning')

                        prod_status = request.form.get('status_prod')
                        if prod_status:
                            if prod_status in PROD_STATUS_STEPS:
                                item.status_prod = prod_status
                            else:
                                flash('생산현황 값이 올바르지 않아 기존 값을 유지했습니다.', 'warning')

                        new_info = f"{item.category}/{item.model_name}({item.quantity})"
                        changed_logs = []

                        if old_info != new_info:
                            changed_logs.append(f"품목정보: {old_info} ➡️ {new_info}")
                        new_spec_summary = _format_spec_summary(item.category, new_spec)
                        if old_spec_summary != new_spec_summary:
                            changed_logs.append(f"품목스펙: {old_spec_summary} ➡️ {new_spec_summary}")

                        if old_sales_status != (item.status_sales or old_sales_status):
                            changed_logs.append(f"영업현황: {old_sales_status} ➡️ {item.status_sales}")
                        if old_admin_status != (item.status_admin or old_admin_status):
                            changed_logs.append(f"구매현황: {old_admin_status} ➡️ {item.status_admin}")
                        if old_prod_status != (item.status_prod or old_prod_status):
                            changed_logs.append(f"생산현황: {old_prod_status} ➡️ {item.status_prod}")

                        if changed_logs:
                            log_content = (
                                f"{current_user}님이 계약품목 수정: {item.model_name or '-'}\n" +
                                "\n".join(changed_logs)
                            )
                            db.add(HistoryLog(
                                project_id=project_id,
                                user_name="시스템 🤖",
                                content=log_content
                            ))
                            ajax_log_entry = {
                                'user_name': '시스템 🤖',
                                'content': log_content,
                                'created_at': datetime.datetime.now().strftime('%y/%m/%d %H:%M:%S')
                            }
                        _sync_material_orders_for_contract_item(db, con, item)

        # 💡 계약 품목 바코드 수기 저장(전체 대체)
        elif action == 'update_contract_item_barcodes_manual':
            item_id = int(request.form.get('item_id'))
            item = db.query(ContractItem).get(item_id)
            if item:
                con = db.query(Contract).get(item.contract_id)
                if con and con.project_id == project_id:
                    if item.category not in LIGHTING_DETAIL_ITEMS:
                        flash('해당 품목은 바코드 관리 대상이 아닙니다.', 'warning')
                    else:
                        rows = []
                        raw_lines = request.form.get('barcode_lines', '') or ''
                        for line in raw_lines.splitlines():
                            code = line.strip()
                            if not code:
                                continue
                            rows.append({
                                'barcode': code,
                                'site_name': request.form.get('site_name') or p.temp_name,
                                'model_name': request.form.get('model_name') or item.model_name,
                                'producer': request.form.get('producer') or '',
                                'lens_angle': request.form.get('lens_angle') or '',
                                'pcb_spec': request.form.get('pcb_spec') or '',
                                'pcb_cct': request.form.get('pcb_cct') or '',
                                'pcb_chip_spec': request.form.get('pcb_chip_spec') or '',
                                'pcb_mfg_date': request.form.get('pcb_mfg_date') or '',
                                'smps_model': request.form.get('smps_model') or '',
                                'smps_qty': request.form.get('smps_qty') or '0',
                                'smps_setting': request.form.get('smps_setting') or '',
                                'smps_vdc': request.form.get('smps_vdc') or '',
                                'smps_adc': request.form.get('smps_adc') or '',
                                'spacing_distance': request.form.get('spacing_distance') or '',
                                'replaced_from_barcode': request.form.get('replaced_from_barcode') or '',
                                'replaced_reason': request.form.get('replaced_reason') or '',
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
                                site_name=row.get('site_name') or p.temp_name,
                                model_name=row.get('model_name') or item.model_name,
                                producer=row.get('producer') or '',
                                lens_angle=row.get('lens_angle') or '',
                                pcb_spec=row.get('pcb_spec') or '',
                                pcb_cct=row.get('pcb_cct') or '',
                                pcb_chip_spec=row.get('pcb_chip_spec') or '',
                                pcb_mfg_date=row.get('pcb_mfg_date') or '',
                                smps_model=row.get('smps_model') or '',
                                smps_qty=_to_int(row.get('smps_qty'), 0),
                                smps_setting=row.get('smps_setting') or '',
                                smps_vdc=row.get('smps_vdc') or '',
                                smps_adc=row.get('smps_adc') or '',
                                spacing_distance=row.get('spacing_distance') or '',
                                replaced_from_barcode=old_code or None,
                                replaced_reason=replace_reason or None,
                                created_by=current_user or '사용자'
                            ))
                            if old_code and old_code != new_code:
                                db.add(HistoryLog(
                                    project_id=project_id,
                                    user_name="시스템 🤖",
                                    content=(
                                        f"{current_user}님이 바코드 교체: {item.model_name or '-'} "
                                        f"{old_code} ➡️ {new_code}" +
                                        (f" (사유: {replace_reason})" if replace_reason else "")
                                    )
                                ))

                        item.barcode_id = (parsed[0].get('barcode') if parsed else None)
                        db.add(HistoryLog(
                            project_id=project_id,
                            user_name="시스템 🤖",
                            content=(
                                f"{current_user}님이 바코드 수기 저장: {item.model_name or '-'} "
                                f"({old_count}건 ➡️ {len(parsed)}건)"
                            )
                        ))

        # 💡 계약 품목 바코드 파일 업로드(CSV/엑셀 CSV)
        elif action == 'upload_contract_item_barcodes':
            item_id = int(request.form.get('item_id'))
            item = db.query(ContractItem).get(item_id)
            file = request.files.get('barcode_file')
            if item and file:
                con = db.query(Contract).get(item.contract_id)
                if con and con.project_id == project_id:
                    if item.category not in LIGHTING_DETAIL_ITEMS:
                        flash('해당 품목은 바코드 관리 대상이 아닙니다.', 'warning')
                    else:
                        file_name = (file.filename or '').lower()
                        parsed = []
                        seen = set()
                        if not file_name.endswith('.xlsx'):
                            flash('업로드는 XLSX 파일만 지원합니다.', 'warning')
                            parsed = []
                        else:
                            file.stream.seek(0)
                            rows = _parse_barcode_xlsx_rows(file)
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
                                site_name=(row.get('site_name') or row.get('현장명') or p.temp_name),
                                model_name=(row.get('model_name') or row.get('모델명') or item.model_name),
                                producer=(row.get('producer') or row.get('생산자') or ''),
                                lens_angle=(row.get('lens_angle') or row.get('렌즈각도') or ''),
                                pcb_spec=(row.get('pcb_spec') or row.get('PCB사양') or ''),
                                pcb_cct=(row.get('pcb_cct') or row.get('색온도') or ''),
                                pcb_chip_spec=(row.get('pcb_chip_spec') or row.get('칩사양') or ''),
                                pcb_mfg_date=(row.get('pcb_mfg_date') or row.get('제조일자') or ''),
                                smps_model=(row.get('smps_model') or row.get('SMPS 모델명') or ''),
                                smps_qty=_to_int((row.get('smps_qty') or row.get('SMPS 수량') or '0'), 0),
                                smps_setting=(row.get('smps_setting') or row.get('SMPS세팅값') or ''),
                                smps_vdc=(row.get('smps_vdc') or row.get('세팅전압(VDC)') or ''),
                                smps_adc=(row.get('smps_adc') or row.get('세팅전류(ADC)') or ''),
                                spacing_distance=(row.get('spacing_distance') or row.get('이격거리') or ''),
                                replaced_from_barcode=old_code or None,
                                replaced_reason=replace_reason or None,
                                created_by=current_user or '사용자'
                            ))
                            if old_code and old_code != new_code:
                                db.add(HistoryLog(
                                    project_id=project_id,
                                    user_name="시스템 🤖",
                                    content=(
                                        f"{current_user}님이 바코드 교체: {item.model_name or '-'} "
                                        f"{old_code} ➡️ {new_code}" +
                                        (f" (사유: {replace_reason})" if replace_reason else "")
                                    )
                                ))

                        item.barcode_id = ((parsed[0].get('barcode') or parsed[0].get('바코드번호')) if parsed else None)
                        db.add(HistoryLog(
                            project_id=project_id,
                            user_name="시스템 🤖",
                            content=(
                                f"{current_user}님이 바코드 파일 업로드: {item.model_name or '-'} "
                                f"({old_count}건 ➡️ {len(parsed)}건)"
                            )
                        ))

        # 💡 계약 품목 바코드 단건 삭제
        elif action == 'delete_contract_item_barcode':
            barcode_id = int(request.form.get('barcode_id'))
            bc = db.query(ContractBarcode).get(barcode_id)
            if bc:
                item = db.query(ContractItem).get(bc.contract_item_id)
                if item:
                    con = db.query(Contract).get(item.contract_id)
                    if con and con.project_id == project_id:
                        del_code = bc.barcode
                        db.delete(bc)
                        db.flush()
                        first_bc = db.query(ContractBarcode).filter_by(contract_item_id=item.id).order_by(ContractBarcode.seq.asc()).first()
                        item.barcode_id = first_bc.barcode if first_bc else None
                        db.add(HistoryLog(
                            project_id=project_id,
                            user_name="시스템 🤖",
                            content=f"{current_user}님이 바코드 삭제: {item.model_name or '-'} / {del_code}"
                        ))

        # 💡 계약 품목 바코드 단건 상세 수정/교체 이력 반영
        elif action == 'update_contract_item_barcode_meta':
            barcode_id = int(request.form.get('barcode_id'))
            bc = db.query(ContractBarcode).get(barcode_id)
            if bc:
                item = db.query(ContractItem).get(bc.contract_item_id)
                if item:
                    con = db.query(Contract).get(item.contract_id)
                    if con and con.project_id == project_id:
                        old_code = bc.barcode
                        new_code = (request.form.get('barcode') or '').strip()
                        replaced_from = (request.form.get('replaced_from_barcode') or '').strip()
                        replaced_reason = (request.form.get('replaced_reason') or '').strip()

                        bc.barcode = new_code or bc.barcode
                        bc.site_name = request.form.get('site_name') or bc.site_name
                        bc.model_name = request.form.get('model_name') or bc.model_name
                        bc.producer = request.form.get('producer') or ''
                        bc.lens_angle = request.form.get('lens_angle') or ''
                        bc.pcb_spec = request.form.get('pcb_spec') or ''
                        bc.pcb_cct = request.form.get('pcb_cct') or ''
                        bc.pcb_chip_spec = request.form.get('pcb_chip_spec') or ''
                        bc.pcb_mfg_date = request.form.get('pcb_mfg_date') or ''
                        bc.smps_model = request.form.get('smps_model') or ''
                        bc.smps_qty = _to_int(request.form.get('smps_qty'), 0)
                        bc.smps_setting = request.form.get('smps_setting') or ''
                        bc.smps_vdc = request.form.get('smps_vdc') or ''
                        bc.smps_adc = request.form.get('smps_adc') or ''
                        bc.spacing_distance = request.form.get('spacing_distance') or ''
                        bc.replaced_from_barcode = replaced_from or None
                        bc.replaced_reason = replaced_reason or None

                        if replaced_from and replaced_from != bc.barcode:
                            db.add(HistoryLog(
                                project_id=project_id,
                                user_name="시스템 🤖",
                                content=(
                                    f"{current_user}님이 바코드 교체: {item.model_name or '-'} "
                                    f"{replaced_from} ➡️ {bc.barcode}" +
                                    (f" (사유: {replaced_reason})" if replaced_reason else "")
                                )
                            ))
                        elif old_code != bc.barcode:
                            db.add(HistoryLog(
                                project_id=project_id,
                                user_name="시스템 🤖",
                                content=f"{current_user}님이 바코드 수정: {item.model_name or '-'} {old_code} ➡️ {bc.barcode}"
                            ))

        # 💡 계약 품목 추가
        elif action == 'add_contract_item':
            contract_id = int(request.form.get('contract_id'))
            con = db.query(Contract).filter_by(id=contract_id, project_id=project_id).first()
            if con:
                category = normalize_detail_item(
                    request.form.get('category'),
                    default=con.item_group or DETAIL_ITEM_OPTIONS[0]
                )
                model_name = (request.form.get('model_name') or '').strip()
                if not model_name:
                    flash('모델명을 입력해 주세요.', 'warning')
                elif category != (con.item_group or DETAIL_ITEM_OPTIONS[0]):
                    flash(f"계약[{con.contract_name}]은 품목군 [{con.item_group}]만 추가 가능합니다.", "warning")
                else:
                    new_item = ContractItem(
                        contract_id=con.id,
                        category=category,
                        model_name=model_name,
                        quantity=_to_int(request.form.get('quantity'), 0),
                        barcode_id=request.form.get('barcode_id') if category in LIGHTING_DETAIL_ITEMS else None
                    )
                    spec = _extract_contract_item_spec(request.form, category)
                    missing_spec = _validate_contract_item_spec(category, spec)
                    if missing_spec:
                        flash(f"필수 스펙 누락: {', '.join(missing_spec)}", 'warning')
                    else:
                        new_item.item_spec = spec
                    db.add(new_item)
                    db.add(HistoryLog(
                        project_id=project_id,
                        user_name="시스템 🤖",
                        content=f"{current_user}님이 계약품목 추가: {new_item.category}/{new_item.model_name}({new_item.quantity})"
                    ))
                    db.flush()
                    _sync_material_orders_for_contract_item(db, con, new_item)

        # 💡 계약 품목 삭제
        elif action == 'delete_contract_item':
            item_id = int(request.form.get('item_id'))
            item = db.query(ContractItem).get(item_id)
            if item:
                con = db.query(Contract).get(item.contract_id)
                if con and con.project_id == project_id:
                    db.add(HistoryLog(
                        project_id=project_id,
                        user_name="시스템 🤖",
                        content=f"{current_user}님이 계약품목 삭제: {item.category}/{item.model_name}({item.quantity})"
                    ))
                    db.query(MaterialOrder).filter(MaterialOrder.contract_item_id == item.id).delete()
                    db.delete(item)

        # 💡 담당자 추가 로그
        elif action == 'add_contact':
            new_con = Contact(
                project_id=project_id,
                name=request.form.get('name'), phone=request.form.get('phone'),
                email=request.form.get('email'), category=request.form.get('contact_category')
            )
            db.add(new_con)
            db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖", 
                              content=f"{current_user}님이 담당자 추가: {new_con.name}({new_con.category})"))

        # 💡 담당자 수정
        elif action == 'update_contact':
            con = db.query(Contact).get(int(request.form.get('contact_id')))
            if con:
                old_info = f"{con.name}/{con.phone or '-'}"
                con.category = request.form.get('contact_category')
                con.name = request.form.get('name')
                con.phone = request.form.get('phone')
                con.email = request.form.get('email')
                new_info = f"{con.name}/{con.phone or '-'}"
                db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖",
                                  content=f"{current_user}님이 담당자 수정: {old_info} ➡️ {new_info}"))

        # 💡 담당자 삭제
        elif action == 'delete_contact':
            con = db.query(Contact).get(int(request.form.get('contact_id')))
            if con:
                reason = request.form.get('delete_reason') or '사유 미입력'
                db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖",
                                  content=f"{current_user}님이 담당자 삭제: {con.name} (사유: {reason})"))
                db.delete(con)

        # 💡 품목 추가 로그
        elif action == 'add_material':
            mat_category = normalize_detail_item(request.form.get('category'), default=DETAIL_ITEM_OPTIONS[0])
            new_mat = Material(
                project_id=project_id, category=mat_category,
                model_name=request.form.get('model_name'), quantity=request.form.get('quantity')
            )
            db.add(new_mat)
            db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖", 
                              content=f"{current_user}님이 품목 추가: {new_mat.category}({new_mat.model_name}) {new_mat.quantity}개"))

        # 💡 품목 삭제
        elif action == 'delete_material':
            mat = db.query(Material).get(int(request.form.get('material_id')))
            if mat:
                db.add(HistoryLog(project_id=project_id, user_name="시스템 🤖",
                                  content=f"{current_user}님이 품목 삭제: {mat.category}({mat.model_name})"))
                db.delete(mat)

        # 채팅 메시지
        elif action == 'add_chat':
            msg = (request.form.get('chat_message') or '').strip()
            if msg:
                append_history_log(
                    db,
                    project_id=project_id,
                    user_name=current_user,
                    content=msg,
                    scope='common',
                    kind='comment'
                )

        elif action == 'add_history_reply':
            parent_id_raw = request.form.get('parent_log_id')
            reply_message = (request.form.get('reply_message') or '').strip()
            if parent_id_raw and reply_message:
                parent = db.query(HistoryLog).get(int(parent_id_raw))
                if parent and parent.project_id == project_id:
                    origin_full = (parent.content or '').strip()
                    origin_snapshot = origin_full
                    if len(origin_snapshot) > 220:
                        origin_snapshot = origin_snapshot[:220] + '...'
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name=current_user,
                        content=reply_message,
                        scope=parent.log_scope or ('common' if (parent.log_kind or '') == 'comment' else page_scope),
                        kind='reply',
                        parent_log_id=parent.id,
                        root_log_id=parent.root_log_id or parent.id,
                        origin_snapshot=origin_snapshot
                    )
                    append_history_log(
                        db,
                        project_id=project_id,
                        user_name=current_user,
                        content=f"[대댓글]\n답글:\n{reply_message}\n---원글---\n{origin_full}",
                        scope='common',
                        kind='comment'
                    )

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
    db.close()
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
def convert_to_contract(project_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if _is_prod_group():
        flash('생산부는 계약 전환 권한이 없습니다.', 'danger')
        return redirect(url_for('project.project_list'))
    db = SessionLocal()
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
                                    quantity=_to_int(mat.quantity, 0)
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
                flash(f'계약 전환 실패: {e}', 'danger')
    db.close()
    return redirect(url_for('project.contract_list'))


# -------------------------------------------------------------------
# 6. 현장 삭제요청/승인 (설계/계약 공통)
# -------------------------------------------------------------------
@project_bp.route('/project_delete_request/<int:project_id>', methods=['POST'])
def project_delete_request(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if _is_prod_group():
        flash('생산부는 삭제요청 권한이 없습니다.', 'danger')
        return redirect(url_for('project.project_list'))

    reason = (request.form.get('delete_reason') or '').strip()
    if not reason:
        flash('삭제 사유는 필수입니다.', 'warning')
        return redirect(request.referrer or url_for('project.project_list'))

    db = SessionLocal()
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
        flash(f'삭제요청 처리 실패: {e}', 'danger')
        return redirect(request.referrer or url_for('project.project_list'))
    finally:
        db.close()


@project_bp.route('/project_delete_requests/<int:req_id>/approve', methods=['POST'])
def approve_project_delete_request(req_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_approve_delete():
        flash('삭제 승인 권한이 없습니다.', 'danger')
        return redirect(url_for('auth.admin_settings'))

    db = SessionLocal()
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
        flash(f'삭제 승인 실패: {e}', 'danger')
    finally:
        db.close()
    return redirect(url_for('auth.admin_settings'))


@project_bp.route('/project_delete_requests/<int:req_id>/reject', methods=['POST'])
def reject_project_delete_request(req_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_approve_delete():
        flash('삭제 반려 권한이 없습니다.', 'danger')
        return redirect(url_for('auth.admin_settings'))

    reject_reason = (request.form.get('reject_reason') or '').strip()

    db = SessionLocal()
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
        flash(f'삭제 반려 실패: {e}', 'danger')
    finally:
        db.close()
    return redirect(url_for('auth.admin_settings'))


@project_bp.route('/project_delete/<int:project_id>', methods=['POST'])
def project_delete(project_id):
    """기존 라우트 호환: 승인권자만 즉시삭제 가능(일반 사용자는 삭제요청 사용)."""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if not _can_approve_delete():
        flash('직접 삭제 권한이 없습니다. 삭제요청을 이용해 주세요.', 'danger')
        return redirect(request.referrer or url_for('project.project_list'))

    db = SessionLocal()
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
        flash(f'현장 삭제 실패: {e}', 'danger')
        return redirect(url_for('project.project_list'))
    finally:
        db.close()