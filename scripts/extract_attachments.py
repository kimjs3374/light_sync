"""SQLite raw_json에서 첨부파일 목록 추출 → JSON 파일 생성."""
import sqlite3
import json
import os

def extract(db_path, board_type):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id, raw_json FROM posts WHERE raw_json IS NOT NULL')
    results = []
    for (post_id, rj) in cur.fetchall():
        data = json.loads(rj)
        # 본문 첨부파일
        for att in data.get('attachments', []):
            results.append({
                'board_type': board_type,
                'post_id': post_id,
                'comment_id': None,
                'att_id': att['id'],
                'url': att['url'],
                'file_name': att.get('file_name', f'{att["id"]}'),
                'file_type': att.get('file_type', 'etc'),
                'content_type': att.get('content_type', ''),
                'file_size': att.get('file_size', 0),
                'thumb_url': att.get('thumb_url', ''),
            })
        # 댓글 첨부파일
        for child in data.get('children', []):
            for att in child.get('attachments', []):
                results.append({
                    'board_type': board_type,
                    'post_id': post_id,
                    'comment_id': child['id'],
                    'att_id': att['id'],
                    'url': att['url'],
                    'file_name': att.get('file_name', f'{att["id"]}'),
                    'file_type': att.get('file_type', 'etc'),
                    'content_type': att.get('content_type', ''),
                    'file_size': att.get('file_size', 0),
                    'thumb_url': att.get('thumb_url', ''),
                })
    conn.close()
    return results

all_atts = []
all_atts.extend(extract('.trash/workboard.db', 'site'))
all_atts.extend(extract('.trash/as.db', 'as'))

out_path = 'scripts/attachments_manifest.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(all_atts, f, ensure_ascii=False, indent=2)

print(f'Total: {len(all_atts)} attachments')
print(f'Site: {sum(1 for a in all_atts if a["board_type"]=="site")}')
print(f'AS: {sum(1 for a in all_atts if a["board_type"]=="as")}')
print(f'Total size: {sum(a["file_size"] for a in all_atts)/1024/1024:.1f} MB')
print(f'Written to {out_path}')
