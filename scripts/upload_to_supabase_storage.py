"""워크보드 아카이브 첨부파일 → Supabase Storage 병렬 업로드.

사용법:
  py scripts/upload_to_supabase_storage.py
"""
import json
import os
import sys
import mimetypes
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.models.helpers import _read_env_value

SUPABASE_URL = _read_env_value('SUPABASE_URL')
SUPABASE_KEY = _read_env_value('SUPABASE_SERVICE_ROLE_KEY')
BUCKET = 'company-files'
STORAGE_DIR = 'storage/archive'
PROGRESS_FILE = 'scripts/upload_progress.json'
WORKERS = 10  # 동시 업로드 수

lock = threading.Lock()


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return set(json.load(f))
    return set()


def save_progress(done):
    with lock:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(list(done), f)


def upload_file(storage_path, local_path, content_type):
    """Supabase Storage에 파일 업로드."""
    encoded_path = urllib.parse.quote(storage_path)
    url = f'{SUPABASE_URL}/storage/v1/object/{BUCKET}/{encoded_path}'

    with open(local_path, 'rb') as f:
        data = f.read()

    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'apikey': SUPABASE_KEY,
        'Content-Type': content_type,
        'x-upsert': 'true',
    })

    try:
        resp = urllib.request.urlopen(req, timeout=120)
        return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 400:
            req2 = urllib.request.Request(url, data=data, method='PUT', headers={
                'Authorization': f'Bearer {SUPABASE_KEY}',
                'apikey': SUPABASE_KEY,
                'Content-Type': content_type,
            })
            try:
                resp2 = urllib.request.urlopen(req2, timeout=120)
                return resp2.status == 200
            except Exception:
                return False
        return False
    except Exception:
        return False


def upload_one(args):
    """단일 파일 업로드 (스레드용)."""
    storage_path, local_path = args
    content_type = mimetypes.guess_type(local_path)[0] or 'application/octet-stream'
    file_size = os.path.getsize(local_path)
    ok = upload_file(storage_path, local_path, content_type)
    return storage_path, local_path, file_size, ok


def main():
    files = []
    for board_type in ['site', 'as']:
        board_dir = os.path.join(STORAGE_DIR, board_type)
        if not os.path.isdir(board_dir):
            continue
        for post_dir in os.listdir(board_dir):
            post_path = os.path.join(board_dir, post_dir)
            if not os.path.isdir(post_path):
                continue
            for fname in os.listdir(post_path):
                fpath = os.path.join(post_path, fname)
                if os.path.isfile(fpath):
                    storage_path = f'archive/{board_type}/{post_dir}/{fname}'
                    files.append((storage_path, fpath))

    done = load_progress()
    remaining = [(sp, lp) for sp, lp in files if sp not in done]

    print(f'총 {len(files)}개 중 {len(done)}개 완료, {len(remaining)}개 남음')
    if not remaining:
        print('모든 파일 업로드 완료!')
        return

    total_size = sum(os.path.getsize(lp) for _, lp in remaining)
    print(f'업로드 용량: {total_size/1024/1024/1024:.2f}GB')
    print(f'병렬 {WORKERS}개 스레드로 업로드 시작...\n')

    success = 0
    fail = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(upload_one, item): item for item in remaining}

        for future in as_completed(futures):
            storage_path, local_path, file_size, ok = future.result()
            fname = os.path.basename(local_path)

            if ok:
                with lock:
                    done.add(storage_path)
                success += 1

                if success % 50 == 0:
                    save_progress(done)

                pct = len(done) / len(files) * 100
                print(f'[{pct:5.1f}%] {len(done)}/{len(files)} | {fname} ({file_size/1024:.0f}KB)')
            else:
                fail += 1
                print(f'[FAIL] {fname}')

    save_progress(done)
    print(f'\n완료! 성공: {success}, 실패: {fail}')
    print(f'총 진행: {len(done)}/{len(files)}')


if __name__ == '__main__':
    main()
