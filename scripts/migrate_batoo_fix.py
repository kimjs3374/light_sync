"""BATOO/MT-FL 완전 롤백 + 잔여물 삭제 + 030 기준 재통합"""
import json, os, re, sys
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app
from modules.db_context import get_db
from modules.models import BomHeader, BomItem, BomModelAlias, StockConsumption, ContractItem
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import distinct, text

BASES = ['BATOO-200','BATOO-300','BATOO-400','BATOO-600','BATOO-800',
         'BATOO-1000','BATOO-1200','BATOO-X400',
         'MT-FL-300A','MT-FL-400S','MT-FL-600A','MT-FL-800A','MT-FL-1000A','MT-FL-1200A']

def get_items(db, bom_id):
    return {bi.item_code: bi for bi in db.query(BomItem).filter(BomItem.bom_id == bom_id).all()}

def add_item(db, tid, src, of_dict):
    db.add(BomItem(bom_id=tid, item_code=src.item_code, item_id=src.item_id,
        item_name=src.item_name, item_spec=src.item_spec, quantity=src.quantity,
        unit_price=src.unit_price, prev_unit_price=src.prev_unit_price, amount=src.amount,
        supplier=src.supplier, unit=src.unit,
        option_filter=json.dumps(of_dict, ensure_ascii=False) if of_dict else None, note=src.note))

def main():
    with app.app_context():
        with get_db() as db:
            # ===== 1. 완전 롤백 =====
            print('=== ROLLBACK ===')
            for bom in db.query(BomHeader).filter(BomHeader.is_active == False).all():
                if bom.product_code.startswith('BATOO') or bom.product_code.startswith('MT-FL'):
                    bom.is_active = True; bom.note = None

            for bom in db.query(BomHeader).all():
                if bom.product_code.startswith('BATOO') or bom.product_code.startswith('MT-FL'):
                    bom.option_schema = None
                    for bi in bom.bom_items:
                        if bi.option_filter: bi.option_filter = None

            for base in BASES:
                bom = db.query(BomHeader).filter(BomHeader.product_code == base).first()
                if bom: bom.product_code = f'{base}-030'; bom.product_name = f'{base}-030'

            # BATOO/MT-FL 별칭 삭제
            for a in list(db.query(BomModelAlias).all()):
                bh = db.query(BomHeader).get(a.bom_id)
                if bh and (bh.product_code.startswith('BATOO') or bh.product_code.startswith('MT-FL')):
                    db.delete(a)
            db.flush()

            # ===== 2. merge 잔여물 삭제 =====
            print('=== CLEANUP JUNK ===')
            for base in BASES:
                bom030 = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-030').first()
                bom045 = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-045').first()
                if not bom030 or not bom045: continue

                codes_045 = {bi.item_code for bi in bom045.bom_items}
                found_lens = False
                for bi in list(bom030.bom_items):
                    if bi.item_code in codes_045:
                        continue
                    is_lens = 'Lens' in (bi.item_code or '') or 'lens' in (bi.item_name or '').lower()
                    if is_lens and not found_lens:
                        found_lens = True
                        continue  # keep first lens (030's own)
                    if is_lens:
                        # junk lens from other variants
                        db.execute(text('UPDATE light_sync.material_orders SET bom_item_id = NULL WHERE bom_item_id = :id'), {'id': bi.id})
                        db.execute(text('UPDATE light_sync.stock_consumption_items SET bom_item_id = NULL WHERE bom_item_id = :id'), {'id': bi.id})
                        db.delete(bi)
                        print(f'  DEL {base}-030: {bi.item_code} ({bi.item_name})')
                db.flush()

            # verify
            for base in BASES:
                bom030 = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-030').first()
                if bom030:
                    n = len(bom030.bom_items)
                    lens = [bi.item_code for bi in bom030.bom_items if 'Lens' in (bi.item_code or '')]
                    print(f'  {base}-030: {n} items, lens={lens}')
            print()

            # ===== 3. 통합 (030 base, 020 last) =====
            print('=== MERGE ===')
            for base in BASES:
                bom_map = {}
                for l in ['020','030','045','060','120']:
                    bom = db.query(BomHeader).filter(BomHeader.product_code == f'{base}-{l}', BomHeader.is_active == True).first()
                    if bom: bom_map[l] = bom
                if '030' not in bom_map: print(f'  SKIP {base}'); continue

                target = bom_map['030']; tid = target.id

                # clean BOM(030,045,060,120) 교집합 = 공통
                clean = [set(get_items(db, bom_map[l].id).keys()) for l in ['030','045','060','120'] if l in bom_map]
                common = set.intersection(*clean) if clean else set()

                for bi in target.bom_items:
                    if bi.item_code not in common:
                        bi.option_filter = json.dumps({'렌즈': '030'}, ensure_ascii=False)

                added = set(get_items(db, tid).keys())
                for lc in ['045','060','120','020']:
                    if lc not in bom_map: continue
                    for code, bi in get_items(db, bom_map[lc].id).items():
                        if code in common or code in added: continue
                        added.add(code)
                        add_item(db, tid, bi, {'렌즈': lc})
                    src = bom_map[lc]
                    db.query(StockConsumption).filter(StockConsumption.bom_id == src.id).update({'bom_id': tid})
                    src.is_active = False; src.note = f'-> {base} superbom'

                target.product_code = base; target.product_name = base
                db.flush()
                target.option_schema = rebuild_option_schema(db, tid)
                total = db.query(BomItem).filter(BomItem.bom_id == tid).count()
                opt = db.query(BomItem).filter(BomItem.bom_id == tid, BomItem.option_filter.isnot(None)).count()
                print(f'  {base}: {total} items ({total-opt} common, {opt} option) schema={target.option_schema}')

            # ===== 4. 별칭 =====
            print('\n=== ALIASES ===')
            bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(BomHeader.is_active == True).all()}
            for b, m in [('BATOO-300','MT-FL-300A'),('BATOO-600','MT-FL-600A'),('BATOO-800','MT-FL-800A'),
                         ('BATOO-1000','MT-FL-1000A'),('BATOO-1200','MT-FL-1200A')]:
                if b in bom_codes and not db.query(BomModelAlias).filter(BomModelAlias.alias_name == m).first():
                    db.add(BomModelAlias(bom_id=bom_codes[b], alias_name=m, alias_type='option', created_by='system'))

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

            db.commit()
            active = db.query(BomHeader).filter(BomHeader.is_active == True).count()
            aliases = db.query(BomModelAlias).count()
            print(f'\nDONE: Active={active}, Aliases={aliases}')

if __name__ == '__main__':
    main()
