"""
거래처 조회 Blueprint (자체 DB - PostgreSQL).

Phase 2: iCUBE 직접 쿼리 -> 자체 DB 조회로 전환.
- 거래처 목록/검색/상세 조회
- 거래처별 발주/입고 이력 (PurchaseOrderHistory / ReceivingHistory)
- 품목별 거래 이력 + 단가 추이
"""

import json
import logging
from flask import Blueprint, render_template, request, jsonify, abort
from sqlalchemy import or_, func, desc
from modules.auth_decorators import login_required, menu_required
from modules.pagination import make_pagination
from modules.utils import safe_int
from modules.db_context import get_db
from modules.models import Vendor, PurchaseOrderHistory, ReceivingHistory

logger = logging.getLogger(__name__)

vendor_bp = Blueprint('vendor', __name__)


# ===================================================================
# 헬퍼 함수
# ===================================================================
def _fmt_money(val):
    """숫자를 천단위 콤마 포맷."""
    if val is None:
        return '0'
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def _parse_items_json(items_json_str):
    """JSON 문자열을 파싱해서 리스트 반환."""
    if not items_json_str:
        return []
    try:
        return json.loads(items_json_str)
    except (json.JSONDecodeError, TypeError):
        return []


# ===================================================================
# 1. 거래처 목록
# ===================================================================
@vendor_bp.route('/vendor')
@login_required
def vendor_list():
    """거래처 목록 (검색/필터/페이지네이션)"""
    q = (request.args.get('q') or '').strip()
    use_yn = (request.args.get('use_yn') or '').strip()
    page = safe_int(request.args.get('page'), 1)
    per_page = safe_int(request.args.get('per_page'), 30)

    with get_db() as db:
        query = db.query(Vendor)

        if q:
            like_q = f"%{q}%"
            query = query.filter(or_(
                Vendor.name.ilike(like_q),
                Vendor.business_no.ilike(like_q),
                Vendor.ceo_name.ilike(like_q),
            ))

        if use_yn == 'Y':
            query = query.filter(Vendor.is_active == True)
        elif use_yn == 'N':
            query = query.filter(Vendor.is_active == False)

        total = query.count()
        pagination = make_pagination(page, per_page, total)
        offset = (pagination['page'] - 1) * per_page

        vendors = query.order_by(Vendor.name).offset(offset).limit(per_page).all()

        # 통계
        stats = {
            'total': db.query(func.count(Vendor.id)).scalar() or 0,
            'active': db.query(func.count(Vendor.id)).filter(Vendor.is_active == True).scalar() or 0,
        }

        # Vendor 객체를 dict로 변환 (템플릿 호환)
        vendor_dicts = []
        for v in vendors:
            vendor_dicts.append({
                'TR_CD': v.icube_tr_cd or str(v.id),
                'TR_NM': v.name,
                'CEO_NM': v.ceo_name,
                'REG_NB': v.business_no,
                'EMAIL': v.email,
                'TEL': v.tel,
                'FAX': v.fax,
                'DIV_ADDR1': v.address,
                'BUSINESS': v.business,
                'JONGMOK': v.jongmok,
                'USE_YN': 'Y' if v.is_active else 'N',
                'vendor_id': v.id,
                'note': v.note or '',
            })

        return render_template(
            'vendor_list.html',
            vendors=vendor_dicts,
            pagination=pagination,
            stats=stats,
            filters={'q': q, 'use_yn': use_yn},
            fmt_money=_fmt_money,
        )


# ===================================================================
# 2. 거래처 상세 + 발주/입고 이력
# ===================================================================
@vendor_bp.route('/vendor/<tr_cd>')
@login_required
def vendor_detail(tr_cd):
    """거래처 상세 + 발주/입고 이력 타임라인"""

    with get_db() as db:
        # 거래처 조회 (icube_tr_cd 또는 id로)
        vendor_obj = db.query(Vendor).filter(
            or_(Vendor.icube_tr_cd == tr_cd, Vendor.id == safe_int(tr_cd, 0))
        ).first()
        if not vendor_obj:
            abort(404)

        # dict 변환 (기존 템플릿 호환)
        vendor = {
            'TR_CD': vendor_obj.icube_tr_cd or str(vendor_obj.id),
            'TR_NM': vendor_obj.name,
            'CEO_NM': vendor_obj.ceo_name,
            'REG_NB': vendor_obj.business_no,
            'EMAIL': vendor_obj.email,
            'TEL': vendor_obj.tel,
            'FAX': vendor_obj.fax,
            'DIV_ADDR1': vendor_obj.address,
            'ADDR2': '',
            'BUSINESS': vendor_obj.business,
            'JONGMOK': vendor_obj.jongmok,
            'USE_YN': 'Y' if vendor_obj.is_active else 'N',
            'vendor_id': vendor_obj.id,
            'note': vendor_obj.note or '',
        }

        # 발주 이력 (PurchaseOrderHistory에서 vendor_tr_cd로 조회)
        po_history = db.query(PurchaseOrderHistory).filter(
            PurchaseOrderHistory.vendor_tr_cd == vendor_obj.icube_tr_cd
        ).order_by(desc(PurchaseOrderHistory.order_date)).all()

        purchase_orders = []
        for po in po_history:
            items_list = _parse_items_json(po.items_json)
            detail_rows = []
            for item in items_list:
                detail_rows.append({
                    'CLS_SQ': item.get('seq', ''),
                    'ITEM_NM': item.get('item_name', ''),
                    'ITEM_CD': item.get('item_cd', ''),
                    'ITEM_DC': item.get('spec', ''),
                    'UNIT_DC': item.get('unit', ''),
                    'CLS_QT': item.get('qty', 0),
                    'CLS_UM': item.get('unit_price', 0),
                    'CLSH_AM': item.get('amount', 0),
                    'ITEM_REMARK': item.get('remark', ''),
                })
            purchase_orders.append({
                'CLS_NB': po.icube_cls_nb,
                'CLS_DT': po.order_date.strftime('%Y-%m-%d') if po.order_date else '',
                'REMARK_DC': po.remark or '',
                'detail_rows': detail_rows,
                'total': int(po.total_amount or 0),
            })

        # 입고 이력 (ReceivingHistory에서 vendor_tr_cd로 조회)
        rcv_history = db.query(ReceivingHistory).filter(
            ReceivingHistory.vendor_tr_cd == vendor_obj.icube_tr_cd
        ).order_by(desc(ReceivingHistory.receive_date)).all()

        receivings = []
        for rcv in rcv_history:
            items_list = _parse_items_json(rcv.items_json)
            detail_rows = []
            for item in items_list:
                detail_rows.append({
                    'RCV_SQ': item.get('seq', ''),
                    'ITEM_NM': item.get('item_name', ''),
                    'ITEM_CD': item.get('item_cd', ''),
                    'ITEM_DC': item.get('spec', ''),
                    'UNIT_DC': item.get('unit', ''),
                    'RCV_QT': item.get('qty', 0),
                    'RCV_UM': item.get('unit_price', 0),
                    'RCVH_AM': item.get('amount', 0),
                    'REMARK_DC': item.get('remark', ''),
                })
            receivings.append({
                'RCV_NB': rcv.icube_rcv_nb,
                'RCV_DT': rcv.receive_date.strftime('%Y-%m-%d') if rcv.receive_date else '',
                'WH_CD': rcv.warehouse or '',
                'detail_rows': detail_rows,
                'total': int(rcv.total_amount or 0),
            })

        # 거래 통계
        trade_stats = {
            'po_count': len(purchase_orders),
            'po_total': sum(po['total'] for po in purchase_orders),
            'rcv_count': len(receivings),
            'rcv_total': sum(rcv['total'] for rcv in receivings),
            'last_po_date': purchase_orders[0]['CLS_DT'] if purchase_orders else '-',
            'last_rcv_date': receivings[0]['RCV_DT'] if receivings else '-',
        }

        def _fmt_date(dt_str):
            return dt_str  # 이미 포맷된 상태

        return render_template(
            'vendor_detail.html',
            vendor=vendor,
            purchase_orders=purchase_orders,
            receivings=receivings,
            trade_stats=trade_stats,
            fmt_date=_fmt_date,
            fmt_money=_fmt_money,
        )


# ===================================================================
# 3-1. 업체 메모 저장 (AJAX)
# ===================================================================
@vendor_bp.route('/api/vendor/<int:vendor_id>/note', methods=['POST'])
@login_required
@menu_required('vendor')
def api_vendor_note(vendor_id):
    """거래처 메모 저장"""
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        vendor = db.query(Vendor).get(vendor_id)
        if not vendor:
            return jsonify({'error': '거래처를 찾을 수 없습니다.'}), 404
        vendor.note = (data.get('note') or '').strip() or None
        db.commit()
        return jsonify({'ok': True})


