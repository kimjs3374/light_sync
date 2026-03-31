"""
나라장터 특정품목조달내역 동기화 서비스
- 엔드포인트: getSpcifyPrdlstPrcureInfoList
- 핵심 트릭: inqryPrdctDiv=3 + prdctIdntNoNm=매그나텍 → 품목코드 순환 불필요
- 일일 동기화 + 초기 벌크 동기화 지원
- 동기화 후 자동 계약 생성 (auto_create_contracts)
"""
import os
import time
import logging
import datetime
import calendar
import urllib.parse

from sqlalchemy import text
from collections import defaultdict

import requests

from modules.models import (
    G2bProcurement, Project, Contract, ContractItem,
    DETAIL_ITEM_OPTIONS, normalize_detail_item,
)

logger = logging.getLogger(__name__)

G2B_BASE_URL = 'https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService'
PROCUREMENT_ENDPOINT = f'{G2B_BASE_URL}/getSpcifyPrdlstPrcureInfoList'

# 매그나텍 사업자등록번호
BIZNO = os.environ.get('G2B_BIZNO', '4088168519')
CORP_KEYWORD = os.environ.get('G2B_CORP_NAME', '매그나텍')

# 매그나텍 품목 매핑: (품명, 세부품명) — API 검색에 둘 다 필요
PRODUCT_MAP = [
    ('투광조명', 'LED투광등기구'),
    ('도로조명설비', 'LED가로등기구'),
    ('거주로조명설비', 'LED보안등기구'),
    ('경관조명', 'LED경관조명기구'),
    ('도로조명설비', 'LED터널용등기구'),
    ('스포츠조명기구', '스포츠조명기구'),
    ('조명타워', '조명타워'),
    ('신재생에너지가로등', '태양광가로등'),
    ('가로등주및부속자재', '철제가로등주'),
    ('가로등주및부속자재', '스테인리스가로등주'),
    ('가로등주및부속자재', '가로등주부속자재'),
]


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


def _build_url(bgn_date, end_date, page_no=1, num_of_rows=999, inqry_div='1',
               clsfc_nm=None, dtil_nm=None):
    """
    API URL 생성.
    inqryPrdctDiv=1 + bizno + corpNm + 품명 + 세부품명 조합으로 검색.
    """
    key = os.environ.get('DATA_GO_KR_API_KEY', '')
    params = {
        'numOfRows': str(num_of_rows),
        'pageNo': str(page_no),
        'type': 'json',
        'inqryDiv': inqry_div,
        'inqryBgnDate': bgn_date,
        'inqryEndDate': end_date,
        'inqryPrdctDiv': '1',
        'fnlCntrctDlvrReqChgOrdYn': 'Y',
        'bizno': BIZNO,
        'corpNm': CORP_KEYWORD,
    }
    if clsfc_nm:
        params['prdctClsfcNoNm'] = clsfc_nm
    if dtil_nm:
        params['dtilPrdctClsfcNoNm'] = dtil_nm

    qs = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items())
    return f'{PROCUREMENT_ENDPOINT}?serviceKey={key}&{qs}'


def _fetch_page(bgn_date, end_date, page_no=1, num_of_rows=999, inqry_div='1', **kwargs):
    """단일 페이지 API 호출 (502/504 시 성공할 때까지 재시도)"""
    url = _build_url(bgn_date, end_date, page_no, num_of_rows, inqry_div, **kwargs)

    for attempt in range(10):
        try:
            resp = requests.get(url, timeout=None)

            # 서버 과부하 재시도 (502, 504)
            if resp.status_code in (502, 504):
                wait = (attempt + 1) * 3
                logger.warning(f"[G2B조달] API HTTP {resp.status_code}, {wait}초 후 재시도 ({attempt+1}/10)")
                time.sleep(wait)
                continue

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

            if isinstance(items, dict):
                items = items.get('item', [])
            if not isinstance(items, list):
                items = [items] if items else []

            return items, total_count

        except requests.RequestException as e:
            wait = (attempt + 1) * 3
            logger.error(f"[G2B조달] API 요청 오류: {e}, {wait}초 후 재시도 ({attempt+1}/10)")
            time.sleep(wait)

    logger.error(f"[G2B조달] API 10회 재시도 실패: {bgn_date}~{end_date}, 다음 건으로 진행")
    return [], 0


def _fetch_all(bgn_date, end_date, inqry_div='1', **kwargs):
    """전체 데이터 페이지네이션 처리"""
    all_items = []
    page = 1
    num_of_rows = 999

    while True:
        items, total = _fetch_page(bgn_date, end_date, page, num_of_rows, inqry_div, **kwargs)
        all_items.extend(items)

        if not items or len(all_items) >= total:
            break
        page += 1

    logger.info(f"[G2B조달] {bgn_date}~{end_date} 조회: {len(all_items)}건")
    time.sleep(1)  # API 연속 호출 과부하 방지
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
    일일 동기화: 마지막 동기화일 ~ 오늘 조회 후 DB Upsert.
    1) 물품규격명=매그나텍 검색 (기본)
    2) 세부품명별 추가 검색 (스포츠조명기구 등 규격명에 매그나텍이 없는 품목)
    """
    from sqlalchemy import func as sa_func
    last_synced = db.query(sa_func.max(G2bProcurement.created_at)).scalar()
    if last_synced:
        since = (last_synced - datetime.timedelta(days=1)).strftime('%Y%m%d')
    else:
        since = (datetime.date.today() - datetime.timedelta(days=30)).strftime('%Y%m%d')
    today = datetime.date.today().strftime('%Y%m%d')
    logger.info(f"[G2B조달] 일일동기화 조회기간: {since} ~ {today}")

    # 품명/세부품명별 순회 조회
    all_items = []
    for clsfc_nm, dtil_nm in PRODUCT_MAP:
        items = _fetch_all(since, today, inqry_div='1',
                           clsfc_nm=clsfc_nm, dtil_nm=dtil_nm)
        all_items.extend(items)

    created, updated, errors = _upsert_items(db, all_items)
    cleaned = _cleanup_non_final(db)
    logger.info(f"[G2B조달] 일일동기화 완료: 신규 {created}, 갱신 {updated}, 오류 {errors}, 정리 {cleaned}")
    return {'created': created, 'updated': updated, 'errors': errors, 'total_fetched': len(all_items)}


def sync_bulk(db, start_year=2020, end_year=None):
    """
    초기 벌크 동기화: start_year부터 end_year(또는 현재)까지 3개월 단위로 순환 조회.
    inqryDiv=1 (계약납품요구일자 기준) 사용.
    """
    now = datetime.date.today()
    end_date = datetime.date(end_year, 12, 31) if end_year else now
    if end_date > now:
        end_date = now
    total_created, total_updated, total_errors = 0, 0, 0

    current = datetime.date(start_year, 1, 1)

    while current <= end_date:
        # 3개월 단위 (API 504 방지)
        month_end = current.month + 2
        year_end = current.year
        if month_end > 12:
            month_end = 12
        last_day = calendar.monthrange(year_end, month_end)[1]
        end = datetime.date(year_end, month_end, last_day)
        if end > end_date:
            end = end_date

        bgn_str = current.strftime('%Y%m%d')
        end_str = end.strftime('%Y%m%d')

        logger.info(f"[G2B조달] 벌크동기화: {bgn_str} ~ {end_str}")

        # 품명/세부품명별 순회 조회
        items = []
        for clsfc_nm, dtil_nm in PRODUCT_MAP:
            fetched = _fetch_all(bgn_str, end_str, inqry_div='1',
                                 clsfc_nm=clsfc_nm, dtil_nm=dtil_nm)
            items.extend(fetched)

        c, u, e = _upsert_items(db, items)
        total_created += c
        total_updated += u
        total_errors += e

        # 다음 3개월로
        next_month = current.month + 3
        next_year = current.year
        if next_month > 12:
            next_month -= 12
            next_year += 1
        current = datetime.date(next_year, next_month, 1)

    cleaned = _cleanup_non_final(db)
    logger.info(
        f"[G2B조달] 벌크동기화 완료: 신규 {total_created}, 갱신 {total_updated}, 오류 {total_errors}, 정리 {cleaned}"
    )
    return {
        'created': total_created,
        'updated': total_updated,
        'errors': total_errors,
    }


def auto_create_contracts(db, since_date=None):
    """
    G2B 동기화 후 호출: 아직 ERP Contract에 연동되지 않은 G2B 건 자동 생성.

    - cntrct_dlvr_req_no 기준 그룹핑
    - 이미 Contract.g2b_contract_no로 연결된 건은 skip
    - 취소건(prdct_amt=0 AND prdct_qty=0) 제외
    - ★ 계약일/납기 기준 6개월 컷오프 (과거 건 유입 완전 차단)
    - ★ 계약일/납기가 NULL인 건도 제외
    - Project: status='G2B자동', is_contracted=True, project_no=G-YYYY-NNNN
    """
    # 자동생성 컷오프: 계약일 기준 6개월 이내만 대상 (과거 유령 건 차단)
    cutoff_date = datetime.date.today() - datetime.timedelta(days=180)

    # 1) 이미 연동된 g2b_contract_no 목록 수집
    existing_g2b_nos = set()
    for (no,) in db.query(Contract.g2b_contract_no).filter(
        Contract.g2b_contract_no.isnot(None),
        Contract.g2b_contract_no != '',
    ).all():
        existing_g2b_nos.add(no)

    # 2) 미연동 G2B 건 조회 (계약일 6개월 이내 + NOT NULL만)
    all_g2b = db.query(G2bProcurement).filter(
        G2bProcurement.cntrct_dlvr_req_no.notin_(existing_g2b_nos),
        G2bProcurement.cntrct_dlvr_req_date.isnot(None),
        G2bProcurement.cntrct_dlvr_req_date >= cutoff_date,
    ).order_by(
        G2bProcurement.cntrct_dlvr_req_no,
        G2bProcurement.prdct_sno,
    ).all()

    grouped = defaultdict(list)
    for g in all_g2b:
        grouped[g.cntrct_dlvr_req_no].append(g)

    created_count = 0
    skipped_count = 0

    year = str(datetime.date.today().year)

    for req_no, items in grouped.items():
        # 이미 연동된 건이면 skip
        if req_no in existing_g2b_nos:
            skipped_count += 1
            continue

        # 유효 품목만 필터 (취소건 제외: 금액=0 AND 수량=0)
        valid_items = [
            it for it in items
            if not ((it.prdct_amt or 0) == 0 and (it.prdct_qty or 0) == 0)
        ]
        if not valid_items:
            skipped_count += 1
            continue

        rep = valid_items[0]
        contract_name = rep.cntrct_dlvr_req_nm or f'G2B-{req_no}'
        contract_date = rep.cntrct_dlvr_req_date
        delivery_due_date = rep.dlvr_tmlmt_date

        # 납기가 6개월 이상 경과한 건은 skip (이미 완료된 과거 건)
        if delivery_due_date and delivery_due_date < cutoff_date:
            skipped_count += 1
            logger.info(f"[G2B조달] 납기경과 스킵: {req_no} 납기={delivery_due_date} ({contract_name})")
            continue

        # 납기 NULL이면 계약일+1년 추정, 그마저도 경과했으면 skip
        if not delivery_due_date and contract_date:
            estimated_end = contract_date + datetime.timedelta(days=365)
            if estimated_end < cutoff_date:
                skipped_count += 1
                logger.info(f"[G2B조달] 납기없음+계약일경과 스킵: {req_no} ({contract_name})")
                continue

        # 3) Project 채번 (G-YYYY-NNNN) — 설계번호(YYYY-NNN)와 분리
        prefix = f'G-{year}-'
        last = db.execute(text(
            "SELECT project_no FROM light_sync.projects "
            "WHERE project_no LIKE :prefix "
            "ORDER BY project_no DESC LIMIT 1"
        ), {'prefix': f'{prefix}%'}).scalar()
        seq = int(last.split('-')[-1]) + 1 if last else 1
        project_no = f"{prefix}{seq:04d}"

        new_project = Project(
            project_no=project_no,
            temp_name=contract_name,
            short_name=rep.dminstt_nm or '',
            status='G2B자동',
            is_contracted=True,
            contract_date=contract_date or datetime.date.today(),
            site_address=rep.dlvr_plce_nm or '',
            shipping_address=rep.dlvr_plce_nm or '',
        )
        db.add(new_project)
        db.flush()  # project.id 확보

        # 4) Contract 생성
        new_contract = Contract(
            project_id=new_project.id,
            contract_name=contract_name,
            contract_date=contract_date,
            delivery_due_date=delivery_due_date,
            g2b_contract_no=req_no,
            item_group=DETAIL_ITEM_OPTIONS[0],
        )
        db.add(new_contract)
        db.flush()  # contract.id 확보

        # 5) ContractItem 생성 (품목별)
        for it in valid_items:
            category = normalize_detail_item(
                it.dtil_prdct_clsfc_no_nm,
                default=DETAIL_ITEM_OPTIONS[0],
            )
            db.add(ContractItem(
                contract_id=new_contract.id,
                category=category,
                model_name=it.prdct_idnt_no_nm or it.prdct_clsfc_no_nm or '',
                quantity=it.prdct_qty or 0,
            ))

        created_count += 1

    logger.info(
        f"[G2B조달] 자동계약생성: 신규 {created_count}건, 스킵 {skipped_count}건 "
        f"(컷오프: {cutoff_date} 이후 계약만 대상)"
    )
    return {'created': created_count, 'skipped': skipped_count}
