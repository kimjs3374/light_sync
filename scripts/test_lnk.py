#!/usr/bin/env python3
"""lnk resolve 테스트"""
import os
import glob
import struct

BASE_DIR = '/volume1/현장관리/000. 현장관리'
YEAR = '2026'


def parse_lnk_target(lnk_path):
    try:
        with open(lnk_path, 'rb') as f:
            data = f.read()
        if data[:4] != b'\x4c\x00\x00\x00':
            return None
        flags = struct.unpack_from('<I', data, 0x14)[0]
        offset = 0x4C
        if flags & 0x01:
            offset += 2 + struct.unpack_from('<H', data, offset)[0]
        if flags & 0x02:
            li_start = offset
            li_size = struct.unpack_from('<I', data, li_start)[0]
            local_offset = struct.unpack_from('<I', data, li_start + 0x10)[0]
            if local_offset > 0:
                ps = li_start + local_offset
                pe = data.index(b'\x00', ps)
                path = data[ps:pe].decode('cp949', errors='replace')
                if path:
                    return path
            offset = li_start + li_size
        for ff in [0x04, 0x08, 0x10, 0x20, 0x40]:
            if flags & ff:
                if offset + 2 > len(data):
                    break
                count = struct.unpack_from('<H', data, offset)[0]
                offset += 2
                s = data[offset:offset + count * 2].decode('utf-16-le', errors='replace')
                offset += count * 2
                if ff == 0x08:
                    return s
        return None
    except Exception:
        return None


def resolve_lnk_to_nas_path(lnk_path):
    target = parse_lnk_target(lnk_path)
    if not target:
        return None
    if target.startswith('.\\') or target.startswith('./'):
        folder_name = target[2:].replace('\\', '/')
        folder_year = folder_name[:4] if len(folder_name) >= 4 else YEAR
        return os.path.join(BASE_DIR, folder_year, folder_name)
    if target.startswith('\\\\'):
        parts = target.replace('\\', '/').lstrip('/').split('/', 2)
        if len(parts) >= 3:
            return '/volume1/' + parts[2]
    if len(target) >= 3 and target[1] == ':':
        rest = target[2:].replace('\\', '/')
        if '현장관리' in rest:
            return '/volume1/' + rest[rest.index('현장관리'):]
    return None


scan_dir = os.path.join(BASE_DIR, YEAR)
for lnk in sorted(glob.glob(os.path.join(scan_dir, '*.lnk'))):
    name = os.path.basename(lnk)
    target = resolve_lnk_to_nas_path(lnk)
    exists = os.path.isdir(target) if target else False
    print(f'{name}')
    print(f'  target: {target}')
    print(f'  exists: {exists}')
    if target and exists:
        plan = os.path.join(target, '.plan.txt')
        print(f'  .plan.txt: {"있음" if os.path.isfile(plan) else "없음"}')
    print()
