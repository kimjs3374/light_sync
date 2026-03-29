"""
슈퍼BOM 통합 (v3) - 올바른 option_filter 태깅

핵심: 각 부품이 어떤 옵션 조합에서 사용되는지 분석하여 정확한 option_filter 부여.
- 모든 변형에 있는 부품 → common (null)
- 5700K에만 있는 부품 → {"색온도":"5700K"}
- 3K에만 있는 부품 → {"색온도":"3K"}
- 특정 렌즈에만 있는 부품 → {"렌즈":"광각"} 등
- 중복 부품은 1개만 (item_code 기준 dedup)
"""

import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import app
from modules.db_context import get_db
from modules.models import (
    BomHeader, BomItem, BomModelAlias,
    StockConsumption, ContractItem,
)
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import distinct


def rollback_previous(db):
    """이전 마이그레이션 롤백."""
    print('=== ROLLBACK ===')

    db.query(BomModelAlias).delete()

    # option_filter 아이템 삭제 (ARENA/BATOO/MT-FL만)
    target_bom_ids = [b.id for b in db.query(BomHeader).all()
                      if any(b.product_code.startswith(p) for p in ['ARENA', 'BATOO', 'MT-FL'])
                      or (b.note and '통합' in (b.note or ''))]
    for bom_id in target_bom_ids:
        db.query(BomItem).filter(BomItem.bom_id == bom_id, BomItem.option_filter.isnot(None)).delete()

    # 비활성 BOM 복원
    for bom in db.query(BomHeader).filter(BomHeader.is_active == False).all():
        if bom.note and ('통합' in bom.note or '폐기' in bom.note):
            bom.is_active = True
            bom.note = None

    # product_code 복원
    restore = {
        'ARENA-200S': 'ARENA-200S-광각', 'ARENA-300S': 'ARENA-300S-광각',
        'ARENA-400': 'ARENA-400-광각', 'ARENA-400S': 'ARENA-400S-광각',
        'ARENA-500': 'ARENA-500-광각', 'ARENA-600': 'ARENA-600-광각',
        'ARENA-800': 'ARENA-800-광각',
        'ARENA-200S-3K': 'ARENA-200S-광각(3K)', 'ARENA-300S-3K': 'ARENA-300S-광각(3K)',
        'ARENA-400-3K': 'ARENA-400-광각(3K)', 'ARENA-400S-3K': 'ARENA-400S-광각(3K)',
        'ARENA-500-3K': 'ARENA-500-광각(3K)', 'ARENA-600-3K': 'ARENA-600-광각(3K)',
        'ARENA-800-3K': 'ARENA-800-광각(3K)',
    }
    for base in ['BATOO-200','BATOO-300','BATOO-400','BATOO-600','BATOO-800',
                 'BATOO-1000','BATOO-1200','BATOO-X400',
                 'MT-FL-300A','MT-FL-400S','MT-FL-600A','MT-FL-800A','MT-FL-1000A','MT-FL-1200A']:
        restore[base] = f'{base}-020'

    for new_code, orig_code in restore.items():
        bom = db.query(BomHeader).filter(BomHeader.product_code == new_code).first()
        if bom:
            bom.product_code = orig_code
            bom.product_name = orig_code
            bom.option_schema = None

    db.flush()
    active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
    print(f'  Restored. Active BOMs: {active}\n')


def analyze_and_merge(db, target_code, variant_map):
    """슈퍼BOM 통합 - 부품별 옵션 조건 분석.

    Args:
        target_code: 통합 후 product_code (예: 'ARENA-200S')
        variant_map: {product_code: {option_key: value, ...}, ...}
            예: {'ARENA-200S-광각': {'렌즈':'광각'}, 'ARENA-200S-중각': {'렌즈':'중각'}, ...}
    """
    # 1. source BOM 수집
    sources = {}  # {product_code: BomHeader}
    for code in variant_map:
        bom = db.query(BomHeader).filter(
            BomHeader.product_code == code, BomHeader.is_active == True
        ).first()
        if bom:
            sources[code] = bom

    if not sources:
        print(f'  SKIP: {target_code} - no sources')
        return None

    all_codes = list(sources.keys())
    option_keys = set()
    for opts in variant_map.values():
        option_keys.update(opts.keys())

    # 2. item_code별 존재 분석
    # item_presence[item_code] = set of source codes where it appears
    item_presence = defaultdict(set)
    # item_data[item_code] = first BomItem (for copying attributes)
    item_data = {}

    for code, bom in sources.items():
        for bi in bom.bom_items:
            item_presence[bi.item_code].add(code)
            if bi.item_code not in item_data:
                item_data[bi.item_code] = bi

    # 3. 각 옵션 키별로 그룹핑
    # 예: 렌즈=광각인 source codes, 색온도=3K인 source codes
    option_groups = {}  # {(key, value): set of codes}
    for code, opts in variant_map.items():
        if code in sources:
            for k, v in opts.items():
                option_groups.setdefault((k, v), set()).add(code)

    all_source_set = set(sources.keys())

    # 4. 각 item_code의 option_filter 결정
    def determine_filter(item_code):
        present_in = item_presence[item_code]
        if present_in == all_source_set:
            return None  # 공통

        # 각 옵션 키별로 체크
        filters = {}
        for key in option_keys:
            # 이 키의 모든 값 중, 어떤 값의 group에 포함되는지 체크
            matching_values = []
            for (k, v), group_codes in option_groups.items():
                if k == key:
                    # present_in이 이 그룹에 완전히 포함되는지? 아니면 교집합?
                    if present_in.issubset(group_codes):
                        matching_values.append(v)
                    elif present_in & group_codes:
                        matching_values.append(v)

            # 이 키의 모든 값에 다 있으면 → 이 키로는 필터 불필요
            all_values_for_key = [v for (k, v) in option_groups if k == key]
            if set(matching_values) == set(all_values_for_key):
                continue  # 모든 값에 존재 → 이 키로는 구분 안 됨

            # 하나의 값에만 있으면 → 그 값으로 필터
            if len(matching_values) == 1:
                filters[key] = matching_values[0]

        return json.dumps(filters, ensure_ascii=False) if filters else None

    # 5. 대표 BOM 선택 (첫번째 source)
    first_code = all_codes[0]
    target_bom = sources[first_code]
    target_item_codes_original = {bi.item_code for bi in target_bom.bom_items}

    print(f'  TARGET: {first_code} (id:{target_bom.id}) -> {target_code}')

    # 6. 대표 BOM의 기존 부품 option_filter 업데이트
    for bi in target_bom.bom_items:
        new_filter = determine_filter(bi.item_code)
        bi.option_filter = new_filter

    # 7. 다른 source의 고유 부품 추가 (중복 방지)
    added_item_codes = set(target_item_codes_original)
    added = 0
    for code in all_codes[1:]:
        bom = sources[code]
        for bi in bom.bom_items:
            if bi.item_code in added_item_codes:
                continue
            added_item_codes.add(bi.item_code)

            new_filter = determine_filter(bi.item_code)
            db.add(BomItem(
                bom_id=target_bom.id,
                item_code=bi.item_code, item_id=bi.item_id,
                item_name=bi.item_name, item_spec=bi.item_spec,
                quantity=bi.quantity, unit_price=bi.unit_price,
                prev_unit_price=bi.prev_unit_price, amount=bi.amount,
                supplier=bi.supplier, unit=bi.unit,
                option_filter=new_filter, note=bi.note,
            ))
            added += 1

    # 8. source BOM 비활성화 + 소진기록 이관
    for code in all_codes[1:]:
        bom = sources[code]
        db.query(StockConsumption).filter(
            StockConsumption.bom_id == bom.id
        ).update({'bom_id': target_bom.id})
        bom.is_active = False
        bom.note = f'-> {target_code} superbom (2026-03-28)'

    # 9. 이름 변경 + option_schema
    target_bom.product_code = target_code
    target_bom.product_name = target_code

    db.flush()
    schema_json = rebuild_option_schema(db, target_bom.id)
    target_bom.option_schema = schema_json

    # 통계
    total_items = len(target_bom.bom_items) + added
    opt_items = sum(1 for bi in db.query(BomItem).filter(
        BomItem.bom_id == target_bom.id, BomItem.option_filter.isnot(None)).all())
    print(f'    items={total_items} (common={total_items-opt_items}, option={opt_items})')
    print(f'    schema={schema_json}')

    return target_bom


def main():
    with app.app_context():
        with get_db() as db:
            rollback_previous(db)

            # =========================
            # ARENA (렌즈 × 색온도)
            # =========================
            print('=== ARENA ===')
            arena_models = ['ARENA-200S', 'ARENA-300S', 'ARENA-400', 'ARENA-400S',
                            'ARENA-500', 'ARENA-600', 'ARENA-800']
            lenses = ['광각', '중각', '협각']

            for base in arena_models:
                variant_map = {}
                for l in lenses:
                    variant_map[f'{base}-{l}'] = {'렌즈': l, '색온도': '5700K'}
                    variant_map[f'{base}-{l}(3K)'] = {'렌즈': l, '색온도': '3K'}
                analyze_and_merge(db, base, variant_map)
                print()

            # 증각 폐기
            for code in ['ARENA-400-증각', 'ARENA-400-증각(3K)']:
                bom = db.query(BomHeader).filter(BomHeader.product_code == code, BomHeader.is_active == True).first()
                if bom:
                    bom.is_active = False
                    bom.note = '오타 폐기 (2026-03-28)'
                    print(f'  DISCARD: {code}')

            # =========================
            # BATOO (렌즈만)
            # =========================
            print('\n=== BATOO ===')
            for base in ['BATOO-200','BATOO-300','BATOO-400','BATOO-600',
                         'BATOO-800','BATOO-1000','BATOO-1200','BATOO-X400']:
                variant_map = {f'{base}-{l}': {'렌즈': l} for l in ['020','030','045','060','120']}
                analyze_and_merge(db, base, variant_map)
                print()

            # =========================
            # MT-FL (렌즈만)
            # =========================
            print('\n=== MT-FL ===')
            for base in ['MT-FL-300A','MT-FL-400S','MT-FL-600A',
                         'MT-FL-800A','MT-FL-1000A','MT-FL-1200A']:
                variant_map = {f'{base}-{l}': {'렌즈': l} for l in ['020','030','045','060','120']}
                analyze_and_merge(db, base, variant_map)
                print()

            # =========================
            # 별칭
            # =========================
            print('=== ALIASES ===')
            # BATOO=MT-FL 크로스
            bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(BomHeader.is_active == True).all()}

            def reg(alias, target):
                if target not in bom_codes:
                    return
                if db.query(BomModelAlias).filter(BomModelAlias.alias_name == alias).first():
                    return
                db.add(BomModelAlias(bom_id=bom_codes[target], alias_name=alias,
                                     alias_type='option', created_by='system'))

            for b, m in [('BATOO-300','MT-FL-300A'),('BATOO-600','MT-FL-600A'),
                         ('BATOO-800','MT-FL-800A'),('BATOO-1000','MT-FL-1000A'),
                         ('BATOO-1200','MT-FL-1200A')]:
                reg(m, b)

            # 접미어 자동
            model_names = [r[0] for r in db.query(distinct(ContractItem.model_name)).filter(
                ContractItem.model_name.isnot(None), ContractItem.model_name != '').all()]
            for model in model_names:
                if model in bom_codes:
                    continue
                for pat, repl in [(r'\(M\)',''), (r'\(D\)',''), (r'\(X\)',''),
                                  (r'-35$',''), (r'-45$',''),
                                  (r'B$',''), (r'A$',''),
                                  (r'\(3000K\)$','')]:
                    s = re.sub(pat, repl, model)
                    if s != model and s in bom_codes:
                        reg(model, s)
                        break

            # exact
            for code, bid in bom_codes.items():
                if db.query(ContractItem).filter(ContractItem.model_name == code).first():
                    if not db.query(BomModelAlias).filter(BomModelAlias.alias_name == code).first():
                        db.add(BomModelAlias(bom_id=bid, alias_name=code,
                                             alias_type='exact', created_by='system'))

            # Summary
            db.flush()
            active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
            aliases = db.query(BomModelAlias).count()
            print(f'\n=== DONE: Active={active}, Aliases={aliases} ===')

            db.commit()


if __name__ == '__main__':
    main()
