"""Light-Sync ERP MCP 서버"""
from mcp.server.fastmcp import FastMCP
from .tools_registry import register_all

# host="0.0.0.0" → DNS rebinding 보호 비활성화 (외부 도메인 허용)
mcp = FastMCP(
    "light-sync-erp",
    host="0.0.0.0",
    instructions="Light-Sync ERP 데이터를 조회하는 MCP 서버. 재고, BOM, 현장, 생산, 재무, 조달 데이터에 접근합니다.",
)

register_all(mcp)
