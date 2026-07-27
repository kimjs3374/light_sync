"""
G2B 조달내역 → 프로젝트 + 계약 자동 생성 + 세금계산서 매칭 + 하자보증 자동 생성

흐름:
  g2b_procurements (계약번호 기준 그룹핑)
    → Project 자동 생성 (1 G2B계약 = 1 현장)
    → Contract 자동 생성 + ContractItem
    → TaxInvoice 매칭 (g2b_contract_no 기준)
    → Warranty 자동 생성 (세금계산서 발행일 기준)

보증 기간:
  - 우수제품(exclc_prodct_yn='Y') 또는 혁신제품(cntrct_mthd_nm에 '혁신') → 3년
  - 나머지 → 1년
"""
import datetime
import logging
from sqlalchemy import text
from modules.models.constants import DETAIL_ITEM_ALIASES, DETAIL_ITEM_OPTIONS

logger = logging.getLogger(__name__)


def _parse_g2b_item(g2b_item):
    """G2B 품목에서 상세품목(item_group), 카테고리, 모델명 추출

    G2B 데이터 형식:
      dtil_prdct_clsfc_no_nm = 'LED투광등기구'
      prdct_idnt_no_nm = 'LED투광등기구, 매그나텍, ARENA-600, 600W'

    Returns:
        (item_group, category, model_name)

    개선 (project_id=4216 회귀 방지):
    - raw_category 가 비어있거나 매칭 실패 시, 무조건 LED투광등기구로 fallback
      하던 기존 로직이 등주/조명타워/태양광 등을 LED투광등으로 잘못 박는 원인이었음.
    - 이제는 prdct_idnt_no_nm 의 첫 토큰(품목분류) 을 한 번 더 확인해서 매칭 시도.
      그래도 매칭 안 되면 마지막 수단으로만 default 사용.
    """
    raw_category = (g2b_item.dtil_prdct_clsfc_no_nm or '').strip()
    raw_spec = (g2b_item.prdct_idnt_no_nm or '').strip()

    # 0. prdct_idnt_no_nm 의 첫 토큰을 보조 카테고리 후보로 사용
    #    "스테인리스가로등주, 매그나텍, MTPS-203-5, 5m, ..." → "스테인리스가로등주"
    spec_head = raw_spec.split(',', 1)[0].strip() if ',' in raw_spec else ''

    def _resolve_category(token):
        """주어진 문자열에서 spec_schema 정식 카테고리 결정 (None 가능)"""
        if not token:
            return None
        # 정확 alias 매칭
        if token in DETAIL_ITEM_ALIASES:
            return DETAIL_ITEM_ALIASES[token]
        # 정식 카테고리 그대로
        if token in DETAIL_ITEM_OPTIONS:
            return token
        # 부분 alias 매칭
        for alias, option in DETAIL_ITEM_ALIASES.items():
            if alias in token:
                return option
        # 부분 정식 카테고리 매칭
        for opt in DETAIL_ITEM_OPTIONS:
            if opt in token:
                return opt
        return None

    # 1. item_group 결정 — raw_category → spec_head → 최후 default
    item_group = _resolve_category(raw_category) or _resolve_category(spec_head)
    if not item_group:
        item_group = DETAIL_ITEM_OPTIONS[0]  # 기본값: LED투광등기구 (최후 수단)

    # 2. 모델명 추출: "LED투광등기구, 매그나텍, ARENA-600, 600W" → "ARENA-600"
    parts = [p.strip() for p in raw_spec.split(',')]
    model_name = raw_spec  # 기본값: 전체 문자열
    if len(parts) >= 3:
        # parts[0]=세부품명, parts[1]=제조사, parts[2]=모델명, parts[3:]=규격
        model_name = parts[2]
    elif len(parts) == 2:
        model_name = parts[1]

    # 3. category = 세부품명 원본 우선, 비면 spec_head, 그것도 비면 item_group
    #    raw_category 가 비어 있는데도 LED투광등기구로 박혀버리던 4216 회귀 차단.
    category = raw_category or spec_head or item_group

    return item_group, category, model_name


def _next_g2b_project_no(db, year):
    """G2B 계약용 프로젝트 번호 채번: G-YYYY-NNNN (설계번호 YYYY-NNN과 별도 체계)"""
    prefix = f'G-{year}-'
    row = db.execute(text(
        "SELECT project_no FROM light_sync.projects "
        "WHERE project_no LIKE :prefix "
        "ORDER BY project_no DESC LIMIT 1"
    ), {'prefix': f'{prefix}%'}).first()
    if row:
        try:
            seq = int(row[0].replace(prefix, '')) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f'{prefix}{seq:04d}'


def sync_g2b_to_contracts(db):
    """G2B 조달내역 → 프로젝트+계약 일괄 생성 (이미 있으면 스킵)

    Returns:
        dict: {created, skipped, matched_invoices, warranties_created}
    """
    from modules.models import (
        Contract, ContractItem, G2bProcurement, TaxInvoice, Warranty,
    )

    result = {'created': 0, 'skipped': 0, 'matched_invoices': 0, 'warranties_created': 0}

    # 1. G2B 계약번호 기준 그룹핑
    g2b_groups = db.execute(text('''
        SELECT cntrct_dlvr_req_no,
               MAX(cntrct_dlvr_req_nm) as contract_name,
               MAX(dminstt_nm) as buyer_name,
               SUM(prdct_amt) as total_amt,
               MAX(cntrct_dlvr_req_date) as contract_date,
               MAX(dlvr_tmlmt_date) as delivery_date,
               MAX(exclc_prodct_yn) as excellent_yn,
               MAX(cntrct_mthd_nm) as method_name,
               MAX(cntrct_div_nm) as div_name,
               MAX(dlvr_plce_nm) as delivery_place
        FROM light_sync.g2b_procurements
        GROUP BY cntrct_dlvr_req_no
        HAVING SUM(prdct_amt) > 0
        ORDER BY MAX(cntrct_dlvr_req_date) DESC NULLS LAST
    ''')).fetchall()

    # 이미 등록된 g2b_contract_no 조회
    existing_g2b_nos = set(
        r[0] for r in db.query(Contract.g2b_contract_no).filter(
            Contract.g2b_contract_no.isnot(None)
        ).all()
    )

    for g in g2b_groups:
        g2b_no = g.cntrct_dlvr_req_no
        if g2b_no in existing_g2b_nos:
            result['skipped'] += 1
            continue

        # ── 2. 프로젝트(현장) 자동 생성 ──
        contract_year = g.contract_date.year if g.contract_date else datetime.date.today().year
        project_no = _next_g2b_project_no(db, contract_year)

        # 계약명에서 현장명 추출 (너무 길면 자르기)
        site_name = g.contract_name or f'G2B-{g2b_no}'
        if len(site_name) > 100:
            site_name = site_name[:97] + '...'

        # 세금계산서 매칭 여부 미리 확인 (아래 '5. 세금계산서 매칭'에서 재사용)
        matched_invoices = db.query(TaxInvoice).filter(
            TaxInvoice.g2b_contract_no == g2b_no,
            TaxInvoice.match_status.in_(['자동매칭', '수동매칭']),
        ).all()
        has_invoice = len(matched_invoices) > 0

        # raw INSERT로 프로젝트 생성 (운영DB에 새 컬럼 미적용 시에도 동작)
        project_id = db.execute(text('''
            INSERT INTO light_sync.projects (project_no, temp_name, short_name, site_address, status, is_contracted, contract_date)
            VALUES (:no, :name, :short, :addr, :status, true, :cdate)
            RETURNING id
        '''), {
            'no': project_no,
            'name': site_name,
            'short': (g.buyer_name or '')[:50],
            'addr': g.delivery_place or '',
            'status': '계약',
            'cdate': g.contract_date,
        }).scalar()

        # ── 3. 계약 생성 ──
        warranty_type = '일반'
        if g.excellent_yn and g.excellent_yn.upper() in ('Y', 'YES', '1'):
            warranty_type = '우수제품'
        elif g.method_name and '혁신' in g.method_name:
            warranty_type = '혁신제품'

        # ── 4. 품목 파싱 + 계약의 item_group 결정 ──
        items = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == g2b_no
        ).all()

        # 계약 뱃지에 쓰이는 대표 상세품목 — 첫 품목만 보면 품목군이 섞인 계약에서
        # 소수 품목이 대표가 된다. 가장 많은 품목군을 쓴다.
        from modules.services.g2b_procurement_sync import _representative_item_group
        representative_group = _representative_item_group(
            _parse_g2b_item(it)[0] for it in items
        )

        contract = Contract(
            project_id=project_id,
            contract_name=g.contract_name or f'G2B-{g2b_no}',
            item_group=representative_group,
            g2b_contract_no=g2b_no,
            contract_date=g.contract_date,
            delivery_due_date=g.delivery_date,
            payment_status='미청구',
        )
        db.add(contract)
        db.flush()

        for item in items:
            item_group, category, model_name = _parse_g2b_item(item)
            ci = ContractItem(
                contract_id=contract.id,
                category=category,
                model_name=model_name,
                quantity=item.prdct_qty or 0,
                status_sales='납품완료' if has_invoice else '계약확인',
                status_admin='완료' if has_invoice else '자재확인중',
                status_prod='완료' if has_invoice else '자재대기중',
            )
            db.add(ci)

        # ── 5. 세금계산서 매칭 ──
        if matched_invoices:
            latest_invoice = max(matched_invoices, key=lambda inv: inv.issue_date or datetime.date.min)

            for inv in matched_invoices:
                inv.contract_id = contract.id
                inv.project_id = project_id
                result['matched_invoices'] += 1

            # 금액 비교 후 수금상태 재계산
            from modules.services.warranty_auto import recalc_contract_payment_status
            status = recalc_contract_payment_status(db, contract, latest_invoice.issue_date)
            if status == '입금완료':
                result['warranties_created'] += 1

        result['created'] += 1

    db.commit()
    logger.info(
        'G2B sync: created=%d, skipped=%d, invoices=%d, warranties=%d',
        result['created'], result['skipped'],
        result['matched_invoices'], result['warranties_created'],
    )
    return result
