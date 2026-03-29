"""FR-03: BOM/품목 도메인 Tools (6개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn


def register(mcp: FastMCP):

    def _match_opt(filter_json, option_filter):
        if not filter_json:
            return True
        if not option_filter:
            return True
        try:
            f = json.loads(filter_json)
            return all(option_filter.get(k) == v for k, v in f.items())
        except Exception:
            return True

    @mcp.tool()
    def get_bom_list(
        category: Optional[str] = None,
        search: Optional[str] = None,
        is_active: bool = True,
    ) -> str:
        """BOM 목록 조회. 완제품별 BOM 헤더와 부품 수를 반환합니다."""
        from modules.models.entities import BomHeader
        session = get_session()
        try:
            q = session.query(BomHeader)
            if is_active:
                q = q.filter(BomHeader.is_active == True)
            if category:
                q = q.filter(BomHeader.product_category.ilike(f"%{category}%"))
            if search:
                q = q.filter(BomHeader.product_name.ilike(f"%{search}%"))
            boms = q.order_by(BomHeader.product_name).all()

            result = [{
                "id": b.id,
                "product_code": _s(b.product_code),
                "product_name": _s(b.product_name),
                "product_category": _s(b.product_category),
                "version": _s(b.version),
                "certification_no": _s(b.certification_no),
                "item_count": len(b.bom_items),
                "has_option_schema": bool(b.option_schema),
            } for b in boms]
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_bom_detail(
        bom_id: Optional[int] = None,
        product_code: Optional[str] = None,
        option_filter: Optional[str] = None,
    ) -> str:
        """BOM 상세 조회. 소요 부품 목록과 원가를 반환합니다.
        option_filter: JSON 문자열 (예: '{"lens_angle":"20도"}')
        bom_id 또는 product_code 중 하나는 필수.
        """
        from modules.models.entities import BomHeader
        session = get_session()
        try:
            if bom_id:
                bom = session.get(BomHeader, bom_id)
            elif product_code:
                bom = session.query(BomHeader).filter(BomHeader.product_code == product_code).first()
            else:
                return "bom_id 또는 product_code가 필요합니다."

            # 별칭 fallback: product_code로 못 찾으면 별칭 테이블에서 검색
            if not bom and product_code:
                from modules.models.inventory_entities import BomModelAlias
                alias = session.query(BomModelAlias).filter(
                    BomModelAlias.alias_name == product_code
                ).first()
                if alias:
                    bom = session.get(BomHeader, alias.bom_id)

            if not bom:
                return "BOM을 찾을 수 없습니다."

            opt = json.loads(option_filter) if option_filter else None
            items = []
            total_cost = 0
            for bi in bom.bom_items:
                if not _match_opt(bi.option_filter, opt):
                    continue
                amount = _sn(bi.unit_price) * _sn(bi.quantity)
                total_cost += amount
                items.append({
                    "id": bi.id,
                    "item_code": _s(bi.item_code),
                    "item_name": _s(bi.item_name),
                    "item_spec": _s(bi.item_spec),
                    "quantity": _sn(bi.quantity),
                    "unit": _s(bi.unit),
                    "unit_price": int(_sn(bi.unit_price)),
                    "amount": int(amount),
                    "supplier": _s(bi.supplier),
                    "option_filter": json.loads(bi.option_filter) if bi.option_filter else None,
                })

            opt_schema = None
            if bom.option_schema:
                try:
                    opt_schema = json.loads(bom.option_schema)
                except Exception:
                    opt_schema = bom.option_schema

            return json.dumps({
                "header": {
                    "id": bom.id,
                    "product_code": _s(bom.product_code),
                    "product_name": _s(bom.product_name),
                    "product_category": _s(bom.product_category),
                    "version": _s(bom.version),
                    "certification_no": _s(bom.certification_no),
                    "option_schema": opt_schema,
                },
                "items": items,
                "item_count": len(items),
                "total_cost": int(total_cost),
                "applied_option_filter": opt,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def calculate_bom_cost(
        bom_id: int,
        quantity: int = 1,
        option_filter: Optional[str] = None,
    ) -> str:
        """BOM 원가 계산. 생산 수량 x 단가 합산으로 총 원가를 계산합니다.
        option_filter: JSON 문자열 (예: '{"lens_angle":"20도"}')
        """
        from modules.models.entities import BomHeader
        session = get_session()
        try:
            bom = session.get(BomHeader, bom_id)
            if not bom:
                return "BOM을 찾을 수 없습니다."

            opt = json.loads(option_filter) if option_filter else None
            items = []
            unit_cost = 0
            for bi in bom.bom_items:
                if not _match_opt(bi.option_filter, opt):
                    continue
                qty_per = _sn(bi.quantity)
                up = _sn(bi.unit_price)
                total_qty = qty_per * quantity
                total_price = up * total_qty
                unit_cost += up * qty_per
                items.append({
                    "item_name": _s(bi.item_name),
                    "item_spec": _s(bi.item_spec),
                    "qty_per_unit": qty_per,
                    "total_qty": total_qty,
                    "unit_price": int(up),
                    "total_price": int(total_price),
                })

            return json.dumps({
                "bom_id": bom_id,
                "product_name": _s(bom.product_name),
                "quantity": quantity,
                "unit_cost": int(unit_cost),
                "total_cost": int(unit_cost * quantity),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_items(
        category: Optional[str] = None,
        search: Optional[str] = None,
        has_stock: Optional[bool] = None,
        limit: int = 100,
    ) -> str:
        """품목 목록 조회. 카테고리, 검색어, 재고 유무로 필터링합니다."""
        from modules.models.entities import Item
        session = get_session()
        try:
            q = session.query(Item).filter(Item.is_active == True)
            if category:
                q = q.filter(Item.category.ilike(f"%{category}%"))
            if search:
                q = q.filter(
                    Item.item_name.ilike(f"%{search}%") | Item.item_spec.ilike(f"%{search}%")
                )
            if has_stock is True:
                q = q.filter(Item.stock_qty > 0)
            elif has_stock is False:
                q = q.filter(Item.stock_qty <= 0)
            items = q.order_by(Item.item_name).limit(limit).all()

            return json.dumps([{
                "id": i.id,
                "icube_item_cd": _s(i.icube_item_cd),
                "item_name": _s(i.item_name),
                "item_spec": _s(i.item_spec),
                "category": _s(i.category),
                "unit": _s(i.unit),
                "stock_qty": _sn(i.stock_qty),
                "last_unit_price": int(_sn(i.last_unit_price)),
                "manufacturer": _s(i.manufacturer),
            } for i in items], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def search_items(query: str) -> str:
        """품목 통합 검색. 품목명, 규격, 품번(iCUBE코드)을 검색합니다."""
        from modules.models.entities import Item
        session = get_session()
        try:
            items = session.query(Item).filter(
                Item.is_active == True,
                Item.item_name.ilike(f"%{query}%")
                | Item.item_spec.ilike(f"%{query}%")
                | Item.icube_item_cd.ilike(f"%{query}%"),
            ).limit(50).all()

            return json.dumps([{
                "id": i.id,
                "icube_item_cd": _s(i.icube_item_cd),
                "item_name": _s(i.item_name),
                "item_spec": _s(i.item_spec),
                "category": _s(i.category),
                "unit": _s(i.unit),
                "stock_qty": _sn(i.stock_qty),
                "last_unit_price": int(_sn(i.last_unit_price)),
            } for i in items], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_bom_stock_status(bom_id: int, quantity: int = 1) -> str:
        """BOM 기준 생산 가능 여부 확인. 소요 부품의 재고 충족 여부를 반환합니다."""
        from modules.models.entities import BomHeader, Item
        session = get_session()
        try:
            bom = session.get(BomHeader, bom_id)
            if not bom:
                return "BOM을 찾을 수 없습니다."

            shortage_items = []
            can_produce = True
            for bi in bom.bom_items:
                required = _sn(bi.quantity) * quantity
                available = 0
                item_name = _s(bi.item_name)

                if bi.item_id:
                    item = session.get(Item, bi.item_id)
                    if item:
                        available = _sn(item.stock_qty)
                        item_name = _s(item.item_name)

                if available < required:
                    can_produce = False
                    shortage_items.append({
                        "item_name": item_name,
                        "item_spec": _s(bi.item_spec),
                        "required": required,
                        "available": round(available, 2),
                        "shortage": round(required - available, 2),
                    })

            return json.dumps({
                "bom_id": bom_id,
                "product_name": _s(bom.product_name),
                "quantity": quantity,
                "can_produce": can_produce,
                "shortage_count": len(shortage_items),
                "shortage_items": shortage_items,
            }, ensure_ascii=False)
        finally:
            session.close()
