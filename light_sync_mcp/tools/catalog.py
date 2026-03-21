"""FR-14: 카탈로그 도메인 Tools (2개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_catalog_products(
        search: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """제품 카탈로그 조회. 나라장터 연동 제품 단가를 검색합니다.
        search: 제품명, 모델명, 규격 검색
        """
        from modules.models.entities import ProductCatalog
        session = get_session()
        try:
            q = session.query(ProductCatalog)
            if search:
                q = q.filter(
                    ProductCatalog.item_name.ilike(f"%{search}%")
                    | ProductCatalog.model_name.ilike(f"%{search}%")
                    | ProductCatalog.spec.ilike(f"%{search}%")
                    | ProductCatalog.krn_prdct_nm.ilike(f"%{search}%")
                )
            if category:
                q = q.filter(ProductCatalog.prdct_clsfc_no.ilike(f"%{category}%"))
            products = q.order_by(ProductCatalog.item_name).limit(limit).all()

            return json.dumps([{
                "id": p.id,
                "item_name": _s(p.item_name),
                "model_name": _s(p.model_name),
                "spec": _s(p.spec),
                "manufacturer": _s(p.manufacturer),
                "unit": _s(p.unit),
                "unit_price": int(_sn(p.unit_price)),
                "price_source": _s(p.price_source),
                "g2b_contract_no": _s(p.g2b_cntrct_no),
                "krn_prdct_nm": _s(p.krn_prdct_nm),
            } for p in products], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_catalog_price(product_name: str) -> str:
        """제품 단가 조회. 제품명으로 나라장터/수기/견적 단가를 검색합니다."""
        from modules.models.entities import ProductCatalog
        session = get_session()
        try:
            products = session.query(ProductCatalog).filter(
                ProductCatalog.item_name.ilike(f"%{product_name}%")
                | ProductCatalog.model_name.ilike(f"%{product_name}%")
            ).limit(20).all()

            return json.dumps([{
                "item_name": _s(p.item_name),
                "model_name": _s(p.model_name),
                "spec": _s(p.spec),
                "unit_price": int(_sn(p.unit_price)),
                "price_source": _s(p.price_source),
                "g2b_contract_no": _s(p.g2b_cntrct_no),
                "contract_period": f"{_sd(p.cntrct_bgn_date)} ~ {_sd(p.cntrct_end_date)}",
            } for p in products], ensure_ascii=False)
        finally:
            session.close()
