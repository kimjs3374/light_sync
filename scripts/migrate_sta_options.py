"""STA BOM 옵션 정리: 바이저별 반사판/프론트커버 + 렌즈 option_filter

1. 구형 반사판(바이저 구분 없음) → 바이저별 3세트로 교체
2. 55도 렌즈 추가
3. 렌즈 + 바이저 option_filter 태깅
4. option_schema 생성
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app
from modules.db_context import get_db
from modules.models import BomHeader, BomItem, Item
from modules.services.bom_actions import rebuild_option_schema
from sqlalchemy import text

# 바이저별 부품 매핑 (엑셀 기준)
# STA S (400~800): 600 시리즈 반사판 + S용 프론트커버
STA_S_VISOR_PARTS = {
    '420': {
        'main_ref': 'MT-STA600-MR420',
        'lsr': 'MT-STA1500600-LSR420',
        'rsr': 'MT-STA1500600-RSR420',
        'ftcover': 'MT-STA-FTCOVER06',
    },
    '480': {
        'main_ref': 'MT-STA600-MR480',
        'lsr': 'MT-STA1500600-LSR480',
        'rsr': 'MT-STA1500600-RSR480',
        'ftcover': 'MT-STA-FTCOVER03',
    },
    '540': {
        'main_ref': 'MT-STA600-MR540',
        'lsr': 'MT-STA1500600-LSR540',
        'rsr': 'MT-STA1500600-RSR540',
        'ftcover': 'MT-STA-FTCOVER05',
    },
}

# STA (1000~1500): 1500 시리즈 반사판 + 1500용 프론트커버
STA_VISOR_PARTS = {
    '420': {
        'main_ref': 'MT-STA1500-MR420',
        'lsr': 'MT-STA1500600-LSR420',
        'rsr': 'MT-STA1500600-RSR420',
        'ftcover': 'MT-STA-FTCOVER01',
    },
    '480': {
        'main_ref': 'MT-STA1500-MR480',
        'lsr': 'MT-STA1500600-LSR480',
        'rsr': 'MT-STA1500600-RSR480',
        'ftcover': 'MT-STA-FTCOVER02',
    },
    '540': {
        'main_ref': 'MT-STA1500-MR540',
        'lsr': 'MT-STA1500600-LSR540',
        'rsr': 'MT-STA1500600-RSR540',
        'ftcover': 'MT-STA-FTCOVER04',
    },
}

# 구형 반사판/프론트커버 (삭제 대상)
OLD_REFLECTORS_S = ['MT-STA S-MR', 'MT-STA S-LSR', 'MT-STA S-RSR']
OLD_REFLECTORS = ['MT-STA-MR', 'MT-STA-LSR', 'MT-STA-RSR']
OLD_FTCOVERS = ['MT-STA-FTCOVER01']  # STA S에 잘못 들어간 것

# 렌즈 매핑
LENS_MAP = {
    'MT-STALens-20': '20도',
    'MT-STALens-35': '30도',
    'MT-STALens-55': '55도',
}

STA_S_MODELS = ['STA-400', 'STA-500', 'STA-600', 'STA-800']
STA_MODELS = ['STA-1000', 'STA-1200', 'STA-1500', 'STA(H)-1500']


def find_item(db, item_code):
    """품목 마스터에서 Item 찾기 (대소문자 무시)."""
    return db.query(Item).filter(Item.icube_item_cd.ilike(item_code)).first()


def safe_delete_bom_item(db, bi):
    """FK 참조 해제 후 BomItem 삭제."""
    db.execute(text('UPDATE light_sync.material_orders SET bom_item_id = NULL WHERE bom_item_id = :id'), {'id': bi.id})
    db.execute(text('UPDATE light_sync.stock_consumption_items SET bom_item_id = NULL WHERE bom_item_id = :id'), {'id': bi.id})
    db.delete(bi)


def add_bom_item(db, bom_id, item_code, item_name, qty, option_filter_dict=None):
    """BomItem 추가."""
    item = find_item(db, item_code)
    of = json.dumps(option_filter_dict, ensure_ascii=False) if option_filter_dict else None
    db.add(BomItem(
        bom_id=bom_id,
        item_code=item_code,
        item_id=item.id if item else None,
        item_name=item_name or (item.item_name if item else item_code),
        item_spec=item.item_spec if item else None,
        quantity=qty,
        unit_price=item.last_unit_price if item else 0,
        supplier='',
        unit='',
        option_filter=of,
    ))


def process_model(db, model, visor_parts, old_refs, is_sta_s):
    """단일 STA 모델 처리."""
    bom = db.query(BomHeader).filter(
        BomHeader.product_code == model, BomHeader.is_active == True
    ).first()
    if not bom:
        print(f'  SKIP {model}: not found')
        return

    bom_id = bom.id
    existing_codes = {(bi.item_code or '').upper(): bi for bi in bom.bom_items}

    # 1. 구형 반사판/프론트커버 삭제
    deleted = []
    for old_code in old_refs:
        key = old_code.upper()
        if key in existing_codes:
            safe_delete_bom_item(db, existing_codes[key])
            deleted.append(old_code)

    # STA S에 잘못 들어간 프론트커버도 삭제
    if is_sta_s:
        for fc in OLD_FTCOVERS:
            key = fc.upper()
            if key in existing_codes:
                safe_delete_bom_item(db, existing_codes[key])
                deleted.append(fc)
        # STA-400 추가 교체: 하우징/림/백커버가 잘못된 경우 (엑셀 비교 결과)
        wrong_parts = {
            'MT-STA-H-01': 'MT-STA-H-02',
            'MT-STA-RIM-01': 'MT-STA-RIM-02(600W)',
            'MT-STA-BACKCOVER1500': 'MT-STA-BACKCOVER600',
        }
        if model == 'STA-400':
            for wrong, correct in wrong_parts.items():
                wkey = wrong.upper()
                if wkey in existing_codes and correct.upper() not in existing_codes:
                    safe_delete_bom_item(db, existing_codes[wkey])
                    item = find_item(db, correct)
                    if item:
                        add_bom_item(db, bom_id, correct, item.item_name, 1)
                        deleted.append(f'{wrong}->{correct}')

    db.flush()

    # 2. 바이저별 부품 추가
    added_visor = 0
    for visor_len, parts in visor_parts.items():
        vf = {'바이저': visor_len}
        for role, item_code in parts.items():
            key = item_code.upper()
            # 이미 있으면 option_filter만 태깅
            existing = None
            for bi in db.query(BomItem).filter(BomItem.bom_id == bom_id).all():
                if (bi.item_code or '').upper() == key:
                    existing = bi
                    break

            if existing:
                existing.option_filter = json.dumps(vf, ensure_ascii=False)
            else:
                item = find_item(db, item_code)
                name = item.item_name if item else item_code
                add_bom_item(db, bom_id, item_code, name, 1, vf)
                added_visor += 1

    # 3. 렌즈 option_filter 태깅 + 55도 추가
    added_lens = 0
    for lens_code, lens_val in LENS_MAP.items():
        lf = {'렌즈': lens_val}
        key = lens_code.upper()

        existing = None
        for bi in db.query(BomItem).filter(BomItem.bom_id == bom_id).all():
            if (bi.item_code or '').upper() == key:
                existing = bi
                break

        if existing:
            existing.option_filter = json.dumps(lf, ensure_ascii=False)
        else:
            item = find_item(db, lens_code)
            # 수량: STA S=18, STA=27
            qty = 18 if is_sta_s else 27
            name = item.item_name if item else lens_code
            add_bom_item(db, bom_id, lens_code, name, qty, lf)
            added_lens += 1

    # 4. 히트파이프 L type 추가 (엑셀에 있고 DB에 없는 경우)
    hp_code = 'MT-STA-HP-01'
    if hp_code.upper() not in {(bi.item_code or '').upper() for bi in db.query(BomItem).filter(BomItem.bom_id == bom_id).all()}:
        item = find_item(db, hp_code)
        if item:
            qty = 24 if is_sta_s else 36
            add_bom_item(db, bom_id, hp_code, item.item_name, qty)

    # 5. option_schema 재생성
    db.flush()
    bom.option_schema = rebuild_option_schema(db, bom_id)

    total = db.query(BomItem).filter(BomItem.bom_id == bom_id).count()
    opt = db.query(BomItem).filter(BomItem.bom_id == bom_id, BomItem.option_filter.isnot(None)).count()
    print(f'  {model}: del={deleted} +visor={added_visor} +lens={added_lens} total={total}({total-opt}common,{opt}opt) schema={bom.option_schema}')


def main():
    with app.app_context():
        with get_db() as db:
            print('=== STA S (400~800) ===')
            for model in STA_S_MODELS:
                process_model(db, model, STA_S_VISOR_PARTS, OLD_REFLECTORS_S, is_sta_s=True)

            print('\n=== STA (1000~1500) ===')
            for model in STA_MODELS:
                process_model(db, model, STA_VISOR_PARTS, OLD_REFLECTORS, is_sta_s=False)

            db.commit()
            print('\nDONE')


if __name__ == '__main__':
    main()
