"""FR-08: MCP Resources (4개)"""
import os
import json

from mcp.server.fastmcp import FastMCP

from ..db import get_session
from ..tools._helpers import _s


def register(mcp: FastMCP):

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

## quotations — 견적서
quote_no, quote_date, project_name, customer_name
total_amount, grand_total, surcharges_json, status

## quotation_items — 견적 품목
quotation_id, seq, item_name, item_spec, quantity, unit_price, amount

## deliveries — 납품
project_id, contract_id, delivery_status, inspection_status
planned_total_qty, delivered_total_qty, contact_name

## delivery_splits — 납품 분할
delivery_id, split_no, quantity, scheduled_date, confirmed_date, status

## contracts — 계약
project_id, contract_name, item_group, contract_date
delivery_due_date, g2b_contract_no, payment_status

## contract_items — 계약 품목
contract_id, category, model_name, quantity
status_sales, status_admin, status_prod

## warranty_cases — 하자/AS 케이스
warranty_id, project_id, case_no, defect_type, symptom, status
reported_date, site_visit_date, completed_date, assigned_to

## drawings — 도면
project_id, title, drawing_type, created_by

## drawing_versions — 도면 버전
drawing_id, version_no, is_latest, dwg_path, pdf_path

## product_catalogs — 제품 카탈로그
item_name, model_name, spec, manufacturer
unit_price, price_source, g2b_cntrct_no

## daily_reports — 일일업무보고
report_date, department, reporter_name
headcount_total, headcount_present, items_json, auto_items_json

## notifications — 알림
user_id, title, message, noti_type, link, is_read
"""
