"""카카오워크 워크보드 아카이브 공용 헬퍼 (Supabase 버전).

ProseMirror content_json → HTML 변환 + 첨부파일 관리.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from markupsafe import Markup, escape

from sqlalchemy import text
from modules.db_context import get_db
from config import WORKBOARD_BOARD_IDS

PAGE_SIZE = 20
STORAGE_BASE = 'storage/archive'

# Supabase Storage 설정
_SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
_SUPABASE_BUCKET = 'company-files'


def _storage_url(board_type, post_id, att_id, ext_name):
    """로컬 파일 우선, 없으면 Supabase Storage URL.

    Supabase 키 스킴: archive/{board_id}/{post_id}/{att_id}{ext}
      예) archive/55772/18402/14381.png
    (파일명을 att_id+확장자로만 구성 → 한글 파일명 키 문제 회피)
    """
    # 로컬 파일 우선 (레거시; 현재는 미사용)
    local_dir = os.path.join(STORAGE_BASE, board_type, str(post_id))
    if os.path.isdir(local_dir):
        prefix = f'{att_id}_'
        for f in os.listdir(local_dir):
            if f.startswith(prefix):
                return f'/static-archive/{board_type}/{post_id}/{f}'

    # Supabase Storage (board_id 기반)
    if _SUPABASE_URL:
        board_id = WORKBOARD_BOARD_IDS.get(board_type)
        if board_id is None:
            return None
        ext = ext_name or ''
        storage_key = f'archive/{board_id}/{post_id}/{att_id}{ext}'
        return f'{_SUPABASE_URL}/storage/v1/object/public/{_SUPABASE_BUCKET}/{storage_key}'

    return None


def fmt_dt(val):
    """날짜 포맷: 카카오워크 스타일 (3월 20일(금) 오후 4:13)."""
    if not val:
        return ''
    if isinstance(val, datetime):
        dt = (val + timedelta(hours=9)) if val.tzinfo else val
    else:
        try:
            dt = datetime.strptime(str(val), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            dt = dt + timedelta(hours=9)
        except Exception:
            return str(val)

    weekdays = ['월', '화', '수', '목', '금', '토', '일']
    wd = weekdays[dt.weekday()]
    ampm = '오전' if dt.hour < 12 else '오후'
    h = dt.hour if dt.hour <= 12 else dt.hour - 12
    if h == 0:
        h = 12
    return f'{dt.year}년 {dt.month}월 {dt.day}일({wd}) {ampm} {h}:{dt.minute:02d}'


def fmt_dt_short(val):
    """짧은 날짜: 목록용."""
    if not val:
        return ''
    if isinstance(val, datetime):
        dt = (val + timedelta(hours=9)) if val.tzinfo else val
    else:
        try:
            dt = datetime.strptime(str(val), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            dt = dt + timedelta(hours=9)
        except Exception:
            return str(val)
    return f'{dt.year}.{dt.month:02d}.{dt.day:02d}'


# ─── ProseMirror → HTML 렌더러 ───

def render_prosemirror(content_json, fallback_text=''):
    """ProseMirror content JSON → HTML 문자열.

    지원 노드: doc, paragraph, text
    지원 marks: bold, link
    지원 인라인: mention
    """
    if not content_json:
        return escape(fallback_text).replace('\n', Markup('<br>'))

    if isinstance(content_json, str):
        try:
            content_json = json.loads(content_json)
        except (json.JSONDecodeError, TypeError):
            return escape(fallback_text).replace('\n', Markup('<br>'))

    parts = []
    for node in content_json.get('content', []):
        parts.append(_render_node(node))
    return Markup(''.join(parts))


def _render_node(node):
    """단일 노드 렌더링."""
    ntype = node.get('type', '')

    if ntype == 'doc':
        return ''.join(_render_node(c) for c in node.get('content', []))

    if ntype == 'paragraph':
        inner = ''.join(_render_node(c) for c in node.get('content', []))
        return f'<p>{inner}</p>'

    if ntype == 'text':
        txt = str(escape(node.get('text', '')))
        # marks 적용
        for mark in node.get('marks', []):
            mtype = mark.get('type', '')
            if mtype == 'bold':
                txt = f'<strong>{txt}</strong>'
            elif mtype == 'link':
                href = escape(mark.get('attrs', {}).get('href', '#'))
                txt = f'<a href="{href}" target="_blank" rel="noopener">{txt}</a>'
        return txt

    if ntype == 'mention':
        label = escape(node.get('attrs', {}).get('label', ''))
        return f'<span class="kw-mention">@{label}</span>'

    if ntype == 'bold':
        inner = ''.join(_render_node(c) for c in node.get('content', []))
        return f'<strong>{inner}</strong>'

    # 알 수 없는 노드
    return ''


# ─── 첨부파일 헬퍼 ───

def parse_attachments(atts_json, board_type, post_id):
    """attachments_json → 템플릿용 딕셔너리 리스트."""
    if not atts_json:
        return []
    if isinstance(atts_json, str):
        try:
            atts_json = json.loads(atts_json)
        except (json.JSONDecodeError, TypeError):
            return []

    result = []
    for att in atts_json:
        att_id = att.get('id', 0)
        fname = att.get('file_name', '')
        ftype = att.get('file_type', 'etc')
        fsize = att.get('file_size', 0)
        ext_name = att.get('ext_name') or os.path.splitext(fname)[1]

        file_url = _storage_url(board_type, post_id, att_id, ext_name)
        is_image = ftype == 'img'

        # 썸네일 URL: 로컬은 on-the-fly, Supabase는 이미지 변환(render/image)으로 경량화
        # (원본 717KB → 변환 ~15KB. data-full 원본은 그대로 두고 클릭 시 원본 표시)
        thumb_url = None
        if is_image and file_url:
            if file_url.startswith('/static-archive/'):
                thumb_url = file_url.replace('/static-archive/', '/static-archive/thumb/', 1)
            elif '/storage/v1/object/public/' in file_url:
                thumb_url = file_url.replace(
                    '/storage/v1/object/public/', '/storage/v1/render/image/public/', 1
                ) + '?width=300&quality=70'

        result.append({
            'id': att_id,
            'file_name': fname,
            'file_type': ftype,
            'file_size': fsize,
            'file_size_fmt': _fmt_size(fsize),
            'ext': att.get('ext_name', '').lstrip('.').lower(),
            'local_url': file_url,
            'thumb_url': thumb_url,
            'original_url': att.get('url', ''),
            'is_image': is_image,
        })
    return result


def _fmt_size(size_bytes):
    """파일 크기 포맷."""
    if size_bytes < 1024:
        return f'{size_bytes}B'
    if size_bytes < 1024 * 1024:
        return f'{size_bytes/1024:.1f}KB'
    return f'{size_bytes/1024/1024:.2f}MB'


# ─── 데이터 조회 ───

def load_post(board_type, post_id):
    """게시글 상세 + 댓글 조회."""
    with get_db() as db:
        row = db.execute(text("""
            SELECT p.id, p.board_type, p.author, p.content_text,
                   p.content_json, p.attachments_json,
                   p.is_notice, p.children_count, p.created_at, p.updated_at,
                   p.contract_id
            FROM light_sync.archive_posts p
            WHERE p.id = :id
        """), {'id': post_id}).fetchone()

        if not row:
            return None

        comments_rows = db.execute(text("""
            SELECT id, author, content_text, content_json, attachments_json, created_at
            FROM light_sync.archive_comments
            WHERE post_id = :pid
            ORDER BY created_at ASC
        """), {'pid': post_id}).fetchall()

    # 본문 HTML 렌더링
    body_html = render_prosemirror(row.content_json, row.content_text or '')
    attachments = parse_attachments(row.attachments_json, board_type, post_id)

    d = {
        'id': row.id,
        'board_type': row.board_type,
        'author': row.author or '',
        'body_html': body_html,
        'body': row.content_text or '',
        'is_notice': row.is_notice,
        'children_count': row.children_count or 0,
        'created_fmt': fmt_dt(row.created_at),
        'updated_fmt': fmt_dt(row.updated_at),
        'is_updated': (row.updated_at and row.created_at and
                       str(row.updated_at) != str(row.created_at)),
        'contract_id': row.contract_id,
        'attachments': attachments,
        'comments': [],
    }

    for c in comments_rows:
        c_html = render_prosemirror(c.content_json, c.content_text or '')
        c_atts = parse_attachments(c.attachments_json, board_type, post_id)
        d['comments'].append({
            'id': c.id,
            'author': c.author or '',
            'body_html': c_html,
            'body': c.content_text or '',
            'created_fmt': fmt_dt(c.created_at),
            'attachments': c_atts,
        })

    return d


def list_posts(board_type, page, q, author):
    """게시글 목록 조회 (피드형: 댓글 + 첨부파일 포함)."""
    offset = (page - 1) * PAGE_SIZE
    wheres = ['p.board_type = :bt']
    params = {'bt': board_type}

    if q:
        wheres.append('p.content_text ILIKE :q')
        params['q'] = f'%{q}%'
    if author:
        wheres.append('p.author = :author')
        params['author'] = author

    where_sql = 'WHERE ' + ' AND '.join(wheres)

    with get_db() as db:
        authors_raw = [
            r[0] for r in db.execute(text("""
                SELECT DISTINCT author FROM light_sync.archive_posts
                WHERE board_type = :bt AND author IS NOT NULL
                ORDER BY author
            """), {'bt': board_type}).fetchall()
        ]

        total = db.execute(text(f"""
            SELECT COUNT(*) FROM light_sync.archive_posts p {where_sql}
        """), params).fetchone()[0]

        rows = db.execute(text(f"""
            SELECT p.id, p.author, p.content_text, p.content_json,
                   p.attachments_json, p.is_notice,
                   p.children_count, p.created_at, p.updated_at,
                   p.contract_id
            FROM light_sync.archive_posts p
            {where_sql}
            ORDER BY p.created_at DESC
            LIMIT :lim OFFSET :off
        """), {**params, 'lim': PAGE_SIZE, 'off': offset}).fetchall()

        # 해당 페이지 게시글들의 댓글 일괄 조회
        post_ids = [r.id for r in rows]
        comments_map = {}
        if post_ids:
            placeholders = ','.join(f':pid{i}' for i in range(len(post_ids)))
            c_params = {f'pid{i}': pid for i, pid in enumerate(post_ids)}
            c_rows = db.execute(text(f"""
                SELECT id, post_id, author, content_text, content_json,
                       attachments_json, created_at
                FROM light_sync.archive_comments
                WHERE post_id IN ({placeholders})
                ORDER BY created_at ASC
            """), c_params).fetchall()
            for c in c_rows:
                comments_map.setdefault(c.post_id, []).append(c)

    posts = []
    for row in rows:
        body_html = render_prosemirror(row.content_json, row.content_text or '')
        attachments = parse_attachments(row.attachments_json, board_type, row.id)

        # 댓글
        comments = []
        for c in comments_map.get(row.id, []):
            c_html = render_prosemirror(c.content_json, c.content_text or '')
            c_atts = parse_attachments(c.attachments_json, board_type, row.id)
            comments.append({
                'id': c.id,
                'author': c.author or '',
                'body_html': c_html,
                'created_fmt': fmt_dt(c.created_at),
                'attachments': c_atts,
            })

        posts.append({
            'id': row.id,
            'author': row.author or '',
            'body_html': body_html,
            'is_notice': row.is_notice,
            'children_count': row.children_count or 0,
            'created_fmt': fmt_dt(row.created_at),
            'is_updated': (row.updated_at and row.created_at and
                           str(row.updated_at) != str(row.created_at)),
            'contract_id': row.contract_id,
            'attachments': attachments,
            'comments': comments,
        })

    return posts, total, authors_raw
