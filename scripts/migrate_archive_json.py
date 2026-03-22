"""SQLite raw_json → Supabase content_json + attachments_json 마이그레이션.

사전 조건: sql_editer.sql의 ALTER TABLE 실행 완료

사용법:
  py scripts/migrate_archive_json.py
"""
import sqlite3
import json
import os
import sys

# Flask 앱 컨텍스트 필요
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from modules.db_context import get_db


def extract_post_data(raw):
    """raw_json에서 content_json, attachments_json, children 추출."""
    data = json.loads(raw)

    content = data.get('content')  # ProseMirror doc
    attachments = data.get('attachments', [])
    children = data.get('children', [])

    # 첨부파일 정리 (필요한 필드만)
    clean_atts = []
    for att in attachments:
        clean_atts.append({
            'id': att['id'],
            'file_name': att.get('file_name', ''),
            'ext_name': att.get('ext_name', ''),
            'content_type': att.get('content_type', ''),
            'file_type': att.get('file_type', 'etc'),
            'file_size': att.get('file_size', 0),
            'url': att.get('url', ''),
            'thumb_url': att.get('thumb_url', ''),
        })

    # 댓글 데이터
    comments = []
    for child in children:
        if child.get('type') in ('SYSTEM_ENTERPRISE_BOARD_SET',):
            continue  # 시스템 메시지 스킵
        c_content = child.get('content')
        c_atts = []
        for att in child.get('attachments', []):
            c_atts.append({
                'id': att['id'],
                'file_name': att.get('file_name', ''),
                'ext_name': att.get('ext_name', ''),
                'content_type': att.get('content_type', ''),
                'file_type': att.get('file_type', 'etc'),
                'file_size': att.get('file_size', 0),
                'url': att.get('url', ''),
                'thumb_url': att.get('thumb_url', ''),
            })
        comments.append({
            'id': child['id'],
            'author': child.get('user', {}).get('display_name', ''),
            'content': c_content,
            'attachments': c_atts,
            'created_at': child.get('created_at'),
            'updated_at': child.get('updated_at'),
        })

    return content, clean_atts, comments


def migrate_board(db_path, board_type):
    """SQLite → Supabase 마이그레이션."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id, raw_json FROM posts WHERE raw_json IS NOT NULL')
    rows = cur.fetchall()
    conn.close()

    print(f'\n[{board_type}] {len(rows)}개 게시글 마이그레이션...')

    with get_db() as db:
        updated_posts = 0
        updated_comments = 0

        for post_id, raw in rows:
            content, attachments, comments = extract_post_data(raw)

            # 게시글 content_json, attachments_json 업데이트
            db.execute(text("""
                UPDATE light_sync.archive_posts
                SET content_json = :cj, attachments_json = :aj
                WHERE id = :id
            """), {
                'id': post_id,
                'cj': json.dumps(content, ensure_ascii=False) if content else None,
                'aj': json.dumps(attachments, ensure_ascii=False),
            })
            updated_posts += 1

            # 댓글 content_json, attachments_json 업데이트
            for comment in comments:
                # archive_comments에 해당 댓글이 있는지 확인
                existing = db.execute(text("""
                    SELECT id FROM light_sync.archive_comments
                    WHERE post_id = :pid AND author = :author
                    AND created_at = to_timestamp(:ts)
                """), {
                    'pid': post_id,
                    'author': comment['author'],
                    'ts': comment['created_at'],
                }).fetchone()

                if existing:
                    db.execute(text("""
                        UPDATE light_sync.archive_comments
                        SET content_json = :cj, attachments_json = :aj
                        WHERE id = :id
                    """), {
                        'id': existing[0],
                        'cj': json.dumps(comment['content'], ensure_ascii=False) if comment['content'] else None,
                        'aj': json.dumps(comment['attachments'], ensure_ascii=False),
                    })
                    updated_comments += 1

        db.commit()

    print(f'  게시글 {updated_posts}개, 댓글 {updated_comments}개 업데이트 완료')


def main():
    from app import app
    with app.app_context():
        migrate_board('.trash/workboard.db', 'site')
        migrate_board('.trash/as.db', 'as')
    print('\n마이그레이션 완료!')


if __name__ == '__main__':
    main()
