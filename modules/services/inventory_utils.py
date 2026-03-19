"""
재고관리 유틸리티 (Inventory Management Utilities).

- record_stock_movement: 모든 재고 변동의 중앙 기록 함수
- confirm_audit: 재고실사 조정 확정
- calc_turnover_rate: 재고회전율 산출
"""

import datetime
import logging

from sqlalchemy import func

from modules.models import (
    Item, StockAudit, StockAuditItem, StockMovement,
)

logger = logging.getLogger(__name__)


def record_stock_movement(db, item_id, movement_type, quantity,
                          reference_type=None, reference_id=None,
                          unit_price=None, note=None, created_by='시스템'):
    """재고 변동을 기록하고 Item.stock_qty를 갱신한다.

    Args:
        db: SQLAlchemy session
        item_id: Item.id
        movement_type: MOVEMENT_TYPES 중 하나
        quantity: 양수=입고, 음수=출고
        reference_type: 참조 테이블명 (receiving, purchase_order, stock_audit, material_order)
        reference_id: 참조 테이블 ID
        unit_price: 변동 시점 단가
        note: 비고
        created_by: 담당자명

    Returns:
        StockMovement 객체 또는 None
    """
    item = db.query(Item).get(item_id)
    if not item:
        logger.warning(f"record_stock_movement: item_id={item_id} not found")
        return None

    before_qty = item.stock_qty or 0
    item.stock_qty = before_qty + quantity
    after_qty = item.stock_qty

    movement = StockMovement(
        item_id=item_id,
        movement_type=movement_type,
        quantity=quantity,
        before_qty=before_qty,
        after_qty=after_qty,
        unit_price=unit_price,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        created_by=created_by,
    )
    db.add(movement)
    return movement


def confirm_audit(db, audit_id, confirmed_by):
    """실사 차이 항목을 일괄 조정하고 stock_qty를 갱신한다."""
    audit = db.query(StockAudit).get(audit_id)
    if not audit:
        return 0

    items = db.query(StockAuditItem).filter(
        StockAuditItem.audit_id == audit_id,
        StockAuditItem.actual_qty.isnot(None),
        StockAuditItem.is_adjusted == False,
        StockAuditItem.diff_qty != 0,
    ).all()

    adjusted_count = 0
    for ai in items:
        record_stock_movement(
            db, ai.item_id,
            movement_type='AUDIT_ADJUST',
            quantity=ai.diff_qty,
            reference_type='stock_audit',
            reference_id=audit_id,
            note=f'실사조정 ({audit.audit_no}): {ai.diff_reason or ""}',
            created_by=confirmed_by,
        )
        ai.is_adjusted = True
        ai.adjusted_at = datetime.datetime.now()
        adjusted_count += 1

    audit.status = '완료'
    audit.diff_items = adjusted_count
    return adjusted_count


def calc_turnover_rate(db, start_date, end_date, category=None):
    """재고회전율 산출.

    회전율 = 기간 내 출고수량(절대값) / 평균재고
    출고 proxy: StockMovement에서 OUT_ 타입 합산
    """
    query = db.query(
        StockMovement.item_id,
        func.sum(func.abs(StockMovement.quantity)).label('total_out')
    ).filter(
        StockMovement.movement_type.in_(['OUT_RESERVE', 'OUT_ADJUST']),
        StockMovement.created_at >= start_date,
        StockMovement.created_at <= end_date,
    ).group_by(StockMovement.item_id)

    results = []
    for item_id, total_out in query.all():
        item = db.query(Item).get(item_id)
        if not item:
            continue
        if category and item.category != category:
            continue
        avg_stock = item.stock_qty or 0
        turnover = total_out / avg_stock if avg_stock > 0 else 0
        stock_value = (item.stock_qty or 0) * (item.last_unit_price or 0)
        results.append({
            'item': item,
            'total_out': total_out,
            'avg_stock': avg_stock,
            'turnover': round(turnover, 2),
            'stock_value': stock_value,
        })
    return results
