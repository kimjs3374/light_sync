"""청구관리 Tools — 납품완료 → 청구완료 → 입금완료 워크플로우"""
import datetime
import json
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd, _erp_url


_PAYMENT_STATUSES = ('미청구', '청구완료', '부분입금')


def register(mcp: FastMCP):

    @mcp.tool()
    def get_billing_status(
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """청구관리 — 납품완료 건 중 미청구/청구완료/부분입금 상태별 조회.
        ★ '청구해야 할 거', '미청구', '아직 청구 못한 거', '세금계산서 발행 안 한 거',
          '부분입금', '청구 진행상황' 등에 사용.
        ※ 미수금(세금계산서 기준 안 받은 돈)은 get_unpaid_invoices() 사용 — 다른 개념.

        status: 미청구 / 청구완료 / 부분입금 / all (생략 시 미청구만)
        search: 계약명/현장명/G2B번호 부분 검색
        limit: 최대 건수 (기본 30)
        """
        from modules.models import Contract, Project, Delivery
        session = get_session()
        try:
            today = datetime.date.today()

            target_status = status or '미청구'
            if target_status == 'all':
                status_filter = list(_PAYMENT_STATUSES)
            elif target_status in _PAYMENT_STATUSES:
                status_filter = [target_status]
            else:
                return json.dumps({
                    "error": f"status는 미청구/청구완료/부분입금/all 중 하나여야 합니다. (입력값: {status})",
                }, ensure_ascii=False)

            base = (
                session.query(Contract)
                .join(Project, Contract.project_id == Project.id)
                .join(Delivery, Delivery.contract_id == Contract.id)
                .filter(
                    Contract.is_excluded.isnot(True),
                    Delivery.delivery_status == 'done',
                    Contract.payment_status.in_(status_filter),
                )
            )

            if search:
                like = f"%{search}%"
                base = base.filter(or_(
                    Contract.contract_name.ilike(like),
                    Project.temp_name.ilike(like),
                    Contract.g2b_contract_no.ilike(like),
                ))

            # 통계 (필터 무시 — 전체 카운트)
            stats_q = (
                session.query(Contract.payment_status, func.count(func.distinct(Contract.id)))
                .join(Delivery, Delivery.contract_id == Contract.id)
                .filter(
                    Contract.is_excluded.isnot(True),
                    Delivery.delivery_status == 'done',
                    Contract.payment_status.in_(_PAYMENT_STATUSES),
                )
                .group_by(Contract.payment_status)
                .all()
            )
            stats = {'미청구': 0, '청구완료': 0, '부분입금': 0}
            for ps, cnt in stats_q:
                stats[ps] = cnt

            contract_ids = [
                r[0] for r in base.with_entities(Contract.id).distinct()
                .order_by(Contract.id.desc()).limit(limit).all()
            ]
            contracts = (
                session.query(Contract)
                .filter(Contract.id.in_(contract_ids))
                .options(joinedload(Contract.project))
                .order_by(Contract.delivery_due_date.asc().nullslast())
                .all()
            ) if contract_ids else []

            items = []
            for c in contracts:
                dday = (c.delivery_due_date - today).days if c.delivery_due_date else None
                items.append({
                    "contract_id": c.id,
                    "contract_name": _s(c.contract_name),
                    "g2b_contract_no": _s(c.g2b_contract_no),
                    "project_name": c.project.temp_name if c.project else "",
                    "payment_status": _s(c.payment_status),
                    "invoice_date": _sd(c.invoice_date),
                    "delivery_due_date": _sd(c.delivery_due_date),
                    "dday": dday,
                    "erp_url": _erp_url(f"/billing") + f"?contract_id={c.id}",
                })

            return json.dumps({
                "stats": stats,
                "filter_applied": target_status,
                "filtered_count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()
