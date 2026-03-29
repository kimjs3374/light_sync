"""
BOM 슈퍼BOM 통합 (최종)

로직:
- 중각+협각 BOM을 기준으로 렌즈 차이 판별 (광각은 파싱 오류 있음)
- 중각 AND 협각에 있는 부품 → 공통
- 중각에만 → {"렌즈":"중각"}
- 협각에만 → 이름에 "렌즈/Lens" → {"렌즈":"협각"}, 나머지 → 광각+협각 2엔트리
- 3K: 5700K 기준으로, PCB 차이만 색온도 옵션으로 태깅
- BATOO/MT-FL: 렌즈 코드(020~120)별 차이만

실행: cd D:/light_sync && ./venv/Scripts/python.exe scripts/migrate_bom_final.py
"""
import json, os, re, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import app
from modules.db_context import get_db
from modules.models import BomHeader, BomItem, BomModelAlias, StockConsumption, ContractItem
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import distinct


def get_items(db, bom_id):
    """BOM 부품 dict {item_code: BomItem}."""
    return {bi.item_code: bi for bi in db.query(BomItem).filter(BomItem.bom_id == bom_id).all()}


def add_item(db, target_bom_id, src_item, option_filter_dict=None):
    """부품 추가."""
    of = json.dumps(option_filter_dict, ensure_ascii=False) if option_filter_dict else None
    db.add(BomItem(
        bom_id=target_bom_id,
        item_code=src_item.item_code, item_id=src_item.item_id,
        item_name=src_item.item_name, item_spec=src_item.item_spec,
        quantity=src_item.quantity, unit_price=src_item.unit_price,
        prev_unit_price=src_item.prev_unit_price, amount=src_item.amount,
        supplier=src_item.supplier, unit=src_item.unit,
        option_filter=of, note=src_item.note,
    ))


def is_lens_only_part(item_name, item_code):
    """협각 전용 부품인지 (렌즈 부품)."""
    name = (item_name or '').lower() + (item_code or '').lower()
    return 'lens' in name or '렌즈' in name


def merge_arena(db, base, bom_ids):
    """ARENA 슈퍼BOM 통합.

    Args:
        base: 대표 코드 (예: 'ARENA-400')
        bom_ids: {'광각': id, '중각': id, '협각': id, '광각3K': id, '중각3K': id, '협각3K': id}
    """
    mid_items = get_items(db, bom_ids['중각'])    # 기준 1
    nar_items = get_items(db, bom_ids['협각'])    # 기준 2

    # 대표 BOM = 중각 (가장 깨끗)
    target_bom = db.query(BomHeader).get(bom_ids['중각'])
    target_id = target_bom.id

    print(f'  {base}: target=중각(id:{target_id})')

    # --- 렌즈 차이 분석 (중각 vs 협각) ---
    common_codes = set(mid_items.keys()) & set(nar_items.keys())
    mid_only = set(mid_items.keys()) - set(nar_items.keys())
    nar_only = set(nar_items.keys()) - set(mid_items.keys())

    # 중각 기존 부품: 공통은 null, 중각전용은 {"렌즈":"중각"}
    for bi in target_bom.bom_items:
        if bi.item_code in mid_only:
            bi.option_filter = json.dumps({'렌즈': '중각'}, ensure_ascii=False)

    # 협각 부품 추가
    for code in nar_only:
        bi = nar_items[code]
        if is_lens_only_part(bi.item_name, bi.item_code):
            # 렌즈 부품 → 협각만
            add_item(db, target_id, bi, {'렌즈': '협각'})
        else:
            # 더미리플렉터, 브라켓, 커버 → 광각+협각
            add_item(db, target_id, bi, {'렌즈': '광각'})
            add_item(db, target_id, bi, {'렌즈': '협각'})

    # --- 3K 차이 분석 (5700K중각 vs 3K중각) ---
    if '중각3K' in bom_ids:
        k3_items = get_items(db, bom_ids['중각3K'])

        for code in set(k3_items.keys()) - common_codes - mid_only:
            # 3K에만 있는 부품 (주로 3K PCB)
            bi = k3_items[code]
            add_item(db, target_id, bi, {'색온도': '3K'})

        # 5700K에만 있는 부품 (주로 5700K PCB) → 색온도 태그
        for code in set(mid_items.keys()) - set(k3_items.keys()):
            if code not in mid_only:  # 중각전용은 이미 처리
                continue
            # skip: 중각전용 부품은 렌즈 태그가 이미 있음

        # PCB 차이 찾기: item_code에 'PCB' 포함
        mid_pcbs = {c for c in mid_items if 'PCB' in c.upper()}
        k3_pcbs = {c for c in k3_items if 'PCB' in c.upper()}

        pcb_5700_only = mid_pcbs - k3_pcbs
        pcb_3k_only = k3_pcbs - mid_pcbs

        if pcb_5700_only or pcb_3k_only:
            # 5700K PCB에 색온도 태그 추가
            for code in pcb_5700_only:
                for bi in target_bom.bom_items:
                    if bi.item_code == code and not bi.option_filter:
                        bi.option_filter = json.dumps({'색온도': '5700K'}, ensure_ascii=False)
                        break

        # 수량 다른 부품: 5700K qty != 3K qty
        for code in common_codes & set(k3_items.keys()):
            mid_qty = mid_items[code].quantity
            k3_qty = k3_items[code].quantity
            if mid_qty != k3_qty:
                # 기존(5700K)에 색온도 태그
                for bi in target_bom.bom_items:
                    if bi.item_code == code and not bi.option_filter:
                        bi.option_filter = json.dumps({'색온도': '5700K'}, ensure_ascii=False)
                        break
                # 3K 수량으로 별도 엔트리
                add_item(db, target_id, k3_items[code], {'색온도': '3K'})

    # --- source 비활성화 + 소진 이관 ---
    for key, bom_id in bom_ids.items():
        if bom_id == target_id:
            continue
        bom = db.query(BomHeader).get(bom_id)
        if bom and bom.is_active:
            db.query(StockConsumption).filter(StockConsumption.bom_id == bom_id).update({'bom_id': target_id})
            bom.is_active = False
            bom.note = f'-> {base} superbom (2026-03-28)'

    # 이름 변경 + schema
    target_bom.product_code = base
    target_bom.product_name = base
    db.flush()
    target_bom.option_schema = rebuild_option_schema(db, target_id)

    total = db.query(BomItem).filter(BomItem.bom_id == target_id).count()
    opt = db.query(BomItem).filter(BomItem.bom_id == target_id, BomItem.option_filter.isnot(None)).count()
    print(f'    items={total} (common={total-opt}, option={opt}) schema={target_bom.option_schema}')


def merge_round(db, base, bom_ids_by_lens):
    """BATOO/MT-FL 렌즈 통합 (색온도 없음).

    bom_ids_by_lens: {'020': id, '030': id, ...}
    """
    codes = list(bom_ids_by_lens.keys())
    first_lens = codes[0]
    target_bom = db.query(BomHeader).get(bom_ids_by_lens[first_lens])
    target_id = target_bom.id
    first_items = get_items(db, target_id)

    print(f'  {base}: target={first_lens}(id:{target_id})')

    # 모든 렌즈 BOM의 아이템 수집
    all_items = {first_lens: first_items}
    for lens in codes[1:]:
        all_items[lens] = get_items(db, bom_ids_by_lens[lens])

    # 모든 렌즈에 공통인 item_code
    all_code_sets = [set(items.keys()) for items in all_items.values()]
    common = set.intersection(*all_code_sets) if all_code_sets else set()

    # 첫번째 BOM: 공통 아닌 것에 렌즈 태그
    for bi in target_bom.bom_items:
        if bi.item_code not in common:
            bi.option_filter = json.dumps({'렌즈': first_lens}, ensure_ascii=False)

    # 나머지 렌즈의 고유 부품 추가
    added_codes = set(first_items.keys())
    for lens in codes[1:]:
        for code, bi in all_items[lens].items():
            if code in added_codes:
                continue
            added_codes.add(code)
            add_item(db, target_id, bi, {'렌즈': lens})

        # source 비활성화
        bom = db.query(BomHeader).get(bom_ids_by_lens[lens])
        if bom:
            db.query(StockConsumption).filter(StockConsumption.bom_id == bom.id).update({'bom_id': target_id})
            bom.is_active = False
            bom.note = f'-> {base} superbom (2026-03-28)'

    target_bom.product_code = base
    target_bom.product_name = base
    db.flush()
    target_bom.option_schema = rebuild_option_schema(db, target_id)

    total = db.query(BomItem).filter(BomItem.bom_id == target_id).count()
    opt = db.query(BomItem).filter(BomItem.bom_id == target_id, BomItem.option_filter.isnot(None)).count()
    print(f'    items={total} (common={total-opt}, option={opt}) schema={target_bom.option_schema}')


def register_aliases(db):
    """별칭 등록."""
    bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(BomHeader.is_active == True).all()}

    def reg(alias, target, atype='option'):
        if target not in bom_codes:
            return
        if db.query(BomModelAlias).filter(BomModelAlias.alias_name == alias).first():
            return
        db.add(BomModelAlias(bom_id=bom_codes[target], alias_name=alias, alias_type=atype, created_by='system'))

    # BATOO=MT-FL 크로스
    for b, m in [('BATOO-300','MT-FL-300A'), ('BATOO-600','MT-FL-600A'),
                 ('BATOO-800','MT-FL-800A'), ('BATOO-1000','MT-FL-1000A'), ('BATOO-1200','MT-FL-1200A')]:
        reg(m, b)

    # 접미어 자동
    model_names = [r[0] for r in db.query(distinct(ContractItem.model_name)).filter(
        ContractItem.model_name.isnot(None), ContractItem.model_name != '').all()]
    for model in model_names:
        if model in bom_codes:
            continue
        for pat, repl in [(r'\(M\)',''), (r'\(D\)',''), (r'\(X\)',''),
                          (r'-35$',''), (r'-45$',''), (r'B$',''), (r'A$',''),
                          (r'\(3000K\)$','')]:
            s = re.sub(pat, repl, model)
            if s != model and s in bom_codes:
                reg(model, s)
                break

    # exact
    for code, bid in bom_codes.items():
        if db.query(ContractItem).filter(ContractItem.model_name == code).first():
            if not db.query(BomModelAlias).filter(BomModelAlias.alias_name == code).first():
                db.add(BomModelAlias(bom_id=bid, alias_name=code, alias_type='exact', created_by='system'))


def main():
    with app.app_context():
        with get_db() as db:
            # === ARENA ===
            print('=== ARENA ===')
            arena_bom_map = {}
            for bom in db.query(BomHeader).filter(BomHeader.product_code.like('ARENA%'), BomHeader.is_active == True).all():
                arena_bom_map[bom.product_code] = bom.id

            arena_models = {
                'ARENA-200S': {'광각':'ARENA-200S-광각','중각':'ARENA-200S-중각','협각':'ARENA-200S-협각',
                               '광각3K':'ARENA-200S-광각(3K)','중각3K':'ARENA-200S-중각(3K)','협각3K':'ARENA-200S-협각(3K)'},
                'ARENA-300S': {'광각':'ARENA-300S-광각','중각':'ARENA-300S-중각','협각':'ARENA-300S-협각',
                               '광각3K':'ARENA-300S-광각(3K)','중각3K':'ARENA-300S-중각(3K)','협각3K':'ARENA-300S-협각(3K)'},
                'ARENA-400':  {'광각':'ARENA-400-광각','중각':'ARENA-400-중각','협각':'ARENA-400-협각',
                               '광각3K':'ARENA-400-광각(3K)','중각3K':'ARENA-400-중각(3K)','협각3K':'ARENA-400-협각(3K)'},
                'ARENA-400S': {'광각':'ARENA-400S-광각','중각':'ARENA-400S-중각','협각':'ARENA-400S-협각',
                               '광각3K':'ARENA-400S-광각(3K)','중각3K':'ARENA-400S-중각(3K)','협각3K':'ARENA-400S-협각(3K)'},
                'ARENA-500':  {'광각':'ARENA-500-광각','중각':'ARENA-500-중각','협각':'ARENA-500-협각',
                               '광각3K':'ARENA-500-광각(3K)','중각3K':'ARENA-500-중각(3K)','협각3K':'ARENA-500-협각(3K)'},
                'ARENA-600':  {'광각':'ARENA-600-광각','중각':'ARENA-600-중각','협각':'ARENA-600-협각',
                               '광각3K':'ARENA-600-광각(3K)','중각3K':'ARENA-600-중각(3K)','협각3K':'ARENA-600-협각(3K)'},
                'ARENA-800':  {'광각':'ARENA-800-광각','중각':'ARENA-800-중각','협각':'ARENA-800-협각',
                               '광각3K':'ARENA-800-광각(3K)','중각3K':'ARENA-800-중각(3K)','협각3K':'ARENA-800-협각(3K)'},
            }

            for base, name_map in arena_models.items():
                bom_ids = {}
                for key, code in name_map.items():
                    if code in arena_bom_map:
                        bom_ids[key] = arena_bom_map[code]
                if '중각' in bom_ids and '협각' in bom_ids:
                    merge_arena(db, base, bom_ids)
                print()

            # 증각 폐기
            for code in ['ARENA-400-증각', 'ARENA-400-증각(3K)']:
                bom = db.query(BomHeader).filter(BomHeader.product_code == code, BomHeader.is_active == True).first()
                if bom:
                    bom.is_active = False
                    bom.note = '오타 폐기'

            # === BATOO ===
            print('=== BATOO ===')
            lens_codes = ['020', '030', '045', '060', '120']
            for base in ['BATOO-200','BATOO-300','BATOO-400','BATOO-600',
                         'BATOO-800','BATOO-1000','BATOO-1200','BATOO-X400']:
                bom_ids = {}
                for l in lens_codes:
                    bom = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-{l}', BomHeader.is_active == True).first()
                    if bom:
                        bom_ids[l] = bom.id
                if len(bom_ids) >= 2:
                    merge_round(db, base, bom_ids)
                print()

            # === MT-FL ===
            print('=== MT-FL ===')
            for base in ['MT-FL-300A','MT-FL-400S','MT-FL-600A','MT-FL-800A','MT-FL-1000A','MT-FL-1200A']:
                bom_ids = {}
                for l in lens_codes:
                    bom = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-{l}', BomHeader.is_active == True).first()
                    if bom:
                        bom_ids[l] = bom.id
                if len(bom_ids) >= 2:
                    merge_round(db, base, bom_ids)
                print()

            # === ALIASES ===
            print('=== ALIASES ===')
            register_aliases(db)

            db.flush()
            active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
            aliases = db.query(BomModelAlias).count()
            print(f'\n=== DONE: Active={active}, Aliases={aliases} ===')
            db.commit()


if __name__ == '__main__':
    main()
