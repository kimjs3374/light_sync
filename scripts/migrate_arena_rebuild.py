"""ARENA 슈퍼BOM 전면 재구축 (엑셀 기준)

엑셀 분석 결과:
- 5700K 광각/중각/협각: 수량 동일, 렌즈 부품만 다름
- 3K: PCB만 다르고 나머지 수량=0 (미입력)
- 따라서: 5700K 중각 기준 + 렌즈 옵션 + PCB 색온도 옵션

ARENA/ARENA S 공통 렌즈 패턴:
- 광각: 리플렉터-더미 + ㄷ브라켓 + 더미커버
- 중각: 리플렉터-중각
- 협각: 리플렉터-더미 + 렌즈-협각 + ㄷ브라켓 + 더미커버
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app
from modules.db_context import get_db
from modules.models import BomHeader, BomItem, BomModelAlias, StockConsumption, Item
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import text

# 렌즈 옵션 부품 패턴 (item_code 기반)
# 광각+협각: 리플렉터-더미, ㄷ브라켓, 더미커버
# 중각: 리플렉터-중각
# 협각: 렌즈-협각
WIDE_NARROW_CODES = {'DR-', 'A-BRKT', 'AS-BRKT', 'MT-A-BRKT', 'MT-AS-BRKT', 'DMCOVER'}
MID_CODES = {'MidR'}
NARROW_ONLY_CODES = {'Lens-Hyup', 'Lens-hyup', 'LENS-HYUP'}


def is_wide_narrow(item_code):
    return any(p in (item_code or '') for p in WIDE_NARROW_CODES)

def is_mid_only(item_code):
    return any(p in (item_code or '') for p in MID_CODES)

def is_narrow_only(item_code):
    return any(p.lower() in (item_code or '').lower() for p in NARROW_ONLY_CODES)

def is_lens_part(item_code):
    return is_wide_narrow(item_code) or is_mid_only(item_code) or is_narrow_only(item_code)


ARENA_MODELS = {
    # base: {5700K 중각 product_code, PCB 5700K code, PCB 3K code}
    'ARENA-400':  {'pcb57': 'PCB-A-72-57',  'pcb30': 'PCB-A-72-30'},
    'ARENA-500':  {'pcb57': 'PCB-A-72-57',  'pcb30': 'PCB-A-72-30'},
    'ARENA-600':  {'pcb57': 'PCB-A-96-57',  'pcb30': 'PCB-A-96-30'},
    'ARENA-800':  {'pcb57': 'PCB-A-96-57',  'pcb30': 'PCB-A-96-30'},
    'ARENA-200S': {'pcb57': 'PCB-AS-24-57', 'pcb30': 'PCB-AS-72-30'},  # 200S 3K는 72구
    'ARENA-300S': {'pcb57': 'PCB-AS-36-57', 'pcb30': 'PCB-AS-36-30'},
    'ARENA-400S': {'pcb57': 'PCB-AS-48-57', 'pcb30': 'PCB-AS-48-30'},
}

# ARENA S 모델의 유리실링도 색온도별로 다름
SEALING_DIFF = {
    'ARENA-200S': {'seal57': 'AS-GSealing-01', 'seal30': 'A-GSealing-01'},
    'ARENA-300S': {'seal57': 'AS-GSealing-01', 'seal30': 'A-GSealing-01'},
    'ARENA-400S': {'seal57': 'AS-GSealing-01', 'seal30': 'A-GSealing-01'},
}


def main():
    with app.app_context():
        with get_db() as db:
            # ===== STEP 1: ARENA 전부 롤백 =====
            print('=== ROLLBACK ARENA ===')
            for bom in db.query(BomHeader).filter(BomHeader.product_code.like('ARENA%')).all():
                for bi in bom.bom_items:
                    if bi.option_filter:
                        bi.option_filter = None
                bom.option_schema = None
                if not bom.is_active:
                    bom.is_active = True
                    bom.note = None

            # product_code 복원
            for base in ARENA_MODELS:
                bom = db.query(BomHeader).filter(BomHeader.product_code == base).first()
                if bom:
                    bom.product_code = f'{base}-중각'
                    bom.product_name = f'{base}-중각'

            # 별칭 삭제
            for a in list(db.query(BomModelAlias).all()):
                bh = db.query(BomHeader).get(a.bom_id)
                if bh and bh.product_code.startswith('ARENA'):
                    db.delete(a)

            db.flush()

            # ===== STEP 2: 엑셀 기준 재구축 =====
            print('=== REBUILD ===')

            for base, info in ARENA_MODELS.items():
                # 중각 5700K = 대표 BOM
                mid_bom = db.query(BomHeader).filter(
                    BomHeader.product_code == f'{base}-중각',
                    BomHeader.is_active == True,
                ).first()
                # 협각 5700K (렌즈 부품 가져오기)
                nar_bom = db.query(BomHeader).filter(
                    BomHeader.product_code == f'{base}-협각',
                    BomHeader.is_active == True,
                ).first()

                if not mid_bom or not nar_bom:
                    print(f'  SKIP {base}')
                    continue

                tid = mid_bom.id
                mid_items = {bi.item_code: bi for bi in mid_bom.bom_items}
                nar_items = {bi.item_code: bi for bi in nar_bom.bom_items}

                # 2-1. 중각 부품 중 렌즈 관련 → option_filter 태깅
                for bi in mid_bom.bom_items:
                    if is_mid_only(bi.item_code):
                        bi.option_filter = json.dumps({'렌즈': '중각'}, ensure_ascii=False)
                    elif bi.item_code == info['pcb57']:
                        bi.option_filter = json.dumps({'색온도': '5700K'}, ensure_ascii=False)
                    elif base in SEALING_DIFF and bi.item_code == SEALING_DIFF[base]['seal57']:
                        bi.option_filter = json.dumps({'색온도': '5700K'}, ensure_ascii=False)

                # 2-2. 협각 부품에서 렌즈 관련 추가
                added = set(mid_items.keys())
                for code, bi in nar_items.items():
                    if code in added:
                        continue
                    if is_narrow_only(code):
                        # 렌즈-협각 → 협각만
                        db.add(BomItem(
                            bom_id=tid, item_code=bi.item_code, item_id=bi.item_id,
                            item_name=bi.item_name, item_spec=bi.item_spec,
                            quantity=bi.quantity, unit_price=bi.unit_price,
                            supplier=bi.supplier, unit=bi.unit,
                            option_filter=json.dumps({'렌즈': '협각'}, ensure_ascii=False),
                        ))
                        added.add(code)
                    elif is_wide_narrow(code):
                        # 리플렉터-더미, ㄷ브라켓, 더미커버 → 광각+협각
                        for lens in ['광각', '협각']:
                            db.add(BomItem(
                                bom_id=tid, item_code=bi.item_code, item_id=bi.item_id,
                                item_name=bi.item_name, item_spec=bi.item_spec,
                                quantity=bi.quantity, unit_price=bi.unit_price,
                                supplier=bi.supplier, unit=bi.unit,
                                option_filter=json.dumps({'렌즈': lens}, ensure_ascii=False),
                            ))
                        added.add(code)

                # 2-3. 3K PCB 추가
                pcb30_item = db.query(Item).filter(Item.icube_item_cd.ilike(info['pcb30'])).first()
                if pcb30_item:
                    db.add(BomItem(
                        bom_id=tid, item_code=info['pcb30'], item_id=pcb30_item.id,
                        item_name=pcb30_item.item_name, quantity=1,
                        option_filter=json.dumps({'색온도': '3K'}, ensure_ascii=False),
                    ))
                else:
                    db.add(BomItem(
                        bom_id=tid, item_code=info['pcb30'], item_name=f'{info["pcb30"]}',
                        quantity=1,
                        option_filter=json.dumps({'색온도': '3K'}, ensure_ascii=False),
                    ))

                # 3K 유리실링 (S모델만)
                if base in SEALING_DIFF:
                    seal30_code = SEALING_DIFF[base]['seal30']
                    seal_item = db.query(Item).filter(Item.icube_item_cd.ilike(seal30_code)).first()
                    db.add(BomItem(
                        bom_id=tid, item_code=seal30_code,
                        item_id=seal_item.id if seal_item else None,
                        item_name=seal_item.item_name if seal_item else seal30_code,
                        quantity=1,
                        option_filter=json.dumps({'색온도': '3K'}, ensure_ascii=False),
                    ))

                # 2-4. 나머지 변형 비활성화 + 소진 이관
                for suffix in ['-광각', '-협각', '-광각(3K)', '-중각(3K)', '-협각(3K)', '-증각', '-증각(3K)']:
                    other = db.query(BomHeader).filter(
                        BomHeader.product_code == f'{base}{suffix}',
                        BomHeader.is_active == True,
                    ).first()
                    if other and other.id != tid:
                        db.query(StockConsumption).filter(
                            StockConsumption.bom_id == other.id
                        ).update({'bom_id': tid})
                        other.is_active = False
                        other.note = f'-> {base} superbom'

                # 2-5. 이름 변경 + schema
                mid_bom.product_code = base
                mid_bom.product_name = base
                db.flush()
                mid_bom.option_schema = rebuild_option_schema(db, tid)

                common = sum(1 for bi in db.query(BomItem).filter(BomItem.bom_id == tid) if not bi.option_filter)
                opt = sum(1 for bi in db.query(BomItem).filter(BomItem.bom_id == tid) if bi.option_filter)
                print(f'  {base}: {common} common + {opt} option  schema={mid_bom.option_schema}')

            # ===== STEP 3: 별칭 재등록 =====
            print('\n=== ALIASES ===')
            from sqlalchemy import distinct
            from modules.models import ContractItem
            import re
            bom_codes = {b.product_code: b.id for b in db.query(BomHeader).filter(BomHeader.is_active == True).all()}
            model_names = [r[0] for r in db.query(distinct(ContractItem.model_name)).filter(
                ContractItem.model_name.isnot(None), ContractItem.model_name != '').all()]
            for model in model_names:
                if not model.startswith('ARENA'):
                    continue
                if model in bom_codes:
                    if not db.query(BomModelAlias).filter(BomModelAlias.alias_name == model).first():
                        db.add(BomModelAlias(bom_id=bom_codes[model], alias_name=model, alias_type='exact', created_by='system'))
                    continue
                for pat, repl in [(r'\(M\)', ''), (r'\(D\)', ''), (r'\(X\)', ''), (r'\(3000K\)$', '')]:
                    s = re.sub(pat, repl, model)
                    if s != model and s in bom_codes:
                        if not db.query(BomModelAlias).filter(BomModelAlias.alias_name == model).first():
                            db.add(BomModelAlias(bom_id=bom_codes[s], alias_name=model, alias_type='option', created_by='system'))
                        break

            db.commit()
            active = db.query(BomHeader).filter(BomHeader.is_active == True, BomHeader.product_code.like('ARENA%')).count()
            aliases = db.query(BomModelAlias).join(BomHeader).filter(BomHeader.product_code.like('ARENA%')).count()
            print(f'\nDONE: Active ARENA={active}, ARENA aliases={aliases}')


if __name__ == '__main__':
    main()
