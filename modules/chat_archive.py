"""카카오워크 대화방 백업 열람 (public.chat_messages).

텍스트는 `text` 컬럼(복호화본) 사용. 첨부(이미지/파일/동영상)는 Storage
`chat/archive/{conversation_id}/{block_id}{ext}` 에 저장됨.
"""
import os
import re
import html as _html
from datetime import datetime, timedelta, timezone

from markupsafe import Markup
from sqlalchemy import text
from modules.db_context import get_db

PAGE_SIZE = 200
KST = timezone(timedelta(hours=9))

_SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
_BUCKET = 'company-files'

_WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']
_URL_RE = re.compile(r'(https?://[^\s<]+)')


def _public_url(key):
    return f'{_SUPABASE_URL}/storage/v1/object/public/{_BUCKET}/{key}' if _SUPABASE_URL else ''


def _media_url(conv_id, block):
    ext = os.path.splitext(block.get('file_name') or '')[1].lower()
    return _public_url(f'chat/archive/{conv_id}/{block.get("id")}{ext}')


def _thumb_url(url):
    """이미지 경량 썸네일 (Supabase 이미지 변환)."""
    if url and '/storage/v1/object/public/' in url:
        return url.replace('/storage/v1/object/public/', '/storage/v1/render/image/public/', 1) + '?width=300&quality=70'
    return url


def _fmt_size(n):
    n = n or 0
    if n < 1024:
        return f'{n}B'
    if n < 1024 * 1024:
        return f'{n/1024:.0f}KB'
    return f'{n/1024/1024:.1f}MB'


def _dt(epoch):
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).astimezone(KST)


def _fmt_time(dt):
    if not dt:
        return ''
    ap = '오전' if dt.hour < 12 else '오후'
    h = dt.hour % 12 or 12
    return f'{ap} {h}:{dt.minute:02d}'


def _fmt_date(dt):
    return f'{dt.year}년 {dt.month}월 {dt.day}일 ({_WEEKDAYS[dt.weekday()]})'


def _render_text(s):
    """평문 → 안전한 HTML (이스케이프 + 줄바꿈 + 링크)."""
    if not s:
        return ''
    s = re.sub(r'\\([^\w\s])', r'\1', s)          # 카카오 백슬래시 이스케이프 제거 \( → (
    s = str(_html.escape(s))
    s = _URL_RE.sub(lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>', s)
    return s.replace('\n', '<br>')


def _avatar_color(key):
    palette = ['#f4b400', '#db4437', '#0f9d58', '#4285f4', '#ab47bc',
               '#00acc1', '#ff7043', '#9e9d24', '#5c6bc0', '#26a69a']
    try:
        n = int(key)
    except (ValueError, TypeError):
        n = sum(ord(c) for c in str(key or ''))
    return palette[n % len(palette)]


# ─────────────────────────────────────────── 조회

def list_rooms():
    with get_db() as db:
        rows = db.execute(text("""
            SELECT conversation_id, conversation_name, COUNT(*), MAX(sent_time)
            FROM public.chat_messages
            GROUP BY conversation_id, conversation_name
            ORDER BY MAX(sent_time) DESC
        """)).fetchall()
    rooms = []
    for r in rows:
        last = _dt(r[3])
        rooms.append({
            'id': r[0],
            'name': r[1] or f'대화방 {r[0]}',
            'count': r[2],
            'last_date': _fmt_date(last) if last else '',
            'color': _avatar_color(r[0]),
        })
    return rooms


def get_room(conv_id):
    with get_db() as db:
        r = db.execute(text("""
            SELECT conversation_id, conversation_name, COUNT(*)
            FROM public.chat_messages WHERE conversation_id = :c
            GROUP BY conversation_id, conversation_name
        """), {'c': conv_id}).fetchone()
    if not r:
        return None
    return {'id': r[0], 'name': r[1] or f'대화방 {r[0]}', 'count': r[2]}


def _media_from_blocks(conv_id, blocks):
    images, files, videos = [], [], []
    for b in blocks or []:
        t = b.get('type')
        if t == 'image':
            url = _media_url(conv_id, b)
            images.append({'url': url, 'thumb': _thumb_url(url), 'name': b.get('file_name', ''),
                           'w': b.get('width') or 0, 'h': b.get('height') or 0})
        elif t == 'image_bundle':
            for child in b.get('items', []) or []:
                url = _media_url(conv_id, child)
                images.append({'url': url, 'thumb': _thumb_url(url), 'name': child.get('file_name', ''),
                               'w': child.get('width') or 0, 'h': child.get('height') or 0})
        elif t == 'video':
            videos.append({'url': _media_url(conv_id, b), 'name': b.get('file_name', '')})
        elif t == 'file':
            files.append({'url': _media_url(conv_id, b), 'name': b.get('file_name', ''),
                          'size': _fmt_size(b.get('file_size'))})
    return images, files, videos


def load_messages(conv_id, page):
    """대화방 메시지 (시간 오름차순, 페이지). page는 1=가장 오래된 묶음."""
    with get_db() as db:
        total = db.execute(text("SELECT COUNT(*) FROM public.chat_messages WHERE conversation_id = :c"),
                           {'c': conv_id}).fetchone()[0]
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, page), total_pages)
        offset = (page - 1) * PAGE_SIZE
        rows = db.execute(text("""
            SELECT id, user_id, user_name, type, sent_time, text, raw_json
            FROM public.chat_messages
            WHERE conversation_id = :c
            ORDER BY sent_time ASC, id ASC
            LIMIT :lim OFFSET :off
        """), {'c': conv_id, 'lim': PAGE_SIZE, 'off': offset}).fetchall()

    items = []
    prev_date = None
    prev_uid = None
    for r in rows:
        dt = _dt(r[4])
        date_str = _fmt_date(dt) if dt else ''
        is_feed = (r[3] == 'feed')

        # 날짜 구분선
        if date_str and date_str != prev_date:
            items.append({'kind': 'date', 'date': date_str})
            prev_date = date_str
            prev_uid = None

        if is_feed:
            items.append({'kind': 'system', 'text': r[5] or ''})
            prev_uid = None
            continue

        images, files, videos = _media_from_blocks(conv_id, (r[6] or {}).get('blocks'))
        items.append({
            'kind': 'msg',
            'id': r[0],
            'user_id': r[1],
            'user_name': r[2] or '(알 수 없음)',
            'color': _avatar_color(r[1]),
            'time': _fmt_time(dt),
            'body': Markup(_render_text(r[5])) if r[5] else '',
            'images': images,
            'files': files,
            'videos': videos,
            'grouped': (r[1] == prev_uid),   # 직전과 같은 사람 → 이름/아바타 생략
            'is_reply': (r[3] == 'reply'),
        })
        prev_uid = r[1]

    return items, page, total_pages, total


def search_messages(conv_id, q, limit=120):
    """대화방 내 텍스트 검색 (최신순)."""
    with get_db() as db:
        rows = db.execute(text("""
            SELECT id, user_name, sent_time, text
            FROM public.chat_messages
            WHERE conversation_id = :c AND text ILIKE :q AND type <> 'feed'
            ORDER BY sent_time DESC, id DESC
            LIMIT :lim
        """), {'c': conv_id, 'q': f'%{q}%', 'lim': limit}).fetchall()
    out = []
    for r in rows:
        dt = _dt(r[2])
        out.append({
            'id': r[0],
            'user_name': r[1] or '(알 수 없음)',
            'color': _avatar_color(r[1]),
            'when': f'{_fmt_date(dt)} {_fmt_time(dt)}' if dt else '',
            'snippet': (r[3] or '')[:140],
        })
    return out


def page_of_message(conv_id, msg_id):
    """특정 메시지가 속한 페이지 번호 (load_messages 와 동일한 ASC 정렬 기준)."""
    with get_db() as db:
        row = db.execute(text("""
            SELECT sent_time FROM public.chat_messages
            WHERE conversation_id = :c AND id = :id
        """), {'c': conv_id, 'id': msg_id}).fetchone()
        if not row:
            return None
        pos = db.execute(text("""
            SELECT COUNT(*) FROM public.chat_messages
            WHERE conversation_id = :c
              AND (sent_time < :t OR (sent_time = :t AND id <= :id))
        """), {'c': conv_id, 't': row[0], 'id': msg_id}).fetchone()[0]
    return (pos - 1) // PAGE_SIZE + 1
