"""카카오워크 워크보드 백업 보드 (일반 블루프린트).

config.WORKBOARDS 레지스트리를 따라 보드별 endpoint를 동적 등록한다.
기존 현장관리(workboard)/A/S(asboard)는 전용 블루프린트가 있으므로
builtin=False 인 신규 보드(자재발주·계약서·장비/운송비·제작현황·업무협의·공지사항)만 등록.

화면은 기존과 동일한 카카오워크 워크보드 스타일(archive_list/detail.html)을 그대로 사용한다.
URL: /board/<slug>  ·  /board/<slug>/<post_id>
endpoint: archive.list_<slug> / archive.detail_<slug>  (모두 인자 없는 list endpoint → 메뉴 url_for 호환)
"""
from flask import Blueprint, render_template, request, abort

from modules.auth_decorators import login_required
from modules.kakao_archive import load_post, list_posts, PAGE_SIZE
from config import WORKBOARDS

archive_bp = Blueprint('archive', __name__, url_prefix='/board')


def _list_view(slug, label):
    page = max(1, request.args.get('page', 1, type=int))
    q = request.args.get('q', '').strip()
    author = request.args.get('author', '').strip()
    posts, total, authors = list_posts(slug, page, q, author)
    return render_template(
        'archive_list.html',
        board_label=label,
        list_endpoint=f'archive.list_{slug}',
        detail_endpoint=f'archive.detail_{slug}',
        posts=posts,
        total=total,
        page=page,
        total_pages=(total + PAGE_SIZE - 1) // PAGE_SIZE,
        q=q,
        author=author,
        authors=authors,
    )


def _detail_view(slug, label, post_id):
    post = load_post(slug, post_id)
    if not post:
        abort(404)
    return render_template(
        'archive_detail.html',
        board_label=label,
        list_endpoint=f'archive.list_{slug}',
        post=post,
    )


def _make_handlers(slug, label):
    """slug/label을 클로저로 묶은 list/detail 핸들러 생성 (login_required 적용)."""
    @login_required
    def list_handler():
        return _list_view(slug, label)

    @login_required
    def detail_handler(post_id):
        return _detail_view(slug, label, post_id)

    return list_handler, detail_handler


# ── 레지스트리 순회하며 신규 보드 endpoint 동적 등록 ──
for _slug, _meta in WORKBOARDS.items():
    if _meta.get('builtin'):
        continue  # site/as 는 workboard/asboard 블루프린트가 담당
    _list_h, _detail_h = _make_handlers(_slug, _meta['label'])
    archive_bp.add_url_rule(f'/{_slug}', endpoint=f'list_{_slug}', view_func=_list_h)
    archive_bp.add_url_rule(f'/{_slug}/<int:post_id>', endpoint=f'detail_{_slug}', view_func=_detail_h)
