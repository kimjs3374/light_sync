"""카카오워크 전자결재 백업 열람 라우트 (문서대장)."""
from flask import Blueprint, render_template, request, abort, Response

from modules.auth_decorators import login_required
from modules.approval_archive import list_docs, load_doc, build_body_html, PAGE_SIZE

approval_archive_bp = Blueprint('approval_archive', __name__, url_prefix='/approval-archive')


@approval_archive_bp.route('')
@login_required
def archive_list():
    page = max(1, request.args.get('page', 1, type=int))
    q = request.args.get('q', '').strip()
    form = request.args.get('form', '').strip()
    docs, total, forms = list_docs(page, q, form)
    return render_template(
        'approval_archive_list.html',
        docs=docs,
        total=total,
        page=page,
        total_pages=(total + PAGE_SIZE - 1) // PAGE_SIZE,
        q=q,
        form=form,
        forms=forms,
    )


@approval_archive_bp.route('/<int:doc_id>')
@login_required
def archive_detail(doc_id):
    doc = load_doc(doc_id)
    if not doc:
        abort(404)
    return render_template('approval_archive_detail.html', doc=doc)


@approval_archive_bp.route('/<int:doc_id>/body')
@login_required
def archive_body(doc_id):
    """본문을 재구성한 HTML 로 서빙 (iframe sandbox 렌더용).

    원본 body.html은 카카오워크 Vue 템플릿이라 standalone 렌더 불가 →
    임베드 data에서 본문 추출·sanitize한 정적 HTML 반환.
    """
    html = build_body_html(doc_id)
    if html is None:
        abort(404)
    resp = Response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp
