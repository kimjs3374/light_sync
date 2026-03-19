"""납품집계 서비스 — G2B 조달내역 월별 피벗 집계 + 엑셀 생성"""
import datetime
from io import BytesIO

from sqlalchemy import extract, func

from modules.models import G2bProcurement


CHART_COLORS = [
    '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
    '#ec4899', '#06b6d4', '#f97316', '#6366f1', '#84cc16',
]


def get_filter_options(db):
    """필터 옵션: 년도 + 대분류(세부품명) 목록"""
    years = db.query(
        extract('year', G2bProcurement.cntrct_dlvr_req_date).label('yr')
    ).filter(
        G2bProcurement.prdct_amt > 0,
    ).distinct().order_by(
        extract('year', G2bProcurement.cntrct_dlvr_req_date).desc()
    ).all()

    categories = db.query(
        G2bProcurement.dtil_prdct_clsfc_no_nm
    ).filter(
        G2bProcurement.prdct_amt > 0,
        G2bProcurement.dtil_prdct_clsfc_no_nm.isnot(None),
    ).distinct().order_by(
        G2bProcurement.dtil_prdct_clsfc_no_nm
    ).all()

    return {
        'years': [int(r[0]) for r in years if r[0]],
        'categories': [r[0] for r in categories if r[0]],
    }


def get_summary_pivot(db, years=None, category=None, q=None, group_by='category'):
    """납품집계 피벗

    group_by:
        'category' = 대분류(dtil_prdct_clsfc_no_nm) 기준
        'model'    = 모델(prdct_idnt_no_nm) 기준
    """
    filters = [G2bProcurement.prdct_amt > 0]
    if years:
        filters.append(extract('year', G2bProcurement.cntrct_dlvr_req_date).in_(years))
    if category:
        filters.append(G2bProcurement.dtil_prdct_clsfc_no_nm == category)
    if q:
        filters.append(G2bProcurement.prdct_idnt_no_nm.ilike(f'%{q}%'))

    if group_by == 'model':
        group_col = G2bProcurement.prdct_idnt_no_nm
    else:
        group_col = G2bProcurement.dtil_prdct_clsfc_no_nm

    rows = db.query(
        group_col.label('name'),
        extract('year', G2bProcurement.cntrct_dlvr_req_date).label('year'),
        extract('month', G2bProcurement.cntrct_dlvr_req_date).label('month'),
        func.sum(G2bProcurement.prdct_qty).label('total_qty'),
        func.sum(G2bProcurement.prdct_amt).label('total_amt'),
    ).filter(*filters).group_by(
        group_col,
        extract('year', G2bProcurement.cntrct_dlvr_req_date),
        extract('month', G2bProcurement.cntrct_dlvr_req_date),
    ).all()

    multi_year = years and len(years) > 1
    return _build_pivot(rows, multi_year=multi_year)


def _empty_months():
    return {i: {'qty': 0, 'amt': 0} for i in range(1, 13)}


def _add_months(target, source):
    for m in range(1, 13):
        target[m]['qty'] += source[m]['qty']
        target[m]['amt'] += source[m]['amt']


def _build_pivot(rows, multi_year=False):
    """쿼리 결과 → 피벗 dict

    multi_year=True 시 각 항목에 년도별 sub_rows 포함:
    models[].sub_rows = [{'year': 2024, 'months': {...}, 'total_qty', 'total_amt'}, ...]
    """
    # name → year → month 집계
    raw = {}
    for r in rows:
        name = r.name or '(미분류)'
        yr = int(r.year)
        m = int(r.month)
        qty = int(r.total_qty or 0)
        amt = int(r.total_amt or 0)

        if name not in raw:
            raw[name] = {}
        if yr not in raw[name]:
            raw[name][yr] = {'months': _empty_months(), 'total_qty': 0, 'total_amt': 0}

        entry = raw[name][yr]
        entry['months'][m]['qty'] += qty
        entry['months'][m]['amt'] += amt
        entry['total_qty'] += qty
        entry['total_amt'] += amt

    # 합산 + sub_rows 생성
    model_map = {}
    for name, year_data in raw.items():
        agg = {'name': name, 'months': _empty_months(), 'total_qty': 0, 'total_amt': 0, 'sub_rows': []}
        for yr in sorted(year_data.keys()):
            yd = year_data[yr]
            _add_months(agg['months'], yd['months'])
            agg['total_qty'] += yd['total_qty']
            agg['total_amt'] += yd['total_amt']
            if multi_year:
                agg['sub_rows'].append({
                    'year': yr,
                    'months': yd['months'],
                    'total_qty': yd['total_qty'],
                    'total_amt': yd['total_amt'],
                })
        model_map[name] = agg

    models = sorted(model_map.values(), key=lambda x: -x['total_amt'])

    grand = {'months': _empty_months(), 'total_qty': 0, 'total_amt': 0}
    for mdl in models:
        _add_months(grand['months'], mdl['months'])
        grand['total_qty'] += mdl['total_qty']
        grand['total_amt'] += mdl['total_amt']

    return {'models': models, 'grand_total': grand}


def build_chart_data(pivot):
    """Chart.js stacked bar (금액 기준, 상위 10개)"""
    labels = [f'{m}월' for m in range(1, 13)]
    datasets = []
    for idx, mdl in enumerate(pivot['models'][:10]):
        color = CHART_COLORS[idx % len(CHART_COLORS)]
        datasets.append({
            'label': mdl['name'][:30],
            'data': [mdl['months'][m]['amt'] for m in range(1, 13)],
            'backgroundColor': color + 'cc',
            'borderColor': color,
            'borderWidth': 1,
        })
    return {'labels': labels, 'datasets': datasets}


def generate_excel(pivot, years, title='납품집계'):
    """피벗 → xlsx"""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]

    thin = Side(style='thin', color='999999')
    border = Border(top=thin, left=thin, right=thin, bottom=thin)
    header_fill = PatternFill(start_color='1e293b', end_color='1e293b', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=10)
    total_fill = PatternFill(start_color='e2e8f0', end_color='e2e8f0', fill_type='solid')
    total_font = Font(bold=True, size=10)
    num_fmt = '#,##0'

    year_str = ','.join(str(y) for y in years) if years else '전체'
    ws.merge_cells('A1:Z1')
    ws['A1'] = f'{title} ({year_str})'
    ws['A1'].font = Font(bold=True, size=14)

    headers = ['구분']
    for m in range(1, 13):
        headers.append(f'{m}월(수량)')
        headers.append(f'{m}월(금액)')
    headers += ['합계(수량)', '합계(금액)']

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border

    row_idx = 4
    for mdl in pivot['models']:
        ws.cell(row=row_idx, column=1, value=mdl['name']).border = border
        col = 2
        for m in range(1, 13):
            for val in [mdl['months'][m]['qty'], mdl['months'][m]['amt']]:
                cell = ws.cell(row=row_idx, column=col, value=val)
                cell.number_format = num_fmt
                cell.border = border
                col += 1
        for val in [mdl['total_qty'], mdl['total_amt']]:
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.number_format = num_fmt
            cell.border = border
            col += 1
        row_idx += 1

    gt = pivot['grand_total']
    ws.cell(row=row_idx, column=1, value='합계').font = total_font
    ws.cell(row=row_idx, column=1).fill = total_fill
    ws.cell(row=row_idx, column=1).border = border
    col = 2
    for m in range(1, 13):
        for val in [gt['months'][m]['qty'], gt['months'][m]['amt']]:
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.number_format = num_fmt
            cell.font = total_font
            cell.fill = total_fill
            cell.border = border
            col += 1
    for val in [gt['total_qty'], gt['total_amt']]:
        cell = ws.cell(row=row_idx, column=col, value=val)
        cell.number_format = num_fmt
        cell.font = total_font
        cell.fill = total_fill
        cell.border = border
        col += 1

    ws.column_dimensions['A'].width = 40
    for c in range(2, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 13

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
