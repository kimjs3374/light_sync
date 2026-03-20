"""FR-08: MCP Resources (4개)"""
import os
import json
from mcp.server import Server
from mcp.types import Resource, TextContent

from ..db import get_session


def register(server: Server):

    @server.list_resources()
    async def list_resources():
        return [
            Resource(
                uri="magnatech://process",
                name="MAGNATECH 생산 공정",
                description="MAGNATECH LED 조명 생산 공정 설명 및 단계별 가이드",
                mimeType="text/plain",
            ),
            Resource(
                uri="magnatech://products",
                name="MAGNATECH 제품 사양",
                description="BOM 기준 제품 목록 및 사양 요약",
                mimeType="application/json",
            ),
            Resource(
                uri="magnatech://certifications",
                name="제품 인증번호 목록",
                description="BOM에 등록된 제품별 인증번호",
                mimeType="application/json",
            ),
            Resource(
                uri="lightsync://schema",
                name="ERP DB 스키마 요약",
                description="Light-Sync ERP 주요 테이블 구조 요약",
                mimeType="text/plain",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str):
        if uri == "magnatech://process":
            return await _get_process_doc()
        elif uri == "magnatech://products":
            return await _get_products_doc()
        elif uri == "magnatech://certifications":
            return await _get_certifications()
        elif uri == "lightsync://schema":
            return await _get_schema_doc()
        return [TextContent(type="text", text=f"Unknown resource: {uri}")]


async def _get_process_doc():
    # docs/magnatech_memory.md 파일 읽기 시도
    doc_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "docs", "magnatech_memory.md"
    )
    if os.path.exists(doc_path):
        with open(doc_path, encoding="utf-8") as f:
            content = f.read()
        return [TextContent(type="text", text=content)]

    # 파일 없으면 기본 설명 반환
    return [TextContent(type="text", text="""# MAGNATECH 생산 공정

## 주요 공정 단계

### 1단계: 설계/영업
- 고객 요구사항 파악 및 시방서 검토
- 제품 사양 확정 (LED 모듈, 드라이버, 하우징 선정)
- 견적 및 계약

### 2단계: 자재 발주
- BOM 기준 소요자재 산출
- 거래처 발주서 작성 및 발송
- 입고 검수

### 3단계: FAB (조립)
- LED 모듈 + 드라이버 + 하우징 조립
- 전기 배선 작업

### 4단계: 검사
- 광학 검사 (조도, 색온도)
- 전기 안전 검사
- 인증 기준 적합성 확인

### 5단계: 납품
- 포장 및 출하
- 현장 설치 지원 (필요 시)
- 시운전 및 완료 확인
""")]


async def _get_products_doc():
    session = get_session()
    try:
        from modules.models.entities import BomHeader
        boms = session.query(BomHeader).filter(BomHeader.is_active == True).all()
        products = [{
            "product_code": bom.product_code,
            "product_name": bom.product_name,
            "product_category": bom.product_category or "",
            "version": bom.version or "1.0",
            "certification_no": bom.certification_no or "",
            "item_count": len(bom.bom_items),
        } for bom in boms]
        return [TextContent(type="text", text=json.dumps(products, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_certifications():
    session = get_session()
    try:
        from modules.models.entities import BomHeader
        boms = session.query(BomHeader).filter(
            BomHeader.is_active == True,
            BomHeader.certification_no != None,
            BomHeader.certification_no != "",
        ).all()
        certs = [{
            "product_code": bom.product_code,
            "product_name": bom.product_name,
            "certification_no": bom.certification_no,
        } for bom in boms]
        return [TextContent(type="text", text=json.dumps(certs, ensure_ascii=False, indent=2))]
    finally:
        session.close()


async def _get_schema_doc():
    schema = """# Light-Sync ERP 주요 테이블 스키마

## projects (현장)
- id, project_no(관리번호), temp_name(현장가칭), short_name(약칭)
- status(설계/영업|계약|생산|납품완료), is_contracted, is_urgent
- site_address, contract_date, created_at

## contracts (계약)
- id, project_id → projects, contract_no, contract_amount, delivery_date

## items (품목 마스터)
- id, icube_item_cd(품번), item_name, item_spec, category, unit
- stock_qty(재고수량), reserved_qty(예약수량), safety_stock(안전재고)
- last_unit_price(최근단가)

## bom_headers (BOM 마스터)
- id, product_code, product_name, product_category, version
- certification_no, option_schema(JSON: 슈퍼BOM 옵션정의)

## bom_items (BOM 부품)
- id, bom_id → bom_headers, item_id → items
- item_name, item_spec, quantity(소요량), unit_price, unit
- option_filter(JSON: null=공통, {key:val}=옵션부품)

## stock_movements (재고변동)
- id, item_id → items, movement_type(IN|OUT|ADJUST)
- quantity, before_qty, after_qty, reference_type, reference_id, created_at

## purchase_orders (발주서)
- id, po_no, po_date, vendor_id, project_id, status, total_amount

## purchase_order_items (발주 품목)
- id, po_id, item_name, item_spec, quantity, unit_price, amount

## receivings (입고)
- id, rcv_no, rcv_date, vendor_id, po_id, status

## tax_invoices (세금계산서)
- id, approval_no, issue_date, buyer_name
- supply_amount, tax_amount, total_amount
- payment_status(미수금|부분입금|입금완료), match_status

## production_processes (생산 공정)
- id, project_id → projects, stage(FAB 등), status
- item_name, quantity, worker_name, start_date, end_date

## vendors (거래처)
- id, vendor_name, vendor_type, contact_name, contact_phone, contact_email

## g2b_procurements (G2B 조달내역)
- id, project_id, contract_date, total_amount, product_name
"""
    return [TextContent(type="text", text=schema)]
