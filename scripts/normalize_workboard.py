"""카카오워크 워크보드 백업(raw) → ERP 아카이브 정규화 파이프라인.

  public.workboard_posts(raw_json)  →  light_sync.archive_posts + archive_comments

config.WORKBOARDS 레지스트리의 8개 보드를 모두 처리한다.
백업을 다시 긁어온 뒤(재검증 후) **그냥 다시 실행만 하면** 최신 상태로 갱신된다.

★ 안전장치 ★
  - 기본은 DRY-RUN: 건수만 집계해서 보여주고 DB는 건드리지 않는다.
  - 실제 기록은 `--commit` 플래그가 있을 때만.
  - 게시글 upsert 시 contract_id / contract_no(조달계약 매칭값)는 보존(덮어쓰지 않음).
  - 댓글은 post_id 단위로 DELETE 후 재삽입 → 재실행해도 중복/잔여 없음(멱등).

사용법:
  py scripts/normalize_workboard.py                 # 전체 보드 dry-run (집계만)
  py scripts/normalize_workboard.py --board notice  # 특정 보드만 dry-run
  py scripts/normalize_workboard.py --commit        # 전체 보드 실제 기록
  py scripts/normalize_workboard.py --board site --commit
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from modules.db_context import get_db
from config import WORKBOARDS

KST = timedelta(hours=9)


# ─────────────────────────────────────────────────────── 추출 헬퍼
def epoch_to_kst_naive(val):
    """카카오워크 epoch(초) → KST 벽시계 naive datetime (기존 archive_posts와 동일 표기)."""
    if val is None:
        return None
    try:
        ts = int(val)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:  # 혹시 ms 단위면 초로 환산
        ts //= 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None) + KST


def flatten_text(content):
    """ProseMirror doc → 검색용 평문(content_text)."""
    if not content:
        return ''
    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get('type') == 'text' and node.get('text'):
                parts.append(node['text'])
            elif node.get('type') == 'mention':
                label = (node.get('attrs') or {}).get('label')
                if label:
                    parts.append(f'@{label}')
            for c in node.get('content', []) or []:
                walk(c)
        elif isinstance(node, list):
            for c in node:
                walk(c)

    walk(content)
    return '\n'.join(p for p in parts if p is not None).strip()


def clean_attachments(atts):
    """첨부 리스트 → 필요한 필드만 (kakao_archive.parse_attachments 호환)."""
    out = []
    for att in atts or []:
        out.append({
            'id': att.get('id'),
            'file_name': att.get('file_name', ''),
            'ext_name': att.get('ext_name', ''),
            'content_type': att.get('content_type', ''),
            'file_type': att.get('file_type', 'etc'),
            'file_size': att.get('file_size', 0),
            'url': att.get('url', ''),
            'thumb_url': att.get('thumb_url', ''),
        })
    return out


def is_system_child(child):
    return str(child.get('type', '')).upper().startswith('SYSTEM')


def extract_post(raw):
    """raw_json → (post dict, [comment dict ...])."""
    content = raw.get('content')
    post = {
        'id': raw.get('id'),
        'author': (raw.get('user') or {}).get('display_name', '') or '',
        'content_text': flatten_text(content),
        'content_json': content,
        'attachments_json': clean_attachments(raw.get('attachments')),
        'is_notice': bool(raw.get('is_notice')),
        'created_at': epoch_to_kst_naive(raw.get('created_at')),
        'updated_at': epoch_to_kst_naive(raw.get('updated_at')),
    }

    comments = []
    for ch in raw.get('children', []) or []:
        if is_system_child(ch):
            continue
        c_content = ch.get('content')
        comments.append({
            'id': ch.get('id'),
            'author': (ch.get('user') or {}).get('display_name', '') or '',
            'content_text': flatten_text(c_content),
            'content_json': c_content,
            'attachments_json': clean_attachments(ch.get('attachments')),
            'created_at': epoch_to_kst_naive(ch.get('created_at')),
        })

    post['children_count'] = len(comments)
    return post, comments


def _j(v):
    return json.dumps(v, ensure_ascii=False) if v is not None else None


# ─────────────────────────────────────────────────────── 보드 처리
def process_board(db, slug, kakao_name, commit):
    rows = db.execute(text("""
        SELECT id, raw_json FROM public.workboard_posts
        WHERE board_type = :bt
        ORDER BY id
    """), {'bt': kakao_name}).fetchall()

    n_posts = n_comments = 0
    for _id, raw in rows:
        post, comments = extract_post(raw)
        if post['id'] is None:
            continue
        n_posts += 1
        n_comments += len(comments)

        if not commit:
            continue

        # 게시글 upsert — contract_id/contract_no 는 보존
        db.execute(text("""
            INSERT INTO light_sync.archive_posts
                (id, board_type, author, content_text, content_json,
                 attachments_json, is_notice, children_count, created_at, updated_at)
            VALUES
                (:id, :bt, :author, :ctext, CAST(:cjson AS jsonb),
                 CAST(:ajson AS jsonb), :notice, :ccount, :created, :updated)
            ON CONFLICT (id) DO UPDATE SET
                board_type       = EXCLUDED.board_type,
                author           = EXCLUDED.author,
                content_text     = EXCLUDED.content_text,
                content_json     = EXCLUDED.content_json,
                attachments_json = EXCLUDED.attachments_json,
                is_notice        = EXCLUDED.is_notice,
                children_count   = EXCLUDED.children_count,
                created_at       = EXCLUDED.created_at,
                updated_at       = EXCLUDED.updated_at
        """), {
            'id': post['id'], 'bt': slug, 'author': post['author'],
            'ctext': post['content_text'], 'cjson': _j(post['content_json']),
            'ajson': _j(post['attachments_json']), 'notice': post['is_notice'],
            'ccount': post['children_count'],
            'created': post['created_at'], 'updated': post['updated_at'],
        })

        # 댓글 멱등 재삽입 (post 단위 DELETE → INSERT)
        db.execute(text("DELETE FROM light_sync.archive_comments WHERE post_id = :pid"),
                   {'pid': post['id']})
        for c in comments:
            if c['id'] is None:
                continue
            db.execute(text("""
                INSERT INTO light_sync.archive_comments
                    (id, post_id, author, content_text, content_json, attachments_json, created_at)
                VALUES
                    (:id, :pid, :author, :ctext, CAST(:cjson AS jsonb), CAST(:ajson AS jsonb), :created)
                ON CONFLICT (id) DO UPDATE SET
                    post_id          = EXCLUDED.post_id,
                    author           = EXCLUDED.author,
                    content_text     = EXCLUDED.content_text,
                    content_json     = EXCLUDED.content_json,
                    attachments_json = EXCLUDED.attachments_json,
                    created_at       = EXCLUDED.created_at
            """), {
                'id': c['id'], 'pid': post['id'], 'author': c['author'],
                'ctext': c['content_text'], 'cjson': _j(c['content_json']),
                'ajson': _j(c['attachments_json']), 'created': c['created_at'],
            })

    return n_posts, n_comments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--board', help='특정 slug만 처리 (생략 시 전체)')
    ap.add_argument('--commit', action='store_true', help='실제 DB 기록 (없으면 dry-run)')
    args = ap.parse_args()

    targets = [(s, m['kakao']) for s, m in WORKBOARDS.items()
               if not args.board or s == args.board]
    if not targets:
        print(f'알 수 없는 보드: {args.board}  (가능: {", ".join(WORKBOARDS)})')
        return

    mode = 'COMMIT(실제 기록)' if args.commit else 'DRY-RUN(집계만)'
    print(f'\n=== 워크보드 정규화 [{mode}] ===')

    from app import app
    with app.app_context():
        with get_db() as db:
            tot_p = tot_c = 0
            for slug, kakao in targets:
                p, c = process_board(db, slug, kakao, args.commit)
                tot_p += p
                tot_c += c
                print(f'  [{slug:9}] {kakao:18} 게시글 {p:5}건  댓글 {c:6}건')

            # 현장관리(site) 신규 글 자동 매칭 → contract_id 연결 (커밋 직전, 같은 트랜잭션)
            if args.commit and any(slug == 'site' for slug, _ in targets):
                from modules.services.archive_matcher import match_site_posts
                mr = match_site_posts(db, commit=True)
                for r in mr['applied']:
                    print(f'  [자동매칭] post {r["post_id"]} → {r["contract_name"][:28]} ({r["score"]:.0%})')
                print(f'  [자동매칭] {len(mr["applied"])}건 연결 · 검토대기 {len(mr["candidates"])}건(<90%)')

            if args.commit:
                db.commit()
                print(f'\n커밋 완료: 게시글 {tot_p}건 / 댓글 {tot_c}건')
            else:
                print(f'\n합계(미반영): 게시글 {tot_p}건 / 댓글 {tot_c}건')
                print('실제 반영하려면 --commit 를 붙여 다시 실행하세요.')


if __name__ == '__main__':
    main()
