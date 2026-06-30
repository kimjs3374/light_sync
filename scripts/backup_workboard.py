"""카카오워크 워크보드 전체 백업 (유료화 대비 아카이빙).

★ 사용법 — 로컬 PC에서 ★
  1) 처음 한 번만:  pip install playwright  &&  python -m playwright install chromium
  2) 실행:          py scripts/backup_workboard.py
  3) 크롬 창이 뜨면 카카오워크 로그인 → 콘솔에 Enter
     → 이후 전부 자동: 사이드바 게시판을 하나씩 찾아 들어가
        끝까지 스크롤하며 모든 글/댓글/첨부를 긁어옵니다 (조작 불필요)
     ※ 자동 발견이 안 되면 그때만 수동(게시판 열고 Enter)으로 전환

결과물 (workboard_backup/ 폴더):
  - raw_capture.db    : 브라우저가 불러온 원본 응답 전량 (재파싱용, 절대 삭제 X)
  - workboard.db      : posts(id, board_type, raw_json) 정규화본 (= 기존 마이그레이션 호환)
  - attachments_manifest.json : 첨부파일 다운로드 목록

원본(raw)을 그대로 저장하므로, 파싱이 어긋나도 재로그인 없이 다시 처리할 수 있습니다.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright가 없습니다. 먼저 실행하세요:")
    print("  pip install playwright")
    print("  python -m playwright install chromium")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent / "workboard_backup"
BASE_DIR.mkdir(exist_ok=True)
RAW_DB = BASE_DIR / "raw_capture.db"
OUT_DB = BASE_DIR / "workboard.db"
MANIFEST = BASE_DIR / "attachments_manifest.json"
STORAGE_DIR = BASE_DIR / "storage"
DL_PROGRESS = BASE_DIR / "download_progress.json"

WORKBOARD_URL = "https://workboard.kakaowork.com"

# 현재 어느 보드를 긁는 중인지 (응답 태깅용)
_current_board = {"type": "unknown"}


# ─────────────────────────────────────────────────────────── raw 저장
def init_raw_db():
    conn = sqlite3.connect(RAW_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_capture (
            seq        INTEGER PRIMARY KEY AUTOINCREMENT,
            board_type TEXT,
            method     TEXT,
            url        TEXT,
            ts         REAL,
            body       TEXT
        )
    """)
    conn.commit()
    return conn


def save_raw(conn, method, url, body, ts):
    conn.execute(
        "INSERT INTO raw_capture(board_type, method, url, ts, body) VALUES (?,?,?,?,?)",
        (_current_board["type"], method, url, ts, body),
    )
    conn.commit()


# ─────────────────────────────────────────────────────────── 응답 캡처
def make_response_handler(conn, counter):
    def handler(resp):
        try:
            url = resp.url
            if "kakaowork" not in url:
                return
            ct = (resp.headers or {}).get("content-type", "")
            if "json" not in ct:
                return
            body = resp.text()
            if not body or body[0] not in "[{":
                return
            save_raw(conn, resp.request.method, url, body, time.time())
            counter[0] += 1
            if counter[0] % 25 == 0:
                print(f"   …캡처 {counter[0]}건")
        except Exception:
            pass  # 본문 못 읽는 응답은 무시
    return handler


# ─────────────────────────────────────────────────────────── 자동 스크롤
def auto_scroll(page, max_idle=6):
    """현재 보드를 끝까지 스크롤해 모든 글을 로드시킨다.
    캡처 건수가 max_idle회 연속 안 늘면 끝으로 판단."""
    js_scroll = """
        () => {
            window.scrollBy(0, 4000);
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollHeight > el.clientHeight + 50) {
                    el.scrollTop = el.scrollTop + 4000;
                }
            });
        }
    """
    conn = sqlite3.connect(RAW_DB)
    last = -1
    idle = 0
    rounds = 0
    while idle < max_idle:
        try:
            page.evaluate(js_scroll)
            page.mouse.wheel(0, 4000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        cur = conn.execute("SELECT COUNT(*) FROM raw_capture").fetchone()[0]
        rounds += 1
        if cur == last:
            idle += 1
        else:
            idle = 0
            print(f"   스크롤 {rounds}회 · 누적 캡처 {cur}건")
        last = cur
    conn.close()
    print(f"   ▶ 이 보드 스크롤 완료 (총 {rounds}회)")


def try_open_posts(page):
    """가능하면 각 글을 열어 댓글까지 로드(셀렉터는 보수적으로 시도)."""
    candidates = [
        "[class*='post']", "[class*='Post']",
        "[class*='card']", "[class*='Card']",
        "article", "li[role='listitem']",
    ]
    for sel in candidates:
        try:
            items = page.query_selector_all(sel)
            if len(items) >= 3:
                print(f"   글 항목 {len(items)}개 감지({sel}) → 하나씩 열어 댓글 로드")
                for i, it in enumerate(items):
                    try:
                        it.click(timeout=2000)
                        page.wait_for_timeout(600)
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                    except Exception:
                        pass
                    if (i + 1) % 20 == 0:
                        print(f"      …{i + 1}/{len(items)} 글 열람")
                return
        except Exception:
            continue
    print("   (글 항목 자동감지 실패 — 목록 응답만 저장됨. 댓글은 재파싱 단계에서 확인)")


# ─────────────────────────────────────────────────────────── 정규화 파싱
def looks_like_post(d):
    """워크보드 게시글로 보이는 dict인가."""
    if not isinstance(d, dict):
        return False
    if "id" not in d:
        return False
    return ("children" in d) or ("content" in d and "attachments" in d)


def walk(obj, found):
    """캡처된 JSON을 재귀 순회하며 게시글 후보 수집."""
    if isinstance(obj, dict):
        if looks_like_post(obj):
            found.append(obj)
        for v in obj.values():
            walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, found)


def parse_to_posts():
    """raw_capture → workboard.db(posts) 정규화 + 첨부 manifest 생성."""
    raw = sqlite3.connect(RAW_DB)
    rows = raw.execute("SELECT board_type, body FROM raw_capture").fetchall()
    raw.close()

    # id별 최선(자식 많은) 버전 채택
    best = {}        # post_id -> (board_type, post_dict, score)
    for board_type, body in rows:
        try:
            data = json.loads(body)
        except Exception:
            continue
        found = []
        walk(data, found)
        for p in found:
            pid = p.get("id")
            if pid is None:
                continue
            score = len(p.get("children", []) or []) * 1000 + len(json.dumps(p, ensure_ascii=False))
            prev = best.get(pid)
            if prev is None or score > prev[2]:
                bt = board_type if board_type != "unknown" else (prev[0] if prev else "unknown")
                best[pid] = (bt, p, score)

    out = sqlite3.connect(OUT_DB)
    out.execute("DROP TABLE IF EXISTS posts")
    out.execute("""
        CREATE TABLE posts (
            id         INTEGER PRIMARY KEY,
            board_type TEXT,
            raw_json   TEXT
        )
    """)
    manifest = []
    n_children = 0
    for pid, (bt, p, _score) in best.items():
        out.execute(
            "INSERT OR REPLACE INTO posts(id, board_type, raw_json) VALUES (?,?,?)",
            (pid, bt, json.dumps(p, ensure_ascii=False)),
        )
        n_children += len(p.get("children", []) or [])
        # 본문/댓글 첨부 + 본문에 박힌 이미지(사진) 전부 수집
        for media in harvest_media(p):
            media["board_type"] = bt
            media["post_id"] = pid
            manifest.append(media)
    out.commit()
    out.close()

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = {}
    for _pid, (bt, _p, _s) in best.items():
        counts[bt] = counts.get(bt, 0) + 1
    n_img = sum(1 for m in manifest if m.get("is_image"))
    print("\n===== 정규화 결과 =====")
    print(f"게시글       : {len(best)}건  {counts}")
    print(f"댓글(추정)   : {n_children}건")
    print(f"첨부/사진    : {len(manifest)}건 (이미지 {n_img}건)")
    print(f"-> {OUT_DB}")
    print(f"-> {MANIFEST}")
    return manifest


# ─────────────────────────────────────────────────────────── 미디어(사진/첨부) URL 수집
_MEDIA_KEYS = ("url", "src", "image_url", "original_url", "download_url", "file_url", "thumb_url")
_IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif")


def harvest_media(post):
    """게시글 dict 전체에서 첨부+본문이미지 URL을 빠짐없이 수집 (url 기준 dedupe)."""
    seen = {}

    def add(url, name, att_id, is_image):
        if not url or not isinstance(url, str) or not url.startswith("http"):
            return
        if url in seen:
            return
        seen[url] = {"url": url, "file_name": name or "", "att_id": att_id, "is_image": is_image}

    # 1) 정식 attachments (본문 + 댓글)
    for scope in [post] + list(post.get("children", []) or []):
        for att in (scope.get("attachments", []) or []):
            ft = (att.get("file_type") or att.get("content_type") or "").lower()
            fn = att.get("file_name", "")
            is_img = "image" in ft or fn.lower().endswith(_IMG_EXT)
            add(att.get("url"), fn, att.get("id"), is_img)

    # 2) 본문/어디든 박혀있는 미디어 URL (ProseMirror 이미지 등) 재귀 수집
    def walk_media(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and k.lower() in _MEDIA_KEYS and v.startswith("http"):
                    low = v.split("?")[0].lower()
                    add(v, low.rsplit("/", 1)[-1], None, low.endswith(_IMG_EXT))
                else:
                    walk_media(v)
        elif isinstance(obj, list):
            for v in obj:
                walk_media(v)

    walk_media(post)
    return list(seen.values())


# ─────────────────────────────────────────────────────────── 게시판 자동 발견 + 순회
def collect_board_candidates(page):
    """사이드바(좌측 영역)에서 게시판으로 보이는 클릭요소의 텍스트 목록 수집."""
    # 사이드바가 지연로딩일 수 있어 좌측 패널을 한 번 스크롤
    try:
        page.evaluate("""
            () => document.querySelectorAll('nav,aside,[class*="side"],[class*="Side"]')
                    .forEach(el => { el.scrollTop = el.scrollHeight; })
        """)
        page.wait_for_timeout(800)
    except Exception:
        pass

    texts = page.evaluate("""
        () => {
            const out = [];
            const seen = new Set();
            const els = document.querySelectorAll("a, li, [role='button'], [role='tab'], [class*='menu'], [class*='Menu'], [class*='item'], [class*='Item']");
            for (const el of els) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                if (r.left > 420) continue;           // 좌측 사이드바만
                if (r.top < 40) continue;             // 상단 헤더 제외
                const t = (el.innerText || '').trim();
                if (!t || t.length > 30 || t.includes('\\n')) continue;
                if (seen.has(t)) continue;
                seen.add(t);
                out.push(t);
            }
            return out;
        }
    """)
    return texts or []


def scrape_all_boards_auto(page, counter):
    """사이드바 게시판을 자동으로 하나씩 눌러 전부 백업. 성공한 보드 수 반환."""
    candidates = collect_board_candidates(page)
    print(f"\n사이드바에서 게시판 후보 {len(candidates)}개 감지: {candidates}")
    done = 0
    for txt in candidates:
        before = counter[0]
        try:
            loc = page.get_by_text(txt, exact=True).first
            loc.click(timeout=4000)
            page.wait_for_timeout(1800)
        except Exception:
            continue
        if counter[0] == before:
            continue  # 클릭해도 새 데이터 안 옴 → 게시판 아님(메뉴/버튼)
        _current_board["type"] = (txt or f"board{done+1}")
        done += 1
        print(f"\n[{txt}] 게시판 진입 ✔  자동 스크롤…")
        auto_scroll(page)
        print(f"[{txt}] 글 열어 댓글 로드…")
        try_open_posts(page)
        auto_scroll(page, max_idle=3)
        print(f"[{txt}] 완료")
    return done


# ─────────────────────────────────────────────────────────── 사진/첨부 다운로드 (같은 세션)
import re as _re


def _safe(name):
    return _re.sub(r'[<>:"/\\|?*]', "_", name or "")[:180] or "file"


def download_session(page, manifest):
    """로그인된 그 창에서 사진/첨부를 즉시 전부 내려받는다 (URL 만료 방지)."""
    if not manifest:
        print("\n내려받을 사진/첨부가 없습니다.")
        return
    # 이어받기
    done = set()
    if DL_PROGRESS.exists():
        try:
            done = set(json.loads(DL_PROGRESS.read_text()))
        except Exception:
            done = set()

    total = len(manifest)
    ok = fail = 0
    print(f"\n사진/첨부 {total}건 다운로드 시작 (같은 로그인 세션)…")
    for i, m in enumerate(manifest):
        url = m["url"]
        key = str(m.get("att_id") or url)
        save_dir = STORAGE_DIR / str(m.get("board_type", "etc")) / str(m.get("post_id", "0"))
        save_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{m.get('att_id') or 'img'}_"
        save_path = save_dir / f"{prefix}{_safe(m.get('file_name') or url.split('?')[0].rsplit('/', 1)[-1])}"

        if key in done or (save_path.exists() and save_path.stat().st_size > 0):
            done.add(key)
            ok += 1
            continue

        got = False
        # 1) 세션 쿠키로 직접 GET (이미지/일반 파일 대부분 OK)
        try:
            resp = page.request.get(url, timeout=60000)
            if resp.ok:
                body = resp.body()
                ct = (resp.headers or {}).get("content-type", "")
                if body and "text/html" not in ct:
                    save_path.write_bytes(body)
                    got = True
        except Exception:
            pass
        # 2) 안 되면 브라우저 다운로드 방식 (다운로드 엔드포인트형 URL)
        if not got:
            try:
                with page.expect_download(timeout=60000) as dl:
                    try:
                        page.goto(url, timeout=20000)
                    except Exception:
                        pass
                dl.value.save_as(str(save_path))
                got = True
            except Exception:
                pass

        if got and save_path.exists() and save_path.stat().st_size > 0:
            ok += 1
            done.add(key)
        else:
            fail += 1

        if (i + 1) % 20 == 0:
            DL_PROGRESS.write_text(json.dumps(list(done)))
            print(f"  [{(i+1)/total*100:5.1f}%] {i+1}/{total}  성공 {ok} 실패 {fail}")
        page.wait_for_timeout(120)

    DL_PROGRESS.write_text(json.dumps(list(done)))
    print(f"\n다운로드 완료: 성공 {ok} / 실패 {fail} (총 {total})")
    print(f"-> {STORAGE_DIR}")
    if fail:
        print("  실패분은 스크립트를 한 번 더 실행하면 이어받습니다 (로그인 유지 시).")


# ─────────────────────────────────────────────────────────── API 엔드포인트 요약
def print_endpoints():
    """캡처된 API 주소를 패턴별로 묶어 출력 (자동화 버전 작성용)."""
    import re
    raw = sqlite3.connect(RAW_DB)
    rows = raw.execute("SELECT method, url FROM raw_capture").fetchall()
    raw.close()
    patterns = {}
    for method, url in rows:
        # 쿼리스트링 제거 + 숫자/UUID를 placeholder로
        path = url.split("?")[0]
        norm = re.sub(r"/\d+", "/{id}", path)
        norm = re.sub(r"/[0-9a-fA-F-]{16,}", "/{hash}", norm)
        key = f"{method} {norm}"
        patterns[key] = patterns.get(key, 0) + 1
    print("\n===== API 엔드포인트 요약 (이 부분을 복사해서 보내주세요) =====")
    for key in sorted(patterns, key=lambda k: -patterns[k]):
        print(f"  {patterns[key]:5d}회  {key}")
    print("=" * 60)


# ─────────────────────────────────────────────────────────── 메인
def main():
    conn = init_raw_db()
    counter = [0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.on("response", make_response_handler(conn, counter))

        page.goto(WORKBOARD_URL)
        print("\n" + "=" * 50)
        print(" 1) 카카오워크에 로그인하세요")
        print(" 2) 백업할 보드(예: 현장관리)를 화면에 여세요")
        print("=" * 50)
        input(" 준비되면 Enter ▶ ")

        # ── 게시판 전체 자동 순회 ──
        print("\n게시판을 자동으로 찾아 전부 백업합니다… (조작 불필요)")
        n = scrape_all_boards_auto(page, counter)

        if n == 0:
            # 자동 발견 실패 시에만 수동 폴백
            print("\n[자동 발견 실패] 게시판을 직접 열고 Enter (전부 끝이면 q)")
            i = 0
            while True:
                c = input("게시판 하나 연 뒤 Enter (끝이면 q): ").strip()
                if c.lower() == "q":
                    break
                i += 1
                try:
                    _current_board["type"] = page.url.rstrip("/").split("/")[-1] or f"board{i}"
                except Exception:
                    _current_board["type"] = f"board{i}"
                tag = _current_board["type"]
                auto_scroll(page)
                try_open_posts(page)
                auto_scroll(page, max_idle=3)
                print(f"[{tag}] 완료 ✔")
        else:
            print(f"\n게시판 {n}개 자동 백업 완료 ✔")

        # ── 글 정규화 → 같은 로그인 세션에서 사진/첨부까지 즉시 다운로드 ──
        print("\n원본 캡처 저장 완료. 정규화 진행…")
        manifest = parse_to_posts()
        download_session(page, manifest)   # 창 닫기 전에! (URL 만료 방지)

        browser.close()

    conn.close()
    print_endpoints()
    print("\n★ 백업 완료 (글 + 사진/첨부 전부).")
    print("  ▶ 위 'API 엔드포인트 요약'과 '정규화 결과'를 복사해 보내주세요.")
    print("    → 누락 점검 후 '로그인만 하면 전 게시판 자동' 버전으로 마무리합니다.")


if __name__ == "__main__":
    main()
