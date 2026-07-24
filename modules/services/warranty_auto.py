"""
하자보증 자동 관리 — 세금계산서 발행 기준 자동 생성

규칙:
- 세금계산서가 계약에 매칭되면 → 해당 계약의 하자보증 자동 생성
- 혁신제품/우수제품: 3년, 나머지: 1년
- warranty_start = 세금계산서 발행일 (issue_date)
- 이미 보증이 존재하면 건너뜀
"""
import datetime
import logging
from modules.models import Warranty, Contract, G2bProcurement, ContractItem, Project, Contact

logger = logging.getLogger(__name__)


def _determine_warranty_type(db, contract):
    """G2B 조달 데이터로 보증유형 판별"""
    if not contract.g2b_contract_no:
        return '일반'

    proc = db.query(G2bProcurement).filter(
        G2bProcurement.cntrct_dlvr_req_no == contract.g2b_contract_no
    ).first()
    if not proc:
        return '일반'

    # 우수제품 여부
    if proc.exclc_prodct_yn and proc.exclc_prodct_yn.upper() in ('Y', 'YES', '1'):
        return '우수제품'

    # 혁신제품 판별 (계약체결방법명 또는 계약구분명에 "혁신" 포함)
    if proc.cntrct_mthd_nm and '혁신' in proc.cntrct_mthd_nm:
        return '혁신제품'
    if proc.cntrct_div_nm and '혁신' in proc.cntrct_div_nm:
        return '혁신제품'

    return '일반'


def auto_create_warranty(db, contract_id, issue_date):
    """세금계산서 매칭 시 하자보증 자동 생성

    Args:
        db: DB session
        contract_id: 계약 ID
        issue_date: 세금계산서 발행일 (warranty_start)

    Returns:
        Warranty or None
    """
    # 이미 보증이 있으면 건너뜀
    existing = db.query(Warranty).filter_by(contract_id=contract_id).first()
    if existing:
        return existing

    contract = db.query(Contract).get(contract_id)
    if not contract:
        return None

    warranty_type = _determine_warranty_type(db, contract)

    # 기간 산출: 혁신/우수제품 3년, 일반 1년
    years = 3 if warranty_type in ('혁신제품', '우수제품') else 1
    start_date = issue_date if isinstance(issue_date, datetime.date) else datetime.date.today()
    end_date = start_date.replace(year=start_date.year + years)

    # 비정규화 데이터 수집
    denorm = {}
    denorm['contract_name'] = contract.contract_name
    denorm['item_group'] = contract.item_group

    # 계약 품목에서 모델명/수량 수집
    first_item = db.query(ContractItem).filter_by(contract_id=contract_id).first()
    if first_item:
        denorm['model_name'] = first_item.model_name
        denorm['quantity'] = first_item.quantity

    # 프로젝트에서 현장 주소 / 이름 수집
    if contract.project_id:
        project = db.query(Project).get(contract.project_id)
        if project:
            denorm['site_address'] = project.site_address

            # 고객 연락처 (첫 번째 연락처)
            contact = db.query(Contact).filter_by(project_id=project.id).first()
            if contact:
                denorm['customer_contact'] = contact.name
                denorm['customer_phone'] = contact.phone

    # G2B 조달 데이터에서 수요기관 정보 보완
    if contract.g2b_contract_no and not denorm.get('customer_contact'):
        proc = db.query(G2bProcurement).filter(
            G2bProcurement.cntrct_dlvr_req_no == contract.g2b_contract_no
        ).first()
        if proc:
            denorm['customer_contact'] = proc.dminstt_nm
            if not denorm.get('site_address') and proc.dlvr_plce_nm:
                denorm['site_address'] = proc.dlvr_plce_nm

    warranty = Warranty(
        contract_id=contract_id,
        project_id=contract.project_id,
        warranty_start=start_date,
        warranty_end=end_date,
        warranty_type=warranty_type,
        auto_generated=True,
        contract_name=denorm.get('contract_name'),
        item_group=denorm.get('item_group'),
        model_name=denorm.get('model_name'),
        quantity=denorm.get('quantity'),
        site_address=denorm.get('site_address'),
        customer_contact=denorm.get('customer_contact'),
        customer_phone=denorm.get('customer_phone'),
    )
    db.add(warranty)

    logger.info(
        'Auto warranty created: contract=%d, type=%s, %s~%s',
        contract_id, warranty_type, start_date, end_date,
    )
    return warranty


def recalc_contract_payment_status(db, contract, latest_issue_date=None):
    """계약의 payment_status를 G2B 금액 vs 세금계산서 합계로 재계산.

    Args:
        db: DB session
        contract: Contract 객체
        latest_issue_date: 최신 세금계산서 발행일 (없으면 DB에서 조회)

    Returns:
        str: 계산된 payment_status
    """
    from sqlalchemy import func, text as sa_text
    from modules.services.tax_invoice_agg import deduped_invoice_subq

    # 예외/변경완료/취소 상태는 건드리지 않음
    if contract.payment_status in ('예외', '변경완료', '취소'):
        return contract.payment_status

    # G2B 조달금액 합계
    g2b_amt = 0
    if contract.g2b_contract_no:
        g2b_amt = db.execute(sa_text(
            'SELECT SUM(prdct_amt) FROM light_sync.g2b_procurements WHERE cntrct_dlvr_req_no = :no'
        ), {'no': contract.g2b_contract_no}).scalar() or 0

    # 매칭된 세금계산서 합계 (수정세금계산서 +/- 상쇄 포함) — 정규화 중복제거
    _inv = deduped_invoice_subq(db)
    invoiced_total = db.query(func.coalesce(func.sum(_inv.c.total_amount), 0)).filter(
        _inv.c.contract_id == contract.id,
    ).scalar() or 0

    # 다량구매할인율 허용 (나라장터 0.5%~2% 할인 적용 시 세금계산서 < G2B)
    discount_threshold = g2b_amt * 0.97  # 최대 3% 할인까지 허용

    if g2b_amt > 0 and invoiced_total >= discount_threshold:
        contract.payment_status = '입금완료'
        if latest_issue_date:
            contract.payment_date = latest_issue_date
        auto_create_warranty(db, contract.id, latest_issue_date or contract.invoice_date)
    elif invoiced_total > 0:
        contract.payment_status = '부분입금'
    else:
        contract.payment_status = '미청구'

    # 최신 발행일 갱신
    if latest_issue_date:
        if not contract.invoice_date or latest_issue_date > contract.invoice_date:
            contract.invoice_date = latest_issue_date

    return contract.payment_status
