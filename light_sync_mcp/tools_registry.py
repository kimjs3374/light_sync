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
    magnatech.register(mcp)
