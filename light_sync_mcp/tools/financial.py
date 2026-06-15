"""FR-06: 재무/매출 도메인 Tools (4개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_revenue_summary(year: int, month: Optional[int] = None) -> str:
        """매출 집계. 세금계산서 기준 연월별 매출 합산을 반환합니다."""
        from modules.models.entities import TaxInvoice
        from sqlalchemy import func, extract
        session = get_session()
        try:
            if month:
                rows = session.query(
                    func.date(TaxInvoice.issue_date).label("date"),
                    func.sum(TaxInvoice.supply_amount).label("supply"),
                    func.sum(TaxInvoice.total_amount).label("total"),
                    func.count(TaxInvoice.id).label("count"),
                ).filter(
                    extract("year", TaxInvoice.issue_date) == year,
                    extract("month", TaxInvoice.issue_date) == month,
                ).group_by(func.date(TaxInvoice.issue_date)).order_by("date").all()
                items = [{"date": str(r.date), "supply_amount": int(r.supply or 0),
                          "total_amount": int(r.total or 0), "count": r.count} for r in rows]
            else:
                rows = session.query(
                    extract("month", TaxInvoice.issue_date).label("month"),
                    func.sum(TaxInvoice.supply_amount).label("supply"),
                    func.sum(TaxInvoice.total_amount).label("total"),
                    func.count(TaxInvoice.id).label("count"),
                ).filter(extract("year", TaxInvoice.issue_date) == year
                ).group_by("month").order_by("month").all()
                items = [{"month": int(r.month), "supply_amount": int(r.supply or 0),
                          "total_amount": int(r.total or 0), "count": r.count} for r in rows]

            return json.dumps({
                "year": year,
                "month": month,
                "grand_total": sum(i["total_amount"] for i in items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_tax_invoices(
        year: Optional[int] = None,
        month: Optional[int] = None,
        payment_status: Optional[str] = None,
        limit: int = 50,
        months_back: int = 24,
        include_old: bool = False,
    ) -> str:
        """세금계산서 목록 조회. G2B 매칭 상태, 수금 상태로 필터링합니다.
        payment_status: 미수금 / 부분입금 / 입금완료

        기본은 **최근 24개월** 데이터만 (year 명시 시 해당 연도만, 이때 기간 필터 자동 해제).
        오래된 데이터(2013년부터)가 검색에 섞이는 데이터 오염 방지.

        Args:
            months_back: 최근 N개월 기간 필터 (기본 24). year 명시 시 무시.
            include_old: True 시 전체 기간 (기본 False).
        """
        from modules.models.entities import TaxInvoice
        from sqlalchemy import extract
        import datetime
        session = get_session()
        try:
            q = session.query(TaxInvoice)
            if year:
                q = q.filter(extract("year", TaxInvoice.issue_date) == year)
            if month:
                q = q.filter(extract("month", TaxInvoice.issue_date) == month)
            if payment_status and hasattr(TaxInvoice, "payment_status"):
                q = q.filter(TaxInvoice.payment_status == payment_status)
            # 기간 필터 — year 명시 안 됐을 때만 적용
            if not year and not include_old and months_back > 0:
                cutoff = datetime.date.today() - datetime.timedelta(days=30 * months_back)
                q = q.filter(TaxInvoice.issue_date >= cutoff)
            invoices = q.order_by(TaxInvoice.issue_date.desc().nullslast()).limit(limit).all()

            return json.dumps([{
                "id": inv.id,
                "approval_no": _s(inv.approval_no),
                "issue_date": _sd(inv.issue_date),
                "buyer_name": _s(inv.buyer_name),
                "supply_amount": int(inv.supply_amount or 0),
                "tax_amount": int(inv.tax_amount or 0),
                "total_amount": int(inv.total_amount or 0),
                "payment_status": _s(inv.payment_status) if hasattr(inv, "payment_status") else "",
                "match_status": _s(inv.match_status) if hasattr(inv, "match_status") else "",
                "g2b_matched": bool(getattr(inv, "g2b_procurement_id", None)),
            } for inv in invoices], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_financial_overview(year: Optional[int] = None) -> str:
        """재무 대시보드 요약. 총 매출, 미수금, 수금액을 반환합니다."""
        from modules.models.entities import TaxInvoice
        from sqlalchemy import func, extract
        session = get_session()
        try:
            q = session.query(
                func.sum(TaxInvoice.supply_amount).label("supply"),
                func.sum(TaxInvoice.total_amount).label("total"),
                func.count(TaxInvoice.id).label("count"),
            )
            if year:
                q = q.filter(extract("year", TaxInvoice.issue_date) == year)
            row = q.first()

            unpaid_q = session.query(func.sum(TaxInvoice.total_amount))
            if year:
                unpaid_q = unpaid_q.filter(extract("year", TaxInvoice.issue_date) == year)
            if hasattr(TaxInvoice, "payment_status"):
                unpaid_q = unpaid_q.filter(TaxInvoice.payment_status.in_(["미수금", "부분입금"]))
            unpaid = int(unpaid_q.scalar() or 0)
            total = int(row.total or 0)

            return json.dumps({
                "year": year,
                "total_supply_amount": int(row.supply or 0),
                "total_amount": total,
                "invoice_count": row.count or 0,
                "unpaid_amount": unpaid,
                "paid_amount": total - unpaid,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_unpaid_invoices(
        limit: int = 50,
        months_back: int = 24,
        include_old: bool = False,
        status: Optional[str] = None,
        include_exception: bool = False,
    ) -> str:
        """미수금 현황 — 조달내역(G2B) 기준.

        ⚠️ ERP 운영 화면과 동일한 방식:
        - 대상 상태: '미청구', '부분입금' (예외는 기본 제외)
          * '예외' 는 ERP 에서 완료/숨김 처리 의미 (routes/financial.py:736
             "예외 처리 = 미청구/부분입금 → 완료 처리")
        - 금액 산정:
          · 미청구  : G2B prdct_amt 합계 (전액)
          · 부분입금 : G2B prdct_amt 합계 − 매칭된 TaxInvoice.total_amount 합계 (잔액)
            (= 받기로 한 총액 − 이미 세금계산서로 청구·수금된 금액)

        Args:
            limit: 최대 반환 건수 (기본 50, 납기 임박순)
            months_back: 최근 N개월 기간 필터 (기본 24). include_old=True 면 무시.
            include_old: True 시 전체 기간 (기본 False).
            status: '미청구' / '부분입금' / '예외' 명시 시 그 한 가지만.
            include_exception: 사용자가 "예외 포함" 명시할 때만 True (기본 False).
                              status='예외' 단독 조회는 status 매개변수로 가능.
        """
        from modules.models.entities import G2bProcurement, TaxInvoice
        from modules.models.contract_entities import Contract
        from modules.models import Project
        from sqlalchemy import func, desc, or_
        from sqlalchemy.orm import joinedload
        import datetime
        session = get_session()
        try:
            # 대상 상태 결정 — 예외는 기본 제외
            if status:
                statuses = [status]
            else:
                statuses = ['미청구', '부분입금']
                if include_exception:
                    statuses.append('예외')

            q = session.query(Contract).options(joinedload(Contract.project)) \
                .filter(Contract.payment_status.in_(statuses))

            # 기간 필터 — Contract.contract_date 기준
            cutoff = None
            if not include_old and months_back > 0:
                cutoff = datetime.date.today() - datetime.timedelta(days=30 * months_back)
                q = q.filter(or_(
                    Contract.contract_date >= cutoff,
                    Contract.contract_date.is_(None),
                ))

            # 정렬: 납기 임박순 (null 은 뒤로)
            q = q.order_by(Contract.delivery_due_date.asc().nullslast())
            contracts = q.limit(limit).all()

            # 금액 산정
            items = []
            grand_total = 0
            by_status = {}
            for ct in contracts:
                # G2B 청구 대상 총액
                g2b_amt = 0
                if ct.g2b_contract_no:
                    g2b_amt = session.query(func.coalesce(func.sum(G2bProcurement.prdct_amt), 0)) \
                        .filter(G2bProcurement.cntrct_dlvr_req_no == ct.g2b_contract_no) \
                        .scalar() or 0
                # 부분입금 시 — 매칭된 세금계산서 발행분(=선금/청구분)을 차감
                # 차장님 확인 (2026-05-14): "매출에 세금계산서 연동된거보면
                # 선금받은금액 확인되는데" — paid_amount 컬럼이 아니라 매칭 invoice
                # total_amount 합계가 실질적인 선금/청구분.
                paid_amt = 0
                unpaid_amt = int(g2b_amt)
                if ct.payment_status == '부분입금':
                    paid_amt = session.query(func.coalesce(func.sum(TaxInvoice.total_amount), 0)) \
                        .filter(
                            TaxInvoice.contract_id == ct.id,
                            TaxInvoice.invoice_type == '세금계산서',
                        ) \
                        .scalar() or 0
                    unpaid_amt = int(g2b_amt) - int(paid_amt)
                    if unpaid_amt < 0:
                        unpaid_amt = 0
                grand_total += unpaid_amt
                by_status[ct.payment_status] = by_status.get(ct.payment_status, 0) + unpaid_amt
                proj = ct.project
                items.append({
                    "contract_id": ct.id,
                    "g2b_contract_no": _s(ct.g2b_contract_no),
                    "project_id": ct.project_id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "contract_name": _s(ct.contract_name),
                    "contract_date": _sd(ct.contract_date),
                    "delivery_due_date": _sd(ct.delivery_due_date),
                    "payment_status": _s(ct.payment_status),
                    "unpaid_reason": _s(ct.unpaid_reason),
                    "g2b_total_amount": int(g2b_amt),
                    "invoiced_amount": int(paid_amt),  # 매칭된 세금계산서 발행분
                    "unpaid_amount": unpaid_amt,
                })

            return json.dumps({
                "total_unpaid": grand_total,
                "count": len(items),
                "by_status": by_status,
                "filter_months_back": None if include_old else months_back,
                "filter_cutoff_date": str(cutoff) if cutoff else None,
                "include_old": include_old,
                "include_exception": include_exception,
                "statuses_in_scope": statuses,
                "basis": "Contract.payment_status (조달내역 기준). 부분입금 잔액 = G2B 합계 − 매칭 TaxInvoice.total_amount(세금계산서) 합계. 예외는 기본 제외.",
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
