"""FR-04: 재고 도메인 Tools (5개)"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ._helpers import _s, _sn, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def get_inventory(
        category: Optional[str] = None,
        low_stock_only: bool = False,
        search: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """현재 재고 현황 조회. 품목별 재고수량, 예약수량, 가용수량, 안전재고를 반환합니다.
        category: 품목 분류 필터 (예: 드라이버, LED모듈, 하우징)
        low_stock_only: True이면 안전재고 미달 품목만
        search: 품목명 검색어
        """
        from modules.models.entities import Item
        session = get_session()
        try:
            q = session.query(Item).filter(Item.is_active == True)
            if category:
                q = q.filter(Item.category.ilike(f"%{category}%"))
            if search:
                q = q.filter(Item.item_name.ilike(f"%{search}%"))
            if low_stock_only:
                q = q.filter(Item.safety_stock > 0, Item.stock_qty < Item.safety_stock)
            items = q.order_by(Item.item_name).limit(limit).all()

            result = []
            for item in items:
                available = _sn(item.stock_qty) - _sn(item.reserved_qty)
                result.append({
                    "id": item.id,
                    "item_name": _s(item.item_name),
                    "item_spec": _s(item.item_spec),
                    "category": _s(item.category),
                    "unit": _s(item.unit),
                    "stock_qty": _sn(item.stock_qty),
                    "reserved_qty": _sn(item.reserved_qty),
                    "available_qty": round(available, 2),
                    "safety_stock": _sn(item.safety_stock),
                    "last_unit_price": int(_sn(item.last_unit_price)),
                    "is_low_stock": _sn(item.stock_qty) < _sn(item.safety_stock) and _sn(item.safety_stock) > 0,
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_low_stock() -> str:
        """안전재고 미달 품목 목록. 부족량 큰 순으로 정렬합니다."""
        from modules.models.entities import Item
        session = get_session()
        try:
            items = session.query(Item).filter(
                Item.is_active == True,
                Item.safety_stock > 0,
                Item.stock_qty < Item.safety_stock,
            ).all()
            result = []
            for item in items:
                shortage = _sn(item.safety_stock) - _sn(item.stock_qty)
                result.append({
                    "id": item.id,
                    "item_name": _s(item.item_name),
                    "item_spec": _s(item.item_spec),
                    "category": _s(item.category),
                    "unit": _s(item.unit),
                    "stock_qty": _sn(item.stock_qty),
                    "safety_stock": _sn(item.safety_stock),
                    "shortage": round(shortage, 2),
                })
            result.sort(key=lambda x: x["shortage"], reverse=True)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_inventory_turnover(year: int, month: Optional[int] = None) -> str:
        """재고 회전율 분석. 지정 기간의 출고 이력 기반으로 품목별 회전율을 계산합니다.
        year: 조회 연도, month: 조회 월 (생략 시 연간 전체)
        """
        from modules.models.entities import Item, StockMovement
        from sqlalchemy import func, extract
        session = get_session()
        try:
            q = session.query(
                StockMovement.item_id,
                func.sum(StockMovement.quantity).label("total_out"),
            ).filter(
                StockMovement.movement_type == "OUT",
                extract("year", StockMovement.created_at) == year,
            )
            if month:
                q = q.filter(extract("month", StockMovement.created_at) == month)
            rows = q.group_by(StockMovement.item_id).all()

            result = []
            for row in rows:
                item = session.get(Item, row.item_id)
                if not item:
                    continue
                avg_stock = _sn(item.stock_qty)
                turnover = round(row.total_out / avg_stock, 2) if avg_stock > 0 else 0
                result.append({
                    "item_id": row.item_id,
                    "item_name": _s(item.item_name),
                    "category": _s(item.category),
                    "total_out": round(float(row.total_out), 2),
                    "current_stock": avg_stock,
                    "turnover_rate": turnover,
                })
            result.sort(key=lambda x: x["turnover_rate"], reverse=True)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_stock_movements(
        item_id: Optional[int] = None,
        movement_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """재고 변동 이력 조회 (입고/출고/조정).
        movement_type: IN / OUT / ADJUST
        date_from / date_to: YYYY-MM-DD 형식
        """
        from modules.models.entities import Item, StockMovement
        session = get_session()
        try:
            q = session.query(StockMovement)
            if item_id:
                q = q.filter(StockMovement.item_id == item_id)
            if movement_type:
                q = q.filter(StockMovement.movement_type == movement_type)
            if date_from:
                q = q.filter(StockMovement.created_at >= date_from)
            if date_to:
                q = q.filter(StockMovement.created_at <= date_to + " 23:59:59")
            movements = q.order_by(StockMovement.created_at.desc()).limit(limit).all()

            result = []
            for m in movements:
                item = session.get(Item, m.item_id)
                result.append({
                    "id": m.id,
                    "date": _sd(m.created_at),
                    "item_name": _s(item.item_name) if item else "",
                    "movement_type": _s(m.movement_type),
                    "quantity": _sn(m.quantity),
                    "before_qty": _sn(m.before_qty),
                    "after_qty": _sn(m.after_qty),
                    "reference_type": _s(m.reference_type),
                    "note": _s(m.note),
                    "created_by": _s(m.created_by),
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_inventory_valuation(category: Optional[str] = None) -> str:
        """재고 평가액 (재고수량 x 최근단가). 분류별 합산 결과를 반환합니다."""
        from modules.models.entities import Item
        session = get_session()
        try:
            q = session.query(Item).filter(Item.is_active == True)
            if category:
                q = q.filter(Item.category.ilike(f"%{category}%"))
            items = q.all()

            total_val = 0
            by_cat = {}
            for item in items:
                val = _sn(item.stock_qty) * _sn(item.last_unit_price)
                total_val += val
                cat = _s(item.category, "미분류")
                if cat not in by_cat:
                    by_cat[cat] = {"category": cat, "count": 0, "valuation": 0}
                by_cat[cat]["count"] += 1
                by_cat[cat]["valuation"] += val

            cat_list = sorted(by_cat.values(), key=lambda x: x["valuation"], reverse=True)
            for c in cat_list:
                c["valuation"] = int(c["valuation"])

            return json.dumps({
                "total_valuation": int(total_val),
                "item_count": len(items),
                "by_category": cat_list,
            }, ensure_ascii=False)
        finally:
            session.close()
