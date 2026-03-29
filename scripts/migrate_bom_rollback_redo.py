"""
BOM 통합 롤백 + 재실행 (렌즈만 통합, 색온도 별도 BOM 유지)

이전 마이그레이션의 문제:
1. 5700K + 3K를 하나의 BOM에 합침 → 3K PCB가 렌즈별 3중 복제
2. 색온도를 option_filter로 넣으면 기본(5700K)일 때 3K도 나옴

수정: 렌즈 변형만 통합. ARENA-400(5700K)과 ARENA-400-3K는 별도 BOM.

실행: cd D:/light_sync && ./venv/Scripts/python.exe scripts/migrate_bom_rollback_redo.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import app
from modules.db_context import get_db
from modules.models import (
    BomHeader, BomItem, BomModelAlias,
    StockConsumption, ContractItem,
)
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import distinct


# ===================================================================
# STEP 1: 롤백
# ===================================================================

def rollback(db):
    """이전 마이그레이션 완전 롤백."""
    print('=' * 60)
    print('STEP 1: ROLLBACK')
    print('=' * 60)

    # 1-1. 모든 별칭 삭제
    alias_count = db.query(BomModelAlias).delete()
    print(f'  Deleted {alias_count} aliases')

    # 1-2. 마이그레이션이 추가한 option_filter 아이템 삭제
    # ARENA/BATOO/MT-FL 계열 BOM의 option_filter 아이템만 삭제
    # (STA-400 등 기존 슈퍼BOM의 아이템은 보존)
    target_prefixes = ['ARENA-', 'BATOO-', 'MT-FL-']
    target_bom_ids = []
    for bom in db.query(BomHeader).all():
        if any(bom.product_code.startswith(p) or (bom.note and '통합' in (bom.note or '')) for p in target_prefixes):
            target_bom_ids.append(bom.id)

    deleted_items = 0
    for bom_id in target_bom_ids:
        cnt = db.query(BomItem).filter(
            BomItem.bom_id == bom_id,
            BomItem.option_filter.isnot(None),
        ).delete()
        deleted_items += cnt
    print(f'  Deleted {deleted_items} option-filtered BomItems')

    # 1-3. 비활성화된 BOM 복원
    restored = 0
    for bom in db.query(BomHeader).filter(BomHeader.is_active == False).all():
        if bom.note and '통합' in bom.note:
            bom.is_active = True
            bom.note = None
            restored += 1
    print(f'  Restored {restored} deactivated BOMs')

    # 1-4. 이름이 바뀐 대표 BOM 복원
    rename_map = {
        # ARENA: 대표 BOM의 product_code를 원래대로 복원
        'ARENA-200S': 'ARENA-200S-광각',
        'ARENA-300S': 'ARENA-300S-광각',
        'ARENA-400': 'ARENA-400-광각',
        'ARENA-400S': 'ARENA-400S-광각',
        'ARENA-500': 'ARENA-500-광각',
        'ARENA-600': 'ARENA-600-광각',
        'ARENA-800': 'ARENA-800-광각',
        # BATOO
        'BATOO-200': 'BATOO-200-020',
        'BATOO-300': 'BATOO-300-020',
        'BATOO-400': 'BATOO-400-020',
        'BATOO-600': 'BATOO-600-020',
        'BATOO-800': 'BATOO-800-020',
        'BATOO-1000': 'BATOO-1000-020',
        'BATOO-1200': 'BATOO-1200-020',
        'BATOO-X400': 'BATOO-X400-020',
        # MT-FL
        'MT-FL-300A': 'MT-FL-300A-020',
        'MT-FL-400S': 'MT-FL-400S-020',
        'MT-FL-600A': 'MT-FL-600A-020',
        'MT-FL-800A': 'MT-FL-800A-020',
        'MT-FL-1000A': 'MT-FL-1000A-020',
        'MT-FL-1200A': 'MT-FL-1200A-020',
    }
    renamed = 0
    for new_code, orig_code in rename_map.items():
        bom = db.query(BomHeader).filter(BomHeader.product_code == new_code).first()
        if bom:
            bom.product_code = orig_code
            bom.product_name = orig_code
            bom.option_schema = None
            renamed += 1
    print(f'  Restored {renamed} product_codes')

    # 1-5. 증각 오타 BOM도 복원 (나중에 다시 폐기)
    for code in ['ARENA-400-증각', 'ARENA-400-증각(3K)']:
        bom = db.query(BomHeader).filter(BomHeader.product_code == code).first()
        if bom and not bom.is_active:
            bom.is_active = True
            bom.note = None

    db.flush()
    active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
    print(f'  Active BOMs after rollback: {active}')
    print()


# ===================================================================
# STEP 2: 재실행 (렌즈만 통합, 색온도 별도)
# ===================================================================

def merge_lens_group(db, target_code, sources_with_lens):
    """렌즈 변형만 하나의 BOM으로 통합.

    Args:
        target_code: 통합 후 product_code
        sources_with_lens: [(product_code, lens_value), ...]
            첫번째가 대표 BOM
    """
    if not sources_with_lens:
        return None

    first_code, first_lens = sources_with_lens[0]
    target_bom = db.query(BomHeader).filter(
        BomHeader.product_code == first_code,
        BomHeader.is_active == True,
    ).first()

    if not target_bom:
        print(f'  SKIP: {target_code} - {first_code} not found')
        return None

    # 대표 BOM의 공통 item_code 수집
    target_item_codes = {bi.item_code for bi in target_bom.bom_items}

    print(f'  TARGET: {first_code} (id:{target_bom.id}) -> {target_code}')

    added = 0
    for src_code, lens_val in sources_with_lens[1:]:
        src_bom = db.query(BomHeader).filter(
            BomHeader.product_code == src_code,
            BomHeader.is_active == True,
        ).first()
        if not src_bom:
            continue

        for bi in src_bom.bom_items:
            if bi.item_code in target_item_codes:
                continue  # 공통부품 스킵

            # 이미 같은 item_code+lens 조합이 추가됐으면 스킵
            existing = db.query(BomItem).filter(
                BomItem.bom_id == target_bom.id,
                BomItem.item_code == bi.item_code,
            ).first()
            if existing:
                continue

            db.add(BomItem(
                bom_id=target_bom.id,
                item_code=bi.item_code,
                item_id=bi.item_id,
                item_name=bi.item_name,
                item_spec=bi.item_spec,
                quantity=bi.quantity,
                unit_price=bi.unit_price,
                prev_unit_price=bi.prev_unit_price,
                amount=bi.amount,
                supplier=bi.supplier,
                unit=bi.unit,
                option_filter=json.dumps({'렌즈': lens_val}, ensure_ascii=False),
                note=bi.note,
            ))
            added += 1

        # 소진기록 이관
        db.query(StockConsumption).filter(
            StockConsumption.bom_id == src_bom.id
        ).update({'bom_id': target_bom.id})

        # source 비활성화
        src_bom.is_active = False
        src_bom.note = f'-> {target_code} 렌즈 통합 (2026-03-28)'

        print(f'    MERGE: {src_code} (id:{src_bom.id})')

    # 대표 BOM 이름 변경
    target_bom.product_code = target_code
    target_bom.product_name = target_code

    # option_schema 재생성
    schema_json = rebuild_option_schema(db, target_bom.id)
    target_bom.option_schema = schema_json

    print(f'    +{added} option items, schema={schema_json}')
    return target_bom


def redo_migration(db):
    """렌즈만 통합하는 올바른 마이그레이션."""

    # -------------------------------------------------------
    # ARENA: 5700K와 3K 각각 렌즈 통합
    # -------------------------------------------------------
    print('=' * 60)
    print('STEP 2: ARENA 렌즈 통합 (색온도 별도)')
    print('=' * 60)

    arena_models = ['ARENA-200S', 'ARENA-300S', 'ARENA-400', 'ARENA-400S',
                    'ARENA-500', 'ARENA-600', 'ARENA-800']
    lenses = [('광각', '광각'), ('중각', '중각'), ('협각', '협각')]

    for base in arena_models:
        # 5700K 통합
        sources_5700 = [(f'{base}-{l}', lens_val) for l, lens_val in lenses]
        merge_lens_group(db, base, sources_5700)

        # 3K 통합 (존재하면)
        sources_3k = [(f'{base}-{l}(3K)', lens_val) for l, lens_val in lenses]
        first_3k = db.query(BomHeader).filter(
            BomHeader.product_code == sources_3k[0][0],
            BomHeader.is_active == True,
        ).first()
        if first_3k:
            merge_lens_group(db, f'{base}-3K', sources_3k)

        print()

    # 증각 폐기
    for code in ['ARENA-400-증각', 'ARENA-400-증각(3K)']:
        bom = db.query(BomHeader).filter(BomHeader.product_code == code, BomHeader.is_active == True).first()
        if bom:
            bom.is_active = False
            bom.note = '오타/폐기 (2026-03-28)'
            print(f'  DISCARD: {code}')
    print()

    # -------------------------------------------------------
    # BATOO: 렌즈 통합
    # -------------------------------------------------------
    print('=' * 60)
    print('STEP 3: BATOO 렌즈 통합')
    print('=' * 60)

    batoo_bases = ['BATOO-200', 'BATOO-300', 'BATOO-400', 'BATOO-600',
                   'BATOO-800', 'BATOO-1000', 'BATOO-1200', 'BATOO-X400']
    batoo_lenses = [('020', '020'), ('030', '030'), ('045', '045'), ('060', '060'), ('120', '120')]

    for base in batoo_bases:
        sources = [(f'{base}-{l}', lens_val) for l, lens_val in batoo_lenses]
        merge_lens_group(db, base, sources)
        print()

    # -------------------------------------------------------
    # MT-FL: 렌즈 통합
    # -------------------------------------------------------
    print('=' * 60)
    print('STEP 4: MT-FL 렌즈 통합')
    print('=' * 60)

    mtfl_bases = ['MT-FL-300A', 'MT-FL-400S', 'MT-FL-600A',
                  'MT-FL-800A', 'MT-FL-1000A', 'MT-FL-1200A']

    for base in mtfl_bases:
        sources = [(f'{base}-{l}', lens_val) for l, lens_val in batoo_lenses]
        merge_lens_group(db, base, sources)
        print()

    # -------------------------------------------------------
    # 별칭 등록
    # -------------------------------------------------------
    print('=' * 60)
    print('STEP 5: 별칭 등록')
    print('=' * 60)

    def reg(alias_name, target_code, atype='option', note=None):
        bom = db.query(BomHeader).filter(
            BomHeader.product_code == target_code,
            BomHeader.is_active == True,
        ).first()
        if not bom:
            return
        existing = db.query(BomModelAlias).filter(BomModelAlias.alias_name == alias_name).first()
        if existing:
            return
        db.add(BomModelAlias(
            bom_id=bom.id, alias_name=alias_name,
            alias_type=atype, note=note, created_by='system',
        ))
        print(f'  {alias_name} -> {target_code}')

    # BATOO = MT-FL 크로스 (400 제외)
    for batoo, mtfl in [('BATOO-300', 'MT-FL-300A'), ('BATOO-600', 'MT-FL-600A'),
                         ('BATOO-800', 'MT-FL-800A'), ('BATOO-1000', 'MT-FL-1000A'),
                         ('BATOO-1200', 'MT-FL-1200A')]:
        reg(mtfl, batoo, 'option', 'BATOO=MT-FL')

    # 접미어 별칭
    import re
    model_names = [r[0] for r in db.query(distinct(ContractItem.model_name)).filter(
        ContractItem.model_name.isnot(None), ContractItem.model_name != '').all()]
    bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(BomHeader.is_active == True).all()}

    suffix_patterns = [
        (r'\(M\)', ''), (r'\(D\)', ''), (r'\(X\)', ''),
        (r'-35$', ''), (r'-45$', ''),
        (r'B$', ''), (r'A$', ''),
        (r'\(3000K\)$', '-3K'),  # ARENA-500(3000K) → ARENA-500-3K
    ]

    for model in model_names:
        if model in bom_codes:
            continue
        for pattern, repl in suffix_patterns:
            stripped = re.sub(pattern, repl, model)
            if stripped != model and stripped in bom_codes:
                reg(model, stripped, 'option', 'suffix auto')
                break

    # exact 별칭 (자기 자신 product_code)
    for bom_code, bom_id in bom_codes.items():
        ci_exists = db.query(ContractItem).filter(ContractItem.model_name == bom_code).first()
        if ci_exists:
            existing = db.query(BomModelAlias).filter(BomModelAlias.alias_name == bom_code).first()
            if not existing:
                db.add(BomModelAlias(
                    bom_id=bom_id, alias_name=bom_code,
                    alias_type='exact', created_by='system',
                ))

    print()


def main():
    dry_run = '--dry-run' in sys.argv
    with app.app_context():
        with get_db() as db:
            if dry_run:
                print('=== DRY RUN ===\n')

            rollback(db)
            redo_migration(db)

            # 결과
            print('=' * 60)
            print('SUMMARY')
            print('=' * 60)
            active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
            inactive = db.query(BomHeader).filter(BomHeader.is_active == False).count()
            aliases = db.query(BomModelAlias).count()
            print(f'  Active BOM: {active}')
            print(f'  Inactive BOM: {inactive}')
            print(f'  Aliases: {aliases}')

            if dry_run:
                print('\n=== DRY RUN - no changes ===')
                db.rollback()
            else:
                db.commit()
                print('\n=== DONE ===')


if __name__ == '__main__':
    main()
