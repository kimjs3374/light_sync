"""모든 tool/resource를 FastMCP 인스턴스에 등록"""
from mcp.server.fastmcp import FastMCP

from .tools import (
    inventory,
    bom,
    project,
    production,
    financial,
    procurement,
    quotation,
    delivery,
    warranty,
    sales,
    drawing,
    catalog,
    contract,
    daily_report,
    notification,
    overview,
    archive,
    g2b,
    certification,
    spec_doc,
    lighting_layout,
    illuminance,
    employee,
    processing_order,
    business_trip,
    document,
    tool_mgmt,
    mail,
    activity,
    material_order,
    vehicle_log,
    billing,
    dept_report,
    incoming_overview,
    approval,
    hr,
    write_ops,
)
from .resources import magnatech


def register_all(mcp: FastMCP):
    inventory.register(mcp)
    bom.register(mcp)
    project.register(mcp)
    production.register(mcp)
    financial.register(mcp)
    procurement.register(mcp)
    quotation.register(mcp)
    delivery.register(mcp)
    warranty.register(mcp)
    sales.register(mcp)
    drawing.register(mcp)
    catalog.register(mcp)
    contract.register(mcp)
    daily_report.register(mcp)
    notification.register(mcp)
    overview.register(mcp)
    archive.register(mcp)
    g2b.register(mcp)
    certification.register(mcp)
    spec_doc.register(mcp)
    lighting_layout.register(mcp)
    illuminance.register(mcp)
    employee.register(mcp)
    processing_order.register(mcp)
    business_trip.register(mcp)
    document.register(mcp)
    tool_mgmt.register(mcp)
    mail.register(mcp)
    activity.register(mcp)
    # ── 추가 조회 도구 (자재발주·운행일지·수금·부서주간보고·입고현황) ──
    material_order.register(mcp)
    vehicle_log.register(mcp)
    billing.register(mcp)
    dept_report.register(mcp)
    incoming_overview.register(mcp)
    # ── 전자결재 · 인사/연차 ──
    approval.register(mcp)
    hr.register(mcp)
    # ── 쓰기 작업 preview 도구 (확인 후 DB 반영) — READONLY 모드면 제외 ──
    import os as _os
    if _os.environ.get("LIGHT_SYNC_MCP_READONLY", "").strip() not in ("1", "true", "True"):
        write_ops.register(mcp)
    magnatech.register(mcp)
