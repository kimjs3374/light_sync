"""
나라장터 특정품목조달내역 동기화 서비스
- 엔드포인트: getSpcifyPrdlstPrcureInfoList
- 핵심 트릭: inqryPrdctDiv=3 + prdctIdntNoNm=매그나텍 → 품목코드 순환 불필요
- 일일 동기화 + 초기 벌크 동기화 지원
"""
import os
import logging
import datetime
import urllib.parse

import requests

from modules.models import G2bProcurement

logger = logging.getLogger(__name__)

G2B_BASE_URL = 'https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService'
PROCUREMENT_ENDPOINT = f'{G2B_BASE_URL}/getSpcifyPrdlstPrcureInfoList'

# 매그나텍 사업자등록번호
BIZNO = os.environ.get('G2B_BIZNO', '4088168519')
CORP_KEYWORD = os.environ.get('G2B_CORP_NAME', '매그나텍')

# 물품규격명에 '매그나텍'이 안 들어가는 세부품명 (세부품명+업체명 조합으로 별도 검색)
EXTRA_PRODUCT_NAMES = ['스포츠조명기구']


def _parse_date(date_str):
    """'YYYYMMDD' 또는 'YYYY-MM-DD' -> date 객체"""
    if not date_str:
        return None
    try:
        cleaned = str(date_str).replace('-', '').strip()
        if len(cleaned) < 8:
            return None
        return datetime.date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    except (ValueError, IndexError):
        return None


def _parse_int(val):
    """숫자 문자열 -> int 또는 None"""
    if val is None or val == '':
        return None
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return None


def _build_url(bgn_date, end_date, page_no=1, num_of_rows=100, inqry_div='1',
               prdct_div='3', search_keyword=None, search_product=None):
    """
    API URL 생성.
    prdct_div=3: 물품규격명 검색 (search_keyword=매그나텍)
    prdct_div=2: 세부품명 검색 (search_product=스포츠조명기구)
    """
    key = os.environ.get('DATA_GO_KR_API_KEY', '')
    params = {
        'numOfRows': str(num_of_rows),
        'pageNo': str(page_no),
        'type': 'json',
        'inqryDiv': inqry_div,
        'inqryBgnDate': bgn_date,
        'inqryEndDate': end_date,
        'inqryPrdctDiv': prdct_div,
        'fnlCntrctDlvrReqChgOrdYn': 'Y',
    }
    if prdct_div == '3':
        params['prdctIdntNoNm'] = search_keyword or CORP_KEYWORD
        params['bizno'] = BIZNO
    elif prdct_div == '2':
        params['dtilPrdctClsfcNoNm'] = search_product or ''
        params['corpNm'] = CORP_KEYWORD

    qs = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items())
    return f'{PROCUREMENT_ENDPOINT}?serviceKey={key}&{qs}'


def _fetch_page(bgn_date, end_date, page_no=1, num_of_rows=100, inqry_div='1', **kwargs):
    """단일 페이지 API 호출"""
    url = _build_url(bgn_date, end_date, page_no, num_of_rows, inqry_div, **kwargs)
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200:
            logger.error(f"[G2B조달] API HTTP {resp.status_code}: {resp.text[:200]}")
            return [], 0

        content_type = resp.headers.get('content-type', '')
        if 'json' not in content_type and 'xml' in content_type:
            logger.error(f"[G2B조달] API XML 에러: {resp.text[:300]}")
            return [], 0

        data = resp.json()
        header = data.get('response', {}).get('header', {})
        if header.get('resultCode', '00') != '00':
            logger.error(f"[G2B조달] API 에러: {header.get('resultCode')} - {header.get('resultMsg')}")
            return [], 0

        body = data.get('response', {}).get('body', {})
        total_count = int(body.get('totalCount', 0))
        items = body.get('items', [])

        # items가 dict인 경우 (단건)
        if isinstance(items, dict):
            items = items.get('item', [])
        if not isinstance(items, list):
            items = [items] if items else []

        return items, total_count

    except requests.RequestException as e:
        logger.error(f"[G2B조달] API 요청 오류: {e}")
        return [], 0


def _fetch_all(bgn_date, end_date, inqry_div='1', **kwargs):
    """전체 데이터 페이지네이션 처리"""
    all_items = []
    page = 1
    num_of_rows = 100

    while True:
        items, total = _fetch_page(bgn_date, end_date, page, num_of_rows, inqry_div, **kwargs)
        all_items.extend(items)

        if not items or len(all_items) >= total:
            break
        page += 1

    logger.info(f"[G2B조달] {bgn_date}~{end_date} 조회: {len(all_items)}건")
    return all_items


def _upsert_item(db, item):
    """단건 Upsert (cntrct_dlvr_req_no + prdct_sno + chg_ord 기준)"""
    req_no = str(item.get('cntrctDlvrReqNo', '')).strip()
    prdct_sno = str(item.get('prdctSno', '1')).strip() or '1'
    chg_ord = str(item.get('cntrctDlvrReqChgOrd', '00')).strip() or '00'

    if not req_no:
        return 'error'

    existing = db.query(G2bProcurement).filter_by(
        cntrct_dlvr_req_no=req_no,
        prdct_sno=prdct_sno,
        cntrct_dlvr_req_chg_ord=chg_ord,
    ).first()

    fields = {
        'prcrmnt_div_nm': str(item.get('prcrmntDivNm', '')).strip() or None,
        'cntrct_div_nm': str(item.get('cntrctDivNm', '')).strip() or None,
        'cntrct_dlvr_div_nm': str(item.get('cntrctDlvrDivNm', '')).strip() or None,
        'cntrct_dlvr_req_date': _parse_date(item.get('cntrctDlvrReqDate')),
        'cntrct_dlvr_req_nm': str(item.get('cntrctDlvrReqNm', '')).strip() or None,
        'cntrct_mthd_nm': str(item.get('cntrctMthdNm', '')).strip() or None,
        'dminstt_nm': str(item.get('dminsttNm', '')).strip() or None,
        'dminstt_cd': str(item.get('dminsttCd', '')).strip() or None,
        'dminstt_rgn_nm': str(item.get('dminsttRgnNm', '')).strip() or None,
        'dmnd_instt_div_nm': str(item.get('dmndInsttDivNm', '')).strip() or None,
        'prdct_clsfc_no': str(item.get('prdctClsfcNo', '')).strip() or None,
        'prdct_clsfc_no_nm': str(item.get('prdctClsfcNoNm', '')).strip() or None,
        'dtil_prdct_clsfc_no': str(item.get('dtilPrdctClsfcNo', '')).strip() or None,
        'dtil_prdct_clsfc_no_nm': str(item.get('dtilPrdctClsfcNoNm', '')).strip() or None,
        'prdct_idnt_no': str(item.get('prdctIdntNo', '')).strip() or None,
        'prdct_idnt_no_nm': str(item.get('prdctIdntNoNm', '')).strip() or None,
        'prdct_uprc': _parse_int(item.get('prdctUprc')),
        'prdct_qty': _parse_int(item.get('prdctQty')),
        'prdct_unit': str(item.get('prdctUnit', '')).strip() or None,
        'prdct_amt': _parse_int(item.get('prdctAmt')),
        'corp_nm': str(item.get('corpNm', '')).strip() or None,
        'bizno': str(item.get('bizno', '')).strip() or None,
        'dlvr_plce_nm': str(item.get('dlvrPlceNm', '')).strip() or None,
        'dlvr_tmlmt_date': _parse_date(item.get('dlvrTmlmtDate')),
        'dlvry_cndtn_nm': str(item.get('dlvryCndtnNm', '')).strip() or None,
        'fnl_cntrct_dlvr_req_chg_ord_yn': str(item.get('fnlCntrctDlvrReqChgOrdYn', '')).strip() or None,
        'mas_yn': str(item.get('masYn', '')).strip() or None,
        'uprc_cntrct_no': str(item.get('uprcCntrctNo', '')).strip() or None,
        'intl_cntrct_dlvr_req_date': _parse_date(item.get('IntlCntrctDlvrReqDate')),
        'exclc_prodct_yn': str(item.get('exclcProdctYn', '')).strip() or None,
    }

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        return 'updated'
    else:
        new_record = G2bProcurement(
            cntrct_dlvr_req_no=req_no,
            prdct_sno=prdct_sno,
            cntrct_dlvr_req_chg_ord=chg_ord,
            **fields,
        )
        db.add(new_record)
        return 'created'


def _upsert_items(db, items):
    """아이템 리스트 일괄 upsert, 결과 카운트 반환"""
    created, updated, errors = 0, 0, 0
    for item in items:
        try:
            result = _upsert_item(db, item)
            if result == 'created':
                created += 1
            elif result == 'updated':
                updated += 1
            else:
                errors += 1
        except Exception as e:
            logger.error(f"[G2B조달] Upsert 오류: {e}")
            errors += 1
    return created, updated, errors


def _cleanup_non_final(db):
    """동일 계약+품목에서 비최종 변경차수 레코드 삭제"""
    from sqlalchemy import func
    subq = db.query(
        G2bProcurement.cntrct_dlvr_req_no,
        G2bProcurement.prdct_sno,
        func.max(G2bProcurement.cntrct_dlvr_req_chg_ord).label('max_chg')
    ).group_by(
        G2bProcurement.cntrct_dlvr_req_no,
        G2bProcurement.prdct_sno
    ).subquery()

    non_final = db.query(G2bProcurement).join(
        subq,
        (G2bProcurement.cntrct_dlvr_req_no == subq.c.cntrct_dlvr_req_no) &
        (G2bProcurement.prdct_sno == subq.c.prdct_sno)
    ).filter(
        G2bProcurement.cntrct_dlvr_req_chg_ord < subq.c.max_chg
    ).all()

    count = len(non_final)
    for r in non_final:
        db.delete(r)
    if count:
        logger.info(f"[G2B조달] 비최종 변경차수 {count}건 정리")
    return count


def sync_daily(db):
    """
    일일 동기화: 전일 계약/납품요구건 조회 후 DB Upsert.
    1) 물품규격명=매그나텍 검색 (기본)
    2) 세부품명별 추가 검색 (스포츠조명기구 등 규격명에 매그나텍이 없는 품목)
    """
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y%m%d')
    today = datetime.date.today().strftime('%Y%m%d')

    # 1) 기본: 물품규격명=매그나텍
    all_items = _fetch_all(yesterday, today, inqry_div='1')

    # 2) 추가: 세부품명별 (스포츠조명기구 등)
    for product_nm in EXTRA_PRODUCT_NAMES:
        extra = _fetch_all(yesterday, today, inqry_div='1',
                           prdct_div='2', search_product=product_nm)
        all_items.extend(extra)

    created, updated, errors = _upsert_items(db, all_items)
    cleaned = _cleanup_non_final(db)
    logger.info(f"[G2B조달] 일일동기화 완료: 신규 {created}, 갱신 {updated}, 오류 {errors}, 정리 {cleaned}")
    return {'created': created, 'updated': updated, 'errors': errors, 'total_fetched': len(all_items)}


def sync_bulk(db, start_year=2020, end_year=None):
    """
    초기 벌크 동기화: start_year부터 end_year(또는 현재)까지 12개월 단위로 순환 조회.
    inqryDiv=2 (최초계약납품요구일자 기준) 사용.
    """
    now = datetime.date.today()
    end_date = datetime.date(end_year, 12, 31) if end_year else now
    if end_date > now:
        end_date = now
    total_created, total_updated, total_errors = 0, 0, 0

    current = datetime.date(start_year, 1, 1)

    while current <= end_date:
        # 12개월 단위 (API 제한)
        end = datetime.date(current.year, 12, 31)
        if end > end_date:
            end = now

        bgn_str = current.strftime('%Y%m%d')
        end_str = end.strftime('%Y%m%d')

        logger.info(f"[G2B조달] 벌크동기화: {bgn_str} ~ {end_str}")

        # 기본: 물품규격명=매그나텍
        items = _fetch_all(bgn_str, end_str, inqry_div='2')

        # 추가: 세부품명별 (스포츠조명기구 등)
        for product_nm in EXTRA_PRODUCT_NAMES:
            extra = _fetch_all(bgn_str, end_str, inqry_div='2',
                               prdct_div='2', search_product=product_nm)
            items.extend(extra)

        c, u, e = _upsert_items(db, items)
        total_created += c
        total_updated += u
        total_errors += e

        # 다음 연도로
        current = datetime.date(current.year + 1, 1, 1)

    cleaned = _cleanup_non_final(db)
    logger.info(
        f"[G2B조달] 벌크동기화 완료: 신규 {total_created}, 갱신 {total_updated}, 오류 {total_errors}, 정리 {cleaned}"
    )
    return {
        'created': total_created,
        'updated': total_updated,
        'errors': total_errors,
    }
