"""BATOO/MT-FL 렌즈 정리 + 슈퍼BOM 통합

1. 각 BOM에서 해당 각도의 렌즈만 남기고 나머지 삭제
2. 120도 BOM은 렌즈 없음 (기본)
3. 슈퍼BOM 통합: 공통부품 + 렌즈별 option_filter
"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app
from modules.db_context import get_db
from modules.models import BomHeader, BomItem, BomModelAlias, StockConsumption, ContractItem
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import distinct, text

# 각도별 정상 렌즈 매핑
ANGLE_LENS = {
    '020': 'MT-Lens-TC2001',
    '030': 'MT-Lens-TP3001',
    '045': 'MT-Lens-TP4501',
    '060': 'MT-Lens-TP6001',
    '120': None,  # 렌즈 없음
}

ALL_LENS_CODES = {'MT-Lens-TC2001', 'MT-Lens-TP3001', 'MT-Lens-TP4501', 'MT-Lens-TP6001'}

BASES = ['BATOO-200','BATOO-300','BATOO-400','BATOO-600','BATOO-800',
         'BATOO-1000','BATOO-1200','BATOO-X400',
         'MT-FL-300A','MT-FL-400S','MT-FL-600A','MT-FL-800A','MT-FL-1000A','MT-FL-1200A']


def cleanup_lenses(db):
    """각 BOM에서 잘못된 렌즈 아이템 삭제."""
    print('=== STEP 1: 렌즈 정리 ===')
    total_deleted = 0

    for base in BASES:
        for angle, correct_lens in ANGLE_LENS.items():
            bom = db.query(BomHeader).filter(
                BomHeader.product_code == f'{base}-{angle}'
            ).first()
            if not bom:
                continue

            wrong_lens = []
            for bi in bom.bom_items:
                if bi.item_code in ALL_LENS_CODES:
                    if correct_lens is None or bi.item_code != correct_lens:
                        wrong_lens.append(bi)

            for bi in wrong_lens:
                db.execute(text('UPDATE light_sync.material_orders SET bom_item_id = NULL WHERE bom_item_id = :id'), {'id': bi.id})
                db.execute(text('UPDATE light_sync.stock_consumption_items SET bom_item_id = NULL WHERE bom_item_id = :id'), {'id': bi.id})
                db.delete(bi)
                total_deleted += 1

        db.flush()

    print(f'  deleted {total_deleted} wrong lens items')

    # 검증
    print('\n  Verify:')
    for base in BASES[:3]:
        for angle in ['020', '030', '045', '060', '120']:
            bom = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-{angle}').first()
            if not bom:
                continue
            lens = [bi.item_code for bi in bom.bom_items if bi.item_code in ALL_LENS_CODES]
            total = len(bom.bom_items)
            print(f'    {base}-{angle}: {total} items, lens={lens}')
    print()


def rollback_previous(db):
    """이전 통합 롤백."""
    print('=== STEP 0: ROLLBACK ===')
    # 비활성 복원
    for bom in db.query(BomHeader).filter(BomHeader.is_active == False).all():
        if bom.product_code.startswith('BATOO') or bom.product_code.startswith('MT-FL'):
            bom.is_active = True
            bom.note = None

    # option_filter 초기화
    for bom in db.query(BomHeader).all():
        if bom.product_code.startswith('BATOO') or bom.product_code.startswith('MT-FL'):
            bom.option_schema = None
            for bi in bom.bom_items:
                if bi.option_filter:
                    bi.option_filter = None

    # product_code 복원
    for base in BASES:
        bom = db.query(BomHeader).filter(BomHeader.product_code == base).first()
        if bom:
            # 현재 base에서 원래 030으로 되어있을 수 있음
            bom.product_code = f'{base}-030'
            bom.product_name = f'{base}-030'

    # 별칭 삭제
    for a in list(db.query(BomModelAlias).all()):
        bh = db.query(BomHeader).get(a.bom_id)
        if bh and (bh.product_code.startswith('BATOO') or bh.product_code.startswith('MT-FL')):
            db.delete(a)

    db.flush()
    active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
    print(f'  Active: {active}\n')


def merge_superbom(db):
    """슈퍼BOM 통합: 120도(렌즈 없음) 기준 → 각 렌즈를 option_filter로."""
    print('=== STEP 2: SUPERBOM MERGE ===')

    def get_items(db, bom_id):
        return {bi.item_code: bi for bi in db.query(BomItem).filter(BomItem.bom_id == bom_id).all()}

    for base in BASES:
        bom_map = {}
        for angle in ANGLE_LENS:
            bom = db.query(BomHeader).filter(
                BomHeader.product_code == f'{base}-{angle}',
                BomHeader.is_active == True,
            ).first()
            if bom:
                bom_map[angle] = bom

        if '120' not in bom_map:
            print(f'  SKIP {base} (no 120)')
            continue

        # 120을 대표 BOM으로 (렌즈 없음 = 공통부품만)
        target = bom_map['120']
        tid = target.id
        common_codes = set(get_items(db, tid).keys())

        # 각 렌즈 BOM에서 렌즈 아이템만 추가 (비렌즈는 이미 공통)
        for angle in ['020', '030', '045', '060']:
            if angle not in bom_map:
                continue
            for code, bi in get_items(db, bom_map[angle].id).items():
                if code in common_codes:
                    continue
                # 렌즈 아이템 추가 with option_filter
                db.add(BomItem(
                    bom_id=tid, item_code=bi.item_code, item_id=bi.item_id,
                    item_name=bi.item_name, item_spec=bi.item_spec,
                    quantity=bi.quantity, unit_price=bi.unit_price,
                    prev_unit_price=bi.prev_unit_price, amount=bi.amount,
                    supplier=bi.supplier, unit=bi.unit,
                    option_filter=json.dumps({'렌즈': angle}, ensure_ascii=False),
                    note=bi.note,
                ))

            # source 비활성화 + 소진 이관
            src = bom_map[angle]
            db.query(StockConsumption).filter(StockConsumption.bom_id == src.id).update({'bom_id': tid})
            src.is_active = False
            src.note = f'-> {base} superbom'

        # product_code 변경 + schema
        target.product_code = base
        target.product_name = base
        db.flush()
        target.option_schema = rebuild_option_schema(db, tid)

        total = db.query(BomItem).filter(BomItem.bom_id == tid).count()
        opt = db.query(BomItem).filter(BomItem.bom_id == tid, BomItem.option_filter.isnot(None)).count()
        print(f'  {base}: {total} items ({total-opt} common, {opt} lens) schema={target.option_schema}')

    print()


def register_aliases(db):
    """별칭 등록."""
    print('=== STEP 3: ALIASES ===')
    bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(BomHeader.is_active == True).all()}

    # BATOO=MT-FL 크로스
    for b, m in [('BATOO-300','MT-FL-300A'), ('BATOO-600','MT-FL-600A'),
                 ('BATOO-800','MT-FL-800A'), ('BATOO-1000','MT-FL-1000A'), ('BATOO-1200','MT-FL-1200A')]:
        if b in bom_codes and not db.query(BomModelAlias).filter(BomModelAlias.alias_name == m).first():
            db.add(BomModelAlias(bom_id=bom_codes[b], alias_name=m, alias_type='option', created_by='system'))

    # exact + suffix
    model_names = [r[0] for r in db.query(distinct(ContractItem.model_name)).filter(
        ContractItem.model_name.isnot(None), ContractItem.model_name != '').all()]
    for model in model_names:
        if model in bom_codes:
            if not db.query(BomModelAlias).filter(BomModelAlias.alias_name == model).first():
                db.add(BomModelAlias(bom_id=bom_codes[model], alias_name=model, alias_type='exact', created_by='system'))
            continue
        for pat, repl in [(r'\(M\)',''), (r'\(D\)',''), (r'\(X\)',''), (r'-35$',''), (r'-45$',''),
                          (r'B$',''), (r'A$',''), (r'\(3000K\)$','')]:
            s = re.sub(pat, repl, model)
            if s != model and s in bom_codes:
                if not db.query(BomModelAlias).filter(BomModelAlias.alias_name == model).first():
                    db.add(BomModelAlias(bom_id=bom_codes[s], alias_name=model, alias_type='option', created_by='system'))
                break


def main():
    with app.app_context():
        with get_db() as db:
            rollback_previous(db)
            cleanup_lenses(db)
            merge_superbom(db)
            register_aliases(db)

            db.commit()
            active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
            aliases = db.query(BomModelAlias).count()
            print(f'=== DONE: Active={active}, Aliases={aliases} ===')


if __name__ == '__main__':
    main()
