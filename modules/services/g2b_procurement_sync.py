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

from sqlalchemy import text, func as sa_func
from collections import defaultdict

import requests

from modules.models import (
    G2bProcurement, Project, Contract, ContractItem,
    DETAIL_ITEM_OPTIONS, normalize_detail_item, normalize_org_name,
)

logger = logging.getLogger(__name__)

G2B_BASE_URL = 'https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService'
PROCUREMENT_ENDPOINT = f'{G2B_BASE_URL}/getSpcifyPrdlstPrcureInfoList'

# 매그나텍 사업자등록번호
BIZNO = os.environ.get('G2B_BIZNO', '4088168519')
CORP_KEYWORD = os.environ.get('G2B_CORP_NAME', '매그나텍')

# 매그나텍 품목 매핑: 물품분류번호(prdctClsfcNo) 기반 — 번호 검색이 한글 품명보다 훨씬 빠름
PRODUCT_CLSFC_NOS = [
    '39111611',  # 투광조명
    '39111603',  # 도로조명설비 (LED가로등, LED터널용)
    '39111608',  # 거주로조명설비 (LED보안등)
    '39111605',  # 경관조명
    '39111537',  # 스포츠조명기구
    '39112001',  # 조명타워
    '39111697',  # 신재생에너지가로등
    '39111526',  # 가로등주및부속자재
    '46161585',  # 도로표지병
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
               clsfc_no=None):
    """
    API URL 생성.
    inqryPrdctDiv=1 + bizno + corpNm + 물품분류번호(prdctClsfcNo) 조합으로 검색.
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
    if clsfc_no:
        params['prdctClsfcNo'] = clsfc_no

    qs = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items())
    return f'{PROCUREMENT_ENDPOINT}?serviceKey={urllib.parse.quote(key)}&{qs}'


def _fetch_page(bgn_date, end_date, page_no=1, num_of_rows=999, inqry_div='1', clsfc_no=None):
    """단일 페이지 API 호출 (502/504 시 성공할 때까지 재시도)"""
    url = _build_url(bgn_date, end_date, page_no, num_of_rows, inqry_div, clsfc_no=clsfc_no)

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


def _fetch_all(bgn_date, end_date, inqry_div='1', clsfc_no=None):
    """전체 데이터 페이지네이션 처리"""
    all_items = []
    page = 1
    num_of_rows = 999

    while True:
        items, total = _fetch_page(bgn_date, end_date, page, num_of_rows, inqry_div, clsfc_no=clsfc_no)
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
        'dminstt_nm': normalize_org_name(str(item.get('dminsttNm', '')).strip()) or None,
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
        changed = False
        for k, v in fields.items():
            if getattr(existing, k) != v:
                setattr(existing, k, v)
                changed = True
        return 'updated' if changed else 'unchanged'
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
            elif result == 'error':
                errors += 1
            # 'unchanged'는 카운트하지 않음
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
    last_synced = db.query(sa_func.max(G2bProcurement.created_at)).scalar()
    if last_synced:
        since = (last_synced - datetime.timedelta(days=1)).strftime('%Y%m%d')
    else:
        since = (datetime.date.today() - datetime.timedelta(days=30)).strftime('%Y%m%d')
    today = datetime.date.today().strftime('%Y%m%d')
    logger.info(f"[G2B조달] 일일동기화 조회기간: {since} ~ {today}")

    # 물품분류번호별 순회 조회
    all_items = []
    for clsfc_no in PRODUCT_CLSFC_NOS:
        items = _fetch_all(since, today, inqry_div='1', clsfc_no=clsfc_no)
        all_items.extend(items)

    created, updated, errors = _upsert_items(db, all_items)
    cleaned = _cleanup_non_final(db)
    logger.info(f"[G2B조달] 일일동기화 완료: 신규 {created}, 갱신 {updated}, 오류 {errors}, 정리 {cleaned}")
    return {'created': created, 'updated': updated, 'errors': errors, 'total_fetched': len(all_items)}


def sync_changes(db):
    """활성 계약 대상 변경계약 + 납품기한 변경 감지.

    1) DB에서 미완료(미청구/부분입금) 계약의 최소 계약일 ~ 오늘 범위로 G2B 조회
    2) 기존 chg_ord보다 높은 변경차수 감지 → upsert
    3) G2B 납품기한과 DB 납품기한 비교 → 불일치 시 자동 업데이트
    """
    from modules.models import Contract

    # 활성 계약 중 가장 오래된 계약일
    oldest = db.query(sa_func.min(Contract.contract_date)).filter(
        Contract.g2b_contract_no.isnot(None),
        Contract.payment_status.in_(['미청구', '부분입금']),
    ).scalar()

    if not oldest:
        logger.info("[G2B조달] 변경계약 조회 대상 없음 (활성 계약 0건)")
        return {'created': 0, 'updated': 0, 'errors': 0, 'total_fetched': 0, 'date_fixed': 0}

    since = oldest
    today = datetime.date.today()
    logger.info(f"[G2B조달] 변경계약 조회기간: {since.strftime('%Y%m%d')} ~ {today.strftime('%Y%m%d')}")

    # API 조회기간 최대 12개월 제한 → 12개월 단위로 분할 조회
    all_items = []
    current = since
    while current <= today:
        chunk_end = min(current + datetime.timedelta(days=365), today)
        bgn_str = current.strftime('%Y%m%d')
        end_str = chunk_end.strftime('%Y%m%d')
        for clsfc_no in PRODUCT_CLSFC_NOS:
            items = _fetch_all(bgn_str, end_str, inqry_div='1', clsfc_no=clsfc_no)
            all_items.extend(items)
        current = chunk_end + datetime.timedelta(days=1)

    created, updated, errors = _upsert_items(db, all_items)
    cleaned = _cleanup_non_final(db)

    # 납품기한 변경 감지: G2B 테이블 vs Contract 테이블 비교
    date_fixed = _sync_delivery_dates(db)

    # 변경계약 수량 반영: G2B 최종차수 수량 → ContractItem.quantity → 납품 계획수량
    qty_result = sync_item_quantities(db)

    logger.info(
        f"[G2B조달] 변경계약 동기화 완료: 신규 {created}, 갱신 {updated}, "
        f"오류 {errors}, 정리 {cleaned}, 납품기한수정 {date_fixed}, "
        f"수량수정 {qty_result['qty_fixed']}건(품목 {qty_result['items_fixed']}), "
        f"품목재정렬 {qty_result['reconciled']}건, 계약취소 {qty_result['cancelled']}건, "
        f"수동확인 {qty_result['needs_review']}건"
    )
    return {'created': created, 'updated': updated, 'errors': errors,
            'total_fetched': len(all_items), 'date_fixed': date_fixed,
            'qty_fixed': qty_result['qty_fixed'],
            'items_fixed': qty_result['items_fixed'],
            'reconciled': qty_result['reconciled'],
            'cancelled': qty_result['cancelled'],
            'needs_review': qty_result['needs_review']}


def _sync_delivery_dates(db):
    """G2B 납품기한과 Contract 납품기한 불일치 시 자동 수정"""
    from modules.models import Contract

    rows = db.execute(text('''
        SELECT c.id, c.g2b_contract_no, c.delivery_due_date,
               MAX(g.dlvr_tmlmt_date) as g2b_date, c.contract_name
        FROM light_sync.contracts c
        JOIN light_sync.g2b_procurements g ON g.cntrct_dlvr_req_no = c.g2b_contract_no
        WHERE c.payment_status IN ('미청구', '부분입금')
          AND c.g2b_contract_no IS NOT NULL
        GROUP BY c.id, c.g2b_contract_no, c.delivery_due_date, c.contract_name
        HAVING c.delivery_due_date != MAX(g.dlvr_tmlmt_date)
    ''')).fetchall()

    for r in rows:
        db.execute(text('''
            UPDATE light_sync.contracts
            SET delivery_due_date = :new_date
            WHERE id = :cid
        '''), {'new_date': r.g2b_date, 'cid': r.id})
        logger.info(
            f"[G2B조달] 납품기한 수정: {r.g2b_contract_no} "
            f"{r.delivery_due_date} → {r.g2b_date} ({r.contract_name[:30]})"
        )

    return len(rows)


def _sno_key(row):
    """품목순번 정렬키 — '2'가 '10'보다 앞서도록 숫자 우선 비교"""
    sno = (row.prdct_sno or '').strip()
    return (0, int(sno), '') if sno.isdigit() else (1, 0, sno)


def _final_g2b_items(db, req_no):
    """계약번호의 품목순번별 최종 변경차수 행만 순번순으로 반환.

    _cleanup_non_final()이 비최종 행을 지우지만, 정리 이전 데이터나
    수동 입력분이 남아 있을 수 있어 여기서 한 번 더 최종차수를 고른다.
    """
    best = {}
    for row in db.query(G2bProcurement).filter(
        G2bProcurement.cntrct_dlvr_req_no == req_no
    ).all():
        sno = (row.prdct_sno or '').strip()
        chg = (row.cntrct_dlvr_req_chg_ord or '00').strip()
        cur = best.get(sno)
        if cur is None or chg > (cur.cntrct_dlvr_req_chg_ord or '00').strip():
            best[sno] = row
    return sorted(best.values(), key=_sno_key)


def _model_name_keys(raw):
    """G2B 규격문자열 → ContractItem.model_name 후보 키.

    계약 자동생성 경로가 둘이라 model_name 저장 형태가 다르다:
      - g2b_contract_sync._parse_g2b_item() → 'MTPF-201-5'  (쉼표 3번째 토큰)
      - g2b_procurement_sync.auto_create_contracts() → 원문 전체
    양쪽 모두를 후보로 만들어 정확매칭한다 (ILIKE 부분매칭 금지).
    """
    raw = (raw or '').strip()
    if not raw:
        return set()
    keys = {raw}
    parts = [p.strip() for p in raw.split(',')]
    if len(parts) >= 3:
        keys.add(parts[2])
    elif len(parts) == 2:
        keys.add(parts[1])
    return {k for k in keys if k}


def _match_g2b_items(g2b_rows, contract_items):
    """G2B 품목 ↔ ContractItem 1:1 매칭.

    Returns:
        (pairs, method) — 매칭 실패 시 (None, None)
    """
    # 1) 모델명 정확매칭 — 모든 품목이 1:1로 떨어질 때만 인정
    remaining = list(contract_items)
    pairs = []
    for g in g2b_rows:
        keys = _model_name_keys(g.prdct_idnt_no_nm)
        hits = [ci for ci in remaining if (ci.model_name or '').strip() in keys]
        if len(hits) != 1:
            pairs = None
            break
        pairs.append((g, hits[0]))
        remaining.remove(hits[0])
    if pairs is not None and not remaining:
        return pairs, '모델명'

    # 2) 품목 수가 같으면 순번 위치매칭 (모델명 표기가 바뀐 변경계약 대응)
    if len(g2b_rows) == len(contract_items):
        return list(zip(g2b_rows, contract_items)), '순번'

    # 3) 품목이 추가/삭제된 변경계약 — 자동 판단 불가
    return None, None


def _item_dependency_count(db, contract_item_id):
    """계약품목에 물려 있는 실무 데이터 수 — 0 이어야 삭제해도 안전하다.

    ContractItem 관계는 cascade='all, delete-orphan' 이라 그냥 지우면
    바코드·도면·자재발주·생산공정이 조용히 같이 날아간다.
    """
    row = db.execute(text('''
        SELECT (SELECT count(*) FROM light_sync.contract_barcodes    WHERE contract_item_id = :i)
             + (SELECT count(*) FROM light_sync.drawings             WHERE contract_item_id = :i)
             + (SELECT count(*) FROM light_sync.material_orders      WHERE contract_item_id = :i)
             + (SELECT count(*) FROM light_sync.production_processes WHERE contract_item_id = :i)
             + (SELECT count(*) FROM light_sync.delivery_split_items WHERE contract_item_id = :i) AS n
    '''), {'i': contract_item_id}).first()
    return int(row.n or 0)


def _reconcile_items(db, contract, g2b_rows, contract_items, dry_run):
    """조달내역을 정본으로 계약품목 구성을 맞춘다 (1:1 매칭 실패 시에만 호출).

    - G2B 에만 있는 품목      → ContractItem 신규 생성
    - 양쪽에 있는 품목        → 수량 갱신
    - ERP 에만 남은 품목      → 수량 0. 종속 데이터가 없으면 삭제, 있으면 남기고 보고

    모델명 정확매칭만 사용한다. 여기서 순번 위치매칭까지 하면 모델이 교체된 계약을
    "이름만 바뀐 같은 품목"으로 오인해 엉뚱한 품목의 수량을 덮어쓴다.

    Returns:
        dict: {detail, blocked[]}
    """
    remaining = list(contract_items)
    matched, new_rows = [], []
    for g in g2b_rows:
        keys = _model_name_keys(g.prdct_idnt_no_nm)
        hit = next((ci for ci in remaining if (ci.model_name or '').strip() in keys), None)
        if hit is not None:
            remaining.remove(hit)
            matched.append((g, hit))
        else:
            new_rows.append(g)

    parts, blocked = [], []

    for g, ci in matched:
        new_qty, old_qty = (g.prdct_qty or 0), (ci.quantity or 0)
        label = _s_model(ci.model_name) or ci.category
        # 조달내역에 취소선(수량 0 AND 금액 0)으로 남은 품목은 계약에서 빠진 것 —
        # 모델 교체건에서 옛 모델이 0EA 로 계속 붙어 있는 걸 막는다
        if (g.prdct_qty or 0) == 0 and (g.prdct_amt or 0) == 0:
            deps = _item_dependency_count(db, ci.id)
            if deps == 0:
                parts.append(f"[삭제] {label} {old_qty}EA (조달 취소선)")
                if not dry_run:
                    db.delete(ci)
            elif old_qty:
                parts.append(f"[수량0] {label} {old_qty}→0EA (조달 취소선)")
                blocked.append(
                    f'조달내역에서 취소된 품목 "{label}" 에 실무데이터 {deps}건이 남아 있어 '
                    f'삭제하지 않고 수량만 0 처리 — 확인 필요'
                )
                if not dry_run:
                    ci.quantity = 0
            # old_qty 가 이미 0 이고 종속 데이터가 있으면 더 할 일이 없다.
            # 매 실행마다 같은 알림을 쏘지 않도록 여기서 조용히 넘긴다
            # (이 상태는 감사(audit-g2b-drift)가 품목구성으로 계속 보여준다)
            continue
        if new_qty != old_qty:
            parts.append(f"{label} {old_qty}→{new_qty}EA")
            if not dry_run:
                ci.quantity = new_qty

    for g in new_rows:
        if (g.prdct_qty or 0) == 0 and (g.prdct_amt or 0) == 0:
            continue  # 취소된 품목을 새로 만들 이유가 없다
        model_name = (g.prdct_idnt_no_nm or g.prdct_clsfc_no_nm or '').strip()
        parts.append(f"[신규] {_s_model(model_name)} {g.prdct_qty or 0}EA")
        if not dry_run:
            db.add(ContractItem(
                contract_id=contract.id,
                category=normalize_detail_item(
                    g.dtil_prdct_clsfc_no_nm, default=DETAIL_ITEM_OPTIONS[0]
                ),
                model_name=model_name,
                quantity=g.prdct_qty or 0,
            ))

    for ci in remaining:
        deps = _item_dependency_count(db, ci.id)
        label = _s_model(ci.model_name) or ci.category
        if deps == 0:
            parts.append(f"[삭제] {label} {ci.quantity or 0}EA")
            if not dry_run:
                db.delete(ci)
        else:
            parts.append(f"[수량0] {label} {ci.quantity or 0}→0EA")
            blocked.append(
                f'조달내역에서 빠진 품목 "{label}" 에 실무데이터 {deps}건(바코드/도면/자재발주/'
                f'생산공정/납품회차)이 남아 있어 삭제하지 않고 수량만 0 처리 — 확인 필요'
            )
            if not dry_run:
                ci.quantity = 0

    return {'detail': ', '.join(parts), 'blocked': blocked}


def _s_model(name):
    """로그·알림용 모델명 축약 — 원문 전체가 저장된 경우가 있어 길다"""
    name = (name or '').strip()
    return name if len(name) <= 40 else name[:37] + '...'


def sync_item_quantities(db, dry_run=False):
    """G2B 변경계약 수량 → ContractItem.quantity 반영 (활성 계약 한정).

    납품관리 계획수량은 sum(contract_items.quantity)로 계산되므로
    (delivery_actions.sync_deliveries), 여기서 갱신해야 조달 변경분이
    납품/생산 화면까지 흘러간다.

    조달내역이 정본이므로 아래도 전부 자동 반영한다:
      - 전 품목 취소(prdct_qty=0 AND prdct_amt=0) → is_excluded + exclude_reason='취소'
        (payment_status 는 실제 수금상태라 건드리지 않는다 — 조달내역 예외처리 API와 동일)
      - 품목 추가/삭제 → _reconcile_items() 로 G2B 기준 재정렬

    사람 확인이 남는 유일한 경우: 조달내역에서 빠진 품목에 실무데이터(바코드/도면/
    자재발주/생산공정/납품회차)가 물려 있어 삭제하지 못하고 수량만 0 처리한 건.

    Returns:
        dict: {qty_fixed, items_fixed, cancelled, reconciled, needs_review, ...}
    """
    from modules.contract_filters import DONE_STATUSES
    from modules.history_board import append_history_log
    from modules.notification_engine import notify
    from modules.services.delivery_actions import sync_deliveries

    contracts = db.query(Contract).filter(
        Contract.g2b_contract_no.isnot(None),
        Contract.g2b_contract_no != '',
        Contract.payment_status.notin_(DONE_STATUSES),
        Contract.is_excluded.isnot(True),
    ).all()

    changes, reviews, cancelled, reconciled = [], [], [], []
    touched_projects = set()

    for contract in contracts:
        g2b_rows = _final_g2b_items(db, contract.g2b_contract_no)
        if not g2b_rows:
            continue

        contract_items = db.query(ContractItem).filter(
            ContractItem.contract_id == contract.id
        ).order_by(ContractItem.id).all()
        if not contract_items:
            continue

        max_chg = max((r.cntrct_dlvr_req_chg_ord or '00').strip() for r in g2b_rows)

        # 취소건: 전 품목이 수량 0 AND 금액 0 — auto_create_contracts와 동일 판정
        if all((r.prdct_qty or 0) == 0 and (r.prdct_amt or 0) == 0 for r in g2b_rows):
            detail = f'G2B {max_chg}차 변경으로 전량 취소 (수량 0 / 금액 0)'
            cancelled.append({
                'contract_id': contract.id,
                'project_id': contract.project_id,
                'g2b_no': contract.g2b_contract_no,
                'contract_name': contract.contract_name,
                'chg_ord': max_chg,
                'detail': detail,
            })
            if contract.project_id:
                touched_projects.add(contract.project_id)
            logger.info(
                f"[G2B조달] 계약취소 반영: {contract.g2b_contract_no} 차수{max_chg} "
                f"({(contract.contract_name or '')[:30]})"
            )
            if not dry_run:
                # 예외처리는 is_excluded 플래그로만 — payment_status 는 실제 수금상태이므로
                # 건드리지 않는다 (조달내역 화면의 예외처리 API와 동일한 방식)
                contract.is_excluded = True
                contract.exclude_reason = '취소'
                contract.exclude_note = detail
                contract.g2b_change_ord = max_chg
                for ci in contract_items:
                    ci.quantity = 0
                if contract.project_id:
                    append_history_log(
                        db,
                        project_id=contract.project_id,
                        user_name='시스템',
                        content=f'G2B 변경계약({max_chg}차) 전량취소 — 예외처리(취소) 자동 반영',
                        scope='contract',
                        kind='system',
                    )
            continue

        # 취소선(수량 0 AND 금액 0)을 품목 수에 넣으면 모델 교체건이 1:1 로 잘못 맞아
        # 옛 모델이 0EA 로 계속 남는다. 살아있는 품목끼리만 매칭한다.
        live_rows = [
            r for r in g2b_rows
            if not ((r.prdct_qty or 0) == 0 and (r.prdct_amt or 0) == 0)
        ]
        pairs, method = _match_g2b_items(live_rows, contract_items)
        if pairs is None:
            # 품목이 추가/삭제된 변경계약 — 조달내역을 정본으로 품목 구성을 맞춘다
            recon = _reconcile_items(db, contract, g2b_rows, contract_items, dry_run)
            if recon['detail']:
                reconciled.append({
                    'contract_id': contract.id,
                    'project_id': contract.project_id,
                    'g2b_no': contract.g2b_contract_no,
                    'contract_name': contract.contract_name,
                    'chg_ord': max_chg,
                    'detail': recon['detail'],
                })
                if contract.project_id:
                    touched_projects.add(contract.project_id)
                logger.info(
                    f"[G2B조달] 품목 재정렬: {contract.g2b_contract_no} 차수{max_chg} "
                    f"{recon['detail']} ({(contract.contract_name or '')[:30]})"
                )
                if not dry_run:
                    contract.g2b_change_ord = max_chg
                    if contract.project_id:
                        append_history_log(
                            db,
                            project_id=contract.project_id,
                            user_name='시스템',
                            content=f'G2B 변경계약({max_chg}차) 품목 재정렬 — {recon["detail"]}',
                            scope='contract',
                            kind='system',
                        )
            # 종속 데이터가 있어 지우지 못한 품목은 사람이 확인해야 한다
            for note in recon['blocked']:
                reviews.append({
                    'contract_id': contract.id,
                    'project_id': contract.project_id,
                    'g2b_no': contract.g2b_contract_no,
                    'contract_name': contract.contract_name,
                    'reason': note,
                })
            continue

        diffs = []
        for g, ci in pairs:
            new_qty = g.prdct_qty or 0
            old_qty = ci.quantity or 0
            if new_qty == old_qty:
                continue
            diffs.append((ci, old_qty, new_qty))

        chg_stale = (contract.g2b_change_ord or '00') != max_chg
        if not diffs and not chg_stale:
            continue

        detail = ', '.join(
            f"{ci.model_name or ci.category} {old}→{new}EA" for ci, old, new in diffs
        )

        if not dry_run:
            for ci, _old, new_qty in diffs:
                ci.quantity = new_qty
            contract.g2b_change_ord = max_chg

        if diffs:
            changes.append({
                'contract_id': contract.id,
                'project_id': contract.project_id,
                'g2b_no': contract.g2b_contract_no,
                'contract_name': contract.contract_name,
                'chg_ord': max_chg,
                'method': method,
                'detail': detail,
                'item_count': len(diffs),
            })
            if contract.project_id:
                touched_projects.add(contract.project_id)

            logger.info(
                f"[G2B조달] 수량 수정({method}): {contract.g2b_contract_no} "
                f"차수{max_chg} {detail} ({(contract.contract_name or '')[:30]})"
            )

            if not dry_run and contract.project_id:
                append_history_log(
                    db,
                    project_id=contract.project_id,
                    user_name='시스템',
                    content=f'G2B 변경계약({max_chg}차) 수량 반영 — {detail}',
                    scope='contract',
                    kind='system',
                )

    if not dry_run:
        db.flush()
        # 납품 계획수량 재계산 — 수량이 바뀐 현장만
        for project_id in touched_projects:
            sync_deliveries(db, project_id=project_id)

        for c in changes:
            notify(db, 'contract.qty_changed', {
                'contract_name': c['contract_name'] or c['g2b_no'],
                'project_id': c['project_id'],
                'chg_ord': c['chg_ord'],
                'detail': c['detail'],
            }, dedupe_key=f"qty_changed:{c['contract_id']}:{c['chg_ord']}:{c['detail']}")

        for c in reconciled:
            notify(db, 'contract.qty_changed', {
                'contract_name': c['contract_name'] or c['g2b_no'],
                'project_id': c['project_id'],
                'chg_ord': c['chg_ord'],
                'detail': f"품목 재정렬 — {c['detail']}",
            }, dedupe_key=f"reconciled:{c['contract_id']}:{c['chg_ord']}:{c['detail']}")

        for c in cancelled:
            notify(db, 'contract.cancelled', {
                'contract_name': c['contract_name'] or c['g2b_no'],
                'project_id': c['project_id'],
                'detail': c['detail'],
            }, dedupe_key=f"cancelled:{c['contract_id']}:{c['chg_ord']}")

        for r in reviews:
            notify(db, 'contract.change_review', {
                'contract_name': r['contract_name'] or r['g2b_no'],
                'project_id': r['project_id'],
                'reason': r['reason'],
            }, dedupe_key=f"change_review:{r['contract_id']}:{r['reason']}")

    return {
        'qty_fixed': len(changes),
        'items_fixed': sum(c['item_count'] for c in changes),
        'cancelled': len(cancelled),
        'reconciled': len(reconciled),
        'needs_review': len(reviews),
        'changes': changes,
        'cancels': cancelled,
        'reconciles': reconciled,
        'reviews': reviews,
    }


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

        # 물품분류번호별 순회 조회
        items = []
        for clsfc_no in PRODUCT_CLSFC_NOS:
            fetched = _fetch_all(bgn_str, end_str, inqry_div='1', clsfc_no=clsfc_no)
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
