#!/usr/bin/env python3
"""VCF 파일 → ERP 공유 주소록 1회성 가져오기.

사용법:
  # 미리보기
  python3 scripts/import_synology_contacts.py contacts.vcf --dry-run

  # 실제 저장
  python3 scripts/import_synology_contacts.py contacts.vcf
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.models.mail_entities import MailContact
from modules.models import SessionLocal


def parse_vcf_file(filepath):
    """VCF 파일에서 연락처 목록 파싱. 여러 vCard가 하나의 파일에 연속으로 들어있는 형식 지원."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read()

    contacts = []
    current = None

    for line in raw.splitlines():
        line = line.strip()

        if line.upper() == 'BEGIN:VCARD':
            current = {'name': '', 'emails': [], 'company': '', 'tels': []}
            continue

        if line.upper() == 'END:VCARD':
            if current:
                contacts.append(current)
            current = None
            continue

        if current is None:
            continue

        upper = line.upper()

        # FN (Full Name) — 우선
        if upper.startswith('FN:') or upper.startswith('FN;'):
            val = line.split(':', 1)[-1].strip()
            if val:
                current['name'] = val

        # N (구조화된 이름) — FN이 없을 때 fallback
        elif upper.startswith('N:') or upper.startswith('N;'):
            if not current['name']:
                parts = line.split(':', 1)[-1].split(';')
                # N: 성;이름;...
                name = ' '.join(p.strip() for p in reversed(parts[:2]) if p.strip())
                if name:
                    current['name'] = name

        # EMAIL (여러 개 가능)
        elif upper.startswith('EMAIL'):
            val = line.split(':', 1)[-1].strip()
            if val and val not in current['emails']:
                current['emails'].append(val)

        # ORG
        elif upper.startswith('ORG'):
            val = line.split(':', 1)[-1].strip().rstrip(';')
            if val:
                current['company'] = val

        # TEL
        elif upper.startswith('TEL'):
            val = line.split(':', 1)[-1].strip()
            if val and val not in current['tels']:
                current['tels'].append(val)

    return contacts


def main():
    parser = argparse.ArgumentParser(description='VCF → ERP 공유 주소록 가져오기')
    parser.add_argument('vcf_file', help='VCF 파일 경로')
    parser.add_argument('--dry-run', action='store_true', help='DB 저장 없이 목록만 출력')
    args = parser.parse_args()

    if not os.path.isfile(args.vcf_file):
        print(f'❌ 파일을 찾을 수 없습니다: {args.vcf_file}')
        sys.exit(1)

    print(f'[1/3] VCF 파일 읽는 중: {args.vcf_file}')
    raw_contacts = parse_vcf_file(args.vcf_file)
    print(f'  vCard {len(raw_contacts)}개 발견')

    # 이메일 있는 것만 필터 + 이메일별로 1건씩 분리
    contacts = []
    for c in raw_contacts:
        if not c['emails']:
            if c['name']:
                print(f'  ⚠ 이메일 없음 (건너뜀): {c["name"]}')
            continue
        tel_str = ', '.join(c['tels']) if c['tels'] else ''
        for email in c['emails']:
            contacts.append({
                'name': c['name'] or email.split('@')[0],
                'email': email,
                'company': c['company'],
                'tel': tel_str,
            })

    print(f'  유효한 연락처: {len(contacts)}건')

    if not contacts:
        print('가져올 연락처가 없습니다.')
        sys.exit(0)

    # 미리보기
    print(f'\n{"이름":<20} {"이메일":<35} {"회사":<20} {"전화번호"}')
    print('-' * 95)
    for c in contacts:
        print(f'{c["name"]:<20} {c["email"]:<35} {c["company"]:<20} {c["tel"]}')

    if args.dry_run:
        print(f'\n[dry-run] DB 저장 건너뜀. 총 {len(contacts)}건.')
        return

    print(f'\n[2/3] DB 저장 중...')
    db = SessionLocal()
    try:
        existing = {c.email.lower() for c in
                    db.query(MailContact.email).filter_by(is_shared=True).all()}

        added, skipped = 0, 0
        for c in contacts:
            if c['email'].lower() in existing:
                skipped += 1
                continue

            db.add(MailContact(
                user_id=None,
                name=c['name'],
                email=c['email'],
                company=c['company'],
                memo=c['tel'],
                is_shared=True,
            ))
            existing.add(c['email'].lower())
            added += 1

        db.commit()
        print(f'  ✅ 추가: {added}건, 중복 건너뜀: {skipped}건')
    finally:
        db.close()

    print('\n[3/3] 완료!')


if __name__ == '__main__':
    main()
