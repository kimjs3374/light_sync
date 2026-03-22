"""카카오워크 워크보드 아카이브 공용 헬퍼 (Supabase 버전)."""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from modules.db_context import get_db

PAGE_SIZE = 20


def fmt_dt(val):
    if not val:
        return ''
    if isinstance(val, datetime):
        return (val + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M') if val.tzinfo else val.strftime('%Y-%m-%d %H:%M')
    try:
        dt = datetime.strptime(str(val), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        return (dt + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(val)


def load_post(board_type, post_id):
    """게시글 상세 + 댓글 조회."""
    with get_db() as db:
        row = db.execute(text("""
            SELECT p.id, p.board_type, p.author, p.content_text,
                   p.is_notice, p.children_count, p.created_at, p.updated_at,
                   p.contract_id
            FROM light_sync.archive_posts p
            WHERE p.id = :id
        """), {'id': post_id}).fetchone()

        if not row:
            return None

        comments_rows = db.execute(text("""
            SELECT id, author, content_text, created_at
            FROM light_sync.archive_comments
            WHERE post_id = :pid
            ORDER BY created_at ASC
        """), {'pid': post_id}).fetchall()

    d = {
        'id': row.id,
        'board_type': row.board_type,
        'author': row.author or '',
        'content_text': row.content_text or '',
        'body': row.content_text or '',
        'is_notice': row.is_notice,
        'children_count': row.children_count or 0,
        'created_at': str(row.created_at or ''),
        'updated_at': str(row.updated_at or ''),
        'created_fmt': fmt_dt(row.created_at),
        'updated_fmt': fmt_dt(row.updated_at),
        'contract_id': row.contract_id,
        'attachments': [],
        'comments': [
            {
                'id': c.id,
                'author': c.author or '',
                'body': c.content_text or '',
                'created_fmt': fmt_dt(c.created_at),
                'attachments': [],
            }
            for c in comments_rows
        ],
    }
    return d


def list_posts(board_type, page, q, author):
    """게시글 목록 조회."""
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
            r[0] for r in db.execute(text(f"""
                SELECT DISTINCT author FROM light_sync.archive_posts
                WHERE board_type = :bt AND author IS NOT NULL
                ORDER BY author
            """), {'bt': board_type}).fetchall()
        ]

        total = db.execute(text(f"""
            SELECT COUNT(*) FROM light_sync.archive_posts p {where_sql}
        """), params).fetchone()[0]

        rows = db.execute(text(f"""
            SELECT p.id, p.author, p.content_text, p.is_notice,
                   p.children_count, p.created_at, p.contract_id
            FROM light_sync.archive_posts p
            {where_sql}
            ORDER BY p.created_at DESC
            LIMIT :lim OFFSET :off
        """), {**params, 'lim': PAGE_SIZE, 'off': offset}).fetchall()

    posts = []
    for row in rows:
        content = row.content_text or ''
        lines = [l for l in content.split('\n') if l.strip()]
        posts.append({
            'id': row.id,
            'author': row.author or '',
            'content_text': content,
            'preview': '\n'.join(lines[:3]),
            'is_notice': row.is_notice,
            'children_count': row.children_count or 0,
            'created_at': str(row.created_at or ''),
            'created_fmt': fmt_dt(row.created_at),
            'contract_id': row.contract_id,
        })

    return posts, total, authors_raw
