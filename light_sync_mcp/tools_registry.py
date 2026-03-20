"""모든 tool/resource를 FastMCP 인스턴스에 등록"""
import json
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .db import get_session


def _s(val, default=""):
    return val if val is not None else default


def _sn(val, default=0.0):
    return float(val) if val is not None else default


def _sd(val):
    return val.isoformat() if val else ""


def register_all(mcp: FastMCP):
    _register_inventory(mcp)
    _register_bom(mcp)
    _register_project(mcp)
    _register_production(mcp)
    _register_financial(mcp)
    _register_procurement(mcp)
    _register_resources(mcp)


# ─────────────────────────────────────────────────────────────────────────────
# FR-04: 재고 도메인 (5개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_inventory(mcp: FastMCP):

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
        """재고 평가액 (재고수량 × 최근단가). 분류별 합산 결과를 반환합니다."""
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


# ─────────────────────────────────────────────────────────────────────────────
# FR-03: BOM/품목 도메인 (6개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_bom(mcp: FastMCP):

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
        """BOM 원가 계산. 생산 수량 × 단가 합산으로 총 원가를 계산합니다.
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
                        available = _sn(item.stock_qty) - _sn(item.reserved_qty)
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


# ─────────────────────────────────────────────────────────────────────────────
# FR-02: 현장/프로젝트 도메인 (5개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_project(mcp: FastMCP):

    @mcp.tool()
    def get_projects(
        status: Optional[str] = None,
        is_contracted: Optional[bool] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """현장 목록 조회. 상태, 계약 여부, 연도, 월, 검색어로 필터링합니다.
        status 예: '설계/영업', '계약', '생산', '납품완료'
        month: 1~12 (year와 함께 사용)
        """
        from modules.models.entities import Project
        from sqlalchemy import extract
        session = get_session()
        try:
            q = session.query(Project)
            if status:
                q = q.filter(Project.status.ilike(f"%{status}%"))
            if is_contracted is not None:
                q = q.filter(Project.is_contracted == is_contracted)
            if year:
                q = q.filter(extract("year", Project.created_at) == year)
            if month:
                q = q.filter(extract("month", Project.created_at) == month)
            if search:
                q = q.filter(
                    Project.temp_name.ilike(f"%{search}%")
                    | Project.short_name.ilike(f"%{search}%")
                    | Project.site_address.ilike(f"%{search}%")
                )
            projects = q.order_by(Project.created_at.desc()).limit(limit).all()

            return json.dumps([{
                "id": p.id,
                "project_no": _s(p.project_no),
                "temp_name": _s(p.temp_name),
                "short_name": _s(p.short_name),
                "status": _s(p.status),
                "is_contracted": p.is_contracted,
                "is_urgent": p.is_urgent,
                "contract_date": _sd(p.contract_date),
                "site_address": _s(p.site_address),
                "created_at": _sd(p.created_at),
            } for p in projects], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_project_detail(
        project_id: Optional[int] = None,
        project_no: Optional[str] = None,
    ) -> str:
        """현장 상세 조회. 계약, 납품 정보를 포함합니다.
        project_id 또는 project_no 중 하나는 필수.
        """
        from modules.models.entities import Project
        session = get_session()
        try:
            if project_id:
                p = session.get(Project, project_id)
            elif project_no:
                p = session.query(Project).filter(Project.project_no == project_no).first()
            else:
                return "project_id 또는 project_no가 필요합니다."

            if not p:
                return "현장을 찾을 수 없습니다."

            contracts = [{
                "id": c.id,
                "contract_amount": int(c.contract_amount) if hasattr(c, "contract_amount") and c.contract_amount else 0,
                "delivery_date": _sd(c.delivery_date) if hasattr(c, "delivery_date") else "",
            } for c in p.contracts]

            deliveries = [{
                "id": d.id,
                "status": _s(d.status) if hasattr(d, "status") else "",
            } for d in p.deliveries]

            return json.dumps({
                "id": p.id,
                "project_no": _s(p.project_no),
                "temp_name": _s(p.temp_name),
                "short_name": _s(p.short_name),
                "status": _s(p.status),
                "is_contracted": p.is_contracted,
                "is_urgent": p.is_urgent,
                "site_address": _s(p.site_address),
                "shipping_address": _s(p.shipping_address),
                "design_basis": _s(p.design_basis),
                "site_memo": _s(p.site_memo),
                "contract_date": _sd(p.contract_date),
                "spec_confirmed": p.spec_confirmed,
                "created_at": _sd(p.created_at),
                "contracts": contracts,
                "deliveries": deliveries,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def search_projects(query: str) -> str:
        """현장 통합 검색. 현장명, 약칭, 주소, 관리번호로 검색합니다."""
        from modules.models.entities import Project
        session = get_session()
        try:
            projects = session.query(Project).filter(
                Project.temp_name.ilike(f"%{query}%")
                | Project.short_name.ilike(f"%{query}%")
                | Project.site_address.ilike(f"%{query}%")
                | Project.project_no.ilike(f"%{query}%")
            ).order_by(Project.created_at.desc()).limit(30).all()

            return json.dumps([{
                "id": p.id,
                "project_no": _s(p.project_no),
                "temp_name": _s(p.temp_name),
                "short_name": _s(p.short_name),
                "status": _s(p.status),
                "is_contracted": p.is_contracted,
                "site_address": _s(p.site_address),
            } for p in projects], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_project_timeline(project_id: int) -> str:
        """현장별 납품/생산 타임라인 조회."""
        from modules.models.entities import Project
        session = get_session()
        try:
            p = session.get(Project, project_id)
            if not p:
                return "현장을 찾을 수 없습니다."

            deliveries = [{
                "type": "납품",
                "status": _s(d.status) if hasattr(d, "status") else "",
            } for d in p.deliveries]

            return json.dumps({
                "project_id": project_id,
                "project_name": _s(p.temp_name),
                "status": _s(p.status),
                "timeline": deliveries,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_delivery_summary(year: int, month: Optional[int] = None, project_id: Optional[int] = None) -> str:
        """현장별 납품집계. 연월 기준 납품 실적(G2B 조달내역)을 반환합니다."""
        from modules.models.entities import G2bProcurement, Project
        from sqlalchemy import func, extract
        session = get_session()
        try:
            q = session.query(
                G2bProcurement.project_id,
                func.sum(G2bProcurement.total_amount).label("total_amount"),
                func.count(G2bProcurement.id).label("count"),
            ).filter(extract("year", G2bProcurement.contract_date) == year)
            if month:
                q = q.filter(extract("month", G2bProcurement.contract_date) == month)
            if project_id:
                q = q.filter(G2bProcurement.project_id == project_id)
            rows = q.group_by(G2bProcurement.project_id).all()

            items = []
            total = 0
            for row in rows:
                proj = session.get(Project, row.project_id) if row.project_id else None
                amount = int(row.total_amount or 0)
                total += amount
                items.append({
                    "project_id": row.project_id,
                    "project_name": _s(proj.temp_name) if proj else "미연결",
                    "count": row.count,
                    "total_amount": amount,
                })
            items.sort(key=lambda x: x["total_amount"], reverse=True)

            return json.dumps({
                "year": year,
                "month": month,
                "grand_total": total,
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()


    @mcp.tool()
    def get_overdue_projects() -> str:
        """납기 지난 현장 목록. 계약 납기일이 오늘보다 이전이고 아직 완료되지 않은 현장을 반환합니다.
        납기일 초과 일수(days_overdue) 기준 내림차순 정렬.
        """
        import datetime
        from modules.models.entities import Project, Contract
        session = get_session()
        try:
            today = datetime.date.today()
            contracts = session.query(Contract).filter(
                Contract.delivery_due_date < today,
                Contract.delivery_due_date != None,
            ).all()

            result = []
            seen = set()
            for c in contracts:
                proj = session.get(Project, c.project_id) if c.project_id else None
                if not proj:
                    continue
                if proj.status in ("납품완료", "완료", "취소"):
                    continue
                if proj.id in seen:
                    continue
                seen.add(proj.id)

                delivery_date = c.delivery_due_date
                days_overdue = (today - delivery_date).days
                result.append({
                    "project_id": proj.id,
                    "project_no": _s(proj.project_no),
                    "project_name": _s(proj.temp_name),
                    "short_name": _s(proj.short_name),
                    "status": _s(proj.status),
                    "delivery_date": delivery_date.isoformat(),
                    "days_overdue": days_overdue,
                    "is_urgent": proj.is_urgent,
                    "site_address": _s(proj.site_address),
                })

            result.sort(key=lambda x: x["days_overdue"], reverse=True)
            return json.dumps({
                "today": today.isoformat(),
                "overdue_count": len(result),
                "projects": result,
            }, ensure_ascii=False)
        finally:
            session.close()


# ─────────────────────────────────────────────────────────────────────────────
# FR-05: 생산 도메인 (4개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_production(mcp: FastMCP):

    @mcp.tool()
    def get_production_status(
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """생산 현황 조회. 현장별, 품목별 공정 진행 상태를 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            q = session.query(ProductionProcess)
            if project_id:
                q = q.filter(ProductionProcess.project_id == project_id)
            if status:
                q = q.filter(ProductionProcess.status.ilike(f"%{status}%"))
            processes = q.order_by(ProductionProcess.id.desc()).limit(limit).all()

            result = []
            for pr in processes:
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                row = {"id": pr.id, "project_name": _s(proj.temp_name) if proj else ""}
                for col in ["project_id", "status", "stage", "item_name", "quantity",
                            "worker_name", "note"]:
                    if hasattr(pr, col):
                        row[col] = _s(getattr(pr, col))
                for col in ["start_date", "end_date"]:
                    if hasattr(pr, col):
                        row[col] = _sd(getattr(pr, col))
                result.append(row)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_production_by_site() -> str:
        """현장별 생산 카드 목록. 현장별로 그룹핑된 생산 공정을 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            processes = session.query(ProductionProcess).all()
            by_project = {}
            for pr in processes:
                pid = pr.project_id or 0
                if pid not in by_project:
                    proj = session.get(Project, pid) if pid else None
                    by_project[pid] = {
                        "project_id": pid,
                        "project_name": _s(proj.temp_name) if proj else "미연결",
                        "processes": [],
                    }
                row = {"id": pr.id}
                for col in ["status", "stage", "item_name", "quantity", "worker_name"]:
                    if hasattr(pr, col):
                        row[col] = _s(getattr(pr, col))
                by_project[pid]["processes"].append(row)

            return json.dumps(list(by_project.values()), ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_worker_assignments() -> str:
        """작업자 배치 현황. 진행 중인 생산 공정의 담당자별 작업 목록을 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            processes = session.query(ProductionProcess).all()
            by_worker = {}
            for pr in processes:
                worker = _s(pr.worker_name) if hasattr(pr, "worker_name") else "미배정"
                if not worker:
                    worker = "미배정"
                if worker not in by_worker:
                    by_worker[worker] = {"worker_name": worker, "tasks": []}
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                by_worker[worker]["tasks"].append({
                    "process_id": pr.id,
                    "project_name": _s(proj.temp_name) if proj else "",
                    "stage": _s(pr.stage) if hasattr(pr, "stage") else "",
                    "status": _s(pr.status) if hasattr(pr, "status") else "",
                    "item_name": _s(pr.item_name) if hasattr(pr, "item_name") else "",
                })
            return json.dumps(list(by_worker.values()), ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_fab_status() -> str:
        """FAB 공정 현황. FAB 단계의 생산 공정 목록을 반환합니다."""
        from modules.models.entities import ProductionProcess, Project
        session = get_session()
        try:
            q = session.query(ProductionProcess)
            if hasattr(ProductionProcess, "stage"):
                q = q.filter(ProductionProcess.stage.ilike("%FAB%"))
            processes = q.all()

            result = []
            for pr in processes:
                proj = session.get(Project, pr.project_id) if pr.project_id else None
                row = {"id": pr.id, "project_name": _s(proj.temp_name) if proj else ""}
                for col in ["status", "stage", "item_name", "quantity", "worker_name", "note"]:
                    if hasattr(pr, col):
                        row[col] = _s(getattr(pr, col))
                result.append(row)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()


# ─────────────────────────────────────────────────────────────────────────────
# FR-06: 재무 도메인 (4개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_financial(mcp: FastMCP):

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
    ) -> str:
        """세금계산서 목록 조회. G2B 매칭 상태, 수금 상태로 필터링합니다.
        payment_status: 미수금 / 부분입금 / 입금완료
        """
        from modules.models.entities import TaxInvoice
        from sqlalchemy import extract
        session = get_session()
        try:
            q = session.query(TaxInvoice)
            if year:
                q = q.filter(extract("year", TaxInvoice.issue_date) == year)
            if month:
                q = q.filter(extract("month", TaxInvoice.issue_date) == month)
            if payment_status and hasattr(TaxInvoice, "payment_status"):
                q = q.filter(TaxInvoice.payment_status == payment_status)
            invoices = q.order_by(TaxInvoice.issue_date.desc()).limit(limit).all()

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
    def get_unpaid_invoices(limit: int = 50) -> str:
        """미수금 현황. 수금되지 않은 세금계산서 목록과 합계를 반환합니다."""
        from modules.models.entities import TaxInvoice
        session = get_session()
        try:
            q = session.query(TaxInvoice)
            if hasattr(TaxInvoice, "payment_status"):
                q = q.filter(TaxInvoice.payment_status.in_(["미수금", "부분입금"]))
            invoices = q.order_by(TaxInvoice.issue_date.desc()).limit(limit).all()

            items = [{
                "id": inv.id,
                "approval_no": _s(inv.approval_no),
                "issue_date": _sd(inv.issue_date),
                "buyer_name": _s(inv.buyer_name),
                "total_amount": int(inv.total_amount or 0),
                "payment_status": _s(inv.payment_status) if hasattr(inv, "payment_status") else "",
            } for inv in invoices]

            return json.dumps({
                "total_unpaid": sum(i["total_amount"] for i in items),
                "count": len(items),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()


# ─────────────────────────────────────────────────────────────────────────────
# FR-07: 조달/발주 도메인 (4개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_procurement(mcp: FastMCP):

    @mcp.tool()
    def get_purchase_orders(
        status: Optional[str] = None,
        vendor_id: Optional[int] = None,
        project_id: Optional[int] = None,
        limit: int = 50,
    ) -> str:
        """발주서 목록 조회. 상태, 거래처, 현장으로 필터링합니다.
        status 예: 작성중, 발송완료, 입고대기, 입고완료, 취소
        """
        from modules.models.entities import PurchaseOrder
        session = get_session()
        try:
            q = session.query(PurchaseOrder)
            if status:
                q = q.filter(PurchaseOrder.status == status)
            if vendor_id:
                q = q.filter(PurchaseOrder.vendor_id == vendor_id)
            if project_id:
                q = q.filter(PurchaseOrder.project_id == project_id)
            orders = q.order_by(PurchaseOrder.po_date.desc()).limit(limit).all()

            return json.dumps([{
                "id": po.id,
                "po_no": _s(po.po_no),
                "po_date": _sd(po.po_date),
                "status": _s(po.status),
                "vendor_name": _s(po.vendor.vendor_name) if po.vendor else "",
                "project_name": _s(po.project.temp_name) if po.project else "",
                "total_amount": int(po.total_amount or 0),
                "item_count": len(po.items),
                "note": _s(po.note),
            } for po in orders], ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_po_detail(
        po_id: Optional[int] = None,
        po_no: Optional[str] = None,
    ) -> str:
        """발주서 상세 조회. 발주 품목 목록과 금액을 포함합니다.
        po_id 또는 po_no 중 하나는 필수.
        """
        from modules.models.entities import PurchaseOrder
        session = get_session()
        try:
            if po_id:
                po = session.get(PurchaseOrder, po_id)
            elif po_no:
                po = session.query(PurchaseOrder).filter(PurchaseOrder.po_no == po_no).first()
            else:
                return "po_id 또는 po_no가 필요합니다."

            if not po:
                return "발주서를 찾을 수 없습니다."

            items = [{
                "item_name": _s(i.item_name),
                "item_spec": _s(i.item_spec),
                "quantity": float(i.quantity or 0),
                "unit": _s(i.unit),
                "unit_price": int(i.unit_price or 0),
                "amount": int(i.amount or 0),
                "delivery_date": _sd(i.delivery_date),
            } for i in po.items]

            return json.dumps({
                "id": po.id,
                "po_no": _s(po.po_no),
                "po_date": _sd(po.po_date),
                "status": _s(po.status),
                "vendor_name": _s(po.vendor.vendor_name) if po.vendor else "",
                "project_name": _s(po.project.temp_name) if po.project else "",
                "total_amount": int(po.total_amount or 0),
                "tax_amount": int(po.tax_amount or 0),
                "note": _s(po.note),
                "items": items,
            }, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_receiving_history(
        vendor_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """입고 이력 조회. 입고일, 거래처별 입고 내역을 반환합니다.
        date_from / date_to: YYYY-MM-DD 형식
        """
        from modules.models.entities import Receiving
        session = get_session()
        try:
            q = session.query(Receiving)
            if vendor_id:
                q = q.filter(Receiving.vendor_id == vendor_id)
            if date_from:
                q = q.filter(Receiving.rcv_date >= date_from)
            if date_to:
                q = q.filter(Receiving.rcv_date <= date_to)
            receivings = q.order_by(Receiving.rcv_date.desc()).limit(limit).all()

            result = []
            for rcv in receivings:
                items = [{
                    "item_name": _s(i.item_name),
                    "item_spec": _s(i.item_spec),
                    "received_qty": float(i.received_qty or 0),
                    "unit_price": int(i.unit_price or 0),
                    "amount": int(i.amount or 0),
                } for i in rcv.items]
                result.append({
                    "id": rcv.id,
                    "rcv_no": _s(rcv.rcv_no),
                    "rcv_date": _sd(rcv.rcv_date),
                    "status": _s(rcv.status),
                    "vendor_name": _s(rcv.vendor.vendor_name) if rcv.vendor else "",
                    "total_amount": sum(i["amount"] for i in items),
                    "items": items,
                })
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_vendor_list(search: Optional[str] = None) -> str:
        """거래처 목록 조회. 거래처명, 담당자, 연락처를 반환합니다."""
        from modules.models.entities import Vendor
        session = get_session()
        try:
            q = session.query(Vendor)
            if search:
                q = q.filter(Vendor.vendor_name.ilike(f"%{search}%"))
            vendors = q.order_by(Vendor.vendor_name).all()

            result = []
            for v in vendors:
                row = {"id": v.id}
                for col in ["vendor_name", "vendor_type", "contact_name", "contact_phone",
                            "contact_email", "business_no", "address"]:
                    if hasattr(v, col):
                        row[col] = _s(getattr(v, col))
                result.append(row)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()


# ─────────────────────────────────────────────────────────────────────────────
# FR-08: MCP Resources (4개)
# ─────────────────────────────────────────────────────────────────────────────

def _register_resources(mcp: FastMCP):

    @mcp.resource("magnatech://process")
    def get_process_doc() -> str:
        """MAGNATECH 생산 공정 설명서"""
        doc_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs", "magnatech_memory.md"
        )
        if os.path.exists(doc_path):
            with open(doc_path, encoding="utf-8") as f:
                return f.read()
        return """# MAGNATECH 생산 공정

## 주요 단계
1. 설계/영업 → 2. 자재 발주 → 3. FAB(조립) → 4. 검사 → 5. 납품
"""

    @mcp.resource("magnatech://products")
    def get_products_doc() -> str:
        """MAGNATECH 제품 사양 목록 (BOM 기준)"""
        session = get_session()
        try:
            from modules.models.entities import BomHeader
            boms = session.query(BomHeader).filter(BomHeader.is_active == True).all()
            products = [{
                "product_code": b.product_code,
                "product_name": b.product_name,
                "product_category": _s(b.product_category),
                "version": _s(b.version),
                "certification_no": _s(b.certification_no),
            } for b in boms]
            return json.dumps(products, ensure_ascii=False)
        finally:
            session.close()

    @mcp.resource("magnatech://certifications")
    def get_certifications() -> str:
        """제품 인증번호 목록"""
        session = get_session()
        try:
            from modules.models.entities import BomHeader
            boms = session.query(BomHeader).filter(
                BomHeader.is_active == True,
                BomHeader.certification_no != None,
                BomHeader.certification_no != "",
            ).all()
            return json.dumps([{
                "product_code": b.product_code,
                "product_name": b.product_name,
                "certification_no": b.certification_no,
            } for b in boms], ensure_ascii=False)
        finally:
            session.close()

    @mcp.resource("lightsync://schema")
    def get_schema_doc() -> str:
        """ERP DB 스키마 요약. 주요 테이블 구조와 컬럼을 설명합니다."""
        return """# Light-Sync ERP 주요 테이블 스키마

## projects — 현장
project_no(관리번호), temp_name(현장가칭), short_name(약칭)
status(설계/영업|계약|생산|납품완료), is_contracted, is_urgent
site_address, contract_date

## items — 품목 마스터
icube_item_cd(품번), item_name, item_spec, category, unit
stock_qty(재고), reserved_qty(예약), safety_stock(안전재고), last_unit_price

## bom_headers — BOM 마스터
product_code, product_name, product_category, version
certification_no, option_schema(JSON: 슈퍼BOM 옵션정의)

## bom_items — BOM 부품
bom_id, item_id, item_name, item_spec, quantity(소요량/개), unit_price
option_filter(JSON: null=공통부품, {key:val}=옵션부품)

## stock_movements — 재고변동
item_id, movement_type(IN|OUT|ADJUST), quantity
before_qty, after_qty, reference_type, reference_id

## purchase_orders — 발주서
po_no, po_date, vendor_id, project_id
status(작성중|발송완료|입고대기|입고완료|취소), total_amount

## receivings — 입고
rcv_no, rcv_date, vendor_id, po_id, status(검수대기|검수완료|반품)

## tax_invoices — 세금계산서
approval_no, issue_date, buyer_name
supply_amount, tax_amount, total_amount
payment_status(미수금|부분입금|입금완료), match_status(자동매칭|수동매칭|미매칭)

## production_processes — 생산공정
project_id, stage, status, item_name, quantity, worker_name, start_date, end_date

## vendors — 거래처
vendor_name, vendor_type, contact_name, contact_phone, contact_email

## g2b_procurements — G2B 조달내역
project_id, contract_date, total_amount, product_name
"""
