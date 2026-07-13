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
    leave_write,
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
    # ── 쓰기 작업 도구 ──
    #   전체쓰기(비-READONLY): write_ops(11종) + leave_write(휴가 preview/confirm)
    #   READONLY + WRITE_ALLOW: 목록에 적힌 쓰기 도구만 허용(카카오워크 봇 전용)
    #   READONLY + LEAVE_ONLY: 위의 구버전 표기. 휴가 상신만 허용
    #   순수 READONLY: 쓰기 도구 없음
    import os as _os

    def _flag(name: str) -> bool:
        return _os.environ.get(name, "").strip() in ("1", "true", "True")

    _WRITE_PREFIXES = ("write_", "confirm_")
    _readonly = _flag("LIGHT_SYNC_MCP_READONLY")
    _allow_raw = _os.environ.get("LIGHT_SYNC_MCP_WRITE_ALLOW", "").strip()
    _allow = {t.strip() for t in _allow_raw.split(",") if t.strip()}
    if _flag("LIGHT_SYNC_MCP_WRITE_LEAVE_ONLY"):  # 하위호환
        _allow |= {"write_preview_leave_request", "confirm_leave_request"}

    if not _readonly:
        write_ops.register(mcp)
        leave_write.register(mcp)
    elif _allow:
        # 전부 등록한 뒤 허용목록 밖의 쓰기 도구를 제거한다.
        # (개별 등록 함수가 없어 등록 후 pruning 이 유일한 방법)
        write_ops.register(mcp)
        leave_write.register(mcp)
        for _name in [t for t in list(mcp._tool_manager._tools)
                      if t.startswith(_WRITE_PREFIXES) and t not in _allow]:
            mcp.remove_tool(_name)
    magnatech.register(mcp)
