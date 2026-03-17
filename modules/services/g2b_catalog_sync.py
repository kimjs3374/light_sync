import os
import re
import logging
import datetime
import requests
from modules.models import ProductCatalog

logger = logging.getLogger(__name__)

# 나라장터 종합쇼핑몰 API (/at/ 경로 필수)
G2B_BASE_URL = 'https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService'

MAS_ENDPOINT = f'{G2B_BASE_URL}/getMASCntrctPrdctInfoList'
THPTY_ENDPOINT = f'{G2B_BASE_URL}/getThptyUcntrctPrdctInfoList'


def _build_api_url(endpoint):
    """data.go.kr serviceKey 인코딩 문제 대응: URL에 직접 삽입"""
    import urllib.parse
    key = os.environ.get('DATA_GO_KR_API_KEY', '')
    corp_nm = os.environ.get('G2B_CORP_NAME', '매그나텍')
    params = {
        'numOfRows': '300',
        'pageNo': '1',
        'type': 'json',
        'cntrctCorpNm': corp_nm,
    }
    qs = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items())
    # serviceKey는 Decoding 키 그대로 전달 (requests가 ==를 재인코딩하는 문제 회피)
    return f'{endpoint}?serviceKey={key}&{qs}'


def _fetch_g2b_items(endpoint, method_label):
    """나라장터 API 호출 -> 아이템 리스트 반환"""
    url = _build_api_url(endpoint)
    try:
        resp = requests.get(url, timeout=60)

        # data.go.kr 게이트웨이 에러 (일일 트래픽 초과, 서비스 점검 등)
        if resp.status_code != 200:
            logger.error(f"[G2B] {method_label} API HTTP {resp.status_code}: {resp.text[:200]}")
            return []

        # XML 에러 응답 체크 (data.go.kr은 에러 시 XML 반환하기도 함)
        content_type = resp.headers.get('content-type', '')
        if 'json' not in content_type and 'xml' in content_type:
            logger.error(f"[G2B] {method_label} API 에러 응답: {resp.text[:300]}")
            return []

        data = resp.json()

        # data.go.kr 에러코드 체크
        header = data.get('response', {}).get('header', {})
        result_code = header.get('resultCode', '00')
        if result_code != '00':
            result_msg = header.get('resultMsg', 'Unknown')
            logger.error(f"[G2B] {method_label} API 에러: {result_code} - {result_msg}")
            return []

        body = data.get('response', {}).get('body', {})
        items = body.get('items', [])
        if isinstance(items, dict):
            items = items.get('item', [])
        if not isinstance(items, list):
            items = [items] if items else []

        logger.info(f"[G2B] {method_label} API 조회: {len(items)}건")
        return items
    except requests.RequestException as e:
        logger.error(f"[G2B] {method_label} API 오류: {e}")
        return []


def _parse_date(date_str):
    """'YYYYMMDD' 또는 'YYYY-MM-DD' -> date 객체"""
    if not date_str:
        return None
    try:
        cleaned = str(date_str).replace('-', '')
        return datetime.date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    except (ValueError, IndexError):
        return None


def _parse_price(price_val):
    """가격 문자열 -> int 또는 None"""
    if price_val is None:
        return None
    try:
        price = int(float(str(price_val)))
        return price if price > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_spec_name(spec_nm):
    """prdctSpecNm 쉼표 분리 -> (품목명, 제조사, 모델명, 규격)"""
    parts = [p.strip() for p in (spec_nm or '').split(',')]
    return {
        'item_name': parts[0] if len(parts) > 0 else None,
        'manufacturer': parts[1] if len(parts) > 1 else None,
        'model_name': parts[2] if len(parts) > 2 else None,
        'spec': ', '.join(parts[3:]) if len(parts) > 3 else None,
    }


def sync_from_g2b(db):
    """
    나라장터 API에서 제품 목록을 가져와 DB에 Upsert.
    - price_source='manual'인 기존 수기 단가는 덮어쓰지 않음
    - prdct_idnt_no 기준 중복 제거

    Returns:
        dict: {'created': int, 'updated': int, 'errors': int}
    """
    now = datetime.datetime.now()
    created = 0
    updated = 0
    errors = 0

    mas_items = _fetch_g2b_items(MAS_ENDPOINT, 'MAS')
    thpty_items = _fetch_g2b_items(THPTY_ENDPOINT, '제3자단가')

    # prdct_idnt_no 기준 중복 제거 (MAS 우선)
    merged = {}
    for item in mas_items:
        idnt_no = str(item.get('prdctIdntNo', '')).strip()
        if idnt_no:
            merged[idnt_no] = (item, 'MAS')
    for item in thpty_items:
        idnt_no = str(item.get('prdctIdntNo', '')).strip()
        if idnt_no and idnt_no not in merged:
            merged[idnt_no] = (item, '제3자단가')

    for idnt_no, (item, contract_method) in merged.items():
        try:
            existing = db.query(ProductCatalog).filter_by(
                prdct_idnt_no=idnt_no
            ).first()

            api_price = _parse_price(item.get('cntrctPrceAmt'))
            krn_nm = str(item.get('prdctSpecNm', '')).strip()
            parsed = _parse_spec_name(krn_nm)
            clsfc_no = str(item.get('prdctClsfcNoNm', '')).strip() or None
            dtl_nm = str(item.get('dtlPrdctNm', '') or krn_nm).strip() or None
            unit_val = str(item.get('prdctUnit', '')).strip() or None
            cntrct_no = str(item.get('cntrctRefNo', '')).strip() or None
            bgn_date = _parse_date(item.get('cntrctBgnDt'))
            end_date = _parse_date(item.get('cntrctEndDt'))

            if existing:
                existing.krn_prdct_nm = krn_nm or existing.krn_prdct_nm
                existing.item_name = parsed['item_name'] or existing.item_name
                existing.manufacturer = parsed['manufacturer'] or existing.manufacturer
                existing.model_name = parsed['model_name'] or existing.model_name
                existing.spec = parsed['spec'] or existing.spec
                existing.prdct_clsfc_no = clsfc_no or existing.prdct_clsfc_no
                existing.dtl_prdct_nm = dtl_nm or existing.dtl_prdct_nm
                existing.unit = unit_val or existing.unit
                existing.g2b_contract_method = contract_method
                existing.g2b_cntrct_no = cntrct_no or existing.g2b_cntrct_no
                existing.cntrct_bgn_date = bgn_date or existing.cntrct_bgn_date
                existing.cntrct_end_date = end_date or existing.cntrct_end_date
                existing.last_synced_at = now

                # 수기 단가 보존
                if existing.price_source not in ('manual', 'quote'):
                    existing.unit_price = api_price
                    existing.price_source = 'api'

                updated += 1
            else:
                new_item = ProductCatalog(
                    prdct_idnt_no=idnt_no,
                    krn_prdct_nm=krn_nm,
                    item_name=parsed['item_name'],
                    manufacturer=parsed['manufacturer'],
                    model_name=parsed['model_name'],
                    spec=parsed['spec'],
                    prdct_clsfc_no=clsfc_no,
                    dtl_prdct_nm=dtl_nm,
                    unit=unit_val,
                    unit_price=api_price,
                    price_source='api',
                    g2b_contract_method=contract_method,
                    g2b_cntrct_no=cntrct_no,
                    cntrct_bgn_date=bgn_date,
                    cntrct_end_date=end_date,
                    last_synced_at=now,
                )
                db.add(new_item)
                created += 1

        except Exception as e:
            logger.error(f"[G2B] Upsert 오류 ({idnt_no}): {e}")
            errors += 1

    return {'created': created, 'updated': updated, 'errors': errors}


# --- 매칭 함수 ---

def _normalize_name(name):
    """매칭용 문자열 정규화: 소문자, 공백/특수문자 제거"""
    if not name:
        return ''
    s = str(name).strip().lower()
    s = re.sub(r'[\(\[\{].*?[\)\]\}]', '', s)
    s = re.sub(r'[\s\-_/.,·]', '', s)
    return s


def get_catalog_price_map(db):
    """
    전체 카탈로그의 정규화된 이름 -> unit_price 매핑 딕셔너리 생성.
    model_name 우선 매칭, fallback으로 krn_prdct_nm 전체 매칭.
    """
    catalogs = db.query(ProductCatalog).all()
    price_map = {}
    for cat in catalogs:
        entry = {
            'unit_price': cat.unit_price,
            'catalog_name': cat.krn_prdct_nm,
            'model_name': cat.model_name,
        }
        # model_name 기반 매칭 (우선)
        if cat.model_name:
            norm_model = _normalize_name(cat.model_name)
            if norm_model:
                price_map[norm_model] = entry
        # krn_prdct_nm 전체 기반 매칭 (fallback)
        norm_full = _normalize_name(cat.krn_prdct_nm)
        if norm_full:
            price_map[norm_full] = entry
    return price_map


def match_from_price_map(price_map, model_name):
    """
    사전 로드된 price_map에서 model_name 매칭.
    """
    if not model_name:
        return {'unit_price': None, 'matched': False, 'catalog_name': None}

    norm = _normalize_name(model_name)
    if not norm:
        return {'unit_price': None, 'matched': False, 'catalog_name': None}

    # 정확 매칭
    if norm in price_map:
        entry = price_map[norm]
        return {
            'unit_price': entry['unit_price'],
            'matched': True,
            'catalog_name': entry['catalog_name'],
        }

    # 부분 포함 매칭
    for cat_norm, entry in price_map.items():
        if norm in cat_norm or cat_norm in norm:
            return {
                'unit_price': entry['unit_price'],
                'matched': True,
                'catalog_name': entry['catalog_name'],
            }

    return {'unit_price': None, 'matched': False, 'catalog_name': None}
