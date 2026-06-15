#!/usr/bin/env python3
"""
NAS 폴더 → ERP 현장 자동 동기화 (v3 - 올인원 Python)

기능:
1. 스캔 디렉토리의 폴더 + .lnk 바로가기 수집
2. .lnk → 원본 폴더 경로 파싱 (Windows 바로가기)
3. 각 폴더의 .plan.txt 읽기
4. ERP API로 전체 목록 전송 (생성/업데이트/rename 감지)
5. API 응답의 write_plans → .plan.txt 파일 자동 생성

설치:
  1. NAS에 복사: /volume1/scripts/nas_folder_sync.py
  2. 실행 권한: chmod +x /volume1/scripts/nas_folder_sync.py
  3. cron 등록: bash /volume1/scripts/nas_folder_sync.sh
     (래퍼 스크립트가 python3 호출)
  ※ /volume1/ 아래에 두어야 시놀로지 재부팅 시 삭제되지 않음
"""

import datetime
import json
import os
import re
import struct
import sys
import urllib.request
import urllib.error

# ── 설정 ──
ERP_URL = "https://work.mgnt.kr/api/sync_nas_folders"
API_KEY = "mgnt-nas-sync-2026-secure-key"

BASE_DIR = "/volume1/현장관리/000. 현장관리"
YEAR = str(datetime.date.today().year)
SCAN_DIR = os.path.join(BASE_DIR, YEAR)
LOG_FILE = "/volume1/scripts/nas_sync.log"

FOLDER_PATTERN = re.compile(r'^\d{4}\.\d{2}\.\d{2}_.+')


# ── 로깅 ──
def log(msg):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


# ── .lnk 파싱 ──
def parse_lnk_target(lnk_path):
    """Windows .lnk 바로가기에서 대상 경로 추출 (LocalBasePath 또는 RELATIVE_PATH)"""
    try:
        with open(lnk_path, 'rb') as f:
            data = f.read()

        if data[:4] != b'\x4c\x00\x00\x00':
            return None

        flags = struct.unpack_from('<I', data, 0x14)[0]
        offset = 0x4C

        # Shell Item ID List 건너뛰기
        if flags & 0x01:
            id_list_size = struct.unpack_from('<H', data, offset)[0]
            offset += 2 + id_list_size

        # LinkInfo
        if flags & 0x02:
            link_info_start = offset
            link_info_size = struct.unpack_from('<I', data, link_info_start)[0]
            local_offset = struct.unpack_from('<I', data, link_info_start + 0x10)[0]
            if local_offset > 0:
                path_start = link_info_start + local_offset
                path_end = data.index(b'\x00', path_start)
                path = data[path_start:path_end].decode('cp949', errors='replace')
                if path:
                    return path
            offset = link_info_start + link_info_size

        # StringData — NAME(0x04), RELATIVE_PATH(0x08), WORKING_DIR(0x10), ...
        for field_flag in [0x04, 0x08, 0x10, 0x20, 0x40]:
            if flags & field_flag:
                if offset + 2 > len(data):
                    break
                count = struct.unpack_from('<H', data, offset)[0]
                offset += 2
                s = data[offset:offset + count * 2].decode('utf-16-le', errors='replace')
                offset += count * 2
                if field_flag == 0x08:  # RELATIVE_PATH
                    return s

        return None
    except Exception:
        return None


def resolve_lnk_to_nas_path(lnk_path):
    """Windows .lnk 대상 → NAS 로컬 경로 변환"""
    target = parse_lnk_target(lnk_path)
    if not target:
        return None

    # 상대경로: .\2024.09.12_현장명 → 폴더명 앞 4자리(YYYY)로 연도 디렉토리 결정
    if target.startswith('.\\') or target.startswith('./'):
        folder_name = target[2:].replace('\\', '/')
        folder_year = folder_name[:4] if len(folder_name) >= 4 else YEAR
        resolved = os.path.join(BASE_DIR, folder_year, folder_name)
        return resolved

    # UNC: \\Magnatech\현장관리\... → /volume1/현장관리/...
    if target.startswith('\\\\'):
        parts = target.replace('\\', '/').lstrip('/').split('/', 2)
        if len(parts) >= 3:
            return '/volume1/' + parts[2]

    # 드라이브: Z:\현장관리\... → /volume1/현장관리/...
    if len(target) >= 3 and target[1] == ':':
        rest = target[2:].replace('\\', '/')
        if '현장관리' in rest:
            idx = rest.index('현장관리')
            return '/volume1/' + rest[idx:]

    return None


# ── 폴더 스캔 ──
def scan_folders():
    """스캔 디렉토리의 폴더 + .lnk 수집, .plan.txt 읽기"""
    if not os.path.isdir(SCAN_DIR):
        log(f"ERROR: 스캔 디렉토리 없음: {SCAN_DIR}")
        sys.exit(1)

    results = []  # [{ name, plan?, _plan_dir? }]

    for entry in sorted(os.listdir(SCAN_DIR)):
        full_path = os.path.join(SCAN_DIR, entry)
        folder_name = None
        plan_dir = None

        if os.path.isdir(full_path):
            if FOLDER_PATTERN.match(entry):
                folder_name = entry
                plan_dir = full_path

        elif entry.endswith('.lnk') and os.path.isfile(full_path):
            name = entry
            for suffix in [' - 바로 가기.lnk', '.lnk']:
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            if FOLDER_PATTERN.match(name):
                folder_name = name
                resolved = resolve_lnk_to_nas_path(full_path)
                if resolved and os.path.isdir(resolved):
                    plan_dir = resolved

        if not folder_name:
            continue

        item = {'name': folder_name, '_plan_dir': plan_dir}

        # .plan.txt 읽기
        if plan_dir:
            plan_path = os.path.join(plan_dir, '.plan.txt')
            if os.path.isfile(plan_path):
                try:
                    with open(plan_path, 'r', encoding='utf-8') as f:
                        item['plan'] = f.read()
                except Exception:
                    pass

        results.append(item)

    return results


# ── API 호출 ──
def call_api(folders_data):
    """ERP API 호출, 응답 반환"""
    # API용 payload (내부 필드 제거)
    api_folders = []
    for item in folders_data:
        entry = {'name': item['name']}
        if 'plan' in item:
            entry['plan'] = item['plan']
        api_folders.append(entry)

    payload = json.dumps({'folders': api_folders}, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        ERP_URL,
        data=payload,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-API-Key': API_KEY,
            'User-Agent': 'MagnatechNAS/1.0 (NAS Folder Sync)',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8')
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return e.code, {'error': body}
    except Exception as e:
        return 0, {'error': str(e)}


# ── .plan.txt 파일 생성 ──
def write_plan_files(folders_data, api_response):
    """API 응답의 write_plans → .plan.txt 파일 생성"""
    write_plans = api_response.get('write_plans', [])
    if not write_plans:
        return

    # 폴더명 → plan_dir 매핑
    dir_map = {item['name']: item.get('_plan_dir') for item in folders_data}

    for wp in write_plans:
        folder = wp.get('folder', '')
        content = wp.get('content', '')
        if not folder or not content:
            continue

        plan_dir = dir_map.get(folder)
        if not plan_dir:
            plan_dir = os.path.join(SCAN_DIR, folder)

        if not os.path.isdir(plan_dir):
            log(f".plan.txt 생성 스킵 (폴더없음): {folder}")
            continue

        plan_path = os.path.join(plan_dir, '.plan.txt')
        try:
            with open(plan_path, 'w', encoding='utf-8') as f:
                f.write(content)
            log(f".plan.txt 생성: {plan_path}")
        except Exception as e:
            log(f".plan.txt 생성 실패: {plan_path} ({e})")


# ── 메인 ──
def main():
    # 1. 폴더 스캔
    folders_data = scan_folders()
    if not folders_data:
        sys.exit(0)

    # 2. API 호출
    status, response = call_api(folders_data)

    if status != 200:
        log(f"동기화 실패 (HTTP {status}): {response}")
        sys.exit(1)

    # 3. .plan.txt 파일 생성
    write_plan_files(folders_data, response)

    # 4. 결과 로깅 (변경사항 있을 때만)
    summary = response.get('summary', '')
    created = response.get('created', [])
    updated = response.get('updated', [])
    if created or updated:
        log(f"동기화 완료 ({len(folders_data)}건 전송): {summary}")


if __name__ == '__main__':
    main()
