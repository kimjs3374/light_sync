"""카카오워크 대화방 백업 열람 라우트 (카카오톡 스타일 + 무한스크롤 + 검색)."""
from flask import Blueprint, render_template, request, abort

from modules.auth_decorators import login_required
from modules.chat_archive import (
    list_rooms, get_room, load_messages, search_messages, page_of_message,
)

chat_archive_bp = Blueprint('chat_archive', __name__, url_prefix='/chat-archive')


@chat_archive_bp.route('')
@login_required
def room_list():
    return render_template('chat_archive_list.html', rooms=list_rooms())


@chat_archive_bp.route('/<int:conv_id>')
@login_required
def room_view(conv_id):
    room = get_room(conv_id)
    if not room:
        abort(404)

    q = request.args.get('q', '').strip()
    if q:
        return render_template(
            'chat_archive_room.html',
            room=room, rooms=list_rooms(),
            q=q, results=search_messages(conv_id, q),
            items=None,
        )

    # 특정 메시지로 점프 (검색결과 클릭) → 그 메시지가 있는 페이지
    jump = request.args.get('jump', type=int)
    page = request.args.get('page', type=int)
    if jump and not page:
        page = page_of_message(conv_id, jump) or 10 ** 9

    items, page, total_pages, total = load_messages(conv_id, page or 10 ** 9)
    return render_template(
        'chat_archive_room.html',
        room=room, rooms=list_rooms(),
        items=items, page=page, total_pages=total_pages, total=total,
        jump=jump, q='', results=None,
    )


@chat_archive_bp.route('/<int:conv_id>/messages')
@login_required
def messages_partial(conv_id):
    """무한스크롤용 메시지 파셜 (HTML 조각)."""
    page = request.args.get('page', 1, type=int)
    items, page, total_pages, total = load_messages(conv_id, page)
    return render_template('chat_archive_items.html', items=items)
