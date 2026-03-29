"""
BOM 통합 마이그레이션 스크립트 (일회성 실행)

ARENA 렌즈별 BOM → 대표 BOM 1개 + option_filter 태깅
BATOO 렌즈별 BOM → 대표 BOM 1개 + option_filter 태깅
MT-FL 렌즈별 BOM → 대표 BOM 1개 + option_filter 태깅
+ BATOO↔MT-FL 크로스 별칭 등록
+ 옵션 접미어((M),(D),(X) 등) 별칭 등록

실행: cd D:/light_sync && ./venv/Scripts/python.exe scripts/migrate_bom_merge.py
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
# 1. ARENA 통합 계획 (44개 → 7개)
# ===================================================================
# 각 그룹: (대표 product_code, [source product_code들], option_key, option_map)
# option_map: {source_product_code: {option_key: value, ...}}

def make_arena_group(base, has_증각=False):
    """ARENA 그룹 생성 헬퍼. 렌즈 3종 × 색온도 2종."""
    lenses = ['광각', '중각', '협각']
    sources_5700 = [f'{base}-{l}' for l in lenses]
    sources_3k = [f'{base}-{l}(3K)' for l in lenses]

    if has_증각:
        # 증각은 오타 → 폐기 대상
        pass

    option_map = {}
    for l in lenses:
        option_map[f'{base}-{l}'] = {'렌즈': l}
        option_map[f'{base}-{l}(3K)'] = {'렌즈': l, '색온도': '3K'}

    return {
        'target_code': base,
        'sources': sources_5700 + sources_3k,
        'option_map': option_map,
        'discard': [f'{base}-증각', f'{base}-증각(3K)'] if has_증각 else [],
    }


ARENA_GROUPS = [
    make_arena_group('ARENA-200S'),
    make_arena_group('ARENA-300S'),
    make_arena_group('ARENA-400', has_증각=True),
    make_arena_group('ARENA-400S'),
    make_arena_group('ARENA-500'),
    make_arena_group('ARENA-600'),
    make_arena_group('ARENA-800'),
]


# ===================================================================
# 2. BATOO 통합 계획 (45개 → 9개)
# ===================================================================

def make_batoo_group(base, lens_codes=('020', '030', '045', '060', '120')):
    sources = [f'{base}-{l}' for l in lens_codes]
    option_map = {f'{base}-{l}': {'렌즈': l} for l in lens_codes}
    return {
        'target_code': base,
        'sources': sources,
        'option_map': option_map,
        'discard': [],
    }


BATOO_GROUPS = [
    make_batoo_group('BATOO-200'),
    make_batoo_group('BATOO-300'),
    make_batoo_group('BATOO-400'),
    make_batoo_group('BATOO-600'),
    make_batoo_group('BATOO-800'),
    make_batoo_group('BATOO-1000'),
    make_batoo_group('BATOO-1200'),
    make_batoo_group('BATOO-X400'),
]


# ===================================================================
# 3. MT-FL 통합 계획 (30개 → 6개)
# ===================================================================

MTFL_GROUPS = [
    make_batoo_group('MT-FL-300A'),
    make_batoo_group('MT-FL-400S'),
    make_batoo_group('MT-FL-600A'),
    make_batoo_group('MT-FL-800A'),
    make_batoo_group('MT-FL-1000A'),
    make_batoo_group('MT-FL-1200A'),
]


# ===================================================================
# 4. 별칭 등록 계획
# ===================================================================

# BATOO ↔ MT-FL 크로스 별칭 (동일 모델, 400 제외)
CROSS_ALIASES = {
    'BATOO-300':  ['MT-FL-300A'],
    'BATOO-600':  ['MT-FL-600A'],
    'BATOO-800':  ['MT-FL-800A'],
    'BATOO-1000': ['MT-FL-1000A'],
    'BATOO-1200': ['MT-FL-1200A'],
}

# 옵션 접미어 별칭: 계약 모델명 → 대표 BOM product_code
# (M)=변형, (D)=디밍, (X)=확장, -35/-45=색온도, A/B=변형
SUFFIX_ALIASES = {}  # 실행 시 동적으로 계약 데이터에서 생성


# ===================================================================
# 통합 실행 로직
# ===================================================================

def merge_bom_group(db, group, dry_run=False):
    """BOM 그룹을 대표 BOM으로 통합."""
    target_code = group['target_code']
    sources = group['sources']
    option_map = group['option_map']
    discard_codes = group.get('discard', [])

    # 폐기 대상 비활성화
    for dc in discard_codes:
        discard_bom = db.query(BomHeader).filter(
            BomHeader.product_code == dc,
            BomHeader.is_active == True,
        ).first()
        if discard_bom:
            print(f'  DISCARD: {dc} (id:{discard_bom.id}, items:{len(discard_bom.bom_items)})')
            if not dry_run:
                discard_bom.is_active = False
                discard_bom.note = f'오타/폐기 → {target_code}으로 통합 (2026-03-28)'

    # source BOM 수집
    source_boms = []
    for sc in sources:
        bom = db.query(BomHeader).filter(
            BomHeader.product_code == sc,
            BomHeader.is_active == True,
        ).first()
        if bom:
            source_boms.append((sc, bom))

    if not source_boms:
        print(f'  SKIP: {target_code} — source BOM 없음')
        return None

    # 첫번째 source를 대표로 사용
    first_code, target_bom = source_boms[0]
    first_options = option_map.get(first_code, {})

    print(f'  TARGET: {first_code} (id:{target_bom.id}) → {target_code}')

    # 대표 BOM의 기존 부품 중 공통 item_code 수집
    common_item_codes = set()
    for bi in target_bom.bom_items:
        if not bi.option_filter:
            common_item_codes.add(bi.item_code)

    # 대표 BOM의 기존 부품에 option_filter 태깅 (첫 source의 고유 부품)
    if first_options and not dry_run:
        for bi in target_bom.bom_items:
            if bi.item_code not in common_item_codes and not bi.option_filter:
                # 다른 source에는 없는 부품 → 첫 source 고유
                bi.option_filter = json.dumps(first_options, ensure_ascii=False)

    # 나머지 source에서 고유 부품 가져오기
    added_count = 0
    for sc, src_bom in source_boms[1:]:
        src_options = option_map.get(sc, {})
        print(f'  MERGE: {sc} (id:{src_bom.id}, {len(src_bom.bom_items)} items)')

        for bi in src_bom.bom_items:
            # 공통 부품(대표 BOM에 같은 item_code가 있으면)은 건너뛰기
            if bi.item_code in common_item_codes:
                continue

            # 고유 부품 → option_filter 태깅하여 대표에 추가
            if not dry_run:
                new_bi = BomItem(
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
                    option_filter=json.dumps(src_options, ensure_ascii=False) if src_options else None,
                    note=bi.note,
                )
                db.add(new_bi)
            added_count += 1

        # 기존 소진기록 bom_id 이관
        if not dry_run:
            db.query(StockConsumption).filter(
                StockConsumption.bom_id == src_bom.id
            ).update({'bom_id': target_bom.id})

        # source BOM 비활성화
        if not dry_run:
            src_bom.is_active = False
            src_bom.note = f'→ {target_code}으로 통합됨 (2026-03-28)'

    # 대표 BOM product_code 변경
    if not dry_run:
        target_bom.product_code = target_code
        target_bom.product_name = target_code

    print(f'  ADDED: {added_count} option items to {target_code}')
    return target_bom


def register_alias(db, bom_id, alias_name, alias_type='option', note=None, dry_run=False):
    """별칭 등록 (중복 시 건너뛰기)."""
    existing = db.query(BomModelAlias).filter(
        BomModelAlias.alias_name == alias_name
    ).first()
    if existing:
        if existing.bom_id != bom_id:
            print(f'  ALIAS CONFLICT: {alias_name} → bom_id:{existing.bom_id} (원하는:{bom_id})')
        return
    if not dry_run:
        db.add(BomModelAlias(
            bom_id=bom_id,
            alias_name=alias_name,
            alias_type=alias_type,
            note=note,
            created_by='시스템',
        ))
    print(f'  ALIAS: {alias_name} → bom_id:{bom_id} ({alias_type})')


def build_suffix_aliases(db):
    """계약 데이터에서 옵션 접미어 별칭을 동적 생성."""
    import re
    aliases = {}

    # 모든 계약 모델명 수집
    model_names = [r[0] for r in db.query(distinct(ContractItem.model_name)).filter(
        ContractItem.model_name.isnot(None),
        ContractItem.model_name != '',
    ).all()]

    # 활성 BOM product_code 목록
    bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(
        BomHeader.is_active == True
    ).all()}

    suffix_patterns = [
        (r'\(M\)', ''),   # (M) 변형
        (r'\(D\)', ''),   # (D) 디밍
        (r'\(X\)', ''),   # (X) 확장
        (r'-35$', ''),    # -35 색온도
        (r'-45$', ''),    # -45 색온도
        (r'B$', ''),      # B 변형 (MTSOLAR-50B → MTSOLAR-50)
        (r'A$', ''),      # A 변형 (MTSOLAR-50A → MTSOLAR-50)
    ]

    for model in model_names:
        if model in bom_codes:
            continue  # 이미 직접 매칭

        for pattern, repl in suffix_patterns:
            stripped = re.sub(pattern, repl, model)
            if stripped != model and stripped in bom_codes:
                aliases[model] = bom_codes[stripped]
                break

    return aliases


def main():
    dry_run = '--dry-run' in sys.argv

    with app.app_context():
        with get_db() as db:
            if dry_run:
                print('=== DRY RUN MODE ===\n')

            # -------------------------------------------------------
            # Step 1: ARENA 통합
            # -------------------------------------------------------
            print('=' * 60)
            print('STEP 1: ARENA 렌즈 통합')
            print('=' * 60)
            arena_targets = {}
            for group in ARENA_GROUPS:
                target = merge_bom_group(db, group, dry_run=dry_run)
                if target:
                    arena_targets[group['target_code']] = target.id
                print()

            # -------------------------------------------------------
            # Step 2: BATOO 통합
            # -------------------------------------------------------
            print('=' * 60)
            print('STEP 2: BATOO 렌즈 통합')
            print('=' * 60)
            batoo_targets = {}
            for group in BATOO_GROUPS:
                target = merge_bom_group(db, group, dry_run=dry_run)
                if target:
                    batoo_targets[group['target_code']] = target.id
                print()

            # -------------------------------------------------------
            # Step 3: MT-FL 통합
            # -------------------------------------------------------
            print('=' * 60)
            print('STEP 3: MT-FL 렌즈 통합')
            print('=' * 60)
            mtfl_targets = {}
            for group in MTFL_GROUPS:
                target = merge_bom_group(db, group, dry_run=dry_run)
                if target:
                    mtfl_targets[group['target_code']] = target.id
                print()

            # -------------------------------------------------------
            # Step 4: option_schema 재생성
            # -------------------------------------------------------
            if not dry_run:
                print('=' * 60)
                print('STEP 4: option_schema 재생성')
                print('=' * 60)
                all_targets = {**arena_targets, **batoo_targets, **mtfl_targets}
                for code, bom_id in all_targets.items():
                    schema_json = rebuild_option_schema(db, bom_id)
                    bom = db.query(BomHeader).get(bom_id)
                    if bom and schema_json:
                        # rebuild_option_schema()는 이미 JSON 문자열을 반환
                        bom.option_schema = schema_json
                        print(f'  {code}: {schema_json}')
                print()

            # -------------------------------------------------------
            # Step 5: BATOO ↔ MT-FL 크로스 별칭
            # -------------------------------------------------------
            print('=' * 60)
            print('STEP 5: BATOO ↔ MT-FL 크로스 별칭')
            print('=' * 60)
            for batoo_code, mtfl_aliases in CROSS_ALIASES.items():
                bom_id = batoo_targets.get(batoo_code)
                if not bom_id:
                    # 통합 전에 이미 있는 BOM에서 찾기
                    bom = db.query(BomHeader).filter(
                        BomHeader.product_code == batoo_code,
                        BomHeader.is_active == True,
                    ).first()
                    if bom:
                        bom_id = bom.id
                if bom_id:
                    for alias in mtfl_aliases:
                        register_alias(db, bom_id, alias, 'option',
                                       f'BATOO=MT-FL 동일모델', dry_run=dry_run)
            print()

            # -------------------------------------------------------
            # Step 6: 옵션 접미어 별칭 (계약 데이터 기반)
            # -------------------------------------------------------
            print('=' * 60)
            print('STEP 6: 옵션 접미어 별칭')
            print('=' * 60)
            suffix_aliases = build_suffix_aliases(db)
            for alias_name, bom_id in suffix_aliases.items():
                register_alias(db, bom_id, alias_name, 'option',
                               '접미어 자동매칭', dry_run=dry_run)
            print(f'  총 {len(suffix_aliases)}건')
            print()

            # -------------------------------------------------------
            # Step 7: 자기 자신 product_code 별칭 (exact)
            # -------------------------------------------------------
            print('=' * 60)
            print('STEP 7: product_code 자기 자신 별칭 등록')
            print('=' * 60)
            active_boms = db.query(BomHeader).filter(BomHeader.is_active == True).all()
            exact_count = 0
            for bom in active_boms:
                # 계약에서 이 product_code를 사용하는 건이 있으면 등록
                ci_exists = db.query(ContractItem).filter(
                    ContractItem.model_name == bom.product_code
                ).first()
                if ci_exists:
                    register_alias(db, bom.id, bom.product_code, 'exact',
                                   None, dry_run=dry_run)
                    exact_count += 1
            print(f'  총 {exact_count}건')
            print()

            # -------------------------------------------------------
            # 결과 요약
            # -------------------------------------------------------
            print('=' * 60)
            print('SUMMARY')
            print('=' * 60)
            active_count = db.query(BomHeader).filter(BomHeader.is_active == True).count()
            inactive_count = db.query(BomHeader).filter(BomHeader.is_active == False).count()
            alias_count = db.query(BomModelAlias).count()
            print(f'  Active BOM: {active_count}')
            print(f'  Inactive BOM: {inactive_count}')
            print(f'  Aliases: {alias_count}')

            if dry_run:
                print('\n=== DRY RUN - no changes ===')
                db.rollback()
            else:
                db.commit()
                print('\n=== 마이그레이션 완료 ===')


if __name__ == '__main__':
    main()
