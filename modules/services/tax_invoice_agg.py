"""
세금계산서(tax_invoices) 집계 공용 헬퍼.

⚠️ 매출/매입 금액을 합산할 때는 반드시 이 모듈의 deduped_invoice_subq() 를 거쳐야 한다.

배경 — 홈택스 수집 과정에서 같은 세금계산서가 승인번호의 하이픈 유/무 등으로
서로 다른 문자열(approval_no unique 제약을 통과)로 2건 저장되는 사고가 있었다.
raw 테이블을 그대로 SUM 하면 매출이 최대 2배까지 과대계상된다.
(참조: project_hometax_sales_dup, MCP_ERROR.md)

해결 — approval_no 에서 숫자만 남긴 정규화 키(regexp_replace(approval_no,'[^0-9]','','g'))
기준으로 중복을 제거(DISTINCT ON)한 뒤 합산한다. 같은 키가 여러 건이면
supply_amount 가 큰 행 1건만 남긴다(금액이 동일하므로 어느 것을 골라도 무방하되 결정적).
"""

from sqlalchemy import func


# 정규화 키: 승인번호에서 숫자 이외 문자(하이픈 등) 모두 제거
def _norm_key(TaxInvoice):
    return func.regexp_replace(TaxInvoice.approval_no, '[^0-9]', '', 'g')


def deduped_invoice_subq(session):
    """정규화 승인번호 기준 중복 제거된 tax_invoices 서브쿼리를 반환한다.

    반환된 subquery 의 컬럼(subq.c.*)으로 SUM/COUNT/GROUP BY 하면 이중저장 걱정 없이
    정확한 매출/매입을 집계할 수 있다. session 은 호출측의 SQLAlchemy 세션을 그대로 사용.
    """
    from modules.models.entities import TaxInvoice
    norm = _norm_key(TaxInvoice)
    return (
        session.query(
            TaxInvoice.id.label('id'),
            TaxInvoice.approval_no.label('approval_no'),
            TaxInvoice.issue_date.label('issue_date'),
            TaxInvoice.direction.label('direction'),
            TaxInvoice.invoice_type.label('invoice_type'),
            TaxInvoice.match_status.label('match_status'),
            TaxInvoice.payment_status.label('payment_status'),
            TaxInvoice.contract_id.label('contract_id'),
            TaxInvoice.project_id.label('project_id'),
            TaxInvoice.supplier_name.label('supplier_name'),
            TaxInvoice.buyer_name.label('buyer_name'),
            TaxInvoice.g2b_contract_no.label('g2b_contract_no'),
            TaxInvoice.supply_amount.label('supply_amount'),
            TaxInvoice.tax_amount.label('tax_amount'),
            TaxInvoice.total_amount.label('total_amount'),
        )
        # Postgres DISTINCT ON (정규화키) — order_by 선두가 동일 표현식이어야 함
        .distinct(norm)
        .order_by(norm, TaxInvoice.supply_amount.desc().nullslast(), TaxInvoice.id.asc())
        .subquery()
    )
