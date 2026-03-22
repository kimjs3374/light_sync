"""인증서 만료 관리 Tools"""
import json
import datetime
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_cert_expiry_alerts(
        days: int = 60,
        cert_type: Optional[str] = None,
    ) -> str:
        """만료 임박 또는 만료된 인증서 목록 조회.
        days: 만료까지 남은 일수 기준 (기본 60일 이내)
        cert_type: 인증 유형 필터 (예: KS, ISO, KC, 시험성적서)
        만료된 인증서도 포함하여 반환합니다.
        """
        from modules.models.entities import Certification
        session = get_session()
        try:
            cutoff = datetime.date.today() + datetime.timedelta(days=days)
            q = session.query(Certification).filter(
                Certification.is_active == True,
                Certification.expiry_date <= cutoff,
            )
            if cert_type:
                q = q.filter(Certification.cert_type.ilike(f"%{cert_type}%"))

            certs = q.order_by(Certification.expiry_date.asc()).all()

            result = []
            for c in certs:
                days_left = (c.expiry_date - datetime.date.today()).days if c.expiry_date else None
                result.append({
                    "id": c.id,
                    "cert_type": _s(c.cert_type),
                    "cert_name": _s(c.cert_name),
                    "cert_no": _s(c.cert_no),
                    "issued_by": _s(c.issued_by),
                    "issued_date": _sd(c.issued_date),
                    "expiry_date": _sd(c.expiry_date),
                    "product_model": _s(c.product_model),
                    "days_left": days_left,
                    "status": "만료" if days_left is not None and days_left < 0 else "임박",
                    "note": _s(c.note),
                })
            return json.dumps({
                "total": len(result),
                "expired": sum(1 for r in result if r["status"] == "만료"),
                "expiring_soon": sum(1 for r in result if r["status"] == "임박"),
                "certs": result,
            }, ensure_ascii=False)
        finally:
            session.close()
