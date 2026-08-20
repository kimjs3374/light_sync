"""서류관리 라우트 — 착수계/납품계 PDF 생성 허브."""

import datetime
import io
import logging
import os
import re

logger = logging.getLogger(__name__)

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify
from modules.auth_decorators import login_required, menu_required
from sqlalchemy import func, text
from sqlalchemy.orm import joinedload

from modules.db_context import get_db
from sqlalchemy import and_, or_, not_
from modules.models import (
    G2bProcurement, Project, Contract, User,
    DocumentPackage, DocumentAttachment, DOC_ATTACH_TYPES, REUSABLE_ATTACH_TYPES,
    determine_org_type, generate_doc_number,
)
from modules.contract_filters import DONE_STATUSES
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.activity import log_activity
from modules.storage_adapter import upload_bytes, download_bytes, delete_object, is_storage_enabled
from werkzeug.utils import secure_filename

document_bp = Blueprint('document', __name__)

# 공통 서류 Supabase 경로 (영문 키)
COMMON_DOCS = {
    'biz_registration': {'label': '사업자등록증', 'path': 'documents/common/biz_registration.pdf'},
    'factory_cert': {'label': '공장등록증명서', 'path': 'documents/common/factory_cert.pdf'},
    'direct_production_light': {'label': '직접생산확인증명서 (등기구)', 'path': 'documents/common/direct_production_light.pdf'},
    'direct_production_pole': {'label': '직접생산확인증명서 (등주)', 'path': 'documents/common/direct_production_pole.pdf'},
    'direct_production_tower': {'label': '직접생산확인증명서 (조명타워)', 'path': 'documents/common/direct_production_tower.pdf'},
}

DRAWINGS_PREFIX = 'documents/drawings/'
# 계약서·첨부도 Supabase Storage에 둔다 (static/ 저장 금지 — CLAUDE.md)
CONTRACT_PDF_PREFIX = 'documents/contracts/'
PKG_ATTACH_PREFIX = 'documents/package_attach/'


def _is_storage_path(path):
    """Supabase Storage 경로인지(레거시 로컬 경로가 아닌지) 판별한다."""
    return bool(path) and str(path).startswith('documents/')


def _read_document_file(path):
    """계약서/첨부 실물을 읽는다. Storage 우선, 과거 로컬 경로도 계속 지원."""
    if not path:
        return None
    if _is_storage_path(path):
        return download_bytes(path)
    abs_path = path if os.path.isabs(path) else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    if os.path.exists(abs_path):
        with open(abs_path, 'rb') as f:
            return f.read()
    return None


def _fmt_money(val):
    """금액 포맷 (1,234,567)."""
    if val is None:
        return '-'
    return f"{int(val):,}"


@document_bp.route('/documents')
@login_required
@menu_required('documents')
def document_list():
    """서류관리 목록 — 납품요구번호별 그룹핑."""
    with get_db() as db:
        q = request.args.get('q', '').strip()

        # 활성 계약(완료/예외 제외)이 있는 건만 표시
        active_req_nos_subq = db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None),
            Contract.payment_status.notin_(DONE_STATUSES),
            Contract.is_excluded.isnot(True),
        ).subquery()

        query = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.max(G2bProcurement.cntrct_dlvr_req_nm).label('business_name'),
            func.max(G2bProcurement.dminstt_nm).label('demand_org'),
            func.sum(G2bProcurement.prdct_amt).label('supply_amount'),
            func.max(G2bProcurement.dlvr_tmlmt_date).label('delivery_due'),
            func.max(G2bProcurement.cntrct_dlvr_req_date).label('req_date'),
            func.count(G2bProcurement.id).label('item_count'),
        ).filter(
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y',
            G2bProcurement.cntrct_dlvr_req_no.in_(active_req_nos_subq),
        ).group_by(
            G2bProcurement.cntrct_dlvr_req_no
        )

        if q:
            query = query.filter(
                G2bProcurement.cntrct_dlvr_req_nm.ilike(f'%{q}%') |
                G2bProcurement.cntrct_dlvr_req_no.ilike(f'%{q}%') |
                G2bProcurement.dminstt_nm.ilike(f'%{q}%')
            )

        query = query.order_by(func.max(G2bProcurement.cntrct_dlvr_req_date).desc())
        groups = query.all()

        req_nos = [g.cntrct_dlvr_req_no for g in groups]
        packages = {}
        if req_nos:
            pkgs = db.query(DocumentPackage).filter(
                DocumentPackage.procurement_req_no.in_(req_nos)
            ).all()
            packages = {p.procurement_req_no: p for p in pkgs}

        items = []
        for g in groups:
            pkg = packages.get(g.cntrct_dlvr_req_no)
            if pkg and pkg.delivery_generated:
                status = '완료'
                status_color = '#dcfce7'
                status_text_color = '#166534'
            elif pkg and pkg.commencement_generated:
                status = '납품계 생성가능'
                status_color = '#dbeafe'
                status_text_color = '#1e40af'
            elif pkg and pkg.req_pdf_path:
                status = '착수계 생성가능'
                status_color = '#fef3c7'
                status_text_color = '#92400e'
            else:
                status = '계약서 미등록'
                status_color = '#f1f5f9'
                status_text_color = '#64748b'

            items.append({
                'req_no': g.cntrct_dlvr_req_no,
                'business_name': g.business_name or '-',
                'demand_org': g.demand_org or '-',
                'supply_amount': g.supply_amount or 0,
                'delivery_due': g.delivery_due,
                'req_date': g.req_date,
                'item_count': g.item_count,
                'status': status,
                'status_color': status_color,
                'status_text_color': status_text_color,
            })

        stats = {
            'total': len(items),
            'no_contract': sum(1 for i in items if i['status'] == '계약서 미등록'),
            'commencement_ready': sum(1 for i in items if i['status'] == '착수계 생성가능'),
            'delivery_ready': sum(1 for i in items if i['status'] == '납품계 생성가능'),
            'done': sum(1 for i in items if i['status'] == '완료'),
        }

        # 공통 서류 등록 상태 — 모달 열 때만 확인 (AJAX)
        common_docs_status = {k: {'label': v['label'], 'exists': None} for k, v in COMMON_DOCS.items()}

        return render_template('document_list.html',
                               items=items, stats=stats, q=q, fmt_money=_fmt_money,
                               common_docs_status=common_docs_status,
                               storage_enabled=is_storage_enabled())


@document_bp.route('/documents/common-status')
@login_required
def common_docs_status_api():
    """공통 서류 등록 상태 확인 (AJAX)."""
    from modules.storage_adapter import exists as storage_exists
    result = {}
    for key, info in COMMON_DOCS.items():
        result[key] = {
            'label': info['label'],
            'exists': storage_exists(info['path']),
            'path': info['path'],
        }
    # 제작도면도 포함
    from modules.storage_adapter import _list_prefix
    drawings = _list_prefix(DRAWINGS_PREFIX)
    drawing_list = []
    for d in drawings:
        name = d.get('name', '')
        if name.endswith('.pdf'):
            drawing_list.append({'model': name.replace('.pdf', ''), 'path': DRAWINGS_PREFIX + name})
    result['_drawings'] = drawing_list
    return jsonify(result)


@document_bp.route('/documents/common-docs')
@login_required
@menu_required('documents')
def common_docs_page():
    """공통서류 관리 페이지."""
    # 공통서류: 업로드 성공 시 DB에 기록했으므로 캐시로 판단, 없으면 미등록으로 표시
    # 페이지 로드 시 Supabase API 호출 없음
    docs = {}
    for key, info in COMMON_DOCS.items():
        docs[key] = {'label': info['label'], 'exists': False, 'path': info['path']}

    with get_db() as db:
        from modules.models import CommonDrawing
        from sqlalchemy import text as _text

        # common_doc_status 테이블에서 등록 여부 확인 (없으면 비동기 체크)
        try:
            rows = db.execute(_text(
                "SELECT doc_key, is_uploaded FROM light_sync.common_doc_status"
            )).fetchall()
            for r in rows:
                if r[0] in docs:
                    docs[r[0]]['exists'] = bool(r[1])
        except Exception:
            pass  # 테이블 없으면 무시 — 아래에서 생성

        drawing_rows = db.query(CommonDrawing).order_by(CommonDrawing.model_code).all()
        drawings = [{'model': d.model_code, 'path': d.storage_path} for d in drawing_rows]

    return render_template('document_common_docs.html', docs=docs, drawings=drawings)


@document_bp.route('/documents/common-upload', methods=['POST'])
@login_required
@menu_required('documents')
def upload_common_doc():
    """공통 서류 업로드 (Supabase)."""
    doc_type = request.form.get('doc_type')
    file = request.files.get('file')
    redirect_to = request.form.get('redirect', 'list')
    target = url_for('document.common_docs_page') if redirect_to == 'common' else url_for('document.document_list')

    if not doc_type or doc_type not in COMMON_DOCS:
        flash('잘못된 서류 유형입니다.', 'warning')
        return redirect(target)
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return redirect(target)

    storage_path = COMMON_DOCS[doc_type]['path']
    ok, msg = upload_bytes(storage_path, file.read(), content_type='application/pdf')
    if ok:
        with get_db() as db:
            db.execute(text(
                "INSERT INTO light_sync.common_doc_status (doc_key, is_uploaded, updated_at) "
                "VALUES (:key, TRUE, NOW()) "
                "ON CONFLICT (doc_key) DO UPDATE SET is_uploaded = TRUE, updated_at = NOW()"
            ), {'key': doc_type})
            db.commit()
        flash(f'{COMMON_DOCS[doc_type]["label"]} 업로드 완료', 'success')
    else:
        flash(f'업로드 실패: {msg}', 'danger')
    return redirect(target)


@document_bp.route('/documents/drawing-upload', methods=['POST'])
@login_required
@menu_required('documents')
def upload_drawing():
    """제작도면 업로드 (모델별, Supabase)."""
    model_code = request.form.get('model_code', '').strip()
    file = request.files.get('file')
    redirect_to = request.form.get('redirect', 'list')
    target = url_for('document.common_docs_page') if redirect_to == 'common' else url_for('document.document_list')

    if not model_code:
        flash('모델코드를 입력해주세요.', 'warning')
        return redirect(target)
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return redirect(target)

    storage_path = DRAWINGS_PREFIX + model_code + '.pdf'
    ok, msg = upload_bytes(storage_path, file.read(), content_type='application/pdf')
    if ok:
        with get_db() as db:
            from modules.models import CommonDrawing
            existing = db.query(CommonDrawing).filter(CommonDrawing.model_code == model_code).first()
            if not existing:
                db.add(CommonDrawing(
                    model_code=model_code,
                    storage_path=storage_path,
                    created_by=session.get('user_display_name') or session.get('username'),
                ))
                db.commit()
        flash(f'{model_code} 제작도면 업로드 완료', 'success')
    else:
        flash(f'업로드 실패: {msg}', 'danger')
    return redirect(target)


@document_bp.route('/documents/<req_no>', methods=['GET', 'POST'])
@login_required
@menu_required('documents')
def document_detail(req_no):
    """서류관리 상세 — 서류 허브."""
    with get_db() as db:
        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        if not procurements:
            flash('해당 납품요구번호의 조달내역이 없습니다.', 'warning')
            return redirect(url_for('document.document_list'))

        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()

        if not package:
            first = procurements[0]
            package = DocumentPackage(
                procurement_req_no=req_no,
                business_name=first.cntrct_dlvr_req_nm,
                demand_org=first.dminstt_nm,
                demand_org_no=first.dminstt_cd,
                org_type=determine_org_type(first.dminstt_nm),
                created_by=session.get('username'),
            )
            if first.cntrct_dlvr_req_no:
                contract = db.query(Contract).filter(
                    Contract.g2b_contract_no == first.cntrct_dlvr_req_no
                ).first()
                if contract:
                    package.contract_id = contract.id
                    package.project_id = contract.project_id
            db.add(package)
            try:
                db.commit()
            except Exception:
                db.rollback()
                package = db.query(DocumentPackage).filter(
                    DocumentPackage.procurement_req_no == req_no
                ).first()

        if request.method == 'POST':
            action = request.form.get('action', '')
            _handle_document_action(db, package, procurements, action)
            return redirect(url_for('document.document_detail', req_no=req_no))

        attachments = db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).order_by(DocumentAttachment.sort_order).all()

        agents = db.query(User).filter(User.is_approved == True).order_by(User.full_name).all()

        # 변경계약으로 빠진 품목(수량 0 + 금액 0)은 화면에서 제외 — 원본은 보존
        procurements = [p for p in procurements
                        if (p.prdct_qty or 0) or (p.prdct_amt or 0)]

        total_supply = sum(p.prdct_amt or 0 for p in procurements)

        return render_template('document_detail.html',
                               package=package,
                               procurements=procurements,
                               attachments=attachments,
                               agents=agents,
                               total_supply=total_supply,
                               fmt_money=_fmt_money,
                               DOC_ATTACH_TYPES=DOC_ATTACH_TYPES)


@document_bp.route('/documents/<req_no>/contract-pdf')
@login_required
@menu_required('documents')
def view_contract_pdf(req_no):
    """업로드된 계약서(납품요구서) PDF 열람."""
    from flask import send_file

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package or not package.req_pdf_path:
            abort(404)
        data = _read_document_file(package.req_pdf_path)
        if data is None:
            abort(404)
        return send_file(io.BytesIO(data), mimetype='application/pdf',
                         download_name=f'계약서_{package.business_name or req_no}.pdf')


@document_bp.route('/documents/attachment/<int:att_id>')
@login_required
@menu_required('documents')
def view_attachment(att_id):
    """서류 패키지 첨부파일 열람."""
    from flask import send_file

    with get_db() as db:
        att = db.query(DocumentAttachment).get(att_id)
        if not att:
            abort(404)
        data = _read_document_file(att.storage_path)
        if data is None:
            abort(404)
        ext = os.path.splitext(att.file_name or att.storage_path or '')[1].lower()
        mimetype = {
            '.pdf': 'application/pdf', '.png': 'image/png',
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        }.get(ext, 'application/octet-stream')
        return send_file(io.BytesIO(data), mimetype=mimetype,
                         download_name=att.file_name or os.path.basename(att.storage_path))


# ── 템플릿 관리 ──

TEMPLATE_STORAGE = {
    'commencement': 'documents/templates/commencement_template.xlsx',
    'delivery': 'documents/templates/delivery_template.xlsx',
}
TEMPLATE_LOCAL = {
    'commencement': os.path.join(os.path.dirname(__file__), '..', 'static', 'templates', 'commencement_template.xlsx'),
    'delivery': os.path.join(os.path.dirname(__file__), '..', 'static', 'templates', 'delivery_template.xlsx'),
}


@document_bp.route('/documents/template/upload', methods=['POST'])
@login_required
@menu_required('documents')
def upload_template():
    """템플릿 업로드 → Supabase + 로컬 동기화."""
    from modules.storage_adapter import upload_bytes

    for tpl_type, field_name in [('commencement', 'commencement_tpl'), ('delivery', 'delivery_tpl')]:
        f = request.files.get(field_name)
        if f and f.filename:
            content = f.read()
            storage_path = TEMPLATE_STORAGE[tpl_type]
            upload_bytes(storage_path, content,
                         content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            local_path = TEMPLATE_LOCAL[tpl_type]
            with open(local_path, 'wb') as lf:
                lf.write(content)
            flash(f'{tpl_type} 템플릿 업로드 완료', 'success')

    return redirect(url_for('document.document_list'))


@document_bp.route('/documents/template/<tpl_type>/edit')
@login_required
@menu_required('documents')
def edit_template(tpl_type):
    """템플릿 ONLYOFFICE 편집기."""
    import time

    if tpl_type not in TEMPLATE_STORAGE:
        abort(404)

    local_path = TEMPLATE_LOCAL[tpl_type]
    if not os.path.exists(local_path):
        abort(404, '템플릿 파일이 없습니다.')

    label = '착수계' if tpl_type == 'commencement' else '납품계'
    doc_key = f'tpl_{tpl_type}_{int(time.time())}'
    file_url = f'http://host.internal:8501/static/templates/{os.path.basename(local_path)}'
    callback_url = f'http://host.internal:8501/api/onlyoffice/callback?tpl_type={tpl_type}'

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{label} 템플릿 편집</title>
<script src="https://docs.mgnt.kr/web-apps/apps/api/documents/api.js"></script>
<style>
html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden; }}
#editor {{ height: 100%; }}
</style>
</head>
<body>
<div id="editor"></div>
<script>
var docEditor = new DocsAPI.DocEditor("editor", {{
  document: {{
    fileType: "xlsx",
    key: "{doc_key}",
    title: "{label}_템플릿.xlsx",
    url: "{file_url}",
  }},
  documentType: "cell",
  editorConfig: {{
    mode: "edit",
    lang: "ko",
    callbackUrl: "{callback_url}",
    customization: {{ forcesave: true }},
  }},
}});
</script>
</body>
</html>'''


@document_bp.route('/documents/<req_no>/edit-commencement')
@login_required
@menu_required('documents')
def edit_commencement(req_no):
    """착수계 ONLYOFFICE 편집기 — 환경설정 시트 데이터 자동 채움."""
    import time

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        agent_user = None
        if package.commencement_agent_id:
            agent_user = db.query(User).get(package.commencement_agent_id)

        # 기존 편집 파일이 있으면 재사용, 없거나 regen 요청 시 새로 생성
        from modules.services.commencement_xlsx import generate_commencement_xlsx
        local_path = f'/web/light_sync/static/documents/commencement/{req_no}.xlsx'
        file_web_path = f'/static/documents/commencement/{req_no}.xlsx'

        if not os.path.exists(local_path) or request.args.get('regen'):
            generate_commencement_xlsx(package, procurements, agent_user)

        doc_key = f'{req_no}_{int(time.time())}'
        title = package.business_name or req_no
        file_url = f'http://host.internal:8501{file_web_path}'

        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>착수계 편집 - {title}</title>
<script src="https://docs.mgnt.kr/web-apps/apps/api/documents/api.js"></script>
<style>
html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden; }}
#editor {{ height: 100%; }}
#pdf-btn {{ position: fixed; top: 10px; right: 60px; z-index: 99999;
  padding: 6px 16px; background: #d32f2f; color: #fff; border: none; border-radius: 4px;
  font-size: 13px; font-weight: bold; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,.3); }}
#pdf-btn:hover {{ background: #b71c1c; }}
</style>
</head>
<body>
<button id="pdf-btn" onclick="docEditor.downloadAs('pdf')">PDF 다운로드</button>
<div id="editor"></div>
<script>
var docEditor = new DocsAPI.DocEditor("editor", {{
  document: {{
    fileType: "xlsx",
    key: "{doc_key}",
    title: "착수계_{title}.xlsx",
    url: "{file_url}",
    permissions: {{ download: true, print: true }},
  }},
  documentType: "cell",
  editorConfig: {{
    mode: "edit",
    lang: "ko",
    callbackUrl: "http://host.internal:8501/api/onlyoffice/callback?req_no={req_no}",
    customization: {{ forcesave: true }},
  }},
  events: {{
    onError: function(e) {{
      console.error("ONLYOFFICE ERROR:", e);
    }},
  }},
}});
</script>
</body>
</html>'''


@document_bp.route('/documents/<req_no>/edit-delivery')
@login_required
@menu_required('documents')
def edit_delivery(req_no):
    """납품계 ONLYOFFICE 편집기 — 기초 자료 입력 시트 데이터 자동 채움."""
    import time

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        from modules.services.delivery_xlsx import generate_delivery_xlsx
        local_path = f'/web/light_sync/static/documents/delivery/{req_no}.xlsx'
        file_web_path = f'/static/documents/delivery/{req_no}.xlsx'

        if not os.path.exists(local_path) or request.args.get('regen'):
            generate_delivery_xlsx(package, procurements, db=db)

        doc_key = f'dlv_{req_no}_{int(time.time())}'
        title = package.business_name or req_no
        file_url = f'http://host.internal:8501{file_web_path}'

        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>납품계 편집 - {title}</title>
<script src="https://docs.mgnt.kr/web-apps/apps/api/documents/api.js"></script>
<style>
html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden; }}
#editor {{ height: 100%; }}
#pdf-btn {{ position: fixed; top: 10px; right: 60px; z-index: 99999;
  padding: 6px 16px; background: #d32f2f; color: #fff; border: none; border-radius: 4px;
  font-size: 13px; font-weight: bold; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,.3); }}
#pdf-btn:hover {{ background: #b71c1c; }}
</style>
</head>
<body>
<button id="pdf-btn" onclick="docEditor.downloadAs('pdf')">PDF 다운로드</button>
<a id="xlsx-btn" href="{file_web_path}" download style="position:fixed;top:10px;right:180px;z-index:99999;padding:6px 16px;background:#1976d2;color:#fff;border:none;border-radius:4px;font-size:13px;font-weight:bold;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.3);text-decoration:none;">원본 다운로드</a>
<div id="editor"></div>
<script>
var docEditor = new DocsAPI.DocEditor("editor", {{
  document: {{
    fileType: "xlsx",
    key: "{doc_key}",
    title: "납품계_{title}.xlsx",
    url: "{file_url}",
    permissions: {{ download: true, print: true }},
  }},
  documentType: "cell",
  editorConfig: {{
    mode: "edit",
    lang: "ko",
    callbackUrl: "http://host.internal:8501/api/onlyoffice/callback?req_no={req_no}",
    customization: {{ forcesave: true }},
  }},
  events: {{
    onError: function(e) {{
      console.error("ONLYOFFICE ERROR:", e);
    }},
  }},
}});
</script>
</body>
</html>'''


@document_bp.route('/documents/preview-delivery-photos/<int:project_id>')
@login_required
@menu_required('documents')
def preview_delivery_photos(project_id):
    """사진대지 미리보기 — 사진관리 사진을 납품계 템플릿에 삽입 후 ONLYOFFICE로 오픈."""
    import time
    import shutil

    with get_db() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            abort(404)

        from modules.services.delivery_xlsx import insert_photos_into_xlsx, get_delivery_photos_data

        template = os.path.join(os.path.dirname(__file__), '..', 'static', 'templates', 'delivery_template.xlsx')
        out_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'documents', 'delivery')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'photo_preview_{project_id}.xlsx')
        file_web_path = f'/static/documents/delivery/photo_preview_{project_id}.xlsx'

        shutil.copy2(os.path.abspath(template), out_path)
        photo_data = get_delivery_photos_data(db, project_id)
        if photo_data:
            insert_photos_into_xlsx(out_path, photo_data)

        doc_key = f'photo_{project_id}_{int(time.time())}'
        title = project.temp_name or str(project_id)
        file_url = f'http://host.internal:8501{file_web_path}'

        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>사진대지 미리보기 - {title}</title>
<script src="https://docs.mgnt.kr/web-apps/apps/api/documents/api.js"></script>
<style>
html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden; }}
#editor {{ height: 100%; }}
</style>
</head>
<body>
<div id="editor"></div>
<script>
var docEditor = new DocsAPI.DocEditor("editor", {{
  document: {{
    fileType: "xlsx",
    key: "{doc_key}",
    title: "사진대지_{title}.xlsx",
    url: "{file_url}",
    permissions: {{ download: true, print: true, edit: false }},
  }},
  documentType: "cell",
  editorConfig: {{
    mode: "view",
    lang: "ko",
  }},
}});
</script>
</body>
</html>'''


# ── 서류 패키지 조립 ──

@document_bp.route('/documents/assembly-order', methods=['GET', 'POST'])
@login_required
@menu_required('documents')
def assembly_order_settings():
    """전체 기본 서류 순서 관리 (GET=조회, POST=저장)."""
    from modules.services.doc_assembly import get_available_items, get_default_order
    from sqlalchemy import text

    with get_db() as db:
        if request.method == 'POST':
            data = request.get_json(force=True, silent=True) or {}
            doc_type = data.get('doc_type', 'commencement')
            order = data.get('order', [])
            key = f'assembly_order_{doc_type}'
            db.execute(text(
                "INSERT INTO light_sync.system_settings (key, value, updated_at) "
                "VALUES (:k, :v, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = NOW()"
            ), {'k': key, 'v': __import__('json').dumps(order)})
            db.commit()
            return jsonify({'ok': True})

        # GET
        doc_type = request.args.get('doc_type', 'commencement')
        key = f'assembly_order_{doc_type}'
        row = db.execute(text(
            "SELECT value FROM light_sync.system_settings WHERE key = :k"
        ), {'k': key}).fetchone()

        saved_order = row[0] if row else None
        if isinstance(saved_order, str):
            saved_order = __import__('json').loads(saved_order)

        items = get_available_items(doc_type)
        default_order = get_default_order(doc_type)

        return jsonify({
            'items': items,
            'order': saved_order or default_order,
            'doc_type': doc_type,
        })


@document_bp.route('/documents/<req_no>/assembly-order', methods=['GET', 'POST'])
@login_required
@menu_required('documents')
def project_assembly_order(req_no):
    """현장별 개별 서류 순서 (GET=조회, POST=저장)."""
    from modules.services.doc_assembly import get_available_items, get_default_order
    from sqlalchemy import text

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        if request.method == 'POST':
            data = request.get_json(force=True, silent=True) or {}
            doc_type = data.get('doc_type', 'commencement')
            order = data.get('order', [])
            # None이면 전체 기본순서 사용, 빈 리스트가 아닌 경우만 저장
            assembly = package.assembly_order or {}
            assembly[doc_type] = order
            package.assembly_order = assembly
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(package, 'assembly_order')
            db.commit()
            return jsonify({'ok': True})

        # GET
        doc_type = request.args.get('doc_type', 'commencement')
        items = get_available_items(doc_type)

        # 현장 개별 순서 → 전체 기본순서 → 하드코딩 기본순서
        project_order = (package.assembly_order or {}).get(doc_type)
        if not project_order:
            key = f'assembly_order_{doc_type}'
            row = db.execute(text(
                "SELECT value FROM light_sync.system_settings WHERE key = :k"
            ), {'k': key}).fetchone()
            if row:
                project_order = row[0] if not isinstance(row[0], str) else __import__('json').loads(row[0])

        if not project_order:
            project_order = get_default_order(doc_type)

        return jsonify({
            'items': items,
            'order': project_order,
            'doc_type': doc_type,
            'is_custom': bool((package.assembly_order or {}).get(doc_type)),
        })


@document_bp.route('/documents/<req_no>/assembly-order/reset', methods=['POST'])
@login_required
@menu_required('documents')
def reset_project_assembly_order(req_no):
    """현장별 개별 순서 초기화 (전체 기본순서로 되돌림)."""
    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        data = request.get_json(force=True, silent=True) or {}
        doc_type = data.get('doc_type', 'commencement')

        assembly = package.assembly_order or {}
        assembly.pop(doc_type, None)
        package.assembly_order = assembly if assembly else None
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(package, 'assembly_order')
        db.commit()
        return jsonify({'ok': True})


@document_bp.route('/documents/<req_no>/assemble-pdf')
@login_required
@menu_required('documents')
def assemble_pdf(req_no):
    """서류 패키지 PDF 조립 및 다운로드."""
    from flask import send_file
    from modules.services.doc_assembly import assemble_package, get_default_order
    from sqlalchemy import text

    doc_type = request.args.get('type', 'commencement')

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        # 순서 결정
        order = (package.assembly_order or {}).get(doc_type)
        if not order:
            key = f'assembly_order_{doc_type}'
            row = db.execute(text(
                "SELECT value FROM light_sync.system_settings WHERE key = :k"
            ), {'k': key}).fetchone()
            if row:
                order = row[0] if not isinstance(row[0], str) else __import__('json').loads(row[0])
        if not order:
            order = get_default_order(doc_type)

        # xlsx 로컬 파일 경로
        if doc_type == 'commencement':
            xlsx_path = f'/web/light_sync/static/documents/commencement/{req_no}.xlsx'
        else:
            xlsx_path = f'/web/light_sync/static/documents/delivery/{req_no}.xlsx'

        if not os.path.exists(xlsx_path):
            flash('먼저 착수계/납품계 편집에서 데이터를 채워주세요.', 'warning')
            return redirect(url_for('document.document_detail', req_no=req_no))

        # 제작도면 수집
        drawings = []
        if 'drawing' in order:
            from modules.storage_adapter import download_bytes as _dl
            drawing_atts = db.query(DocumentAttachment).filter(
                DocumentAttachment.package_id == package.id,
                DocumentAttachment.file_type == 'drawing'
            ).order_by(DocumentAttachment.sort_order).all()
            for att in drawing_atts:
                data = _dl(att.storage_path)
                if data:
                    drawings.append(data)

        # 조립
        pdf_bytes = assemble_package(xlsx_path, order, doc_type, drawings)

        title = package.business_name or req_no
        label = '착수계' if doc_type == 'commencement' else '납품계'
        filename = f'{label}_{title}.pdf'

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename,
        )


@document_bp.route('/documents/<req_no>/commencement-pdf')
@login_required
@menu_required('documents')
def download_commencement_pdf(req_no):
    """착수계 PDF 다운로드."""
    from flask import send_file
    from modules.services.commencement_pdf import generate_commencement_pdf

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        agent_user = None
        if package.commencement_agent_id:
            agent_user = db.query(User).get(package.commencement_agent_id)

        # 첨부파일 목록
        att_list = db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).order_by(DocumentAttachment.sort_order).all()

        pdf_buf = generate_commencement_pdf(
            package, procurements, agent_user=agent_user,
            attachments=att_list
        )

        if not package.commencement_generated:
            package.commencement_generated = True
            db.commit()

        filename = f"착수계_{package.business_name or req_no}.pdf"
        return send_file(pdf_buf, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)


@document_bp.route('/documents/<req_no>/delivery-pdf')
@login_required
@menu_required('documents')
def download_delivery_pdf(req_no):
    """납품서류 PDF 다운로드."""
    from flask import send_file
    from modules.services.delivery_doc_pdf import generate_delivery_doc_pdf

    with get_db() as db:
        package = db.query(DocumentPackage).filter(
            DocumentPackage.procurement_req_no == req_no
        ).first()
        if not package:
            abort(404)

        procurements = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == req_no,
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
        ).all()

        stamp_path = None
        official_stamp_path = None
        for att in db.query(DocumentAttachment).filter(
            DocumentAttachment.package_id == package.id
        ).all():
            if att.file_type == 'stamp_corporate':
                stamp_path = att.storage_path
            elif att.file_type == 'stamp_official':
                official_stamp_path = att.storage_path

        pdf_buf = generate_delivery_doc_pdf(
            package, procurements,
            stamp_path=stamp_path, official_stamp_path=official_stamp_path
        )

        if not package.delivery_generated:
            package.delivery_generated = True
            db.commit()

        filename = f"납품계_{package.business_name or req_no}.pdf"
        return send_file(pdf_buf, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)


def _handle_document_action(db, package, procurements, action):
    """서류관리 POST 액션 처리."""
    if action == 'upload_contract_pdf':
        _handle_upload_contract_pdf(db, package, procurements)
    elif action == 'save_commencement':
        _handle_save_commencement(db, package)
    elif action == 'save_delivery':
        _handle_save_delivery(db, package)
    elif action == 'upload_attachment':
        _handle_upload_attachment(db, package)
    elif action == 'delete_attachment':
        att_id = request.form.get('attachment_id')
        if att_id:
            att = db.query(DocumentAttachment).get(int(att_id))
            if att and att.package_id == package.id:
                if _is_storage_path(att.storage_path):
                    delete_object(att.storage_path)
                db.delete(att)
                db.commit()
                flash('첨부파일이 삭제되었습니다.', 'success')


@document_bp.route('/documents/bulk-upload-contract')
@login_required
@menu_required('documents')
def bulk_upload_page():
    """계약서 일괄 업로드 페이지."""
    with get_db() as db:
        # 서류관리 리스트와 완전히 동일한 쿼리
        active_req_nos_subq = db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None),
            Contract.payment_status.notin_(DONE_STATUSES),
            Contract.is_excluded.isnot(True),
        ).subquery()

        groups = db.query(
            G2bProcurement.cntrct_dlvr_req_no,
            func.max(G2bProcurement.cntrct_dlvr_req_nm).label('business_name'),
        ).filter(
            G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y',
            G2bProcurement.cntrct_dlvr_req_no.in_(active_req_nos_subq),
        ).group_by(
            G2bProcurement.cntrct_dlvr_req_no
        ).order_by(
            func.max(G2bProcurement.cntrct_dlvr_req_date).desc()
        ).all()

        req_nos = [g.cntrct_dlvr_req_no for g in groups]
        g2b_names = {g.cntrct_dlvr_req_no: g.business_name for g in groups}

        packages = {}
        if req_nos:
            pkgs = db.query(DocumentPackage).filter(
                DocumentPackage.procurement_req_no.in_(req_nos)
            ).all()
            packages = {p.procurement_req_no: p for p in pkgs}

        items = []
        for req_no in req_nos:
            p = packages.get(req_no)
            items.append({
                'req_no': req_no,
                'name': g2b_names.get(req_no) or '',
                'has_pdf': bool(p and p.contract_no),
                'contract_no': (p.contract_no if p else '') or '',
                'fee': p.fee if p else None,
                'warranty': (p.warranty_period if p else '') or '',
                'inspection': (p.inspection_org if p else '') or '',
                'acceptance': (p.acceptance_org if p else '') or '',
            })

        uploaded = sum(1 for i in items if i['has_pdf'])
        return render_template('document_bulk_upload.html',
                               items=items, uploaded=uploaded, total=len(items))


@document_bp.route('/documents/bulk-upload-contract', methods=['POST'])
@login_required
@menu_required('documents')
def bulk_upload_contract_pdf():
    """계약서 PDF 일괄 업로드 API — JSON 응답."""
    from modules.services.contract_pdf_parser import parse_contract_pdf, update_procurement_from_pdf

    files = request.files.getlist('files')
    if not files or not files[0].filename:
        return jsonify({'error': '파일을 선택해주세요.'}), 400

    results = []

    with get_db() as db:
        for file in files:
            fname = file.filename
            if not fname.lower().endswith('.pdf'):
                results.append({'file': fname, 'status': 'skip', 'msg': 'PDF 아님'})
                continue

            file_bytes = file.read()
            try:
                parsed = parse_contract_pdf(file_bytes)
            except Exception as e:
                results.append({'file': fname, 'status': 'fail', 'msg': f'파싱 실패: {e}'})
                continue

            req_no_raw = parsed.get('delivery_req_no', '').strip()
            if not req_no_raw:
                results.append({'file': fname, 'status': 'fail', 'msg': '계약번호 추출 실패'})
                continue

            # 변경차수 제거: -00 또는 끝 00 (R26TA0148584300→R26TA01485843)
            req_no = re.sub(r'-\d{2}$', '', req_no_raw)
            candidates = [req_no]
            if req_no.endswith('00') and len(req_no) > 12:
                candidates.append(req_no[:-2])

            # 계약번호로 Contract 직접 매칭
            contract = None
            matched_no = req_no
            for c in candidates:
                contract = db.query(Contract).filter(
                    Contract.g2b_contract_no == c
                ).first()
                if contract:
                    matched_no = c
                    break

            if not contract:
                results.append({'file': fname, 'status': 'fail',
                                'msg': f'매칭 실패 (계약번호: {req_no})',
                                'req_no': req_no})
                continue

            # DocumentPackage 조회 or 자동 생성
            package = db.query(DocumentPackage).filter(
                DocumentPackage.procurement_req_no == matched_no
            ).first()
            if not package:
                first_proc = db.query(G2bProcurement).filter(
                    G2bProcurement.cntrct_dlvr_req_no == matched_no,
                    G2bProcurement.fnl_cntrct_dlvr_req_chg_ord_yn == 'Y'
                ).first()
                package = DocumentPackage(
                    procurement_req_no=matched_no,
                    business_name=first_proc.cntrct_dlvr_req_nm if first_proc else None,
                    demand_org=first_proc.dminstt_nm if first_proc else None,
                    demand_org_no=first_proc.dminstt_cd if first_proc else None,
                    org_type=determine_org_type(first_proc.dminstt_nm) if first_proc else None,
                    contract_id=contract.id,
                    project_id=contract.project_id,
                    created_by=session.get('username'),
                )
                db.add(package)
                db.flush()

            storage_path = CONTRACT_PDF_PREFIX + f'{package.procurement_req_no}.pdf'
            ok, msg = upload_bytes(storage_path, file_bytes, content_type='application/pdf')
            if not ok:
                results.append({'file': fname, 'status': 'fail', 'msg': f'저장 실패: {msg}'})
                continue

            package.req_pdf_path = storage_path
            package.contract_no = parsed.get('contract_no')
            package.contract_date = parsed.get('contract_date')
            package.fee = parsed.get('fee')
            package.total_amount = parsed.get('total_amount')
            package.supply_amount = parsed.get('supply_amount')
            package.warranty_period = parsed.get('warranty_period')
            package.inspection_org = parsed.get('inspection_org')
            package.acceptance_org = parsed.get('acceptance_org')
            if parsed.get('demand_org_no'):
                package.demand_org_no = parsed['demand_org_no']
            package.org_type = determine_org_type(package.demand_org)

            update_procurement_from_pdf(db, parsed)

            insp = parsed.get('inspection_org', '').strip()
            accp = parsed.get('acceptance_org', '').strip()
            if insp and accp and insp != accp:
                ct = db.query(Contract).filter(
                    Contract.project_id == package.project_id
                ).first() if package.project_id else None
                if not ct:
                    ct = db.query(Contract).filter(
                        Contract.g2b_contract_no == package.procurement_req_no
                    ).first()
                if ct and not ct.is_prof_inspection:
                    ct.is_prof_inspection = True

            fee_str = f"{parsed['fee']:,}" if parsed.get('fee') else '-'
            biz = parsed.get('business_name', '')[:30] or package.business_name or ''
            results.append({
                'file': fname, 'status': 'success',
                'req_no': package.procurement_req_no,
                'msg': f'{biz}',
                'fee': fee_str,
                'inspection': insp,
                'acceptance': accp,
                'warranty': parsed.get('warranty_period', ''),
            })

        db.commit()

    return jsonify({'results': results})


def _handle_upload_contract_pdf(db, package, procurements):
    """납품요구서 PDF 업로드 + 자동 파싱."""
    from modules.services.contract_pdf_parser import parse_contract_pdf, update_procurement_from_pdf

    file = request.files.get('contract_pdf')
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return

    file_bytes = file.read()

    # 저장 전에 먼저 검증한다 — 엉뚱한 계약서를 올린 뒤 지우는 것보다,
    # 애초에 올리지 않는 쪽이 Storage에 쓰레기를 안 남긴다.
    parsed = None
    try:
        parsed = parse_contract_pdf(file_bytes)
    except Exception as e:
        flash(f'PDF 파싱 중 오류: {e}', 'danger')

    if parsed:
        # 계약번호 불일치 검증 — 잘못된 계약서 업로드 방지
        parsed_req = re.sub(r'-\d{2}$', '', parsed.get('delivery_req_no', '').strip())
        if parsed_req and package.procurement_req_no:
            pkg_no = package.procurement_req_no.strip()
            if not parsed_req.startswith(pkg_no) and not pkg_no.startswith(parsed_req):
                flash(
                    f'계약서 불일치 — 업로드한 PDF의 계약번호({parsed_req})가 '
                    f'현재 건({pkg_no})과 다릅니다. 올바른 계약서를 업로드해주세요.',
                    'danger'
                )
                return

    storage_path = CONTRACT_PDF_PREFIX + f'{package.procurement_req_no}.pdf'
    ok, msg = upload_bytes(storage_path, file_bytes, content_type='application/pdf')
    if not ok:
        flash(f'PDF 저장 실패: {msg}', 'danger')
        return
    package.req_pdf_path = storage_path

    if not parsed:
        db.commit()
        return

    try:
        package.contract_no = parsed.get('contract_no')
        package.contract_date = parsed.get('contract_date')
        package.fee = parsed.get('fee')
        package.total_amount = parsed.get('total_amount')
        package.supply_amount = parsed.get('supply_amount')
        package.warranty_period = parsed.get('warranty_period')
        package.inspection_org = parsed.get('inspection_org')
        package.acceptance_org = parsed.get('acceptance_org')
        if parsed.get('demand_org_no'):
            package.demand_org_no = parsed['demand_org_no']
        package.org_type = determine_org_type(package.demand_org)

        update_procurement_from_pdf(db, parsed)

        # 검사기관 ≠ 검수기관이면 전문기관검사로 설정
        insp = parsed.get('inspection_org', '').strip()
        accp = parsed.get('acceptance_org', '').strip()
        if insp and accp and insp != accp:
            contract = db.query(Contract).filter(
                Contract.project_id == package.project_id
            ).first() if package.project_id else None
            if not contract:
                contract = db.query(Contract).filter(
                    Contract.g2b_contract_no == package.procurement_req_no
                ).first()
            if contract and not contract.is_prof_inspection:
                contract.is_prof_inspection = True
                logger.info("전문기관검사 설정: %s (검사=%s, 검수=%s)",
                            package.procurement_req_no, insp, accp)

        fee_str = f"{parsed['fee']:,}" if parsed.get('fee') else '-'
        flash(f'납품요구서 파싱 완료 — 계약번호: {parsed.get("contract_no")}, 수수료: {fee_str}원', 'success')
    except Exception as e:
        flash(f'PDF 파싱 중 오류: {e}', 'danger')

    db.commit()


def _handle_save_commencement(db, package):
    """착수계 정보 저장."""
    package.commencement_date = request.form.get('commencement_date') or None
    agent_id = request.form.get('agent_id')
    package.commencement_agent_id = int(agent_id) if agent_id else None

    if not package.commencement_doc_no:
        doc_date = None
        if package.commencement_date:
            try:
                doc_date = datetime.date.fromisoformat(package.commencement_date) if isinstance(package.commencement_date, str) else package.commencement_date
            except (ValueError, TypeError):
                pass
        package.commencement_doc_no = generate_doc_number(db, doc_date)

    db.commit()
    flash('착수계 정보가 저장되었습니다.', 'success')


def _handle_save_delivery(db, package):
    """납품계 정보 저장."""
    package.delivery_date = request.form.get('delivery_date') or None

    if not package.delivery_doc_no:
        doc_date = None
        if package.delivery_date:
            try:
                doc_date = datetime.date.fromisoformat(package.delivery_date) if isinstance(package.delivery_date, str) else package.delivery_date
            except (ValueError, TypeError):
                pass
        package.delivery_doc_no = generate_doc_number(db, doc_date)

    db.commit()
    flash('납품계 정보가 저장되었습니다.', 'success')


def _handle_upload_attachment(db, package):
    """첨부파일 업로드."""
    file = request.files.get('attachment_file')
    file_type = request.form.get('file_type', 'other')
    if not file or not file.filename:
        flash('파일을 선택해주세요.', 'warning')
        return

    sort_order = len(package.attachments) + 1
    # 한글 파일명은 secure_filename이 비워버리므로 원본은 file_name 컬럼에 따로 남긴다
    safe_name = secure_filename(file.filename) or 'file'
    storage_path = PKG_ATTACH_PREFIX + f'{package.id}/{sort_order}_{safe_name}'
    ok, msg = upload_bytes(storage_path, file.read(),
                           content_type=file.mimetype or 'application/octet-stream')
    if not ok:
        flash(f'첨부 저장 실패: {msg}', 'danger')
        return

    att = DocumentAttachment(
        package_id=package.id,
        file_type=file_type,
        file_name=file.filename,
        storage_path=storage_path,
        sort_order=sort_order,
    )
    db.add(att)
    db.commit()
    flash(f'{DOC_ATTACH_TYPES.get(file_type, file_type)} 업로드 완료', 'success')
