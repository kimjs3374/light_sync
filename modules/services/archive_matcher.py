"""워크보드 아카이브 ↔ 조달계약 자동 매칭 (단일 원천).

현장관리(site) 게시글 본문에서 건명을 추출해 contracts.contract_name과 매칭,
score >= threshold 이면 archive_posts.contract_id 를 채운다.

- 이미 연결된 글(contract_id NOT NULL)은 절대 건드리지 않음 (멱등, IS NULL 가드).
- 매칭 로직은 명세서 `.claude/archive_matching_spec.md` 기준:
  포함관계(0.9) / 한글 키워드 교집합 / SequenceMatcher 유사도 중 max.
- 백업 정규화(scripts/normalize_workboard.py) 말미에서 호출되어 신규 글을 자동 연결.
- 수동 재실행: `venv/bin/python -m modules.services.archive_matcher [--commit] [--threshold 0.9]`

주의: 커밋은 호출자가 통제한다. commit=True 는 UPDATE 문만 세션에 실행하며,
최종 db.commit() 은 호출측(normalize main / 이 모듈의 __main__)이 수행한다.
"""
import re
from difflib import SequenceMatcher

from sqlalchemy import text

DEFAULT_THRESHOLD = 0.90       # dry-run 25/25 정확 검증된 안전선
REVIEW_FLOOR = 0.30            # 이 미만은 후보에도 안 올림 (현장글 아님으로 간주)

# reverify(정밀도 정리)용 임계값
KEEP_FLOOR = 0.60             # 현재 연결이 이 이상이면 유지
UNLINK_CEIL = 0.50            # 어떤 계약과도 이 미만이면 연결 해제(오연결/무건명)
RELINK_FLOOR = 0.90           # 다른 계약이 이 이상이면 그쪽으로 재연결

_TITLE_PATS = [r'건\s*명\s*:\s*(.+)', r'현장명\s*:\s*(.+)', r'계약명\s*:\s*(.+)']
_STOP = re.compile(r'계약일자|납품기한|곙약일자|출고|납품')
_NORM = re.compile(r'[\s\-_()（）\[\]]+')
_HANGUL2 = re.compile(r'[가-힣]{2,}')


def extract_title(content_text):
    """본문에서 건명 추출. 표준양식(건명 :) 우선, 없으면 첫 줄(80자)."""
    t = content_text or ''
    for pat in _TITLE_PATS:
        m = re.search(pat, t)
        if m:
            s = _STOP.split(m.group(1))[0].lstrip(': ').strip()
            if s:
                return s
    first = t.strip().split('\n')[0]
    return first[:80]


def site_score(title, contract_name):
    """건명 vs 계약명 유사도 (0.0~1.0). gen_matching_xlsx.py site_score 로직."""
    if not title or not contract_name:
        return 0.0
    ac = _NORM.sub('', title)
    nc = _NORM.sub('', contract_name)
    best = 0.0
    if len(ac) >= 2 and ac in nc:
        best = max(best, 0.9)
    elif len(nc) >= 2 and nc in ac:
        best = max(best, 0.9)
    aw = set(_HANGUL2.findall(title))
    nw = set(_HANGUL2.findall(contract_name))
    if aw and nw:
        best = max(best, len(aw & nw) / max(len(aw), len(nw)))
    best = max(best, SequenceMatcher(None, ac, nc).ratio())
    return best


def match_site_posts(db, threshold=DEFAULT_THRESHOLD, commit=False):
    """미연결 site 게시글을 매칭.

    Args:
        db: SQLAlchemy 세션
        threshold: 이 이상이면 자동 연결(applied)
        commit: True면 contract_id UPDATE 실행 (최종 commit 은 호출자 책임)

    Returns:
        {'applied': [rec...], 'candidates': [rec...]}
        rec = {post_id, contract_id, contract_name, score, title}
        candidates = REVIEW_FLOOR~threshold 구간 (수동 검토 대상)
    """
    contracts = db.execute(text("""
        SELECT id, contract_name FROM light_sync.contracts
        WHERE contract_name IS NOT NULL AND contract_name <> ''
    """)).fetchall()
    posts = db.execute(text("""
        SELECT id, content_text FROM light_sync.archive_posts
        WHERE board_type = 'site' AND contract_id IS NULL
    """)).fetchall()

    applied, candidates = [], []
    for p in posts:
        title = extract_title(p.content_text)
        if not title:
            continue
        best_s, best_c = 0.0, None
        for c in contracts:
            s = site_score(title, c.contract_name)
            if s > best_s:
                best_s, best_c = s, c
        if not best_c or best_s < REVIEW_FLOOR:
            continue
        rec = {
            'post_id': p.id, 'contract_id': best_c.id,
            'contract_name': best_c.contract_name,
            'score': round(best_s, 3), 'title': title,
        }
        if best_s >= threshold:
            if commit:
                db.execute(text("""
                    UPDATE light_sync.archive_posts SET contract_id = :cid
                    WHERE id = :pid AND board_type = 'site' AND contract_id IS NULL
                """), {'cid': best_c.id, 'pid': p.id})
            applied.append(rec)
        else:
            candidates.append(rec)
    return {'applied': applied, 'candidates': candidates}


def reverify_site_posts(db, commit=False):
    """이미 연결된 site 게시글의 정밀도 재검증(정리).

    각 글의 건명을 현재 계약명과 재비교하여:
      - KEEP  : 현재 유사도 >= KEEP_FLOOR (유지)
      - RELINK: 다른 계약이 RELINK_FLOOR 이상 (그쪽으로 재연결)
      - UNLINK: 어떤 계약과도 UNLINK_CEIL 미만 (오연결/무건명 → 연결 해제, contract_id=NULL)
      - REVIEW : 그 외 애매구간 (건드리지 않음)

    자동 훅(match_site_posts)과 분리 — 해제는 수동/주기 실행 전용.
    최종 commit 은 호출자 책임.

    Returns: {'relink': [...], 'unlink': [...], 'review_count': int, 'keep_count': int}
    """
    contracts = db.execute(text("""
        SELECT id, contract_name FROM light_sync.contracts
        WHERE contract_name IS NOT NULL AND contract_name <> ''
    """)).fetchall()
    linked = db.execute(text("""
        SELECT ap.id, ap.content_text, ap.contract_id, c.contract_name AS cur_name
        FROM light_sync.archive_posts ap
        JOIN light_sync.contracts c ON c.id = ap.contract_id
        WHERE ap.board_type = 'site'
    """)).fetchall()

    relink, unlink = [], []
    keep_count = review_count = 0
    for r in linked:
        title = extract_title(r.content_text)
        cur_s = site_score(title, r.cur_name)
        best_s, best_c = 0.0, None
        for c in contracts:
            s = site_score(title, c.contract_name)
            if s > best_s:
                best_s, best_c = s, c

        if cur_s >= KEEP_FLOOR:
            keep_count += 1
        elif best_c and best_s >= RELINK_FLOOR and best_c.id != r.contract_id:
            if commit:
                db.execute(text("UPDATE light_sync.archive_posts SET contract_id=:cid WHERE id=:pid"),
                           {'cid': best_c.id, 'pid': r.id})
            relink.append({'post_id': r.id, 'from': r.cur_name, 'to': best_c.contract_name,
                           'score': round(best_s, 3), 'title': title})
        elif best_s < UNLINK_CEIL:
            if commit:
                db.execute(text("UPDATE light_sync.archive_posts SET contract_id=NULL WHERE id=:pid"),
                           {'pid': r.id})
            unlink.append({'post_id': r.id, 'was': r.cur_name, 'best_score': round(best_s, 3), 'title': title})
        else:
            review_count += 1

    return {'relink': relink, 'unlink': unlink,
            'review_count': review_count, 'keep_count': keep_count}


if __name__ == '__main__':
    import os
    import sys
    import argparse
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from modules.db_context import get_db

    ap = argparse.ArgumentParser(description='워크보드 현장관리 아카이브 자동 매칭')
    ap.add_argument('--commit', action='store_true', help='실제 DB 기록 (없으면 dry-run)')
    ap.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument('--reverify', action='store_true', help='기존 연결 정밀도 재검증(정리) 모드')
    args = ap.parse_args()

    from app import app
    with app.app_context():
        with get_db() as db:
            if args.reverify:
                res = reverify_site_posts(db, commit=args.commit)
                for r in res['relink']:
                    print(f"[재연결] post {r['post_id']} ({r['score']:.0%})  "
                          f"{r['from'][:22]} → {r['to'][:22]}")
                for r in res['unlink']:
                    print(f"[해제]   post {r['post_id']} (best {r['best_score']:.0%})  "
                          f"건명='{r['title'][:26]}'")
                summary = (f"재연결 {len(res['relink'])} · 해제 {len(res['unlink'])} · "
                           f"유지 {res['keep_count']} · 보류 {res['review_count']}")
                if args.commit:
                    db.commit()
                    print(f"\n커밋 완료: {summary}")
                else:
                    print(f"\n[DRY-RUN] {summary}. --commit 로 반영.")
            else:
                res = match_site_posts(db, threshold=args.threshold, commit=args.commit)
                for r in res['applied']:
                    print(f"[매칭] post {r['post_id']} → cid {r['contract_id']} "
                          f"{r['contract_name'][:34]} ({r['score']:.0%})")
                for r in res['candidates']:
                    print(f"[검토] post {r['post_id']} → {r['contract_name'][:34]} "
                          f"({r['score']:.0%})  건명='{r['title'][:24]}'")
                if args.commit:
                    db.commit()
                    print(f"\n커밋 완료: {len(res['applied'])}건 연결 "
                          f"(검토대기 {len(res['candidates'])}건)")
                else:
                    print(f"\n[DRY-RUN] {len(res['applied'])}건 연결 예정, "
                          f"검토대기 {len(res['candidates'])}건. --commit 로 반영.")
