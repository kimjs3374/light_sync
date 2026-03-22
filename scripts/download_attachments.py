"""카카오워크 워크보드 첨부파일 일괄 다운로드.

사용법:
  py scripts/download_attachments.py

1. Chromium 브라우저가 열리면 카카오워크 로그인
2. 워크보드 현장관리 화면이 보일 때까지 기다림
3. 콘솔에서 Enter
4. 자동으로 2,405개 파일 다운로드 시작
"""
import json
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

MANIFEST = 'scripts/attachments_manifest.json'
STORAGE_DIR = 'storage/archive'
PROGRESS_FILE = 'scripts/download_progress.json'


def sanitize_filename(name):
    """파일명에서 위험한 문자 제거."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name[:200]


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return set(json.load(f))
    return set()


def save_progress(done_ids):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(list(done_ids), f)


def main():
    with open(MANIFEST, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    done_ids = load_progress()
    remaining = [a for a in manifest if str(a['att_id']) not in done_ids]
    print(f'총 {len(manifest)}개 중 {len(done_ids)}개 완료, {len(remaining)}개 남음')

    if not remaining:
        print('모든 파일 다운로드 완료!')
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # 로그인 페이지로 이동
        page.goto('https://workboard.kakaowork.com')
        print('\n=== 카카오워크 로그인하세요 ===')
        print('=== 워크보드 현장관리 화면이 보이면 Enter를 눌러주세요 ===')
        input()

        print('다운로드 시작...\n')

        success = 0
        fail = 0
        consecutive_fails = 0

        for i, att in enumerate(remaining):
            board = att['board_type']
            post_id = att['post_id']
            att_id = att['att_id']
            fname = sanitize_filename(att['file_name'])

            # 저장 디렉토리
            save_dir = Path(STORAGE_DIR) / board / str(post_id)
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / f'{att_id}_{fname}'

            if save_path.exists() and save_path.stat().st_size > 0:
                done_ids.add(str(att_id))
                success += 1
                continue

            try:
                # expect_download을 먼저 설정하고 navigate
                with page.expect_download(timeout=120000) as dl_info:
                    # wait_until 없이 — 다운로드 시작되면 바로 반환됨
                    try:
                        page.goto(att['url'], timeout=30000)
                    except Exception:
                        pass  # "Download is starting" 에러는 정상

                download = dl_info.value
                download.save_as(str(save_path))

                done_ids.add(str(att_id))
                success += 1
                consecutive_fails = 0

                if success % 20 == 0:
                    save_progress(done_ids)

                size_kb = save_path.stat().st_size / 1024
                total_done = len(done_ids)
                pct = total_done / len(manifest) * 100
                print(f'[{pct:5.1f}%] {total_done}/{len(manifest)} | {fname} ({size_kb:.0f}KB)')

            except Exception as e:
                fail += 1
                consecutive_fails += 1
                err_msg = str(e)[:80]
                print(f'[FAIL] {att_id} {fname}: {err_msg}')

                # 연속 10번 실패하면 세션 만료로 판단
                if consecutive_fails >= 10:
                    print('\n연속 10회 실패. 세션 만료로 판단합니다.')
                    print('진행 상태를 저장하고 종료합니다. 다시 실행하세요.')
                    save_progress(done_ids)
                    browser.close()
                    return

            # 서버 부하 방지
            time.sleep(0.2)

        save_progress(done_ids)
        browser.close()

    print(f'\n완료! 성공: {success}, 실패: {fail}')
    print(f'총 진행: {len(done_ids)}/{len(manifest)}')


if __name__ == '__main__':
    main()
