from flask import Blueprint, render_template, request, abort

from modules.auth_decorators import login_required
from modules.kakao_archive import load_post, list_posts, PAGE_SIZE

workboard_bp = Blueprint('workboard', __name__, url_prefix='/workboard')

_BOARD_TYPE = 'site'
_LABEL = '현장관리'


@workboard_bp.route('')
@login_required
def workboard_list():
    page = max(1, request.args.get('page', 1, type=int))
    q = request.args.get('q', '').strip()
    author = request.args.get('author', '').strip()
    posts, total, authors = list_posts(_BOARD_TYPE, page, q, author)
    return render_template(
        'archive_list.html',
        board_label=_LABEL,
        list_endpoint='workboard.workboard_list',
        detail_endpoint='workboard.workboard_detail',
        posts=posts,
        total=total,
        page=page,
        total_pages=(total + PAGE_SIZE - 1) // PAGE_SIZE,
        q=q,
        author=author,
        authors=authors,
    )


@workboard_bp.route('/<int:post_id>')
@login_required
def workboard_detail(post_id):
    post = load_post(_BOARD_TYPE, post_id)
    if not post:
        abort(404)
    return render_template(
        'archive_detail.html',
        board_label=_LABEL,
        list_endpoint='workboard.workboard_list',
        post=post,
    )
