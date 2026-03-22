"""카카오워크 워크보드 아카이브 공용 헬퍼."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

PAGE_SIZE = 20


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.text_factory = bytes
    conn.row_factory = sqlite3.Row
    return conn


def decode_row(row):
    d = {}
    for key in row.keys():
        val = row[key]
        if isinstance(val, bytes):
            val = val.decode('utf-8')
        d[key] = val
    return d


def parse_content(content_node):
    """ProseMirror doc → plain text (bold → **text**)"""
    if not content_node:
        return ''
    lines = []
    for block in content_node.get('content', []):
        parts = []
        for inline in block.get('content', []):
            text = inline.get('text', '')
            if 'bold' in [m['type'] for m in inline.get('marks', [])]:
                text = f'**{text}**'
            parts.append(text)
        lines.append(''.join(parts))
    return '\n'.join(lines)


def fmt_dt(iso_str):
    if not iso_str:
        return ''
    try:
        dt = datetime.strptime(iso_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        return (dt + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return iso_str


def load_post(db_path, post_id):
    with get_conn(db_path) as conn:
        cur = conn.execute('SELECT * FROM posts WHERE id=?', (post_id,))
        row = cur.fetchone()
    if not row:
        return None
    d = decode_row(row)
    raw = json.loads(d['raw_json'])
    d['body'] = parse_content(raw.get('content'))
    d['created_fmt'] = fmt_dt(d['created_at'])
    d['updated_fmt'] = fmt_dt(d['updated_at'])
    d['attachments'] = raw.get('attachments', [])
    d['comments'] = [
        {
            'id': ch['id'],
            'author': ch.get('user', {}).get('display_name', ''),
            'body': parse_content(ch.get('content')),
            'created_fmt': fmt_dt(ch.get('created_at', '')),
            'attachments': ch.get('attachments', []),
        }
        for ch in raw.get('children', [])
    ]
    return d


def list_posts(db_path, page, q, author):
    offset = (page - 1) * PAGE_SIZE
    wheres, params = [], []
    if q:
        wheres.append('content_text LIKE ?')
        params.append(f'%{q}%')
    if author:
        wheres.append('author = ?')
        params.append(author.encode('utf-8'))

    where_sql = ('WHERE ' + ' AND '.join(wheres)) if wheres else ''

    with get_conn(db_path) as conn:
        authors_raw = [
            r[0].decode('utf-8') if isinstance(r[0], bytes) else r[0]
            for r in conn.execute('SELECT DISTINCT author FROM posts ORDER BY author').fetchall()
        ]
        total = conn.execute(f'SELECT COUNT(*) FROM posts {where_sql}', params).fetchone()[0]
        rows = conn.execute(
            f'SELECT id, author, content_text, is_notice, children_count, created_at '
            f'FROM posts {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?',
            params + [PAGE_SIZE, offset],
        ).fetchall()

    posts = []
    for row in rows:
        d = decode_row(row)
        lines = [l for l in d['content_text'].split('\n') if l.strip()]
        d['preview'] = '\n'.join(lines[:3])
        d['created_fmt'] = fmt_dt(d['created_at'])
        posts.append(d)

    return posts, total, authors_raw
